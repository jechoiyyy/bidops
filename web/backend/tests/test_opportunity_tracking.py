from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.ingest.loader import _merge_opportunities, ingest_run
from app.core.models import AuditEvent
from app.lifecycle.models import Notice, Opportunity, OpportunityLink
from app.services.opportunity_integrity import OpportunityIntegrityError
from app.services.opportunity_tracking import (
    raise_recheck_signal,
    set_tracking_status,
)


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
    return engine


def _opportunity(**kwargs):
    values = {"first_registered_stage": "pre_spec"}
    values.update(kwargs)
    return Opportunity(**values)


def _write_tracking_run(
    root: Path,
    directory_name: str,
    notice_id: str,
    plan_no: str,
    *,
    include_plan: bool = False,
) -> Path:
    run_dir = root / "runs" / directory_name
    run_dir.mkdir(parents=True, exist_ok=True)
    source_window = {
        "from": "2026-08-29",
        "to": "2026-08-29",
        "timezone": "Asia/Seoul",
    }
    validation = {
        "schema_version": "bidops.validation-set.v2",
        "generated_at": f"2026-08-29T{1 if include_plan else 2:02d}:00:00+00:00",
        "source_window": source_window,
        "notices": [
            {
                "notice_id": notice_id,
                "source_type": "bid_notice",
                "title": "공식 입찰공고",
                "lifecycle": {"order_plan_no": plan_no},
                "raw_source": "raw/notice.json",
            }
        ],
    }
    (run_dir / "validation-set.json").write_text(
        json.dumps(validation, ensure_ascii=False), encoding="utf-8"
    )
    if include_plan:
        plan_artifact = {
            "schema_version": "bidops.collected-order-plans.v1",
            "generated_at": "2026-08-29T01:00:00+00:00",
            "source_window": source_window,
            "counts": {"total": 1},
            "warnings": [],
            "order_plans": [
                {
                    "order_plan_unty_no": plan_no,
                    "title": "공식 발주계획",
                    "raw_source": "raw/order-plan.json",
                }
            ],
        }
        (run_dir / "collected-order-plans.json").write_text(
            json.dumps(plan_artifact, ensure_ascii=False), encoding="utf-8"
        )
    return run_dir


def test_new_opportunity_defaults_to_unselected_tracking_status():
    engine = _engine()
    try:
        with Session(engine) as session:
            opportunity = _opportunity()
            session.add(opportunity)
            session.commit()

            assert opportunity.tracking_status == "미선택"
            row = session.execute(
                select(Opportunity.tracking_status).where(Opportunity.id == opportunity.id)
            ).one()
            assert row[0] == "미선택"
    finally:
        engine.dispose()


def test_all_tracking_status_values_are_stored():
    engine = _engine()
    try:
        selected_at = datetime(2026, 8, 29, tzinfo=timezone.utc)
        opportunities = [
            _opportunity(tracking_status="미선택"),
            _opportunity(
                tracking_status="계속 추적",
                tracking_reason="공고 변화를 확인",
                tracking_selected_by="담당자-계속",
                tracking_selected_at=selected_at,
            ),
            _opportunity(
                tracking_status="보류",
                tracking_reason="선행 정보 대기",
                tracking_selected_by="담당자-보류",
                tracking_selected_at=selected_at,
            ),
            _opportunity(
                tracking_status="종료",
                tracking_reason="현재 추적 종료",
                tracking_selected_by="담당자-종료",
                tracking_selected_at=selected_at,
            ),
        ]
        with Session(engine) as session:
            session.add_all(opportunities)
            session.commit()

            values = session.scalars(
                select(Opportunity.tracking_status).order_by(Opportunity.id)
            ).all()
            assert values == ["미선택", "계속 추적", "보류", "종료"]
    finally:
        engine.dispose()


