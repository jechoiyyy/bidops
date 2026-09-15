import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { Token } from "@astryxdesign/core/Token";
import { Button } from "@astryxdesign/core/Button";
import { api } from "../../lib/api";
import { preSpecAutoPreparationReasonLabel } from "../../lib/preSpecAutoPreparation";
import { qualityStatusLabel } from "../../lib/qualityStatus";
import type { CompanyFitAttempt, CompanyFitResponse } from "../../lib/types";
import "../../styles/company-fit.css";

export const decisions = { matched: "부합", mismatch: "불일치", unknown: "판단 보류 · 정보 부족" };
export const statuses = { queued: "판정 대기", running: "판정 중", completed: "판정 결과", failed: "실행 실패", needs_human_review: "검증 실패 · 사람 확인 필요" };

/** 화면 문구는 `회사 적합성`으로 통일한다(docs/0915_ui-redesign/spec.md §4 용어).
 * API 필드명(`company_fit`)·함수명은 그대로 둔다.
 *
 * 저장된 판정이 없는 상태는 **불일치가 아니다**. 목록과 상세가 같은 문장을 쓰도록
 * 문구는 여기 하나만 두고 두 화면이 읽는다(CLAUDE.md 강제 게이트: `unknown`·`null`
 * 은 검증 대기 상태로 보존한다). */
export const NO_CURRENT_ATTEMPT_NOTICE = "회사 적합성 판정 없음 · 불일치 아님";


function valueText(value: unknown): string {
  return value === null ? "미확인" : typeof value === "string" ? value : JSON.stringify(value);
}

export function CompanyFitVerdict({ attempt }: { attempt: CompanyFitAttempt }) {
  const result = attempt.result;
  return <>
    <div className="company-fit-heading">
      <strong>{result ? decisions[result.decision] : statuses[attempt.status]}</strong>
      <Token label={qualityStatusLabel(attempt.quality_status)} size="sm" />
    </div>
    {!attempt.is_current && <p role="status" className="company-fit-notice">이전 입력 기준의 판정입니다. 현재 개요·회사 프로필·정책과 일치하는지 확인이 필요합니다.</p>}
    {result ? <p className="company-fit-summary">{result.summary}</p> : <p>{attempt.status === "failed" ? "판정 결과가 생성되지 않았습니다. 불일치로 처리하지 않습니다." : attempt.status === "needs_human_review" ? "검증을 통과한 판정 근거가 없어 결과를 사용할 수 없습니다." : "검증된 판정이 생성되면 과업과 회사 정보의 대조 근거를 표시합니다."}</p>}
  </>;
}

