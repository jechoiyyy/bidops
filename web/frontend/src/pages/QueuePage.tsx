import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { Toast } from "../components/common/Toast";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { AttachmentPanel } from "../components/notice/AttachmentPanel";
import { CounterargumentList } from "../components/notice/CounterargumentList";
import { JudgmentBanner } from "../components/notice/JudgmentBanner";
import { NoticeFacts } from "../components/notice/NoticeFacts";
import { PerspectiveTable } from "../components/notice/PerspectiveTable";
import { RetrievalSignals } from "../components/notice/RetrievalSignals";
import { ReviewBar, type ReviewDraft } from "../components/notice/ReviewBar";
import { VerificationItemTable } from "../components/notice/VerificationItemTable";
import { QueueFilters, type QueueFilterValues } from "../components/queue/QueueFilters";
import { QueueList } from "../components/queue/QueueList";
import { api } from "../lib/api";
import { formatPrice, present } from "../lib/format";
import { describeDeadline } from "../lib/deadline";
import type { NoticeDetailResponse, ReviewAnswerInput, ReviewResponse, ReviewUpsertRequest } from "../lib/types";
import { gradeVariant } from "../lib/grade";
import "../styles/review-workspace-relaxed.css";

const emptyDraft: ReviewDraft = {
  disposition: "",
  system_judgment_review: "",
  corrected_grade: "",
  corrected_readiness: "",
  weakest_perspective: "",
  reason: "",
  verification_answers: [],
};

function draftFromNotice(notice: NoticeDetailResponse | undefined, runId: string): ReviewDraft {
  const review = notice?.reviews.find((item) => item.run_id === runId);
  if (!review) return { ...emptyDraft, verification_answers: [] };
  return {
    disposition: review.disposition ?? "",
    system_judgment_review: review.system_judgment_review ?? "",
    corrected_grade: review.corrected_grade ?? "",
    corrected_readiness: review.corrected_readiness ?? "",
    weakest_perspective: review.weakest_perspective ?? "",
    reason: review.reason ?? "",
    verification_answers: review.answers.map((answer) => ({ item: answer.item, answer: answer.answer })),
  };
}

// 확인 항목 답변은 순서가 보장되지 않으므로 항목 이름을 기준으로 맞춰 본다.
function answersEqual(left: ReviewAnswerInput[], right: ReviewAnswerInput[]): boolean {
  if (left.length !== right.length) return false;
  const rightByItem = new Map(right.map((entry) => [entry.item, entry.answer] as const));
  return left.every((entry) => rightByItem.has(entry.item) && rightByItem.get(entry.item) === entry.answer);
}

function draftsEqual(left: ReviewDraft, right: ReviewDraft): boolean {
  return left.disposition === right.disposition
    && left.system_judgment_review === right.system_judgment_review
    && left.corrected_grade === right.corrected_grade
    && left.corrected_readiness === right.corrected_readiness
    && left.weakest_perspective === right.weakest_perspective
    && left.reason === right.reason
    && answersEqual(left.verification_answers, right.verification_answers);
}

// 회차와 공고마다 초안을 따로 보관한다. 회차를 바꿨다가 돌아와도 입력값이 남아 있어야 한다.
function draftStorageKey(runId: string, noticePk: number): string {
  return `bidops.queue-draft:${runId}:${noticePk}`;
}

function readStoredDraft(runId: string, noticePk: number): ReviewDraft | null {
  try {
    const raw = window.localStorage.getItem(draftStorageKey(runId, noticePk));
    return raw ? (JSON.parse(raw) as ReviewDraft) : null;
  } catch {
    return null;
  }
}

function writeStoredDraft(runId: string, noticePk: number, draft: ReviewDraft): void {
  try {
    window.localStorage.setItem(draftStorageKey(runId, noticePk), JSON.stringify(draft));
  } catch {
    // 저장 공간이 없거나 접근이 막힌 환경에서는 임시 저장만 포기한다.
  }
}

