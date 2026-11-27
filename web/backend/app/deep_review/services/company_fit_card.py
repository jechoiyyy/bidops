"""사업 범위 카드(PS-01 C1): 로드·구조 검사·sha 고정·모델 입력 투영.

카드는 git 밖의 YAML 파일 하나다(회사 자료이고 원격 저장소는 공개다). 이 모듈은
설정 경로의 파일을 읽어 구조를 검사하고, 파일 bytes의 SHA-256을 설정값과 대조한 뒤
측정 실행기(`docs/validation-runs/20261127-company-fit-probe/fit_probe.py`
`card_facts`)와 **같은 규칙**으로 회사 근거 `company_facts`를 만든다.

* 실패 코드는 둘뿐이다. 경로가 비었거나 읽을 수 없거나 구조를 어기면
  ``card_unavailable``, 설정 sha가 64자 소문자 hex가 아니거나 파일 sha와 다르면
  ``card_sha256_mismatch``다(C4의 평가 순서 4 → 5).
* 화면 표시 이름 ``company_fact_labels``는 모델에 보내지 않는다. policy에는 이름
  필드가 없고 ``kind``가 겹치므로(``exclude``가 둘) ``POLICY_LABELS``를 쓴다.
* 카드의 그 밖의 키(``company``·``basis``·``questions``·``level`` 등)는 읽지만
  투영하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from ...core.model_client import sanitize_for_prompt

CARD_SCHEMA_PREFIX = "bidops.business-scope-card."
CARD_VERSION_MAX = 64
CARD_UNAVAILABLE = "card_unavailable"
CARD_SHA256_MISMATCH = "card_sha256_mismatch"

#: policy id → 화면 이름. 표에 없는 id는 id 문자열 그대로 쓴다.
POLICY_LABELS: Mapping[str, str] = {
    "policy:no-bid": "수행하지 않는 사업",
    "policy:caution": "확인이 필요한 사업",
    "policy:onsite": "상주 조건",
    "policy:mixed-scope": "섞인 사업 판단",
}

#: 투영하는 선택 필드. 순서는 측정 실행기 ``card_facts``와 같다.
SCOPE_VALUE_KEYS = ("summary", "includes", "boundary", "keywords", "examples")
POLICY_VALUE_KEYS = ("summary", "items", "rules")

_HEX64 = re.compile(r"[0-9a-f]{64}")


class BusinessScopeCardError(ValueError):
    """카드를 쓸 수 없다. ``code``는 C4 사유 코드 하나다."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BusinessScopeCard:
    card_version: str
    card_sha256: str
    company_facts: list[dict[str, Any]] = field(default_factory=list)
    company_fact_labels: dict[str, str] = field(default_factory=dict)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _entries(card: Mapping[str, Any], key: str, prefix: str, label_key: str) -> list[Mapping[str, Any]]:
    rows = card.get(key)
    if not isinstance(rows, list) or not rows:
        raise BusinessScopeCardError(CARD_UNAVAILABLE)
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise BusinessScopeCardError(CARD_UNAVAILABLE)
        ref = row.get("id")
        if not isinstance(ref, str) or not ref.startswith(prefix) or ref in seen:
            raise BusinessScopeCardError(CARD_UNAVAILABLE)
        if not _text(row.get(label_key)) or not _text(row.get("summary")):
            raise BusinessScopeCardError(CARD_UNAVAILABLE)
        seen.add(ref)
    return rows


def card_projection(card: Any) -> tuple[str, list[dict[str, Any]], dict[str, str]]:
    """구조를 검사하고 ``(card_version, company_facts, company_fact_labels)``를 돌려준다."""

    if not isinstance(card, Mapping):
        raise BusinessScopeCardError(CARD_UNAVAILABLE)
    version = card.get("schema_version")
    if (
        not isinstance(version, str)
        or not version.startswith(CARD_SCHEMA_PREFIX)
        or len(version) > CARD_VERSION_MAX
    ):
        raise BusinessScopeCardError(CARD_UNAVAILABLE)
    scopes = _entries(card, "scopes", "scope:", "name")
    policies = _entries(card, "policies", "policy:", "kind")
    if {row["id"] for row in scopes} & {row["id"] for row in policies}:
        raise BusinessScopeCardError(CARD_UNAVAILABLE)
    # fit_probe.card_facts와 같은 식이다(값의 truthiness로 선택 필드를 고른다).
    facts: list[dict[str, Any]] = []
    for sc in scopes:
        facts.append({"ref": sc["id"], "fact_key": sc["name"], "status": "confirmed",
                      "value": {k: sc[k] for k in SCOPE_VALUE_KEYS if sc.get(k)}})
    for po in policies:
        facts.append({"ref": po["id"], "fact_key": po["kind"], "status": "confirmed",
                      "value": {k: po[k] for k in POLICY_VALUE_KEYS if po.get(k)}})
    try:
        # YAML 날짜·집합 같은 JSON 밖 값은 모델 입력이 될 수 없다.
        json.dumps(facts, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise BusinessScopeCardError(CARD_UNAVAILABLE) from None
    if sanitize_for_prompt(facts) != facts:
        raise BusinessScopeCardError(CARD_UNAVAILABLE)
    labels = {sc["id"]: sc["name"] for sc in scopes}
    labels.update({po["id"]: POLICY_LABELS.get(po["id"], po["id"]) for po in policies})
    return version, facts, labels


def load_business_scope_card(settings: Any) -> BusinessScopeCard:
    """설정 경로의 카드를 읽는다. 실패는 ``BusinessScopeCardError`` 하나다.

    평가 순서는 C4와 같다: 경로·읽기·구조(``card_unavailable``) → sha
    (``card_sha256_mismatch``). sha가 어긋나면 읽은 내용을 돌려주지 않는다.
    """

    path = str(getattr(settings, "prespec_company_fit_card_path", "") or "").strip()
    if not path:
        raise BusinessScopeCardError(CARD_UNAVAILABLE)
    try:
        raw = Path(path).read_bytes()
        parsed = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        raise BusinessScopeCardError(CARD_UNAVAILABLE) from None
    version, facts, labels = card_projection(parsed)
    actual = hashlib.sha256(raw).hexdigest()
    expected = str(getattr(settings, "prespec_company_fit_card_sha256", "") or "")
    if not _HEX64.fullmatch(expected) or expected != actual:
        raise BusinessScopeCardError(CARD_SHA256_MISMATCH)
    return BusinessScopeCard(card_version=version, card_sha256=actual,
                             company_facts=facts, company_fact_labels=labels)


def card_or_reason(settings: Any) -> tuple[BusinessScopeCard | None, str | None]:
    """``(카드, None)`` 또는 ``(None, 사유 코드)``."""

    try:
        return load_business_scope_card(settings), None
    except BusinessScopeCardError as error:
        return None, error.code


__all__ = [
    "BusinessScopeCard",
    "BusinessScopeCardError",
    "CARD_SHA256_MISMATCH",
    "CARD_UNAVAILABLE",
    "POLICY_LABELS",
    "card_or_reason",
    "card_projection",
    "load_business_scope_card",
]
