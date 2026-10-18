"""Deterministic, non-production analysis provider for workflow acceptance tests.

The mock implements the same bounded ``invoke`` boundary as the vLLM
adapter.  It never calls a model or network service.  Its output is
deliberately simple: exact source quotes become supported facts, while stage 3
adds one fixed recommendation.  The normal authoritative validator, report
materializer, persistence, and audit paths remain unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
import hashlib
import json
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ...core.model_client import InvocationResult, build_prompt


MOCK_MODEL_NAME = "bidops-deterministic-mock-v1"
MAX_MOCK_ROWS = 8


def _stable_uuid(input_slice: Mapping[str, Any], kind: str, key: str) -> str:
    scope = ":".join((
        str(input_slice.get("deep_review_id", "")),
        str(input_slice.get("attempt_id", "")),
        str(input_slice.get("stage", "")),
        str(input_slice.get("slice_index", 0)),
        kind,
        key,
    ))
    return str(uuid5(NAMESPACE_URL, f"bidops.mock:{scope}"))


def _exact_quote(value: Any, *, limit: int = 512) -> str | None:
    """Choose a bounded substring that cannot span joined source blocks."""

    if not isinstance(value, str):
        return None
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return None
    return max(lines, key=len)[:limit]


def _category(text: str, *, fallback: str) -> str:
    folded = text.casefold()
    if any(token in folded for token in ("자격", "qualification", "입찰참가")):
        return "eligibility"
    if any(token in folded for token in ("평가", "배점", "evaluation")):
        return "evaluation"
    if any(token in folded for token in ("산출물", "제출", "deliverable")):
        return "scope_deliverables"
    if any(token in folded for token in ("보안", "계약", "법률", "security")):
        return "security_legal_contract_risks"
    return fallback


def _document_fact(input_slice: Mapping[str, Any], requirement: Mapping[str, Any], index: int, *, stage: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    quote = _exact_quote(requirement.get("text"))
    document_id = requirement.get("document_version_id")
    structure_id = requirement.get("structure_id")
    source_sha256 = requirement.get("source_sha256")
    page = requirement.get("page")
    if not quote or not all(isinstance(value, str) and value for value in (document_id, structure_id, source_sha256)) or not isinstance(page, int):
        return None
    requirement_id = str(requirement.get("requirement_id") or index)
    evidence_id = _stable_uuid(input_slice, "document-evidence", requirement_id)
    claim_id = _stable_uuid(input_slice, "document-claim", requirement_id)
    evidence = {
        "evidence_id": evidence_id,
        "source_kind": "document",
        "document_version_id": document_id,
        "structure_id": structure_id,
        "profile_version_id": None,
        "profile_evidence_id": None,
        "locator_type": "page",
        "locator": {"page": page},
        "quote": quote,
        "confidence": None,
        "source_sha256": source_sha256,
    }
    fallback = "requirements" if stage == "requirements_and_evaluation" else "delivery_risk"
    claim = {
        "claim_id": claim_id,
        "category": _category(quote, fallback=fallback),
        "claim_type": "fact",
        "body": f"문서 근거 확인: {quote[:300]}",
        "status": "supported",
        "formula": None,
        "premise_claim_ids": [],
        "reason": None,
        "evidence_ids": [evidence_id],
    }
    return claim, evidence


def _profile_fact(input_slice: Mapping[str, Any], evidence: Mapping[str, Any], index: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    profile_evidence_id = evidence.get("profile_evidence_id")
    profile_version_id = evidence.get("profile_version_id")
    fact_key = evidence.get("fact_key")
    quote = evidence.get("quote")
    source_sha256 = evidence.get("source_sha256")
    if not all(isinstance(value, str) and value for value in (profile_evidence_id, profile_version_id, fact_key, quote, source_sha256)):
        return None
    evidence_id = _stable_uuid(input_slice, "profile-evidence", f"{fact_key}:{index}")
    claim_id = _stable_uuid(input_slice, "profile-claim", f"{fact_key}:{index}")
    output_evidence = {
        "evidence_id": evidence_id,
        "source_kind": "profile",
        "document_version_id": None,
        "structure_id": None,
        "profile_version_id": profile_version_id,
        "profile_evidence_id": profile_evidence_id,
        "locator_type": "profile_fact",
        "locator": {"fact_key": fact_key},
        "quote": quote,
        "confidence": None,
        "source_sha256": source_sha256,
    }
    claim = {
        "claim_id": claim_id,
        "category": "delivery_company_capability",
        "claim_type": "fact",
        "body": f"회사 프로필 근거 확인: {quote[:300]}",
        "status": "supported",
        "formula": None,
        "premise_claim_ids": [],
        "reason": None,
        "evidence_ids": [evidence_id],
    }
    return claim, output_evidence


class MockAnalysisClient:
    """Generate schema-valid fixtures without performing model inference."""

    provider_name = "mock-analysis"
    model = MOCK_MODEL_NAME

    def invoke(
        self,
        stage: str,
        input_slice: Mapping[str, Any],
        policy: Mapping[str, Any],
        *,
        profile: Mapping[str, Any] | None = None,
        prior_stages: Sequence[Mapping[str, Any]] = (),
    ) -> InvocationResult:
        prompt = build_prompt(stage, input_slice, policy, profile=profile, prior_stages=prior_stages)
        claims: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        unknowns: list[str] = []

        if stage in {"requirements_and_evaluation", "delivery_risk_economics"}:
            requirements = input_slice.get("requirements", [])
            if isinstance(requirements, list):
                for index, row in enumerate(requirements[:MAX_MOCK_ROWS]):
                    result = _document_fact(input_slice, row, index, stage=stage) if isinstance(row, Mapping) else None
                    if result is not None:
                        claim, evidence_row = result
                        claims.append(claim)
                        evidence.append(evidence_row)

        if stage == "delivery_risk_economics" and len(claims) < MAX_MOCK_ROWS:
            profile_rows = input_slice.get("profile_evidence", [])
            if isinstance(profile_rows, list):
                for index, row in enumerate(profile_rows):
                    if len(claims) >= MAX_MOCK_ROWS:
                        break
                    result = _profile_fact(input_slice, row, index) if isinstance(row, Mapping) else None
                    if result is not None:
                        claim, evidence_row = result
                        claims.append(claim)
                        evidence.append(evidence_row)

        if stage == "synthesis_and_validation" and int(input_slice.get("slice_index", 0)) == 0:
            claims.append({
                "claim_id": _stable_uuid(input_slice, "recommendation", "conditional"),
                "category": "system_recommendation",
                "claim_type": "opinion",
                "body": "조건부 추진 검토",
                "status": "supported",
                "formula": None,
                "premise_claim_ids": [],
                "reason": "Mock 워크플로우 검증을 위한 고정 권고이며 실제 사업 판단이 아닙니다.",
                "evidence_ids": [],
            })

        if not claims:
            claims.append({
                "claim_id": _stable_uuid(input_slice, "unknown", "empty-slice"),
                "category": "analysis",
                "claim_type": "unknown",
                "body": "Mock 입력 slice에서 직접 확인 가능한 항목이 없습니다.",
                "status": "unknown",
                "formula": None,
                "premise_claim_ids": [],
                "reason": "직접 인용 가능한 문서 또는 프로필 근거가 없습니다.",
                "evidence_ids": [],
            })
            unknowns.append("Mock 입력 slice에 직접 인용 가능한 근거가 없습니다.")

        output = {
            "schema": "bidops.deep-review-stage.v1",
            "deep_review_id": input_slice["deep_review_id"],
            "attempt_id": input_slice["attempt_id"],
            "stage": stage,
            "claims": claims,
            "evidence": evidence,
            "unknowns": unknowns,
            "warnings": ["Mock 분석 결과이며 실제 모델 품질 평가에 사용할 수 없습니다."],
        }
        raw = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return InvocationResult(
            structured_output=output,
            raw_response=raw,
            input_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            output_sha256=hashlib.sha256(raw).hexdigest(),
            prompt_tokens=None,
            output_tokens=None,
            latency_ms=0,
            attempts=({"retry_index": 0, "status": "succeeded", "latency_ms": 0},),
            provider=self.provider_name,
            model=self.model,
        )


class MockOverviewTransport:
    """사전규격 개요 두 단계(draft·semantic)의 결정적 transport (명세 §6.3).

    `ModelClient`의 주입 seam(`completion_create`·`models_list`)만 채운다.
    C-1 판정의 mock transport(ADR-0029)와 같은 자리이며 **네트워크를 열지
    않는다.** 프롬프트 조립·결정적 검증·의미 검토·저장 경로는 실제 실행과 같고,
    이 class는 그 경계 바깥에서 OpenAI 호환 응답 한 벌을 만들 뿐이다.

    주장의 본문은 **동결 입력 쪽의 한 줄을 그대로** 쓴다. 문장을 지어내 원문에
    없는 인용을 만들지 않는다는 뜻이며, 그래서 결정적 검증이 실제 실행과 같은
    규칙으로 통과하거나 실패한다.
    """

    provider_name = "mock-overview"
    #: 주장 하나를 만들 수 있는 줄의 최소 길이. 너무 짧은 줄은 다른 쪽에서도
    #: 나타나 인용이 모호해질 수 있다.
    MIN_QUOTE_CHARS = 8

    def __init__(self, model: str) -> None:
        self.model = model
        self.calls = 0

    def models_list(self) -> dict[str, Any]:
        """`GET /models`의 자리. 서버가 revision을 싣지 않는 stock 모양이다."""

        return {"data": [{"id": self.model}]}

    @staticmethod
    def _unique_lines(blocks: Sequence[Mapping[str, Any]]) -> list[tuple[int, str]]:
        """쪽 안에서 **정확히 한 번** 나타나는 줄만 인용 후보로 남긴다."""

        seen: dict[str, int] = {}
        candidates: list[tuple[int, str]] = []
        for block in blocks:
            page = block.get("pdf_page")
            text = block.get("text")
            if not isinstance(page, int) or not isinstance(text, str):
                continue
            counts: dict[str, int] = {}
            for line in text.splitlines():
                stripped = line.strip()
                if len(stripped) >= MockOverviewTransport.MIN_QUOTE_CHARS:
                    counts[stripped] = counts.get(stripped, 0) + 1
            for line, count in counts.items():
                if count != 1 or line in seen:
                    continue
                seen[line] = page
                candidates.append((page, line))
        return candidates

    def _draft(self, input_slice: Mapping[str, Any]) -> dict[str, Any]:
        blocks = input_slice.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("mock overview prompt carries no block")
        candidates = self._unique_lines(blocks)
        if len(candidates) < 2:
            raise ValueError("mock overview input has no two unique quotes")
        sections = ("business_overview", "main_tasks", "budget_and_period")
        claims = []
        for index, (page, line) in enumerate(candidates[:len(sections)]):
            claims.append({
                "id": f"c{index + 1}",
                "section": sections[index],
                "text": line,
                "evidence": [{"page": page, "quote": line}],
                "quantities": [],
            })
        return {
            "schema_version": "bidops.prespec-overview-claims.v1",
            "claims": claims,
        }

    @staticmethod
    def _semantic(input_slice: Mapping[str, Any]) -> dict[str, Any]:
        draft = input_slice.get("draft")
        if not isinstance(draft, Mapping):
            raise ValueError("mock overview semantic prompt carries no draft")
        supported = {"status": "supported", "reason_codes": []}
        return {
            "schema_version": "bidops.prespec-overview-semantic.v1",
            "checks": [
                {"claim_id": row["id"], **supported} for row in draft.get("claims", [])
            ],
        }

    def completion_create(self, **request: Any) -> dict[str, Any]:
        self.calls += 1
        # 보정 지시는 프롬프트 **뒤에** 붙는 별도 user 메시지다. 마지막 메시지만
        # 보면 재생성 호출에서 입력을 잃으므로 뒤에서부터 JSON 프롬프트를 찾는다.
        input_slice: Any = None
        for message in reversed(request.get("messages") or []):
            content = message.get("content") if isinstance(message, Mapping) else None
            if not isinstance(content, str):
                continue
            try:
                candidate = json.loads(content)
            except ValueError:
                continue
            if isinstance(candidate, Mapping) and isinstance(candidate.get("input_slice"), Mapping):
                input_slice = candidate["input_slice"]
                break
        if input_slice is None:
            raise ValueError("mock overview prompt does not carry an input slice")
        output = (
            self._semantic(input_slice) if input_slice.get("draft") is not None
            else self._draft(input_slice)
        )
        return {
            "model": request.get("model", self.model),
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(output, ensure_ascii=False, sort_keys=True),
                    },
                }
            ],
        }


# --- RL-03 card-v1 mock (결정 B16) -----------------------------------------------------

#: Provider lineage of the mock card path (same value as the narrative mock).
MOCK_CARD_PROVIDER = MockAnalysisClient.provider_name
_CARD_CONTRACTS = {
    "extract": "card-extract-v1",
    "eligibility_economics": "card-role-v1",
    "technical_fit": "card-role-v1",
    "operations_risk": "card-role-v1",
    "synthesis": "card-synthesis-v1",
}
#: 결정 B55: synthesis contracts the mock answers (v1: policies up to v8, v2: v9).
_CARD_SYNTHESIS_CONTRACTS = frozenset({"card-synthesis-v1", "card-synthesis-v2"})
# --- 결정 B35: realistic numeric constraints of the v2 mock answer --------------------
#
# Every match is quoted verbatim as number + unit word + an attached comparator
# (whitespace and one particle 를/을/의 allowed), exactly as the v5 extract
# instruction asks.  결정 B37 (v6): a quote that repeats in its block is extended
# by whole words on the left until it is unique ("월 1회", "연 1회 이상").  A number that continues a range or list (preceded by a
# digit, ``~``/``～``/``〜``, ``-``, ``/``, ``.`` or ``,``) is skipped.

_MOCK_NUMBER = r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?"
_MOCK_COMPARATOR = r"(?:\s*(?:[를을의]\s*)?(?:이상|이하|이내|초과|미만))?"
_MOCK_AMOUNT_MULTIPLIERS = {"억원": 100_000_000, "백만원": 1_000_000, "천원": 1_000, "원": 1}
_MOCK_PATTERNS = (
    ("count", "person", re.compile(rf"({_MOCK_NUMBER})\s*명{_MOCK_COMPARATOR}")),
    ("amount", "KRW", re.compile(rf"({_MOCK_NUMBER})\s*(억원|백만원|천원|원){_MOCK_COMPARATOR}")),
    ("duration", "day", re.compile(rf"({_MOCK_NUMBER})\s*일\s*이상")),
    ("percentage", "percent", re.compile(rf"({_MOCK_NUMBER})\s*%{_MOCK_COMPARATOR}")),
)
_MOCK_RANGE_BEFORE = "0123456789~～〜-/.,"
#: 결정 B37: a repeated quote is extended by whole words on the left (at most
#: ``_MOCK_MAX_LEFT_WORDS``, never over a digit or an opening bracket/colon).
_MOCK_MAX_LEFT_WORDS = 3
_MOCK_WORD_STOP = "([{（「『<〈:：,，"


def _occurrences(quote: str, text: str) -> int:
    count, start = 0, text.find(quote)
    while start >= 0:
        count += 1
        start = text.find(quote, start + 1)
    return count


def _unique_left_extended(text: str, start: int, end: int) -> int | None:
    """Start index of the shortest left-extended quote ``text[start:end]`` that occurs once, or ``None``."""

    for _ in range(_MOCK_MAX_LEFT_WORDS + 1):
        if _occurrences(text[start:end], text) == 1:
            return start
        cursor = start
        while cursor > 0 and text[cursor - 1].isspace():
            cursor -= 1
        word_end = cursor
        while cursor > 0 and not text[cursor - 1].isspace() and text[cursor - 1] not in _MOCK_WORD_STOP:
            cursor -= 1
        if cursor == word_end or any(char.isdigit() for char in text[cursor:word_end]):
            return None
        start = cursor
    return None


def _mock_number(raw: str) -> int | float:
    value = Decimal(raw.replace(",", ""))
    return int(value) if value == value.to_integral_value() else float(value)


def mock_numeric_constraints(unit: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Deterministic v2 numeric constraints of one unit (no operator, ``fact_key`` null)."""

    constraints: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for block in unit.get("blocks") or []:
        text = str(block.get("text") or "")
        for kind, unit_name, pattern in _MOCK_PATTERNS:
            for match in pattern.finditer(text):
                before = text[:match.start()].rstrip()
                if before and before[-1] in _MOCK_RANGE_BEFORE:
                    continue
                start = _unique_left_extended(text, match.start(), match.end())
                if start is None:
                    continue  # no unique quote within three words: no constraint (never a guess)
                quote = text[start:match.end()]
                value = _mock_number(match.group(1))
                if kind == "amount":
                    value = _mock_number(str(Decimal(match.group(1).replace(",", ""))
                                             * _MOCK_AMOUNT_MULTIPLIERS[match.group(2)]))
                key = (kind, quote, str(block["block_key"]))
                if key in seen:
                    continue
                seen.add(key)
                constraints.append({
                    "kind": kind, "value": value, "unit": unit_name, "fact_key": None, "quote": quote,
                    "locator": {"source_sha256": unit["source_sha256"], "block_key": block["block_key"]},
                })
    return constraints


