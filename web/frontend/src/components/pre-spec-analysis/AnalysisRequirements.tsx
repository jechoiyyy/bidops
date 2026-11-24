import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { RecordTable, type RecordTableColumn } from "../common/RecordTable";
import { useRowKeyboardNavigation } from "../common/useRowKeyboardNavigation";
import type { WikiProject } from "../../lib/companyWikiApi";
import type { EngineAnalysis } from "../../lib/engineApi";
import type { PdfQuoteLocation } from "../../lib/pdfQuoteLocator";
import { citationLabel, knowledgeName, known, replaceAnalysisHash, requirementKey, type Requirement } from "./analysisPresentation";
import type { PageLink } from "./AnalysisSource";

const categories: Record<string, string> = {
  SFR: "기능", SER: "보안", PER: "성능", INR: "인터페이스", DAR: "데이터", TER: "테스트",
  QUR: "품질", COR: "제약사항", PMR: "프로젝트 관리", PSR: "프로젝트 지원", ECR: "장비 구성",
};
const fitNames = { GAP: "부족", UNKNOWN: "미확인", PARTIAL: "부분", FULL: "충족" };
const fitOrder = ["GAP", "UNKNOWN", "PARTIAL", "FULL"] as const;
type Filter = "all" | Requirement["fit"];

function category(fit: Requirement) {
  return fit.req_id.split("-")[0];
}

function period(project: WikiProject) {
  const start = known(project.period_start);
  const end = known(project.period_end);
  return start === "미확인" && end === "미확인" ? "기간 미확인" : `${start}~${end}`;
}

interface Props {
  fits: Requirement[];
  judged?: number;
  knowledge: EngineAnalysis["knowledge"];
  portfolio: ReadonlyMap<string, WikiProject>;
  wikiNames: ReadonlyMap<string, string>;
  target: { key: string } | null;
  go: () => void;
  locate: (quote: string) => PdfQuoteLocation;
  locating: boolean;
  pageLink: PageLink;
  related: (fit: Requirement) => ReactNode[];
}

