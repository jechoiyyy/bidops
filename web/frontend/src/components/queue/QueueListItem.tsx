import { Badge, type BadgeVariant } from "../common/Badge";
import type { NoticeListItem } from "../../lib/types";
import { formatDeadline, formatNumber, formatPrice } from "../../lib/format";

interface QueueListItemProps {
  notice: NoticeListItem;
  selected: boolean;
  reviewed: boolean;
  onClick: () => void;
}

function gradeVariant(grade: string | null): BadgeVariant {
  if (grade === "우선 검토") return "grade-1";
  if (grade === "검토 권장") return "grade-2";
  if (grade === "관찰 대상") return "grade-3";
  if (grade === "제외") return "grade-4";
  return "neutral";
}

function deadlineVariant(value: string | null): BadgeVariant {
  if (!value) return "neutral";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "neutral";
  const remaining = date.getTime() - Date.now();
  return remaining >= 0 && remaining <= 7 * 86_400_000 ? "alert" : "neutral";
}

export function QueueListItem({ notice, selected, reviewed, onClick }: QueueListItemProps) {
  const attachmentLabel = notice.attachment_status === "none"
    ? "첨부 미확보"
    : notice.attachment_status === "manual"
      ? `수동 첨부 ${formatNumber(notice.attachment_count)}`
      : `첨부 ${formatNumber(notice.attachment_count)}`;
  return (
    <button className={`queue-list-item ${selected ? "is-selected" : ""}`.trim()} type="button" onClick={onClick}>
      <span className="queue-list-title">{notice.title?.trim() || "공고명 미확인"}</span>
      <span className="queue-list-badges">
        <Badge label={notice.grade} variant={gradeVariant(notice.grade)} />
        <Badge label={notice.readiness} variant="readiness" />
        {notice.deadline_at ? <Badge label={formatDeadline(notice.deadline_at)} variant={deadlineVariant(notice.deadline_at)} /> : null}
        <Badge label={attachmentLabel} variant="neutral" />
        {reviewed ? <Badge label="리뷰 완료" variant="evidence-confirmed" /> : null}
      </span>
      <span className="queue-list-meta">
        <span>{notice.agency?.trim() || "발주기관 미확인"}</span>
        <span className="queue-list-dot" aria-hidden="true">·</span>
        <span className="mono tabular-nums">{formatPrice(notice.estimated_price)}</span>
        <span className="queue-list-dot" aria-hidden="true">·</span>
        <span>{notice.focus?.trim() || "역량 축 미확인"}</span>
      </span>
    </button>
  );
}
