"""평일 브리핑의 결정적 규칙 엔진 (RL-01 spec "결정적 점수와 제외").

I/O·DB·네트워크가 없는 순수 함수다. 입력은 세 가지다.

- 회사 규칙: lifecycle 확장점 `company_facts_projection`이 돌려준 실회사 확정 사실
  (`CompanyFactsProjection`). 제공자가 `confirmed`만 넘기지만 여기서 status를 **한 번 더**
  확인한다(이중 검사). `proposed`·`unknown`은 어떤 점수·제외에도 쓰이지 않는다.
- 후보: `Notice`(사전규격·입찰공고)와 `OrderPlan`을 spec의 stage별 매핑 표대로 읽은
  `BriefingCandidate`. 모집단·창·소유 사업기회 확인은 생성 service(STEP-003)가 한다.
- 규칙 파일: `briefing_policy.BriefingPolicy`(가중치·top_n·마감 경고·대기업 상수).

같은 입력이면 항상 같은 출력이다. 입력 순서와 사실 순서에 기대지 않도록 사실은
`fact_key`로, 후보는 전순서 키로 정렬한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
import unicodedata
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from ..extensions import CompanyFactsProjection
from . import name_matching
from .briefing_policy import BriefingPolicy

#: 후보 stage 전체(spec "기준일과 모집단").
STAGES = ("pre_spec", "bid_notice", "order_plan")

#: 키워드로 판정하는 제외 kind. `region`·`amount_floor`는 별도 식이다.
KEYWORD_EXCLUSION_KINDS = ("hardware", "election", "design_only", "staffing_only")

#: 제외 사유 집계 키와 판정 순서. 한 후보에 여러 사유가 맞으면 **이 순서의 첫 사유**
#: 하나로만 센다(집계 합 = 제외 후보 수).
EXCLUSION_KINDS = (*KEYWORD_EXCLUSION_KINDS, "region", "amount_floor")

#: 추적 변화 묶음에 드는 사업기회 추적 상태(spec "tracked_change 묶음").
TRACKED_STATUSES = frozenset({"계속 추적", "보류"})

#: 마감 알림 사유(RL-02 spec "마감 알림"). 추적 변화 행 `change_fields`에 들어가는 값이며
#: 공고 열 이름이 아니다(규칙 파일 `tracked_change_fields`에는 넣을 수 없다).
DEADLINE_REMINDER_FIELD = "deadline_reminder"
#: 마감 알림을 받는 공고 `source_type`. 사전규격 의견 마감은 대상이 아니다.
DEADLINE_REMINDER_SOURCE_TYPE = "bid_notice"

#: stage별 후보 필드 매핑 표(spec 표 그대로). `notice`는 사전규격·입찰공고 공통이다.
CANDIDATE_FIELD_MAP: dict[str, dict[str, Any]] = {
    "notice": {
        "text": ("title", "agency", "demand_agency"),
        "agency": ("agency", "demand_agency"),
        "amount": ("estimated_price", "budget"),
        "region": "region_limit_json",
        "deadline": "deadline_at",
        "planned_month": None,
    },
    "order_plan": {
        "text": ("title", "agency_name", "supervising_agency_name"),
        "agency": ("agency_name", "supervising_agency_name"),
        "amount": ("budget_amount",),
        "region": None,
        "deadline": None,
        "planned_month": "planned_order_month",
    },
}

_DEADLINE_KIND = {"pre_spec": "opinion_close", "bid_notice": "bid_close", "order_plan": "planned_month"}
_STAGE_ORDER = {stage: index for index, stage in enumerate(STAGES)}
_SEOUL = ZoneInfo("Asia/Seoul")


class BriefingRulesError(ValueError):
    """규칙 입력이 계약과 다르다. 메시지는 안전한 code 하나다."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --- 정규화 ------------------------------------------------------------------