export function AnalysisRequirements({ fits, judged, knowledge, portfolio, wikiNames, target, go, locate, locating, pageLink, related }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [group, setGroup] = useState("all");
  const [search, setSearch] = useState("");
  const [noCompany, setNoCompany] = useState(false);
  const [selection, setSelection] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<{ key: string } | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  const previousTarget = useRef<typeof target>(null);
  const prefixList = [...new Set(fits.map(category))];
  const query = search.trim().toLowerCase();
  const portfolioName = (id: string) => portfolio.has(id) ? known(portfolio.get(id)?.title) : id;
  const replaceRationale = (text: string) => text.replace(/\[\[([^\]]+)\]\]/g, (_token, id: string) => portfolioName(id));
  const rationaleNodes = (text: string) => text.split(/\[\[([^\]]+)\]\]/g).map((part, i) =>
    i % 2 ? <span className="paw-pf" key={i} title={part}>{portfolioName(part)}</span> : part);
  const rows = fits.filter((fit) => (filter === "all" || fit.fit === filter)
    && (group === "all" || category(fit) === group)
    && (!noCompany || !fit.evidence_portfolio_ids?.length)
    && (!query || [fit.req_id, fit.name, fit.definition, replaceRationale(fit.rationale), fit.evidence?.quote,
      fit.gap_action, ...(fit.evidence_portfolio_ids ?? []).map(portfolioName)].join(" ").toLowerCase().includes(query)))
    .sort((a, b) => fitOrder.indexOf(a.fit) - fitOrder.indexOf(b.fit));
  const selected = rows.find((fit) => requirementKey(fit) === selection) ?? rows[0];
  const selectedKey = selected ? requirementKey(selected) : null;
  const index = selected ? rows.indexOf(selected) : -1;
  const relatedIssues = selected ? related(selected) : [];

  function select(key: string, focus = false) {
    setSelection(key);
    if (focus) setFocusKey({ key });
    replaceAnalysisHash("req", key);
  }

  const navigation = useRowKeyboardNavigation({
    containerRef: listRef,
    keys: rows.map(requirementKey),
    selectedKey,
    onSelect: select,
  });

  useLayoutEffect(() => {
    if (!target || target === previousTarget.current) return;
    previousTarget.current = target;
    const fit = fits.find((row) => requirementKey(row) === target.key) ?? fits.find((row) => row.req_id === target.key);
    if (!fit) return;
    setFilter("all");
    setGroup("all");
    setSearch("");
    setNoCompany(false);
    select(requirementKey(fit), true);
    go();
  }, [target, fits, go]);

  useLayoutEffect(() => {
    if (!focusKey || selectedKey !== focusKey.key) return;
    const list = listRef.current;
    const row = list?.querySelector<HTMLElement>(`[data-row-key="${CSS.escape(focusKey.key)}"]`);
    if (!list || !row) return;
    const viewport = list.getBoundingClientRect();
    const box = row.getBoundingClientRect();
    const header = list.querySelector("thead")?.getBoundingClientRect().height ?? 0;
    if (box.top < viewport.top + header) list.scrollTop += box.top - viewport.top - header;
    else if (box.bottom > viewport.bottom) list.scrollTop += box.bottom - viewport.bottom;
    row.focus({ preventScroll: true });
  }, [focusKey, selectedKey]);

  useLayoutEffect(() => { if (detailRef.current) detailRef.current.scrollTop = 0; }, [selectedKey]);

  function changeFilter(change: () => void) {
    setSelection(selectedKey);
    change();
  }

  const columns: RecordTableColumn<Requirement>[] = [
    { key: "id", header: "ID", width: 80, className: "paw-mono", renderCell: ({ req_id }) => req_id },
    { key: "requirement", header: "요구사항 · 판단 사유", title: (fit) => known(fit.name),
      titleClassName: "paw-nm", renderBelow: ({ rationale }) => <span className="paw-one paw-rs" title={replaceRationale(rationale)}>{rationaleNodes(rationale)}</span> },
    { key: "fit", header: "대응", width: 74, renderCell: (fit) => <Fit fit={fit.fit} /> },
    { key: "portfolio", header: "회사 근거 실적", width: 150, renderCell: (fit) => {
      const ids = fit.evidence_portfolio_ids ?? [];
      if (!ids.length) return <span className="paw-faint">연결 없음</span>;
      const titles = ids.map(portfolioName).join(", ");
      const meta = ids.map((id) => {
        const project = portfolio.get(id);
        return project ? `${known(project.client, "발주처 미확인")} · ${period(project)}` : "실적 정보 없음";
      }).join(", ");
      return <span className="paw-co paw-one" title={`${titles} · ${meta}`}>
        {titles}<small className="paw-one">{meta}</small>
      </span>;
    } },
    { key: "page", header: "원문", width: 64, renderCell: (fit) => {
      if (locating) return <span className="paw-page-loading">쪽 찾는 중</span>;
      const page = locate(fit.evidence?.quote ?? "").page;
      return <span className={`paw-pg${page === null ? " paw-none" : ""}`}>{page === null ? "없음" : `${page}쪽`}</span>;
    } },
  ];

  return <section className="paw-blk" id="s-reqs" aria-label="요구사항 비교">
    <div className="paw-blk-h"><h2>요구사항 대응</h2><span className="paw-n">{fits.length}건 · 엔진 판정 {judged == null ? "미확인" : `${judged}건`}</span>
      <span className="paw-aside">행을 고르면 오른쪽에 원문 발췌·회사 근거·보완 방안이 나와요 · ↑↓로 이동</span></div>
    <p className="paw-kn">{knowledge ? <>회사 근거는 위키 <b>{knowledge.pages.length}쪽</b>만 분석에 들어갔고 <b>{knowledge.skipped.length}쪽</b>은 분석 분량 제한으로 빠졌어요
      {knowledge.skipped.length > 0 && `(${knowledge.skipped.map((slug) => knowledgeName(slug, portfolio, wikiNames)).join(", ")})`}.</>
      : "분석에 쓰인 회사 근거 위키 쪽은 미확인이에요."} ‘회사 근거 없음’이 실적이 없다는 뜻은 아니에요.</p>
    <div className="paw-reqbar">
      <div className="paw-filters" role="group" aria-label="대응으로 거르기">
        {(["all", ...fitOrder] as const).map((value) => {
          const count = value === "all" ? fits.length : fits.filter((fit) => fit.fit === value).length;
          const disabled = count === 0 && value !== "all";
          return <button className="paw-fchip" type="button" key={value} aria-pressed={filter === value} disabled={disabled}
            title={disabled ? "해당 없음" : undefined} onClick={() => changeFilter(() => setFilter(value))}>{value === "all" ? "전체" : fitNames[value]}<b>{count}</b></button>;
        })}
      </div>
      <select aria-label="분류로 거르기" value={group} onChange={(event) => changeFilter(() => setGroup(event.target.value))}>
        <option value="all">분류 전체</option>
        {prefixList.map((prefix) => <option key={prefix} value={prefix}>{prefix}{categories[prefix] ? ` ${categories[prefix]}` : ""} ({fits.filter((fit) => category(fit) === prefix).length})</option>)}
      </select>
      <input type="search" placeholder="ID·요구사항·원문·사유 검색" aria-label="요구사항 검색" value={search}
        onChange={(event) => changeFilter(() => setSearch(event.target.value))} />
      <label className="paw-tog"><input type="checkbox" checked={noCompany} onChange={(event) => changeFilter(() => setNoCompany(event.target.checked))} /> 회사 근거 없는 것만</label>
      <span className="paw-count" aria-live="polite">{rows.length}건 표시</span>
    </div>
    <div className="paw-reqgrid">
      <RecordTable label="요구사항 대응 목록" rows={rows} columns={columns} getKey={requirementKey}
        activeKey={selectedKey} viewportRef={listRef} navigation={navigation} className="paw-reqlist"
        onActivate={(key) => select(key, true)} />
      {rows.length === 0 && <p className="paw-req-empty">조건에 맞는 요구사항이 없어요.</p>}
      <aside className="paw-detail" ref={detailRef} aria-live="polite" aria-label="선택한 요구사항">
        {selected ? <>
          <div className="paw-top"><span className="paw-mono">{selected.req_id}</span>
            <span className="paw-faint">{categories[category(selected)] ?? category(selected)}</span>
            <Fit fit={selected.fit} /><div className="paw-navbtns">
              <button type="button" className="paw-btn" aria-label="이전 요구사항" disabled={index <= 0}
                onClick={() => select(requirementKey(rows[index - 1]), true)}>↑ 이전</button>
              <button type="button" className="paw-btn" aria-label="다음 요구사항" disabled={index >= rows.length - 1}
                onClick={() => select(requirementKey(rows[index + 1]), true)}>↓ 다음</button>
            </div>
          </div>
          <h3>{known(selected.name)}</h3>
          {selected.definition && selected.definition !== selected.name && <p className="paw-def">{selected.definition}</p>}
          <h4>원문 발췌 {pageLink(selected.evidence, `${selected.req_id} 원문 발췌`)} <span className="paw-faint">
            {citationLabel(selected.evidence)}{!locating && selected.evidence && locate(selected.evidence.quote).kind === "not_found"
              && " · PDF 본문에서 문장을 찾지 못했어요"}</span></h4>
          {selected.evidence?.quote ? <blockquote>{selected.evidence.quote}</blockquote> : <p className="paw-muted">연결된 원문 발췌가 없어요.</p>}
          <h4>판단 사유 (엔진)</h4><p>{rationaleNodes(known(selected.rationale))}</p>
          <h4>회사 근거</h4>
          {selected.evidence_portfolio_ids?.length ? selected.evidence_portfolio_ids.map((id) => {
            const project = portfolio.get(id);
            return <div className="paw-cocard" key={id}><b>{portfolioName(id)}</b>
              {project ? <><span className="paw-meta">{known(project.client, "발주처 미확인")} · {period(project)} · {known(project.type)} · {known(project.role)}</span>
                <div><a href={`/company?view=portfolio&project=${encodeURIComponent(id)}`} target="_blank" rel="noreferrer">회사 근거에서 이 실적 열기 ↗</a></div></>
                : <span className="paw-meta">회사 근거에 없는 코드예요</span>}
            </div>;
          }) : <p className="paw-muted">연결된 회사 실적이 없어요.{knowledge && knowledge.skipped.length > 0
            && ` 위키 ${knowledge.skipped.length}쪽이 분석에서 빠졌으니 실적이 없다는 뜻은 아니에요.`}</p>}
          <h4>보완 방안 (엔진)</h4><p>{selected.gap_action || <span className="paw-muted">엔진이 보완 방안을 내지 않았어요.</span>}</p>
          {relatedIssues.length > 0 && <><h4>관련 쟁점</h4>{relatedIssues}</>}
        </> : <p className="paw-muted">요구사항을 고르세요.</p>}
      </aside>
    </div>
  </section>;
}

function Fit({ fit }: { fit: Requirement["fit"] }) {
  return <span className={`paw-fit ${fit}`}>{fitNames[fit]}</span>;
}
