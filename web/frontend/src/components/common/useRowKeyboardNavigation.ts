import { useCallback, useEffect, useRef } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEventHandler, RefObject } from "react";

/**
 * 목록 행을 ↑↓로 오르내리는 키보드 이동.
 *
 * 검토 대기열(`QueuePage`)이 화면 안에 직접 들고 있던 패턴(`isTypingTarget`·
 * `moveSelection`·행의 `scrollIntoView`)을 화면 밖으로 뺀 것이다. 발주계획 검토 목록이
 * 먼저 쓰고, 사전규격(DenseList)·사업 추적·Go/No-Go(Astryx `Table`)도 같은 형태로 쓸 수
 * 있다 — `rowProps`가 DOM 형태를 가정하지 않고 `data-row-key`와 roving `tabIndex`만
 * 돌려주므로, `<li>`든 표의 첫 열 버튼이든 그 요소에 그대로 뿌리면 된다.
 *
 * **왜 window 리스너가 아닌가.** 리스너는 목록 컨테이너에 단다. 전역으로 달면 같은
 * 화면의 상세 pane 입력, 목록 폭 리사이즈 손잡이의 `ArrowLeft/Right/Home/End`,
 * 대화상자 안의 방향키와 경쟁하게 되고, 어느 쪽이 먼저 잡을지가 마운트 순서에 달리게
 * 된다. 컨테이너에 달면 "목록 안에 초점이 있을 때만" 동작한다는 규칙이 DOM 구조로
 * 보장된다.
 *
 * **페이지 단축키와의 관계.** 이 핸들러는 행에서 올라온 이벤트를 bubble 단계에서 받는다.
 * 화면이 행에 자기 `onKeyDown`(예: `Ctrl+Enter`로 추적 시작)을 달고 `preventDefault()`를
 * 부르면, 여기서는 `event.defaultPrevented`를 보고 아무 것도 하지 않는다. 화면 단축키가
 * 항상 먼저다.
 *
 * **선택은 이 hook이 소유하지 않는다.** 목록의 선택은 URL(`?selected=`)이나 화면 상태가
 * 정본이므로, 여기서는 `onSelect`로 이동을 요청만 하고 목표 key를 `pendingRef`에 적어
 * 둔다. 실제로 `selectedKey`가 그 값이 됐을 때에만 그 행에 초점을 옮긴다. 그래서 저장하지
 * 않은 입력 때문에 화면이 이탈 확인 대화상자를 띄우고 사람이 **취소**하면, 선택이 바뀌지
 * 않았으므로 초점도 움직이지 않는다(대기만 남고, 마우스로 다른 행을 누르면 지워진다).
 */

export type RowKey = string | number;

/** 행 요소에 그대로 뿌리는 props. 선택된 행만 tab 순서에 남는 roving tabindex다. */
export interface RowKeyboardNavigationRowProps {
  "data-row-key": string;
  tabIndex: 0 | -1;
}

export interface RowKeyboardNavigationOptions<K extends RowKey> {
  /**
   * 키 이벤트를 받을 컨테이너. `<ul>`이나 목록 스크롤 영역처럼 모든 행을 담는 요소면 된다.
   * 행 요소를 찾을 때의 검색 범위이기도 하다.
   */
  containerRef: RefObject<HTMLElement | null>;
  /** 지금 그려져 있는 행의 key를 보이는 순서대로. 이동은 이 배열 안에서만 일어난다. */
  keys: readonly K[];
  /** 지금 선택된 행. 선택이 없으면 `null`. */
  selectedKey: K | null;
  /** 이동 요청. 화면이 URL·상태를 바꾼다(막을 수 있다 — 이탈 확인 등). */
  onSelect: (key: K) => void;
  /**
   * `keys`의 처음/끝을 넘어가려 할 때 불린다. 페이지 넘김처럼 화면만 아는 이동을
   * 맡긴다. 호출 뒤 `selectedKey`가 실제로 바뀌면 그 행에 초점을 옮긴다.
   */
  onBoundary?: (direction: "next" | "previous") => void;
  /** `Home`·`End`로 처음·끝 행으로 뛰는 기능을 켠다. @default false */
  homeEnd?: boolean;
  /**
   * 행 요소를 찾는 선택자를 직접 만든다(컨테이너 기준). 기본값은
   * `[data-row-key="<key>"]`이며, `rowProps`를 그대로 뿌렸다면 바꿀 필요가 없다.
   */
  rowSelector?: (key: K) => string;
}

export interface RowKeyboardNavigation<K extends RowKey> {
  /** 컨테이너에 단다. */
  onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => void;
  /** 컨테이너에 단다. 마우스 조작이 대기 중이던 키보드 초점 이동을 덮지 않게 한다. */
  onPointerDownCapture: PointerEventHandler<HTMLElement>;
  /** 행 요소(또는 표 행의 첫 열 버튼)에 뿌린다. */
  rowProps: (key: K) => RowKeyboardNavigationRowProps;
}

type PendingFocus<K extends RowKey> =
  | { kind: "key"; key: K }
  | { kind: "boundary"; from: K | null };

