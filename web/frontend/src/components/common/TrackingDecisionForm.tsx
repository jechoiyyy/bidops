import type { ComponentProps, ReactNode, Ref } from "react";
import { Selector } from "@astryxdesign/core/Selector";
import { TextInput } from "@astryxdesign/core/TextInput";
import type { ApiErrorDescription } from "../../lib/apiErrors";
import type { OpportunityTrackingStatus } from "../../lib/types";
import { ActorField } from "./ActorField";
import { MutationFeedback } from "./MutationFeedback";
import { ReviewDecisionAction } from "./ReviewPrimitives";

/**
 * 추적 결정 입력 한 벌(설계고도화안 C-7, 2026-11-19).
 *
 * 추적 결정을 받는 자리가 셋이었다 — 발주계획 상세 바닥, 사전규격(목록 바닥·상세 카드), 사업기회의
 * `추적 상태 변경` 대화상자. 필드 이름·순서·검증 문구·버튼 이름·저장 결과 표시가 자리마다 달랐다.
 * 발주계획 바닥의 모양(사유 → 담당자 → 결정 버튼, 버튼마다 같은 비활성 사유를 `aria-describedby`로
 * 가리킴, `종료`만 확인 단계)을 기준으로 이 파일에 모으고 세 자리가 이것을 쓴다.
 *
 * 이 파일이 정하는 것: 필드(선택 사유 → 선택 사유 직접 입력 → 담당자 이름)와 그 이름, 검증 순서와
 * 문구, 결정 버튼의 순서와 이름, 저장 성공·실패 문장. 저장 결과의 모양은 `MutationFeedback`의 규칙을
 * 따른다 — 실패는 입력 옆의 `TrackingSaveError`(폼 오류), 성공은 화면의 알림(`useToast`·`Toast`)에
 * `trackingSavedMessage`를 싣는다. **정하지 않는 것**: 어느 상태를 고를 수 있는지
 * (사전규격은 `계속 추적` 하나 — ADR-0046 결정 6), 사유 예시의 내용, 저장 API와 캐시 반영. 저장 요청은
 * 화면마다 이전과 같은 `PATCH /opportunities/{id}/tracking-status`다.
 */

/** 사유 드롭다운의 `기타 · 직접 입력`. 계약에 실리지 않는 화면 키다. */
export const TRACKING_OTHER_REASON = "__other__";

export const TRACKING_FIELD_LABEL = {
  reason: "선택 사유",
  custom: "선택 사유 직접 입력 (필수)",
  actor: "담당자 이름 (필수)",
} as const;

/** 결정 버튼의 고정 순서. 화면은 고를 수 있는 상태만 넘기며 순서는 바꾸지 않는다. */
export const TRACKING_DECISION_ORDER = ["계속 추적", "보류", "종료"] as const;
export type TrackingDecisionStatus = (typeof TRACKING_DECISION_ORDER)[number];

/**
 * 결정 버튼 이름. `계속 추적`은 아직 아무도 고르지 않은 건(`미선택`·사업기회 없음)에서는
 * `추적 시작하기`(2026-11-19 최종 시안 — 주 버튼은 `~하기`), 이미 다른 결정이 있으면 `계속 추적`이다.
 * `종료`는 어디서나 `추적 종료`다.
 */
export function trackingActionLabel(status: TrackingDecisionStatus, current: OpportunityTrackingStatus | null): string {
  if (status === "계속 추적") return current === null || current === "미선택" ? "추적 시작하기" : "계속 추적";
  if (status === "종료") return "추적 종료";
  return "보류";
}

/** 지금 저장 요청에 실릴 사유(앞뒤 공백 제외). `기타`면 직접 입력, 아니면 고른 예시다. */
export function trackingReasonValue(choice: string, custom: string): string {
  return (choice === TRACKING_OTHER_REASON ? custom : choice).trim();
}

/**
 * 입력 때문에 저장할 수 없는 이유. 세 자리가 같은 순서·같은 문장으로 막는다. 사업기회 미연결처럼
 * 화면 사정으로 막는 이유는 화면이 이보다 앞에 둔다.
 */