def normalize_text(value: str | None) -> str:
    """NFKC → `name_matching.normalize` → 모든 공백 제거 → casefold (spec 순서 그대로).

    `name_matching.normalize` 단독은 NFKC·casefold가 없어 쓰지 않는다. 키워드·기관명·
    후보 텍스트가 모두 이 함수를 거친 뒤 부분문자열/동일 비교된다.
    """

    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = name_matching.normalize(text)
    text = "".join(text.split())
    return text.casefold()


def _joined(values: Iterable[Any]) -> str:
    return normalize_text(" ".join(str(value) for value in values if value is not None and str(value)))


# --- 회사 규칙 ---------------------------------------------------------------


@dataclass(frozen=True)
class Keyword:
    """원문 표기(이유 칩에 쓴다)와 정규화 값(비교에 쓴다)."""

    text: str
    normalized: str


@dataclass(frozen=True)
class DomainPreference:
    fact_key: str
    tier: int
    keywords: tuple[Keyword, ...]


@dataclass(frozen=True)
class ProjectRecord:
    fact_key: str
    label: str
    #: 길이 ≥ `name_matching.MIN_FRAGMENT_CHARS`인 fragment의 정규화 값.
    fragments: tuple[str, ...]


@dataclass(frozen=True)
class CompanyRules:
    graph_version_id: UUID
    domains: tuple[DomainPreference, ...]
    #: `hardware|election|design_only|staffing_only` → 키워드. 확정 사실이 없는 kind는 없다.
    exclusion_keywords: Mapping[str, tuple[Keyword, ...]]
    #: `excl:region` 허용 지역 이름. 형태만 검증하고 제외에는 쓰지 않는다(지역 제외 보류).
    allowed_regions: tuple[Keyword, ...] | None
    amount_floor_krw: int | None
    amount_range: tuple[int, int] | None
    solo_cap_krw: int | None
    agencies: tuple[Keyword, ...]
    projects: tuple[ProjectRecord, ...]


def _invalid() -> BriefingRulesError:
    return BriefingRulesError("company_facts_invalid")


