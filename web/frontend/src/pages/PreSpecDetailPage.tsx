import { Button } from "@astryxdesign/core/Button";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { BUNDLE_STATUS_LABELS, DocumentPreparationPanel } from "../components/deep-review/DocumentPreparationPanel";
import { getDocumentBundles, getDocumentStructurePage } from "../components/deep-review/api";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { ReviewDecisionAction, ReviewHistoryLinkRail } from "../components/common/ReviewPrimitives";
import { SkeletonBlock, SkeletonPanel } from "../components/common/Skeleton";
import { PreSpecDocumentSummary, TrackingDecisionControl, updateTrackingProjection } from "../components/pre-specs/TrackingDecisionControl";
import { api } from "../lib/api";
import { PreSpecRecordIdentity } from "../components/pre-specs/PreSpecRecordIdentity";
import { CompanyFitSection } from "../components/pre-specs/CompanyFitSection";
import { PageOverviewSection } from "../components/pre-specs/PageOverviewSection";
import { apiErrorRecoveryAction, describeApiError } from "../lib/apiErrors";
import { describeDeadline } from "../lib/deadline";
import { formatDateTime, formatNumber, present } from "../lib/format";
import { gradeLabel, gradeSourceLabel, gradeVariant } from "../lib/grade";
import {
  PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL,
  preSpecAutoPreparationReasonLabel,
  preSpecAutoPreparationVariant,
} from "../lib/preSpecAutoPreparation";
import {
  hasCanonicalOverviewNoticeId,
  PRE_SPEC_OVERVIEW_ATTEMPT_STATUS_LABEL,
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
  PRE_SPEC_OVERVIEW_VALIDATION,
  PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION,
  preSpecOverviewStatusVariant,
} from "../lib/preSpecOverviewStatus";
import { qualityStatusLabel, qualityStatusNote, qualityStatusVariant } from "../lib/qualityStatus";
import type {
  PreSpecListItem,
  PreSpecListResponse,
  PreSpecOverviewCutStatus,
  PreSpecOverviewEvidence,
} from "../lib/types";
import "../styles/pre-specs-relaxed.css";
import "../styles/detail-skeleton.css";
import "../styles/pre-spec-detail-erp.css";

/** The reading column scrolls normally; only the adjacent decision form stays in view. */
function focusSection(id: string) {
  const target = document.getElementById(id);
  if (target) { target.scrollIntoView({ block: "start" }); target.focus({ preventScroll: true }); }
}

const REVIEW_STATUS = PRE_SPEC_OVERVIEW_STATUS_LABEL;

/** 오른쪽 결정 패널의 저장 액션이 같은 패널 안의 폼을 submit한다. */
const TRACKING_FORM_ID = "pre-spec-detail-tracking-form";
const TRACKING_REASON_PRESETS = ["후속 입찰공고 확인", "세부 과업·연계 범위 확인", "참여 자격·실적 확인 필요"] as const;

function recordDateTime(value: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return "미확인";
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(value));
  const part = (type: string) => parts.find(item => item.type === type)?.value;
  return `${part("year")}.${part("month")}.${part("day")} ${part("hour")}:${part("minute")} KST`;
}

interface TrackingDecisionState {
  ready: boolean;
  disabledReason: string | null;
  hasForm: boolean;
  saveLabel: string;
}

const ATTEMPT_STATUS = PRE_SPEC_OVERVIEW_ATTEMPT_STATUS_LABEL;

// 검증 상태 문구와 대기 사유 문장은 `lib/preSpecOverviewStatus`가 소유한다.
// 사전규격 목록 화면의 개요 탭이 같은 문장을 쓰므로 두 벌로 두지 않는다.
const VALIDATION_STATUS = PRE_SPEC_OVERVIEW_VALIDATION;
const REVIEW_WAITING_DESCRIPTION = PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION;

const statusVariant = preSpecOverviewStatusVariant;

