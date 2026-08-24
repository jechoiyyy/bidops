import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { AttachmentPanel } from "../components/notice/AttachmentPanel";
import { CounterargumentList } from "../components/notice/CounterargumentList";
import { JudgmentHistory } from "../components/notice/JudgmentHistory";
import { JudgmentSummary } from "../components/notice/JudgmentSummary";
import { LifecycleTimeline } from "../components/notice/LifecycleTimeline";
import { NoticeFacts } from "../components/notice/NoticeFacts";
import { PerspectiveTable } from "../components/notice/PerspectiveTable";
import { QualificationFlags } from "../components/notice/QualificationFlags";
import { RelatedNotices } from "../components/notice/RelatedNotices";
import { RetrievalSignals } from "../components/notice/RetrievalSignals";
import { VerificationItemTable } from "../components/notice/VerificationItemTable";
import { api } from "../lib/api";
import { formatDate, formatDateTime, formatPrice, present } from "../lib/format";
import type { NoticeListItem } from "../lib/types";
import { gradeVariant } from "../lib/grade";

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}


function NoticePickerItem({ notice, selected, onSelect }: { notice: NoticeListItem; selected: boolean; onSelect: () => void }) {
  return (
    <button className={`judgment-notice-item ${selected ? "is-selected" : ""}`.trim()} type="button" onClick={onSelect}>
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
  const navigate = useNavigate();
  const { noticePk: noticePkParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const runId = searchParams.get("run") ?? runsQuery.data?.items[0]?.run_id ?? null;
  const selectedId = noticePkParam && Number.isInteger(Number(noticePkParam)) ? Number(noticePkParam) : null;

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
  const detailQuery = useQuery({
    queryKey: ["notice", selectedId],
    queryFn: () => api.getNotice(selectedId as number),
    enabled: selectedId !== null,
    staleTime: 30_000,
  });

  const notices = noticesQuery.data?.items ?? [];
  const selectedNotice = useMemo(() => notices.find((notice) => notice.id === selectedId), [notices, selectedId]);
  const detail = detailQuery.data?.id === selectedId ? detailQuery.data : undefined;

  const selectNotice = (id: number) => navigate({ pathname: `/judgments/${id}`, search: searchParams.toString() });

  if (runsQuery.error) {
    return <EmptyState title="회차 정보를 불러오지 못했습니다." description={errorMessage(runsQuery.error, "회차를 확인할 수 없습니다.")} />;
  }
  if (!runId) {
    return <EmptyState title="선택된 회차가 없습니다." description="상단의 실행 회차 선택기에서 회차를 선택하십시오." />;
  }
  if (noticesQuery.error) {
    return <EmptyState title="회차 공고 목록을 불러오지 못했습니다." description={errorMessage(noticesQuery.error, "공고 목록을 확인할 수 없습니다.")} />;
  }

  return (
    <div className="judgment-page">
      <header className="judgment-page-header">
        <div>
          <div className="judgment-breadcrumb">
            <span>공고 판정 이력</span>
            <span aria-hidden="true">›</span>
            <span className="mono tabular-nums">{detail ? present(detail.notice_key, "식별자 미확인") : "공고 선택"}</span>
          </div>
          <h2>{detail ? present(detail.title, "공고명 미확인") : "공고 판정 상세"}</h2>
          {detail ? (
            <div className="judgment-page-subline">
              <span className="mono tabular-nums">{present(detail.notice_key, "식별자 미확인")}</span>
              <span aria-hidden="true">·</span>
              <span>{present(detail.agency, "발주기관 미확인")}</span>
              <span aria-hidden="true">·</span>
              <span className="mono tabular-nums">{formatPrice(detail.estimated_price)}</span>
            </div>
          ) : null}
        </div>
        <div className="judgment-page-actions">
          <Link className="notice-source-link" to={`/queue${searchParams.toString() ? `?${searchParams.toString()}` : ""}`}>
            검토 대기열
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6" /></svg>
          </Link>
          {detail?.url ? (
            <a className="notice-source-link" href={detail.url} target="_blank" rel="noreferrer">
              나라장터 원문
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M14 5h5v5M19 5l-8 8" /><path d="M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>
            </a>
          ) : null}
        </div>
      </header>
      <div className="judgment-workspace">
        <aside className="judgment-notice-list" aria-label="회차 공고 목록">
          <div className="judgment-list-header">
            <span><strong className="mono tabular-nums">{noticesQuery.data?.total ?? notices.length}</strong>건 · 회차 공고</span>
            <span>{selectedNotice ? "선택됨" : "선택 필요"}</span>
          </div>
          <div className="judgment-list-scroll">
            {noticesQuery.isLoading ? <div className="inline-loading">공고 목록을 불러오는 중입니다.</div> : null}
            {!noticesQuery.isLoading && notices.length === 0 ? <EmptyState compact title="회차 공고가 없습니다." /> : null}
            {notices.map((notice) => (
              <NoticePickerItem key={notice.id} notice={notice} selected={notice.id === selectedId} onSelect={() => selectNotice(notice.id)} />
            ))}
          </div>
        </aside>
        <section className="judgment-detail-pane" aria-label="공고 판정 상세">
          {!selectedId ? (
            <EmptyState title="공고를 선택하십시오." description="왼쪽 회차 목록에서 공고를 선택하면 생애주기와 판정 이력이 표시됩니다." />
          ) : detailQuery.isLoading ? (
            <div className="queue-detail-loading">공고 상세와 판정 이력을 불러오는 중입니다.</div>
          ) : detailQuery.error ? (
            <EmptyState title="공고 상세를 불러오지 못했습니다." description={errorMessage(detailQuery.error, "상세 정보를 확인할 수 없습니다.")} />
          ) : !detail ? (
            <EmptyState title="공고 상세가 없습니다." description="선택한 공고의 상세 데이터를 확인할 수 없습니다." />
          ) : (
            <div className="judgment-detail-scroll">
              <div className="judgment-detail-badges">
                <Badge label={detail.judgment?.grade} variant={gradeVariant(detail.judgment?.grade ?? null)} />
                <Badge label={detail.judgment?.readiness} variant="readiness" />
                <Badge label={detail.judgment?.primary_focus} variant="focus" />
                <span className="mono tabular-nums judgment-published">{detail.published_at ? `공고 ${formatDate(detail.published_at)}` : "공고일 미확인"}</span>
              </div>
              <LifecycleTimeline notice={detail} />
              <div className="judgment-summary-grid">
                <JudgmentSummary judgment={detail.judgment} />
                <NoticeFacts notice={detail} />
                <QualificationFlags notice={detail} />
              </div>
              <div className="judgment-history-grid">
                <JudgmentHistory noticePk={detail.id} />
                <RelatedNotices noticePk={detail.id} />
              </div>
              <AttachmentPanel noticePk={detail.id} attachments={detail.attachments} />
              <PerspectiveTable perspectives={detail.judgment?.perspectives ?? []} />
              <div className="notice-review-grid">
                <CounterargumentList items={detail.judgment?.counterarguments ?? []} />
                <VerificationItemTable items={detail.judgment?.verification_items ?? []} answers={[]} />
              </div>
              <RetrievalSignals matches={detail.focus_matches} />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
