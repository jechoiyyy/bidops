import { useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { AttachmentPanel } from "../components/notice/AttachmentPanel";
import { CounterargumentList } from "../components/notice/CounterargumentList";
import { JudgmentHistory } from "../components/notice/JudgmentHistory";
import { JudgmentBanner } from "../components/notice/JudgmentBanner";
import { LifecycleTimeline } from "../components/notice/LifecycleTimeline";
import { NoticeFacts } from "../components/notice/NoticeFacts";
import { PerformanceMatches } from "../components/notice/PerformanceMatches";
import { PerspectiveTable } from "../components/notice/PerspectiveTable";
import { QualificationFlags } from "../components/notice/QualificationFlags";
import { RelatedNotices } from "../components/notice/RelatedNotices";
import { RetrievalSignals } from "../components/notice/RetrievalSignals";
import { VerificationItemTable } from "../components/notice/VerificationItemTable";
import { api, ApiError } from "../lib/api";
import { formatDate, formatDateTime, formatPrice, present } from "../lib/format";
import { describeDeadline } from "../lib/deadline";
import type { NoticeListItem } from "../lib/types";
import { gradeVariant } from "../lib/grade";
import "../styles/review-workspace-relaxed.css";

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function NoticePickerItem({ notice, selected, onSelect }: { notice: NoticeListItem; selected: boolean; onSelect: () => void }) {
  const itemRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (selected) itemRef.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  return (
    <button aria-current={selected ? "true" : undefined} className={`judgment-notice-item ${selected ? "is-selected" : ""}`.trim()} ref={itemRef} type="button" onClick={onSelect}>
      <span className="judgment-notice-title">{present(notice.title, "공고명 미확인")}</span>
      <span className="judgment-notice-badges">
        <Badge label={notice.grade} variant={gradeVariant(notice.grade)} />
        <Badge label={notice.readiness} variant="readiness" />
      </span>
      <span className="judgment-notice-meta">
        <span>{present(notice.agency, "발주기관 미확인")}</span>
        <span aria-hidden="true">·</span>
        <span className="mono tabular-nums">{formatPrice(notice.estimated_price)}</span>
      </span>
    </button>
  );
}

export function NoticeDetailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { noticePk: noticePkParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const selectedId = noticePkParam && Number.isInteger(Number(noticePkParam)) ? Number(noticePkParam) : null;
  const keepListOpen = Boolean((location.state as { keepListOpen?: boolean } | null)?.keepListOpen);
  const detailQuery = useQuery({
    queryKey: ["notice", selectedId],
    queryFn: () => api.getNotice(selectedId as number),
    enabled: selectedId !== null,
    staleTime: 30_000,
  });
  /**
   * 회차는 주소의 `run`이 먼저다. 주소에 회차가 없이 공고를 연 링크(사업기회 레코드·추적 흐름)는
   * **그 공고 상세가 알려 준 회차**를 쓴다 — 기본 회차의 목록에 그 공고가 없다는 이유로 다른 공고로
   * 바꾸지 않는다(설계고도화안 C-5). 공고를 고르지 않았을 때만 최신 회차를 기본으로 둔다.
   */
  const detailRunId = detailQuery.data?.id === selectedId ? detailQuery.data?.run_id ?? null : null;
  const runId = searchParams.get("run")
    ?? (selectedId !== null ? detailRunId : runsQuery.data?.items[0]?.run_id ?? null);

  useEffect(() => {
    if (searchParams.get("run") || !runId) return;
    const next = new URLSearchParams(searchParams);
    next.set("run", runId);
    setSearchParams(next, { replace: true });
  }, [runId, searchParams, setSearchParams]);

  const noticesQuery = useQuery({
    queryKey: ["judgment-notices", runId],
    queryFn: () => api.getNotices({ run_id: runId as string, grade: "all", sample_role: "all", sort: "published", limit: 500, offset: 0 }),
    enabled: Boolean(runId),
    staleTime: 30_000,
  });

  const notices = noticesQuery.data?.items ?? [];
  const selectedNotice = useMemo(() => notices.find((notice) => notice.id === selectedId), [notices, selectedId]);
  const detail = detailQuery.data?.id === selectedId ? detailQuery.data : undefined;
  const selectedIndex = notices.findIndex((notice) => notice.id === selectedId);
  const detailDeadline = detail ? describeDeadline(detail.deadline_at) : null;

  // 공고를 고르지 않고 들어왔을 때만 목록의 첫 공고를 고른다. 고른 공고가 이 회차 목록(최대 500건)에
  // 없더라도 **다른 공고로 바꾸지 않는다** — 상세는 공고 번호로 따로 읽는다(설계고도화안 C-5).
  useEffect(() => {
    if (!runId || noticesQuery.isLoading || notices.length === 0) return;
    if (selectedId === null && !keepListOpen) {
      navigate({ pathname: `/judgments/${notices[0].id}`, search: searchParams.toString() }, { replace: true, state: null });
    }
  }, [keepListOpen, navigate, notices, noticesQuery.isLoading, runId, searchParams, selectedId]);

  const selectNotice = (id: number) => navigate({ pathname: `/judgments/${id}`, search: searchParams.toString() }, { state: null });

  if (runsQuery.error) {
    return <EmptyState title="회차 정보를 불러오지 못했어요" description={errorMessage(runsQuery.error, "회차를 확인할 수 없어요.")} />;
  }
  if (selectedId !== null && !runId) {
    // 회차 없이 연 공고 상세: 상세가 회차를 알려 줄 때까지 기다리고, 공고가 없으면 다른 공고로
    // 바꾸지 않고 찾을 수 없다고 말한다(설계고도화안 C-5).
    if (detailQuery.isPending) return <p className="rec-status" role="status">공고 상세를 불러오는 중이에요.</p>;
    if (detailQuery.isError && detailQuery.error instanceof ApiError && detailQuery.error.status === 404) {
      return <EmptyState title={`공고 ${selectedId}을(를) 찾을 수 없어요.`} description="없는 공고 번호이거나 지워진 공고예요. 다른 공고로 대신 보여 주지 않아요." />;
    }
    if (detailQuery.isError) {
      return <EmptyState title="공고 상세를 불러오지 못했어요" description={errorMessage(detailQuery.error, "상세 정보를 확인할 수 없어요.")} action={{ label: "다시 시도", onClick: () => void detailQuery.refetch() }} />;
    }
  }
  if (!runId) {
    return <EmptyState title="선택된 회차가 없어요" description="상단의 실행 회차 선택기에서 회차를 선택해 주세요." />;
  }
  if (noticesQuery.error) {
    return <EmptyState title="회차 공고 목록을 불러오지 못했어요" description={errorMessage(noticesQuery.error, "공고 목록을 확인할 수 없어요.")} action={{ label: "다시 시도", onClick: () => void noticesQuery.refetch() }} />;
  }

  return (
    <div className="judgment-page">
      <header className="judgment-page-header">
        <div>
          <div className="judgment-breadcrumb">
            <span>입찰공고 상세</span>
            <span aria-hidden="true">›</span>
            <span className="mono tabular-nums">{detail ? present(detail.notice_key, "식별자 미확인") : "공고 선택"}</span>
          </div>
          <h2>{detail ? present(detail.title, "공고명 미확인") : "입찰공고 상세"}</h2>
          {detail ? (
            <>
              <div className="judgment-page-heading-meta">
                <Badge label={detail.judgment?.grade} variant={gradeVariant(detail.judgment?.grade ?? null)} />
                <Badge label={detail.judgment?.readiness} variant="readiness" />
                {detailDeadline ? <span className={`queue-detail-deadline is-${detailDeadline.urgency} mono tabular-nums`}>{detailDeadline.label}</span> : null}
              </div>
              <div className="judgment-page-subline">
                <span className="mono tabular-nums">{present(detail.notice_key, "식별자 미확인")}</span>
                <span aria-hidden="true">·</span>
                <span>{present(detail.agency, "발주기관 미확인")}</span>
                <span aria-hidden="true">·</span>
                <span className="mono tabular-nums">{formatPrice(detail.estimated_price)}</span>
              </div>
            </>
          ) : null}
        </div>
        <div className="judgment-page-actions">
          {detail?.url ? (
            <a className="notice-source-link" href={detail.url} target="_blank" rel="noreferrer">
              나라장터 원문
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M14 5h5v5M19 5l-8 8" /><path d="M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>
            </a>
          ) : null}
        </div>
      </header>
      <div className={`judgment-workspace ${selectedId !== null ? "shows-detail" : "shows-list"}`}>
        <aside className="judgment-notice-list" aria-label="회차 공고 목록">
          <div className="judgment-list-header">
            <span><strong className="mono tabular-nums">{noticesQuery.data?.total ?? notices.length}</strong>건 · 회차 공고</span>
            <span>{selectedNotice ? "선택됨" : "선택 필요"}</span>
          </div>
          <div className="judgment-list-scroll">
            {noticesQuery.isLoading ? <div className="inline-loading" role="status" aria-live="polite">공고 목록을 불러오는 중이에요.</div> : null}
            {!noticesQuery.isLoading && notices.length === 0 ? <EmptyState compact title="회차 공고가 없어요" /> : null}
            {notices.map((notice) => (
              <NoticePickerItem key={notice.id} notice={notice} selected={notice.id === selectedId} onSelect={() => selectNotice(notice.id)} />
            ))}
          </div>
        </aside>
        <section className="judgment-detail-pane" aria-label="입찰공고 상세">
          {!selectedId ? (
            <EmptyState title="공고를 선택해 주세요" description="왼쪽 회차 목록에서 공고를 선택하면 생애주기와 판정 이력이 표시돼요." />
          ) : detailQuery.isLoading ? (
            <div className="queue-detail-loading" role="status" aria-live="polite">공고 상세와 판정 이력을 불러오는 중이에요.</div>
          ) : detailQuery.error ? (
            <EmptyState title="공고 상세를 불러오지 못했어요" description={errorMessage(detailQuery.error, "상세 정보를 확인할 수 없어요.")} action={{ label: "다시 시도", onClick: () => void detailQuery.refetch() }} />
          ) : !detail ? (
            <EmptyState title="공고 상세가 없어요" description="선택한 공고의 상세 데이터를 확인할 수 없어요." />
          ) : (
            <div className="judgment-detail-scroll">
              <div className="judgment-detail-badges">
                <Badge label={detail.judgment?.grade} variant={gradeVariant(detail.judgment?.grade ?? null)} />
                <Badge label={detail.judgment?.readiness} variant="readiness" />
                <Badge label={detail.judgment?.primary_focus} variant="focus" />
                {detailDeadline ? <span className={`queue-detail-deadline is-${detailDeadline.urgency} mono tabular-nums`}>{detailDeadline.label}</span> : null}
                <span className="mono tabular-nums judgment-published">{detail.published_at ? `공고 ${formatDate(detail.published_at)}` : "공고일 미확인"}</span>
              </div>
              <section className="review-workspace-section judgment-overview-section" aria-labelledby="judgment-overview-heading">
                <div className="review-section-heading">
                  <div>
                    <span className="review-section-eyebrow">이력 확인</span>
                    <h3 id="judgment-overview-heading">공고 생애주기와 판정 요약</h3>
                  </div>
                  <span>현재 공고의 기준선</span>
                </div>
                <LifecycleTimeline notice={detail} />
                <JudgmentBanner judgment={detail.judgment} />
              </section>
              <section className="review-workspace-section judgment-information-section" aria-labelledby="judgment-information-heading">
                <div className="review-section-heading">
                  <div>
                    <span className="review-section-eyebrow">원문 메타데이터</span>
                    <h3 id="judgment-information-heading">공고 정보와 자격</h3>
                  </div>
                  <span>API 직접 제공값</span>
                </div>
                <div className="judgment-summary-grid">
                  <NoticeFacts notice={detail} />
                  <QualificationFlags notice={detail} />
                </div>
              </section>
              <section className="review-workspace-section judgment-history-section" aria-labelledby="judgment-history-heading">
                <div className="review-section-heading">
                  <div>
                    <span className="review-section-eyebrow">회차별 기록</span>
                    <h3 id="judgment-history-heading">판정 이력과 관련 공고</h3>
                  </div>
                  <span>첫 이력 자동 펼침</span>
                </div>
                <div className="judgment-history-grid">
                  <JudgmentHistory noticePk={detail.id} />
                  <RelatedNotices noticePk={detail.id} />
                </div>
              </section>
              <section className="review-workspace-section judgment-basis-section" aria-labelledby="judgment-basis-heading">
                <div className="review-section-heading">
                  <div>
                    <span className="review-section-eyebrow">검토 자료</span>
                    <h3 id="judgment-basis-heading">첨부 문서와 판정 근거</h3>
                  </div>
                  <span>원문·관점·확인 항목</span>
                </div>
                <AttachmentPanel noticePk={detail.id} attachments={detail.attachments} />
                <PerspectiveTable perspectives={detail.judgment?.perspectives ?? []} />
                <div className="notice-review-grid">
                  <CounterargumentList items={detail.judgment?.counterarguments ?? []} />
                  <VerificationItemTable items={detail.judgment?.verification_items ?? []} answers={[]} />
                </div>
              </section>
              <section className="review-workspace-section judgment-support-section" aria-labelledby="judgment-support-heading">
                <div className="review-section-heading">
                  <div>
                    <span className="review-section-eyebrow">탐색 보조 정보</span>
                    <h3 id="judgment-support-heading">추가 검색 신호</h3>
                  </div>
                  <span>후보 편입 근거</span>
                </div>
                <RetrievalSignals matches={detail.focus_matches} />
                {/* 회사 실적과 대조된 것 — 수집 탐색 신호와 판정 검토 결과는
                    구조가 다르므로 표를 나눈다(spec §6.3). */}
                <PerformanceMatches
                  matchedPerformances={detail.judgment?.matched_performances ?? []}
                  performanceMatches={detail.performance_matches}
                  performanceTopScore={detail.performance_top_score}
                />
              </section>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
