import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { Token } from "@astryxdesign/core/Token";
import { Button } from "@astryxdesign/core/Button";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { ActorField } from "../common/ActorField";
import { Badge } from "../common/Badge";
import { qualityStatusLabel, qualityStatusVariant } from "../../lib/qualityStatus";
import type {
  PageOverviewCurrent,
  PageOverviewCurrentStatus,
  PageOverviewFact,
  PageOverviewRangeCandidate,
  PageOverviewRangeConfirmation,
  PageOverviewRangeReview as PageOverviewRangeReviewData,
  PageOverviewResponse,
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

export function pageOverviewPdfUrl(review: PageOverviewView): string {
  return `/api/pre-specs/${review.notice_id}/overview-pages/${review.id}/pdf`;
}

export function PageOverviewFactLine({ fact, review }: { fact: PageOverviewFact; review: PageOverviewView }) {
  const pdfUrl = pageOverviewPdfUrl(review);
  return <>
    <span className="page-overview-fact-line">{displayFact(fact)}</span>
    <span className="page-overview-links" aria-label="PDF 페이지 근거">
      {[...new Set(fact.evidence_pages)].sort((a, b) => a - b).map(page => (
        review.reviewed_pages.includes(page) && page <= review.pdf_page_count
          ? <a key={page} href={`${pdfUrl}#page=${page}`} target="_blank" rel="noreferrer">PDF {page}페이지 ↗</a>
          : <span key={page}>PDF {page}페이지 · 근거 위치 확인 필요</span>
      ))}
    </span>
  </>;
}

export function PageOverviewFacts({
  title,
  items,
  review,
  ordered = false,
}: {
  title: string;
  items: PageOverviewFact[];
  review: PageOverviewView;
  ordered?: boolean;
}) {
  const List = ordered ? "ol" : "ul";
  return (
    <section className="page-overview-section">
      <h4>{title}</h4>
      {items.length === 0 ? <p className="page-overview-note">이번 입력에서는 확인되지 않았습니다.</p> : (
        <List className={ordered ? "page-overview-tasks" : "page-overview-facts"}>
          {items.map((fact, i) => <li key={i}>
            <div className="page-overview-fact-content"><PageOverviewFactLine fact={fact} review={review} /></div>
          </li>)}
        </List>
      )}
    </section>
  );
}

export function PageOverviewAnalysis({ items }: { items: string[] }) {
  return <section className="page-overview-section"><h4>검토 포인트 <span className="page-overview-note">모델 의견</span></h4>
    {items.map((text, i) => <p key={i}>{text}</p>)}
  </section>;
}

export function PageOverviewUnknowns({ items }: { items: string[] }) {
  return <section className="page-overview-section"><h4>추가 확인 사항</h4>
    {items.length ? <ul>{items.map((text, i) => <li key={i}>{text}</li>)}</ul> : <p className="page-overview-note">추가 확인 사항이 제시되지 않았습니다.</p>}
  </section>;
}

export function PageOverviewExecutionInfo({ review }: { review: PageOverviewView }) {
  const payload = review.payload;
  const pdfUrl = pageOverviewPdfUrl(review);
  return <details className="page-overview-section"><summary>검토 범위와 실행 정보</summary>
    {payload.input_limitations.map((text, i) => <p key={i}>{text}</p>)}
    <p>표지를 포함한 변환 PDF 순번 기준 · {review.reviewed_pages.join(", ")} / 총 {review.pdf_page_count}페이지. 원본 한컴 쪽 배치와 다를 수 있습니다.</p>
    <p>{review.model_name} · {review.prompt_version}</p>
    {review.validation_errors.length ? <p>검증 사유: {review.validation_errors.join(", ")}</p> : null}
    <a href={pdfUrl} target="_blank" rel="noreferrer">전체 근거 PDF 열기 ↗</a>
  </details>;
}

export function PageOverviewResult({ review }: { review: PageOverviewView }) {
  const payload = review.payload;
  return <section className="page-overview" aria-label="PDF 기반 개요 검토">
    <header className="page-overview-heading">
      <h3>개요 검토 결과</h3>
      <Badge label={qualityStatusLabel(review.quality_status)} variant={qualityStatusVariant(review.quality_status)} />
    </header>
    <div className="page-overview-validation" role="status">
      <strong>{review.validation_status === "failed" ? "검증 실패 · 사람 확인 필요" : "근거 검사 통과 · 참조 결과"}</strong>
      <p>사업 설명을 위한 요약입니다. 추적 승인과 최종 입찰 결정은 사람이 진행하며, 현재 회사 핏과 조건을 충족한 경우에만 심층 검토가 자동 시작됩니다.</p>
      {review.validation_status === "failed" && review.evidence_check_status === "passed" ? (
        <p>새 페이지 근거 검사는 통과했으나, 원실행의 검증 실패 기록은 유지합니다.</p>
      ) : null}
    </div>
    <PageOverviewFacts title="사업 개요" items={payload.business_overview} review={review} />
    <PageOverviewFacts title="주요 과업" items={payload.main_tasks} review={review} ordered />
    <PageOverviewFacts title="사업 규모와 일정" items={payload.budget_and_period} review={review} />
    <PageOverviewFacts title="핵심 조건" items={payload.important_conditions} review={review} />
    <PageOverviewAnalysis items={payload.reviewer_analysis} />
    <PageOverviewUnknowns items={payload.unknowns} />
    <PageOverviewExecutionInfo review={review} />
  </section>;
}

export function PageOverviewCurrent({
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

export function PageOverviewHistory({ reviews }: { reviews: PageOverviewView[] }) {
  if (reviews.length === 0) return null;
  return (
    <details className="page-overview-section page-overview-history">
      <summary>이전 개요 결과 {reviews.length}건</summary>
      <ol className="page-overview-history-list">
        {reviews.map((review) => {
          const pdfUrl = pageOverviewPdfUrl(review);
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

/**
 * 개요 입력 범위를 사람이 확정하는 자리(R7).
 *
 * 결정적 heading 선택기가 `ready`를 못 내면 서버는 실패 attempt 대신
 * `needs_human_review` target을 동결하고 절 후보를 드러낸다. 이 화면은 그 후보
 * 중 시작·끝을 사람이 고르게 하고 확정만 보낸다 — **확정은 개요 검토(attempt)를
 * 열지 않는다.** 모델 보조 제안은 감사 기록일 뿐이라 미리 고르는 것까지만 하고
 * 저장하지 않으며, 모델이 적은 사유 문장은 계약에 없어 화면에 실리지 않는다.
 */
const RANGE_REASON_LABEL: Record<string, string> = {
  scope_heading_missing: "범위 제목을 찾지 못함",
  scope_end_missing: "범위 끝을 찾지 못함",
  ambiguous_scope_boundary: "범위 경계가 모호함",
  ambiguous_scope: "범위 경계가 모호함",
};

/** 서버가 고정한 안전 코드의 한국어 문구. 모르는 코드는 그대로 보여 준다. */
const RANGE_ERROR_LABEL: Record<string, string> = {
  target_not_pending: "이미 다른 결정이 반영된 대상입니다. 새로 고쳐 확인하세요",
  range_invalid: "선택한 범위가 유효하지 않습니다",
  input_size_limit: "선택 범위가 입력 한도를 넘습니다",
  target_not_found: "확정 대상을 찾을 수 없습니다",
};

const RANGE_ORDER_ERROR = "끝 절은 시작 절과 같거나 뒤여야 합니다";
const RANGE_CONFIRMED_NOTE = "범위가 확정되었습니다 · 개요 검토는 자동 실행되지 않습니다";

function rangeReasonLabel(reasonCode: string | null): string {
  if (reasonCode === null) return "사유 코드 없음";
  return RANGE_REASON_LABEL[reasonCode] ?? reasonCode;
}

function RangeReviewHeading({ token }: { token: string }) {
  return (
    <header className="page-overview-heading">
      <h3>개요 입력 범위 확인</h3>
      <Token label={token} size="sm" />
    </header>
  );
}

interface RangeCandidateRow extends Record<string, unknown> {
  candidate: PageOverviewRangeCandidate;
}

/** 확정 대기: 절 후보(또는 쪽)에서 시작·끝을 사람이 고른다. */
function RangeReviewPending({
  noticeId,
  review,
  onConfirmed,
}: {
  noticeId: number;
  review: PageOverviewRangeReviewData;
  onConfirmed: () => void;
}) {
  // 후보가 없으면 쪽 범위로 확정한다. 두 방식은 body에서 정확히 하나의 쌍만 채운다.
  const pagesMode = review.candidates.length === 0;
  const [startIndex, setStartIndex] = useState<number | null>(null);
  const [endIndex, setEndIndex] = useState<number | null>(null);
  const [firstPage, setFirstPage] = useState<number | null>(null);
  const [lastPage, setLastPage] = useState<number | null>(null);
  const [actorName, setActorName] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [failure, setFailure] = useState<{ code: string | null } | null>(null);

  const start = pagesMode ? firstPage : startIndex;
  const end = pagesMode ? lastPage : endIndex;
  const selected = start !== null && end !== null;
  // 쪽 입력은 NumberInput의 min·max가 1~pdf_page_count로 이미 고정한다. 여기서
  // 더 보는 것은 두 방식에 공통인 순서 규칙뿐이다.
  const orderInvalid = selected && (end as number) < (start as number);
  const valid = selected && !orderInvalid;

  const mutation = useMutation({
    mutationFn: () => api.confirmPageOverviewRange(
      noticeId,
      pagesMode
        ? { target_id: review.target_id, start_index: null, end_index: null, first_page: firstPage, last_page: lastPage, note: null }
        : { target_id: review.target_id, start_index: startIndex, end_index: endIndex, first_page: null, last_page: null, note: null },
      actorName,
    ),
    onSuccess: () => {
      setFailure(null);
      setConfirmed(true);
      // 화면이 새 상태를 만들지 않는다. 확정 결과는 서버 응답을 다시 읽어 반영한다.
      onConfirmed();
    },
    onError: (caught: unknown) => {
      // 서버 message는 화면에 싣지 않는다. 안전 코드만 문구로 옮긴다.
      setConfirmed(false);
      setFailure({ code: caught instanceof ApiError ? caught.code : null });
    },
  });

  const locked = confirmed || mutation.isPending;
  const ready = valid && actorName.trim().length > 0 && !locked;
  const missing = !selected
    ? (pagesMode ? "시작 쪽과 끝 쪽을 입력하십시오." : "시작 절과 끝 절을 고르십시오.")
    : actorName.trim().length === 0
      ? "담당자 이름을 입력하십시오."
      : null;

  // 한 벌의 radio가 표의 행을 가로질러야 한다. Astryx `RadioList`는 자기
  // children만 묶으므로 표의 행을 가로지를 수 없어, 같은 `name`으로 묶는 native
  // radio를 쓴다(저장소의 native checkbox 사용과 같은 이유).
  const radioCell = (
    row: RangeCandidateRow,
    name: "range-start" | "range-end",
    label: string,
    value: number | null,
    onPick: (index: number) => void,
  ) => (
    <input
      type="radio"
      name={name}
      aria-label={`${label} #${row.candidate.index}`}
      checked={value === row.candidate.index}
      disabled={locked}
      onChange={() => onPick(row.candidate.index)}
    />
  );

  const columns: TableColumn<RangeCandidateRow>[] = [
    { key: "start", header: "시작", width: pixel(56), renderCell: (row) => radioCell(row, "range-start", "시작", startIndex, setStartIndex) },
    { key: "end", header: "끝", width: pixel(56), renderCell: (row) => radioCell(row, "range-end", "끝", endIndex, setEndIndex) },
    { key: "index", header: "#", width: pixel(56), renderCell: (row) => row.candidate.index },
    { key: "title", header: "절 제목", width: proportional(1), renderCell: (row) => row.candidate.title },
    { key: "page", header: "쪽", width: pixel(72), renderCell: (row) => `${row.candidate.page}쪽` },
  ];

  return (
    <section className="page-overview-section page-overview-range" aria-label="개요 범위 확인">
      <RangeReviewHeading token="범위 확인 필요" />
      <p className="page-overview-range-reason">
        <strong>확인 사유 · {rangeReasonLabel(review.reason_code)}</strong>{" "}
        결정적 선택기가 범위를 정하지 못했습니다. 사람이 시작·끝을 확정해야 개요 검토 입력이 준비됩니다. 확정해도 개요 검토는 자동 실행되지 않습니다.
      </p>

      {review.assisted ? (
        <div className="page-overview-range-assist">
          <span>
            모델 제안 · {qualityStatusLabel(review.assisted.quality_status)}: 시작 #{review.assisted.start_index} → 끝 #{review.assisted.end_index}
          </span>
          {pagesMode ? null : (
            <Button
              label="제안 적용"
              size="sm"
              variant="secondary"
              isDisabled={locked}
              onClick={() => {
                // 제안은 미리 고르기만 한다. 저장은 사람이 따로 누른다.
                setStartIndex(review.assisted?.start_index ?? null);
                setEndIndex(review.assisted?.end_index ?? null);
              }}
            />
          )}
        </div>
      ) : null}

      {pagesMode ? (
        <>
          <div className="page-overview-range-pages">
            <NumberInput
              label="시작 쪽"
              size="sm"
              value={firstPage}
              min={1}
              max={review.pdf_page_count}
              isIntegerOnly
              isWheelEnabled={false}
              isDisabled={locked}
              onChange={setFirstPage}
            />
            <NumberInput
              label="끝 쪽"
              size="sm"
              value={lastPage}
              min={1}
              max={review.pdf_page_count}
              isIntegerOnly
              isWheelEnabled={false}
              isDisabled={locked}
              onChange={setLastPage}
            />
          </div>
          <p className="page-overview-note">절 후보가 없어 쪽 범위로 확정합니다. 전체 {review.pdf_page_count}쪽</p>
        </>
      ) : (
        <div className="page-overview-range-table">
          <Table
            aria-label="개요 범위 절 후보"
            columns={columns}
            data={review.candidates.map((candidate) => ({ candidate }))}
            density="compact"
            dividers="rows"
            idKey={(row) => row.candidate.index}
            verticalAlign="top"
          />
        </div>
      )}

      {orderInvalid ? <p role="alert" className="page-overview-range-invalid">{RANGE_ORDER_ERROR}</p> : null}

      <div className="page-overview-range-form">
        <ActorField
          label="담당자 이름 (필수)"
          required
          value={actorName}
          onChange={setActorName}
          placeholder="예: 홍길동"
          autoComplete="off"
          disabled={locked}
        />
        <Button
          label={mutation.isPending ? "확정 중…" : "범위 확정"}
          size="sm"
          isDisabled={!ready}
          onClick={() => { if (ready) mutation.mutate(); }}
        />
        {missing && !confirmed ? <p className="page-overview-note">{missing}</p> : null}
      </div>

      {confirmed ? <p role="status">{RANGE_CONFIRMED_NOTE}</p> : null}
      {failure ? (
        <p role="alert" className="page-overview-range-invalid">
          {failure.code === null ? "범위 확정 요청을 보내지 못했습니다" : RANGE_ERROR_LABEL[failure.code] ?? failure.code}
        </p>
      ) : null}
    </section>
  );
}

/** 확정 완료: 무엇이 확정됐는지만 읽기 전용으로 남긴다. */
function RangeReviewConfirmed({
  review,
  confirmation,
}: {
  review: PageOverviewRangeReviewData;
  confirmation: PageOverviewRangeConfirmation;
}) {
  // index가 null이면 쪽으로 직접 확정한 것이다. 제목을 지어내지 않는다.
  const clauseTitle = (index: number | null) => index === null
    ? "쪽 범위 직접 입력"
    : review.candidates.find((candidate) => candidate.index === index)?.title ?? "절 제목 확인 불가";
  return (
    <section className="page-overview-section page-overview-range" aria-label="개요 범위 확인">
      <RangeReviewHeading token="범위 확정됨" />
      <dl className="page-overview-execution-meta">
        <div><dt>확정 쪽 범위</dt><dd>{confirmation.first_page}~{confirmation.last_page}쪽</dd></div>
        <div><dt>시작 절</dt><dd>{clauseTitle(confirmation.start_index)}</dd></div>
        <div><dt>끝 절</dt><dd>{clauseTitle(confirmation.end_index)}</dd></div>
        <div><dt>담당자</dt><dd>{confirmation.actor}</dd></div>
        <div><dt>확정 시각</dt><dd>{formatDateTime(confirmation.created_at)}</dd></div>
      </dl>
      <p className="page-overview-note">개요 검토(attempt)는 별도 승인으로만 실행됩니다</p>
    </section>
  );
}

export function PageOverviewRangeReview({
  noticeId,
  review,
  onConfirmed,
}: {
  noticeId: number;
  review: PageOverviewRangeReviewData;
  onConfirmed: () => void;
}) {
  if (review.selection_status === "ready") {
    return review.confirmation ? <RangeReviewConfirmed review={review} confirmation={review.confirmation} /> : null;
  }
  return <RangeReviewPending noticeId={noticeId} review={review} onConfirmed={onConfirmed} />;
}

type CurrentPageOverviewState = {
  query: UseQueryResult<PageOverviewResponse>;
  isValid: boolean;
  current: PageOverviewCurrent | null;
  hasCurrentProjection: boolean;
  currentResult: PageOverviewView | null;
  legacyReview: PageOverviewView | null;
  history: PageOverviewView[];
  /** 범위 사람 확인 대상이 없으면 `null`이며 그 자리를 그리지 않는다. */
  rangeReview: PageOverviewRangeReviewData | null;
};

export function useCurrentPageOverview(noticeId: number | null): CurrentPageOverviewState {
  const queryClient = useQueryClient();
  const terminalSyncKey = useRef<string | null>(null);
  const query = useQuery({
    queryKey: ["pre-spec-overview-pages", noticeId],
    queryFn: ({ signal }) => api.getPageOverviews(noticeId as number, { signal }),
    retry: false,
    enabled: noticeId !== null,
    refetchInterval: (currentQuery) => {
      const status = currentQuery.state.data?.current?.status;
      return status === "queued" || status === "running" ? 5000 : false;
    },
  });

  const current = query.data?.current ?? null;
  const currentSyncKey = current && TERMINAL_CURRENT_STATUSES.includes(current.status)
    ? `${noticeId}:${current.attempt_id}:${current.status}:${current.result_id ?? ""}:${current.created_at}`
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

  const data = query.data;
  const reviews = data?.reviews ?? [];
  const rangeReview = data?.range_review ?? null;
  const hasCurrentProjection = data?.current !== null && data?.current !== undefined;
  const currentResult = currentResultFor(current, reviews);
  const legacyReview = !hasCurrentProjection ? reviews[0] ?? null : null;
  const history = hasCurrentProjection
    ? reviews.filter((review) => review.id !== currentResult?.id)
    : reviews.slice(1);
  const isValid = data !== undefined
    && noticeId !== null
    && data.schema_version === "bidops.prespec-overview-pages.v1"
    && data.notice_id === noticeId
    && !data.reviews.some((review) => review.notice_id !== noticeId || review.payload.schema_version !== "bidops.prespec-overview-page-review.v3")
    && (data.current === null || data.current === undefined || isValidCurrentStatus(data.current.status))
    && (rangeReview === null || rangeReview.selection_status === "needs_human_review" || rangeReview.selection_status === "ready");

  return { query, isValid, current, hasCurrentProjection, currentResult, legacyReview, history, rangeReview };
}

export function PageOverviewSection({ noticeId }: { noticeId: number }) {
  const { query, isValid, current, hasCurrentProjection, currentResult, legacyReview, history, rangeReview } = useCurrentPageOverview(noticeId);

  if (query.isPending) return <p role="status">PDF 기반 개요를 불러오는 중입니다.</p>;
  if (query.isError) return <div role="alert" className="page-overview-validation">
    <p>PDF 기반 개요를 불러오지 못했습니다. 아래 기존 개요 기록과는 별도 조회입니다.</p>
    <Button label="개요 다시 불러오기" size="sm" onClick={() => { void query.refetch(); }} />
  </div>;
  if (!isValid) {
    return <p role="alert">개요 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.</p>;
  }

  // 범위 확인은 현재 실행 카드보다 위에 온다. 입력 범위가 정해지지 않으면
  // 아래 실행 기록은 아직 그 범위의 결과가 아니다.
  const rangeReviewNode = rangeReview
    ? <PageOverviewRangeReview noticeId={noticeId} review={rangeReview} onConfirmed={() => { void query.refetch(); }} />
    : null;

  if (!hasCurrentProjection) {
    return legacyReview ? <>
      {rangeReviewNode}
      <PageOverviewResult review={legacyReview} />
      <h3 className="page-overview-legacy">기존 개요 권고·처리 기록</h3>
      <PageOverviewHistory reviews={history} />
    </> : rangeReviewNode;
  }

  return <>
    {rangeReviewNode}
    {current ? <PageOverviewCurrent current={current} currentResult={currentResult} /> : null}
    {currentResult ? <PageOverviewResult review={currentResult} /> : null}
    <PageOverviewHistory reviews={history} />
  </>;
}
