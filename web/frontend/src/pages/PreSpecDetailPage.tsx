import { Button } from "@astryxdesign/core/Button";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { BUNDLE_STATUS_LABELS, DocumentPreparationPanel } from "../components/deep-review/DocumentPreparationPanel";
import { getDocumentBundles } from "../components/deep-review/api";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { ReviewHistoryLinkRail } from "../components/common/ReviewPrimitives";
import { SkeletonPanel } from "../components/common/Skeleton";
import { PreSpecDocumentSummary, TrackingDecisionControl, updateTrackingProjection } from "../components/pre-specs/TrackingDecisionControl";
import { api } from "../lib/api";
import { PreSpecRecordIdentity } from "../components/pre-specs/PreSpecRecordIdentity";
import { OverviewSection } from "../components/pre-specs/OverviewSection";
import {
  CompanyFitAutomationNotice,
  CompanyFitExecutionInfo,
  CompanyFitReasons,
  CompanyFitVerdict,
  NO_CURRENT_ATTEMPT_NOTICE,
  useCompanyFit,
} from "../components/pre-specs/CompanyFitSection";
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
import type { PreSpecListResponse } from "../lib/types";
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
  const companyFitState = useCompanyFit(noticeId);
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
  const { query: companyFitQuery } = companyFitState;
  const companyFitData = companyFitState.isValid ? companyFitState.data : null;
  const currentCompanyFitAttempt = companyFitState.isValid ? companyFitState.currentAttempt : null;
  const previousCompanyFitAttempts = companyFitState.isValid ? companyFitState.previousAttempts : [];
  const companyFitVerificationItems = currentCompanyFitAttempt?.result?.verification_items ?? [];
  const checkCount = companyFitVerificationItems.length;
  const historyIsOpen = currentCompanyFitAttempt?.status === "failed"
    || currentCompanyFitAttempt?.status === "needs_human_review"
    || latestBundle?.status === "failed"
    || latestBundle?.status === "quarantined"
    || latestBundle?.status === "needs_review";
  const trackingStatusLabel = preSpecItem?.opportunity_id == null
    ? "사업기회 미연결"
    : preSpecItem.tracking_status === "계속 추적"
      ? "추적 중"
      : preSpecItem.tracking_status === "종료"
        ? "추적 종료"
        : preSpecItem.tracking_status ?? "미확인";
  const companyFitDecision = currentCompanyFitAttempt?.result?.decision ?? "unknown";

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
              {preSpecItem?.business_division ? <span className="ps-chip ps-chip-accent">{preSpecItem.business_division}</span> : null}
            </div>
            <h2 id="pre-spec-detail-title" className="ps-h-page">{present(notice.title, "사업명 미확인")}</h2>
            <div className="ps-record-meta">
              <span className="ps-record-agency">{present(notice.agency, "발주기관 미확인")}</span>
              <span aria-hidden="true">·</span>
              <PreSpecRecordIdentity key={noticeId} number={preSpecNumber} url={notice.url} />
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

              <DocumentPreparationPanel
                noticeId={notice.id}
                // 헤더가 보여 주는 것과 **같은 현재 등급**을 넘긴다. `notice.grade`는
                // 사람 정정을 반영하지 않아 헤더와 다른 값을 말할 수 있다(명세 §6.2).
                currentGrade={preSpecItem?.grade ?? null}
                onDeepReviewCreated={(review) => navigate(`/deep-reviews/${review.id}`)}
              />
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

          {/* 개요 검토는 문서 준비 뒤, 회사 핏 앞이다. 준비된 문서에서 무엇을
              읽었는지 먼저 보고 그다음 회사와 대조한다. */}
          <div id="ps-record-overview" className="ps-record-section" tabIndex={-1}>
            <OverviewSection noticeId={notice.id} />
          </div>

          <div id="ps-record-history" className="ps-record-section ps-record-history ps-collapsed" tabIndex={-1}>
            <Collapsible key={historyIsOpen ? "history-open" : "history-closed"} trigger="처리 이력과 실행 정보" defaultIsOpen={historyIsOpen}>
              <ReviewHistoryLinkRail
                className="detail-skeleton-rail"
                historySections={[{
                  className: "detail-skeleton-rail-panel",
                  content: <p className="detail-skeleton-rail-note">개요 검토의 입력 범위와 실행 이력은 위 개요 검토 자리에서 봅니다.</p>,
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

            <dl className="ps-kv">
              <div><dt className="ps-k">추적 상태</dt><dd>{preSpecItem?.tracking_status ?? "미확인"}</dd></div>
              <div><dt className="ps-k">자동 준비</dt><dd>{autoStatus ? `${PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL[autoStatus]}${autoReasonLabel ? ` · ${autoReasonLabel}` : ""}` : "미확인"}</dd></div>
            </dl>
          </RecordSection>

          <RecordSection title="확인이 필요한 것" count={String(checkCount)}>
            {checkCount === 0 ? <p className="pre-spec-overview-empty">추가 조건·미확인 항목 없음</p> : (
              <div className="ps-check-groups">
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

          <section className="company-fit ps-card ps-sec" aria-label="회사 업무 부합 여부">
            <div className="ps-sec-head"><h3 className="ps-h-sec">회사 업무 부합 여부</h3></div>
            <p className="company-fit-note">개요의 과업과 회사 정보를 대조한 분석입니다. 추적 승인과 최종 입찰 결정은 사람이 진행합니다.</p>
            {companyFitQuery.isPending ? <p role="status">회사 핏 판정을 불러오는 중입니다.</p> : companyFitQuery.isError ? <div role="alert">
              <p>회사 핏 판정을 불러오지 못했습니다.</p>
              <Button label="회사 핏 다시 불러오기" size="sm" onClick={() => { void companyFitQuery.refetch(); }} />
            </div> : !companyFitState.isValid || companyFitData === null ?
              <p role="alert">판정 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.</p> : <>
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
        </div>
      </div>
    </section>
  );
}
