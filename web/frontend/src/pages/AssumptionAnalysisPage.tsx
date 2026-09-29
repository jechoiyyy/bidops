import {Link, useParams} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {assumptionApi} from '../components/deep-review/api';
import {AssumptionReader} from '../components/assumption-analysis/Reader';

export function AssumptionAnalysisPage() {
  const {runId=''}=useParams();
  const query=useQuery({queryKey:['assumption-analysis',runId],queryFn:()=>assumptionApi.get(runId),refetchInterval:q=>['queued','running'].includes(q.state.data?.status||'')?3000:false});
  if(query.isPending)return <p role="status">가정 분석을 읽는 중입니다.</p>;
  if(query.isError)return <p role="alert">가정 분석을 읽지 못했습니다. <button onClick={()=>void query.refetch()}>다시 읽기</button></p>;
  const data=query.data;
  const grouped = new Map<string, import('../components/assumption-analysis/types').Section>();
  for (const section of data.stages.flatMap(s=>s.result?.sections||[])) {
    const prior = grouped.get(section.key);
    grouped.set(section.key, {...section, paragraphs: [...(prior?.paragraphs||[]), ...section.paragraphs]});
  }
  const partial = [...grouped.values()];
  return <section className="assumption-page"><header><Link to={`/pre-specs/${data.notice_id}`}>사전규격 상세로</Link><p role="status">{data.status} · 호출 {data.call_count}회 · {Math.round(data.latency_ms/1000)}초{data.error_code?` · ${data.error_code}`:''}</p><p>{data.active_call ? `${data.active_call.stage} ${data.active_call.part+1} 진행 중 · ` : ""}{data.scenario.settings.model} · {data.scenario.settings.reasoning_effort} · {data.stages.map(s=>`${s.stage} ${s.part+1}: ${s.status}`).join(' / ')}</p></header>{data.report?<AssumptionReader data={data} report={data.report}/>:partial.length?<AssumptionReader data={data} report={{sections:partial,complete:false,warnings:[]}}/>:<p>아직 읽을 수 있는 단계 결과가 없습니다. 세 단계와 완성 보고서가 있어야 완료입니다.</p>}</section>;
}
