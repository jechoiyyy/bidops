import { useId, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ActorField } from "../common/ActorField";
import { Badge } from "../common/Badge";
import { DataTable } from "../common/DataTable";
import { DisabledReason } from "../common/DisabledReason";
import { MutationFeedback } from "../common/MutationFeedback";
import { ReviewEvidenceList } from "../common/ReviewPrimitives";
import { api } from "../../lib/api";
import { describeApiError } from "../../lib/apiErrors";
import {
  PRE_SPEC_OVERVIEW_RANGE_SOURCE_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
  preSpecOverviewReasonLabel,
  preSpecOverviewStatusVariant,
} from "../../lib/preSpecOverviewStatus";
import type {
  OverviewClaim,
  OverviewEnvelope,
  OverviewEvidence,
  OverviewFailedClaim,
  OverviewRun,
  OverviewRunResult,
} from "../../lib/types";

/**
 * 사전규격 개요 검토(`bidops.prespec-overview.v1`) 한 자리.
 *
 * 이 화면은 서버가 준 run 하나를 그대로 읽는다. 상태를 다시 판정하지 않고,
 * `completed`가 아닌 run에서 완료 본문을 만들지 않으며, 검증을 통과하지 못한
 * 인용을 근거처럼 보여 주지 않는다(CLAUDE.md 강제 게이트).
 */

const OVERVIEW_SCHEMA = "bidops.prespec-overview.v1";

type ResultSectionKey = "business_overview" | "main_tasks" | "budget_and_period" | "important_conditions";

const RESULT_SECTIONS: readonly { key: ResultSectionKey; title: string }[] = [
  { key: "business_overview", title: "사업 개요" },
  { key: "main_tasks", title: "주요 과업" },
  { key: "budget_and_period", title: "예산과 기간" },
  { key: "important_conditions", title: "중요 조건" },
];

const SECTION_TITLE: Record<string, string> = Object.fromEntries(
  RESULT_SECTIONS.map((section) => [section.key, section.title]),
);

/** 계약에 없는 섹션 key는 문구를 지어내지 않고 그대로 보여 준다. */
function sectionTitle(key: string): string {
  return SECTION_TITLE[key] ?? key;
}

/** 64자 digest는 줄을 통째로 먹는다. 값을 바꾸지 않고 앞뒤만 남기며 전문은
 * `title`에 그대로 둔다(CriteriaPrimitives의 `shortIdentifier`와 같은 규칙). */
function shortRevision(value: string | null): string {
  if (!value) return "미확인";
  return value.length <= 20 ? value : `${value.slice(0, 12)}…${value.slice(-6)}`;
}

function runDateTime(value: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return "미확인";
  return new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
}

/** 읽은 쪽 범위 한 줄. 준비 전에는 쪽이 `null`이며 1쪽으로 접지 않는다. */
function rangeText(run: OverviewRun): string {
  const pages = run.page_start !== null && run.page_end !== null
    ? `p.${run.page_start}–${run.page_end}`
    : "쪽 범위 미확정";
  return `${pages} · ${PRE_SPEC_OVERVIEW_RANGE_SOURCE_LABEL[run.range_source]}`;
}

function ReasonList({ codes, label }: { codes: string[]; label: string }) {
  if (codes.length === 0) return null;
  return (
    <ul aria-label={label} className="pre-spec-overview-list">
      {codes.map((code) => <li key={code}>{preSpecOverviewReasonLabel(code)}</li>)}
    </ul>
  );
}

/** 인용 하나마다 고정 스냅샷 PDF의 그 쪽을 새 탭으로 연다. */
function EvidenceLinks({ evidence, pdfUrl }: { evidence: OverviewEvidence[]; pdfUrl: string }) {
  if (evidence.length === 0) {
    return <span className="pre-spec-overview-unverifiable">검증된 인용 없음</span>;
  }
  return (
    <span className="ps-refs">
      {evidence.map((item, index) => (
        <a
          className="ps-ref"
          href={`${pdfUrl}#page=${item.page}`}
          key={`${item.page}-${index}`}
          rel="noreferrer"
          target="_blank"
          title={item.quote}
        >
          p.{item.page}
        </a>
      ))}
    </span>
  );
}

