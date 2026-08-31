import { useEffect } from "react";
import { useBlocker } from "react-router-dom";

interface UnsavedGuardOptions {
  blockSpaNavigation?: boolean;
  message?: string;
}

const DEFAULT_MESSAGE = "저장되지 않은 변경이 있습니다. 이 페이지를 벗어나시겠습니까?";

/**
 * 브라우저 종료·새로고침을 보호하고, 요청한 화면에서는 SPA route 이동도 확인한다.
 * 로컬 임시 저장처럼 화면별 보존 계약은 호출자가 그대로 유지한다.
 */
export function useUnsavedGuard(dirty: boolean, options: UnsavedGuardOptions = {}): void {
  const { blockSpaNavigation = false, message = DEFAULT_MESSAGE } = options;
  const blocker = useBlocker(blockSpaNavigation && dirty);

  useEffect(() => {
    if (blocker.state !== "blocked") return;
    if (window.confirm(message)) {
      blocker.proceed();
    } else {
      blocker.reset();
    }
  }, [blocker, message]);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);
}
