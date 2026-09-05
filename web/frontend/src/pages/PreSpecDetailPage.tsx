import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { BUNDLE_STATUS_LABELS, DocumentPreparationPanel } from "../components/deep-review/DocumentPreparationPanel";
import { getDocumentBundles, getDocumentStructurePage } from "../components/deep-review/api";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { ReviewDecisionAction, ReviewHistoryLinkRail, StickyDecisionHeader } from "../components/common/ReviewPrimitives";
import { PreSpecDocumentSummary, TrackingDecisionControl, updateTrackingProjection } from "../components/pre-specs/TrackingDecisionControl";
import { api } from "../lib/api";
import { describeDeadline } from "../lib/deadline";
import { formatDateTime, formatNumber, present } from "../lib/format";
import { gradeLabel, gradeSourceLabel, gradeVariant } from "../lib/grade";
import {
  PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL,
  preSpecAutoPreparationReasonLabel,
  preSpecAutoPreparationVariant,
} from "../lib/preSpecAutoPreparation";
import {
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
  preSpecOverviewStatusVariant,
} from "../lib/preSpecOverviewStatus";
import { qualityStatusLabel, qualityStatusNote, qualityStatusVariant } from "../lib/qualityStatus";
import type {
  PreSpecListItem,
  PreSpecListResponse,
  PreSpecOverviewAttemptStatus,
  PreSpecOverviewCutStatus,
  PreSpecOverviewEvidence,
  PreSpecOverviewReviewStatus,
  PreSpecOverviewValidationStatus,
} from "../lib/types";
import "../styles/pre-specs-relaxed.css";
import "../styles/detail-skeleton.css";

const REVIEW_STATUS = PRE_SPEC_OVERVIEW_STATUS_LABEL;

/** 헤더의 저장 액션이 `form` 속성으로 본문의 추적 결정 폼을 submit한다. */
const TRACKING_FORM_ID = "pre-spec-detail-tracking-form";

interface TrackingDecisionState {
  ready: boolean;
  disabledReason: string | null;
  hasForm: boolean;
  saveLabel: string;
}

const ATTEMPT_STATUS: Record<PreSpecOverviewAttemptStatus, string> = {
  queued: "대기",
  running: "실행 중",
  completed: "완료",
  failed: "실패",
  cancelled: "취소",
};

const VALIDATION_STATUS: Record<PreSpecOverviewValidationStatus, { label: string; variant: BadgeVariant; warning: string | null }> = {
  passed: { label: "검증 통과 · passed", variant: "evidence-confirmed", warning: null },
  failed: { label: "검증 실패 · failed", variant: "alert", warning: "검증에 실패한 결과입니다. 이 내용을 판정으로 읽지 마세요." },
  pending: { label: "검증 대기 · pending", variant: "neutral", warning: "아직 결정적 검증을 통과하지 않은 결과입니다. 이 내용을 판정으로 읽지 마세요." },
};

const REVIEW_WAITING_DESCRIPTION: Record<PreSpecOverviewReviewStatus, string> = {
  awaiting_document: "검토할 문서가 아직 준비되지 않아 개요 입력을 만들지 못했습니다.",
  awaiting_structure: "문서 구조화가 끝나고 개요 입력 범위가 확정되기를 기다리고 있습니다.",
  preparing: "서버가 개요 검토용 입력 snapshot을 준비하고 있습니다.",
  awaiting_model: "승인된 모델 binding이 없어 아직 실행되지 않은 상태입니다. 승인된 사설 모델 binding이 준비되기 전에는 모델을 호출하지 않습니다.",
  queued: "승인된 모델 실행이 큐에서 차례를 기다리고 있습니다.",
  running: "승인된 모델 실행이 진행 중이며 검증된 결과를 기다리고 있습니다.",
  needs_human_review: "입력 범위 또는 실행 결과를 사람이 확인해야 하므로 검증된 권고로 확정할 수 없습니다.",
  completed: "처리 상태는 완료지만 검증된 결과 payload가 없어 권고를 표시할 수 없습니다.",
  failed: "모델 실행 또는 결과 검증이 실패했습니다. 실패 결과를 권고로 보정하지 않습니다.",
  cancelled: "실행이 취소되어 검증된 권고 결과가 없습니다.",
};