function clearStoredDraft(runId: string, noticePk: number): void {
  try {
    window.localStorage.removeItem(draftStorageKey(runId, noticePk));
  } catch {
    // 위와 같다.
  }
}

function filterFromParams(params: URLSearchParams): QueueFilterValues {
  const attachment = params.get("attachment");
  const sort = params.get("sort");
  return {
    grade: params.get("grade") ?? "",
    readiness: params.get("readiness") ?? "",
    focus: params.get("focus") ?? "",
    sampleRole: params.get("sample_role") ?? "analysis",
    attachment: attachment === "none" || attachment === "manual" ? attachment : "any",
    q: params.get("q") ?? "",
    // 담당자는 등급이 높은 공고부터 처리하므로 등급순이 기본이다.
    sort: sort === "deadline" || sort === "published" ? sort : "grade",
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

// 900px 이하에서는 목록과 상세를 한 화면에 같이 두지 않는다.
// 이 값은 theme.css의 태블릿 전환점과 짝을 이루므로 함께 바꿔야 한다.
const SPLIT_QUERY = "(max-width: 900px)";

function useSplitLayout(): boolean {
  const [split, setSplit] = useState(() => window.matchMedia(SPLIT_QUERY).matches);
  useEffect(() => {
    const query = window.matchMedia(SPLIT_QUERY);
    const onChange = (event: MediaQueryListEvent) => setSplit(event.matches);
    query.addEventListener("change", onChange);
    setSplit(query.matches);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return split;
}

export function QueuePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { noticePk: noticePkParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const runId = searchParams.get("run");
  const filters = useMemo(() => filterFromParams(searchParams), [searchParams]);
  const noticePk = noticePkParam ? Number(noticePkParam) : null;
  const selectedId = noticePk !== null && Number.isInteger(noticePk) ? noticePk : null;
  const [draft, setDraft] = useState<ReviewDraft>(emptyDraft);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; actionLabel?: string; onAction?: () => void } | null>(null);
  // draft가 어느 공고의 것인지 함께 들고 있어야 한다. 공고를 바꾸는 렌더에서는 draft가
  // 아직 이전 공고의 값이므로, 이 키가 맞을 때만 비교하고 임시 저장한다.
  const [draftOwner, setDraftOwner] = useState<string | null>(null);
  const splitLayout = useSplitLayout();

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
  const serverDraft = useMemo(() => draftFromNotice(detail, runId ?? ""), [detail, runId]);
  const draftKey = detail && runId ? draftStorageKey(runId, detail.id) : null;
  const draftMatchesDetail = draftOwner === draftKey;
  const isDirty = Boolean(detail) && draftMatchesDetail && !draftsEqual(draft, serverDraft);
  const detailDeadline = detail ? describeDeadline(detail.deadline_at) : null;
  const selectedIndex = notices.findIndex((notice) => notice.id === selectedId);
  useUnsavedGuard(isDirty);

  useEffect(() => {
    if (!runId || noticesQuery.isLoading) return;
    if (notices.length === 0) {
      if (selectedId !== null) navigate({ pathname: "/queue", search: searchParams.toString() }, { replace: true });
      return;
    }
    if ((selectedId !== null && selectedIndex === -1) || (selectedId === null && !splitLayout)) {
      navigate({ pathname: `/queue/${notices[0].id}`, search: searchParams.toString() }, { replace: true });
    }
  }, [navigate, notices, noticesQuery.isLoading, runId, searchParams, selectedId, selectedIndex, splitLayout]);

  useEffect(() => {
    if (!detail || !runId) {
      setDraft({ ...emptyDraft, verification_answers: [] });
      setDraftOwner(null);
      setSaveError(null);
      return;
    }
    const stored = readStoredDraft(runId, detail.id);
    setDraft(stored ?? draftFromNotice(detail, runId));
    setDraftOwner(draftStorageKey(runId, detail.id));
    setSaveError(null);
  }, [detail, runId]);

  useEffect(() => {
    if (!detail || !runId || !draftMatchesDetail) return;
    if (draftsEqual(draft, serverDraft)) {
      clearStoredDraft(runId, detail.id);
      return;
    }
    writeStoredDraft(runId, detail.id, draft);
  }, [draft, draftMatchesDetail, detail, runId, serverDraft]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 6000);
    return () => window.clearTimeout(timer);
  }, [toast]);

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

  const updateDraft = <K extends keyof ReviewDraft>(key: K, value: ReviewDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const discardDraft = () => {
    if (!detail || !runId) return;
    clearStoredDraft(runId, detail.id);
    setDraft(draftFromNotice(detail, runId));
    setSaveError(null);
  };

  const updateAnswer = (item: string, answer: string) => {
    setDraft((current) => {
      const index = current.verification_answers.findIndex((entry) => entry.item === item);
      if (index === -1) {
        return { ...current, verification_answers: [...current.verification_answers, { item, answer }] };
      }
      const next = [...current.verification_answers];
      next[index] = { ...next[index], answer };
      return { ...current, verification_answers: next };
    });
  };

  const saveReview = async () => {
    if (!selectedId || !runId || !detail) return;
    setSaving(true);
    setSaveError(null);
    const payload: ReviewUpsertRequest = {
      run_id: runId,
      disposition: draft.disposition || null,
      system_judgment_review: draft.system_judgment_review || null,
      corrected_grade: draft.corrected_grade || null,
      corrected_readiness: draft.corrected_readiness || null,
      weakest_perspective: draft.weakest_perspective || null,
      reason: draft.reason || null,
      verification_answers: draft.verification_answers,
    };
    try {
      const saved = await api.saveReview(selectedId, payload);
      clearStoredDraft(runId, selectedId);
      queryClient.setQueryData<ReviewResponse[]>(["reviews", runId], (current = []) => {
        const next = current.filter((review) => review.notice_pk !== saved.notice_pk);
        return [...next, saved].sort((left, right) => left.notice_pk - right.notice_pk);
      });
      queryClient.setQueryData<NoticeDetailResponse>(["notice", selectedId], (current) => current ? {
        ...current,
        reviews: [...current.reviews.filter((review) => review.run_id !== saved.run_id), saved],
      } : current);
      const currentIndex = notices.findIndex((notice) => notice.id === selectedId);
      const nextNotice = currentIndex >= 0 ? notices[currentIndex + 1] : undefined;
      if (nextNotice) {
        const savedId = selectedId;
        setToast({
          message: "저장됨 · 다음 공고로 이동했습니다",
          actionLabel: "되돌리기",
          onAction: () => navigate({ pathname: `/queue/${savedId}`, search: searchParams.toString() }),
        });
        navigate({ pathname: `/queue/${nextNotice.id}`, search: searchParams.toString() });
      } else {
        setToast({ message: "저장됨 · 마지막 공고입니다" });
        setDraft(draftFromNotice(detail, runId));
      }
    } catch (error) {
      setSaveError(errorMessage(error, "리뷰 저장에 실패했습니다."));
    } finally {
      setSaving(false);
    }
  };

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
      <div className={`queue-workspace ${selectedId !== null ? "shows-detail" : "shows-list"}`}>
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
              <header className="queue-detail-header">
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
              </header>
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
                    <VerificationItemTable
                      items={detail.judgment?.verification_items ?? []}
                      answers={draft.verification_answers}
                      onAnswerChange={updateAnswer}
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
              </div>
              <ReviewBar
                draft={draft}
                perspectives={detail.judgment?.perspectives ?? []}
                saving={saving}
                dirty={isDirty}
                error={saveError}
                onChange={updateDraft}
                onDiscard={discardDraft}
                onSave={() => void saveReview()}
              />
            </>
          )}
        </section>
      </div>
      {toast ? (
        <Toast
          message={toast.message}
          actionLabel={toast.actionLabel}
          onAction={toast.onAction ? () => { toast.onAction?.(); setToast(null); } : undefined}
          onDismiss={() => setToast(null)}
        />
      ) : null}
    </div>
  );
}
