"""One company-fit slot in the composed analysis worker; no standalone process.

The slot claims queued attempts of both lineages in ``created_at, id`` order
and branches on ``company_id``:

* ``company_id IS NULL`` -- the legacy single-company fit: automatic enqueue
  (``_enqueue_one`` creates NULL rows only), v1 input/validator, the
  synthetic "no confirmed facts" result and the automatic deep-review start.
* ``company_id IS NOT NULL`` -- DEMO-03 company fit: rows are created only by
  ``enqueue-company-fit``; the frozen CompanyAnalysisInput is re-checked for
  currentness, sent through the ``overview`` purpose client with the stored
  fit policy, and validated by the v2 validator.  No synthetic result, no
  automatic deep review.  While ``BIDOPS_DEMO_ENABLED`` is false, company rows
  are neither claimed nor changed.
* ``company_id IS NULL AND card_sha256 IS NOT NULL`` -- PS-01 business scope
  card: while the card mode is effective (C4) one notice per poll is enqueued
  (SW사업대상, automatic processing scope, verified overview; the C-1 grade is
  never read), claimed rows are re-checked (C9 + model binding), sent with the
  seven model-input keys and the v3.1 card policy, and validated by the v1
  validator.  Card rows never start a deep review.  While the card mode is
  effective the profile lineage is paused (no enqueue, no claim).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any, Callable
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.model_client import ModelClient, ModelInvocationError, strip_leading_thinking
from ...core.models import AuditEvent
from ...core.object_store import EncryptedModelResponseStore
from ...lifecycle import lock_notice
from ...lifecycle.models import Notice
from ..models import DeepReview, DocumentBundle, PreSpecCompanyFitAttempt
from .auto_preparation import _auto_start_scope, maybe_auto_start_deep_review
from .company_fit import (CONTRACT, JUDGED_BY_MODEL, card_current_flags, card_mode_with_card,
                          card_model_input, company_attempt_policy, company_audit_metadata,
                          company_current_flags, company_fit_contract, company_fit_enabled,
                          configured_binding, current_flags, digest, fit_policy, frozen_card_input,
                          frozen_input, overview_inputs, validate_company_fit_result, validate_result)
from .company_fit_card import BusinessScopeCard
from .company_fit_policy import COMPANY_FIT_STAGE
from .effective_grade import priority_notice_ids
from .input_versions import resolve_active_versions
from .model_response_storage import store_raw_model_response
from .model_retry import (
    VALIDATION_RETRY_INVOCATION_CODES,
    VALIDATION_RETRY_SEED,
    build_correction,
    validation_retry_metadata,
)
from .overview_runs import current_runs


def _now():
    return datetime.now(UTC)


def attempt_audit_metadata(row: PreSpecCompanyFitAttempt, retry: dict | None = None) -> dict:
    """Legacy metadata keys stay exactly as before; card and company rows add identities."""

    if row.company_id is not None:
        return company_audit_metadata(row, retry)
    metadata = {"notice_id": row.notice_id, "status": row.status, "reason_code": row.error_code,
                "input_sha256": row.input_sha256, "quality_status": row.quality_status,
                "validation_retry": dict(retry) if retry else None}
    if row.card_sha256 is not None:
        inputs = row.input_jsonb if isinstance(row.input_jsonb, dict) else {}
        metadata.update(lineage="card", card_version=row.card_version, card_sha256=row.card_sha256,
                        judged_by=inputs.get("judged_by"))
    return metadata


def _audit(session: Session, row: PreSpecCompanyFitAttempt, retry: dict | None = None):
    session.add(AuditEvent(actor_kind="system", claimed_name="company-fit", action="prespec_company_fit.attempt",
        aggregate_type="prespec_company_fit_attempt", aggregate_id=str(row.id),
        safe_metadata=attempt_audit_metadata(row, retry)))


def _metrics(response) -> dict:
    return {"prompt_tokens": response.prompt_tokens, "output_tokens": response.output_tokens,
            "latency_ms": response.latency_ms}


def _validated(response, inputs, validator: Callable[[Any, Any], Any] | None = None):
    """저장된 원본 bytes와 파싱 결과를 대조한 뒤 결정적 검증을 통과시킨다."""

    # 선행 `<think>` 블록은 파싱 입력에서만 걷어 낸다. 저장·hash 대상인 원본
    # bytes는 그대로다 — 걷어 내지 않으면 정상 응답이 불일치로 거부된다.
    parsed, _thinking = strip_leading_thinking(bytes(response.raw_response).decode("utf-8"))
    if json.loads(parsed) != response.structured_output:
        raise ValueError("raw_response_mismatch")
    return (validator or validate_result)(response.structured_output, inputs)


class PreSpecCompanyFitRunner:
    def __init__(self, *, settings=None, client=None, raw_response_store=None, clock=_now, company_client=None):
        self.settings = settings or get_settings()
        self.client = client
        #: Optional injected client for company rows (tests). Otherwise one
        #: ``overview`` purpose client is built per company attempt.
        self.company_client = company_client
        self.store = raw_response_store
        self.clock = clock

    def _enqueue_one(self, session: Session) -> None:
        # Resolve local approvals before queue construction or any model request.
        configured_binding(self.settings)
        profile, policy = resolve_active_versions(session, allow_unmeasured_reference=self.settings.reference_workflow_mode)
        ids = list(session.scalars(select(Notice.id).join(DocumentBundle, DocumentBundle.notice_id == Notice.id)
            .where(Notice.source_type == "pre_spec", DocumentBundle.status == "ready",
                   DocumentBundle.confirmed_by_name == "auto-preparation")
            .distinct().order_by(Notice.id)))
        priority = priority_notice_ids(session, ids)
        candidate_ids = [i for i in ids if i in priority]
        runs = current_runs(session, candidate_ids)
        sources = overview_inputs(session, candidate_ids, runs=runs)
        existing_inputs = set(
            session.scalars(
                select(PreSpecCompanyFitAttempt.input_sha256).where(
                    PreSpecCompanyFitAttempt.company_id.is_(None),
                    PreSpecCompanyFitAttempt.card_sha256.is_(None),
                )
            )
        )
        existing_deep = set(session.scalars(select(DeepReview.bundle_id).where(
            DeepReview.company_id.is_(None),
            DeepReview.profile_version_id == profile.id, DeepReview.policy_version_id == policy.id)))
        for notice_id in ids:
            source = sources.get(notice_id)
            if source is None:
                continue
            bundle_id, reason = _auto_start_scope(
                session, notice_id, require_company_fit=False, runs=runs
            )
            if reason is not None or bundle_id in existing_deep:
                continue
            try:
                inputs = frozen_input(session, notice_id, source, settings=self.settings)
            except (ValueError, TypeError):
                # A malformed/oversized candidate must not starve later notices.
                continue
            input_hash = digest(inputs)
            if input_hash in existing_inputs:
                continue
            lock_notice(session, notice_id)
            if session.scalar(
                select(PreSpecCompanyFitAttempt.id).where(
                    PreSpecCompanyFitAttempt.input_sha256 == input_hash,
                    PreSpecCompanyFitAttempt.company_id.is_(None),
                    PreSpecCompanyFitAttempt.card_sha256.is_(None),
                )
            ):
                continue
            row = PreSpecCompanyFitAttempt(id=uuid4(), company_id=None, notice_id=notice_id, document_version_id=source.document_id,
                overview_run_id=source.id,
                profile_version_id=profile.id, deep_policy_version_id=policy.id,
                input_jsonb=inputs, input_sha256=input_hash, policy_digest=inputs["policy_digest"],
                model_name=inputs["model_name"], model_revision=inputs["model_revision"],
                quality_status=source.quality_status, status="queued", created_at=self.clock())
            session.add(row)
            _audit(session, row)
            session.commit()
            return
        session.commit()

    def _enqueue_card(self, session: Session, card: BusinessScopeCard, now) -> None:
        """Freeze at most one card lineage attempt (spec "상태 값과 실패 처리").

        Targets: pre-spec notices that are SW사업대상, inside the automatic
        processing scope at ``now`` and have a verified current overview.  The
        C-1 grade is never read.  Order: the pre-spec list deadline order, then
        notice id.  A notice whose card input already exists (any status, so a
        failed or expired input is never retried) or whose input is too large is
        skipped without blocking later notices.
        """

        from ...lifecycle import pre_spec_deadline_sort_expression
        from .effective_grade import auto_processing_notice_ids, sw_business_notice_ids

        model, revision, _legacy_policy = configured_binding(self.settings)
        bucket, future_deadline, past_deadline = pre_spec_deadline_sort_expression(now)
        ids = list(session.scalars(
            select(Notice.id).where(Notice.source_type == "pre_spec")
            .order_by(bucket.asc(), future_deadline.asc().nulls_last(), past_deadline.desc().nulls_last(),
                      Notice.id.asc())
        ))
        sw = sw_business_notice_ids(session, ids)
        in_scope = auto_processing_notice_ids(session, ids, now=now)
        candidates = [notice_id for notice_id in ids if notice_id in sw and notice_id in in_scope]
        sources = overview_inputs(session, candidates)
        existing = set(session.scalars(select(PreSpecCompanyFitAttempt.input_sha256).where(
            PreSpecCompanyFitAttempt.company_id.is_(None), PreSpecCompanyFitAttempt.card_sha256.is_not(None))))
        for notice_id in candidates:
            source = sources.get(notice_id)
            if source is None:
                continue
            try:
                inputs = frozen_card_input(session, notice_id, source, card, model_name=model,
                                           model_revision=revision, judged_by=JUDGED_BY_MODEL)
            except (ValueError, TypeError):
                # company_fit_input_too_large: skip, never block the next notice.
                continue
            input_hash = digest(inputs)
            if input_hash in existing:
                continue
            lock_notice(session, notice_id)
            if session.scalar(select(PreSpecCompanyFitAttempt.id).where(
                    PreSpecCompanyFitAttempt.input_sha256 == input_hash)):
                continue
            row = PreSpecCompanyFitAttempt(
                id=uuid4(), company_id=None, notice_id=notice_id, document_version_id=source.document_id,
                overview_run_id=source.id, profile_version_id=None, deep_policy_version_id=None,
                card_version=card.card_version, card_sha256=card.card_sha256,
                input_jsonb=inputs, input_sha256=input_hash, policy_digest=inputs["policy_digest"],
                model_name=inputs["model_name"], model_revision=inputs["model_revision"],
                quality_status=source.quality_status, status="queued", created_at=self.clock())
            session.add(row)
            _audit(session, row)
            session.commit()
            return
        session.commit()

    def run_once(self, session: Session, worker_id: str) -> bool:
        if not self.settings.prespec_company_fit_enabled:
            return False
        # No measured company-fit policy exists yet. Reference workflow is an explicit opt-in.
        if not self.settings.reference_workflow_mode:
            return False
        company_enabled = company_fit_enabled(self.settings)
        now = self.clock()
        expired = select(PreSpecCompanyFitAttempt).where(
            PreSpecCompanyFitAttempt.status == "running", PreSpecCompanyFitAttempt.lease_expires_at <= now
        )
        if not company_enabled:
            expired = expired.where(PreSpecCompanyFitAttempt.company_id.is_(None))
        for row in session.scalars(expired.with_for_update(skip_locked=True)):
            self._finish(session, row, "failed", "lease_expired")
        session.commit()
        card_state, card = card_mode_with_card(self.settings, session)
        card_effective = bool(card_state["effective"] and card is not None)
        legacy_enabled = True
        if card_effective:
            # PS-01 coexistence: the profile lineage is paused while the card mode
            # is effective (no `_enqueue_one`, its queued rows are not claimed).
            legacy_enabled = False
            try:
                self._enqueue_card(session, card, now)
            except Exception:
                # The card queue has its own failure boundary; queued rows still run.
                session.rollback()
        else:
            try:
                self._enqueue_one(session)
            except Exception:
                session.rollback()
                # The legacy queue is unavailable (as before, its rows wait), but an
                # explicitly enqueued company row still has its own frozen binding.
                legacy_enabled = False
        lineages = []
        if legacy_enabled:
            lineages.append(and_(PreSpecCompanyFitAttempt.company_id.is_(None),
                                 PreSpecCompanyFitAttempt.card_sha256.is_(None)))
        if card_effective:
            lineages.append(and_(PreSpecCompanyFitAttempt.company_id.is_(None),
                                 PreSpecCompanyFitAttempt.card_sha256.is_not(None)))
        if company_enabled:
            lineages.append(PreSpecCompanyFitAttempt.company_id.is_not(None))
        if not lineages:
            session.rollback()
            return False
        claim = select(PreSpecCompanyFitAttempt).where(PreSpecCompanyFitAttempt.status == "queued", or_(*lineages))
        row = session.scalar(claim.order_by(PreSpecCompanyFitAttempt.created_at, PreSpecCompanyFitAttempt.id)
                             .with_for_update(skip_locked=True).limit(1))
        if row is None:
            session.rollback()
            return False
        if row.company_id is not None:
            return self._run_company(session, row, worker_id, now)
        if row.card_sha256 is not None:
            return self._run_card(session, row, worker_id, now)
        attempt_id, notice_id = row.id, row.notice_id
        if not self._eligible(session, row):
            self._finish(session, row, "failed", "inputs_changed")
            session.commit()
            return True
        row.status = "running"
        row.lease_owner = worker_id
        row.lease_expires_at = now + timedelta(seconds=600)
        inputs = row.input_jsonb
        _audit(session, row)
        session.commit()
        result, raw, metrics = None, None, {}
        first_raw, retry = None, None
        status, error = "completed", None
        try:
            if not any(f["status"] == "confirmed" and f["value"] is not None for f in inputs["company_facts"]):
                result = validate_result({"schema_version": "bidops.prespec-company-fit-result.v1", "decision": "unknown",
                    "summary": "업무 범위를 확인할 승인된 회사 정보가 부족합니다.",
                    "reasons": [{"kind": "information_gap", "explanation": "확인된 회사 정보가 없어 과업과의 부합 여부를 판단할 수 없습니다.",
                                 "notice_refs": [inputs["notice_facts"][0]["ref"]], "company_refs": []}],
                    "verification_items": ["승인된 회사 업무 범위와 수행 역량을 확인해 주세요."]}, inputs)
            else:
                if self.client is None:
                    self.client = ModelClient.for_purpose("overview", model=inputs["model_name"],
                                                         settings=self.settings, output_contract=CONTRACT)
                identity = self.client.verify_identity()
                if identity.model != inputs["model_name"] or identity.revision != inputs["model_revision"]:
                    raise ValueError("model_binding_changed")
                model_inputs = {key: value for key, value in inputs.items() if key != "fit_policy"}
                status, error, result, raw, first_raw, retry, metrics = self._invoke_validated(
                    self.client, model_inputs, inputs["fit_policy"], inputs, validate_result, {}
                )
        except Exception:
            status, error = "failed", "company_fit_execution_failed"
        if not self._store(session, attempt_id, worker_id, status, error, result, raw, first_raw, retry, metrics):
            return True
        # The shared creation service rechecks current input, policy and bundle.
        maybe_auto_start_deep_review(session, notice_id)
        return True

    def _invoke_validated(self, client, model_inputs, policy, inputs, validator, invoke_kwargs):
        """One call plus at most one deterministic-validation retry (same input)."""

        result, raw, metrics = None, None, {}
        first_raw, retry = None, None
        status, error = "completed", None
        codes: list[str] = []
        try:
            response = client.invoke(COMPANY_FIT_STAGE, model_inputs, policy, **invoke_kwargs)
            raw = bytes(response.raw_response)
            metrics = _metrics(response)
            try:
                result = _validated(response, inputs, validator)
            except (ValueError, TypeError) as invalid:
                codes = [str(getattr(invalid, "code", None) or "company_fit_validation_failed")]
        except ModelInvocationError as failure:
            code = str(getattr(failure, "code", "") or "")
            if code not in VALIDATION_RETRY_INVOCATION_CODES:
                raise
            error_raw = getattr(failure, "raw_response", None)
            raw = bytes(error_raw) if isinstance(error_raw, (bytes, bytearray)) else None
            codes = [code]
        if codes:
            # 결정적 검증 실패에 한해 같은 입력으로 한 번만 더 부른다.
            first_raw, correction = raw, build_correction(codes)
            retry = validation_retry_metadata(codes, correction, None)
            response = client.invoke(COMPANY_FIT_STAGE, model_inputs, policy,
                                     seed=VALIDATION_RETRY_SEED, correction=correction, **invoke_kwargs)
            raw = bytes(response.raw_response)
            metrics = _metrics(response)
            try:
                result = _validated(response, inputs, validator)
            except (ValueError, TypeError):
                result = None
                status, error = "needs_human_review", "company_fit_validation_failed"
        return status, error, result, raw, first_raw, retry, metrics

    def _store(self, session, attempt_id, worker_id, status, error, result, raw, first_raw, retry, metrics) -> bool:
        """Persist the terminal state under the lease fence. False if fenced out."""

        session.expire_all()
        row = session.scalar(select(PreSpecCompanyFitAttempt).where(PreSpecCompanyFitAttempt.id == attempt_id).with_for_update())
        if row.status != "running" or row.lease_owner != worker_id or row.lease_expires_at <= self.clock():
            session.rollback()
            return False
        try:
            if raw is not None or first_raw is not None:
                if self.store is None:
                    self.store = EncryptedModelResponseStore(self.settings)
            if first_raw is not None:
                # 재시도 전 응답도 그대로 암호화 보존한다. 행이 가리키는 것은
                # 마지막 응답이므로 첫 응답 hash는 감사에만 남는다.
                retry["first_raw_response_sha256"] = store_raw_model_response(
                    session, first_raw, store=self.store, clock=self.clock)
            if raw is not None:
                row.raw_response_sha256 = (
                    retry["first_raw_response_sha256"] if raw is first_raw
                    else store_raw_model_response(session, raw, store=self.store, clock=self.clock))
            for key, value in metrics.items():
                setattr(row, key, value)
            if status == "completed" and result is not None:
                row.result_jsonb = result.model_dump(mode="json")
                row.result_sha256 = digest(row.result_jsonb)
            self._finish(session, row, status, error, retry)
            session.commit()
        except Exception:
            session.rollback()
            row = session.scalar(select(PreSpecCompanyFitAttempt).where(PreSpecCompanyFitAttempt.id == attempt_id).with_for_update())
            if row.status == "running" and row.lease_owner == worker_id:
                row.result_jsonb = None
                row.result_sha256 = None
                self._finish(session, row, "failed", "company_fit_storage_failed", retry)
                session.commit()
            return False
        return True

    def _run_company(self, session: Session, row: PreSpecCompanyFitAttempt, worker_id: str, now) -> bool:
        """Execute one claimed company attempt from its frozen input only."""

        attempt_id = row.id
        policy = company_attempt_policy(session, row)
        if policy is None or not self._company_eligible(session, row):
            self._finish(session, row, "failed", "inputs_changed")
            session.commit()
            return True
        row.status = "running"
        row.lease_owner = worker_id
        row.lease_expires_at = now + timedelta(seconds=600)
        inputs = row.input_jsonb
        _audit(session, row)
        session.commit()
        result, raw, first_raw, retry, metrics = None, None, None, None, {}
        status, error = "completed", None
        owned_client = None
        try:
            client = self.company_client
            if client is None:
                client = owned_client = ModelClient.for_purpose(
                    "overview", model=inputs["model_name"], settings=self.settings,
                    output_contract=company_fit_contract(policy),
                )
            identity = client.verify_identity()
            # A declared policy revision must match; null means "not declared"
            # and is never replaced by a guessed or server-reported value.
            if identity.model != inputs["model_name"] or (
                inputs["model_revision"] is not None and identity.revision != inputs["model_revision"]
            ):
                raise ValueError("model_binding_changed")
            status, error, result, raw, first_raw, retry, metrics = self._invoke_validated(
                client, inputs, policy, inputs, validate_company_fit_result,
                {"prompt_max_chars": policy["chunking"]["max_characters"]},
            )
        except Exception:
            status, error = "failed", "company_fit_execution_failed"
        finally:
            if owned_client is not None:
                owned_client.close()
        self._store(session, attempt_id, worker_id, status, error, result, raw, first_raw, retry, metrics)
        # Company fits never start a deep review; Luna analysis is a separate request.
        return True

    def _card_eligible(self, session: Session, row: PreSpecCompanyFitAttempt) -> bool:
        """C9 currentness plus the model binding the runner will call (MVP 3)."""

        inputs = row.input_jsonb if isinstance(row.input_jsonb, dict) else {}
        if inputs.get("judged_by") != JUDGED_BY_MODEL:
            return False
        try:
            model, revision, _legacy_policy = configured_binding(self.settings)
        except (ValueError, OSError):
            return False
        if row.model_name != model or row.model_revision != revision:
            return False
        return bool(card_current_flags(session, [row], settings=self.settings).get(row.id))

    def _run_card(self, session: Session, row: PreSpecCompanyFitAttempt, worker_id: str, now) -> bool:
        """Execute one claimed card attempt from its frozen input only."""

        attempt_id = row.id
        if not self._card_eligible(session, row):
            self._finish(session, row, "failed", "inputs_changed")
            session.commit()
            return True
        row.status = "running"
        row.lease_owner = worker_id
        row.lease_expires_at = now + timedelta(seconds=600)
        inputs = row.input_jsonb
        _audit(session, row)
        session.commit()
        result, raw, first_raw, retry, metrics = None, None, None, None, {}
        status, error = "completed", None
        try:
            if self.client is None:
                self.client = ModelClient.for_purpose("overview", model=inputs["model_name"],
                                                     settings=self.settings, output_contract=CONTRACT)
            identity = self.client.verify_identity()
            if identity.model != inputs["model_name"] or identity.revision != inputs["model_revision"]:
                raise ValueError("model_binding_changed")
            status, error, result, raw, first_raw, retry, metrics = self._invoke_validated(
                self.client, card_model_input(inputs), inputs["fit_policy"], inputs, validate_result, {}
            )
        except Exception:
            status, error = "failed", "company_fit_execution_failed"
        self._store(session, attempt_id, worker_id, status, error, result, raw, first_raw, retry, metrics)
        # Card fits only suggest; they never start a deep review (ADR-0078 결정 1).
        return True

    def _company_eligible(self, session: Session, row: PreSpecCompanyFitAttempt) -> bool:
        return bool(company_current_flags(session, [row], settings=self.settings).get(row.id))

    def _eligible(self, session: Session, row: PreSpecCompanyFitAttempt) -> bool:
        if not current_flags(session, [row], settings=self.settings).get(row.id):
            return False
        if row.notice_id not in priority_notice_ids(session, [row.notice_id]):
            return False
        _, reason = _auto_start_scope(session, row.notice_id, require_company_fit=False)
        return reason is None

    def _finish(self, session: Session, row: PreSpecCompanyFitAttempt, status: str, error: str | None, retry: dict | None = None):
        row.status, row.error_code = status, error
        row.completed_at = self.clock()
        row.lease_owner, row.lease_expires_at = None, None
        _audit(session, row, retry)
