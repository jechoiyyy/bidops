import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { AttachmentPanel } from "../components/notice/AttachmentPanel";
import { CounterargumentList } from "../components/notice/CounterargumentList";
import { JudgmentSummary } from "../components/notice/JudgmentSummary";
import { NoticeFacts } from "../components/notice/NoticeFacts";
import { PerspectiveTable } from "../components/notice/PerspectiveTable";
import { RetrievalSignals } from "../components/notice/RetrievalSignals";
import { ReviewBar, type ReviewDraft } from "../components/notice/ReviewBar";
import { VerificationItemTable } from "../components/notice/VerificationItemTable";
import { QueueFilters, type QueueFilterValues } from "../components/queue/QueueFilters";
import { QueueList } from "../components/queue/QueueList";
import { api } from "../lib/api";
import { formatDeadline, formatPrice, present } from "../lib/format";
import type { NoticeDetailResponse, ReviewResponse, ReviewUpsertRequest } from "../lib/types";

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
    sort: sort === "grade" || sort === "published" ? sort : "deadline",
  };
}

function gradeVariant(grade: string | null): BadgeVariant {
  if (grade === "우선 검토") return "grade-1";
  if (grade === "검토 권장") return "grade-2";
  if (grade === "관찰 대상") return "grade-3";
  if (grade === "제외") return "grade-4";
  return "neutral";
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function isSoon(value: string | null): boolean {
  if (!value) return false;
  const date = new Date(value);
  const remaining = date.getTime() - Date.now();
  return !Number.isNaN(date.getTime()) && remaining >= 0 && remaining <= 7 * 86_400_000;
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
  const reviewedIds = useMemo(() => new Set((reviewsQuery.data ?? []).map((review) => review.notice_pk)), [reviewsQuery.data]);
  const focusOptions = useMemo(
    () => Array.from(new Set(notices.map((notice) => notice.focus).filter((focus): focus is string => Boolean(focus)))).sort((a, b) => a.localeCompare(b, "ko")),
    [notices],
  );
  const detail = detailQuery.data?.id === selectedId ? detailQuery.data : undefined;

  useEffect(() => {
    if (!runId || noticesQuery.isLoading) return;
    if (notices.length === 0) {
      if (selectedId !== null) navigate({ pathname: "/queue", search: searchParams.toString() }, { replace: true });
      return;
    }
    if (selectedId === null || !notices.some((notice) => notice.id === selectedId)) {
      navigate({ pathname: `/queue/${notices[0].id}`, search: searchParams.toString() }, { replace: true });
    }
  }, [navigate, notices, noticesQuery.isLoading, runId, searchParams, selectedId]);

  useEffect(() => {
    setDraft(detail ? draftFromNotice(detail, runId ?? "") : { ...emptyDraft, verification_answers: [] });
    setSaveError(null);
  }, [detail, runId]);

  const setFilter = <K extends keyof QueueFilterValues>(key: K, value: QueueFilterValues[K]) => {
    const next = new URLSearchParams(searchParams);
    const queryKey: Record<keyof QueueFilterValues, string> = {
      grade: "grade",
      readiness: "readiness",
      focus: "focus",
      sampleRole: "sample_role",
      attachment: "attachment",
      q: "q",
      sort: "sort",
    };
    const serialized = String(value);
    if (!serialized || (key === "sampleRole" && serialized === "analysis") || (key === "attachment" && serialized === "any") || (key === "sort" && serialized === "deadline")) {
      next.delete(queryKey[key]);
    } else {
      next.set(queryKey[key], serialized);
    }
    setSearchParams(next, { replace: true });
  };

  const selectNotice = (id: number) => navigate({ pathname: `/queue/${id}`, search: searchParams.toString() });

  const updateDraft = <K extends keyof ReviewDraft>(key: K, value: ReviewDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
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
        navigate({ pathname: `/queue/${nextNotice.id}`, search: searchParams.toString() });
      } else {
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
    return <EmptyState title="검토 대기열을 불러오지 못했습니다." description={errorMessage(noticesQuery.error, "공고 목록을 확인할 수 없습니다.")} />;
  }

  return (
    <div className="queue-page">
      <QueueFilters
        value={filters}
        focusOptions={focusOptions}
        onChange={setFilter}
        total={noticesQuery.data?.total ?? 0}
        reviewedCount={reviewsQuery.data?.length ?? 0}
      />
      <div className="queue-workspace">
        <QueueList notices={notices} selectedId={selectedId} reviewedIds={reviewedIds} total={noticesQuery.data?.total ?? 0} onSelect={selectNotice} />
        <section className="queue-detail-pane" aria-label="공고 상세">
          {!selectedId ? (
            <EmptyState title="검토할 공고를 선택하십시오." description="왼쪽 목록에서 공고를 선택하면 판정 근거와 리뷰 입력이 표시됩니다." />
          ) : detailQuery.isLoading || !detail ? (
            <div className="queue-detail-loading">공고 상세와 판정 근거를 불러오는 중입니다.</div>
          ) : detailQuery.error ? (
            <EmptyState title="공고 상세를 불러오지 못했습니다." description={errorMessage(detailQuery.error, "상세 정보를 확인할 수 없습니다.")} />
          ) : (
            <>
              <header className="queue-detail-header">
                <div className="queue-detail-heading">
                  <div className="queue-detail-badges">
                    <Badge label={detail.judgment?.grade} variant={gradeVariant(detail.judgment?.grade ?? null)} />
                    <Badge label={detail.judgment?.readiness} variant="readiness" />
                    <Badge label={detail.judgment?.primary_focus} variant="focus" />
                    {detail.deadline_at ? <Badge label={formatDeadline(detail.deadline_at)} variant={isSoon(detail.deadline_at) ? "alert" : "neutral"} /> : null}
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
                <div className="notice-top-grid">
                  <JudgmentSummary judgment={detail.judgment} />
                  <NoticeFacts notice={detail} />
                  <AttachmentPanel noticePk={detail.id} attachments={detail.attachments} />
                </div>
                <PerspectiveTable perspectives={detail.judgment?.perspectives ?? []} />
                <div className="notice-review-grid">
                  <CounterargumentList items={detail.judgment?.counterarguments ?? []} />
                  <VerificationItemTable
                    items={detail.judgment?.verification_items ?? []}
                    answers={draft.verification_answers}
                    onAnswerChange={updateAnswer}
                  />
                </div>
                <RetrievalSignals matches={detail.focus_matches} />
              </div>
              <ReviewBar
                draft={draft}
                perspectives={detail.judgment?.perspectives ?? []}
                saving={saving}
                error={saveError}
                onChange={updateDraft}
                onSave={() => void saveReview()}
              />
            </>
          )}
        </section>
      </div>
    </div>
  );
}
