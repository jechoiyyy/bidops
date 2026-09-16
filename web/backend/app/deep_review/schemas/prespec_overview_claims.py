"""Strict contracts for the two-stage, claim-verified overview.

Empty evidence/claim/reference arrays remain parseable so the deterministic gate
can classify them as factual failures, never requests to regenerate facts.
"""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...core.schema_base import Digest

CLAIMS_SCHEMA = "bidops.prespec-overview-claims.v1"
#: 검증을 통과한 개요 결과의 계약 식별자. 개요를 앞부분 요약 세 절로 좁히면서
#: 폐기된 `bidops.prespec-overview-page-review.v4`를 대신한다 (ADR-0057 결정 1).
RESULT_SCHEMA = "bidops.prespec-overview-claims.v2"
CHECKS_SCHEMA = "bidops.prespec-overview-claim-checks.v1"
SEMANTIC_SCHEMA = "bidops.prespec-overview-semantic.v1"
VALIDATOR_VERSION = "prespec-claim-evidence.v2"
#: 개요가 읽는 절. 참여 조건·검토 의견·미확인은 심층 검토의 일이다 (ADR-0057).
FACT_SECTIONS = ("business_overview", "main_tasks", "budget_and_period")
MAX_CLAIMS = 12
MAX_TEXT_CHARS = 300
MAX_QUOTE_CHARS = 300
MAX_EVIDENCE = 2
MAX_QUANTITIES = 4

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")]
BoundedText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS)]
PageNumber = Annotated[int, Field(strict=True, ge=1)]
Section = Literal["business_overview", "main_tasks", "budget_and_period"]
SemanticStatus = Literal["supported", "contradicted", "insufficient", "not_run"]
SemanticReason = Literal[
    "quantity_mismatch", "role_mismatch", "negation_mismatch", "condition_mismatch",
    "business_nature_mismatch", "obligation_strengthened", "unsupported_fact",
    "company_capability_unverified", "unknown_contradicted", "prompt_injection",
    "insufficient_evidence", "analysis_premise_unverified", "company_comparison_scope_mismatch",
]
DeterministicReason = Literal[
    "required_fact_missing", "duplicate_id", "fact_empty", "evidence_missing",
    "page_out_of_range", "quote_not_found", "quote_ambiguous", "quote_empty",
    "quantity_mismatch", "quantity_metadata_mismatch", "quantity_relation_ambiguous",
    "quantity_unit_missing", "requirement_id_mismatch", "date_mismatch",
    "latin_term_mismatch", "input_limit_exceeded",
    "fact_structure_missing", "fact_schema_invalid", "output_limit_exceeded", "duplicate_json_key",
]


class StrictClaimModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ClaimEvidence(StrictClaimModel):
    page: PageNumber
    quote: Annotated[str, Field(min_length=1, max_length=MAX_QUOTE_CHARS)]


class Quantity(StrictClaimModel):
    subject: Annotated[str, Field(min_length=1, max_length=100)]
    role: Literal["budget", "contract_amount", "period", "count", "percentage"]
    value_decimal: Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")]
    unit: Literal["원", "천원", "만원", "백만원", "천만원", "억원", "개월", "년", "일", "주", "명", "개", "건", "식", "%"]
    currency: Literal["KRW"] | None
    vat: Literal["included", "excluded"] | None
    period_basis: Literal["contract_date", "start_date", "delivery_date"] | None
    evidence_index: Annotated[int, Field(strict=True, ge=0, lt=MAX_EVIDENCE)]


class OverviewClaim(StrictClaimModel):
    id: Identifier
    section: Section
    text: BoundedText
    evidence: Annotated[list[ClaimEvidence], Field(max_length=MAX_EVIDENCE)]
    quantities: Annotated[list[Quantity], Field(max_length=MAX_QUANTITIES)]


class OverviewClaimsDraft(StrictClaimModel):
    """앞부분 요약 주장만. 검토 의견(`analysis`)과 미확인(`unknowns`)은
    개요 계약에서 빠졌고 심층 검토가 소유한다 (ADR-0057 결정 1)."""

    schema_version: Literal["bidops.prespec-overview-claims.v1"]
    claims: Annotated[list[OverviewClaim], Field(max_length=MAX_CLAIMS)]


class VerifiedEvidence(StrictClaimModel):
    page: PageNumber
    # Whitespace-equivalent matching retains the larger ORIGINAL slice.
    quote: Annotated[str, Field(min_length=1, max_length=2000)]
    start_char: Annotated[int, Field(strict=True, ge=0)]
    end_char: Annotated[int, Field(strict=True, ge=1)]
    page_text_sha256: Digest

    @model_validator(mode="after")
    def check_span(self):
        if self.end_char - self.start_char != len(self.quote):
            raise ValueError("evidence_span_invalid")
        return self


class DeterministicCheck(StrictClaimModel):
    status: Literal["passed", "failed"]
    reason_codes: list[DeterministicReason]
    verified_evidence: list[VerifiedEvidence]

    @model_validator(mode="after")
    def check_status(self):
        if (self.status == "passed") != (not self.reason_codes):
            raise ValueError("deterministic_status_invalid")
        return self


