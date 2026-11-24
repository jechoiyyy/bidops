import { Button } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import { Navigate, useSearchParams } from "react-router-dom";
import { PageHeaderTabs } from "../components/common/PageHeaderActions";
import { WorkspaceViewTabs } from "../components/common/WorkspaceFilters";
import { usePageHeader } from "../components/shell/PageHeaderContext";
import { WikiState, wikiValue } from "../components/company-wiki/WikiState";
import { WikiOverview, WikiPages, WikiPortfolio, WikiTopics } from "../components/company-wiki/WikiViews";
import { ApiError } from "../lib/api";
import { ingestList, inProgress } from "../lib/companyWikiIngestApi";
import { WikiQuality } from "../components/company-wiki/WikiQuality";
import { WikiIngests } from "../components/company-wiki/WikiIngests";
import { IngestProblem } from "../components/company-wiki/IngestProblem";
import { wikiUrl } from "../components/company-wiki/WikiBody";
import { wiki, type WikiLog } from "../lib/companyWikiApi";
import "../styles/criteria-erp.css";
import "../styles/company-wiki.css";

const tabs = [
  { key: "overview", label: "개요" }, { key: "portfolio", label: "실적" },
  { key: "work-units", label: "업무별 근거" }, { key: "pages", label: "규칙·페이지" },
  { key: "quality", label: "답변 품질" }, { key: "ingests", label: "넣기 기록" }, { key: "log", label: "변경 이력" },
];

function logText(entry: WikiLog) {
  switch (entry.kind) {
    case "init": return "업무 분류표를 만들었어요";
    case "feedback": return "분석에서 확인한 내용을 반영했어요";
    case "ingest": return `${entry.project_title ?? entry.project} 실적을 넣었어요 · 요구사항 ${entry.requirement_count}건` +
      (entry.unassigned_count ? ` · 분류되지 않은 요구사항 ${entry.unassigned_count}건` : "");
    default: return entry.text;
  }
}

export default function CompanyWikiPage() {
  const [params, setParams] = useSearchParams();
  const view = tabs.find(tab => tab.key === params.get("view"))?.key ?? "overview";
  const summary = useQuery(wiki.summary);
  const start = Number(params.get("offset"));
  const offset = view === "ingests" && Number.isSafeInteger(start) && start > 0 ? start : 0;
  const records = useQuery({
    ...ingestList(offset), enabled: summary.isSuccess,
    refetchInterval: query => view === "ingests" && query.state.data?.items.some(inProgress) ? 2500 : false,
  });
  const disabled = records.error instanceof ApiError && records.error.status === 404 &&
    records.error.code === "company_wiki_ingest_disabled";
  const visibleTabs = tabs.filter(tab => tab.key !== "ingests" || (!disabled && !records.isPending));
  const counts = summary.data?.counts;
  const description = counts
    ? summary.data?.work_units_available && counts.ingested_projects !== null
      ? `실적 ${counts.portfolio_items}건 가운데 ${counts.ingested_projects}건이 업무별 근거 지도에 들어 있어요`
      : `실적 ${counts.portfolio_items}건이 등록돼 있어요`
    : null;
  usePageHeader({ description });
  if (disabled && view === "ingests") return <Navigate replace to={wikiUrl("portfolio")}/>;
  return <>
    <PageHeaderTabs><WorkspaceViewTabs label="회사 근거 보기" tabs={visibleTabs} value={view}
      onChange={key => {
        if (key === "ingests" && offset === 0) void records.refetch();
        setParams({ view: key });
      }}/></PageHeaderTabs>
    <div className="company-wiki">
      {summary.error || !summary.data ? <WikiState error={summary.error}/> : <>
        {view === "quality" && <WikiQuality/>}
        {view === "overview" && <WikiOverview summary={summary.data}/>}
        {view === "portfolio" && <>
          {disabled && <p>실적 넣기는 아직 켜지지 않았어요.</p>}
          {records.error && !disabled && <IngestProblem error={records.error}/>}
          <WikiPortfolio selected={params.get("project")} uploadEnabled={records.isSuccess}/>
        </>}
        {view === "ingests" && (records.error ? <div className="wiki-content"><IngestProblem error={records.error}/>
          <Button label="기록 다시 조회" onClick={() => { void records.refetch(); }}/></div> :
          records.data ? <WikiIngests {...records.data} offset={offset} selection={params.get("run")}/> :
            <p role="status">넣기 기록을 불러오고 있어요.</p>)}
        {view === "work-units" && (summary.data.work_units_available ? <WikiTopics selected={params.get("topic")}/> : <p>업무별 근거 지도가 아직 없어요.</p>)}
        {view === "pages" && <WikiPages selected={params.get("page")}/>}
        {view === "log" && <section className="wiki-content"><h2>변경 이력</h2>
          {summary.data.log.length ? <table><thead><tr><th>날짜</th><th>내용</th></tr></thead><tbody>
            {summary.data.log.map((entry, i) => <tr key={i}><td>{entry.date ? <time>{entry.date}</time> : wikiValue(null)}</td><td>{logText(entry)}</td></tr>)}
          </tbody></table> : <p>기록된 변경 이력이 없어요.</p>}</section>}
      </>}
    </div>
  </>;
}
