import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { TechnicalInfo } from "../common/TechnicalInfo";
import { wiki, type WikiFact, type WikiKind, type WikiLog, type WikiSummary } from "../../lib/companyWikiApi";
import { wikiUrl } from "./WikiBody";
import { WikiState, wikiValue } from "./WikiState";
import {
  count, factText, groupFacts, isBlank, LEVELS, leadFirst, levelCounts, levelKey, registrationBuckets, splitList, wonInManwon,
  type FactGroup, type LevelKey,
} from "./profileOverview";

/** 회사 근거 개요 — 2026-11-25 시안 A(요약 대시보드). 값은 프로필 응답 그대로이고 확인 수준을 값마다 보인다. */

const kinds = { rule: "규칙", capability: "역량", category: "분류", glossary: "용어집", portfolio: "실적" };
type Section = { key: string; label: string | null; facts: WikiFact[] };

function Level({ level, text = false }: { level: string | null; text?: boolean }) {
  const key = levelKey(level);
  const info = LEVELS.find(item => item.key === key);
  const label = info?.label ?? wikiValue(level);
  return <span className={`wiki-lv wiki-lv-${key ?? "other"}${text ? "" : " is-dot"}`} title={info ? `${info.label} · ${info.note}` : `확인 수준 ${label}`}>
    <span className={text ? undefined : "visually-hidden"}>{label}</span></span>;
}

function Value({ fact }: { fact: WikiFact }) {
  return isBlank(fact) ? <span className="wiki-ov-empty">{factText(fact)}</span> : <>{factText(fact)}</>;
}

function TrustBar({ facts, changed }: { facts: WikiFact[]; changed: string | null }) {
  const { counts, other } = levelCounts(facts);
  return <div className="wiki-ov-trust">
    <p className="wiki-ov-trust-head"><span>프로필 값 {facts.length}개의 확인 수준</span>
      {changed && <span>마지막으로 바뀐 날 · <time>{changed}</time></span>}</p>
    <div className="wiki-ov-bar" role="img" aria-label={LEVELS.map(level => `${level.label} ${counts[level.key]}개`).join(", ")}>
      {LEVELS.map(level => counts[level.key] > 0 && <i key={level.key} className={`wiki-seg-${level.key}`} style={{ flexGrow: counts[level.key] }}/>)}
    </div>
    <ul className="wiki-ov-legend" aria-label="확인 수준의 뜻">
      {LEVELS.map(level => <li key={level.key} title={level.note}><Level level={level.key === "none" ? null : level.key}/>
        {level.label}<b>{counts[level.key]}</b></li>)}
      {other > 0 && <li>그 밖의 표시 <b>{other}</b></li>}
    </ul>
  </div>;
}

function Identity({ name, fact }: { name: string | null; fact: (path: string) => WikiFact | undefined }) {
  const line: [string, string][] = [["대표", "company.ceo"], ["본점", "company.region"], ["주소", "company.address"], ["설립", "company.founded"],
    ["기업 규모", "company.size"], ["임직원", "company.employees"], ["사업자", "company.biz_no"]];
  const english = fact("company.name_en");
  return <div>
    <h2 className="wiki-ov-name">{wikiValue(name)}{english && !isBlank(english) && <small>{factText(english)}</small>}</h2>
    <p className="wiki-ov-id">{line.map(([label, path]) => {
      const item = fact(path);
      return item && !isBlank(item) && <span key={path}>{label} <b>{factText(item)}</b></span>;
    })}</p>
  </div>;
}

function Coverage({ counts }: { counts: WikiSummary["counts"] }) {
  const rows: [string, number | null][] = [["등록 실적", counts.portfolio_items], ["실적 원문 페이지가 있는 실적", counts.portfolio_pages],
    ["요구사항까지 정리돼 근거 지도에 든 실적", counts.ingested_projects]];
  const top = counts.portfolio_items || 1;
  return <article className="wiki-ov-card" aria-labelledby="wiki-ov-coverage">
    <h3 id="wiki-ov-coverage">근거 자료 범위 <Link to={wikiUrl("portfolio")}>실적 보기</Link></h3>
    <dl className="wiki-ov-funnel">{rows.map(([label, value]) => <div key={label}>
      <dt>{label}</dt><dd>{value === null ? "값 없음" : `${value}건`}</dd>
      <span aria-hidden="true"><i style={{ width: `${Math.min(100, (value ?? 0) / top * 100)}%` }}/></span></div>)}</dl>
    {counts.work_units !== null && <p className="wiki-ov-foot">근거 지도 · 업무 주제 {counts.work_topics ?? "값 없음"}개 · 업무 {counts.work_units}가지 · 근거 연결 {
      counts.evidence_links === null ? "값 없음" : counts.evidence_links.toLocaleString("ko-KR")}건</p>}
  </article>;
}

