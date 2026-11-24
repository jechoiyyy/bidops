"""RFP 사실 스키마(Evidence, RfpFacts, RfpFactsPartial)와 Evidence 순회(spec M2-01),
게이트·점수 결과 스키마(GateResult, ScoreEstimate — spec M2-03),
적합도·리스크·권고·분석 결과 스키마(spec M2-04).

필드 선언 순서가 JSON 키 순서다. 기본값 규칙(계약 시트 13절 X9):
- 모든 `X | None` 스칼라는 `= None`, 모든 리스트는 `Field(default_factory=list)`
  (`RuleParams`의 `list[...] | None`은 `= None`), 하위 모델·RfpFacts 최상위 객체 필드는
  `Field(default_factory=<그 모델>)`. 그래서 `RfpFacts()`는 인자 없이 만들어진다.
- 필수(기본값 없음): `Evidence.quote`와 단일 `Evidence` 필드, `| None`이 아닌 스칼라.

LLM 출력 모델 규칙(X7): 이 모듈의 모델은 `messages.parse` 출력 모델로 쓰이므로 pydantic
Field 제약(min/max 길이·값, pattern)을 두지 않는다. 인용 길이(`QUOTE_MAX_CHARS`) 등 검증은
코드(M2-02 evidence.verify)가 한다. M2-04의 LLM 출력 모델(`RequirementFitOut`, `MatchOut`,
`SynthOut`과 그 하위 `Risk`·`ChecklistItem`·`DataToConfirm`·`Profitability`)도 같다. 제약이
필요한 저장 모델(`RequirementFit`, `Recommendation`)은 LLM 출력 모델과 분리해 후처리에서 변환한다.
"""

import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_serializer, model_validator

from bid_deep_engine.analysis.workunits import WorkUnitSummary

# company.knowledge는 bid_deep_engine.analysis를 import하지 않는다(순환 없음, KB-01 import 규칙)
from bid_deep_engine.company.knowledge import KnowledgeSelection
from bid_deep_engine.ingest.models import REQUIREMENT_BASE_ID_PATTERN

QUOTE_MAX_CHARS = 200  # 인용 최대 길이(제약 1). 모델이 아니라 M2-02 verify가 검사한다.

