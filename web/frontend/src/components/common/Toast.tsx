import { useCallback, useEffect, useRef, useState } from "react";

export type ToastVariant = "success" | "info" | "warning" | "error";

/**
 * 자동 소멸까지의 시간. 6초는 한국어 두 줄 문장을 읽고 `실행 취소`류 액션까지
 * 누르기에 짧았다. 읽는 동안(hover·focus) 타이머는 멈춘다.
 */
const AUTO_DISMISS_MS = 8_000;

interface ToastProps {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
  onDismiss: () => void;
  variant?: ToastVariant;
  /** 자동 소멸 시간(ms). `null`이면 자동으로 사라지지 않는다. */
  autoDismissMs?: number | null;
}

/**
 * 저장처럼 화면을 바꾸지 않는 동작의 결과를 알린다.
 * 화면 낭독기가 결과를 놓치지 않도록 aria-live 영역으로 둔다.
 *
 * 타이머를 이 컴포넌트가 소유한다 — 멈춰야 할 조건(pointer가 올라와 있거나
 * 안의 버튼에 focus가 있음)이 여기에서만 관찰되기 때문이다.
 */
export function Toast({
  message,
  actionLabel,
  onAction,
  onDismiss,
  variant = "success",
  autoDismissMs = AUTO_DISMISS_MS,
}: ToastProps) {
  const isError = variant === "error";
  const [held, setHeld] = useState(false);
  const dismissRef = useRef(onDismiss);
  dismissRef.current = onDismiss;

  useEffect(() => {
    if (autoDismissMs === null || held) return;
    const timer = window.setTimeout(() => dismissRef.current(), autoDismissMs);
    return () => window.clearTimeout(timer);
    // message가 바뀌면 새 알림이므로 시간도 처음부터 다시 센다.
  }, [autoDismissMs, held, message]);

  const hold = useCallback(() => setHeld(true), []);
  const release = useCallback(() => setHeld(false), []);

  return (
    <div
      className={`toast toast-${variant}`}
      role={isError ? "alert" : "status"}
      aria-live={isError ? "assertive" : "polite"}
      data-toast-held={held ? "true" : "false"}
      onMouseEnter={hold}
      onMouseLeave={release}
      onFocusCapture={hold}
      onBlurCapture={release}
    >
      <span className="toast-message">{message}</span>
      {actionLabel && onAction ? (
        <button className="toast-action" type="button" onClick={onAction}>{actionLabel}</button>
      ) : null}
      <button className="toast-dismiss" type="button" aria-label="알림 닫기" onClick={onDismiss}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="m6 6 12 12M18 6 6 18" />
        </svg>
      </button>
    </div>
  );
}