function Revenue({ facts }: { facts: WikiFact[] }) {
  const amounts = facts.map(fact => wonInManwon(fact.display_value));
  const top = Math.max(1, ...amounts.map(amount => amount ?? 0));
  return <article className="wiki-ov-card" aria-labelledby="wiki-ov-revenue">
    <h3 id="wiki-ov-revenue">매출액 <LevelSummary facts={facts}/></h3>
    <ul className="wiki-ov-revenue">{facts.map((fact, i) => <li key={fact.path}>
      <b><Value fact={fact}/></b>
      {amounts[i] !== null && <i aria-hidden="true" style={{ height: `${Math.max(8, (amounts[i] ?? 0) / top * 56)}px` }}/>}
      <span>{fact.path.split(".").at(-1)}</span></li>)}</ul>
  </article>;
}

/** 카드 머리의 확인 수준: 한 가지면 그 이름을, 섞였으면 값마다 표식을 본다. */
function LevelSummary({ facts }: { facts: WikiFact[] }) {
  const levels = [...new Set(facts.map(fact => fact.level))];
  return levels.length === 1 ? <Level level={levels[0]} text/> : null;
}

function People({ fact, grades }: { fact: (path: string) => WikiFact | undefined; grades: WikiFact[] }) {
  const total = fact("people.total_tech_staff");
  const numbers = grades.map(item => count(item.display_value));
  const sum = numbers.reduce<number>((a, b) => a + (b ?? 0), 0);
  const extras: [string, string[]][] = [["PM 수행 가능", ["people.roles.pm_capable"]], ["정보처리기사", ["people.certifications.정보처리기사"]],
    ["정보보안기사 · PMP", ["people.certifications.정보보안기사", "people.certifications.PMP"]]];
  return <article className="wiki-ov-card" aria-labelledby="wiki-ov-people">
    <h3 id="wiki-ov-people">기술 인력 {total && <Level level={total.level} text/>}</h3>
    {total && <p className="wiki-ov-big"><Value fact={total}/></p>}
    {sum > 0 && numbers.every(n => n !== null) && <p className="wiki-ov-stack" role="img"
      aria-label={grades.map(item => `${item.label ?? item.path} ${factText(item)}`).join(", ")}>
      {grades.map((item, i) => (numbers[i] ?? 0) > 0 && <i key={item.path} style={{ flexGrow: numbers[i] ?? 0 }} title={`${item.label ?? item.path} ${factText(item)}`}>
        {(numbers[i] ?? 0) / sum < 0.12 ? numbers[i] : `${(item.label ?? item.path).replace(/ 기술자$/, "")} ${numbers[i]}`}</i>)}</p>}
    <dl className="wiki-ov-kv">{extras.map(([label, paths]) => {
      const items = paths.map(fact).filter((item): item is WikiFact => !!item);
      return items.length > 0 && <div key={label}><dt>{label}</dt><dd>{items.map((item, i) => <span key={item.path}>
        {i > 0 && <span className="wiki-ov-sep" aria-hidden="true">·</span>}<Level level={item.level}/><Value fact={item}/></span>)}</dd></div>;
    })}</dl>
  </article>;
}

function Regions({ facts }: { facts: WikiFact[] }) {
  const names = [...new Set(facts.map(fact => fact.path.split(".")[2]))];
  return <article className="wiki-ov-card" aria-labelledby="wiki-ov-regions">
    <h3 id="wiki-ov-regions">지역별 상주 <LevelSummary facts={facts}/></h3>
    <ul className="wiki-ov-regions">{names.map(name => {
      const ok = facts.find(fact => fact.path.endsWith(`.${name}.ok`));
      const people = facts.find(fact => fact.path.endsWith(`.${name}.max_people`));
      const yes = ok?.display_value === "가능";
      return <li key={name} className={yes ? "is-ok" : undefined}><span>{name}</span>
        <b>{ok ? factText(ok) : "값 없음"}{yes && people && !isBlank(people) ? ` · ${factText(people)}` : ""}</b></li>;
    })}</ul>
  </article>;
}

function Tile({ group }: { group: FactGroup }) {
  return <li className="wiki-ov-tile"><strong>{group.title}</strong>
    <ul>{leadFirst(group).map(({ fact, sub }) => <li key={fact.path}><Level level={fact.level}/>{sub && <span>{sub}</span>}<em><Value fact={fact}/></em></li>)}</ul></li>;
}

