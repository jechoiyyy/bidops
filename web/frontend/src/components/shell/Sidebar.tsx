import { useQuery } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../lib/api";
import type { WorkloadKey } from "../../lib/types";
import { runSearchFor } from "./route-meta";

/**
 * RL 사이드바 — docs/1016_rootlab-redefinition/ui-spec.md §1.2 (시안 v26, mockups/v26).
 *
 * 위에서 아래로: 워크스페이스 → 검색(⌘K) → 빠른 이동(알림·다음 행동·노트·보고서)
 * → 레코드(공고·사업기회·기관·회사 근거) → 리스트(오늘의 브리핑·추적 중·연차
 * 예고·마감 임박·새 리스트) → 하단(팀원 초대·도움말·설정·사용자).
 *
 * 아직 화면이 없는 항목(노트·보고서·기관·새 리스트·팀원 초대·도움말)은 자리만
 * 두고 `aria-disabled`로 비활성이다. 스스로 "준비 중" 화면을 만들지 않는다.
 * 건수는 `GET /api/workload`의 값만 쓰고(ADR-0067) 없으면 그리지 않는다.
 */
type IconName =
  | "search"
  | "bell"
  | "task"
  | "note"
  | "chart"
  | "doc"
  | "opp"
  | "org"
  | "shield"
  | "plus"
  | "users"
  | "help"
  | "gear"
  | "external";

interface NavItem {
  label: string;
  /** 이동할 주소. `null`이면 화면이 아직 없는 비활성 항목이다. */
  path: string | null;
  icon?: IconName;
  /** 리스트 항목의 색 점. 상태를 색 점만으로 말하지 않으며 식별용이다. */
  dot?: "accent" | "teal" | "warning" | "error";
  /** 활성 판단에 쓰는 `navPath`. 없으면 `path`의 pathname이다. */
  navPath?: string;
  /** 이 항목이 흡수한 옛 경로. 그 주소에서도 이 항목이 활성으로 보인다. */
  absorbs?: string[];
  /** `GET /api/workload`에서 읽는 건수 키. */
  count?: WorkloadKey;
}

interface NavGroup {
  label: string | null;
  items: NavItem[];
}

const groups: NavGroup[] = [
  {
    label: null,
    items: [
      // 알림은 대시보드가 누적 업무 집계를 맡고 있으므로 그 화면으로 간다.
      { label: "알림", path: "/", icon: "bell", count: "human_check_required" },
      { label: "다음 행동", path: "/opportunities?section=조치 필요", icon: "task", navPath: "/opportunities?section=조치 필요", count: "tracking_action_required" },
      { label: "노트", path: null, icon: "note" },
      { label: "보고서", path: null, icon: "chart" },
    ],
  },
  {
    label: "레코드",
    items: [
      // 공고 오브젝트. 사전규격 목록이 현재 정본이고 발주계획·심층 보고서·판정 이력을 흡수한다.
      { label: "공고", path: "/pre-specs", icon: "doc", absorbs: ["/deep-reviews", "/assumption-analyses", "/queue", "/judgments", "/reviews", "/deadlines"] },
      // 사업기회 오브젝트의 전체 보기. 리스트 `추적 중`과 같은 화면이라 활성은 리스트 쪽이 받는다.
      { label: "사업기회", path: "/opportunities?section=전체", icon: "opp", navPath: "/opportunities?section=전체", absorbs: ["/go-no-go"] },
      { label: "기관", path: null, icon: "org" },
      { label: "회사 근거", path: "/profile", icon: "shield", absorbs: ["/companies"] },
    ],
  },
  {
    label: "리스트",
    items: [
      { label: "오늘의 브리핑", path: "/briefing", dot: "accent" },
      { label: "추적 중", path: "/opportunities?section=추적 중", dot: "teal", navPath: "/opportunities?section=추적 중" },
      // 연차 예고는 발주계획에서 나온다. 발주계획 목록이 현재 그 리스트다.
      { label: "연차 예고", path: "/order-plans", dot: "warning", count: "order_plan_new_priority" },
      { label: "마감 임박", path: "/opportunities?section=전체&deadline_within_days=7&sort=deadline", dot: "error", navPath: "/opportunities?deadline", count: "tracking_deadline_imminent" },
      { label: "새 리스트", path: null, icon: "plus" },
    ],
  },
];

const footerItems: NavItem[] = [
  { label: "팀원 초대", path: null, icon: "users" },
  { label: "도움말", path: null, icon: "help" },
  // 운영 메뉴(판정 기준·실행 상태·회차·첨부·감사)는 설정 아래로 옮겼다(ui-spec §1.2).
  { label: "설정", path: "/criteria", icon: "gear", absorbs: ["/run-status", "/runs", "/attachments", "/operations", "/audit", "/policies", "/quality-gates", "/metrics", "/order-plan-policies"] },
];

