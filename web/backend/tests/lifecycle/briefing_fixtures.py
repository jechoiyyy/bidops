"""RL-01 브리핑 생성·조회·반응 검사의 공용 합성 세계.

lifecycle 테이블(회차·공고·관측·발주계획·사업기회·연결)만 심는다. 회사 사실과 발주계획
후보는 lifecycle 확장점 자료형을 직접 만든 가짜 제공자로 넣는다 — 이 파일은 deep_review·
screening을 import하지 않는다(경계 검사 1). 값은 회사 자료가 아니라 계약 모양만 갖춘
합성 값이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.lifecycle.extensions import CompanyFact, CompanyFactsProjection
from app.lifecycle.models import (
    IngestWarning,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    Run,
)

GRAPH = UUID("11111111-2222-3333-4444-555555555555")
#: 브리핑 날짜 D(금요일)와 그 수집 기준일 D-1.
BRIEFING_DATE = date(2026, 10, 16)
NEXT_BRIEFING_DATE = date(2026, 10, 19)  # 월요일
SATURDAY = date(2026, 10, 17)
#: 직전 브리핑이 없을 때 창의 시작 = D-1 00:00 KST.
WINDOW_START = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
#: 생성 시각 = D 07:30 KST.
NOW = datetime(2026, 10, 15, 22, 30, tzinfo=UTC)
COLLECTION_RUN = "lifecycle-20261015-notices--2026-10-15T21:00:00Z"
COLLECTION_RETRY_RUN = "lifecycle-20261015-notices-retry1--2026-10-15T21:30:00Z"


def _fact(fact_key: str, type_: str, value: Any, *, status: str = "confirmed", label: str | None = None):
    return CompanyFact(fact_key=fact_key, type=type_, status=status, label=label or fact_key, value=value)


def _domain(tier, keywords, *, excluded=False, kind=None):
    return {"tier": tier, "keywords": list(keywords), "excluded": excluded, "kind": kind}


def company_facts() -> list[CompanyFact]:
    return [
        _fact("pref:domain:01", "domain", _domain(1, ["유지관리", "홈페이지"])),
        _fact("pref:domain:02", "domain", _domain(2, ["데이터 플랫폼"])),
        _fact("excl:hardware", "domain", _domain(None, ["하드웨어"], excluded=True, kind="hardware")),
        _fact("excl:region", "domain", _domain(None, ["대구", "경북", "전국"], excluded=True, kind="region")),
        _fact("pref:amount_floor", "capability", {"scope": "core", "description": "합성", "params": {"krw": 30_000_000}}),
        _fact("pref:agency:01", "domain", _domain(None, ["대구테크노파크"]), label="대구테크노파크"),
        _fact(
            "project:2024-01", "project",
            {"role": None, "scope": None, "agency": "대구테크노파크", "year": 2024},
            label="스마트 관광 플랫폼 고도화 용역",
        ),
    ]


def company_projection() -> CompanyFactsProjection:
    return CompanyFactsProjection(graph_version_id=GRAPH, facts=tuple(company_facts()))


class FakeCompanyFacts:
    def __init__(self, projection: CompanyFactsProjection | None = None) -> None:
        self.projection = projection if projection is not None else company_projection()

    def company_facts_projection(self, session: Any) -> CompanyFactsProjection | None:
        return self.projection


class FakeOrderPlans:
    """`(since, until]`을 기록하고 정해 둔 id를 돌려준다(최신 C-2 relevant 판정은 screening 몫)."""

    def __init__(self, ids: list[int] | None = None) -> None:
        self.ids = list(ids or [])
        self.calls: list[tuple[datetime, datetime]] = []

    def briefing_order_plan_candidates(self, session: Any, since: datetime, until: datetime) -> list[int]:
        self.calls.append((since, until))
        return list(self.ids)


def register_providers(registry, *, facts: bool = True, plans: FakeOrderPlans | None = None) -> FakeOrderPlans | None:
    if facts:
        registry.register_company_facts_projection(FakeCompanyFacts(), owner="briefing-test")
    if plans is not None:
        registry.register_briefing_order_plan_candidates(plans, owner="briefing-test")
    return plans


@dataclass
class World:
    """한 session 위에 합성 레코드를 심는다. 모든 메서드는 flush까지만 한다."""

    session: Session
    _serial: Any = field(default_factory=lambda: count(1))
    #: 같은 DB에 World를 여러 번 만들어도 외부 키·회차 id가 겹치지 않게 한다.
    _prefix: str = field(default_factory=lambda: uuid4().hex[:8])

    def _next(self) -> int:
        return next(self._serial)

    def run(self, run_id: str, *, generated_at: datetime = NOW) -> Run:
        row = self.session.get(Run, run_id)
        if row is None:
            row = Run(id=run_id, generated_at=generated_at)
            self.session.add(row)
            self.session.flush()
        return row

    def collection_run(self, run_id: str = COLLECTION_RUN, *, warnings: int = 0) -> Run:
        row = self.run(run_id)
        for index in range(warnings):
            self.session.add(
                IngestWarning(run_id=run_id, level="warning", code="fixture_warning", message=f"합성 경고 {index}")
            )
        self.session.flush()
        return row

    def opportunity(self, *, tracking_status: str = "미선택", stage: str = "pre_spec") -> Opportunity:
        values: dict[str, Any] = {"first_registered_stage": stage, "tracking_status": tracking_status}
        if tracking_status != "미선택":
            values.update(
                tracking_reason="합성 추적 사유",
                tracking_selected_by="추적 담당자",
                tracking_selected_at=NOW - timedelta(days=30),
            )
        row = Opportunity(**values)
        self.session.add(row)
        self.session.flush()
        return row

    def observe(self, notice: Notice, observed_at: datetime, changed: list[str] | None = None) -> NoticeObservation:
        run = self.run(f"fixture-observation-{self._prefix}-{self._next():04d}--2026-10-15T00:00:00Z")
        row = NoticeObservation(
            notice_id=notice.id, run_id=run.id, observed_at=observed_at, changed_fields_json=list(changed or [])
        )
        self.session.add(row)
        self.session.flush()
        return row

    def notice(
        self,
        title: str,
        *,
        source_type: str = "pre_spec",
        sw: str | None = "Y",
        observed_at: datetime | None = NOW - timedelta(hours=3),
        deadline_at: datetime | None = None,
        estimated_price: int | None = None,
        agency: str = "합성구청",
        owner: Opportunity | None | bool = True,
        review_exclusion_status: str = "included",
    ) -> Notice:
        key = f"briefing-notice-{self._prefix}-{self._next():04d}"
        row = Notice(
            notice_key=key,
            source_type=source_type,
            title=title,
            agency=agency,
            deadline_at=deadline_at,
            estimated_price=None if estimated_price is None else Decimal(estimated_price),
            qualification_flags_json={"sw_business_status": sw} if sw is not None else None,
            review_exclusion_status=review_exclusion_status,
        )
        if review_exclusion_status != "included":
            row.review_exclusion_actor_name = "제외 담당자"
            row.review_exclusion_reason = "합성 제외"
            row.review_exclusion_changed_at = NOW - timedelta(days=1)
        self.session.add(row)
        self.session.flush()
        if observed_at is not None:
            self.observe(row, observed_at)
        if owner is True:
            owner = self.opportunity(stage="pre_spec" if source_type == "pre_spec" else "bid_notice")
        if isinstance(owner, Opportunity):
            self.link_notice(owner, row)
        return row

    def link_notice(self, owner: Opportunity, notice: Notice) -> OpportunityLink:
        link = OpportunityLink(
            opportunity_id=owner.id, notice_id=notice.id, stage="notice", link_type="official",
            status="확정", evidence_external_no=notice.notice_key,
        )
        self.session.add(link)
        self.session.flush()
        return link

    def plan(
        self,
        title: str,
        *,
        agency_name: str = "대구테크노파크",
        first_discovered_at: datetime = NOW - timedelta(hours=2),
        owner: bool = True,
        month: str = "2027-02",
    ) -> OrderPlan:
        number = f"briefing-plan-{self._prefix}-{self._next():04d}"
        row = OrderPlan(
            order_plan_unty_no=number, title=title, agency_name=agency_name,
            planned_order_month=month, first_discovered_at=first_discovered_at,
        )
        self.session.add(row)
        self.session.flush()
        if owner:
            opportunity = self.opportunity(stage="order_plan")
            self.session.add(
                OpportunityLink(
                    opportunity_id=opportunity.id, order_plan_id=row.id, stage="order_plan",
                    link_type="official", status="확정", evidence_external_no=number,
                )
            )
            self.session.flush()
        return row


__all__ = [
    "BRIEFING_DATE",
    "COLLECTION_RETRY_RUN",
    "COLLECTION_RUN",
    "GRAPH",
    "NEXT_BRIEFING_DATE",
    "NOW",
    "SATURDAY",
    "WINDOW_START",
    "FakeCompanyFacts",
    "FakeOrderPlans",
    "World",
    "company_facts",
    "company_projection",
    "register_providers",
]