def test_tracking_status_rejects_value_outside_the_allowed_list():
    engine = _engine()
    try:
        with Session(engine) as session:
            session.add(_opportunity(tracking_status="관심 없음"))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


def test_unselected_tracking_status_cannot_have_a_human_author():
    engine = _engine()
    try:
        with Session(engine) as session:
            session.add(
                _opportunity(
                    tracking_status="미선택",
                    tracking_selected_by="아직 고르지 않은 사람",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "missing_field",
    ["tracking_selected_by", "tracking_selected_at"],
)
def test_selected_tracking_status_requires_human_author_and_time(missing_field):
    engine = _engine()
    try:
        values = {
            "tracking_status": "종료",
            "tracking_reason": "현재 추적 종료",
            "tracking_selected_by": "담당자",
            "tracking_selected_at": datetime(2026, 8, 29, tzinfo=timezone.utc),
        }
        values[missing_field] = None
        with Session(engine) as session:
            session.add(_opportunity(**values))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


def test_recheck_signal_is_independent_and_points_to_the_official_link():
    engine = _engine()
    try:
        selected_at = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
        signal_at = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
        with Session(engine) as session:
            notice = Notice(
                notice_key="bid:R26BK01696186:000",
                source_type="bid_notice",
                title="새 공식 공고",
            )
            opportunity = _opportunity(
                tracking_status="종료",
                tracking_reason="현재 추적 종료",
                tracking_selected_by="담당자",
                tracking_selected_at=selected_at,
            )
            session.add_all([notice, opportunity])
            session.flush()
            link = OpportunityLink(
                opportunity=opportunity,
                notice=notice,
                stage="notice",
                link_type="official",
                status="확정",
                evidence_external_no="R26BK01696186",
            )
            session.add(link)
            session.flush()

            opportunity.recheck_signal_at = signal_at
            opportunity.recheck_signal_link_id = link.id
            session.commit()
            session.expire_all()

            stored = session.get(Opportunity, opportunity.id)
            assert stored is not None
            assert stored.tracking_status == "종료"
            assert stored.tracking_reason == "현재 추적 종료"
            assert stored.tracking_selected_by == "담당자"
            assert stored.tracking_selected_at == selected_at
            assert stored.recheck_signal_at == signal_at
            assert stored.recheck_signal_link_id == link.id

            signal_link = session.get(OpportunityLink, stored.recheck_signal_link_id)
            assert signal_link is not None
            assert signal_link.opportunity_id == stored.id
            assert signal_link.notice_id == notice.id
    finally:
        engine.dispose()


def test_tracking_status_service_appends_human_history_including_reset_and_reselection():
    engine = _engine()
    try:
        with Session(engine) as session:
            opportunity = _opportunity()
            session.add(opportunity)
            session.commit()

            choices = [
                ("계속 추적", "변화를 확인", "담당자-계속", 1),
                ("계속 추적", "같은 상태를 재확인", "담당자-재확인", 2),
                ("보류", "선행 정보 대기", "담당자-보류", 3),
                ("미선택", "검토 큐로 되돌림", "담당자-복귀", 4),
            ]
            for status, reason, actor, hour in choices:
                set_tracking_status(
                    session,
                    opportunity,
                    status=status,
                    reason=reason,
                    selected_by=actor,
                    selected_at=datetime(2026, 8, 29, hour, tzinfo=timezone.utc),
                )
            session.commit()

            stored = session.get(Opportunity, opportunity.id)
            assert stored is not None
            assert stored.tracking_status == "미선택"
            assert stored.tracking_reason is None
            assert stored.tracking_selected_by is None
            assert stored.tracking_selected_at is None

            audits = session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.aggregate_type == "opportunity",
                    AuditEvent.aggregate_id == str(opportunity.id),
                    AuditEvent.action == "opportunity.tracking_status.changed",
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            ).all()
            assert len(audits) == len(choices)
            assert [audit.actor_kind for audit in audits] == ["human"] * len(choices)
            assert [audit.claimed_name for audit in audits] == [item[2] for item in choices]
            assert [audit.safe_metadata["tracking_status"] for audit in audits] == [
                item[0] for item in choices
            ]
            assert all(
                "검토 큐로 되돌림" not in str(audit.safe_metadata)
                and "API_KEY" not in str(audit.safe_metadata)
                for audit in audits
            )
    finally:
        engine.dispose()


