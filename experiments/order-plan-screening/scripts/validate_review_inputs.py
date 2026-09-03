#!/usr/bin/env python3
"""Validate the human-review manifest without printing protected document bodies."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
from typing import Any

from common import (
    ExperimentError,
    is_sha256,
    load_capabilities,
    load_json,
    parse_timezone_timestamp,
    sha256_file,
)


MANIFEST_SCHEMA = "bidops.order-plan-review-inputs-manifest.v1"
DOCUMENT_KINDS = {"company_capabilities", "prompt"}
DOCUMENT_STATUSES = {"approved", "draft", "retired"}


def _require_exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ExperimentError("invalid_review_inputs", f"{label} 필드 구성이 잘못됐습니다")
    return value


def _resolve_document(root: Path, relative_value: Any) -> Path:
    if not isinstance(relative_value, str) or not relative_value:
        raise ExperimentError("invalid_review_inputs", "document path가 필요합니다")
    relative = PurePosixPath(relative_value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != relative_value:
        raise ExperimentError("invalid_review_inputs", "document path는 안전한 상대 경로여야 합니다")
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ExperimentError("review_input_unavailable", f"검토 입력 파일을 읽을 수 없습니다: {candidate.name}")
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ExperimentError("invalid_review_inputs", "document path가 검토 폴더를 벗어났습니다") from exc
    return candidate


def validate_review_inputs(root: Path) -> dict[str, Any]:
    manifest = _require_exact_keys(
        load_json(root / "manifest.json"),
        {
            "schema_version",
            "updated_at",
            "active_company_capabilities",
            "active_prompt",
            "documents",
        },
        "review inputs manifest",
    )
    if manifest["schema_version"] != MANIFEST_SCHEMA:
        raise ExperimentError("schema_mismatch", "review inputs manifest schema가 다릅니다")
    parse_timezone_timestamp(manifest["updated_at"], "review-inputs.updated_at")
    documents = manifest["documents"]
    if not isinstance(documents, list) or not documents:
        raise ExperimentError("invalid_review_inputs", "documents가 비어 있습니다")

    indexed: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(documents):
        document = _require_exact_keys(
            raw,
            {
                "kind",
                "path",
                "version",
                "status",
                "execution_allowed",
                "sha256",
                "source_path",
            },
            f"documents[{index}]",
        )
        kind = document["kind"]
        status = document["status"]
        if kind not in DOCUMENT_KINDS or status not in DOCUMENT_STATUSES:
            raise ExperimentError("invalid_review_inputs", f"documents[{index}] 상태가 잘못됐습니다")
        if not isinstance(document["version"], str) or not document["version"].strip():
            raise ExperimentError("invalid_review_inputs", f"documents[{index}].version이 필요합니다")
        if not isinstance(document["source_path"], str) or not document["source_path"].strip():
            raise ExperimentError("invalid_review_inputs", f"documents[{index}].source_path가 필요합니다")
        allowed = document["execution_allowed"]
        if not isinstance(allowed, bool) or (allowed and status != "approved"):
            raise ExperimentError("invalid_review_inputs", "실행 허용 문서는 approved 상태여야 합니다")
        expected_hash = document["sha256"]
        if not is_sha256(expected_hash):
            raise ExperimentError("invalid_review_inputs", f"documents[{index}].sha256이 잘못됐습니다")

        path_value = document["path"]
        if path_value in indexed:
            raise ExperimentError("invalid_review_inputs", "document path가 중복됐습니다")
        path = _resolve_document(root, path_value)
        if sha256_file(path) != expected_hash:
            raise ExperimentError("hash_mismatch", f"검토 입력 SHA-256이 다릅니다: {path.name}")
        if kind == "company_capabilities":
            load_capabilities(path, require_approved=status == "approved")
        else:
            try:
                prompt = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise ExperimentError("review_input_unavailable", "prompt를 읽을 수 없습니다") from exc
            if not prompt.strip() or "\x00" in prompt:
                raise ExperimentError("invalid_review_inputs", "prompt가 비었거나 잘못됐습니다")
        indexed[path_value] = document

    active_capabilities = manifest["active_company_capabilities"]
    active_prompt = manifest["active_prompt"]
    for path_value, expected_kind in (
        (active_capabilities, "company_capabilities"),
        (active_prompt, "prompt"),
    ):
        active = indexed.get(path_value)
        if (
            active is None
            or active["kind"] != expected_kind
            or active["status"] != "approved"
            or active["execution_allowed"] is not True
        ):
            raise ExperimentError("active_review_input_invalid", "active 검토 입력이 승인·실행 허용 상태가 아닙니다")

    return {
        "schema_version": MANIFEST_SCHEMA,
        "document_count": len(documents),
        "active_company_capabilities": active_capabilities,
        "active_company_capabilities_sha256": indexed[active_capabilities]["sha256"],
        "active_prompt": active_prompt,
        "active_prompt_sha256": indexed[active_prompt]["sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "review-inputs",
    )
    args = parser.parse_args()
    try:
        result = validate_review_inputs(args.root)
    except ExperimentError as exc:
        print(f"error[{exc.code}]: {exc}")
        return 2
    print(
        "review_inputs=valid "
        f"documents={result['document_count']} "
        f"capabilities_sha256={result['active_company_capabilities_sha256']} "
        f"prompt_sha256={result['active_prompt_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
