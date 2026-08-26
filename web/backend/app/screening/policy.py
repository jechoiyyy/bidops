"""Repository and deterministic canonicalization for screening policies."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Final
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..models import (
    AuditEvent,
    QualityGate,
    QualityGateEvaluation,
    ScreeningExecution,
    ScreeningPolicy,
    utc_now,
)


POLICY_SCHEMA_VERSION: Final[str] = "bidops.screening-policy.v1"
SEED_POLICY_VERSION: Final[str] = "screening-policy.v1.20260825"
SEED_PROMPT_VERSION: Final[str] = "screening-prompt.v1"
_PACKAGE_SEED_POLICY_PATH: Final[Path] = Path(__file__).with_name("seed_policy.json")
SEED_POLICY_PATH: Final[Path] = _PACKAGE_SEED_POLICY_PATH
SEED_POLICY_DIGEST: Final[str] = "954f8275f8737183885d5007597f2d4c785b10d8720031d38015008f4c9c1289"
_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "policy_version",
        "prompt_version",
        "perspective_prompts",
        "counterargument_prompt",
        "synthesis_prompt",
        "candidate_selection",
        "thresholds",
    }
)
_PERSPECTIVE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "기술 적합성",
        "실적 정합성",
        "공공 SI 적합성",
        "사업성·자격 제약",
        "전략 부합",
    }
)
_CANDIDATE_SELECTION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "rules_version",
        "mode",
        "include_collection_buckets",
        "rejudge_on",
        "carry_over_if_unchanged",
    }
)
_CANDIDATE_SELECTION_LITERAL: Final[dict[str, Any]] = {
    "rules_version": "collect-candidate.v2",
    "mode": "candidate_pool_all",
    "include_collection_buckets": ["candidate_pool"],
    "rejudge_on": ["정정", "재공고", "본공고 전환", "담당자 요청"],
    "carry_over_if_unchanged": True,
}
_THRESHOLD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "grade_reproducibility_min_pct",
        "priority_review_rate_min_pct",
        "priority_review_rate_max_pct",
        "evidence_agreement_min_pct",
        "evidence_insufficient_max_pct",
        "perspective_split_min_pct",
        "min_valid_reviews",
        "min_discrimination_sample",
    }
)


class PolicyError(RuntimeError):
    """Base class for policy repository errors safe to expose to operators."""


class PolicyConflict(PolicyError):
    """The requested version/content or state transition conflicts."""


class PolicyActivationError(PolicyConflict):
    """The referenced quality gate cannot activate a policy."""


# Compatibility aliases used by service callers.
PolicyConflictError = PolicyConflict
PolicyActivationConflict = PolicyActivationError


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError("policy JSON contains duplicate keys")
        result[key] = value
    return result


def canonical_policy_bytes(body: Mapping[str, Any]) -> bytes:
    """Return the one canonical UTF-8 JSON byte representation of a policy."""

    if not isinstance(body, Mapping):
        raise PolicyError("policy body must be a JSON object")
    keys = set(body)
    if keys != _POLICY_KEYS or any(not isinstance(key, str) for key in keys):
        raise PolicyError("policy body must contain exactly the canonical top-level keys")
    for key in ("schema_version", "policy_version", "prompt_version"):
        if not isinstance(body[key], str) or not body[key].strip():
            raise PolicyError("policy metadata is invalid")
    if body["schema_version"] != POLICY_SCHEMA_VERSION:
        raise PolicyError("policy schema version is invalid")
    _validate_nested_policy(body)
    try:
        return json.dumps(
            dict(body),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PolicyError("policy body is not canonical JSON") from exc


def _validate_nested_policy(body: Mapping[str, Any]) -> None:
    perspectives = body["perspective_prompts"]
    if not isinstance(perspectives, dict) or set(perspectives) != _PERSPECTIVE_NAMES:
        raise PolicyError("policy perspective mapping is invalid")
    for name, value in perspectives.items():
        if not isinstance(value, dict) or set(value) != {
            "template",
            "input_fields",
            "profile_sections",
            "output_schema",
        }:
            raise PolicyError("policy perspective schema is invalid")
        template = value["template"]
        fields = value["input_fields"]
        sections = value["profile_sections"]
        if (
            not isinstance(template, str)
            or not template.strip()
            or not isinstance(fields, list)
            or not fields
            or any(not isinstance(item, str) or not item.strip() for item in fields)
            or len(set(fields)) != len(fields)
            or not isinstance(sections, list)
            or not sections
            or any(not isinstance(item, str) or not item.strip() for item in sections)
            or len(set(sections)) != len(sections)
            or value["output_schema"] != "perspective.v1"
        ):
            raise PolicyError(f"policy perspective {name} value is invalid")

    _validate_prompt_object(
        body["counterargument_prompt"],
        input_fields=["perspectives", "notice"],
        output_schema="counterargument.v1",
    )
    _validate_prompt_object(
        body["synthesis_prompt"],
        input_fields=["notice", "perspectives", "counterarguments"],
        output_schema="judgment.v3",
    )

    candidate = body["candidate_selection"]
    if not isinstance(candidate, dict) or set(candidate) != _CANDIDATE_SELECTION_KEYS:
        raise PolicyError("candidate selection schema is invalid")
    if (
        candidate["rules_version"] != _CANDIDATE_SELECTION_LITERAL["rules_version"]
        or candidate["mode"] != _CANDIDATE_SELECTION_LITERAL["mode"]
        or candidate["include_collection_buckets"] != ["candidate_pool"]
        or candidate["rejudge_on"] != _CANDIDATE_SELECTION_LITERAL["rejudge_on"]
        or type(candidate["carry_over_if_unchanged"]) is not bool
        or candidate["carry_over_if_unchanged"] is not True
    ):
        raise PolicyError("candidate selection literal is invalid")

    thresholds = body["thresholds"]
    if not isinstance(thresholds, dict) or set(thresholds) != _THRESHOLD_KEYS:
        raise PolicyError("policy threshold schema is invalid")
    percentage_keys = {
        "grade_reproducibility_min_pct",
        "priority_review_rate_min_pct",
        "priority_review_rate_max_pct",
        "evidence_agreement_min_pct",
        "evidence_insufficient_max_pct",
        "perspective_split_min_pct",
    }
    for key in _THRESHOLD_KEYS:
        value = thresholds[key]
        if type(value) is not int or value < 0:
            raise PolicyError("policy threshold value is invalid")
        if key in percentage_keys and value > 100:
            raise PolicyError("policy percentage threshold is invalid")
        if key not in percentage_keys and value < 1:
            raise PolicyError("policy count threshold is invalid")
    if thresholds["priority_review_rate_min_pct"] > thresholds["priority_review_rate_max_pct"]:
        raise PolicyError("policy priority threshold order is invalid")


def _validate_prompt_object(
    value: Any,
    *,
    input_fields: list[str],
    output_schema: str,
) -> None:
    if not isinstance(value, dict) or set(value) != {"template", "input_fields", "output_schema"}:
        raise PolicyError("policy prompt schema is invalid")
    if (
        not isinstance(value["template"], str)
        or not value["template"].strip()
        or value["input_fields"] != input_fields
        or value["output_schema"] != output_schema
    ):
        raise PolicyError("policy prompt value is invalid")


def policy_content_digest(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_policy_bytes(body)).hexdigest()


# Descriptive aliases used by pipeline code and tests.
canonical_bytes = canonical_policy_bytes
policy_digest = policy_content_digest
canonicalize_policy = canonical_policy_bytes


def load_policy_file(path: Path = SEED_POLICY_PATH) -> dict[str, Any]:
    """Load and validate one policy JSON file (never merge or patch it)."""

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            body = json.load(handle, object_pairs_hook=_reject_duplicate_keys)
    except PolicyError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyError("seed policy file could not be read") from exc
    if not isinstance(body, dict):
        raise PolicyError("seed policy file must contain one JSON object")
    # Canonicalization performs the exact top-key and JSON validity checks.
    canonical_policy_bytes(body)
    return body


def _actor(actor: str) -> str:
    if not isinstance(actor, str) or not actor.strip():
        raise PolicyConflict("actor must be nonblank")
    return actor.strip()


def _audit(
    session: Session,
    *,
    event_type: str,
    actor: str,
    target_id: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any],
) -> AuditEvent:
    # Details are deliberately metadata only.  In particular, no prompt body,
    # company profile body, secret, or free-form policy JSON is recorded.
    details = {"before": dict(before) if before is not None else None, "after": dict(after)}
    event = AuditEvent(
        event_id="audit-" + uuid4().hex,
        event_type=event_type,
        actor=actor,
        target_type="screening_policy",
        target_id=target_id,
        occurred_at=utc_now(),
        details_json=details,
    )
    session.add(event)
    return event


def _metadata(row: ScreeningPolicy) -> dict[str, Any]:
    return {
        "policy_version": row.policy_version,
        "schema_version": row.schema_version,
        "prompt_version": row.prompt_version,
        "content_digest": row.content_digest,
        "status": row.status,
        "active_slot": row.active_slot,
        "quality_gate_result_id": row.quality_gate_result_id,
    }


class PolicyRepository:
    """Transactional policy version repository.

    Methods flush their changes but do not commit the caller's transaction.
    This makes policy activation and its audit rows one transaction with any
    surrounding work while still allowing normal SQLAlchemy session use.
    """

    def __init__(self, session: Session):
        self.session = session

    def seed(self, actor: str | None = None, *, created_by: str | None = None) -> ScreeningPolicy:
        return seed_policy(self.session, actor, created_by=created_by)

    seed_default = seed

    def create(
        self,
        body: Mapping[str, Any],
        *,
        created_by: str | None = None,
        actor: str | None = None,
        status: str = "draft",
    ) -> ScreeningPolicy:
        if status != "draft":
            raise PolicyConflict("general policy creation only permits draft status")
        actor = _actor(created_by if created_by is not None else (actor or ""))
        canonical_policy_bytes(body)
        digest = policy_content_digest(body)
        version = body["policy_version"]
        existing = self.session.scalar(
            select(ScreeningPolicy).where(ScreeningPolicy.policy_version == version)
        )
        if existing is not None:
            if existing.content_digest != digest:
                raise PolicyConflict("policy version already exists with different content")
            return existing

        row = ScreeningPolicy(
            policy_version=version,
            schema_version=body["schema_version"],
            prompt_version=body["prompt_version"],
            content_digest=digest,
            status="draft",
            active_slot=None,
            perspective_prompts_json=body["perspective_prompts"],
            counterargument_prompt_json=body["counterargument_prompt"],
            synthesis_prompt_json=body["synthesis_prompt"],
            candidate_selection_json=body["candidate_selection"],
            thresholds_json=body["thresholds"],
            created_at=utc_now(),
            created_by=actor,
        )
        self.session.add(row)
        _audit(
            self.session,
            event_type="screening_policy.created",
            actor=actor,
            target_id=version,
            before=None,
            after=_metadata(row),
        )
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            existing = self.session.scalar(
                select(ScreeningPolicy).where(ScreeningPolicy.policy_version == version)
            )
            if existing is not None and existing.content_digest == digest:
                return existing
            # Do not retain SQLAlchemy's exception as a cause: its bound
            # parameters can contain the immutable prompt JSON body.
            raise PolicyConflict("policy version could not be created") from None
        return row

    create_policy = create

    def designate_candidate(
        self,
        policy_version: str,
        *,
        actor: str | None = None,
        confirmed_by: str | None = None,
    ) -> ScreeningPolicy:
        actor = _actor(actor if actor is not None else (confirmed_by or ""))
        row = self._get(policy_version)
        if row.status != "draft":
            raise PolicyConflict("only a draft policy can become an activation candidate")
        before = _metadata(row)
        row.status = "activation_candidate"
        row.active_slot = None
        row.activated_at = None
        row.activated_by = None
        row.quality_gate_result_id = None
        _audit(
            self.session,
            event_type="screening_policy.activation_candidate",
            actor=actor,
            target_id=policy_version,
            before=before,
            after=_metadata(row),
        )
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise PolicyConflict("policy could not become an activation candidate") from exc
        return row

    mark_candidate = designate_candidate
    designate_activation_candidate = designate_candidate
    candidate = designate_candidate

    def activate(
        self,
        policy_version: str,
        *,
        quality_gate_result_id: str | None = None,
        evaluation_id: str | None = None,
        gate_evaluation_id: str | None = None,
        actor: str | None = None,
        confirmed_by: str | None = None,
        activated_at: datetime | None = None,
    ) -> ScreeningPolicy:
        actor = _actor(actor if actor is not None else (confirmed_by or ""))
        quality_gate_result_id = quality_gate_result_id or evaluation_id or gate_evaluation_id
        if not isinstance(quality_gate_result_id, str) or not quality_gate_result_id.strip():
            raise PolicyActivationError("quality gate evaluation is required")
        row = self._get(policy_version)
        if row.status != "activation_candidate":
            raise PolicyActivationError("only an activation candidate can become active")
        # Keep the gate row lock through the rest of this activation
        # transaction.  A point-in-time boolean from a closed session is not
        # sufficient: a concurrent review may otherwise append a newer
        # revision before this policy commit.
        try:
            from .quality_gate import QualityGateActivationError, QualityGateService

            QualityGateService.validate_activation_in_session(
                self.session,
                quality_gate_result_id,
                policy_version=policy_version,
                prompt_version=row.prompt_version,
            )
        except QualityGateActivationError as exc:
            raise PolicyActivationError(str(exc)) from None
        evaluation, gate = self._valid_gate(
            policy_version=policy_version,
            prompt_version=row.prompt_version,
            evaluation_id=quality_gate_result_id,
        )
        before_active: list[tuple[ScreeningPolicy, dict[str, Any]]] = []
        # SQLite does not implement SELECT FOR UPDATE, but this statement is
        # still useful on other supported SQL backends.  The unique active-slot
        # index remains the final race arbiter and is translated below.
        active_rows = list(
            self.session.scalars(
                select(ScreeningPolicy)
                .where(ScreeningPolicy.status == "active")
                .with_for_update()
            )
        )
        for current in active_rows:
            before = _metadata(current)
            current.status = "activation_candidate"
            current.active_slot = None
            current.activated_at = None
            current.activated_by = None
            current.quality_gate_result_id = None
            before_active.append((current, before))

        timestamp = activated_at or utc_now()
        before_target = _metadata(row)
        for current, before in before_active:
            _audit(
                self.session,
                event_type="screening_policy.deactivated",
                actor=actor,
                target_id=current.policy_version,
                before=before,
                after=_metadata(current),
            )
        if before_active:
            try:
                # Force the old active slot to be released before assigning it
                # to the target.  Both flushes remain inside the caller's
                # transaction, so an activation failure rolls back changes
                # and audit rows together.
                self.session.flush()
            except (IntegrityError, OperationalError):
                self.session.rollback()
                raise PolicyActivationError(
                    "policy activation could not release the previous active slot"
                ) from None
        row.status = "active"
        row.active_slot = 1
        row.activated_at = timestamp
        row.activated_by = actor
        row.quality_gate_result_id = evaluation.evaluation_id
        _audit(
            self.session,
            event_type="screening_policy.activated",
            actor=actor,
            target_id=row.policy_version,
            before=before_target,
            after=_metadata(row),
        )
        try:
            self.session.flush()
        except (IntegrityError, OperationalError) as exc:
            self.session.rollback()
            raise PolicyActivationError("policy activation conflicted with another activation") from exc
        return row

    activate_policy = activate

    def _get(self, policy_version: str) -> ScreeningPolicy:
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise PolicyConflict("policy version is required")
        row = self.session.scalar(
            select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version)
        )
        if row is None:
            raise PolicyConflict("policy version was not found")
        return row

    def _valid_gate(
        self,
        *,
        policy_version: str,
        prompt_version: str,
        evaluation_id: str,
    ) -> tuple[QualityGateEvaluation, QualityGate]:
        evaluation = self.session.scalar(
            select(QualityGateEvaluation).where(
                QualityGateEvaluation.evaluation_id == evaluation_id
            )
        )
        if evaluation is None:
            raise PolicyActivationError("quality gate evaluation was not found")
        latest = self.session.scalar(
            select(func.max(QualityGateEvaluation.revision)).where(
                QualityGateEvaluation.gate_id == evaluation.gate_id
            )
        )
        gate = self.session.get(QualityGate, evaluation.gate_id)
        if (
            gate is None
            or latest != evaluation.revision
            or evaluation.result_status != "통과"
            or gate.purpose != "operational_approval"
            or gate.execution_status != "완료"
            or gate.policy_version != policy_version
            or gate.prompt_version != prompt_version
        ):
            raise PolicyActivationError("quality gate does not approve this policy")
        # Keep a repository-level guard in addition to the service check so
        # every activation path enforces the same frozen generation binding.
        try:
            from .generation_config import GenerationConfigError, config_from_value, validate_digest

            gate_config = config_from_value(gate.generation_config_json)
            validate_digest(gate_config, gate.generation_config_digest)
        except (GenerationConfigError, AttributeError):
            raise PolicyActivationError("quality gate generation config is invalid") from None
        if evaluation.generation_config_digest != gate.generation_config_digest:
            raise PolicyActivationError("quality gate evaluation generation config mismatch")
        passes = [
            self.session.get(ScreeningExecution, gate.pass_a_execution_id),
            self.session.get(ScreeningExecution, gate.pass_b_execution_id),
        ]
        if any(
            execution is None
            or execution.generation_config_digest != gate.generation_config_digest
            or execution.generation_config_json != gate_config.canonical_value()
            for execution in passes
        ):
            raise PolicyActivationError("quality pass generation config mismatch")
        return evaluation, gate


ScreeningPolicyRepository = PolicyRepository
PolicyStore = PolicyRepository


def create_policy(
    session: Session,
    body: Mapping[str, Any],
    *,
    created_by: str | None = None,
    actor: str | None = None,
) -> ScreeningPolicy:
    return PolicyRepository(session).create(
        body,
        created_by=created_by if created_by is not None else (actor or ""),
    )


def designate_policy_candidate(
    session: Session,
    policy_version: str,
    *,
    actor: str | None = None,
    confirmed_by: str | None = None,
) -> ScreeningPolicy:
    return PolicyRepository(session).designate_candidate(
        policy_version,
        actor=actor,
        confirmed_by=confirmed_by,
    )


def activate_policy(
    session: Session,
    policy_version: str,
    *,
    quality_gate_result_id: str | None = None,
    evaluation_id: str | None = None,
    gate_evaluation_id: str | None = None,
    actor: str | None = None,
    confirmed_by: str | None = None,
    activated_at: datetime | None = None,
) -> ScreeningPolicy:
    return PolicyRepository(session).activate(
        policy_version,
        quality_gate_result_id=quality_gate_result_id,
        evaluation_id=evaluation_id,
        gate_evaluation_id=gate_evaluation_id,
        actor=actor,
        confirmed_by=confirmed_by,
        activated_at=activated_at,
    )


def _seed_policy_from_path(
    session: Session,
    actor: str | None = None,
    *,
    created_by: str | None = None,
    path: Path = SEED_POLICY_PATH,
) -> ScreeningPolicy:
    """Load the checked-in seed file and create/designate it idempotently."""

    actor = actor if actor is not None else created_by
    if actor is None:
        raise PolicyConflict("actor must be nonblank")
    body = load_policy_file(path)
    if body.get("policy_version") != SEED_POLICY_VERSION or body.get("prompt_version") != SEED_PROMPT_VERSION:
        raise PolicyError("seed policy metadata is invalid")
    if policy_content_digest(body) != SEED_POLICY_DIGEST:
        raise PolicyError("seed policy content digest is invalid")
    repository = PolicyRepository(session)
    row = repository.create(body, created_by=actor)
    if row.status == "draft":
        row = repository.designate_candidate(row.policy_version, actor=actor)
    elif row.status != "activation_candidate":
        # Seed never silently changes an active policy.
        if row.status == "active":
            return row
        raise PolicyConflict("seed policy has an invalid persisted state")
    return row


def seed_policy(
    session: Session,
    actor: str | None = None,
    *,
    created_by: str | None = None,
) -> ScreeningPolicy:
    """Seed only the package-owned immutable policy file."""

    return _seed_policy_from_path(
        session,
        actor,
        created_by=created_by,
        path=_PACKAGE_SEED_POLICY_PATH,
    )


# A command-like alias is useful for an explicit operator invocation; nothing
# calls it from app startup or a migration.
seed = seed_policy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.screening.policy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed_parser = subparsers.add_parser("seed-default")
    seed_parser.add_argument("--created-by", required=True)
    args = parser.parse_args(argv)
    if args.command != "seed-default":  # pragma: no cover - argparse choices
        return 2
    try:
        from ..db import SessionLocal

        with SessionLocal() as session:
            row = seed_policy(session, actor=args.created_by)
            session.commit()
            print(f"{row.policy_version} {row.status}")
        return 0
    except PolicyError:
        # Keep prompt/profile content and SQL parameters out of operator output.
        print("seed policy failed", file=sys.stderr)
        return 2
    except Exception:
        print("seed policy failed", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised by subprocess tests
    raise SystemExit(main())


__all__ = [
    "POLICY_SCHEMA_VERSION",
    "SEED_POLICY_PATH",
    "SEED_POLICY_DIGEST",
    "SEED_POLICY_VERSION",
    "SEED_PROMPT_VERSION",
    "PolicyActivationConflict",
    "PolicyActivationError",
    "PolicyConflict",
    "PolicyConflictError",
    "PolicyError",
    "PolicyRepository",
    "PolicyStore",
    "ScreeningPolicyRepository",
    "activate_policy",
    "canonical_policy_bytes",
    "canonical_bytes",
    "canonicalize_policy",
    "create_policy",
    "designate_policy_candidate",
    "load_policy_file",
    "policy_content_digest",
    "policy_digest",
    "seed",
    "seed_policy",
    "main",
]
