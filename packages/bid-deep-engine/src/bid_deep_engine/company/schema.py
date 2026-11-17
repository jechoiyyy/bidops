"""회사 프로필 스키마(CompanyProfile, PortfolioItem). 필드 선언 순서 = 템플릿 순서 = todo 순서.

unknown 규칙(docs/conventions.md): 미확인 = 문자열 "unknown", null = 해당 없음.
- `X | Unknown` 필드는 키가 없으면 "unknown", 목록은 `[]`, `X | None`은 `None`.
- `list[...] | Unknown`·`dict[...] | Unknown`의 `[]`/`{}`는 "확인된 미보유"이고 null은 오류(X17).
- 모든 모델은 extra 금지·strict: 따옴표 없는 번호(int → str), 문자열 금액("100" → int),
  실수 금액(1.0 → int), 문자열 불리언은 변환하지 않고 오류로 본다.
- 날짜는 `YYYY-MM`/`YYYY-MM-DD` 문자열. PyYAML이 만든 `datetime.date`는 loader가
  미리 문자열로 바꾼다.
- 실적 ID 형식(`PORTFOLIO_ID_RE`)은 모델이 검사하지 않는다. validate 규칙 3 한 곳에서만(X64).
"""

import re
from typing import Annotated, Any, Literal, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    with_config,
)

UNKNOWN = "unknown"
Unknown = Literal["unknown"]

DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?$")
PORTFOLIO_ID_RE = re.compile(r"^P\d{4}-\d{2}$")

DateStr = Annotated[str, StringConstraints(pattern=DATE_RE.pattern)]
Krw = Annotated[int, Field(ge=0)]  # 원 단위 정수
Count = Annotated[int, Field(ge=0)]  # 인원·건수
Pct = Annotated[float, Field(ge=0, le=100)]

# enum(spec "enum" 표). "unknown" 허용 여부는 필드 타입에서 `| Unknown`으로 정한다.
CompanySize = Literal["중소기업", "중견기업", "대기업", "소상공인"]
CertStatus = Literal["valid", "expired", "none", "unknown"]
Debarment = Literal["none", "active", "none_known"]
TaxDelinquency = Literal["none", "exists", "unknown"]
Insolvency = Literal["none", "active", "unknown"]
BidMode = Literal["solo", "consortium"]
ClientType = Literal["중앙행정", "지자체", "교육기관", "공공기관", "민간", "해외"]
ProjectType = Literal["구축", "고도화", "유지관리", "운영", "개발", "컨설팅", "물품"]
ProjectRole = Literal["주사업자", "공동수급", "하도급"]
OnsiteRegion = Literal["대구", "경북", "부산", "서울", "기타"]
Grade = Literal["초급", "중급", "고급", "특급"]

# 템플릿 순서(사전 키 채움·todo 순서용). Grade enum 순서와 다르다.
GRADE_KEYS: tuple[Grade, ...] = ("특급", "고급", "중급", "초급")
ONSITE_KEYS: tuple[OnsiteRegion, ...] = ("대구", "경북", "부산", "서울", "기타")

# 목록 항목의 식별 키(todo 경로·오류 경로의 `[키 값]`). 키 = 목록의 점 경로(인덱스는 `[*]`).
LIST_ID_KEYS: dict[str, str] = {
    "portfolio": "id",
    "registrations.direct_production": "item_no",
    "registrations.iso": "std",
    "registrations.cloud_certs": "name",
    "registrations.other_certs": "name",
    "registrations.web_accessibility_certs.sites": "site",
    "people.key_staff": "alias",
    "capabilities.solutions": "name",
}

_CONFIG = ConfigDict(extra="forbid", strict=True)


class _Model(BaseModel):
    model_config = _CONFIG


# --- company ---


