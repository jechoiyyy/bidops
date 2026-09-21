import { Token } from "@astryxdesign/core/Token";
import { DenseListRow, type DenseListRowSelection } from "../common/ReviewPrimitives";
import { describeDeadline, shortDateLabel } from "../../lib/deadline";
import { formatDateTime } from "../../lib/format";
import {
  agencyOf,
  attachmentAttention,
  budgetLabel,
  exactBudget,
  nextActionLabel,
  originLabel,
  overviewStatusLabel,
  overviewTokenColor,
  swRowNote,
  titleOf,
  trackingLabel,
} from "../../lib/preSpecViews";
import type { KeyboardEventHandler } from "react";
import { displayAssessmentLabel } from "../../lib/grade";
import type { PreSpecListItem } from "../../lib/types";
import type { RowKeyboardNavigationRowProps } from "../common/useRowKeyboardNavigation";

export function DeadlineMark({ value }: { value: string | null }) {
  const deadline = describeDeadline(value);
  return (
    <span aria-label={`D-day: ${deadline.label}`} className={`pre-specs-deadline is-${deadline.urgency} mono tabular-nums`}>
      {deadline.label}
    </span>
  );
}

/**
 * 목록 행 — 시안의 두 열 구조다.
 *
 * 왼쪽 열은 사업명(16px, 굵게) → 발주기관(16px) → 예산·발견 구분(14px) → 개요 상태와
 * 추적 상태(14px)를 그대로 쌓는다. 행에서 먼저 읽혀야 하는 것은 사업명이므로 시안의
 * 두 줄 차례를 뒤집었다(사용자 정정). 오른쪽 열은 의견등록 마감뿐이며 D-day와 짧은
 * 날짜만 둔다. 정확한 일시·금액과 등급·자동 준비 같은 나머지 사실은 선택한 건의
 * 상세가 보여 준다 — 목록에서 같은 사실을 강한 배지로 반복하지 않는다.
 *
 * 행은 스스로 판정하지 않는다. 서버가 준 상태를 옮길 뿐이고, 사업명을 눌러도
 * 목록을 떠나지 않고 오른쪽 상세만 바뀐다(상세 화면 진입은 상세 pane 바닥의
 * `상세 검토 열기`가 소유한다).
 */
export function PreSpecRow({
  item,
  isSelected,
  onSelect,
  selection,
  ...rowProps
}: {
  item: PreSpecListItem;
  isSelected: boolean;
  onSelect: () => void;
  selection?: DenseListRowSelection;
} & Partial<RowKeyboardNavigationRowProps> & {
  onKeyDown?: KeyboardEventHandler<HTMLElement>;
}) {
  const title = titleOf(item);
  const swNote = swRowNote(item.sw_business_status);
  const attention = attachmentAttention(item);
  const nextAction = nextActionLabel(item.next_action);
  const shortDeadline = shortDateLabel(item.deadline_at);
  return (
    <DenseListRow
      // `data-row-key`·roving `tabIndex`·`onKeyDown`은 키보드 이동 hook이 준다.
      // 그대로 행 요소까지 내려야 hook이 행을 찾아 초점을 옮길 수 있다.
      {...rowProps}
      // 선택 모드에서는 행과 체크박스가 독립된 컨트롤이므로 사업명을 행 이름으로 고정한다.
      aria-label={title}
      className="pre-specs-row"
      data-checked={selection?.checked ? "true" : "false"}
      selected={isSelected}
      onSelect={onSelect}
      selection={selection}
      label={<span className="pre-specs-row-title">{title}</span>}
      description={(
        <>
          <span className="pre-specs-row-agency">{agencyOf(item)}</span>
          <span className="pre-specs-row-meta">
            <span title={exactBudget(item.budget)}>{budgetLabel(item.budget)}</span>
            <span aria-hidden="true">·</span>
            <span>{originLabel(item.origin)}</span>
            {swNote ? (
              <>
                <span aria-hidden="true">·</span>
                <span>{swNote}</span>
              </>
            ) : null}
            {/* 등급은 글자 토큰 하나다(ADR-0055 결정 2). 색으로 뜻을 전하지 않고,
                판정 없음을 특정 등급으로 접지 않는다. 출처는 상세가 갖는다. */}
            <span aria-hidden="true">·</span>
            {item.review_exclusion_status === "excluded" ? <Token size="sm" label="검토 제외" color="default" /> : null}
            <span className="pre-specs-row-grade">{displayAssessmentLabel(item.display_assessment)}</span>
            {item.kept_by_tracking ? (
              <>
                <span aria-hidden="true">·</span>
                {/* 뜻은 `표시 범위` 대화상자가 문장으로 갖는다. 목록에는 짧은 표식만
                    두고 그 뜻을 접근 가능한 이름으로 함께 남긴다. */}
                <span
                  aria-label="추적 예외 · SW사업대상 Y가 아니지만 추적 중인 발주계획에 연결됨"
                  className="pre-specs-tracking-exception"
                >
                  추적 예외
                </span>
              </>
            ) : null}
          </span>
          <span className="pre-specs-row-state">
            <Token
              size="sm"
              label={overviewStatusLabel(item.overview_review_status)}
              color={overviewTokenColor(item.overview_review_status)}
            />
            <span className="pre-specs-row-tracking">{trackingLabel(item)}</span>
            {nextAction ? <span className="pre-specs-row-next-action">다음: {nextAction}</span> : null}
            {/* 0건은 실제 0이므로 아무것도 적지 않는다. 1건 이상일 때만 남긴다. */}
            {attention ? <span className="pre-specs-row-attention">{attention}</span> : null}
          </span>
        </>
      )}
      endContent={(
        <span className="pre-specs-row-end">
          <DeadlineMark value={item.deadline_at} />
          <span
            className="pre-specs-row-deadline-at"
            title={item.deadline_at ? formatDateTime(item.deadline_at) : undefined}
          >
            {shortDeadline ?? "일시 없음"}
          </span>
        </span>
      )}
    />
  );
}