function NavIcon({ name }: { name: IconName }) {
  const common = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  switch (name) {
    case "search":
      return <svg {...common}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>;
    case "bell":
      return <svg {...common}><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10 21a2 2 0 0 0 4 0" /></svg>;
    case "task":
      return <svg {...common}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m8 12 3 3 5-6" /></svg>;
    case "note":
      return <svg {...common}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></svg>;
    case "chart":
      return <svg {...common}><path d="M3 3v18h18" /><path d="M7 15l4-5 4 3 5-7" /></svg>;
    case "doc":
      return <svg {...common}><path d="M4 4h12l4 4v12H4z" /><path d="M8 12h8M8 16h8" /></svg>;
    case "opp":
      return <svg {...common}><path d="M3 12h4l3-7 4 14 3-7h4" /></svg>;
    case "org":
      return <svg {...common}><path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6" /></svg>;
    case "shield":
      return <svg {...common}><path d="M12 3 4 7v5c0 5 3.5 8.5 8 9 4.5-.5 8-4 8-9V7z" /><path d="m9 12 2 2 4-4" /></svg>;
    case "plus":
      return <svg {...common}><path d="M12 5v14M5 12h14" /></svg>;
    case "users":
      return <svg {...common}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M16 4a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4.5-6.2" /></svg>;
    case "help":
      return <svg {...common}><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7" /><path d="M12 17h.01" /></svg>;
    case "gear":
      return <svg {...common}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>;
    case "external":
      return <svg {...common}><path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" /></svg>;
  }
}

function pathnameOf(path: string): string {
  const index = path.indexOf("?");
  return index === -1 ? path : path.slice(0, index);
}

function isCurrentPath(pathname: string, path: string): boolean {
  return path === "/" ? pathname === "/" : pathname === path || pathname.startsWith(`${path}/`);
}

/**
 * 활성 항목은 화면 metadata가 정한 `activeNavPath`가 먼저 정한다. 같은 pathname을
 * 쓰는 항목(사업기회 전체 보기·추적 중·마감 임박)은 항목의 `navPath`가 주소의
 * 검색어까지 포함해 구분한다. metadata가 없는 주소에서만 경로·흡수 목록으로 돌아간다.
 */
function isActiveItem(item: NavItem, activeNavPath: string | null, pathname: string, search: string): boolean {
  if (item.path === null) return false;
  const itemNav = item.navPath ?? pathnameOf(item.path);
  if (activeNavPath !== null) {
    if (activeNavPath !== pathnameOf(itemNav)) {
      return (item.absorbs ?? []).some((absorbed) => isCurrentPath(pathname, absorbed));
    }
    // 같은 화면을 가리키는 항목이 여럿이면 검색어가 가장 많이 맞는 하나만 활성이다.
    const params = new URLSearchParams(search);
    const section = params.get("section");
    const deadline = params.has("deadline_within_days");
    const isDetail = pathname.startsWith("/opportunities/") || pathname.startsWith("/go-no-go");
    if (itemNav === "/opportunities?deadline") return deadline && !isDetail;
    // 사업기회 레코드: 전체 보기와 상세·최종 Go/No-Go.
    if (itemNav === "/opportunities?section=전체") return isDetail || (section === "전체" && !deadline);
    // 다음 행동: 기본 구역(조치 필요). 화면이 기본 구역의 section 파라미터를 지우므로 비어 있어도 활성이다.
    if (itemNav === "/opportunities?section=조치 필요") return !isDetail && !deadline && (section === null || section === "조치 필요");
    if (itemNav === "/opportunities?section=추적 중") return !isDetail && !deadline && section === "추적 중";
    return true;
  }
  if (isCurrentPath(pathname, pathnameOf(item.path))) return true;
  return (item.absorbs ?? []).some((absorbed) => isCurrentPath(pathname, absorbed));
}

/**
 * 가상회사 데모 메뉴(`GET /api/demo-config`가 enabled일 때만). 회사가 정해진 주소에서만
 * 그 회사의 화면 항목을 보이며, 회사를 몰래 고르지 않는다(`docs/work/demo-contract.md` §1).
 */
function demoGroup(companyId: string | null): NavGroup {
  const items: NavItem[] = [{ label: "회사 선택", path: "/companies", icon: "org" }];
  if (companyId) {
    items.push(
      { label: "회사 사전규격", path: `/companies/${companyId}/pre-specs`, icon: "doc" },
      { label: "회사 프로필", path: `/companies/${companyId}/profile`, icon: "shield" },
    );
  }
  return { label: "가상회사 데모", items };
}

