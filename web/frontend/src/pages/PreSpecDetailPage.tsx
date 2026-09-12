import { Button } from "@astryxdesign/core/Button";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { BUNDLE_STATUS_LABELS, DocumentPreparationPanel } from "../components/deep-review/DocumentPreparationPanel";
import { getDocumentBundles } from "../components/deep-review/api";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { ReviewHistoryLinkRail } from "../components/common/ReviewPrimitives";
import { SkeletonPanel } from "../components/common/Skeleton";
import { PreSpecDocumentSummary, TrackingDecisionControl, updateTrackingProjection } from "../components/pre-specs/TrackingDecisionControl";
import { PreSpecBriefingSection } from "../components/pre-specs/PreSpecBriefingSection";
import { PreSpecAttachmentList } from "../components/pre-specs/PreSpecAttachmentList";
import { documentPanelDefaultOpen } from "../lib/documentPanelDefaultOpen";
import { api } from "../lib/api";
import { PreSpecRecordIdentity } from "../components/pre-specs/PreSpecRecordIdentity";
import {
  CompanyFitAutomationNotice,
  CompanyFitExecutionInfo,
  CompanyFitReasons,
  CompanyFitVerdict,
  NO_CURRENT_ATTEMPT_NOTICE,
  useCompanyFit,
} from "../components/pre-specs/CompanyFitSection";
import {
  PageOverviewCurrent,
  PageOverviewClaimLinks,
  PageOverviewExecutionInfo,
  PageOverviewFactLine,
  PageOverviewHistory,
  PageOverviewRangeReview,
  PageOverviewVerificationDetails,
  pageOverviewPdfUrl,
  useCurrentPageOverview,
} from "../components/pre-specs/PageOverviewSection";
import { apiErrorRecoveryAction, describeApiError } from "../lib/apiErrors";
import { describeDeadline } from "../lib/deadline";
import { formatNumber, present } from "../lib/format";
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
import { readPreSpecLifecycle, readProcurementClass } from "../lib/noticeLifecycle";
import type { PageOverviewFact, PageOverviewView, PreSpecListResponse } from "../lib/types";
import "../styles/pre-specs-relaxed.css";
import "../styles/detail-skeleton.css";
import "../styles/pre-spec-detail-erp.css";

const TRACKING_REASON_PRESETS = ["후속 입찰공고 확인", "세부 과업·연계 범위 확인", "참여 자격·실적 확인 필요"] as const;

function recordDateTime(value: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return "미확인";
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(value));
  const part = (type: string) => parts.find(item => item.type === type)?.value;
  return `${part("year")}.${part("month")}.${part("day")} ${part("hour")}:${part("minute")} KST`;
}

function deadlineChipVariant(urgency: ReturnType<typeof describeDeadline>["urgency"]): "neutral" | "warn" | "err" {
  if (urgency === "passed") return "err";
  if (urgency === "critical" || urgency === "soon") return "warn";
  return "neutral";
}

/** 승인 시안의 카드 한 장(`.card.sec`). 제목·부가 수치·우측 참조 링크 한 줄. */
function RecordSection({
  title,
  count,
  action,
  className = "",
  children,
}: {
  title: string;
  count?: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`ps-card ps-sec ${className}`.trim()}>
      <div className="ps-sec-head">
        <h2 className="ps-h-sec">{title}{count ? <> <span className="ps-cnt">{count}</span></> : null}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function OverviewPdfReference({ review }: { review: PageOverviewView }) {
  return <a className="ps-ref" href={pageOverviewPdfUrl(review)} target="_blank" rel="noreferrer">전체 근거 PDF 열기 ↗</a>;
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
        <div className="ps-record-aside ps-record-side">
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
    <li className="pre-spec-auto-step ps-step">
      <span className="pre-spec-auto-step-label ps-k">{label}</span>
      <Badge label={value} variant={variant} />
      {detail ? <span className="pre-spec-auto-step-detail ps-d">{detail}</span> : null}
    </li>
  );
}

/** 시안의 점 목록 한 줄. 문장과 PDF 근거 링크는 `PageOverviewFactLine`이 그린다. */
function FactBullets({ items, review }: { items: PageOverviewFact[]; review: PageOverviewView }) {
  if (items.length === 0) return <p className="ps-cap ps-muted">이번 입력에서는 확인되지 않았습니다.</p>;
  return (
    <ul className="ps-bul">
      {items.map((fact, index) => (
        <li key={index}>
          <span className="ps-dot ps-dot-neutral" aria-hidden="true" />
          <span className="ps-t"><PageOverviewFactLine fact={fact} review={review} /></span>
        </li>
      ))}
    </ul>
  );
}

