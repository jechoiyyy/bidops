"""Read-only v7 policy and bounded stage payloads; never calls a model."""
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from ...core.model_client import APPROVED_GENERATION, StructuredOutputContract, build_prompt
from ..schemas.prespec_overview_claims import (
    OverviewClaimChecks, OverviewClaimsDraft, OverviewSemanticResponse, VALIDATOR_VERSION,
)

CLAIMS_STAGE = "prespec_overview_claims"
SEMANTIC_STAGE = "prespec_overview_semantic"
POLICY_PATH = Path(__file__).resolve().parents[1] / "policies" / "prespec-overview-policy-v7.json"
LIMITS = {
    "max_calls": 3, "max_draft_calls": 2, "max_semantic_calls": 1,
    "timeout_seconds": 300, "lease_seconds": 1200, "dispatch_reserve_seconds": 360,
    "max_prompt_chars": 120000, "max_page_text_chars": 100000, "max_pages": 60,
    # 상한 판정은 요청 JSON의 **byte 수**를 token 상계로 쓴다. 한국어는
    # 글자당 3 byte이므로 v6의 100,000자 쪽 텍스트를 담으려면 이 천장도
    # 함께 올라가야 한다 — 그러지 않으면 허용 입력이 호출 전에 막힌다.
    "max_model_context_tokens": 393216,
    "chat_template_reserve_tokens": 1024,
    "max_draft_chars": 10000, "max_response_chars": 16000,
    "max_claims": 12,
    "max_text_chars": 300, "max_evidence_per_claim": 2, "max_quote_chars": 300,
    "max_quantities_per_claim": 4,
}
FORMAT_RETRY_CODES = frozenset({
    "json_invalid", "top_level_invalid", "field_type_invalid", "required_field_missing", "extra_field_forbidden",
})


def canonical_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ClaimsOverviewPolicy:
    document: dict[str, Any]
    digest: str

    def structured_output_contract(
        self, stage: str, *, expected_check_count: int | None = None,
    ) -> StructuredOutputContract:
        """이 run이 보낼 구조화 출력 계약.

        `expected_check_count`를 주면 의미 단계의 `checks` 길이를 그 run의 실제
        주장 수로 못박는다. 정책 파일의 `max_claims`(12)는 그대로 상한 검증에만
        쓰이고 **파일은 바뀌지 않는다** — `stage_policy`가 `deepcopy`를 돌려주고
        digest는 `self.document`에서만 계산하므로 policy digest에 영향이 없다.
        """

        policy = self.stage_policy(stage)
        schema = policy["output_schema"]
        if expected_check_count is not None:
            if stage != SEMANTIC_STAGE:
                raise ValueError("overview_stage_invalid")
            if not 1 <= expected_check_count <= LIMITS["max_claims"]:
                raise ValueError("expected_check_count_invalid")
            schema["properties"]["checks"]["minItems"] = expected_check_count
            schema["properties"]["checks"]["maxItems"] = expected_check_count
        return StructuredOutputContract(name=stage, schema=schema, system_prompt=policy["system_prompt"])

    def stage_policy(self, stage: str) -> dict[str, Any]:
        if canonical_sha256(self.document) != self.digest:
            raise ValueError("overview_policy_invalid")
        row = next((r for r in self.document["stages"] if r["stage"] == stage), None)
        if row is None:
            raise ValueError("overview_stage_invalid")
        return deepcopy({
            "schema": self.document["schema"], "model_name": self.document["model_name"],
            "model_endpoint_ref": self.document["model_endpoint_ref"],
            "prompt_version": self.document["prompt_version"],
            **{k: row[k] for k in ("generation", "chunking", "system_prompt", "output_schema", "prompt_output_contract")},
            "stages": [{"stage": stage, "instruction": row["instruction"]}],
        })