class SemanticCheck(StrictClaimModel):
    status: SemanticStatus
    reason_codes: list[SemanticReason]

    @model_validator(mode="after")
    def check_status(self):
        if self.status == "supported" and self.reason_codes:
            raise ValueError("semantic_status_invalid")
        if self.status in {"contradicted", "insufficient"} and not self.reason_codes:
            raise ValueError("semantic_reason_required")
        return self


class ClaimCheck(StrictClaimModel):
    claim_id: Identifier
    section: Section
    text: BoundedText
    deterministic: DeterministicCheck
    semantic: SemanticCheck
    #: 대조는 어긋났지만 인용 자체는 성립하는 비차단 관찰(수치·날짜·ID·라틴
    #: 용어·analysis 전제). 사람이 원문과 함께 확인할 값이며 `deterministic`을
    #: 실패로 만들지 않는다.
    warnings: list[str] = Field(default_factory=list)


# 모델이 돌려주는 의미 검토 행은 저장 행과 **다른 계약**이다. `warnings`는
# 서버가 결정적으로 만든 값이므로 모델 응답 schema에 넣지 않는다.
class SemanticClaimCheck(SemanticCheck):
    claim_id: Identifier
    status: Literal["supported", "contradicted", "insufficient"]


class OverviewSemanticResponse(StrictClaimModel):
    schema_version: Literal["bidops.prespec-overview-semantic.v1"]
    checks: Annotated[list[SemanticClaimCheck], Field(max_length=MAX_CLAIMS)]


class OverviewClaimChecks(StrictClaimModel):
    schema_version: Literal["bidops.prespec-overview-claim-checks.v1"]
    attempt_id: UUID
    draft_sha256: Digest
    input_sha256: Digest
    policy_digest: Digest
    binding_digest: Digest
    validator_version: Literal["prespec-claim-evidence.v2"]
    checks: list[ClaimCheck]
    # Whole-draft failures (e.g. a missing required section) cannot vanish when
    # there is no individual claim to attach them to.
    reason_codes: list[DeterministicReason]
    #: 검사 전체의 비차단 관찰. 행별 `warnings`의 합집합과 draft 전체 관찰을
    #: 함께 담으며 `overall`을 바꾸지 않는다.
    warnings: list[str] = Field(default_factory=list)
    overall: Literal["passed", "needs_human_review"]

    @model_validator(mode="after")
    def passed_requires_every_check(self):
        ids = [c.claim_id for c in self.checks]
        if self.overall == "passed" and (
            len(set(ids)) != len(ids) or
            # 섹션 배정 쏠림은 2026-09-11부터 경고다. 주장이 한 개도 없는
            # 것만 통과를 막는다(`passed`는 이미 `bool(self.checks)`를 본다).
            any(not c.deterministic.verified_evidence for c in self.checks)
        ):
            raise ValueError("verification_coverage_invalid")
        passed = bool(self.checks) and not self.reason_codes and all(
            c.deterministic.status == "passed" and c.semantic.status == "supported"
            for c in self.checks
        )
        if (self.overall == "passed") != passed:
            raise ValueError("verification_overall_invalid")
        return self


#: 검증을 통과한 개요 결과 payload. 결정적 검증기가 만들고 읽는 유일한 결과
#: 계약이며, REST 응답 모양은 P2가 따로 정한다.
Text = Annotated[str, Field(min_length=1)]


class VerifiedPageFact(StrictClaimModel):
    claim_id: Identifier
    text: BoundedText
    evidence: Annotated[list[VerifiedEvidence], Field(min_length=1)]


class OverviewResultPayload(StrictClaimModel):
    """앞부분 요약 세 절. `important_conditions`·`reviewer_analysis`·`unknowns`
    key는 **존재하지 않는다** — 빈 배열로 남기지 않는다 (ADR-0057 결정 1)."""

    schema_version: Literal["bidops.prespec-overview-claims.v2"]
    # 섹션별 최소 1개는 요구하지 않는다. 모델이 한 섹션에 몰아 넣은 것은
    # 경고(`required_fact_missing`)로 남고 개요는 그대로 만든다. 선택 범위에
    # 예산·기간이 없어 빈 절은 run 경고 `section_empty:<section>`이다.
    business_overview: list[VerifiedPageFact]
    main_tasks: list[VerifiedPageFact]
    budget_and_period: list[VerifiedPageFact]
    input_limitations: Annotated[list[Text], Field(min_length=1)]
    verification_id: UUID
    verification_sha256: Digest

    @model_validator(mode="after")
    def require_unique_claims(self):
        facts = self.business_overview + self.main_tasks + self.budget_and_period
        ids = [fact.claim_id for fact in facts]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_id")
        return self


def parse_overview_result_payload(value: object) -> OverviewResultPayload:
    """검증된 결과 하나만 읽는다. 폐기된 v3·v4 판은 더 이상 받지 않는다."""

    import json

    if isinstance(value, OverviewResultPayload):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        raise ValueError("overview_schema_invalid")
    if value.get("schema_version") != RESULT_SCHEMA:
        raise ValueError("overview_schema_unsupported")
    # JSON validation permits the UUID wire encoding while retaining strict
    # integers, strings and unknown-field rejection in nested evidence.
    return OverviewResultPayload.model_validate_json(json.dumps(value, ensure_ascii=False))
