import { useLayoutEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * 화면의 페이지 액션을 상단바 슬롯(`#page-header-actions`)에 넣는다.
 *
 * **왜 portal인가.** 목록 4화면은 상단바가 제목을 그리고(`route-meta.ts`의
 * 제목 모드) 페이지는 제목 줄을 두지 않는다. 그러면 `실행 상태`·`데이터 현황`
 * 같은 화면 액션이 놓일 자리가 사라지는데, 그 단추들은 **페이지의 상태**
 * (선택한 회차·조회 결과·대화상자 열림)를 쓰므로 셸로 올릴 수 없다. 그래서
 * 제목은 route metadata가, 액션은 이 portal이 맡는다. 제목까지 portal로 보내면
 * lazy chunk 로딩·오류 경계 상태에서 `<h1>`이 통째로 사라진다.
 *
 * **슬롯이 항상 있는 이유.** 슬롯은 영속 layout route(`AppShell`)의 `TopBar`가
 * 그린다. React는 한 commit의 DOM 변경을 모두 적용한 뒤 layout effect를
 * 실행하므로, 첫 렌더에서 페이지와 상단바가 같은 commit에 들어가든 lazy
 * 페이지가 나중 commit에 들어가든 이 효과가 도는 시점에는 슬롯이 이미 문서에
 * 있다. `useEffect`가 아니라 `useLayoutEffect`인 것은 첫 페인트부터 액션이
 * 보이게 하기 위해서다(액션이 한 프레임 뒤 나타나면 상단바가 흔들린다).
 * 조회는 멱등이라 StrictMode의 이중 호출에도 결과가 같다. SSR은 없다
 * (`main.tsx`의 `createRoot`).
 *
 * 슬롯이 없으면(테스트 등에서 셸 없이 페이지만 그릴 때) 아무것도 그리지 않는다.
 * 액션을 잃는 것이 문서에 슬롯을 새로 만드는 것보다 안전하다.
 *
 * portal 내용은 페이지 root 밖이라 화면별 CSS(4단 글자 재적용 포함)가 닿지
 * 않는다. 셸이 `.topbar-page-actions`에서 그 규칙을 한 번 준다
 * (`styles/shell-relaxed.css`).
 */
export function PageHeaderActions({ children }: { children: ReactNode }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    setSlot(document.getElementById("page-header-actions"));
  }, []);
  return slot ? createPortal(children, slot) : null;
}
