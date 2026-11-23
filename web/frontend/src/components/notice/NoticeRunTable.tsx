import { useEffect, useRef } from "react";
import { DeadlineText, StatusMark } from "../common/Marks";
import { RecordTable, type RecordTableColumn, type RecordTableState } from "../common/RecordTable";
import { useRowKeyboardNavigation } from "../common/useRowKeyboardNavigation";
import { NoticeGradeMark } from "./NoticeMarks";
import { describeDeadline } from "../../lib/deadline";
import { formatNumber, present } from "../../lib/format";
import type { NoticeListItem, ReviewResponse } from "../../lib/types";

interface NoticeRunTableProps {
  label: string;
  notices: NoticeListItem[];
  selectedId: number | null;
  total: number;
  listNote: string;
  detailNote?: string;
  reviews?: ReadonlyMap<number, ReviewResponse>;
  onSelect: (noticePk: number) => void;
  state?: RecordTableState;
}

export function NoticeRunTable({
  label, notices, selectedId, total, listNote, detailNote, reviews, onSelect, state,
}: NoticeRunTableProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const navigation = useRowKeyboardNavigation({
    containerRef: viewportRef,
    keys: notices.map((notice) => notice.id),
    selectedKey: selectedId,
    onSelect,
  });

  useEffect(() => {
    const viewport = viewportRef.current;
    const row = viewport?.querySelector('tr[aria-current="true"]');
    if (!viewport || !row) return;
    const viewportBox = viewport.getBoundingClientRect();
    const rowBox = row.getBoundingClientRect();
    const headerHeight = viewport.querySelector("thead")?.getBoundingClientRect().height ?? 0;
    // Restore the active row without moving the page or the table's horizontal scroll.
    const top = rowBox.top - viewportBox.top - headerHeight;
    const bottom = rowBox.bottom - viewportBox.bottom;
    if (top < 0) viewport.scrollTop += top;
    else if (bottom > 0) viewport.scrollTop += bottom;
  }, [notices, selectedId]);

  const reviewedCount = reviews ? notices.filter((notice) => reviews.has(notice.id)).length : 0;
  const progress = notices.length > 0 ? Math.round((reviewedCount / notices.length) * 100) : 0;
  const columns: RecordTableColumn<NoticeListItem>[] = [
    {
      key: "title", header: "사업명", title: (notice) => present(notice.title, "공고명 미확인"),
      renderBelow: (notice) => {
        const agency = notice.agency?.trim();
        return agency ? <span className="record-table-ellipsis record-table-note notice-run-agency" title={agency}>{agency}</span> : null;
      },
    },
    {
      key: "state", header: "상태", width: 112, renderCell: (notice) => {
        const review = reviews?.get(notice.id);
        return (
          <div className="record-table-status notice-run-status">
            <NoticeGradeMark grade={notice.grade} />
            {notice.readiness?.trim() ? <StatusMark mark={{ label: notice.readiness, tone: "neutral" }} /> : null}
            {review ? <span className="record-table-note">{present(review.disposition, "리뷰 기록 있음")}</span> : null}
          </div>
        );
      },
    },
    {
      key: "deadline", header: "마감", width: 124,
      renderCell: (notice) => {
        const deadline = describeDeadline(notice.deadline_at);
        return <DeadlineText text={deadline.label} urgency={deadline.urgency} />;
      },
    },
  ];

  return (
    <aside aria-label={label} className="notice-run-list">
      <div className="notice-run-list-head">
        <div>
          <span><strong>{formatNumber(total)}</strong>건 · {listNote}</span>
          {reviews ? <span>리뷰 <strong>{formatNumber(reviewedCount)}</strong> / {formatNumber(notices.length)}</span> : null}
          {detailNote ? <span>{detailNote}</span> : null}
        </div>
        {reviews && notices.length > 0 ? (
          <div className="queue-list-progress" role="progressbar" aria-valuemin={0} aria-valuemax={notices.length} aria-valuenow={reviewedCount} aria-label="리뷰 진행률">
            <span style={{ width: `${progress}%` }} />
          </div>
        ) : null}
      </div>
      <RecordTable
        activeKey={selectedId}
        columns={columns}
        getKey={(notice) => notice.id}
        label={label}
        navigation={navigation}
        onActivate={onSelect}
        rows={notices}
        state={state}
        viewportRef={viewportRef}
      />
    </aside>
  );
}
