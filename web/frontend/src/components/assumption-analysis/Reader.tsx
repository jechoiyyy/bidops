import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {Button} from '@astryxdesign/core/Button';
import {Token} from '@astryxdesign/core/Token';
import {Table, proportional} from '@astryxdesign/core/Table';
import type {Analysis, EvidenceLink, EconomicRow, Report} from './types';
import {kindLabels} from './types';
import '../../styles/assumption-analysis.css';

const money = (value: string) => `${Number(value).toLocaleString('ko-KR')}원`;
const warningLabels: Record<string,string> = {numbers_unverified:'숫자 근거 대조 미확인',unlinked:'근거 미연결',quote_mismatch:'인용 불일치',source_kind_mismatch:'사실·가정 출처 불일치',source_missing:'근거 없음',kind_unrecognized:'분류 미확인',references_unreadable:'근거 형식 미확인',reference_unreadable:'근거 형식 미확인'};
function textReport(data: Analysis, report: Report) {
  return ['# 1489번 가정 분석', '실제 Luna 참조 분석 · 품질 미측정 · 가상 회사 정보 포함',
    report.complete?'완성 보고서':'부분 결과 · 최종 보고서 미완료', ...report.warnings, `입력 ${data.input_sha256}`, ...report.sections.flatMap(section=>[
      `## ${section.title}`, ...section.paragraphs.map(p=>`[${kindLabels[p.kind]}] ${p.body}\n${p.refs.map(r=>`[${r.source_id}: ${r.status}] ${r.quote}`).join('\n')}\n${p.warnings.map(w=>warningLabels[w] || w).join(' · ')}`)]),
    '## 경제성 12조합 — 가정상 잔액', '6/12개월은 실제 잔여 계약기간이 아닌 민감도 분석. 원 단위 반올림, 중간 반올림 없음.',
    '|기간|가격 비율|지원비|VAT 제외 매출 가정|원가|가정상 잔액|', '|---|---|---|---|---|---|',
    ...data.scenario.economics.rows.map(r=>`|${r.months}개월|${Number(r.price_ratio)*100}%|${money(r.support_cost_won)}|${money(r.revenue_ex_vat_won)}|${money(r.cost_won)}|${money(r.assumed_balance_won)}|`),
    '## 입력 근거', ...data.sources.map(s=>`### ${s.id} · ${kindLabels[s.kind]}\n${s.text}\n${JSON.stringify(s.locations)}`)].join('\n\n');
}

