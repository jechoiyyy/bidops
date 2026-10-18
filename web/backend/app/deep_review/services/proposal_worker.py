"""RL-04 proposal section worker: one ``proposal_section`` WorkJob per claim (spec "생성 입력·정책·호출").

It runs inside the shared analysis worker process (one slot, concurrency 1,
like ``assumption_analysis``) and reuses ``DeepReviewService``'s lease, fence
and encrypted raw-response helpers without touching the deep-review queue.

Order of one claimed section (nothing is sent before every check passed):

1. claim: job ``running`` (lease, fence), section ``queued -> running``, draft
   ``queued -> running`` with ``started_at`` on the first claim;
2. pinned proposal policy row, Luna/reference flags, provider lineage of the
   draft (creation audit) equal to the configured provider;
3. draft deadline: revision 1 sections share ``review_timeout_seconds`` (5400)
   counted from the draft's first claim (``started_at``, carried into this
   process as a monotonic deadline); a regeneration counts from its own claim.
   Expired → ``proposal_review_timeout`` for this section and every still
   queued revision-1 section of the draft (no call);
4. frozen input (``proposal_input``; ``input_sha256``), checked 8-key payload,
   prompt and ``input_budget_exceeded`` before any call;
5. transfer approval re-check with this section excluded (cap 1 unit; never for
   the mock provider), then the fixed runner endpoint check (결정 B25) -- both
   before the transfer audit;
6. under the fence: ``input_sha256`` and the one ``analysis.transfer.sent``
   (purpose ``proposal``; none for the mock provider), then the calls;
7. ``proposal-section-v1`` call (per-section ``timeout_seconds`` 900, capped by
   the draft deadline), at most ``validation_repair_attempts`` (1) repair and
   only for a schema-class failure (client ``schema_invalid`` or a validator
   result that is ``repairable``); the repair envelope carries rule codes and
   integer indexes only (결정 B33 mirror).  No other retry;
8. store the validated Section (``payload``, ``result_sha256``, tokens,
   latency) or fail the section with one code; settle the draft.

Section error codes: validator ``proposal_forbidden_content`` /
``proposal_section_invalid`` / ``proposal_coverage_incomplete``;
``input_budget_exceeded``; ``proposal_review_timeout``; LunaClient codes as
RL-03 passes them (``runner_unavailable``, ``runner_failed``,
``output_truncated``, ``model_timeout``, ``authentication_failed``,
``model_access_denied``, ``runner_identity_mismatch``, ``prompt_rejected``,
``lease_lost``); a malformed frozen input or payload-guard failure
(``ProposalSectionInputError``/``ProposalInputError``) is
``company_input_invalid`` (결정 B44 code); ``verdict_required``;
``policy_not_approved``/``daily_cap_reached``; ``analysis_policy_unavailable``;
``service_unavailable``; ``model_binding_invalid`` (lineage); an expired lease
of a claimed section is ``lease_expired`` (the call is never re-run);
anything else ``processing_failed``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
import hashlib
import re
import time
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ...core.model_binding import canonical_json_bytes
from ...core.model_client import ModelInvocationError
from ...core.models import AuditEvent
from ...lifecycle.models import Notice
from ..models import AnalysisPolicyVersion, ProposalDraft, ProposalSection, WorkJob
from . import transfer_policy
from .deep_reviews import DeepReviewService, DeepReviewServiceError, JobClaim, StaleFenceError, _policy_payload
from .input_versions import canonical_json_hash
from .proposal_draft import (
    JOB_TYPE,
    ProposalServiceError,
    draft_lineage,
    provider_lineage,
    require_execution_flags,
    settle_draft,
    validate_proposal_policy_row,
)
from .proposal_input import (
    ProposalInputError,
    build_proposal_input,
    notice_meta,
    proposal_input_sha256,
    proposal_transfer_payload,
    require_input_budget,
    load_verdict_sources,
)
from .proposal_validation import ProposalSectionInputError, validate_proposal_section


CONTRACT = "proposal-section-v1"
REVIEW_TIMEOUT = "proposal_review_timeout"
SECTION_INVALID = "proposal_section_invalid"
_RULE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_INDEX_KEYS = ("paragraph_index", "sentence_index", "source_index", "link_index", "unit_index")


class SectionFailure(Exception):
    """One section failure code (and whether the draft deadline expired)."""

    def __init__(self, code: str, *, expire: bool = False, detail: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.expire = expire
        self.detail = dict(detail or {})
        super().__init__(code)


def proposal_prompt(
    policy: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    repair_detail: Mapping[str, Any] | None = None,
) -> str:
    """Canonical prompt envelope (``input`` = the checked 8-key payload).

    A repair adds ``validation_repair`` with ``scope``, ``rule_codes`` and
    ``violations`` (rule code + integer indexes) -- never model or source text.
    """

    instructions = {row["stage"]: row["instruction"] for row in policy["stages"]}
    envelope: dict[str, Any] = {
        "stage": payload["section_key"],
        "instruction": instructions[payload["section_key"]],
        "output_contract": dict(policy["prompt_output_contract"]),
        "input": dict(payload),
    }
    if repair_detail is not None:
        rule_codes = repair_detail.get("rule_codes")
        violations = repair_detail.get("violations")
        if (
            set(repair_detail) != {"rule_codes", "violations"}
            or not isinstance(rule_codes, list) or not rule_codes
            or any(not isinstance(code, str) or _RULE_CODE.fullmatch(code) is None for code in rule_codes)
            or not isinstance(violations, list)
            or any(
                not isinstance(row, Mapping) or set(row) != {"rule_code", *_INDEX_KEYS}
                or not isinstance(row["rule_code"], str) or _RULE_CODE.fullmatch(row["rule_code"]) is None
                or any(row[key] is not None and (type(row[key]) is not int or row[key] < 0) for key in _INDEX_KEYS)
                for row in violations
            )
        ):
            raise SectionFailure("processing_failed")
        envelope["validation_repair"] = {
            "scope": "syntax_or_schema_only", "rule_codes": list(rule_codes),
            "violations": [dict(row) for row in violations],
        }
    return canonical_json_bytes(envelope).decode("utf-8")


class ProposalWorker:
    """Claims and runs one ``proposal_section`` job per ``run_once``."""

    def __init__(
        self,
        *,
        base: DeepReviewService | None = None,
        client: Any | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base = base or DeepReviewService()
        #: An injected client (tests) replaces the runner client; the mock provider uses its own.
        self.client = client
        self.monotonic = monotonic

    # --- claim ------------------------------------------------------------------------------

    def run_once(self, session: Session, worker_id: str) -> bool:
        now = self.base.clock()
        if session.in_transaction():
            session.commit()
        job = session.scalar(
            select(WorkJob)
            .where(
                WorkJob.job_type == JOB_TYPE,
                or_(WorkJob.status == "queued", and_(WorkJob.status == "running", WorkJob.lease_expires_at < now)),
            )
            .order_by(WorkJob.priority.desc(), WorkJob.scheduled_at.asc(), WorkJob.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            session.commit()
            return False
        section = session.get(ProposalSection, job.aggregate_id)
        draft = session.get(ProposalDraft, section.draft_id) if section is not None else None
        if section is None or draft is None:
            self._close_job(job, "proposal_scope_missing", now)
            session.commit()
            return True
        if job.status == "running":
            # An expired lease is never re-run (one approved transfer per section).
            job.lease_fence = int(job.lease_fence) + 1
            self._close_job(job, "lease_expired", now)
            if section.status in {"queued", "running"}:
                self._fail_section(section, "lease_expired", now)
            settle_draft(session, draft, now=now)
            self._audit(session, "proposal.section.failed", section, draft, {"error_code": "lease_expired"})
            session.commit()
            return True
        if section.status != "queued":
            self._close_job(job, "section_not_queued", now)
            session.commit()
            return True
        fence = int(job.lease_fence) + 1
        job.status = "running"
        job.lease_owner = worker_id
        job.lease_fence = fence
        job.lease_expires_at = now + timedelta(seconds=self.base.lease_seconds)
        job.attempt_count = int(job.attempt_count) + 1
        section.status = "running"
        if draft.status == "queued":
            draft.status = "running"
            draft.started_at = draft.started_at or now
        self._audit(session, "proposal.section.claimed", section, draft, {"fence": fence})
        session.commit()
        self._execute(session, JobClaim(job.id, section.id, section.id, worker_id, fence))
        return True

    @staticmethod
    def _close_job(job: WorkJob, code: str, now: Any) -> None:
        job.status = "failed"
        job.last_error_code = code
        job.completed_at = now
        job.lease_expires_at = None

    @staticmethod
    def _fail_section(section: ProposalSection, code: str, now: Any) -> None:
        section.status = "failed"
        if section.error_code is None:
            section.error_code = code
        if section.completed_at is None:
            section.completed_at = now

    @staticmethod
    def _audit(session: Session, action: str, section: ProposalSection, draft: ProposalDraft,
               extra: Mapping[str, Any]) -> None:
        session.add(AuditEvent(
            actor_kind="system", claimed_name="system:proposal-worker", action=action,
            aggregate_type="proposal_section", aggregate_id=str(section.id), request_id=None,
            safe_metadata={"draft_id": str(draft.id), "section_id": str(section.id),
                           "section_key": section.section_key, "revision": int(section.revision), **dict(extra)},
        ))

    # --- execute ----------------------------------------------------------------------------

    def _execute(self, session: Session, claim: JobClaim) -> None:
        state: dict[str, Any] = {"input_sha256": None, "calls": 0, "repairs": 0}
        client = None
        owned = False
        try:
            section = session.get(ProposalSection, claim.attempt_id)
            draft = session.get(ProposalDraft, section.draft_id)
            settings = self.base.settings
            mock = settings.analysis_provider == "mock"
            try:
                policy = validate_proposal_policy_row(session.get(AnalysisPolicyVersion, draft.policy_version_id))
                if policy.policy_sha256 != draft.policy_sha256:
                    raise ProposalServiceError("analysis_policy_unavailable")
                require_execution_flags(settings)
            except ProposalServiceError as error:
                raise SectionFailure(error.code) from None
            provider, quality_status = provider_lineage(settings)
            lineage = draft_lineage(session, draft.id)
            if lineage is None or lineage.get("provider") != provider:
                raise SectionFailure("model_binding_invalid")
            state["quality_status"] = quality_status
            policy_payload = _policy_payload(policy)
            execution = policy_payload["execution"]
            review_timeout = int(execution["review_timeout_seconds"])
            call_timeout = int(execution["timeout_seconds"])
            repairs = int(execution["validation_repair_attempts"])
            started = self.monotonic()
            if section.revision == 1 and draft.started_at is not None:
                elapsed = max((self.base.clock() - draft.started_at).total_seconds(), 0.0)
                draft_deadline = started + review_timeout - elapsed
            else:
                draft_deadline = started + review_timeout
            state["deadline"] = draft_deadline
            if self.monotonic() >= draft_deadline:
                raise SectionFailure(REVIEW_TIMEOUT, expire=section.revision == 1)
            call_deadline = min(draft_deadline, started + call_timeout)

            # frozen input, checked payload, prompt budget (no call yet)
            try:
                sources = load_verdict_sources(session, draft.verdict_attempt_id)
                notice = session.get(Notice, draft.notice_id)
                frozen = build_proposal_input(
                    sources, section_key=section.section_key, execution_nonce=section.id, draft_id=draft.id,
                    opportunity_id=draft.opportunity_id, notice_id=draft.notice_id,
                    policy_sha256=draft.policy_sha256, notice_meta=notice_meta(notice),
                )
                state["input_sha256"] = proposal_input_sha256(frozen)
                payload = proposal_transfer_payload(
                    frozen, sources, operational_values=(draft.approval_id, section.id, draft.id, claim.job_id),
                )
                require_input_budget(proposal_prompt(policy_payload, payload))
            except ProposalInputError as error:
                raise SectionFailure(error.code) from None
            session.rollback()

            # approval re-check (own section excluded), then the endpoint -- both before the audit
            try:
                approval = transfer_policy.require_proposal_transfer_approval(
                    session, policy, requested_sections=1, check_cap=not mock, reserve_in_flight=False,
                    exclude_section_id=section.id,
                )
            except transfer_policy.TransferPolicyError as error:
                raise SectionFailure(error.code) from None
            if not mock and self.client is None:
                from .luna_client import valid_runner_endpoint

                if not valid_runner_endpoint(settings.luna_runner_url):
                    raise SectionFailure("runner_unavailable")
            if not self.base._lock_claim(session, claim):
                session.rollback()
                raise StaleFenceError()
            section = session.get(ProposalSection, claim.attempt_id)
            if section.input_sha256 is None:
                section.input_sha256 = state["input_sha256"]
            if not mock:
                transfer_policy.record_proposal_transfer_sent(
                    session, approval=approval, draft_id=draft.id, section_id=section.id,
                    section_key=section.section_key, notice_id=int(draft.notice_id),
                    input_sha256=state["input_sha256"],
                )
            session.commit()

            if mock:
                from .mock_proposal_client import MockProposalClient

                client = MockProposalClient()
            elif self.client is not None:
                client = self.client
            else:
                from .luna_client import LunaClient

                client = LunaClient(settings.luna_runner_url,
                                    lambda: self.base._renew_lease(session, claim, require_live=True), call_deadline)
                owned = True

            repair_detail: dict[str, Any] | None = None
            for attempt in range(repairs + 1):
                if self.monotonic() >= draft_deadline:
                    raise SectionFailure(REVIEW_TIMEOUT, expire=section.revision == 1)
                self.base._renew_lease(session, claim, require_live=True)
                prompt = proposal_prompt(policy_payload, payload, repair_detail=repair_detail if attempt else None)
                try:
                    require_input_budget(prompt)
                except ProposalInputError as error:
                    raise SectionFailure(error.code) from None
                state["calls"] += 1
                state["repairs"] = attempt
                try:
                    result = client.invoke_prompt(prompt, contract=CONTRACT)
                except ModelInvocationError as error:
                    if error.code in {"review_timeout", "model_timeout"}:
                        if self.monotonic() >= draft_deadline:
                            raise SectionFailure(REVIEW_TIMEOUT, expire=section.revision == 1) from None
                        raise SectionFailure("model_timeout") from None
                    if error.raw_response:
                        self._persist_raw(session, claim, error, call_index=state["calls"], repair_attempt=attempt)
                    if error.code != "schema_invalid":
                        raise SectionFailure(error.code) from None
                    if attempt >= repairs:
                        raise SectionFailure(SECTION_INVALID, detail={"rule_codes": ["output_schema"]}) from None
                    repair_detail = {"rule_codes": ["output_schema"], "violations": []}
                    continue
                if isinstance(getattr(result, "raw_response", None), bytes) and result.raw_response:
                    self._persist_raw(session, claim, result, call_index=state["calls"], repair_attempt=attempt)
                output = getattr(result, "structured_output", None)
                try:
                    verdict = validate_proposal_section(output, section_input=frozen)
                except ProposalSectionInputError:
                    raise SectionFailure("company_input_invalid") from None
                if verdict.ok:
                    self._complete(session, claim, output, result, state)
                    return
                detail = verdict.safe_detail()
                if verdict.repairable and attempt < repairs:
                    repair_detail = {"rule_codes": list(detail["rule_codes"]), "violations": list(detail["violations"])}
                    continue
                raise SectionFailure(verdict.error_code or SECTION_INVALID,
                                     detail={"rule_codes": detail["rule_codes"], "violations": detail["violations"]})
            raise SectionFailure(SECTION_INVALID)
        except StaleFenceError:
            session.rollback()
        except SectionFailure as failure:
            session.rollback()
            self._fail(session, claim, failure, state)
        except DeepReviewServiceError as error:
            session.rollback()
            self._fail(session, claim, SectionFailure(error.code), state)
        except Exception:
            session.rollback()
            self._fail(session, claim, SectionFailure("processing_failed"), state)
        finally:
            if owned and client is not None:
                client.close()

    def _persist_raw(self, session: Session, claim: JobClaim, result: Any, *, call_index: int,
                     repair_attempt: int) -> None:
        raw = result.raw_response
        aggregate, metadata = self.base._store_raw_aggregate([(
            result, {"slice_index": call_index, "validation_repair_attempt": repair_attempt},
        )])
        if not self.base._lock_claim(session, claim):
            session.rollback()
            raise StaleFenceError()
        content = self.base._raw_content_row(session, aggregate, metadata)
        section = session.get(ProposalSection, claim.attempt_id)
        draft = session.get(ProposalDraft, section.draft_id)
        self._audit(session, "proposal.section.raw_response.stored", section, draft, {
            "call_index": int(call_index), "repair_attempt": int(repair_attempt),
            "content_object_id": str(content.id), "response_sha256": hashlib.sha256(raw).hexdigest(),
        })
        session.commit()

    def _complete(self, session: Session, claim: JobClaim, output: Mapping[str, Any], result: Any,
                  state: Mapping[str, Any]) -> None:
        now = self.base.clock()
        if not self.base._lock_claim(session, claim):
            session.rollback()
            raise StaleFenceError()
        section = session.get(ProposalSection, claim.attempt_id)
        draft = session.get(ProposalDraft, section.draft_id)
        job = session.get(WorkJob, claim.job_id)
        result_sha256 = canonical_json_hash(output)
        section.status = "completed"
        if section.input_sha256 is None:
            section.input_sha256 = state["input_sha256"]
        section.payload = dict(output)
        section.result_sha256 = result_sha256
        section.prompt_tokens = getattr(result, "prompt_tokens", None)
        section.output_tokens = getattr(result, "output_tokens", None)
        latency = getattr(result, "latency_ms", None)
        section.latency_ms = int(latency) if isinstance(latency, int) and not isinstance(latency, bool) else None
        section.completed_at = now
        job.status = "completed"
        job.completed_at = now
        job.lease_expires_at = None
        session.flush()
        settle_draft(session, draft, now=now)
        self._audit(session, "proposal.section.completed", section, draft, {
            "input_sha256": state["input_sha256"], "result_sha256": result_sha256,
            "call_count": int(state["calls"]), "repair_count": int(state["repairs"]),
            "quality_status": state.get("quality_status"),
        })
        session.commit()

    def _fail(self, session: Session, claim: JobClaim, failure: SectionFailure, state: Mapping[str, Any]) -> None:
        now = self.base.clock()
        if not self.base._lock_claim(session, claim):
            session.rollback()
            return
        section = session.get(ProposalSection, claim.attempt_id)
        draft = session.get(ProposalDraft, section.draft_id)
        job = session.get(WorkJob, claim.job_id)
        if job.lease_expires_at is not None and job.lease_expires_at <= now:
            failure = SectionFailure("lease_expired")
        if section.input_sha256 is None and state.get("input_sha256") is not None:
            section.input_sha256 = state["input_sha256"]
        self._fail_section(section, failure.code, now)
        self._close_job(job, failure.code, now)
        expired: list[str] = []
        if failure.expire:
            for other in session.scalars(select(ProposalSection).where(
                ProposalSection.draft_id == draft.id, ProposalSection.revision == 1,
                ProposalSection.status == "queued",
            )).all():
                self._fail_section(other, REVIEW_TIMEOUT, now)
                expired.append(str(other.id))
                for other_job in session.scalars(select(WorkJob).where(
                    WorkJob.job_type == JOB_TYPE, WorkJob.aggregate_id == other.id, WorkJob.status == "queued",
                )).all():
                    self._close_job(other_job, REVIEW_TIMEOUT, now)
        session.flush()
        settle_draft(session, draft, now=now)
        extra: dict[str, Any] = {"error_code": failure.code, "call_count": int(state.get("calls", 0))}
        if failure.detail:
            extra["rule_codes"] = list(failure.detail.get("rule_codes") or [])
            if "violations" in failure.detail:
                extra["violations"] = list(failure.detail["violations"])
        if expired:
            extra["expired_section_ids"] = expired
        self._audit(session, "proposal.section.failed", section, draft, extra)
        session.commit()


def run_once(session: Session, worker_id: str, *, worker: ProposalWorker | None = None) -> bool:
    """Claim and run at most one proposal section job (shared analysis slot)."""

    return (worker or ProposalWorker()).run_once(session, worker_id)


__all__ = ["CONTRACT", "ProposalWorker", "SectionFailure", "proposal_prompt", "run_once"]
