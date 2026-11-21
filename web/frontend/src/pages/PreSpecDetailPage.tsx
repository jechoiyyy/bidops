import { usePageHeader } from "../components/shell/PageHeaderContext";
import { FEATURE_OFF_LABEL, useFeatureFlags } from "../lib/featureFlags";
import { CurrentCompanyEnginePanel } from "../components/engine/EngineAnalysisPanel";
import { Button } from "@astryxdesign/core/Button";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Token } from "@astryxdesign/core/Token";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, lazy, Suspense, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { BUNDLE_STATUS_LABELS, DocumentPreparationPanel } from "../components/deep-review/DocumentPreparationPanel";
import { getDocumentBundles } from "../components/deep-review/api";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { ReviewHistoryLinkRail } from "../components/common/ReviewPrimitives";
import { PreSpecExclusionRecord } from "../components/pre-specs/PreSpecAgency";
import { SkeletonPanel } from "../components/common/Skeleton";
import { PreSpecDocumentSummary, TRACKING_DECISION_STATUSES_AFTER_ANALYSIS, TrackingDecisionControl, updateTrackingProjection } from "../components/pre-specs/TrackingDecisionControl";
import { OPPORTUNITY_TRACKING_REASONS } from "../components/opportunities/TrackingStatusDialog";
import type { EngineRun } from "../lib/engineApi";
import { PreSpecBriefingSection } from "../components/pre-specs/PreSpecBriefingSection";
import { PreSpecVerdictColumn, usePreSpecVerdict } from "../components/pre-specs/PreSpecVerdictColumn";
import { PreSpecAttachmentList } from "../components/pre-specs/PreSpecAttachmentList";
import { PreSpecProblemNotice } from "../components/pre-specs/PreSpecProblemNotice";
import { preSpecProblemNotice, type PreSpecProcessBlock } from "../lib/preSpecProblemNotice";
import { OrderPlanCandidatesSection } from "../components/pre-specs/OrderPlanCandidatesSection";
import { documentPanelDefaultOpen } from "../lib/documentPanelDefaultOpen";
import { preSpecProcessDefaultOpen, preSpecTechnicalInfoDefaultOpen } from "../lib/preSpecProcessDefaultOpen";
import { api } from "../lib/api";
import { PreSpecRecordIdentity } from "../components/pre-specs/PreSpecRecordIdentity";
import {
  CompanyFitExecutionSection,
  useCompanyFit,
} from "../components/pre-specs/CompanyFitSection";
import {
  PageOverviewCurrent,
  PageOverviewCurrentFacts,
  PageOverviewExecutionInfo,
  PageOverviewFactLine,
  PageOverviewHistory,
  PageOverviewHistoryFacts,
  PageOverviewNotices,
  PageOverviewRangeReview,
  PageOverviewResultFacts,
  PageOverviewVerificationDetails,
  pageOverviewPdfUrl,
  useCurrentPageOverview,
} from "../components/pre-specs/PageOverviewSection";
import { PageFooterBar, PageHeaderActions } from "../components/common/PageHeaderActions";
import { apiErrorRecoveryAction, describeApiError } from "../lib/apiErrors";
import { describeDeadlineCountdown } from "../lib/deadline";
import { formatNumber, present } from "../lib/format";
import { displayAssessmentSemanticLabel } from "../lib/grade";
import { preSpecCautions } from "../lib/preSpecCautions";
import { qualityStatusLabel, qualityStatusVariant } from "../lib/qualityStatus";
import {
  PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL,
  preSpecAutoPreparationReasonLabel,
} from "../lib/preSpecAutoPreparation";
import {
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
  PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION,
  preSpecOverviewReasonLabel,
  preSpecOverviewStatusVariant,
} from "../lib/preSpecOverviewStatus";
import {
  preSpecDetailUrl,
  preSpecReviewListUrl,
  readPreSpecSelectionReview,
} from "../lib/preSpecSelectionReview";
import { originLabel } from "../lib/preSpecViews";
import { readPreSpecLifecycle, readProcurementClass } from "../lib/noticeLifecycle";
import type { OpportunityDetailResponse, PageOverviewFact, PageOverviewView, PreSpecListItem, PreSpecListResponse } from "../lib/types";
import "../styles/pre-specs-relaxed.css";
import "../styles/detail-skeleton.css";
import "../styles/pre-spec-detail-erp.css";

const TRACKING_REASON_PRESETS = ["후속 입찰공고 확인", "세부 과업·연계 범위 확인", "참여 자격·실적 확인 필요"] as const;

/**
 * `분석 완료` 화면(2026-11-21 시안 b1~b3)은 **mock 빌드 전용**이다. `BIDOPS_REVIEW_MOCK`이 `false`로 접히는 운영
 * 빌드에서는 아래 동적 import가 사라져 그 모듈의 코드·문구·CSS가 운영 번들에 들어가지 않는다(엔진 mock 패널과 같은 경계).
 */
const loadAnalysisView = import.meta.env.BIDOPS_REVIEW_MOCK
  ? () => import("../components/pre-spec-analysis/PreSpecAnalysisView")
  : null;
const PreSpecEngineAnalysisProbe = loadAnalysisView
  ? lazy(() => loadAnalysisView().then((module) => ({ default: module.PreSpecEngineAnalysisProbe })))
  : null;
const PreSpecAnalysisSections = loadAnalysisView
  ? lazy(() => loadAnalysisView().then((module) => ({ default: module.PreSpecAnalysisSections })))
  : null;

function recordDateTime(value: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return "미확인";
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(value));
  const part = (type: string) => parts.find(item => item.type === type)?.value;
  return `${part("year")}.${part("month")}.${part("day")} ${part("hour")}:${part("minute")} KST`;
}

function OverviewPdfReference({ review }: { review: PageOverviewView }) {
  return <a className="ps-ref" href={pageOverviewPdfUrl(review)} target="_blank" rel="noreferrer">전체 근거 PDF 열기 ↗</a>;
}

const ASSESSMENT_AXIS_LABEL = {
  ai_data: "AI/데이터",
  blockchain_did: "블록체인/DID",
  public_si_integration: "공공 SI/통합관리",
} as const;

const ASSESSMENT_RELATION_LABEL = {
  direct: "직접",
  partial: "부분",
  indirect: "간접",
  unrelated: "무관",
  unknown: "미확인",
} as const;

/**
 * 상세 화면이 기다리는 것을 자리로 먼저 보여 준다. 쿼리마다 다른 문장이 뜨고
 * 사라지며 레이아웃이 흔들리던 자리를 사실·개요 자리로 고정한다. 추적 결정은 패널 아래 띠가
 * 같은 동안 `불러오는 중`을 말한다.
 */
