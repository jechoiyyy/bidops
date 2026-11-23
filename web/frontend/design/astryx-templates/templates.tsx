/*
 * 화면 틀 P0(셸)·P1(목록|미리보기 작업 화면). 발주계획·사전규격·사업기회·최종 Go/No-Go·브리핑과
 * 관리 화면(판정 기준·실행 상태·회사 근거)이 모두 Workspace 하나를 쓴다.
 * 안(유지안·시안 1~3)에 따라 달라지는 것은 이 파일 안의 배치뿐이고, 화면 파일은 안을 모른다.
 */
import { useMemo, useState, type ReactNode } from "react";
import { Activity, ArrowUpRight, CalendarDays, ChevronDown, ExternalLink, FileText, Home, Layers, ListFilter, PanelRight, Search, Settings, ShieldCheck } from "lucide-react";
import { BreadcrumbItem, Breadcrumbs } from "@astryxdesign/core/Breadcrumbs";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Icon } from "@astryxdesign/core/Icon";
import { List, ListItem } from "@astryxdesign/core/List";
import { MultiSelector } from "@astryxdesign/core/MultiSelector";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { Pagination } from "@astryxdesign/core/Pagination";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Heading, Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Token } from "@astryxdesign/core/Token";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import {
  DeadlineText, DecisionBar, Empty, Facts, Flow, KeyFigures, OPTIONAL_COLUMNS, SectionBlock, Shortcuts, StatusMark, Tag, useMode, useVariant,
  type ViewPrefs,
  type Action, type Deadline, type Decision, type Fact, type FlowStep, type Mark, type SectionModel, type Shortcut,
} from "./kit";

/* ── P0 셸 ─────────────────────────────────────────────────────────────── */

export interface Crumb { label: string; page?: string }

const NAV: { group: string | null; items: { page: string; label: string; icon: typeof Home; count?: string; sub?: boolean }[] }[] = [
  { group: null, items: [{ page: "dashboard", label: "오늘 할 일", icon: Home }] },
  { group: "탐색", items: [
    { page: "order-plans", label: "발주계획", icon: CalendarDays, count: "829" },
    { page: "pre-specs", label: "사전규격", icon: FileText, count: "88" },
  ] },
  { group: null, items: [
    { page: "opportunities", label: "사업기회", icon: Activity },
    { page: "go-no-go", label: "최종 Go/No-Go", icon: Activity, sub: true },
  ] },
  { group: "관리", items: [
    { page: "company", label: "회사 근거", icon: ShieldCheck },
    { page: "criteria", label: "판정 기준", icon: Settings },
    { page: "run-status", label: "실행 상태", icon: Activity },
  ] },
];

/** T14 보기 설정 — 내 화면 맞춤 방안에서 위치 줄 오른쪽에 놓는 조절 도구. 화면마다 따로 만들지 않는다. */
function ViewSettings({ list }: { list: boolean }) {
  const { prefs, setPrefs } = useMode();
  return (
    <div className="mk-viewset" role="group" aria-label="보기 설정">
      <SegmentedControl label="글자 크기" value={prefs.text} onChange={(next) => setPrefs({ text: next as ViewPrefs["text"] })} size="sm">
        <SegmentedControlItem value="normal" label="글자 보통" />
        <SegmentedControlItem value="large" label="크게" />
      </SegmentedControl>
      {list ? (
        <>
          <SegmentedControl label="행 밀도" value={prefs.density} onChange={(next) => setPrefs({ density: next as ViewPrefs["density"] })} size="sm">
            <SegmentedControlItem value="compact" label="촘촘" />
            <SegmentedControlItem value="balanced" label="보통" />
            <SegmentedControlItem value="spacious" label="넓게" />
          </SegmentedControl>
          <MultiSelector label="표시할 열" isLabelHidden size="sm" variant="ghost" width={132} placeholder="열 없음"
            options={OPTIONAL_COLUMNS} value={prefs.columns} onChange={(next) => setPrefs({ columns: next })}
            formatValue={(items) => `열 ${items.length}개`} />
          <Button label={prefs.inspector ? "미리보기 접기" : "미리보기 펴기"} variant="ghost" size="sm" icon={<PanelRight aria-hidden="true" />}
            onClick={() => setPrefs({ inspector: !prefs.inspector })} />
        </>
      ) : null}
    </div>
  );
}

