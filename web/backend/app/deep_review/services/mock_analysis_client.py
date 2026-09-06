"""Deterministic, non-production analysis provider for workflow acceptance tests.

The mock implements the same bounded ``invoke`` boundary as the vLLM
adapter.  It never calls a model or network service.  Its output is
deliberately simple: exact source quotes become supported facts, while stage 3
adds one fixed recommendation.  The normal authoritative validator, report
materializer, persistence, and audit paths remain unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
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
    """사전규격 개요 판정의 결정적 transport (명세 §6.3).

    `ModelClient`의 주입 seam(`completion_create`·`models_list`)만 채운다.
    C-1 판정의 mock transport(ADR-0029)와 같은 자리이며 **네트워크를 열지
    않는다.** 모델 client·prompt 조립·검증·저장 경로는 실제 실행과 같고, 이
    class는 그 경계 바깥에서 OpenAI 호환 응답 한 벌을 만들 뿐이다.

    응답의 근거 locator는 프롬프트가 실은 block 중 **첫 block**을 가리킨다.
    문장을 지어내 원문에 없는 위치를 만들지 않는다는 뜻이며, 그래서 결정적
    검증이 실제 실행과 같은 규칙으로 통과하거나 실패한다.
    """

    provider_name = "mock-overview"

    def __init__(self, model: str) -> None:
        self.model = model
        self.calls = 0

    def models_list(self) -> dict[str, Any]:
        """`GET /models`의 자리. 서버가 revision을 싣지 않는 stock 모양이다."""

        return {"data": [{"id": self.model}]}

    def completion_create(self, **request: Any) -> dict[str, Any]:
        self.calls += 1
        messages = request.get("messages") or []
        prompt = messages[-1].get("content") if messages else None
        if not isinstance(prompt, str):
            raise ValueError("mock overview request has no prompt")
        try:
            blocks = json.loads(prompt)["input_slice"]["blocks"]
        except (TypeError, KeyError, ValueError) as error:
            raise ValueError("mock overview prompt does not carry an input slice") from error
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("mock overview prompt carries no block")
        first = blocks[0]
        output = {
            "schema_version": "bidops.prespec-overview-result.v1",
            "recommendation": "추진 검토",
            "summary": "모의 개요 결과이며 실제 사업 판단이나 승인 근거가 아닙니다.",
            "conditions": [],
            "verification_due_at": None,
            "unknowns": [],
            "evidence": [
                {
                    "claim": "모의 개요 근거 자리표시자이며 실제 원문 판단이 아닙니다.",
                    "locator": {
                        "block_key": first.get("block_key"),
                        "page": first.get("page"),
                        "ordinal": first.get("ordinal"),
                    },
                }
            ],
            "input_limitations": ["모의 실행이며 사업개요 범위만 확인했습니다."],
        }
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


__all__ = [
    "MAX_MOCK_ROWS",
    "MOCK_MODEL_NAME",
    "MockAnalysisClient",
    "MockOverviewTransport",
]
