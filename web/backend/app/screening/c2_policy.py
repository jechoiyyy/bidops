"""Explicit operator commands for the C-2 policy row (load, retire).

``python -m app.screening.c2_policy load --policy <path> --binding <path>
--created-by <name>`` creates one ``order_plan_screening_policy`` row.  App
startup, migrations and image builds never do this (ADR-0060 §4).

``python -m app.screening.c2_policy retire --policy-version <v> --retired-by
<name> --reason <text>`` takes the active row down to ``retired`` **without a
replacement**.  That is an exceptional operational action: the normal path is
the automatic retirement of the previous active row when a new version is
activated.  The transition itself lives in
``services/order_plan_policy.retire_policy``.

The digests are ``sha256`` of the file bytes as published.  The v2 files are
not canonical JSON, so re-serializing them would produce a digest that no
mounted file matches and every execution would fail ``binding_mismatch``.

The file's stateful fields (``policy_status``, ``activation.*``,
``quality_gate.*``, ``audit_sample.status``) are publication-time snapshots.
They are schema-validated but never gate this command: the row is always a
``draft`` and only the policy REST moves it forward.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Final
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.api_errors import BundleServiceError, validate_actor
from ..core.models import AuditEvent, utc_now
from .c2_contracts import OrderPlanScreeningPolicyArtifact
from .models import OrderPlanScreeningPolicy
from .policy import PolicyError, _reject_duplicate_keys


BINDING_SCHEMA_VERSION: Final[str] = "bidops.order-plan-screening-phase0-binding.v1"
DECISION_SCOPE: Final[str] = "c2_order_plan_first_pass"
BINDING_STATUSES: Final[frozenset[str]] = frozenset({"blocked", "activation_candidate", "approved"})
LOADED_POLICY_STATUS: Final[str] = "draft"
# ``NULL`` and ``not_measured`` both pass the table check; the row has no DB
# gate evaluation yet, which ``not_measured`` states explicitly.  Only the
# activation transition may change it afterwards (guard trigger, 0029).
LOADED_QUALITY_GATE_STATUS: Final[str] = "not_measured"
AUDIT_ACTION: Final[str] = "c2.policy_loaded"


class C2PolicyLoadError(RuntimeError):
    """A load failure whose ``code`` is safe to print; no body or path."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class C2PolicyLoadResult:
    row: OrderPlanScreeningPolicy
    created: bool


def _reject_constant(value: str) -> Any:
    # NaN/Infinity are not JSON and PostgreSQL JSONB rejects them.
    raise ValueError(value)


def _read_json_object(path: Path, *, code: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        body = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except PolicyError:
        raise C2PolicyLoadError(f"{code}_duplicate_key") from None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise C2PolicyLoadError(f"{code}_unreadable") from None
    if not isinstance(body, dict):
        raise C2PolicyLoadError(f"{code}_not_object")
    return raw, body


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_binding(binding: Mapping[str, Any], policy: OrderPlanScreeningPolicyArtifact, policy_sha256: str) -> None:
    if binding.get("schema_version") != BINDING_SCHEMA_VERSION:
        raise C2PolicyLoadError("binding_schema_invalid")
    reference = binding.get("policy")
    if not isinstance(reference, Mapping):
        raise C2PolicyLoadError("binding_policy_reference_invalid")
    if reference.get("sha256") != policy_sha256:
        raise C2PolicyLoadError("binding_policy_digest_mismatch")
    if reference.get("policy_version") != policy.policy_version:
        raise C2PolicyLoadError("binding_policy_version_mismatch")
    if reference.get("policy_status") != policy.policy_status:
        # Same rule as the worker: the two files must agree with each other.
        # The value itself is a publication snapshot and gates nothing.
        raise C2PolicyLoadError("binding_policy_status_mismatch")
    status = binding.get("status")
    if status not in BINDING_STATUSES:
        raise C2PolicyLoadError("binding_status_invalid")
    transport = binding.get("external_transport")
    if status == "blocked" and isinstance(transport, Mapping) and transport.get("execution_allowed") is True:
        # ADR-0060 §3: a blocked binding that allows execution contradicts itself.
        raise C2PolicyLoadError("binding_blocked_execution_allowed")


def _existing(session: Session, policy_version: str) -> OrderPlanScreeningPolicy | None:
    return session.scalar(
        select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == policy_version)
    )


def _same_or_conflict(row: OrderPlanScreeningPolicy, policy_sha256: str, binding_sha256: str) -> C2PolicyLoadResult:
    if row.policy_sha256 != policy_sha256 or row.binding_sha256 != binding_sha256:
        raise C2PolicyLoadError("immutable_conflict")
    return C2PolicyLoadResult(row=row, created=False)


