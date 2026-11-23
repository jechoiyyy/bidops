import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { wiki, type Requirement, type WikiUnit } from "../../lib/companyWikiApi";
import { wikiUrl } from "./WikiBody";
import { WikiState, wikiValue } from "./WikiState";

export function Requirements({ project, items }: { project: string; items: Requirement[] }) {
  return <ul>{items.map(item => <li key={item.req_id}><RequirementRow project={project} item={item}/></li>)}</ul>;
}

function RequirementRow({ project, item }: { project: string; item: Requirement }) {
  const [open, setOpen] = useState(false);
  const result = useQuery({ ...wiki.requirement(project, item.req_id), enabled: open });
  const missing = result.error instanceof ApiError && result.error.code === "company_wiki_requirement_not_found";
  return <>
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{item.name ?? item.req_id}</button>
    {open && <div className="wiki-excerpt">
      {result.error ? <p role="alert">{missing ? "요구사항 원문을 찾을 수 없어요." : "요구사항 원문을 불러오지 못했어요."}</p> :
        result.data ? <p>{result.data.text || "기록된 원문이 없어요."}</p> : <p role="status">원문을 불러오고 있어요.</p>}
      <small>실적 {project} · 요구사항 {item.req_id}</small>
    </div>}
  </>;
}

function EvidenceUnit({ unit }: { unit: WikiUnit }) {
  const [expanded, setExpanded] = useState(false);
  return <section className="wiki-unit">
    <h3>{unit.title}</h3><p>포함 범위 · {wikiValue(unit.covers)}</p>
    {unit.not !== "" && <p>제외 범위 · {wikiValue(unit.not)}</p>}
    <p>{unit.project_count ? `${unit.project_count}개 사업에서 수행 · 최근 ${unit.latest_year === null ? "연도 값 없음" : unit.latest_year + "년"}` : "수행 기록 없음"}</p>
    {(expanded ? unit.projects : unit.projects.slice(0, 3)).map(project => <section key={project.project}>
      <h4><Link to={wikiUrl("portfolio", { project: project.project })}>{wikiValue(project.title)}</Link>
        {" · "}{wikiValue(project.client)} · {wikiValue(project.year)}</h4>
      <Requirements project={project.project} items={project.requirements}/>
    </section>)}
    {unit.projects.length > 3 && <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      {expanded ? "사업 접기" : `나머지 ${unit.projects.length - 3}개 사업 보기`}</button>}
    {unit.no_record.map((memo, i) => <p key={i}>기록 없음 확인 메모 · {wikiValue(memo.note)}<br/>
      기준일 · {wikiValue(memo.as_of)} · 출처 · {wikiValue(memo.source)}</p>)}
  </section>;
}

export function TopicDetail({ id }: { id: string }) {
  const query = useQuery(wiki.topic(id));
  if (!query.data || query.error) return <WikiState error={query.error}/>;
  return <><h2>{query.data.title}</h2><p>범위 · {wikiValue(query.data.scope)}</p>
    {query.data.units.length ? query.data.units.map(unit => <EvidenceUnit key={unit.id} unit={unit}/>) :
      <p>등록된 업무 단위가 없어요.</p>}
  </>;
}
