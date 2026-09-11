"""사전규격 개요 MVP 실사용 검증 깔때기 (읽기 전용).

`source_type='pre_spec'` 공고만 본다. 발주계획·입찰공고는 다루지 않는다.
DB에 아무것도 쓰지 않으며, 공고 id 목록·원문·경로는 출력하지 않는다.

실행:
    BIDOPS_DATABASE_URL=... python scripts/validation/overview_funnel.py [--json] [--since YYYY-MM-DD]

`collect_funnel(session, since=None)`은 이 파일이 import될 때 이미 정의돼
있으므로 backend venv의 pytest가 그대로 가져다 쓸 수 있다.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web/backend"))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.constants import DEEP_REVIEW_CREATION_ACTION_BY_ACTOR_KIND  # noqa: E402
from app.core.models import AuditEvent  # noqa: E402
from app.deep_review.models import (  # noqa: E402
    AttachmentFetch,
    DeepReview,
    DocumentBundle,
    PrespecOverviewRun,
)
from app.deep_review.services.auto_preparation import auto_preparation_fields  # noqa: E402
from app.deep_review.services.effective_grade import priority_notice_ids  # noqa: E402
from app.lifecycle.models import Attachment, Notice, NoticeObservation  # noqa: E402

#: attachment_fetch가 더 진행되지 않는 상태 (명세: 대기·진행만 미종결).
TERMINAL_FETCH_STATUSES = {"완료", "차단", "실패"}
#: prespec_overview_run.status의 전체 값 (표에 0건도 보이도록 고정 순서로 둔다).
RUN_STATUSES = ("queued", "running", "completed", "needs_human_review", "failed", "cancelled")
RANGE_SOURCES = ("auto", "fallback", "human")
TOP_N = 5

SCHEMA = "bidops.overview-funnel.v1"


def _percent(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(part * 100.0 / whole, 1)


def _top_reasons(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"reason": reason, "count": count} for reason, count in counter.most_common(TOP_N)]


def _is_sw_business(flags: Any) -> bool:
    return isinstance(flags, dict) and flags.get("sw_business_status") == "Y"


def collect_funnel(session: Session, since: date | None = None) -> dict[str, Any]:
    """사전규격 실사용 검증 깔때기를 단계별로 집계한다 (읽기 전용, 상수 회 조회).

    `since`가 있으면 공고의 첫 관측(`NoticeObservation.observed_at`의 최솟값)이
    그 날짜 이상인 것만 본다. `Notice`에는 `created_at` 컬럼이 없어 이 값을
    대신 쓴다.
    """

    # 1) 사전규격 전체 (+선택적 since).
    scope_query = select(Notice.id, Notice.qualification_flags_json).where(
        Notice.source_type == "pre_spec"
    )
    if since is not None:
        since_at = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
        first_observed = (
            select(
                NoticeObservation.notice_id.label("notice_id"),
                func.min(NoticeObservation.observed_at).label("first_observed_at"),
            )
            .group_by(NoticeObservation.notice_id)
            .subquery()
        )
        scope_query = scope_query.join(
            first_observed, first_observed.c.notice_id == Notice.id
        ).where(first_observed.c.first_observed_at >= since_at)
    scope_rows = session.execute(scope_query).all()
    total_pre_spec = len(scope_rows)
    notice_ids = [int(row.id) for row in scope_rows]
    sw_ids = {int(row.id) for row in scope_rows if _is_sw_business(row.qualification_flags_json)}

    # 2) 자격 후보: SW사업대상=Y 또는 effective grade `우선 검토`.
    priority_ids = set(priority_notice_ids(session, notice_ids)) if notice_ids else set()
    candidate_ids = sorted(sw_ids | priority_ids)
    candidates = len(candidate_ids)

    # 3) 첨부 취득 완료 공고, 전부 종결됐지만 완료 0건인 공고.
    error_codes: Counter[str] = Counter()
    attachment_completed = 0
    attachment_all_terminal_zero_completed = 0
    if candidate_ids:
        fetch_rows = session.execute(
            select(Attachment.notice_id, AttachmentFetch.status, AttachmentFetch.last_error_code)
            .join(AttachmentFetch, AttachmentFetch.attachment_id == Attachment.id)
            .where(Attachment.notice_id.in_(candidate_ids), Attachment.retired_at.is_(None))
        ).all()
        statuses_by_notice: dict[int, list[str]] = defaultdict(list)
        for notice_id, status, last_error_code in fetch_rows:
            statuses_by_notice[int(notice_id)].append(status)
            if last_error_code:
                error_codes[last_error_code] += 1
        for statuses in statuses_by_notice.values():
            if "완료" in statuses:
                attachment_completed += 1
            elif statuses and all(status in TERMINAL_FETCH_STATUSES for status in statuses):
                attachment_all_terminal_zero_completed += 1

    # 4) 묶음 ready 공고 (공고별 최신 revision 기준).
    bundle_ready = 0
    if candidate_ids:
        bundle_rows = session.execute(
            select(DocumentBundle.notice_id, DocumentBundle.revision, DocumentBundle.status).where(
                DocumentBundle.notice_id.in_(candidate_ids)
            )
        ).all()
        latest_bundle: dict[int, tuple[int, str]] = {}
        for notice_id, revision, status in bundle_rows:
            notice_id = int(notice_id)
            current = latest_bundle.get(notice_id)
            if current is None or revision > current[0]:
                latest_bundle[notice_id] = (revision, status)
        bundle_ready = sum(1 for _, status in latest_bundle.values() if status == "ready")

    # 5) 개요 run: 공고별 최신 run의 status·range_source 분포.
    reason_code_counter: Counter[str] = Counter()
    warning_counter: Counter[str] = Counter()
    latest_run: dict[int, Any] = {}
    if candidate_ids:
        run_rows = session.execute(
            select(
                PrespecOverviewRun.notice_id,
                PrespecOverviewRun.created_at,
                PrespecOverviewRun.status,
                PrespecOverviewRun.range_source,
                PrespecOverviewRun.reason_codes,
                PrespecOverviewRun.warnings_json,
            ).where(PrespecOverviewRun.notice_id.in_(candidate_ids))
        ).all()
        for row in run_rows:
            notice_id = int(row.notice_id)
            current = latest_run.get(notice_id)
            if current is None or row.created_at > current.created_at:
                latest_run[notice_id] = row
        for run in latest_run.values():
            if run.status in ("failed", "needs_human_review"):
                codes = run.reason_codes if isinstance(run.reason_codes, list) else []
                reason_code_counter.update(str(code) for code in codes)
            codes = run.warnings_json if isinstance(run.warnings_json, list) else []
            warning_counter.update(str(code) for code in codes)

    has_run = len(latest_run)
    status_distribution = {
        status: sum(1 for run in latest_run.values() if run.status == status)
        for status in RUN_STATUSES
    }
    range_source_distribution = {
        source: sum(1 for run in latest_run.values() if run.range_source == source)
        for source in RANGE_SOURCES
    }
    overview_completed = status_distribution["completed"]

    # 6) 이탈 사유 상위 5 (자동 준비 미충족 사유는 기존 배치 함수를 재사용).
    auto_prep_counter: Counter[str] = Counter()
    if candidate_ids:
        fields = auto_preparation_fields(session, candidate_ids)
        for info in fields.values():
            reason = info.get("auto_preparation_reason")
            if reason:
                auto_prep_counter[str(reason)] += 1

    # 7) 심층 검토 자동 시작 수. `deep_review.auto_create` 감사 action이
    #    사람 클릭(`deep_review.create`)과 자동 시작을 가르는 판별 필드다.
    deep_review_total = 0
    deep_review_auto_started = 0
    if candidate_ids:
        deep_review_rows = session.execute(
            select(DeepReview.id).where(DeepReview.notice_id.in_(candidate_ids))
        ).all()
        deep_review_total = len(deep_review_rows)
        if deep_review_rows:
            system_action = DEEP_REVIEW_CREATION_ACTION_BY_ACTOR_KIND["system"]
            review_ids = [str(row.id) for row in deep_review_rows]
            deep_review_auto_started = len(
                set(
                    session.scalars(
                        select(AuditEvent.aggregate_id).where(
                            AuditEvent.aggregate_type == "deep_review",
                            AuditEvent.action == system_action,
                            AuditEvent.aggregate_id.in_(review_ids),
                        )
                    ).all()
                )
            )

    return {
        "schema": SCHEMA,
        "since": since.isoformat() if since is not None else None,
        "total_pre_spec": total_pre_spec,
        "candidates": {
            "count": candidates,
            "pct_of_total": _percent(candidates, total_pre_spec),
        },
        "attachment": {
            "completed": {
                "count": attachment_completed,
                "pct_of_candidates": _percent(attachment_completed, candidates),
            },
            "all_terminal_zero_completed": {
                "count": attachment_all_terminal_zero_completed,
                "pct_of_candidates": _percent(attachment_all_terminal_zero_completed, candidates),
            },
        },
        "bundle_ready": {
            "count": bundle_ready,
            "pct_of_attachment_completed": _percent(bundle_ready, attachment_completed),
        },
        "overview_run": {
            "has_run": {
                "count": has_run,
                "pct_of_bundle_ready": _percent(has_run, bundle_ready),
            },
            "status_distribution": {
                status: {"count": count, "pct_of_has_run": _percent(count, has_run)}
                for status, count in status_distribution.items()
            },
            "range_source_distribution": {
                source: {"count": count, "pct_of_has_run": _percent(count, has_run)}
                for source, count in range_source_distribution.items()
            },
        },
        "dropoff_reasons": {
            "attachment_last_error_code": _top_reasons(error_codes),
            "overview_run_reason_codes": _top_reasons(reason_code_counter),
            "overview_run_warnings": _top_reasons(warning_counter),
            "auto_preparation_reason": _top_reasons(auto_prep_counter),
        },
        "deep_review_auto_start": {
            "count": deep_review_auto_started,
            "total_deep_reviews": deep_review_total,
            "pct_of_overview_completed": _percent(deep_review_auto_started, overview_completed),
        },
    }


def _format_table(result: dict[str, Any]) -> str:
    lines: list[str] = []
    since = result["since"] or "전체 기간"
    lines.append(f"사전규격 개요 MVP 실사용 검증 깔때기 (since={since})")
    lines.append("-" * 60)
    lines.append(f"1. 사전규격 전체                        : {result['total_pre_spec']:>6}건")
    candidates = result["candidates"]
    lines.append(
        f"2. 자격 후보(SW=Y 또는 우선 검토)        : {candidates['count']:>6}건"
        f" ({candidates['pct_of_total']:5.1f}% of 1)"
    )
    attachment = result["attachment"]
    completed = attachment["completed"]
    zero = attachment["all_terminal_zero_completed"]
    lines.append(
        f"3. 첨부 취득 완료(1건 이상)              : {completed['count']:>6}건"
        f" ({completed['pct_of_candidates']:5.1f}% of 2)"
    )
    lines.append(
        f"   - 첨부 전부 종결, 완료 0건            : {zero['count']:>6}건"
        f" ({zero['pct_of_candidates']:5.1f}% of 2)"
    )
    bundle = result["bundle_ready"]
    lines.append(
        f"4. 문서 묶음 ready(최신 revision)        : {bundle['count']:>6}건"
        f" ({bundle['pct_of_attachment_completed']:5.1f}% of 3)"
    )
    overview = result["overview_run"]
    has_run = overview["has_run"]
    lines.append(
        f"5. 개요 run 존재(공고별 최신 run)        : {has_run['count']:>6}건"
        f" ({has_run['pct_of_bundle_ready']:5.1f}% of 4)"
    )
    lines.append("   상태 분포 (개요 run 존재 대비 %):")
    for status, entry in overview["status_distribution"].items():
        lines.append(f"     {status:<20}: {entry['count']:>6}건 ({entry['pct_of_has_run']:5.1f}%)")
    lines.append("   range_source 분포 (개요 run 존재 대비 %):")
    for source, entry in overview["range_source_distribution"].items():
        lines.append(f"     {source:<20}: {entry['count']:>6}건 ({entry['pct_of_has_run']:5.1f}%)")
    lines.append("6. 이탈 사유 상위 5")
    dropoff = result["dropoff_reasons"]
    labels = {
        "attachment_last_error_code": "(a) 첨부 취득 실패 코드",
        "overview_run_reason_codes": "(b) 개요 run 실패/사람검토 사유 코드",
        "overview_run_warnings": "(c) 개요 run 경고 코드",
        "auto_preparation_reason": "(d) 자동 준비 미충족 사유",
    }
    for key, label in labels.items():
        entries = dropoff[key]
        if not entries:
            lines.append(f"   {label}: 없음")
            continue
        rendered = ", ".join(f"{item['reason']}={item['count']}" for item in entries)
        lines.append(f"   {label}: {rendered}")
    deep_review = result["deep_review_auto_start"]
    lines.append(
        "7. 심층 검토 자동 시작"
        f"                    : {deep_review['count']:>6}건"
        f" (자동 시작 판별: `deep_review.auto_create` 감사 action;"
        f" 후보 공고의 심층 검토 전체 {deep_review['total_deep_reviews']}건 중,"
        f" 개요 completed {deep_review['pct_of_overview_completed']:5.1f}% 대비)"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="표 대신 JSON 하나를 출력한다")
    parser.add_argument(
        "--since", type=date.fromisoformat, default=None, help="YYYY-MM-DD, 공고 첫 관측일 기준"
    )
    args = parser.parse_args()

    from app.core.db import SessionLocal

    with SessionLocal() as session:
        result = collect_funnel(session, since=args.since)

    if args.json:
        import json

        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(_format_table(result))


if __name__ == "__main__":
    main()
