"""결정적 참가자격 게이트(spec M2-03). `RfpFacts × CompanyProfile → GateResult[]`.

판정은 코드 규칙표로만 한다(LLM·네트워크 없음, 제약 3). verdict·company_value·action은 모두
코드의 상수·포맷 문자열이다. 프로필의 "unknown"은 가정값으로 채우지 않고 UNKNOWN(파생 게이트는
RISK)과 `unknown_fields` 경로로 남긴다(제약 2).

구성: 기준일(`resolve_as_of`), 날짜 헬퍼(`add_years`, `parse_leading_date`, `profile_date`),
창업기업 판정(`is_startup`), 실적 창(`performance_window`), 지역 정규화(`normalize_region`),
eligibility 규칙 13종과 재분류 규칙 2종(CONSORTIUM_CONDITION·INSOLVENCY), OTHER 재분류
(`OTHER_RECLASS`·`reclassify_other`), 계약조건 파생 게이트 2종, 조합(`evaluate_gates`).

OTHER 재분류(GT-01, X77, 허용 목록): `code == "OTHER"`인 조항은 `norm_clause(text)` **전체**가
`OTHER_RECLASS` 템플릿(정규식 `fullmatch`) 하나와 통째로 맞을 때만(표 순서, 먼저 맞는 것)
그 코드의 규칙으로 판정한다. 다른 요건이 덧붙거나 문형이 다르면 재분류하지 않는다(→ 사람 확인).
`GateResult.code`는 재분류 코드, `rule_text`는 원문 + ` [재분류 OTHER→<code>]`(+ 날짜 게이트면
기준일 접미). facts는 바꾸지 않고, 규칙 함수는 `rule.code`를 읽지 않는다. 맞는 템플릿이 없으면
기존 OTHER(UNKNOWN "원문 확인").

실적 키워드(GT-02): `parse_perf_keyword`가 keyword를 핵심 토큰(불용어·괄호 구간·길이 1·숫자 시작
토큰 제거)과 허용 사업 유형(`PERF_TYPE_TOKENS`)으로 나누고, `keyword_match`가 핵심 토큰을 동의어
그룹(`PERF_SYNONYMS`)까지 포함해 모두(AND) 실적 title/domain에서 찾은 뒤 실적 `type`을 대조한다
(`"match" | "type_unknown" | "no"`). 상수 3개는 tunable. `_performance_rule`은 "no"를 제외하고,
"type_unknown"은 확정 후보 자리에서 불확실 후보로 바꿔 `portfolio[<ID>].type` 경로를 남긴다.
keyword 문자열이 있으면 company_value 끝에 `; 키워드=[…]; 유형=[…]`(없는 값 `-`, 유형은
ProjectType 선언 순)를 붙인다. keyword 문자열이 있는데 핵심 토큰·유형이 모두 비면 후보를 만들지
않고 UNKNOWN("실적 목록 확인")이다.

실적 지식·역량 대안(설계 docs/design/2026-10-25-past-performance-capability.md 2절): 호출자가
`portfolio_texts`(실적 ID → confirmed 실적 페이지 세 절 본문)를 넘기면 핵심 토큰을 그 텍스트에서도
찾는다(2.1). 조항 원문에 역량 대안(`has_capability_alternative`)이 있고 실적 대조가 PASS가 아니면
`capabilities.domains`·`solutions[*]`·`tech_stack.*`의 뷰 수용 값을 대조해 일치하면 PASS +
`; 역량 근거=[경로…]`(2.2). 지식·역량 텍스트의 2글자 이하 변형은 단어 경계 일치만 인정한다(2.3,
`perf_text_has`). 게이트는 지식 트리를 직접 읽지 않는다.

기준일 규칙(계약 시트 6절): 제출마감 → 공고일 → 실행일. 프로필 날짜 해석: 만료일 성격
(`valid_until`, 실적 `period.end`)의 `YYYY-MM`은 그 달 말일, 시작일 성격(`company.founded`,
`period.start`)의 `YYYY-MM`은 그 달 1일.

action 규칙(spec, 위에서 먼저 맞는 것): PASS → None; 행별 문구(유효기간 경과 "갱신 확인" 등,
RISK 문구); FAIL → `FAIL_ACTION`; UNKNOWN이고 unknown_fields가 있으면 "확인 필요: " +
`hint_for(첫 경로)`; 그 외 UNKNOWN은 규칙별 고정 문구.
"""

import calendar
import hashlib
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, get_args

from bid_deep_engine.analysis.evidence_locations import canonical_json
from bid_deep_engine.analysis.schemas import (
    EligibilityRule,
    Evidence,
    GateCode,
    GateResult,
    RfpFacts,
    RuleParams,
    StaffingReq,
    Verdict,
)
from bid_deep_engine.company.hints import hint_for
from bid_deep_engine.company.provenance import CompanyEvidenceView, encode_path_token, resolve_profile_path
from bid_deep_engine.company.schema import LIST_ID_KEYS, UNKNOWN, CompanyProfile, PortfolioItem, ProjectType

CompanyInput = CompanyProfile | CompanyEvidenceView

STARTUP_YEARS = 7  # 창업기업 특례 기간(초기 설계). 모듈 상수, ≥ 1

# 지역 정규화 사전(tunable): 정규 시·도 키 → 변형 목록.
REGION_ALIASES: dict[str, list[str]] = {
    "서울": ["서울특별시", "서울시", "서울"],
    "부산": ["부산광역시", "부산시", "부산"],
    "대구": ["대구광역시", "대구시", "대구"],
    "인천": ["인천광역시", "인천시", "인천"],
    "광주": ["광주광역시", "광주시", "광주"],
    "대전": ["대전광역시", "대전시", "대전"],
    "울산": ["울산광역시", "울산시", "울산"],
    "세종": ["세종특별자치시", "세종시", "세종"],
    "경기": ["경기도", "경기"],
    "강원": ["강원특별자치도", "강원도", "강원"],
    "충북": ["충청북도", "충북"],
    "충남": ["충청남도", "충남"],
    "전북": ["전북특별자치도", "전라북도", "전북"],
    "전남": ["전라남도", "전남"],
    "경북": ["경상북도", "경북"],
    "경남": ["경상남도", "경남"],
    "제주": ["제주특별자치도", "제주도", "제주"],
}

# 인증·등록 이름(tunable): 프로필 registrations 키 → 이름. 존재(None 아님)하면 보유로 본다.
# rnd_institute(`type` 값), iso("ISO {std}"), cloud_certs(`name`), gs_cert(각 항목 + "GS인증"),
# esg_cert(`has` true일 때)는 `profile_cert_names`가 값에서 만든다.
CERT_LABELS: dict[str, tuple[str, ...]] = {
    "venture": ("벤처기업",),
    "innobiz": ("이노비즈", "Inno-Biz"),
    "mainbiz": ("메인비즈", "Main-Biz"),
    "specialized_research_business": ("전문연구사업자",),
    "engineering_business_report": ("엔지니어링사업자",),
    "industrial_design_company": ("산업디자인전문회사",),
    "performance_sharing_company": ("성과공유기업",),
    "military_designated_company": ("병역지정업체",),
    "gs_cert": ("GS인증",),
    "esg_cert": ("ESG",),
}

# 그 밖의 인증(`registrations.other_certs[].name`) 별칭(tunable, GT-01): `_norm_name(name)` 키 →
# 이름 목록에 함께 넣을 별칭. 공고가 약칭 없이 "정보보호 관리체계 인증"으로만 쓸 때를 위한 것.
OTHER_CERT_ALIASES: dict[str, tuple[str, ...]] = {
    "isms": ("정보보호관리체계",),
    "isms-p": ("정보보호및개인정보보호관리체계",),
}

# 상주 지역 키(tunable, M1-01 onsite_capacity 키). 나머지 지역·장소 미상은 ONSITE_OTHER_KEY.
ONSITE_REGION_KEYS: list[str] = ["서울", "대구", "경북", "부산"]
ONSITE_OTHER_KEY = "기타"

# rule_text에 기준일 접미를 붙이는 게이트(날짜 기준일을 쓰는 규칙).
DATE_GATE_CODES: frozenset[str] = frozenset(
    {"SME_CERT", "DIRECT_PRODUCTION", "SW_BUSINESS_REPORT", "PAST_PERFORMANCE"}
)

# action 문구(코드 상수).
FAIL_ACTION = "참가자격 미충족: 입찰 불가 또는 요건 확보 필요"
ACTION_RENEWAL = "갱신 확인"
ACTION_ITEM_NO_MISSING = "원문 확인: 세부품명번호 미추출"
ACTION_CHECK_SOURCE = "원문 확인"
ACTION_CHECK_HOLDING = "보유 여부 확인"
ACTION_CHECK_PORTFOLIO = "실적 목록 확인"
ACTION_CHECK_REPORT_YEAR = "신고 연도 확인"
ACTION_DEBARMENT_RISK = "부정당업자 제재 여부 조회 확인"
ACTION_MID_SIZE_RISK = "중견기업 참가 허용 여부 원문 확인"  # spec 미지정 RISK 문구(보고 대상)
ACTION_STAFFING_RISK = "자사 인력 투입 가능 여부 확인"
ACTION_CHECK_CONSORTIUM = "공동수급체 구성원 자격 확인"
UNKNOWN_HINT_PREFIX = "확인 필요: "

AsOfSource = Literal["submission_deadline", "notice_date", "run_date"]

_LEADING_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_PROFILE_DATE_RE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")


def parse_leading_date(text: str | None) -> date | None:
    """`^\\d{4}-\\d{2}-\\d{2}` 앞부분을 date로. 형식이 아니거나 없는 날짜(2026-02-30)면 None."""
    if not isinstance(text, str):
        return None
    m = _LEADING_DATE_RE.match(text)
    if m is None:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def resolve_as_of(facts: RfpFacts, today: date | None = None) -> tuple[date, AsOfSource]:
    """기준일과 그 출처. 제출마감 → 공고일 → `today`(기본 `date.today()`, 출처 "run_date")."""
    deadline = parse_leading_date(facts.schedule.submission_deadline)
    if deadline is not None:
        return deadline, "submission_deadline"
    notice = parse_leading_date(facts.schedule.notice_date)
    if notice is not None:
        return notice, "notice_date"
    return (today if today is not None else date.today()), "run_date"


def add_years(d: date, years: int) -> date:
    """연 단위 가감. 2월 29일이 없는 해로 가면 28일."""
    year = d.year + years
    try:
        return d.replace(year=year)
    except ValueError:  # 2월 29일 → 평년
        return d.replace(year=year, day=28)


