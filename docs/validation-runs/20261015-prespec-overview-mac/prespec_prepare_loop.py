"""web 컨테이너에서 10-13·10-14 대상 중 첨부가 모두 종결된 공고만 자동 준비 → 커밋.

`prepare-overviews`와 같은 `maybe_auto_prepare(session, [id]); session.commit()`이며,
web은 개요 정책 경로(v7-litellm-v2)를 가진다. 2분마다 돌고, 첨부 드라이버가 끝나고
더 할 일이 없으면 끝난다. 모델은 부르지 않는다.
"""
import os, time
from sqlalchemy import select, func, cast, Date
from app.core.db import SessionLocal
from app.lifecycle.models import Notice
from app.deep_review.cli.prepare_overviews import eligible_notice_ids, notices_with_runs
from app.deep_review.services.auto_preparation import maybe_auto_prepare
from app.deep_review.services.overview_runs import active_run

TARGET_DAYS = ("2026-10-13", "2026-10-14")
done_flag = "/tmp/prespec-driver-done"
idle_after_done = 0
while True:
    with SessionLocal() as s:
        day = cast(func.timezone("Asia/Seoul", Notice.published_at), Date)
        targets = set(int(v) for v in s.scalars(select(Notice.id).where(
            Notice.source_type == "pre_spec", func.to_char(day, "YYYY-MM-DD").in_(TARGET_DAYS))).all())
        ready = [n for n in eligible_notice_ids(s) if n in targets]
        existing = notices_with_runs(s, ready)
        pending = [n for n in ready if n not in existing]
        s.rollback()
        for n in pending:
            outcome = maybe_auto_prepare(s, [n])[0]
            s.commit()
            q = active_run(s, n) is not None
            s.rollback()
            print(f"PREP {n} {outcome.reason or 'confirmed'} {'queued' if q else '-'}", flush=True)
    if os.path.exists(done_flag):
        idle_after_done += 1
        if idle_after_done >= 2:
            print("PREP_LOOP_DONE", flush=True)
            break
    time.sleep(120)
