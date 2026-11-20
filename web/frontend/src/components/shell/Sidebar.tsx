import { useEffect, useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../lib/api";
import { companyContextQueryKey, getCompanyContext } from "../../lib/companyApi";
import { orderPlanViewTotalQuery, preSpecDefaultViewTotalQuery } from "../../lib/defaultViewCounts";
import type { WorkloadKey } from "../../lib/types";
import { ActorField, useRememberedActorName } from "../common/ActorField";
import { runSearchFor } from "./route-meta";

/**
 * RL 사이드바 — docs/1016_rootlab-redefinition/ui-spec.md §1.2 (시안 v26, mockups/v26).
 *
 * 2026-11-18 개정(설계고도화안 A-7·C-1·C-2, ui-spec §1.2 날짜 메모): 시안의 묶음과 모양은 그대로
 * 두되 **항목 이름 = 여는 화면의 제목**이다. 화면이 없는 자리표시(노트·보고서·기관·새 리스트·
 * 팀원 초대·도움말·검색)는 그리지 않는다. 최종 Go/No-Go와 실행 상태에 고정 항목을 둔다.
 *
 * - 빠른 이동: 대시보드
 * - 레코드: 발주계획 · 사전규격 · 사업기회 · 최종 Go/No-Go · 회사 근거
 * - 리스트(사업기회·브리핑의 이름 붙은 보기): 오늘의 브리핑 · 추적 중 · 마감 임박
 * - 하단: 실행 상태 · 판정 기준
 *
 * 건수는 **도착 화면의 기본 보기가 보이는 건수**만 그린다(목록 API `total` 또는 같은 정의의
 * `GET /api/workload` 키). 그런 값이 없는 항목은 건수를 그리지 않는다.
 * 활성 항목은 주소 하나당 정확히 하나다(`resolveActiveItemId`).
 *
 * 2026-11-19 최종 시안(`docs/1119_kstyle-shell/mockups/`): 묶음·항목·순서·건수 출처는 그대로 두고
 * 모양만 바꿨다. 사이드바는 바탕(frame) 위에 면 없이 228px로 놓이고, 행 36px·글자 14px·아이콘 16px,
 * 활성은 채움 + 굵은 본문색 + 먹색 알약 건수다. `리스트` 묶음은 색 점·아이콘 없이 들여쓴다.
 * 맨 아래 담당자 칸은 이 브라우저에 기억된 담당자 이름(`bidops.actorName`, 화면들의 담당자 입력이
 * 같이 쓰는 값)을 보이고 고칠 수 있다 — 감사 표식이며 로그인이 아니다.
 */
type IconName =
  | "home"
  | "plan"
  | "doc"
  | "opp"
  | "decision"
  | "shield"
  | "activity"
  | "gear"
  | "external";

/** 건수 출처. workload 키이거나 목록 기본 보기의 total이다. */
type CountSource = { kind: "workload"; key: WorkloadKey } | { kind: "order-plan-default" } | { kind: "pre-spec-default" };

interface NavItem {
  id: string;
  label: string;
  /** 이동할 주소(검색어 포함 가능). */
  path: string;
  icon?: IconName;
  /** 리스트 항목의 색 점. 상태를 색 점만으로 말하지 않으며 식별용이다. */
  dot?: "accent" | "teal" | "warning" | "error";
  /** 화면 metadata의 `navPath`와 맞추는 값. 없으면 `path`의 pathname이다. */
  navPath?: string;
  /** metadata가 없는 주소에서 이 항목이 활성이 되는 옛 경로. */
  absorbs?: string[];
  count?: CountSource;
}

interface NavGroup {
  label: string | null;
  items: NavItem[];
}

const groups: NavGroup[] = [
  {
    label: null,
    items: [
      // 대시보드는 목록이 아니라 여러 업무의 요약이므로 건수를 그리지 않는다.
      { id: "dashboard", label: "대시보드", path: "/", icon: "home" },
    ],
  },
  {
    label: "레코드",
    items: [
      // 건수 = 발주계획 기본 보기 `관련`(모델 판단 관련 AND 추적 미선택)의 건수.
      { id: "order-plans", label: "발주계획", path: "/order-plans", icon: "plan", count: { kind: "order-plan-default" } },
      // 건수 = 사전규격 기본 보기 `검토할 항목`(마감 전·미확인, SW사업대상)의 건수.
      { id: "pre-specs", label: "사전규격", path: "/pre-specs", icon: "doc", count: { kind: "pre-spec-default" } },
      // 건수 = 사업기회 기본 구역 `조치 필요`(workload `tracking_action_required`가 같은 식으로 센다).
      // `/judgments/:id`는 입찰공고 상세로 남아 사업기회 아래에서 열린다. 판정 대기열(`/queue`·`/reviews`·
      // `/deadlines`)은 2026-11-19에 흡수 목록에서 뺐다 — C-1 공고 판정을 다시 돌리지 않는다.
      { id: "opportunities", label: "사업기회", path: "/opportunities", icon: "opp", absorbs: ["/judgments"], count: { kind: "workload", key: "tracking_action_required" } },
      // 기본 보기 `검토 대상`은 목록 전체를 받아야 셀 수 있어 사이드바에서는 그리지 않는다.
      { id: "go-no-go", label: "최종 Go/No-Go", path: "/go-no-go", icon: "decision" },
      // 회사 근거(RL-00)는 읽기 전용 `/company`다. 건수는 기본 묶음 `확인 필요`의 건수다.
      { id: "company", label: "회사 근거", path: "/company", icon: "shield", absorbs: ["/companies"], count: { kind: "workload", key: "company_attention" } },
    ],
  },
  {
    label: "리스트",
    items: [
      // 건수는 가장 최근 브리핑의 반응 대기 추천 수다(`briefing_pending`) — 기본 탭 `반응 대기`.
      { id: "briefing", label: "오늘의 브리핑", path: "/briefing", dot: "accent", count: { kind: "workload", key: "briefing_pending" } },
      // 사업기회의 `추적 중` 구역. 이름은 그 보기 탭의 이름이다.
      { id: "tracking", label: "추적 중", path: "/opportunities?section=추적 중", navPath: "/opportunities?section=추적 중", dot: "teal" },
      // 사업기회의 7일 이내 마감 보기. 건수는 같은 조건의 workload `tracking_deadline_imminent`.
      { id: "deadline", label: "마감 임박", path: "/opportunities?section=전체&deadline_within_days=7&sort=deadline", navPath: "/opportunities?deadline_within_days", dot: "error", count: { kind: "workload", key: "tracking_deadline_imminent" } },
    ],
  },
];

const footerItems: NavItem[] = [
  // 운영 화면(실행 상태·회차·첨부·상시 운영·감사)은 한 화면의 탭이다.
  { id: "run-status", label: "실행 상태", path: "/run-status", icon: "activity", absorbs: ["/runs", "/attachments", "/operations", "/audit"] },
  // 판정 기준(회사 프로필·판정 정책·품질 게이트·검증 지표·발주계획 판정 기준)도 한 화면의 탭이다.
  { id: "criteria", label: "판정 기준", path: "/criteria", icon: "gear", absorbs: ["/profile", "/policies", "/quality-gates", "/metrics", "/order-plan-policies"] },
];

function NavIcon({ name }: { name: IconName }) {
  const common = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  switch (name) {
    case "home":
      return <svg {...common}><path d="M3 11 12 4l9 7" /><path d="M5 10v10h14V10" /></svg>;
    case "plan":
      return <svg {...common}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></svg>;
    case "doc":
      return <svg {...common}><path d="M4 4h12l4 4v12H4z" /><path d="M8 12h8M8 16h8" /></svg>;
    case "opp":
      return <svg {...common}><path d="M3 12h4l3-7 4 14 3-7h4" /></svg>;
    case "decision":
      return <svg {...common}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m8 12 3 3 5-6" /></svg>;
    case "shield":
      return <svg {...common}><path d="M12 3 4 7v5c0 5 3.5 8.5 8 9 4.5-.5 8-4 8-9V7z" /><path d="m9 12 2 2 4-4" /></svg>;
    case "activity":
      return <svg {...common}><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>;
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
 * 활성 항목을 **하나만** 고른다. 화면 metadata의 `activeNavPath`가 먼저이고, 같은 화면을 여는
 * 항목(사업기회·추적 중·마감 임박)은 목록 주소의 검색어로만 가른다 — 레코드·상세·Go/No-Go
 * 같은 다른 화면은 자기 항목을 갖는다. metadata가 없는 주소만 경로·흡수 목록으로 돌아간다.
 */
export function resolveActiveItemId(items: readonly NavItem[], activeNavPath: string | null, pathname: string, search: string): string | null {
  if (activeNavPath === "/opportunities" && pathname === "/opportunities") {
    const params = new URLSearchParams(search);
    if (params.has("deadline_within_days")) return "deadline";
    if (params.get("section") === "추적 중") return "tracking";
    return "opportunities";
  }
  const navOf = (item: NavItem) => item.navPath ?? pathnameOf(item.path);
  const target = activeNavPath ?? pathname;
  const exact = items.find((item) => navOf(item) === target);
  if (exact) return exact.id;
  const byPrefix = items.find((item) => navOf(item) !== "/" && isCurrentPath(target, navOf(item)));
  if (byPrefix) return byPrefix.id;
  const absorbed = items.find((item) => (item.absorbs ?? []).some((path) => isCurrentPath(target, path) || isCurrentPath(pathname, path)));
  return absorbed?.id ?? null;
}

/**
 * 가상회사 데모 메뉴(`GET /api/demo-config`가 enabled일 때만). 회사가 정해진 주소에서만
 * 그 회사의 화면 항목을 보이며, 회사를 몰래 고르지 않는다(`docs/work/demo-contract.md` §1).
 */
function demoGroup(companyId: string | null): NavGroup {
  const items: NavItem[] = [{ id: "demo-companies", label: "회사 선택", path: "/companies", icon: "plan" }];
  if (companyId) {
    items.push(
      { id: "demo-pre-specs", label: "회사 사전규격", path: `/companies/${companyId}/pre-specs`, icon: "doc" },
      { id: "demo-profile", label: "회사 프로필", path: `/companies/${companyId}/profile`, icon: "shield" },
    );
  }
  return { label: "가상회사 데모", items };
}

/** 법인 표기(`㈜`·`(주)`·`주식회사`)를 뗀 이름. 이름이 없으면 제품 이름이다. */
function workspaceIdentity(companyName: string | null): { name: string } {
  const short = (companyName ?? "").replace(/^(?:㈜|\(주\)|주식회사)\s*/u, "").replace(/\s*(?:㈜|\(주\)|주식회사)$/u, "").trim();
  return { name: short || "BidOps" };
}

export interface SidebarDemoNav {
  /** 주소에서 읽은 현재 회사. 회사가 정해지지 않은 주소면 `null`이다. */
  companyId: string | null;
}

export function Sidebar({ activeNavPath, runSearch, demoNav = null }: { activeNavPath: string | null; runSearch: string; demoNav?: SidebarDemoNav | null }) {
  const { pathname, search } = useLocation();
  const workload = useQuery({ queryKey: ["workload"], queryFn: () => api.getWorkload(), staleTime: 60_000 });
  // 목록 기본 보기의 건수는 그 목록 API의 total이다. 대시보드 타일과 같은 query key를 쓴다.
  const orderPlanDefault = useQuery(orderPlanViewTotalQuery("relevant"));
  const preSpecDefault = useQuery(preSpecDefaultViewTotalQuery());
  const workloadCounts = new Map<WorkloadKey, number>();
  for (const item of workload.data?.items ?? []) {
    if (typeof item.count === "number") workloadCounts.set(item.key, item.count);
  }
  /**
   * 건수(기본 보기의 건수). 0이면 숫자를 그리지 않는다(최종 시안). 불러오지 못했으면 0과 다른 모양(`–`)으로
   * 그려 "없음"과 "모름"을 섞지 않는다. 값이 없는 키(브리핑이 아직 없음 등)는 그리지 않는다.
   */
  const countOf = (source: CountSource | undefined): number | "error" | null => {
    if (!source) return null;
    if (source.kind === "workload") {
      if (workload.isError) return "error";
      return workloadCounts.get(source.key) ?? null;
    }
    const query = source.kind === "order-plan-default" ? orderPlanDefault : preSpecDefault;
    if (query.isError) return "error";
    return typeof query.data === "number" ? query.data : null;
  };
  // 워크스페이스 이름은 `GET /api/company`가 준다. 읽지 못하면 이름을 지어내지 않고
  // 제품 이름을 둔다(회사 화면이 같은 key로 오류를 설명한다).
  const company = useQuery({ queryKey: companyContextQueryKey, queryFn: ({ signal }) => getCompanyContext({ signal }), retry: false, staleTime: 60_000 });
  const workspace = workspaceIdentity(company.data?.company.name ?? null);
  const visibleGroups = demoNav ? [...groups, demoGroup(demoNav.companyId)] : groups;
  const allItems = [...visibleGroups.flatMap((group) => group.items), ...footerItems];
  const activeId = resolveActiveItemId(allItems, activeNavPath, pathname, search);
  return (
    <aside aria-label="주 메뉴" className="sidebar" data-shell-region="sidebar">
      {/* 워크스페이스 줄(시안: 머리글자 아이콘 + 회사명). 로그인·워크스페이스 전환이
          없으므로 링크는 브리핑으로 간다. */}
      <Link aria-label={`${workspace.name} BidOps 오늘의 브리핑으로 이동`} className="sidebar-brand" to={{ pathname: "/briefing", search: runSearchFor("/briefing", runSearch) }}>
        {/* 시안: 제품 이름(굵게) + 회사 이름(작게). 회사 이름을 모르면 제품 이름 하나만 둔다. */}
        {workspace.name !== "BidOps" ? <span className="sidebar-brand-product">BidOps</span> : null}
        <strong>{workspace.name}</strong>
      </Link>
      <nav aria-label="주 메뉴" className="sidebar-nav">
        {visibleGroups.map((group, index) => (
          <div className="sidebar-group" key={group.label ?? `quick-${index}`}>
            {group.label ? <div className="sidebar-group-label">{group.label}</div> : null}
            <div className="sidebar-items">
              {group.items.map((item) => (
                <NavEntry
                  active={item.id === activeId}
                  count={countOf(item.count)}
                  item={item}
                  key={item.id}
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
            active={item.id === activeId}
            count={null}
            item={item}
            key={item.id}
            runSearch={runSearch}
          />
        ))}
        <SidebarActor />
      </div>
    </aside>
  );
}

function NavEntry({ item, active, count, runSearch }: { item: NavItem; active: boolean; count: number | "error" | null; runSearch: string }) {
  const body = (
    <>
      {/* 리스트 묶음(색 점 항목)은 시안대로 아이콘·점 없이 들여쓴다. 점의 색은 식별용이었고
          항목 이름이 같은 말을 하므로 잃는 정보가 없다. */}
      {item.icon ? <NavIcon name={item.icon} /> : null}
      <span className="sidebar-item-label">{item.label}</span>
      {/* 건수는 보조 표시다. 링크의 접근 가능한 이름은 항목 이름 하나로 두고(테스트·
          보조 기술이 "알림 2"가 아니라 "알림"으로 읽는다) 건수는 title로 함께 준다. */}
      {count === "error" ? (
        <span aria-hidden="true" className="sidebar-item-count is-unknown">–</span>
      ) : count !== null && count > 0 ? (
        <span aria-hidden="true" className={`sidebar-item-count${active ? " is-active" : ""}`}>{count}</span>
      ) : null}
    </>
  );
  const pathname = pathnameOf(item.path);
  const query = item.path.includes("?") ? item.path.slice(item.path.indexOf("?")) : "";
  const runQuery = runSearchFor(pathname, runSearch);
  const searchValue = query && runQuery ? `${query}&${runQuery.slice(1)}` : query || runQuery;
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={`sidebar-item${active ? " is-active" : ""}${item.dot ? " is-list" : ""}`}
      title={count === "error" ? `${item.label} · 건수를 불러오지 못했어요` : count !== null && count > 0 ? `${item.label} ${count}건` : undefined}
      to={{ pathname, search: searchValue }}
    >
      {body}
    </Link>
  );
}

/**
 * 사이드바 맨 아래 담당자 칸(최종 시안). 이 브라우저에 기억된 담당자 이름을 보이고, 누르면 그 자리에서
 * 고친다. 값은 화면들의 담당자 입력(`ActorField`)과 같은 저장소다. 이름은 결정 기록에 남는 표식일 뿐
 * 로그인·신원 인증·권한이 아니며, 저장 요청마다 화면이 다시 확인한다.
 */
function SidebarActor() {
  const remembered = useRememberedActorName();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(remembered);
  const panelId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) setDraft(remembered);
  }, [open, remembered]);
  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };
  return (
    <div className="sidebar-actor">
      {open ? (
        <div
          className="sidebar-actor-panel"
          id={panelId}
          onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); close(); } }}
        >
          <ActorField
            autoFocus
            description="반응·추적 결정 기록에 남는 이름이에요. 로그인이나 신원 인증이 아니에요."
            id="sidebar-actor-input"
            label="담당자 이름"
            onChange={setDraft}
            showRememberNote={false}
            value={draft}
          />
          <button className="sidebar-actor-done" onClick={close} type="button">닫기</button>
        </div>
      ) : null}
      <button
        aria-controls={open ? panelId : undefined}
        aria-expanded={open}
        className="sidebar-actor-trigger"
        onClick={() => setOpen((value) => !value)}
        ref={triggerRef}
        type="button"
      >
        <span>담당자</span>
        <strong>{remembered.trim() || "미입력"}</strong>
        <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} viewBox="0 0 24 24"><path d="m6 9 6 6 6-6" /></svg>
      </button>
    </div>
  );
}
