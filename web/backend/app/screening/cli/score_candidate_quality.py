"""Score a fixed, human-reviewed candidate quality manifest without activation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from ..services.candidate_quality import CandidateQualityError, CandidateQualityManifest, score_candidate_quality


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.screening.cli score-candidate-quality",
        description="Score human-reviewed Qwen candidate quality evidence",
    )
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



__all__ = ["build_parser", "main"]


if __name__ == "__main__":  # pragma: no cover
    # T8 2단계가 이 파일의 직접 실행 경로를 없앴다. 호환 shim을 두지 않으므로
    # 옛 명령은 동작하지 않는다. 다만 그냥 두면 `__main__` 블록이 없는 모듈이
    # 아무 일도 하지 않고 종료 코드 0을 내서, 옛 기록을 따라 실행한 운영자가
    # 성공으로 오인한다. mutating 명령이 조용히 건너뛰지 않도록 fail-closed로 막는다.
    raise SystemExit("이 명령은 `python -m app.screening.cli score-candidate-quality <인자>`로 실행한다")
