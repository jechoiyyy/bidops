"""결정적 검증 실패에 한 번만 다시 부르는 규칙과 그 감사 기록.

철거된 v4 runner가 갖고 있던 것을 그대로 옮겼다. 회사 핏 실행기와 P2의 개요
실행기가 같은 규칙을 두 벌 만들지 않도록 여기 한 벌만 둔다. 모델을 부르지
않고 DB를 보지 않는다 — 코드·digest·seed만 다룬다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

#: 검증 실패 한 건에 허용하는 재시도 횟수.
VALIDATION_RETRY_LIMIT = 1
#: 재시도 호출이 쓰는 기준 seed. 승인 기본값(0)으로 같은 프롬프트를 다시
#: 보내면 결정적으로 같은 실패가 돌아온다.
VALIDATION_RETRY_SEED = 1
#: 같은 입력을 다시 보낼 가치가 있는 모델 실패 코드. timeout·provider·신원·
#: 프롬프트 상한 실패는 응답 내용의 문제가 아니므로 포함하지 않는다.
VALIDATION_RETRY_INVOCATION_CODES = frozenset({"malformed_json", "truncated_json"})
#: 실패한 검사 코드만 채워 넣는 고정 문장. 원문·응답 본문을 담지 않으므로
#: digest만 감사에 남긴다.
CORRECTION_TEMPLATE = (
    "이전 응답은 다음 검증에 실패했다: {codes}. 같은 입력으로 output_contract의 JSON schema에 맞는 객체 하나만 다시 출력한다."
    " 원문에 없는 숫자·영문 용어·페이지 번호를 추가하지 않고, 사고 과정이나 설명 문장을 JSON 밖에 쓰지 않는다."
)


def build_correction(codes: Sequence[str]) -> str:
    """실패 코드만 치환한 보정 지시."""

    return CORRECTION_TEMPLATE.format(codes=", ".join(sorted({str(code) for code in codes if code})))


def validation_retry_metadata(codes: Sequence[str], correction: str, first_raw_sha256: str | None) -> dict[str, Any]:
    """감사에 남기는 재시도 사실. 코드·digest·seed뿐이며 본문은 없다."""

    return {
        "count": VALIDATION_RETRY_LIMIT,
        "first_error_codes": [str(code) for code in codes],
        "first_raw_response_sha256": first_raw_sha256,
        "seed": VALIDATION_RETRY_SEED,
        "correction_sha256": hashlib.sha256(correction.encode("utf-8")).hexdigest(),
    }


__all__ = [
    "CORRECTION_TEMPLATE",
    "VALIDATION_RETRY_INVOCATION_CODES",
    "VALIDATION_RETRY_LIMIT",
    "VALIDATION_RETRY_SEED",
    "build_correction",
    "validation_retry_metadata",
]