def load_policy(
    session: Session,
    *,
    policy_path: Path,
    binding_path: Path,
    created_by: str,
) -> C2PolicyLoadResult:
    """Validate one policy/binding pair and create its ``draft`` row.

    Flushes but does not commit.  The same version with the same two digests
    returns the existing row unchanged; a different digest is
    ``immutable_conflict``.
    """

    try:
        actor = validate_actor(created_by)
    except BundleServiceError:
        raise C2PolicyLoadError("created_by_invalid") from None
    policy_bytes, policy_raw = _read_json_object(policy_path, code="policy")
    binding_bytes, binding_raw = _read_json_object(binding_path, code="binding")
    try:
        # The artifact model also pins ``decision_scope`` to DECISION_SCOPE and
        # ``policy_status`` to the enum without reading its value as a gate.
        policy = OrderPlanScreeningPolicyArtifact.model_validate(policy_raw)
    except ValidationError:
        # Pydantic messages echo input values; keep them out of operator output.
        raise C2PolicyLoadError("policy_schema_invalid") from None
    policy_sha256 = _sha256(policy_bytes)
    binding_sha256 = _sha256(binding_bytes)
    _validate_binding(binding_raw, policy, policy_sha256)

    existing = _existing(session, policy.policy_version)
    if existing is not None:
        return _same_or_conflict(existing, policy_sha256, binding_sha256)

    now = utc_now()
    row = OrderPlanScreeningPolicy(
        id=uuid4(),
        policy_version=policy.policy_version,
        schema_version=policy.schema_version,
        producer=policy.producer,
        consumer=policy.consumer,
        policy_status=LOADED_POLICY_STATUS,
        decision_scope=policy.decision_scope,
        policy_payload_jsonb=policy_raw,
        binding_payload_jsonb=binding_raw,
        policy_sha256=policy_sha256,
        binding_sha256=binding_sha256,
        # The file's ``activation`` block is a snapshot kept in the payload;
        # activation provenance lives in ``activated_by/at``.
        activation_metadata_jsonb={},
        quality_gate_status=LOADED_QUALITY_GATE_STATUS,
        active_slot=None,
        created_by=actor,
        created_at=now,
        activated_by=None,
        activated_at=None,
    )
    session.add(row)
    session.add(AuditEvent(
        id=uuid4(),
        actor_kind="human",
        claimed_name=actor,
        action=AUDIT_ACTION,
        aggregate_type="order_plan_screening_policy",
        aggregate_id=policy.policy_version,
        safe_metadata={
            "policy_status": LOADED_POLICY_STATUS,
            "policy_sha256": policy_sha256,
            "binding_sha256": binding_sha256,
            "binding_version": binding_raw.get("binding_version"),
            "binding_status": binding_raw.get("status"),
        },
        request_id=None,
        created_at=now,
    ))
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = _existing(session, policy.policy_version)
        if existing is not None:
            return _same_or_conflict(existing, policy_sha256, binding_sha256)
        # SQLAlchemy's exception carries the payload as bound parameters.
        raise C2PolicyLoadError("policy_insert_rejected") from None
    return C2PolicyLoadResult(row=row, created=True)


def _retire(args: argparse.Namespace) -> int:
    """``retire`` 서브커맨드. 서비스가 전이·감사를 하고 여기서 commit한다."""

    # 지연 import: ``load`` 경로의 import 그래프를 넓히지 않는다(순환 import 사고 예방).
    from ..core.db import SessionLocal
    from .services.order_plan_policy import retire_policy
    from .services.order_plan_screening import OrderPlanScreeningError

    try:
        with SessionLocal() as session:
            result = retire_policy(
                session,
                policy_version=args.policy_version,
                retired_by=args.retired_by,
                reason=args.reason,
            )
            session.commit()
            row = result.policy
            outcome = "retired" if result.changed else "already_retired"
            print(f"{row.policy_version} {row.policy_status} {row.policy_sha256} {row.binding_sha256} {outcome}")
        return 0
    except OrderPlanScreeningError as exc:
        # 안정 code만 낸다. ``policy_not_active``는 고정 enum인 현재 상태를 덧붙인다.
        status = (getattr(exc, "details", None) or {}).get("policy_status")
        suffix = f" (policy_status={status})" if status else ""
        print(f"c2 policy retire failed: {exc.code}{suffix}", file=sys.stderr)
        return 2
    except Exception:
        print("c2 policy retire failed", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.screening.c2_policy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    load_parser = subparsers.add_parser("load")
    load_parser.add_argument("--policy", required=True, type=Path)
    load_parser.add_argument("--binding", required=True, type=Path)
    load_parser.add_argument("--created-by", required=True)
    retire_parser = subparsers.add_parser("retire")
    retire_parser.add_argument("--policy-version", required=True)
    retire_parser.add_argument("--retired-by", required=True)
    retire_parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    if args.command == "retire":
        return _retire(args)
    if args.command != "load":  # pragma: no cover - argparse choices
        return 2
    try:
        from ..core.db import SessionLocal

        with SessionLocal() as session:
            result = load_policy(
                session,
                policy_path=args.policy,
                binding_path=args.binding,
                created_by=args.created_by,
            )
            session.commit()
            row = result.row
            outcome = "created" if result.created else "unchanged"
            print(f"{row.policy_version} {row.policy_status} {row.policy_sha256} {row.binding_sha256} {outcome}")
        return 0
    except C2PolicyLoadError as exc:
        # Only the stable code: no file body, path or SQL parameters.
        print(f"c2 policy load failed: {exc.code}", file=sys.stderr)
        return 2
    except Exception:
        print("c2 policy load failed", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised by subprocess tests
    raise SystemExit(main())


__all__ = [
    "AUDIT_ACTION",
    "BINDING_SCHEMA_VERSION",
    "C2PolicyLoadError",
    "C2PolicyLoadResult",
    "load_policy",
    "main",
]
