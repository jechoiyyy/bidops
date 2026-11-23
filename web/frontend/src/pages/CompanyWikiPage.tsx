import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { PageHeaderTabs } from "../components/common/PageHeaderActions";
import { WorkspaceViewTabs } from "../components/common/WorkspaceFilters";
import { usePageHeader } from "../components/shell/PageHeaderContext";
import { WikiState } from "../components/company-wiki/WikiState";
import { WikiOverview, WikiPages, WikiPortfolio, WikiTopics } from "../components/company-wiki/WikiViews";
import { wiki } from "../lib/companyWikiApi";
import "../styles/company-wiki.css";

const tabs = [
  { key: "overview", label: "개요" }, { key: "portfolio", label: "실적" },
  { key: "work-units", label: "업무별 근거" }, { key: "pages", label: "규칙·페이지" },
  { key: "log", label: "변경 이력" },
];

export default function CompanyWikiPage() {
  const [params, setParams] = useSearchParams();
  const view = tabs.find(tab => tab.key === params.get("view"))?.key ?? "overview";
  const summary = useQuery(wiki.summary);
  const counts = summary.data?.counts;
  let title = "회사 근거 자료를 살펴봐요";
  if (counts) {
    title = summary.data?.work_units_available && counts.ingested_projects !== null
      ? `실적 ${counts.portfolio_items}건 가운데 ${counts.ingested_projects}건이 업무별 근거 지도에 들어 있어요`
      : `실적 ${counts.portfolio_items}건이 등록돼 있어요`;
  }
  usePageHeader({ eyebrow: "회사 근거", title });
  return <>
    <PageHeaderTabs><WorkspaceViewTabs label="회사 근거 보기" tabs={tabs} value={view}
      onChange={key => setParams({ view: key })}/></PageHeaderTabs>
    <div className="company-wiki">
      {summary.error || !summary.data ? <WikiState error={summary.error}/> : <>
        {view === "overview" && <WikiOverview summary={summary.data}/>}
        {view === "portfolio" && <WikiPortfolio selected={params.get("project")}/>}
        {view === "work-units" && (summary.data.work_units_available ? <WikiTopics selected={params.get("topic")}/> : <p>업무별 근거 지도가 아직 없어요.</p>)}
        {view === "pages" && <WikiPages selected={params.get("page")}/>}
        {view === "log" && <section className="wiki-content"><h2>변경 이력</h2>
          {summary.data.log.length ? <table><thead><tr><th>날짜</th><th>내용</th></tr></thead><tbody>
            {summary.data.log.map((entry, i) => <tr key={i}><td><time>{entry.date}</time></td><td>{entry.text}</td></tr>)}
          </tbody></table> : <p>기록된 변경 이력이 없어요.</p>}</section>}
      </>}
    </div>
  </>;
}