function ClaimSection({ claims, pdfUrl, title }: { claims: OverviewClaim[]; pdfUrl: string; title: string }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="pre-spec-overview-section">
      <h4 className="ps-sub" id={headingId}>{title}</h4>
      {claims.length === 0 ? (
        <p className="pre-spec-overview-empty">이 항목에서 확인된 주장이 없습니다.</p>
      ) : (
        <ReviewEvidenceList
          items={claims.map((claim) => ({
            id: claim.claim_id,
            locator: <EvidenceLinks evidence={claim.evidence} pdfUrl={pdfUrl} />,
            title: claim.text,
          }))}
          label={`${title} 주장`}
        />
      )}
    </section>
  );
}

function TextSection({ items, note, title }: { items: string[]; note?: string; title: string }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="pre-spec-overview-section">
      <h4 className="ps-sub" id={headingId}>{title}</h4>
      {note ? <p className="pre-spec-overview-limit">{note}</p> : null}
      {items.length === 0 ? (
        <p className="pre-spec-overview-empty">기록된 항목이 없습니다.</p>
      ) : (
        <ul className="pre-spec-overview-list">{items.map((item, index) => <li key={index}>{item}</li>)}</ul>
      )}
    </section>
  );
}

/** 완료된 개요 본문. `result`가 없으면 본문을 만들어 내지 않는다. */
function CompletedResult(
  { failedClaims, pdfUrl, result }: { failedClaims: OverviewFailedClaim[]; pdfUrl: string; result: OverviewRunResult },
) {
  return (
    <div className="pre-spec-overview-content">
      {RESULT_SECTIONS.map((section) => (
        <ClaimSection claims={result[section.key]} key={section.key} pdfUrl={pdfUrl} title={section.title} />
      ))}
      {failedClaims.length > 0 ? (
        <Collapsible trigger={`제외된 주장 ${failedClaims.length}건 (원문 대조 실패)`}>
          <FailedClaims
            claims={failedClaims}
            intro="원문 대조에 실패해 결과에서 제외한 주장입니다. 개요 본문에는 포함되지 않았습니다."
            pdfUrl={pdfUrl}
          />
        </Collapsible>
      ) : null}
      <TextSection
        items={result.reviewer_analysis.map((analysis) => (
          analysis.supporting_claim_ids.length > 0
            ? `${analysis.text} (근거 주장 · ${analysis.supporting_claim_ids.join(", ")})`
            : analysis.text
        ))}
        note="모델이 적은 의견입니다. 원문에서 확인된 사실이 아니며 참여 결정을 대신하지 않습니다."
        title="검토자 분석"
      />
      <TextSection items={result.unknowns} title="확인 못 한 항목" />
      <TextSection
        items={result.input_limitations}
        note="이 범위 밖의 내용은 읽지 않았습니다."
        title="입력 한계"
      />
    </div>
  );
}

/** 사람이 확인해야 하는 주장. `needs_human_review`에서는 완료 본문 대신 이것만
 * 보여 주고, completed에서는 결과 4섹션 아래 접이식으로 함께 보여 준다. 두
 * 맥락의 안내 문구가 달라 `intro`로 넘긴다(기본값은 needs_human_review 문구). */
function FailedClaims({
  claims,
  intro = "검증을 통과하지 못한 주장이 있어 개요를 완료로 두지 않았습니다. 아래 주장을 원문과 대조하고, 필요하면 읽을 범위를 다시 지정하십시오. 화면이 자동으로 고치지 않습니다.",
  pdfUrl,
}: { claims: OverviewFailedClaim[]; intro?: string; pdfUrl: string }) {
  return (
    <section aria-label="근거 확인이 필요한 주장" className="pre-spec-overview-section">
      <p className="pre-spec-overview-waiting">
        <strong>근거 확인 필요</strong>
        <span>{intro}</span>
      </p>
      {claims.length === 0 ? (
        <p className="pre-spec-overview-empty">서버가 실패한 주장 목록을 남기지 않았습니다.</p>
      ) : (
        <ReviewEvidenceList
          items={claims.map((claim) => ({
            detail: `${sectionTitle(claim.section)} · ${claim.reason_codes.map(preSpecOverviewReasonLabel).join(" / ")}`,
            id: claim.claim_id,
            locator: <EvidenceLinks evidence={claim.evidence} pdfUrl={pdfUrl} />,
            title: claim.text,
            tone: "warning" as const,
          }))}
          label="근거 확인이 필요한 주장"
        />
      )}
    </section>
  );
}

