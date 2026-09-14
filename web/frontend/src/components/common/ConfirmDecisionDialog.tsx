import { useId } from "react";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { Dialog as AstryxDialog } from "@astryxdesign/core/Dialog";
import "../../styles/confirm-decision-dialog.css";

/**
 * 되돌릴 수 없는 결정의 마지막 확인 단계.
 *
 * 화면이 "되돌릴 수 없습니다"라고 쓰면서 submit 한 번에 요청을 보내면 그 문장은
 * 경고가 아니라 사후 설명이다. 최종 Go/No-Go, append-only 심층검토 의견, 추적
 * `종료`처럼 저장 뒤 취소할 수 없는 저장은 이 컴포넌트를 거친다.
 *
 * `tone="unsaved"`는 같은 골격을 저장하지 않은 입력을 버리는 자리(화면 이탈, 다른
 * 행 선택)에 쓴다. 확인하는 대상이 "저장할 결정"이 아니라 "버릴 입력"이라는 것만
 * 다르고, 사람이 보는 골격·조작·취소 경로는 같아야 하므로 컴포넌트를 나누지 않는다.
 *
 * 이 컴포넌트는 **무엇을 저장하는지 다시 보여 줄 뿐** 업무 규칙을 갖지 않는다.
 * 저장 전제조건(계산 완료·사유 필수·담당자 필수·validation acknowledge)과 비활성
 * 사유는 부르는 화면이 그대로 소유한다. 확인 버튼은 `destructive`가 아니라
 * primary다 — 결정은 오류가 아니다.
 */

/** 확인 다이얼로그가 기본으로 쓰는 경고 문장. 화면마다 다르게 쓰지 않는다. */
export const IRREVERSIBLE_DECISION_WARNING = "이 결정은 저장 뒤 되돌릴 수 없습니다.";

/** 저장하지 않은 입력을 버리는 경고. 되돌릴 수 없다는 점은 결정과 같지만 원인이 다르다. */
export const UNSAVED_INPUT_WARNING = "저장하지 않고 이동하면 입력한 내용이 사라집니다.";

/**
 * 이 확인 단계가 무엇을 확인하는지의 두 갈래.
 *
 * - `decision`: 사람이 **저장하려는** 결정을 되돌릴 수 없다(최종 Go/No-Go, 추적 종료).
 * - `unsaved`: 사람이 **저장하지 않은** 입력을 버린다(화면 이탈, 다른 행 선택).
 *
 * 둘 다 되돌릴 수 없지만 사람이 잃는 것이 다르므로 머리말과 기본 경고 문장을 나눈다.
 * 색으로는 구분하지 않는다 — 구분은 머리말·경고 문장·버튼 이름이 진다.
 */
export type ConfirmDecisionTone = "decision" | "unsaved";

const TONE_KICKER: Record<ConfirmDecisionTone, string> = {
  decision: "되돌릴 수 없는 결정 · 최종 확인",
  unsaved: "저장되지 않은 입력 · 이동 확인",
};

const TONE_WARNING: Record<ConfirmDecisionTone, string> = {
  decision: IRREVERSIBLE_DECISION_WARNING,
  unsaved: UNSAVED_INPUT_WARNING,
};

export interface ConfirmDecisionSummaryItem {
  label: string;
  value: string;
}

export interface ConfirmDecisionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** 대상·결정 값·담당자·사유처럼 저장될 내용을 그대로 다시 보여 준다.
   * 되풀이할 값이 없으면(예: 이탈 확인) 비워 두고, 그때는 요약 표를 그리지 않는다. */
  summary?: ConfirmDecisionSummaryItem[];
  /** 기본은 되돌릴 수 없는 결정(`decision`)이다. 저장하지 않은 입력을 버리는
   * 자리는 `unsaved`를 준다. */
  tone?: ConfirmDecisionTone;
  warning?: string;
  /** 행동을 그대로 말하는 문구. 폼의 저장 버튼과 같은 이름을 쓰지 않는다. */
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  isPending?: boolean;
}

