"""Run the isolated document-bundle to deep-review acceptance flow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Sequence

from pydantic import ValidationError

from ..services.bc_e2e import BcE2EError, BcE2EManifest, JsonAcceptanceApi, run_bc_e2e


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run isolated BidOps stage B to C API acceptance")
    parser.add_argument("manifest", type=Path, help="absolute bidops.bc-e2e-run.v1 JSON path")
    parser.add_argument("--confirm-target", help="must exactly match manifest api_base before mutation")
    parser.add_argument("--output", type=Path, help="absolute evidence JSON path (required unless --dry-run)")
    parser.add_argument("--analysis-timeout-seconds", type=float, default=3600)
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--t7", action="store_true", help="run the complete mock-reference B-to-C-to-decision acceptance flow")
    parser.add_argument("--dry-run", action="store_true", help="validate inputs and print the bounded plan without API mutation")
    return parser


def _load_manifest(path: Path) -> BcE2EManifest:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise BcE2EError("invalid_manifest", "manifest must be an absolute regular non-symlink file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return BcE2EManifest.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
        raise BcE2EError("invalid_manifest", "B-to-C E2E manifest is invalid") from error


def _write_evidence(path: Path, payload: dict[str, Any]) -> None:
    if (
        not path.is_absolute()
        or path.exists()
        or path.is_symlink()
        or not path.parent.is_dir()
        or path.parent.resolve() != path.parent
    ):
        raise BcE2EError("invalid_output", "output must be a new absolute file in an existing directory")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        # link(2) is an atomic no-clobber publish: unlike replace(), it fails
        # if another acceptance run created the requested evidence path.
        os.link(temporary, path)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError as error:
        temporary.unlink(missing_ok=True)
        raise BcE2EError("invalid_output", "output already exists") from error
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = _load_manifest(args.manifest)
        if args.analysis_timeout_seconds < 30 or args.poll_seconds <= 0 or args.poll_seconds > 60:
            raise BcE2EError("invalid_request", "timeout must be >=30 seconds and poll interval must be within 0..60 seconds")
        plan = {
            "schema": "bidops.t7-e2e-plan.v1" if args.t7 else "bidops.bc-e2e-plan.v1",
            "api_base": manifest.api_base,
            "notice_id": manifest.notice_id,
            "document_count": len(manifest.documents),
            "document_identities": [
                {"filename": document.path.name, "role": document.role, "size_bytes": document.path.stat().st_size}
                for document in manifest.documents
            ],
            "analysis_retry_limit": manifest.analysis_retry_limit,
        }
        if args.t7:
            plan["workflow"] = "t7-mock-reference"
        if args.dry_run:
            print(json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 0
        if args.confirm_target != manifest.api_base:
            raise BcE2EError("target_not_confirmed", "--confirm-target must exactly match manifest api_base")
        if args.output is None:
            raise BcE2EError("invalid_output", "--output is required for a mutating acceptance run")
        if args.t7:
            from ..services.agent_e2e import PersistedAgentProjectionReader, run_t7_e2e

            result = run_t7_e2e(
                manifest,
                JsonAcceptanceApi(manifest.api_base),
                PersistedAgentProjectionReader(),
                timeout_seconds=args.analysis_timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
        else:
            result = run_bc_e2e(
                manifest,
                JsonAcceptanceApi(manifest.api_base),
                timeout_seconds=args.analysis_timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
        _write_evidence(args.output, result)
        if args.t7:
            first_flow = result["first_flow"]
            second_flow = result["second_flow"]
            summary = {
                "passed": True,
                "evidence_file": str(args.output),
                "workflow": result["workflow"],
                "first_bundle_id": first_flow["bundle_id"],
                "first_deep_review_id": first_flow["review_id"],
                "second_bundle_id": second_flow["bundle_id"],
                "second_deep_review_id": second_flow["review_id"],
                "final_opinion_id": first_flow["final_opinion"]["id"],
                "active_work_jobs": result["work_jobs"]["active"],
            }
        else:
            summary = {
                "passed": True,
                "evidence_file": str(args.output),
                "bundle_id": result["bundle"]["id"],
                "deep_review_id": result["deep_review"]["id"],
            }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except BcE2EError as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error), "status": error.status}}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
