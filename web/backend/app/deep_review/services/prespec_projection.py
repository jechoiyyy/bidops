"""사전규격 개요·문서 projection의 deep_review 구현 (명세 §6.1 둘째 행).

lifecycle의 `GET /api/pre-specs`는 누적 목록이라 회차 상한이 없다. 그래서 세
메서드 모두 호출부가 넘긴 `notice_ids`를 batch projection으로 처리하고,
공고 수에 따라 조회를 늘리지 않는다. 개요 상태는 공고별 최신 run 하나이며,
run이 없는 공고는 빠뜨린다 — `None`/0으로 채우는 것은 lifecycle의 몫이다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select

from ...lifecycle import AcquiredAttachmentFile, PreSpecDocumentCounts, WorkloadCount
from ..models import AttachmentFetch, ContentObject, DocumentVersion
from ...lifecycle.models import Attachment, Notice
from .auto_preparation import auto_preparation_fields
from .display_assessment import display_assessments
from .overview_runs import current_runs, overview_status_for

# attachment_fetch.status 값 → PreSpecDocumentCounts 필드. 응답 별칭(완료·대기·
# 진행·차단·실패)은 lifecycle의 응답 모델이 붙인다.
_FETCH_STATUS_FIELDS: Mapping[str, str] = {
    "완료": "completed",
    "대기": "pending",
    "진행": "running",
    "차단": "blocked",
    "실패": "failed",
}


def _distinct_ids(notice_ids: Sequence[int]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(int(value) for value in notice_ids))


class AcquiredAttachmentFiles:
    """`AcquiredAttachmentFilesProvider` 제공자.

    첨부의 **현재 문서 version**에서 실제 파일명과 크기를 읽는다. 짝은
    `document_version.attachment_id`이고(첨부당 current는 unique index로 하나다) 순번·주소·
    이름으로 맞추지 않는다. 안전 검사 상태는 가리지 않는다 — 파일명은 취득 응답의 metadata일
    뿐이고 원문을 열 수 있는지는 묶음·검사 상태가 따로 말한다.
    """

    def acquired_attachment_files(
        self, session: Any, attachment_ids: Sequence[int]
    ) -> Mapping[int, AcquiredAttachmentFile]:
        ids = _distinct_ids(attachment_ids)
        if not ids:
            return {}
        rows = session.execute(
            select(
                DocumentVersion.attachment_id,
                DocumentVersion.original_filename,
                ContentObject.size_bytes,
            )
            .join(ContentObject, ContentObject.id == DocumentVersion.content_object_id)
            .where(DocumentVersion.attachment_id.in_(ids), DocumentVersion.is_current.is_(True))
        ).all()
        files: dict[int, AcquiredAttachmentFile] = {}
        for attachment_id, filename, size_bytes in rows:
            if not filename:
                continue
            # 확장자 표기는 첨부 등록(`file_ext`)과 같은 규칙이다: 접미사를 대문자로, 없으면 미확인.
            suffix = PurePosixPath(filename).suffix.upper().lstrip(".")
            files[int(attachment_id)] = AcquiredAttachmentFile(
                filename=filename,
                file_ext=suffix or None,
                size_bytes=int(size_bytes) if size_bytes is not None else None,
            )
        return files


class PreSpecOverviewDocumentProjection:
    """`OverviewDocumentProjection` 제공자."""

    def _overview_statuses(
        self, session: Any, notice_ids: Sequence[int]
    ) -> dict[int, str]:
        """공고별 최신 개요 run의 상태 하나. batch 조회 한 번이다."""

        ids = _distinct_ids(notice_ids)
        if not ids:
            return {}
        runs = current_runs(session, ids)
        statuses = {notice_id: overview_status_for(runs.get(notice_id)) for notice_id in ids}
        return {notice_id: status for notice_id, status in statuses.items() if status is not None}

    def overview_status(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, str]:
        return self._overview_statuses(session, notice_ids)

    def overview_status_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[str, int]:
        return dict(Counter(self._overview_statuses(session, notice_ids).values()))

    def document_counts(
        self, session: Any, notice_ids: Sequence[int]
    ) -> Mapping[int, PreSpecDocumentCounts]:
        ids = _distinct_ids(notice_ids)
        if not ids:
            return {}
        # 은퇴한 첨부의 취득 행은 세지 않는다. lifecycle이 `attachments`를 셀 때와
        # 같은 조건이라 두 숫자의 모집단이 같다.
        rows = session.execute(
            select(
                Attachment.notice_id,
                AttachmentFetch.status,
                func.count(AttachmentFetch.id),
            )
            .join(Attachment, Attachment.id == AttachmentFetch.attachment_id)
            .where(Attachment.notice_id.in_(ids), Attachment.retired_at.is_(None))
            .group_by(Attachment.notice_id, AttachmentFetch.status)
        ).all()
        grouped: dict[int, dict[str, int]] = {}
        for notice_id, status, count in rows:
            field = _FETCH_STATUS_FIELDS.get(status)
            if field is None:
                continue
            grouped.setdefault(int(notice_id), {})[field] = int(count or 0)
        return {
            notice_id: PreSpecDocumentCounts(**fields) for notice_id, fields in grouped.items()
        }

    def prespec_status_fields(
        self, session: Any, notice_ids: Sequence[int]
    ) -> Mapping[int, Mapping[str, Any]]:
        """등급·자동 준비 상태·최신 심층 검토 (명세 §8).

        계산은 자동 준비 서비스가 갖는다. projection은 확장점 서명을 맞추고
        결과를 그대로 넘긴다 — 상태의 뜻을 두 곳에서 정의하지 않는다.
        """

        ids = _distinct_ids(notice_ids)
        if not ids:
            return {}
        fields = {notice_id: dict(value) for notice_id, value in auto_preparation_fields(session, ids).items()}
        runs = current_runs(session, ids)
        assessments = display_assessments(session, ids, latest_runs=runs)
        # 회사 핏 요약(PS-01 C6)은 최신 카드 lineage attempt로만 정한다.
        from .company_fit import card_fit_summaries

        fits = card_fit_summaries(session, ids, runs=runs)
        for notice_id in ids:
            fields.setdefault(notice_id, {})["display_assessment"] = assessments[notice_id]
            fields[notice_id]["company_fit"] = fits[notice_id]
        return fields

    def notice_ids_for_auto_preparation_status(
        self, session: Any, notice_ids: Sequence[int], status: str
    ) -> Sequence[int]:
        ids = _distinct_ids(notice_ids)
        if not ids:
            return []
        fields = auto_preparation_fields(session, ids)
        return [
            notice_id
            for notice_id in ids
            if fields.get(notice_id, {}).get("auto_preparation_status") == status
        ]


#: `사람 확인 필요` 패널의 개요 하위 건수가 세는 상태. 두 상태는 서로 배타적이라
#: 사전규격 목록 `overview_view=failed`·`overview_view=attention`의 `total` 합과 같다
#: (ADR-0067 §7.1). `pending` 계열과 run 부재(`null`)는 사람을 기다리지 않는다.
_HUMAN_REVIEW_OVERVIEW_STATUSES = ("failed", "needs_human_review")

class DeepReviewWorkloadProjection:
    """deep_review가 소유한 업무 건수. 대상이 없으면 실제 0이다."""

    def workload_counts(self, session: Any) -> Mapping[str, WorkloadCount]:
        from .company_knowledge import company_attention_count
        from .decision_queue import decision_queue
        from .engine_review import workload_counts as engine_review_counts

        notice_ids = session.scalars(select(Notice.id).where(Notice.source_type == "pre_spec")).all()
        projection = PreSpecOverviewDocumentProjection()
        # 사전규격 `검토할 항목`·`확인 필요` 건수(`pre_spec_actionable`·`pre_spec_needs_check`)는
        # lifecycle이 목록 질의 그 자체로 센다(2026-11-19). 옛 `pre_spec_deep_review_ready`는
        # 여기서 기존 심층 검토 "클릭 대기"를 세었고 마감·검토 제외·SW 조건을 보지 않아
        # 목록 건수와 달랐다.
        statuses = projection.overview_status_counts(session, notice_ids)
        return {
            "bid_final_decision_pending": WorkloadCount(decision_queue(session, limit=1)["total"]),
            "overview_human_review": WorkloadCount(
                sum(int(statuses.get(status, 0)) for status in _HUMAN_REVIEW_OVERVIEW_STATUSES)
            ),
            # RL-00 사이드바 "회사 근거" pill. 실회사·활성 binding이 없으면 null과 사유다.
            "company_attention": WorkloadCount(*company_attention_count(session)),
            **engine_review_counts(session),
        }


__all__ = ["DeepReviewWorkloadProjection", "PreSpecOverviewDocumentProjection"]