def load_claims_policy(path: Path | None = None) -> ClaimsOverviewPolicy:
    try:
        value = json.loads((path or POLICY_PATH).read_text(encoding="utf-8"))
        if set(value) != {"schema", "model_name", "model_endpoint_ref", "prompt_version", "limits", "verification", "stages"}:
            raise ValueError
        if (value["schema"], value["model_name"], value["model_endpoint_ref"], value["prompt_version"]) != (
            "bidops.prespec-overview-policy.v7", "qwen3.8-27B", "vllm-openai-compatible", "prespec-overview-v7",
        ) or value["limits"] != LIMITS:
            raise ValueError
        # The set order is immaterial to validation but the original file order
        # still participates in the immutable policy digest.
        check = dict(value["verification"])
        check["format_retry_codes"] = sorted(check["format_retry_codes"])
        if check != {
            "validator_version": VALIDATOR_VERSION, "format_retry_codes": sorted(FORMAT_RETRY_CODES),
            "factual_failure_action": "needs_human_review", "semantic_response_failure": "semantic_response_invalid",
            "transport_retries": 0,
        }:
            raise ValueError
        stages = value["stages"]
        if [r["stage"] for r in stages] != [CLAIMS_STAGE, SEMANTIC_STAGE]:
            raise ValueError
        for row, model in zip(stages, (OverviewClaimsDraft, OverviewSemanticResponse), strict=True):
            if set(row) != {"stage", "generation", "chunking", "system_prompt", "instruction", "prompt_output_contract", "output_schema"}:
                raise ValueError
            if row["generation"] != APPROVED_GENERATION or row["chunking"] != {"retries": 0, "timeout_seconds": 300}:
                raise ValueError
            if row["output_schema"] != model.model_json_schema():
                raise ValueError
            if not row["system_prompt"].strip() or not row["instruction"].strip() or not isinstance(row["prompt_output_contract"], dict):
                raise ValueError
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("overview_policy_invalid") from None
    return ClaimsOverviewPolicy(value, canonical_sha256(value))


def build_claims_stage_input(
    pages: dict[int, str], *, draft: OverviewClaimsDraft | None = None,
    checks: OverviewClaimChecks | None = None, company_comparison_performed: bool = False,
) -> dict[str, Any]:
    if (not pages or len(pages) > LIMITS["max_pages"] or
        any(type(n) is not int or n < 1 or not isinstance(t, str) for n, t in pages.items()) or
        sum(len(t) for t in pages.values()) > LIMITS["max_page_text_chars"]):
        raise ValueError("input_limit_exceeded")
    result: dict[str, Any] = {
        "schema_version": "bidops.prespec-overview-claims-input.v1",
        "blocks": [{"pdf_page": n, "text": pages[n]} for n in sorted(pages)],
        "company_comparison_performed": company_comparison_performed,
    }
    if draft is not None:
        if len(canonical_json(draft)) > LIMITS["max_draft_chars"]:
            raise ValueError("input_limit_exceeded")
        if checks is None or checks.draft_sha256 != canonical_sha256(draft) or checks.reason_codes or any(
            row.deterministic.status != "passed" for row in checks.checks
        ):
            raise ValueError("deterministic_checks_required")
        if sorted(row.claim_id for row in checks.checks) != sorted(row.id for row in draft.claims) or not checks.checks:
            raise ValueError("deterministic_checks_required")
        for row in checks.checks:
            for evidence in row.deterministic.verified_evidence:
                page = pages.get(evidence.page)
                if page is None or hashlib.sha256(page.encode("utf-8")).hexdigest() != evidence.page_text_sha256 or page[evidence.start_char:evidence.end_char] != evidence.quote:
                    raise ValueError("verified_input_mismatch")
        result["draft"] = draft.model_dump(mode="json")
        # 기대 ID와 개수를 입력에 명시한다. 응답 schema의 `checks` 길이도 이
        # 값으로 못박으므로 모델이 상한(12)을 채우려고 분석·미확인 ID를 지어
        # 넣을 자리가 없다 (ADR-0057 결정 3).
        result["expected_claim_ids"] = [claim.id for claim in draft.claims]
        result["expected_check_count"] = len(draft.claims)
        result["verified_evidence"] = [
            {"claim_id": row.claim_id, "evidence": [e.model_dump(mode="json") for e in row.deterministic.verified_evidence]}
            for row in checks.checks
        ]
    elif checks is not None:
        raise ValueError("draft_required")
    return result


def build_claims_prompt(policy: ClaimsOverviewPolicy, stage: str, input_slice: dict[str, Any]) -> str:
    """Same core builder the client uses, bounded by the policy prompt cap."""
    return build_prompt(stage, input_slice, policy.stage_policy(stage), max_chars=LIMITS["max_prompt_chars"])