class Company(_Model):
    name: str
    name_en: str = UNKNOWN
    biz_no: str = UNKNOWN
    ceo: str = UNKNOWN
    address: str = UNKNOWN
    region: str = UNKNOWN  # 시·도
    founded: DateStr | Unknown = UNKNOWN
    incorporated: DateStr | Unknown = UNKNOWN
    size: CompanySize | Unknown = UNKNOWN
    employees: Count | Unknown = UNKNOWN
    capital_krw: Krw | Unknown = UNKNOWN
    revenue_krw: dict[int, Krw | Unknown] = Field(default_factory=dict)  # 키 = 연도
    branches: list[str] = Field(default_factory=list)


# --- registrations ---


class G2b(_Model):
    registered: bool | Unknown = UNKNOWN
    industry_codes: list[str] | Unknown = UNKNOWN
    other_codes: list[str] | Unknown = UNKNOWN


class SwBusinessReport(_Model):
    reported: bool | Unknown = UNKNOWN
    latest_year: int | Unknown = UNKNOWN


class SmeCertificate(_Model):
    status: CertStatus = UNKNOWN
    valid_until: DateStr | Unknown = UNKNOWN
    classification: Literal["중기업", "소기업", "소상공인", "unknown"] = UNKNOWN


class DirectProduction(_Model):
    item_no: str  # 식별 키
    name: str = UNKNOWN
    status: CertStatus = UNKNOWN
    valid_until: DateStr | Unknown = UNKNOWN


class Venture(_Model):
    type: str = UNKNOWN
    since: DateStr | Unknown = UNKNOWN
    valid_until: DateStr | Unknown = UNKNOWN


class SinceUntil(_Model):
    """innobiz·mainbiz."""

    since: DateStr | Unknown = UNKNOWN
    valid_until: DateStr | Unknown = UNKNOWN


class RndInstitute(_Model):
    type: str = UNKNOWN
    since: DateStr | Unknown = UNKNOWN


class SinceField(_Model):
    """전문연구사업자·엔지니어링사업자·산업디자인전문회사."""

    since: DateStr | Unknown = UNKNOWN
    field: str = UNKNOWN


class Since(_Model):
    since: DateStr | Unknown = UNKNOWN


class IsoCert(_Model):
    std: str  # 식별 키, 따옴표 문자열("9001")
    since: DateStr | Unknown = UNKNOWN


class CloudCert(_Model):
    name: str  # 식별 키
    since: DateStr | Unknown = UNKNOWN


class OtherCert(_Model):
    name: str  # 식별 키
    since: DateStr | Unknown = UNKNOWN
    valid_until: DateStr | Unknown = UNKNOWN


class EsgCert(_Model):
    has: bool | Unknown = UNKNOWN
    since: DateStr | Unknown = UNKNOWN


class WebAccessibilitySite(_Model):
    site: str  # 식별 키
    cert_body: str = UNKNOWN
    year: int | Unknown = UNKNOWN


class WebAccessibilityCerts(_Model):
    count: Count | Unknown = UNKNOWN
    sites: list[WebAccessibilitySite] = Field(default_factory=list)


class CreditRating(_Model):
    grade: str = UNKNOWN
    agency: str = UNKNOWN
    valid_until: DateStr | Unknown = UNKNOWN


class TechRating(_Model):
    grade: str = UNKNOWN
    since: DateStr | Unknown = UNKNOWN
    agency: str = UNKNOWN


