"""수집 색인·선별 적재·추적 보충 (spec §1.2·§2·§5).

회차 디렉터리는 수집기 현재 출력 모양(`bidops.collected.v2`, 새 optional 키 포함)으로
직접 만든다. lifecycle 단독 동작을 보므로 확장점은 비워 둔다(`empty_extensions`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.core.generation_config import GenerationConfig
from app.lifecycle import SCREENING_COMMON_NOTICE_KEYS, ingest_run, screening_input_error
from app.lifecycle.ingest import cli
from app.lifecycle.ingest.contracts import NoticeContract
from app.lifecycle.ingest.loader import _upsert_notice, tracked_backfill
from app.lifecycle.models import (
    CollectedRecordIndex,
    CollectedRecordToken,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    Run,
)
from app.lifecycle.services.name_matching import normalize
from app.lifecycle.services.opportunity_integrity import authoritative_link_predicate
from app.lifecycle.services.opportunity_tracking import set_tracking_status


WINDOW = {"from": "2026-09-14", "to": "2026-09-16", "timezone": "Asia/Seoul"}
GENERATED = "2026-09-16T00:00:00+00:00"

QUALIFICATION_KEYS = (
    "participation_limited", "industry_limited", "information_business", "general_service",
    "service_division", "joint_contract_method", "performance_restricted_competition",
    "pq_evaluation", "technical_evaluation", "technical_evaluation_rate", "successful_bid_method",
)

# `main` 3344076(새 optional 키 이전)의 `_upsert_notice`로 계산한 관측 digest다.
# 과거 회차 산출물을 다시 적재해도 이 값이 바뀌면 안 된다.
OLD_BID = {
    "notice_id": "bid:R26BK01690001:000",
    "source_type": "bid_notice",
    "title": "데이터 플랫폼 고도화 용역",
    "agency": "테스트 수요기관",
    "published_at": "2026-09-15T10:00:00+09:00",
    "deadline_at": "2026-09-25T18:00:00+09:00",
    "budget": "150000000",
    "estimated_price": None,
    "method": "제한경쟁",
    "url": "https://example.invalid/bid",
    "procurement_class": {"large": "용역", "middle": "SW 및 시스템 개발", "detail": "개발", "code": "01"},
    "region_limit": {"basis": None, "joint_contract_regions": [], "joint_contract_rate": None, "regional_joint_contract_limit": None},
    "lifecycle": {"pre_spec_no": None, "order_plan_no": None, "re_notice": "N", "changed_at": None, "change_reason": None, "unified_notice_no": None, "previous_failed_notice_no": None},
    "attachments": [{"name": "제안요청서", "url": "https://example.invalid/rfp.hwp"}],
    "qualification_flags": {"participation_limited": "Y", "industry_limited": "Y", "information_business": "Y", "general_service": "N", "service_division": "일반용역", "joint_contract_method": None, "performance_restricted_competition": "N", "pq_evaluation": "N", "technical_evaluation": "Y", "technical_evaluation_rate": "90", "successful_bid_method": "협상에 의한 계약"},
    "focus_matches": [],
    "performance_matches": [],
    "performance_top_score": None,
    "candidate_sources": [],
    "collection_bucket": "audit_pool",
    "unknown_fields": [],
    "raw_source": "raw/bid-page-001.json",
}
OLD_BID_SHA256 = "2201ffef0b77c6f622105a834d974c4b87b833141e14ba914534e046e1dece3b"
OLD_PRE_SPEC = {
    "notice_id": "pre:R26BD00270001",
    "source_type": "pre_spec",
    "title": "행정정보 시스템 구축 사전규격",
    "agency": "테스트 발주기관",
    "published_at": "2026-09-14T09:00:00+09:00",
    "deadline_at": "2026-09-19T18:00:00+09:00",
    "budget": "300000000",
    "estimated_price": None,
    "method": None,
    "url": None,
    "procurement_class": {"large": None, "middle": None, "detail": "소프트웨어개발", "code": "81111598"},
    "region_limit": {"basis": None, "joint_contract_regions": [], "joint_contract_rate": None, "regional_joint_contract_limit": None},
    "lifecycle": {"pre_spec_no": "R26BD00270001", "re_notice": None, "changed_at": None, "change_reason": None, "unified_notice_no": None, "previous_failed_notice_no": None, "bid_ntice_no_list": None},
    "attachments": [],
    "qualification_flags": {**dict.fromkeys(QUALIFICATION_KEYS), "sw_business_status": "Y", "business_division": "일반용역"},
    "focus_matches": [],
    "performance_matches": [],
    "performance_top_score": None,
    "candidate_sources": [],
    "collection_bucket": "audit_pool",
    "unknown_fields": ["attachments"],
    "raw_source": "raw/prespec-page-001.json",
}
OLD_PRE_SPEC_SHA256 = "3ed16ef501f65c444fb282c6082f6e687bac9a824b3e0764ea405cfec9659966"


def _session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    return Session(engine)


def _bid(
    bid_no: str,
    order: str = "000",
    *,
    title: str = "공공 데이터 분석 시스템 구축",
    method: str | None = "일반경쟁",
    order_plan_no: str | None = None,
    pre_spec_no: str | None = None,
    sw_industry_1468: str | None = None,
    opening_at: str | None = None,
) -> dict[str, Any]:
    """Current collector bid shape, including the new optional keys."""

    return {
        "notice_id": f"bid:{bid_no}:{order}",
        "source_type": "bid_notice",
        "title": title,
        "agency": "테스트 수요기관",
        "demand_agency": None,
        "published_at": "2026-09-15T10:00:00+09:00",
        "deadline_at": "2026-09-25T18:00:00+09:00",
        "budget": "100000000",
        "estimated_price": None,
        "method": method,
        "url": "https://example.invalid/bid",
        "procurement_class": {"large": "용역", "middle": None, "detail": None, "code": None},
        "region_limit": {"basis": None, "joint_contract_regions": [], "joint_contract_rate": None, "regional_joint_contract_limit": None},
        "lifecycle": {
            "pre_spec_no": pre_spec_no,
            "order_plan_no": order_plan_no,
            "re_notice": "N",
            "changed_at": None,
            "change_reason": None,
            "unified_notice_no": None,
            "previous_failed_notice_no": None,
            "opening_at": opening_at,
        },
        "attachments": [],
        "qualification_flags": {**dict.fromkeys(QUALIFICATION_KEYS), "sw_industry_1468": sw_industry_1468},
        "focus_matches": [],
        "performance_matches": [],
        "performance_top_score": None,
        "candidate_sources": [],
        "collection_bucket": "audit_pool",
        "unknown_fields": [],
        "raw_source": "raw/bid-page-001.json",
    }


def _pre_spec(
    number: str,
    *,
    sw: str | None = "Y",
    title: str = "행정정보 시스템 구축 사전규격",
    demand_agency: str | None = None,
    bid_ntice_no_list: str | None = None,
) -> dict[str, Any]:
    """Current collector pre-spec shape, including the new optional keys."""

    return {
        "notice_id": f"pre:{number}",
        "source_type": "pre_spec",
        "title": title,
        "agency": "테스트 발주기관",
        "demand_agency": demand_agency,
        "published_at": "2026-09-14T09:00:00+09:00",
        "deadline_at": "2026-09-19T18:00:00+09:00",
        "budget": "300000000",
        "estimated_price": None,
        "method": None,
        "url": None,
        "procurement_class": {"large": None, "middle": None, "detail": "소프트웨어개발", "code": "81111598"},
        "region_limit": {"basis": None, "joint_contract_regions": [], "joint_contract_rate": None, "regional_joint_contract_limit": None},
        "lifecycle": {
            "pre_spec_no": number,
            "re_notice": None,
            "changed_at": None,
            "change_reason": None,
            "unified_notice_no": None,
            "previous_failed_notice_no": None,
            "opening_at": None,
            "bid_ntice_no_list": bid_ntice_no_list,
        },
        "attachments": [],
        "qualification_flags": {
            **dict.fromkeys(QUALIFICATION_KEYS),
            "sw_business_status": sw,
            "business_division": "일반용역",
            "sw_industry_1468": None,
        },
        "focus_matches": [],
        "performance_matches": [],
        "performance_top_score": None,
        "candidate_sources": [],
        "collection_bucket": "audit_pool",
        "unknown_fields": [],
        "raw_source": "raw/prespec-page-001.json",
    }


def _plan(number: str, *, title: str = "통합 행정 플랫폼 구축", bid_ntice_no_list: str | None = None) -> dict[str, Any]:
    return {
        "order_plan_unty_no": number,
        "title": title,
        "agency_code": "1234567",
        "agency_name": "테스트 발주기관",
        "published_at": "2026-09-10T09:00:00+09:00",
        "contract_method": "제한경쟁",
        "bid_ntice_no_list": bid_ntice_no_list,
        "sw_business_status": None,
        "source_sha256": "a" * 64,
        "raw_source": "raw/page-00001.json",
    }


def _write_run(
    root: Path,
    name: str,
    *,
    generated_at: str = GENERATED,
    plans: list[dict[str, Any]] | None = None,
    notices: list[dict[str, Any]] | None = None,
) -> Path:
    run_dir = root / "runs" / name
    run_dir.mkdir(parents=True)
    if plans is not None:
        (run_dir / "collected-order-plans.json").write_text(
            json.dumps(
                {
                    "schema_version": "bidops.collected-order-plans.v1",
                    "generated_at": generated_at,
                    "source_window": WINDOW,
                    "counts": {"total": len(plans)},
                    "order_plans": plans,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    if notices is not None:
        (run_dir / "collected-notices.json").write_text(
            json.dumps(
                {
                    "schema_version": "bidops.collected.v2",
                    "generated_at": generated_at,
                    "source_window": WINDOW,
                    "counts": {"total": len(notices), "candidate_pool": 0, "audit_pool": len(notices)},
                    "warnings": [],
                    "metadata": {"sw_industry_1468": {"status": "complete", "total": 1, "pages": 1}},
                    "notices": notices,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return run_dir


def _index_rows(session: Session, run_id: str) -> dict[str, CollectedRecordIndex]:
    return {
        row.record_key: row
        for row in session.scalars(
            select(CollectedRecordIndex).where(CollectedRecordIndex.run_id == run_id)
        )
    }


def _observation_digests(session: Session) -> dict[tuple[str, str], str]:
    return {
        (notice_key, run_id): digest
        for notice_key, run_id, digest in session.execute(
            select(Notice.notice_key, NoticeObservation.run_id, NoticeObservation.source_sha256)
            .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        )
    }


def _owner(session: Session, *, order_plan: OrderPlan | None = None, notice: Notice | None = None) -> Opportunity:
    statement = (
        select(Opportunity)
        .join(OpportunityLink, OpportunityLink.opportunity_id == Opportunity.id)
        .where(authoritative_link_predicate(OpportunityLink))
    )
    if order_plan is not None:
        statement = statement.where(OpportunityLink.order_plan_id == order_plan.id)
    else:
        assert notice is not None
        statement = statement.where(OpportunityLink.notice_id == notice.id)
    return session.scalars(statement).one()


def _track(session: Session, opportunity: Opportunity, status: str) -> None:
    set_tracking_status(
        session,
        opportunity,
        status=status,
        reason="담당자 추적 결정",
        selected_by="담당자",
        selected_at=datetime(2026, 9, 16, 1, tzinfo=timezone.utc),
    )
    session.commit()


def _notice(session: Session, key: str) -> Notice | None:
    return session.scalar(select(Notice).where(Notice.notice_key == key))


PLAN_A = "R26DD20850001"
PLAN_B = "R26DD20850002"
PRE_Y = "R26BD00271001"
PRE_N = "R26BD00271002"
BID_A = "R26BK01691001"
BID_B = "R26BK01691002"
BID_C = "R26BK01691003"


def test_every_record_is_indexed_once_and_a_rerun_is_a_no_op(tmp_path, empty_extensions):
    run_dir = _write_run(
        tmp_path,
        "lifecycle-20260916-notices",
        plans=[
            _plan(PLAN_A, title="[재공고] 통합·행정 플랫폼 구축", bid_ntice_no_list=f"{BID_A}000, {BID_B}001"),
            _plan(PLAN_B),
        ],
        notices=[
            _pre_spec(PRE_Y, demand_agency="수요기관 갑", bid_ntice_no_list=f"{BID_A}, ,{BID_B}"),
            _pre_spec(PRE_N, sw="N"),
            _bid(BID_A, sw_industry_1468="Y"),
            _bid(BID_B, sw_industry_1468="N"),
            _bid(BID_C),
        ],
    )
    with _session() as session:
        first = ingest_run(run_dir, session, selection="collection")
        rows = _index_rows(session, first.run_id)
        assert sorted((row.record_kind, key) for key, row in rows.items()) == sorted(
            [
                ("order_plan", PLAN_A),
                ("order_plan", PLAN_B),
                ("pre_spec", f"pre:{PRE_Y}"),
                ("pre_spec", f"pre:{PRE_N}"),
                ("bid_notice", f"bid:{BID_A}:000"),
                ("bid_notice", f"bid:{BID_B}:000"),
                ("bid_notice", f"bid:{BID_C}:000"),
            ]
        )
        plan_row = rows[PLAN_A]
        assert plan_row.title_normalized == normalize("[재공고] 통합·행정 플랫폼 구축")
        assert [token.token for token in plan_row.tokens] == [f"{BID_A}000", f"{BID_B}001"]
        pre_row = rows[f"pre:{PRE_Y}"]
        assert [token.token for token in pre_row.tokens] == [BID_A, BID_B]
        assert pre_row.bf_spec_rgst_no == PRE_Y and pre_row.demand_agency == "수요기관 갑"
        bid_row = rows[f"bid:{BID_A}:000"]
        assert (bid_row.bid_no, bid_row.bid_ord, bid_row.sw_industry_1468) == (BID_A, "000", "Y")
        assert rows[f"bid:{BID_C}:000"].sw_industry_1468 is None

        assert {key: row.selection_reason for key, row in rows.items()} == {
            PLAN_A: "order_plan_all",
            PLAN_B: "order_plan_all",
            f"pre:{PRE_Y}": "pre_spec_sw",
            f"pre:{PRE_N}": None,
            f"bid:{BID_A}:000": "bid_sw_industry_competitive",
            f"bid:{BID_B}:000": None,
            f"bid:{BID_C}:000": None,
        }
        loaded_pre = _notice(session, f"pre:{PRE_Y}")
        assert loaded_pre is not None and pre_row.ingested_notice_id == loaded_pre.id
        assert loaded_pre.demand_agency == "수요기관 갑"
        assert plan_row.ingested_order_plan_id == session.scalar(
            select(OrderPlan.id).where(OrderPlan.order_plan_unty_no == PLAN_A)
        )
        assert rows[f"bid:{BID_B}:000"].ingested_notice_id is None
        assert _notice(session, f"pre:{PRE_N}") is None and _notice(session, f"bid:{BID_C}:000") is None

        expected_selection = {
            "order_plan": {"collected": 2, "selected": {"order_plan_all": 2}, "skipped": 0},
            "pre_spec": {
                "collected": 2,
                "selected": {"pre_spec_sw": 1, "pre_spec_referenced": 0},
                "skipped": 1,
            },
            "bid_notice": {
                "collected": 3,
                "selected": {
                    "bid_same_notice_no": 0,
                    "bid_tracked_reference": 0,
                    "bid_sw_prespec_reference": 0,
                    "bid_sw_industry_competitive": 1,
                },
                "skipped": 2,
            },
        }
        assert first.selection == expected_selection
        assert first.as_dict()["selection"] == expected_selection
        assert first.notices == 2 and first.order_plans == 2
        assert session.get(Run, first.run_id).counts_json["selection"] == expected_selection
        # Exclusion is statistics, not a warning.
        assert not any(item["level"] == "error" for item in first.warnings)
        assert not any(item["code"] == "unknown_field" for item in first.warnings)

        digests = _observation_digests(session)
        row_ids = {key: row.id for key, row in rows.items()}
        token_count = session.scalar(select(func.count()).select_from(CollectedRecordToken))

        second = ingest_run(run_dir, session, selection="collection")

        assert second.run_id == first.run_id
        assert second.selection == expected_selection
        rerun_rows = _index_rows(session, first.run_id)
        assert {key: row.id for key, row in rerun_rows.items()} == row_ids
        assert {key: row.selection_reason for key, row in rerun_rows.items()} == {
            key: row.selection_reason for key, row in rows.items()
        }
        assert session.scalar(select(func.count()).select_from(CollectedRecordToken)) == token_count
        assert _observation_digests(session) == digests


PLAN_TRACKED = "R26DD20852001"
PRE_TRACKED = "R26BD00272001"
PRE_OLD = "R26BD00272002"
PRE_NEW_SW = "R26BD00272003"
BID_EXISTING = "R26BK01692001"
BID_ORDER_PLAN = "R26BK01692002"
BID_PLAN_TOKEN = "R26BK01692003"
BID_PRESPEC_TOKEN = "R26BK01692004"
BID_BFSPEC_TRACKED = "R26BK01692005"
BID_SW_PRESPEC = "R26BK01692006"
BID_REFERENCED = "R26BK01692007"
BID_PAIR = "R26BK01692008"


def test_each_selection_reason_and_its_precedence(tmp_path, empty_extensions):
    run1_dir = _write_run(
        tmp_path,
        "lifecycle-20260915-notices",
        generated_at="2026-09-15T00:00:00+00:00",
        plans=[_plan(PLAN_TRACKED, bid_ntice_no_list=f"{BID_PLAN_TOKEN}000")],
        notices=[
            _pre_spec(PRE_TRACKED, sw="Y", bid_ntice_no_list=BID_PRESPEC_TOKEN),
            _pre_spec(PRE_OLD, sw="N"),
            _bid(BID_EXISTING, "000", sw_industry_1468="Y"),
        ],
    )
    run2_dir = _write_run(
        tmp_path,
        "lifecycle-20260916-notices",
        notices=[
            _bid(BID_EXISTING, "001"),
            _bid(BID_ORDER_PLAN, order_plan_no=PLAN_TRACKED, sw_industry_1468="Y"),
            _bid(BID_PLAN_TOKEN, "000"),
            _bid(BID_PRESPEC_TOKEN, "000"),
            _bid(BID_BFSPEC_TRACKED, pre_spec_no=PRE_TRACKED),
            _pre_spec(PRE_NEW_SW, sw="Y"),
            _bid(BID_SW_PRESPEC, pre_spec_no=PRE_NEW_SW),
            _bid(BID_REFERENCED, pre_spec_no=PRE_OLD, sw_industry_1468="Y"),
            _bid(BID_PAIR, "001"),
            _bid(BID_PAIR, "000", sw_industry_1468="Y"),
        ],
    )
    with _session() as session:
        run1 = ingest_run(run1_dir, session, selection="collection")
        assert _index_rows(session, run1.run_id)[f"pre:{PRE_OLD}"].selection_reason is None
        _track(session, _owner(session, order_plan=session.scalar(select(OrderPlan))), "계속 추적")
        _track(session, _owner(session, notice=_notice(session, f"pre:{PRE_TRACKED}")), "보류")

        run2 = ingest_run(run2_dir, session, selection="collection")

        reasons = {key: row.selection_reason for key, row in _index_rows(session, run2.run_id).items()}
        assert reasons == {
            # another order of the same bid number is already in the database
            f"bid:{BID_EXISTING}:001": "bid_same_notice_no",
            # tracked orderPlanUntyNo wins over the 1468 tag
            f"bid:{BID_ORDER_PLAN}:000": "bid_tracked_reference",
            # plan bidNtceNoList token (bid number + order) of a tracked plan
            f"bid:{BID_PLAN_TOKEN}:000": "bid_tracked_reference",
            # pre-spec bidNtceNoList token (bid number) of a tracked pre-spec
            f"bid:{BID_PRESPEC_TOKEN}:000": "bid_tracked_reference",
            # tracked bfSpecRgstNo wins over the SW pre-spec rule
            f"bid:{BID_BFSPEC_TRACKED}:000": "bid_tracked_reference",
            f"pre:{PRE_NEW_SW}": "pre_spec_sw",
            f"bid:{BID_SW_PRESPEC}:000": "bid_sw_prespec_reference",
            f"bid:{BID_REFERENCED}:000": "bid_sw_industry_competitive",
            # selected by the order of the same bid number in this run,
            # independent of the file order
            f"bid:{BID_PAIR}:001": "bid_same_notice_no",
            f"bid:{BID_PAIR}:000": "bid_sw_industry_competitive",
        }
        assert all(_notice(session, key) is not None for key in reasons)

        # The referenced SW=N pre-spec existed only in the earlier run's index.
        # It is loaded from that run's file and observed in that run.
        old_row = _index_rows(session, run1.run_id)[f"pre:{PRE_OLD}"]
        old_notice = _notice(session, f"pre:{PRE_OLD}")
        assert old_notice is not None
        assert old_row.selection_reason == "pre_spec_referenced"
        assert old_row.ingested_notice_id == old_notice.id
        assert [item.run_id for item in old_notice.observations] == [run1.run_id]
        assert session.get(Run, run1.run_id).counts_json["notices"] == 3

        assert run2.selection["bid_notice"] == {
            "collected": 9,
            "selected": {
                "bid_same_notice_no": 2,
                "bid_tracked_reference": 4,
                "bid_sw_prespec_reference": 1,
                "bid_sw_industry_competitive": 2,
            },
            "skipped": 0,
        }
        assert run2.selection["pre_spec"]["selected"] == {"pre_spec_sw": 1, "pre_spec_referenced": 0}
        tokens = set(session.scalars(select(CollectedRecordToken.token)))
        assert {f"{BID_PLAN_TOKEN}000", BID_PRESPEC_TOKEN} <= tokens


def test_null_or_non_competitive_conditions_never_select(tmp_path, empty_extensions):
    unknown_pre = "R26BD00273001"
    run_dir = _write_run(
        tmp_path,
        "lifecycle-20260916-notices",
        notices=[
            _pre_spec(unknown_pre, sw=None),
            _bid("R26BK01693001", sw_industry_1468=None, method="일반경쟁"),
            _bid("R26BK01693002", sw_industry_1468="Y", method="수의계약"),
            _bid("R26BK01693003", sw_industry_1468="Y", method=None),
            _bid("R26BK01693004", sw_industry_1468="N", method="일반경쟁"),
            _bid("R26BK01693005", pre_spec_no=unknown_pre),
            _bid("R26BK01693006", order_plan_no="R26DD20853999"),
        ],
    )
    with _session() as session:
        result = ingest_run(run_dir, session, selection="collection")

        rows = _index_rows(session, result.run_id)
        assert all(row.selection_reason is None for row in rows.values())
        assert rows[f"pre:{unknown_pre}"].sw_business_status is None
        assert rows["bid:R26BK01693001:000"].sw_industry_1468 is None
        assert session.scalar(select(func.count()).select_from(Notice)) == 0
        assert session.scalar(select(func.count()).select_from(Opportunity)) == 0
        assert result.notices == 0
        assert result.selection["pre_spec"] == {
            "collected": 1,
            "selected": {"pre_spec_sw": 0, "pre_spec_referenced": 0},
            "skipped": 1,
        }
        assert result.selection["bid_notice"]["collected"] == 6
        assert result.selection["bid_notice"]["skipped"] == 6
        assert sum(result.selection["bid_notice"]["selected"].values()) == 0
        assert result.selection["order_plan"] == {
            "collected": 0,
            "selected": {"order_plan_all": 0},
            "skipped": 0,
        }


def test_old_artifacts_keep_their_digest_and_new_null_keys_do_not_change_it(empty_extensions):
    with _session() as session:
        for run_id in ("old-run--20260915T000000Z", "new-run--20260916T000000Z", "rich-run--20260917T000000Z"):
            session.add(Run(id=run_id, generated_at=datetime(2026, 9, 15, tzinfo=timezone.utc)))
        session.flush()

        def observe(run_id: str, record: dict[str, Any]) -> NoticeObservation:
            notice = _upsert_notice(
                session, run_id, NoticeContract.model_validate(record), record, "Asia/Seoul"
            )
            session.flush()
            return session.scalars(
                select(NoticeObservation).where(
                    NoticeObservation.notice_id == notice.id, NoticeObservation.run_id == run_id
                )
            ).one()

        old_bid = observe("old-run--20260915T000000Z", OLD_BID)
        old_pre = observe("old-run--20260915T000000Z", OLD_PRE_SPEC)
        assert (old_bid.source_sha256, old_pre.source_sha256) == (OLD_BID_SHA256, OLD_PRE_SPEC_SHA256)
        # Same-run replay of the old artifact is a no-op, not a conflict.
        assert observe("old-run--20260915T000000Z", OLD_BID).id == old_bid.id

        new_bid = {
            **OLD_BID,
            "demand_agency": None,
            "lifecycle": {**OLD_BID["lifecycle"], "opening_at": None},
            "qualification_flags": {**OLD_BID["qualification_flags"], "sw_industry_1468": None},
        }
        new_pre = {
            **OLD_PRE_SPEC,
            "demand_agency": "수요기관 병",
            "lifecycle": {**OLD_PRE_SPEC["lifecycle"], "opening_at": None},
            "qualification_flags": {**OLD_PRE_SPEC["qualification_flags"], "sw_industry_1468": None},
        }
        assert observe("new-run--20260916T000000Z", new_bid).source_sha256 == OLD_BID_SHA256
        assert observe("new-run--20260916T000000Z", new_pre).source_sha256 == OLD_PRE_SPEC_SHA256
        pre_notice = _notice(session, OLD_PRE_SPEC["notice_id"])
        assert pre_notice.demand_agency == "수요기관 병"
        assert "opening_at" not in pre_notice.lifecycle_json
        assert "sw_industry_1468" not in pre_notice.qualification_flags_json

        # A value is part of the observed record once it is present.
        rich_bid = {
            **new_bid,
            "lifecycle": {**new_bid["lifecycle"], "opening_at": "2026-09-26T11:00:00+09:00"},
            "qualification_flags": {**new_bid["qualification_flags"], "sw_industry_1468": "Y"},
        }
        rich = observe("rich-run--20260917T000000Z", rich_bid)
        assert rich.source_sha256 != OLD_BID_SHA256
        bid_notice = _notice(session, OLD_BID["notice_id"])
        assert bid_notice.lifecycle_json["opening_at"] == "2026-09-26T11:00:00+09:00"
        assert bid_notice.qualification_flags_json["sw_industry_1468"] == "Y"


def _screening_input(run_id: str, records: list[dict[str, Any]], *, extra: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The fixed C-1 full-run projection of collected records (orchestrator shape)."""

    config = GenerationConfig()
    notices = []
    for record in records:
        notice = {key: record.get(key) for key in SCREENING_COMMON_NOTICE_KEYS}
        notice.update({"judgment_mode": "신규", "carry_over_from": None, "rejudge_reason": None})
        notice.update((extra or {}).get(record["notice_id"], {}))
        notices.append(notice)
    return {
        "schema_version": "bidops.screening-input.v1",
        "execution_id": "scr-" + "c" * 32,
        "run_id": run_id,
        "generated_at": GENERATED,
        "source_window": WINDOW,
        "policy_version": "screening-policy.test",
        "prompt_version": "prompt.test",
        "company_profile_version": "company-profile.sha256:" + "d" * 64,
        "company_profile_digest": "d" * 64,
        "candidate_count": len(notices),
        "notices": notices,
        "generation_config": config.canonical_value(),
        "generation_config_digest": config.digest(),
    }