function cutStatus(status: PreSpecOverviewCutStatus): { label: string; variant: BadgeVariant; description: string } {
  if (status === "ready") {
    return { label: "입력 범위 준비됨", variant: "evidence-confirmed", description: "서버가 구조화 문서에서 개요 입력 범위를 확정했습니다." };
  }
  if (status === "unknown") {
    return { label: "unknown · 사람 확인 필요", variant: "evidence-unknown", description: "구조 절단 범위를 확정하지 못했습니다. 전체 문서 성공으로 자동 보정하지 않습니다." };
  }
  if (status === "failed") {
    return { label: "입력 준비 실패", variant: "danger", description: "개요 입력 준비가 실패했습니다. 사람 확인과 안전한 재처리가 필요합니다." };
  }
  return { label: "입력 준비 대기", variant: "neutral", description: "개요 입력 범위가 아직 확정되지 않았습니다." };
}

/**
 * 상세 화면이 기다리는 것을 자리로 먼저 보여 준다. 쿼리마다 다른 문장이 뜨고
 * 사라지며 레이아웃이 흔들리던 자리를 헤더·사실·개요 세 자리로 고정한다.
 */
function PreSpecDetailSkeleton({ noticeId }: { noticeId: number }) {
  return (
    <div className="pre-spec-detail-page detail-skeleton ps-record" data-astryx-theme="bidops">
      <div className="detail-skeleton-grid">
        <div className="detail-skeleton-main">
          <SkeletonPanel label={`사전규격 ${noticeId} 상세를 불러오는 중`} lines={3} />
          <SkeletonPanel label="사전규격 사실을 불러오는 중" lines={4} />
          <SkeletonPanel label="개요 검토 상태를 불러오는 중" lines={5} />
        </div>
        <div className="ps-record-side">
          <SkeletonPanel label="추적 결정 정보를 불러오는 중" lines={6} />
        </div>
      </div>
    </div>
  );
}

/**
 * 상세 화면의 조회 오류 하나. 제목은 화면 맥락이고, 원인과 다음 행동은
 * `lib/apiErrors`의 정책 하나가 정한다. 서버 raw message·원문·경로는 여기까지
 * 오지 않는다(docs/security.md).
 */