export function CompanyFitReasons({ attempt }: { attempt: CompanyFitAttempt }) {
  const result = attempt.result;
  if (!result) return null;
  return <ol className="company-fit-reasons">
        {result.reasons.length === 0 && <li>상세 사유가 저장되지 않았습니다.</li>}
        {result.reasons.map((reason, index) => <li key={index}>
          <p><strong>판단 사유 {index + 1} · 모델 의견</strong></p>
          <p>{reason.explanation}</p>
          <dl className="company-fit-evidence">
            <dt>공고 과업 근거</dt><dd>{reason.notice_refs.map(ref => {
              const fact = attempt.notice_facts.find(item => item.ref === ref);
              if (!fact) return <p key={ref}>근거를 확인할 수 없습니다.</p>;
              return <div key={ref}><p>{fact.text}</p>
                {/* 새 개요 run은 자기 스냅샷 PDF를 열 수 있다. 이전 세대의 개요
                    입력(`page`·`extractive`)은 살아있는 열람 경로가 없으므로 깨진
                    링크 대신 위치만 문장으로 남긴다. */}
                {attempt.overview_kind === "overview_run"
                  ? <p>{fact.pages.map((pageNumber, pageIndex) => <span key={pageNumber}>{pageIndex > 0 ? " " : null}<a href={`${api.preSpecOverviewRunPdfUrl(attempt.notice_id, attempt.overview_id)}#page=${pageNumber}`} rel="noreferrer" target="_blank">PDF {pageNumber}페이지 ↗</a></span>)}</p>
                  : attempt.overview_kind === "page" ? <p>PDF {fact.pages.join(", ")}페이지 (개요 원문 열람 화면은 아직 없습니다)</p> : <p>개요 원문 블록 · {fact.block_key ?? "위치 미확인"} (문서 구조 기준)</p>}
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
}

export function CompanyFitVerificationItems({ attempt }: { attempt: CompanyFitAttempt }) {
  const result = attempt.result;
  if (!result || result.verification_items.length === 0) return null;
  return <section><h4>확인할 사항</h4><ul>{result.verification_items.map((item, i) => <li key={i}>{item}</li>)}</ul></section>;
}

export function CompanyFitExecutionInfo({ attempt }: { attempt: CompanyFitAttempt }) {
  return <details><summary>판정 기준과 실행 정보</summary>
      <p>생성 시각 · {new Date(attempt.created_at).toLocaleString("ko-KR")}</p>
      <p>모델 · {attempt.model_name} / 프롬프트 · {attempt.prompt_version}</p>
      <p>개요 · {attempt.overview_id} / {attempt.overview_sha256}</p>
      <p>회사 프로필 · {attempt.profile_version_id} / {attempt.profile_sha256}</p>
      <p>정책 · {attempt.policy_digest} / 모델 버전 · {attempt.model_revision}</p>
      <p>입력 토큰 · {attempt.prompt_tokens ?? "미측정"} / 출력 토큰 · {attempt.output_tokens ?? "미측정"} / 소요 시간 · {attempt.latency_ms === null ? "미측정" : `${attempt.latency_ms}ms`}</p>
      {attempt.error_code && <p>처리 사유 · {attempt.error_code}</p>}
    </details>
}

function Assessment({ attempt }: { attempt: CompanyFitAttempt }) {
  return <div className="company-fit-assessment">
    <CompanyFitVerdict attempt={attempt} />
    <CompanyFitReasons attempt={attempt} />
    <CompanyFitVerificationItems attempt={attempt} />
    <CompanyFitExecutionInfo attempt={attempt} />
  </div>;
}

type CompanyFitState = {
  query: UseQueryResult<CompanyFitResponse>;
  isValid: boolean;
  data: CompanyFitResponse | null;
  currentAttempt: CompanyFitAttempt | null;
  previousAttempts: CompanyFitAttempt[];
};

export function useCompanyFit(noticeId: number | null): CompanyFitState {
  const query = useQuery({ queryKey: ["pre-spec-company-fit", noticeId],
    queryFn: ({ signal }) => api.getCompanyFit(noticeId as number, { signal }), retry: false,
    enabled: noticeId !== null,
    refetchInterval: query => {
      const data = query.state.data;
      return data?.automation_enabled && (!data.attempts.length || data.attempts.some(a => a.status === "queued" || a.status === "running")) ? 5000 : false;
    } });
  const data = query.data ?? null;
  const isValid = data !== null
    && noticeId !== null
    && data.schema_version === "bidops.prespec-company-fit.v1"
    && data.notice_id === noticeId
    && !data.attempts.some(a => a.notice_id !== noticeId || (a.result && a.result.schema_version !== "bidops.prespec-company-fit-result.v1"));
  const currentAttempt = data?.attempts[0] ?? null;
  const previousAttempts = data?.attempts.slice(1) ?? [];
  return { query, isValid, data, currentAttempt, previousAttempts };
}

export function CompanyFitAutomationNotice({ data }: { data: CompanyFitResponse }) {
  return <div className="company-fit-notice"><strong>자동 심층 검토</strong>
    {data.deep_review_id ? <p>생성된 심층 검토가 있습니다. <a href={`/deep-reviews/${data.deep_review_id}`}>심층 검토 열기</a></p> :
      <p>{data.auto_deep_review_reason ? preSpecAutoPreparationReasonLabel(data.auto_deep_review_reason) : "생성된 심층 검토가 없습니다."}</p>}
    {!data.automation_enabled && <p>회사 적합성 자동 판정은 비활성입니다.</p>}
  </div>;
}

export function CompanyFitSection({ noticeId, compact = false }: { noticeId: number; compact?: boolean }) {
  const { query, isValid, data, currentAttempt, previousAttempts } = useCompanyFit(noticeId);
  if (compact && !query.isError && isValid && data !== null && !data.automation_enabled && !currentAttempt) {
    return <section className="company-fit" aria-label="회사 업무 부합 여부">
      <p>{NO_CURRENT_ATTEMPT_NOTICE} · 자동 판정 비활성{data.deep_review_id
        ? <> · <a href={`/deep-reviews/${data.deep_review_id}`}>심층 검토 열기</a></> : null}</p>
    </section>;
  }
  return <section className="company-fit" aria-label="회사 업무 부합 여부">
    <h3>회사 업무 부합 여부</h3>
    <p className="company-fit-note">개요의 과업과 회사 정보를 대조한 분석입니다. 추적 승인과 최종 입찰 결정은 사람이 진행합니다.</p>
    {query.isPending ? <p role="status">회사 적합성 판정을 불러오는 중입니다.</p> : query.isError ? <div role="alert">
      <p>회사 적합성 판정을 불러오지 못했습니다.</p>
      <Button label="회사 적합성 다시 불러오기" size="sm" onClick={() => { void query.refetch(); }} />
    </div> : !isValid || data === null ?
      <p role="alert">판정 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.</p> : <>
        {currentAttempt ? <Assessment attempt={currentAttempt} /> : <p>{NO_CURRENT_ATTEMPT_NOTICE}</p>}
        <CompanyFitAutomationNotice data={data} />
        {previousAttempts.length > 0 && <details><summary>이전 판정 {previousAttempts.length}건</summary>
          {previousAttempts.map(attempt => <Assessment key={attempt.id} attempt={attempt} />)}
        </details>}
      </>}
  </section>;
}