def test_collection_then_screening_input_of_the_same_run_does_not_conflict(tmp_path, empty_extensions):
    pre = _pre_spec("R26BD00274001", sw="Y", demand_agency="수요기관 을")
    bid = _bid(
        "R26BK01694001",
        pre_spec_no="R26BD00274001",
        sw_industry_1468="Y",
        opening_at="2026-09-26T11:00:00+09:00",
    )
    run_dir = _write_run(tmp_path, "lifecycle-20260916-notices", notices=[pre, bid])
    with _session() as session:
        collected = ingest_run(run_dir, session, selection="collection")
        assert collected.notices == 2
        digests = _observation_digests(session)
        observation_count = session.scalar(select(func.count()).select_from(NoticeObservation))

        value = _screening_input(
            collected.run_id,
            [pre, bid],
            # The importer also accepts the optional top-level key; it does not
            # take part in the observation snapshot either.
            extra={pre["notice_id"]: {"demand_agency": "수요기관 을"}},
        )
        assert screening_input_error(value) is None
        (run_dir / "screening-input.json").write_bytes(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )

        screened = ingest_run(run_dir, session)

        assert screened.run_id == collected.run_id
        assert "selection" not in screened.as_dict()
        assert not any(item["code"] == "screening_input_invalid" for item in screened.warnings)
        assert screened.notices == 2
        assert session.scalar(select(func.count()).select_from(NoticeObservation)) == observation_count
        assert _observation_digests(session) == digests
        stored_bid = _notice(session, bid["notice_id"])
        assert stored_bid.lifecycle_json["opening_at"] == "2026-09-26T11:00:00+09:00"
        assert stored_bid.qualification_flags_json["sw_industry_1468"] == "Y"
        assert _notice(session, pre["notice_id"]).demand_agency == "수요기관 을"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda notice: notice.update(unexpected="value"), "notice fields are not exact"),
        (lambda notice: notice.update(demand_agency=" "), "notice string is invalid"),
        (lambda notice: notice["lifecycle"].update(opening_at="2026-09-26T11:00:00"), "lifecycle timestamp is invalid"),
        (lambda notice: notice["lifecycle"].update(unexpected="value"), "notice nested fields are not exact"),
        (lambda notice: notice["qualification_flags"].update(sw_industry_1468="X"), "qualification flags are invalid"),
    ],
)
def test_screening_input_accepts_only_the_declared_optional_keys(mutate, reason):
    notice = _bid("R26BK01695001", sw_industry_1468="N", opening_at="2026-09-26T11:00:00+09:00")
    value = _screening_input("source-run", [notice])
    assert screening_input_error(value) is None
    mutate(value["notices"][0])
    assert screening_input_error(value) == reason