export interface SidebarDemoNav {
  /** 주소에서 읽은 현재 회사. 회사가 정해지지 않은 주소면 `null`이다. */
  companyId: string | null;
}

export function Sidebar({ activeNavPath, runSearch, demoNav = null }: { activeNavPath: string | null; runSearch: string; demoNav?: SidebarDemoNav | null }) {
  const { pathname, search } = useLocation();
  const workload = useQuery({ queryKey: ["workload"], queryFn: () => api.getWorkload(), staleTime: 60_000 });
  const counts = new Map<WorkloadKey, number>();
  for (const item of workload.data?.items ?? []) {
    if (typeof item.count === "number") counts.set(item.key, item.count);
  }
  const visibleGroups = demoNav ? [...groups, demoGroup(demoNav.companyId)] : groups;
  return (
    <aside aria-label="주 메뉴" className="sidebar" data-shell-region="sidebar">
      {/* 워크스페이스 줄(시안: 머리글자 아이콘 + 회사명). 로그인·워크스페이스 전환이
          없으므로 링크는 브리핑으로 간다. */}
      <Link aria-label="루트랩 BidOps 오늘의 브리핑으로 이동" className="sidebar-brand" to={{ pathname: "/briefing", search: runSearchFor("/briefing", runSearch) }}>
        <span aria-hidden="true" className="sidebar-brand-mark">루</span>
        <strong>루트랩</strong>
      </Link>
      {/* 검색은 커맨드 팔레트가 들어오기 전까지 자리만 둔다(ui-spec §1.2). */}
      <button aria-disabled="true" className="sidebar-search" disabled type="button">
        <NavIcon name="search" />
        <span>검색</span>
        <kbd>⌘K</kbd>
      </button>
      <nav aria-label="주 메뉴" className="sidebar-nav">
        {visibleGroups.map((group, index) => (
          <div className="sidebar-group" key={group.label ?? `quick-${index}`}>
            {group.label ? <div className="sidebar-group-label">{group.label}</div> : null}
            <div className="sidebar-items">
              {group.items.map((item) => (
                <NavEntry
                  active={isActiveItem(item, activeNavPath, pathname, search)}
                  count={item.count ? counts.get(item.count) ?? null : null}
                  item={item}
                  key={item.label}
                  runSearch={runSearch}
                />
              ))}
            </div>
          </div>
        ))}
        <a
          aria-label="나라장터 바로가기 (새 탭에서 열림)"
          className="sidebar-item sidebar-external-link"
          href="https://www.g2b.go.kr/"
          rel="noopener noreferrer"
          target="_blank"
        >
          <NavIcon name="external" />
          <span>나라장터 바로가기</span>
        </a>
      </nav>
      <div className="sidebar-footer">
        {footerItems.map((item) => (
          <NavEntry
            active={isActiveItem(item, activeNavPath, pathname, search)}
            count={null}
            item={item}
            key={item.label}
            runSearch={runSearch}
          />
        ))}
        {/* 사용자 줄. 로그인이 없으므로 부서 표식만 둔다(담당자 이름은 인증이 아니다). */}
        <div className="sidebar-user">
          <span aria-hidden="true" className="sidebar-avatar">기</span>
          <span>기획부 · 사업기획</span>
        </div>
      </div>
    </aside>
  );
}

function NavEntry({ item, active, count, runSearch }: { item: NavItem; active: boolean; count: number | null; runSearch: string }) {
  const body = (
    <>
      {item.icon ? <NavIcon name={item.icon} /> : null}
      {item.dot ? <span aria-hidden="true" className={`sidebar-dot is-${item.dot}`} /> : null}
      <span className="sidebar-item-label">{item.label}</span>
      {/* 건수는 보조 표시다. 링크의 접근 가능한 이름은 항목 이름 하나로 두고(테스트·
          보조 기술이 "알림 2"가 아니라 "알림"으로 읽는다) 건수는 title로 함께 준다. */}
      {count !== null ? (
        <span aria-hidden="true" className={`sidebar-item-count${active ? " is-active" : ""}`}>{count}</span>
      ) : null}
    </>
  );
  if (item.path === null) {
    return (
      <span aria-disabled="true" className="sidebar-item is-disabled" title="아직 준비되지 않은 항목">
        {body}
      </span>
    );
  }
  const pathname = pathnameOf(item.path);
  const query = item.path.includes("?") ? item.path.slice(item.path.indexOf("?")) : "";
  const runQuery = runSearchFor(pathname, runSearch);
  const searchValue = query && runQuery ? `${query}&${runQuery.slice(1)}` : query || runQuery;
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={`sidebar-item${active ? " is-active" : ""}`}
      title={count !== null ? `${item.label} ${count}건` : undefined}
      to={{ pathname, search: searchValue }}
    >
      {body}
    </Link>
  );
}
