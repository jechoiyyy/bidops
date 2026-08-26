"""Deterministic, non-production analysis provider for workflow acceptance tests.

The mock implements the same bounded ``invoke`` boundary as the vLLM and
Codex adapters.  It never calls a model or network service.  Its output is
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

from .vllm_client import InvocationResult, build_prompt


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


__all__ = ["MAX_MOCK_ROWS", "MOCK_MODEL_NAME", "MockAnalysisClient"]
