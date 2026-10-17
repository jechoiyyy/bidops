import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "../common/EmptyState";
import { MutationFeedback } from "../common/MutationFeedback";
import type { ApiErrorDescription } from "../../lib/apiErrors";
import {
  ACTIVITY_FILTER_LABEL,
  filterActivity,
  type ActivityFilter,
} from "../../lib/record";
import type { OpportunityActivityItem } from "../../lib/types";
import { ActivityItem } from "./ActivityItem";

/*
 * 활동 피드: 필터 칩(전체·사람·사업 사건) + 항목 목록 + 커서 `더 보기`.
 *
 * 필터는 받아 둔 항목을 클라이언트에서 가른다. `다음 행동` 칩은 좌측 `모두 보기`를 눌렀을 때만
 * 생기는 임시 필터이며 다른 칩을 누르면 사라진다. 커서(`next_before`)가 있으면 필터와 무관하게
 * 더 불러올 수 있다 — 지금 받은 항목에 맞는 것이 없다는 말이 서버에 더 없다는 뜻은 아니다.
 */

interface ActivityFeedProps {
  items: readonly OpportunityActivityItem[];
  filter: ActivityFilter;
  onFilterChange: (filter: ActivityFilter) => void;
  hasMore: boolean;
  isFetchingMore: boolean;
  onLoadMore: () => void;
  problem: ApiErrorDescription | null;
  onRetry: () => void;
  now: Date;
}

export function ActivityFeed({
  items,
  filter,
  onFilterChange,
  hasMore,
  isFetchingMore,
  onLoadMore,
  problem,
  onRetry,
  now,
}: ActivityFeedProps) {
  const visible = filterActivity(items, filter);
  const filters: ActivityFilter[] = filter === "action" ? ["all", "people", "business", "action"] : ["all", "people", "business"];
  return (
    <section aria-labelledby="rec-feed-title" className="rec-feed">
      <div className="rec-feed-head">
        <h3 className="rec-section-title" id="rec-feed-title">활동</h3>
        <div aria-label="활동 필터" className="rec-chips" role="group">
          {filters.map((key) => (
            <button
              aria-pressed={filter === key}
              className="rec-chip"
              key={key}
              onClick={() => onFilterChange(key)}
              type="button"
            >
              {ACTIVITY_FILTER_LABEL[key]}
            </button>
          ))}
        </div>
      </div>
      {problem ? (
        <MutationFeedback onRecover={onRetry} problem={problem} tone="error" />
      ) : null}
      {visible.length === 0 && !problem ? (
        <EmptyState
          compact
          description={hasMore ? "아래 더 보기로 이전 활동을 불러올 수 있습니다." : undefined}
          title={items.length === 0 ? "아직 기록된 활동이 없습니다" : "이 필터에 해당하는 활동이 없습니다"}
        />
      ) : null}
      {visible.length > 0 ? (
        <ol aria-label="활동 목록" className="rec-activity-list">
          {visible.map((item) => <ActivityItem item={item} key={item.item_id} now={now} />)}
        </ol>
      ) : null}
      {hasMore ? (
        <div className="rec-feed-more">
          <Button
            isDisabled={isFetchingMore}
            label={isFetchingMore ? "불러오는 중…" : "더 보기"}
            onClick={onLoadMore}
            size="sm"
          />
        </div>
      ) : null}
    </section>
  );
}