/** 담당자가 읽을 쪽 범위를 다시 정한다. 활성 run이 있으면 보낼 수 없다. */
function RangeForm({ hasActiveRun, noticeId }: { hasActiveRun: boolean; noticeId: number }) {
  const queryClient = useQueryClient();
  const reasonId = useId();
  const [pageStart, setPageStart] = useState("");
  const [pageEnd, setPageEnd] = useState("");
  const [note, setNote] = useState("");
  const [actorName, setActorName] = useState("");

  const mutation = useMutation({
    mutationFn: () => api.confirmPreSpecOverviewRange(
      noticeId,
      { page_start: Number(pageStart), page_end: Number(pageEnd), ...(note.trim() ? { note: note.trim() } : {}) },
      actorName.trim(),
    ),
    onSuccess: () => {
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["pre-spec-overview", noticeId] });
      void queryClient.invalidateQueries({ queryKey: ["pre-spec-detail", noticeId] });
    },
  });

  const start = Number(pageStart);
  const end = Number(pageEnd);
  const rangeReady = /^\d+$/.test(pageStart) && /^\d+$/.test(pageEnd) && start >= 1 && end >= start;
  const canSubmit = rangeReady && actorName.trim().length > 0 && !hasActiveRun && !mutation.isPending;

  return (
    <form
      aria-label="개요 입력 범위 다시 지정"
      className="pre-spec-overview-section"
      onSubmit={(event) => { event.preventDefault(); if (canSubmit) mutation.mutate(); }}
    >
      <h4 className="ps-sub">읽을 범위 다시 지정</h4>
      <p className="pre-spec-overview-limit">
        표지를 포함해 세는 물리 PDF 쪽 번호입니다. 인쇄 쪽수·목차 숫자와 다를 수 있습니다.
      </p>
      <TextInput
        isDisabled={hasActiveRun}
        label="시작 쪽"
        onChange={setPageStart}
        size="sm"
        value={pageStart}
      />
      <TextInput
        isDisabled={hasActiveRun}
        label="끝 쪽"
        onChange={setPageEnd}
        size="sm"
        value={pageEnd}
      />
      <TextInput
        isDisabled={hasActiveRun}
        isOptional
        label="메모"
        onChange={setNote}
        placeholder="이 범위를 고른 이유를 남깁니다."
        size="sm"
        value={note}
      />
      <ActorField onChange={setActorName} value={actorName} />
      <Button
        aria-describedby={hasActiveRun ? `${reasonId}-disabled` : undefined}
        isDisabled={!canSubmit}
        label={mutation.isPending ? "예약하는 중" : "이 범위로 다시 검토"}
        size="sm"
        type="submit"
      />
      {hasActiveRun ? (
        <DisabledReason id={`${reasonId}-disabled`}>
          실행 중이거나 대기 중인 개요 검토가 끝나야 새 범위를 보낼 수 있습니다.
        </DisabledReason>
      ) : null}
      {mutation.isError ? (
        <MutationFeedback
          problem={describeApiError(mutation.error, "범위를 확정하지 못했습니다.")}
          tone="error"
        />
      ) : null}
      {mutation.isSuccess ? (
        <MutationFeedback tone={mutation.data.attempt_enqueued ? "success" : "warning"}>
          {mutation.data.attempt_enqueued
            ? `새 개요 검토를 예약했습니다 · run ${mutation.data.run_id}`
            : `범위는 저장했지만 실행이 예약되지 않았습니다 · run ${mutation.data.run_id}`}
        </MutationFeedback>
      ) : null}
    </form>
  );
}

function RunBody({ noticeId, run }: { noticeId: number; run: OverviewRun }) {
  const pdfUrl = api.preSpecOverviewRunPdfUrl(noticeId, run.id);
  if (run.status === "completed") {
    return run.result
      ? <CompletedResult failedClaims={run.failed_claims} pdfUrl={pdfUrl} result={run.result} />
      : <p className="pre-spec-overview-empty">완료로 기록됐지만 응답에 개요 본문이 없습니다. 화면이 본문을 만들지 않습니다.</p>;
  }
  if (run.status === "needs_human_review") {
    return <FailedClaims claims={run.failed_claims} pdfUrl={pdfUrl} />;
  }
  if (run.status === "failed" || run.status === "cancelled") {
    return (
      <div className="pre-spec-overview-section">
        <p className="pre-spec-overview-empty">
          {run.status === "failed"
            ? "개요 검토가 실패했습니다. 결과 본문은 없습니다."
            : "개요 검토가 취소됐습니다. 실패와 다른 상태입니다."}
        </p>
        {run.reason_codes.length === 0
          ? <p className="pre-spec-overview-empty">서버가 사유 코드를 남기지 않았습니다.</p>
          : <ReasonList codes={run.reason_codes} label="실행 사유" />}
      </div>
    );
  }
  return (
    <p className="pre-spec-overview-waiting" role="status">
      <strong>{run.status === "queued" ? "실행 대기 중" : "실행 중"}</strong>
      <span>끝나면 개요 본문과 근거가 여기에 표시됩니다. 아직 결과가 없습니다.</span>
    </p>
  );
}

