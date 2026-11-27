import { useEffect, useId, useRef, useState } from "react";
import { Layers } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../lib/api";
import { orderPlanViewTotalQuery, preSpecDefaultViewTotalQuery } from "../../lib/defaultViewCounts";
import type { WorkloadKey } from "../../lib/types";
import { ActorField, OPEN_ACTOR_EVENT, useRememberedActorName } from "../common/ActorField";
import { runSearchFor } from "./route-meta";

/** 실무자는 오늘 할 일에서 시작해 탐색과 사업기회로 이동한다. */
type IconName =
  | "home"
  | "plan"
  | "doc"
  | "opp"
  | "shield"
  | "activity"
  | "gear"
  | "decision"
  | "external";

/** 건수 출처. workload 키이거나 목록 기본 보기의 total이다. */
type CountSource = { kind: "workload"; key: WorkloadKey } | { kind: "order-plan-default" } | { kind: "pre-spec-default" };

interface NavItem {
  id: string;
  label: string;
  /** 이동할 화면 주소. */
  path: string;
  icon?: IconName;
  nested?: boolean;
  /** metadata가 없는 주소에서 이 항목이 활성이 되는 옛 경로. */
  absorbs?: string[];
  count?: CountSource;
}

interface NavGroup {
  label: string | null;
  items: NavItem[];
}

const groups: NavGroup[] = [
  { label: null, items: [{ id: "dashboard", label: "오늘 할 일", path: "/", icon: "home" }] },
  {
    label: "탐색",
    items: [
      { id: "order-plans", label: "발주계획", path: "/order-plans", icon: "plan", count: { kind: "order-plan-default" } },
      { id: "pre-specs", label: "사전규격", path: "/pre-specs", icon: "doc", count: { kind: "pre-spec-default" } },
    ],
  },
  {
    label: null,
    items: [
      { id: "opportunities", label: "사업기회", path: "/opportunities", icon: "opp", absorbs: ["/judgments"], count: { kind: "workload", key: "tracking_action_required" } },
      { id: "go-no-go", label: "최종 Go/No-Go", path: "/go-no-go", icon: "decision", nested: true },
    ],
  },
];

const managementItems: NavItem[] = [
  { id: "company", label: "회사 근거", path: "/company", icon: "shield", absorbs: ["/companies"], count: { kind: "workload", key: "company_attention" } },
  { id: "criteria", label: "판정 기준", path: "/criteria", icon: "gear", absorbs: ["/profile", "/policies", "/quality-gates", "/metrics", "/order-plan-policies"] },
  { id: "run-status", label: "실행 상태", path: "/run-status", icon: "activity", absorbs: ["/runs", "/attachments", "/operations", "/audit"] },
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
    case "shield":
      return <svg {...common}><path d="M12 3 4 7v5c0 5 3.5 8.5 8 9 4.5-.5 8-4 8-9V7z" /><path d="m9 12 2 2 4-4" /></svg>;
    case "activity":
      return <svg {...common}><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>;
    case "gear":
      return <svg {...common}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>;
    case "decision":
      // 상단 바의 같은 화면 아이콘(lucide ClipboardCheck)과 같은 모양.
      return <svg {...common}><rect x="8" y="2" width="8" height="4" rx="1" /><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><path d="m9 14 2 2 4-4" /></svg>;
    case "external":
      return <svg {...common}><path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" /></svg>;
  }
}

function isCurrentPath(pathname: string, path: string): boolean {
  return path === "/" ? pathname === "/" : pathname === path || pathname.startsWith(`${path}/`);
}

/** 데이터 보기의 URL 조건과 관계없이 소속 화면 하나를 활성화한다. */
function resolveActiveItemId(items: readonly NavItem[], activeNavPath: string | null, pathname: string): string | null {
  const navOf = (item: NavItem) => item.path;
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

export interface SidebarDemoNav {
  /** 주소에서 읽은 현재 회사. 회사가 정해지지 않은 주소면 `null`이다. */
  companyId: string | null;
}

export function Sidebar({ activeNavPath, runSearch, demoNav = null }: { activeNavPath: string | null; runSearch: string; demoNav?: SidebarDemoNav | null }) {
  const { pathname, search } = useLocation();
  const workload = useQuery({ queryKey: ["workload"], queryFn: () => api.getWorkload(), staleTime: 60_000 });
  // 목록 기본 보기의 건수는 그 목록 API의 total이다. 대시보드 타일과 같은 query key를 쓴다.
  const params = new URLSearchParams(search);
  // The unscoped workspace supplies the same count in its first page response.
  const orderPlanDefault = useQuery({
    ...orderPlanViewTotalQuery("relevant"),
    enabled: pathname !== "/order-plans" || Boolean(params.get("source_run_id") || params.get("first_observed_from")),
  });
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
  const visibleGroups = [
    ...groups,
    ...(demoNav ? [demoGroup(demoNav.companyId)] : []),
    { label: "관리", items: managementItems },
  ];
  const allItems = visibleGroups.flatMap((group) => group.items);
  const activeId = resolveActiveItemId(allItems, activeNavPath, pathname);
  return (
    <aside aria-label="주 메뉴" className="sidebar" data-shell-region="sidebar">
      <Link aria-label="BidOps 오늘 할 일로 이동" className="sidebar-brand" to="/">
        {/* 제품 이름만 둔다(2026-11-25 사용자 요청: 회사 이름 표기 제거). */}
        <span className="sidebar-brand-mark" aria-hidden="true"><Layers size={15} /></span>
        <span className="sidebar-brand-product">BidOps</span>
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
        <SidebarActor />
      </div>
    </aside>
  );
}

function NavEntry({ item, active, count, runSearch }: { item: NavItem; active: boolean; count: number | "error" | null; runSearch: string }) {
  const body = (
    <>
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
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={`sidebar-item${active ? " is-active" : ""}${item.nested ? " is-nested" : ""}`}
      title={count === "error" ? `${item.label} · 건수를 불러오지 못했어요` : count !== null && count > 0 ? `${item.label} ${count}건` : undefined}
      to={{ pathname: item.path, search: runSearchFor(item.path, runSearch) }}
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
  // 본문 화면이 이름을 요구할 때 이 칸을 연다(`requestActorInput`). 열리면 입력 칸이 초점을 받는다.
  useEffect(() => {
    const onOpen = () => {
      setOpen(true);
      // 이미 열려 있으면 autoFocus가 다시 돌지 않으므로 다음 프레임에 초점을 직접 옮긴다.
      window.requestAnimationFrame(() => document.getElementById("sidebar-actor-input")?.focus());
    };
    window.addEventListener(OPEN_ACTOR_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_ACTOR_EVENT, onOpen);
  }, []);
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
