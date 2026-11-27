import { createContext, useContext, useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * 패널 헤더의 글자를 화면이 셸에 알리는 context(2026-11-19 최종 시안, `docs/specs/1119_kstyle-shell/`).
 *
 * 패널 헤더는 셸(`TopBar`)이 그린다 — 화면 이름(작은 글자) · 문장형 제목 `<h1>` · 한 줄 설명 ·
 * 오른쪽 액션(`#page-header-actions`) · 아래 탭(`#page-header-tabs`). `<h1>`을 셸이 쥐는 이유는
 * `PageHeaderActions`와 같다: 제목까지 portal로 보내면 lazy chunk 로딩·오류 경계 상태에서 `<h1>`이
 * 통째로 사라진다. 그래서 화면은 **문자열만** 올리고, 올리기 전(로딩·오류)에는 route 이름이 `<h1>`이다.
 *
 * 값은 올린 화면의 pathname과 함께 저장되며 셸은 **지금 주소의 pathname과 같을 때만** 쓴다 — 다른
 * 화면으로 옮긴 직후 이전 화면의 제목이 한 프레임이라도 남지 않게 한다(`RecordTitleContext`와 같은 규칙).
 *
 * 문장의 숫자는 화면이 이미 가진 값(목록 total·탭 건수 등)으로만 만든다. 셸은 값을 계산하지 않는다.
 */
export type PageHeaderTagTone = "brand" | "warning" | "info" | "muted";

/**
 * 사실 값의 의미색. 옛 헤더 pill이 쓰던 의미(진행 가능 success · 사람 검토 필요 warning · 진행 어려움 error)를
 * 그대로 옮긴다. 값이 없으면 본문색이다. 색은 테마의 의미색 토큰만 쓴다(`styles/shell-relaxed.css`).
 */
export type PageHeaderFactTone = "success" | "warning" | "error";

export interface PageHeaderContent {
  /** 제목 위 작은 화면 이름(14px). 예: `오늘의 브리핑 · 10월 16일 금요일`. */
  eyebrow?: string | null;
  /** 화면 이름 옆 상태 표식(사업기회 레코드의 추적 상태). 글자가 상태 이름이다. */
  tag?: { label: string; tone: PageHeaderTagTone } | null;
  /** `<h1>` 글자. 없으면 route 이름이다. */
  title?: string | null;
  /** 제목 아래 한 줄 설명(15px). */
  description?: string | null;
  /**
   * 설명 아래 사실 한 줄(이름 · 값 짝). 서로 다른 축(단계·마감·판정·판정 확인·최종 Go/No-Go)을 한 상태로
   * 합치지 않도록 짝마다 이름을 붙여 둔다. 사업기회 레코드가 쓴다.
   */
  facts?: ReadonlyArray<{ key: string; label: string; value: string; tone?: PageHeaderFactTone }> | null;
}

export interface PublishedPageHeader {
  pathname: string;
  content: PageHeaderContent;
}

export const PageHeaderSetterContext = createContext<((pathname: string, content: PageHeaderContent | null) => void) | null>(null);

/**
 * 화면이 패널 헤더의 글자를 올린다. `null`이면 올리지 않는다(로딩·오류 상태는 route 이름이 남는다).
 * 화면을 떠날 때 비운다.
 */
export function usePageHeader(content: PageHeaderContent | null): void {
  const set = useContext(PageHeaderSetterContext);
  const { pathname } = useLocation();
  const key = content === null ? null : JSON.stringify(content);
  useEffect(() => {
    if (!set) return undefined;
    set(pathname, key === null ? null : (JSON.parse(key) as PageHeaderContent));
    return () => set(pathname, null);
  }, [set, pathname, key]);
}

/** 셸이 쓸 값. 지금 주소와 같은 pathname에서 올린 값만 돌려준다. */
export function currentPageHeader(published: PublishedPageHeader | null, pathname: string): PageHeaderContent | null {
  return published && published.pathname === pathname ? published.content : null;
}