export function Shell({ navPage, title, crumbs, actions, listPage = false, onNavigate, children }: {
  navPage: string; title: string; crumbs?: Crumb[]; actions?: ReactNode; listPage?: boolean; onNavigate: (page: string) => void; children: ReactNode;
}) {
  const { mode } = useMode();
  return (
    <div className="mk-app">
      <aside className="mk-side" aria-label="주 메뉴">
        <div className="mk-brand"><span className="mk-brand-mark" aria-hidden="true"><Layers /></span>BidOps</div>
        <nav className="mk-nav">
          {NAV.map((group, index) => (
            <div className="mk-nav-group" key={group.group ?? `g${index}`}>
              {group.group ? <div className="mk-nav-label">{group.group}</div> : null}
              {group.items.map((item) => (
                <button
                  key={item.page} type="button" className="mk-nav-item" data-sub={item.sub ? "true" : "false"}
                  aria-current={navPage === item.page ? "page" : undefined} onClick={() => onNavigate(item.page)}
                >
                  {item.sub ? null : <item.icon aria-hidden="true" />}
                  <span>{item.label}</span>
                  {item.count ? <span className="mk-nav-count">{item.count}</span> : null}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="mk-side-foot">
          <span className="mk-nav-item"><ExternalLink aria-hidden="true" /><span>나라장터 바로가기</span></span>
          <span className="mk-actor"><Text type="supporting" color="secondary">담당자</Text><Text type="label" weight="semibold">김담당</Text><ChevronDown aria-hidden="true" /></span>
        </div>
      </aside>
      <main className="mk-panel">
        <header className="mk-loc">
          <div className="mk-loc-start">
            {crumbs ? (
              <Breadcrumbs separator="›">
                {crumbs.map((crumb) => (
                  <BreadcrumbItem key={crumb.label} href={crumb.page ? "#" : undefined} onClick={crumb.page ? (event) => { event.preventDefault(); onNavigate(crumb.page!); } : undefined}>
                    {crumb.label}
                  </BreadcrumbItem>
                ))}
              </Breadcrumbs>
            ) : <Heading level={1}>{title}</Heading>}
          </div>
          <div className="mk-loc-end">
            <span className="mk-collect"><StatusMark mark={{ label: "수집 완료", tone: "success" }} /><Text type="supporting" color="secondary">기준일 11-22</Text></span>
            {mode === "z" ? <ViewSettings list={listPage} /> : null}
            {actions}
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}

/* ── P1 작업 화면 ──────────────────────────────────────────────────────── */

export interface View { id: string; label: string; count?: string }
export interface Row extends Record<string, unknown> {
  id: string; title: string; agency: string; meta: string;
  budget?: string; mark?: Mark; deadline?: Deadline; group?: string; note?: string;
}
export interface Preview {
  eyebrow: string; title: string; marks: Mark[]; tags?: string[]; idLine?: string; link?: string;
  /** flow.current — 운영 화면에 이미 있는 단계 표시인가. 유지안은 있는 것만 그린다. */
  facts: Fact[]; flow?: { steps: FlowStep[]; active: number; current?: boolean };
  sections: SectionModel[]; decision?: Decision;
}
export interface WorkspaceCfg {
  kind: "review" | "admin";
  views: View[]; view: string;
  subViews?: View[]; subView?: string;
  sideNav?: { title: string; items: { label: string; active?: boolean }[] }[];
  strip?: Fact[];
  filters?: string[];
  searchLabel?: string;
  listTitle: string; listNote?: string;
  mainHeader: string; statusHeader?: string; deadlineHeader?: string;
  bulk?: Action[];
  rows: Row[]; total: number; pageSize: number;
  groups?: string[];
  listFoot?: string;
  emptyList?: { title: string; description: string; action?: string };
  preview: (row: Row | null) => Preview | null;
  previewTabs?: string[];
  position?: boolean;
  /** 목록 키보드 조작. 유지안은 지금처럼 안내를 그리지 않는다. */
  shortcuts?: Shortcut[];
}

/** T1 보기 줄 — 보기 탭은 왼쪽, 필터·검색은 오른쪽. */
export function ViewBar({ views, view, filters, searchLabel, onView }: {
  views: View[]; view: string; filters?: string[]; searchLabel?: string; onView?: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  return (
    <div className="mk-viewbar">
      <TabList value={view} onChange={(next) => onView?.(next)} size="md">
        {views.map((item) => (
          <Tab key={item.id} value={item.id} label={item.label}
            endContent={item.count ? <span className="mk-tab-count">{item.count}</span> : undefined} />
        ))}
      </TabList>
      {searchLabel ? (
        <div className="mk-viewbar-end">
          {filters?.map((filter) => <Token key={filter} size="sm" color="gray" label={filter} onRemove={() => undefined} />)}
          <Button label="필터" variant="secondary" size="sm" icon={<ListFilter aria-hidden="true" />} />
          <TextInput label={searchLabel} isLabelHidden value={query} onChange={setQuery} placeholder={searchLabel} size="sm" startIcon={Search} width={220} />
        </div>
      ) : null}
    </div>
  );
}

/** T13 요약 줄 — 관리 화면 위의 현재 조건. 유지안·시안 1·3은 한 줄, 시안 2는 칸. */
function SummaryStrip({ facts, tiles }: { facts: Fact[]; tiles: boolean }) {
  return (
    <div className="mk-strip" data-tiles={tiles ? "true" : "false"}>
      {facts.map((fact) => (
        <div className="mk-strip-item" key={fact.label}>
          <Text type="supporting" color="secondary">{fact.label}</Text>
          <span className="mk-strip-value">{fact.value}</span>
        </div>
      ))}
    </div>
  );
}

/** T4 목록 행 — 사업명·기관은 왼쪽, 상태·마감은 고정 열. 네 목록이 같은 격자를 쓴다. */
function RowGrid({ row, active, checked, hasCheck, hasDeadline, onActivate, onCheck }: {
  row: Row; active: boolean; checked: boolean; hasCheck: boolean; hasDeadline: boolean;
  onActivate: () => void; onCheck: (next: boolean) => void;
}) {
  return (
    <div className="mk-row" data-active={active ? "true" : "false"} data-check={hasCheck ? "true" : "false"} data-deadline={hasDeadline ? "true" : "false"} onClick={onActivate}>
      {hasCheck ? (
        <span className="mk-row-check" onClick={(event) => event.stopPropagation()}>
          <CheckboxInput label={`${row.title} 선택`} isLabelHidden value={checked} onChange={onCheck} size="sm" />
        </span>
      ) : null}
      <button type="button" className="mk-row-main" aria-current={active ? "true" : undefined}>
        <span className="mk-row-title">{row.title}</span>
        <span className="mk-row-meta">{row.meta}</span>
        {row.note ? <span className="mk-row-meta">{row.note}</span> : null}
      </button>
      <span className="mk-row-status">{row.mark ? <StatusMark mark={row.mark} /> : null}</span>
      {hasDeadline ? <span className="mk-row-deadline">{row.deadline ? <DeadlineText deadline={row.deadline} /> : null}</span> : null}
    </div>
  );
}

function PreviewPane({ preview, tabs, position, total, index }: {
  preview: Preview | null; tabs?: string[]; position?: boolean; total: number; index: number;
}) {
  const variant = useVariant();
  const { mode } = useMode();
  const [tab, setTab] = useState(tabs?.[0] ?? "");
  if (!preview) {
    return (
      <div className="mk-preview">
        <div className="mk-pane-head"><span className="mk-pane-title"><PanelRight aria-hidden="true" />미리보기</span></div>
        <Empty title="고른 항목이 없어요" description="목록에서 항목을 고르면 여기에서 내용을 볼 수 있어요." />
      </div>
    );
  }
  const factColumns = variant === "c" ? 4 : 2;
  return (
    <div className="mk-preview">
      <div className="mk-pane-head">
        <span className="mk-pane-title"><PanelRight aria-hidden="true" />미리보기</span>
        {position ? <Text type="supporting" color="secondary" hasTabularNumbers>{index + 1} / {total.toLocaleString("ko-KR")}</Text> : null}
      </div>
      <div className="mk-preview-body">
        <div className="mk-preview-head">
          <Text type="supporting" color="secondary" display="block">{preview.eyebrow}</Text>
          <Heading level={2}>{preview.title}</Heading>
          <div className="mk-preview-marks">
            {preview.marks.map((mark) => <StatusMark key={mark.label} mark={mark} />)}
            {preview.tags?.map((tag) => <Tag key={tag} label={tag} />)}
          </div>
          {preview.idLine ? <Text type="supporting" color="secondary" display="block">{preview.idLine}</Text> : null}
        </div>
        {variant === "b" && preview.flow ? <div className="mk-preview-flow"><Flow steps={preview.flow.steps} active={preview.flow.active} /></div> : null}
        {variant === "c" && tabs ? (
          <TabList value={tab} onChange={setTab} size="sm" hasDivider>
            {tabs.map((item) => <Tab key={item} value={item} label={item} />)}
          </TabList>
        ) : null}
        {variant === "a" && mode === "y" ? (
          <>
            <KeyFigures facts={preview.facts.filter((fact) => fact.strong)} />
            <Facts facts={preview.facts.filter((fact) => !fact.strong)} side />
          </>
        ) : <Facts facts={preview.facts} columns={factColumns} side={variant === "a"} />}
        {variant !== "b" && preview.flow?.current ? (
          <SectionBlock section={{ id: "flow", title: "사업 흐름", body: <Flow steps={preview.flow.steps} active={preview.flow.active} vertical={variant === "a"} /> }} />
        ) : null}
        {preview.sections.map((section) => <SectionBlock key={section.id} section={section} />)}
        {preview.link ? <a className="mk-link" href="#">{preview.link}<ArrowUpRight aria-hidden="true" /></a> : null}
      </div>
      {preview.decision ? <DecisionBar decision={preview.decision} /> : null}
    </div>
  );
}

export function Workspace({ cfg }: { cfg: WorkspaceCfg }) {
  const variant = useVariant();
  const { mode, prefs } = useMode();
  const inspectorPanel = useResizable({ defaultSize: 420, minSizePx: 320, maxSizePx: 640 });
  const density = mode === "x" ? "balanced" : mode === "z" ? prefs.density : "compact";
  // 크게 보기·넓은 밀도에서는 긴 사업명을 자르지 않고 두 줄까지 보여 준다.
  const wrapTitle = mode === "x" || (mode === "z" && prefs.density !== "compact");
  const inspectorOpen = mode !== "z" || prefs.inspector;
  const mergeAgency = wrapTitle && cfg.kind !== "admin";
  const agencyShown = mode !== "z" || prefs.columns.includes("agency");
  const [activeId, setActiveId] = useState<string | null>(cfg.rows[0]?.id ?? null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(1);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const activeRow = cfg.rows.find((row) => row.id === activeId) ?? null;
  const activeIndex = Math.max(0, cfg.rows.findIndex((row) => row.id === activeId));
  const preview = cfg.preview(activeRow);
  const hasCheck = Boolean(cfg.bulk);
  const hasDeadline = Boolean(cfg.deadlineHeader);
  const admin = cfg.kind === "admin";
  const toggle = (id: string, next: boolean) => setChecked((prev) => {
    const copy = new Set(prev);
    if (next) copy.add(id); else copy.delete(id);
    return copy;
  });

  const groups = useMemo(() => {
    const order = cfg.groups ?? [];
    return order.map((label) => ({ label, rows: cfg.rows.filter((row) => row.group === label) })).filter((group) => group.rows.length > 0);
  }, [cfg.groups, cfg.rows]);

  const columns = useMemo<TableColumn<Row>[]>(() => {
    const list: TableColumn<Row>[] = [];
    if (hasCheck) {
      list.push({ key: "check", header: "", width: pixel(40), renderCell: (row) => (
        <CheckboxInput label={`${row.title} 선택`} isLabelHidden value={checked.has(row.id)} onChange={(next) => toggle(row.id, next)} size="sm" />
      ) });
    }
    list.push({ key: "title", header: mergeAgency && agencyShown ? cfg.mainHeader : cfg.mainHeader.split(" / ")[0], width: proportional(1), renderCell: (row) => (
      <button type="button" className="mk-cell-title" data-wrap={wrapTitle ? "true" : "false"} aria-current={row.id === activeId ? "true" : undefined} onClick={() => setActiveId(row.id)}>
        <span className="mk-cell-title-text">{row.title}</span>
        {mergeAgency && agencyShown ? <span className="mk-cell-sub">{row.agency}</span> : null}
      </button>
    ) });
    // 비례 열은 서로 비율을 지킨 채 최소 폭을 가지므로, 좁은 폭에서 넘치지 않게 사업명만 비례로 둔다.
    // 사업명을 두 줄로 보여 줄 때는 발주기관을 사업명 아래 줄로 내려 사업명 열 폭을 지킨다(1280px에서 사업명이 8자에서 잘리던 문제).
    if (!mergeAgency) list.push({ key: "agency", header: admin ? "구분" : "발주기관", width: pixel(admin ? 160 : 120) });
    if (!admin) list.push({ key: "budget", header: "예산", width: pixel(wrapTitle ? 116 : 96), align: "end" });
    if (cfg.statusHeader && cfg.rows.some((row) => row.mark)) list.push({ key: "mark", header: cfg.statusHeader, width: pixel(wrapTitle ? 128 : 112), renderCell: (row) => (row.mark ? <StatusMark mark={row.mark} /> : null) });
    if (hasDeadline) list.push({ key: "deadline", header: cfg.deadlineHeader!, width: pixel(wrapTitle || mode === "y" ? 108 : 96), align: mode === "y" ? "start" : "end", renderCell: (row) => (row.deadline ? <DeadlineText deadline={row.deadline} /> : null) });
    // 내 화면 맞춤: 사용자가 끈 열은 그리지 않는다.
    const shown = mode === "z" ? list.filter((column) => !OPTIONAL_COLUMNS.some((option) => option.value === column.key) || prefs.columns.includes(column.key)) : list;
    if (mode !== "y") return shown;
    // 훑기 길잡이: 우선순위를 정하는 마감·상태를 사업명 바로 옆에 둔다.
    const order = ["check", "title", "deadline", "mark", "agency", "budget"];
    return [...shown].sort((left, right) => order.indexOf(left.key) - order.indexOf(right.key));
  }, [activeId, admin, cfg.deadlineHeader, cfg.mainHeader, cfg.statusHeader, checked, hasCheck, hasDeadline, mode, prefs.columns, wrapTitle, mergeAgency, agencyShown]);

  const rowGrid = (row: Row) => (
    <RowGrid key={row.id} row={row} active={row.id === activeId} checked={checked.has(row.id)} hasCheck={hasCheck} hasDeadline={hasDeadline}
      onActivate={() => setActiveId(row.id)} onCheck={(next) => toggle(row.id, next)} />
  );

  let body: ReactNode;
  if (cfg.rows.length === 0 && cfg.emptyList) {
    body = <Empty title={cfg.emptyList.title} description={cfg.emptyList.description} action={cfg.emptyList.action} />;
  } else if (variant === "a") {
    body = <div className="mk-table"><Table data={cfg.rows} columns={columns} idKey="id" density={density} hasHover isStriped={mode === "y"} textOverflow={wrapTitle ? "wrap" : "truncate"} /></div>;
  } else if (variant === "b" && groups.length > 0) {
    body = groups.map((group) => {
      const closed = collapsed.has(group.label);
      return (
        <div className="mk-group" key={group.label}>
          <button type="button" className="mk-group-head" aria-expanded={!closed}
            onClick={() => setCollapsed((prev) => { const copy = new Set(prev); if (closed) copy.delete(group.label); else copy.add(group.label); return copy; })}>
            <ChevronDown aria-hidden="true" data-closed={closed ? "true" : "false"} />
            <span>{group.label}</span>
            <span className="mk-group-count">{group.rows.length}건</span>
          </button>
          {closed ? null : group.rows.map(rowGrid)}
        </div>
      );
    });
  } else if (variant === "c") {
    body = (
      <List density="compact" hasDividers>
        {cfg.rows.map((row) => (
          <ListItem key={row.id} label={row.title} description={row.meta} isSelected={row.id === activeId} onClick={() => setActiveId(row.id)}
            startContent={hasCheck ? <CheckboxInput label={`${row.title} 선택`} isLabelHidden value={checked.has(row.id)} onChange={(next) => toggle(row.id, next)} size="sm" /> : undefined}
            endContent={row.deadline ? <DeadlineText deadline={row.deadline} /> : row.mark ? <StatusMark mark={row.mark} /> : undefined} />
        ))}
      </List>
    );
  } else {
    body = cfg.rows.map(rowGrid);
  }

  const showTabs = !(variant === "a" && cfg.sideNav);
  return (
    <>
      {showTabs ? <ViewBar views={cfg.views} view={cfg.view} filters={variant === "a" ? cfg.filters : undefined} searchLabel={cfg.searchLabel} /> : null}
      <div className="mk-ws" data-kind={cfg.kind} data-side={!showTabs ? "true" : "false"}>
        {!showTabs && cfg.sideNav ? (
          <nav className="mk-sections" aria-label="기준 구역">
            {cfg.sideNav.map((section) => (
              <div key={section.title} className="mk-sections-group">
                <div className="mk-nav-label">{section.title}</div>
                {section.items.map((item) => <button type="button" key={item.label} className="mk-sections-item" aria-current={item.active ? "page" : undefined}>{item.label}</button>)}
              </div>
            ))}
          </nav>
        ) : null}
        <div className="mk-ws-main">
          {cfg.strip ? <SummaryStrip facts={cfg.strip} tiles={variant === "b"} /> : null}
          <div className="mk-split" data-inspector={inspectorOpen ? "open" : "closed"}
            style={mode === "z" && inspectorOpen ? { gridTemplateColumns: `minmax(0, 1fr) auto ${inspectorPanel.size}px` } : undefined}>
            <div className="mk-list">
              <div className="mk-pane-head">
                <span className="mk-pane-title">{cfg.listTitle}</span>
                {showTabs && cfg.subViews ? (
                  <SegmentedControl label="하위 보기" value={cfg.subView ?? cfg.subViews[0].id} onChange={() => undefined} size="sm">
                    {cfg.subViews.map((item) => <SegmentedControlItem key={item.id} value={item.id} label={item.count ? `${item.label} ${item.count}` : item.label} />)}
                  </SegmentedControl>
                ) : cfg.listNote ? <Text type="supporting" color="secondary">{cfg.listNote}</Text> : null}
              </div>
              {hasCheck ? (
                <Toolbar label="선택 도구" size="sm" gap={1} dividers={["bottom"]}
                  startContent={<>
                    <span className="mk-select-count">선택 {checked.size}건</span>
                    <Button label="전체 선택" variant="secondary" onClick={() => setChecked(new Set(cfg.rows.map((row) => row.id)))} />
                    <Button label="전체 해제" variant="ghost" isDisabled={checked.size === 0} onClick={() => setChecked(new Set())} />
                  </>}
                  endContent={variant === "c"
                    ? <Button label="선택 작업" variant="secondary" isDisabled={checked.size === 0} endContent={<Icon icon={ChevronDown} size="sm" />} />
                    : <>{cfg.bulk!.map((action) => <Button key={action.label} label={action.label} variant={action.kind ?? "secondary"} isDisabled={checked.size === 0} />)}</>}
                />
              ) : null}
              {variant === "k" || variant === "b" ? (
                <div className="mk-colhead" data-check={hasCheck ? "true" : "false"} data-deadline={hasDeadline ? "true" : "false"}>
                  {hasCheck ? <span /> : null}
                  <span>{cfg.mainHeader}</span>
                  <span>{cfg.statusHeader ?? ""}</span>
                  {hasDeadline ? <span className="mk-colhead-end">{cfg.deadlineHeader}</span> : null}
                </div>
              ) : null}
              <div className="mk-list-body">{body}</div>
              <div className="mk-list-foot">
                <span className="mk-list-foot-start">
                  <Text type="supporting" color="secondary" hasTabularNumbers>{cfg.listFoot ?? `전체 ${cfg.total.toLocaleString("ko-KR")}건`}</Text>
                  {variant !== "k" && cfg.shortcuts ? <Shortcuts items={cfg.shortcuts} /> : null}
                </span>
                {cfg.total > cfg.pageSize ? <Pagination page={page} onChange={setPage} totalItems={cfg.total} pageSize={cfg.pageSize} variant="count" size="sm" label="목록 페이지" /> : null}
              </div>
            </div>
            {mode === "z" && inspectorOpen ? <ResizeHandle direction="horizontal" isReversed hasDivider isAlwaysVisible resizable={inspectorPanel.props} label="미리보기 너비 조절" /> : null}
            {inspectorOpen ? <PreviewPane preview={preview} tabs={cfg.previewTabs} position={cfg.position} total={cfg.total} index={activeIndex} /> : null}
          </div>
        </div>
      </div>
    </>
  );
}
