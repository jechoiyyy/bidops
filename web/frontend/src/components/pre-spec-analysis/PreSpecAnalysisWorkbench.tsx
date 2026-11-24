import { useQuery } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { FileText } from "lucide-react";
import { PageHeaderActions, PageHeaderTabs } from "../common/PageHeaderActions";
import { usePageHeader } from "../shell/PageHeaderContext";
import { api } from "../../lib/api";
import { wiki } from "../../lib/companyWikiApi";
import { remainingDeadlineDays } from "../../lib/deadline";
import { createEngineRiskLinker } from "../../lib/engineRiskLinks";
import type { EngineAnalysis, EngineEvidence, EngineRun } from "../../lib/engineApi";
import { createPdfQuoteLocator, normalizePdfQuote } from "../../lib/pdfQuoteLocator";
import { qualityStatusLabel } from "../../lib/qualityStatus";
import type { NoticeDetailResponse, PageOverviewFact, PageOverviewView, PreSpecListItem } from "../../lib/types";
import { AnalysisRequirements } from "./AnalysisRequirements";
import { analysisDate, citationLabel, known, replaceAnalysisHash, requirementKey, type Requirement } from "./analysisPresentation";
import { AnalysisSource, AnalysisTerms, type PageLink } from "./AnalysisSource";
import "../../styles/pre-spec-analysis-workbench.css";

const noRisks: NonNullable<EngineAnalysis["risks"]> = [];
const sections = ["brief", "issues", "reqs", "terms", "source"] as const;
type Section = typeof sections[number];
type IssueFilter = "all" | "why" | "pre" | "high";

const severity = { H: "상", M: "중", L: "하" };
const rank = { H: 0, M: 1, L: 2 };
const fitLabel = { FULL: "충족", PARTIAL: "부분", GAP: "부족", UNKNOWN: "미확인" };
const decision = { GO: "참여 검토", CONDITIONAL_GO: "조건부 참여 검토", NO_GO: "참여 비권장" };
const legend = "사유·전제와 리스크의 연결은 엔진 출력이 아니라 화면이 문장을 대조해 붙였어요.";
function won(value: number) {
  return `${value.toLocaleString("ko-KR")}원`;
}

interface Props {
  run: EngineRun;
  notice: NoticeDetailResponse;
  item?: PreSpecListItem;
  shown: PageOverviewView | null;
  overviewUnavailable: string;
  number: string | null;
  bidNotice: string | null;
  originalFilename?: string;
  process?: ReactNode;
}

function overviewEvidence(claim: PageOverviewFact) {
  return "evidence" in claim ? claim.evidence : claim.evidence_pages.map((page) => ({ page }));
}

export function PreSpecAnalysisWorkbench(props: Props) {
  const { run } = props;
  return run.analysis && <Workbench {...props} analysis={run.analysis} />;
}