def _keywords(value: Any) -> tuple[Keyword, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _invalid()
    keywords = []
    for item in value:
        normalized = normalize_text(item)
        if normalized:
            keywords.append(Keyword(text=item, normalized=normalized))
    return tuple(keywords)


def _int_param(value: Any, key: str) -> int:
    params = value.get("params") if isinstance(value, Mapping) else None
    number = params.get(key) if isinstance(params, Mapping) else None
    if isinstance(number, bool) or not isinstance(number, int) or number < 0:
        raise _invalid()
    return number


def _domain_value(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not {"tier", "keywords", "excluded", "kind"} <= set(value):
        raise _invalid()
    return value


def company_rules(projection: CompanyFactsProjection) -> CompanyRules:
    """회사 사실 projection을 규칙 입력으로 바꾼다.

    `status != "confirmed"`인 사실은 건너뛴다(제공자 필터와 이중 검사). 확정 사실인데
    RL-00 value 스키마와 모양이 다르면 추정하지 않고 `company_facts_invalid`로 멈춘다.
    """

    domains: list[DomainPreference] = []
    exclusions: dict[str, tuple[Keyword, ...]] = {}
    allowed_regions: tuple[Keyword, ...] | None = None
    amount_floor: int | None = None
    amount_range: tuple[int, int] | None = None
    solo_cap: int | None = None
    agencies: list[Keyword] = []
    projects: list[ProjectRecord] = []

    for fact in sorted(projection.facts, key=lambda item: item.fact_key):
        if fact.status != "confirmed":
            continue
        key, kind, value = fact.fact_key, fact.type, fact.value
        if key.startswith("pref:domain:") and kind == "domain":
            body = _domain_value(value)
            tier = body["tier"]
            if tier is None:
                continue
            if isinstance(tier, bool) or tier not in (1, 2, 3) or body["excluded"] is not False:
                raise _invalid()
            domains.append(DomainPreference(key, tier, _keywords(body["keywords"])))
        elif key.startswith("excl:") and kind == "domain":
            body = _domain_value(value)
            exclusion = key.removeprefix("excl:")
            if body["excluded"] is not True or body["kind"] != exclusion:
                raise _invalid()
            if exclusion in KEYWORD_EXCLUSION_KINDS:
                exclusions[exclusion] = _keywords(body["keywords"])
            elif exclusion == "region":
                allowed_regions = _keywords(body["keywords"])
            # `excl:amount_floor`는 표식일 뿐이고 값은 `pref:amount_floor`에서 읽는다.
        elif key == "pref:amount_floor" and kind == "capability":
            amount_floor = _int_param(value, "krw")
        elif key == "pref:amount_range" and kind == "capability":
            low, high = _int_param(value, "min_krw"), _int_param(value, "max_krw")
            if low > high:
                raise _invalid()
            amount_range = (low, high)
        elif key == "pref:solo_cap" and kind == "capability":
            solo_cap = _int_param(value, "krw")
        elif key.startswith("pref:agency:") and kind == "domain":
            names = _domain_value(value)["keywords"]
            if not isinstance(names, list) or not names or not isinstance(names[0], str):
                raise _invalid()
            normalized = normalize_text(names[0])
            if normalized:
                agencies.append(Keyword(text=names[0], normalized=normalized))
        elif key.startswith("project:") and kind == "project":
            label = fact.label
            if not isinstance(label, str):
                raise _invalid()
            fragments = tuple(
                dict.fromkeys(
                    normalized
                    for fragment in name_matching.fragments(label)
                    if len(fragment) >= name_matching.MIN_FRAGMENT_CHARS
                    and (normalized := normalize_text(fragment))
                )
            )
            projects.append(ProjectRecord(key, label, fragments))

    domains.sort(key=lambda item: (item.tier, item.fact_key))
    return CompanyRules(
        graph_version_id=projection.graph_version_id,
        domains=tuple(domains),
        exclusion_keywords={kind: exclusions[kind] for kind in KEYWORD_EXCLUSION_KINDS if kind in exclusions},
        allowed_regions=allowed_regions,
        amount_floor_krw=amount_floor,
        amount_range=amount_range,
        solo_cap_krw=solo_cap,
        agencies=tuple(agencies),
        projects=tuple(projects),
    )


# --- 후보 --------------------------------------------------------------------


@dataclass(frozen=True)
class BriefingCandidate:
    """spec 매핑 표로 읽은 후보 하나."""

    stage: Literal["pre_spec", "bid_notice", "order_plan"]
    notice_id: int | None
    order_plan_id: int | None
    opportunity_id: int | None
    title: str | None
    #: 표시용 기관(공고 `agency`, 발주계획 `agency_name`).
    agency: str | None
    texts: tuple[str | None, ...]
    agencies: tuple[str | None, ...]
    amount: Decimal | None
    region_limit: Any
    deadline_at: datetime | None
    deadline_kind: str | None
    planned_month: str | None
    first_observed_at: datetime
    sw_target: bool

    @property
    def amount_krw(self) -> int | None:
        # 원 단위 금액은 정수다. 소수점이 있으면 0 쪽으로 버린다(표시·저장용).
        return None if self.amount is None else int(self.amount)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _first_amount(source: Any, names: Sequence[str]) -> Decimal | None:
    for name in names:
        value = getattr(source, name, None)
        if value is not None:
            return _decimal(value)
    return None


def notice_candidate(
    notice: Any,
    *,
    stage: Literal["pre_spec", "bid_notice"],
    first_observed_at: datetime,
    opportunity_id: int | None = None,
) -> BriefingCandidate:
    """사전규격·입찰공고 `Notice`를 후보로 읽는다(매핑 표 `notice` 열)."""

    if stage not in ("pre_spec", "bid_notice"):
        raise ValueError("notice candidate stage must be pre_spec or bid_notice")
    fields = CANDIDATE_FIELD_MAP["notice"]
    flags = getattr(notice, "qualification_flags_json", None)
    sw_status = flags.get("sw_business_status") if isinstance(flags, Mapping) else None
    return BriefingCandidate(
        stage=stage,
        notice_id=int(notice.id),
        order_plan_id=None,
        opportunity_id=opportunity_id,
        title=notice.title,
        agency=notice.agency,
        texts=tuple(getattr(notice, name) for name in fields["text"]),
        agencies=tuple(getattr(notice, name) for name in fields["agency"]),
        amount=_first_amount(notice, fields["amount"]),
        region_limit=getattr(notice, fields["region"]),
        deadline_at=getattr(notice, fields["deadline"]),
        deadline_kind=_DEADLINE_KIND[stage],
        planned_month=None,
        first_observed_at=first_observed_at,
        sw_target=stage == "pre_spec" and sw_status == "Y",
    )


def order_plan_candidate(plan: Any, *, opportunity_id: int | None = None) -> BriefingCandidate:
    """C-2 relevant `OrderPlan`을 후보로 읽는다(매핑 표 `order_plan` 열).

    `first_observed_at`은 `OrderPlan.first_discovered_at`이다(spec "기준일과 모집단").
    """

    fields = CANDIDATE_FIELD_MAP["order_plan"]
    return BriefingCandidate(
        stage="order_plan",
        notice_id=None,
        order_plan_id=int(plan.id),
        opportunity_id=opportunity_id,
        title=plan.title,
        agency=plan.agency_name,
        texts=tuple(getattr(plan, name) for name in fields["text"]),
        agencies=tuple(getattr(plan, name) for name in fields["agency"]),
        amount=_first_amount(plan, fields["amount"]),
        region_limit=None,
        deadline_at=None,
        deadline_kind=_DEADLINE_KIND["order_plan"],
        planned_month=getattr(plan, fields["planned_month"]),
        first_observed_at=plan.first_discovered_at,
        sw_target=False,
    )


# --- 제외·점수·정렬 ----------------------------------------------------------


@dataclass(frozen=True)
class Recommendation:
    candidate: BriefingCandidate
    rank: int
    score: int
    reasons: tuple[dict[str, Any], ...]
    blocking: tuple[dict[str, Any], ...]
    change_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecommendationResult:
    items: tuple[Recommendation, ...]
    #: `EXCLUSION_KINDS` 순서의 키 전부(0 포함).
    excluded_counts: dict[str, int]
    #: 제외는 아니지만 점수 0이라 항목에 넣지 않은 후보 수.
    unscored_count: int
    #: 반복 발주처 ∧ 유사 실적이 아니어서 후보가 아닌 발주계획 수.
    order_plan_not_repeat_count: int


def _exclusion(candidate: BriefingCandidate, text: str, rules: CompanyRules) -> str | None:
    for kind in KEYWORD_EXCLUSION_KINDS:
        if any(keyword.normalized in text for keyword in rules.exclusion_keywords.get(kind, ())):
            return kind
    # `region` 제외는 보류한다(2026-10-17 사용자 결정, spec "결정적 점수와 제외"). 수집한
    # `region_limit_json.basis`는 소재지 판단 기준("본사소재지")이고 `joint_contract_regions`는
    # 공동도급 의무 지역이라 참가 가능 지역 이름이 없다. 모르는 값은 제외 근거가 아니므로
    # `excluded_counts.region`은 항상 0이다(docs/tracking/findings.md).
    if (
        rules.amount_floor_krw is not None
        and candidate.amount is not None
        and candidate.amount < rules.amount_floor_krw
    ):
        return "amount_floor"
    return None


def _keyword_hit(text: str, rules: CompanyRules) -> tuple[int, str] | None:
    """가장 높은 tier의 첫 hit 키워드. 분야는 tier 오름차순·fact_key 순, 키워드는 등록 순서."""

    for domain in rules.domains:
        for keyword in domain.keywords:
            if keyword.normalized in text:
                return domain.tier, keyword.text
    return None


def _repeat_agency(candidate: BriefingCandidate, rules: CompanyRules) -> str | None:
    names = {normalize_text(name) for name in candidate.agencies} - {""}
    for agency in rules.agencies:
        if agency.normalized in names:
            return agency.text
    return None


def _similar_projects(text: str, rules: CompanyRules) -> int:
    return sum(
        1 for project in rules.projects if any(fragment in text for fragment in project.fragments)
    )


def korean_amount_text(krw: int) -> str:
    """원 금액의 한글 표기: `15억 원`, `10억 5,000만 원`, `3,000만 원`."""

    eok, rest = divmod(int(krw), 100_000_000)
    man, won = divmod(rest, 10_000)
    parts = []
    if eok:
        parts.append(f"{eok:,}억")
    if man:
        parts.append(f"{man:,}만")
    if won or not parts:
        parts.append(f"{won:,}")
    return " ".join(parts) + " 원"


def _days_until(deadline: datetime, now: datetime) -> int:
    return (deadline.astimezone(_SEOUL).date() - now.astimezone(_SEOUL).date()).days


def _blocking(
    candidate: BriefingCandidate, rules: CompanyRules, policy: BriefingPolicy, now: datetime
) -> tuple[dict[str, Any], ...]:
    blocking: list[dict[str, Any]] = []
    thresholds = [policy.large_enterprise_threshold_krw]
    if rules.solo_cap_krw is not None:
        thresholds.append(rules.solo_cap_krw)
    threshold = min(thresholds)
    if candidate.amount is not None and candidate.amount >= threshold:
        blocking.append(
            {"kind": "consortium_review", "text": f"{korean_amount_text(threshold)} 이상 · 컨소시엄 검토"}
        )
    if candidate.deadline_at is not None:
        days = _days_until(candidate.deadline_at, now)
        if 0 <= days <= policy.deadline_warning_days:
            blocking.append({"kind": "deadline_short", "text": f"마감 {days}일"})
    return tuple(blocking[:2])


def _order_key(item: tuple[int, BriefingCandidate]) -> tuple[Any, ...]:
    score, candidate = item
    deadline = candidate.deadline_at
    return (
        -score,
        deadline is None,
        deadline if deadline is not None else candidate.first_observed_at,
        candidate.first_observed_at,
        # 아래는 spec 동점 규칙 뒤의 전순서 보조 키다(결정성 보장).
        _STAGE_ORDER[candidate.stage],
        candidate.notice_id or 0,
        candidate.order_plan_id or 0,
    )


def build_recommendations(
    candidates: Sequence[BriefingCandidate],
    rules: CompanyRules,
    policy: BriefingPolicy,
    *,
    now: datetime,
) -> RecommendationResult:
    """제외 → (발주계획) 반복 발주처 규칙 → 점수 → 정렬 → top_n.

    `now`는 `deadline_short` 일수 계산의 기준 시각이다(KST 일자 차).
    """

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    weights = policy.weights
    excluded = {kind: 0 for kind in EXCLUSION_KINDS}
    unscored = 0
    not_repeat = 0
    scored: list[tuple[int, BriefingCandidate, tuple[dict[str, Any], ...]]] = []
    for candidate in candidates:
        text = _joined(candidate.texts)
        exclusion = _exclusion(candidate, text, rules)
        if exclusion is not None:
            excluded[exclusion] += 1
            continue
        agency = _repeat_agency(candidate, rules)
        similar = _similar_projects(text, rules)
        if candidate.stage == "order_plan" and (agency is None or similar == 0):
            not_repeat += 1
            continue
        keyword = _keyword_hit(text, rules)
        score = 0
        if keyword is not None:
            score += weights.tier(keyword[0])
        if agency is not None:
            score += weights.repeat_agency
        if similar:
            score += weights.similar_project
        if candidate.sw_target:
            score += weights.sw_target
        if (
            rules.amount_range is not None
            and candidate.amount is not None
            and rules.amount_range[0] <= candidate.amount <= rules.amount_range[1]
        ):
            score += weights.amount_in_range
        if score == 0:
            unscored += 1
            continue
        reasons: list[dict[str, Any]] = []
        if keyword is not None:
            reasons.append({"kind": "keyword", "text": keyword[1]})
        if similar:
            reasons.append({"kind": "similar_project", "count": similar})
        if agency is not None:
            reasons.append({"kind": "repeat_agency", "text": agency})
        scored.append((score, candidate, tuple(reasons[:3])))

    scored.sort(key=lambda item: _order_key((item[0], item[1])))
    items = tuple(
        Recommendation(
            candidate=candidate,
            rank=rank,
            score=score,
            reasons=reasons,
            blocking=_blocking(candidate, rules, policy, now),
        )
        for rank, (score, candidate, reasons) in enumerate(scored[: policy.top_n], start=1)
    )
    return RecommendationResult(
        items=items,
        excluded_counts=excluded,
        unscored_count=unscored,
        order_plan_not_repeat_count=not_repeat,
    )


# --- 추적 변화 ---------------------------------------------------------------


@dataclass(frozen=True)
class TrackedChangeObservation:
    """창 안 `NoticeObservation` 하나와 그 공고의 권위 연결 사업기회.

    권위 연결(contracts "마감 임박 창")과 창 판정은 생성 service가 조회로 한다. 여기서는
    추적 상태와 바뀐 필드만 본다. `changed_fields`는 `changed_fields_json` 그대로이며
    과거 모양(dict)이면 키를 필드 이름으로 읽는다.
    """

    notice_id: int
    opportunity_id: int
    tracking_status: str
    changed_fields: Sequence[str] | Mapping[str, Any]


@dataclass(frozen=True)
class TrackedChange:
    notice_id: int
    opportunity_id: int
    #: 바뀐 필드 합집합. 규칙 파일 `tracked_change_fields` 순서.
    change_fields: tuple[str, ...]


def tracked_changes(
    observations: Iterable[TrackedChangeObservation], policy: BriefingPolicy
) -> tuple[TrackedChange, ...]:
    """(브리핑, 공고)당 1행. 추적 상태 `계속 추적|보류`이고 추적 필드가 바뀐 공고만."""

    allowed = policy.tracked_change_fields
    fields_by_notice: dict[int, set[str]] = {}
    owner: dict[int, int] = {}
    for observation in observations:
        if observation.tracking_status not in TRACKED_STATUSES:
            continue
        changed = observation.changed_fields
        names = set(changed.keys()) if isinstance(changed, Mapping) else set(changed)
        hit = names & set(allowed)
        if not hit:
            continue
        notice_id = int(observation.notice_id)
        fields_by_notice.setdefault(notice_id, set()).update(hit)
        # 공고의 권위 연결은 하나다(부분 UNIQUE). 같은 공고면 같은 사업기회다.
        owner.setdefault(notice_id, int(observation.opportunity_id))
    return tuple(
        TrackedChange(
            notice_id=notice_id,
            opportunity_id=owner[notice_id],
            change_fields=tuple(name for name in allowed if name in fields_by_notice[notice_id]),
        )
        for notice_id in sorted(fields_by_notice)
    )


@dataclass(frozen=True)
class DeadlineReminderCandidate:
    """추적 중 사업기회의 권위 연결 공고 하나와 그 마감(RL-02 spec "마감 알림").

    권위 연결(contracts "마감 임박 창")과 활성 사업기회 판정은 생성 service가 조회로 한다.
    여기서는 추적 상태·공고 종류·마감 KST 날짜만 본다.
    """

    notice_id: int
    opportunity_id: int
    tracking_status: str
    source_type: str | None
    deadline_at: datetime | None


def deadline_reminders(
    candidates: Iterable[DeadlineReminderCandidate], policy: BriefingPolicy, briefing_date: date
) -> tuple[TrackedChange, ...]:
    """마감 KST 날짜 − 브리핑 날짜가 `deadline_reminder_days`에 드는 입찰공고, 공고당 1행.

    추적 상태 `계속 추적|보류`인 사업기회의 입찰공고(`source_type='bid_notice'`)만 본다.
    v1 규칙 파일(`deadline_reminder_days=()`)이면 언제나 빈 tuple이다. 하루 1회는 브리핑
    날짜 UNIQUE가 보장한다.
    """

    days = set(policy.deadline_reminder_days)
    if not days:
        return ()
    owner: dict[int, int] = {}
    for candidate in candidates:
        if candidate.tracking_status not in TRACKED_STATUSES:
            continue
        if candidate.source_type != DEADLINE_REMINDER_SOURCE_TYPE:
            continue
        deadline = candidate.deadline_at
        if deadline is None or deadline.tzinfo is None or deadline.utcoffset() is None:
            continue
        if (deadline.astimezone(_SEOUL).date() - briefing_date).days not in days:
            continue
        owner.setdefault(int(candidate.notice_id), int(candidate.opportunity_id))
    return tuple(
        TrackedChange(notice_id=notice_id, opportunity_id=owner[notice_id], change_fields=(DEADLINE_REMINDER_FIELD,))
        for notice_id in sorted(owner)
    )


def combine_tracked_changes(
    changes: Sequence[TrackedChange], reminders: Sequence[TrackedChange]
) -> tuple[TrackedChange, ...]:
    """정정 행과 마감 알림을 (브리핑, 공고)당 1행으로 합친다.

    같은 공고에 정정이 있으면 그 행 `change_fields` 끝에 `deadline_reminder`를 더하고(행을
    추가하지 않는다), 없으면 마감 사유만 가진 행을 만든다. 입력은 바꾸지 않는다.
    """

    by_notice: dict[int, TrackedChange] = {change.notice_id: change for change in changes}
    for reminder in reminders:
        existing = by_notice.get(reminder.notice_id)
        if existing is None:
            by_notice[reminder.notice_id] = reminder
            continue
        combined = tuple(dict.fromkeys((*existing.change_fields, *reminder.change_fields)))
        by_notice[reminder.notice_id] = replace(existing, change_fields=combined)
    return tuple(by_notice[notice_id] for notice_id in sorted(by_notice))


def tracked_change_verdict(change_fields: Sequence[str]) -> str:
    """추적 변화 행의 표시: 정정 사유가 하나라도 있으면 "재검토 중", 마감 사유만이면 "마감 임박"."""

    fields = list(change_fields)
    if fields and all(name == DEADLINE_REMINDER_FIELD for name in fields):
        return "마감 임박"
    return "재검토 중"


def merge_tracked_changes(
    items: Sequence[Recommendation], changes: Sequence[TrackedChange]
) -> tuple[tuple[Recommendation, ...], tuple[TrackedChange, ...]]:
    """같은 공고가 추천과 추적 변화에 함께 해당하면 추천 행 하나만 남긴다.

    변화 사유는 추천 행 `change_fields`로 옮긴다(공고당 1행 보장). 입력은 바꾸지 않는다.
    """

    by_notice = {change.notice_id: change for change in changes}
    merged: list[Recommendation] = []
    absorbed: set[int] = set()
    for item in items:
        notice_id = item.candidate.notice_id
        change = by_notice.get(notice_id) if notice_id is not None else None
        if change is None:
            merged.append(item)
            continue
        absorbed.add(change.notice_id)
        combined = tuple(dict.fromkeys((*item.change_fields, *change.change_fields)))
        merged.append(replace(item, change_fields=combined))
    remaining = tuple(change for change in changes if change.notice_id not in absorbed)
    return tuple(merged), remaining


__all__ = [
    "CANDIDATE_FIELD_MAP",
    "DEADLINE_REMINDER_FIELD",
    "DEADLINE_REMINDER_SOURCE_TYPE",
    "EXCLUSION_KINDS",
    "KEYWORD_EXCLUSION_KINDS",
    "STAGES",
    "TRACKED_STATUSES",
    "BriefingCandidate",
    "BriefingRulesError",
    "CompanyRules",
    "DeadlineReminderCandidate",
    "DomainPreference",
    "Keyword",
    "ProjectRecord",
    "Recommendation",
    "RecommendationResult",
    "TrackedChange",
    "TrackedChangeObservation",
    "build_recommendations",
    "combine_tracked_changes",
    "company_rules",
    "deadline_reminders",
    "korean_amount_text",
    "merge_tracked_changes",
    "normalize_text",
    "notice_candidate",
    "order_plan_candidate",
    "tracked_change_verdict",
    "tracked_changes",
]
