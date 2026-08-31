import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { DocumentPreparationPanel } from "../components/deep-review/DocumentPreparationPanel";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { api } from "../lib/api";
import { describeDeadline } from "../lib/deadline";
import { formatDateTime, formatNumber, present } from "../lib/format";
import type {
  PreSpecOverviewAttemptStatus,
  PreSpecOverviewCutStatus,
  PreSpecOverviewReviewStatus,
} from "../lib/types";
import "../styles/pre-specs-relaxed.css";

const REVIEW_STATUS: Record<PreSpecOverviewReviewStatus, string> = {
  awaiting_document: "문서 대기",
  awaiting_structure: "구조화 대기",
  preparing: "입력 준비 중",
  awaiting_model: "모델 실행 대기",
  queued: "실행 대기",
  running: "실행 중",
  needs_human_review: "사람 검토 필요",
  completed: "완료",
  failed: "실패",
  cancelled: "취소",
};

const ATTEMPT_STATUS: Record<PreSpecOverviewAttemptStatus, string> = {
  queued: "대기",
  running: "실행 중",
  completed: "완료",
  failed: "실패",
  cancelled: "취소",
};

function statusVariant(status: PreSpecOverviewReviewStatus): BadgeVariant {
  if (status === "completed") return "evidence-confirmed";
  if (status === "failed" || status === "needs_human_review") return "alert";
  return "neutral";
}

function cutStatus(status: PreSpecOverviewCutStatus): { label: string; variant: BadgeVariant; description: string } {
  if (status === "ready") {
    return { label: "입력 범위 준비됨", variant: "evidence-confirmed", description: "서버가 구조화 문서에서 개요 입력 범위를 확정했습니다." };
  }
  if (status === "unknown") {
    return { label: "unknown · 사람 확인 필요", variant: "evidence-unknown", description: "구조 절단 범위를 확정하지 못했습니다. 전체 문서 성공으로 자동 보정하지 않습니다." };
  }
  if (status === "failed") {
    return { label: "입력 준비 실패", variant: "alert", description: "개요 입력 준비가 실패했습니다. 사람 확인과 안전한 재처리가 필요합니다." };
  }
  return { label: "입력 준비 대기", variant: "neutral", description: "개요 입력 범위가 아직 확정되지 않았습니다." };
}

function errorMessage(_error: unknown, fallback: string): string {
  // API error bodies are not a UI transport contract.  Keep server details,
  // raw content, and provider diagnostics out of this metadata-only view.
  return fallback;
}

function hasCanonicalOverviewNoticeId(
  response: unknown,
  noticeId: number,
): response is { notice_id: number; reviews: Array<{ notice_id: number }> } {
  if (typeof response !== "object" || response === null) return false;
  if (!("notice_id" in response) || !("reviews" in response)) return false;
  const candidate = response as { notice_id?: unknown; reviews?: unknown };
  return candidate.notice_id === noticeId
    && Array.isArray(candidate.reviews)
    && candidate.reviews.every((review) => (
      typeof review === "object"
      && review !== null
      && "notice_id" in review
      && review.notice_id === noticeId
    ));
}