# enum(spec "enum" 값 집합 전체). 모듈 수준 별칭.
AgencyType = Literal["중앙행정", "지자체", "교육기관", "공공기관", "민간", "기타"]
EligibilityCode = Literal[
    "G2B_REGISTERED",
    "INDUSTRY_CODE",
    "SW_BUSINESS_REPORT",
    "SME_CERT",
    "DIRECT_PRODUCTION",
    "LARGE_CORP_EXCLUDED",
    "MUTUAL_INVEST_GROUP_EXCLUDED",
    "REGION_LIMIT",
    "DEBARMENT",
    "TAX_DELINQUENCY",
    "PAST_PERFORMANCE",
    "REQUIRED_CERT",
    "OTHER",
]
EvalKind = Literal["CREDIT_RATING", "PAST_PERFORMANCE", "CERT_COUNT", "STAFF_TRAINING", "OTHER"]
Grade = Literal["초급", "중급", "고급", "특급"]
ConsortiumType = Literal["공동이행", "분담이행", "주계약자", "혼합"]
QualifyingBasis = Literal["points", "percent"]  # Evaluation.qualifying_basis
# 게이트 코드(M2-03·GT-01, 17개): EligibilityCode 13개 + 계약조건 파생 2개(STAFFING_CAPACITY,
# ONSITE_LOCATION) + 재분류 2개(CONSORTIUM_CONDITION, INSOLVENCY — OTHER 조항을 gates.py 키워드
# 규칙으로 재분류한 코드. extract 프롬프트 코드 목록·EligibilityCode에는 없다, X76).
GateCode = Literal[
    "G2B_REGISTERED",
    "INDUSTRY_CODE",
    "SW_BUSINESS_REPORT",
    "SME_CERT",
    "DIRECT_PRODUCTION",
    "LARGE_CORP_EXCLUDED",
    "MUTUAL_INVEST_GROUP_EXCLUDED",
    "REGION_LIMIT",
    "DEBARMENT",
    "TAX_DELINQUENCY",
    "PAST_PERFORMANCE",
    "REQUIRED_CERT",
    "OTHER",
    "STAFFING_CAPACITY",
    "ONSITE_LOCATION",
    "CONSORTIUM_CONDITION",
    "INSOLVENCY",
]
Verdict = Literal["PASS", "FAIL", "UNKNOWN", "RISK"]
# M2-04: 적합도·리스크·권고 enum.
Fit = Literal["FULL", "PARTIAL", "GAP", "UNKNOWN"]
RiskCategory = Literal["인력", "계약", "기술", "일정", "재무", "보안", "지역"]
Severity = Literal["H", "M", "L"]
DecisionValue = Literal["GO", "CONDITIONAL_GO", "NO_GO"]  # 결정 값 단일 출처(X24)
# PF-01: 잠정 결론을 바꾸는 조건의 종류. 표시·정렬 순서는 CONDITION_KIND_ORDER(고정)다.
ConditionKind = Literal[
    "recheck_fail",
    "risk_gate",
    "unknown_gate",
    "requirements_missing",
    "fit_coverage",
    "pdf_numeric",
    "stale_analysis",
]
CONDITION_KIND_ORDER: tuple[ConditionKind, ...] = (
    "recheck_fail",
    "risk_gate",
    "unknown_gate",
    "requirements_missing",
    "fit_coverage",
    "pdf_numeric",
    "stale_analysis",
)
ProvisionalBasis = Literal["confirmed", "assumed"]
StrategyName = Literal["single", "mapreduce"]  # 전략 이름 단일 출처(X54)
LocationStatus = Literal["exact", "ambiguous", "unavailable"]
Stage = Literal["facts", "gates", "scores", "fits", "synth", "requests", "recommendation"]
StageState = Literal["current", "stale", "unknown", "missing"]
ReasonCode = Literal[
    "legacy_metadata",
    "stale_stage",
    "missing_stage",
    "empty_requirements",
    "missing_fits",
    "unknown_gate",
    "untrusted_company_input",
    "uncertain_fit_decision",
    "untrusted_failure",
    "confirmation_outdated",
    "hard_gate_fail",
    "min_contract_fail",
]
REASON_CODE_ORDER: tuple[ReasonCode, ...] = (
    "legacy_metadata",
    "stale_stage",
    "missing_stage",
    "empty_requirements",
    "missing_fits",
    "unknown_gate",
    "untrusted_company_input",
    "uncertain_fit_decision",
    "untrusted_failure",
    "confirmation_outdated",
    "hard_gate_fail",
    "min_contract_fail",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _relative_source_path(value: str) -> str:
    """Bundle 안의 POSIX 상대경로만 허용한다(경로를 고치거나 추측하지 않는다)."""
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or re.match(r"^[A-Za-z]:/", value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or PurePosixPath(value).is_absolute()
    ):
        raise ValueError("file must be a bundle-relative POSIX path")
    return value


class SourceLocation(BaseModel):
    """현재 캐시 원문의 파일별 물리 페이지와 NFC Unicode 구간 ``[start,end)``."""

    file: str
    file_sha256: str
    page: int
    start: int
    end: int

    @field_validator("file")
    @classmethod
    def _file_is_relative(cls, value: str) -> str:
        return _relative_source_path(value)

    @field_validator("file_sha256")
    @classmethod
    def _sha256_is_lower_hex(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("file_sha256 must be 64 lowercase hex characters")
        return value

    @field_validator("page", "start", "end", mode="before")
    @classmethod
    def _integer_offsets(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("page/start/end must be integers")
        return value

    @model_validator(mode="after")
    def _valid_span(self) -> "SourceLocation":
        if self.page < 1:
            raise ValueError("page must be >= 1")
        if self.start < 0:
            raise ValueError("start must be >= 0")
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class SourceBlockLocation(BaseModel):
    """NFC 문자 구간 [start, end)과 정규화 전 원문 블록 번호."""

    file: str
    file_sha256: str
    block_idx: int = Field(strict=True)
    start: int = Field(strict=True)
    end: int = Field(strict=True)

    @field_validator("file")
    @classmethod
    def _file_is_relative(cls, value: str) -> str:
        return _relative_source_path(value)

    @field_validator("file_sha256")
    @classmethod
    def _sha256_is_lower_hex(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("file_sha256 must be 64 lowercase hex characters")
        return value

    @model_validator(mode="after")
    def _valid_span(self) -> "SourceBlockLocation":
        if self.block_idx < 0 or self.start < 0:
            raise ValueError("block_idx and start must be >= 0")
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class Evidence(BaseModel):
    quote: str  # 원문 그대로, ≤ QUOTE_MAX_CHARS — 길이는 코드에서 검증
    section_id: str | None = None  # LLM 입력 표지의 S번호("S012"). 모르면 null
    page: int | None = None  # 확인된 물리 쪽. 이전 산출물에는 섹션 시작 쪽일 수 있다.
    verified: bool | None = None  # 코드가 채움(M2-02). LLM은 null
    repaired: bool | None = None  # 코드가 채움(M2-02): 근사 일치로 원문 구간 교정. LLM은 null
    # LLM 출력의 일부가 아니라 verify 뒤 현재 ingest 캐시 resolver가 덮어쓰는 코드 소유 metadata다.
    # mapreduce merge guard에는 각 Evidence 경로별 명시 규칙으로 등록한다.
    locations: list[SourceLocation] = Field(default_factory=list)
    location_status: LocationStatus = "unavailable"
    block_locations: list[SourceBlockLocation] = Field(default_factory=list)
    block_location_status: LocationStatus = "unavailable"

    @model_validator(mode="after")
    def _location_count_matches_status(self) -> "Evidence":
        expected: LocationStatus = (
            "unavailable"
            if not self.locations
            else "exact"
            if len(self.locations) == 1
            else "ambiguous"
        )
        if self.location_status != expected:
            raise ValueError(
                f"location_status must be {expected} for {len(self.locations)} locations"
            )
        count = len(self.block_locations)
        block_status = "unavailable" if count == 0 else "exact" if count == 1 else "ambiguous"
        if self.block_location_status != block_status:
            raise ValueError(f"block_location_status must be {block_status} for {count} locations")
        return self


class Period(BaseModel):
    start: str | None = None
    end: str | None = None
    days: int | None = None
    months: int | None = None
    note: str | None = None


class Project(BaseModel):
    name: str | None = None  # 구간 추출에서 지어내지 않게 선택(X9). 리포트는 rfp.json title로 대체
    agency: str | None = None
    agency_type: AgencyType | None = None
    budget_krw: int | None = None
    budget_note: str | None = None
    vat_included: bool | None = None
    is_fixed_price: bool | None = None
    period: Period = Field(default_factory=Period)
    contract_method: str | None = None
    bidding_method: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class Schedule(BaseModel):
    # 가능하면 "YYYY-MM-DD" 또는 "YYYY-MM-DD HH:MM". 형식 검증은 하지 않는다(소비자가 파싱).
    notice_date: str | None = None
    briefing: str | None = None
    qna_deadline: str | None = None
    submission_deadline: str | None = None
    eval_date: str | None = None
    kickoff: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class RuleParams(BaseModel):
    item_no: list[str] | None = None
    industry_code: list[str] | None = None
    region: list[str] | None = None
    years: int | None = None
    amount_krw: int | None = None
    keyword: str | None = None
    cert_name: str | None = None


class EligibilityRule(BaseModel):
    code: EligibilityCode
    text: str
    params: RuleParams = Field(default_factory=RuleParams)
    evidence: Evidence


class Criterion(BaseModel):
    condition: str
    points: float


class EvalItem(BaseModel):
    item: str
    max_points: float
    kind: EvalKind
    criteria: list[Criterion] = Field(default_factory=list)
    criteria_table_id: str | None = None  # LLM은 null(X62 — 입력에 표 ID 없음)
    evidence: Evidence


class QualItem(BaseModel):
    item: str
    max_points: float


class Evaluation(BaseModel):
    tech_weight: int | None = None
    price_weight: int | None = None
    qualifying_rule: str | None = None
    qualifying_threshold: float | None = None
    qualifying_basis: QualifyingBasis | None = None
    quantitative: list[EvalItem] = Field(default_factory=list)
    qualitative: list[QualItem] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class StaffingReq(BaseModel):
    role: str
    grade: Grade | None = None
    count: int | None = None
    resident: bool | None = None
    location: str | None = None
    min_years: int | None = None
    notes: str | None = None
    evidence: Evidence


class Subcontract(BaseModel):
    allowed: bool | None = None
    limit_pct: float | None = None
    note: str | None = None


class Consortium(BaseModel):
    allowed: bool | None = None
    type: ConsortiumType | None = None
    note: str | None = None


class Sla(BaseModel):
    has: bool | None = None
    penalty_note: str | None = None


class RemoteWork(BaseModel):
    allowed: bool | None = None
    note: str | None = None


class ContractTerms(BaseModel):
    subcontract: Subcontract = Field(default_factory=Subcontract)
    consortium: Consortium = Field(default_factory=Consortium)
    ip_ownership: str | None = None
    sla: Sla = Field(default_factory=Sla)
    warranty_months: int | None = None
    proposal_compensation: str | None = None
    proposal_page_limit: int | None = None
    remote_work: RemoteWork = Field(default_factory=RemoteWork)
    evidence: list[Evidence] = Field(default_factory=list)


class CommercialSw(BaseModel):
    name: str
    vendor: str | None = None
    evidence: Evidence


class SystemEnv(BaseModel):
    framework: str | None = None
    cloud: str | None = None
    accessibility_std: str | None = None
    cms: str | None = None


class SubmissionDoc(BaseModel):
    name: str
    due: str | None = None
    copies: str | None = None
    stage: str | None = None
    condition: str | None = None
    evidence: Evidence


class Conflict(BaseModel):
    field: str
    values: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class RfpFacts(BaseModel):
    """Pass1 추출 결과(공고 하나). `conflicts`는 M3-01 병합이 채우고 single은 빈 리스트."""

    schema_version: int = 1
    project: Project = Field(default_factory=Project)
    schedule: Schedule = Field(default_factory=Schedule)
    eligibility: list[EligibilityRule] = Field(default_factory=list)
    evaluation: Evaluation = Field(default_factory=Evaluation)
    staffing: list[StaffingReq] = Field(default_factory=list)
    contract_terms: ContractTerms = Field(default_factory=ContractTerms)
    commercial_sw: list[CommercialSw] = Field(default_factory=list)
    system_env: SystemEnv = Field(default_factory=SystemEnv)
    deliverables: list[str] = Field(default_factory=list)
    submission_docs: list[SubmissionDoc] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)


class RfpFactsPartial(BaseModel):
    """맵리듀스 Pass1의 chunk 하나 출력(M3-01). 하위 모델은 RfpFacts와 같은 클래스.

    최상위 값이 None이면 "그 chunk가 그 필드를 모른다(누락)"(X9). `conflicts`는 없다.
    """

    schema_version: int = 1
    project: Project | None = None
    schedule: Schedule | None = None
    eligibility: list[EligibilityRule] | None = None
    evaluation: Evaluation | None = None
    staffing: list[StaffingReq] | None = None
    contract_terms: ContractTerms | None = None
    commercial_sw: list[CommercialSw] | None = None
    system_env: SystemEnv | None = None
    deliverables: list[str] | None = None
    submission_docs: list[SubmissionDoc] | None = None


class GateResult(BaseModel):
    """참가자격 게이트 판정 하나(M2-03 `gates.evaluate_gates`의 출력).

    `evidence`는 필수 필드지만 빈 리스트를 허용한다(원천 인용이 없는 파생 게이트, X15).
    `action`은 PASS면 None, 그 외 코드가 만든다. `unknown_fields`는 판정에 필요했지만
    "unknown"이었던 프로필 경로(중복 제거, 등장 순).
    """

    code: GateCode
    rule_text: str
    company_value: str
    verdict: Verdict
    evidence: list[Evidence]
    action: str | None = None
    unknown_fields: list[str] = Field(default_factory=list)
    input_fields: list[str] = Field(default_factory=list)
    rule_hash: str | None = None

    @field_validator("rule_hash")
    @classmethod
    def _rule_hash_is_lower_hex(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_RE.fullmatch(value):
            raise ValueError("rule_hash must be 64 lowercase hex characters")
        return value

    @field_validator("input_fields")
    @classmethod
    def _dedup_input_fields(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class ScoreEstimate(BaseModel):
    """정량평가 항목 하나의 추정 점수 구간(M2-03 `scoring.estimate_scores`의 출력).

    불변식 0 ≤ est_min ≤ est_max ≤ max_points는 모델이 아니라 scoring 코드가 clamp로 지킨다.
    """

    item: str
    kind: EvalKind
    max_points: float
    est_min: float
    est_max: float
    basis: str
    unknown_inputs: list[str] = Field(default_factory=list)
    input_fields: list[str] = Field(default_factory=list)

    @field_validator("input_fields")
    @classmethod
    def _dedup_input_fields(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class RequirementFitOut(BaseModel):
    """Pass2 LLM 출력 항목(Field 제약 없음 — X7). `postprocess_fits`가 `RequirementFit`으로 변환."""

    req_id: str
    fit: Fit
    rationale: str
    evidence_portfolio_ids: list[str] = Field(default_factory=list)
    gap_action: str | None = None
    evidence: Evidence | None = None


class RequirementFit(BaseModel):
    """요구사항 적합도 저장 모델(fits.json·analysis.json). 후처리 후 `evidence`는 항상 채워진다.

    `evidence_pages`는 모델 출력이 아니다(X7): pipeline `annotate_evidence_pages`가 `rationale`의
    `[[slug]]` 중 발췌 페이지와 해당 요구사항의 지도 근거를 채운다. 필드 도입 전 산출물은 `[]`.
    """

    req_id: str = Field(pattern=REQUIREMENT_BASE_ID_PATTERN)
    fit: Fit
    rationale: str
    evidence_portfolio_ids: list[str] = Field(default_factory=list)
    evidence_pages: list[str] = Field(default_factory=list)  # 발췌 포함 지식 페이지 slug(등장 순)
    gap_action: str | None = None
    evidence: Evidence | None = None
    name: str | None = None
    definition: str | None = None
    instance_key: str | None = None

    @property
    def key(self) -> str:
        return self.instance_key or self.req_id


class Risk(BaseModel):
    category: RiskCategory
    severity: Severity
    description: str
    evidence: Evidence
    mitigation: str | None = None


class ChecklistItem(BaseModel):
    item: str
    due: str | None = None
    source: Evidence | None = None


class DataToConfirm(BaseModel):
    field: str
    why: str
    origin: Literal["code", "llm", "legacy"] = "legacy"


class ActionRef(BaseModel):
    source: Literal["code", "llm", "legacy"]
    path: str


class ConfirmRequest(BaseModel):
    id: str
    kind: Literal["company", "notice", "execution"]
    fields: list[str]
    title: str
    why: str
    affects: list[str]
    blocking: bool
    completion: str
    refs: list[ActionRef]
    purpose: Literal["decision", "scoring", "execution"] | None = None
    availability: Literal["check_now", "awaiting_input"] | None = None


class Preparation(BaseModel):
    """STEP-002가 채우는 서류·일정·실행 준비 항목의 저장 계약."""

    id: str
    kind: Literal["document", "schedule", "execution"]
    title: str
    due: str | None
    copies: str | None
    stage: str | None
    condition: str | None
    refs: list[ActionRef]


class ExcludedRequest(BaseModel):
    field: str
    refs: list[ActionRef]
    reason: Literal["confirmed", "out_of_scope", "score_invariant"]


class ActionCounts(BaseModel):
    raw_requests: int
    active_requests: int
    excluded_requests: int
    raw_preparations: int
    unique_preparations: int


class ReviewActions(BaseModel):
    schema_version: Literal[1] = 1
    requests: list[ConfirmRequest] = Field(default_factory=list)
    preparations: list[Preparation] = Field(default_factory=list)
    excluded: list[ExcludedRequest] = Field(default_factory=list)
    counts: ActionCounts


class Profitability(BaseModel):
    budget_krw: int | None = None
    est_mm: float | None = None
    note: str


class MatchOut(BaseModel):
    """Pass2 LLM 출력 모델(Field 제약 없음 — X7)."""

    fits: list[RequirementFitOut] = Field(default_factory=list)


class SynthOut(BaseModel):
    """Pass3 LLM 출력 모델(Field 제약 없음 — X7). 결정·점수·판정 필드는 없다(사용자 결정 7)."""

    risks: list[Risk] = Field(default_factory=list)
    profitability: Profitability
    checklist: list[ChecklistItem] = Field(default_factory=list)
    data_to_confirm: list[DataToConfirm] = Field(default_factory=list)
    summary: str
    preconditions: list[str] = Field(default_factory=list)
    why_not: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    """권고(코드 계산, M2-04 `recommend.recommend`). LLM 출력 모델이 아니라 제약을 둔다."""

    decision: DecisionValue
    fit_score: int = Field(ge=0, le=100)
    summary: str
    preconditions: list[str] = Field(default_factory=list)
    why_not: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, Any]
    basis: list[str] = Field(default_factory=list)


class StageParameters(BaseModel):
    """한 단계가 실제로 사용한 요청/지식 선택. 환경의 현재 기본값은 기록하지 않는다."""

    model: str | None
    strategy: StrategyName | None
    effort: str | None
    knowledge_root: str | None
    knowledge_categories: list[str]
    knowledge_category_source: Literal["auto", "manual", "none"]
    model_fingerprint: str | None = None

    @model_validator(mode="after")
    def _knowledge_fields_are_consistent(self) -> "StageParameters":
        inactive = self.knowledge_category_source == "none"
        if inactive != (self.knowledge_root is None and self.knowledge_categories == []):
            raise ValueError("inactive knowledge requires root=null, categories=[], source=none")
        return self


class StageStamp(BaseModel):
    """생성자가 실제 입력과 의미 출력을 알고 있을 때만 저장하는 단계 지문."""

    input_hash: str
    output_hash: str
    version: str
    computed_at: str
    inputs: dict[str, str | None]
    parameters: StageParameters

    @field_validator("input_hash", "output_hash")
    @classmethod
    def _hash_is_lower_hex(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("hash must be 64 lowercase hex characters")
        return value

    @field_validator("inputs")
    @classmethod
    def _input_hashes_are_lower_hex(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        if any(
            key != "work_units" if item is None else not _SHA256_RE.fullmatch(item)
            for key, item in value.items()
        ):
            raise ValueError("input hashes must be 64 lowercase hex characters")
        return value

    @field_validator("computed_at")
    @classmethod
    def _computed_at_has_offset(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("computed_at must include an ISO 8601 UTC offset")
        return value


class ScoreInterval(BaseModel):
    min: int
    max: int

    @model_validator(mode="after")
    def _ordered(self) -> "ScoreInterval":
        if self.min > self.max:
            raise ValueError("score interval min must not exceed max")
        return self


class ProvisionalCondition(BaseModel):
    """잠정 결론을 바꿀 수 있는 조건 하나. `refs`는 내부 참조라 사용자에게 표시하지 않는다."""

    id: str  # "<kind>:<대상>" — 대상: gate code | "requirements" | "fits" | "pdf" | "analysis"
    kind: ConditionKind
    title: str
    check: str
    if_not: str
    gate_codes: list[GateCode] = Field(default_factory=list)
    company_fields: list[str] = Field(default_factory=list)  # 등장 순, 중복 없음
    refs: list[str] = Field(default_factory=list)


class FitCoverage(BaseModel):
    judged: int
    total: int


class Provisional(BaseModel):
    """회사 기록(public·estimate 가정 포함)으로 계산한 잠정 결론. stamp 해시에서 제외된다.

    `demo_fields`: 결론을 정한 게이트 범위(assumed_fields와 같은 규칙)에서 판정에 쓴 demo 수준
    회사 경로(정렬, 중복 없음). demo는 확인값과 같이 쓰므로 basis에 영향이 없고, 실제 운영 전
    교체 대상을 보고서에 알리는 데만 쓴다.
    """

    decision: DecisionValue
    basis: ProvisionalBasis
    conditions: list[ProvisionalCondition]  # 전부 저장. 표시 상한은 PF-03
    fit_coverage: FitCoverage
    fit_base: int | None  # judged == 0이면 None
    assumed_fields: list[str]  # 정렬, 중복 없음
    demo_fields: list[str] = Field(default_factory=list)  # 정렬, 중복 없음

    @model_validator(mode="after")
    def _condition_ids_unique(self) -> "Provisional":
        ids = [condition.id for condition in self.conditions]
        duplicated = sorted({item for item in ids if ids.count(item) > 1})
        if duplicated:
            raise ValueError(f"provisional condition ids must be unique: {', '.join(duplicated)}")
        return self


class Assessment(BaseModel):
    state: Literal["ready", "abstain"]
    decision: DecisionValue | None
    reason_codes: list[ReasonCode]
    score_interval: ScoreInterval | None
    # None = 회사 미지정 또는 이 필드 이전 산출물. stamp 해시에서 제외된다(provenance.py).
    provisional: Provisional | None = None

    @field_validator("reason_codes")
    @classmethod
    def _stable_reason_codes(cls, value: list[ReasonCode]) -> list[ReasonCode]:
        included = set(value)
        return [code for code in REASON_CODE_ORDER if code in included]

    @model_validator(mode="after")
    def _state_matches_decision(self) -> "Assessment":
        if (self.state == "ready") != (self.decision is not None):
            raise ValueError("ready requires a decision and abstain requires decision=null")
        return self


class PolicyConflict(BaseModel):
    code: Literal["seoul_onsite"]
    company_fields: list[str]
    evidence: list[Evidence]
    message: str


class RequirementCounts(BaseModel):
    source_found: int
    analysis_input: int
    source_expected: int | None = None


class LanguageWarning(BaseModel):
    path: str
    terms: list[str]
    retry_pass: Literal["extract", "match", "synth"] | None = None


class Analysis(BaseModel):
    """analysis.json 최상위(공고 하나). `strategy`=요청, `strategy_effective`=실제.

    `numeric_facts_unconfirmed`: rfp 문서의 primary_format이 pdf면 True(제약 4 — pdf 단독 숫자 사실
    확정 금지). recommend 가드와 report 표지가 이 값만 본다. 이 필드 도입 전 산출물은 False.
    `knowledge`: match·synth에 넣은 회사 지식 발췌 선택(`knowledge_hash` 포함, KB-03). 지식
    비활성 실행과 이 필드 도입 전 산출물은 None.
    """

    schema_version: int = 1
    slug: str
    model: str
    served_model: str
    strategy: str
    strategy_effective: StrategyName | None = None  # None = 이 필드 도입 전 산출물(M2)
    numeric_facts_unconfirmed: bool = False
    knowledge: KnowledgeSelection | None = None  # None = 지식 비활성 또는 필드 도입 전 산출물
    work_units: WorkUnitSummary | None = None
    company_input_hash: str | None = None  # None = REV-01 이전 또는 legacy 호출
    effort: str
    requirement_counts: RequirementCounts | None = None
    language_warnings: list[LanguageWarning] = Field(default_factory=list)
    facts: RfpFacts
    gates: list[GateResult] = Field(default_factory=list)
    scores: list[ScoreEstimate] = Field(default_factory=list)
    fits: list[RequirementFit] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    profitability: Profitability
    checklist: list[ChecklistItem] = Field(default_factory=list)
    data_to_confirm: list[DataToConfirm] = Field(default_factory=list)
    raw_data_to_confirm: list[DataToConfirm] | None = None
    review_actions: ReviewActions | None = None
    recommendation: Recommendation
    # REV additive fields. Legacy files omit these and remain readable without manufacturing
    # metadata.
    synth_output: SynthOut | None = None
    assessment: Assessment | None = None
    stages: dict[Stage, StageStamp] = Field(default_factory=dict)
    citations: dict[str, int]  # total, verified, repaired, unverified
    usage: dict[str, int | float]  # calls, 토큰 4종, cost_usd
    created_at: str  # ISO 8601, 초 단위, 로컬 시간대

    @model_serializer(mode="wrap")
    def _omit_missing_work_units(self, handler):  # type: ignore[no-untyped-def]
        data = handler(self)
        if self.work_units is None:
            data.pop("work_units", None)
        return data


def iter_evidence(model: BaseModel, *, include_conflicts: bool = False) -> Iterator[Evidence]:
    """`model`의 Evidence 인스턴스를 문서 순서(필드 선언 순서, 리스트 인덱스 순서)로 낸다.

    하위 모델·리스트를 재귀로 따라가고 None 필드는 건너뛴다. `include_conflicts=False`(기본)면
    최상위 `conflicts` 필드 아래는 내지 않는다(X10 — 인용 통계는 기본, M2-02 verify는 True).
    인스턴스 자체를 내므로 호출자가 제자리에서 고칠 수 있다.
    """
    if isinstance(model, Evidence):
        yield model
        return
    for name in type(model).model_fields:
        if name == "conflicts" and not include_conflicts:
            continue
        yield from _iter_value(getattr(model, name))


def _iter_value(value: object) -> Iterator[Evidence]:
    if isinstance(value, Evidence):
        yield value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _iter_value(getattr(value, name))
    elif isinstance(value, list):
        for item in value:
            yield from _iter_value(item)