function Workbench({ run, notice, item, shown, overviewUnavailable, number, bidNotice, originalFilename, process, analysis }: Props & { analysis: EngineAnalysis }) {
  const root = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<Section>("brief");
  const [issueFilter, setIssueFilter] = useState<IssueFilter>("all");
  const [openIssues, setOpenIssues] = useState<ReadonlySet<number>>(() => new Set());
  const [issueTarget, setIssueTarget] = useState<{ index: number } | null>(null);
  const [reqTarget, setReqTarget] = useState<{ key: string } | null>(null);
  const [initialHash] = useState(() => new URLSearchParams(window.location.hash.slice(1)));
  const opportunityId = item?.opportunity_id ?? null;
  const opportunity = useQuery({
    queryKey: ["opportunity", opportunityId],
    queryFn: ({ signal }) => api.getOpportunity(opportunityId!, { signal }),
    enabled: opportunityId !== null,
    retry: false,
    staleTime: 30_000,
  });
  const portfolioQuery = useQuery(wiki.portfolio);
  const wikiPages = useQuery(wiki.pages);
  const portfolio = useMemo(() => new Map(portfolioQuery.data?.items.map((project) => [project.id, project])), [portfolioQuery.data]);
  const wikiNames = useMemo(() => new Map(wikiPages.data?.pages.map((page) => [page.slug, page.title])), [wikiPages.data]);
  const includedPages = analysis.knowledge?.pages ?? [];
  const includedProjectPages = includedPages.filter((slug) =>
    portfolio.has(slug) || Object.hasOwn(analysis.knowledge?.portfolio_excerpts ?? {}, slug)
    || wikiPages.data?.pages.some((page) => page.slug === slug && page.kind === "portfolio"));
  const readProjectCount = includedPages.every((slug) => includedProjectPages.includes(slug) || wikiNames.has(slug))
    ? includedProjectPages.length : null;
  const openedOpportunity = opportunity.data?.id === opportunityId ? opportunity.data : null;

  const pdf = shown?.pdf_sha256 && shown.pdf_page_count > 0 ? api.preSpecOverviewRunPdfUrl(notice.id, shown.id) : null;
  const texts = useQuery({
    queryKey: ["prespec-overview-page-text", notice.id, shown?.id, shown?.pdf_sha256],
    queryFn: ({ signal }) => api.getOverviewRunPageText(notice.id, shown!.id, { signal }),
    enabled: pdf !== null,
    retry: false,
  });
  const text = texts.data;
  const boundText = text?.schema === "bidops.prespec-overview-page-text.v1"
    && text.notice_id === notice.id && text.run_id === shown?.id && text.pdf_sha256 === shown.pdf_sha256
    && text.document_version_id === shown.document_version_id && text.page_count === shown.pdf_page_count ? text : null;
  const canLocate = Boolean(shown?.document_version_id
    && run.documents.some((document) => document.document_version_id === shown.document_version_id));
  const locating = pdf !== null && canLocate && texts.isPending;
  const locate = useMemo(() => createPdfQuoteLocator(canLocate ? boundText?.pages ?? [] : []), [boundText, canLocate]);
  const pageCount = shown?.pdf_page_count ?? 0;
  const tracking = item?.tracking_status ?? (opportunityId === null && item ? "사업기회 미연결" : "미확인");
  const deadline = notice.deadline_at ? remainingDeadlineDays(new Date(notice.deadline_at), new Date()) : NaN;
  const countdown = Number.isFinite(deadline) ? deadline < 0 ? "마감 지남" : deadline === 0 ? "D-day" : `D-${deadline}` : null;
  const quality = qualityStatusLabel(run.quality_status);

  usePageHeader({
    title: known(notice.title, "사업명 미확인"),
    facts: [
      { key: "opinion-deadline", label: "의견 마감", value: analysisDate(notice.deadline_at) },
      { key: "demand-agency", label: "수요기관", value: known(item?.demand_agency) },
      { key: "announcer", label: "공고기관", value: known(notice.agency) },
      { key: "published", label: "게시", value: analysisDate(notice.published_at, false) },
      { key: "prespec-number", label: "사전규격번호", value: known(number) },
      { key: "division", label: "구분", value: `${known(item?.business_division)} · SW사업대상 ${known(item?.sw_business_status)}` },
      { key: "bid-notice", label: "본공고", value: known(bidNotice) },
    ],
  });

  useLayoutEffect(() => {
    const panel = root.current?.closest<HTMLElement>(".app-content");
    const scroller = root.current?.closest<HTMLElement>(".page-canvas");
    if (!panel || !scroller) return;
    const previousWidth = panel.dataset.readingWidth;
    panel.dataset.readingWidth = "analysis";
    const blocks = sections.map((id) => root.current?.querySelector<HTMLElement>(`#s-${id}`));
    const spy = () => {
      panel.dataset.headerCompact = String(scroller.scrollTop > 60);
      const top = scroller.getBoundingClientRect().top + 60;
      let current: Section = "brief";
      blocks.forEach((block, index) => {
        if (block && block.getBoundingClientRect().top <= top) current = sections[index];
      });
      if (scroller.scrollTop > 0 && scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 4) current = "source";
      setActive(current);
    };
    scroller.addEventListener("scroll", spy, { passive: true });
    const observer = new ResizeObserver(spy);
    observer.observe(scroller);
    if (root.current) observer.observe(root.current);
    spy();
    return () => {
      observer.disconnect();
      scroller.removeEventListener("scroll", spy);
      delete panel.dataset.headerCompact;
      if (panel.dataset.readingWidth === "analysis") {
        if (previousWidth) panel.dataset.readingWidth = previousWidth;
        else delete panel.dataset.readingWidth;
      }
    };
  }, []);

  useLayoutEffect(() => {
    const panel = root.current?.closest<HTMLElement>(".app-content");
    if (!panel || !countdown) return;
    panel.style.setProperty("--paw-deadline-countdown", JSON.stringify(countdown));
    return () => { panel.style.removeProperty("--paw-deadline-countdown"); };
  }, [countdown]);

  const risks = analysis.risks ?? noRisks;
  const { why_not: whyNot, preconditions } = analysis.recommendation;
  const requests = analysis.review_actions?.requests ?? [];
  const execution = requests.filter((request) => request.kind === "execution");
  const link = createEngineRiskLinker(risks);
  const whyLinks = whyNot.map(link);
  const preLinks = preconditions.map(link);
  const requestLinks = execution.map((request) => link(`${request.title} ${request.why}`));
  const requirements = analysis.fits;
  const indexByQuote = new Map<string, Requirement[]>();
  for (const fit of requirements) {
    const key = normalizePdfQuote(fit.evidence?.quote ?? "");
    if (!key) continue;
    const same = indexByQuote.get(key) ?? [];
    same.push(fit);
    indexByQuote.set(key, same);
  }
  const issues = risks.map((risk, index) => ({
    risk, index,
    why: whyLinks.flatMap((target, i) => target === index ? [i] : []),
    pre: preLinks.flatMap((target, i) => target === index ? [i] : []),
    requests: execution.filter((_request, i) => requestLinks[i] === index),
    same: indexByQuote.get(normalizePdfQuote(risk.evidence.quote)) ?? [],
  })).sort((a, b) => rank[a.risk.severity] - rank[b.risk.severity]
    || Number(b.why.length > 0) - Number(a.why.length > 0) || a.index - b.index);

  const issueFilters = [
    { id: "all", name: "전체", match: () => true },
    { id: "why", name: "조건부 사유", match: (issue: typeof issues[number]) => issue.why.length > 0 },
    { id: "pre", name: "참여 전제만", match: (issue: typeof issues[number]) => issue.why.length === 0 },
    { id: "high", name: "심각도 상", match: (issue: typeof issues[number]) => issue.risk.severity === "H" },
  ] as const;
  const visibleIssues = issues.filter((issue) => issueFilters.find(({ id }) => id === issueFilter)?.match(issue));
  const go = (id: Section) => root.current?.querySelector(`#s-${id}`)?.scrollIntoView({ block: "start" });

  function openIssue(index: number) {
    if (!risks[index]) return;
    if (!visibleIssues.some((issue) => issue.index === index)) setIssueFilter("all");
    setOpenIssues((open) => new Set(open).add(index));
    setIssueTarget({ index });
    replaceAnalysisHash("issue", String(index));
  }

  useEffect(() => {
    const scrollHash = (hash: URLSearchParams) => {
      const issue = hash.get("issue");
      const req = hash.get("req");
      if (issue !== null && /^(0|[1-9]\d*)$/.test(issue) && risks[Number(issue)]) {
        const index = Number(issue);
        setIssueFilter("all");
        setOpenIssues((open) => new Set(open).add(index));
        setIssueTarget({ index });
      } else if (req !== null) setReqTarget({ key: req });
    };
    scrollHash(initialHash);
    const onHash = () => scrollHash(new URLSearchParams(window.location.hash.slice(1)));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [initialHash, risks]);

  useLayoutEffect(() => {
    if (!issueTarget) return;
    const row = root.current?.querySelector<HTMLButtonElement>(`#issue-${issueTarget.index} > button`);
    row?.focus({ preventScroll: true });
    const issue = row?.parentElement;
    issue?.scrollIntoView({ block: "start" });
    if (issue && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const color = getComputedStyle(issue).getPropertyValue("--color-warning-muted").trim();
      issue.animate([{ backgroundColor: color }, { backgroundColor: "transparent" }], 1400);
    }
  }, [issueTarget]);

  function pdfPageLink(page: number | null, label: string, text?: string) {
    if (!pdf || page === null || page < 1 || page > pageCount) {
      return <span className="paw-pg paw-none" title="PDF에서 이 문장을 찾지 못했어요">쪽 없음</span>;
    }
    return <a className="paw-pg" href={`${pdf}#page=${page}`} target="_blank" rel="noreferrer"
      title={`${label} · PDF ${page}쪽 새 탭에서 열기`}>
      <FileText aria-hidden="true" />{text ?? `${page}쪽`}
    </a>;
  }

  const pageLink: PageLink = (evidence, label) => {
    if (locating) return <span className="paw-pg paw-none">쪽 찾는 중</span>;
    const { page } = locate(evidence?.quote ?? "");
    return page === null && pdf && (texts.isError || (text && !boundText)) && canLocate
      ? <><span className="paw-pg paw-none">쪽 없음</span>{" "}<a className="paw-pg" href={pdf} target="_blank" rel="noreferrer">PDF 새 탭에서 열기 ↗</a></>
      : pdfPageLink(page, label);
  };
  const pagePlace = (evidence?: EngineEvidence | null) => {
    const location = locate(evidence?.quote ?? "");
    return locating ? "쪽 찾는 중" : location.page === null ? "쪽 없음" : `${location.page}쪽`;
  };
  const claimLinks = (claim: PageOverviewFact | undefined, label = "개요 근거 문장") =>
    claim && overviewEvidence(claim).map((evidence, i) => <span key={i}>
      {i > 0 && " "}{pdfPageLink(evidence.page, label)}
    </span>);
  const overview = shown?.payload.business_overview ?? [];
  const tasks = shown?.payload.main_tasks ?? [];
  const budgetClaim = shown?.payload.budget_and_period.find((claim) => claim.text.includes("금액"));
  const period = shown?.payload.budget_and_period.find((claim) => claim.text.includes("기간"));
  const project = analysis.facts?.project;
  const budgetEvidence = project?.evidence.find((evidence) => /VAT|부가/.test(evidence.quote));
  const registered = notice.budget;
  const projectAmount = project?.budget_krw;
  const diff = registered == null || projectAmount == null ? null : registered - projectAmount;
  const sourceFound = analysis.requirement_counts?.source_found;
  const judged = analysis.assessment?.provisional?.fit_coverage.judged;
  const whyTitle = analysis.recommendation.decision === "CONDITIONAL_GO" ? "엔진이 ‘조건부’로 본 이유" : "엔진이 이 의견을 낸 이유";
  const omittedHigh = issues.filter(({ risk, why }) => risk.severity === "H" && !why.length);
  const issueJump = (index: number, prefix = "", suffix = " →") => {
    const quote = risks[index].evidence.quote;
    return <button type="button" className="paw-jump paw-issue-jump" title={quote} onClick={() => openIssue(index)}>{prefix}{quote}{suffix}</button>;
  };
  const claimItem = (claim: PageOverviewFact, i: number) =>
    <li key={i}><span>{claim.text}</span><span>{claimLinks(claim)}</span></li>;

  const tabLabels = ["한눈에", "쟁점", "요구사항", "자격·계약", "원문·처리 정보"];
  const tabCounts = [null, risks.length, requirements.length, analysis.gates.length, null];

  return <div ref={root} className="paw-workbench">
    <PageHeaderActions><span className="paw-chip">{quality}</span></PageHeaderActions>
    <PageHeaderTabs>
      <nav className="paw-tabs" aria-label="분석 구역 이동">
        {sections.map((id, index) => <a key={id} href={`#s-${id}`} aria-current={active === id ? "location" : undefined}
          onClick={(event) => { event.preventDefault(); go(id); }}>
          {tabLabels[index]}{tabCounts[index] !== null && <b>{tabCounts[index]}</b>}
        </a>)}
        <span className="paw-tab-hint">쪽 링크는 제안요청서 PDF를 새 탭에서 열어요</span>
      </nav>
    </PageHeaderTabs>

    <section className="paw-blk paw-brief" id="s-brief" aria-label="한눈에">
      <div>
        <h3 className="paw-sub paw-purpose-head">사업 개요{shown?.reviewed_pages.length
          ? <span>제안요청서 PDF {shown.reviewed_pages.join("·")}쪽 기준</span> : null}</h3>
        {overview.length > 0
          ? <ul className="paw-claims paw-purpose">{overview.map(claimItem)}</ul>
          : <p className="paw-muted" role="status">{shown ? "검증된 결과에 사업 개요 문장이 없어요." : overviewUnavailable}</p>}
        <h3 className="paw-sub">사업 금액 대조</h3>
        <div className="paw-bcmp">
          <div><div className="paw-k">사전규격 등록액</div><div className="paw-v">{registered == null ? "예산 미제공" : won(registered)}</div>
            <div className="paw-s">출처: 나라장터 사전규격 등록 정보({known(number)}) · 부가세 포함 여부 표시 없음</div></div>
          <div><div className="paw-k">제안요청서 사업금액</div><div className="paw-v">{projectAmount == null ? "미확인" : won(projectAmount)}
            <small>{project?.vat_included == null ? "부가가치세 포함 여부 미확인" : project.vat_included ? "부가가치세 포함" : "부가가치세 별도"}</small></div>
            <div className="paw-s">출처: 제안요청서 {claimLinks(budgetClaim, "제안요청서 사업금액")}
              {budgetEvidence && <> · 같은 금액 {pageLink(budgetEvidence, "제안요청서 사업금액(사업 개요 절)")}</>}</div></div>
          <div className="paw-d"><b>차이 {diff === null ? "계산 불가" : won(Math.abs(diff))}</b>
            {diff === null || diff === 0 ? "" : diff > 0 ? " · 등록액이 더 커요" : " · 제안요청서 금액이 더 커요"} · 차이가 생긴 이유는 수집한 자료에 없어요.</div>
        </div>
        <h3 className="paw-sub">주요 과업 {shown ? `${tasks.length}건` : "미확인"}</h3>
        <ol className="paw-claims paw-tasks">{tasks.map(claimItem)}</ol>
        <h3 className="paw-sub paw-period">사업 기간</h3>
        <p>{period?.text ?? "미확인"} {claimLinks(period, "제안요청서 사업기간")}</p>
      </div>
      <div>
        <div className="paw-layers">
          <div className="paw-layer paw-engine"><div className="paw-who"><b>엔진 참고 의견</b>분석 엔진</div><div className="paw-val">
            <strong>{decision[analysis.recommendation.decision]}</strong> <span className="paw-chip paw-model">참고</span> <span className="paw-chip">{quality}</span>
            <div className="paw-layer-note">요구사항 {sourceFound == null ? "건수 미확인" : `${sourceFound}건`} 중 {judged == null ? "판정 건수 미확인" : `${judged}건 판정`} · {analysisDate(run.completed_at)} 분석. 의견은 결정이 아니에요.</div>
          </div></div>
          <div className="paw-layer"><div className="paw-who"><b>추적 판단</b>사람 · 지금 정해요</div><div className="paw-val">
            <strong>{tracking}</strong> <span className="paw-layer-note">· {openedOpportunity?.tracking_selected_by ?? "미확인"} · {analysisDate(openedOpportunity?.tracking_selected_at, false)}</span>
            <div className="paw-layer-note">사유: {known(openedOpportunity?.tracking_reason, openedOpportunity ? "값 없음" : "미확인")}</div>
          </div></div>
          <div className="paw-layer"><div className="paw-who"><b>최종 입찰 결정</b>Go/No-Go · 사람 · 본공고 뒤</div><div className="paw-val">
            <strong>{bidNotice ? "미확인" : "아직 없음"}</strong> <span className="paw-layer-note">· 본공고 {known(bidNotice)}</span>
            <div className="paw-layer-note">입찰공고가 연결되면 최종 Go/No-Go 화면에서 정해요.</div>
          </div></div>
        </div>
        <h3 className="paw-sub">{whyTitle} {whyNot.length}건</h3>
        <ol className="paw-why">{whyNot.map((reason, i) => {
          const issue = issues.find(({ index }) => index === whyLinks[i]);
          return <li key={i}><span className="paw-no">{i + 1}</span><div>{reason}
            {issue && <div className="paw-line">
              <span className={`paw-sev ${issue.risk.severity}`}>{severity[issue.risk.severity]}</span>
              {issueJump(issue.index, "쟁점: ")}{pageLink(issue.risk.evidence, "리스크 근거 문장")}
              {issue.same.map((fit) => <button className="paw-jump" type="button" key={requirementKey(fit)}
                onClick={() => setReqTarget({ key: requirementKey(fit) })}>{fit.req_id}</button>)}
            </div>}
          </div></li>;
        })}</ol>
        <p className="paw-connection-note">{legend}</p>
        <div className="paw-also">
          {omittedHigh.length > 0 && <>심각도 상이지만 ‘조건부’ 사유에는 없는 쟁점: {omittedHigh.map((issue, i) =>
            <span key={issue.index}>{i > 0 && ", "}{issueJump(issue.index, "", "")} {pageLink(issue.risk.evidence, "리스크 근거 문장")}</span>)}
            {omittedHigh.every((issue) => issue.pre.length > 0) && <> · 화면이 <b>참여 전제</b>와 연결했어요.</>}{" "}</>}
          <button type="button" className="paw-jump" onClick={() => go("issues")}>쟁점 {risks.length}건 모두 보기 →</button>
        </div>
      </div>
    </section>

    <section className="paw-blk" id="s-issues" aria-label="쟁점">
      <div className="paw-blk-h"><h2>먼저 확인할 쟁점</h2><span className="paw-n">{risks.length}건</span>
        <span className="paw-aside">엔진 리스크 {risks.length}건 · 심각도 순</span></div>
      <div className="paw-filters" role="group" aria-label="쟁점 보기">{issueFilters.map(({ id, name, match }) =>
        <button className="paw-fchip" type="button" key={id} aria-pressed={issueFilter === id}
          onClick={() => { setIssueFilter(id); setOpenIssues(new Set()); }}>{name}<b>{issues.filter(match).length}</b></button>)}</div>
      <div className="paw-legend">
        <span><span className="paw-chip paw-model">조건부 사유</span> 엔진이 의견의 이유(why_not)로 직접 적었어요</span>
        <span><span className="paw-chip">참여 전제</span> 엔진이 참여 전제 조건으로만 적었어요</span>
        <span className="paw-faint">{legend}</span>
      </div>
      <div className="paw-issues">
        {visibleIssues.length === 0 && <p className="paw-empty">이 보기에 해당하는 쟁점이 없어요.</p>}
        {visibleIssues.map(({ risk, index, why, pre, same, requests: confirmations }) => {
          const opened = openIssues.has(index);
          const location = locate(risk.evidence.quote);
          const quote = risk.evidence.quote;
          return <div className={`paw-issue${opened ? " paw-open" : ""}`} key={index} id={`issue-${index}`}>
            <button type="button" className="paw-rowbtn" aria-expanded={opened} aria-controls={`paw-issue-body-${index}`}
              onClick={() => setOpenIssues((previous) => {
                const next = new Set(previous);
                if (next.has(index)) next.delete(index);
                else next.add(index);
                return next;
              })}>
              <span className={`paw-sev ${risk.severity}`} title={`심각도 ${severity[risk.severity]}`}>{severity[risk.severity]}</span>
              <span className="paw-t" title={quote}>{quote}<small>{risk.category}</small></span>
              <span className="paw-rel">
                {why.map((i) => <span className="paw-chip paw-model" key={`why-${i}`} title={whyNot[i]}>조건부 사유 {i + 1}</span>)}
                {pre.map((i) => <span className="paw-chip" key={`pre-${i}`} title={preconditions[i]}>참여 전제 {i + 1}</span>)}
              </span>
              <span><span className={`paw-pg${location.page === null ? " paw-none" : ""}`}>{pagePlace(risk.evidence)}</span></span>
              <span className="paw-caret" aria-hidden="true">›</span>
            </button>
            <div className="paw-body" id={`paw-issue-body-${index}`} hidden={!opened}>
              <div className="paw-kv">
                <h4>원문 근거 {pageLink(risk.evidence, "리스크 근거 문장")} <span className="paw-faint">
                  {risk.evidence.verified === false ? "인용 미검증" : citationLabel(risk.evidence)} · {locating ? "PDF 본문에서 찾는 중" : location.kind === "exact" ? "PDF 본문과 문장 일치" : location.kind === "span" ? "이웃한 두 쪽에서 문장 일치" : "PDF 본문과 일치 못 찾음"}
                </span></h4>
                <blockquote>{quote}</blockquote>
                <h4>엔진 설명</h4><p>{risk.description}</p>
                <h4>엔진이 제안한 대응</h4><p>{known(risk.mitigation, "값 없음")}</p>
              </div>
              <div className="paw-kv">
                <h4>엔진 의견과의 관계</h4>
                {why.length ? why.map((i) => <blockquote className="paw-engine-said" key={i}><b>조건부 사유 {i + 1}</b> · {whyNot[i]}</blockquote>)
                  : <p className="paw-muted">‘조건부’ 사유(why_not)에는 직접 적히지 않았어요.</p>}
                {pre.map((i) => <p className="paw-precondition" key={i}><span className="paw-chip">참여 전제 {i + 1}</span> {preconditions[i]}</p>)}
                {confirmations.length > 0 && <><h4>엔진이 확인을 요청한 자료</h4><ul>{confirmations.map((request) =>
                  <li key={request.id}><b>{request.title}</b> — {request.why}</li>)}</ul></>}
                {same.length > 0 && <><h4>같은 원문 문장을 인용한 요구사항</h4>{same.map((fit) =>
                  <p key={requirementKey(fit)}><button className="paw-jump" type="button" onClick={() => setReqTarget({ key: requirementKey(fit) })}>
                    {fit.req_id} {fit.name}</button> <span className={`paw-fit ${fit.fit}`}>{fitLabel[fit.fit]}</span></p>)}</>}
              </div>
            </div>
          </div>;
        })}
      </div>
    </section>

    <AnalysisRequirements fits={requirements} knowledge={analysis.knowledge} workUnits={analysis.work_units} readProjectCount={readProjectCount}
      judged={judged} portfolio={portfolio} wikiNames={wikiNames}
      target={reqTarget} go={() => go("reqs")} locate={locate} locating={locating} pageLink={pageLink}
      related={(fit) => issues.filter((issue) => issue.same.includes(fit)).map(({ index, risk }) =>
        <div key={index}><span className={`paw-sev ${risk.severity}`}>{severity[risk.severity]}</span> {issueJump(index)}</div>)} />
    <AnalysisTerms analysis={analysis} pageLink={pageLink} consortiumIssue={issues.find(({ risk }) =>
      /공동수급/.test(risk.evidence.quote) && /공동수급/.test(risk.description) && /평가기준|평가 기준/.test(risk.description))?.index}
      openIssue={openIssue} />
    <AnalysisSource run={run} analysis={analysis} shown={shown} notice={notice} originalFilename={originalFilename} portfolio={portfolio}
      wikiNames={wikiNames} readProjectCount={readProjectCount}
      locate={locate} pagesReady={boundText !== null && canLocate} claimLinks={claimLinks}
      openPdf={pdf ? pdfPageLink(1, "원문 전체", "PDF 처음부터 열기") : null} />
    {process}
  </div>;
}