function PreSpecDetailSkeleton({ noticeId }: { noticeId: number }) {
  return (
    <div className="detail-skeleton-main">
      <SkeletonPanel label={`사전규격 ${noticeId} 상세를 불러오는 중`} lines={3} />
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

  if (!hasReview) {
    return (
      <nav className="ps-detail-navigation" aria-label="사전규격 목록 이동">
        <Link to={preSpecReviewListUrl(search, noticeId)}>사전규격 목록으로</Link>
      </nav>
    );
  }
  return (
    <nav className="ps-detail-navigation" aria-label="사전규격 선택 순회">
      <div className="ps-detail-navigation-position">
        <span className="ps-k">선택 항목</span>
        <strong aria-live="polite">{`${index + 1} / ${review.orderedNoticeIds.length}`}</strong>
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

/**
 * 패널 아래 고정 추적 결정 띠(2026-11-21 시안 `docs/1121_prespec-detail/` `.decision-bar`). 본문의 옛 ② 추적 결정
 * 구역이 이 자리로 왔다. 상태값·사유 필수·저장·이탈 보호는 `TrackingDecisionControl`이 그대로 정하고 이 띠는
 * 배치(`presentation="bar"`)만 고른다. 담당자 이름은 사이드바 담당자 칸의 값을 쓴다.
 */
function PreSpecTrackingBar({
  noticeId,
  noticeNumber,
  item,
  isPending,
  isError,
  onRetry,
  afterAnalysis = false,
}: {
  noticeId: number;
  noticeNumber: string | null;
  item: PreSpecListItem | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  /** 분석 완료 화면이면 계속 추적·보류·종료 세 가지를 고른다(2026-11-21 사용자 결정, `TRACKING_DECISION_STATUSES` 주석). */
  afterAnalysis?: boolean;
}) {
  const queryClient = useQueryClient();
  const onSaved = (saved: OpportunityDetailResponse) => {
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
  };
  return (
    <PageFooterBar>
      <div className="ps-decision-bar" data-astryx-theme="bidops" role="region" aria-label="추적 결정">
        <div className="ps-decision-bar-inner" id="ps-tracking-bar">
          <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}>
            <TrackingDecisionControl
              key={`${noticeId}:${afterAnalysis ? "after-analysis" : "before-analysis"}`}
              compact
              presentation="bar"
              noticeNumber={noticeNumber}
              // 세 상태를 고르는 자리는 사업기회 추적 상태 변경과 같은 사유 예시를 쓴다(상태별로 나누지 않는 한 목록).
              reasonPresets={afterAnalysis ? OPPORTUNITY_TRACKING_REASONS : TRACKING_REASON_PRESETS}
              barStatuses={afterAnalysis ? TRACKING_DECISION_STATUSES_AFTER_ANALYSIS : undefined}
              item={item}
              isPending={isPending}
              isError={isError}
              onRetry={onRetry}
              onSaved={onSaved}
            />
          </InternationalizationProvider>
        </div>
      </div>
    </PageFooterBar>
  );
}

/** 자동 준비 진행 한 줄 단계 표시. 세 칸의 값은 모두 서버가 준 것이며 화면이
 * 다른 값에서 다시 계산하지 않는다:
 *
 * 1. 첨부 취득 — 사전규격 projection의 상태별 건수
 * 2. 묶음 — document bundle 응답의 `status`와 자동 준비 사유
 * 3. 개요 — projection의 `overview_review_status`(행이 없으면 미시작)
 *
 * 옛 넷째 칸 `심층 검토`는 2026-11-19에 내려갔다(사전규격 단계 수정안 §3 B).
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

/**
 * 개요 주장 목록. 주장 한 줄의 오른쪽에 그 주장의 PDF 쪽 링크가 붙는다(옛 ⑤ `주장별 원문 위치` 목록을 흡수했다 —
 * 같은 문장이 두 번 나오지 않는다). 문장과 링크는 `PageOverviewFactLine`이 그린다.
 */
function OverviewClaims({
  items,
  review,
  ordered = false,
  emptyLabel,
}: {
  items: PageOverviewFact[];
  review: PageOverviewView;
  ordered?: boolean;
  emptyLabel: string;
}) {
  if (items.length === 0) return <p className="ps-cap ps-muted">{emptyLabel}</p>;
  const List = ordered ? "ol" : "ul";
  return (
    <List className={`ps-claims${ordered ? " is-numbered" : ""}`}>
      {items.map((fact, index) => (
        <li key={index}>
          {ordered ? <span className="ps-claim-no" aria-hidden="true">{index + 1}</span> : null}
          <PageOverviewFactLine fact={fact} review={review} />
        </li>
      ))}
    </List>
  );
}

/** 읽은 쪽 목록의 표기. 이어진 쪽이면 `5~6`, 아니면 쉼표로 잇는다. 값을 바꾸거나 채우지 않는다. */
function reviewedPagesLabel(pages: readonly number[]): string {
  if (pages.length === 0) return "읽은 쪽 미확인";
  const sorted = [...pages].sort((left, right) => left - right);
  const contiguous = sorted.every((page, index) => index === 0 || page === sorted[index - 1] + 1);
  return contiguous && sorted.length > 1 ? `${sorted[0]}~${sorted[sorted.length - 1]}쪽` : `${sorted.join(", ")}쪽`;
}

/**
 * 개요 본문(2026-11-21 시안 a1). 기준 줄(검토 범위 · 검증 표식 · 품질 표식) → 사업 개요 → 주요 과업(번호) →
 * 사업 규모와 일정 → 접힌 대조 경고. 참여 조건·회사 적합성·위험은 이 구역이 갖지 않는다(ADR-0057 결정 1).
 */
function OverviewBody({ review, validationLabel }: { review: PageOverviewView; validationLabel: string | null }) {
  const { payload } = review;
  const warnings = review.warnings ?? [];
  return (
    <section className="page-overview ps-overview" aria-label="PDF 기반 개요 검토">
      <div className="ps-overview-basis page-overview-validation" role="status">
        <p>변환 PDF {review.pdf_page_count}쪽 중 {reviewedPagesLabel(review.reviewed_pages)}을 읽은 요약이에요. 판정이 아니에요.</p>
        {validationLabel ? <span className="ps-chip ps-chip-neutral">{validationLabel}</span> : null}
        <Badge label={qualityStatusLabel(review.quality_status)} variant={qualityStatusVariant(review.quality_status)} />
        {review.validation_status === "failed" && review.evidence_check_status === "passed" ? (
          <p className="ps-overview-basis-note">새 페이지 근거 검사는 통과했으나, 원실행의 검증 실패 기록은 유지해요.</p>
        ) : null}
      </div>
      <h3 className="ps-sub">사업 개요</h3>
      <OverviewClaims items={payload.business_overview} review={review} emptyLabel="이번 입력에서는 확인되지 않았어요." />
      <h3 className="ps-sub">주요 과업</h3>
      <OverviewClaims items={payload.main_tasks} review={review} ordered emptyLabel="이번 입력 범위에는 없음" />
      <h3 className="ps-sub">사업 규모와 일정</h3>
      <OverviewClaims items={payload.budget_and_period} review={review} emptyLabel="이번 입력 범위에는 없음" />
      {warnings.length > 0 ? (
        <details className="ps-overview-warnings">
          <summary>원문 대조 경고 {warnings.length}건 보기</summary>
          <ul>
            {warnings.map((code) => {
              // 모르는 코드는 그대로 보인다(`preSpecOverviewReasonLabel`이 코드 자체를 돌려준다).
              const label = preSpecOverviewReasonLabel(code);
              return <li key={code}><code>{code}</code>{label !== code ? ` · ${label}` : null}</li>;
            })}
          </ul>
          <p className="ps-cap ps-muted">경고가 붙은 수치·날짜는 원문 쪽에서 확인해 주세요.</p>
        </details>
      ) : null}
    </section>
  );
}

/** 사전규격 상세의 패널 헤더 글자를 올린다. 응답이 온 뒤에만 그려지므로 로딩·오류에서는 route 이름이 남는다. */
function PreSpecHeaderPublisher({ title, agency }: { title: string | null; agency: string | null }) {
  usePageHeader({
    eyebrow: agency?.trim() ? `사전규격 · ${agency.trim()}` : "사전규격",
    title: title?.trim() || "사업명 미확인",
  });
  return null;
}

/** 접힌 개요 구역 제목 줄 오른쪽 요약. 서버 상태 이름과 받은 과업 수만 잇는다. */
function joinOverviewSummary(statusLabel: string | null, review: PageOverviewView | null): string {
  return [
    statusLabel ? (statusLabel.startsWith("개요") ? statusLabel : `개요 ${statusLabel}`) : "개요 상태 미확인",
    review ? `과업 ${review.payload.main_tasks.length}건` : null,
  ].filter(Boolean).join(" · ");
}

function trimmedOrNull(value: string | null | undefined): string | null {
  return value?.trim() || null;
}

function PreSpecRecordBody({ noticeId, listSearch }: { noticeId: number | null; listSearch: string }) {
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
  const projectionItem = preSpecProjectionQuery.data?.items.find((item) => item.notice_pk === noticeId);
  // 참여 판정 열과 같은 응답을 읽는다. `회사 관련성 참고` 구역을 그릴지(값이 있는가)만 여기서 본다.
  const verdict = usePreSpecVerdict(projectionItem?.opportunity_id ?? null);
  // 사람이 직접 여닫거나 닫기 전에는 `null`이고, 그동안은 묶음·자동 준비 상태가
  // 정하는 기본값을 따른다. 응답이 늦게 와도 기본값이 다시 계산된다.
  const [documentPanelOverride, setDocumentPanelOverride] = useState<boolean | null>(null);
  const documentPanelInitialRef = useRef<boolean | null>(null);
  // 맨 아래 `처리 상태·기술 정보` 구역. 사람이 여닫기 전에는 기본 규칙(`preSpecProcessDefaultOpen`)을 따른다.
  // 문제가 보여 한 번 열린 구역은 상태가 나아졌다고 스스로 접지 않는다 — 사람이 그 안에서 작업하는 중일 수 있다.
  const [processOverride, setProcessOverride] = useState<boolean | null>(null);
  const processLatchRef = useRef(false);
  // 개요 구역의 `사람 확인 필요 → 보기`처럼 닫힌 구역 안의 자리를 가리키는 링크를 눌렀을 때, 구역을 연 뒤 그 자리로 옮긴다.
  const pendingScrollRef = useRef<string | null>(null);
  // 개요 입력 범위가 이미 정해진 건의 범위 확인(절 후보 표)은 눌렀을 때만 연다.
  const [rangeOpen, setRangeOpen] = useState(false);
  // 분석 완료 화면(mock 빌드 전용): 최신 엔진 run이 완료·부분 완료이고 `analysis`가 있으면 그 run이다.
  const [engineRun, setEngineRun] = useState<EngineRun | null>(null);
  // 분석 완료 화면에서 `사업 개요와 주요 과업`은 접혀 들어온다.
  const [overviewOpen, setOverviewOpen] = useState(false);
  // 개요 자동 검토가 이 환경에서 꺼져 있으면 실행 기록이 없는 이유를 먼저 말한다(설계고도화안 C-4).
  const overviewFeature = useFeatureFlags().state("prespec_overview");
  const overviewOff = overviewFeature === "off";
  // 문제 상태에서 열린 `처리 상태·기술 정보`는 관련 블록만 먼저 보이고 나머지는 이 토글 뒤에 둔다(시안 c `?open=1`).
  // 조건부 렌더링이다 — 안의 문서 준비 패널은 닫힌 동안 그리지 않는다(Astryx `Collapsible`을 쓰지 않는 이유와 같다).
  const [processRestOpen, setProcessRestOpen] = useState(false);

  useEffect(() => {
    const target = pendingScrollRef.current;
    if (!target) return;
    const element = document.getElementById(target);
    if (!element) return;
    pendingScrollRef.current = null;
    element.scrollIntoView({ block: "start" });
    element.focus({ preventScroll: true });
  });

  if (noticeId === null) {
    return (
      <EmptyState
        tone="error"
        title="사전규격 식별자를 확인할 수 없어요"
        description="주소의 사전규격 번호가 올바르지 않아요."
        action={{ label: "사전규격 목록", to: listUrl }}
      />
    );
  }

  const trackingBar = (
    <PreSpecTrackingBar
      noticeId={noticeId}
      noticeNumber={null}
      item={projectionItem}
      isPending={noticeQuery.isPending || preSpecProjectionQuery.isPending}
      isError={preSpecProjectionQuery.isError}
      onRetry={() => { void preSpecProjectionQuery.refetch(); }}
    />
  );

  if (noticeQuery.isPending) {
    return <>
      <PreSpecDetailSkeleton noticeId={noticeId} />
      {trackingBar}
    </>;
  }

  if (noticeQuery.isError) {
    const problem = describeApiError(noticeQuery.error, "선택한 사전규격의 상세 정보를 확인할 수 없어요.");
    return (
      <EmptyState
        tone="error"
        title={`사전규격 ${noticeId} 상세를 불러오지 못했어요.`}
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
        title="사전규격을 확인할 수 없어요"
        description="요청한 번호와 같은 사전규격이 아니에요. 다른 공고로 이동하지 않았어요."
        action={{ label: "사전규격 목록", to: listUrl }}
      />
    );
  }

  const deadlineCountdown = describeDeadlineCountdown(notice.deadline_at);
  const preSpecItem = projectionItem;
  const lifecycle = readPreSpecLifecycle(notice.lifecycle);
  const procurementClass = readProcurementClass(notice.procurement_class);
  const rawNumber = preSpecItem?.pre_spec_no ?? lifecycle.pre_spec_no;
  const preSpecNumber = rawNumber?.trim() && rawNumber !== "unknown" ? rawNumber.trim() : null;
  // 묶음 상태는 최신 revision 하나만 본다. 없으면 "묶음 없음"이며 초안으로
  // 보정하지 않는다.
  const latestBundle = [...(bundleQuery.data?.items ?? [])].sort((left, right) => right.revision - left.revision)[0] ?? null;
  const autoStatus = preSpecItem?.auto_preparation_status ?? null;
  const autoReasonLabel = preSpecAutoPreparationReasonLabel(preSpecItem?.auto_preparation_reason ?? null);
  const documentCounts = preSpecItem?.document ?? null;
  const overviewStatusForStep = preSpecItem
    ? (preSpecItem.overview_review_status === null
      ? PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL
      // 모르는 상태 값은 그대로 보인다 — 다른 상태 이름으로 바꾸지 않는다.
      : PRE_SPEC_OVERVIEW_STATUS_LABEL[preSpecItem.overview_review_status] ?? preSpecItem.overview_review_status)
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
  // 사람이 범위를 확정해야 하는 상태(시안 a3)면 범위 폼이 개요 구역 자리에 온다. 그 밖의 범위 확인은
  // 맨 아래 `처리 상태·기술 정보` 안에서 눌렀을 때만 연다.
  const rangeNeedsDecision = rangeReviewForView?.selection_status === "needs_human_review";
  const { query: companyFitQuery } = companyFitState;
  const companyFitData = companyFitState.isValid ? companyFitState.data : null;
  const currentCompanyFitAttempt = companyFitState.isValid ? companyFitState.currentAttempt : null;
  const previousCompanyFitAttempts = companyFitState.isValid ? companyFitState.previousAttempts : [];
  const companyFitVerificationItems = currentCompanyFitAttempt?.result?.verification_items ?? [];
  // 접힌 `기술 정보`의 기본 열림 규칙(0915 spec §4 ⑥ "실패·사람 확인 상태면 기본 열림"). 규칙은
  // `lib/preSpecProcessDefaultOpen.ts` 한 곳이 갖는다.
  const technicalIsOpen = preSpecTechnicalInfoDefaultOpen({
    bundle: latestBundle,
    overviewCurrent: currentPageOverview,
    companyFitAttempt: currentCompanyFitAttempt,
    verification: pageOverviewVerification,
  });
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
  // `처리 상태·기술 정보` 구역의 기본 열림. 응답이 모두 온 뒤에만 판단하고, 한 번 열리면 사람이 닫기 전까지 연다.
  const processInputsSettled = !bundleQuery.isPending && !pageOverviewQuery.isPending && !preSpecProjectionQuery.isPending;
  // 문제 상태 안내(시안 c1~c5). 세 응답이 모두 성공하고 개요 응답이 정본일 때만 고른다 — 조회 실패·불일치는 종전 문구가
  // 그대로 말한다. 문장·조작은 `lib/preSpecProblemNotice.ts`가 정한다.
  const problem = processInputsSettled
    && bundleQuery.isSuccess && preSpecProjectionQuery.isSuccess && pageOverviewQuery.isSuccess && pageOverviewValid
    ? preSpecProblemNotice({
      overview: currentPageOverview,
      rangeReview: rangeReviewForView,
      bundle: latestBundle,
      item: preSpecItem ?? null,
      attachments: notice.attachments,
      overviewFeature,
      deadlinePassed: deadlineCountdown ? deadlineCountdown.urgency === "passed" : null,
    })
    : null;
  // 범위 확정 폼이 어디에 있는가: 안내 안(문제 상태) · 개요 구역 자리(시안 a3) · 처리 상태 안(그 밖).
  const rangeInNotice = problem !== null && rangeNeedsDecision
    && problem.actions.some((action) => action.kind === "range_form" || action.kind === "range_form_toggle");
  const rangeAtTop = problem === null && rangeNeedsDecision;
  const runHasReasonCodes = (currentPageOverviewForView?.reason_codes.length ?? 0) > 0;
  if (processInputsSettled && preSpecProcessDefaultOpen({
    bundle: latestBundle,
    autoStatus,
    overviewCurrent: currentPageOverview,
    companyFitAttempt: currentCompanyFitAttempt,
    verification: pageOverviewVerification,
    rangeReview: rangeReviewForView,
    problemNotice: problem !== null,
  })) {
    processLatchRef.current = true;
  }
  const processOpen = processOverride ?? processLatchRef.current;
  const verificationReasonCount = pageOverviewVerification
    ? pageOverviewVerification.reason_codes.length
      + pageOverviewVerification.claims.reduce((total, claim) => total + claim.reason_codes.length, 0)
    : 0;

  // 위험 및 미확인 사항은 회사 적합성 확인 항목만 모은다. 옛 열은 기존 심층 검토 보고서의
  // 미확인과 C-1 판정의 반론·확인 항목을 읽었다 — 둘 다 2026-11-19에 화면에서 내려갔다
  // (사전규격 단계 수정안 §3 B). 판정의 차단 조건·주의는 첫 열(참여 판정)이 갖는다.
  const cautionCounts = preSpecItem
    ? preSpecCautions({
      item: preSpecItem,
      verification: pageOverviewVerification,
      deepReviewUnknownCount: null,
    })
    : null;
  // v4 주장만 원문 위치(claim id)를 갖는다. 기술 정보의 `주장 ID` 목록이 읽는다.
  const evidenceClaimIds = shown
    ? [...shown.payload.business_overview, ...shown.payload.main_tasks, ...shown.payload.budget_and_period]
      .filter((fact): fact is Extract<PageOverviewFact, { claim_id: string }> => "claim_id" in fact)
      .map((fact) => fact.claim_id)
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
  };

  // 식별 줄의 값들. 헤더 작은 줄이 이미 수요기관(없으면 공고기관)을 보이므로, 공고기관은 수요기관과 다를 때만
  // 적는다. 품명 분류는 사업명과 같으면 적지 않는다(2026-11-21 시안 정보 감사).
  const demandAgency = trimmedOrNull(preSpecItem?.demand_agency);
  const announcerAgency = trimmedOrNull(notice.agency);
  const showAnnouncer = demandAgency !== null && announcerAgency !== null && announcerAgency !== demandAgency;
  const classification = trimmedOrNull(procurementClass.detail ?? procurementClass.code);
  const showClassification = classification !== null && classification !== trimmedOrNull(notice.title);
  const bidNoticeNumber = trimmedOrNull(lifecycle.bid_ntice_no_list);
  const excluded = preSpecItem?.review_exclusion_status === "excluded";

  // `회사 관련성 참고`(옛 ④ 참여 판정·회사 적합성·위험과 머리의 예비 판단 근거)는 값이 있을 때만 그린다.
  // 값이 없으면 각 열의 상태 문구(꺼짐·판정 없음)는 `처리 상태·기술 정보` 안으로 간다 — 지우지 않는다.
  const preliminary = preSpecItem?.display_assessment.source === "preliminary_assessment" ? preSpecItem.display_assessment : null;
  const relevanceVisible = verdict.hasValue || currentCompanyFitAttempt !== null || preliminary !== null;
  // 분석 완료 화면(mock 빌드 전용). 회사 관련성 참고 구역은 이 화면의 구성(시안 b)에 없으므로 처리 상태 안으로 간다.
  const analysisView = engineRun !== null && PreSpecAnalysisSections !== null;
  const showRelevanceSection = relevanceVisible && !analysisView;
  const trackingStateLabel = !preSpecItem
    ? "미확인"
    : preSpecItem.opportunity_id == null ? "사업기회 미연결" : preSpecItem.tracking_status ?? "미확인";

  // `처리 상태·기술 정보` 제목 줄 오른쪽 요약 한 줄. 서버 상태 이름을 그대로 잇고 새 판단을 만들지 않는다.
  // 문제 상태에서는 멈춘 단계를 말로 적는다(안내와 같은 표). 꺼진 기능 표시는 그대로 붙는다.
  const processSummary = [
    ...(problem ? [problem.foldSummary] : [bundleQuery.isPending
      ? "원문 묶음 확인 중"
      : bundleQuery.isError
        ? "원문 묶음 확인 실패"
        : latestBundle ? `원문 묶음 ${BUNDLE_STATUS_LABELS[latestBundle.status]}` : "원문 묶음 없음",
    preSpecItem
      ? preSpecItem.overview_review_status === null
        ? PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL
        : `개요 ${overviewStatusForStep}`
      : "개요 상태 미확인"]),
    ...(overviewOff ? ["개요 자동 검토 꺼짐"] : []),
    ...(verdict.rlOff ? ["참여 판정(RL 분석) 꺼짐"] : []),
    ...(companyFitData !== null && !companyFitData.automation_enabled ? ["회사 적합성 자동 판정 비활성"] : []),
  ].join(" · ");

  const openProcessTarget = (event: MouseEvent<HTMLElement>) => {
    // 개요 알림의 `→ 보기`는 `처리 상태·기술 정보` 안의 처리 이력을 가리킨다. 구역이 닫혀 있으면 열고 그 자리로 옮긴다.
    const anchor = (event.target as HTMLElement).closest?.("a[href='#ps-record-history']");
    if (!anchor || (processOpen && (problem === null || processRestOpen))) return;
    event.preventDefault();
    pendingScrollRef.current = "ps-record-history";
    setProcessOverride(true);
    setProcessRestOpen(true);
  };

  // 안내의 `문서 준비 열기`: 구역을 열고 문서 준비 패널을 펼친 뒤 그 자리로 초점을 옮긴다.
  const openDocumentPreparation = () => {
    pendingScrollRef.current = "ps-record-documents";
    setDocumentPanelOverride(true);
    setProcessOverride(true);
  };

  const relevanceColumns = (
    <div className="ps-tri">
      <PreSpecVerdictColumn opportunityId={preSpecItem?.opportunity_id ?? null} />

      <PreSpecBriefingSection noticeId={noticeId} />

      <section className="ps-tri-col" aria-labelledby="ps-risk-title">
        <div className="ps-tri-head">
          <h3 id="ps-risk-title" className="ps-h-col">위험 및 미확인 사항</h3>
          <span className="ps-cap ps-dim">주의 {cautionCounts?.count ?? 0}</span>
        </div>
        {companyFitVerificationItems.length === 0 ? (
          <p className="pre-spec-overview-empty">회사 적합성 확인 항목 없음 · 차단 조건과 주의는 참여 판정에서 확인해요.</p>
        ) : (
          <ul className="ps-risks">
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
  );

  /* ── `처리 상태·기술 정보` 안의 블록들 ───────────────────────────────────
     정상 상태는 종전 순서 그대로 모두 그린다(`processAllBlocks`). 문제 상태에서는 안내가 가리키는 블록을 먼저 두고
     (`problem.firstBlock`) 나머지를 같은 순서로 `나머지 기술 정보 보기` 뒤에 둔다. 블록 내용과 조작·폴링은 같다. */
  const documentToggleBlock = (
    <div key="actions" className="ps-process-actions">
      <Button
        label={documentPanelOpen ? "문서 준비 닫기" : "문서 준비 열기"}
        size="sm"
        variant="ghost"
        aria-expanded={documentPanelOpen}
        onClick={() => setDocumentPanelOverride(!documentPanelOpen)}
      />
      {/* 개요 재실행 단추는 그리지 않는다(intent 결정 3). 재실행은 문서 준비 패널 안에서만 연다.
          기존 심층 검토 보고서 단추는 2026-11-19에 내려갔다(사전규격 단계 수정안 §3 B). */}
    </div>
  );

  const stepsBlock = (
    <div key="steps" className="pre-spec-auto-preparation" aria-label="자동 준비 진행">
      <ol className="pre-spec-auto-steps ps-steps">
        <AutoPreparationStep
          index={1}
          name="첨부 취득"
          done={stepDone.attachments}
          value={documentCounts ? `${documentCounts.attachments}건` : "집계 없음"}
          variant={documentCounts && (documentCounts["차단"] > 0 || documentCounts["실패"] > 0) ? "alert" : "neutral"}
          detail={documentCounts
            ? `완료 ${documentCounts["완료"]} · 대기 ${documentCounts["대기"]} · 진행 ${documentCounts["진행"]} · 차단 ${documentCounts["차단"]} · 실패 ${documentCounts["실패"]}`
            : "사전규격 요약 정보가 없어 첨부 집계를 표시하지 않아요."}
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
          detail={[latestBundle ? `수정본 ${latestBundle.revision}` : null, autoReasonLabel]
            .filter((part): part is string => Boolean(part)).join(" · ") || undefined}
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
      </ol>
      {/* 경계 문장은 하단 추적 결정 띠가 한 번만 갖는다. 자동 시작 조건은 이 단계들의 사실이라 남는다. */}
      <p className="pre-spec-auto-preparation-note">
        첨부 취득·문서 준비·개요 검토는 의견 마감 전이거나 추적 중인 사전규격에서 자동으로 진행해요. 마감이 지난 건은 추적을 시작하면 진행해요.
      </p>
    </div>
  );

  const documentSummaryLineBlock = (
    <p key="summary-line" className="ps-document-panel-summary-line">
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
  );

  /* 범위가 이미 정해진 건(자동 선택·확정됨)의 범위 확인은 눌렀을 때만 연다 — 절 후보 표가 본문을 길게 늘이지 않게
     한다. 사람이 확정해야 하는 상태면 폼은 위 개요 구역 자리(시안 a3)나 문제 상태 안내 안에 있다. */
  const rangeBlock = rangeReviewForView && !rangeAtTop && !rangeInNotice ? (
    <section key="range" id="ps-record-range" className="ps-record-section ps-record-range" tabIndex={-1} aria-label="개요 입력 범위 확정">
      <Button
        label={rangeOpen ? "개요 입력 범위 닫기" : "개요 입력 범위 보기"}
        size="sm"
        variant="ghost"
        aria-expanded={rangeOpen}
        onClick={() => setRangeOpen(!rangeOpen)}
      />
      {rangeOpen ? (
        <PageOverviewRangeReview
          noticeId={noticeId}
          review={rangeReviewForView}
          runHasReasonCodes={runHasReasonCodes}
          onConfirmed={() => { void pageOverviewQuery.refetch(); }}
        />
      ) : null}
    </section>
  ) : null;

  const documentPanelBlock = (
    <div key="documents" id="ps-record-documents" className="ps-record-section ps-record-documents" tabIndex={-1}>
      {/* Astryx `Collapsible`은 `display:none`으로 감춰 조작을 막는다.
          여기는 조건부 렌더링이므로 열린 동안은 패널이 온전히 살아 있다. */}
      {documentPanelOpen ? (
        <DocumentPreparationPanel key={noticeId} noticeId={notice.id} />
      ) : null}
    </div>
  );

  const fetchSummaryBlock = (
    <div key="fetch" id="ps-record-fetch" className="ps-record-section ps-record-fetch" tabIndex={-1}>
      {preSpecProjectionQuery.isPending ? (
        <SkeletonPanel label="첨부 원문 취득 집계를 불러오는 중" lines={3} />
      ) : null}
      {preSpecProjectionQuery.isError ? (
        <PreSpecQueryError
          onRetry={() => { void preSpecProjectionQuery.refetch(); }}
          error={preSpecProjectionQuery.error}
          fallback="사전규격 요약 정보를 불러오지 못해 첨부 취득 집계를 표시하지 않아요."
          title="첨부 원문 취득 집계를 불러오지 못했어요"
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
  );

  /* 분석 엔진 mock 참조 패널은 실험 경로라 개발·mock 서버에서만 그린다(설계고도화안 C-9).
     운영 번들에는 들어가지 않으며 live 전송은 원래부터 fail closed다. */
  const engineBlock = import.meta.env.BIDOPS_REVIEW_MOCK
    ? <CurrentCompanyEnginePanel key="engine" noticeId={noticeId} bundleId={latestBundle?.status === "ready" ? latestBundle.id : null} hideScore />
    : null;

  /* 회사 관련성 참고 구역을 그리지 않은 건(값 없음)의 열 상태 문구 — `이 환경에서 꺼져 있음`·`판정 없음`·
     `자동 판정 비활성` — 는 여기 남는다. 지우지 않고 옮긴다. */
  const relevanceBlock = showRelevanceSection ? null : (
    <section key="relevance" className="ps-record-section ps-process-relevance" aria-label="회사 관련성 참고 상태">
      <h3 className="ps-sub">회사 관련성 참고</h3>
      {relevanceColumns}
    </section>
  );

  // 개요 run이 멈춘 문제 상태에서는 `현재 개요 검토`(마지막 실행)가 처리 이력에서 나와 먼저 보이는 블록이 된다.
  const runFirst = problem?.firstBlock === "run";
  const currentRunNode = currentPageOverviewForView ? (
    <PageOverviewCurrent current={currentPageOverviewForView} currentResult={currentResult} />
  ) : null;
  const runBlock = runFirst && currentRunNode ? (
    <div key="run" id="ps-record-run" className="ps-record-section ps-record-run" tabIndex={-1}>{currentRunNode}</div>
  ) : null;

  const historyBlock = (
    <div key="history" id="ps-record-history" className="ps-record-section ps-record-history" tabIndex={-1}>
      <ReviewHistoryLinkRail
        className="detail-skeleton-rail"
        historySections={[{
          className: "detail-skeleton-rail-panel",
          content: <p className="detail-skeleton-rail-note">개요 입력 범위와 현재 실행은 이 카드의 `개요 입력 범위 확정` 자리와 아래 실행 정보에서 봐요.</p>,
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
      {runFirst ? null : currentRunNode}
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
  );

  /* 접힌 `기술 정보` 하나(0915 spec §4 ⑥ · ADR-0066 결정 1 `이동`). 주장 검증 진단 · 고정 입력과 식별 해시 · 회사
     적합성 실행 정보 세 덩어리를 소제목으로 나눠 담는다. 기본 열림 규칙은 바꾸지 않는다 — 실패·사람 확인 상태(묶음·
     개요·검증·회사 적합성)면 열린 채로 들어온다. */
  const technicalBlock = (
    <div key="technical" className="ps-record-section ps-collapsed">
      <Collapsible
        key={`${noticeId}-${technicalIsOpen ? "technical-open" : "technical-closed"}`}
        trigger="기술 정보 · 주장 검증 진단, 고정 입력과 식별 해시, 회사 적합성 실행 정보"
        defaultIsOpen={technicalIsOpen}
      >
        {/* 첨부 표 아래에 있던 고정 문장. 그 순간의 데이터가 아니라 이 화면의 규칙이라 여기로 왔다. */}
        <p className="ps-cap ps-muted">첨부 원문 열기는 검증된 절대 HTTP(S) 주소만 사용하며 나라장터 원문 URL을 대신하지 않아요.</p>
        {currentPageOverviewForView?.attempt_id && pageOverviewVerification ? (
          <PageOverviewVerificationDetails
            noticeId={noticeId}
            attemptId={currentPageOverviewForView.attempt_id}
            verification={pageOverviewVerification}
          />
        ) : null}
        <section className="page-overview-section" aria-label="고정 입력과 식별 해시">
          <h3>고정 입력과 식별 해시</h3>
          {currentPageOverviewForView ? <PageOverviewCurrentFacts current={currentPageOverviewForView} /> : null}
          {shown ? <PageOverviewResultFacts review={shown} claimIds={evidenceClaimIds} /> : null}
          {shown ? <PageOverviewExecutionInfo review={shown} /> : null}
          {!currentPageOverviewForView && !shown ? <p>{overviewOff ? `개요 검토 실행 기록이 없어요 · ${FEATURE_OFF_LABEL}.` : "개요 검토 실행 기록이 없어요."}</p> : null}
          <PageOverviewHistoryFacts reviews={pageOverviewValid ? pageOverviewHistory : []} />
        </section>
        <CompanyFitExecutionSection
          current={currentCompanyFitAttempt}
          previous={previousCompanyFitAttempts}
          state={companyFitQuery.isPending ? "pending" : companyFitData === null ? "unavailable" : "ready"}
        />
      </Collapsible>
    </div>
  );

  // 정상 상태: 종전 순서 그대로. (문서 준비 패널과 첨부 취득 집계는 종전처럼 바로 이어진다.)
  const processAllBlocks = [
    documentToggleBlock, stepsBlock, documentSummaryLineBlock, rangeBlock, documentPanelBlock, fetchSummaryBlock,
    engineBlock, relevanceBlock, historyBlock, technicalBlock,
  ];
  // 문제 상태: 먼저 보일 블록. 문서 준비는 토글·요약 줄·패널·취득 집계를 함께 둔다.
  const firstBlockGroups: Record<PreSpecProcessBlock, ReactNode[]> = {
    run: [runBlock],
    documents: [documentToggleBlock, documentSummaryLineBlock, documentPanelBlock, fetchSummaryBlock],
    fetch: [stepsBlock, fetchSummaryBlock],
    steps: [stepsBlock],
  };
  const processFirstBlocks = problem ? firstBlockGroups[problem.firstBlock] : [];
  const processRestBlocks = problem
    ? processAllBlocks.filter((block) => !processFirstBlocks.includes(block))
    : [];

  return (
    <Fragment>
      {/* 자체 브레드크럼·`목록으로 돌아가기`는 두지 않는다. 패널 헤더의 `‹ 사전규격`이 목록의 필터·선택 순회를
          되살리는 돌아갈 링크다. */}
      {/* 패널 헤더(2026-11-19 최종 시안 패턴): `‹ 사전규격` · 화면 이름 줄 · 사업명 `<h1>`. */}
      <PreSpecHeaderPublisher agency={preSpecItem?.demand_agency ?? notice.agency} title={notice.title} />
      {PreSpecEngineAnalysisProbe ? (
        <Suspense fallback={null}><PreSpecEngineAnalysisProbe noticeId={noticeId} onChange={setEngineRun} /></Suspense>
      ) : null}

      {/* 1. 사실 줄 (2026-11-21 시안): 의견 마감(D-n) · 사업 예산 · 구분 · 게시 / 식별 줄. 옛 칩 줄·추적 결정 칩·
          머리의 사업 요약·빈 칸·`첨부 원문 n건` 칸은 같은 값을 두 번 말해 없앴다. */}
      <header id="ps-summary" className="pre-spec-detail-header detail-skeleton-head ps-card ps-record-facts-section" aria-label="사전규격 상세 정보">
        {/* 사업명은 패널 헤더의 `<h1>`이 제목으로 그린다. 같은 이름의 제목을 하나 더 두면 제목 탐색이
            두 번 걸리므로, 여기는 `aria-labelledby`가 가리킬 구역 이름(제목 아님)만 낭독기에 남긴다. */}
        <span id="pre-spec-detail-title" className="ps-h-page visually-hidden">{present(notice.title, "사업명 미확인")}</span>
        <dl className={`ps-fact-row${analysisView ? " has-tracking" : ""}`}>
          <div className="ps-fact-cell">
            <dt>의견 마감</dt>
            <dd>
              {recordDateTime(notice.deadline_at)}
              {deadlineCountdown ? (
                <small className={`ps-fact-sub is-deadline${deadlineCountdown.urgency === "passed" ? " is-err" : deadlineCountdown.urgency === "critical" || deadlineCountdown.urgency === "soon" ? " is-warn" : ""}`}>
                  {deadlineCountdown.label}
                </small>
              ) : null}
            </dd>
          </div>
          <div className="ps-fact-cell">
            <dt>사업 예산</dt>
            <dd>{notice.budget === null ? "예산 미제공" : `${formatNumber(notice.budget)}원`}</dd>
          </div>
          <div className="ps-fact-cell">
            <dt>구분</dt>
            <dd>
              {preSpecItem?.business_division ?? "미확인"}
              <small className="ps-fact-sub">SW사업대상 {preSpecItem?.sw_business_status ?? "미확인"}</small>
            </dd>
          </div>
          <div className="ps-fact-cell">
            <dt>게시</dt>
            <dd>{recordDateTime(notice.published_at)}</dd>
          </div>
          {analysisView ? (
            <div className="ps-fact-cell">
              <dt>추적 상태</dt>
              <dd>{trackingStateLabel}</dd>
            </div>
          ) : null}
        </dl>
        <div className="ps-ident">
          <PreSpecRecordIdentity key={noticeId} number={preSpecNumber} url={notice.url} />
          <span className="ps-ident-item">{bidNoticeNumber ? `본공고 ${bidNoticeNumber}` : "본공고 미확인"}</span>
          {/* `독립 발견`·`발주계획 연계`는 발견 경로의 값이다(business-rules). 값만 있으면 뜻이 안 읽혀 이름을 붙인다. */}
          {preSpecItem ? <span className="ps-ident-item">발견 경로 {originLabel(preSpecItem.origin)}</span> : null}
          {showAnnouncer ? <span className="ps-ident-item ps-record-agency">공고기관 {announcerAgency}</span> : null}
          {showClassification ? <span className="ps-ident-item ps-record-classification">품명 분류 · {classification}</span> : null}
        </div>
        {/* 제외된 건은 누가·언제·왜를 함께 남긴다(spec §6.2). 지우지 않는다. */}
        {excluded && preSpecItem ? (
          <p className="ps-exclusion-line">
            <Token size="sm" label="검토 제외" color="default" />
            <PreSpecExclusionRecord className="ps-record-exclusion-note" item={preSpecItem} />
          </p>
        ) : null}
      </header>

      {/* 분석 완료 화면(시안 b1~b3, mock 빌드 전용): 요약 · 차단·자격 조건 · 확인할 일 · 요구사항 대응 · 리스크 · 인력·계약. */}
      {analysisView && engineRun && PreSpecAnalysisSections ? (
        <Suspense fallback={<SkeletonPanel label="분석 결과를 불러오는 중" lines={4} />}>
          <PreSpecAnalysisSections run={engineRun} />
        </Suspense>
      ) : null}

      {/* 2. 사업 개요와 주요 과업 (옛 ③). 주장마다 그 줄 오른쪽에 쪽 링크가 붙는다. */}
      <section
        id="ps-tasks"
        className={`ps-card ps-sec ps-record-tasks${analysisView ? " ps-fold" : ""}`}
        aria-labelledby="ps-tasks-title"
        onClickCapture={openProcessTarget}
      >
        {analysisView ? (
          /* 분석 완료 화면에서는 접혀 들어온다(시안 b). 여는 것은 사람의 조작이다. */
          <div className="ps-sec-head ps-fold-head">
            <h2 id="ps-tasks-title" className="ps-h-sec">
              <button className="ps-fold-toggle" type="button" aria-expanded={overviewOpen} onClick={() => setOverviewOpen(!overviewOpen)}>
                <svg aria-hidden="true" className="ps-fold-chevron" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} viewBox="0 0 24 24"><path d="m9 6 6 6-6 6" /></svg>
                사업 개요와 주요 과업
              </button>
            </h2>
            <p className="ps-fold-meta">{joinOverviewSummary(overviewStatusForStep, shown)}</p>
          </div>
        ) : (
          <div className="ps-sec-head">
            <h2 id="ps-tasks-title" className="ps-h-sec">사업 개요와 주요 과업</h2>
            {shown && !rangeNeedsDecision ? (
              <div className="ps-sec-actions">
                <OverviewPdfReference review={shown} />
              </div>
            ) : null}
          </div>
        )}
        {analysisView && !overviewOpen ? null : <>
        {problem ? (
          /* 문제 상태 안내 한 블록(시안 c1~c5). 실제 사유·할 일을 말하고, 범위 확정이 다시 실행하는 길이면 폼을 품는다.
             종전 알림 두 줄과 개요 자리 범위 폼은 이때 그리지 않는다(같은 일을 두 번 말하지 않는다). */
          <PreSpecProblemNotice
            notice={problem}
            noticeId={noticeId}
            rangeForm={rangeInNotice && rangeReviewForView ? (
              <PageOverviewRangeReview
                noticeId={noticeId}
                review={rangeReviewForView}
                presentation="notice"
                runHasReasonCodes={runHasReasonCodes}
                onConfirmed={() => { void pageOverviewQuery.refetch(); }}
              />
            ) : null}
            onOpenDocuments={openDocumentPreparation}
          />
        ) : <>
          {/* 알림 두 줄(개요 입력 범위 확정 필요 · 사람 확인 필요)은 그대로다. */}
          <PageOverviewNotices
            rangeReview={rangeReviewForView}
            current={currentPageOverviewForView}
            verification={pageOverviewVerification}
            verificationReasonCount={verificationReasonCount}
          />
          {rangeAtTop && rangeReviewForView ? (
            /* 시안 a3: 범위 확정이 필요하면 범위 폼이 개요 자리에 온다. 알림의 `확정하기 →`가 가리키는 자리다. */
            <section id="ps-record-range" className="ps-record-section ps-record-range" tabIndex={-1} aria-label="개요 입력 범위 확정">
              <PageOverviewRangeReview
                noticeId={noticeId}
                review={rangeReviewForView}
                runHasReasonCodes={runHasReasonCodes}
                onConfirmed={() => { void pageOverviewQuery.refetch(); }}
              />
            </section>
          ) : null}
        </>}
        {pageOverviewQuery.isPending ? (
          <p role="status">PDF 기반 개요를 불러오는 중이에요.</p>
        ) : pageOverviewQuery.isError ? (
          <div role="alert" className="page-overview-validation">
            <p>PDF 기반 개요를 불러오지 못했어요. 아래 기존 개요 기록과는 별도 조회예요.</p>
            <Button label="개요 다시 불러오기" size="sm" onClick={() => { void pageOverviewQuery.refetch(); }} />
          </div>
        ) : !pageOverviewValid ? (
          <p role="alert">개요 응답의 공고 또는 구조가 일치하지 않아 표시하지 않아요.</p>
        ) : shown ? (
          <OverviewBody review={shown} validationLabel={overviewValidationLabel} />
        ) : rangeAtTop || problem ? null : (
          /* 검증된 결과가 없으면 그 상태가 무엇을 기다리는지 한 줄로 남긴다. 문장은
             `preSpecOverviewStatus`가 소유하며 화면이 다시 적지 않는다. */
          <div className="pre-spec-overview-waiting">
            <strong>{overviewStatusForStep ?? "개요 검토 상태 미확인"}</strong>
            <p>{preSpecItem?.overview_review_status
              ? PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION[preSpecItem.overview_review_status]
              : overviewOff
                ? `개요 검토 · ${FEATURE_OFF_LABEL}. 이 환경의 운영 설정에서 개요 자동 검토가 꺼져 있어 실행 기록이 없고 주요 과업을 표시할 수 없어요.`
                : "개요 검토 실행 기록이 없어 주요 과업을 표시할 수 없어요."}</p>
          </div>
        )}
        </>}
      </section>

      {/* (조건부) 회사 관련성 참고 — 옛 ④ 세 열과 머리의 예비 판단 근거. 값이 있을 때만 개요 아래에 그린다. */}
      {showRelevanceSection ? (
        <section id="ps-conditions" className="ps-card ps-sec ps-record-quad" aria-labelledby="ps-conditions-title">
          <div className="ps-sec-head">
            <h2 id="ps-conditions-title" className="ps-h-sec">회사 관련성 참고</h2>
          </div>
          {preliminary ? (
            <div className="ps-record-summary" aria-label="예비 적합성 판단 근거">
              <span className="ps-chip ps-chip-neutral">예비 판단 근거</span>
              <p>
                {preliminary.axes.length > 0
                  ? preliminary.axes.map((axis) => (
                    `${ASSESSMENT_AXIS_LABEL[axis.axis]} ${ASSESSMENT_RELATION_LABEL[axis.relation]} · ${axis.reason}`
                  )).join(" / ")
                  : preliminary.reason_codes.length > 0
                    ? `판단 보류 · ${preliminary.reason_codes.join(", ")}`
                    : "판단 근거가 게시되지 않았어요."}
                {preliminary.verification_items.length > 0
                  ? ` 확인 항목 · ${preliminary.verification_items.join(", ")}`
                  : ""}
                {preliminary.quality_status
                  ? ` 품질 · ${qualityStatusLabel(preliminary.quality_status)}`
                  : ""}
                {displayAssessmentSemanticLabel(preliminary)
                  ? ` · ${displayAssessmentSemanticLabel(preliminary)}`
                  : ""}
                {" "}<a className="ps-ref" href="#ps-evidence">원문 근거로 이동</a>
              </p>
            </div>
          ) : null}
          {relevanceColumns}
        </section>
      ) : null}

      {/* 3. 원문·첨부 (옛 ⑤). 첨부 표만 남고, 발주계획 후보는 1건 이상일 때만 아래에 붙는다. */}
      <section id="ps-evidence" tabIndex={-1} className="ps-card ps-sec ps-record-evidence" aria-labelledby="ps-evidence-title">
        <div className="ps-sec-head">
          <h2 id="ps-evidence-title" className="ps-h-sec">원문·첨부 <span className="ps-cnt">{notice.attachments.length}건</span></h2>
        </div>
        <PreSpecAttachmentList attachments={notice.attachments} />
        {/* 발주계획 후보(docs/0917_opportunity-tracking/spec.md §11.4). 연결 확인은 사람이 한다. 조회 오류는 숨기지 않는다. */}
        <OrderPlanCandidatesSection noticeId={noticeId} hideWhenEmpty />
      </section>

      {/* 4. 처리 상태·기술 정보 (옛 ⑥ 전체). 맨 아래 접힌 구역 하나다 — 삭제가 아니라 이동이다(ADR-0066).
          기본 닫힘이고 문제가 있으면 열린 채로 들어온다(`lib/preSpecProcessDefaultOpen.ts`). Astryx `Collapsible`을
          쓰지 않는다 — 안의 문서 준비 패널이 조작·폴링을 잃지 않게 조건부 렌더링한다. */}
      <section id="ps-process" className="ps-card ps-sec ps-record-process ps-fold" aria-labelledby="ps-process-title">
        <div className="ps-sec-head ps-fold-head">
          <h2 id="ps-process-title" className="ps-h-sec">
            <button
              className="ps-fold-toggle"
              type="button"
              aria-expanded={processOpen}
              aria-controls={processOpen ? "ps-process-body" : undefined}
              onClick={() => setProcessOverride(!processOpen)}
            >
              <svg aria-hidden="true" className="ps-fold-chevron" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} viewBox="0 0 24 24"><path d="m9 6 6 6-6 6" /></svg>
              처리 상태·기술 정보
            </button>
          </h2>
          <p className="ps-fold-meta" data-testid="pre-spec-process-summary">{processSummary}</p>
        </div>

        {processOpen ? (
          <div id="ps-process-body" className="ps-fold-body">
            {problem ? <>
              {/* 문제 상태(시안 c `?open=1`): 멈춘 단계의 블록이 먼저이고, 나머지는 지우지 않고 한 번 더 접는다(ADR-0066 이동). */}
              {processFirstBlocks}
              <div className="ps-process-rest">
                <button
                  className="ps-fold-toggle ps-process-rest-toggle"
                  type="button"
                  aria-expanded={processRestOpen}
                  aria-controls={processRestOpen ? "ps-process-rest-body" : undefined}
                  onClick={() => setProcessRestOpen(!processRestOpen)}
                >
                  <svg aria-hidden="true" className="ps-fold-chevron" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} viewBox="0 0 24 24"><path d="m9 6 6 6-6 6" /></svg>
                  {processRestOpen ? "나머지 기술 정보 접기" : "나머지 기술 정보 보기"}
                </button>
                {processRestOpen ? (
                  <div id="ps-process-rest-body" className="ps-process-rest-body">{processRestBlocks}</div>
                ) : null}
              </div>
            </> : processAllBlocks}
          </div>
        ) : null}
      </section>

      {/* 패널 아래 고정 추적 결정 띠(옛 ② `#ps-tracking` 구역). */}
      <PreSpecTrackingBar
        noticeId={noticeId}
        noticeNumber={preSpecNumber}
        item={preSpecItem}
        isPending={preSpecProjectionQuery.isPending}
        isError={preSpecProjectionQuery.isError}
        onRetry={() => { void preSpecProjectionQuery.refetch(); }}
        afterAnalysis={analysisView}
      />
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
