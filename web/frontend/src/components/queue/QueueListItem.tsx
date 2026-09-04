import { useEffect, useRef } from "react";
import { Badge } from "../common/Badge";
import { DenseListRow } from "../common/ReviewPrimitives";
import type { NoticeListItem } from "../../lib/types";
import { formatNumber } from "../../lib/format";
import { describeDeadline, formatCompactPrice } from "../../lib/deadline";
import { gradeRailClass } from "../../lib/grade";

interface QueueListItemProps {
  notice: NoticeListItem;
  selected: boolean;
  reviewed: boolean;
  disposition: string | null;
  onClick: () => void;
}

export function QueueListItem({ notice, selected, reviewed, disposition, onClick }: QueueListItemProps) {
  const itemRef = useRef<HTMLLIElement>(null);
  const attachmentLabel = notice.attachment_status === "none"
    ? "첨부 미확보"
    : notice.attachment_status === "manual"
      ? `수동 첨부 ${formatNumber(notice.attachment_count)}`
      : `첨부 ${formatNumber(notice.attachment_count)}`;
  const deadline = describeDeadline(notice.deadline_at);
  const className = [
    "queue-list-item",
    gradeRailClass(notice.grade),
    selected ? "is-selected" : "",
    reviewed ? "is-reviewed" : "",
  ].filter(Boolean).join(" ");

  useEffect(() => {
    if (selected) itemRef.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  return (
    <DenseListRow
      className={className}
      description={
        <>
          <span className="queue-list-badges">
            <Badge label={notice.readiness} variant="readiness" />
            <Badge label={notice.focus} variant="focus" />
            <Badge label={attachmentLabel} variant={notice.attachment_status === "none" ? "alert" : "neutral"} />
          </span>
          <span className="queue-list-meta">
            <span>{notice.agency?.trim() || "발주기관 미확인"}</span>
            <span className="queue-list-dot" aria-hidden="true">·</span>
            <span className="mono tabular-nums">{formatCompactPrice(notice.estimated_price)}</span>
            {reviewed && disposition ? (
              <>
                <span className="queue-list-dot" aria-hidden="true">·</span>
                <span className="queue-list-disposition">{disposition}</span>
              </>
            ) : null}
          </span>
        </>
      }
      label={
        <span className="queue-list-line">
          {reviewed ? (
            <svg className="queue-list-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
              <path d="m5 12 5 5L20 7" />
            </svg>
          ) : null}
          <span className="queue-list-title">{notice.title?.trim() || "공고명 미확인"}</span>
          <span className={`queue-list-deadline is-${deadline.urgency} mono tabular-nums`}>{deadline.label}</span>
        </span>
      }
      onSelect={onClick}
      ref={itemRef}
      selected={selected}
    />
  );
}