function Registrations({ facts }: { facts: WikiFact[] }) {
  const { buckets, disqualifiers } = registrationBuckets(groupFacts(facts));
  const total = buckets.reduce((n, bucket) => n + bucket.groups.length, 0) + disqualifiers.length;
  return <section className="wiki-ov-panel" aria-labelledby="wiki-ov-reg">
    <h3 id="wiki-ov-reg">등록·인증 <span>{total}가지 · 같은 대상의 시기·유효기간은 한 칸에 모았어요</span></h3>
    {buckets.map(bucket => <div key={bucket.title} className="wiki-ov-bucket"><h4>{bucket.title}</h4>
      <ul className="wiki-ov-tiles">{bucket.groups.map(group => <Tile key={group.key} group={group}/>)}</ul></div>)}
    {disqualifiers.length > 0 && <div className="wiki-ov-bucket"><h4>결격 사유</h4>
      <ul className="wiki-ov-clean">{disqualifiers.flatMap(group => group.items).map(({ fact }) =>
        <li key={fact.path}><Level level={fact.level}/>{fact.label ?? fact.path} <b><Value fact={fact}/></b></li>)}</ul></div>}
  </section>;
}

function Policy({ facts }: { facts: WikiFact[] }) {
  return <section className="wiki-ov-panel" aria-labelledby="wiki-ov-policy"><h3 id="wiki-ov-policy">입찰 방침</h3>
    <dl className="wiki-ov-policy">{facts.map(fact => <div key={fact.path} className={fact.path === "policy.no_bid_if" ? "is-nobid" : undefined}>
      <dt><Level level={fact.level}/>{fact.label ?? fact.path}</dt><dd><Value fact={fact}/></dd></div>)}</dl>
  </section>;
}

function Domains({ fact, solutions }: { fact: WikiFact | undefined; solutions: FactGroup[] }) {
  if (!fact && !solutions.length) return null;
  return <section className="wiki-ov-panel" aria-labelledby="wiki-ov-domains"><h3 id="wiki-ov-domains">사업 분야·자체 솔루션</h3>
    {fact && !isBlank(fact) && <ul className="wiki-ov-chips" aria-label={fact.label ?? fact.path}>
      {splitList(factText(fact)).map(part => <li key={part}>{part}</li>)}</ul>}
    {solutions.length > 0 && <ul className="wiki-ov-solutions">{solutions.map(group => {
      const name = group.items.find(item => item.fact.path.endsWith(".name"))?.fact;
      const desc = group.items.find(item => item.fact.path.endsWith(".desc"))?.fact;
      return <li key={group.key}><b>{name ? factText(name) : group.title}</b>{desc && !isBlank(desc) && <span> · {factText(desc)}</span>}</li>;
    })}</ul>}
  </section>;
}

function Skills({ facts }: { facts: WikiFact[] }) {
  const stack = facts.filter(fact => fact.path.startsWith("capabilities.tech_stack."));
  const rest = facts.filter(fact => !fact.path.startsWith("capabilities.tech_stack.") && fact.path !== "capabilities.domains" &&
    !fact.path.startsWith("capabilities.solutions"));
  if (!stack.length && !rest.length) return null;
  const shown = [...stack, ...rest];
  const estimated = shown.filter(fact => fact.level === "estimate").length;
  return <section className="wiki-ov-panel" aria-labelledby="wiki-ov-skills">
    <h3 id="wiki-ov-skills">기술·경험 {estimated > 0 && <span>{shown.length}개 중 {estimated}개가 추정 값이에요</span>}</h3>
    <dl className="wiki-ov-skills">
      {stack.map(fact => <div key={fact.path}><dt><Level level={fact.level}/>{(fact.label ?? fact.path).replace(/^기술 · /, "")}</dt>
        <dd>{isBlank(fact) ? <Value fact={fact}/> : <ul className="wiki-ov-chips">{splitList(factText(fact)).map(part => <li key={part}>{part}</li>)}</ul>}</dd></div>)}
      {rest.map(fact => <div key={fact.path}><dt><Level level={fact.level}/>{fact.label ?? fact.path}</dt><dd><Value fact={fact}/></dd></div>)}
    </dl>
  </section>;
}

function Recent({ log }: { log: WikiLog[] }) {
  const ingests = log.filter(entry => entry.kind === "ingest").slice(0, 5);
  if (!ingests.length) return null;
  return <section className="wiki-ov-panel" aria-labelledby="wiki-ov-recent">
    <h3 id="wiki-ov-recent">최근 넣은 실적 <Link to={wikiUrl("log")}>변경 이력 {log.length}건</Link></h3>
    <ul className="wiki-ov-log">{ingests.map((entry, i) => <li key={i}>
      {entry.date ? <time>{entry.date}</time> : <span>{wikiValue(null)}</span>}
      {entry.project ? <Link to={wikiUrl("portfolio", { project: entry.project })}>{entry.project_title ?? entry.project}</Link> : <span>{entry.project_title ?? entry.text}</span>}
      <span>요구사항 {entry.requirement_count ?? "값 없음"}{entry.requirement_count === null ? "" : "건"}</span></li>)}</ul>
  </section>;
}

