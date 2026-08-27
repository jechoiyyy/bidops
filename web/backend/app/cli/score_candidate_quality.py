"""Score a fixed, human-reviewed candidate quality manifest without activation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from ..services.candidate_quality import CandidateQualityError, CandidateQualityManifest, score_candidate_quality


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score human-reviewed Qwen candidate quality evidence")
    parser.add_argument("manifest", type=Path, help="UTF-8 bidops.qwen-quality-evaluation.v1 JSON")
    return parser


def _load_manifest(path: Path) -> CandidateQualityManifest:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise CandidateQualityError("manifest must be an absolute regular non-symlink file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CandidateQualityError("candidate quality manifest cannot be read") from error
    try:
        return CandidateQualityManifest.model_validate(payload)
    except ValidationError as error:
        raise CandidateQualityError("candidate quality manifest is invalid") from error


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = score_candidate_quality(_load_manifest(args.manifest))
    except CandidateQualityError as error:
        print(json.dumps({"error": {"code": "invalid_quality_manifest", "message": str(error)}}, ensure_ascii=False, sort_keys=True))
        return 2
    output = result.model_dump(mode="json", by_alias=True)
    output["policy_import_arguments"] = result.policy_import_arguments()
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result.passed else 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