def profile_date(value: object, *, end_of_month: bool) -> date | None:
    """프로필 날짜 문자열(`YYYY-MM`/`YYYY-MM-DD`)을 date로.

    `YYYY-MM`은 `end_of_month`면 그 달 말일(만료일 성격), 아니면 1일(시작일 성격).
    "unknown"·None·문자열이 아닌 값·해석 불가 날짜는 None(호출자가 unknown으로 다룬다).
    """
    if not isinstance(value, str):
        return None
    m = _PROFILE_DATE_RE.match(value)
    if m is None:
        return None
    year, month = int(m[1]), int(m[2])
    try:
        if m[3] is not None:
            return date(year, month, int(m[3]))
        if end_of_month:
            return date(year, month, calendar.monthrange(year, month)[1])
        return date(year, month, 1)
    except ValueError:
        return None


def _as_evidence_view(
    company: CompanyInput, evidence_view: CompanyEvidenceView | None = None
) -> CompanyEvidenceView:
    if isinstance(company, CompanyEvidenceView):
        if evidence_view is not None and evidence_view is not company:
            raise ValueError("company and evidence_view refer to different evidence views")
        return company
    if evidence_view is not None:
        if evidence_view.profile is not company:
            raise ValueError("evidence_view.profile must be the supplied CompanyProfile")
        return evidence_view
    return CompanyEvidenceView(company)


# 가정 목록 완전성(PF-01)을 인정하는 항목 하위 출처 수준. demo는 confirmed와 같이 다룬다:
# demo 목록 경로는 value()로 이미 완전하고, demo 항목만으로는 목록을 가정하지 않는다.
_ASSUMED_ITEM_LEVELS: frozenset[str] = frozenset({"public", "estimate"})


@dataclass
class _CompanyReader:
    view: CompanyEvidenceView
    input_fields: list[str] = field(default_factory=list)
    _evidence: dict[str, dict[str, object]] = field(default_factory=dict)
    # 가정으로 완전하다고 본 목록 경로(등장 순, 중복 없음). 한 평가의 리더들이 공유한다.
    assumed_lists: list[str] = field(default_factory=list)
    # 회사 지식 실적 페이지 대조 텍스트(실적 ID → 본문, `load_portfolio_texts`). 프로필 경로가
    # 아니라 input_fields에 남기지 않는다(gates stamp의 `portfolio_knowledge` 입력이 추적한다).
    portfolio_texts: Mapping[str, str] = field(default_factory=dict)

    @property
    def profile(self) -> CompanyProfile:
        return self.view.profile

    def get(self, path: str) -> dict[str, object]:
        """Read provenance and record every lookup at its single entry point."""
        self.input_fields.append(path)
        if path not in self._evidence:
            self._evidence[path] = self.view.get(path)
        return self._evidence[path]

    def value(self, path: str) -> object:
        evidence = self.get(path)
        if self.view.accepts(evidence["effective_level"]) and evidence["value"] != UNKNOWN:
            return evidence["value"]
        return UNKNOWN

    def raw_value(self, path: str) -> object:
        """Read structure only; callers must still use ``get``/``value`` for decisions."""
        return resolve_profile_path(self.profile, path)

    def has_provenance(self, path: str) -> bool:
        """Whether an exact compatibility path exists, without reading its decision value."""
        return self.view.provenance is not None and path in self.view.provenance.fields

    def list_complete(self, path: str) -> bool:
        """Whether the list at ``path`` may be treated as complete for absence decisions.

        An accepted list value proves completeness.  Otherwise, only a view that accepts
        ``public`` may *assume* completeness, and only when the list itself has no provenance
        entry, its raw value is non-empty, and at least one item carries a public/estimate
        entry under its item path.  Item checks read the view directly so they are not
        recorded as decision inputs.  Assumed paths are appended to ``assumed_lists``.
        """
        if self.value(path) != UNKNOWN:
            return True
        if not self._assumable_list(path):
            return False
        if path not in self.assumed_lists:
            self.assumed_lists.append(path)
        return True

    def _assumable_list(self, path: str) -> bool:
        if not self.view.accepts("public") or self.has_provenance(path):
            return False
        provenance = self.view.provenance
        id_key = LIST_ID_KEYS.get(path)
        if provenance is None or id_key is None:
            return False
        raw = self.raw_value(path)
        if not isinstance(raw, list) or not raw:
            return False
        for idx, item in enumerate(raw):
            identifier = item.get(id_key) if isinstance(item, dict) else None
            item_path = _item_path(path, identifier, idx)
            for key in provenance.fields:
                if key != item_path and not key.startswith(f"{item_path}."):
                    continue
                try:
                    evidence = self.view.get(key)
                except ValueError:
                    continue
                if evidence["effective_level"] in _ASSUMED_ITEM_LEVELS:
                    return True
        return False

    def optional_value(self, path: str, field_name: str) -> tuple[object, list[str]]:
        """Read an optional object's leaf, or the object path itself when it is absent.

        Optional object existence is structural only while the object is present; the leaf is
        still the decision input.  When the raw object is ``None``, its parent path is the
        decision input so missing provenance and confirmed absence remain distinguishable.
        """
        if self.raw_value(path) is None:
            value = self.value(path)
            return value, [path] if value == UNKNOWN else []
        field_path = f"{path}.{field_name}"
        value = self.value(field_path)
        return value, [field_path] if value == UNKNOWN else []

    def optional_present(self, path: str, field_names: tuple[str, ...]) -> tuple[object, list[str]]:
        """Use a source-bearing leaf as evidence that an optional fixed-label object exists."""
        if self.raw_value(path) is None:
            value = self.value(path)
            return value, [path] if value == UNKNOWN else []
        candidate_paths = [f"{path}.{field_name}" for field_name in field_names]
        for candidate in candidate_paths:
            evidence = self.get(candidate)
            if self.view.accepts(evidence["effective_level"]) and evidence["value"] != UNKNOWN:
                return True, []
        # One confirmed leaf is sufficient for existence, so expose one source-bearing path as
        # the actionable confirmation rather than every alternative audit lookup.
        actionable = next(
            (candidate for candidate in candidate_paths if self.raw_value(candidate) != UNKNOWN),
            candidate_paths[0],
        )
        return UNKNOWN, [actionable]