def test_ingest_new_official_bid_signals_closed_opportunity_without_changing_human_tracking_choice(
    tmp_path,
):
    """The production ingest path changes only the independent signal fields."""

    engine = _engine()
    try:
        plan_no = "R26DD20999999"
        with Session(engine) as session:
            first_dir = _write_tracking_run(
                tmp_path,
                "tracking-first-run",
                "bid:R26BK01696186:000",
                plan_no,
                include_plan=True,
            )
            first = ingest_run(first_dir, session, reports_root=tmp_path / "reports")
            assert first.notices == 1 and first.order_plans == 1
            opportunity = session.scalar(select(Opportunity))
            assert opportunity is not None

            selected_at = datetime(2026, 8, 29, 9, tzinfo=timezone.utc)
            set_tracking_status(
                session,
                opportunity,
                status="종료",
                reason="현재 추적 종료",
                selected_by="담당자-종료",
                selected_at=selected_at,
            )
            session.commit()

            second_dir = _write_tracking_run(
                tmp_path,
                "tracking-second-run",
                "bid:R26BK01696187:000",
                plan_no,
            )
            second = ingest_run(second_dir, session, reports_root=tmp_path / "reports")
            assert second.notices == 1

            stored = session.get(Opportunity, opportunity.id)
            assert stored is not None
            assert stored.tracking_status == "종료"
            assert stored.tracking_reason == "현재 추적 종료"
            assert stored.tracking_selected_by == "담당자-종료"
            assert stored.tracking_selected_at == selected_at
            assert stored.recheck_signal_at is not None
            assert stored.recheck_signal_link_id is not None

            new_bid = session.scalar(
                select(Notice).where(Notice.notice_key == "bid:R26BK01696187:000")
            )
            assert new_bid is not None
            signal_link = session.get(OpportunityLink, stored.recheck_signal_link_id)
            assert signal_link is not None
            assert signal_link.opportunity_id == stored.id
            assert signal_link.notice_id == new_bid.id
            assert signal_link.link_type == "official"
            assert signal_link.status == "확정"

            audits = session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.aggregate_type == "opportunity",
                    AuditEvent.aggregate_id == str(stored.id),
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            ).all()
            human = [audit for audit in audits if audit.action == "opportunity.tracking_status.changed"]
            system = [audit for audit in audits if audit.action == "opportunity.recheck_signal.created"]
            assert len(human) == 1
            assert human[0].actor_kind == "human"
            assert human[0].claimed_name == "담당자-종료"
            assert len(system) == 1
            assert system[0].actor_kind == "system"
            assert system[0].claimed_name is None
            assert system[0].safe_metadata["link_id"] == signal_link.id
            assert system[0].safe_metadata["evidence_external_no"] == plan_no
            safe = str(system[0].safe_metadata)
            assert "공식 입찰공고" not in safe
            assert "API_KEY" not in safe
            assert "비밀번호" not in safe
    finally:
        engine.dispose()


