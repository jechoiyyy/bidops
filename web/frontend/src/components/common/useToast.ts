import { useCallback, useState } from "react";
import type { ToastVariant } from "./Toast";

export interface ToastState {
  message: string;
  variant: ToastVariant;
  /** 결과에서 이어 갈 화면 링크. 없으면 빈 배열이다. */
  links: ReadonlyArray<{ label: string; to: string }>;
}

export interface ToastController {
  /** 지금 떠 있는 알림. 없으면 `null`이다. */
  toast: ToastState | null;
  /** 저장처럼 화면을 바꾸지 않는 동작의 결과를 알린다. */
  showToast: (message: string, variant?: ToastVariant, links?: ReadonlyArray<{ label: string; to: string }>) => void;
  dismissToast: () => void;
}

/**
 * 화면 하나가 소유하는 알림 상태.
 *
 * 저장 성공 피드백이 화면마다 달랐다 — 어떤 화면은 `Toast`, 어떤 화면은 인라인
 * `MutationFeedback`, 어떤 화면은 그냥 `<p role="status">`였다. 이 hook은 띄우는
 * 방식을 하나로 모은다. 자동 소멸과 hover·focus 중 멈춤은 `Toast` 컴포넌트가
 * 소유하므로 여기에는 타이머가 없다.
 *
 * 전역 store를 만들지 않는다. 알림은 그 화면의 저장 결과이며, 화면을 벗어나면
 * 같이 사라지는 것이 맞다.
 */
export function useToast(): ToastController {
  const [toast, setToast] = useState<ToastState | null>(null);

  const showToast = useCallback((message: string, variant: ToastVariant = "success", links: ReadonlyArray<{ label: string; to: string }> = []) => {
    setToast({ message, variant, links });
  }, []);

  const dismissToast = useCallback(() => setToast(null), []);

  return { toast, showToast, dismissToast };
}
