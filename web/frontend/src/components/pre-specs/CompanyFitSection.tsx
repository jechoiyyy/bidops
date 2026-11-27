import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { Token } from "@astryxdesign/core/Token";
import { Button } from "@astryxdesign/core/Button";
import { api } from "../../lib/api";
import { qualityStatusLabel } from "../../lib/qualityStatus";
import type { CompanyFitAttempt, CompanyFitMode, CompanyFitResponse } from "../../lib/types";
import { ClassTag } from "../common/Marks";
import "../../styles/company-fit.css";

type CompanyFitResult = NonNullable<CompanyFitAttempt["result"]>;
type Decision = CompanyFitResult["decision"];
type CompanyFitReason = CompanyFitResult["reasons"][number];

/** 화면 문구는 `회사 적합성`으로 통일한다(docs/specs/0915_ui-redesign/spec.md §4 용어).
 * API 필드명(`company_fit`)·함수명은 그대로 둔다. 판정 이름은 목록의 회사 핏 열과 같다. */
export const DECISION_LABEL: Record<Decision, string> = { matched: "부합", unknown: "판단 보류", mismatch: "불일치" };
export const STATUS_LABEL: Record<CompanyFitAttempt["status"], string> = {
  queued: "판정 대기", running: "판정 중", completed: "판정 결과", failed: "판정 실패", needs_human_review: "사람 확인 필요",
};
const STATUS_NOTE: Partial<Record<CompanyFitAttempt["status"], string>> = {
  failed: "판정 결과가 만들어지지 않았어요. 불일치로 보지 않아요.",
  needs_human_review: "근거를 확인할 수 없어 판정을 쓰지 않았어요. 담당자가 개요를 직접 확인해 주세요.",
};
const PENDING_NOTE = "판정이 끝나면 근거와 함께 보여 드려요.";

/** 저장된 판정이 없는 상태는 **불일치가 아니다**. 목록과 상세가 같은 문장을 쓰도록
 * 문구는 여기 하나만 두고 두 화면이 읽는다(CLAUDE.md 강제 게이트: `unknown`·`null`
 * 은 검증 대기 상태로 보존한다). */
export const NO_CURRENT_ATTEMPT_NOTICE = "회사 적합성 판정 없음 · 불일치 아님";

/** 카드 lineage 부합 + 추천 모드에서만 서버가 `engine_suggested`를 준다(PS-01 C5). 표시만 하며
 * 버튼·링크를 두지 않는다 — 분석 요청은 사람의 추적 시작·클릭에서만 나온다(ADR-0078 결정 1). */
export const ENGINE_SUGGESTION_NOTICE = "회사 사업 범위와 맞는 사업이에요. 추적을 시작하면 상세 분석을 요청할 수 있어요.";

/** 가져온 Claude 참조 판정(PS-01 MVP 2)은 모델 결과와 구분해 품질 표식 옆에 적는다. */
export const CLAUDE_REFERENCE_LABEL = "Claude 판정 · 참조";

/** 판정 주체 이름. 프로필 lineage(`judged_by=null`)도 모델 판정이다. */
export function companyFitJudgeLabel(attempt: CompanyFitAttempt): string {
  return attempt.judged_by === "claude_reference" ? CLAUDE_REFERENCE_LABEL : "모델 판정";
}

const MODE_LABEL: Record<CompanyFitMode["mode"], string> = { off: "꺼짐", suggest: "추천" };


function valueText(value: unknown): string {
  return value === null ? "미확인" : typeof value === "string" ? value : JSON.stringify(value);
}

/** 참조 결과의 표식. 품질 표식은 늘, Claude 참조 판정은 그 옆에 함께 보인다(지우면 안 되는 경고). */
export function CompanyFitMarks({ attempt }: { attempt: CompanyFitAttempt }) {
  return <span className="company-fit-marks">
    <Token label={qualityStatusLabel(attempt.quality_status)} size="sm" />
    {attempt.judged_by === "claude_reference" ? <Token label={CLAUDE_REFERENCE_LABEL} size="sm" /> : null}
  </span>;
}

