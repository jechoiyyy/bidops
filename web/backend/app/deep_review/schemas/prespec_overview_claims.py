"""Strict contracts for the two-stage, claim-verified overview.

Empty evidence/claim/reference arrays remain parseable so the deterministic gate
can classify them as factual failures, never requests to regenerate facts.
"""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...core.schema_base import Digest

CLAIMS_SCHEMA = "bidops.prespec-overview-claims.v1"
CHECKS_SCHEMA = "bidops.prespec-overview-claim-checks.v1"
SEMANTIC_SCHEMA = "bidops.prespec-overview-semantic.v1"
VALIDATOR_VERSION = "prespec-claim-evidence.v2"
FACT_SECTIONS = ("business_overview", "main_tasks", "budget_and_period", "important_conditions")
MAX_CLAIMS = 12
MAX_ANALYSIS = 4
MAX_UNKNOWNS = 6
MAX_TEXT_CHARS = 300
MAX_QUOTE_CHARS = 300
MAX_EVIDENCE = 2
MAX_QUANTITIES = 4

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")]
BoundedText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS)]
PageNumber = Annotated[int, Field(strict=True, ge=1)]
Section = Literal["business_overview", "main_tasks", "budget_and_period", "important_conditions"]
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
    "latin_term_mismatch", "analysis_reference_missing", "analysis_premise_unverified",
    "company_comparison_scope_mismatch", "unknown_reason_mismatch", "input_limit_exceeded",
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


class OverviewAnalysis(StrictClaimModel):
    id: Identifier
    text: BoundedText
    supporting_claim_ids: Annotated[list[Identifier], Field(max_length=MAX_CLAIMS)]


class OverviewUnknown(StrictClaimModel):
    id: Identifier
    topic: Literal["budget", "period", "eligibility", "scope", "schedule", "company_comparison"]
    reason_code: Literal["not_in_reviewed_input", "ambiguous_source", "company_comparison_not_performed"]


class OverviewClaimsDraft(StrictClaimModel):
    schema_version: Literal["bidops.prespec-overview-claims.v1"]
    claims: Annotated[list[OverviewClaim], Field(max_length=MAX_CLAIMS)]
    analysis: Annotated[list[OverviewAnalysis], Field(max_length=MAX_ANALYSIS)]
    unknowns: Annotated[list[OverviewUnknown], Field(max_length=MAX_UNKNOWNS)]


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


class AnalysisCheck(SemanticCheck):
    analysis_id: Identifier
    warnings: list[str] = Field(default_factory=list)


class UnknownCheck(SemanticCheck):
    unknown_id: Identifier
    warnings: list[str] = Field(default_factory=list)


# 모델이 돌려주는 의미 검토 행은 저장 행과 **다른 계약**이다. `warnings`는
# 서버가 결정적으로 만든 값이므로 모델 응답 schema에 넣지 않는다.
class SemanticClaimCheck(SemanticCheck):
    claim_id: Identifier
    status: Literal["supported", "contradicted", "insufficient"]


class SemanticAnalysisCheck(SemanticCheck):
    analysis_id: Identifier
    status: Literal["supported", "contradicted", "insufficient"]


class SemanticUnknownCheck(SemanticCheck):
    unknown_id: Identifier
    status: Literal["supported", "contradicted", "insufficient"]


class OverviewSemanticResponse(StrictClaimModel):
    schema_version: Literal["bidops.prespec-overview-semantic.v1"]
    checks: Annotated[list[SemanticClaimCheck], Field(max_length=MAX_CLAIMS)]
    analysis_checks: Annotated[list[SemanticAnalysisCheck], Field(max_length=MAX_ANALYSIS)]
    unknown_checks: Annotated[list[SemanticUnknownCheck], Field(max_length=MAX_UNKNOWNS)]

