import { Button } from "@astryxdesign/core/Button";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { BUNDLE_STATUS_LABELS, DocumentPreparationPanel } from "../components/deep-review/DocumentPreparationPanel";
import { getDeepReview, getDocumentBundles, getReport } from "../components/deep-review/api";
import type { ReportSection } from "../components/deep-review/types";
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
  PageOverviewExecutionInfo,
  PageOverviewFactLine,
  PageOverviewHistory,
  PageOverviewNotices,
  PageOverviewRangeReview,
  PageOverviewVerificationDetails,
  pageOverviewPdfUrl,
  useCurrentPageOverview,
  type PageOverviewRisk,
} from "../components/pre-specs/PageOverviewSection";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { apiErrorRecoveryAction, describeApiError } from "../lib/apiErrors";
import { describeDeadline } from "../lib/deadline";
import { formatNumber, present } from "../lib/format";
import { gradeLabel, gradeSourceLabel, gradeVariant } from "../lib/grade";
import { preSpecCautions } from "../lib/preSpecCautions";
import { qualityStatusLabel, qualityStatusVariant } from "../lib/qualityStatus";
import {
  PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL,
  preSpecAutoPreparationReasonLabel,
  preSpecAutoPreparationVariant,
} from "../lib/preSpecAutoPreparation";
import {
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
  PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION,
  preSpecOverviewStatusVariant,
} from "../lib/preSpecOverviewStatus";
import {
  preSpecDetailUrl,
  preSpecReviewListUrl,
  readPreSpecSelectionReview,
} from "../lib/preSpecSelectionReview";
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

function OverviewPdfReference({ review }: { review: PageOverviewView }) {
  return <a className="ps-ref" href={pageOverviewPdfUrl(review)} target="_blank" rel="noreferrer">전체 근거 PDF 열기 ↗</a>;
}

/**
 * ④ `참여 조건` 열이 심층 검토 보고서의 `eligibility_matrix` 절에서 읽는 항목.
 * 개요는 앞부분 요약만 맡으므로(ADR-0057 결정 1) 참여 조건은 심층 검토 결과가
 * 있을 때만 그 결과에서 읽는다 — 새 분석·문장 생성은 하지 않고 이미 받은 절의
 * 표 행·본문만 고른다.
 */
function reportSectionBullets(section: ReportSection | undefined): string[] {
  if (!section) return [];
  return section.blocks.flatMap((block) => {
    if (block.rows.length > 0) return block.rows.map((row) => `${row.label} · ${row.cells.join(" · ")}`);
    return block.body ? [block.body] : [];
  });
}

/**
 * 상세 화면이 기다리는 것을 자리로 먼저 보여 준다. 쿼리마다 다른 문장이 뜨고
 * 사라지며 레이아웃이 흔들리던 자리를 헤더·사실·개요 세 자리로 고정한다.
 */