export function CompanyFitVerdict({ attempt }: { attempt: CompanyFitAttempt }) {
  const result = attempt.result;
  return <>
    <div className="company-fit-verdict" data-tone={result ? result.decision : "pending"}>
      <strong className="company-fit-decision">{result ? DECISION_LABEL[result.decision] : STATUS_LABEL[attempt.status]}</strong>
      <div className="company-fit-verdict-body">
        <p className="company-fit-summary">{result ? result.summary : STATUS_NOTE[attempt.status] ?? PENDING_NOTE}</p>
        <CompanyFitMarks attempt={attempt} />
      </div>
    </div>
    {!attempt.is_current ? <p role="status" className="company-fit-notice">개요나 회사 기준이 바뀌기 전의 판정이에요. 지금 내용과 맞는지 확인해 주세요.</p> : null}
  </>;
}

/** 근거 문장의 위치. 새 개요 run은 자기 스냅샷 PDF를 열 수 있다. 이전 세대의 개요 입력
 * (`page`·`extractive`)은 살아있는 열람 경로가 없으므로 깨진 링크 대신 위치만 글자로 남긴다. */
function FactPlace({ attempt, fact }: { attempt: CompanyFitAttempt; fact: CompanyFitAttempt["notice_facts"][number] }) {
  if (attempt.overview_kind === "overview_run") {
    return <>{fact.pages.map((page, index) => <span key={page}>{index > 0 ? " " : null}<a className="company-fit-page" href={`${api.preSpecOverviewRunPdfUrl(attempt.notice_id, attempt.overview_id)}#page=${page}`} rel="noreferrer" target="_blank">PDF {page}페이지 ↗</a></span>)}</>;
  }
  if (attempt.overview_kind === "page") return fact.pages.length ? <span className="company-fit-page">PDF {fact.pages.join(", ")}페이지</span> : null;
  return <span className="company-fit-page">개요 원문 블록 · {fact.block_key ?? "위치 미확인"}</span>;
}

function Reason({ attempt, reason, index }: { attempt: CompanyFitAttempt; reason: CompanyFitReason; index: number }) {
  const noticeFacts = reason.notice_refs.map(ref => ({ ref, fact: attempt.notice_facts.find(item => item.ref === ref) }));
  return <li className="company-fit-reason">
    <span className="company-fit-reason-no" aria-hidden="true">{index + 1}</span>
    <div className="company-fit-reason-body">
      <p className="company-fit-reason-text">{reason.explanation}</p>
      {noticeFacts.length ? <ul className="company-fit-quotes" aria-label={`근거 ${index + 1} 공고 원문`}>
        {noticeFacts.map(({ ref, fact }) => <li key={ref}>
          {fact ? <><span>{fact.text}</span> <FactPlace attempt={attempt} fact={fact} /></> : <span>근거 위치를 확인할 수 없어요.</span>}
        </li>)}
      </ul> : null}
      <div className="company-fit-basis">
        <span className="company-fit-basis-label">회사 기준</span>
        {reason.company_refs.length ? reason.company_refs.map(ref => {
          // 카드 lineage는 범위·정책의 이름만 보인다(value JSON은 화면에 싣지 않는다, PS-01 C1).
          // 이름이 없으면 ref를 그대로 적고 다른 이름을 지어내지 않는다.
          if (attempt.lineage === "card") return <ClassTag key={ref} label={attempt.company_fact_labels?.[ref] ?? ref} />;
          const fact = attempt.company_facts.find(item => item.ref === ref);
          return <span key={ref}>{fact ? `${fact.fact_key} · ${fact.status === "confirmed" ? "확인됨" : "확인 필요"} — ${valueText(fact.value)}` : `${ref} · 근거를 확인할 수 없어요`}</span>;
        }) : <span className="company-fit-basis-empty">인용 없음 · 역량이 없다는 뜻은 아니에요</span>}
      </div>
    </div>
  </li>;
}

