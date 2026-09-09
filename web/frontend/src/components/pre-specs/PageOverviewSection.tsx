import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Token } from "@astryxdesign/core/Token";
import { Button } from "@astryxdesign/core/Button";
import { useEffect, useRef } from "react";
import { api } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { qualityStatusLabel } from "../../lib/qualityStatus";
import type {
  PageOverviewCurrent,
  PageOverviewCurrentStatus,
  PageOverviewFact,
  PageOverviewView,
} from "../../lib/types";
import "../../styles/page-overview.css";

const CURRENT_STATUS_LABEL: Record<PageOverviewCurrentStatus, string> = {
  queued: "개요 검토 대기",
  running: "개요 검토 실행 중",
  completed: "개요 검토 완료",
  failed: "개요 검토 실패",
  needs_human_review: "사람 확인 필요",
  stale: "현재성 확인 필요",
  cancelled: "개요 검토 취소",
};

const CURRENT_STATUS_DESCRIPTION: Record<PageOverviewCurrentStatus, string> = {
  queued: "개요 검토 대기 중입니다. 선택한 PDF 입력의 실행을 기다리고 있습니다.",
  running: "개요 검토 중입니다. 선택한 PDF 입력의 근거를 검증하고 있습니다.",
  completed: "개요 검토가 완료되었습니다.",
  failed: "개요 검토에 실패했습니다. 사람 확인이 필요합니다.",
  needs_human_review: "개요 입력과 근거를 사람이 확인해야 합니다.",
  stale: "이전 입력 기준의 결과는 현재 결과로 사용할 수 없습니다. 사람 확인이 필요합니다.",
  cancelled: "개요 검토가 취소되었습니다. 사람 확인이 필요합니다.",
};

const CURRENT_STATUS_VALUES: readonly PageOverviewCurrentStatus[] = [
  "queued",
  "running",
  "completed",
  "failed",
  "needs_human_review",
  "stale",
  "cancelled",
];

const TERMINAL_CURRENT_STATUSES: readonly PageOverviewCurrentStatus[] = [
  "completed",
  "failed",
  "needs_human_review",
  "stale",
  "cancelled",
];

function isValidCurrentStatus(value: unknown): value is PageOverviewCurrentStatus {
  return typeof value === "string" && CURRENT_STATUS_VALUES.includes(value as PageOverviewCurrentStatus);
}

function currentResultFor(
  current: PageOverviewCurrent | null | undefined,
  reviews: PageOverviewView[],
): PageOverviewView | null {
  if (!current || current.status !== "completed" || !current.result_id) return null;
  const result = reviews.find((review) => review.id === current.result_id) ?? null;
  return result?.validation_status === "passed" && result.evidence_check_status === "passed" ? result : null;
}

// Presentation only: preserve raw output, hide only a suffix matching the separate page links.
function displayFact(fact: PageOverviewFact): string {
  const match = fact.text.match(/\s*\((PDF\s*\d+\s*페이지(?:\s*[·,]\s*PDF\s*\d+\s*페이지)*|PDF\s*\d+(?:\s*[,·]\s*\d+)*\s*페이지)\)\s*$/);
  const pages = new Set(match?.[1].match(/\d+/g)?.map(Number) ?? []);
  return match && pages.size === new Set(fact.evidence_pages).size && fact.evidence_pages.every(n => pages.has(n))
    ? fact.text.slice(0, match.index) : fact.text;
}