export function AssumptionReader({data, report}: {data: Analysis; report: Report}) {
  const [active, setActive] = useState(report.sections[0]?.key || '');
  const [focus, setFocus] = useState(false), [large, setLarge] = useState(false);
  const [links, setLinks] = useState<EvidenceLink[] | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null), sourceHeading = useRef<HTMLHeadingElement>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const restore = useRef<{element: HTMLElement; offset: number} | null>(null);
  function preserve(change: ()=>void, anchor?: HTMLElement | null) {
    const element=anchor || scroll.current?.querySelector<HTMLElement>(`[data-section="${active}"]`);
    if(element) restore.current={element,offset:element.getBoundingClientRect().top};
    change();
  }
  useLayoutEffect(()=>{
    if(restore.current && scroll.current){scroll.current.scrollTop+=restore.current.element.getBoundingClientRect().top-restore.current.offset;restore.current=null;}
  },[focus,large,links]);
  function close() {preserve(()=>setLinks(null),trigger.current); requestAnimationFrame(()=>trigger.current?.focus({preventScroll:true}));}
  useEffect(()=>{if(links) sourceHeading.current?.focus({preventScroll:true});},[links]);
  useEffect(()=>{
    const el=scroll.current;
    if(!el) return;
    const update=()=>{let next=report.sections[0]?.key || ''; for(const s of report.sections){const section=el.querySelector<HTMLElement>(`[data-section="${s.key}"]`); if(section && section.getBoundingClientRect().top <= el.getBoundingClientRect().top+100) next=s.key;} setActive(next);};
    el.addEventListener('scroll',update,{passive:true}); return ()=>el.removeEventListener('scroll',update);
  },[report]);
  useEffect(()=>{if(!links)return; const key=(e: KeyboardEvent)=>{if(e.key==='Escape'){e.preventDefault(); close();}}; window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[links]);
  function download() {const url=URL.createObjectURL(new Blob([textReport(data,report)],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`1489-가정분석-${data.id}.md`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function goto(key: string) {const heading=scroll.current?.querySelector<HTMLElement>(`[data-section="${key}"] h2`);heading?.scrollIntoView({block:'start'}); heading?.focus({preventScroll:true});setActive(key);}
  const columns = [
    {key:'months',header:'기간',width:proportional(1),renderCell:(r:EconomicRow)=>`${r.months}개월${r.sensitivity_only?' (민감도)':''}`},
    {key:'price_ratio',header:'가격',width:proportional(1),renderCell:(r:EconomicRow)=>`${Number(r.price_ratio)*100}%`},
    ...([['support_cost_won','지원비'],['revenue_ex_vat_won','VAT 제외 매출'],['cost_won','원가'],['assumed_balance_won','가정상 잔액']] as const).map(([key,header])=>({key,header,width:proportional(1.3),renderCell:(r:EconomicRow)=>money(r[key])})),
  ];
  return <section className={`assumption-reader ${focus?'is-focused':''} ${large?'is-large':''} ${links?'has-evidence':''}`} aria-label="가정 분석 보고서">
    <header className="assumption-toolbar"><strong>1489번 가정 분석 · A안</strong><div><Button label={large?'기본 글자':'글자 크게'} variant="ghost" onClick={()=>preserve(()=>setLarge(!large))}/><Button label={focus?'기본 화면':'본문 집중'} variant="ghost" onClick={()=>preserve(()=>setFocus(!focus))}/><Button label="본문 내려받기" onClick={download}/></div></header>
    <div className="assumption-scroll" ref={scroll}>
      <div className="assumption-grid">
        <nav className="assumption-toc" aria-label="보고서 목차"><strong>보고서 목차</strong>{report.sections.map((s,i)=><a key={`${s.key}-${i}`} href={`#assumption-${s.key}`} aria-current={active===s.key?'location':undefined} onClick={e=>{e.preventDefault();goto(s.key);}}>{String(i+1).padStart(2,'0')} · {s.title}</a>)}</nav>
        <article className="assumption-prose" aria-label="가정 분석 본문">
          <header><h1>1489번 가정 분석 보고서</h1><p>실제 Luna 참조 분석 · 품질 미측정</p><Token label="가상 회사 정보 포함"/><p>모델 내용의 정확성은 미측정입니다. 사실 주장·원문·가정을 대조하십시오. 추적 승인과 최종 Go/No-Go는 별도입니다.</p>{report.warnings.length>0&&<p>구성 경고: {report.warnings.join(" · ")}</p>}{!report.complete&&<p role="status">부분 결과 · 최종 보고서 미완료</p>}</header>
          {report.sections.map((s,i)=><section key={`${s.key}-${i}`} id={`assumption-${s.key}`} data-section={s.key} className="assumption-section"><header><small>{String(i+1).padStart(2,'0')} · 조건 → 회사 영향 → 확인 사항 → 판단 변경</small><h2 tabIndex={-1}>{s.title}</h2></header>{s.paragraphs.map((p,j)=><div key={j} className={s.key==='assessment'&&j===0?'assumption-takeaway':''}><Token label={kindLabels[p.kind]}/><p>{p.body}</p>{p.warnings.length>0&&<p className="assumption-warning">{p.warnings.map(w=>warningLabels[w]||w).join(' · ')}</p>}{p.refs.length>0&&<button className="assumption-citation" onClick={e=>{trigger.current=e.currentTarget;preserve(()=>setLinks(p.refs),e.currentTarget);}}>근거 {p.refs.length}개 확인</button>}</div>)}</section>)}
          <section aria-label="경제성 계산표"><h2>12개 조합 · 가정상 잔액</h2><p>월 300만원 + 준비비 200만원 + 지원비. VAT 제외 매출 가정 = 35,199,815 ÷ 1.1 × 가격 비율. 원 단위 반올림이며 중간값은 반올림하지 않습니다.</p><p>6·12개월은 실제 잔여 계약기간이 아닌 민감도 분석입니다. 차액은 확정 이익이 아닙니다.</p><div className="assumption-table"><Table data={data.scenario.economics.rows} columns={columns} idKey="id" density="balanced"/></div></section>
        </article>
        {links && <aside className="assumption-evidence" aria-label="원문 근거 패널"><header><h2 tabIndex={-1} ref={sourceHeading}>원문 근거</h2><Button label="근거 닫기" variant="ghost" onClick={close}/></header>{links.map((link,i)=>{const source=data.sources.find(s=>s.id===link.source_id); return <section key={i}><h3>{source?kindLabels[source.kind]:'근거 미연결'}</h3><p>{link.source_id} · {warningLabels[link.status]||'인용 문자열 일치 · 의미 미검증'}</p><h4>모델 인용</h4><p>{link.quote || '인용 없음'}</p>{source?<><h4>승인된 입력 원문</h4><p>{source.text}</p><details><summary>원문 위치</summary><pre>{JSON.stringify(source.locations,null,2)}</pre></details></>:<p>존재하는 원문에 연결되지 않았습니다. 실제 근거로 취급하지 않습니다.</p>}</section>;})}</aside>}
      </div>
    </div>
    <footer className="assumption-footer">현재 읽는 절 · {report.sections.find(s=>s.key===active)?.title}</footer>
  </section>;
}
