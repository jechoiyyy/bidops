// An offline reading prototype of the approved single report; no API or persistence.
import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Button} from '@astryxdesign/core/Button';
import {Token} from '@astryxdesign/core/Token';
import {Table, proportional} from '@astryxdesign/core/Table';
import {ArrowLeft, ArrowUp, ArrowRight, BookOpen, Building2, CalendarDays, ChevronLeft, ChevronRight, CircleAlert, FileText, FolderSearch, LayoutDashboard, ListChecks, Maximize2, Minimize2, PanelRightClose, Quote, Route, Settings2, ShieldCheck, Type, X} from 'lucide-react';
import reportMarkdown from '../report.md';
import sourceMarkdown from '../report-source.md';

const sectionNames=['판단의 출발점','사업 목적과 과업','회사 근거와 부족한 자료','수행에 영향을 주는 조건','평가와 제안 준비','계약과 경제성','확인할 일','판단을 갱신할 조건'];
const sectionRoutes=['사업의 성격 → 판단의 전제','발주 목적 → 과업 → 완료 의무','확인된 경험 → 이번 요구와의 차이','문서 조건 → 수행 영향 → 확인 순서','평가 기준 → 설명할 내용 → 준비할 증거','계약 조건 → 책임과 비용 → 산정할 자료','확인할 질문 → 필요한 이유 → 다음 판단','확인 결과 → 참여 방식과 검토 방향'];
const tableTitles={2:'과업에서 산출물과 준비 사항까지',3:'요구 조건과 회사자료의 대조',5:'배점에 맞춰 준비할 설명과 증거',6:'비용이 발생하는 이유와 산정에 필요한 자료',7:'확인 시점과 다음 판단을 함께 정리'};
function parseBlocks(text){
  const lines=text.trim().split('\n'); const blocks=[];
  for(let i=0;i<lines.length;i++){
    const line=lines[i].trim(); if(!line)continue;
    if(line.startsWith('### ')){blocks.push({type:'heading',text:line.slice(4)});continue;}
    if(line.startsWith('|')){
      const rows=[]; while(i<lines.length&&lines[i].trim().startsWith('|')){rows.push(lines[i].trim().slice(1,-1).split('|').map(c=>c.trim()));i++;}i--;
      blocks.push({type:'table',headers:rows[0],rows:rows.slice(2)});continue;
    }
    const para=[line];while(i+1<lines.length&&lines[i+1].trim()&&!/^(### |\|)/.test(lines[i+1].trim()))para.push(lines[++i].trim());
    blocks.push({type:'paragraph',text:para.join(' ')});
  }return blocks;
}
const sections=[...reportMarkdown.matchAll(/^## (\d+)\. (.+)\n([\s\S]*?)(?=^## \d+\.|$(?![\s\S]))/gm)].map(m=>({id:`section-${m[1]}`,number:Number(m[1]),title:m[2],blocks:parseBlocks(m[3])}));
const sources=[...sourceMarkdown.matchAll(/^### (문서|회사) (\d+) — (.+)\n([\s\S]*?)(?=^#{2,3} |$(?![\s\S]))/gm)].map(m=>{const [title,page]=m[3].split(' / ');return{id:`${m[1]}-${m[2]}`,kind:m[1],number:m[2],title,page,text:m[4].trim()};});
const limitation=reportMarkdown.match(/^\*\*이 보고서의 한계:\*\* (.+)$/m)[1];
function citationIds(text){
  const ids=[];
  for(const m of text.matchAll(/(문서|회사)\s+([\d~·\s]+)/g)){
    for(const piece of m[2].trim().split('·')){
      const [start,end]=piece.trim().split('~').map(Number);if(!start)continue;
      for(let n=start;n<=(end||start);n++)ids.push(`${m[1]}-${String(n).padStart(2,'0')}`);
    }
  }return [...new Set(ids)].filter(id=>sources.some(s=>s.id===id));
}
function Emphasis({text}){return text.split(/(\*\*[^*]+\*\*)/g).map((s,i)=>s.startsWith('**')?<strong key={i}>{s.slice(2,-2)}</strong>:s);}
function Inline({text,onEvidence,sectionId}){
  const parts=text.split(/(\[(?:문서|회사) [^\]]+\])/g);
  return parts.map((part,i)=>{
    if(/^\[(문서|회사) /.test(part)){const ids=citationIds(part);return <button key={i} className="citation" title={part.slice(1,-1)} aria-label={`${part.slice(1,-1)} 근거 확인`} onClick={e=>onEvidence(ids,sectionId,e.currentTarget)}><Quote/><span>근거 {ids.length}</span></button>;}
    return <Emphasis key={i} text={part}/>;
  });
}
function ReportTable({block,onEvidence,sectionId,title}){
  const data=block.rows.map((row,i)=>({id:String(i),...Object.fromEntries(row.map((cell,j)=>[`c${j}`,cell]))}));
  const columns=block.headers.map((header,i)=>({key:`c${i}`,header,width:proportional(i===0?.8:1.4),renderCell:row=><Inline text={row[`c${i}`]} onEvidence={onEvidence} sectionId={sectionId}/>}));
  return <figure className="table-figure"><figcaption><span>대조해서 읽기</span><strong>{title}</strong></figcaption><div className="report-table"><Table data={data} columns={columns} idKey="id" density="balanced" verticalAlign="top"/></div></figure>;
}
function ConditionMap({onEvidence}){
  const links=[
    {label:'문서의 조건',title:'실제 데이터는 기관 내부에서 처리',text:'외부 테스트 환경에서 실제 데이터를 사용할 수 없습니다.',cite:'[문서 06]'},
    {label:'우리에게 미치는 영향 · 해석',title:'정제·성능 시험의 환경부터 정해야 함',text:'접속·반입·시험 데이터 조건에 따라 작업 방법과 투입 장소가 달라질 수 있습니다.',cite:'[문서 04~06·12]'},
    {label:'확인할 사항',title:'보안지침 + 샘플 + 검수 기준',text:'어떤 환경에서 무엇을 검사할 수 있는지 먼저 확인해야 합니다.',cite:'[문서 04~06·12]'},
    {label:'확인 뒤 갱신할 판단',title:'수행 일정과 원가의 산정 전제',text:'환경과 시험 조건을 확보한 뒤 일정·인력·비용을 구체화합니다.',cite:'[문서 06·10~12]'},
  ];
  return <figure className="condition-map" aria-label="보안 조건과 수행 판단의 연결"><figcaption><span className="editorial-kicker">조건을 연결해 읽기</span><h3>보안 조건 하나가 일정·원가로 이어집니다</h3><p>아래 본문에서 다룰 조건의 관계입니다. 지연이 확정됐다는 뜻은 아닙니다.</p></figcaption><ol>{links.map((link,i)=><li key={link.label}><span className="chain-step" aria-hidden="true">{String(i+1).padStart(2,'0')}</span><div><span className="chain-label">{link.label}</span><strong>{link.title}</strong><p>{link.text} <Inline text={link.cite} onEvidence={onEvidence} sectionId="section-4"/></p></div></li>)}</ol></figure>;
}
function ReadingLinks({goto}){
  const rows=[['자격 증빙','회사자료와 미확인 조건',3],['수행 조건','데이터·보안·검수·일정',4],['책임과 원가','계약 수용 범위와 비용',6]];
  return <nav className="reading-links" aria-label="판단 조건의 상세 설명"><span>판단의 전제부터 확인하려면</span>{rows.map(([label,detail,n])=><a key={n} href={`#section-${n}`} onClick={e=>{e.preventDefault();goto(`section-${n}`);}}><b>{label}</b><span>{detail}</span><ArrowRight/></a>)}</nav>;
}
function SectionBody({section,onEvidence,goto}){
  let topic=0;
  const blocks=section.number===1?[section.blocks[1],section.blocks[0],...section.blocks.slice(2)]:section.blocks;
  return <>
    {section.number===4&&<ConditionMap onEvidence={onEvidence}/>}
    <div className="report-prose">{blocks.map((block,j)=>{
      if(block.type==='heading')return <h3 key={j} className="topic-heading"><span aria-hidden="true">{String(++topic).padStart(2,'0')}</span>{block.text}</h3>;
      if(block.type==='table')return <ReportTable key={j} block={block} sectionId={section.id} title={tableTitles[section.number]} onEvidence={onEvidence}/>;
      const note=block.text.startsWith('근거:')||block.text.startsWith('표의 산출물');
      const decision=block.text.startsWith('**사람 검토 의견:');
      const takeaway=section.number===1&&j===0;
      return <React.Fragment key={j}>{takeaway&&<div className="takeaway-label">지금 판단을 바꾸는 핵심 조건</div>}<p className={note?'table-note':decision?'human-decision':takeaway?'takeaway':section.number===6&&j<4?'contract-clause':j===0&&section.number!==4&&section.number!==7?'section-lead':''}><Inline text={block.text} sectionId={section.id} onEvidence={onEvidence}/></p>{section.number===1&&j===1&&<ReadingLinks goto={goto}/>}</React.Fragment>;
    })}</div>
  </>;
}
function Prototype(){
  const [active,setActive]=useState('section-1');
  const [focus,setFocus]=useState(false);const [large,setLarge]=useState(false);
  const [evidence,setEvidence]=useState(null);const [selected,setSelected]=useState('');
  const scrollRef=useRef(null),sourceHeading=useRef(null),sourcePane=useRef(null),returnTo=useRef(null),restore=useRef(null);
  const visibleSources=evidence?sources.filter(s=>evidence.ids.includes(s.id)):[];
  const current=visibleSources.find(s=>s.id===selected)||visibleSources[0];
  const index=visibleSources.indexOf(current);
  useEffect(()=>{
    const area=scrollRef.current;
    const update=()=>{const boundary=area.getBoundingClientRect().top+110;let found=sections[0].id;for(const s of sections){if(document.getElementById(s.id).getBoundingClientRect().top<=boundary)found=s.id;}setActive(found);};
    area.addEventListener('scroll',update,{passive:true});update();return()=>area.removeEventListener('scroll',update);
  },[]);
  function preservePosition(change,element){
    const anchor=element||document.getElementById(active);restore.current={element:anchor,offset:anchor.getBoundingClientRect().top};change();
  }
  useLayoutEffect(()=>{
    if(restore.current){const {element,offset}=restore.current;scrollRef.current.scrollTop+=element.getBoundingClientRect().top-offset;restore.current=null;}
    if(evidence)sourceHeading.current?.focus({preventScroll:true});
  },[!!evidence,focus,large]);
  useLayoutEffect(()=>{
    if(!evidence)return;
    const area=scrollRef.current;
    const fit=()=>{const pane=sourcePane.current;if(pane)pane.style.setProperty('--source-available-height',`${Math.max(240,area.getBoundingClientRect().bottom-pane.getBoundingClientRect().top-16)}px`);};
    fit();area.addEventListener('scroll',fit,{passive:true});window.addEventListener('resize',fit);
    return()=>{area.removeEventListener('scroll',fit);window.removeEventListener('resize',fit);};
  },[!!evidence,focus,large]);
  function openEvidence(ids,sectionId,trigger){if(!ids.length)return;returnTo.current=trigger;preservePosition(()=>{setEvidence({ids,sectionId});setSelected(ids[0]);},trigger);}
  function closeEvidence(){const target=returnTo.current;preservePosition(()=>setEvidence(null),target);requestAnimationFrame(()=>target?.focus({preventScroll:true}));}
  useEffect(()=>{if(!evidence)return;const key=e=>{if(e.key==='Escape'){e.preventDefault();closeEvidence();}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[evidence]);
  function goto(id){const el=document.getElementById(id);const area=scrollRef.current;area.scrollTo({top:area.scrollTop+el.getBoundingClientRect().top-area.getBoundingClientRect().top-24,behavior:'instant'});setActive(id);el.querySelector('h2').focus({preventScroll:true});}
  function download(){const blob=new Blob([reportMarkdown],{type:'text/markdown;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='심층검토-A안-본문-가상예시.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  return <div className={`prototype ${focus?'focus-mode':''} ${evidence?'with-evidence':''} ${large?'large-type':''}`} data-astryx-theme="bidops" data-theme="light">
    <aside className="app-nav" aria-label="서비스 탐색">
      <div className="logo"><span className="logo-symbol"><ListChecks/></span><b>BidOps</b></div>
      <div className="nav-label">사업 탐색</div>
      <nav>{[[LayoutDashboard,'대시보드'],[FolderSearch,'발주계획'],[FileText,'사전규격'],[BookOpen,'입찰공고'],[Route,'사업 추적'],[ShieldCheck,'Go / No-Go']].map(([Icon,label])=><span key={label} className={label==='사전규격'?'nav-current':''} title={label}><Icon/><span>{label}</span></span>)}</nav>
      <div className="nav-foot"><Settings2/><span>내부 의사결정 지원</span></div>
    </aside>
    <div className="app-content">
      <header className="app-header"><div className="breadcrumb"><span>사전규격</span><ChevronRight/><strong>심층검토</strong></div><div className="header-note"><Token label="UI 시안" color="gray"/><span>가상 데이터 · 운영 저장 없음</span></div></header>
      <div className="reader-toolbar"><div className="reader-title"><BookOpen/><strong>심층검토 보고서</strong><span>A안 · 설명형 본문</span></div><div className="reader-actions"><Button label={large?'기본 글자':'글자 크게'} variant="ghost" size="sm" icon={<Type/>} aria-pressed={large} onClick={()=>preservePosition(()=>setLarge(!large))}/><Button label={focus?'기본 화면':'본문 집중'} variant="ghost" size="sm" icon={focus?<Minimize2/>:<Maximize2/>} aria-pressed={focus} onClick={()=>preservePosition(()=>setFocus(!focus))}/><Button label="본문 내려받기" variant="secondary" size="sm" icon={<FileText/>} onClick={download}/></div></div>
      <div className="reading-area" ref={scrollRef} id="reading-area">
        <div className="page-intro"><p className="eyebrow"><Building2/>한빛시 · 디지털정책과<span>사전규격</span></p><h1>한빛시 민원 데이터 통합·분석 플랫폼 구축</h1><div className="project-meta"><span>총사업예산 <b>8.4억 원</b><small>부가세 포함</small></span><span>수행 기간 <b>계약일부터 8개월</b></span><span><CalendarDays/>의견 마감 <b>2026.09.25 18:00</b></span></div></div>
        <div className="reading-grid">
          <aside className="toc" aria-label="보고서 목차"><div className="toc-title"><ListChecks/><strong>보고서 목차</strong><span>8개 절</span></div><nav>{sections.map((section,i)=><a key={section.id} href={`#${section.id}`} aria-current={active===section.id?'location':undefined} onClick={e=>{e.preventDefault();goto(section.id);}}><span className="toc-number">{String(i+1).padStart(2,'0')}</span><span>{sectionNames[i]}</span>{active===section.id&&<ChevronRight/>}</a>)}</nav><div className="toc-guide"><Quote/><p>문장 옆 <strong>근거</strong>를 누르면<br/>관련 원문과 회사자료를<br/>함께 확인할 수 있습니다.</p></div><div className="toc-status"><span>검토 기준</span><b>2026.09.22</b><span>제안요청서 1차</span><span>회사자료 2026.09.22 기준</span><Token label="mock 참조" color="gray"/></div><a className="back-top" href="#report-start" onClick={e=>{e.preventDefault();scrollRef.current.scrollTo({top:0,behavior:'instant'});}}><ArrowUp/>보고서 처음으로</a></aside>
          <article className="report" aria-label="심층검토 보고서 본문" id="report-start">
            <div className="report-prelude"><div><span className="document-kicker">사전규격 심층검토</span><Token label="mock 참조" color="gray"/></div><p>제안요청서 1차 · 회사자료 2026.09.22 기준</p><p className="deadline-note">사전규격 의견 마감과 별개로, 입찰 제출 마감은 아직 확인되지 않았습니다.</p></div>
            <div className="report-limitation"><CircleAlert/><div><strong>이 보고서의 한계</strong><p>{limitation}</p></div></div>
            {sections.map((section,i)=><section id={section.id} key={section.id} className="report-section" aria-labelledby={`${section.id}-heading`}><header className="section-heading"><span className="section-number">{String(section.number).padStart(2,'0')}</span><div><p className="section-route">{sectionRoutes[i]}</p><h2 id={`${section.id}-heading`} tabIndex={-1}>{section.title}</h2></div></header><SectionBody section={section} onEvidence={openEvidence} goto={goto}/></section>)}
            <footer className="report-end"><BookOpen/><div><strong>보고서 본문 끝</strong><p>가상 사업과 회사자료로 구성한 시안입니다. 실제 분석 품질을 뜻하지 않습니다.</p></div><Button label="처음으로" size="sm" variant="ghost" icon={<ArrowUp/>} onClick={()=>scrollRef.current.scrollTo({top:0,behavior:'instant'})}/></footer>
          </article>
          {evidence&&current&&<aside ref={sourcePane} className="source-pane" aria-label="원문 근거 패널"><header className="source-header"><div><Quote/><h2 tabIndex={-1} ref={sourceHeading}>원문 근거</h2></div><Button label="근거 패널 닫기" size="sm" variant="ghost" isIconOnly icon={<PanelRightClose/>} onClick={closeEvidence}/></header><div className="source-body"><p className="source-context">{sections.find(s=>s.id===evidence.sectionId)?.title}</p><label htmlFor="source-select">이 문장에 연결된 근거 {visibleSources.length}건</label><select id="source-select" value={current.id} onChange={e=>setSelected(e.target.value)}>{visibleSources.map(s=><option key={s.id} value={s.id}>{s.kind==='문서'?'제안요청서':'회사자료'} · {s.title}{s.page?` (${s.page})`:''}</option>)}</select><div className="source-location"><span>{current.kind==='문서'?<FileText/>:<Building2/>}{current.kind==='문서'?'제안요청서 1차':'회사자료'} </span><strong>{current.page||'2026.09.22 기준'}</strong></div><div className="source-paper"><span className="source-label">{current.kind==='문서'?'문서 조건':'회사에서 확인한 자료'}</span><h3>{current.title}</h3><p>{current.text}</p><span className="fiction-label">가상 원문 발췌</span></div><div className="source-pagination"><Button label="이전 근거" size="sm" variant="ghost" isIconOnly icon={<ChevronLeft/>} isDisabled={index===0} onClick={()=>setSelected(visibleSources[index-1].id)}/><span>{index+1} / {visibleSources.length}</span><Button label="다음 근거" size="sm" variant="ghost" isIconOnly icon={<ChevronRight/>} isDisabled={index===visibleSources.length-1} onClick={()=>setSelected(visibleSources[index+1].id)}/></div><div className="source-explanation"><CircleAlert/><p>원문에 적힌 조건과 보고서의 해석을 대조하세요. 회사자료의 미확인은 조건 미충족을 뜻하지 않습니다.</p></div><Button label="본문으로 돌아가기" size="sm" variant="secondary" icon={<ArrowLeft/>} width="100%" onClick={closeEvidence}/></div></aside>}
        </div>
      </div>
      <footer className="reading-footer"><span><BookOpen/>현재 읽는 절 <b>{String(sections.findIndex(s=>s.id===active)+1).padStart(2,'0')} / 08</b><span>{sectionNames[sections.findIndex(s=>s.id===active)]}</span></span><span>심층검토 의견 · 사업 추적 · 최종 Go/No-Go는 별도입니다.</span></footer>
    </div>
  </div>;
}
createRoot(document.getElementById('root')).render(<Prototype/>);