@pytest.mark.parametrize("status", ["계속 추적", "보류"])
def test_ingest_does_not_raise_recheck_signal_for_non_closed_tracking_status(tmp_path, status):
    engine = _engine()
    try:
        plan_no = "R26DD20999999"
        with Session(engine) as session:
            first_dir = _write_tracking_run(
                tmp_path,
                "non-closed-first-run",
                "bid:R26BK01696186:000",
                plan_no,
                include_plan=True,
            )
            ingest_run(first_dir, session, reports_root=tmp_path / "reports")
            opportunity = session.scalar(select(Opportunity))
            assert opportunity is not None
            set_tracking_status(
                session,
                opportunity,
                status=status,
                reason="상태별 신호 정책 확인",
                selected_by="담당자",
                selected_at=datetime(2026, 8, 29, 9, tzinfo=timezone.utc),
            )
            session.commit()

            second_dir = _write_tracking_run(
                tmp_path,
                "non-closed-second-run",
                "bid:R26BK01696187:000",
                plan_no,
            )
            ingest_run(second_dir, session, reports_root=tmp_path / "reports")
            stored = session.get(Opportunity, opportunity.id)
            assert stored is not None
            assert stored.tracking_status == status
            assert stored.recheck_signal_at is None
            assert stored.recheck_signal_link_id is None
            assert session.scalar(
                select(AuditEvent).where(
                    AuditEvent.aggregate_type == "opportunity",
                    AuditEvent.aggregate_id == str(opportunity.id),
                    AuditEvent.action == "opportunity.recheck_signal.created",
                )
            ) is None
    finally:
        engine.dispose()


def test_recheck_signal_keeps_latest_distinct_official_link_and_deduplicates_same_link():
    engine = _engine()
    try:
        with Session(engine) as session:
            opportunity = _opportunity(
                tracking_status="종료",
                tracking_reason="현재 추적 종료",
                tracking_selected_by="담당자",
                tracking_selected_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
            )
            first_notice = Notice(notice_key="bid:R26BK01696186:000", source_type="bid_notice")
            second_notice = Notice(notice_key="bid:R26BK01696187:000", source_type="bid_notice")
            session.add_all([opportunity, first_notice, second_notice])
            session.flush()
            first_link = OpportunityLink(
                opportunity=opportunity,
                notice=first_notice,
                stage="notice",
                link_type="official",
                status="확정",
                evidence_external_no="R26BK01696186",
            )
            second_link = OpportunityLink(
                opportunity=opportunity,
                notice=second_notice,
                stage="notice",
                link_type="official",
                status="확정",
                evidence_external_no="R26BK01696187",
            )
            session.add_all([first_link, second_link])
            session.flush()

            first_at = datetime(2026, 8, 29, 10, tzinfo=timezone.utc)
            second_at = datetime(2026, 8, 29, 11, tzinfo=timezone.utc)
            assert raise_recheck_signal(session, opportunity, first_link, signaled_at=first_at)
            assert not raise_recheck_signal(session, opportunity, first_link, signaled_at=second_at)
            assert raise_recheck_signal(session, opportunity, second_link, signaled_at=second_at)
            session.commit()

            stored = session.get(Opportunity, opportunity.id)
            assert stored is not None
            assert stored.recheck_signal_link_id == second_link.id
            assert stored.recheck_signal_at == second_at
            events = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.aggregate_id == str(opportunity.id),
                    AuditEvent.action == "opportunity.recheck_signal.created",
                )
            ).all()
            assert len(events) == 2
            assert all(event.actor_kind == "system" for event in events)
            assert all(event.claimed_name is None for event in events)
    finally:
        engine.dispose()