const statusVariant = preSpecOverviewStatusVariant;

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

/** 자동 준비 진행 한 줄 단계 표시. 네 칸의 값은 모두 서버가 준 것이며 화면이
 * 다른 값에서 다시 계산하지 않는다:
 *
 * 1. 첨부 취득 — 사전규격 projection의 상태별 건수
 * 2. 묶음 — document bundle 응답의 `status`
 * 3. 개요 — projection의 `overview_review_status`(행이 없으면 미시작)
 * 4. 심층 검토 — projection의 `auto_preparation_status`와 그 사유
 */
interface AutoPreparationStepProps {
  label: string;
  value: string;
  variant: BadgeVariant;
  detail?: ReactNode;
}

function AutoPreparationStep({ label, value, variant, detail }: AutoPreparationStepProps) {
  return (
    <li className="pre-spec-auto-step">
      <span className="pre-spec-auto-step-label">{label}</span>
      <Badge label={value} variant={variant} />
      {detail ? <span className="pre-spec-auto-step-detail">{detail}</span> : null}
    </li>
  );
}

function evidenceKey(evidence: PreSpecOverviewEvidence): string {
  return `${evidence.claim}-${evidence.locator.block_key}-${evidence.locator.page}-${evidence.locator.ordinal}`;
}

export function PreSpecDetailPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
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
  const preSpecProjectionQuery = useQuery({
    queryKey: ["pre-spec-detail", noticeId],
    queryFn: ({ signal }) => api.getPreSpecs({ notice_pk: noticeId }, { signal }),
    enabled: noticeId !== null,
    staleTime: 30_000,
  });
  // DocumentPreparationPanel과 **같은 query key**를 쓴다. 단계 표시가 새 요청을
  // 만들지 않고 이미 있는 bundle 응답을 함께 읽는다.
  const bundleQuery = useQuery({
    queryKey: ["document-bundles", noticeId],
    queryFn: () => getDocumentBundles(noticeId as number),
    enabled: noticeId !== null,
    staleTime: 30_000,
  });
  const overviewQuery = useQuery({
    queryKey: ["pre-spec-overview-reviews-v2", noticeId],
    queryFn: ({ signal }) => api.getPreSpecOverviewReviewsV2(noticeId as number, { signal }),
    enabled: noticeId !== null,
    staleTime: 30_000,
  });
  const overviewResponseInvalid = overviewQuery.isSuccess
    && !hasCanonicalOverviewNoticeId(overviewQuery.data, noticeId ?? 0);
  const overview = overviewResponseInvalid ? undefined : overviewQuery.data?.reviews[0];
  const snapshot = overview?.current_snapshot;
  const [selectedEvidence, setSelectedEvidence] = useState<PreSpecOverviewEvidence | null>(null);
  const sourceStructureId = snapshot?.structure_id;
  const sourcePageNumber = selectedEvidence?.locator.page;
  const sourcePageQuery = useQuery({
    queryKey: ["pre-spec-document-structure-page", sourceStructureId, sourcePageNumber],
    queryFn: () => getDocumentStructurePage(sourceStructureId as string, sourcePageNumber as number),
    enabled: Boolean(sourceStructureId && sourcePageNumber),
    staleTime: 30_000,
  });

  useEffect(() => {
    setSelectedEvidence(null);
  }, [noticeId]);

  // 조기 반환보다 앞에 둔다. 아래 반환들이 hook 순서를 흔들면 화면이 통째로
  // 오류 경계로 떨어진다.
  const [trackingDecision, setTrackingDecision] = useState<TrackingDecisionState>({
    ready: false,
    disabledReason: null,
    hasForm: false,
    saveLabel: "추적 상태 저장",
  });
  const handleTrackingDecisionState = useCallback((next: TrackingDecisionState) => {
    setTrackingDecision((current) => (
      current.ready === next.ready
        && current.disabledReason === next.disabledReason
        && current.hasForm === next.hasForm
        && current.saveLabel === next.saveLabel
        ? current
        : next
    ));
  }, []);
  const trackingPanelRef = useRef<HTMLDivElement>(null);
  const focusTrackingForm = useCallback(() => {
    const panel = trackingPanelRef.current;
    if (!panel) return;
    panel.scrollIntoView({ block: "start" });
    panel.querySelector<HTMLElement>("button, textarea, input")?.focus({ preventScroll: true });
  }, []);

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
  const cut = snapshot ? cutStatus(snapshot.cut_status) : null;
  const sourceBlocks = sourcePageQuery.data?.blocks ?? [];
  const selectedBlockIndex = selectedEvidence
    ? sourceBlocks.findIndex((block) => block.block_key === selectedEvidence.locator.block_key)
    : -1;
  const displayedSourceBlocks = selectedBlockIndex === -1
    ? sourceBlocks
    : sourceBlocks.slice(Math.max(0, selectedBlockIndex - 1), Math.min(sourceBlocks.length, selectedBlockIndex + 2));
  const preSpecItem = preSpecProjectionQuery.data?.items.find((item) => item.notice_pk === noticeId);
  const trackingStatusLabel = preSpecItem?.tracking_status ?? "미선택";
  // 묶음 상태는 최신 revision 하나만 본다. 없으면 "묶음 없음"이며 초안으로
  // 보정하지 않는다.
  const latestBundle = [...(bundleQuery.data?.items ?? [])].sort((left, right) => right.revision - left.revision)[0] ?? null;
  const autoStatus = preSpecItem?.auto_preparation_status ?? null;
  const autoReasonLabel = preSpecAutoPreparationReasonLabel(preSpecItem?.auto_preparation_reason ?? null);
  const autoDeepReviewId = preSpecItem?.latest_deep_review_id ?? null;
  const documentCounts = preSpecItem?.document ?? null;
  const overviewStatusForStep = preSpecItem
    ? (preSpecItem.overview_review_status === null
      ? PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL
      : PRE_SPEC_OVERVIEW_STATUS_LABEL[preSpecItem.overview_review_status])
    : null;

  return (
    <section className="pre-spec-detail-page detail-skeleton" data-astryx-theme="bidops" aria-labelledby="pre-spec-detail-title">
      <nav className="pre-spec-detail-breadcrumb" aria-label="사전규격 상세 경로">
        <Link to={listUrl}>사전규격 목록</Link>
        <span aria-hidden="true">›</span>
        <span className="mono tabular-nums">notice {noticeId}</span>
      </nav>

      {/* 상세 3종 공통 골격(4단계): 요약 헤더는 position:sticky로 스크롤 위치와
          무관하게 첫 화면에 남는다. 결정 액션(심층 검토 추적 선택)은 이 헤더의
          상태 배지 줄 오른쪽 끝(margin-left:auto)에만 있고 레일에는 복제하지
          않는다. */}
      <StickyDecisionHeader className="pre-spec-detail-header detail-skeleton-head" label="사전규격 상세 결정 헤더">
        <div className="detail-skeleton-head-top">
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
        </div>

        {/* 등급과 등급 출처(명세 §6.8). 등급은 서버가 준 값 그대로이며 화면이
            판정하지 않는다. 판정도 사람 정정도 없으면 `판정 없음`이고, 그것은
            다섯 번째 등급이 아니라 아직 판정하지 않았다는 뜻이다. */}
        <div className="pre-spec-detail-grade-row">
          <span className="pre-spec-detail-grade-label">적합성 등급</span>
          {preSpecProjectionQuery.isPending ? (
            <span className="pre-spec-detail-grade-source">등급을 불러오는 중입니다.</span>
          ) : (
            <>
              <Badge label={gradeLabel(preSpecItem?.grade ?? null)} variant={gradeVariant(preSpecItem?.grade ?? null)} />
              <span className="pre-spec-detail-grade-source">
                등급 출처 · {gradeSourceLabel(preSpecItem?.grade_source ?? null)}
              </span>
            </>
          )}
        </div>

        {/* 자동 준비 진행 — 첨부 취득 → 묶음 → 개요 → 심층 검토. */}
        <div className="pre-spec-auto-preparation" aria-label="자동 준비 진행">
          <ol className="pre-spec-auto-steps">
            <AutoPreparationStep
              label="1 · 첨부 취득"
              value={documentCounts ? `${documentCounts.attachments}건` : "집계 없음"}
              variant={documentCounts && (documentCounts["차단"] > 0 || documentCounts["실패"] > 0) ? "alert" : "neutral"}
              detail={documentCounts
                ? `완료 ${documentCounts["완료"]} · 대기 ${documentCounts["대기"]} · 진행 ${documentCounts["진행"]} · 차단 ${documentCounts["차단"]} · 실패 ${documentCounts["실패"]}`
                : "사전규격 projection이 없어 첨부 집계를 표시하지 않습니다."}
            />
            <AutoPreparationStep
              label="2 · 문서 묶음"
              value={bundleQuery.isPending
                ? "확인 중"
                : latestBundle ? BUNDLE_STATUS_LABELS[latestBundle.status] : "묶음 없음"}
              variant={latestBundle?.status === "ready"
                ? "evidence-confirmed"
                : latestBundle?.status === "failed" || latestBundle?.status === "quarantined" || latestBundle?.status === "needs_review"
                  ? "alert"
                  : "neutral"}
              detail={latestBundle ? `revision ${latestBundle.revision}` : undefined}
            />
            <AutoPreparationStep
              label="3 · 개요 검토"
              value={overviewStatusForStep ?? "확인 중"}
              variant={preSpecItem && preSpecItem.overview_review_status !== null
                ? preSpecOverviewStatusVariant(preSpecItem.overview_review_status)
                : "neutral"}
            />
            <AutoPreparationStep
              label="4 · 심층 검토"
              value={autoStatus ? PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL[autoStatus] : "확인 중"}
              variant={autoStatus ? preSpecAutoPreparationVariant(autoStatus) : "neutral"}
              detail={autoReasonLabel ?? undefined}
            />
          </ol>
          {autoStatus === "deep_review_started" && autoDeepReviewId ? (
            <Link className="pre-spec-auto-preparation-link" to={`/deep-reviews/${autoDeepReviewId}`}>
              자동 시작된 심층 검토 보고서 열기 →
            </Link>
          ) : null}
          {autoStatus === "deep_review_started" && !autoDeepReviewId ? (
            <p className="pre-spec-auto-preparation-note">
              심층 검토가 자동으로 시작됐지만 응답에 식별자가 없어 보고서로 갈 수 없습니다. 다른 보고서로 대신 보내지 않습니다.
            </p>
          ) : null}
          {autoStatus === "deep_review_ready_for_click" ? (
            <a className="pre-spec-auto-preparation-link" href="#document-preparation">
              심층 검토 실행 · 아래 문서 준비에서 시작 →
            </a>
          ) : null}
          <p className="pre-spec-auto-preparation-note">
            자동 준비는 문서를 모으는 단계까지입니다. 추적 선택·참여 준비 상태·최종 입찰 Go/No-Go를 대신하지 않습니다.
          </p>
        </div>

        {/* 처리 상태·검증 상태·입력 준비 배지는 본문(개요 검토 상태 패널)과
            우측 레일(이력)이 이미 정본으로 보여준다. 여기서 같은 문구를
            또 배지로 복제하면 같은 role·이름을 가진 요소가 늘어나 strict
            mode 선택자가 깨진다 — 헤더는 현재 추적 상태 배지와 결정 액션만
            갖는다.

            결정 **액션**은 헤더에 고정하고 되돌릴 수 없는 입력 **form**은 본문에
            둔다(PLAN 단계 F 작업 1·완료 게이트). 시안 `PreSpecDetail`·
            `DetailSkeleton`의 헤더도 버튼만 갖는다. 저장 버튼은 form 속성으로
            본문 폼을 submit하므로 전제조건이 한 곳에만 있다. */}
        <div className="detail-skeleton-status-row">
          <Badge label={`추적 ${trackingStatusLabel}`} variant={trackingStatusLabel === "미선택" ? "neutral" : "grade-1"} />
          <div className="detail-skeleton-actions">
            {trackingDecision.hasForm ? (
              <>
                <ReviewDecisionAction
                  className="interaction-control"
                  disabledReason={trackingDecision.disabledReason ?? undefined}
                  disabledReasonId="pre-spec-detail-tracking-disabled"
                  form={TRACKING_FORM_ID}
                  isDisabled={!trackingDecision.ready}
                  label={trackingDecision.saveLabel}
                  type="submit"
                  variant="primary"
                />
                <button className="interaction-control" type="button" onClick={focusTrackingForm}>
                  추적 결정 입력으로 이동
                </button>
              </>
            ) : (
              <button className="interaction-control" type="button" onClick={focusTrackingForm}>
                추적 상태 확인
              </button>
            )}
          </div>
        </div>
      </StickyDecisionHeader>

      <div className="detail-skeleton-grid">
      <div className="detail-skeleton-main">
        {/* 되돌릴 수 없는 입력 form은 본문에 둔다. 헤더는 같은 submit을 쏘는
            액션과 현재 상태 배지만 갖는다(PLAN 단계 F 작업 1). */}
        <div ref={trackingPanelRef}>
          <TrackingDecisionControl
            compact
            formId={TRACKING_FORM_ID}
            headingLevel="h3"
            item={preSpecItem}
            isPending={preSpecProjectionQuery.isPending}
            isError={preSpecProjectionQuery.isError}
            onDecisionStateChange={handleTrackingDecisionState}
            onRetry={() => { void preSpecProjectionQuery.refetch(); }}
            onSaved={(saved) => {
              if (noticeId === null) return;
              queryClient.setQueryData<PreSpecListResponse>(
                ["pre-spec-detail", noticeId],
                (current) => updateTrackingProjection(current, noticeId, saved),
              );
              queryClient.setQueriesData<PreSpecListResponse>(
                { queryKey: ["pre-specs"] },
                (current) => updateTrackingProjection(current, noticeId, saved),
              );
              void queryClient.invalidateQueries({ queryKey: ["pre-spec-overview-reviews-v2", noticeId] });
              void queryClient.invalidateQueries({ queryKey: ["pre-spec-detail", noticeId] });
              void queryClient.invalidateQueries({ queryKey: ["pre-specs"] });
              void queryClient.invalidateQueries({ queryKey: ["opportunity", saved.id] });
            }}
          />
        </div>

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

        {preSpecProjectionQuery.isPending ? <p role="status">첨부 원문 취득 집계를 불러오는 중입니다.</p> : null}
        {preSpecProjectionQuery.isError ? (
          <EmptyState
            compact
            tone="error"
            title="첨부 원문 취득 집계를 불러오지 못했습니다."
            description="사전규격 projection을 불러오지 못해 첨부 취득 집계를 표시하지 않습니다."
            action={{ label: "다시 시도", onClick: () => { void preSpecProjectionQuery.refetch(); } }}
          />
        ) : null}
        {preSpecItem ? (
          // PreSpecDocumentSummary가 자체 heading("첨부 원문 취득 집계")을
          // 이미 렌더링하므로 Panel에 title을 다시 주지 않는다 — 같은
          // 문구의 heading이 둘이면 strict mode 선택자가 깨진다.
          <Panel>
            <PreSpecDocumentSummary item={preSpecItem} />
          </Panel>
        ) : null}

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
              {/* 개요 카드의 품질 표식(명세 §6.3·§8). 참조 실행과 mock 참조를
                  운영 완료로 보이게 하지 않고, 표식이 없으면 `표식 없음`이다. */}
              <div className="pre-spec-overview-quality">
                <span>품질 표식</span>
                <Badge label={qualityStatusLabel(overview.quality_status)} variant={qualityStatusVariant(overview.quality_status)} />
                <p>{qualityStatusNote(overview.quality_status)}</p>
              </div>
              {overview.result ? (
                <>
                  <div className={`pre-spec-overview-decision ${overview.validation_status === "passed" ? "" : "is-unverified"}`}>
                    <div className="pre-spec-overview-recommendation">
                      <span>권고</span>
                      <strong>{overview.result.recommendation}</strong>
                    </div>
                    <div className="pre-spec-overview-validation">
                      <span>신뢰도 · 검증 상태</span>
                      <Badge
                        label={VALIDATION_STATUS[overview.validation_status].label}
                        variant={VALIDATION_STATUS[overview.validation_status].variant}
                      />
                    </div>
                  </div>
                  {VALIDATION_STATUS[overview.validation_status].warning ? (
                    <p className="pre-spec-overview-validation-warning" role="alert">
                      {VALIDATION_STATUS[overview.validation_status].warning}
                    </p>
                  ) : null}
                  <div className="pre-spec-overview-statuses">
                    <span>처리 상태</span>
                    <Badge label={REVIEW_STATUS[overview.status]} variant={statusVariant(overview.status)} />
                  </div>

                  <section className="pre-spec-overview-section" aria-labelledby="pre-spec-overview-summary-title">
                    <h4 id="pre-spec-overview-summary-title">요약</h4>
                    <p className="pre-spec-overview-summary">{overview.result.summary}</p>
                  </section>

                  <section className="pre-spec-overview-section" aria-labelledby="pre-spec-overview-conditions-title">
                    <h4 id="pre-spec-overview-conditions-title">조건과 기한</h4>
                    <div className="pre-spec-overview-due">
                      <span>확인 기한</span>
                      {overview.result.verification_due_at ? (
                        <span className="pre-spec-overview-due-value">
                          <span className={`pre-specs-deadline is-${describeDeadline(overview.result.verification_due_at).urgency} mono tabular-nums`}>
                            {describeDeadline(overview.result.verification_due_at).label}
                          </span>
                          <span>{formatDateTime(overview.result.verification_due_at)}</span>
                        </span>
                      ) : <strong>확인 기한 미지정</strong>}
                    </div>
                    {overview.result.conditions.length > 0 ? (
                      <ul className="pre-spec-overview-list">
                        {overview.result.conditions.map((condition) => <li key={condition}>{condition}</li>)}
                      </ul>
                    ) : <p className="pre-spec-overview-empty">추가 조건 없음</p>}
                  </section>

                  <section className="pre-spec-overview-section" aria-labelledby="pre-spec-overview-unknowns-title">
                    <h4 id="pre-spec-overview-unknowns-title">미확인</h4>
                    {overview.result.unknowns.length > 0 ? (
                      <ul className="pre-spec-overview-unknowns">
                        {overview.result.unknowns.map((unknown) => (
                          <li key={`${unknown.topic}-${unknown.reason}`}>
                            <dl>
                              <div><dt>항목</dt><dd>{unknown.topic}</dd></div>
                              <div><dt>이유</dt><dd>{unknown.reason}</dd></div>
                              <div>
                                <dt>확인 방법</dt>
                                {/* 확인 방법이 없는 unknown은 아무도 착수할 수 없는 항목이다.
                                    문구만으로는 다른 값과 섞여 읽히므로 표식을 붙인다. */}
                                <dd className={unknown.verification_action === null ? "pre-spec-overview-unverifiable" : undefined}>
                                  {unknown.verification_action ?? "확인 방법 미지정"}
                                </dd>
                              </div>
                            </dl>
                          </li>
                        ))}
                      </ul>
                    ) : <p className="pre-spec-overview-empty">미확인 항목 없음</p>}
                  </section>

                  <section className="pre-spec-overview-section" aria-labelledby="pre-spec-overview-evidence-title">
                    <h4 id="pre-spec-overview-evidence-title">근거</h4>
                    <ul className="pre-spec-overview-evidence">
                      {overview.result.evidence.map((evidence) => {
                        const itemKey = evidenceKey(evidence);
                        return (
                        <li key={itemKey}>
                          <p>{evidence.claim}</p>
                          <div className="pre-spec-overview-evidence-footer">
                            <div className="pre-spec-overview-evidence-locator" aria-label="근거 위치">
                              <span>위치</span>
                              <span>{evidence.locator.page}쪽</span>
                              <code className="mono">{evidence.locator.block_key}</code>
                              <code className="mono">ordinal {evidence.locator.ordinal}</code>
                            </div>
                            <button
                              type="button"
                              className="pre-spec-overview-evidence-open"
                              aria-controls="pre-spec-overview-source"
                              aria-expanded={selectedEvidence !== null && evidenceKey(selectedEvidence) === itemKey}
                              onClick={() => setSelectedEvidence(evidence)}
                            >
                              원문 열기
                            </button>
                          </div>
                        </li>
                        );
                      })}
                    </ul>
                    {selectedEvidence ? (
                      <section
                        id="pre-spec-overview-source"
                        className="pre-spec-overview-source"
                        aria-labelledby="pre-spec-overview-source-title"
                      >
                        <header className="pre-spec-overview-source-header">
                          <div>
                            <span className="pre-spec-overview-source-eyebrow">근거 원문</span>
                            <h5 id="pre-spec-overview-source-title">페이지 {selectedEvidence.locator.page} · 원문 블록 확인</h5>
                          </div>
                          <button
                            type="button"
                            className="pre-spec-overview-source-close"
                            aria-label="원문 닫기"
                            onClick={() => setSelectedEvidence(null)}
                          >
                            닫기
                          </button>
                        </header>

                        {!sourceStructureId || !sourcePageNumber ? (
                          <EmptyState
                            compact
                            tone="warning"
                            title="원문 위치를 확인할 수 없습니다."
                            description="현재 snapshot의 구조 ID 또는 페이지가 없어 원문을 열지 않았습니다."
                          />
                        ) : null}
                        {sourceStructureId && sourcePageNumber && sourcePageQuery.isPending ? (
                          <p className="pre-spec-overview-source-loading" role="status" aria-live="polite">
                            페이지 {sourcePageNumber}의 원문을 불러오는 중입니다.
                          </p>
                        ) : null}
                        {sourceStructureId && sourcePageNumber && sourcePageQuery.isError ? (
                          <EmptyState
                            compact
                            tone="error"
                            title="원문을 불러오지 못했습니다."
                            description={errorMessage(sourcePageQuery.error, "선택한 문서 페이지를 확인할 수 없습니다.")}
                            action={{ label: "다시 시도", onClick: () => { void sourcePageQuery.refetch(); } }}
                          />
                        ) : null}
                        {sourcePageQuery.isSuccess ? (
                          <>
                            {selectedBlockIndex === -1 ? (
                              <div className="pre-spec-overview-source-mismatch" role="alert">
                                <strong>근거 위치와 원문이 어긋났습니다.</strong>
                                <p>
                                  locator의 block_key를 이 페이지 원문에서 찾지 못해 어떤 블록도 강조하지 않았습니다. 근거를 사람 검토로 확인해야 합니다.
                                </p>
                              </div>
                            ) : null}
                            <div className="pre-spec-overview-source-page">페이지 {sourcePageQuery.data.page}</div>
                            <ol className="pre-spec-overview-source-blocks">
                              {displayedSourceBlocks.map((block) => (
                                <li
                                  key={`${block.page}-${block.block_key}`}
                                  className={`pre-spec-overview-source-block ${block.block_key === selectedEvidence.locator.block_key ? "is-target" : ""}`.trim()}
                                  data-block-key={block.block_key}
                                >
                                  <div className="pre-spec-overview-source-block-header">
                                    <span>페이지 {block.page}</span>
                                    <code className="mono">{block.block_key}</code>
                                    {block.block_key === selectedEvidence.locator.block_key ? (
                                      <span className="pre-spec-overview-source-highlight-label">강조된 근거 위치</span>
                                    ) : null}
                                  </div>
                                  <p>{block.text}</p>
                                </li>
                              ))}
                            </ol>
                          </>
                        ) : null}
                      </section>
                    ) : null}
                  </section>

                  <section className="pre-spec-overview-section pre-spec-overview-limitations" aria-labelledby="pre-spec-overview-limitations-title">
                    <h4 id="pre-spec-overview-limitations-title">이 판단의 한계</h4>
                    <ul className="pre-spec-overview-list">
                      {overview.result.input_limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
                    </ul>
                  </section>
                </>
              ) : (
                <>
                  <div className="pre-spec-overview-decision is-unconfirmed">
                    <div className="pre-spec-overview-recommendation">
                      <span>권고</span>
                      <strong>검토 결과 미확정</strong>
                    </div>
                    <div className="pre-spec-overview-validation">
                      <span>신뢰도 · 검증 상태</span>
                      <Badge
                        label={VALIDATION_STATUS[overview.validation_status].label}
                        variant={VALIDATION_STATUS[overview.validation_status].variant}
                      />
                    </div>
                  </div>
                  <div className="pre-spec-overview-statuses">
                    <span>처리 상태</span>
                    <Badge label={REVIEW_STATUS[overview.status]} variant={statusVariant(overview.status)} />
                  </div>
                  <div className="pre-spec-overview-waiting">
                    <strong>{REVIEW_STATUS[overview.status]} · 검증된 결과를 기다리는 중</strong>
                    <p>{REVIEW_WAITING_DESCRIPTION[overview.status]}</p>
                  </div>
                </>
              )}

              <p className="pre-spec-overview-limit">
                이 개요 검토는 서버가 고정한 구조 절단 입력만 다룹니다. 개요 결과는 추적 상태·참여 준비·최종 Go/No-Go를 대신하지 않습니다.
              </p>
            </div>
          ) : null}
        </Panel>
      </div>

      {/* 우측 레일은 이력과 연결만 담는다(시안 주석 원문). 결정 액션(추적
          선택)은 헤더에만 있고 여기서 복제하지 않는다. */}
      <ReviewHistoryLinkRail
        className="detail-skeleton-rail"
        footer={<p className="detail-skeleton-rail-note">우측 레일은 이력과 연결만 담습니다. 결정 액션은 헤더에만 있습니다.</p>}
        historySections={[{
          className: "detail-skeleton-rail-panel",
          content: overview ? (
            <>
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
                        <span>검증 {attempt.validation_status}</span>
                        <span className="pre-spec-overview-digest mono">result {attempt.result_digest ?? "없음"}</span>
                        <span className="pre-spec-overview-digest mono">binding {attempt.binding_digest ?? "없음"}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <dl className="pre-spec-overview-digests">
                <div><dt>결과 digest</dt><dd className="mono">{overview.result_digest ?? "없음"}</dd></div>
                <div><dt>binding digest</dt><dd className="mono">{overview.binding_digest ?? "없음"}</dd></div>
              </dl>
            </>
          ) : <p className="detail-skeleton-rail-note">아직 개요 검토 이력이 없습니다.</p>,
          entries: [],
          label: "입력 범위와 실행",
          showHeading: false,
        }]}
        links={[
          { href: listUrl, label: "사전규격 목록 →" },
          ...(preSpecItem?.opportunity_id ? [{ href: `/opportunities/${preSpecItem.opportunity_id}`, label: "사업기회 보기 →" }] : []),
        ]}
        linksClassName="detail-skeleton-rail-links"
        title="이력 · 입력 범위와 실행"
      />
      </div>

      <DocumentPreparationPanel
        noticeId={notice.id}
        // 헤더가 보여 주는 것과 **같은 현재 등급**을 넘긴다. `notice.grade`는
        // 사람 정정을 반영하지 않아 헤더와 다른 값을 말할 수 있다(명세 §6.2).
        currentGrade={preSpecItem?.grade ?? null}
        onDeepReviewCreated={(review) => navigate(`/deep-reviews/${review.id}`)}
      />
    </section>
  );
}
