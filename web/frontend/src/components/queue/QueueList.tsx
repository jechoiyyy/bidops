import { Fragment, useMemo } from "react";
import { EmptyState } from "../common/EmptyState";
import { DenseList } from "../common/ReviewPrimitives";
import type { NoticeListItem, ReviewResponse } from "../../lib/types";
import { formatNumber } from "../../lib/format";
import { gradeRailClass, gradeRank } from "../../lib/grade";
import { QueueListItem } from "./QueueListItem";
import type { QueueFilterValues } from "./QueueFilters";

interface QueueListProps {
  notices: NoticeListItem[];
  selectedId: number | null;
  reviews: Map<number, ReviewResponse>;
  total: number;
  sort: QueueFilterValues["sort"];
  onSelect: (noticePk: number) => void;
}

const sortLabels: Record<QueueFilterValues["sort"], string> = {
  grade: "등급순",
  deadline: "마감 임박순",
  published: "공고일순",
};

interface GradeGroup {
  grade: string;
  items: NoticeListItem[];
}

/**
 * 등급순으로 볼 때만 등급 머리글을 세운다.
 * 다른 정렬에서는 같은 등급이 흩어지므로 머리글이 오히려 목록을 끊어 놓는다.
 */
function groupByGrade(notices: NoticeListItem[]): GradeGroup[] {
  const groups: GradeGroup[] = [];
  for (const notice of notices) {
    const grade = notice.grade?.trim() || "등급 미확인";
    const last = groups[groups.length - 1];
    if (last && last.grade === grade) {
      last.items.push(notice);
    } else {
      groups.push({ grade, items: [notice] });
    }
  }
  return groups.sort((left, right) => gradeRank(left.grade) - gradeRank(right.grade));
}

export function QueueList({ notices, selectedId, reviews, total, sort, onSelect }: QueueListProps) {
  const groups = useMemo(() => (sort === "grade" ? groupByGrade(notices) : null), [notices, sort]);
  const reviewedCount = useMemo(
    () => notices.reduce((count, notice) => (reviews.has(notice.id) ? count + 1 : count), 0),
    [notices, reviews],
  );
  const progress = notices.length > 0 ? Math.round((reviewedCount / notices.length) * 100) : 0;

  const renderItem = (notice: NoticeListItem) => {
    const review = reviews.get(notice.id);
    return (
      <QueueListItem
        disposition={review?.disposition ?? null}
        key={notice.id}
        notice={notice}
        reviewed={Boolean(review)}
        selected={notice.id === selectedId}
        onClick={() => onSelect(notice.id)}
      />
    );
  };

  return (
    <aside className="queue-list-pane" aria-label="검토 대기 공고 목록">
      <div className="queue-list-header">
        <div className="queue-list-header-line">
          <span><strong className="mono tabular-nums">{formatNumber(total)}</strong>건 · {sortLabels[sort]}</span>
          <span className="queue-list-hint">
            리뷰 <strong className="mono tabular-nums">{formatNumber(reviewedCount)}</strong> / {formatNumber(notices.length)}
          </span>
        </div>
        <div
          className="queue-list-progress"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={notices.length}
          aria-valuenow={reviewedCount}
          aria-label="리뷰 진행률"
        >
          <span style={{ width: `${progress}%` }} />
        </div>
      </div>
      <div className="queue-list-scroll">
        {notices.length === 0 ? (
          <EmptyState compact title="조건에 맞는 공고가 없습니다." description="필터를 넓혀 다른 공고를 확인하십시오." />
        ) : (
          <DenseList aria-label="검토 대기 공고 목록">
            {groups ? (
              groups.map((group) => (
                <Fragment key={group.grade}>
                  <li className={`queue-group-header ${gradeRailClass(group.grade)}`}>
                    <span className="queue-group-swatch" aria-hidden="true" />
                    <span className="queue-group-label">{group.grade}</span>
                    <span className="mono tabular-nums queue-group-count">{formatNumber(group.items.length)}건</span>
                  </li>
                  {group.items.map(renderItem)}
                </Fragment>
              ))
            ) : (
              notices.map(renderItem)
            )}
          </DenseList>
        )}
      </div>
    </aside>
  );
}
