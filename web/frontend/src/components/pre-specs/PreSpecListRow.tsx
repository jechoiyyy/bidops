import { DeadlineText, StatusMark } from "../common/Marks";
import type { RecordTableColumn } from "../common/RecordTable";
import { PreSpecRowAgency } from "./PreSpecAgency";
import { describeDeadline, describeDeadlineCountdown, shortDateLabel } from "../../lib/deadline";
import { formatDateTime } from "../../lib/format";
import {
  attachmentAttention,
  budgetLabel,
  exactBudget,
  overviewStatusLabel,
  overviewStatusTone,
  titleOf,
  trackingLabel,
} from "../../lib/preSpecViews";
import type { PreSpecListItem } from "../../lib/types";

export function DeadlineMark({ value }: { value: string | null }) {
  const deadline = describeDeadline(value);
  return (
    <span aria-label={`D-day: ${deadline.label}`} className="pre-specs-deadline">
      <DeadlineText text={deadline.label} urgency={deadline.urgency} />
    </span>
  );
}

function PreSpecListDeadline({ value }: { value: string | null }) {
  const countdown = describeDeadlineCountdown(value);
  const date = shortDateLabel(value);
  // The column header already says 마감. On the due day, keep the time beside 오늘.
  const label = countdown && date ? `${countdown.label.replace(/ 마감$/, "")} · ${date}` : "마감 미확인";
  return (
    <span aria-label={`D-day: ${label}`} className="pre-specs-deadline" title={value ? formatDateTime(value) : undefined}>
      <DeadlineText text={label} urgency={countdown?.urgency ?? "none"} />
    </span>
  );
}

function PreSpecStatus({ item, hideUntracked }: { item: PreSpecListItem; hideUntracked: boolean }) {
  const attention = attachmentAttention(item);
  return (
    <div className="record-table-status pre-specs-row-state">
      <StatusMark mark={{ label: overviewStatusLabel(item.overview_review_status), tone: overviewStatusTone(item.overview_review_status) }} />
      {item.review_exclusion_status === "excluded" ? <StatusMark mark={{ label: "검토 제외", tone: "neutral" }} /> : null}
      {hideUntracked && item.opportunity_id !== null && item.tracking_status === "미선택"
        ? null
        : <span className="record-table-note pre-specs-row-tracking">{trackingLabel(item)}</span>}
      {attention ? <span className="record-table-note pre-specs-row-attention">{attention}</span> : null}
    </div>
  );
}

export function preSpecColumns(hideUntracked: boolean): RecordTableColumn<PreSpecListItem>[] {
  return [
    {
      key: "business", header: "사업명", title: titleOf, titleClassName: "pre-specs-row-title",
      renderBelow: (item) => item.kept_by_tracking ? (
        <span
          aria-label="추적 예외 · SW사업대상 Y가 아니지만 추적 중인 발주계획에 연결됨"
          className="record-table-note pre-specs-tracking-exception"
        >
          추적 예외
        </span>
      ) : null,
    },
    {
      key: "agency", header: "발주기관", width: 60, grow: true, className: "pre-specs-row-agency",
      renderCell: (item) => <PreSpecRowAgency item={item} />,
    },
    {
      key: "budget", header: "예산", width: 98, numeric: true, className: "pre-specs-row-budget",
      renderCell: (item) => <span title={exactBudget(item.budget)}>{budgetLabel(item.budget)}</span>,
    },
    {
      key: "overview", header: "개요 상태", width: 92,
      renderCell: (item) => <PreSpecStatus item={item} hideUntracked={hideUntracked} />,
    },
    {
      key: "deadline", header: "의견 마감", width: 132, className: "pre-specs-row-date",
      renderCell: (item) => <PreSpecListDeadline value={item.deadline_at} />,
    },
  ];
}