class Registrations(_Model):
    g2b: G2b = Field(default_factory=G2b)
    sw_business_report: SwBusinessReport = Field(default_factory=SwBusinessReport)
    sme_certificate: SmeCertificate = Field(default_factory=SmeCertificate)
    direct_production: list[DirectProduction] = Field(default_factory=list)
    venture: Venture | None = None
    innobiz: SinceUntil | None = None
    mainbiz: SinceUntil | None = None
    rnd_institute: RndInstitute | None = None
    specialized_research_business: SinceField | None = None
    engineering_business_report: SinceField | None = None
    industrial_design_company: SinceField | None = None
    performance_sharing_company: Since | None = None
    military_designated_company: Since | None = None
    iso: list[IsoCert] = Field(default_factory=list)
    cloud_certs: list[CloudCert] = Field(default_factory=list)
    esg_cert: EsgCert | None = None
    gs_cert: list[str] | Unknown = UNKNOWN
    other_certs: list[OtherCert] = Field(default_factory=list)
    web_accessibility_certs: WebAccessibilityCerts = Field(default_factory=WebAccessibilityCerts)
    egov_framework_inspection_reports: Count | Unknown = UNKNOWN
    credit_rating: CreditRating = Field(default_factory=CreditRating)
    tech_rating: TechRating | None = None
    debarment: Debarment = "none_known"
    tax_delinquency: TaxDelinquency = UNKNOWN
    insolvency: Insolvency = UNKNOWN
    wage_arrears_listed: bool | Unknown = UNKNOWN
    aa_noncompliance_listed: bool | Unknown = UNKNOWN
    patents: Count | Unknown = UNKNOWN
    copyrights: Count | Unknown = UNKNOWN


# --- people ---


@with_config(_CONFIG)
class HeadcountByGrade(TypedDict):
    """등급별 인원. 실제 값은 dict(키 = Grade, 그 외 키 오류). 빠진 키는 "unknown"으로 채운다."""

    특급: Count | Unknown
    고급: Count | Unknown
    중급: Count | Unknown
    초급: Count | Unknown


class OnsiteSlot(_Model):
    """대구·경북·부산·서울 상주 가능 여부와 최대 인원."""

    ok: bool | Unknown = UNKNOWN
    max_people: Count | Unknown = UNKNOWN


class OnsiteOtherSlot(_Model):
    """기타 지역. max_people 키는 오류."""

    ok: bool | Unknown = UNKNOWN


@with_config(_CONFIG)
class OnsiteCapacity(TypedDict):
    """지역별 상주 가능 슬롯. 실제 값은 dict(키 = OnsiteRegion, 그 외 키 오류).

    빠진 지역 키는 모델이 기본 슬롯("unknown")으로 채운다. 빠짐 경고는 loader가 원본에서 계산한다.
    """

    대구: OnsiteSlot
    경북: OnsiteSlot
    부산: OnsiteSlot
    서울: OnsiteSlot
    기타: OnsiteOtherSlot


class Roles(_Model):
    pm_capable: Count | Unknown = UNKNOWN
    web_developer: Count | Unknown = UNKNOWN
    web_designer_5y_plus: Count | Unknown = UNKNOWN
    publisher: Count | Unknown = UNKNOWN
    ai_engineer: Count | Unknown = UNKNOWN
    blockchain_engineer: Count | Unknown = UNKNOWN
    security: Count | Unknown = UNKNOWN


class Trainings(_Model):
    sw_security_diagnostician: Count | Unknown = UNKNOWN
    sw_test_expert: Count | Unknown = UNKNOWN


class KeyStaff(_Model):
    alias: str  # 식별 키(실명 불필요)
    role: str = UNKNOWN
    grade: Grade | Unknown = UNKNOWN
    years: Count | Unknown = UNKNOWN
    certs: list[str] = Field(default_factory=list)
    trainings: list[str] = Field(default_factory=list)


def _fill_keys(value: Any, keys: tuple[str, ...], fill: Any) -> Any:
    """매핑이면 빠진 키를 템플릿 순서로 채운다. 모르는 키는 뒤에 남겨 extra 오류가 나게 한다."""
    if not isinstance(value, dict):
        return value
    filled = {k: value.get(k, fill(k)) for k in keys}
    filled.update({k: v for k, v in value.items() if k not in filled})
    return filled


