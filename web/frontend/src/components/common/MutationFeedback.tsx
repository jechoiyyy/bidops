import type { ReactNode } from "react";
import { apiErrorRecoveryAction, type ApiErrorDescription } from "../../lib/apiErrors";

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
          <p className="mutation-feedback-detail">
            {problem.detail}
            {problem.code ? <span className="mutation-feedback-code"> · 오류 코드 {problem.code}</span> : null}
          </p>
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
