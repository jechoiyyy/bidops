import type { RefObject } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

type IconName = "dashboard" | "queue" | "deadline" | "judgment" | "review" | "profile" | "metrics" | "quality" | "policy" | "runs" | "attachments" | "operations" | "audit" | "order-plan";

interface NavItem {
  label: string;
  path: string;
  icon: IconName;
  // 이 항목의 화면이 흡수한 옛 경로들이다. 옛 경로는 리다이렉트가 아니라 그
  // 뷰·탭의 정식 주소로 남아 있으므로(ADR-0045 결정 8), 그 주소에 있을 때도
  // 이 항목이 활성으로 보여야 한다.
  absorbs?: string[];
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

// ADR-0045 결정 1·2: 1차 분류를 `오늘의 업무` / `탐색과 추적`으로 바꾸고 항목을
// 16에서 7로 줄인다. `검토 대기열`은 회차 축이라 같은 사업기회가 회차마다 다른
// 행으로 나타났다. 그 자리를 `사업 추적`이 받고, 검토 대기열·공고 판정 이력·
// 담당자 리뷰 기록·마감 추적은 사업 추적이 여는 화면이 된다.
//
// 회차 선택기 표시 여부가 사이드바만 보고 예측돼야 하므로(ADR-0045 결정 7)
// 사이드바 항목 중 회차 선택기를 갖는 것은 `대시보드` 하나다. 나머지 한 자리인
// 공고 판정 이력은 사이드바 항목이 아니다.
const groups: NavGroup[] = [
  {
    label: "오늘의 업무",
    items: [
      { label: "대시보드", path: "/", icon: "dashboard" },
    ],
  },
  {
    label: "탐색과 추적",
    items: [
      { label: "발주계획", path: "/order-plans", icon: "order-plan" },
      { label: "사전규격", path: "/pre-specs", icon: "judgment" },
      // 사업 추적이 검토 대기열의 자리를 받는다. 흡수한 옛 경로는 리다이렉트가
      // 아니라 그 화면들의 정식 주소로 남아 있으므로(ADR-0045 결정 8) 그 주소에
      // 있을 때도 이 항목이 활성으로 보인다.
      {
        label: "사업 추적",
        path: "/opportunities",
        icon: "queue",
        absorbs: ["/queue", "/judgments", "/reviews", "/deadlines", "/deep-reviews"],
      },
      { label: "최종 Go/No-Go", path: "/go-no-go", icon: "judgment" },
    ],
  },
  {
    label: "기준과 운영",
    items: [
      { label: "판정 기준", path: "/criteria", icon: "policy", absorbs: ["/profile", "/policies", "/quality-gates", "/metrics"] },
      { label: "실행 상태", path: "/run-status", icon: "operations", absorbs: ["/runs", "/attachments", "/operations", "/audit"] },
    ],
  },
];

function NavIcon({ name }: { name: IconName }) {
  const common = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, "aria-hidden": true };
  switch (name) {
    case "dashboard":
      return <svg {...common}><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></svg>;
    case "queue":
      return <svg {...common}><path d="M4 6h16M4 12h16M4 18h9" /></svg>;
    case "order-plan":
      return <svg {...common}><path d="M5 4h14v16H5z" /><path d="M8 8h8M8 12h8M8 16h5" /><path d="M8 4V2M16 4V2" /></svg>;
    case "deadline":
      return <svg {...common}><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></svg>;
    case "judgment":
      return <svg {...common}><path d="M6 3h9l4 4v14H6z" /><path d="M14 3v5h5M9 13h7M9 17h5" /></svg>;
    case "review":
      return <svg {...common}><path d="M21 12a9 9 0 1 1-4-7.5" /><path d="m9 12 2.5 2.5L20 6" /></svg>;
    case "profile":
      return <svg {...common}><path d="M4 21V6l7-3 7 3v15" /><path d="M9 21v-6h4v6M4 21h16" /></svg>;
    case "metrics":
      return <svg {...common}><path d="M4 19V5M4 19h16" /><path d="m8 15 4-6 3 3 4-7" /></svg>;
    case "quality":
      return <svg {...common}><path d="m12 3 7 3v5c0 4.4-2.9 8.3-7 10-4.1-1.7-7-5.6-7-10V6z" /><path d="m9 12 2 2 4-4" /></svg>;
    case "policy":
      return <svg {...common}><path d="M6 3h9l4 4v14H6z" /><path d="M14 3v5h5M9 13h7M9 17h5" /></svg>;
    case "runs":
      return <svg {...common}><path d="M12 3v6M12 15v6M5 12H3M21 12h-2" /><circle cx="12" cy="12" r="3" /><path d="m6.5 6.5 1.5 1.5M17.5 17.5 16 16" /></svg>;
    case "attachments":
      return <svg {...common}><path d="m21 11-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.7 8.7a2 2 0 0 1-2.9-2.8L15.5 6" /></svg>;
    case "operations":
      return <svg {...common}><path d="M4 17h3l2-10 4 14 2-8h5" /></svg>;
    case "audit":
      return <svg {...common}><path d="M3 7h18M3 12h18M3 17h18" /></svg>;
  }
}