class People(_Model):
    total_tech_staff: Count | Unknown = UNKNOWN
    headcount_by_grade: HeadcountByGrade = Field(default_factory=dict, validate_default=True)
    roles: Roles = Field(default_factory=Roles)
    trainings: Trainings = Field(default_factory=Trainings)
    certifications: dict[str, Count] | Unknown = UNKNOWN
    onsite_capacity: OnsiteCapacity = Field(default_factory=dict, validate_default=True)
    key_staff: list[KeyStaff] = Field(default_factory=list)

    @field_validator("headcount_by_grade", mode="before")
    @classmethod
    def _fill_grades(cls, value: Any) -> Any:
        return _fill_keys(value, GRADE_KEYS, lambda _k: UNKNOWN)

    @field_validator("onsite_capacity", mode="before")
    @classmethod
    def _fill_regions(cls, value: Any) -> Any:
        return _fill_keys(value, ONSITE_KEYS, lambda _k: {})


# --- capabilities ---


class TechStack(_Model):
    backend: list[str] | Unknown = UNKNOWN
    frontend: list[str] | Unknown = UNKNOWN
    db: list[str] | Unknown = UNKNOWN
    infra: list[str] | Unknown = UNKNOWN
    ai: list[str] | Unknown = UNKNOWN
    blockchain: list[str] | Unknown = UNKNOWN


class Solution(_Model):
    name: str  # 식별 키
    desc: str | None = None  # X38: X | None 스칼라는 = None


class Capabilities(_Model):
    domains: list[str] = Field(default_factory=list)
    tech_stack: TechStack = Field(default_factory=TechStack)
    cms_experience: list[str] | Unknown = UNKNOWN
    commercial_sw_experience: list[str] | Unknown = UNKNOWN
    egov_framework_experience: bool | Unknown = UNKNOWN
    web_accessibility_experience: bool | Unknown = UNKNOWN
    solutions: list[Solution] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


# --- policy ---


class Policy(_Model):
    min_contract_amount_krw: Krw | Unknown = UNKNOWN
    target_gross_margin_pct: Pct | Unknown = UNKNOWN
    seoul_resident_ok: bool | Unknown = UNKNOWN
    max_concurrent_new_projects: Count | Unknown = UNKNOWN
    default_bid_mode: BidMode | Unknown = UNKNOWN
    no_bid_if: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)


# --- portfolio ---


class Period(_Model):
    start: DateStr | Unknown = UNKNOWN
    end: DateStr | Unknown = UNKNOWN


class PortfolioItem(_Model):
    id: str  # 형식 `PORTFOLIO_ID_RE`·유일성은 validate 규칙 3에서만 검사(X64)
    client: str
    client_type: ClientType | Unknown = UNKNOWN
    title: str
    type: ProjectType | Unknown = UNKNOWN
    domain: list[str] = Field(default_factory=list)
    tech: list[str] | Unknown = UNKNOWN
    period: Period = Field(default_factory=Period)
    amount_krw: Krw | Unknown = UNKNOWN
    role: ProjectRole | Unknown = UNKNOWN
    share_pct: Pct | Unknown = UNKNOWN
    completed: bool | Unknown = UNKNOWN
    evidence: str = UNKNOWN  # 실적증명서/계약서 보유 여부 또는 URL
    web_accessibility_cert: bool | Unknown = UNKNOWN
    egov_framework: bool | Unknown = UNKNOWN


class CompanyProfile(_Model):
    schema_version: Literal[1]
    company: Company
    registrations: Registrations = Field(default_factory=Registrations)
    people: People = Field(default_factory=People)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    portfolio_file: str  # 프로필 파일 폴더 기준 상대 경로
    provenance_file: str | None = None  # 프로필 폴더 기준 상대 경로, legacy는 None
    policy: Policy = Field(default_factory=Policy)
    # 프로필 YAML에는 쓰지 않는다. loader가 portfolio_file에서 읽어 채운다
    # (YAML의 portfolio 키는 loader가 거부).
    portfolio: list[PortfolioItem] = Field(default_factory=list)