export function PreSpecDetailPage() {
  const navigate = useNavigate();
  const { noticeId: noticeIdParam } = useParams();
  const [searchParams] = useSearchParams();
  const parsedNoticeId = Number(noticeIdParam);
  const noticeId = Number.isInteger(parsedNoticeId) && parsedNoticeId > 0 ? parsedNoticeId : null;
  const listSearch = searchParams.toString();
  const listUrl = `/pre-specs${listSearch ? `?${listSearch}` : ""}`;

  const noticeQuery = useQuery({
    queryKey: ["pre-spec-notice", noticeId],
    queryFn: () => api.getNotice(noticeId as number),
    enabled: noticeId !== null,
    staleTime: 30_000,
  });
  const overviewQuery = useQuery({
    queryKey: ["pre-spec-overview-reviews", noticeId],
    queryFn: ({ signal }) => api.getPreSpecOverviewReviews(noticeId as number, { signal }),
    enabled: noticeId !== null,
    staleTime: 30_000,
  });

  if (noticeId === null) {
    return (
      <EmptyState
        tone="error"
        title="사전규격 식별자를 확인할 수 없습니다."
        description="양의 정수 notice ID가 필요합니다."
        action={{ label: "사전규격 목록", to: listUrl }}
      />
    );
  }

  if (noticeQuery.isPending) {
    return <div className="pre-specs-loading" role="status" aria-live="polite">사전규격 {noticeId} 상세를 불러오는 중입니다.</div>;
  }

  if (noticeQuery.isError) {
    return (
      <EmptyState
        tone="error"
        title={`사전규격 ${noticeId} 상세를 불러오지 못했습니다.`}
        description={errorMessage(noticeQuery.error, "선택한 notice의 상세 정보를 확인할 수 없습니다.")}
        action={{ label: "다시 시도", onClick: () => { void noticeQuery.refetch(); } }}
        secondaryAction={{ label: "사전규격 목록", to: listUrl }}
      />
    );
  }

  const notice = noticeQuery.data;
  if (notice.id !== noticeId || notice.source_type !== "pre_spec") {
    return (
      <EmptyState
        tone="error"
        title="사전규격 정본을 확인할 수 없습니다."
        description="요청한 ID와 일치하는 사전규격 레코드가 아닙니다. 다른 공고로 이동하지 않았습니다."
        action={{ label: "사전규격 목록", to: listUrl }}
      />
    );
  }

  const deadline = describeDeadline(notice.deadline_at);
  const overviewResponseInvalid = overviewQuery.isSuccess
    && !hasCanonicalOverviewNoticeId(overviewQuery.data, noticeId);
  const overview = overviewResponseInvalid ? undefined : overviewQuery.data?.reviews[0];
  const snapshot = overview?.current_snapshot;
  const cut = snapshot ? cutStatus(snapshot.cut_status) : null;

  return (
    <section className="pre-spec-detail-page" aria-labelledby="pre-spec-detail-title">
      <nav className="pre-spec-detail-breadcrumb" aria-label="사전규격 상세 경로">
        <Link to={listUrl}>사전규격 목록</Link>
        <span aria-hidden="true">›</span>
        <span className="mono tabular-nums">notice {noticeId}</span>
      </nav>

      <header className="pre-spec-detail-header">
        <div>
          <span className="pre-specs-eyebrow">사전규격 정본 상세 · 누적 조회</span>
          <h2 id="pre-spec-detail-title">{present(notice.title, "사업명 미확인")}</h2>
          <div className="pre-spec-detail-subline">
            <span>{present(notice.agency, "발주기관 미확인")}</span>
            <span aria-hidden="true">·</span>
            <span className="mono tabular-nums">notice {notice.id}</span>
            <span aria-hidden="true">·</span>
            <span className="mono tabular-nums">{present(notice.notice_key, "정본 키 미확인")}</span>
          </div>
        </div>
        <div className="pre-spec-detail-actions">
          <span className={`pre-specs-deadline is-${deadline.urgency} mono tabular-nums`}>{deadline.label}</span>
          {notice.url ? <a href={notice.url} target="_blank" rel="noreferrer">나라장터 원문</a> : null}
        </div>
      </header>

      <div className="pre-spec-detail-grid">
        <Panel title="사전규격 사실">
          <dl className="pre-spec-detail-facts">
            <div><dt>게시 시각</dt><dd>{formatDateTime(notice.published_at)}</dd></div>
            <div><dt>의견등록 마감</dt><dd>{formatDateTime(notice.deadline_at)}</dd></div>
            <div><dt>D-day</dt><dd><span className={`pre-specs-deadline is-${deadline.urgency} mono tabular-nums`}>{deadline.label}</span></dd></div>
            <div><dt>사업 예산</dt><dd>{notice.budget === null ? "예산 미확인" : `${formatNumber(notice.budget)}원`}</dd></div>
            <div><dt>첨부 원문</dt><dd>{notice.attachment_count}건</dd></div>
            <div><dt>데이터 유형</dt><dd>사전규격</dd></div>
          </dl>
        </Panel>

        <Panel title="개요 검토 상태" className="pre-spec-overview-panel">
          {overviewQuery.isPending ? <p role="status">개요 검토 projection을 불러오는 중입니다.</p> : null}
          {overviewQuery.isError ? (
            <EmptyState
              compact
              tone="error"
              title="개요 검토 상태를 불러오지 못했습니다."
              description={errorMessage(overviewQuery.error, "개요 검토 API 응답을 확인할 수 없습니다.")}
              action={{ label: "다시 시도", onClick: () => { void overviewQuery.refetch(); } }}
            />
          ) : null}
          {overviewResponseInvalid ? (
            <EmptyState
              compact
              tone="error"
              title="개요 검토 정본을 확인할 수 없습니다."
              description="응답의 notice ID가 요청과 일치하지 않아 개요 검토를 표시하지 않습니다."
            />
          ) : null}
          {overviewQuery.isSuccess && !overview && !overviewResponseInvalid ? (
            <EmptyState compact title="개요 검토 기록이 없습니다." description="서버가 제공한 개요 검토 기록이 없습니다." />
          ) : null}
          {overview ? (
            <div className="pre-spec-overview-content">
              <div className="pre-spec-overview-statuses">
                <Badge label={REVIEW_STATUS[overview.status]} variant={statusVariant(overview.status)} />
                {overview.result ? <Badge label={overview.result} variant="focus" /> : <Badge label="검토 결과 미확정" variant="neutral" />}
              </div>
              {cut ? (
                <div className={`pre-spec-cut-state is-${snapshot?.cut_status}`}>
                  <Badge label={cut.label} variant={cut.variant} />
                  <p>{cut.description}</p>
                </div>
              ) : (
                <div className="pre-spec-cut-state is-pending">
                  <Badge label="입력 snapshot 없음" variant="neutral" />
                  <p>서버 projection에 현재 입력 snapshot이 없습니다.</p>
                </div>
              )}
              {snapshot ? (
                <dl className="pre-spec-overview-lineage">
                  <div><dt>절단 전략</dt><dd>{snapshot.strategy ?? "전략 미확정"}</dd></div>
                  <div><dt>문서 버전</dt><dd className="mono">{snapshot.document_version_id}</dd></div>
                  <div><dt>구조 버전</dt><dd className="mono">{snapshot.structure_id}</dd></div>
                  <div><dt>입력 생성</dt><dd>{formatDateTime(snapshot.created_at)}</dd></div>
                </dl>
              ) : null}
              <div className="pre-spec-overview-attempts">
                <strong>실행 이력</strong>
                {overview.attempts.length === 0 ? <span>모델 실행 이력 없음</span> : (
                  <ul>
                    {overview.attempts.map((attempt) => (
                      <li key={attempt.id}>
                        <span className="mono tabular-nums">#{attempt.sequence}</span>
                        <Badge
                          label={ATTEMPT_STATUS[attempt.status]}
                          variant={attempt.status === "completed" ? "evidence-confirmed" : attempt.status === "failed" ? "alert" : "neutral"}
                        />
                        <span>{attempt.reference_only ? "참고 전용" : attempt.deployable ? "배포 가능" : "배포 불가"}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <p className="pre-spec-overview-limit">
                이 개요 검토는 서버가 고정한 구조 절단 입력만 다룹니다. 개요 결과는 추적 상태·참여 준비·최종 Go/No-Go를 대신하지 않습니다.
              </p>
            </div>
          ) : null}
        </Panel>
      </div>

      <DocumentPreparationPanel
        noticeId={notice.id}
        displayedGrade={notice.grade}
        onDeepReviewCreated={(review) => navigate(`/deep-reviews/${review.id}`)}
      />
    </section>
  );
}
