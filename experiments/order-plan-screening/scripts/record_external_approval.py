#!/usr/bin/env python3
"""Show a safe Luna preview or record an explicit immutable approval artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import (
    EXTERNAL_APPROVAL_SCHEMA,
    ExperimentError,
    load_run_population,
    parse_timezone_timestamp,
    write_json_new,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-dir", required=True, type=Path)
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--target-run-id")
    parser.add_argument("--approved-by")
    parser.add_argument("--approved-at")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def preview_from_run(run: dict) -> dict:
    external = run.get("external_transmission")
    if not isinstance(external, dict) or external.get("status") != "pending_approval":
        raise ExperimentError("external_preview_unavailable", "pending Luna preview가 없습니다")
    keys = (
        "model",
        "purpose",
        "prompt_sha256",
        "company_capabilities_sha256",
        "payload_fields",
        "record_count",
        "batch_size",
        "batch_count",
        "preview_sha256",
    )
    preview = {key: external.get(key) for key in keys}
    if (
        not isinstance(preview["model"], str)
        or not isinstance(preview["purpose"], str)
        or not isinstance(preview["prompt_sha256"], str)
        or not isinstance(preview["company_capabilities_sha256"], str)
        or not isinstance(preview["payload_fields"], list)
        or not isinstance(preview["record_count"], int)
        or isinstance(preview["record_count"], bool)
        or preview["record_count"] < 0
        or not isinstance(preview["batch_size"], int)
        or isinstance(preview["batch_size"], bool)
        or preview["batch_size"] < 1
        or not isinstance(preview["batch_count"], int)
        or isinstance(preview["batch_count"], bool)
        or preview["batch_count"]
        != (preview["record_count"] + preview["batch_size"] - 1)
        // preview["batch_size"]
        or not isinstance(preview["preview_sha256"], str)
    ):
        raise ExperimentError("external_preview_invalid", "Luna preview 계약이 잘못됐습니다")
    return preview


def main() -> int:
    args = parse_args()
    try:
        if args.show == args.approve:
            raise ExperimentError("approval_action_invalid", "--show 또는 --approve 중 하나만 선택해야 합니다")
        run, _population = load_run_population(args.source_run_dir.resolve())
        preview = preview_from_run(run)
        safe_preview = {
            "source_run_id": run["run_id"],
            **preview,
            "company_payload": "승인된 최소 역량 projection (본문 미표시)",
        }
        if args.show:
            print(json.dumps(safe_preview, ensure_ascii=False, indent=2))
            return 0
        if not args.target_run_id or not args.approved_by or not args.approved_at or args.output is None:
            raise ExperimentError(
                "approval_fields_missing",
                "승인 기록에는 target-run-id, approved-by, approved-at, output이 필요합니다",
            )
        if (
            "/" in args.target_run_id
            or "\\" in args.target_run_id
            or ".." in args.target_run_id
        ):
            raise ExperimentError("invalid_run_id", "target run_id가 안전하지 않습니다")
        parse_timezone_timestamp(args.approved_at, "approved_at")
        approval = {
            "schema_version": EXTERNAL_APPROVAL_SCHEMA,
            "run_id": args.target_run_id,
            **preview,
            "approved_by": args.approved_by,
            "approved_at": args.approved_at,
        }
        write_json_new(args.output.resolve(), approval)
        print(
            json.dumps(
                {
                    "status": "approved",
                    "run_id": args.target_run_id,
                    "model": preview["model"],
                    "record_count": preview["record_count"],
                    "batch_size": preview["batch_size"],
                    "batch_count": preview["batch_count"],
                    "preview_sha256": preview["preview_sha256"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except ExperimentError as exc:
        print(json.dumps({"status": "failed", "error_code": exc.code}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
