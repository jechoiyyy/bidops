"""사업 추적 연결·병합·결정 대표 통합 시나리오 (plan §검증 "대표 통합 시나리오").

수집 회차 파일(`bidops.collected*.v*`)을 임시 `data/runs` 아래에 쓰고 공개 진입점만
부른다: `ingest_run(..., selection="collection")`, 추적 보충 함수, 조립된 FastAPI
앱(lifecycle·screening·deep_review)의 REST. 회차는 일일 운영처럼 발주계획 회차와
공고 회차를 나눈다.

| 회차 | 내용 |
|---|---|
| A 발주계획 09-14 | P(추적 대상), P2, P3 |
| B 공고 09-15 | S(SW=Y, P와 수요기관·가운뎃점 변형 제목), S2, S4(SW=Y), B7(P3을 가리키는 색인 전용 입찰공고) |
| A2 발주계획 09-16 | P4(S4와 같은 기관·제목, S4보다 늦게 등록) |
| C 공고 09-16 | B1(X 000, bfSpecRgstNo=S), U1(1468 N), U2(1468 수의계약), N1(1468 경쟁, 키 없음), S4 재관측, B4(P4+S4) |
| D 공고 09-17 | B2(X 001, 키 없음), B6(P2+S2) |
| E 공고 09-18 | B3(X 002, 키 없음) |
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.core.models import AuditEvent
from app.lifecycle import ingest_run, screening_input_error
from app.lifecycle.ingest.loader import tracked_backfill
from app.lifecycle.models import Notice, NoticeObservation, Opportunity, OpportunityLink, OrderPlan, Run
from app.lifecycle.routers import opportunities as opportunities_router
from app.lifecycle.routers import workload as workload_router
from app.lifecycle.services.opportunity_integrity import authoritative_link_predicate
from app.lifecycle.services.workload import get_workload
from app.main import create_app
from tests.lifecycle.test_collection_ingest import (
    _bid,
    _index_rows,
    _notice,
    _observation_digests,
    _owner,
    _plan,
    _pre_spec,
    _screening_input,
    _write_run,
)
from tests.postgres import migrated_engine, requires_postgres


KST = timezone(timedelta(hours=9))
ACTOR_NAME = "추적 담당자"
ACTOR = {
    "X-BidOps-Actor-Name": f"UTF-8''{quote(ACTOR_NAME, safe='')}",
    "X-BidOps-Actor-Name-Format": "utf-8-percent-v1",
}
MODULES = ("lifecycle", "screening", "deep_review")

PLAN_P, PLAN_P2, PLAN_P3, PLAN_P4 = "R26DD30010001", "R26DD30010002", "R26DD30010003", "R26DD30010004"
PRE_S, PRE_S2, PRE_S4 = "R26BD00310001", "R26BD00310002", "R26BD00310004"
BID_X = "R26BK03100001"
BID_B4, BID_B6, BID_B7 = "R26BK03100004", "R26BK03100006", "R26BK03100007"
BID_U1, BID_U2, BID_N1 = "R26BK03100011", "R26BK03100012", "R26BK03100013"
S_KEY, S2_KEY, S4_KEY = f"pre:{PRE_S}", f"pre:{PRE_S2}", f"pre:{PRE_S4}"
B1_KEY, B2_KEY, B3_KEY = f"bid:{BID_X}:000", f"bid:{BID_X}:001", f"bid:{BID_X}:002"
B4_KEY, B6_KEY, B7_KEY = f"bid:{BID_B4}:000", f"bid:{BID_B6}:000", f"bid:{BID_B7}:000"
U1_KEY, U2_KEY, N1_KEY = f"bid:{BID_U1}:000", f"bid:{BID_U2}:000", f"bid:{BID_N1}:000"

AGENCY_P = "테스트 정보화진흥원"
PLATFORM_PLAN_TITLE = "공공데이터·AI 통합 플랫폼 구축"
PLATFORM_TITLE = "공공데이터 AI 통합 플랫폼 구축"
AGENCY_CCTV = "테스트 도시관제센터"
CCTV_TITLE = "지능형 CCTV 관제 시스템 구축"

#: spec §2.2 원천별 통계 사유. 기대값을 제품 상수에서 만들지 않는다.
SELECTION_REASONS = {
    "order_plan": ("order_plan_all",),
    "pre_spec": ("pre_spec_sw", "pre_spec_referenced", "pre_spec_known"),
    "bid_notice": (
        "bid_same_notice_no",
        "bid_tracked_reference",
        "bid_sw_prespec_reference",
        "bid_sw_industry_competitive",
    ),
}


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def flow_engine(request):
    if request.param == "postgres":
        with migrated_engine() as engine:
            yield engine
        return
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@dataclass
class _Flow:
    client: TestClient
    sessions: sessionmaker
    reader: Session
    data_root: Path

    def read(self) -> Session:
        """The committed state: end the reader transaction and expire what it loaded."""

        self.reader.rollback()
        return self.reader

    def collect(self, run_dir: Path, expected: dict[str, Any]):
        # One session per ingest, as `python -m app.lifecycle.ingest.cli --run … --collection`.
        with self.sessions() as session:
            result = ingest_run(run_dir, session, selection="collection")
        assert result.selection == expected
        assert self.read().get(Run, result.run_id).counts_json["selection"] == expected
        return result


@pytest.fixture
def flow(flow_engine, empty_extensions, monkeypatch, tmp_path):
    """조립된 앱. `create_app`이 빈 registry에 screening·deep_review 제공자를 채운다.

    세션은 `app.core.db.SessionLocal`과 같은 설정(autoflush·expire_on_commit 끔)으로
    요청마다, 적재마다 새로 연다. 한 세션을 공유하면 identity map이 병합·후보 이동의
    결함을 가릴 수 있다.
    """

    sessions = sessionmaker(
        bind=flow_engine, class_=Session, autoflush=False, expire_on_commit=False
    )

    def request_session():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    application = create_app(modules=MODULES, mount_frontend=False)
    application.dependency_overrides[get_db] = request_session
    # 추적 저장 뒤 추적 보충은 `<bidops_root>/data/runs`의 회차 파일을 읽는다.
    monkeypatch.setattr(
        opportunities_router, "get_settings", lambda: SimpleNamespace(bidops_root=tmp_path)
    )
    with TestClient(application) as client, Session(flow_engine) as reader:
        yield _Flow(client, sessions, reader, tmp_path / "data")


# --- helpers ---------------------------------------------------------------


def _selection(skipped: dict[str, int] | None = None, **selected: int) -> dict[str, Any]:
    skipped = skipped or {}
    known = {reason for reasons in SELECTION_REASONS.values() for reason in reasons}
    assert set(selected) <= known
    stats: dict[str, Any] = {}
    for kind, reasons in SELECTION_REASONS.items():
        counts = {reason: selected.get(reason, 0) for reason in reasons}
        stats[kind] = {
            "collected": sum(counts.values()) + skipped.get(kind, 0),
            "selected": counts,
            "skipped": skipped.get(kind, 0),
        }
    return stats


def _reasons(session: Session, run_id: str) -> dict[str, str | None]:
    return {key: row.selection_reason for key, row in _index_rows(session, run_id).items()}


def _ok(response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


def _detail(client: TestClient, opportunity_id: int) -> dict[str, Any]:
    return _ok(client.get(f"/api/opportunities/{opportunity_id}"))


def _listing(client: TestClient, **params: Any) -> dict[str, Any]:
    return _ok(client.get("/api/opportunities", params={"limit": 500, **params}))


def _ids(client: TestClient, **params: Any) -> list[int]:
    return sorted(item["id"] for item in _listing(client, **params)["items"])


def _track(client: TestClient, opportunity_id: int, status: str, reason: str) -> dict[str, Any]:
    return _ok(
        client.patch(
            f"/api/opportunities/{opportunity_id}/tracking-status",
            json={"tracking_status": status, "reason": reason},
            headers=ACTOR,
        )
    )


def _ack(client: TestClient, opportunity_id: int, link_id: int) -> dict[str, Any]:
    return _ok(
        client.post(
            f"/api/opportunities/{opportunity_id}/recheck-acknowledgements",
            json={"expected_link_id": link_id, "note": "새 공고 확인"},
            headers=ACTOR,
        )
    )


def _tracking(body: dict[str, Any]) -> tuple[Any, ...]:
    return (
        body["tracking_status"],
        body["tracking_reason"],
        body["tracking_selected_by"],
        body["tracking_selected_at"],
    )


def _order_plan(session: Session, number: str) -> OrderPlan:
    return session.scalars(select(OrderPlan).where(OrderPlan.order_plan_unty_no == number)).one()


def _owning_link(session: Session, notice: Notice) -> OpportunityLink:
    return session.scalars(
        select(OpportunityLink).where(
            OpportunityLink.notice_id == notice.id, authoritative_link_predicate(OpportunityLink)
        )
    ).one()


def _audits(session: Session, action: str, aggregate_id: Any) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == action, AuditEvent.aggregate_id == str(aggregate_id)
            )
        )
    )


@contextmanager
def _router_clock(monkeypatch, instant: datetime):
    """Freeze the opportunities router clock, which stamps the human tracking decision."""

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return instant.astimezone(tz)

    with monkeypatch.context() as patch:
        patch.setattr(opportunities_router, "datetime", FrozenDatetime)
        yield


def _bid_record(bid_no: str, order: str = "000", *, published_at: str, agency: str, **kwargs: Any) -> dict[str, Any]:
    return {**_bid(bid_no, order, **kwargs), "published_at": published_at, "agency": agency}


def _pre_spec_record(number: str, *, agency: str, published_at: str, **kwargs: Any) -> dict[str, Any]:
    return {**_pre_spec(number, **kwargs), "agency": agency, "published_at": published_at}


def _plan_record(number: str, *, title: str, agency: str) -> dict[str, Any]:
    return {**_plan(number, title=title), "agency_name": agency}


# --- scenario --------------------------------------------------------------


def test_tracking_lifecycle_links_merges_signals_holds_and_decides(flow, monkeypatch):
    client, data_root = flow.client, flow.data_root

    # ── 1. 발주계획 회차 A → P의 사업기회를 `계속 추적`으로 저장 ─────────────────
    run_a_dir = _write_run(
        data_root,
        "lifecycle-20260914-plans",
        generated_at="2026-09-14T12:00:00+00:00",
        plans=[
            _plan_record(PLAN_P, title=PLATFORM_PLAN_TITLE, agency=AGENCY_P),
            _plan_record(PLAN_P2, title="도로시설물 안전점검 체계 고도화", agency="테스트 도로관리청"),
            _plan_record(PLAN_P3, title="해양관측 자료 수집 체계 구축", agency="테스트 해양조사원"),
        ],
    )
    flow.collect(run_a_dir, _selection(order_plan_all=3))
    db = flow.read()
    p_id = _owner(db, order_plan=_order_plan(db, PLAN_P)).id
    p2_id = _owner(db, order_plan=_order_plan(db, PLAN_P2)).id
    p3_id = _owner(db, order_plan=_order_plan(db, PLAN_P3)).id
    assert len({p_id, p2_id, p3_id}) == 3

    tracked = _track(client, p_id, "계속 추적", "SW 사업 발주계획")
    assert (tracked["tracking_status"], tracked["tracking_selected_by"], tracked["section"]) == (
        "계속 추적",
        ACTOR_NAME,
        "추적 중",
    )
    p_tracking = _tracking(tracked)
    (tracking_audit,) = _audits(flow.read(), "opportunity.tracking_status.changed", p_id)
    assert (tracking_audit.actor_kind, tracking_audit.claimed_name) == ("human", ACTOR_NAME)
    assert tracking_audit.safe_metadata["tracking_status"] == "계속 추적"

    # ── 2. 공고 회차 B: 같은 기관 SW=Y 사전규격 S → P 소유 후보 → 수락 병합 ─────────
    # 발주계획 orderInsttNm은 S의 수요기관(demand_agency)과만 같고 S의 발주기관(agency)은
    # 조달청이다. 제목은 P의 가운뎃점을 공백으로 바꾼 변형이다.
    s4_record = _pre_spec_record(
        PRE_S4, title=CCTV_TITLE, agency=AGENCY_CCTV, published_at="2026-09-15T09:30:00+09:00"
    )
    run_b_dir = _write_run(
        data_root,
        "lifecycle-20260915-notices",
        generated_at="2026-09-15T12:00:00+00:00",
        notices=[
            _pre_spec_record(
                PRE_S,
                title=PLATFORM_TITLE,
                agency="조달청",
                demand_agency=AGENCY_P,
                published_at="2026-09-15T09:00:00+09:00",
            ),
            _pre_spec_record(
                PRE_S2,
                title="스마트 민원 상담 챗봇 고도화",
                agency="테스트 민원청",
                published_at="2026-09-15T09:10:00+09:00",
            ),
            s4_record,
            # P3을 가리키지만 P3이 아직 `미선택`이고 1468도 N이라 색인에만 남는다(7단계).
            _bid_record(
                BID_B7,
                title="해양관측 자료 수집 체계 구축",
                agency="테스트 해양조사원",
                published_at="2026-09-15T10:00:00+09:00",
                order_plan_no=PLAN_P3,
                sw_industry_1468="N",
            ),
        ],
    )
    run_b = flow.collect(run_b_dir, _selection(pre_spec_sw=3, skipped={"bid_notice": 1}))
    db = flow.read()
    assert _reasons(db, run_b.run_id)[B7_KEY] is None and _notice(db, B7_KEY) is None
    s = _notice(db, S_KEY)
    s_notice_id = s.id
    assert (s.agency, s.demand_agency) == ("조달청", AGENCY_P)
    s_id = _owner(db, notice=s).id
    s2_id = _owner(db, notice=_notice(db, S2_KEY)).id
    s4_id = _owner(db, notice=_notice(db, S4_KEY)).id
    assert len({p_id, s_id, s2_id, s4_id}) == 4

    (candidate,) = db.scalars(select(OpportunityLink).where(OpportunityLink.link_type == "candidate")).all()
    candidate_id = candidate.id
    assert (
        candidate.opportunity_id,
        candidate.notice_id,
        candidate.status,
        candidate.search_strategy,
        candidate.agency_match,
        candidate.attempted_strategies_json,
    ) == (p_id, s_notice_id, "후보 확인 대기", "breaking_split", True, ["full", "breaking_split"])
    assert candidate.last_searched_at is not None
    assert _ids(client, section="조치 필요", reason="candidate_pending") == [p_id]

    accepted = _ok(
        client.patch(
            f"/api/opportunities/links/{candidate_id}/decision",
            json={"decision": "accepted", "reason": "발주계획과 같은 사업으로 확인"},
            headers=ACTOR,
        )
    )
    assert (accepted["status"], accepted["human_decision"], accepted["reviewer_name"]) == (
        "사람 확인 병합",
        "accepted",
        ACTOR_NAME,
    )
    retained = _detail(client, p_id)
    assert _tracking(retained) == p_tracking
    assert (retained["merged_into_opportunity_id"], retained["recheck_signal"]) == (None, False)
    assert (retained["first_registered_stage"], retained["section"], retained["action_reasons"]) == (
        "order_plan",
        "추적 중",
        [],
    )
    assert {(link["status"], link["notice_id"]) for link in retained["links"]} >= {
        ("확정", s_notice_id),
        ("사람 확인 병합", s_notice_id),
    }
    merged = _detail(client, s_id)
    assert (merged["merged_into_opportunity_id"], merged["merge_reason"]) == (
        p_id,
        "human_confirmed_candidate",
    )
    db = flow.read()
    # The authoritative unique index kept exactly one owner of S: the moved official link.
    assert _owner(db, notice=_notice(db, S_KEY)).id == p_id
    assert db.get(OpportunityLink, candidate_id).opportunity_id == p_id
    (merge_audit,) = _audits(db, "opportunity.merged.human_confirmed", p_id)
    assert merge_audit.safe_metadata == {
        "retained_opportunity_id": p_id,
        "secondary_opportunity_id": s_id,
        "opportunity_link_id": candidate_id,
    }
    assert len(_audits(db, "opportunity_link.candidate_decision.recorded", candidate_id)) == 1
    assert _audits(db, "opportunity.recheck_signal.created", p_id) == []

    # P2c 준비: S4보다 늦게 등록되는 발주계획 P4 (같은 기관·같은 제목).
    run_a2_dir = _write_run(
        data_root,
        "lifecycle-20260916-plans",
        generated_at="2026-09-15T21:00:00+00:00",
        plans=[_plan_record(PLAN_P4, title=CCTV_TITLE, agency=AGENCY_CCTV)],
    )
    flow.collect(run_a2_dir, _selection(order_plan_all=1))
    db = flow.read()
    p4_id = _owner(db, order_plan=_order_plan(db, PLAN_P4)).id

    # ── 3·5. 공고 회차 C ─────────────────────────────────────────────────────
    run_c_generated = "2026-09-16T12:00:00+00:00"
    run_c_dir = _write_run(
        data_root,
        "lifecycle-20260916-notices",
        generated_at=run_c_generated,
        notices=[
            _bid_record(
                BID_X,
                "000",
                title=PLATFORM_TITLE,
                agency=AGENCY_P,
                published_at="2026-09-16T10:00:00+09:00",
                pre_spec_no=PRE_S,
                sw_industry_1468="Y",
                opening_at="2026-09-28T11:00:00+09:00",
            ),
            _bid_record(
                BID_U1,
                title="청사 시설 경비 용역",
                agency="테스트 청사관리소",
                published_at="2026-09-16T11:00:00+09:00",
                sw_industry_1468="N",
            ),
            _bid_record(
                BID_U2,
                title="누리집 유지관리 용역",
                agency="테스트 홍보원",
                published_at="2026-09-16T11:00:00+09:00",
                method="수의계약",
                sw_industry_1468="Y",
            ),
            _bid_record(
                BID_N1,
                title="재난안전 데이터 분석 시스템 구축",
                agency="테스트 재난관리원",
                published_at="2026-09-16T11:00:00+09:00",
                method="제한경쟁",
                sw_industry_1468="Y",
            ),
            s4_record,
            _bid_record(
                BID_B4,
                title=CCTV_TITLE,
                agency=AGENCY_CCTV,
                published_at="2026-09-16T11:30:00+09:00",
                order_plan_no=PLAN_P4,
                pre_spec_no=PRE_S4,
            ),
        ],
    )
    run_c = flow.collect(
        run_c_dir,
        _selection(
            skipped={"bid_notice": 2},
            pre_spec_sw=1,
            bid_tracked_reference=1,
            bid_sw_prespec_reference=1,
            bid_sw_industry_competitive=1,
        ),
    )
    db = flow.read()
    assert _reasons(db, run_c.run_id) == {
        # §2.2 첫 일치 순서에서 `bid_tracked_reference`가 `bid_sw_prespec_reference`보다
        # 앞선다. S는 2단계 병합으로 `계속 추적`인 P의 사업기회가 소유하므로 B1은 추적
        # 참조로 선별된다. SW 사전규격 참조 사유는 아무도 추적하지 않는 S4를 가리키는 B4가 받는다.
        B1_KEY: "bid_tracked_reference",
        B4_KEY: "bid_sw_prespec_reference",
        N1_KEY: "bid_sw_industry_competitive",
        S4_KEY: "pre_spec_sw",
        U1_KEY: None,
        U2_KEY: None,
    }

    # 3. B1 → P의 사업기회에 자동 연결, 재검토 신호 → 확인 처리(추적 상태 불변)
    b1 = _notice(db, B1_KEY)
    b1_notice_id = b1.id
    b1_link_id = _owning_link(db, b1).id
    assert _owner(db, notice=b1).id == p_id
    signaled = _detail(client, p_id)
    assert (signaled["recheck_signal"], signaled["recheck_signal_link_id"]) == (True, b1_link_id)
    assert datetime.fromisoformat(signaled["recheck_signal_at"]).tzinfo is not None
    assert (signaled["section"], signaled["action_reasons"]) == ("조치 필요", ["new_link"])
    assert _tracking(signaled) == p_tracking
    assert _ids(client, section="조치 필요", reason="new_link") == [p_id]

    acknowledged = _ack(client, p_id, b1_link_id)
    assert (acknowledged["recheck_signal"], acknowledged["recheck_signal_link_id"]) == (False, None)
    assert (acknowledged["section"], acknowledged["action_reasons"]) == ("추적 중", [])
    assert _tracking(acknowledged) == p_tracking
    history = _ok(client.get(f"/api/opportunities/{p_id}/tracking-decisions"))
    assert [item["tracking_status"] for item in history["items"]] == ["계속 추적"]
    assert [(event["kind"], event["link_id"], event["actor_kind"]) for event in history["recheck_events"]] == [
        ("acknowledged", b1_link_id, "human"),
        ("created", b1_link_id, "system"),
    ]

    # 5. 무관 입찰공고·1468 수의계약은 색인에만, 1468 경쟁입찰은 `신규 입찰공고`
    db = flow.read()
    assert _notice(db, U1_KEY) is None and _notice(db, U2_KEY) is None
    n1_id = _owner(db, notice=_notice(db, N1_KEY)).id
    n1 = _detail(client, n1_id)
    assert (n1["tracking_status"], n1["first_registered_stage"], n1["section"]) == (
        "미선택",
        "bid_notice",
        "신규 입찰공고",
    )
    assert _ids(client, section="신규 입찰공고") == [n1_id]

    # P2c 위험 고정: 같은 적재에서 S4 재관측이 만든 후보(소유 P4)는, 뒤이은 B4가 P4를
    # 더 오래된 S4 사업기회로 자동 병합할 때 유지 사업기회로 함께 옮겨져야 한다.
    s4 = _notice(db, S4_KEY)
    (cctv_candidate,) = db.scalars(
        select(OpportunityLink).where(
            OpportunityLink.link_type == "candidate", OpportunityLink.notice_id == s4.id
        )
    ).all()
    assert (cctv_candidate.search_strategy, cctv_candidate.status) == ("full", "후보 확인 대기")
    assert cctv_candidate.opportunity_id == s4_id
    assert db.get(Opportunity, p4_id).merged_into_opportunity_id == s4_id
    assert _owner(db, order_plan=_order_plan(db, PLAN_P4)).id == s4_id
    assert _owner(db, notice=_notice(db, B4_KEY)).id == s4_id
    cctv = _detail(client, s4_id)
    # 유지 사업기회가 이미 소유한 레코드를 가리키는 후보는 조치 사유가 아니다.
    assert (cctv["first_registered_stage"], cctv["action_reasons"], cctv["pending_candidate_link_count"]) == (
        "order_plan",
        [],
        0,
    )

    # ── 4·6. 공고 회차 D ─────────────────────────────────────────────────────
    assert _track(client, p2_id, "보류", "예산 확정 대기")["section"] == "보류"
    assert _track(client, s2_id, "계속 추적", "민원 챗봇 사업")["section"] == "추적 중"
    run_d_dir = _write_run(
        data_root,
        "lifecycle-20260917-notices",
        generated_at="2026-09-17T12:00:00+00:00",
        notices=[
            _bid_record(
                BID_X,
                "001",
                title=PLATFORM_TITLE,
                agency=AGENCY_P,
                published_at="2026-09-17T10:00:00+09:00",
            ),
            _bid_record(
                BID_B6,
                title="민원 상담 챗봇과 도로시설물 점검 연계",
                agency="테스트 도로관리청",
                published_at="2026-09-17T11:00:00+09:00",
                order_plan_no=PLAN_P2,
                pre_spec_no=PRE_S2,
            ),
        ],
    )
    run_d = flow.collect(run_d_dir, _selection(bid_same_notice_no=1, bid_tracked_reference=1))
    db = flow.read()
    assert _reasons(db, run_d.run_id) == {B2_KEY: "bid_same_notice_no", B6_KEY: "bid_tracked_reference"}

    # 4. 키 없는 2차수는 같은 bid_no로 같은 사업기회
    b2 = _notice(db, B2_KEY)
    b2_notice_id = b2.id
    assert _owner(db, notice=b2).id == _owner(db, notice=_notice(db, B1_KEY)).id == p_id

    # 6. 사람 선택이 두 사업기회(P2 보류·S2 계속 추적)에 있으면 병합하지 않는다
    b6 = _notice(db, B6_KEY)
    b6_owner_id = _owner(db, notice=b6).id
    assert b6_owner_id not in {p2_id, s2_id}
    confirmations = db.scalars(
        select(OpportunityLink).where(OpportunityLink.search_strategy == "merge_confirmation")
    ).all()
    assert sorted((link.opportunity_id, link.notice_id, link.link_type, link.status) for link in confirmations) == sorted(
        [
            (p2_id, b6.id, "candidate", "후보 확인 대기"),
            (s2_id, b6.id, "candidate", "후보 확인 대기"),
        ]
    )
    warnings = [item for item in run_d.warnings if item["code"] == "opportunity_merge_confirmation_required"]
    assert len(warnings) == 1
    assert warnings[0]["context"]["owner_opportunity_id"] == b6_owner_id
    assert warnings[0]["context"]["held_opportunity_ids"] == sorted([p2_id, s2_id])
    assert "opportunity_merge_state_conflict" not in {item["code"] for item in run_d.warnings}
    for held_id, status in ((p2_id, "보류"), (s2_id, "계속 추적")):
        held = _detail(client, held_id)
        assert (held["tracking_status"], held["merged_into_opportunity_id"], held["recheck_signal"]) == (
            status,
            None,
            False,
        )
        assert (held["section"], held["action_reasons"]) == ("조치 필요", ["merge_confirmation"])
    b6_opportunity = _detail(client, b6_owner_id)
    assert (b6_opportunity["tracking_status"], b6_opportunity["first_registered_stage"]) == ("미선택", "bid_notice")
    assert _ids(client, section="조치 필요", reason="merge_confirmation") == sorted([p2_id, s2_id])
    assert _ids(client, section="신규 입찰공고") == sorted([n1_id, b6_owner_id])

    # ── 7. 색인에만 있는 B7을 가리키는 P3을 `보류`로 저장 → 추적 보충 ─────────────
    # 저장 시각은 한국 시간 자정 1마이크로초 뒤로 고정한다(8단계 경계).
    kst_midnight = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
    p3_selected_at = kst_midnight + timedelta(microseconds=1)
    with _router_clock(monkeypatch, p3_selected_at):
        held_p3 = _track(client, p3_id, "보류", "해양 예산 확정 대기")
    assert held_p3["tracking_status"] == "보류"
    assert datetime.fromisoformat(held_p3["tracking_selected_at"]) == p3_selected_at
    db = flow.read()
    b7 = _notice(db, B7_KEY)
    assert b7 is not None
    b7_row = _index_rows(db, run_b.run_id)[B7_KEY]
    assert (b7_row.selection_reason, b7_row.ingested_notice_id) == ("tracked_backfill", b7.id)
    assert [observation.run_id for observation in b7.observations] == [run_b.run_id]
    b7_link_id = _owning_link(db, b7).id
    assert _owner(db, notice=b7).id == p3_id
    assert b7.id in {link["notice_id"] for link in held_p3["links"]}
    assert held_p3["recheck_signal_link_id"] == b7_link_id
    assert _ack(client, p3_id, b7_link_id)["recheck_signal"] is False
    # 일일 CLI(`--tracked-backfill`)의 전체 추적 보충이 더 가져올 색인 레코드는 없다.
    with flow.sessions() as session:
        backfilled = tracked_backfill(session, runs_root=data_root / "runs")
        session.commit()
    assert backfilled == {"passes": 0, "candidates": 0, "loaded": {}, "unavailable": 0}

    # ── 8. 보류 +14일 경계: 기한 - 1µs(= KST 자정)는 아직, 기한 정각은 지남 ───────
    due = p3_selected_at + timedelta(days=14)
    just_before = due - timedelta(microseconds=1)
    assert (just_before.utcoffset(), just_before.hour, just_before.microsecond) == (timedelta(hours=9), 0, 0)
    sections_before = {"조치 필요": 3, "추적 중": 0, "보류": 1, "추적 종료": 0, "신규 입찰공고": 2, "미결정": 1}
    reasons_before = {
        "new_link": 1,  # P (회차 D의 B2)
        "candidate_pending": 0,
        "merge_confirmation": 2,  # P2, S2
        "blocking_item": 0,
        "hold_overdue": 0,
    }
    for now, overdue in ((just_before, False), (due, True)):
        with monkeypatch.context() as clock:
            # +09:00 기준 시각을 요청 clock과 workload 서비스에 주입한다.
            clock.setattr(opportunities_router, "_request_now", lambda now=now: now)
            clock.setattr(workload_router, "get_workload", lambda session, now=now: get_workload(session, now=now))
            p3 = _detail(client, p3_id)
            assert datetime.fromisoformat(p3["hold_review_due_at"]) == due
            listing = _listing(client)
            workload = {item["key"]: item["count"] for item in _ok(client.get("/api/workload"))["items"]}
            if overdue:
                assert (p3["section"], p3["action_reasons"]) == ("조치 필요", ["hold_overdue"])
                assert listing["section_counts"] == {**sections_before, "조치 필요": 4, "보류": 0}
                assert listing["action_reason_counts"] == {**reasons_before, "hold_overdue": 1}
                assert _ids(client, hold_review="overdue") == [p3_id]
                assert _ids(client, section="조치 필요", reason="hold_overdue") == [p3_id]
                assert (workload["tracking_hold_review_due"], workload["tracking_action_required"]) == (1, 4)
            else:
                assert (p3["section"], p3["action_reasons"]) == ("보류", [])
                assert listing["section_counts"] == sections_before
                assert listing["action_reason_counts"] == reasons_before
                assert _ids(client, hold_review="overdue") == []
                assert _ids(client, section="조치 필요", reason="hold_overdue") == []
                assert (workload["tracking_hold_review_due"], workload["tracking_action_required"]) == (0, 3)

    # ── 9. 공고 조건 근거 go → 3차수 도착 시 currentness `stale` ────────────────
    conditions = _ok(client.get(f"/api/opportunities/{p_id}/bid-conditions"))
    b2_sha = flow.read().scalars(
        select(NoticeObservation.source_sha256).where(
            NoticeObservation.notice_id == b2_notice_id, NoticeObservation.run_id == run_d.run_id
        )
    ).one()
    assert [row["notice_id"] for row in conditions["bid_notices"]] == [b1_notice_id, b2_notice_id]
    assert (conditions["latest_notice_id"], conditions["latest_observation_sha256"]) == (b2_notice_id, b2_sha)
    assert conditions["pre_spec"]["notice_id"] == s_notice_id
    decision = _ok(
        client.post(
            f"/api/opportunities/{p_id}/final-decisions",
            json={
                "request_id": str(uuid4()),
                "expected_notice_id": conditions["latest_notice_id"],
                "expected_observation_sha256": conditions["latest_observation_sha256"],
                "supersedes_final_decision_id": None,
                "decision": "go",
                "reason": "공고 조건 확인 후 참여",
            },
            headers=ACTOR,
        ),
        201,
    )
    assert (decision["basis_kind"], decision["basis_notice_id"], decision["currentness"]) == (
        "notice_conditions",
        b2_notice_id,
        "current",
    )
    (decision_audit,) = _audits(flow.read(), "bid_final_decision.recorded", decision["id"])
    assert (decision_audit.claimed_name, decision_audit.safe_metadata["opportunity_id"]) == (ACTOR_NAME, p_id)
    assert (decision_audit.safe_metadata["basis_kind"], decision_audit.safe_metadata["basis_notice_id"]) == (
        "notice_conditions",
        b2_notice_id,
    )
    workspace = _ok(client.get(f"/api/opportunities/{p_id}/bid-delta"))
    assert (workspace["decision_currentness"], workspace["currentness_reasons"]) == ("current", [])
    assert _ok(client.get("/api/bid-delta/decision-queue"))["items"] == []

    run_e_dir = _write_run(
        data_root,
        "lifecycle-20260918-notices",
        generated_at="2026-09-18T12:00:00+00:00",
        notices=[
            _bid_record(
                BID_X,
                "002",
                title=PLATFORM_TITLE,
                agency=AGENCY_P,
                published_at="2026-09-18T10:00:00+09:00",
            )
        ],
    )
    run_e = flow.collect(run_e_dir, _selection(bid_same_notice_no=1))
    db = flow.read()
    assert _reasons(db, run_e.run_id) == {B3_KEY: "bid_same_notice_no"}
    assert _owner(db, notice=_notice(db, B3_KEY)).id == p_id
    workspace = _ok(client.get(f"/api/opportunities/{p_id}/bid-delta"))
    assert workspace["latest_final_decision"]["id"] == decision["id"]
    assert (workspace["decision_currentness"], workspace["currentness_reasons"]) == ("stale", ["newer_bid_notice"])
    queue = _ok(client.get("/api/bid-delta/decision-queue"))["items"]
    assert [
        (item["opportunity_id"], item["decision_currentness"], item["latest_final_decision"]["decision"])
        for item in queue
    ] == [(p_id, "stale", "go")]

    # ── 10. 같은 공고 회차 C에 C-1 full_run 입력 적재 → 관측 snapshot 충돌 없음 ──
    # 수집 파일의 레코드를 orchestrator 투영(`_notice_common` 키 집합)으로 동결한다.
    # 모든 수집 bucket을 고르는 정책이라 회차 C의 레코드 전부가 입력이다. generated_at을
    # 수집 파일과 같게 두어 같은 Run으로 적재되고, 수집 적재가 남긴 관측과 snapshot을
    # 직접 대조한다.
    collected_c = json.loads((run_c_dir / "collected-notices.json").read_text(encoding="utf-8"))
    screening_input = {
        **_screening_input(run_c.run_id, collected_c["notices"]),
        "generated_at": run_c_generated,
    }
    assert screening_input_error(screening_input) is None
    (run_c_dir / "screening-input.json").write_bytes(
        json.dumps(screening_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    observed_c = {
        key: digest for key, digest in _observation_digests(flow.read()).items() if key[1] == run_c.run_id
    }
    assert set(observed_c) == {(key, run_c.run_id) for key in (B1_KEY, N1_KEY, S4_KEY, B4_KEY)}

    with flow.sessions() as session:
        screened = ingest_run(run_c_dir, session)

    assert screened.run_id == run_c.run_id
    assert not {"screening_input_invalid", "observation_snapshot_unavailable"} & {
        item["code"] for item in screened.warnings
    }
    after = _observation_digests(flow.read())
    assert {key: after[key] for key in observed_c} == observed_c