function isCurrentPath(pathname: string, path: string): boolean {
  return path === "/" ? pathname === "/" : pathname === path || pathname.startsWith(`${path}/`);
}

function isActiveItem(pathname: string, item: NavItem): boolean {
  if (isCurrentPath(pathname, item.path)) return true;
  return (item.absorbs ?? []).some((absorbed) => isCurrentPath(pathname, absorbed));
}

export function Sidebar({ navRef, open, onClose }: { navRef: RefObject<HTMLElement | null>; open: boolean; onClose: () => void }) {
  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();
  // 회차 선택은 주소의 run 파라미터에만 남아 있다. 화면을 옮길 때 이 값을 잃으면
  // 담당자가 고른 회차가 최신 회차로 되돌아가므로, 모든 이동에 그대로 넘긴다.
  const runSearchParams = new URLSearchParams();
  if (searchParams.has("run")) runSearchParams.set("run", searchParams.get("run") ?? "");
  const runSearch = runSearchParams.toString() ? `?${runSearchParams.toString()}` : "";
  const atHome = pathname === "/";
  return (
    <>
      <div
        className={`sidebar-backdrop ${open ? "is-open" : ""}`.trim()}
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        aria-label="주 메뉴"
        className={`sidebar ${open ? "is-open" : ""}`.trim()}
        data-shell-region="sidebar"
        id="primary-navigation"
        ref={navRef}
      >
        <Link
          aria-current={atHome ? "page" : undefined}
          aria-label="RootLab BidOps 대시보드로 이동"
          className={`sidebar-brand ${atHome ? "is-current" : ""}`.trim()}
          to={{ pathname: "/", search: runSearch }}
          onClick={onClose}
        >
          <img alt="" className="sidebar-brand-logo" src="/rootlab-icon-light.svg" />
          <span className="sidebar-brand-text">
            <strong>BidOps</strong>
            <span>ROOTLAB · 사업기회 모니터링</span>
          </span>
        </Link>
        <nav aria-label="주 메뉴" className="sidebar-nav">
          {groups.map((group) => (
            <div className="sidebar-group" key={group.label}>
              <div className="sidebar-group-label">{group.label}</div>
              <div className="sidebar-items">
                {group.items.map((item) => (
                  <NavLinkItem
                    active={isActiveItem(pathname, item)}
                    item={item}
                    key={item.path}
                    onNavigate={onClose}
                    runSearch={runSearch}
                  />
                ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span>기획부 · 사업기획</span>
          <span>관리자 화면</span>
        </div>
      </aside>
    </>
  );
}

function NavLinkItem({ item, active, onNavigate, runSearch }: { item: NavItem; active: boolean; onNavigate: () => void; runSearch: string }) {
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={`sidebar-item ${active ? "is-active" : ""}`.trim()}
      to={{ pathname: item.path, search: runSearch }}
      onClick={onNavigate}
    >
      <NavIcon name={item.icon} />
      <span>{item.label}</span>
    </Link>
  );
}