function PreSpecQueryError({
  error,
  fallback,
  onRetry,
  title,
}: {
  error: unknown;
  fallback: string;
  onRetry: () => void;
  title: string;
}) {
  const problem = describeApiError(error, fallback);
  return (
    <EmptyState
      compact
      tone="error"
      title={title}
      problem={problem}
      action={apiErrorRecoveryAction(problem, onRetry)}
    />
  );
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
    return <PreSpecDetailSkeleton noticeId={noticeId} />;
  }

  if (noticeQuery.isError) {
    const problem = describeApiError(noticeQuery.error, "선택한 notice의 상세 정보를 확인할 수 없습니다.");
    return (
      <EmptyState
        tone="error"
        title={`사전규격 ${noticeId} 상세를 불러오지 못했습니다.`}
        problem={problem}
        action={apiErrorRecoveryAction(problem, () => { void noticeQuery.refetch(); })}
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
  const lifecycle = notice.lifecycle;
  const lifecycleNumber = lifecycle && typeof lifecycle === "object" && !Array.isArray(lifecycle) && "pre_spec_no" in lifecycle && typeof lifecycle.pre_spec_no === "string" ? lifecycle.pre_spec_no : null;
  const rawNumber = preSpecItem?.pre_spec_no ?? lifecycleNumber;
  const preSpecNumber = rawNumber?.trim() && rawNumber !== "unknown" ? rawNumber.trim() : null;
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
    <section className="pre-spec-detail-page detail-skeleton ps-record" data-astryx-theme="bidops" aria-labelledby="pre-spec-detail-title">
      {/* 자체 브레드크럼은 두지 않는다. 상단 경로(`nav[aria-label="현재 위치"]`)가
          `탐색과 추적 › 사전규격 › notice ID`를 이미 그리고, 사전규격 칸이 목록
          링크다. 경로가 두 벌이면 현재 위치를 두 번 읽어야 한다. */}
      <div className="detail-skeleton-grid">
      <div className="detail-skeleton-main">
      <header className="pre-spec-detail-header detail-skeleton-head" aria-label="사전규격 상세 정보">
        <div className="detail-skeleton-head-top"><div>
          <h2 id="pre-spec-detail-title">{present(notice.title, "사업명 미확인")}</h2>
          <p className="ps-record-agency">{present(notice.agency, "발주기관 미확인")}</p>
        </div></div>
        <PreSpecRecordIdentity key={noticeId} number={preSpecNumber} url={notice.url} />
        <dl className="ps-record-facts" aria-label="사전규격 기본 정보">
          <div><dt>사업 예산</dt><dd>{notice.budget === null ? "예산 미확인" : `${formatNumber(notice.budget)}원`}</dd></div>
          <div><dt>의견등록 마감 <span className={`pre-specs-deadline is-${deadline.urgency} mono tabular-nums`}>{deadline.label}</span></dt><dd>{recordDateTime(notice.deadline_at)}</dd></div>
        </dl>

        <div className="detail-skeleton-status-row">
        {/* 등급과 등급 출처(명세 §6.8). 등급은 서버가 준 값 그대로이며 화면이
            판정하지 않는다. 판정도 사람 정정도 없으면 `판정 없음`이고, 그것은
            다섯 번째 등급이 아니라 아직 판정하지 않았다는 뜻이다. */}
        <div className="pre-spec-detail-grade-row">
          <span className="pre-spec-detail-grade-label">적합성 등급</span>
          {preSpecProjectionQuery.isPending ? (
            <span className="pre-spec-detail-grade-source">등급을 불러오는 중입니다.</span>
          ) : !preSpecItem || preSpecProjectionQuery.isError ? (
            <span className="pre-spec-detail-grade-source">등급 미확인</span>
          ) : (
            <>
              <Badge label={gradeLabel(preSpecItem?.grade ?? null)} variant={gradeVariant(preSpecItem?.grade ?? null)} />
              <span className="pre-spec-detail-grade-source">
                등급 출처 · {gradeSourceLabel(preSpecItem?.grade_source ?? null)}
              </span>
            </>
          )}
        </div>


          <span className="ps-record-sw">SW사업대상 <strong>{preSpecItem?.sw_business_status ?? "미확인"}</strong></span>

        </div>
        <nav className="ps-record-nav" aria-label="상세 검토 구역">
          <Button variant="ghost" label="검토 요약" onClick={() => focusSection("ps-record-overview")} />
          <Button variant="ghost" label="첨부 문서" onClick={() => focusSection("ps-record-documents")} />
          <Button variant="ghost" label="처리 이력" onClick={() => focusSection("ps-record-history")} />
          <Link to={listUrl}>목록으로 돌아가기</Link>
        </nav>
      </header>


        <div id="ps-record-overview" className="ps-record-section" tabIndex={-1}>
        <Panel title="검토 요약" className="pre-spec-overview-panel">
          {overviewQuery.isPending ? (
            <SkeletonBlock label="개요 검토 요약 정보를 불러오는 중" lines={4} />
          ) : null}
          {overviewQuery.isError ? (
            <PreSpecQueryError
              onRetry={() => { void overviewQuery.refetch(); }}
              error={overviewQuery.error}
              fallback="개요 검토 API 응답을 확인할 수 없습니다."
              title="개요 검토 상태를 불러오지 못했습니다."
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
              {overview.result ? (
                <>
                  <div className={`pre-spec-overview-decision ${overview.validation_status === "passed" ? "" : "is-unverified"}`}>
                    <div className="pre-spec-overview-recommendation">
                      <span>개요 권고</span>
                      <strong>{overview.result.recommendation}</strong>
                    </div>
                    <div className="pre-spec-overview-quality" aria-label="실행 품질"><Badge label={qualityStatusLabel(overview.quality_status)} variant={qualityStatusVariant(overview.quality_status)} /></div>
                  </div>
                  {VALIDATION_STATUS[overview.validation_status].warning ? (
                    <div className="pre-spec-overview-validation-warning" role="alert"><Badge label={VALIDATION_STATUS[overview.validation_status].label} variant={VALIDATION_STATUS[overview.validation_status].variant} /><p>{VALIDATION_STATUS[overview.validation_status].warning}</p></div>
                  ) : null}
                  {overview.status !== "completed" ? <div className="pre-spec-overview-statuses"><span>처리 상태</span><Badge label={REVIEW_STATUS[overview.status]} variant={statusVariant(overview.status)} /></div> : null}

                  <section className="pre-spec-overview-section" aria-labelledby="pre-spec-overview-summary-title">
                    <h4 id="pre-spec-overview-summary-title">사업 핵심</h4>
                    <p className="pre-spec-overview-summary">{overview.result.summary} {overview.result.evidence.length > 0 ? <button className="ps-record-inline-link" type="button" onClick={() => focusSection("ps-record-evidence")}>근거 보기 ›</button> : null}</p>
                  </section>

                  <section className="pre-spec-overview-section ps-record-checks" aria-labelledby="pre-spec-overview-conditions-title">
                    <div className="ps-record-check-heading"><h4 id="pre-spec-overview-conditions-title">우선 확인할 사항 <span>{overview.result.conditions.length + overview.result.unknowns.length}</span></h4><span className="pre-spec-overview-due">확인 기한 · {overview.result.verification_due_at ? recordDateTime(overview.result.verification_due_at) : "미지정"}</span></div>
                    <ol className="ps-record-check-list">
                      {overview.result.conditions.map((condition, index) => <li key={`condition-${index}`}><span>{index + 1}</span><p>{condition}</p></li>)}
                      {overview.result.unknowns.map((unknown, index) => <li key={`${unknown.topic}-${index}`}><span>{overview.result!.conditions.length + index + 1}</span><details className="ps-record-check-detail"><summary>{unknown.topic}</summary><dl><div><dt>이유</dt><dd>{unknown.reason}</dd></div><div><dt>확인 방법</dt><dd className={unknown.verification_action === null ? "pre-spec-overview-unverifiable" : undefined}>{unknown.verification_action ?? "확인 방법 미지정"}</dd></div></dl></details></li>)}
                    </ol>
                    {overview.result.conditions.length === 0 && overview.result.unknowns.length === 0 ? <p className="pre-spec-overview-empty">추가 조건·미확인 항목 없음</p> : null}
                  </section>

                </>
              ) : (
                <>
                  <div className="pre-spec-overview-decision is-unconfirmed">
                    <div className="pre-spec-overview-quality" aria-label="실행 품질"><Badge label={qualityStatusLabel(overview.quality_status)} variant={qualityStatusVariant(overview.quality_status)} /></div>
                    <div className="pre-spec-overview-recommendation">
                      <span>개요 권고</span>
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

              <details className="ps-record-quality-details"><summary>품질·검증 정보</summary>
                <p>{qualityStatusNote(overview.quality_status)}</p>
                <dl><div><dt>처리 상태</dt><dd><Badge label={REVIEW_STATUS[overview.status]} variant={statusVariant(overview.status)} /></dd></div>{overview.result && overview.validation_status === "passed" ? <div><dt>신뢰도 · 검증 상태</dt><dd><Badge label={VALIDATION_STATUS[overview.validation_status].label} variant={VALIDATION_STATUS[overview.validation_status].variant} /></dd></div> : null}</dl>
                {overview.result ? (                  <section className="pre-spec-overview-section pre-spec-overview-limitations" aria-labelledby="pre-spec-overview-limitations-title">
                    <h4 id="pre-spec-overview-limitations-title">이 판단의 한계</h4>
                    <ul className="pre-spec-overview-list">
                      {overview.result.input_limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
                    </ul>
                  </section>
) : null}
                <p className="pre-spec-overview-limit">이 개요 검토는 서버가 고정한 구조 절단 입력만 다룹니다. 개요 결과는 추적 상태·참여 준비·최종 Go/No-Go를 대신하지 않습니다.</p>
              </details>
            </div>
          ) : null}
        </Panel>
        </div>
        {noticeId !== null && <PageOverviewSection key={noticeId} noticeId={noticeId} />}
        {noticeId !== null && <CompanyFitSection key={`fit-${noticeId}`} noticeId={noticeId} />}
        <div id="ps-record-documents" className="ps-record-section ps-record-documents" tabIndex={-1}>
        {overview?.result ? <Panel title="첨부 문서·근거" className="ps-record-evidence-panel">                  <section className="pre-spec-overview-section" id="ps-record-evidence" tabIndex={-1} aria-labelledby="pre-spec-overview-evidence-title">
                    <h4 id="pre-spec-overview-evidence-title">근거</h4>
                    <ul className="pre-spec-overview-evidence">
                      {overview.result.evidence.length === 0 ? <li>제공된 근거 없음</li> : null}
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
                            description="현재 고정 입력의 구조 ID 또는 페이지가 없어 원문을 열지 않았습니다."
                          />
                        ) : null}
                        {sourceStructureId && sourcePageNumber && sourcePageQuery.isPending ? (
                          <SkeletonBlock
                            className="pre-spec-overview-source-loading"
                            label={`페이지 ${sourcePageNumber}의 원문을 불러오는 중`}
                            lines={3}
                          />
                        ) : null}
                        {sourceStructureId && sourcePageNumber && sourcePageQuery.isError ? (
                          <PreSpecQueryError
                            onRetry={() => { void sourcePageQuery.refetch(); }}
                            error={sourcePageQuery.error}
                            fallback="선택한 문서 페이지를 확인할 수 없습니다."
                            title="원문을 불러오지 못했습니다."
                          />
                        ) : null}
                        {sourcePageQuery.isSuccess ? (
                          <>
                            {selectedBlockIndex === -1 ? (
                              <div className="pre-spec-overview-source-mismatch" role="alert">
                                <strong>근거 위치와 원문이 어긋났습니다.</strong>
                                <p>
                                  원문 위치가 가리키는 블록을 이 페이지에서 찾지 못해 어떤 블록도 강조하지 않았습니다. 근거를 사람이 확인해야 합니다.
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

</Panel> : null}
        {preSpecProjectionQuery.isPending ? (
          <SkeletonPanel label="첨부 원문 취득 집계를 불러오는 중" lines={3} />
        ) : null}
        {preSpecProjectionQuery.isError ? (
          <PreSpecQueryError
            onRetry={() => { void preSpecProjectionQuery.refetch(); }}
            error={preSpecProjectionQuery.error}
            fallback="사전규격 요약 정보를 불러오지 못해 첨부 취득 집계를 표시하지 않습니다."
            title="첨부 원문 취득 집계를 불러오지 못했습니다."
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

      <DocumentPreparationPanel
        noticeId={notice.id}
        // 헤더가 보여 주는 것과 **같은 현재 등급**을 넘긴다. `notice.grade`는
        // 사람 정정을 반영하지 않아 헤더와 다른 값을 말할 수 있다(명세 §6.2).
        currentGrade={preSpecItem?.grade ?? null}
        onDeepReviewCreated={(review) => navigate(`/deep-reviews/${review.id}`)}
      />
        </div>


      <div id="ps-record-history" className="ps-record-section ps-record-history" tabIndex={-1}>
        <Panel title="검토 진행" className="ps-record-progress">
        <dl className="ps-record-secondary-facts"><div><dt>게시 시각</dt><dd>{recordDateTime(notice.published_at)}</dd></div><div><dt>첨부 원문</dt><dd>{notice.attachment_count}건</dd></div></dl>
        {/* 자동 준비 진행 — 첨부 취득 → 묶음 → 개요 → 심층 검토. */}
        <div className="pre-spec-auto-preparation" aria-label="자동 준비 진행">
          <ol className="pre-spec-auto-steps">
            <AutoPreparationStep
              label="1 · 첨부 취득"
              value={documentCounts ? `${documentCounts.attachments}건` : "집계 없음"}
              variant={documentCounts && (documentCounts["차단"] > 0 || documentCounts["실패"] > 0) ? "alert" : "neutral"}
              detail={documentCounts
                ? `완료 ${documentCounts["완료"]} · 대기 ${documentCounts["대기"]} · 진행 ${documentCounts["진행"]} · 차단 ${documentCounts["차단"]} · 실패 ${documentCounts["실패"]}`
                : "사전규격 요약 정보가 없어 첨부 집계를 표시하지 않습니다."}
            />
            <AutoPreparationStep
              label="2 · 문서 묶음"
              value={bundleQuery.isPending
                ? "확인 중"
                : bundleQuery.isError ? "확인 실패" : latestBundle ? BUNDLE_STATUS_LABELS[latestBundle.status] : "묶음 없음"}
              variant={latestBundle?.status === "ready"
                ? "evidence-confirmed"
                : latestBundle?.status === "failed" || latestBundle?.status === "quarantined" || latestBundle?.status === "needs_review"
                  ? "alert"
                  : "neutral"}
              detail={latestBundle ? `revision ${latestBundle.revision}` : undefined}
            />
            <AutoPreparationStep
              label="3 · 개요 검토"
              value={overviewStatusForStep ?? (preSpecProjectionQuery.isPending ? "확인 중" : "미확인")}
              variant={preSpecItem && preSpecItem.overview_review_status !== null
                ? preSpecOverviewStatusVariant(preSpecItem.overview_review_status)
                : "neutral"}
            />
            <AutoPreparationStep
              label="4 · 심층 검토"
              value={autoStatus ? PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL[autoStatus] : preSpecProjectionQuery.isPending ? "확인 중" : "미확인"}
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
            조건을 충족하면 심층 검토까지 자동으로 시작합니다. 추적 선택과 최종 입찰 Go/No-Go는 사람이 결정합니다.
          </p>
        </div>

        </Panel>
      <ReviewHistoryLinkRail
        className="detail-skeleton-rail"
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
                  <Badge label="고정 입력 없음" variant="neutral" />
                  <p>서버 요약 정보에 현재 고정 입력이 없습니다.</p>
                </div>
              )}
              <Collapsible trigger="고정 입력과 식별 정보" defaultIsOpen={false}>
              {snapshot ? (
                <dl className="pre-spec-overview-lineage">
                  <div><dt>절단 전략</dt><dd>{snapshot.strategy ?? "전략 미확정"}</dd></div>
                  <div><dt>문서 버전</dt><dd className="mono">{snapshot.document_version_id}</dd></div>
                  <div><dt>구조 버전</dt><dd className="mono">{snapshot.structure_id}</dd></div>
                  <div><dt>입력 생성</dt><dd>{formatDateTime(snapshot.created_at)}</dd></div>
                </dl>
              ) : null}
              <dl className="pre-spec-overview-digests">
                <div><dt>결과 식별 해시</dt><dd className="mono">{overview.result_digest ?? "없음"}</dd></div>
                <div><dt>모델 연결 식별 해시</dt><dd className="mono">{overview.binding_digest ?? "없음"}</dd></div>
              </dl>
              </Collapsible>
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
                        <span className="pre-spec-overview-digest mono">결과 해시 {attempt.result_digest ?? "없음"}</span>
                        <span className="pre-spec-overview-digest mono">모델 연결 해시 {attempt.binding_digest ?? "없음"}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

            </>
          ) : <p className="detail-skeleton-rail-note">{overviewQuery.isPending ? "처리 이력을 불러오는 중입니다." : overviewQuery.isError || overviewResponseInvalid ? "처리 이력을 확인할 수 없습니다." : "아직 개요 검토 이력이 없습니다."}</p>,
          entries: [],
          label: "입력 범위와 실행",
          showHeading: false,
        }]}
        links={[
          { href: listUrl, label: "사전규격 목록 →" },
          ...(preSpecItem?.opportunity_id ? [{ href: `/opportunities/${preSpecItem.opportunity_id}`, label: "사업기회 보기 →" }] : []),
        ]}
        linksClassName="detail-skeleton-rail-links"
        title="처리 이력과 연결"
      />
      </div>
      </div>
      <aside className="ps-record-side" aria-label="추적 결정" data-decision-panel="true">
        <div className="ps-record-decision-body">
          <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}>
          <TrackingDecisionControl
            key={noticeId}
            compact
            presentation="record"
            noticeNumber={preSpecNumber}
            reasonPresets={TRACKING_REASON_PRESETS}
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
          </InternationalizationProvider>
        </div>
        {trackingDecision.hasForm ? (
          <div className="ps-record-decision-footer">
            {trackingDecision.ready ? <p className="ps-record-save-ready">선택한 사유로 계속 추적을 시작합니다.</p> : null}
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
            <p className="ps-record-decision-note">입찰 참여 여부는 최종 Go/No-Go에서 결정합니다.</p>
          </div>
        ) : null}
      </aside>
      </div>
    </section>
  );
}