#: 결정 B33: the extract stage answers v1 (policy v1-v3) or v2 (policy v4).
_CARD_EXTRACT_CONTRACTS = frozenset({"card-extract-v1", "card-extract-v2"})
_MOCK_ROLE_REASON = "모의 실행: 결정적 대조 결과를 그대로 옮겼다(모델 판단 아님)"
_MOCK_SYNTHESIS_REASON = "모의 실행 결과이며 모델 판정이 아니다. 연결 확인용으로만 쓴다."


def _mock_requirement_type(unit: Mapping[str, Any]) -> str:
    if unit.get("kind") == "card":
        return "기능"
    sections = unit.get("section_kinds") or []
    if "eligibility" in sections:
        return "자격"
    if "evaluation" in sections:
        return "평가"
    if "contract" in sections:
        return "계약"
    return "운영"


class MockCardAnalysisClient:
    """Deterministic ``invoke_prompt`` stand-in for the RL card-v1 runner (B16).

    Used only when ``BIDOPS_ANALYSIS_PROVIDER=mock`` with reference mode.  It
    performs no runner, model or network call.  Every answer is derived from
    the stage input of the prompt and passes the normal validators unchanged:

    * extract: one item per unit; ``normalized_requirement`` and the single
      evidence quote are the unit's first non-blank block text copied
      verbatim, no constraints (so no number is introduced), concept
      candidates are the unit's ``expected_concepts`` copied as given when the
      payload carries them (``card-sections-v3``, 결정 B30 -- the same
      contract the real model is told to follow), otherwise the
      deterministic ontology matches of the unit blocks.  Under the v2 extract
      contract (``card-extract-v2``, policy v4, 결정 B33) the answer has no
      ``concept_candidates`` and no operators -- the same v2 shape the real
      model returns; code derives both.  It also carries the realistic numeric
      constraints of ``mock_numeric_constraints`` (결정 B35: ``N명``, ``N원``,
      ``N일 이상``, ``N%`` quoted with unit and attached comparator), so the
      quote/unit/operator rules are exercised;
    * roles: each unit's assessment is its deterministic compare result;
    * synthesis: ``판단 불가`` with no blocking ids, cautions or actions; under
      ``card-synthesis-v2`` (policy v9, 결정 B55) the v2 shape without
      ``blocking_condition_ids``.  ``fail_synthesis=True`` makes every synthesis
      call schema-invalid (a failed attempt whose other stages can be resumed).

    ``raw_response`` is empty, so no model response object is stored.
    """

    provider_name = MOCK_CARD_PROVIDER
    model = MOCK_MODEL_NAME

    def __init__(self, ontology: Any, *, fail_synthesis: bool = False) -> None:
        self.ontology = ontology
        self.fail_synthesis = fail_synthesis
        self.calls: list[tuple[str, str]] = []

    def invoke_prompt(self, prompt: str, *, contract: str) -> InvocationResult:
        from ...core.model_client import ModelInvocationError

        envelope = json.loads(prompt)
        stage = envelope.get("stage") if isinstance(envelope, Mapping) else None
        value = envelope.get("input") if isinstance(envelope, Mapping) else None
        allowed = (
            _CARD_EXTRACT_CONTRACTS if stage == "extract"
            else _CARD_SYNTHESIS_CONTRACTS if stage == "synthesis"
            else {_CARD_CONTRACTS.get(stage)}
        )
        if stage not in _CARD_CONTRACTS or contract not in allowed or not isinstance(value, Mapping):
            raise ModelInvocationError("schema_invalid", (), b"")
        self.calls.append((contract, str(stage)))
        if stage == "extract":
            output = self._extract(value, v2=contract == "card-extract-v2")
        elif stage == "synthesis":
            if self.fail_synthesis:
                # 결정 B55: a deterministic synthesis failure (schema-invalid every time,
                # so the single repair also fails) to leave a resumable failed attempt.
                raise ModelInvocationError("schema_invalid", (), b"")
            if contract == "card-synthesis-v2":
                # 결정 B55 (policy v9): no blocking ids -- code computes them.
                output = {
                    "schema_version": "bidops.practitioner-verdict.v2", "verdict": "판단 불가",
                    "reason": _MOCK_SYNTHESIS_REASON, "cautions": [], "next_actions": [],
                }
            else:
                output = {
                    "schema_version": "bidops.practitioner-verdict.v1", "verdict": "판단 불가",
                    "reason": _MOCK_SYNTHESIS_REASON, "blocking_condition_ids": [], "cautions": [],
                    "next_actions": [],
                }
        else:
            output = self._role(value)
        encoded = json.dumps(output, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return InvocationResult(
            output,
            b"",
            hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            hashlib.sha256(encoded).hexdigest(),
            None,
            None,
            0,
            (),
            self.provider_name,
            self.model,
        )

    def _extract(self, value: Mapping[str, Any], *, v2: bool = False) -> dict[str, Any]:
        from ...core.model_client import ModelInvocationError
        from .company_knowledge_retrieval import match_concepts

        items = []
        for unit in value.get("units") or []:
            blocks = [block for block in unit.get("blocks") or [] if str(block.get("text") or "").strip()]
            if not blocks:
                raise ModelInvocationError("schema_invalid", (), b"")
            candidates: list[dict[str, Any]] = []
            if "expected_concepts" in unit:
                expected = unit["expected_concepts"]
                if not isinstance(expected, list):
                    raise ModelInvocationError("schema_invalid", (), b"")
                candidates = [
                    {"concept_id": row["concept_id"], "alias_text": row["alias_text"]} for row in expected
                ]
            else:
                seen: set[tuple[str, str]] = set()
                for block in blocks:
                    for concept_id in match_concepts(block["text"], self.ontology):
                        if (concept_id, block["text"]) not in seen:
                            seen.add((concept_id, block["text"]))
                            candidates.append({"concept_id": concept_id, "alias_text": block["text"]})
            first = blocks[0]
            item = {
                "unit_id": unit["unit_id"], "type": _mock_requirement_type(unit),
                "normalized_requirement": first["text"], "mandatory": None, "constraints": [],
                "concept_candidates": candidates, "unknowns": [],
                "evidence": [{"source_sha256": unit["source_sha256"], "block_key": first["block_key"],
                              "quote": first["text"]}],
            }
            if v2:
                item.pop("concept_candidates")
                item["constraints"] = mock_numeric_constraints(unit)
            items.append(item)
        version = "bidops.requirement-extract.v2" if v2 else "bidops.requirement-extract.v1"
        return {"schema_version": version, "items": items}

    @staticmethod
    def _role(value: Mapping[str, Any]) -> dict[str, Any]:
        fits = {row["unit_id"]: row["fit_status"] for row in value["compare"]["items"]}
        return {
            "schema_version": "bidops.verdict-role.v1", "role": value["role"],
            "unit_findings": [
                {"unit_id": row["unit_id"], "assessment": fits[row["unit_id"]], "reason": _MOCK_ROLE_REASON,
                 "evidence_refs": row["evidence"]}
                for row in value["extract"]["items"]
            ],
            "cautions": [], "evidence_refs": [],
        }


__all__ = [
    "MAX_MOCK_ROWS",
    "MOCK_CARD_PROVIDER",
    "MOCK_MODEL_NAME",
    "MockAnalysisClient",
    "MockCardAnalysisClient",
    "mock_numeric_constraints",
    "MockOverviewTransport",
]