def test_merge_with_human_selected_tracking_status_fails_closed():
    engine = _engine()
    try:
        with Session(engine) as session:
            primary = _opportunity(
                created_at=datetime(2026, 8, 29, 8, tzinfo=timezone.utc),
                tracking_status="종료",
                tracking_reason="현재 추적 종료",
                tracking_selected_by="담당자",
                tracking_selected_at=datetime(2026, 8, 29, 7, tzinfo=timezone.utc),
            )
            secondary = _opportunity(
                created_at=datetime(2026, 8, 29, 9, tzinfo=timezone.utc),
            )
            primary_notice = Notice(
                notice_key="bid:R26BK01696186:000",
                source_type="bid_notice",
            )
            secondary_notice = Notice(
                notice_key="bid:R26BK01698765:000",
                source_type="bid_notice",
            )
            session.add_all([primary, secondary, primary_notice, secondary_notice])
            session.flush()
            moved_link = OpportunityLink(
                opportunity=secondary,
                notice=secondary_notice,
                stage="notice",
                link_type="official",
                status="확정",
                evidence_external_no="R26BK01698765",
            )
            session.add(
                OpportunityLink(
                    opportunity=primary,
                    notice=primary_notice,
                    stage="notice",
                    link_type="official",
                    status="확정",
                    evidence_external_no="R26BK01696186",
                )
            )
            session.add(moved_link)
            session.flush()

            with pytest.raises(
                OpportunityIntegrityError,
                match="자동 병합할 수 없습니다",
            ):
                _merge_opportunities(session, [primary, secondary])
            session.commit()

            stored = session.get(Opportunity, primary.id)
            stored_secondary = session.get(Opportunity, secondary.id)
            assert stored is not None
            assert stored_secondary is not None
            assert stored.merged_into_opportunity_id is None
            assert stored_secondary.merged_into_opportunity_id is None
            assert stored.tracking_status == "종료"
            assert stored.tracking_reason == "현재 추적 종료"
            assert stored.tracking_selected_by == "담당자"
            assert stored.tracking_selected_at == datetime(2026, 8, 29, 7, tzinfo=timezone.utc)
            assert stored.recheck_signal_link_id is None
            assert moved_link.opportunity_id == stored_secondary.id
            assert session.scalar(
                select(AuditEvent).where(
                    AuditEvent.aggregate_id == str(primary.id),
                    AuditEvent.action == "opportunity.recheck_signal.created",
                )
            ) is None
    finally:
        engine.dispose()


def _legacy_opportunity_schema(engine):
    metadata = MetaData()
    Table(
        "opportunity",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("first_registered_stage", String(32), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        CheckConstraint(
            "first_registered_stage IN ('order_plan', 'pre_spec', 'bid_notice')",
            name="ck_opportunity_first_registered_stage",
        ),
    )
    Table("opportunity_link", metadata, Column("id", Integer, primary_key=True))
    Table(
        "screening_audit_event",
        metadata,
        Column("event_id", String(38), primary_key=True),
        Column("event_type", String(128), nullable=False),
        Column("actor", String(255), nullable=False),
        Column("target_type", String(128), nullable=False),
        Column("target_id", String(255), nullable=False),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
        Column("details_json", JSON, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO opportunity (first_registered_stage, created_at) "
                "VALUES ('pre_spec', '2026-08-29T00:00:00+00:00')"
            )
        )


def _run_revision(engine, operation):
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            operation()


def test_0007_upgrade_backfills_and_downgrade_restores_the_old_schema():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        _legacy_opportunity_schema(engine)
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "0007_opportunity_tracking_state.py"
        )
        spec = importlib.util.spec_from_file_location(
            "bidops_migration_0007", migration_path
        )
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        old_columns = {
            column["name"] for column in inspect(engine).get_columns("opportunity")
        }

        _run_revision(engine, migration.upgrade)
        upgraded_columns = {
            column["name"] for column in inspect(engine).get_columns("opportunity")
        }
        assert upgraded_columns == old_columns | {
            "tracking_status",
            "tracking_reason",
            "tracking_selected_by",
            "tracking_selected_at",
            "recheck_signal_at",
            "recheck_signal_link_id",
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT tracking_status FROM opportunity")) == "미선택"

        _run_revision(engine, migration.downgrade)
        assert {
            column["name"] for column in inspect(engine).get_columns("opportunity")
        } == old_columns
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM opportunity")) == 1
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM screening_audit_event "
                    "WHERE event_id = 'audit-4f7a9c2e1d6b4385a0f3e8c7b2d19460'"
                )
            ) == 0
    finally:
        engine.dispose()