export function trackingInputBlockedReason(input: { choice: string; custom: string; actorName: string; pending?: boolean }): string | null {
  if (input.pending) return "추적 결정 저장 요청을 처리하고 있어요.";
  const reason = trackingReasonValue(input.choice, input.custom);
  const actor = input.actorName.trim();
  if (!reason && !actor) return "선택 사유와 담당자 이름을 입력하면 추적 결정을 기록할 수 있어요.";
  if (!reason) {
    return input.choice === TRACKING_OTHER_REASON
      ? "선택 사유를 직접 입력하면 추적 결정을 기록할 수 있어요."
      : "선택 사유를 고르면 추적 결정을 기록할 수 있어요.";
  }
  if (!actor) return "담당자 이름을 입력하면 추적 결정을 기록할 수 있어요.";
  return null;
}

/** 저장 성공 문장. 화면은 뒤에 이동 사실 같은 한 문장만 덧붙인다. */
export function trackingSavedMessage(status: OpportunityTrackingStatus): string {
  return `추적 상태를 ${status}(으)로 기록했어요.`;
}

/** 저장 실패의 기본 제목(`describeApiError` fallback). */
export const TRACKING_SAVE_FAILED = "추적 결정을 저장하지 못했어요.";

/** 저장 실패 뒤에 붙는 사실. 초안은 남고 서버 상태는 그대로다. */
export const TRACKING_SAVE_KEPT_NOTE = "입력한 내용은 그대로 남아 있어요. 저장된 추적 상태는 바뀌지 않았어요.";

export interface TrackingDecisionInputsProps {
  /** 사유 예시. 화면마다 내용은 다르고 끝에 `기타 · 직접 입력`이 붙는다. */
  presets: readonly string[];
  choice: string;
  onChoiceChange: (value: string) => void;
  custom: string;
  onCustomChange: (value: string) => void;
  actorName: string;
  onActorNameChange: (value: string) => void;
  isDisabled?: boolean;
  size?: "sm" | "md";
  /** 사유 칸(드롭다운 + 직접 입력)의 배치 class. 화면의 기존 배치 규칙이 이 칸을 잡는다. */
  reasonClassName?: string;
  /** 사유 드롭다운 바로 아래에 둘 보조 조작(예: 발주계획의 `직전 사유 다시 쓰기`). */
  reasonExtra?: ReactNode;
  /** 사유 칸 ref. 키보드 진입 때 드롭다운으로 초점을 옮기는 화면이 쓴다. */
  reasonRef?: Ref<HTMLDivElement>;
  /** 담당자 이름을 이 브라우저(localStorage)에 기억할지. 탭 단위로 따로 기억하는 화면은 끈다. */
  rememberActor?: boolean;
  actorPlaceholder?: string;
  /**
   * 담당자 칸 대신 둘 내용. 이름이 이미 정해진 화면(발주계획 — 최종 시안 `이하늘 이름으로 기록해요`)이
   * 문장과 `이름 바꾸기`를 넣는다. 없으면 입력 칸이다.
   */
  actorSlot?: ReactNode;
  /**
   * 칸 이름(`선택 사유`·`선택 사유 직접 입력`)을 화면에서 감추고 낭독기에만 남긴다. 한 줄 띠(사전규격 상세 하단 결정 띠)
   * 처럼 칸 위에 라벨 줄을 둘 자리가 없을 때 쓴다. 무슨 칸인지는 placeholder가 말한다.
   */
  isLabelHidden?: boolean;
  /** 사유 드롭다운이 열리는 쪽. 화면 아래에 고정된 띠는 `above`다(아래로 열면 화면 밖으로 나간다). */
  selectorPlacement?: ComponentProps<typeof Selector>["placement"];
}

/**
 * 필드 셋: 선택 사유 → (기타일 때) 선택 사유 직접 입력 → 담당자 이름. 부모의 배치(격자·한 줄)에
 * 그대로 놓이도록 감싸는 요소 없이 사유 칸과 담당자 칸 둘을 돌려준다.
 */
