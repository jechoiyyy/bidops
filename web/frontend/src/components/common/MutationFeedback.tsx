import type { ReactNode } from "react";
import { apiErrorRecoveryAction, type ApiErrorDescription } from "../../lib/apiErrors";
import { TechnicalInfo } from "./TechnicalInfo";

export type MutationFeedbackTone = "info" | "success" | "warning" | "error";

interface MutationFeedbackProps {
  children?: ReactNode;
  className?: string;
  tone?: MutationFeedbackTone;
  /**
   * `lib/apiErrors.describeApiError`의 결과. 주면 제목·설명·다음 행동 버튼을
   * 이 컴포넌트가 같은 모양으로 그린다. 서버 raw message는 들어오지 않는다.
   */
  problem?: ApiErrorDescription;
  /** 다음 행동이 `retry`·`reload`일 때 누를 수 있는 복구 조작. */
  onRecover?: () => void;
  /** 복구 버튼 문구를 화면 맥락으로 바꿀 때만 준다. */
  recoverLabel?: string;
  recoverPendingLabel?: string;
  recoverPending?: boolean;
}

/**
 * Mutation 결과를 색뿐 아니라 문구와 live-region 의미로 전달한다.
 *
 * 인라인 피드백은 **폼 오류 전용**이다. 저장 성공처럼 화면을 바꾸지 않는
 * 결과는 `useToast`와 `Toast`가 맡는다.
 */
export function MutationFeedback({
  children,
  className = "",
  tone = "info",
  problem,
  onRecover,
  recoverLabel,
  recoverPendingLabel,
  recoverPending = false,
}: MutationFeedbackProps) {
  const isError = tone === "error";
  const recovery = problem ? apiErrorRecoveryAction(problem, onRecover, recoverLabel) : undefined;
  return (
    <div
      className={`mutation-feedback mutation-feedback-${tone} ${className}`.trim()}
      role={isError ? "alert" : "status"}
      aria-live={isError ? "assertive" : "polite"}
      aria-atomic="true"
    >
      {problem ? (
        <>
          <strong className="mutation-feedback-title">{problem.title}</strong>
          {/* 문단이 `<div>`인 것은 접힌 `기술 정보`(native `<details>`)를 문장 옆에
              두기 위해서다 — `<details>`는 `<p>` 안에 들어갈 수 없다. 글자 크기·여백은
              `.mutation-feedback-detail` 그대로다. */}
          <div className="mutation-feedback-detail">
            {problem.detail}
            {problem.code ? (
              <>
                {/* 코드는 접어도 **보조기술에는 계속 읽힌다.** 이 영역은
                    `role="alert"`·`aria-atomic`이라 나타날 때 안쪽 전체가 읽히는데,
                    접힌 `<details>` 안은 접근 트리에서 감춰져 읽히지 않는다. 그래서
                    같은 문장을 시각적으로만 감춰 한 번 더 둔다. 눈으로 보는 사람은
                    접힘을 펴서 코드를 복사한다. 코드 값 자체는 `apiErrors.ts`가 준
                    안전 코드 그대로이며 줄이거나 번역하지 않는다(ADR-0066 결정 2·3). */}
                <span className="visually-hidden"> 오류 코드 {problem.code}</span>
                <TechnicalInfo className="technical-info-inline" summary="기술 정보">
                  <p className="mutation-feedback-code">오류 코드 {problem.code}</p>
                </TechnicalInfo>
              </>
            ) : null}
          </div>
          {recovery ? (
            <button
              className="interaction-control"
              type="button"
              onClick={recovery.onClick}
              disabled={recoverPending}
            >
              {recoverPending ? (recoverPendingLabel ?? `${recovery.label} 중`) : recovery.label}
            </button>
          ) : null}
        </>
      ) : null}
      {children}
    </div>
  );
}
