import { Link, useLocation, useSearchParams } from "react-router-dom";

type IconName = "dashboard" | "queue" | "deadline" | "judgment" | "review" | "profile" | "metrics" | "runs" | "attachments" | "audit";

interface NavItem {
  label: string;
  path: string;
  icon: IconName;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const groups: NavGroup[] = [
  {
    label: "모니터링",
    items: [
      { label: "대시보드", path: "/", icon: "dashboard" },
      { label: "검토 대기열", path: "/queue", icon: "queue" },
      { label: "마감 추적", path: "/deadlines", icon: "deadline" },
    ],
  },
  {
    label: "판정",
    items: [
      { label: "공고 판정 이력", path: "/judgments", icon: "judgment" },
      { label: "담당자 리뷰 기록", path: "/reviews", icon: "review" },
    ],
  },
  {
    label: "기준",
    items: [
      { label: "회사 프로필", path: "/profile", icon: "profile" },
      { label: "검증 지표", path: "/metrics", icon: "metrics" },
    ],
  },
  {
    label: "운영",
    items: [
      { label: "수집 실행", path: "/runs", icon: "runs" },
      { label: "첨부 확보", path: "/attachments", icon: "attachments" },
      { label: "산출물 감사 로그", path: "/audit", icon: "audit" },
    ],
  },
];

function NavIcon({ name }: { name: IconName }) {
  const common = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7 };
  switch (name) {
    case "dashboard":
      return <svg {...common}><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></svg>;
    case "queue":
      return <svg {...common}><path d="M4 6h16M4 12h16M4 18h9" /></svg>;
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
    case "runs":
      return <svg {...common}><path d="M12 3v6M12 15v6M5 12H3M21 12h-2" /><circle cx="12" cy="12" r="3" /><path d="m6.5 6.5 1.5 1.5M17.5 17.5 16 16" /></svg>;
    case "attachments":
      return <svg {...common}><path d="m21 11-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.7 8.7a2 2 0 0 1-2.9-2.8L15.5 6" /></svg>;
    case "audit":
      return <svg {...common}><path d="M3 7h18M3 12h18M3 17h18" /></svg>;
  }
}

function isCurrentPath(pathname: string, path: string): boolean {
  return path === "/" ? pathname === "/" : pathname === path || pathname.startsWith(`${path}/`);
}

export function Sidebar() {
  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();
  // 회차 선택은 주소의 run 파라미터에만 남아 있다. 화면을 옮길 때 이 값을 잃으면
  // 담당자가 고른 회차가 최신 회차로 되돌아가므로, 모든 이동에 그대로 넘긴다.
  const runSearch = searchParams.get("run") ? `?run=${encodeURIComponent(searchParams.get("run") as string)}` : "";
  const atHome = pathname === "/";
  return (
    <aside className="sidebar">
      <Link
        aria-current={atHome ? "page" : undefined}
        aria-label="대시보드로 이동"
        className={`sidebar-brand ${atHome ? "is-current" : ""}`.trim()}
        to={{ pathname: "/", search: runSearch }}
      >
        <span className="sidebar-brand-text">
          <strong>BidOps</strong>
          <span>사업기회 모니터링</span>
        </span>
        <svg className="sidebar-brand-home" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
          <path d="M4 11.5 12 4l8 7.5" />
          <path d="M6 10v10h12V10" />
        </svg>
      </Link>
      <nav aria-label="주 메뉴" className="sidebar-nav">
        {groups.map((group) => (
          <div className="sidebar-group" key={group.label}>
            <div className="sidebar-group-label">{group.label}</div>
            <div className="sidebar-items">
              {group.items.map((item) => (
                <NavLinkItem
                  active={isCurrentPath(pathname, item.path)}
                  item={item}
                  key={item.path}
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
  );
}

function NavLinkItem({ item, active, runSearch }: { item: NavItem; active: boolean; runSearch: string }) {
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={`sidebar-item ${active ? "is-active" : ""}`.trim()}
      to={{ pathname: item.path, search: runSearch }}
    >
      <NavIcon name={item.icon} />
      <span>{item.label}</span>
    </Link>
  );
}
