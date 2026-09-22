import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { DenseListRow } from "../common/ReviewPrimitives";
import type { RowKeyboardNavigationRowProps } from "../common/useRowKeyboardNavigation";
import { formatCompactPrice } from "../../lib/deadline";
import type { OrderPlanListItem } from "../../lib/types";
import {
  budgetValue,
  formatKstDateShort,
  humanFeedbackBadgeLabel,
  plannedTiming,
  qwenBadgeVariant,
  qwenRowLabel,
  stage1BadgeLabel,
  stage1BadgeVariant,
  textOrUnknown,
  trackingChipLabel,
} from "./orderPlanFormat";

/**
 * 행의 판정 표식과 첫 수집일.
 *
 * 판정한 policy 이름은 실무 화면에서 뺐다(0921 명세 §3.1 — 운영 화면이 진다). 남는 것은
 * **판정이 없다는 사실**뿐이다: 판정 없음은 비관련이 아니다(경고 ⑤).
 *
 * 첫 수집일은 날짜만 보인다(결정 16 — 발주계획은 첫 관측 그대로 고정된다). 한국 시간
 * 관측일이며 해가 올해와 다를 때만 연도를 붙인다. 값이 없으면 미확인으로 남긴다.
 *
 * 절을 두 항목으로 나눠 그린다(B2, 0920 검수). 항목 하나를 통짜 문자열로 두면
 * `overflow-wrap: anywhere`가 날짜 숫자 중간을 끊는다 — 항목 안은 줄바꿈하지 않고
 * 항목 사이에서만 줄바꿈되게 하려면 항목 경계 자체가 있어야 한다.
 */
function hasNoJudgment(item: Pick<OrderPlanListItem, "policy_version">): boolean {
  return item.policy_version === null;
}

function collectedClauseLabel(item: Pick<OrderPlanListItem, "first_observed_at">): string {
  return `첫 수집 ${formatKstDateShort(item.first_observed_at)}`;
}

function budgetLabel(value: number | null): string {
  return value === null ? "예산 미제공" : formatCompactPrice(value);
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
  // 1차 선별의 기본값 둘(`선정`·`제외`)은 그리지 않는다(0921 명세 §3.1). 남는 것은
  // 실패·거부·값 없음뿐이며, 실패한 사실과 값이 없는 사실은 서로 다른 문구로 보인다.
  const stage1Label = stage1BadgeLabel(item.stage1_status);
  const stage1Badge = stage1Label
    ? <Badge variant={stage1BadgeVariant(item.stage1_status)} label={stage1Label} />
    : null;
  const feedbackLabel = humanFeedbackBadgeLabel(item.human_feedback?.revision ?? null);
  const feedbackBadge = feedbackLabel ? <Badge variant="neutral" label={feedbackLabel} /> : null;
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
          {/* budgetValue의 null 문구는 이미 `예산`을 포함한다(U3) — 중복을 피해
              null이 아닐 때만 "예산 " 접두를 붙인다. */}
          <span className="c2l-row-meta" title={item.budget_amount === null ? budgetValue(item.budget_amount) : `예산 ${budgetValue(item.budget_amount)}`}>
            <span className="c2l-row-meta-item">{budgetLabel(item.budget_amount)}</span>
            {/* 구분점은 전부 뒤 항목 앞에 붙인다(B2 후속, 0920 검수) — 줄이 바뀌어도
                구분점이 앞 항목 끝에 홀로 남지 않는다. 이 구분점은 `.c2l-row-verdict`
                밖에 있어 그 요소의 텍스트(`[판정 없음 · ]첫 수집 …`)는 그대로다. */}
            <span className="c2l-row-meta-group">
              {/* inline-flex 항목의 양끝 공백은 잘려 나가므로 줄바꿈 없는 공백으로 둔다 —
                  아래 `첫 관측` 앞 구분점(" · ")과 같은 간격으로 읽힌다. */}
              <span aria-hidden="true">{" · "}</span>
              {/* 행이 싣는 것은 첫 수집일과 **판정이 없다는 사실**뿐이다(0921 명세 §3.1).
                  판정한 policy는 운영 화면이 진다. 두 항목으로 나눠 항목 사이에서만
                  줄바꿈되게 한다(B2). */}
              <span className="c2l-row-verdict">
                {hasNoJudgment(item) ? <span className="c2l-row-meta-item">판정 없음</span> : null}
                <span className="c2l-row-meta-item">
                  {hasNoJudgment(item) ? <span aria-hidden="true"> · </span> : null}
                  {collectedClauseLabel(item)}
                </span>
              </span>
            </span>
          </span>
          <span className="c2l-row-state">
            {/* 모델 판단은 이 목록을 훑는 이유이므로 행마다 같은 자리에서 읽힌다. */}
            <Badge className="c2l-row-model" variant={qwenBadgeVariant(item)} label={qwenRowLabel(item)} />
            {/* 추적 결정 칩(M5 ① 승인). 모델 판단 바로 옆에 붙어 "이 건을 이미 집었는가"를
                같은 눈길에서 읽게 한다. 사람의 결정이므로 성공·실패 의미색을 쓰지 않고
                중립으로 둔다 — 보류·종료가 실패로, 계속 추적이 성공으로 읽히면 안 된다.
                **판단 근거 한 줄은 행에 싣지 않는다**(M5 승인 — 근거는 상세에서만). */}
            <Badge className="c2l-row-tracking" variant="neutral" label={trackingChipLabel(item)} />
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