export function PageOverviewResult({ review }: { review: PageOverviewView }) {
  const payload = review.payload;
  const pdfUrl = `/api/pre-specs/${review.notice_id}/overview-pages/${review.id}/pdf`;
  const facts = (title: string, items: PageOverviewFact[], ordered = false) => (
    <section className="page-overview-section">
      <h4>{title}</h4>
      {items.length === 0 ? <p className="page-overview-note">이번 입력에서는 확인되지 않았습니다.</p> : (
        <ol className={ordered ? "page-overview-tasks" : "page-overview-facts"}>
          {items.map((fact, i) => <li key={i}>
            <p>{displayFact(fact)}</p>
            <div className="page-overview-links" aria-label="PDF 페이지 근거">
              {[...new Set(fact.evidence_pages)].sort((a, b) => a - b).map(page => (
                review.reviewed_pages.includes(page) && page <= review.pdf_page_count ? <a key={page} href={`${pdfUrl}#page=${page}`} target="_blank" rel="noreferrer">PDF {page}페이지 ↗</a> : <span key={page}>PDF {page}페이지 · 근거 위치 확인 필요</span>
              ))}
            </div>
          </li>)}
        </ol>
      )}
    </section>
  );
  return <section className="page-overview" aria-label="PDF 기반 개요 검토">
    <header className="page-overview-heading">
      <h3>개요 검토 결과</h3>
      <Token label={qualityStatusLabel(review.quality_status)} size="sm" />
    </header>
    <div className="page-overview-validation" role="status">
      <strong>{review.validation_status === "failed" ? "검증 실패 · 사람 확인 필요" : "근거 검사 통과 · 참조 결과"}</strong>
      <p>사업 설명을 위한 요약입니다. 추적 승인과 최종 입찰 결정은 사람이 진행하며, 현재 회사 핏과 조건을 충족한 경우에만 심층 검토가 자동 시작됩니다.</p>
      {review.validation_status === "failed" && review.evidence_check_status === "passed" ? (
        <p>새 페이지 근거 검사는 통과했으나, 원실행의 검증 실패 기록은 유지합니다.</p>
      ) : null}
    </div>
    {facts("사업 개요", payload.business_overview)}
    {facts("주요 과업", payload.main_tasks, true)}
    {facts("사업 규모와 일정", payload.budget_and_period)}
    {facts("핵심 조건", payload.important_conditions)}
    <section className="page-overview-section"><h4>검토 포인트 <span className="page-overview-note">모델 의견</span></h4>
      {payload.reviewer_analysis.map((text, i) => <p key={i}>{text}</p>)}
    </section>
    <section className="page-overview-section"><h4>추가 확인 사항</h4>
      {payload.unknowns.length ? <ul>{payload.unknowns.map((text, i) => <li key={i}>{text}</li>)}</ul> : <p className="page-overview-note">추가 확인 사항이 제시되지 않았습니다.</p>}
    </section>
    <details className="page-overview-section"><summary>검토 범위와 실행 정보</summary>
      {payload.input_limitations.map((text, i) => <p key={i}>{text}</p>)}
      <p>표지를 포함한 변환 PDF 순번 기준 · {review.reviewed_pages.join(", ")} / 총 {review.pdf_page_count}페이지. 원본 한컴 쪽 배치와 다를 수 있습니다.</p>
      <p>{review.model_name} · {review.prompt_version}</p>
      {review.validation_errors.length ? <p>검증 사유: {review.validation_errors.join(", ")}</p> : null}
      <a href={pdfUrl} target="_blank" rel="noreferrer">전체 근거 PDF 열기 ↗</a>
    </details>
  </section>;
}

function PageOverviewCurrent({
  current,
  currentResult,
}: {
  current: PageOverviewCurrent;
  currentResult: PageOverviewView | null;
}) {
  const hasUnusableCompletedResult = current.status === "completed" && currentResult === null;
  return (
    <section className="page-overview-section page-overview-current" aria-label="현재 v4 개요 실행">
      <header className="page-overview-heading">
        <h3>현재 v4 개요 실행</h3>
        <Token label={CURRENT_STATUS_LABEL[current.status]} size="sm" />
      </header>
      <div className="page-overview-validation" role={current.status === "failed" ? "alert" : "status"}>
        <strong>{CURRENT_STATUS_DESCRIPTION[current.status]}</strong>
        {hasUnusableCompletedResult ? (
          <p>검증 통과한 현재 결과를 확인할 수 없어 본문을 표시하지 않습니다.</p>
        ) : null}
        <details className="page-overview-execution-details">
          <summary>실행 정보</summary>
          <dl className="page-overview-execution-meta">
            <div><dt>시도 ID</dt><dd>{current.attempt_id ?? "시도 식별자 없음"}</dd></div>
            <div><dt>프롬프트</dt><dd>{current.prompt_version ?? "프롬프트 미확인"}</dd></div>
            <div><dt>실행 시각</dt><dd>{formatDateTime(current.created_at)}</dd></div>
            <div><dt>결과 ID</dt><dd>{current.result_id ?? "결과 없음"}</dd></div>
            {current.reason_code ? <div><dt>처리 사유 코드</dt><dd>{current.reason_code}</dd></div> : null}
          </dl>
        </details>
      </div>
    </section>
  );
}

