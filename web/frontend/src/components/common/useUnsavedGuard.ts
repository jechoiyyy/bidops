import { createElement, useCallback, useEffect, useMemo, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { useBlocker } from "react-router-dom";
import { ConfirmDecisionDialog, type ConfirmDecisionSummaryItem } from "./ConfirmDecisionDialog";

/**
 * 저장되지 않은 입력을 지키는 화면 계약.
 *
 * 확인은 브라우저 `window.confirm`이 아니라 화면의 확인 다이얼로그
 * (`ConfirmDecisionDialog`, tone `unsaved`)로 한다. 브라우저 confirm은 화면의
 * 문구·초점·테마를 따르지 않고, 무엇을 잃는지 되풀이해 보여 줄 자리도 없다.
 *
 * `beforeunload`만은 그대로 native다. 브라우저 종료·새로고침은 native 경고 외의
 * 수단이 없다.
 */

const DEFAULT_TITLE = "저장하지 않은 입력이 있습니다";
const DEFAULT_MESSAGE = "저장되지 않은 변경이 있습니다. 이 페이지를 벗어나시겠습니까?";
const DEFAULT_CONFIRM_LABEL = "저장하지 않고 이동";
const DEFAULT_CANCEL_LABEL = "계속 편집";

/** 다이얼로그가 사람에게 보여 줄 내용. 부르는 자리마다 잃는 것이 다르므로 문구를 넘긴다. */
export interface UnsavedGuardContent {
  title?: string;
  /** 경고 문장. 무엇을 잃는지 그대로 적는다. */
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 잃게 될 입력을 되풀이해 보여 준다. 비우면 요약 표를 그리지 않는다. */
  summary?: ConfirmDecisionSummaryItem[];
}

export interface UnsavedGuardOptions extends UnsavedGuardContent {
  /** route 이동(SPA navigation)을 막을지. 기본은 막지 않는다. */
  blockSpaNavigation?: boolean;
  /**
   * 어떤 이동을 막을지.
   *
   * - `any`(기본): 검색 인자만 바뀌는 이동까지 모두 막는다.
   * - `pathname`: 경로가 바뀔 때만 막는다. 목록 화면은 행 선택·필터·페이지를
   *   검색 인자로 옮기므로, 그 이동은 화면이 자기 문구로 `confirmDiscard`를
   *   불러 확인한다. 그렇지 않으면 "이 페이지를 벗어나시겠습니까?"라는 틀린
   *   문구가 행 전환에도 뜨고, 화면이 따로 건 확인과 겹쳐 두 번 묻는다.
   */
  scope?: "any" | "pathname";
}

export interface UnsavedGuard {
  /**
   * 화면 안에서 입력을 버리는 이동(다른 행 선택, 필터 변경, 페이지 이동)을
   * 확인한 뒤 실행한다. 입력이 없으면 묻지 않고 바로 실행한다.
   *
   * `content.dirty`를 주면 그 값으로 판단한다. 한 화면에 잃는 범위가 다른 입력이
   * 여러 개일 때(행을 바꾸면 사라지는 입력 / 화면을 떠나야 사라지는 입력) 서로
   * 다른 조건을 물어야 하기 때문이다.
   */
  confirmDiscard: (run: () => void, content?: UnsavedGuardContent & { dirty?: boolean }) => void;
  /**
   * 저장에 성공한 직후처럼 "이제 잃을 것이 없다"를 **다시 그리기 전에** 알린다.
   * 저장 성공 handler가 곧바로 `navigate()`를 부르면 dirty 계산은 아직 이전
   * 렌더의 값이라 자기 이동을 자기가 막는다.
   */
  release: () => void;
}

interface HostRequest extends Required<Omit<UnsavedGuardContent, "summary">> {
  summary: ConfirmDecisionSummaryItem[];
  owner: symbol;
  onConfirm: () => void;
  onCancel: () => void;
  returnFocus: HTMLElement | null;
}

// --- 다이얼로그 host -------------------------------------------------------
//
// hook은 JSX를 돌려줄 수 없고, 이 hook을 부르는 화면 중 일부(DeepReviewPage,
// BidDeltaDecisionPage)는 이번 변경의 소유 파일이 아니라 "돌려받은 노드를
// 그려 달라"고 요구할 수 없다. 그래서 확인 다이얼로그는 body에 붙인 host root
// 하나가 그린다. 셸이 host 컴포넌트를 한 번 그려 주면 이 root는 지울 수 있다.
//
// host는 한 번 만들고 지우지 않는다. 요청이 없으면 `open={false}`라
// Astryx native dialog가 top layer에서 내려오므로, 다른 root를 렌더 중에
// unmount하는 위험을 만들 이유가 없다.
let hostContainer: HTMLElement | null = null;
let hostRoot: Root | null = null;
let activeRequest: HostRequest | null = null;

function paintHost(): void {
  if (!hostRoot) return;
  const request = activeRequest;
  hostRoot.render(createElement(ConfirmDecisionDialog, {
    cancelLabel: request?.cancelLabel ?? DEFAULT_CANCEL_LABEL,
    confirmLabel: request?.confirmLabel ?? DEFAULT_CONFIRM_LABEL,
    onConfirm: () => {
      const current = activeRequest;
      closeHost(false);
      current?.onConfirm();
    },
    onOpenChange: (next: boolean) => {
      // 취소·Esc·overlay 클릭은 모두 "이동하지 않는다"로 읽는다.
      if (next) return;
      const current = activeRequest;
      closeHost(true);
      current?.onCancel();
    },
    open: request !== null,
    summary: request?.summary ?? [],
    title: request?.title ?? DEFAULT_TITLE,
    tone: "unsaved" as const,
    warning: request?.message ?? DEFAULT_MESSAGE,
  }));
}

function closeHost(restoreFocus: boolean): void {
  const focusTarget = activeRequest?.returnFocus;
  activeRequest = null;
  paintHost();
  if (!restoreFocus || !focusTarget?.isConnected) return;
  // Astryx Dialog restores its trigger when one exists. This host has no
  // trigger (it is mounted once at document.body), so restore the element
  // that owned focus before the guard opened after the native dialog closes.
  requestAnimationFrame(() => {
    if (focusTarget.isConnected) focusTarget.focus({ preventScroll: true });
  });
}

function openHost(request: HostRequest): void {
  if (!hostRoot) {
    hostContainer = document.createElement("div");
    hostContainer.setAttribute("data-unsaved-guard-host", "");
    document.body.appendChild(hostContainer);
    hostRoot = createRoot(hostContainer);
  }
  const focused = document.activeElement;
  activeRequest = {
    ...request,
    returnFocus: focused instanceof HTMLElement && focused !== document.body ? focused : null,
  };
  paintHost();
}

/** 자기가 연 요청만 닫는다. 남의 확인 단계를 대신 닫지 않는다. */
function dismissHost(owner: symbol): void {
  if (activeRequest?.owner !== owner) return;
  activeRequest = null;
  paintHost();
}

function requestFrom(
  owner: symbol,
  content: UnsavedGuardContent,
  handlers: { onConfirm: () => void; onCancel: () => void },
): HostRequest {
  return {
    cancelLabel: content.cancelLabel ?? DEFAULT_CANCEL_LABEL,
    confirmLabel: content.confirmLabel ?? DEFAULT_CONFIRM_LABEL,
    message: content.message ?? DEFAULT_MESSAGE,
    onCancel: handlers.onCancel,
    onConfirm: handlers.onConfirm,
    owner,
    returnFocus: null,
    summary: content.summary ?? [],
    title: content.title ?? DEFAULT_TITLE,
  };
}

/**
 * 브라우저 종료·새로고침을 보호하고, 요청한 화면에서는 SPA route 이동도 확인한다.
 * 로컬 임시 저장처럼 화면별 보존 계약은 호출자가 그대로 유지한다.
 */
export function useUnsavedGuard(dirty: boolean, options: UnsavedGuardOptions = {}): UnsavedGuard {
  const { blockSpaNavigation = false, scope = "any" } = options;
  // hook 인스턴스마다 다른 표식. 두 화면이 겹쳐 있을 때 서로의 확인 단계를 닫지 않는다.
  const owner = useMemo(() => Symbol("unsaved-guard"), []);

  // 이동 시점에 읽어야 하는 값들은 ref로 최신을 들고 있는다. `useBlocker`의 판단
  // 함수와 `confirmDiscard`는 렌더가 아니라 사람이 조작한 순간에 실행된다.
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const contentRef = useRef<UnsavedGuardContent>(options);
  contentRef.current = options;

  const shouldBlock = useCallback(
    ({ currentLocation, nextLocation }: { currentLocation: { pathname: string }; nextLocation: { pathname: string } }) => {
      if (!blockSpaNavigation || !dirtyRef.current) return false;
      if (scope === "pathname" && currentLocation.pathname === nextLocation.pathname) return false;
      return true;
    },
    [blockSpaNavigation, scope],
  );

  const blocker = useBlocker(shouldBlock);
  const blockerRef = useRef(blocker);
  blockerRef.current = blocker;

  // 막힌 이동 하나마다 확인 창 하나다. 상태만 보면 안 된다: router는 blocker 갱신을
  // transition으로 묶으므로, `계속 편집`의 reset() 직후 다음 이동이 다시 막히면 React는
  // "unblocked"를 그리지 않은 채 blocked→blocked만 본다. 그때 상태 값은 같아 효과가
  // 다시 돌지 않고 이동은 확인 창 없이 조용히 막힌다. 막힌 이동마다 새로 만들어지는
  // `blocker.location`을 함께 보아 새 이동이면 창을 다시 연다. 같은 이동이 다시
  // 그려질 때는 같은 객체라 창을 두 번 열지 않는다.
  const blockedLocation = blocker.state === "blocked" ? blocker.location : null;
  useEffect(() => {
    if (blocker.state !== "blocked") return undefined;
    openHost(requestFrom(owner, contentRef.current, {
      onCancel: () => blockerRef.current.reset?.(),
      onConfirm: () => blockerRef.current.proceed?.(),
    }));
    return () => dismissHost(owner);
  }, [blocker.state, blockedLocation, owner]);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const confirmDiscard = useCallback<UnsavedGuard["confirmDiscard"]>((run, content = {}) => {
    const { dirty: overrideDirty, ...text } = content;
    const blocked = overrideDirty ?? dirtyRef.current;
    if (!blocked) {
      run();
      return;
    }
    openHost(requestFrom(owner, { ...contentRef.current, ...text }, {
      onCancel: () => {},
      onConfirm: run,
    }));
  }, [owner]);

  const release = useCallback(() => {
    dirtyRef.current = false;
  }, []);

  return useMemo(() => ({ confirmDiscard, release }), [confirmDiscard, release]);
}