/** 판단 근거(공고 원문·회사 기준)와 확인할 사항. 카드 버전·식별 해시는 기술 정보가 전문으로 갖는다. */
export function CompanyFitBody({ attempt }: { attempt: CompanyFitAttempt }) {
  const result = attempt.result;
  if (!result) return null;
  const checks = result.verification_items;
  return <div className={checks.length ? "company-fit-body has-checks" : "company-fit-body"}>
    <section className="company-fit-reasons-block" aria-label="판단 근거">
      <h4 className="company-fit-sub">판단 근거</h4>
      {result.reasons.length
        ? <ol className="company-fit-reasons">{result.reasons.map((reason, index) => <Reason key={index} attempt={attempt} reason={reason} index={index} />)}</ol>
        : <p className="company-fit-muted">저장된 상세 근거가 없어요.</p>}
    </section>
    {checks.length ? <section className="company-fit-checks" aria-label="확인할 사항">
      <h4 className="company-fit-sub">확인할 사항 <span className="company-fit-count">{checks.length}</span></h4>
      <ul>{checks.map((item, index) => <li key={index}>{item}</li>)}</ul>
    </section> : null}
  </div>;
}

/**
 * 한 판정 실행의 고정 입력·식별 해시·소요(ADR-0066 결정 1 `이동`·결정 2).
 *
 * 종전 ④ 회사 적합성 구역 안의 `판정 기준과 실행 정보` 접힘이었다. 같은 화면
 * ⑥의 접힌 `기술 정보` 하나로 모았으므로(docs/specs/0915_ui-redesign/spec.md:234)
 * 여기서는 다시 접지 않고 값만 그린다. **값은 하나도 줄이지 않는다** — 식별자와
 * 해시는 전문을 그대로 두고 줄바꿈으로만 흐르게 한다.
 */
export function CompanyFitExecutionInfo({ attempt, label }: { attempt: CompanyFitAttempt; label: string }) {
  return <div className="company-fit-execution">
    <h4>{label}</h4>
    <dl className="company-fit-execution-facts" aria-label={`${label} 실행 정보`}>
      <div><dt>생성 시각</dt><dd>{new Date(attempt.created_at).toLocaleString("ko-KR")}</dd></div>
      <div><dt>모델</dt><dd>{attempt.model_name}</dd></div>
      <div><dt>프롬프트</dt><dd>{attempt.prompt_version}</dd></div>
      <div><dt>개요 ID</dt><dd className="mono">{attempt.overview_id}</dd></div>
      <div><dt>개요 식별 해시</dt><dd className="mono">{attempt.overview_sha256}</dd></div>
      {attempt.lineage === "card" ? <>
        <div><dt>판정 기준</dt><dd>사업 범위 카드</dd></div>
        <div><dt>판정 주체</dt><dd>{attempt.judged_by === "claude_reference" ? CLAUDE_REFERENCE_LABEL : attempt.judged_by === "model" ? "모델" : "미확인"}</dd></div>
        <div><dt>카드 버전</dt><dd className="mono">{attempt.card_version ?? "미확인"}</dd></div>
        <div><dt>카드 식별 해시</dt><dd className="mono">{attempt.card_sha256 ?? "미확인"}</dd></div>
      </> : <>
        <div><dt>회사 프로필 버전</dt><dd className="mono">{attempt.profile_version_id ?? "미확인"}</dd></div>
        <div><dt>회사 프로필 식별 해시</dt><dd className="mono">{attempt.profile_sha256 ?? "미확인"}</dd></div>
      </>}
      <div><dt>정책 식별 해시</dt><dd className="mono">{attempt.policy_digest}</dd></div>
      <div><dt>모델 버전</dt><dd className="mono">{attempt.model_revision}</dd></div>
      <div><dt>입력 토큰</dt><dd>{attempt.prompt_tokens ?? "미측정"}</dd></div>
      <div><dt>출력 토큰</dt><dd>{attempt.output_tokens ?? "미측정"}</dd></div>
      <div><dt>소요 시간</dt><dd>{attempt.latency_ms === null ? "미측정" : `${attempt.latency_ms}ms`}</dd></div>
      {attempt.error_code ? <div><dt>처리 사유</dt><dd>{attempt.error_code}</dd></div> : null}
    </dl>
  </div>;
}

