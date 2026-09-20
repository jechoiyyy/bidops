import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { Badge } from "@astryxdesign/core/Badge";
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

/**
 * 행의 판정 표식. 결과가 없는 행은 policy를 지어내지 않고 `판정 없음`이다.
 *
 * 절을 두 항목(policy·첫 관측)으로 나눠 반환한다(B2, 0920 검수). 항목 하나를
 * 통짜 문자열로 두면 `overflow-wrap: anywhere`가 날짜 숫자 중간을 끊는다 — 항목
 * 안은 줄바꿈하지 않고 항목 사이에서만 줄바꿈되게 하려면 항목 경계 자체가 있어야 한다.
 */
function policyClauseLabel(item: Pick<OrderPlanListItem, "policy_version">): string {
  return item.policy_version ? `판정 policy ${item.policy_version}` : "판정 없음";
}

function observedClauseLabel(item: Pick<OrderPlanListItem, "first_observed_at">): string {
  return `첫 관측 ${formatObservedDate(item.first_observed_at)}`;
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
        <>
          {/* 사전규격 행과 같은 차례다(ADR-0062): 사업명 → 발주기관 → metadata 줄 →
              상태 칩 줄. 발주 예정은 오른쪽 열이 갖는다. 발주기관은 사업명 다음 줄에서
              같은 크기·보통 굵기로 읽힌다. */}
          <span className="c2l-row-agency">{textOrUnknown(item.agency_name)}</span>
          <span className="c2l-row-meta" title={`예산 ${budgetValue(item.budget_amount)}`}>
            <span className="c2l-row-meta-item">{budgetLabel(item.budget_amount)}</span>
            {/* 구분점은 전부 뒤 항목 앞에 붙인다(B2 후속, 0920 검수) — 줄이 바뀌어도
                구분점이 앞 항목 끝에 홀로 남지 않는다. 이 구분점은 `.c2l-row-verdict`
                밖에 있어 그 요소의 텍스트(판정 policy … · 첫 관측 …)는 그대로다. */}
            <span className="c2l-row-meta-group">
              {/* inline-flex 항목의 양끝 공백은 잘려 나가므로 줄바꿈 없는 공백으로 둔다 —
                  아래 `첫 관측` 앞 구분점(" · ")과 같은 간격으로 읽힌다. */}
              <span aria-hidden="true">{" · "}</span>
              {/* 누적 목록에서는 행마다 판정한 시점이 다르다. 어느 policy가 판정했는지와 판정
                  기준 시점인 첫 관측일을 행에 싣는다(spec §7). 결과가 없으면 `판정 없음`이다.
                  두 항목으로 나눠 항목 사이에서만 줄바꿈되게 한다(B2). */}
              <span className="c2l-row-verdict">
                <span className="c2l-row-meta-item">{policyClauseLabel(item)}</span>
                <span className="c2l-row-meta-item">
                  <span aria-hidden="true"> · </span>{observedClauseLabel(item)}
                </span>
              </span>
            </span>
          </span>
          <span className="c2l-row-state">
            {/* 모델 판단은 이 목록을 훑는 이유이므로 행마다 같은 자리에서 읽힌다. */}
            <Badge className="c2l-row-model" variant={qwenBadgeVariant(item)} label={qwenRowLabel(item)} />
            {/* 그릴 배지가 하나도 없으면 줄 자체를 만들지 않는다 — 빈 묶음이 행마다 다른
                높이를 만들면 밀집 목록이 흔들린다. */}
            {stage1Badge || feedbackBadge ? (
              <span className="c2l-row-badges">
                {stage1Badge}
                {feedbackBadge}
              </span>
            ) : null}
          </span>
        </>
      }
      endContent={
        <span className="c2l-row-end">
          <span className="c2l-row-planned">{plannedTiming(item.planned_order_year, item.planned_order_month)}</span>
        </span>
      }
      label={
        /* 긴 한글 제목은 한 줄에 담기지 않는다. 두 줄까지 보이고 그 뒤를 말줄임한다. */
        <span className="c2l-row-title">{textOrUnknown(item.title)}</span>
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
