import { useState } from "react";
import { Requirements, TopicDetail } from "./WikiEvidence";
import { WikiSplit } from "./WikiSplit";
import { WikiUpload } from "./WikiUpload";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { wiki, type WikiKind, type WikiProject } from "../../lib/companyWikiApi";
import { WikiBody, wikiUrl } from "./WikiBody";
import { WikiState, wikiValue } from "./WikiState";

const kinds = { rule: "규칙", capability: "역량", category: "분류", glossary: "용어집", portfolio: "실적" };

function Detail({ kind, slug }: { kind: WikiKind; slug: string }) {
  const page = useQuery(wiki.detail(kind, slug));
  const index = useQuery(wiki.pages);
  if (page.error || !page.data) return <WikiState error={page.error}/>;
  if (index.error || !index.data) return <WikiState error={index.error}/>;
  return <article key={slug}><h2>{page.data.title}</h2><WikiBody body={page.data.body} pages={index.data.pages}/></article>;
}

function ingestion(item: WikiProject) {
  if (!item.has_page) return "상세 페이지 없음";
  return item.requirement_count === null ? "요구사항 목록 없음" : `요구사항 ${item.requirement_count}건 정리됨`;
}

function ProjectDetail({ id }: { id: string }) {
  const result = useQuery(wiki.project(id));
  const [raw, setRaw] = useState(false);
  const data = result.data;
  if (!data || result.error) return <WikiState error={result.error}/>;
  return <article><h2>{wikiValue(data.title)}</h2>
    <p>발주처 · {wikiValue(data.client)}<br/>기간 · {wikiValue(data.period_start)} ~ {wikiValue(data.period_end)}<br/>
      유형 · {wikiValue(data.type)}<br/>역할 · {wikiValue(data.role)}</p>
    <h3>수행한 범위</h3>
    {data.scope_lines.length ? <ul>{data.scope_lines.map((line, i) => <li key={i}>{line}</li>)}</ul> : <p>기록된 범위가 없어요.</p>}
    <h3>이 사업에서 수행한 업무</h3>
    {data.work_units.length ? data.work_units.map(topic => <section key={topic.topic_id}><h4>{topic.topic_title}</h4>
      <ul>{topic.units.map(unit => <li key={unit.id}><Link to={wikiUrl("work-units", { topic: topic.topic_id })}>
        {unit.title}</Link></li>)}</ul></section>) : <p>연결된 업무가 없어요.</p>}
    <h3>요구사항</h3>
    {data.requirements.length ? <Requirements project={id} items={data.requirements}/> : <p>정리된 요구사항이 없어요.</p>}
    {data.has_page && <details onToggle={event => setRaw(event.currentTarget.open)}><summary>위키 원문 보기</summary>
      {raw && <Detail kind="portfolio" slug={id}/>}</details>}
  </article>;
}

export function WikiPortfolio({ selected, uploadEnabled }: { selected: string | null; uploadEnabled: boolean }) {
  const projects = useQuery(wiki.portfolio);
  if (projects.error || !projects.data) return <WikiState error={projects.error}/>;
  if (!projects.data.items.length) return <p>등록된 실적이 없어요.</p>;
  const current = projects.data.items.find(item => item.id === selected);
  return <WikiSplit selected={selected} list={projects.data.items.map(item =>
    <Link key={item.id} to={wikiUrl("portfolio", { project: item.id })} aria-current={item === current ? "page" : undefined}>
      <strong>{wikiValue(item.title)}</strong>
      <span>{wikiValue(item.client)} · {wikiValue(item.period_start)} ~ {wikiValue(item.period_end)}</span>
      <span>{ingestion(item)}</span><small>실적 {item.id}</small>
    </Link>)}>
    {current && uploadEnabled && <WikiUpload key={current.id} project={current}/>}
    {current ? <ProjectDetail id={current.id}/>
      : <p>{selected ? "선택한 실적을 찾을 수 없어요." : "본문을 볼 실적을 선택해 주세요."}</p>}
  </WikiSplit>;
}

export function WikiTopics({ selected }: { selected: string | null }) {
  const topics = useQuery(wiki.topics);
  if (topics.error || !topics.data) return <WikiState error={topics.error}/>;
  if (!topics.data.topics.length) return <p>등록된 업무 주제가 없어요.</p>;
  const current = topics.data.topics.find(topic => topic.id === selected);
  return <WikiSplit selected={selected} list={topics.data.topics.map(topic =>
    <Link key={topic.id} to={wikiUrl("work-units", { topic: topic.id })} aria-current={topic === current ? "page" : undefined}>
      <strong>{topic.title}</strong>
      <span>업무 {topic.unit_count}가지 · 실적 {topic.project_count}건</span>
      {topic.units_without_evidence > 0 && <span>근거 없는 업무 {topic.units_without_evidence}가지</span>}
    </Link>)}>
    {current ? <TopicDetail id={current.id}/> : <p>{selected ? "선택한 주제를 찾을 수 없어요." : "업무 단위를 볼 주제를 선택해 주세요."}</p>}
  </WikiSplit>;
}

export function WikiPages({ selected }: { selected: string | null }) {
  const pages = useQuery(wiki.pages);
  if (pages.error || !pages.data) return <WikiState error={pages.error}/>;
  const entries = pages.data.pages.filter(entry => `${entry.kind}/${entry.slug}` === selected || (entry.kind !== "portfolio" && !entry.slug.startsWith("work-")));
  if (!entries.length) return <p>등록된 규칙이나 페이지가 없어요.</p>;
  const current = entries.find(entry => `${entry.kind}/${entry.slug}` === selected);
  return <WikiSplit selected={selected} list={(["rule", "capability", "category", "glossary", "portfolio"] as const).map(kind => {
    const group = entries.filter(entry => entry.kind === kind);
    return group.length > 0 && <section key={kind}><h3>{kinds[kind]}</h3>{group.map(entry =>
      <Link key={entry.slug} to={wikiUrl("pages", { page: `${kind}/${entry.slug}` })} aria-current={entry === current ? "page" : undefined}>
        {entry.title}
      </Link>)}</section>;
  })}>
    {current ? <Detail kind={current.kind} slug={current.slug}/> :
      <p>{selected ? "선택한 페이지를 찾을 수 없어요." : "본문을 볼 페이지를 선택해 주세요."}</p>}
  </WikiSplit>;
}
