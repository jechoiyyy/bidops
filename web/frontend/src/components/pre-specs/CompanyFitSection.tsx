import { useQuery } from "@tanstack/react-query";
import { Token } from "@astryxdesign/core/Token";
import { Button } from "@astryxdesign/core/Button";
import { api } from "../../lib/api";
import { preSpecAutoPreparationReasonLabel } from "../../lib/preSpecAutoPreparation";
import { qualityStatusLabel } from "../../lib/qualityStatus";
import type { CompanyFitAttempt } from "../../lib/types";
import "../../styles/company-fit.css";

const decisions = { matched: "부합", mismatch: "불일치", unknown: "판단 보류 · 정보 부족" };
const statuses = { queued: "판정 대기", running: "판정 중", completed: "판정 결과", failed: "실행 실패", needs_human_review: "검증 실패 · 사람 확인 필요" };


function valueText(value: unknown): string {
  return value === null ? "미확인" : typeof value === "string" ? value : JSON.stringify(value);
}

function Assessment({ attempt }: { attempt: CompanyFitAttempt }) {
  const result = attempt.result;
  return <div className="company-fit-assessment">
    <div className="company-fit-heading">
      <strong>{result ? decisions[result.decision] : statuses[attempt.status]}</strong>
      <Token label={qualityStatusLabel(attempt.quality_status)} size="sm" />
    </div>
    {!attempt.is_current && <p role="status" className="company-fit-notice">이전 입력 기준의 판정입니다. 현재 개요·회사 프로필·정책과 일치하는지 확인이 필요합니다.</p>}
    {result ? <>
      <p className="company-fit-summary">{result.summary}</p>
      <ol className="company-fit-reasons">
        {result.reasons.length === 0 && <li>상세 사유가 저장되지 않았습니다.</li>}
        {result.reasons.map((reason, index) => <li key={index}>
          <p><strong>판단 사유 {index + 1} · 모델 의견</strong></p>
          <p>{reason.explanation}</p>
          <dl className="company-fit-evidence">
            <dt>공고 과업 근거</dt><dd>{reason.notice_refs.map(ref => {
              const fact = attempt.notice_facts.find(item => item.ref === ref);
              if (!fact) return <p key={ref}>근거를 확인할 수 없습니다.</p>;
              return <div key={ref}><p>{fact.text}</p>
                {attempt.overview_kind === "page" ? <div className="company-fit-links">{fact.pages.map(page => <a key={page}
                  href={`/api/pre-specs/${attempt.notice_id}/overview-pages/${attempt.overview_id}/pdf#page=${page}`}
                  target="_blank" rel="noreferrer">PDF {page}페이지 ↗</a>)}</div> : <p>개요 원문 블록 · {fact.block_key ?? "위치 미확인"} (문서 구조 기준)</p>}
              </div>;
            })}</dd>
            <dt>회사 정보 근거</dt><dd>{reason.company_refs.length ? reason.company_refs.map(ref => {
              const fact = attempt.company_facts.find(item => item.ref === ref);
              return fact ? <p key={ref}>{fact.fact_key} · {fact.status === "confirmed" ? "확인됨" : "확인 필요"} — {valueText(fact.value)}</p> : <p key={ref}>근거를 확인할 수 없습니다.</p>;
            }) : <p>인용된 회사 정보가 없습니다. 역량이 없다는 뜻이 아닙니다.</p>}
            <p>판정 시점에 고정한 승인 프로필 기준</p></dd>
          </dl>
        </li>)}
      </ol>
      {result.verification_items.length > 0 && <section><h4>확인할 사항</h4><ul>{result.verification_items.map((item, i) => <li key={i}>{item}</li>)}</ul></section>}
    </> : <p>{attempt.status === "failed" ? "판정 결과가 생성되지 않았습니다. 불일치로 처리하지 않습니다." : attempt.status === "needs_human_review" ? "검증을 통과한 판정 근거가 없어 결과를 사용할 수 없습니다." : "검증된 판정이 생성되면 과업과 회사 정보의 대조 근거를 표시합니다."}</p>}
    <details><summary>판정 기준과 실행 정보</summary>
      <p>생성 시각 · {new Date(attempt.created_at).toLocaleString("ko-KR")}</p>
      <p>모델 · {attempt.model_name} / 프롬프트 · {attempt.prompt_version}</p>
      <p>개요 · {attempt.overview_id} / {attempt.overview_sha256}</p>
      <p>회사 프로필 · {attempt.profile_version_id} / {attempt.profile_sha256}</p>
      <p>정책 · {attempt.policy_digest} / 모델 버전 · {attempt.model_revision}</p>
      <p>입력 토큰 · {attempt.prompt_tokens ?? "미측정"} / 출력 토큰 · {attempt.output_tokens ?? "미측정"} / 소요 시간 · {attempt.latency_ms === null ? "미측정" : `${attempt.latency_ms}ms`}</p>
      {attempt.error_code && <p>처리 사유 · {attempt.error_code}</p>}
    </details>
  </div>;
}

export function CompanyFitSection({ noticeId }: { noticeId: number }) {
  const query = useQuery({ queryKey: ["pre-spec-company-fit", noticeId],
    queryFn: ({ signal }) => api.getCompanyFit(noticeId, { signal }), retry: false,
    refetchInterval: query => {
      const data = query.state.data;
      return data?.automation_enabled && (!data.attempts.length || data.attempts.some(a => a.status === "queued" || a.status === "running")) ? 5000 : false;
    } });
  return <section className="company-fit" aria-label="회사 업무 부합 여부">
    <h3>회사 업무 부합 여부</h3>
    <p className="company-fit-note">개요의 과업과 회사 정보를 대조한 분석입니다. 추적 승인과 최종 입찰 결정은 사람이 진행합니다.</p>
    {query.isPending ? <p role="status">회사 핏 판정을 불러오는 중입니다.</p> : query.isError ? <div role="alert">
      <p>회사 핏 판정을 불러오지 못했습니다.</p>
      <Button label="회사 핏 다시 불러오기" size="sm" onClick={() => { void query.refetch(); }} />
    </div> : query.data.schema_version !== "bidops.prespec-company-fit.v1" || query.data.notice_id !== noticeId || query.data.attempts.some(a => a.notice_id !== noticeId || (a.result && a.result.schema_version !== "bidops.prespec-company-fit-result.v1")) ?
      <p role="alert">판정 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.</p> : <>
        {query.data.attempts[0] ? <Assessment attempt={query.data.attempts[0]} /> : <p>저장된 회사 핏 판정이 없습니다. 불일치로 판단한 상태가 아닙니다.</p>}
        <div className="company-fit-notice"><strong>자동 심층 검토</strong>
          {query.data.deep_review_id ? <p>생성된 심층 검토가 있습니다. <a href={`/deep-reviews/${query.data.deep_review_id}`}>심층 검토 열기</a></p> :
            <p>{query.data.auto_deep_review_reason ? preSpecAutoPreparationReasonLabel(query.data.auto_deep_review_reason) : "생성된 심층 검토가 없습니다."}</p>}
          {!query.data.automation_enabled && <p>회사 핏 자동 판정은 비활성입니다.</p>}
        </div>
        {query.data.attempts.length > 1 && <details><summary>이전 판정 {query.data.attempts.length - 1}건</summary>
          {query.data.attempts.slice(1).map(attempt => <Assessment key={attempt.id} attempt={attempt} />)}
        </details>}
      </>}
  </section>;
}
