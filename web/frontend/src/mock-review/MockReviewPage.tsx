import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@astryxdesign/core/Button';
import { Token } from '@astryxdesign/core/Token';
import { bundles, bundleInput, bundleOutput, sources, title } from './scenario';

const box: CSSProperties = { padding:'var(--spacing-6)', background:'var(--color-background-surface)', borderRadius:'var(--radius-element)', border:'var(--border-width) solid var(--color-border)' };
const row: CSSProperties = { display:'flex', alignItems:'center', gap:'var(--spacing-3)', flexWrap:'wrap' };
const prose: CSSProperties = { lineHeight:1.8, marginBlock:'var(--spacing-3)', maxWidth:'76ch' };
type Phase = 'detail'|'preview'|'running'|'complete'|'failed';

export default function MockReviewPage() {
  const [phase,setPhase] = useState<Phase>('detail');
  const [step,setStep] = useState(-1);
  const [failure,setFailure] = useState(false);
  const [approved,setApproved] = useState(false);
  const [inspector,setInspector] = useState(false);
  const started = useRef(false);
  useEffect(()=>{
    if(phase!=='running') return;
    const timer = window.setTimeout(()=>{
      if(failure && step===1) setPhase('failed');
      else if(step===2) setPhase('complete');
      else setStep(step+1);
    },1400);
    return ()=>window.clearTimeout(timer);
  },[phase,step,failure]);
  useEffect(()=>{ if(phase==='complete') window.location.assign('/__mock-review/approved'); },[phase]);
  const start=()=>{ if(started.current || !approved) return; started.current=true; setStep(-1); setPhase('running'); };
  const reset=()=>{ started.current=false; setPhase('detail'); setStep(-1); setApproved(false); };
  const completed=phase==='complete'?3:Math.max(0,step);
  return <section aria-label="심층검토 MOCK 시안" style={{padding:'var(--spacing-6)',overflowY:'auto',height:'100%',fontSize:'var(--bo-type-body)',color:'var(--color-text-primary)'}}>
    <header style={{...box,marginBottom:'var(--spacing-5)'}}>
      <div style={row}><Link to="/pre-specs">사전규격 목록</Link><Token label="MOCK · 가상 자료" /><small>외부 전송·모델 호출 없음 · 새로고침하면 초기화</small></div>
      <h1 style={{fontSize:'var(--bo-type-page-title)',marginBlock:'var(--spacing-4)'}}>{title}</h1>
      <p>한빛시 · 계약일부터 8개월 · 총사업예산 8.4억원(부가세 포함) · 의견 마감 2026.09.25 18:00</p>
      <div style={row}><Token label={phase==='complete'?'시안 보고서 준비됨':phase==='failed'?'모의 분석 실패':phase==='running'?'모의 분석 중':'심층검토 요청 전'} /><small>최종 추적·입찰 결정은 사람이 별도로 합니다.</small></div>
    </header>
    {phase==='detail' && <section style={box}>
      <h2>우리 회사가 검토할 만한 사업인가?</h2>
      <p style={prose}>기존 데이터 통합 경험은 연결되지만 자격 증빙·보안 환경·인력과 원가 확인이 필요한 가상 사업입니다. 사업 문서와 회사 자료를 함께 읽고, 참여 조건·수행 부담·다음 행동을 하나의 보고서로 확인합니다.</p>
      <p>가상 입력: 기존 A안의 제안요청서·회사 자료 · 답할 질문 8개 · 요청 묶음 3개</p>
      <label style={{...row,marginBlock:'var(--spacing-4)'}}>모의 시나리오 <select aria-label="모의 시나리오" value={failure?'failure':'success'} onChange={e=>setFailure(e.target.value==='failure')}><option value="success">완성 보고서</option><option value="failure">두 번째 단계 실패</option></select></label>
      <Button label="심층검토 요청" onClick={()=>setPhase('preview')} />
    </section>}
    {phase==='preview' && <section style={box}>
      <h2>분석에 사용할 자료 확인</h2><p>아래 가상 자료 v1을 세 묶음에 사용합니다. 이 시안의 승인은 실제 자료 전송 승인이 아닙니다.</p>
      {sources.map(s=><details key={s.id} style={{paddingBlock:'var(--spacing-3)',borderBottom:'var(--border-width) solid var(--color-border)'}}><summary>{s.id} · {s.location}</summary><p style={prose}>{s.text}</p></details>)}
      <p>대상: 고정된 MOCK 응답 · 실제 모델 미연결 · 입력 수정 기능 없음</p>
      <label style={{...row,marginBlock:'var(--spacing-4)'}}><input type="checkbox" checked={approved} onChange={e=>setApproved(e.target.checked)} />가상 입력과 MOCK 실행임을 확인했습니다</label>
      <div style={row}><Button label="MOCK 분석 시작" isDisabled={!approved} onClick={start}/><Button label="돌아가기" variant="ghost" onClick={()=>{setApproved(false);setPhase('detail');}}/></div>
    </section>}
    {['running','complete','failed'].includes(phase) && <section aria-label="분석 진행" style={{...box,marginBottom:'var(--spacing-5)'}}>
      <h2>{phase==='failed'?'회사 대조 단계에서 중단되었습니다':phase==='complete'?'세 묶음의 답변을 보고서로 정리했습니다':'사업과 회사를 함께 검토하고 있습니다'}</h2>
      <p role="status">{phase==='running'&&step<0?'실행 대기':`${completed}/3 단계 완료`}{phase==='running'&&step>=0?` · ${bundles[step].title} 진행 중`:''}</p>
      <ol style={{...row,paddingLeft:'var(--spacing-5)'}}>{bundles.map((b,i)=><li key={b.title} style={{marginRight:'var(--spacing-6)'}}>{b.title} · {i<completed?'완료':phase==='failed'&&i===1?'실패':phase==='running'&&i===step?'진행 중':'대기'}</li>)}</ol>
      <p style={{color:'var(--color-text-secondary)'}}>진행 시간은 시연용입니다. 실제 모델의 속도·품질은 측정하지 않았습니다.</p>
      {phase==='failed'&&<><p role="alert">가상 입력: 제안요청서·회사 자료·1차 결과 → 회사 대조 응답 시간 초과를 재현했습니다. 사업 조건 분석만 완료됐으며 최종 보고서는 생성되지 않았습니다.</p><Button label="시안 처음으로" onClick={reset}/></>}
    </section>}
    <section style={{...box,marginTop:'var(--spacing-5)'}}><Button label={inspector?'요청 구성 닫기':'세 요청의 입력·응답 보기'} variant="ghost" onClick={()=>setInspector(!inspector)}/>
      {inspector&&<><p>질문별 8회 대신 아래 3개 요청을 순차 구성합니다. 실제 외부 호출은 0회입니다. 응답 예시는 실행 전에도 확인할 수 있습니다.</p>{bundles.map((b,i)=><details key={b.title}><summary style={{paddingBlock:'var(--spacing-3)'}}>{i+1}. {b.title} · {b.answerIds.length}개 질문</summary><h3>요청 입력</h3><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',fontSize:'var(--bo-type-caption)'}}>{JSON.stringify(bundleInput(i),null,2)}</pre><h3>고정 응답 예시</h3><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',fontSize:'var(--bo-type-caption)'}}>{JSON.stringify(bundleOutput(i),null,2)}</pre></details>)}<p>실제 연결에서는 모델 입력·출력 한도를 확인한 뒤 문맥 단위로 분할합니다. 이 표본의 3회 구성이 모든 문서에 적용된다는 의미는 아닙니다.</p></>}
    </section>
  </section>;
}