export function ConfirmDecisionDialog({
  open,
  title,
  tone = "decision",
  warning = TONE_WARNING[tone],
  summary = [],
  cancelLabel = "취소",
  confirmLabel,
  onConfirm,
  onOpenChange,
  isPending = false,
}: ConfirmDecisionDialogProps) {
  const id = useId().replace(/:/g, "");
  const titleId = `confirm-decision-dialog-title-${id}`;
  const descriptionId = `confirm-decision-dialog-description-${id}`;
  return (
    <AstryxDialog
      aria-describedby={descriptionId}
      aria-labelledby={titleId}
      aria-modal="true"
      className="confirm-decision-dialog"
      data-astryx-theme="bidops"
      data-tone={tone}
      data-slot="alert-dialog-content"
      isOpen={open}
      onOpenChange={(next) => {
        if (!next && !isPending) onOpenChange(false);
      }}
      // Unsaved guards and irreversible confirmations historically dismissed
      // on backdrop click. Astryx's info purpose preserves that behavior while
      // keeping Escape and native focus trapping in the same implementation.
      purpose="info"
      role="alertdialog"
      width={560}
      maxHeight="90dvh"
      style={{ pointerEvents: "auto" }}
    >
      <header className="confirm-decision-dialog-header">
        <span className="confirm-decision-dialog-kicker">
          {TONE_KICKER[tone]}
        </span>
        <h2 id={titleId} data-slot="alert-dialog-title">{title}</h2>
        <p id={descriptionId} data-slot="alert-dialog-description">{warning}</p>
      </header>
      {summary.length ? (
        <dl className="confirm-decision-dialog-summary">
          {summary.map((entry) => (
            <div className="confirm-decision-dialog-summary-row" key={entry.label}>
              <dt>{entry.label}</dt>
              <dd>{entry.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <footer className="confirm-decision-dialog-footer" data-slot="alert-dialog-footer">
        <AstryxButton
          className="confirm-decision-dialog-cancel"
          data-autofocus="true"
          data-slot="alert-dialog-cancel"
          isDisabled={isPending}
          label={cancelLabel}
          onClick={() => onOpenChange(false)}
          variant="secondary"
        />
        <AstryxButton
          className="confirm-decision-dialog-confirm"
          data-slot="alert-dialog-action"
          isDisabled={isPending}
          label={isPending ? "저장 중…" : confirmLabel}
          onClick={onConfirm}
          variant="primary"
        />
      </footer>
    </AstryxDialog>
  );
}

/** 긴 사유를 요약 줄 하나에 담는다. 값이 없으면 `값 없음`이며 빈 문자열로 두지 않는다. */
export function decisionSummaryExcerpt(value: string, limit = 120): string {
  const trimmed = value.trim();
  if (!trimmed) return "값 없음";
  return trimmed.length > limit ? `${trimmed.slice(0, limit)}…` : trimmed;
}

/**
 * 추적 `종료`는 사전규격(TrackingDecisionControl)과 사업 추적(OpportunitiesPage)
 * 두 자리에서 저장된다. 확인 문구가 자리마다 갈라지지 않도록 여기서 한 번만
 * 만든다. `계속 추적`·`보류`는 되돌릴 수 있으므로 확인 단계를 두지 않는다.
 */
export function trackingEndConfirmContent({
  target,
  actor,
  reason,
}: {
  target: string;
  actor: string;
  reason: string;
}): { title: string; confirmLabel: string; summary: ConfirmDecisionSummaryItem[] } {
  return {
    title: "추적을 종료합니다",
    confirmLabel: "종료 상태로 저장",
    summary: [
      { label: "대상", value: target },
      { label: "추적 상태", value: "종료 · 추적 종료" },
      { label: "담당자", value: actor.trim() || "값 없음" },
      { label: "사유", value: decisionSummaryExcerpt(reason) },
    ],
  };
}