/** 카드 lineage 모드(PS-01 C4)의 읽기 전용 표시. 바꾸는 조작은 화면에 없다(모드 변경은 운영 절차). */
export function CompanyFitModeInfo({ mode }: { mode: CompanyFitMode }) {
  return <div className="company-fit-execution">
    <h4>회사 핏 모드</h4>
    <dl className="company-fit-execution-facts" aria-label="회사 핏 모드">
      <div><dt>모드</dt><dd>{MODE_LABEL[mode.mode] ?? mode.mode}</dd></div>
      <div><dt>실행기 적용</dt><dd>{mode.effective ? "적용 중" : "적용 안 됨"}</dd></div>
      <div><dt>사유 코드</dt><dd className="mono">{mode.reason_code ?? "없음"}</dd></div>
      <div><dt>카드 버전</dt><dd className="mono">{mode.card_version ?? "확인 불가"}</dd></div>
      <div><dt>카드 식별 해시</dt><dd className="mono">{mode.card_sha256 ?? "확인 불가"}</dd></div>
      <div><dt>프롬프트 버전</dt><dd className="mono">{mode.prompt_version}</dd></div>
    </dl>
  </div>;
}

/**
 * ⑥ 접힌 `기술 정보`의 세 덩어리 중 하나. 현재 판정과 이전 판정의 실행 정보를
 * 모두 담는다 — ④에서 뺀 값이 어느 것도 화면에서 사라지지 않게 한다.
 *
 * 조회 실패·구조 불일치는 "실행 기록 없음"과 다른 상태이므로 문장을 나눈다
 * (`unknown`·`null`을 확인 완료로 바꾸지 않는다).
 */
export function CompanyFitExecutionSection({
  current,
  previous,
  state,
  mode = null,
}: {
  current: CompanyFitAttempt | null;
  previous: CompanyFitAttempt[];
  /** 조회 중·확인 불가·정상은 서로 다른 상태다. 한 문장으로 합치지 않는다. */
  state: "pending" | "unavailable" | "ready";
  /** 응답의 `mode`. 화면은 `GET /mode`를 부르지 않는다(PS-01 C5). */
  mode?: CompanyFitMode | null;
}) {
  return <section className="company-fit-execution-section" aria-label="회사 적합성 실행 정보">
    <h3>회사 적합성 실행 정보</h3>
    {state === "ready" && mode ? <CompanyFitModeInfo mode={mode} /> : null}
    {state === "pending"
      ? <p role="status">회사 적합성 판정을 불러오는 중이에요.</p>
      : state === "unavailable"
        ? <p>회사 적합성 판정을 확인할 수 없어 실행 정보를 표시하지 않아요.</p>
        : current === null && previous.length === 0
          ? <p>회사 적합성 판정 실행 기록이 없어요.</p>
          : null}
    {current ? <CompanyFitExecutionInfo attempt={current} label="현재 판정" /> : null}
    {previous.map((attempt, index) => (
      <CompanyFitExecutionInfo key={attempt.id} attempt={attempt} label={`이전 판정 ${index + 1}`} />
    ))}
  </section>;
}

