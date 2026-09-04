import { useCallback, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { SplitWorkspace, StickyDecisionHeader } from "../components/common/ReviewPrimitives";
import { AttachmentPanel } from "../components/notice/AttachmentPanel";
import { CounterargumentList } from "../components/notice/CounterargumentList";
import { JudgmentBanner } from "../components/notice/JudgmentBanner";
import { NoticeFacts } from "../components/notice/NoticeFacts";
import { PerspectiveTable } from "../components/notice/PerspectiveTable";
import { RetrievalSignals } from "../components/notice/RetrievalSignals";
import { ReviewRecord } from "../components/notice/ReviewRecord";
import { VerificationItemTable } from "../components/notice/VerificationItemTable";
import { QueueFilters, type QueueFilterValues } from "../components/queue/QueueFilters";
import { QueueList } from "../components/queue/QueueList";
import { api } from "../lib/api";
import { formatPrice, present } from "../lib/format";
import { describeDeadline } from "../lib/deadline";
import type { ReviewAnswerInput } from "../lib/types";
import { gradeVariant } from "../lib/grade";
import "../styles/review-workspace-relaxed.css";

/**
 * 공고 1차 판정은 읽기 전용 이력이다 (ADR-0045 결정 3, PLAN 단계 E 작업 4).
 *
 * 이 화면이 갖고 있던 리뷰 초안·localStorage 임시 저장·`PUT /notices/{pk}/review`
 * 저장은 모두 사라졌다. 같은 저장 계약을 쓰는 사람 수정 경로는 사업 추적 상세의
 * 예외 작업이 갖고 있으며(단계 E 작업 3-2, 먼저 통과시킨 뒤 여기를 잠갔다),
 * 회차는 공고의 `run_id`를 그대로 쓰므로 누적 화면에서도 회차가 어긋나지 않는다.
 *
 * 저장이 사라졌으므로 미저장 guard도 임시 초안도 필요 없다. 저장할 것이 없는
 * 화면에서 "저장되지 않은 변경"을 경고하면 사람이 없는 위험을 찾게 된다.
 */

function filterFromParams(params: URLSearchParams, defaultSort: QueueFilterValues["sort"] = "grade"): QueueFilterValues {
  const attachment = params.get("attachment");
  const sort = params.get("sort");
  return {
    grade: params.get("grade") ?? "",
    readiness: params.get("readiness") ?? "",
    focus: params.get("focus") ?? "",
    sampleRole: params.get("sample_role") ?? "analysis",
    attachment: attachment === "none" || attachment === "manual" ? attachment : "any",
    q: params.get("q") ?? "",
    // 담당자는 등급이 높은 공고부터 처리하므로 등급순이 기본이다. 마감 추적
    // 저장된 뷰(/deadlines)로 들어오면 그 뷰의 기본 정렬을 쓴다.
    sort: sort === "deadline" || sort === "published" ? sort : defaultSort,
  };
}

const filterQueryKeys: Record<keyof QueueFilterValues, string> = {
  grade: "grade",
  readiness: "readiness",
  focus: "focus",
  sampleRole: "sample_role",
  attachment: "attachment",
  q: "q",
  sort: "sort",
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

// 목록 위를 오르내리는 단축키는 입력 중에는 동작하면 안 된다.
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

/**
 * @param defaultSort 주소에 sort가 없을 때 쓸 정렬. 마감 추적(/deadlines)은
 *   리다이렉트가 아니라 이 화면의 저장된 뷰이므로(docs/design/PLAN.md 2단계)
 *   그 경로로 들어오면 마감순을 기본으로 삼는다. 리다이렉트로 sort 파라미터를
 *   실어 보내던 방식은 AppShell의 회차 동기화와 경쟁해 파라미터를 잃었다.
 */
export function QueuePage({ defaultSort = "grade" }: { defaultSort?: QueueFilterValues["sort"] } = {}) {
  const navigate = useNavigate();
  const { noticePk: noticePkParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const runId = searchParams.get("run");
  const filters = useMemo(() => filterFromParams(searchParams, defaultSort), [searchParams, defaultSort]);
  const noticePk = noticePkParam ? Number(noticePkParam) : null;
  const selectedId = noticePk !== null && Number.isInteger(noticePk) ? noticePk : null;

  const noticesQuery = useQuery({
    queryKey: ["queue-notices", runId, filters],
    queryFn: () => api.getNotices({
      run_id: runId as string,
      grade: filters.grade || undefined,
      readiness: filters.readiness || undefined,
      focus: filters.focus || undefined,
      sample_role: filters.sampleRole,
      attachment: filters.attachment,
      q: filters.q || undefined,
      sort: filters.sort,
      limit: 500,
      offset: 0,
    }),
    enabled: Boolean(runId),
    staleTime: 10_000,
  });
  const reviewsQuery = useQuery({
    queryKey: ["reviews", runId],
    queryFn: () => api.getReviews(runId as string),
    enabled: Boolean(runId),
    staleTime: 10_000,
  });
  const detailQuery = useQuery({
    queryKey: ["notice", selectedId],
    queryFn: () => api.getNotice(selectedId as number),
    enabled: selectedId !== null,
    staleTime: 10_000,
  });

  const notices = noticesQuery.data?.items ?? [];
  const reviewsById = useMemo(
    () => new Map((reviewsQuery.data ?? []).map((review) => [review.notice_pk, review] as const)),
    [reviewsQuery.data],
  );
  const focusOptions = useMemo(
    () => Array.from(new Set(notices.map((notice) => notice.focus).filter((focus): focus is string => Boolean(focus)))).sort((a, b) => a.localeCompare(b, "ko")),
    [notices],
  );
  const detail = detailQuery.data?.id === selectedId ? detailQuery.data : undefined;
  // 저장된 리뷰는 이 회차의 것 하나다. 다른 회차의 리뷰를 이 회차의 값으로 읽지 않는다.
  const savedReview = useMemo(
    () => detail?.reviews.find((review) => review.run_id === runId),
    [detail, runId],
  );
  const savedAnswers = useMemo<ReviewAnswerInput[]>(
    () => (savedReview?.answers ?? []).map((answer) => ({ item: answer.item, answer: answer.answer })),
    [savedReview],
  );
  const detailDeadline = detail ? describeDeadline(detail.deadline_at) : null;
  const selectedIndex = notices.findIndex((notice) => notice.id === selectedId);

  useEffect(() => {
    if (!runId || noticesQuery.isLoading) return;
    if (notices.length === 0) {
      if (selectedId !== null) navigate({ pathname: "/queue", search: searchParams.toString() }, { replace: true });
      return;
    }
    // ADR-0046: 지원 폭은 1280~1920px 하나뿐이라 목록만 보여주는 좁은 폭 모드가
    // 없다. 어느 폭에서도 첫 공고를 골라 두 pane을 함께 유지한다.
    if (selectedId === null || selectedIndex === -1) {
      navigate({ pathname: `/queue/${notices[0].id}`, search: searchParams.toString() }, { replace: true });
    }
  }, [navigate, notices, noticesQuery.isLoading, runId, searchParams, selectedId, selectedIndex]);

  const setFilter = <K extends keyof QueueFilterValues>(key: K, value: QueueFilterValues[K]) => {
    const next = new URLSearchParams(searchParams);
    const serialized = String(value);
    if (!serialized || (key === "sampleRole" && serialized === "analysis") || (key === "attachment" && serialized === "any") || (key === "sort" && serialized === "grade")) {
      next.delete(filterQueryKeys[key]);
    } else {
      next.set(filterQueryKeys[key], serialized);
    }
    setSearchParams(next, { replace: true });
  };

  // 회차와 정렬은 화면의 기준이므로 남기고, 목록을 좁히던 조건만 지운다.
  const resetFilters = () => {
    const next = new URLSearchParams(searchParams);
    for (const key of ["grade", "readiness", "focus", "sample_role", "attachment", "q"]) {
      next.delete(key);
    }
    setSearchParams(next, { replace: true });
  };

  const selectNotice = useCallback(
    (id: number) => navigate({ pathname: `/queue/${id}`, search: searchParams.toString() }),
    [navigate, searchParams],
  );

  const moveSelection = useCallback(
    (step: number) => {
      if (notices.length === 0) return;
      const nextIndex = selectedIndex === -1 ? 0 : Math.min(Math.max(selectedIndex + step, 0), notices.length - 1);
      if (nextIndex === selectedIndex) return;
      selectNotice(notices[nextIndex].id);
    },
    [notices, selectNotice, selectedIndex],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || isTypingTarget(event.target)) return;
      if (event.key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        moveSelection(1);
      } else if (event.key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        moveSelection(-1);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [moveSelection]);

  if (!runId) {
    return <EmptyState title="선택된 회차가 없습니다." description="상단의 실행 회차 선택기에서 회차를 선택하십시오." />;
  }
  if (noticesQuery.error) {
    return <EmptyState title="검토 대기열을 불러오지 못했습니다." description={errorMessage(noticesQuery.error, "공고 목록을 확인할 수 없습니다.")} action={{ label: "다시 시도", onClick: () => void noticesQuery.refetch() }} />;
  }

  return (
    <div className="queue-page">
      <QueueFilters
        value={filters}
        focusOptions={focusOptions}
        onChange={setFilter}
        onReset={resetFilters}
      />
      <SplitWorkspace
        className={`queue-workspace ${selectedId !== null ? "shows-detail" : "shows-list"}`}
        detailLabel="공고 상세"
        listLabel="검토 대기 공고 목록"
      >
        <QueueList
          notices={notices}
          reviews={reviewsById}
          selectedId={selectedId}
          sort={filters.sort}
          total={noticesQuery.data?.total ?? 0}
          onSelect={selectNotice}
        />
        <section className="queue-detail-pane" aria-label="공고 상세">
          {!selectedId ? (
            <EmptyState title="검토할 공고를 선택하십시오." description="왼쪽 목록에서 공고를 선택하면 판정 근거와 리뷰 입력이 표시됩니다." />
          ) : detailQuery.isLoading || !detail ? (
            <div className="queue-detail-loading" role="status" aria-live="polite">공고 상세와 판정 근거를 불러오는 중입니다.</div>
          ) : detailQuery.error ? (
            <EmptyState title="공고 상세를 불러오지 못했습니다." description={errorMessage(detailQuery.error, "상세 정보를 확인할 수 없습니다.")} action={{ label: "다시 시도", onClick: () => void detailQuery.refetch() }} />
          ) : (
            <>
              <StickyDecisionHeader className="queue-detail-header" label="공고 상세 결정 헤더">
                <div className="queue-detail-back">
                  <Link to={{ pathname: "/queue", search: searchParams.toString() }}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M19 12H6M11 6l-6 6 6 6" /></svg>
                    목록으로
                  </Link>
                  {selectedIndex >= 0 ? (
                    <span className="mono tabular-nums">{selectedIndex + 1} / {notices.length}</span>
                  ) : null}
                </div>
                <div className="queue-detail-heading">
                  <div className="queue-detail-badges">
                    <Badge label={detail.judgment?.grade} variant={gradeVariant(detail.judgment?.grade ?? null)} />
                    <Badge label={detail.judgment?.readiness} variant="readiness" />
                    <Badge label={detail.judgment?.primary_focus} variant="focus" />
                    {detailDeadline ? (
                      <span className={`queue-detail-deadline is-${detailDeadline.urgency} mono tabular-nums`}>{detailDeadline.label}</span>
                    ) : null}
                    <span className="mono tabular-nums notice-key">{present(detail.notice_key, "식별자 미확인")}</span>
                  </div>
                  <h2>{present(detail.title, "공고명 미확인")}</h2>
                  <div className="queue-detail-subline">
                    <span>{present(detail.agency, "발주기관 미확인")}</span>
                    <span aria-hidden="true">·</span>
                    <span className="mono tabular-nums">{formatPrice(detail.estimated_price)}</span>
                  </div>
                </div>
                <div className="queue-detail-actions">
                  <Link className="notice-source-link" to={{ pathname: `/judgments/${detail.id}`, search: searchParams.toString() }}>
                    판정 상세
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6" /></svg>
                  </Link>
                  {detail.url ? (
                    <a className="notice-source-link" href={detail.url} target="_blank" rel="noreferrer">
                      나라장터 원문
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M14 5h5v5M19 5l-8 8" /><path d="M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>
                    </a>
                  ) : null}
                </div>
              </StickyDecisionHeader>
              <div className="queue-detail-scroll">
                <section className="review-workspace-section queue-information-section" aria-labelledby="queue-information-heading">
                  <div className="review-section-heading">
                    <div>
                      <span className="review-section-eyebrow">공고 원문과 메타데이터</span>
                      <h3 id="queue-information-heading">공고 정보</h3>
                    </div>
                    <span>등급·준비 상태와 별도 확인</span>
                  </div>
                  <div className="notice-facts-grid">
                    <NoticeFacts notice={detail} />
                    <AttachmentPanel noticePk={detail.id} attachments={detail.attachments} />
                  </div>
                </section>
                <section className="review-workspace-section queue-basis-section" aria-labelledby="queue-basis-heading">
                  <div className="review-section-heading">
                    <div>
                      <span className="review-section-eyebrow">시스템 판정</span>
                      <h3 id="queue-basis-heading">판정 근거</h3>
                    </div>
                    <span>요약·관점·확인 항목</span>
                  </div>
                  <JudgmentBanner judgment={detail.judgment} />
                  <PerspectiveTable perspectives={detail.judgment?.perspectives ?? []} />
                  <div className="notice-review-grid">
                    <CounterargumentList items={detail.judgment?.counterarguments ?? []} />
                    {/* 답변은 저장된 리뷰의 것을 그대로 읽는다. 입력 자리는 없다. */}
                    <VerificationItemTable
                      items={detail.judgment?.verification_items ?? []}
                      answers={savedAnswers}
                    />
                  </div>
                </section>
                <section className="review-workspace-section queue-support-section" aria-labelledby="queue-support-heading">
                  <div className="review-section-heading">
                    <div>
                      <span className="review-section-eyebrow">탐색 보조 정보</span>
                      <h3 id="queue-support-heading">추가 확인</h3>
                    </div>
                    <span>후보 편입 신호</span>
                  </div>
                  <RetrievalSignals matches={detail.focus_matches} />
                </section>
                {/* 결정 액션이 아니라 이력이므로 pane 바닥에 고정하지 않고 본문 안에 둔다. */}
                <ReviewRecord review={savedReview} correctionSearch={`q=${encodeURIComponent(detail.title ?? "")}`} />
              </div>
            </>
          )}
        </section>
      </SplitWorkspace>
    </div>
  );
}
