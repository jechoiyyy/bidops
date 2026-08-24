import { EmptyState } from "../common/EmptyState";
import type { NoticeListItem } from "../../lib/types";
import { QueueListItem } from "./QueueListItem";

interface QueueListProps {
  notices: NoticeListItem[];
  selectedId: number | null;
  reviewedIds: Set<number>;
  total: number;
  onSelect: (noticePk: number) => void;
}

export function QueueList({ notices, selectedId, reviewedIds, total, onSelect }: QueueListProps) {
  return (
    <aside className="queue-list-pane" aria-label="검토 대기 공고 목록">
      <div className="queue-list-header">
        <span><strong className="mono tabular-nums">{total}</strong>건 · 선택한 정렬 기준</span>
        <span className="queue-list-hint">{reviewedIds.size > 0 ? `리뷰 ${reviewedIds.size}건` : "리뷰 없음"}</span>
      </div>
      <div className="queue-list-scroll">
        {notices.length === 0 ? (
          <EmptyState compact title="조건에 맞는 공고가 없습니다." description="필터를 넓혀 다른 공고를 확인하십시오." />
        ) : (
          notices.map((notice) => (
            <QueueListItem
              key={notice.id}
              notice={notice}
              reviewed={reviewedIds.has(notice.id)}
              selected={notice.id === selectedId}
              onClick={() => onSelect(notice.id)}
            />
          ))
        )}
      </div>
    </aside>
  );
}
