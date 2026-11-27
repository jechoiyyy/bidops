import { useCallback, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { NoticeRecord } from "../components/notice/NoticeRecord";
import { NoticeRunTable } from "../components/notice/NoticeRunTable";
import { QueueFilters, type QueueFilterValues } from "../components/queue/QueueFilters";
import { api } from "../lib/api";
import { gradeRank } from "../lib/grade";

const sortLabels: Record<QueueFilterValues["sort"], string> = {
  grade: "등급순",
  deadline: "마감 임박순",
  published: "공고일순",
};

/**
 * 공고 1차 판정은 읽기 전용 이력이다 (ADR-0046 결정 3, PLAN 단계 E 작업 4).
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
 *   리다이렉트가 아니라 이 화면의 저장된 뷰이므로(docs/design/PLAN.md (git 이력) 2단계)
 *   그 경로로 들어오면 마감순을 기본으로 삼는다. 리다이렉트로 sort 파라미터를
 *   실어 보내던 방식은 AppShell의 회차 동기화와 경쟁해 파라미터를 잃었다.
 */
export function QueuePage({ defaultSort = "grade" }: { defaultSort?: QueueFilterValues["sort"] } = {}) {
  const navigate = useNavigate();
  const { noticePk: noticePkParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => filterFromParams(searchParams, defaultSort), [searchParams, defaultSort]);
  const noticePk = noticePkParam ? Number(noticePkParam) : null;
  const selectedId = noticePk !== null && Number.isInteger(noticePk) ? noticePk : null;
  const detailQuery = useQuery({
    queryKey: ["notice", selectedId],
    queryFn: () => api.getNotice(selectedId as number),
    enabled: selectedId !== null,
    staleTime: 10_000,
  });
  const detail = detailQuery.data?.id === selectedId ? detailQuery.data : undefined;
  // 회차 없이 연 상세는 공고 응답의 회차를 쓴다(C-5). 명시된 회차가 있으면 그 값을 우선한다.
  const runInUrl = searchParams.get("run");
  const runId = runInUrl ?? detail?.run_id ?? null;

  useEffect(() => {
    if (runInUrl !== null || !runId) return;
    const next = new URLSearchParams(searchParams);
    next.set("run", runId);
    setSearchParams(next, { replace: true });
  }, [runId, runInUrl, searchParams, setSearchParams]);

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
  const notices = noticesQuery.data?.items ?? [];
  const reviewsById = useMemo(
    () => new Map((reviewsQuery.data ?? []).map((review) => [review.notice_pk, review] as const)),
    [reviewsQuery.data],
  );
  const focusOptions = useMemo(
    () => Array.from(new Set(notices.map((notice) => notice.focus).filter((focus): focus is string => Boolean(focus)))).sort((a, b) => a.localeCompare(b, "ko")),
    [notices],
  );
  // 저장된 리뷰는 이 회차의 것 하나다. 다른 회차의 리뷰를 이 회차의 값으로 읽지 않는다.
  const savedReview = useMemo(
    () => detail?.reviews.find((review) => review.run_id === runId),
    [detail, runId],
  );
  const orderedNotices = useMemo(
    () => filters.sort === "grade" ? [...notices].sort((a, b) => gradeRank(a.grade) - gradeRank(b.grade)) : notices,
    [filters.sort, notices],
  );
  const selectedIndex = orderedNotices.findIndex((notice) => notice.id === selectedId);

  useEffect(() => {
    if (!runId || !noticesQuery.isSuccess) return;
    // 같은 회차의 공고는 필터나 목록 조회 한도 밖이어도 상세를 유지한다.
    if (selectedId !== null && (detailQuery.isPending || detail?.run_id === runId)) return;
    if (notices.length === 0) {
      if (selectedId !== null) navigate({ pathname: "/queue", search: searchParams.toString() }, { replace: true });
      return;
    }
    // ADR-0047: 지원 폭은 1280~1920px 하나뿐이라 목록만 보여주는 좁은 폭 모드가
    // 없다. 어느 폭에서도 첫 공고를 골라 두 pane을 함께 유지한다.
    if (selectedId === null || selectedIndex === -1) {
      navigate({ pathname: `/queue/${notices[0].id}`, search: searchParams.toString() }, { replace: true });
    }
  }, [detail?.run_id, detailQuery.isPending, navigate, notices, noticesQuery.isSuccess, runId, searchParams, selectedId, selectedIndex]);

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
      if (orderedNotices.length === 0) return;
      const nextIndex = selectedIndex === -1 ? 0 : Math.min(Math.max(selectedIndex + step, 0), orderedNotices.length - 1);
      if (nextIndex === selectedIndex) return;
      selectNotice(orderedNotices[nextIndex].id);
    },
    [orderedNotices, selectNotice, selectedIndex],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || isTypingTarget(event.target)) return;
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

  if (!runId && selectedId !== null) {
    if (detailQuery.isPending) {
      return <div className="queue-detail-loading" role="status">공고 상세와 판정 근거를 불러오는 중이에요.</div>;
    }
    if (detailQuery.isError) {
      return <EmptyState title="공고 상세를 불러오지 못했어요" description={errorMessage(detailQuery.error, "상세 정보를 확인할 수 없어요.")} action={{ label: "다시 시도", onClick: () => void detailQuery.refetch() }} />;
    }
  }
  if (!runId) {
    return <EmptyState title="선택된 회차가 없어요" description="상단의 실행 회차 선택기에서 회차를 선택해 주세요." />;
  }
  if (noticesQuery.error) {
    return <EmptyState title="검토 대기열을 불러오지 못했어요" description={errorMessage(noticesQuery.error, "공고 목록을 확인할 수 없어요.")} action={{ label: "다시 시도", onClick: () => void noticesQuery.refetch() }} />;
  }

  const emptyQueue = selectedId === null && !noticesQuery.isLoading && notices.length === 0;
  return (
    <div className="notice-queue">
      <QueueFilters
        value={filters}
        focusOptions={focusOptions}
        onChange={setFilter}
        onReset={resetFilters}
      />
      <div className="notice-read-workspace" data-empty={emptyQueue || undefined}>
        <NoticeRunTable
          label="검토 대기 공고 목록"
          listNote={sortLabels[filters.sort]}
          notices={orderedNotices}
          onSelect={selectNotice}
          reviews={reviewsById}
          selectedId={selectedId}
          state={noticesQuery.isLoading ? { kind: "loading", label: "공고 목록을 불러오는 중이에요." }
            : notices.length === 0 ? {
              kind: "empty",
              message: { title: "조건에 맞는 공고가 없어요", description: "필터를 넓혀 다른 공고를 확인해 주세요." },
            } : undefined}
          total={noticesQuery.data?.total ?? 0}
        />
        {emptyQueue ? null : (
          <section className="notice-read-detail" aria-label="공고 상세">
            {selectedId === null ? (
              <EmptyState title="검토할 공고를 선택해 주세요" description="왼쪽 목록에서 공고를 선택하면 판정 근거와 저장된 리뷰를 볼 수 있어요." />
            ) : detailQuery.isLoading ? (
              <p role="status">공고 상세와 판정 근거를 불러오는 중이에요.</p>
            ) : detailQuery.error ? (
              <EmptyState title="공고 상세를 불러오지 못했어요" description={errorMessage(detailQuery.error, "상세 정보를 확인할 수 없어요.")} action={{ label: "다시 시도", onClick: () => void detailQuery.refetch() }} />
            ) : !detail ? (
              <EmptyState title="공고 상세가 없어요" description="선택한 공고의 상세 데이터를 확인할 수 없어요." />
            ) : <NoticeRecord notice={detail} queueContext={{ review: savedReview, search: searchParams.toString() }} />}
          </section>
        )}
      </div>
    </div>
  );
}
