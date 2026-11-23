import { WikiSplit } from "./WikiSplit";
import { WikiUpload } from "./WikiUpload";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { wiki, type WikiFact, type WikiKind, type WikiProject, type WikiSummary } from "../../lib/companyWikiApi";
import { WikiBody, wikiUrl } from "./WikiBody";
import { WikiState, wikiValue } from "./WikiState";

const kinds = { rule: "규칙", capability: "역량", category: "분류", glossary: "용어집", portfolio: "실적" };
const levels = new Map(Object.entries({ confirmed: "확인됨", demo: "데모값", public: "공개 자료", estimate: "추정" }));

const sectionNames = new Map(Object.entries({
  company: "회사", registrations: "등록·인증", people: "인력", capabilities: "역량", tech_stack: "기술", policy: "입찰 방침",
}));

export function WikiOverview({ summary }: { summary: WikiSummary }) {
  const profile = useQuery(wiki.profile);
  const sections = new Map<string, WikiFact[]>();
  for (const fact of profile.data?.facts ?? []) {
    if (fact.path === fact.section) continue;
    if (!sections.has(fact.section)) sections.set(fact.section, []);
    sections.get(fact.section)!.push(fact);
  }
  const counts = summary.counts;
  const stats = {
    "실적 목록": counts.portfolio_items, "실적 페이지": counts.portfolio_pages,
    "지도에 넣은 실적": counts.ingested_projects, "업무 주제": counts.work_topics,
    "업무 단위": counts.work_units, "근거 연결": counts.evidence_links, "근거 없는 단위": counts.units_without_evidence,
  };
  return <section className="wiki-content">
    <h2>{summary.company_name ? wikiValue(summary.company_name) : "회사 자료"}</h2>
    <p>묶음 판 <code>{summary.bundle_sha256.slice(0, 12)}</code></p>
    <dl className="wiki-stats">{Object.entries(stats).map(([label, value]) =>
      <div key={label}><dt>{label}</dt><dd>{wikiValue(value)}</dd></div>)}</dl>
    <p>{Object.entries(counts.pages_by_kind).map(([kind, count]) => `${kinds[kind as WikiKind]} ${count}쪽`).join(" · ")}</p>
    <h2>프로필 값</h2>
    {profile.error || !profile.data ? <WikiState error={profile.error}/> :
      sections.size === 0 ? <p>등록된 프로필 값이 없어요.</p> :
      Array.from(sections, ([section, facts]) => <table key={section}>
        <caption>{sectionNames.get(section) ?? section}</caption><thead><tr><th>항목</th><th>값</th><th>확인 수준</th></tr></thead>
        <tbody>{facts.map(fact => <tr key={fact.path}><th scope="row">{fact.path}</th>
          <td>{wikiValue(fact.value)}</td><td>{fact.level === null ? "표시 없음" : levels.get(fact.level) ?? wikiValue(fact.level)}</td>
        </tr>)}</tbody></table>)}
  </section>;
}

function Detail({ kind, slug }: { kind: WikiKind; slug: string }) {
  const page = useQuery(wiki.detail(kind, slug));
  const index = useQuery(wiki.pages);
  if (page.error || !page.data) return <WikiState error={page.error}/>;
  if (index.error || !index.data) return <WikiState error={index.error}/>;
  return <article key={slug}><h2>{page.data.title}</h2><WikiBody body={page.data.body} pages={index.data.pages}/></article>;
}

function ingestion(item: WikiProject) {
  const state = item.ingested === null ? "근거 지도 없음" : item.ingested ? "넣음" : "미반영";
  const requirements = item.requirement_count === null ? "요구사항 목록 없음" : `요구사항 ${item.requirement_count}건`;
  return `${state} · ${item.has_page ? requirements : "페이지 없음"}`;
}

export function WikiPortfolio({ selected, uploadEnabled }: { selected: string | null; uploadEnabled: boolean }) {
  const projects = useQuery(wiki.portfolio);
  if (projects.error || !projects.data) return <WikiState error={projects.error}/>;
  if (!projects.data.items.length) return <p>등록된 실적이 없어요.</p>;
  const current = projects.data.items.find(item => item.id === selected);
  return <WikiSplit selected={selected} list={projects.data.items.map(item =>
    <Link key={item.id} to={wikiUrl("portfolio", { project: item.id })} aria-current={item === current ? "page" : undefined}>
      <span>실적 {item.id}</span><strong>{wikiValue(item.title)}</strong>
      <span>발주처 · {wikiValue(item.client)}</span>
      <span>기간 · {wikiValue(item.period_start)} ~ {wikiValue(item.period_end)}</span>
      <span>근거 지도 반영 · {ingestion(item)}</span>
    </Link>)}>
    {current && uploadEnabled && <WikiUpload key={current.id} project={current}/>}
    {current ? current.has_page ? <Detail kind="portfolio" slug={current.id}/> : <p>실적 페이지가 없어요.</p>
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
      <span>단위 {topic.units.length}개 · 근거 없는 단위 {topic.units.filter(unit => !unit.projects.length).length}개</span>
    </Link>)}>
    {current ? <><h2>{current.title}</h2><p>범위 · {wikiValue(current.scope)}</p>
      {!current.units.length && <p>등록된 업무 단위가 없어요.</p>}
      {current.units.map(unit => <section className="wiki-unit" key={unit.id}>
        <h3>{unit.title}</h3><p>포함 범위 · {wikiValue(unit.covers)}</p>{unit.not !== "" && <p>제외 범위 · {wikiValue(unit.not)}</p>}
        <h4>근거 실적</h4>
        {unit.projects.length ? <ul>{unit.projects.map(project => <li key={project.project}>
          <Link to={wikiUrl("portfolio", { project: project.project })}>{project.project}</Link> {project.req_ids.join(", ")}
        </li>)}</ul> : <p>기록 없음</p>}
        {unit.no_record.map((memo, i) => <p key={i}>기록 없음 확인 메모 · {wikiValue(memo.note)}<br/>
          기준일 · {wikiValue(memo.as_of)} · 출처 · {wikiValue(memo.source)}</p>)}
      </section>)}</> : <p>{selected ? "선택한 주제를 찾을 수 없어요." : "업무 단위를 볼 주제를 선택해 주세요."}</p>}
  </WikiSplit>;
}

export function WikiPages({ selected }: { selected: string | null }) {
  const pages = useQuery(wiki.pages);
  if (pages.error || !pages.data) return <WikiState error={pages.error}/>;
  const entries = pages.data.pages.filter(entry => entry.kind !== "portfolio" && !(entry.kind === "capability" && entry.slug.startsWith("work-")));
  if (!entries.length) return <p>등록된 규칙이나 페이지가 없어요.</p>;
  const current = entries.find(entry => `${entry.kind}/${entry.slug}` === selected);
  return <WikiSplit selected={selected} list={(["rule", "capability", "category", "glossary"] as const).map(kind => {
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