function AllFacts({ sections, levels }: { sections: Section[]; levels: Record<LevelKey, number> }) {
  const total = sections.reduce((n, section) => n + section.facts.length, 0);
  return <details className="wiki-ov-all"><summary>프로필 값 전체 보기 <span>{total}개 · 위에 없는 세부 값도 모두 여기 있어요 · 담당자 확인 전 값 {levels.demo + levels.estimate + levels.none}개</span></summary>
    <div className="wiki-ov-all-body">
      <ul className="wiki-ov-meanings" aria-label="확인 수준의 뜻">{LEVELS.map(level => <li key={level.key}>
        <Level level={level.key === "none" ? null : level.key}/>{level.label} · {level.note}</li>)}</ul>
      {sections.map(section => <table key={section.key}>
      <caption>{section.label ?? section.key}</caption><thead><tr><th>항목</th><th>값</th><th>확인 수준</th></tr></thead>
      <tbody>{section.facts.map(fact => <tr key={fact.path}><th scope="row">{fact.label ?? fact.path}</th>
        <td><Value fact={fact}/></td><td><Level level={fact.level} text/></td></tr>)}</tbody></table>)}
    </div>
  </details>;
}

export function WikiOverview({ summary }: { summary: WikiSummary }) {
  const profile = useQuery(wiki.profile);
  const counts = summary.counts;
  const sections: Section[] = profile.data?.sections ?? [];
  const facts = sections.flatMap(section => section.facts);
  const byPath = new Map(facts.map(fact => [fact.path, fact]));
  const fact = (path: string) => byPath.get(path);
  const under = (prefix: string) => facts.filter(item => item.path.startsWith(prefix));
  const sectionFacts = (key: string) => sections.find(section => section.key === key)?.facts ?? [];
  const revenue = under("company.revenue_krw.");
  const grades = under("people.headcount_by_grade.");
  const regions = under("people.onsite_capacity.");
  const capabilities = sectionFacts("capabilities");
  const solutions = groupFacts(capabilities.filter(item => item.path.startsWith("capabilities.solutions")));
  return <section className="wiki-content wiki-ov">
    <header className="wiki-ov-hero">
      <Identity name={summary.company_name} fact={fact}/>
      {facts.length > 0 ? <TrustBar facts={facts} changed={summary.last_changed}/>
        : summary.last_changed && <p>마지막으로 바뀐 날 · <time>{summary.last_changed}</time></p>}
    </header>
    {profile.error || !profile.data ? <><div className="wiki-ov-cards"><Coverage counts={counts}/></div><WikiState error={profile.error}/></> : <>
      {(() => {
        const cards = [<Coverage key="coverage" counts={counts}/>,
          revenue.length > 0 && <Revenue key="revenue" facts={revenue}/>,
          (fact("people.total_tech_staff") || grades.length > 0) && <People key="people" fact={fact} grades={grades}/>,
          regions.length > 0 && <Regions key="regions" facts={regions}/>].filter(Boolean);
        return <div className="wiki-ov-cards" data-count={cards.length}>{cards}</div>;
      })()}
      {!sections.length ? <p>등록된 프로필 값이 없어요.</p> : <>
        <div className="wiki-ov-cols">
          {sectionFacts("registrations").length > 0 ? <Registrations facts={sectionFacts("registrations")}/> : <span/>}
          <div className="wiki-ov-side">
            {sectionFacts("policy").length > 0 && <Policy facts={sectionFacts("policy")}/>}
            <Domains fact={fact("capabilities.domains")} solutions={solutions}/>
          </div>
        </div>
        <div className="wiki-ov-cols">
          <Skills facts={capabilities}/>
          <Recent log={summary.log}/>
        </div>
        <AllFacts sections={sections} levels={levelCounts(facts).counts}/>
      </>}
    </>}
    <TechnicalInfo summary="기술 정보">
      <p>묶음 판 · <code>{summary.bundle_sha256.slice(0, 12)}</code><br/>위키 식별 이름 · {summary.slug}<br/>
        이름표 · {summary.labels_available ? "사용" : "사용 안 함"}</p>
      <p>{Object.entries(counts.pages_by_kind).map(([kind, n]) => `${kinds[kind as WikiKind]} ${n}쪽`).join(" · ")}</p>
      {facts.filter(item => item.label !== null).map(item => <p key={item.path}><small>{item.label} · {item.path}</small></p>)}
    </TechnicalInfo>
  </section>;
}