/** 개요 본문의 브리핑 자리. 핵심 조건은 아래 "지켜야 할 조건" 카드가 소유한다. */
function PageOverviewBriefing({ review }: { review: PageOverviewView }) {
  const { payload } = review;
  const isVerifiedV4 = payload.schema_version === "bidops.prespec-overview-page-review.v4";
  const remainingOverview = payload.business_overview.slice(1);
  const claimTextById: ReadonlyMap<string, string> = isVerifiedV4
    ? new Map(
      [...payload.business_overview, ...payload.main_tasks, ...payload.budget_and_period, ...payload.important_conditions]
        .map((fact) => [fact.claim_id, fact.text] as const),
    )
    : new Map();
  return <div className="page-overview">
    {/* 헤더 띠가 첫 문장을 이미 보여 준다. 개요 본문 영역이 같은 문장을 계약대로
        담고 있어야 하므로 자리만 유지하고 화면에서는 감춘다. */}
    {payload.business_overview[0] ? (
      <p className="visually-hidden" aria-hidden="true"><PageOverviewFactLine fact={payload.business_overview[0]} review={review} anchor={false} /></p>
    ) : null}
    <div className="page-overview-validation" role="status">
      <strong>{review.validation_status === "failed" ? "검증 실패 · 사람 확인 필요" : isVerifiedV4 ? "주장 검증 완료 · 운영 승인 아님" : "근거 검사 통과 · 이전 검증 기준"}</strong>
      <p>사업 설명을 위한 요약입니다. 추적 승인과 최종 입찰 결정은 사람이 진행하며, 현재 회사 핏과 조건을 충족한 경우에만 심층 검토가 자동 시작됩니다.</p>
      {review.validation_status === "failed" && review.evidence_check_status === "passed" ? (
        <p>새 페이지 근거 검사는 통과했으나, 원실행의 검증 실패 기록은 유지합니다.</p>
      ) : null}
    </div>
    {remainingOverview.length > 0 ? <>
      <h4 className="ps-sub">사업 개요</h4>
      <FactBullets items={remainingOverview} review={review} />
    </> : null}
    <h4 className="ps-sub">주요 과업</h4>
    {payload.main_tasks.length === 0 ? <p className="ps-cap ps-muted">이번 입력에서는 확인되지 않았습니다.</p> : (
      <ol className="ps-bul">
        {payload.main_tasks.map((fact, index) => (
          <li key={index}>
            <span className="ps-n" aria-hidden="true">{index + 1}</span>
            <span className="ps-t"><PageOverviewFactLine fact={fact} review={review} /></span>
          </li>
        ))}
      </ol>
    )}
    <h4 className="ps-sub">사업 규모와 일정</h4>
    <FactBullets items={payload.budget_and_period} review={review} />
    <h4 className="ps-sub">검토 포인트 <span className="ps-cnt">모델 의견</span></h4>
    {isVerifiedV4
      ? payload.reviewer_analysis.map((item) => <p key={item.id}>{item.text} <span className="ps-cap ps-muted">근거 주장 · <PageOverviewClaimLinks claimIds={item.supporting_claim_ids} claimTextById={claimTextById} /></span></p>)
      : payload.reviewer_analysis.map((text, index) => <p key={index}>{text}</p>)}
  </div>;
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
  const pageOverviewState = useCurrentPageOverview(noticeId);
  const companyFitState = useCompanyFit(noticeId);
  // 사람이 직접 여닫거나 닫기 전에는 `null`이고, 그동안은 묶음·자동 준비 상태가
  // 정하는 기본값을 따른다. 응답이 늦게 와도 기본값이 다시 계산된다.
  const [documentPanelOverride, setDocumentPanelOverride] = useState<boolean | null>(null);
  const documentPanelInitialRef = useRef<boolean | null>(null);
  if (noticeId === null) {
    return (
      <EmptyState
        tone="error"
        title="사전규격 식별자를 확인할 수 없습니다."
        description="주소의 사전규격 번호가 올바르지 않습니다."
        action={{ label: "사전규격 목록", to: listUrl }}
      />
    );
  }

  if (noticeQuery.isPending) {
    return <PreSpecDetailSkeleton noticeId={noticeId} />;
  }

  if (noticeQuery.isError) {
    const problem = describeApiError(noticeQuery.error, "선택한 사전규격의 상세 정보를 확인할 수 없습니다.");
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
        title="사전규격을 확인할 수 없습니다."
        description="요청한 번호와 같은 사전규격이 아닙니다. 다른 공고로 이동하지 않았습니다."
        action={{ label: "사전규격 목록", to: listUrl }}
      />
    );
  }

  const deadline = describeDeadline(notice.deadline_at);
  const preSpecItem = preSpecProjectionQuery.data?.items.find((item) => item.notice_pk === noticeId);
  const lifecycle = readPreSpecLifecycle(notice.lifecycle);
  const procurementClass = readProcurementClass(notice.procurement_class);
  const rawNumber = preSpecItem?.pre_spec_no ?? lifecycle.pre_spec_no;
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
  const {
    query: pageOverviewQuery,
    isValid: pageOverviewValid,
    current: currentPageOverview,
    currentResult,
    legacyReview,
    history: pageOverviewHistory,
    rangeReview,
    verification: pageOverviewVerification,
  } = pageOverviewState;
  const shown = pageOverviewValid ? currentResult ?? legacyReview : null;
  const currentPageOverviewForView = pageOverviewValid ? currentPageOverview : null;
  // 범위 확인은 실행이 아직 없을 때도 나타난다. 확정은 새 실행 하나를 예약한다.
  const rangeReviewForView = pageOverviewValid ? rangeReview : null;
  const { query: companyFitQuery } = companyFitState;
  const companyFitData = companyFitState.isValid ? companyFitState.data : null;
  const currentCompanyFitAttempt = companyFitState.isValid ? companyFitState.currentAttempt : null;
  const previousCompanyFitAttempts = companyFitState.isValid ? companyFitState.previousAttempts : [];
  const pageOverviewUnknowns = shown?.payload.unknowns ?? [];
  const companyFitVerificationItems = currentCompanyFitAttempt?.result?.verification_items ?? [];
  const checkCount = pageOverviewUnknowns.length + companyFitVerificationItems.length;
  const historyIsOpen = currentPageOverview?.status === "failed"
    || currentPageOverview?.status === "needs_human_review"
    || currentPageOverview?.status === "cancelled"
    || currentCompanyFitAttempt?.status === "failed"
    || currentCompanyFitAttempt?.status === "needs_human_review"
    || latestBundle?.status === "failed"
    || latestBundle?.status === "quarantined"
    || latestBundle?.status === "needs_review"
    || pageOverviewVerification?.status === "needs_human_review";
  const trackingStatusLabel = preSpecItem?.opportunity_id == null
    ? "사업기회 미연결"
    : preSpecItem.tracking_status === "계속 추적"
      ? "추적 중"
      : preSpecItem.tracking_status === "종료"
        ? "추적 종료"
        : preSpecItem.tracking_status ?? "미확인";
  const companyFitDecision = currentCompanyFitAttempt?.result?.decision ?? "unknown";
  // 기본값은 들어올 때 한 번만 정한다. 사람이 패널 안에서 작업하는 동안 묶음이
  // `ready`로 바뀌었다고 해서 화면이 스스로 접으면, 방금 한 조작의 결과가 사라진다.
  // 닫는 것은 사람의 명시적인 조작이거나 다른 건을 열었을 때뿐이다.
  // 묶음 응답이 도착한 뒤 첫 판단을 한 번 잠근다. 응답 전에는 묶음 없음과
  // 구분할 근거가 없으므로 확정하지 않는다.
  if (documentPanelInitialRef.current === null && !bundleQuery.isPending) {
    documentPanelInitialRef.current = documentPanelDefaultOpen(latestBundle, autoStatus);
  }
  const documentPanelOpen = documentPanelOverride
    ?? documentPanelInitialRef.current
    ?? documentPanelDefaultOpen(latestBundle, autoStatus);
  const verificationReasonCount = pageOverviewVerification
    ? pageOverviewVerification.reason_codes.length
      + pageOverviewVerification.claims.reduce((total, claim) => total + claim.reason_codes.length, 0)
    : 0;

  return (
    <section className="pre-spec-detail-page detail-skeleton ps-record" data-astryx-theme="bidops" aria-labelledby="pre-spec-detail-title">
      {/* 자체 브레드크럼은 두지 않는다. 상단 경로(`nav[aria-label="현재 위치"]`)가
          `탐색과 추적 › 사전규격 › notice ID`를 이미 그리고, 사전규격 칸이 목록
          링크다. 경로가 두 벌이면 현재 위치를 두 번 읽어야 한다. */}
      <header className="pre-spec-detail-header detail-skeleton-head ps-card" aria-label="사전규격 상세 정보">
        <div className="ps-record-header-top">
          <div className="ps-record-header-main">
            <div className="ps-record-chips">
              <span className="ps-chip ps-chip-neutral">사전규격 · {preSpecItem?.origin ?? "미확인"}</span>
              <span className={`ps-chip ps-chip-${deadlineChipVariant(deadline.urgency)}`}>{deadline.label}</span>
              <span className="ps-chip ps-chip-accent">SW사업대상 {preSpecItem?.sw_business_status ?? "미확인"}</span>
              <span className="ps-chip ps-chip-neutral">본공고 {lifecycle.bid_ntice_no_list ?? "미확인"}</span>
              {preSpecItem?.business_division ? <span className="ps-chip ps-chip-accent">{preSpecItem.business_division}</span> : null}
            </div>
            <h2 id="pre-spec-detail-title" className="ps-h-page">{present(notice.title, "사업명 미확인")}</h2>
            <div className="ps-record-meta">
              <span className="ps-record-agency">{present(notice.agency, "발주기관 미확인")}</span>
              <span aria-hidden="true">·</span>
              <PreSpecRecordIdentity key={noticeId} number={preSpecNumber} url={notice.url} />
              {procurementClass.detail || procurementClass.code ? (
                <>
                  <span aria-hidden="true">·</span>
                  <span className="ps-record-classification">
                    품명 분류 · {procurementClass.detail ?? procurementClass.code}
                  </span>
                </>
              ) : null}
            </div>
          </div>
          <div className="ps-record-header-actions">
            <span className="ps-chip ps-chip-neutral">
              <span aria-hidden="true">추적 결정 ·</span>
              <span aria-label="현재 추적 상태">{trackingStatusLabel}</span>
            </span>
            <Link className="ps-ref ps-ref-plain ps-record-list-link" to={listUrl}>목록으로 돌아가기</Link>
          </div>
        </div>
        {shown?.payload.business_overview[0] ? <>
          <div className="ps-divider" aria-hidden="true" />
          <div className="ps-record-summary">
            <span className="ps-chip ps-chip-dark">사업 개요</span>
            <p><PageOverviewFactLine fact={shown.payload.business_overview[0]} review={shown} /></p>
          </div>
        </> : null}
      </header>

      <aside className="ps-card ps-record-tracking-card" aria-label="추적 결정">
        <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}>
          <TrackingDecisionControl
            key={noticeId}
            compact
            presentation="record"
            showRecordHeading={false}
            showIntent={false}
            noticeNumber={preSpecNumber}
            reasonPresets={TRACKING_REASON_PRESETS}
            headingLevel="h3"
            item={preSpecItem}
            isPending={preSpecProjectionQuery.isPending}
            isError={preSpecProjectionQuery.isError}
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
              void queryClient.invalidateQueries({ queryKey: ["pre-spec-detail", noticeId] });
              void queryClient.invalidateQueries({ queryKey: ["pre-specs"] });
              void queryClient.invalidateQueries({ queryKey: ["opportunity", saved.id] });
            }}
          />
        </InternationalizationProvider>
        <footer className="ps-record-tracking-footer">
          <p className="ps-record-tracking-help">추적을 시작하면 새 문서·입찰공고·정정공고를 계속 확인합니다.</p>
          <p className="ps-record-decision-note">입찰 참여 여부는 최종 Go/No-Go에서 결정합니다.</p>
        </footer>
      </aside>

      <dl className="ps-card ps-facts ps-record-facts">
        <div className="ps-fact"><dt className="ps-k">사업 예산</dt><dd className="ps-v">{notice.budget === null ? "예산 미확인" : `${formatNumber(notice.budget)}원`}</dd><span className="ps-s" /></div>
        <div className="ps-fact"><dt className="ps-k">의견등록 마감</dt><dd className="ps-v">{recordDateTime(notice.deadline_at)}</dd><span className="ps-s" /></div>
        <div className="ps-fact"><dt className="ps-k">게시</dt><dd className="ps-v">{recordDateTime(notice.published_at)}</dd><span className="ps-s" /></div>
        <div className="ps-fact">
          <dt className="ps-k">구분</dt>
          <dd className="ps-v">{preSpecItem?.business_division ?? "미확인"}</dd>
          <span className="ps-s">SW사업대상 {preSpecItem?.sw_business_status ?? "미확인"}</span>
        </div>
        <div className="ps-fact">
          <dt className="ps-k">적합성 등급</dt>
          <dd className="pre-spec-detail-grade-row">
            <span className="ps-v">
              {preSpecProjectionQuery.isPending ? (
                <span className="pre-spec-detail-grade-source">등급을 불러오는 중입니다.</span>
              ) : !preSpecItem || preSpecProjectionQuery.isError ? (
                <span className="pre-spec-detail-grade-source">등급 미확인</span>
              ) : (
                <Badge label={gradeLabel(preSpecItem.grade)} variant={gradeVariant(preSpecItem.grade)} />
              )}
            </span>
            {preSpecItem && !preSpecProjectionQuery.isError ? <span className="ps-s">등급 출처 · {gradeSourceLabel(preSpecItem.grade_source)}</span> : null}
          </dd>
        </div>
        <div className="ps-fact"><dt className="ps-k">첨부 원문</dt><dd className="ps-v ps-record-secondary-facts">{notice.attachment_count}건</dd><span className="ps-s" /></div>
      </dl>

      <div className="ps-grid detail-skeleton-grid">
        <div className="ps-col detail-skeleton-main">
          <RecordSection
            title="무엇을 만들어야 하나"
            count={shown ? `주요 과업 ${shown.payload.main_tasks.length}` : undefined}
            action={shown ? <OverviewPdfReference review={shown} /> : undefined}
          >
            {pageOverviewQuery.isPending ? (
              <p role="status">PDF 기반 개요를 불러오는 중입니다.</p>
            ) : pageOverviewQuery.isError ? (
              <div role="alert" className="page-overview-validation">
                <p>PDF 기반 개요를 불러오지 못했습니다. 아래 기존 개요 기록과는 별도 조회입니다.</p>
                <Button label="개요 다시 불러오기" size="sm" onClick={() => { void pageOverviewQuery.refetch(); }} />
              </div>
            ) : !pageOverviewValid ? (
              <p role="alert">개요 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.</p>
            ) : shown ? (
              <section className="page-overview" aria-label="PDF 기반 개요 검토">
                <PageOverviewBriefing review={shown} />
              </section>
            ) : null}
          </RecordSection>

          {/* 개요가 읽어 낸 핵심 조건이다. 조건이 없으면 카드를 만들지 않는다. */}
          {shown && shown.payload.important_conditions.length > 0 ? (
            <RecordSection title="지켜야 할 조건" count={String(shown.payload.important_conditions.length)}>
              <FactBullets items={shown.payload.important_conditions} review={shown} />
            </RecordSection>
          ) : null}

          <PreSpecBriefingSection judgment={notice.judgment} reviews={notice.reviews} />

          <RecordSection
            title="첨부 문서·근거"
            count={`${notice.attachments.length}건`}
            action={shown ? <OverviewPdfReference review={shown} /> : undefined}
          >
            <PreSpecAttachmentList attachments={notice.attachments} />
          </RecordSection>

          <section id="ps-record-range" className="ps-record-section ps-record-range" tabIndex={-1} aria-label="개요 입력 범위 확정">
            {rangeReviewForView ? (
              <PageOverviewRangeReview
                noticeId={noticeId}
                review={rangeReviewForView}
                onConfirmed={() => { void pageOverviewQuery.refetch(); }}
              />
            ) : null}
          </section>

          <div id="ps-record-documents" className="ps-record-section ps-record-documents" tabIndex={-1}>
            <Panel title="문서 준비와 심층 검토 실행">
              <div className="pre-spec-auto-preparation" aria-label="자동 준비 진행">
                <ol className="pre-spec-auto-steps ps-steps">
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
                    detail={latestBundle ? `수정본 ${latestBundle.revision}` : undefined}
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

              <div className="ps-document-panel-summary">
                <p className="ps-document-panel-summary-line">
                  {bundleQuery.isPending
                    ? "묶음 확인 중"
                    : bundleQuery.isError
                      ? "묶음 확인 실패"
                      : latestBundle
                        ? `묶음 ${BUNDLE_STATUS_LABELS[latestBundle.status]}`
                        : "묶음 없음"}
                  {" · 문서 "}{latestBundle ? latestBundle.documents.length : 0}건
                  {" · 차단 issue "}{latestBundle ? latestBundle.issues.filter((issue) => issue.blocking).length : 0}건
                  {autoStatus ? ` · ${PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL[autoStatus]}` : ""}
                </p>
                <Button
                  label={documentPanelOpen ? "문서 준비 닫기" : "문서 준비 열기"}
                  size="sm"
                  variant="ghost"
                  aria-expanded={documentPanelOpen}
                  onClick={() => setDocumentPanelOverride(!documentPanelOpen)}
                />
              </div>
              {/* Astryx `Collapsible`은 `display:none`으로 감춰 조작을 막는다.
                  여기는 조건부 렌더링이므로 열린 동안은 패널이 온전히 살아 있다. */}
              {documentPanelOpen ? (
                <DocumentPreparationPanel
                  noticeId={notice.id}
                  // 헤더가 보여 주는 것과 **같은 현재 등급**을 넘긴다. `notice.grade`는
                  // 사람 정정을 반영하지 않아 헤더와 다른 값을 말할 수 있다(명세 §6.2).
                  currentGrade={preSpecItem?.grade ?? null}
                  onDeepReviewCreated={(review) => navigate(`/deep-reviews/${review.id}`)}
                />
              ) : null}
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
            </Panel>
          </div>

          <div id="ps-record-history" className="ps-record-section ps-record-history ps-collapsed" tabIndex={-1}>
            <Collapsible key={historyIsOpen ? "history-open" : "history-closed"} trigger="처리 이력과 실행 정보" defaultIsOpen={historyIsOpen}>
              <ReviewHistoryLinkRail
                className="detail-skeleton-rail"
                historySections={[{
                  className: "detail-skeleton-rail-panel",
                  content: <p className="detail-skeleton-rail-note">개요 입력 범위와 현재 실행은 오른쪽 "현재 판단" 자리에서 봅니다.</p>,
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
              {lifecycle.changed_at || lifecycle.change_reason ? (
                <section className="ps-record-lifecycle-change" aria-label="사전규격 변경">
                  <h3 className="ps-sub">변경</h3>
                  <p>
                    {lifecycle.changed_at ? `변경 일시 · ${recordDateTime(lifecycle.changed_at)}` : "변경 일시 · 미확인"}
                    {" · "}
                    {lifecycle.change_reason ? `변경 사유 · ${lifecycle.change_reason}` : "변경 사유 · 미확인"}
                  </p>
                </section>
              ) : null}
              <PageOverviewHistory reviews={pageOverviewValid ? pageOverviewHistory : []} />
              {currentPageOverviewForView?.attempt_id && pageOverviewVerification ? (
                <PageOverviewVerificationDetails
                  noticeId={noticeId}
                  attemptId={currentPageOverviewForView.attempt_id}
                  verification={pageOverviewVerification}
                />
              ) : null}
              {shown ? <PageOverviewExecutionInfo review={shown} /> : null}
            </Collapsible>
          </div>
        </div>

        <div className="ps-col ps-record-aside ps-record-side">
          <RecordSection title="현재 판단" action={<span className="ps-cap ps-dim">모델 참조 결과 · 사람이 확정</span>}>
            <div className="ps-verdict">
              {companyFitState.isValid && companyFitData !== null && currentCompanyFitAttempt ? (
                <div className={`ps-vbox is-${companyFitDecision}`}>
                  <span className="ps-k">회사 핏</span>
                  <CompanyFitVerdict attempt={currentCompanyFitAttempt} />
                </div>
              ) : null}
            </div>

            {rangeReviewForView?.selection_status === "needs_human_review" ? (
              <p className="ps-note ps-range-review-notice">
                <strong>개요 입력 범위 확정 필요</strong>
                <a href="#ps-record-range">확정하기 →</a>
              </p>
            ) : null}
            {currentPageOverviewForView ? (
              <div className="ps-note ps-judgment-note">
                <PageOverviewCurrent current={currentPageOverviewForView} currentResult={currentResult} />
              </div>
            ) : null}
            {currentPageOverviewForView?.status === "needs_human_review" || pageOverviewVerification?.status === "needs_human_review" ? (
              <p className="ps-note ps-verification-notice">
                <strong>사람 확인 필요 · 사유 {verificationReasonCount}건</strong>
                <a href="#ps-record-history">→ 보기</a>
              </p>
            ) : null}
          </RecordSection>

          <RecordSection title="확인이 필요한 것" count={String(checkCount)}>
            {checkCount === 0 ? <p className="pre-spec-overview-empty">추가 조건·미확인 항목 없음</p> : (
              <div className="ps-check-groups">
                {shown && pageOverviewUnknowns.length > 0 ? (
                  <section className="ps-check-group">
                    <h4 className="ps-sub">PDF 개요</h4>
                    <ul className="ps-check ps-record-check-list">
                      {pageOverviewUnknowns.map((item, index) => <li key={`${item}-${index}`}>
                        <span className="ps-box" aria-hidden="true" />
                        <span className="ps-t ps-record-check-detail">{item}</span>
                      </li>)}
                    </ul>
                  </section>
                ) : null}
                {currentCompanyFitAttempt && companyFitVerificationItems.length > 0 ? (
                  <section className="ps-check-group">
                    <h4 className="ps-sub">회사 핏</h4>
                    <ul className="ps-check ps-record-check-list">
                      {companyFitVerificationItems.map((item, index) => <li key={`${item}-${index}`}>
                        <span className="ps-box" aria-hidden="true" />
                        <span className="ps-t ps-record-check-detail">{item}</span>
                      </li>)}
                    </ul>
                  </section>
                ) : null}
              </div>
            )}
          </RecordSection>

          {/* 자동 판정이 비활성이고 저장된 판정도 없으면 카드 하나를 사우지 않고
              한 줄로 남긴다. 판정 없음은 불일치가 아니므로 의미색도 쓰지 않는다. */}
          {companyFitState.isValid && companyFitData !== null && !companyFitQuery.isError
            && !companyFitData.automation_enabled && !currentCompanyFitAttempt ? (
            <section className="company-fit ps-card ps-sec is-compact" aria-label="회사 업무 부합 여부">
              <p>{NO_CURRENT_ATTEMPT_NOTICE} · 자동 판정 비활성</p>
            </section>
          ) : (
          <section className="company-fit ps-card ps-sec" aria-label="회사 업무 부합 여부">
            <div className="ps-sec-head"><h3 className="ps-h-sec">회사 업무 부합 여부</h3></div>
            <p className="company-fit-note">개요의 과업과 회사 정보를 대조한 분석입니다. 추적 승인과 최종 입찰 결정은 사람이 진행합니다.</p>
            {companyFitQuery.isPending ? <p role="status">회사 핏 판정을 불러오는 중입니다.</p> : companyFitQuery.isError ? <div role="alert">
              <p>회사 핏 판정을 불러오지 못했습니다.</p>
              <Button label="회사 핏 다시 불러오기" size="sm" onClick={() => { void companyFitQuery.refetch(); }} />
            </div> : !companyFitState.isValid || companyFitData === null ?
              <p role="alert">판정 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.</p> : <>
                {/* 사유·근거와 실행 정보는 접힌 자리에 함께 둔다. 판정 카드 본문에는
                    판정 라벨·요약·품질 표식만 남는다. */}
                {currentCompanyFitAttempt ? <details className="company-fit-reasons-details">
                  <summary>{currentCompanyFitAttempt.result ? `판단 사유 ${currentCompanyFitAttempt.result.reasons.length}개와 근거 보기` : "판정 근거와 실행 정보 보기"}</summary>
                  <CompanyFitReasons attempt={currentCompanyFitAttempt} />
                  <CompanyFitExecutionInfo attempt={currentCompanyFitAttempt} />
                </details> : <p>{NO_CURRENT_ATTEMPT_NOTICE}</p>}
                <CompanyFitAutomationNotice data={companyFitData} />
                {previousCompanyFitAttempts.length > 0 ? <details>
                  <summary>이전 판정 {previousCompanyFitAttempts.length}건</summary>
                  {previousCompanyFitAttempts.map((attempt) => <div className="company-fit-assessment" key={attempt.id}>
                    <CompanyFitVerdict attempt={attempt} />
                    <CompanyFitReasons attempt={attempt} />
                    <CompanyFitExecutionInfo attempt={attempt} />
                  </div>)}
                </details> : null}
              </>}
          </section>
          )}
        </div>
      </div>
    </section>
  );
}