/** 목록 위 단축키는 사람이 글자를 입력하는 동안에는 동작하면 안 된다. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest("input, textarea, select, [contenteditable]"));
}

/** 속성 선택자의 따옴표 안에 들어갈 값. key에 `"`나 `\`가 있어도 선택자가 깨지지 않는다. */
function escapeAttributeValue(value: string): string {
  return value.replace(/["\\]/g, "\\$&");
}

export function useRowKeyboardNavigation<K extends RowKey>({
  containerRef,
  keys,
  selectedKey,
  onSelect,
  onBoundary,
  homeEnd = false,
  rowSelector,
}: RowKeyboardNavigationOptions<K>): RowKeyboardNavigation<K> {
  const pendingRef = useRef<PendingFocus<K> | null>(null);

  const focusRow = useCallback(
    (key: K) => {
      const container = containerRef.current;
      if (!container) return;
      const selector = rowSelector ? rowSelector(key) : `[data-row-key="${escapeAttributeValue(String(key))}"]`;
      const row = container.querySelector<HTMLElement>(selector);
      if (!row) return;
      // 초점 이동이 만드는 기본 스크롤은 행을 화면 가운데로 끌고 간다. 스크롤은
      // 우리가 "가장 가까운 위치까지만" 따로 준다.
      row.focus({ preventScroll: true });
      row.scrollIntoView({ block: "nearest" });
    },
    [containerRef, rowSelector],
  );

  useEffect(() => {
    const pending = pendingRef.current;
    if (pending === null) return;
    if (pending.kind === "key") {
      // 목표 행이 목록에서 사라졌다면(필터·회차 변경) 대기를 버린다.
      if (!keys.includes(pending.key)) {
        pendingRef.current = null;
        return;
      }
      // 아직 선택이 옮겨지지 않았다 — 이탈 확인 대화상자가 열려 있는 상태다.
      if (selectedKey !== pending.key) return;
      pendingRef.current = null;
      focusRow(pending.key);
      return;
    }
    // 경계 이동: 화면이 실제로 선택을 옮겼을 때에만 초점을 따라 보낸다.
    if (selectedKey === null || selectedKey === pending.from) return;
    pendingRef.current = null;
    focusRow(selectedKey);
  }, [focusRow, keys, selectedKey]);

  const moveTo = useCallback(
    (key: K) => {
      if (key === selectedKey) {
        // 이미 선택된 행이면 선택은 바뀌지 않는다(effect도 돌지 않는다). 초점만 준다.
        pendingRef.current = null;
        focusRow(key);
        return;
      }
      pendingRef.current = { kind: "key", key };
      onSelect(key);
    },
    [focusRow, onSelect, selectedKey],
  );

  const crossBoundary = useCallback(
    (direction: "next" | "previous") => {
      if (!onBoundary) return;
      pendingRef.current = { kind: "boundary", from: selectedKey };
      onBoundary(direction);
    },
    [onBoundary, selectedKey],
  );

  const onKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLElement>) => {
      // 화면이 자기 단축키로 이미 처리했거나, 수정키 조합이거나, 입력 중이면 우리 것이 아니다.
      if (event.defaultPrevented) return;
      if (event.ctrlKey || event.altKey || event.metaKey) return;
      if (isTypingTarget(event.target)) return;
      if (keys.length === 0) return;

      const index = selectedKey === null ? -1 : keys.indexOf(selectedKey);

      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (index === -1) moveTo(keys[0]);
        else if (index + 1 < keys.length) moveTo(keys[index + 1]);
        else crossBoundary("next");
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (index === -1) moveTo(keys[0]);
        else if (index - 1 >= 0) moveTo(keys[index - 1]);
        else crossBoundary("previous");
        return;
      }
      if (!homeEnd) return;
      if (event.key === "Home") {
        event.preventDefault();
        moveTo(keys[0]);
        return;
      }
      if (event.key === "End") {
        event.preventDefault();
        moveTo(keys[keys.length - 1]);
      }
    },
    [crossBoundary, homeEnd, keys, moveTo, selectedKey],
  );

  const onPointerDownCapture = useCallback<PointerEventHandler<HTMLElement>>(() => {
    // 마우스로 다른 행을 고르면 키보드 이동의 대기는 더 이상 사람의 의도가 아니다.
    pendingRef.current = null;
  }, []);

  // 선택이 목록 밖 값이면(필터 직후 등) 첫 행을 tab 순서에 남긴다. 목록에 tab으로 들어올
  // 자리가 하나도 없는 상태를 만들지 않는다.
  const focusableKey = selectedKey !== null && keys.includes(selectedKey)
    ? selectedKey
    : keys.length > 0
      ? keys[0]
      : null;

  const rowProps = useCallback(
    (key: K): RowKeyboardNavigationRowProps => ({
      "data-row-key": String(key),
      tabIndex: key === focusableKey ? 0 : -1,
    }),
    [focusableKey],
  );

  return { onKeyDown, onPointerDownCapture, rowProps };
}
