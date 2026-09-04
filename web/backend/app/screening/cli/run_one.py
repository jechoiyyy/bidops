"""Operator CLI for one notice, with no model/network work at import time."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Sequence

from ..orchestrator import ScreeningCreationError, ScreeningOrchestrator
from ..worker import ScreeningWorker


PROFILE_RE = re.compile(r"^(?:current|git:[0-9a-f]{40})$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.screening.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run-one")
    run.add_argument("--run-id", required=True)
    run.add_argument("--notice-id", required=True)
    run.add_argument("--policy-version", required=True)
    run.add_argument("--profile-source", required=True)
    run.add_argument("--requested-by", required=True)
    run.add_argument("--wait", action="store_true")
    return parser


def _print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main(
    argv: Sequence[str] | None = None,
    *,
    service: ScreeningOrchestrator | None = None,
    worker: ScreeningWorker | None = None,
) -> int:
    try:
        args = build_parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit:
        # CLI callers receive the documented input-error exit code rather than
        # an argparse-specific process status.
        return 1
    if args.command != "run-one":
        return 1
    if not PROFILE_RE.fullmatch(args.profile_source):
        _print({"status": "실패", "error_code": "input_error"})
        return 1
    try:
        creator = service or ScreeningOrchestrator()
        created = creator.create_execution(
            run_id=args.run_id,
            notice_id=args.notice_id,
            policy_version=args.policy_version,
            profile_source=args.profile_source,
            requested_by=args.requested_by,
            scope="single_notice",
            trigger="cli_single",
        )
    except (ScreeningCreationError, ValueError, RuntimeError):
        _print({"status": "실패", "error_code": "input_error"})
        return 1
    if not args.wait:
        _print({
            "execution_id": created.execution_id,
            "status": created.status,
            "model": created.model_name,
            "model_digest": created.model_digest,
            "profile": created.profile_version,
            "profile_digest": created.profile_digest,
            "artifact_dir": created.artifact_dir,
            "input_artifact_path": created.input_artifact_path,
            "result_artifact_path": f"{created.artifact_dir}/screening-results.json",
            "failure_artifact_path": f"{created.artifact_dir}/screening-failures.json",
        })
        return 0
    try:
        runner = worker or ScreeningWorker()
        final = runner.run_until(created.execution_id)
    except Exception:
        _print({"execution_id": created.execution_id, "status": "실패", "error_code": "execution_failure"})
        return 1
    _print({
        "execution_id": final.execution_id, "status": final.status,
        "model": final.model_name, "model_digest": final.model_digest,
        "profile": getattr(final, "company_profile_version", getattr(final, "profile_version", "")),
        "profile_digest": getattr(final, "company_profile_digest", getattr(final, "profile_digest", "")),
        "artifact_dir": final.artifact_dir,
        "result_artifact_path": f"{final.artifact_dir}/screening-results.json",
        "failure_artifact_path": f"{final.artifact_dir}/screening-failures.json",
    })
    if final.status == "성공":
        return 0
    if final.status == "부분 성공":
        return 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