def test_tracked_backfill_loads_an_index_only_bid_after_tracking_starts(tmp_path, empty_extensions):
    plan_no = "R26DD20855001"
    bid_key = "bid:R26BK01696001:000"
    run_dir = _write_run(
        tmp_path,
        "lifecycle-20260916-notices",
        plans=[_plan(plan_no)],
        notices=[_bid("R26BK01696001", order_plan_no=plan_no, sw_industry_1468="N")],
    )
    with _session() as session:
        ingested = ingest_run(run_dir, session, selection="collection")
        bid_row = _index_rows(session, ingested.run_id)[bid_key]
        assert bid_row.selection_reason is None and _notice(session, bid_key) is None

        idle = tracked_backfill(session, runs_root=run_dir.parent)
        assert idle == {"passes": 0, "candidates": 0, "loaded": {}, "unavailable": 0}

        plan = session.scalar(select(OrderPlan).where(OrderPlan.order_plan_unty_no == plan_no))
        opportunity = _owner(session, order_plan=plan)
        _track(session, opportunity, "계속 추적")

        result = tracked_backfill(session, runs_root=run_dir.parent)
        session.commit()

        assert result == {
            "passes": 1,
            "candidates": 1,
            "loaded": {"tracked_backfill": 1},
            "unavailable": 0,
        }
        bid = _notice(session, bid_key)
        assert bid is not None
        session.refresh(bid_row)
        assert bid_row.selection_reason == "tracked_backfill"
        assert bid_row.ingested_notice_id == bid.id
        assert [item.run_id for item in bid.observations] == [ingested.run_id]
        assert _owner(session, notice=bid).id == opportunity.id
        assert tracked_backfill(session, runs_root=run_dir.parent)["passes"] == 0


@pytest.mark.parametrize(
    "argv",
    [[], ["--collection"], ["--all", "--collection"], ["--all", "--tracked-backfill"]],
)
def test_ingest_cli_rejects_mode_combinations_before_touching_the_database(argv):
    with pytest.raises(SystemExit) as exited:
        cli.main(argv)
    assert exited.value.code == 2
