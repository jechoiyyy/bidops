"""Deterministic ``proposal-section-v1`` stand-in for the reference-mode mock path (RL-04 T10/T11 mock).

Used only when ``BIDOPS_ANALYSIS_PROVIDER=mock`` with reference mode.  No runner,
model or network call is made and nothing is transmitted (no transfer audit;
``quality_status=mock_reference``).  Every answer is built from the transfer
payload inside the prompt and passes ``validate_proposal_section`` unchanged:

* one paragraph per input unit (heading = the unit's normalized id), holding one
  ``statement`` whose single ``requirement_unit`` source quotes the unit's first
  non-blank block text verbatim and whole (so the quote is unique and never cuts
  a number); ``requirement_links`` link every unit to its paragraph, so the
  ``requirements`` section covers every card unit;
* one paragraph for the confirmed ``company_facts`` (a ``company_fact`` source
  quoting the fact label verbatim) and, for ``overview``, the notice title;
* a ``placeholder`` for every ``missing_facts`` entry (the hint names the fact
  key only, never a value) and one section placeholder (가격, 투입 인력 수, ...);
* sentence texts are fixed Korean sentences without digits, so no forbidden
  amount/staffing/schedule pattern can occur.

``raw_response`` is empty, so no model response object is stored.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ...core.model_client import InvocationResult, ModelInvocationError
from .mock_analysis_client import MOCK_CARD_PROVIDER, MOCK_MODEL_NAME

CONTRACT = "proposal-section-v1"
_TITLES = {
    "overview": "제안 개요",
    "track_record": "사업수행 실적",
    "strategy": "수행 전략",
    "requirements": "요구사항 수행방안",
    "operations_sla": "운영·SLA",
    "organization": "수행조직",
}
_SECTION_PLACEHOLDER = {
    "overview": "가격",
    "track_record": "실적증명서 발급 건 목록",
    "strategy": "전략 수치",
    "requirements": "가격",
    "operations_sla": "성능 목표 수치",
    "organization": "투입 인력 수",
}
_UNIT_TEXT = "이 요구사항의 원문 조건에 맞추어 수행 방안을 제시한다."
_FACT_TEXT = "확인된 회사 사실을 이 절의 근거로 제시한다."
_TITLE_TEXT = "공고명에 드러난 사업의 목적과 범위를 정리한다."
_MISSING_TEXT = "확인되지 않은 회사 정보는 사람이 채운다."
_PLACEHOLDER_TEXT = "사람이 정할 값은 빈 자리로 남긴다."


class MockProposalClient:
    provider_name = MOCK_CARD_PROVIDER
    model = MOCK_MODEL_NAME

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke_prompt(self, prompt: str, *, contract: str = CONTRACT) -> InvocationResult:
        try:
            envelope = json.loads(prompt)
        except ValueError:
            raise ModelInvocationError("schema_invalid", (), b"") from None
        value = envelope.get("input") if isinstance(envelope, Mapping) else None
        if contract != CONTRACT or not isinstance(value, Mapping) or value.get("section_key") not in _TITLES:
            raise ModelInvocationError("schema_invalid", (), b"")
        output = mock_section(value)
        self.calls.append(str(value["section_key"]))
        encoded = json.dumps(output, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return InvocationResult(
            output, b"", hashlib.sha256(prompt.encode("utf-8")).hexdigest(), hashlib.sha256(encoded).hexdigest(),
            None, None, 0, (), self.provider_name, self.model,
        )

    def close(self) -> None:  # parity with LunaClient
        return None


def mock_section(value: Mapping[str, Any]) -> dict[str, Any]:
    """The deterministic Section of one transfer payload (see module docstring)."""

    section_key = str(value["section_key"])
    counter = [0]

    def sentence(text: str, kind: str, sources: list[dict[str, str]], hint: str | None = None) -> dict[str, Any]:
        counter[0] += 1
        return {
            "sentence_id": str(uuid5(NAMESPACE_URL, f"bidops:mock-proposal:{section_key}:{counter[0]}")),
            "text": text, "kind": kind, "sources": sources, "placeholder_hint": hint,
        }

    paragraphs: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []
    for unit in value.get("units") or []:
        paragraph_id = f"p{len(paragraphs) + 1}"
        texts = [str(block.get("text") or "") for block in unit.get("blocks") or []]
        quote = next((text for text in texts if text.strip()), None)
        if quote is None:
            sentences = [sentence(_PLACEHOLDER_TEXT, "placeholder", [], "원문 확인")]
        else:
            sentences = [sentence(_UNIT_TEXT, "statement",
                                  [{"kind": "requirement_unit", "ref": str(unit["unit_id"]), "quote": quote}])]
        paragraphs.append({"paragraph_id": paragraph_id, "heading": unit.get("normalized_id") or None,
                           "sentences": sentences})
        links.append({"unit_id": str(unit["unit_id"]), "paragraph_id": paragraph_id})
    meta = value.get("notice_meta") or {}
    fact_sentences: list[dict[str, Any]] = []
    if section_key == "overview" and isinstance(meta.get("title"), str) and meta["title"].strip():
        fact_sentences.append(sentence(_TITLE_TEXT, "statement",
                                       [{"kind": "notice_meta", "ref": "title", "quote": meta["title"]}]))
    for fact in value.get("company_facts") or []:
        label = fact.get("label")
        if isinstance(label, str) and label.strip():
            fact_sentences.append(sentence(_FACT_TEXT, "statement",
                                           [{"kind": "company_fact", "ref": str(fact["fact_key"]), "quote": label}]))
    for missing in value.get("missing_facts") or []:
        fact_sentences.append(sentence(_MISSING_TEXT, "placeholder", [], f"{missing['fact_key']} 확인"))
    fact_sentences.append(sentence(_PLACEHOLDER_TEXT, "placeholder", [], _SECTION_PLACEHOLDER[section_key]))
    paragraphs.append({"paragraph_id": f"p{len(paragraphs) + 1}", "heading": None, "sentences": fact_sentences})
    return {"section_key": section_key, "title": _TITLES[section_key], "paragraphs": paragraphs,
            "requirement_links": links}


__all__ = ["CONTRACT", "MockProposalClient", "mock_section"]
