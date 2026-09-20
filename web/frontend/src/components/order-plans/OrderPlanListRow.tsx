import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Text } from "@astryxdesign/core/Text";
import { DenseListRow } from "../common/ReviewPrimitives";
import type { RowKeyboardNavigationRowProps } from "../common/useRowKeyboardNavigation";
import { formatCompactPrice } from "../../lib/deadline";
import type { OrderPlanListItem } from "../../lib/types";
import {
  budgetValue,
  plannedTiming,
  qwenBadgeVariant,
  qwenRowLabel,
  stage1BadgeVariant,
  stage1RowLabel,
  textOrUnknown,
} from "./orderPlanFormat";

/**
 * 첫 관측일은 날짜만 보인다(결정 16 — 발주계획은 첫 관측 그대로 고정된다). 날짜는 한국 시간
 * 관측일이다. 값이 없으면 지어내지 않고 미확인으로 남긴다.
 */
const KST_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });

function formatObservedDate(value: string | null | undefined): string {
  if (!value) return "미확인";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : KST_DATE.format(parsed);
}

/** 행의 판정 표식. 결과가 없는 행은 policy를 지어내지 않고 `판정 없음`이다. */
function verdictLabel(item: Pick<OrderPlanListItem, "policy_version" | "first_observed_at">): string {
  const verdict = item.policy_version ? `판정 policy ${item.policy_version}` : "판정 없음";
  return `${verdict} · 첫 관측 ${formatObservedDate(item.first_observed_at)}`;
}

function budgetLabel(value: number | null): string {
  return value === null ? "예산 null (미제공)" : formatCompactPrice(value);
}

export function OrderPlanListRow({
  item,
  isSelected,
  isChecked,
  onCheckedChange,
  disabled = false,
  onKeyDown,
  onSelect,
  rowProps,
}: {
  item: OrderPlanListItem;
  isSelected: boolean;
  isChecked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  /** 화면 단축키(Ctrl+Enter). `preventDefault()`하면 행 선택·↑↓ 이동보다 먼저다. */
  onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => void;
  onSelect: () => void;
  /** `useRowKeyboardNavigation`의 roving tabindex와 행 식별자. */
  rowProps: RowKeyboardNavigationRowProps;
}) {
  // BM25 `선정`은 목록의 거의 모든 행에 붙는 값이라 배지로 그리면 아무것도 구분하지
  // 못한다. 탈락·실패·거부·null만 남긴다 — 숨기는 것은 **기본값 하나**이고, 값이
  // 없거나 실패한 사실은 그대로 보인다.
  const stage1Badge = item.stage1_status !== "selected"
    ? <Badge variant={stage1BadgeVariant(item.stage1_status)} label={stage1RowLabel(item.stage1_status)} />
    : null;
  const feedbackBadge = item.human_feedback
    ? <Badge variant="neutral" label={`피드백 수정본 ${item.human_feedback.revision}`} />
    : null;
  return (
    <DenseListRow
      {...rowProps}
      aria-label={textOrUnknown(item.title)}
      className={`c2l-row-wrap c2l-row${isSelected ? " is-selected" : ""}`.trim()}
      description={
        <span className="c2l-row-desc">
          {/* 시안의 차례 그대로다: 사업명 아래 상태 배지, 그 아래 metadata 줄. 발주기관은
              자리를 옮기지 않고 metadata 줄의 첫 항목이며, 굵기를 주지 않는다. 목록에서
              먼저 읽혀야 하는 것은 사업명이다(사용자 정정).
              그릴 배지가 하나도 없으면 줄 자체를 만들지 않는다 — 빈 줄이 행마다 다른
              높이를 만들면 밀집 목록이 흔들린다. */}
          {stage1Badge || feedbackBadge ? (
            <span className="c2l-row-badges">
              {stage1Badge}
              {feedbackBadge}
            </span>
          ) : null}
          <span className="c2l-row-meta" title={`예산 ${budgetValue(item.budget_amount)}`}>
            <Text className="c2l-row-agency" type="body" color="primary" as="span">
              {textOrUnknown(item.agency_name)}
            </Text>
            <Text type="supporting" color="secondary" as="span">
              · {budgetLabel(item.budget_amount)} · {plannedTiming(item.planned_order_year, item.planned_order_month)}
            </Text>
          </span>
          {/* 누적 목록에서는 행마다 판정한 시점이 다르다. 어느 policy가 판정했는지와 판정 기준
              시점인 첫 관측일을 행에 싣는다(spec §7). 결과가 없는 행은 `판정 없음`이다. */}
          <Text className="c2l-row-verdict" type="supporting" color="secondary" as="span">
            {verdictLabel(item)}
          </Text>
        </span>
      }
      label={
        <span className="c2l-row-line c2l-row-head">
          {/* 긴 한글 제목은 한 줄에 담기지 않는다. 두 줄까지 보이고 그 뒤를 말줄임한다.
              크기와 굵기는 `.c2l-row-title`이 본문보다 한 단 위로 올린다. */}
          <Text className="c2l-row-title" type="body" color="primary" weight="semibold" maxLines={2}>{textOrUnknown(item.title)}</Text>
          {/* 모델 판단은 이 목록을 훑는 이유이므로 행마다 같은 자리(우상단)에서 읽힌다.
              baseline 정렬이라 제목이 두 줄로 잘려도 배지는 첫 줄에 붙어 있다. */}
          <Badge className="c2l-row-model" variant={qwenBadgeVariant(item)} label={qwenRowLabel(item)} />
        </span>
      }
      onKeyDown={onKeyDown}
      onSelect={onSelect}
      selected={isSelected}
      disabled={disabled}
      selection={{
        checked: isChecked,
        onCheckedChange,
        ariaLabel: `${textOrUnknown(item.title)} 선택`,
      }}
    />
  );
}