def _reader(
    view: CompanyEvidenceView,
    assumed_lists: list[str] | None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> _CompanyReader:
    texts: Mapping[str, str] = {} if portfolio_texts is None else portfolio_texts
    if assumed_lists is None:
        return _CompanyReader(view, portfolio_texts=texts)
    return _CompanyReader(view, assumed_lists=assumed_lists, portfolio_texts=texts)


def _item_path(base: str, identifier: object, idx: int) -> str:
    label = _list_label(identifier, idx)
    return f"{base}[{encode_path_token(str(label))}]"


def _is_startup(reader: _CompanyReader, as_of: date) -> bool | None:
    founded = profile_date(reader.value("company.founded"), end_of_month=False)
    if founded is None:
        return None
    return as_of < add_years(founded, STARTUP_YEARS)


def is_startup(
    profile: CompanyInput,
    as_of: date,
    *,
    evidence_view: CompanyEvidenceView | None = None,
) -> bool | None:
    """창업기업 특례 대상 여부. `company.founded`가 unknown이면 None(특례 미적용 + 미확인)."""
    return _is_startup(_CompanyReader(_as_evidence_view(profile, evidence_view)), as_of)


def _performance_window(
    reader: _CompanyReader, as_of: date, years: int | None
) -> tuple[date | None, date]:
    """실적 인정 창 `(시작 또는 None=하한 없음, as_of)`.

    창업기업이면 시작 = 창업일(창업일 이후 전체). 아니면 `years`가 있을 때 `as_of`의 `years`년 전,
    없으면 None. founded가 unknown이면 비창업으로 계산한다(미확인 경로 기록은 호출자 몫).
    """
    startup = _is_startup(reader, as_of)
    if startup:
        return profile_date(reader.value("company.founded"), end_of_month=False), as_of
    if years is not None:
        return add_years(as_of, -years), as_of
    return None, as_of


def performance_window(
    profile: CompanyInput,
    as_of: date,
    years: int | None,
    *,
    evidence_view: CompanyEvidenceView | None = None,
) -> tuple[date | None, date]:
    return _performance_window(
        _CompanyReader(_as_evidence_view(profile, evidence_view)), as_of, years
    )


# --- 정규화 ---

_REGION_SPLIT_RE = re.compile(r"[,·ㆍ/]|및|또는")
_SPACE_RE = re.compile(r"\s+")
_NON_DIGIT_RE = re.compile(r"[^0-9]")


def normalize_region(text: str) -> list[str]:
    """지역 문자열 → 시·도 정규 키 목록(토큰마다 1개, 토큰 순, 중복 제거 — X14).

    NFC → `[,·ㆍ/]|및|또는`으로 분리 → 토큰 공백 제거 → 토큰 안 어디든(괄호 안 포함) 나오는
    `REGION_ALIASES` 변형 중 가장 긴 것, 길이가 같으면 먼저 나온 것의 정규 키. 변형이 없으면
    (공백을 뗀) 토큰을 그대로 둔다.
    """
    if not isinstance(text, str):
        return []
    out: list[str] = []
    for raw in _REGION_SPLIT_RE.split(unicodedata.normalize("NFC", text)):
        token = _SPACE_RE.sub("", raw)
        if not token:
            continue
        best: tuple[int, int] | None = None  # (길이, -위치) 최대
        best_key = token
        for key, variants in REGION_ALIASES.items():
            for variant in variants:
                pos = token.find(variant)
                if pos < 0:
                    continue
                rank = (len(variant), -pos)
                if best is None or rank > best:
                    best, best_key = rank, key
        out.append(best_key)
    return list(dict.fromkeys(out))


def _digits(text: object) -> str:
    """숫자만 남긴 문자열(세부품명번호 비교용). 문자열이 아니면 빈 문자열."""
    return _NON_DIGIT_RE.sub("", text) if isinstance(text, str) else ""


def _norm_name(text: str) -> str:
    """인증 이름 비교 정규화: NFC·공백 제거·소문자."""
    return _SPACE_RE.sub("", unicodedata.normalize("NFC", text)).lower()


def norm_compact(text: str) -> str:
    """비교용 정규화: NFC → 공백(`\\s+`) 제거.

    실적 keyword·사람 확인 기록 키에 쓴다. OTHER 재분류는 공백을 남기는 `norm_clause`를 쓴다.
    """
    return _SPACE_RE.sub("", unicodedata.normalize("NFC", text))


_STAFFING_HASH_FIELDS: tuple[str, ...] = (
    "role",
    "grade",
    "count",
    "resident",
    "location",
    "min_years",
    "notes",
)


def eligibility_rule_payload(text: str) -> dict[str, object]:
    """원 EligibilityRule.text만으로 만드는 안정 판정 항목 payload."""
    return {"schema_version": 1, "origin": "eligibility", "text": norm_compact(text)}


def staffing_requirement_payload(requirement: StaffingReq) -> dict[str, object]:
    """StaffingReq의 의미 조건 7개만 원 필드 순서로 투영한다(evidence 제외)."""
    dumped = requirement.model_dump(mode="json")
    return {name: dumped[name] for name in _STAFFING_HASH_FIELDS}


def staffing_capacity_rule_payload(facts: RfpFacts) -> dict[str, object]:
    return {
        "schema_version": 1,
        "origin": "staffing_capacity",
        "requirements": [staffing_requirement_payload(item) for item in facts.staffing],
        "consortium_allowed": facts.contract_terms.consortium.allowed,
        "subcontract_allowed": facts.contract_terms.subcontract.allowed,
    }


def onsite_location_rule_payload(requirement: StaffingReq) -> dict[str, object]:
    return {
        "schema_version": 1,
        "origin": "onsite_location",
        "requirement": staffing_requirement_payload(requirement),
    }


def rule_payload_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def eligibility_rule_hash(text: str) -> str:
    return rule_payload_hash(eligibility_rule_payload(text))


def _is_count(value: object) -> bool:
    """bool이 아닌 int(인원·연도 등 확정 정수)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _known_text(value: object) -> bool:
    """의미 있는 문자열 값(빈 값·"unknown" 아님)."""
    return isinstance(value, str) and bool(value.strip()) and value != UNKNOWN


@dataclass
class _CertInventory:
    names: list[str] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)


def _profile_cert_inventory(reader: _CompanyReader) -> _CertInventory:
    """프로필 인증·등록 이름 목록(`CERT_LABELS`, 등장 순). 유효기간은 보지 않는다.

    `other_certs`의 이름은 gs_cert 다음에, 각 이름 뒤에 `OTHER_CERT_ALIASES` 별칭을 붙인다.
    중복은 처음 등장만 남긴다.
    """
    reg = reader.profile.registrations
    names: list[str] = []
    unknown_fields: list[str] = []
    fixed_optional_fields = {
        "venture": ("type", "since", "valid_until"),
        "innobiz": ("since", "valid_until"),
        "mainbiz": ("since", "valid_until"),
        "specialized_research_business": ("since", "field"),
        "engineering_business_report": ("since", "field"),
        "industrial_design_company": ("since", "field"),
        "performance_sharing_company": ("since",),
        "military_designated_company": ("since",),
    }
    for key in ("venture", "innobiz", "mainbiz"):
        value, unknown = reader.optional_present(f"registrations.{key}", fixed_optional_fields[key])
        unknown_fields.extend(unknown)
        if value is True:
            names.extend(CERT_LABELS[key])
    rnd_type, unknown = reader.optional_value("registrations.rnd_institute", "type")
    unknown_fields.extend(unknown)
    if _known_text(rnd_type):
        names.append(rnd_type)
    for key in (
        "specialized_research_business",
        "engineering_business_report",
        "industrial_design_company",
        "performance_sharing_company",
        "military_designated_company",
    ):
        value, unknown = reader.optional_present(f"registrations.{key}", fixed_optional_fields[key])
        unknown_fields.extend(unknown)
        if value is True:
            names.extend(CERT_LABELS[key])
    iso_names, unknown = _trusted_list_identifiers(reader, "registrations.iso", reg.iso, "std")
    names.extend(f"ISO {value}" for value in iso_names)
    unknown_fields.extend(unknown)
    cloud_names, unknown = _trusted_list_identifiers(
        reader, "registrations.cloud_certs", reg.cloud_certs, "name"
    )
    names.extend(cloud_names)
    unknown_fields.extend(unknown)
    esg_has, unknown = reader.optional_value("registrations.esg_cert", "has")
    unknown_fields.extend(unknown)
    if esg_has is True:
        names.extend(CERT_LABELS["esg_cert"])
    gs_cert = reader.value("registrations.gs_cert")
    if isinstance(gs_cert, list):
        names.extend(g for g in gs_cert if _known_text(g))
        if gs_cert:
            names.extend(CERT_LABELS["gs_cert"])
    else:
        unknown_fields.append("registrations.gs_cert")
    other_names, unknown = _trusted_list_identifiers(
        reader, "registrations.other_certs", reg.other_certs, "name"
    )
    unknown_fields.extend(unknown)
    for value in other_names:
        if _known_text(value):
            names.append(value)
            names.extend(OTHER_CERT_ALIASES.get(_norm_name(value), ()))
    return _CertInventory(
        names=list(dict.fromkeys(names)),
        unknown_fields=list(dict.fromkeys(unknown_fields)),
    )


def _trusted_list_identifiers(
    reader: _CompanyReader,
    path: str,
    raw_items: Iterable[object],
    id_key: str,
) -> tuple[list[str], list[str]]:
    """Return trusted structural IDs without requiring provenance on the ID leaf itself.

    A confirmed list path proves completeness and membership.  Otherwise, an exact confirmed
    item path proves that item.  The ID leaf is accepted only as compatibility for existing
    sidecars; unannotated structural IDs are never promoted from the raw profile.
    """
    complete = reader.value(path)
    if isinstance(complete, list):
        return (
            [
                value
                for item in complete
                if isinstance(item, dict) and _known_text(value := item.get(id_key))
            ],
            [],
        )

    trusted: list[str] = []
    for idx, item in enumerate(raw_items):
        identifier = getattr(item, id_key)
        item_path = _item_path(path, identifier, idx)
        item_evidence = reader.get(item_path)
        if reader.view.accepts(item_evidence["effective_level"]):
            item_value = item_evidence["value"]
            if isinstance(item_value, dict) and _known_text(item_value.get(id_key)):
                trusted.append(item_value[id_key])
                continue

        # Existing sidecars may put evidence on the semantic name even though it is also the
        # stable ID.  Consume it only when explicitly confirmed; never request it as a missing
        # field when no such metadata exists.
        id_path = f"{item_path}.{id_key}"
        if reader.has_provenance(id_path):
            id_evidence = reader.get(id_path)
            if reader.view.accepts(id_evidence["effective_level"]) and _known_text(
                id_evidence["value"]
            ):
                trusted.append(id_evidence["value"])
    # Confirming the collection path resolves both membership and completeness.  Exact item and
    # legacy ID paths are audit alternatives, not additional mandatory user actions.
    return trusted, [path]


def _profile_cert_names(reader: _CompanyReader) -> list[str]:
    return _profile_cert_inventory(reader).names


def profile_cert_names(
    profile: CompanyInput, *, evidence_view: CompanyEvidenceView | None = None
) -> list[str]:
    return _profile_cert_names(_CompanyReader(_as_evidence_view(profile, evidence_view)))


# --- 판정 공통 ---


@dataclass
class _Judgment:
    """규칙 하나의 판정. `action`은 행별 문구(action 규칙 2), `fallback`은 unknown_fields가 빈
    UNKNOWN의 고정 문구(규칙 5)."""

    verdict: Verdict
    company_value: str
    unknown_fields: list[str] = field(default_factory=list)
    action: str | None = None
    fallback: str = ACTION_CHECK_SOURCE


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    return str(value)


def _kv(pairs: Iterable[tuple[str, object]]) -> str:
    """company_value 포맷 `키=값; 키=값`(값이 없으면 "-")."""
    text = "; ".join(f"{k}={_fmt(v)}" for k, v in pairs)
    return text or "-"


def _action(j: _Judgment) -> str | None:
    if j.verdict == "PASS":
        return None
    if j.action is not None:
        return j.action
    if j.verdict == "FAIL":
        return FAIL_ACTION
    if j.unknown_fields:
        return UNKNOWN_HINT_PREFIX + hint_for(j.unknown_fields[0])
    return j.fallback


def _result(
    code: GateCode,
    rule_text: str,
    evidence: list[Evidence],
    j: _Judgment,
    input_fields: Iterable[str] = (),
    *,
    rule_hash: str,
) -> GateResult:
    fields = list(dict.fromkeys(j.unknown_fields))
    j.unknown_fields = fields
    return GateResult(
        code=code,
        rule_text=rule_text,
        company_value=j.company_value,
        verdict=j.verdict,
        evidence=[e.model_copy(deep=True) for e in evidence],
        action=_action(j),
        unknown_fields=fields,
        input_fields=list(dict.fromkeys(input_fields)),
        rule_hash=rule_hash,
    )


def _list_label(key_value: object, idx: int) -> str:
    """목록 항목 경로의 식별 키. 빈 문자열이 아닌 문자열은 공백도 원문 그대로 보존한다."""
    return key_value if isinstance(key_value, str) and key_value else str(idx)


# --- eligibility 규칙 ---

_RuleFn = Callable[[EligibilityRule, _CompanyReader, date], _Judgment]


def _size_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    size = reader.value("company.size")
    cv = _kv([("company.size", size)])
    if size in ("중소기업", "소상공인"):
        return _Judgment("PASS", cv)
    if size == "대기업":
        return _Judgment("FAIL", cv)
    if size == "중견기업":
        return _Judgment("RISK", cv, action=ACTION_MID_SIZE_RISK)
    return _Judgment("UNKNOWN", cv, ["company.size"])


def _sme_allowed_classifications(text: str) -> frozenset[str] | None:
    """보수적으로 SME 요구 분류를 읽는다. 부정·예외·충돌은 사람이 확인한다."""
    compact = norm_compact(text)
    if any(
        token in compact
        for token in (
            "제외",
            "예외",
            "아닌",
            "아니",
            "않",
            "비해당",
            "미해당",
            "불인정",
            "단,",
        )
    ):
        return None
    # A broad SME category joined explicitly with a narrower category remains the broad union.
    # Check this before looking for "소기업": it is also a substring of "중소기업".
    broad = r"(?:중소기업|중·소기업)(?:자)?(?:확인서)?"
    separator = r"(?:또는|및|·|/)"
    if re.search(rf"(?:{broad}{separator}|{separator}{broad})", compact):
        return frozenset({"중기업", "소기업", "소상공인"})
    if "소기업또는소상공인" in compact or "소기업·소상공인" in compact:
        return frozenset({"소기업", "소상공인"})
    # 중·소기업·소상공인은 공고에서 중소기업 전체를 열거한 표현이다.
    if "중·소기업·소상공인" in compact:
        return frozenset({"중기업", "소기업", "소상공인"})
    # 확인서·법 이름의 "중소기업"은 분류 요구가 아니다. 이를 걷어낸 뒤 좁은 분류를 먼저 본다.
    requirement = (
        compact.replace("중소기업확인서", "")
        .replace("중소기업기본법", "")
        .replace("중·소기업자", "")
        .replace("중·소기업", "")
    )
    has_small = re.search(r"(?<!중)소기업", requirement) is not None
    has_micro = "소상공인" in requirement
    if has_small and has_micro:
        return None
    if has_small:
        return frozenset({"소기업"})
    if has_micro:
        return frozenset({"소상공인"})
    if "중소기업" in compact or "중·소기업" in compact:
        return frozenset({"중기업", "소기업", "소상공인"})
    return None


def _sme_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    base = "registrations.sme_certificate"
    allowed = _sme_allowed_classifications(rule.text)
    if allowed is None:
        return _Judgment("UNKNOWN", "-", fallback=ACTION_CHECK_SOURCE)
    status = reader.value(f"{base}.status")
    cv = _kv([(f"{base}.status", status)])
    if status == "valid":
        valid_until = reader.value(f"{base}.valid_until")
        cv = _kv([(f"{base}.status", status), (f"{base}.valid_until", valid_until)])
        until = profile_date(valid_until, end_of_month=True)
        if until is None:
            return _Judgment("UNKNOWN", cv, [f"{base}.valid_until"])
        if until < as_of:
            return _Judgment("FAIL", cv, action=ACTION_RENEWAL)
        classification = reader.value(f"{base}.classification")
        cv = _kv(
            [
                (f"{base}.status", status),
                (f"{base}.valid_until", valid_until),
                (f"{base}.classification", classification),
            ]
        )
        if classification == UNKNOWN:
            return _Judgment("UNKNOWN", cv, [f"{base}.classification"])
        if classification in allowed:
            return _Judgment("PASS", cv)
        # 소기업 단일 요구에 소상공인을 대입하는 포함관계는 명백한 불일치로 단정하지 않는다.
        if allowed == frozenset({"소기업"}) and classification == "소상공인":
            return _Judgment("UNKNOWN", cv, fallback=ACTION_CHECK_SOURCE)
        return _Judgment("FAIL", cv)
    if status in ("expired", "none"):
        return _Judgment("FAIL", cv)
    return _Judgment("UNKNOWN", cv, [f"{base}.status"])


def _direct_production_rule(
    rule: EligibilityRule, reader: _CompanyReader, as_of: date
) -> _Judgment:
    base = "registrations.direct_production"
    raw_items = [x for x in (rule.params.item_no or []) if _digits(x)]
    required = list(dict.fromkeys(_digits(x) for x in raw_items))
    if not required:
        return _Judgment("UNKNOWN", "-", action=ACTION_ITEM_NO_MISSING)
    raw_by_digits = {}
    for x in raw_items:
        raw_by_digits.setdefault(_digits(x), x)

    pairs: list[tuple[str, object]] = []
    fields: list[str] = []
    any_pass = False
    all_confirmed_fail = True
    raw_list = reader.profile.registrations.direct_production
    for req in required:
        matches = [(idx, d) for idx, d in enumerate(raw_list) if _digits(d.item_no) == req]
        if not matches:
            pairs.append((f"{base}[{raw_by_digits[req]}]", "목록에 없음"))
            if not reader.list_complete(base):
                fields.append(base)
                all_confirmed_fail = False
            continue
        for idx, d in matches:
            path = _item_path(base, d.item_no, idx)
            status = reader.value(f"{path}.status")
            pairs.append((f"{path}.status", status))
            if status == "valid":
                valid_until = reader.value(f"{path}.valid_until")
                pairs.append((f"{path}.valid_until", valid_until))
                until = profile_date(valid_until, end_of_month=True)
                if until is None:
                    fields.append(f"{path}.valid_until")
                    all_confirmed_fail = False
                elif until >= as_of:
                    any_pass = True
            elif status not in ("none", "expired"):
                fields.append(f"{path}.status")
                all_confirmed_fail = False
    if not any_pass and all_confirmed_fail and not reader.list_complete(base):
        fields.append(base)
        all_confirmed_fail = False
    cv = _kv(pairs)
    if any_pass:
        return _Judgment("PASS", cv)
    if all_confirmed_fail:
        return _Judgment("FAIL", cv)
    return _Judgment("UNKNOWN", cv, fields, fallback=ACTION_CHECK_HOLDING)


def _g2b_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    path = "registrations.g2b.registered"
    registered = reader.value(path)
    cv = _kv([(path, registered)])
    if registered is True:
        return _Judgment("PASS", cv)
    if registered is False:
        return _Judgment("FAIL", cv)
    return _Judgment("UNKNOWN", cv, [path])


def _industry_code_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    sources = [
        ("registrations.g2b.industry_codes", reader.value("registrations.g2b.industry_codes")),
        ("registrations.g2b.other_codes", reader.value("registrations.g2b.other_codes")),
    ]
    cv = _kv(sources)
    required = [c.strip() for c in (rule.params.industry_code or []) if c.strip()]
    if not required:
        return _Judgment("UNKNOWN", cv, fallback=ACTION_CHECK_SOURCE)
    held: set[str] = set()
    unknown_paths: list[str] = []
    for path, value in sources:
        if isinstance(value, list):
            held.update(str(v).strip() for v in value)
        else:
            unknown_paths.append(path)
    if any(code in held for code in required):
        return _Judgment("PASS", cv)
    if not unknown_paths:
        return _Judgment("FAIL", cv)
    return _Judgment("UNKNOWN", cv, unknown_paths)


def _sw_report_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    base = "registrations.sw_business_report"
    reported = reader.value(f"{base}.reported")
    latest_year = reader.value(f"{base}.latest_year")
    cv = _kv([(f"{base}.reported", reported), (f"{base}.latest_year", latest_year)])
    year_known = _is_count(latest_year)
    if reported is True:
        if not year_known:
            return _Judgment("UNKNOWN", cv, [f"{base}.latest_year"])
        if latest_year >= as_of.year - 1:  # type: ignore[operator]
            return _Judgment("PASS", cv)
        return _Judgment("UNKNOWN", cv, fallback=ACTION_CHECK_REPORT_YEAR)
    if reported is False:
        return _Judgment("FAIL", cv)
    fields = [f"{base}.reported"] + ([] if year_known else [f"{base}.latest_year"])
    return _Judgment("UNKNOWN", cv, fields)


def _region_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    region = reader.value("company.region")
    cv = _kv([("company.region", region)])
    targets: list[str] = []
    for text in rule.params.region or []:
        targets.extend(normalize_region(text))
    if not targets:
        return _Judgment("UNKNOWN", cv, fallback=ACTION_CHECK_SOURCE)
    if not _known_text(region):
        return _Judgment("UNKNOWN", cv, ["company.region"])
    if set(normalize_region(region)) & set(targets):
        return _Judgment("PASS", cv)
    return _Judgment("FAIL", cv)


def _debarment_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    path = "registrations.debarment"
    value = reader.value(path)
    cv = _kv([(path, value)])
    if value == "none":
        return _Judgment("PASS", cv)
    if value == "active":
        return _Judgment("FAIL", cv)
    if value == "none_known":
        return _Judgment("RISK", cv, action=ACTION_DEBARMENT_RISK)
    return _Judgment("UNKNOWN", cv, [path])  # 모델상 도달하지 않음(타입 불일치 대비)


def _tax_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    path = "registrations.tax_delinquency"
    value = reader.value(path)
    cv = _kv([(path, value)])
    if value == "none":
        return _Judgment("PASS", cv)
    if value == "exists":
        return _Judgment("FAIL", cv)
    return _Judgment("UNKNOWN", cv, [path])


def _required_cert_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    inventory = _profile_cert_inventory(reader)
    cv = _kv([("보유 인증·등록", inventory.names)])
    cert_name = rule.params.cert_name
    if not isinstance(cert_name, str) or not cert_name.strip():
        return _Judgment("UNKNOWN", cv, fallback=ACTION_CHECK_SOURCE)
    target = _norm_name(cert_name)
    for name in inventory.names:
        label = _norm_name(name)
        if label and (label in target or target in label):
            return _Judgment("PASS", cv)
    if inventory.unknown_fields:
        return _Judgment("UNKNOWN", cv, inventory.unknown_fields, fallback=ACTION_CHECK_HOLDING)
    return _Judgment("FAIL", cv)


# --- 실적 키워드 해석·매칭(GT-02) ---

# 불용어(tunable, perf_norm 형태): keyword 토큰 중 실적 title/domain 대조에 쓰지 않는 수식어.
PERF_STOPWORDS: frozenset[str] = frozenset(
    {
        "기업", "기관", "공공기관", "공공", "민간", "사업", "용역", "실적", "수행", "수행실적",
        "구축실적", "등", "관련", "분야", "최근", "이내", "이상", "년", "보유", "업체", "경험",
        "유사", "동종", "동일", "및", "또는",
    }
)  # fmt: skip

# 사업 유형 토큰(tunable): keyword 토큰 → 허용 실적 type(ProjectType) 집합. 고도화는 구축에
# 포함하지 않는다(보수적 기본값 — 공고마다 인정 여부가 다름).
_BUILD = frozenset({"구축", "개발"})
_REBUILD = frozenset({"구축", "고도화"})
_MAINTAIN = frozenset({"유지관리", "운영"})
PERF_TYPE_TOKENS: dict[str, frozenset[str]] = {
    "구축": _BUILD,
    "개발": _BUILD,
    "신규": _BUILD,
    "고도화": frozenset({"고도화"}),
    "개편": _REBUILD,
    "리뉴얼": _REBUILD,
    "유지관리": _MAINTAIN,
    "유지보수": _MAINTAIN,
    "운영": _MAINTAIN,
    "위탁운영": _MAINTAIN,
    "컨설팅": frozenset({"컨설팅"}),
    "물품": frozenset({"물품"}),
    "구입": frozenset({"물품"}),
    "납품": frozenset({"물품"}),
}

# 동의어 그룹(tunable, perf_norm 형태, 그룹끼리 겹치지 않음 — 겹치면 첫 그룹). 변형은 필드
# 매칭 전용이라 최소 길이 제한을 받지 않는다(예: "앱"). 홈페이지·챗봇 그룹은 설계 2.3
# (docs/design/2026-10-25-past-performance-capability.md)에서 넓혔다.
PERF_SYNONYMS: tuple[frozenset[str], ...] = (
    frozenset({"홈페이지", "누리집", "웹사이트", "웹페이지", "홈피", "포털"}),
    frozenset(
        {
            "챗봇",
            "chatbot",
            "대화형봇",
            "대화형",
            "에이전트",
            "ai에이전트",
            "rag",
            "민원응대",
            "상담봇",
        }
    ),  # fmt: skip
    frozenset({"모바일앱", "앱", "어플리케이션", "애플리케이션"}),
)

# 지식·역량 텍스트(설계 2.1·2.2)의 짧은 변형 경계 일치(설계 2.3, tunable). 이 길이 이하 변형은
# 앞뒤가 단어 문자(`[0-9a-z가-힣]`)가 아닐 때만 인정한다. 뒤에 조사 하나(`_PERF_PARTICLES`)는
# 붙어도 된다. 실적 title·domain 대조는 기존 부분 문자열 그대로다(지식이 없으면 기존 동작).
PERF_BOUNDARY_MAX_LEN = 2
_PERF_PARTICLES: tuple[str, ...] = (
    "으로", "에서", "에게", "까지", "부터", "이나",
    "을", "를", "은", "는", "의", "에", "와", "과", "로", "이", "가", "도", "나",
)  # fmt: skip
_PERF_WORD_CHARS = "0-9a-z가-힣"

_PERF_PAREN_RE = re.compile(r"[(（\[［][^)）\]］]*[)）\]］]")  # 괄호 구간(중첩 없음)
_PERF_SPLIT_RE = re.compile(r"[\s,·ㆍ/]+")  # 토큰 분리
_PERF_NUMBER_START_RE = re.compile(r"^\d")  # 수량 표현("3년", "2건") 토큰
_PERF_MIN_TOKEN_LEN = 2  # 핵심 토큰 최소 길이(숫자 시작 토큰은 길이와 무관하게 버림)
_PROJECT_TYPE_ORDER: tuple[str, ...] = get_args(ProjectType)  # company_value 유형 표기 순서


@dataclass(frozen=True)
class PerfKeyword:
    """해석된 실적 keyword.

    raw: params.keyword 원문. core: 핵심 토큰(perf_norm 형태, 등장 순, 중복 제거).
    types: 허용 실적 type 집합(유형 토큰의 합집합). 유형 토큰이 없으면 None(유형 필터 없음).
    """

    raw: str
    core: tuple[str, ...]
    types: frozenset[str] | None


def perf_norm(text: str) -> str:
    """실적 매칭용 정규화: NFC → casefold → 공백(`\\s+`) 제거(`norm_compact` + casefold)."""
    return _SPACE_RE.sub("", unicodedata.normalize("NFC", text).casefold())


def parse_perf_keyword(text: str) -> PerfKeyword:
    """keyword 문구를 핵심 토큰과 허용 유형으로 나눈다(spec GT-02 규칙 ①~⑤).

    NFC·casefold → 괄호 구간 제거 → 공백·`,`·`·`·`ㆍ`·`/`로 분리 → 토큰마다 유형 토큰
    (`PERF_TYPE_TOKENS`, 허용 집합 합집합)이면 유형으로, 아니면 불용어·길이 < 2·숫자 시작이면
    버리고 나머지는 핵심 토큰(등장 순, 중복 제거).
    """
    folded = unicodedata.normalize("NFC", text).casefold()
    stripped = _PERF_PAREN_RE.sub("", folded)
    core: list[str] = []
    types: set[str] = set()
    has_type = False
    for token in _PERF_SPLIT_RE.split(stripped):
        if not token:
            continue
        allowed = PERF_TYPE_TOKENS.get(token)
        if allowed is not None:
            has_type = True
            types |= allowed
            continue
        if (
            token in PERF_STOPWORDS
            or len(token) < _PERF_MIN_TOKEN_LEN
            or _PERF_NUMBER_START_RE.match(token)
        ):
            continue
        if token not in core:
            core.append(token)
    return PerfKeyword(raw=text, core=tuple(core), types=frozenset(types) if has_type else None)


def perf_variants(token: str) -> frozenset[str]:
    """token이 속한 `PERF_SYNONYMS` 그룹 전체(첫 그룹). 어느 그룹에도 없으면 `{token}`."""
    for group in PERF_SYNONYMS:
        if token in group:
            return group
    return frozenset({token})


@dataclass(frozen=True)
class PerfText:
    """지식·역량 대조 텍스트 하나. `folded`는 NFC·casefold(공백 유지), `compact`는 perf_norm."""

    folded: str
    compact: str


def perf_text(text: str) -> PerfText:
    folded = unicodedata.normalize("NFC", text).casefold()
    return PerfText(folded=folded, compact=_SPACE_RE.sub("", folded))


_PERF_BOUNDARY_CACHE: dict[str, re.Pattern[str]] = {}


def _boundary_pattern(variant: str) -> re.Pattern[str]:
    pattern = _PERF_BOUNDARY_CACHE.get(variant)
    if pattern is None:
        particles = "|".join(map(re.escape, _PERF_PARTICLES))
        pattern = re.compile(
            rf"(?<![{_PERF_WORD_CHARS}]){re.escape(variant)}(?:{particles})?"
            rf"(?![{_PERF_WORD_CHARS}])"
        )
        _PERF_BOUNDARY_CACHE[variant] = pattern
    return pattern


def perf_text_has(text: PerfText, variant: str) -> bool:
    """지식·역량 텍스트에 변형이 있는가(설계 2.3). 길이 ≤ `PERF_BOUNDARY_MAX_LEN`이면 단어
    경계 일치(뒤 조사 하나 허용), 그보다 길면 공백을 뗀 텍스트의 부분 문자열."""
    # 짧은 변형과 영문 변형(예: rag가 storage 안에서 맞지 않게)은 단어 경계 일치만 인정한다.
    if len(variant) <= PERF_BOUNDARY_MAX_LEN or variant.isascii():
        return _boundary_pattern(variant).search(text.folded) is not None
    return variant in text.compact


def keyword_match(
    item: PortfolioItem, kw: PerfKeyword, knowledge_text: str | None = None
) -> Literal["match", "type_unknown", "no"]:
    """실적 항목과 해석된 keyword 대조(spec GT-02 + 설계 2.1).

    핵심 토큰마다 동의어 변형 중 하나가 perf_norm(title) 또는 perf_norm(domain[*])에 부분
    문자열로 있거나, `knowledge_text`(그 실적의 회사 지식 실적 페이지 대조 텍스트)에
    `perf_text_has`로 있어야 한다(AND, 토큰마다 다른 필드여도 됨). 하나라도 없으면 "no".
    이어서 유형: types None 또는 item.type ∈ types → "match", item.type unknown →
    "type_unknown", 그 외 "no"."""
    fields = [perf_norm(item.title)] + [perf_norm(d) for d in item.domain if isinstance(d, str)]
    extra = perf_text(knowledge_text) if knowledge_text else None
    for token in kw.core:
        variants = perf_variants(token)
        if any(v in f for v in variants for f in fields):
            continue
        if extra is None or not any(perf_text_has(extra, v) for v in variants):
            return "no"
    if kw.types is None or item.type in kw.types:
        return "match"
    if item.type == UNKNOWN:
        return "type_unknown"
    return "no"


def _perf_keyword_suffix(kw: PerfKeyword) -> str:
    """PAST_PERFORMANCE company_value 접미: `; 키워드=[…]; 유형=[…]`(없는 값 `-`, 유형은 ProjectType
    선언 순)."""
    core = ", ".join(kw.core) or "-"
    types = "-"
    if kw.types is not None:
        types = ", ".join(t for t in _PROJECT_TYPE_ORDER if t in kw.types) or "-"
    return f"; 키워드=[{core}]; 유형=[{types}]"


def performance_amount(
    item: PortfolioItem, base: str, reader: _CompanyReader
) -> tuple[float | None, list[str]]:
    """실적 금액(spec 실적 규칙 3)과 미확인 경로.

    주사업자·하도급 = amount_krw, 공동수급 = amount_krw × share_pct / 100. amount_krw·share_pct
    (공동수급)·role 중 하나라도 unknown이면 금액 미확인(None)이고 그 경로들을 돌려준다(X18 —
    role unknown이면 주사업자로 가정하지 않는다).
    """
    paths: list[str] = []
    amount = reader.value(f"{base}.amount_krw")
    if not _is_count(amount):
        paths.append(f"{base}.amount_krw")
    role = reader.value(f"{base}.role")
    share = reader.value(f"{base}.share_pct") if role == "공동수급" else item.share_pct
    if role == "공동수급":
        if not isinstance(share, int | float) or isinstance(share, bool):
            paths.append(f"{base}.share_pct")
    elif role not in ("주사업자", "하도급"):
        paths.append(f"{base}.role")
    if paths:
        return None, paths
    if role == "공동수급":
        return amount * share / 100, []  # type: ignore[operator]
    return float(amount), []  # type: ignore[arg-type]


def _performance_keyword_match(
    reader: _CompanyReader, item: PortfolioItem, base: str, kw: PerfKeyword
) -> tuple[Literal["match", "type_unknown", "no", "unknown"], list[str]]:
    unknown: list[str] = []
    values: list[str] = []
    title_path = f"{base}.title"
    title = reader.value(title_path)
    if _known_text(title):
        values.append(perf_norm(title))
    else:
        unknown.append(title_path)
    domain_path = f"{base}.domain"
    domain = reader.value(domain_path)
    if isinstance(domain, list):
        values.extend(perf_norm(d) for d in domain if isinstance(d, str))
    else:
        unknown.append(domain_path)
    # 설계 2.1: 그 실적 ID의 회사 지식 실적 페이지(confirmed) 세 절 본문도 대조한다.
    knowledge = reader.portfolio_texts.get(item.id)
    extra = perf_text(knowledge) if knowledge else None
    for token in kw.core:
        variants = perf_variants(token)
        if any(v in value for v in variants for value in values):
            continue
        if extra is not None and any(perf_text_has(extra, v) for v in variants):
            continue
        return ("unknown", unknown) if unknown else ("no", [])
    if kw.types is None:
        return "match", []
    type_path = f"{base}.type"
    project_type = reader.value(type_path)
    if project_type in kw.types:
        return "match", []
    if project_type == UNKNOWN:
        return "type_unknown", [type_path]
    return "no", []


# 역량 대안(설계 2.2): 조항이 "실적 또는 (구축) 역량"·"역량을 보유"처럼 회사 역량을 대안으로
# 허용하는지. norm_compact(rule.text)에 찾는다. 부정·예외 단서가 있으면 대안으로 보지 않는다.
_CAPABILITY_ALT_RE = re.compile(r"실적(?:또는|혹은|이나)[가-힣A-Za-z]{0,8}?역량|역량(?:을|를)?보유")
_CAPABILITY_ALT_BLOCKERS: tuple[str, ...] = ("불인정", "인정하지", "제외", "아닌", "않")


def has_capability_alternative(text: str) -> bool:
    """조항 원문이 실적 대신 회사 역량을 허용하는가(설계 2.2)."""
    compact = norm_compact(text)
    if any(token in compact for token in _CAPABILITY_ALT_BLOCKERS):
        return False
    return _CAPABILITY_ALT_RE.search(compact) is not None


def _capability_texts(value: object) -> list[str]:
    """역량 값 하나의 대조 텍스트: 목록이면 문자열 원소, 솔루션 항목이면 name·desc."""
    if isinstance(value, list):
        return [t for t in value if _known_text(t)]
    if isinstance(value, dict):
        return [t for t in (value.get("name"), value.get("desc")) if _known_text(t)]
    return []


def _capability_paths(reader: _CompanyReader) -> list[str]:
    """역량 대조 범위(설계 2.2)의 경로: `capabilities.domains`, `capabilities.solutions[*]`,
    `capabilities.tech_stack.<키>`(구조만 읽는다 — 판정 입력으로 기록하지 않음)."""
    paths = ["capabilities.domains"]
    solutions = reader.raw_value("capabilities.solutions")
    if isinstance(solutions, list):
        for idx, item in enumerate(solutions):
            name = item.get("name") if isinstance(item, dict) else None
            paths.append(_item_path("capabilities.solutions", name, idx))
    stack = reader.raw_value("capabilities.tech_stack")
    if isinstance(stack, dict):
        paths.extend(f"capabilities.tech_stack.{encode_path_token(str(key))}" for key in stack)
    return paths


def _capability_decision_value(reader: _CompanyReader, path: str) -> object:
    """뷰가 수용한 역량 값. 솔루션 항목은 항목 경로가 수용되지 않으면 목록 경로 값에서 찾는다."""
    try:
        value = reader.value(path)
    except ValueError:  # 이름이 겹치는 솔루션 항목 등 경로가 하나를 가리키지 않음
        return UNKNOWN
    base = "capabilities.solutions"
    if value == UNKNOWN and path.startswith(f"{base}[") and reader.has_provenance(base):
        whole = reader.value(base)
        raw = reader.raw_value(path)
        if isinstance(whole, list) and isinstance(raw, dict):
            return next((item for item in whole if item == raw), UNKNOWN)
    return value


def _capability_match(reader: _CompanyReader, kw: PerfKeyword) -> list[str]:
    """핵심 토큰이 모두(AND) 한 역량 값 안에 동의어로 있는 역량 경로(등장 순, 중복 없음).

    원값이 일치하는 경로만 판정 값으로 읽는다(그 경로가 input_fields에 남는다). 일치는 뷰가
    수용한 값으로만 인정한다 — 수용되지 않은 값은 경로만 남기고 일치로 세지 않는다.
    """
    if not kw.core:
        return []

    def matches(text: str) -> bool:
        normalized = perf_text(text)
        return all(
            any(perf_text_has(normalized, v) for v in perf_variants(token)) for token in kw.core
        )

    matched: list[str] = []
    for path in _capability_paths(reader):
        try:
            raw = reader.raw_value(path)
        except ValueError:
            continue
        if not any(matches(t) for t in _capability_texts(raw)):
            continue
        if any(matches(t) for t in _capability_texts(_capability_decision_value(reader, path))):
            matched.append(path)
    return list(dict.fromkeys(matched))


def _performance_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    """실적 규칙(M2-03·GT-02 + 설계 2.1) 뒤 역량 대안(설계 2.2).

    실적 대조가 PASS가 아니고 조항에 역량 대안이 있으면 회사 역량을 대조한다. 일치하면 PASS이고
    company_value 끝에 `; 역량 근거=[경로…]`를 붙인다. 일치가 없으면(수용되지 않은 값뿐이어도)
    실적 대조 결과 그대로다.
    """
    judgment = _portfolio_performance_rule(rule, reader, as_of)
    if judgment.verdict == "PASS" or not has_capability_alternative(rule.text):
        return judgment
    keyword = rule.params.keyword
    if not isinstance(keyword, str) or not keyword.strip():
        return judgment
    paths = _capability_match(reader, parse_perf_keyword(keyword))
    if not paths:
        return judgment
    return _Judgment("PASS", judgment.company_value + f"; 역량 근거=[{', '.join(paths)}]")


def _portfolio_performance_rule(
    rule: EligibilityRule, reader: _CompanyReader, as_of: date
) -> _Judgment:
    params = rule.params
    required = params.amount_krw
    startup = _is_startup(reader, as_of)
    start, end = _performance_window(reader, as_of, params.years)
    fields: list[str] = []
    if startup is None:
        fields.append("company.founded")
    keyword = params.keyword
    kw = parse_perf_keyword(keyword) if isinstance(keyword, str) and keyword.strip() else None
    # keyword 문자열이 있는데 핵심 토큰·유형이 모두 지워지면(예: "유사 용역 수행 실적") 대조 근거가
    # 없다 → 후보를 만들지 않는다(모든 실적을 후보로 보면 근거 없는 PASS, 제약 2).
    blank_kw = kw is not None and not kw.core and kw.types is None

    confirmed = unconfirmed_amount = uncertain = 0
    known_sum = 0.0
    for idx, item in enumerate(() if blank_kw else reader.profile.portfolio):
        base = _item_path("portfolio", item.id, idx)
        completed = reader.value(f"{base}.completed")
        if completed is False:
            continue
        match, match_unknown = (
            _performance_keyword_match(reader, item, base, kw) if kw is not None else ("match", [])
        )
        if match == "no":
            continue
        type_unknown = match == "type_unknown"
        if match == "unknown":
            uncertain += 1
            fields.extend(match_unknown)
            continue
        period_end = reader.value(f"{base}.period.end")
        end_date = profile_date(period_end, end_of_month=True)
        if completed is True and end_date is not None:
            if end_date > end or (start is not None and end_date < start):
                continue  # 창 밖
            if type_unknown:
                # 확정 후보 자리지만 유형 미확인 → 불확실 후보(금액은 합계에 넣지 않는다)
                uncertain += 1
                fields.extend(match_unknown)
                if required is not None:
                    fields += performance_amount(item, base, reader)[1]
                continue
            confirmed += 1
            value, amount_paths = performance_amount(item, base, reader)
            if value is None:
                unconfirmed_amount += 1
                if required is not None:
                    fields += amount_paths
            else:
                known_sum += value
            continue
        # 불확실 후보: completed unknown, 또는 completed True인데 종료일 미상(창 판정 불가)
        uncertain += 1
        if completed is not True:
            fields.append(f"{base}.completed")
        if end_date is None:
            fields.append(f"{base}.period.end")
        if type_unknown:
            fields.extend(match_unknown)
        if required is not None:
            fields += performance_amount(item, base, reader)[1]

    startup_label = {True: "예", False: "아니오", None: "미상"}[startup]
    cv = (
        f"창={start.isoformat() if start else '-'}~{end.isoformat()}; 창업특례={startup_label}; "
        f"확정후보={confirmed}; 금액확인합계={known_sum:.0f}; 금액미확인={unconfirmed_amount}; "
        f"불확실={uncertain}"
    )
    if kw is not None:
        cv += _perf_keyword_suffix(kw)
    if blank_kw:
        return _Judgment("UNKNOWN", cv, fields, fallback=ACTION_CHECK_PORTFOLIO)
    if required is None:
        if confirmed >= 1:
            return _Judgment("PASS", cv, fields)
        if not reader.list_complete("portfolio"):
            fields.append("portfolio")
            return _Judgment("UNKNOWN", cv, fields, fallback=ACTION_CHECK_PORTFOLIO)
        if uncertain or fields:
            return _Judgment("UNKNOWN", cv, fields, fallback=ACTION_CHECK_PORTFOLIO)
        return _Judgment("FAIL", cv)
    if known_sum >= required:
        return _Judgment("PASS", cv, fields)
    if unconfirmed_amount or uncertain:
        return _Judgment("UNKNOWN", cv, fields)
    if confirmed == 0:
        if not reader.list_complete("portfolio"):
            fields.append("portfolio")
            return _Judgment("UNKNOWN", cv, fields, fallback=ACTION_CHECK_PORTFOLIO)
        if fields:
            return _Judgment("UNKNOWN", cv, fields, fallback=ACTION_CHECK_PORTFOLIO)
        return _Judgment("FAIL", cv)
    if not reader.list_complete("portfolio"):
        fields.append("portfolio")
        return _Judgment("UNKNOWN", cv, fields)
    return _Judgment("FAIL", cv, fields)


def _other_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    return _Judgment("UNKNOWN", "-", fallback=ACTION_CHECK_SOURCE)


# --- 재분류 규칙(GT-01): OTHER 조항에서만 쓰인다(EligibilityCode에는 없음) ---


def _consortium_condition_rule(
    rule: EligibilityRule, reader: _CompanyReader, as_of: date
) -> _Judgment:
    """공동수급 조건부 조항·단독입찰 전용 조항: 기본 입찰 형태가 단독이면 해당 없음(PASS)."""
    path = "policy.default_bid_mode"
    mode = reader.value(path)
    cv = _kv([(path, mode)])
    if mode == "solo":
        return _Judgment("PASS", cv)
    if mode == "consortium":
        return _Judgment("UNKNOWN", cv, action=ACTION_CHECK_CONSORTIUM)
    return _Judgment("UNKNOWN", cv, [path])


def _insolvency_rule(rule: EligibilityRule, reader: _CompanyReader, as_of: date) -> _Judgment:
    """부도·파산·회생절차 조항."""
    path = "registrations.insolvency"
    value = reader.value(path)
    cv = _kv([(path, value)])
    if value == "none":
        return _Judgment("PASS", cv)
    if value == "active":
        return _Judgment("FAIL", cv)
    return _Judgment("UNKNOWN", cv, [path])


_RULES: dict[str, _RuleFn] = {
    "LARGE_CORP_EXCLUDED": _size_rule,
    "MUTUAL_INVEST_GROUP_EXCLUDED": _size_rule,
    "SME_CERT": _sme_rule,
    "DIRECT_PRODUCTION": _direct_production_rule,
    "G2B_REGISTERED": _g2b_rule,
    "INDUSTRY_CODE": _industry_code_rule,
    "SW_BUSINESS_REPORT": _sw_report_rule,
    "REGION_LIMIT": _region_rule,
    "DEBARMENT": _debarment_rule,
    "TAX_DELINQUENCY": _tax_rule,
    "PAST_PERFORMANCE": _performance_rule,
    "REQUIRED_CERT": _required_cert_rule,
    "OTHER": _other_rule,
    "CONSORTIUM_CONDITION": _consortium_condition_rule,
    "INSOLVENCY": _insolvency_rule,
}


# --- OTHER 재분류(GT-01, X77) — 허용 목록(리뷰 2회 뒤 사용자 결정 2026-10-23) ---

# 재분류 비교용 문자 통일(정규화 규칙의 일부). 낫표 변형 → 「」, 가운뎃점 변형 → ·, 전각 괄호·쉼표 →
# 반각. 공백은 지우지 않는다(공백 제거 비교가 "도급"→"부도" 같은 단어 경계 오탐을 만들었다).
_CLAUSE_CHAR_MAP = str.maketrans(
    {
        "｢": "「",
        "『": "「",
        "｣": "」",
        "』": "」",
        "ㆍ": "·",
        "∙": "·",
        "・": "·",
        "･": "·",
        "‧": "·",
        "（": "(",
        "）": ")",
        "，": ",",
    }
)
_CLAUSE_DOT_SPACE_RE = re.compile(r" ?· ?")  # 가운뎃점 앞뒤 공백
_CLAUSE_OPEN_SPACE_RE = re.compile(r"([(「]) ")  # 여는 괄호 뒤 공백
_CLAUSE_CLOSE_SPACE_RE = re.compile(r" ([)」,])")  # 닫는 괄호·쉼표 앞 공백
_CLAUSE_END_PERIOD_RE = re.compile(r" ?[.。]$")  # 끝 마침표 하나


def norm_clause(text: str) -> str:
    """재분류 템플릿 비교용 정규화(GT-01 허용 목록). NFC → 문자 통일(`_CLAUSE_CHAR_MAP`) → 공백
    접기(`\\s+` → 공백 1개, 앞뒤 제거) → 가운뎃점 앞뒤·여는 괄호 뒤·닫는 괄호/쉼표 앞 공백 제거 →
    끝 마침표 하나 제거. 단어 사이 공백은 남긴다(`norm_compact`와 다름).
    """
    t = unicodedata.normalize("NFC", text).translate(_CLAUSE_CHAR_MAP)
    t = _SPACE_RE.sub(" ", t).strip()
    t = _CLAUSE_DOT_SPACE_RE.sub("·", t)
    t = _CLAUSE_OPEN_SPACE_RE.sub(r"\1", t)
    t = _CLAUSE_CLOSE_SPACE_RE.sub(r"\1", t)
    return _CLAUSE_END_PERIOD_RE.sub("", t)


@dataclass(frozen=True)
class OtherReclass:
    """재분류 표 한 행. `templates`는 `norm_clause(text)` **전체**에 `fullmatch`하는 정규식이다
    (대소문자 무시). 조항 전체가 템플릿 하나와 통째로 맞을 때만 재분류하고, 그 밖(다른 요건이
    덧붙거나 문형이 다른 조항)은 OTHER UNKNOWN(→ 사람 확인 `gate confirm`)으로 남긴다.
    템플릿의 가변 부분은 선택적 수식어·조사·어미·구분자 변형뿐이다(`.` 같은 임의 문자 없음).
    `keyword`가 있으면 재분류 params는 `RuleParams(keyword=keyword)`.
    """

    code: GateCode  # 재분류 대상(`_RULES` 키)
    templates: tuple[re.Pattern[str], ...]
    keyword: str | None = None


def _tpl(*parts: str) -> re.Pattern[str]:
    """템플릿 조각을 이어 붙여 컴파일(대소문자 무시). 조각은 `norm_clause` 형태로 적는다."""
    return re.compile("".join(parts), re.IGNORECASE)


# 템플릿 조각(norm_clause 형태: 단어 사이 공백 1개, 가운뎃점·괄호 안쪽 공백 없음)
# INSOLVENCY: 부도·파산·회생절차 나열(1~3개, 구분자 · , 및 또는) + "중에 있지 아니한 업체" 어미 변형
_INSOLV_ITEM = r"(?:부도|파산|회생절차|회생)"
_INSOLV_SEP = r"(?:·|, ?| 및 | 또는 )"
_INSOLV_STATE = r"(?: 진행)? (?:중에 있지 (?:아니한|않은)|중이 아닌)"
_SUBJECT = r" (?:업체|자|기업)"
# CONSORTIUM_CONDITION: 공동이행 원칙(선택) + 구성원 모두 입찰참가자격 구비
_CONS_LEAD = r"(?:공동수급은 공동이행방식을 원칙으로 하며, ?)?"
_CONS_MEMBERS = r"공동수급체 구성원 (?:모두|전원)(?:가|이|는)? "
_CONS_SCOPE = r"(?:본 입찰에서 요구하는 |본 입찰에 필요한 )?"
_BID_QUAL = r"입찰 ?참가 ?자격"
_MUST_HAVE = r"을 (?:갖추어야|갖춰야) (?:함|한다|합니다)"
# CONSORTIUM_CONDITION(단독입찰 전용): "본 사업은 단독입찰만 허용하며, 공동수급(공동이행)을 허용하지
# 않음" 류. 회사가 단독으로 입찰하면 해당 없음이라 같은 규칙으로 판정한다(설계 2.2).
_SOLO_SUBJ = r"(?:본 (?:사업|입찰|용역)(?:은|는|에서는) )?"
_SOLO_ONLY = r"단독 ?입찰만 (?:허용|가능)(?:하며|하고|함|합니다|한다)?"
_CONS_KIND = (
    r"(?:\((?:공동이행|분담이행|공동 ?또는 ?분담이행|공동이행 ?또는 ?분담이행)(?: ?방식)?\))?"
)
_NO_CONS = (
    rf"공동 ?수급{_CONS_KIND}(?:을|은|는)? "
    r"(?:허용하지 (?:않음|아니함|않는다|않습니다)|불허(?:함)?|불가(?:함)?)"
)
# LARGE_CORP_EXCLUDED: 소프트웨어 진흥법 제48조에 따른 중소 SW사업자 사업참여 지원 지침 준수
_SW_LAW = r"「?소프트웨어 ?진흥법」? 제48조(?:\(중소 ?소프트웨어 ?사업자의 사업 ?참여 ?지원\))?"
_SW_GUIDE = r"「?중소 ?소프트웨어 ?사업자의 사업 ?참여 ?지원에 관한 지침」?"
# G2B_REGISTERED: 국가계약법 시행령 제12조(+시행규칙 제14조)에 따른 경쟁입찰 참가자격
_CONTRACT_LAW = r"(?:국가를 당사자로 하는 계약에 관한 법률|국가계약법)"
_DECREE_12 = rf"「?{_CONTRACT_LAW} 시행령」? 제12조(?:\(경쟁입찰의 참가 ?자격\))?"
_RULE_14 = (
    rf"(?:동법 시행규칙|같은 법 시행규칙|「?{_CONTRACT_LAW} 시행규칙」?) 제14조"
    r"(?:\(입찰 ?참가 ?자격 ?요건의 증명\))?"
)
_BY_RULE = r" ?(?:규정에 의한|규정에 따른|에 의한|에 따른) "
_COMPETITIVE_QUAL = r"경쟁입찰 ?참가 ?자격"
_HAS_QUAL = r"(?:을 (?:갖추어야 (?:하며|함|한다|합니다)|갖춘 (?:업체|자|기업)))?"
_G2B_SYSTEM = r"(?:조달청|나라장터|국가종합전자조달시스템(?:\(나라장터\))?)(?:에)? "
# PAST_PERFORMANCE(챗봇): (AI) 챗봇(생성형 AI 기반 포함) 구축 실적 (또는 구축 역량) + 보유 어미.
# 괄호는 범위를 넓히는 "(… 포함)"만 허용한다 — "(LLM 기반)"처럼 좁히는 한정어는 실적 규칙이
# 판정하지 못하므로 재분류하지 않는다(OTHER → 사람 확인). keyword "챗봇 구축"으로 유형을
# 구축·개발로 한정.
_CHATBOT = r"(?:AI ?|인공지능 ?)?챗봇(?:\((?:생성형 ?AI|LLM|대화형 ?AI)(?: 기반)? 포함\))?"
_PERF_OR_CAP = r" 구축 실적(?: 또는 (?:구축 )?역량)?"
_HOLDS = rf"(?:(?:을|를) 보유한{_SUBJECT}|이 있는{_SUBJECT}| 보유(?:{_SUBJECT})?)?"

# tunable. 순서 = 우선순위(위에서 먼저 맞는 것; fullmatch라 행끼리 겹치지 않는 것이 정상 —
# 테스트가 허용 예시마다 맞는 행이 하나뿐인지 확인한다). 조항 표현이 늘면 템플릿을 추가한다.
OTHER_RECLASS: tuple[OtherReclass, ...] = (
    OtherReclass(
        "INSOLVENCY",
        (_tpl(_INSOLV_ITEM, rf"(?:{_INSOLV_SEP}{_INSOLV_ITEM}){{0,2}}", _INSOLV_STATE, _SUBJECT),),
    ),
    OtherReclass(
        "CONSORTIUM_CONDITION",
        (
            _tpl(_CONS_LEAD, _CONS_MEMBERS, _CONS_SCOPE, _BID_QUAL, _MUST_HAVE),
            _tpl(_SOLO_SUBJ, _SOLO_ONLY, rf"(?:, ?{_NO_CONS})?"),
            _tpl(_SOLO_SUBJ, _NO_CONS),
        ),
    ),
    OtherReclass(
        "LARGE_CORP_EXCLUDED",
        (
            _tpl(
                rf"(?:{_SW_LAW} ?(?:에 따른|에 의한|및) )?",
                _SW_GUIDE,
                r"(?:을|를)? (?:준수|적용)(?:함|하여야 함|해야 함|한다)?",
            ),
            _tpl(
                rf"(?:{_SW_LAW} ?에 따라 )?",
                r"대기업인 소프트웨어 ?사업자(?:의)? (?:사업 ?)?참여(?:를)? ",
                r"제한(?:함|됨|한다|된다)?",
            ),
        ),
    ),
    OtherReclass(
        "G2B_REGISTERED",
        (
            _tpl(_DECREE_12, rf"(?: 및 {_RULE_14})?", _BY_RULE, _COMPETITIVE_QUAL, _HAS_QUAL),
            _tpl(_G2B_SYSTEM, _BID_QUAL, r" ?등록을 (?:마친|한|필한)", _SUBJECT),
        ),
    ),
    OtherReclass(
        "PAST_PERFORMANCE",
        (_tpl(_CHATBOT, _PERF_OR_CAP, _HOLDS),),
        keyword="챗봇 구축",
    ),
)
RECLASS_SUFFIX = " [재분류 OTHER→{code}]"
# 게이트 rule_text 접미(재분류 → 기준일 순)의 norm_compact 형태. 사람 확인 키 일치에 쓴다.
RULE_TEXT_SUFFIX_RE = re.compile(
    r"(?:\[재분류OTHER→[A-Z_]+\])?(?:\[기준일\d{4}-\d{2}-\d{2}(?:제출마감|공고일|실행일)\])?"
)


def reclassify_other(rule: EligibilityRule) -> tuple[GateCode, RuleParams] | None:
    """OTHER 조항의 재분류 코드와 그 규칙에 넘길 params. OTHER가 아니거나, `norm_clause(text)`
    전체와 맞는(`fullmatch`) 템플릿이 없으면 None(기존 OTHER UNKNOWN "원문 확인").

    `keyword`가 있는 행이면 `RuleParams(keyword=<keyword>)`(years·amount 없음), 아니면
    `rule.params` 그대로. 입력을 바꾸지 않는다.
    """
    if rule.code != "OTHER":
        return None
    text = norm_clause(rule.text)
    for entry in OTHER_RECLASS:
        if any(t.fullmatch(text) for t in entry.templates):
            if entry.keyword is not None:
                return entry.code, RuleParams(keyword=entry.keyword)
            return entry.code, rule.params
    return None


def _eligibility_gate(
    rule: EligibilityRule,
    view: CompanyEvidenceView,
    as_of: date,
    as_of_suffix: str,
    assumed_lists: list[str] | None = None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> GateResult:
    reader = _reader(view, assumed_lists, portfolio_texts)
    reclass = reclassify_other(rule)
    if reclass is not None:
        code, params = reclass
        judgment = _RULES[code](rule.model_copy(update={"params": params}), reader, as_of)
        rule_text = (
            rule.text
            + RECLASS_SUFFIX.format(code=code)
            + (as_of_suffix if code in DATE_GATE_CODES else "")
        )
        return _result(
            code,
            rule_text,
            [rule.evidence],
            judgment,
            reader.input_fields,
            rule_hash=eligibility_rule_hash(rule.text),
        )
    judgment = _RULES.get(rule.code, _other_rule)(rule, reader, as_of)
    rule_text = rule.text + (as_of_suffix if rule.code in DATE_GATE_CODES else "")
    return _result(
        rule.code,
        rule_text,
        [rule.evidence],
        judgment,
        reader.input_fields,
        rule_hash=eligibility_rule_hash(rule.text),
    )


# --- 계약조건 파생 게이트 ---


def _dedup_evidence(items: Iterable[Evidence]) -> list[Evidence]:
    """`(quote, section_id)` 기준 중복 제거, 처음 등장 순서 유지."""
    seen: set[tuple[str, str | None]] = set()
    out: list[Evidence] = []
    for ev in items:
        key = (ev.quote, ev.section_id)
        if key not in seen:
            seen.add(key)
            out.append(ev)
    return out


# tunable. 인원이 적히지 않은 요구 직무 하나를 몇 명으로 가정할지(설계
# docs/design/2026-10-25-gate-staffing-consortium.md 2.1). 자사 기술 인력이 가정 합계 이상이면 PASS.
STAFFING_UNKNOWN_COUNT_ASSUMED = 3


def _staffing_capacity_gate(
    facts: RfpFacts, view: CompanyEvidenceView, assumed_lists: list[str] | None = None
) -> GateResult | None:
    """공동수급·하도급 모두 불허면 자사 인력만으로 요구 인력(staffing 전체)을 채울 수 있는지.

    상주 여부와 무관하게 생성한다(mission "강원대 공동수급·하도급 불허"). PASS/RISK만 낸다.
    """
    terms = facts.contract_terms
    if not (terms.consortium.allowed is False and terms.subcontract.allowed is False):
        return None
    reqs = facts.staffing
    has_none = any(s.count is None for s in reqs)
    total = sum(s.count if s.count is not None else 1 for s in reqs)
    # 인원 미상 직무는 STAFFING_UNKNOWN_COUNT_ASSUMED명으로 가정해 충분 여부를 본다.
    assumed = sum(s.count if s.count is not None else STAFFING_UNKNOWN_COUNT_ASSUMED for s in reqs)
    by_grade: dict[str, int] = {}
    for s in reqs:
        if s.grade is not None:
            by_grade[s.grade] = by_grade.get(s.grade, 0) + (
                s.count if s.count is not None else STAFFING_UNKNOWN_COUNT_ASSUMED
            )

    reader = _reader(view, assumed_lists)
    staff = reader.value("people.total_tech_staff")
    grade_values = {
        g: reader.value(f"people.headcount_by_grade.{encode_path_token(g)}") for g in by_grade
    }
    cv = _kv(
        [("total_tech_staff", staff)]
        + [(f"headcount_by_grade.{g}", v) for g, v in grade_values.items()]
    )
    evidence = _dedup_evidence([*(s.evidence for s in reqs), *terms.evidence])

    if total == 0:
        rule_text = "공동수급·하도급 불허(인력 요건 미추출, 자사 단독 수행 필요)"
        judgment = _Judgment("RISK", cv, action=ACTION_STAFFING_RISK)
        return _result(
            "STAFFING_CAPACITY",
            rule_text,
            evidence,
            judgment,
            reader.input_fields,
            rule_hash=rule_payload_hash(staffing_capacity_rule_payload(facts)),
        )

    count_text = f"{total}명 이상(인원 미상 포함)" if has_none else f"{total}명"
    rule_text = f"공동수급·하도급 불허 + 요구 인력 {count_text}(자사 인력만으로 충족 필요)"
    fields: list[str] = []
    enough = True
    if has_none:
        cv += f"; 인원 미상 직무 가정={STAFFING_UNKNOWN_COUNT_ASSUMED}명씩(합계 {assumed}명)"
    if not _is_count(staff):
        fields.append("people.total_tech_staff")
        enough = False
    elif staff < assumed:
        enough = False
    for g, value in grade_values.items():
        if not _is_count(value):
            fields.append(f"people.headcount_by_grade.{encode_path_token(g)}")
            enough = False
        elif value < by_grade[g]:
            enough = False
    if enough:
        return _result(
            "STAFFING_CAPACITY",
            rule_text,
            evidence,
            _Judgment("PASS", cv),
            reader.input_fields,
            rule_hash=rule_payload_hash(staffing_capacity_rule_payload(facts)),
        )
    judgment = _Judgment("RISK", cv, fields, action=ACTION_STAFFING_RISK)
    return _result(
        "STAFFING_CAPACITY",
        rule_text,
        evidence,
        judgment,
        reader.input_fields,
        rule_hash=rule_payload_hash(staffing_capacity_rule_payload(facts)),
    )


def onsite_region_key(location: str | None) -> str:
    """상주 장소 → `ONSITE_REGION_KEYS` 지역 키(normalize_region 결과의 첫 해당 키), 없으면 기타."""
    if not location:
        return ONSITE_OTHER_KEY
    for key in normalize_region(location):
        if key in ONSITE_REGION_KEYS:
            return key
    return ONSITE_OTHER_KEY


def _onsite_gate(
    req: StaffingReq, view: CompanyEvidenceView, assumed_lists: list[str] | None = None
) -> GateResult:
    """상주 인력 하나의 상주 가능 판정. PASS/RISK만 낸다(`기타`는 max_people이 없어 PASS 불가)."""
    key = onsite_region_key(req.location)
    reader = _reader(view, assumed_lists)
    base = f"people.onsite_capacity.{encode_path_token(key)}"
    ok = reader.value(f"{base}.ok")
    has_max = key != ONSITE_OTHER_KEY
    max_people = reader.value(f"{base}.max_people") if has_max else None
    seoul_resident_ok = reader.value("policy.seoul_resident_ok")
    cv = _kv(
        [
            (f"onsite_capacity.{key}.ok", ok),
            ("max_people", max_people),
            ("policy.seoul_resident_ok", seoul_resident_ok),
        ]
    )
    fields: list[str] = []
    if not isinstance(ok, bool):
        fields.append(f"{base}.ok")
    if has_max and ok is not False and not _is_count(max_people):
        fields.append(f"{base}.max_people")

    count_text = f"{req.count}명" if req.count is not None else "인원 미상"
    location_text = req.location if req.location and req.location.strip() else "장소 미상"
    rule_text = f"{req.role} {count_text} 상주: {location_text}"
    passed = (
        ok is True
        and has_max
        and _is_count(max_people)
        and _is_count(req.count)
        and max_people >= req.count  # type: ignore[operator]
    )
    if passed:
        judgment = _Judgment("PASS", cv)
    else:
        judgment = _Judgment("RISK", cv, fields, action=f"{key} 상주 가능 인원 확인")
    return _result(
        "ONSITE_LOCATION",
        rule_text,
        [req.evidence],
        judgment,
        reader.input_fields,
        rule_hash=rule_payload_hash(onsite_location_rule_payload(req)),
    )


# --- 조합 ---


def _as_of_source_label(facts: RfpFacts, as_of: date) -> str:
    """기준일 출처 표기: as_of가 파싱된 마감일과 같으면 제출마감, 공고일과 같으면 공고일,
    둘 다 아니면 실행일."""
    if parse_leading_date(facts.schedule.submission_deadline) == as_of:
        return "제출마감"
    if parse_leading_date(facts.schedule.notice_date) == as_of:
        return "공고일"
    return "실행일"


def evaluate_gates_traced(
    facts: RfpFacts,
    profile: CompanyInput,
    *,
    as_of: date,
    evidence_view: CompanyEvidenceView | None = None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> tuple[list[GateResult], tuple[str, ...]]:
    """`evaluate_gates`와 같은 게이트 목록과, 가정으로 완전하다고 본 목록 경로(등장 순).

    모든 리더가 하나의 가정 목록 누적 리스트를 공유한다. 기본 뷰(confirmed·demo 수용)에서는
    목록을 가정하지 않으므로 둘째 값은 항상 비어 있다.
    """
    view = _as_evidence_view(profile, evidence_view)
    assumed_lists: list[str] = []
    suffix = f" [기준일 {as_of.isoformat()} {_as_of_source_label(facts, as_of)}]"
    results = [
        _eligibility_gate(rule, view, as_of, suffix, assumed_lists, portfolio_texts)
        for rule in facts.eligibility
    ]
    capacity = _staffing_capacity_gate(facts, view, assumed_lists)
    if capacity is not None:
        results.append(capacity)
    results.extend(
        _onsite_gate(req, view, assumed_lists) for req in facts.staffing if req.resident is True
    )
    return results, tuple(assumed_lists)


def evaluate_gates(
    facts: RfpFacts,
    profile: CompanyInput,
    *,
    as_of: date,
    evidence_view: CompanyEvidenceView | None = None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> list[GateResult]:
    """참가자격 게이트 목록: eligibility 항목마다 하나(문서 순) → STAFFING_CAPACITY(최대 1개)
    → ONSITE_LOCATION(상주 staffing마다, staffing 순).

    날짜 기준일을 쓰는 게이트(`DATE_GATE_CODES`)는 rule_text 끝에 ` [기준일 YYYY-MM-DD 출처]`를
    붙인다. evidence는 원천 Evidence의 복사본이다. 입력을 바꾸지 않으며 같은 입력이면 같은 결과다.

    `portfolio_texts`(실적 ID → 회사 지식 실적 페이지 대조 텍스트, `knowledge.load_portfolio_texts`)
    가 있으면 PAST_PERFORMANCE 키워드 대조에 더한다(설계 2.1). None·빈 값이면 지식 없는 판정이다.
    """
    return evaluate_gates_traced(
        facts,
        profile,
        as_of=as_of,
        evidence_view=evidence_view,
        portfolio_texts=portfolio_texts,
    )[0]