export function OverviewSection({ noticeId }: { noticeId: number }) {
  const query = useQuery({
    queryKey: ["pre-spec-overview", noticeId],
    queryFn: ({ signal }) => api.getPreSpecOverview(noticeId, { signal }),
    retry: false,
    staleTime: 30_000,
  });

  const envelope: OverviewEnvelope | null = query.data ?? null;
  const isValid = envelope !== null
    && envelope.schema === OVERVIEW_SCHEMA
    && envelope.notice_id === noticeId;
  const run = isValid ? envelope.current : null;
  const history = isValid ? envelope.history : [];
  const hasActiveRun = run !== null && (run.status === "queued" || run.status === "running");

  return (
    <section aria-labelledby="pre-spec-overview-title" className="ps-card ps-sec pre-spec-overview-content">
      <div className="ps-sec-head">
        <h3 className="ps-h-sec" id="pre-spec-overview-title">개요 검토</h3>
        {run ? <Badge label={PRE_SPEC_OVERVIEW_STATUS_LABEL[run.status]} variant={preSpecOverviewStatusVariant(run.status)} /> : null}
      </div>

      {query.isPending ? <p role="status">개요 검토를 불러오는 중입니다.</p> : null}
      {query.isError ? (
        <MutationFeedback
          onRecover={() => { void query.refetch(); }}
          problem={describeApiError(query.error, "개요 검토를 불러오지 못했습니다.")}
          tone="error"
        />
      ) : null}
      {!query.isPending && !query.isError && !isValid ? (
        <p role="alert">개요 응답의 공고 또는 계약이 일치하지 않아 표시하지 않습니다.</p>
      ) : null}

      {isValid && run === null ? <p className="pre-spec-overview-empty">개요 검토가 아직 없습니다.</p> : null}

      {run ? (
        <>
          <p className="ps-s">읽은 범위 · {rangeText(run)}</p>
          <ReasonList codes={run.range_reason_codes} label="범위 선택 사유" />
          <RunBody noticeId={noticeId} run={run} />
          {run.warnings.length > 0 ? (
            <Collapsible trigger={`경고 ${run.warnings.length}건`}>
              <p className="pre-spec-overview-limit">실행을 막지 않는 대조 경고입니다. 사람이 원문과 확인합니다.</p>
              <ReasonList codes={run.warnings} label="비차단 경고" />
            </Collapsible>
          ) : null}
          <p className="pre-spec-overview-limit">
            모델 · {run.model_name} / 버전 ·{" "}
            <span title={run.model_revision ?? undefined}>{shortRevision(run.model_revision)}</span>
            {" "}· 호출 {run.call_count}회
            {run.actor_name ? ` · 범위 확정 ${run.actor_name}` : ""}
          </p>
        </>
      ) : null}

      {isValid ? <RangeForm hasActiveRun={hasActiveRun} noticeId={noticeId} /> : null}

      {history.length >= 2 ? (
        <Collapsible trigger={`실행 이력 ${history.length}건`}>
          <DataTable
            columns={[
              { key: "status", header: "상태", render: (item: OverviewRun) => PRE_SPEC_OVERVIEW_STATUS_LABEL[item.status] },
              { key: "range", header: "범위", render: (item: OverviewRun) => rangeText(item) },
              { key: "created_at", header: "생성 시각", render: (item: OverviewRun) => runDateTime(item.created_at) },
              { key: "call_count", header: "모델 호출", render: (item: OverviewRun) => `${item.call_count}회` },
            ]}
            rowKey="id"
            rows={history}
          />
        </Collapsible>
      ) : null}
    </section>
  );
}
