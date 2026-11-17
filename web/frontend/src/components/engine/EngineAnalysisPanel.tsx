import { Button } from "@astryxdesign/core/Button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api";
import { describeApiError } from "../../lib/apiErrors";
import { companyContextQueryKey, getCompanyContext } from "../../lib/companyApi";
import { engineApi, engineKeys, type EngineEvidence, type EngineRun } from "../../lib/engineApi";
import { formatDateTime } from "../../lib/format";
import { qualityStatusLabel } from "../../lib/qualityStatus";
import { generateRequestId } from "../../lib/requestId";
import { ActorField } from "../common/ActorField";
import "../../styles/engine-analysis.css";

const RUN_LABEL: Record<EngineRun["status"], string> = {
  queued: "대기", running: "실행 중", completed: "실행 완료", partial: "부분 완료 · 사람 확인 필요", failed: "실패",
};
const active = (run: EngineRun | undefined) => run?.status === "queued" || run?.status === "running";

function EngineProblem({ error }: { error: unknown }) {
  const problem = describeApiError(error, "엔진 실행 정보를 확인하지 못했습니다.");
  return <p role="alert">{problem.title} {problem.detail}{problem.code ? ` (${problem.code})` : ""}</p>;
}

/** Normal prespec route uses the server's real-company context, never a guessed company. */
export function CurrentCompanyEnginePanel({ noticeId, bundleId }: { noticeId: number; bundleId: string | null }) {
  const company = useQuery({ queryKey: companyContextQueryKey, queryFn: ({ signal }) => getCompanyContext({ signal }), retry: false });
  if (company.isPending) return <p role="status">엔진 분석의 회사 기준을 확인하는 중입니다.</p>;
  if (company.isError) return <section className="engine-panel"><h3>분석 엔진 · mock 참조</h3><EngineProblem error={company.error} /><Button label="회사 기준 다시 조회" onClick={() => { void company.refetch(); }} /></section>;
  if (!company.data) return null;
  const companyId = company.data.company.company_id;
  return <EngineAnalysisPanel key={`${companyId}:${noticeId}`} companyId={companyId} noticeId={noticeId} bundleId={bundleId} />;
}