function Assessment({ attempt, suggested = false }: { attempt: CompanyFitAttempt; suggested?: boolean }) {
  return <div className="company-fit-assessment">
    <CompanyFitVerdict attempt={attempt} />
    {suggested ? <p role="note" className="company-fit-notice company-fit-suggestion">{ENGINE_SUGGESTION_NOTICE}</p> : null}
    <CompanyFitBody attempt={attempt} />
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
    && data.schema_version === "bidops.prespec-company-fit.v2"
    && data.notice_id === noticeId
    && !data.attempts.some(a => a.notice_id !== noticeId || (a.result && a.result.schema_version !== "bidops.prespec-company-fit-result.v1"));
  const currentAttempt = data?.attempts[0] ?? null;
  const previousAttempts = data?.attempts.slice(1) ?? [];
  return { query, isValid, data, currentAttempt, previousAttempts };
}

/**
 * 회사 적합성 자동 판정 스위치 안내. 2026-11-19(사전규격 단계 수정안 §3 B): 기존 자동 심층
 * 검토의 생성 여부·사유와 보고서 링크는 화면에서 내려갔다. 응답의 `deep_review_id`·
 * `auto_deep_review_reason`은 계약에 그대로 있고 화면만 읽지 않는다.
 */
export function CompanyFitAutomationNotice({ data }: { data: CompanyFitResponse }) {
  if (data.automation_enabled) return null;
  return <p className="company-fit-notice">회사 적합성 자동 판정은 비활성이에요.</p>;
}

/**
 * 사전규격의 회사 적합성: 판정 한 줄(품질 표식·판정 주체 포함), 판단 근거(공고 원문·회사 기준), 확인할 사항.
 *
 * `compact`는 상세 `회사 관련성 참고`의 좁은 가운데 열이다. 판정 없음 + 자동 판정 비활성이면 한 줄로 줄인다.
 * `showSuggestion=false`는 분석이 이미 있는 화면(분석 작업대)에서 추적 시작 안내를 숨긴다.
 * 자동 판정 비활성 안내는 판정이 없을 때만 여기 둔다 — 판정이 있으면 `처리 상태·기술 정보` 요약 줄이 말한다.
 */
export function CompanyFitSection({ noticeId, compact = false, showSuggestion = true }: { noticeId: number; compact?: boolean; showSuggestion?: boolean }) {
  const { query, isValid, data, currentAttempt, previousAttempts } = useCompanyFit(noticeId);
  const className = compact ? "company-fit is-compact" : "company-fit";
  if (compact && !query.isError && isValid && data !== null && !data.automation_enabled && !currentAttempt) {
    return <section className={className} aria-label="회사 업무 부합 여부">
      <p>{NO_CURRENT_ATTEMPT_NOTICE} · 자동 판정 비활성</p>
    </section>;
  }
  return <section className={className} aria-label="회사 업무 부합 여부">
    {query.isPending ? <p role="status" className="company-fit-muted">회사 적합성 판정을 불러오는 중이에요.</p> : query.isError ? <div role="alert" className="company-fit-error">
      <p>회사 적합성 판정을 불러오지 못했어요.</p>
      <Button label="회사 적합성 다시 불러오기" size="sm" onClick={() => { void query.refetch(); }} />
    </div> : !isValid || data === null ?
      <p role="alert" className="company-fit-muted">판정 응답의 공고 또는 구조가 일치하지 않아 표시하지 않아요.</p> : <>
        {currentAttempt
          ? <Assessment attempt={currentAttempt} suggested={showSuggestion && data.engine_suggested} />
          : <><p className="company-fit-muted">{NO_CURRENT_ATTEMPT_NOTICE}</p><CompanyFitAutomationNotice data={data} /></>}
        {previousAttempts.length > 0 && <details className="company-fit-previous"><summary>이전 판정 {previousAttempts.length}건</summary>
          {previousAttempts.map(attempt => <Assessment key={attempt.id} attempt={attempt} />)}
        </details>}
      </>}
  </section>;
}