function PageOverviewHistory({ reviews }: { reviews: PageOverviewView[] }) {
  if (reviews.length === 0) return null;
  return (
    <details className="page-overview-section page-overview-history">
      <summary>이전 개요 결과 {reviews.length}건</summary>
      <ol className="page-overview-history-list">
        {reviews.map((review) => {
          const pdfUrl = `/api/pre-specs/${review.notice_id}/overview-pages/${review.id}/pdf`;
          return (
            <li key={review.id} className="page-overview-history-item">
              <details>
                <summary>실행 시각 · {formatDateTime(review.created_at)} · {qualityStatusLabel(review.quality_status)} · 결과 ID · {review.id}</summary>
                <PageOverviewResult review={review} />
                <div className="page-overview-history-links">
                  {review.validation_errors.length ? <p>검증 사유 · {review.validation_errors.join(", ")}</p> : null}
                  <a href={pdfUrl} target="_blank" rel="noreferrer">이력 근거 PDF 열기 ↗</a>
                </div>
              </details>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

export function PageOverviewSection({ noticeId }: { noticeId: number }) {
  const queryClient = useQueryClient();
  const terminalSyncKey = useRef<string | null>(null);
  const query = useQuery({
    queryKey: ["pre-spec-overview-pages", noticeId],
    queryFn: ({ signal }) => api.getPageOverviews(noticeId, { signal }),
    retry: false,
    refetchInterval: (currentQuery) => {
      const status = currentQuery.state.data?.current?.status;
      return status === "queued" || status === "running" ? 5000 : false;
    },
  });

  const current = query.data?.current ?? null;
  const currentSyncKey = current && TERMINAL_CURRENT_STATUSES.includes(current.status)
    ? `${current.attempt_id}:${current.status}:${current.result_id ?? ""}:${current.created_at}`
    : null;

  useEffect(() => {
    if (currentSyncKey === null) {
      terminalSyncKey.current = null;
      return;
    }
    if (terminalSyncKey.current === currentSyncKey) return;
    terminalSyncKey.current = currentSyncKey;
    // The projection becomes authoritative only after the terminal current state
    // is visible. Refresh the list, detail projection, v2 status card, and company
    // fit query that may have been waiting on the v4 result.
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["pre-specs"] }),
      queryClient.invalidateQueries({ queryKey: ["pre-spec-detail", noticeId] }),
      queryClient.invalidateQueries({ queryKey: ["pre-spec-overview-reviews-v2", noticeId] }),
      queryClient.invalidateQueries({ queryKey: ["pre-spec-company-fit", noticeId] }),
    ]);
  }, [currentSyncKey, noticeId, queryClient]);

  if (query.isPending) return <p role="status">PDF 기반 개요를 불러오는 중입니다.</p>;
  if (query.isError) return <div role="alert" className="page-overview-validation">
    <p>PDF 기반 개요를 불러오지 못했습니다. 아래 기존 개요 기록과는 별도 조회입니다.</p>
    <Button label="개요 다시 불러오기" size="sm" onClick={() => { void query.refetch(); }} />
  </div>;
  if (query.data.schema_version !== "bidops.prespec-overview-pages.v1" || query.data.notice_id !== noticeId || query.data.reviews.some(r => r.notice_id !== noticeId || r.payload.schema_version !== "bidops.prespec-overview-page-review.v3") || (query.data.current !== null && query.data.current !== undefined && !isValidCurrentStatus(query.data.current.status))) {
    return <p role="alert">개요 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.</p>;
  }

  const hasCurrentProjection = query.data.current !== null && query.data.current !== undefined;
  const currentResult = currentResultFor(query.data.current, query.data.reviews);
  if (!hasCurrentProjection) {
    const legacyReview = query.data.reviews[0];
    return legacyReview ? <>
      <PageOverviewResult review={legacyReview} />
      <h3 className="page-overview-legacy">기존 개요 권고·처리 기록</h3>
      <PageOverviewHistory reviews={query.data.reviews.slice(1)} />
    </> : null;
  }

  const history = query.data.reviews.filter((review) => review.id !== currentResult?.id);
  return <>
    {current ? <PageOverviewCurrent current={current} currentResult={currentResult} /> : null}
    {currentResult ? <PageOverviewResult review={currentResult} /> : null}
    <PageOverviewHistory reviews={history} />
  </>;
}