export function EngineAnalysisPanel({ companyId, noticeId, bundleId }: { companyId: string; noticeId: number; bundleId: string | null }) {
  const client = useQueryClient();
  const [actor, setActor] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // A lost POST response must retry the same receipt, not create a duplicate execution.
  const pendingRequest = useRef<{ id: string; actor: string; bundleId: string } | null>(null);
  const submitting = useRef(false);
  const list = useQuery({
    queryKey: engineKeys.list(companyId, noticeId),
    queryFn: ({ signal }) => engineApi.list(companyId, noticeId, { signal }), retry: false,
    refetchInterval: (query) => query.state.data?.items.some(active) ? 2500 : false,
  });
  const runId = selectedId ?? list.data?.items[0]?.id ?? null;
  const detail = useQuery({
    queryKey: engineKeys.detail(companyId, noticeId, runId),
    queryFn: ({ signal }) => engineApi.get(runId!, { signal }), enabled: runId !== null, retry: false,
    refetchInterval: (query) => active(query.state.data) ? 1500 : false,
  });
  const previousBundleId = useRef(bundleId);
  useEffect(() => {
    // Keep local drafts/receipts across bundle updates, but re-read the server's
    // currentness for terminal results. Initial mount already fetches both queries.
    if (previousBundleId.current === bundleId) return;
    previousBundleId.current = bundleId;
    void client.invalidateQueries({ queryKey: engineKeys.list(companyId, noticeId), exact: true });
    if (runId !== null) void client.invalidateQueries({ queryKey: engineKeys.detail(companyId, noticeId, runId), exact: true });
  }, [bundleId, client, companyId, noticeId, runId]);
  const rawRun = detail.data;
  const run = rawRun?.company_id === companyId && rawRun.notice_id === noticeId ? rawRun : undefined;
  const mutation = useMutation({
    mutationFn: async () => {
      if (!pendingRequest.current) {
        if (!bundleId) throw new Error("bundle required");
        pendingRequest.current = { id: generateRequestId(), actor: actor.trim(), bundleId };
      }
      return engineApi.create(companyId, noticeId, { bundle_id: pendingRequest.current.bundleId, request_id: pendingRequest.current.id, mode: "mock_reference" }, pendingRequest.current.actor);
    },
    onSuccess: (result) => {
      pendingRequest.current = null;
      if (result.company_id !== companyId || result.notice_id !== noticeId) return;
      client.setQueryData(engineKeys.detail(companyId, noticeId, result.id), result);
      setSelectedId(result.id);
      void client.invalidateQueries({ queryKey: engineKeys.list(companyId, noticeId) });
    },
    onError: (error) => {
      // Deterministic 4xx rejection has no receipt to recover. Network/5xx keep its UUID.
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) pendingRequest.current = null;
    },
  });
  const analysis = run?.analysis;
  const busy = mutation.isPending || active(run) || Boolean(list.data?.items.some(active));
  return (
    <section className="engine-panel" aria-label="분석 엔진 mock 참조" data-testid="engine-analysis-panel">
      <h3>분석 엔진 · mock 참조</h3>
      <p>외부 모델 전송 없이 고정 응답으로 실행 경로를 확인합니다. 품질 합격이나 운영 분석 결과가 아니며, 사람의 추적 결정·최종 입찰 Go/No-Go와 별개입니다.</p>
      <ActorField label="엔진 참조 실행 담당자 이름" value={actor} onChange={setActor} disabled={busy || pendingRequest.current !== null} />
      <div className="engine-actions">
        <Button label={pendingRequest.current && mutation.isError ? "같은 요청 다시 확인" : "mock 참조 실행"} isDisabled={(!pendingRequest.current && (!bundleId || !actor.trim())) || busy || list.isPending || list.isError} isLoading={mutation.isPending} onClick={async () => {
          if (submitting.current) return;
          submitting.current = true;
          try { await mutation.mutateAsync(); } catch { /* rendered below */ } finally { submitting.current = false; }
        }} />
        <Button label="엔진 실행 새로고침" variant="ghost" onClick={() => { void list.refetch(); if (runId) void detail.refetch(); }} />
      </div>
      {!bundleId ? <p>확정된 준비 완료 문서 묶음이 필요합니다.</p> : null}
      {list.isPending ? <p role="status">엔진 실행 이력을 불러오는 중입니다.</p> : null}
      {list.isError ? <EngineProblem error={list.error} /> : null}
      {mutation.isError ? <EngineProblem error={mutation.error} /> : null}
      {runId !== null && detail.isPending ? <p role="status" data-testid="engine-detail-pending">선택한 엔진 실행의 상세 결과를 불러오는 중입니다.</p> : null}
      {detail.isError ? <EngineProblem error={detail.error} /> : null}
      {rawRun && !run ? <p role="alert">회사·공고가 일치하지 않아 결과를 표시하지 않습니다.</p> : null}
      {!runId && list.isSuccess ? <p>엔진 실행 기록이 없습니다.</p> : null}
      {list.data && list.data.items.length > 1 ? <label className="engine-history">실행 이력<select aria-label="엔진 실행 이력" value={runId ?? ""} onChange={(event) => setSelectedId(event.target.value)}>{list.data.items.map((item) => <option key={item.id} value={item.id}>{formatDateTime(item.created_at)} · {RUN_LABEL[item.status]} · {item.id.slice(0, 8)}</option>)}</select></label> : null}
      {run ? <>
        <p role="status" data-testid="engine-run-status" data-status={run.status}>{RUN_LABEL[run.status]} · {qualityStatusLabel(run.quality_status)}</p>
        <p data-testid="engine-currentness">입력 현재성 · {run.input_currentness === "current" ? "현재 입력과 일치" : run.input_currentness === "stale" ? "입력이 변경된 과거 결과" : "확인되지 않음"}</p>
        {run.bundle_id !== bundleId ? <p>현재 문서 묶음과 다른 입력으로 실행된 기록입니다.</p> : null}
        {run.error_code ? <p role="alert">실행 오류 · {run.error_code}</p> : null}
        {run.warnings.length > 0 ? <div><h4>실행 경고</h4><ul>{run.warnings.map((warning, index) => <li key={`${index}:${warning}`}>{warning}</li>)}</ul></div> : null}
        {analysis ? <div data-testid="engine-analysis-result">
          <h4>엔진 참고 결과</h4>
          <p>{analysis.recommendation.summary}</p>
          <dl className="engine-facts">
            <dt>판정 상태</dt><dd>{analysis.assessment === null ? "표식 없음" : analysis.assessment.state === "abstain" ? "판정 유보 · 미확인 조건 확인 필요" : "엔진 참고 판정 준비됨"}</dd>
            <dt>엔진 참고 판정</dt><dd>{analysis.assessment?.decision ?? "미확인"}</dd>
            <dt>점수 구간</dt><dd>{analysis.assessment?.score_interval ? `${analysis.assessment.score_interval.min}–${analysis.assessment.score_interval.max}` : "계산 불가"}</dd>
          </dl>
          {analysis.assessment?.reason_codes.length ? <p>판정 사유 · {analysis.assessment.reason_codes.join(" · ")}</p> : null}
          <h4>참여 조건</h4>
          {analysis.gates.length ? <ul className="engine-result-list">{analysis.gates.map((gate, index) => <li key={`${index}:${gate.code}`}>
            <strong>{gate.code} · {gate.verdict === "UNKNOWN" ? "미확인 (UNKNOWN)" : gate.verdict}</strong>
            <p>{gate.rule_text}</p><p>회사 입력 · {gate.company_value}</p>
            {gate.action ? <p>확인할 일 · {gate.action}</p> : null}
            {gate.unknown_fields.length ? <p>미확인 항목 · {gate.unknown_fields.join(" · ")}</p> : null}
            <EvidenceList evidence={gate.evidence} />
          </li>)}</ul> : <p>참여 조건 결과 없음</p>}
          <h4>요구사항 대응</h4>
          {analysis.fits.length ? <ul className="engine-result-list">{analysis.fits.map((fit, index) => <li key={`${index}:${fit.req_id}`}><strong>{fit.req_id} · {fit.fit}</strong><p>{fit.rationale}</p>{fit.gap_action ? <p>{fit.gap_action}</p> : null}<EvidenceList evidence={fit.evidence ? [fit.evidence] : []} /></li>)}</ul> : <p>요구사항 대응 결과 없음 · 대응 가능으로 해석하지 않습니다.</p>}
          <h4>추가 확인</h4>
          {analysis.data_to_confirm.length ? <ul>{analysis.data_to_confirm.map((item, index) => <li key={`${index}:${item.field}`}>{item.field} · {item.why}</li>)}</ul> : <p>등록된 확인 항목 없음</p>}
          {analysis.recommendation.preconditions.length ? <><h4>전제 조건</h4><ul>{analysis.recommendation.preconditions.map((text, index) => <li key={index}>{text}</li>)}</ul></> : null}
          {analysis.recommendation.why_not.length ? <><h4>제약 사유</h4><ul>{analysis.recommendation.why_not.map((text, index) => <li key={index}>{text}</li>)}</ul></> : null}
        </div> : <p>{active(run) ? "분석 결과를 기다리고 있습니다." : "저장된 분석 결과가 없습니다."}</p>}
        <details><summary>실행 식별 정보</summary><dl className="engine-facts"><dt>실행</dt><dd>{run.id}</dd><dt>회사</dt><dd>{run.company_id}</dd><dt>문서 묶음</dt><dd>{run.bundle_id}</dd><dt>엔진 버전</dt><dd>{run.engine_version}</dd><dt>엔진 SHA-256</dt><dd>{run.engine_sha256}</dd><dt>회사 프로필 버전</dt><dd>{run.profile_version_id}</dd><dt>회사 그래프 버전</dt><dd>{run.graph_version_id}</dd><dt>입력 SHA-256</dt><dd>{run.input_sha256}</dd></dl></details>
      </> : null}
    </section>
  );
}

function EvidenceList({ evidence }: { evidence: EngineEvidence[] }) {
  if (!evidence.length) return <p>연결된 원문 근거 없음</p>;
  return <ul>{evidence.map((item, index) => <li key={index}><q>{item.quote}</q> · {item.page === null ? "쪽 미확인" : `${item.page}쪽`} · {item.verified === null ? "검증 대기" : item.verified ? "인용 검증됨" : "인용 검증 실패"} · 위치 {item.location_status}</li>)}</ul>;
}
