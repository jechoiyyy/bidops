"""Bounded operator commands for the opt-in prespec v4 preparation cohort."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.deep_review.cli prespec-v4",
        description="Manage the explicitly activated prespec v4 preparation cohort",
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--dry-run", action="store_true", help="read-only eligibility plan")
    actions.add_argument("--activate", action="store_true", help="append an active cohort audit event")
    actions.add_argument("--deactivate", action="store_true", help="append an off audit event")
    actions.add_argument("--prepare", action="store_true", help="prepare and freeze one or more PDF inputs")
    actions.add_argument("--enqueue", action="store_true", help="prepare and enqueue one or more v4 attempts")
    actions.add_argument("--enqueue-reference", action="store_true", help="enqueue one Luna reference attempt (app role)")
    actions.add_argument("--retry", action="store_true", help="append a new attempt for a failed target")
    actions.add_argument("--run-reference", action="store_true", help="run an already queued Luna reference attempt (worker role)")
    parser.add_argument("--notice-id", action="append", type=int, default=[])
    parser.add_argument("--target-id", type=str)
    parser.add_argument("--mode", choices=("explicit_sample", "new_reference"), default="explicit_sample")
    parser.add_argument("--actor")
    parser.add_argument("--reason", default="operator_requested")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--binding", type=Path, help="trusted worker/model binding JSON")
    parser.add_argument("--luna-response", type=Path, help="one-time gpt-5.6-luna response envelope JSON")
    parser.add_argument("--sample-key", help="sample key when --luna-response is a Luna generation-record.json")
    parser.add_argument("--options", type=Path, help="trusted ProcessorOptions JSON")
    parser.add_argument("--renderer", type=Path, help="trusted generated-worker renderer binding JSON")
    parser.add_argument("--font", type=Path, help="trusted generated-worker font binding JSON")
    parser.add_argument("--config", type=Path, help="trusted normalized converter config JSON")
    return parser


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("invalid_binding_path")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("binding_json_invalid")
    return value


def _load_luna_response(path: Path, *, policy: Any, sample_key: str | None):
    from ..services.prespec_v4_ops import V4OpsError
    from ..services.prespec_v4_luna_reference import (
        LunaReferenceError,
        load_luna_generation_sample,
        load_luna_reference_response,
    )

    try:
        if sample_key is not None:
            return load_luna_generation_sample(path, sample_key=sample_key, policy=policy)
        return load_luna_reference_response(path, policy=policy)
    except LunaReferenceError as error:
        raise V4OpsError(error.code) from error


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from ...core.db import SessionLocal, init_db
        from ...core.config import get_settings
        from ..services.prespec_v4_ops import (
            V4OpsError,
            activate_v4,
            deactivate_v4,
            dry_run_v4,
            load_v4_activation_artifact,
            prepare_v4_notice_once,
            resolve_v4_reference_binding,
            retry_v4_attempt,
        )
        from ..services.prespec_v4_runner import V4ModelBinding, load_v4_policy

        settings = get_settings()
        init_db()
        if not args.actor and not args.dry_run:
            raise V4OpsError("actor_required")
        with SessionLocal() as session:
            if args.dry_run:
                result = dry_run_v4(session, notice_ids=args.notice_id, mode=args.mode, settings=settings)
            elif args.activate:
                artifact = _read_json(args.artifact)
                activation_binding = None
                if args.binding is not None and args.luna_response is not None:
                    raise V4OpsError("binding_source_conflict")
                if args.luna_response is not None:
                    reference = _load_luna_response(
                        args.luna_response,
                        policy=load_v4_policy(),
                        sample_key=args.sample_key,
                    )
                    activation_binding = reference.binding
                elif args.binding is not None:
                    activation_binding = V4ModelBinding(**(_read_json(args.binding) or {}))
                result = activate_v4(session, actor=args.actor, mode=args.mode, artifact=artifact, artifact_path=args.artifact, binding=activation_binding, settings=settings)
                session.commit()
                result = {"status": "active", "activation_id": str(result.activation_id), "mode": result.mode, "artifact_sha256": result.artifact_sha256, "binding_digest": result.binding.binding_digest}
            elif args.deactivate:
                activation_id = deactivate_v4(session, actor=args.actor, reason=args.reason)
                session.commit()
                result = {"status": "off", "activation_id": str(activation_id)}
            elif args.enqueue_reference:
                if not args.target_id or args.luna_response is None:
                    raise V4OpsError("reference_target_and_response_required")
                from ..services.prespec_v4_luna_reference import record_luna_reference_audit
                from ..services.prespec_v4_runner import enqueue_v4_attempt

                policy = load_v4_policy()
                reference = _load_luna_response(
                    args.luna_response,
                    policy=policy,
                    sample_key=args.sample_key,
                )
                target_id = __import__("uuid").UUID(args.target_id)
                attempt = enqueue_v4_attempt(
                    session, target_id=target_id, binding=reference.binding, quality_status="unmeasured_reference"
                )
                if attempt is None:
                    raise V4OpsError("reference_attempt_unavailable")
                record_luna_reference_audit(session, attempt_id=attempt.id, response=reference)
                session.commit()
                result = {
                    "status": "queued" if attempt.status == "queued" else attempt.status,
                    "attempt_id": str(attempt.id),
                    "target_id": str(target_id),
                    "model": reference.binding.model_name,
                    "model_digest": reference.binding.model_digest,
                    "quality_status": "unmeasured_reference",
                }
            elif args.run_reference:
                if not args.target_id or args.luna_response is None:
                    raise V4OpsError("reference_target_and_response_required")
                from sqlalchemy import select
                from ...core.models import AuditEvent
                from ..models import PrespecV4Attempt
                from ..services.prespec_v4_luna_reference import LunaReferenceClient
                from ..services.prespec_v4_runner import PrespecV4OverviewRunner
                from ...core.object_store import object_store

                policy = load_v4_policy()
                reference = _load_luna_response(
                    args.luna_response,
                    policy=policy,
                    sample_key=args.sample_key,
                )
                target_id = __import__("uuid").UUID(args.target_id)
                attempt = session.scalar(
                    select(PrespecV4Attempt)
                    .where(PrespecV4Attempt.target_id == target_id)
                    .order_by(PrespecV4Attempt.sequence.desc())
                )
                if attempt is None or attempt.status != "queued":
                    raise V4OpsError("reference_attempt_not_queued")
                if attempt.binding_digest != reference.binding.binding_digest or attempt.model_digest != reference.binding.model_digest:
                    raise V4OpsError("reference_binding_mismatch")
                audit = session.scalar(
                    select(AuditEvent)
                    .where(
                        AuditEvent.action == "prespec_v4.luna_reference",
                        AuditEvent.aggregate_type == "prespec_v4_attempt",
                        AuditEvent.aggregate_id == str(attempt.id),
                    )
                    .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                )
                if audit is None or not isinstance(audit.safe_metadata, dict) or audit.safe_metadata.get("manifest_sha256") != reference.manifest_sha256:
                    raise V4OpsError("reference_audit_missing")
                runner = PrespecV4OverviewRunner(
                    client=LunaReferenceClient(reference),
                    binding=reference.binding,
                    policy=policy,
                    object_store=object_store(namespaces=("structure",), read_namespaces=("structure",)),
                    settings=settings,
                )
                run = runner.run_once(session, worker_id=f"luna-reference:{args.actor}")
                result = {
                    "status": run.status,
                    "reason_code": run.reason_code,
                    "attempt_id": str(run.attempt_id or attempt.id),
                    "target_id": str(target_id),
                    "model": reference.binding.model_name,
                    "model_digest": reference.binding.model_digest,
                    "quality_status": "unmeasured_reference",
                }
            else:
                if args.prepare or args.enqueue:
                    if not args.notice_id:
                        raise V4OpsError("notice_id_required")
                    if args.renderer is None or args.font is None or args.config is None:
                        raise V4OpsError("worker_binding_required")
                    from ...core.clamav import ClamAVScanner
                    from ...core.object_store import object_store
                    from ..services.document_converter import ScratchDocumentProcessor
                    from ...core.config import get_settings as _settings

                    options = _read_json(args.options) or {
                        "prepare_pdf": True, "ocr": False, "timeout_seconds": 300,
                        "max_output_bytes": 64 * 1024 * 1024, "max_pdf_objects": 10000,
                    }
                    config = _read_json(args.config) or {}
                    scanner = ClamAVScanner(settings.clamav_host, settings.clamav_port, settings.clamav_timeout_seconds)
                    converter = ScratchDocumentProcessor(wait_seconds=310, clamav_checker=scanner.scan)
                    store = object_store(namespaces=("source", "structure"), read_namespaces=("source",))
                    outputs = []
                    for notice_id in args.notice_id:
                        outcome = prepare_v4_notice_once(
                            session, notice_id=notice_id, mode=args.mode, store=store, converter=converter,
                            options=options, renderer=_read_json(args.renderer) or {}, font=_read_json(args.font) or {},
                            config=config, scanner=scanner.scan, settings=settings, enqueue=args.enqueue,
                        )
                        outputs.append({"notice_id": outcome.notice_id, "status": outcome.status, "target_id": str(outcome.target_id), "attempt_id": str(outcome.attempt_id) if outcome.attempt_id else None})
                    session.commit()
                    result = outputs
                elif args.retry:
                    if not args.target_id:
                        raise V4OpsError("target_id_required")
                    binding_value = _read_json(args.binding)
                    binding = resolve_v4_reference_binding(settings=settings) if binding_value is None else V4ModelBinding(**binding_value)
                    attempt = retry_v4_attempt(session, target_id=__import__("uuid").UUID(args.target_id), binding=binding, settings=settings)
                    session.commit()
                    result = {"status": "queued", "attempt_id": str(attempt.id), "target_id": str(attempt.target_id)}
                else:  # pragma: no cover - argparse makes this unreachable
                    raise V4OpsError("action_required")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
        return 0
    except V4OpsError as error:
        print(json.dumps({"error": error.code}, ensure_ascii=False, sort_keys=True))
        return 2
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        print(json.dumps({"error": "v4_ops_failed"}, ensure_ascii=False, sort_keys=True))
        return 2


__all__ = ["build_parser", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("이 명령은 `python -m app.deep_review.cli prespec-v4 <인자>`로 실행한다")
