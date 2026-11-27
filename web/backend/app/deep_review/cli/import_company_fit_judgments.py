"""``import-company-fit-judgments``: Claude 참조 판정을 카드 lineage 행으로 넣는다 (PS-01 MVP 5).

``python -m app.deep_review.cli import-company-fit-judgments --file <json> --actor <name>
[--dry-run]``은 JSON 한 줄 ``{file_sha256, card_sha256, imported[], skipped[], errors[]}``을
출력한다.

입력 파일은 ``{"judged_by":"claude_reference","card_sha256":…,"rows":[{"notice_id":int,
"result":<bidops.prespec-company-fit-result.v1>}]}``이다. 공고마다 현재 DB 기준으로 카드
동결 입력을 만들고(``model_name=claude-reference-judgment``, ``model_revision`` = 묶음
파일 sha256), 결과를 결정적 검증기로 통과시킨 뒤 ``completed`` 행으로 넣는다. 개요 입력이
없거나 검증에 실패한 공고, 이미 있는 입력은 건너뛴다(사유를 ``skipped``에 남긴다).

**worker** DB 역할로 실행한다(attempt INSERT·종결 UPDATE는 worker 권한이다). 모델은 부르지
않는다. 종료 코드: 0 전부 처리 또는 건너뜀, 2 입력·카드 거부(``input_invalid``·
``actor_invalid``·``card_unavailable``·``card_sha256_mismatch``, stderr에 코드 한 줄),
1 내부 오류(``storage_failed``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from ...core.db import SessionLocal, init_db
from ..services.company_fit_import import (
    CompanyFitImportError,
    import_company_fit_judgments,
    parse_judgment_bundle,
)


def _emit(payload: dict[str, Any], *, error_code: str | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if error_code is not None:
        print(error_code, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.deep_review.cli import-company-fit-judgments")
    parser.add_argument("--file", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    empty = {"file_sha256": None, "card_sha256": None, "imported": [], "skipped": [], "errors": []}
    try:
        try:
            raw = Path(args.file).read_bytes()
        except OSError:
            raise CompanyFitImportError("input_invalid") from None
        payload, file_sha256 = parse_judgment_bundle(raw)
        init_db()
        with SessionLocal() as session:
            try:
                result = import_company_fit_judgments(
                    session, payload, file_sha256=file_sha256, actor=args.actor, dry_run=args.dry_run,
                )
            except BaseException:
                session.rollback()
                raise
        _emit({**result.as_dict(), "errors": []})
        return 0
    except CompanyFitImportError as error:
        _emit({**empty, "errors": [error.code]}, error_code=error.code)
        return 2
    except Exception:  # keep internal paths, SQL, and model details outside the CLI
        _emit({**empty, "errors": ["storage_failed"]}, error_code="storage_failed")
        return 1


__all__ = ["build_parser", "main"]
