"""사전규격 10-13·10-14(KST 등록일) 공고만 첨부 취득만 (자동 준비·개요 등록은 web의 prepare 루프가 한다).

첨부 worker의 `run_once`(공고 한정)와 `prepare-overviews`가 쓰는 것과 같은
`maybe_auto_prepare` + `session.commit()`만 부른다. 모델은 부르지 않는다 —
개요 실행은 analysis worker가 한다. stdin으로 넣어 일회성 컨테이너에서 돈다.
"""

from sqlalchemy import select, func, cast, Date

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging_setup import configure
from app.lifecycle.models import Notice
from app.deep_review.services.auto_preparation import maybe_auto_prepare
from app.deep_review.services.overview_runs import active_run
from app.deep_review.workers import prespec_attachment as worker
from app.deep_review.services import assets
from app.core.clamav import ClamAVScanner

TARGET_DAYS = ("2026-10-13", "2026-10-14")

settings = get_settings()
configure(settings)
connectors = assets.g2b_attachment_connectors(settings)
assert connectors, "attachment connectors disabled"
scanner = ClamAVScanner(host=settings.clamav_host, port=settings.clamav_port, timeout=settings.clamav_timeout_seconds)

with SessionLocal() as session:
    day = cast(func.timezone("Asia/Seoul", Notice.published_at), Date)
    targets = [
        int(v) for v in session.scalars(
            select(Notice.id).where(
                Notice.source_type == "pre_spec",
                func.to_char(day, "YYYY-MM-DD").in_(TARGET_DAYS),
            ).order_by(Notice.id)
        ).all()
    ]
    session.rollback()
print(f"TARGETS {len(targets)}", flush=True)

for notice_id in targets:
    claimed = 0
    for _ in range(20):
        with SessionLocal() as session:
            try:
                ok = worker.run_once(
                    session, settings.worker_id, connectors=connectors,
                    lease_seconds=settings.prespec_attachment_lease_seconds,
                    clamav_checker=scanner.scan, notice_id=notice_id,
                )
            except Exception as error:  # noqa: BLE001
                session.rollback()
                print(f"FETCH_ERROR notice={notice_id} {type(error).__name__}", flush=True)
                ok = False
        if not ok:
            break
        claimed += 1
    print(f"NOTICE {notice_id} fetched={claimed}", flush=True)
print("DRIVER_DONE", flush=True)
