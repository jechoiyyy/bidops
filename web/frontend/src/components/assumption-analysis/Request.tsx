import {useRef, useState} from 'react';
import {Link} from 'react-router-dom';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {Button} from '@astryxdesign/core/Button';
import {assumptionApi, DeepReviewApiError} from '../deep-review/api';
import {generateRequestId} from '../../lib/requestId';
import type {Preview} from './types';

function previewModelLabel(input: Record<string, unknown>): string {
  const scenario = input.scenario;
  if (scenario === null || typeof scenario !== 'object') return '설정 확인 불가';
  const settings = (scenario as Record<string, unknown>).settings;
  if (settings === null || typeof settings !== 'object') return '설정 확인 불가';
  const {model, reasoning_effort: reasoningEffort} = settings as Record<string, unknown>;
  if (typeof model !== 'string' || typeof reasoningEffort !== 'string') return '설정 확인 불가';
  return `${model} · ${reasoningEffort}`;
}

export function AssumptionRequest({noticeId, bundleId, actor}: {noticeId: number; bundleId: string; actor: string}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const locked = useRef(false), request = useRef<string | null>(null);
  const cache = useQueryClient();
  const history = useQuery({queryKey: ['assumption-analyses', noticeId], queryFn: ()=>assumptionApi.list(noticeId), refetchInterval: 5000});
  async function act(submit: boolean) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError('');
    try {
      if (submit && preview && approved) {
        request.current ??= generateRequestId();
        await assumptionApi.create(noticeId, preview.preview_id, request.current, actor);
        setPreview(null); setApproved(false);
        await cache.invalidateQueries({queryKey: ['assumption-analyses', noticeId]});
      } else {
        setPreview(await assumptionApi.preview(noticeId, bundleId)); setApproved(false); request.current = null;
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '가정 분석 요청 실패');
      if (failure instanceof DeepReviewApiError && ['preview_changed','preview_used'].includes(failure.code || '')) {
        setPreview(null); setApproved(false); request.current = null;
      }
    }
    finally { locked.current = false; setBusy(false); }
  }
  return <section aria-label="가정 분석 요청">
    <h3>1489번 가정 분석</h3>
    <p>실제 문서·회사 자료에 별도 가정을 더합니다. 품질 미측정 · 가상 회사 정보 포함</p>
    <Button label="가정 분석 입력 미리보기" onClick={()=>void act(false)} isDisabled={busy}/>
    {preview && <section aria-label="가정 분석 전송 승인">
      <p>실행 모델 · {previewModelLabel(preview.input)}</p>
      <p>이전 미리보기 대비 변경: {preview.previous_preview_id ? preview.changed_fields.join(', ') || '없음' : '최초 입력'}</p>
      <p>미확인 필수 증빙 유효·담당/백업 확보·90분 현장 도착 체계는 가정입니다. 부품·제조사 지원 확보는 미확인입니다.</p>
      <p>월 300만원 · 준비비 200만원 · 지원비 400/800만원 · 3/6/12개월 × 90/100%의 12조합. 6/12개월은 민감도 분석이며 차액은 가정상 잔액입니다.</p>
      <details><summary>전송 입력·가정·실행 설정 전체</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(preview.input,null,2)}</pre></details>
      <p style={{overflowWrap:'anywhere'}}>입력 해시 {preview.input_sha256}</p>
      <label><input type="checkbox" checked={approved} onChange={e=>setApproved(e.target.checked)}/>이 입력과 가정 및 같은 실행의 선행 결과를 Luna로 전송하는 데 동의합니다</label>
      <Button label="승인하고 가정 분석 요청" isDisabled={busy || !approved || !actor.trim()} onClick={()=>void act(true)}/>
    </section>}
    {error && <p role="alert">{error}</p>}
    {history.isError && <p role="alert">가정 분석 이력을 읽을 수 없습니다.</p>}
    <ul>{history.data?.items.map(item=><li key={item.id}><Link to={`/assumption-analyses/${item.id}`}>{new Date(item.approved_at).toLocaleString('ko-KR')} · {item.status}{item.error_code ? ` · ${item.error_code}` : ''}</Link></li>)}</ul>
  </section>;
}