function PreSpecDetailSkeleton({ noticeId }: { noticeId: number }) {
  return (
    <div className="detail-skeleton-main">
      <SkeletonPanel label={`사전규격 ${noticeId} 상세를 불러오는 중`} lines={3} />
      <SkeletonPanel label="추적 결정 정보를 불러오는 중" lines={6} />
      <SkeletonPanel label="사전규격 사실을 불러오는 중" lines={4} />
      <SkeletonPanel label="개요 검토 상태를 불러오는 중" lines={5} />
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

/**
 * 선택 검토 context를 읽는 유일한 상세 순회 표면이다. 현재 목록 응답이나
 * 주소의 다른 query를 다시 정렬에 사용하지 않고, 저장된 snapshot의 인접 ID만
 * 이동 대상으로 삼는다. token이 없거나 깨진 경우에는 명시적으로 단건 모드다.
 */
function PreSpecDetailNavigation({ noticeId, search }: { noticeId: number | null; search: string }) {
  const navigate = useNavigate();
  const review = readPreSpecSelectionReview(search, noticeId);
  const index = review ? review.orderedNoticeIds.indexOf(noticeId as number) : -1;
  const hasReview = review !== null && index >= 0;
  const previousId = hasReview && index > 0 ? review.orderedNoticeIds[index - 1] : null;
  const nextId = hasReview && index < review.orderedNoticeIds.length - 1
    ? review.orderedNoticeIds[index + 1]
    : null;
  const moveTo = (nextNoticeId: number | null) => {
    if (!review || nextNoticeId === null) return;
    // 저장된 목록 query와 review token을 그대로 사용한다. 현재 상세 route의
    // index나 이후 query 변경으로 snapshot 순서를 재계산하지 않는다.
    navigate(preSpecDetailUrl(nextNoticeId, review.listSearch, review.reviewId));
  };

  return (
    <nav className="ps-detail-navigation" aria-label="사전규격 선택 순회">
      <div className="ps-detail-navigation-position">
        <span className="ps-k">선택 항목</span>
        <strong aria-live="polite">{hasReview ? `${index + 1} / ${review.orderedNoticeIds.length}` : "단건 상세"}</strong>
      </div>
      <div className="ps-detail-navigation-actions">
        <button
          className="ps-btn ps-btn-sm"
          type="button"
          aria-label="이전 선택 사전규격"
          disabled={previousId === null}
          onClick={() => moveTo(previousId)}
        >
          이전
        </button>
        <button
          className="ps-btn ps-btn-sm"
          type="button"
          aria-label="다음 선택 사전규격"
          disabled={nextId === null}
          onClick={() => moveTo(nextId)}
        >
          다음
        </button>
      </div>
    </nav>
  );
}

function PreSpecDetailFrame({
  noticeId,
  search,
  children,
}: {
  noticeId: number | null;
  search: string;
  children: ReactNode;
}) {
  return (
    <section
      className="pre-spec-detail-page detail-skeleton ps-record"
      data-astryx-theme="bidops"
      aria-label="사전규격 상세"
    >
      {/* 순회 컨트롤은 본문 맨 위 카드가 아니라 상단바 액션 슬롯이 갖는다
          (docs/0915_ui-redesign/spec.md §4 상단바). 조회 성공 여부와 무관하게
          그려야 하므로 본문이 아니라 이 틀이 portal한다. */}
      <PageHeaderActions>
        <PreSpecDetailNavigation noticeId={noticeId} search={search} />
      </PageHeaderActions>
      {children}
    </section>
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
  index: number;
  name: string;
  /** 이 단계가 끝났는가. 시안의 완료 카드(테두리·번호 강조)를 정한다(spec §4 ⑥). */
  done: boolean;
  value: string;
  variant: BadgeVariant;
  detail?: ReactNode;
}

function AutoPreparationStep({ index, name, done, value, variant, detail }: AutoPreparationStepProps) {
  return (
    <li className={`pre-spec-auto-step ps-step${done ? " is-done" : ""}`}>
      <span className="pre-spec-auto-step-label ps-k">
        <span className="ps-step-no">{index}</span>
        {/* 단계 이름은 종전과 같은 `n · 이름` 한 문장으로 남는다. 가운뎃점만 시안의
            번호 동그라미 배치를 위해 화면에서 감춘다 — 읽는 글자는 바뀌지 않는다. */}
        <span className="ps-step-sep">{" · "}</span>
        <span className="ps-step-name">{name}</span>
      </span>
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

/**
 * ③ 카드 본문(spec §4 ③, ADR-0057 결정 1). 사업 개요 → 주요 과업 → 예산·기간
 * (`사업 규모와 일정` 타일) 세 섹션만 읽는다. 검증 라벨 칩·품질 표식·근거 PDF
 * 링크는 카드 머리가 갖는다. 참여 조건·회사 적합성·위험 및 미확인 사항은
 * 심층 검토 영역이 소유한다.
 */
function PageOverviewBriefing({ review }: { review: PageOverviewView }) {
  const { payload } = review;
  const remainingOverview = payload.business_overview.slice(1);
  return <div className="page-overview">
    {/* 헤더 띠가 첫 문장을 이미 보여 준다. 개요 본문 영역이 같은 문장을 계약대로
        담고 있어야 하므로 자리만 유지하고 화면에서는 감춘다. */}
    {payload.business_overview[0] ? (
      <p className="visually-hidden" aria-hidden="true"><PageOverviewFactLine fact={payload.business_overview[0]} review={review} anchor={false} /></p>
    ) : null}
    <div className="page-overview-validation" role="status">
      <p>사업 설명을 위한 요약입니다. 추적 승인과 최종 입찰 결정은 사람이 진행하며, 현재 회사 적합성과 조건을 충족한 경우에만 심층 검토가 자동 시작됩니다.</p>
      {review.validation_status === "failed" && review.evidence_check_status === "passed" ? (
        <p>새 페이지 근거 검사는 통과했으나, 원실행의 검증 실패 기록은 유지합니다.</p>
      ) : null}
    </div>
    {remainingOverview.length > 0 ? <>
      <h4 className="ps-sub">사업 개요</h4>
      <FactBullets items={remainingOverview} review={review} />
    </> : null}
    {payload.main_tasks.length === 0 ? <p className="ps-cap ps-muted">이번 입력 범위에는 없음</p> : (
      <ol className="ps-bul ps-tasks">
        {payload.main_tasks.map((fact, index) => (
          <li key={index}>
            <span className="ps-n" aria-hidden="true">{index + 1}</span>
            <span className="ps-t"><PageOverviewFactLine fact={fact} review={review} /></span>
          </li>
        ))}
      </ol>
    )}
    <h4 className="ps-sub">사업 규모와 일정</h4>
    {payload.budget_and_period.length === 0 ? <p className="ps-cap ps-muted">이번 입력 범위에는 없음</p> : (
      <ul className="ps-tiles">
        {payload.budget_and_period.map((fact, index) => (
          <li key={index} className="ps-tile">
            <span className="ps-t"><PageOverviewFactLine fact={fact} review={review} /></span>
          </li>
        ))}
      </ul>
    )}
  </div>;
}

function PreSpecRecordBody({ noticeId, listSearch }: { noticeId: number | null; listSearch: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const listUrl = preSpecReviewListUrl(listSearch, noticeId);

  const noticeQuery = useQuery({
    queryKey: ["pre-spec-notice", noticeId],
    queryFn: ({ signal }) => api.getNotice(noticeId as number, { signal }),
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
  // 참여 조건·위험 및 미확인 사항은 심층 검토 결과가 있을 때만 그 결과에서 읽는다
  // (ADR-0057 결정 1·4). 목록 projection이 최신 심층 검토 id를 이미 주므로 그
  // id로만 조회하고, 완료 전에는 보고서를 요청하지 않는다.
  const earlyDeepReviewId = preSpecProjectionQuery.data?.items.find((item) => item.notice_pk === noticeId)?.latest_deep_review_id ?? null;
  const deepReviewStatusQuery = useQuery({
    queryKey: ["deep-review", earlyDeepReviewId],
    queryFn: () => getDeepReview(earlyDeepReviewId as string),
    enabled: earlyDeepReviewId !== null,
    staleTime: 30_000,
  });
  const deepReviewReportQuery = useQuery({
    queryKey: ["deep-review-report", earlyDeepReviewId],
    queryFn: () => getReport(earlyDeepReviewId as string),
    enabled: earlyDeepReviewId !== null && deepReviewStatusQuery.data?.status === "completed",
    staleTime: 30_000,
  });
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

  // 참여 조건·위험 및 미확인 사항은 개요가 아니라 심층 검토 보고서에서 읽는다
  // (ADR-0057 결정 1). 보고서가 없으면(심층 검토 미시작 또는 미완료) 각 열이
  // "심층 검토에서 확인" 한 줄만 보인다.
  const deepReviewReport = deepReviewReportQuery.data?.report ?? null;
  const hasDeepReviewReport = deepReviewReport !== null;
  const deepReviewUnknowns = deepReviewReport?.unknowns ?? [];
  const eligibilityItems = reportSectionBullets(
    deepReviewReport?.sections.find((section) => section.section_key === "eligibility_matrix"),
  );
  const risks: PageOverviewRisk[] = deepReviewUnknowns.map((text) => ({
    label: "미확인",
    tone: "neutral",
    title: text,
    detail: null,
  }));
  const judgment = notice.judgment;
  const judgmentRiskCount = (judgment?.counterarguments.length ?? 0) + (judgment?.verification_items.length ?? 0);
  const cautionCounts = preSpecItem
    ? preSpecCautions({ item: preSpecItem, verification: pageOverviewVerification, unknowns: pageOverviewUnknowns })
    : null;
  // v4 주장만 원문 위치를 갖는다. 이전 세대 결과는 claim id가 없으므로 ⑤의 주장별
  // 목록을 만들지 않는다 — 없는 식별자를 지어내지 않는다(spec §4 ⑤). 참여 조건은
  // 더 이상 개요 결과에 없으므로(ADR-0057) 세 섹션만 모은다.
  const evidenceClaims = shown
    ? [...shown.payload.business_overview, ...shown.payload.main_tasks, ...shown.payload.budget_and_period]
      .filter((fact): fact is Extract<PageOverviewFact, { claim_id: string }> => "claim_id" in fact)
    : [];
  const overviewValidationLabel = shown
    ? shown.validation_status === "failed"
      ? "검증 실패 · 사람 확인 필요"
      : shown.payload.schema_version === "bidops.prespec-overview-page-review.v4"
        ? "주장 검증 완료 · 운영 승인 아님"
        : "근거 검사 통과 · 이전 검증 기준"
    : null;
  const stepDone = {
    attachments: Boolean(documentCounts && documentCounts.attachments > 0
      && documentCounts["대기"] === 0 && documentCounts["진행"] === 0
      && documentCounts["차단"] === 0 && documentCounts["실패"] === 0),
    bundle: latestBundle?.status === "ready",
    overview: preSpecItem?.overview_review_status === "completed",
    deepReview: autoStatus === "deep_review_started",
  };

  return (
    <Fragment>
      {/* 자체 브레드크럼은 두지 않는다. 상단 경로(`nav[aria-label="현재 위치"]`)가
          `탐색과 추적 › 사전규격 › notice ID`를 이미 그리고, 사전규격 칸이 목록
          링크다. 경로가 두 벌이면 현재 위치를 두 번 읽어야 한다. */}
      {/* ① 사업명·기관·요약·예산·일정 (spec §4 ①) */}
      <header id="ps-summary" className="pre-spec-detail-header detail-skeleton-head ps-card" aria-label="사전규격 상세 정보">
        <div className="ps-record-header-body">
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
              {/* 현재 추적 상태 글자는 화면에 한 번만 둔다(spec §4). 이 칩은 결정의
                  현재 값을 읽는 자리고, 상태 이름을 다시 말하는 블록은 ② 카드가 갖는다. */}
              <span className="ps-chip ps-chip-neutral">추적 결정 · {trackingStatusLabel}</span>
              <Link className="ps-ref ps-ref-plain ps-record-list-link" to={listUrl}>목록으로 돌아가기</Link>
            </div>
          </div>
          {shown?.payload.business_overview[0] ? (
            <div className="ps-record-summary">
              <span className="ps-chip ps-chip-accent">사업 요약</span>
              <p><PageOverviewFactLine fact={shown.payload.business_overview[0]} review={shown} /></p>
            </div>
          ) : null}
        </div>

        <dl className="ps-facts ps-record-facts">
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
      </header>

      {/* ② 추적 결정 (spec §4 ②) */}
      <aside id="ps-tracking" className="ps-card ps-record-tracking-card" aria-label="추적 결정">
        <div className="ps-record-tracking-head">
          <h2 className="ps-h-sec">추적 결정</h2>
          <span className="ps-cap ps-dim">보류·추적 종료는 사업 추적에서 변경</span>
        </div>
        <div className="ps-record-tracking-body">
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
        </div>
      </aside>

      {/* ③ 주요 과업과 수행 범위 (spec §4 ③) */}
      <section id="ps-tasks" className="ps-card ps-sec ps-record-tasks" aria-labelledby="ps-tasks-title">
        <div className="ps-sec-head">
          <h2 id="ps-tasks-title" className="ps-h-sec">주요 과업과 수행 범위{shown ? <> <span className="ps-cnt">{shown.payload.main_tasks.length}건</span></> : null}</h2>
          <div className="ps-sec-actions">
            {overviewValidationLabel ? <span className="ps-chip ps-chip-accent">{overviewValidationLabel}</span> : null}
            {shown ? <Badge label={qualityStatusLabel(shown.quality_status)} variant={qualityStatusVariant(shown.quality_status)} /> : null}
            {shown ? <OverviewPdfReference review={shown} /> : null}
          </div>
        </div>
        {/* 종전 오른쪽 `현재 판단` 열의 알림 두 줄이 여기로 온다(spec §4 ③). */}
        <PageOverviewNotices
          rangeReview={rangeReviewForView}
          current={currentPageOverviewForView}
          verification={pageOverviewVerification}
          verificationReasonCount={verificationReasonCount}
        />
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
        ) : (
          /* 검증된 결과가 없으면 그 상태가 무엇을 기다리는지 한 줄로 남긴다. 문장은
             `preSpecOverviewStatus`가 소유하며 화면이 다시 적지 않는다. */
          <div className="pre-spec-overview-waiting">
            <strong>{overviewStatusForStep ?? "개요 검토 상태 미확인"}</strong>
            <p>{preSpecItem?.overview_review_status
              ? PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION[preSpecItem.overview_review_status]
              : "개요 검토 실행 기록이 없어 주요 과업을 표시할 수 없습니다."}</p>
          </div>
        )}
      </section>

      {/* ⑤ 근거 문서 · 첨부 (spec §4 ⑤). 목록 우측 영역의 `근거 보기 →`가 이 자리로 온다. */}
      <section id="ps-evidence" tabIndex={-1} className="ps-card ps-sec ps-record-evidence" aria-labelledby="ps-evidence-title">
        <div className="ps-sec-head">
          <h2 id="ps-evidence-title" className="ps-h-sec">근거 문서 · 첨부</h2>
          <span className="ps-cap ps-dim">첨부 {notice.attachments.length}건 · 근거 항목 {evidenceClaims.length}건</span>
        </div>
        <PreSpecAttachmentList attachments={notice.attachments} />
        {shown ? (
          <div className="ps-evidence-claims">
            <div className="ps-sec-head">
              <span className="ps-cap ps-dim">문서 근거 · 개요 검토 결과의 주장별 원문 위치</span>
              <OverviewPdfReference review={shown} />
            </div>
            {evidenceClaims.length === 0 ? <p className="ps-cap ps-muted">이번 입력에서는 확인되지 않았습니다.</p> : (
              <ul className="ps-ev">
                {evidenceClaims.map((fact) => (
                  <li key={fact.claim_id}>
                    <span className="ps-loc"><code>{fact.claim_id}</code></span>
                    <span className="ps-t"><PageOverviewFactLine fact={fact} review={shown} anchor={false} /></span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
        <p className="ps-cap ps-dim">첨부 원문 열기는 검증된 절대 HTTP(S) 주소만 사용하며 나라장터 원문 URL을 대신하지 않습니다.</p>
      </section>

      {/* ⑥ 처리 이력 · 문서 준비 · 검토 실행 (spec §4 ⑥) */}
      <section id="ps-process" className="ps-card ps-sec ps-record-process" aria-labelledby="ps-process-title">
        <div className="ps-sec-head">
          <h2 id="ps-process-title" className="ps-h-sec">처리 이력 · 문서 준비 · 검토 실행</h2>
          <div className="ps-sec-actions">
            <Button
              label={documentPanelOpen ? "문서 준비 닫기" : "문서 준비 열기"}
              size="sm"
              variant="ghost"
              aria-expanded={documentPanelOpen}
              onClick={() => setDocumentPanelOverride(!documentPanelOpen)}
            />
            {/* 개요 재실행 단추는 그리지 않는다(intent 결정 3). 재실행은 문서 준비 패널 안에서만 연다. */}
            {autoDeepReviewId ? (
              <Link className="ps-btn ps-btn-sm" to={`/deep-reviews/${autoDeepReviewId}`}>심층 검토 보고서 열기 →</Link>
            ) : (
              <button className="ps-btn ps-btn-sm" type="button" disabled>시작 기록 없음</button>
            )}
          </div>
        </div>

        <div className="pre-spec-auto-preparation" aria-label="자동 준비 진행">
          <ol className="pre-spec-auto-steps ps-steps">
            <AutoPreparationStep
              index={1}
              name="첨부 취득"
              done={stepDone.attachments}
              value={documentCounts ? `${documentCounts.attachments}건` : "집계 없음"}
              variant={documentCounts && (documentCounts["차단"] > 0 || documentCounts["실패"] > 0) ? "alert" : "neutral"}
              detail={documentCounts
                ? `완료 ${documentCounts["완료"]} · 대기 ${documentCounts["대기"]} · 진행 ${documentCounts["진행"]} · 차단 ${documentCounts["차단"]} · 실패 ${documentCounts["실패"]}`
                : "사전규격 요약 정보가 없어 첨부 집계를 표시하지 않습니다."}
            />
            <AutoPreparationStep
              index={2}
              name="문서 묶음"
              done={stepDone.bundle}
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
              index={3}
              name="개요 검토"
              done={stepDone.overview}
              value={overviewStatusForStep ?? (preSpecProjectionQuery.isPending ? "확인 중" : "미확인")}
              variant={preSpecItem && preSpecItem.overview_review_status !== null
                ? preSpecOverviewStatusVariant(preSpecItem.overview_review_status)
                : "neutral"}
            />
            <AutoPreparationStep
              index={4}
              name="심층 검토"
              done={stepDone.deepReview}
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

        {/* 범위 확정 자리는 패널을 열지 않아도 늘 mount한다. 알림 링크가 가리키는 자리다. */}
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
          {/* Astryx `Collapsible`은 `display:none`으로 감춰 조작을 막는다.
              여기는 조건부 렌더링이므로 열린 동안은 패널이 온전히 살아 있다. */}
          {documentPanelOpen ? (
            <DocumentPreparationPanel
              key={noticeId}
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
        </div>

        <div id="ps-record-history" className="ps-record-section ps-record-history" tabIndex={-1}>
          <ReviewHistoryLinkRail
            className="detail-skeleton-rail"
            historySections={[{
              className: "detail-skeleton-rail-panel",
              content: <p className="detail-skeleton-rail-note">개요 입력 범위와 현재 실행은 이 카드의 `개요 입력 범위 확정` 자리와 아래 실행 정보에서 봅니다.</p>,
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
          {currentPageOverviewForView ? (
            <PageOverviewCurrent current={currentPageOverviewForView} currentResult={currentResult} />
          ) : null}
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
        </div>

        <div className="ps-record-section ps-collapsed">
          <Collapsible
            key={`${noticeId}-${historyIsOpen ? "history-open" : "history-closed"}`}
            trigger="현재 주장 검증 진단 · 고정 입력과 식별 해시"
            defaultIsOpen={historyIsOpen}
          >
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
      </section>

      {/* ④ 참여 조건 · 회사 적합성 · 위험 및 미확인 사항 — 심층 검토 영역
          (spec §4 ④, ADR-0057 결정 1·4). 개요는 앞부분 요약만 맡으므로 참여
          조건·위험/미확인은 심층 검토 결과가 있을 때만 그 결과에서 읽는다.
          회사 적합성(`CompanyFitSection`)은 이 영역에 그대로 둔다. */}
      <section id="ps-conditions" className="ps-card ps-sec ps-record-quad" aria-labelledby="ps-conditions-title">
        <div className="ps-sec-head">
          <h2 id="ps-conditions-title" className="ps-h-sec">참여 조건 · 회사 적합성 · 위험 및 미확인 사항</h2>
          <span className="ps-cap ps-dim">적합성 등급 · 추적 결정 · 최종 Go/No-Go는 서로 대신하지 않음</span>
        </div>
        <div className="ps-tri">
          <section className="ps-tri-col" aria-labelledby="ps-conditions-list-title">
            <div className="ps-tri-head">
              <h3 id="ps-conditions-list-title" className="ps-h-col">참여 조건</h3>
              <span className="ps-cap ps-dim">{hasDeepReviewReport ? `${eligibilityItems.length}건` : "심층 검토 대기"}</span>
            </div>
            {!hasDeepReviewReport ? (
              <p className="ps-cap ps-muted">심층 검토에서 확인</p>
            ) : eligibilityItems.length > 0 ? (
              <ul className="ps-check ps-record-conditions">
                {eligibilityItems.map((text, index) => (
                  <li key={index}>
                    <span className="ps-box" aria-hidden="true" />
                    <span className="ps-t">{text}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="ps-cap ps-muted">이번 입력 범위에는 없음</p>}
          </section>

          <PreSpecBriefingSection noticeId={noticeId} judgment={judgment} reviews={notice.reviews} />

          <section className="ps-tri-col" aria-labelledby="ps-risk-title">
            <div className="ps-tri-head">
              <h3 id="ps-risk-title" className="ps-h-col">위험 및 미확인 사항</h3>
              <span className="ps-cap ps-dim">
                주의 {cautionCounts?.count ?? 0} · 미확인 {deepReviewUnknowns.length}
              </span>
            </div>
            {risks.length === 0 && judgmentRiskCount === 0 && companyFitVerificationItems.length === 0 ? (
              <p className="pre-spec-overview-empty">{hasDeepReviewReport ? "추가 조건·미확인 항목 없음" : "심층 검토에서 확인"}</p>
            ) : (
              <ul className="ps-risks">
                {risks.map((risk, index) => (
                  <li key={`deep-review-${index}`} className={`ps-risk is-${risk.tone}`}>
                    <div className="ps-risk-head">
                      <span className={`ps-chip ${risk.tone === "caution" ? "ps-chip-warn" : "ps-chip-neutral"}`}>{risk.label}</span>
                      <strong>{risk.title}</strong>
                    </div>
                    {risk.detail ? <span className="ps-cap ps-muted">{risk.detail}</span> : null}
                  </li>
                ))}
                {(judgment?.counterarguments ?? []).map((counterargument, index) => (
                  <li key={counterargument.id} className="ps-risk is-neutral">
                    <div className="ps-risk-head">
                      <span className="ps-chip ps-chip-neutral">반론</span>
                      <strong>{counterargument.text?.trim() || `반론 ${index + 1} 내용 미확인`}</strong>
                    </div>
                  </li>
                ))}
                {(judgment?.verification_items ?? []).map((item, index) => (
                  <li key={item.id} className="ps-risk is-neutral">
                    <div className="ps-risk-head">
                      <span className="ps-chip ps-chip-neutral">확인 항목</span>
                      <strong>{item.item?.trim() || `확인 항목 ${index + 1}`}</strong>
                    </div>
                    {item.why?.trim() ? <span className="ps-cap ps-muted">{item.why}</span> : null}
                  </li>
                ))}
                {companyFitVerificationItems.map((item, index) => (
                  <li key={`fit-${index}`} className="ps-risk is-neutral">
                    <div className="ps-risk-head">
                      <span className="ps-chip ps-chip-neutral">회사 적합성 확인</span>
                      <strong>{item}</strong>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </section>
    </Fragment>
  );
}

export function PreSpecDetailPage() {
  const { noticeId: noticeIdParam } = useParams();
  const [searchParams] = useSearchParams();
  const parsedNoticeId = Number(noticeIdParam);
  const noticeId = Number.isInteger(parsedNoticeId) && parsedNoticeId > 0 ? parsedNoticeId : null;
  const listSearch = searchParams.toString();
  // A route param is the record identity. Keying the body here gives React a
  // true record boundary: all query instances and local draft state are
  // discarded together on A → B navigation, while this navigation shell stays
  // mounted for loading and error states.
  const recordKey = noticeId === null ? `invalid:${noticeIdParam ?? ""}` : String(noticeId);
  return (
    <PreSpecDetailFrame noticeId={noticeId} search={listSearch}>
      <PreSpecRecordBody key={recordKey} noticeId={noticeId} listSearch={listSearch} />
    </PreSpecDetailFrame>
  );
}
