export type ToastVariant = "success" | "info" | "warning" | "error";

interface ToastProps {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
  onDismiss: () => void;
  variant?: ToastVariant;
}

/**
 * 저장처럼 화면을 바꾸지 않는 동작의 결과를 알린다.
 * 화면 낭독기가 결과를 놓치지 않도록 aria-live 영역으로 둔다.
 */
export function Toast({ message, actionLabel, onAction, onDismiss, variant = "success" }: ToastProps) {
  return (
    <div className={`toast toast-${variant}`} role="status" aria-live="polite">
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