class OverviewClaimChecks(StrictClaimModel):
    schema_version: Literal["bidops.prespec-overview-claim-checks.v1"]
    attempt_id: UUID
    draft_sha256: Digest
    input_sha256: Digest
    policy_digest: Digest
    binding_digest: Digest
    validator_version: Literal["prespec-claim-evidence.v2"]
    checks: list[ClaimCheck]
    analysis_checks: list[AnalysisCheck]
    unknown_checks: list[UnknownCheck]
    analysis: list[OverviewAnalysis]
    unknowns: list[OverviewUnknown]
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
        analysis_ids = [a.id for a in self.analysis]
        unknown_ids = [u.id for u in self.unknowns]
        all_ids = ids + analysis_ids + unknown_ids
        if self.overall == "passed" and (
            len(set(all_ids)) != len(all_ids) or
            sorted(c.analysis_id for c in self.analysis_checks) != sorted(analysis_ids) or
            sorted(c.unknown_id for c in self.unknown_checks) != sorted(unknown_ids) or
            any(not a.supporting_claim_ids or set(a.supporting_claim_ids) - set(ids) for a in self.analysis) or
            # 섹션 배정 쏠림은 2026-09-11부터 경고다. 주장이 한 개도 없는
            # 것만 통과를 막는다(`passed`는 이미 `bool(self.checks)`를 본다).
            any(not c.deterministic.verified_evidence for c in self.checks)
        ):
            raise ValueError("verification_coverage_invalid")
        # 미확인 항목(unknown)의 contradicted/insufficient는 2026-09-11부터
        # 통과를 막지 않는다. 그 unknown만 결과에서 빠지고 run은 경고
        # `unknown_contradicted`/`unknown_insufficient`를 남긴다.
        passed = bool(self.checks) and not self.reason_codes and all(
            c.deterministic.status == "passed" and c.semantic.status == "supported"
            for c in self.checks
        ) and all(c.status == "supported" for c in self.analysis_checks)
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


class PageOverviewPayloadV4(StrictClaimModel):
    schema_version: Literal["bidops.prespec-overview-page-review.v4"]
    # 섹션별 최소 1개는 요구하지 않는다. 모델이 한 섹션에 몰아 넣은 것은
    # 경고(`required_fact_missing`)로 남고 개요는 그대로 만든다.
    business_overview: list[VerifiedPageFact]
    main_tasks: list[VerifiedPageFact]
    budget_and_period: list[VerifiedPageFact]
    important_conditions: list[VerifiedPageFact]
    reviewer_analysis: list[OverviewAnalysis]
    unknowns: list[Text]
    input_limitations: Annotated[list[Text], Field(min_length=1)]
    verification_id: UUID
    verification_sha256: Digest

    @model_validator(mode="after")
    def require_unique_claims(self):
        facts = self.business_overview + self.main_tasks + self.budget_and_period + self.important_conditions
        ids = [fact.claim_id for fact in facts]
        analysis_ids = [row.id for row in self.reviewer_analysis]
        if len(set(ids + analysis_ids)) != len(ids + analysis_ids):
            raise ValueError("duplicate_id")
        if any(not a.supporting_claim_ids or set(a.supporting_claim_ids) - set(ids) for a in self.reviewer_analysis):
            raise ValueError("analysis_reference_missing")
        return self


def parse_page_overview_payload(value: object) -> PageOverviewPayloadV4:
    """검증된 v4 결과 하나만 읽는다. 폐기된 v3는 더 이상 받지 않는다."""

    import json

    if isinstance(value, PageOverviewPayloadV4):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        raise ValueError("overview_schema_invalid")
    if value.get("schema_version") != "bidops.prespec-overview-page-review.v4":
        raise ValueError("overview_schema_unsupported")
    # JSON validation permits the UUID wire encoding while retaining strict
    # integers, strings and unknown-field rejection in nested evidence.
    return PageOverviewPayloadV4.model_validate_json(json.dumps(value, ensure_ascii=False))