export function TrackingDecisionInputs({
  presets,
  choice,
  onChoiceChange,
  custom,
  onCustomChange,
  actorName,
  onActorNameChange,
  isDisabled = false,
  size = "sm",
  reasonClassName = "",
  reasonExtra,
  reasonRef,
  rememberActor = true,
  actorPlaceholder = "예: 홍길동",
  actorSlot,
  isLabelHidden = false,
  selectorPlacement,
}: TrackingDecisionInputsProps) {
  return (
    <>
      <div className={`tracking-decision-reason ${reasonClassName}`.trim()} ref={reasonRef}>
        <Selector
          label={TRACKING_FIELD_LABEL.reason}
          isLabelHidden={isLabelHidden}
          placement={selectorPlacement}
          hasClear
          size={size}
          isDisabled={isDisabled}
          placeholder="사유를 선택하세요"
          options={[
            ...presets.map((preset) => ({ value: preset, label: preset })),
            { value: TRACKING_OTHER_REASON, label: "기타 · 직접 입력" },
          ]}
          value={choice || null}
          onChange={(next) => {
            const chosen = next ?? "";
            onChoiceChange(chosen);
            // 지우기 단추로 비우면 직접 입력도 함께 비운다. 다른 예시를 고르면 그 값이 그대로 실린다.
            if (chosen === "") onCustomChange("");
          }}
        />
        {reasonExtra}
        {choice === TRACKING_OTHER_REASON ? (
          <TextInput
            label={TRACKING_FIELD_LABEL.custom}
            isLabelHidden={isLabelHidden}
            size={size}
            value={custom}
            onChange={onCustomChange}
            isDisabled={isDisabled}
            placeholder="이 결정을 고른 이유를 적어 주세요"
          />
        ) : null}
      </div>
      {actorSlot ?? <ActorField
        label={TRACKING_FIELD_LABEL.actor}
        required
        value={actorName}
        onChange={onActorNameChange}
        remember={rememberActor}
        // 세 자리가 같은 짧은 설명을 쓴다. 기억 여부는 자리마다 달라 문장 끝에서만 갈린다.
        description={rememberActor ? "결정 이력에 남는 이름이며 인증이 아니에요. 이 브라우저에 기억돼요." : "결정 이력에 남는 이름이며 인증이 아니에요."}
        showRememberNote={false}
        placeholder={actorPlaceholder}
        autoComplete="off"
        disabled={isDisabled}
      />}
    </>
  );
}

export interface TrackingDecisionActionsProps {
  /** 이 자리가 기록할 수 있는 결정. 순서는 `TRACKING_DECISION_ORDER`가 정한다. */
  statuses: readonly TrackingDecisionStatus[];
  /** 지금 서버의 추적 상태. `추적 시작`·`계속 추적` 이름을 고른다. */
  current: OpportunityTrackingStatus | null;
  isDisabled: boolean;
  /** 비활성 사유 문장의 id. 문장은 화면이 한 번만 그리고 버튼은 모두 이 id를 가리킨다. */
  disabledReasonId: string;
  onDecide: (status: TrackingDecisionStatus) => void;
  /** 저장 중인 결정. 그 버튼만 `저장 중…`이 된다. */
  pendingStatus?: TrackingDecisionStatus | null;
}

/** 결정 버튼 줄. 첫 버튼이 주 결정이고 나머지는 보조다. 확인 단계(`종료`)는 화면이 연다. */
export function TrackingDecisionActions({
  statuses,
  current,
  isDisabled,
  disabledReasonId,
  onDecide,
  pendingStatus = null,
}: TrackingDecisionActionsProps) {
  const allowed = TRACKING_DECISION_ORDER.filter((status) => statuses.includes(status));
  return (
    <>
      {allowed.map((status, index) => (
        <ReviewDecisionAction
          key={status}
          disabledReasonId={disabledReasonId}
          isDisabled={isDisabled}
          label={pendingStatus === status ? "저장 중…" : trackingActionLabel(status, current)}
          className={`tracking-action is-${status === "계속 추적" ? "continue" : status === "보류" ? "hold" : "end"}`}
          variant={index === 0 ? "primary" : "secondary"}
          onClick={() => onDecide(status)}
        />
      ))}
    </>
  );
}

/** 저장 실패. 오류 설명은 `describeApiError`가 옮긴 것만 쓰고, 초안이 남았다는 사실을 붙인다. */
export function TrackingSaveError({ problem }: { problem: ApiErrorDescription }) {
  return (
    <MutationFeedback className="tracking-save-error" problem={problem} tone="error">
      <p>{TRACKING_SAVE_KEPT_NOTE}</p>
    </MutationFeedback>
  );
}
