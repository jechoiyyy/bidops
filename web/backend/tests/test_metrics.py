from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle.models import Notice, NoticeObservation, Run
from app.screening.models import Judgment, Perspective
from app.services.metrics import calculate_validation_metrics


def test_validation_metrics_keep_unmeasurable_values_as_null():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    with Session(engine) as session:
        first_run = Run(
            id="metric-run-1",
            window_from=date(2026, 8, 1),
            window_to=date(2026, 8, 7),
            generated_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        )
        second_run = Run(
            id="metric-run-2",
            window_from=date(2026, 8, 8),
            window_to=date(2026, 8, 14),
            generated_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        )
        first_notice = Notice(
            run=first_run,
            notice_key="bid:SAME:000",
            sample_role="analysis",
        )
        first_judgment = Judgment(notice=first_notice, grade="검토 권장", readiness="부분 확인 필요")
        second_notice = first_notice
        second_judgment = first_judgment
        second_run.notice_observations.append(
            NoticeObservation(notice=first_notice, changed_fields_json=[])
        )
        second_judgment.perspectives.extend(
            [
                Perspective(name="기술", assessment="적합"),
                Perspective(name="사업성", assessment="확인 불가"),
            ]
        )
        session.add_all([first_run, second_run, first_judgment])
        session.commit()

        metrics = {item.key: item for item in calculate_validation_metrics(session, second_run.id)}

    assert metrics["reproducibility"].status == "not_measurable"
    assert metrics["discriminative_power"].value == 0
    assert metrics["evidence_validity"].status == "not_measurable"
    assert metrics["evidence_validity"].value is None
    assert metrics["perspective_split"].value == 1
