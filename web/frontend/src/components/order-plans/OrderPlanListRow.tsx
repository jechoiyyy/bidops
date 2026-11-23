import { DeadlineText, StatusMark } from "../common/Marks";
import type { RecordTableColumn } from "../common/RecordTable";
import { formatCompactPrice } from "../../lib/deadline";
import { ORDER_PLAN_UNJUDGED_KIND_LABEL } from "../../lib/glossary";
import type { OrderPlanListItem } from "../../lib/types";
import {
  budgetValue,
  currentKstMonth,
  hasNoModelJudgment,
  humanFeedbackBadgeLabel,
  NO_MODEL_JUDGMENT_LABEL,
  orderPlanStaleReason,
  orderPlanUnjudgedKind,
  plannedTiming,
  qwenStatusTone,
  qwenRowLabel,
  stage1BadgeLabel,
  stage1StatusTone,
  stage1RankLabel,
  textOrUnknown,
  trackingChipLabel,
} from "./orderPlanFormat";

interface OrderPlanRowDisplay {
  unjudged: boolean;
  hideModelLabel: string | null;
  hideUntracked: boolean;
}

function OrderPlanStatus({ item, unjudged, hideModelLabel, hideUntracked }: OrderPlanRowDisplay & { item: OrderPlanListItem }) {
  const unjudgedKind = unjudged ? orderPlanUnjudgedKind(item) : null;
  const staleReason = orderPlanStaleReason(item, currentKstMonth(Date.now()));
  const stage1Label = stage1BadgeLabel(item.stage1_status);
  const feedbackLabel = humanFeedbackBadgeLabel(item.human_feedback?.revision ?? null);
  const modelTone = qwenStatusTone(item);
  const showModel = !unjudged && (item.qwen_relevance !== hideModelLabel || hideModelLabel === null || modelTone === "error");
  return (
    <div className="record-table-status c2l-row-state">
      {showModel ? <StatusMark className="c2l-row-model" mark={{ label: qwenRowLabel(item), tone: modelTone }} /> : null}
      {unjudgedKind ? (
        <StatusMark className="c2l-row-unjudged" mark={{
          label: ORDER_PLAN_UNJUDGED_KIND_LABEL[unjudgedKind],
          tone: unjudgedKind === "judgment_failed" ? "warning" : "neutral",
        }} />
      ) : hasNoModelJudgment(item) ? <StatusMark className="c2l-row-no-judgment" mark={{ label: NO_MODEL_JUDGMENT_LABEL, tone: "warning" }} /> : null}
      {hideUntracked && item.tracking?.tracking_status === "미선택"
        ? null
        : <StatusMark className="c2l-row-tracking" mark={{ label: trackingChipLabel(item), tone: "neutral" }} />}
      {staleReason ? <StatusMark className="c2l-row-stale" mark={{ label: staleReason, tone: "neutral" }} /> : null}
      {(stage1Label && !unjudged) || feedbackLabel ? (
        <span className="c2l-row-badges">
          {stage1Label && !unjudged ? <StatusMark mark={{ label: stage1Label, tone: stage1StatusTone(item.stage1_status) }} /> : null}
          {feedbackLabel ? <StatusMark mark={{ label: feedbackLabel, tone: "neutral" }} /> : null}
        </span>
      ) : null}
    </div>
  );
}

export function orderPlanColumns(display: OrderPlanRowDisplay): RecordTableColumn<OrderPlanListItem>[] {
  return [
    {
      key: "business", header: "사업명",
      title: (item) => textOrUnknown(item.title),
      titleClassName: "c2l-row-title",
      renderBelow: (item) => item.policy_version === null || display.unjudged ? (
        <div className="record-table-note">
          {item.policy_version === null ? <span className="c2l-row-verdict">판정 없음</span> : null}
          {item.policy_version === null && display.unjudged ? " · " : null}
          {display.unjudged ? <span className="c2l-row-rank">{stage1RankLabel(item.stage1_rank)}</span> : null}
        </div>
      ) : null,
    },
    {
      key: "agency", header: "발주기관", width: 60, grow: true, ellipsis: true, className: "c2l-row-agency",
      renderCell: (item) => textOrUnknown(item.agency_name),
    },
    {
      key: "budget", header: "예산", width: 98, numeric: true, className: "c2l-row-budget",
      renderCell: (item) => (
        <span title={item.budget_amount === null ? budgetValue(item.budget_amount) : `예산 ${budgetValue(item.budget_amount)}`}>
          {item.budget_amount === null ? "예산 미제공" : formatCompactPrice(item.budget_amount)}
        </span>
      ),
    },
    {
      key: "status", header: "상태", width: 100,
      renderCell: (item) => <OrderPlanStatus item={item} {...display} />,
    },
    {
      key: "planned", header: "발주 예정", width: 120, className: "c2l-row-planned",
      renderCell: (item) => <DeadlineText text={plannedTiming(item.planned_order_year, item.planned_order_month)} urgency="none" />,
    },
  ];
}
