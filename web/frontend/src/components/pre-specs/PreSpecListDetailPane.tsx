import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Heading } from "@astryxdesign/core/Heading";
import { Token } from "@astryxdesign/core/Token";
import { Badge } from "../common/Badge";
import { getDocumentBundles } from "../deep-review/api";
import {
  BUNDLE_STATUS_LABELS,
  SAFETY_STATUS_LABELS,
  STRUCTURE_STATUS_LABELS,
} from "../deep-review/DocumentPreparationPanel";
import { CompanyFitSection } from "./CompanyFitSection";
import {
  isInheritedTracking,
  TrackingDecisionControl,
  updateTrackingProjection,
} from "./TrackingDecisionControl";
import { PageOverviewSection, useCurrentPageOverview } from "./PageOverviewSection";
import { DeadlineMark } from "./PreSpecListRow";
import { nextActionOf } from "../../lib/preSpecNextAction";
import { api } from "../../lib/api";
import { describeApiError } from "../../lib/apiErrors";
import { formatDateTime } from "../../lib/format";
import { gradeLabel, gradeSourceLabel } from "../../lib/grade";
import {
  agencyOf,
  attachmentAttention,
  exactBudget,
  originLabel,
  overviewStatusLabel,
  overviewTokenColor,
  titleOf,
  trackingLabel,
} from "../../lib/preSpecViews";
import {
  PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL,
  preSpecAutoPreparationReasonLabel,
} from "../../lib/preSpecAutoPreparation";
import {
  hasCanonicalOverviewNoticeId,
  PRE_SPEC_OVERVIEW_ATTEMPT_STATUS_LABEL,
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
  PRE_SPEC_OVERVIEW_VALIDATION,
  PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION,
} from "../../lib/preSpecOverviewStatus";
import { qualityStatusLabel, qualityStatusNote, qualityStatusVariant } from "../../lib/qualityStatus";
import type {
  PageOverviewCurrent,
  PageOverviewCurrentStatus,
  PageOverviewFactV4,
  PageOverviewPayloadV4,
  PageOverviewView,
  PreSpecListItem,
} from "../../lib/types";

type DetailTab = "overview" | "documents" | "history";

export const DETAIL_TABS: readonly { key: DetailTab; label: string }[] = [
  { key: "overview", label: "개요 검토" },
  { key: "documents", label: "첨부 문서" },
  { key: "history", label: "처리 이력" },
];

const TRACKING_REASON_PRESETS = [
  "후속 입찰공고 확인",
  "세부 과업·연계 범위 확인",
  "참여 자격·실적 확인 필요",
] as const;

/** 조회 실패 한 자리. 서버 raw message는 여기까지 오지 않고 `describeApiError`가
 * 옮긴 안전한 문구만 나온다(docs/security.md). 같은 화면에 alert가 여럿 생기지
 * 않도록 이 자리는 polite status로 알린다. */
export function DetailQueryError({
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
    <div className="pre-specs-detail-error" role="status">
      <strong>{title}</strong>
      <p>{problem.title} {problem.detail}{problem.code ? ` · 오류 코드 ${problem.code}` : ""}</p>
      <button className="interaction-control" type="button" onClick={onRetry}>다시 시도</button>
    </div>
  );
}

/** 새 계약에는 `stale`이 없다. 남은 자리를 위한 문장만 두고 상태를 지어내지 않는다. */
function overviewWaitingDescription(status: PageOverviewCurrentStatus): string {
  return status === "stale"
    ? "이전 입력 기준의 결과는 현재 결과로 쓸 수 없습니다. 사람 확인이 필요합니다."
    : PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION[status];
}

/** 결과 본문의 주장 전부. 섹션 순서를 유지한 채 근거 목록 하나로 모은다. */
function overviewClaims(payload: PageOverviewPayloadV4): PageOverviewFactV4[] {
  return [
    ...payload.business_overview,
    ...payload.main_tasks,
    ...payload.budget_and_period,
    ...payload.important_conditions,
  ];
}

/** 개요 결과 본문 — 시안의 세 구역(결과 · 확인 조건 · 문서 근거)이다.
 *
 * **모든 값은 서버의 개요 응답 그대로다.** 결과가 없으면 없다고 말하고
 * metadata에서 결론을 지어내지 않는다. 품질 표식과 검증 상태는 결과 머리줄에
 * 붙어 있어 결과를 읽는 자리에서 함께 보인다 — 참조 실행이나 검증 실패를 운영
 * 완료처럼 보이게 하지 않는다. 권고 문장은 새 계약에 없으므로 그 자리에는
 * 검증된 첫 주장을 둔다(모델의 권고로 읽히지 않게 요약과 같은 사실이다). */
export function OverviewResult({
  review,
  current,
  detailUrl,
}: {
  review: PageOverviewView | null;
  current: PageOverviewCurrent | null;
  detailUrl: string;
}) {
  const payload = review && review.payload.schema_version === "bidops.prespec-overview-page-review.v4"
    ? review.payload
    : null;
  const validation = PRE_SPEC_OVERVIEW_VALIDATION[review ? review.validation_status : "pending"];
  // 첫 주장은 결과 머리줄이 이미 보여 준다. 근거 목록이 같은 문장을 한 번 더
  // 그리면 한 카드 안에서 같은 사실이 두 번 읽힌다(ADR-0055 D7). 근거 건수는
  // 그려지는 주장 기준이므로 같은 목록에서 센다.
  const claims = payload ? overviewClaims(payload).filter((claim) => claim.claim_id !== payload.business_overview[0]?.claim_id) : [];
  const evidenceCount = claims.reduce((total, claim) => total + claim.evidence.length, 0);
  const summary = payload ? payload.business_overview.slice(1).map((fact) => fact.text).join(" ") : "";
  const pdfUrl = review ? api.preSpecOverviewRunPdfUrl(review.notice_id, review.id) : null;
  return (
    <div className="pre-specs-overview">
      <section className="pre-specs-overview-section is-result" aria-labelledby="pre-specs-overview-result">
        <div className="pre-specs-overview-section-head">
          <h4 id="pre-specs-overview-result">개요 검토 결과</h4>
          {/* 품질 표식은 결과를 읽는 자리에 붙는다. 뜻을 적은 문장은 tooltip과
              `표시 범위` 대화상자가 갖고, 기본 화면에는 표식만 둔다. */}
          <span className="pre-specs-overview-quality" title={qualityStatusNote(review?.quality_status ?? null)}>
            <Token size="sm" label={qualityStatusLabel(review?.quality_status ?? null)} color="default" />
          </span>
        </div>
        {payload ? (
          <>
            <p className={`pre-specs-overview-recommendation${review?.validation_status === "passed" ? "" : " is-unverified"}`}>
              {payload.business_overview[0]?.text ?? "검토 결과 미확정"}
              <span className="pre-specs-overview-validation">{validation.label}</span>
            </p>
            {summary ? <p className="pre-specs-overview-summary">{summary}</p> : null}
          </>
        ) : (
          <>
            <p className="pre-specs-overview-recommendation is-unverified">
              검토 결과 미확정
              <span className="pre-specs-overview-validation">{validation.label}</span>
            </p>
            <p className="pre-specs-overview-summary">
              {current ? overviewWaitingDescription(current.status) : "개요 검토 실행이 아직 없습니다."}
            </p>
          </>
        )}
        {validation.warning ? <p className="pre-specs-overview-warning" role="status">{validation.warning}</p> : null}
      </section>

      {payload ? (
        <>
          {payload.important_conditions.length > 0 ? (
            <section className="pre-specs-overview-section" aria-labelledby="pre-specs-overview-conditions">
              <div className="pre-specs-overview-section-head">
                <h4 id="pre-specs-overview-conditions">확인 조건</h4>
                {/* 확인 기한은 새 계약에 없다. 미지정 문구를 지어내지 않고 자리를 비운다. */}
              </div>
              <ul className="pre-specs-overview-list">
                {payload.important_conditions.map((condition) => <li key={condition.claim_id}>{condition.text}</li>)}
              </ul>
            </section>
          ) : null}

          <section className="pre-specs-overview-section" aria-labelledby="pre-specs-overview-evidence">
            <div className="pre-specs-overview-section-head">
              <h4 id="pre-specs-overview-evidence">문서 근거</h4>
              <span>{evidenceCount}건</span>
            </div>
            {claims.length > 0 ? (
              <ul className="pre-specs-overview-evidence">
                {claims.map((claim) => (
                  <li key={claim.claim_id}>
                    <p>{claim.text}</p>
                    <span className="pre-specs-overview-locator" aria-label="근거 위치">
                      {claim.evidence.map((evidence) => (
                        <a
                          key={`${claim.claim_id}-${evidence.page}`}
                          href={`${pdfUrl}#page=${evidence.page}`}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {evidence.page}쪽
                        </a>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            ) : <p className="pre-specs-overview-empty">근거 항목 없음</p>}
            {/* 원문 열람은 상세 화면이 소유한다. 이 자리에서 원문을 여는 흉내를
                내지 않고 실제로 여는 화면으로 보낸다. */}
            <Link className="pre-specs-overview-source-link" to={detailUrl}>상세에서 근거 원문 열기 →</Link>
          </section>

          {/* 미확인 목록은 위 개요 구역(`PageOverviewUnknowns`)이 이미 갖는다. 같은 탭
              안에서 두 번 적지 않는다(ADR-0055 D7). */}

          {payload.input_limitations.length > 0 ? (
            <p className="pre-specs-overview-note">
              이 판단의 한계 · {payload.input_limitations.join(" ")}
            </p>
          ) : null}
        </>
      ) : null}

      <p className="pre-specs-overview-note">
        개요 결과는 추적 상태·참여 준비·최종 Go/No-Go를 대신하지 않습니다.
      </p>
    </div>
  );
}

/**
 * 선택한 사전규격 하나.
 *
 * 목록 응답에 있는 사실(기관·예산·마감·등급·자동 준비·첨부 집계·추적 상태)과
 * 별도 endpoint인 개요 검토 응답을 각자 자리에서 보여 준다. 목록 응답만으로 개요
 * 본문을 만들지 않는다.
 */
export function PreSpecDetail({
  item,
  listSearch,
  onDirtyChange,
  onSaved,
  onTrackingDialogChange,
  trackingDialogOpen,
  trackingCloseRequested,
  onTrackingCloseCancel,
  onTrackingCloseConfirm,
}: {
  item: PreSpecListItem;
  listSearch: string;
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (saved: Parameters<typeof updateTrackingProjection>[2]) => void;
  onTrackingDialogChange: (open: boolean) => void;
  trackingDialogOpen: boolean;
  trackingCloseRequested: boolean;
  onTrackingCloseCancel: () => void;
  onTrackingCloseConfirm: () => void;
}) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<DetailTab>("overview");
  const noticePk = item.notice_pk;
  const detailUrl = `/pre-specs/${noticePk}${listSearch ? `?${listSearch}` : ""}`;

  // 개요 본문과 같은 query를 읽는다(같은 key라 요청이 늘지 않는다). 이력 탭은
  // 결과가 남은 실행만 나열하고 상태를 다시 판정하지 않는다.
  const pageOverview = useCurrentPageOverview(noticePk);
  const overviewQuery = pageOverview.query;
  // 응답이 이 공고의 정본인지만 본다. 어긋나면 다른 공고의 결과를 그리지 않는다.
  const overviewInvalid = overviewQuery.isSuccess
    && !hasCanonicalOverviewNoticeId(overviewQuery.data, noticePk);
  const overviewValid = pageOverview.isValid && !overviewInvalid;
  const overviewRuns = overviewValid
    ? [...(pageOverview.currentResult ? [pageOverview.currentResult] : []), ...pageOverview.history]
    : [];
  const overviewCurrent = overviewValid ? pageOverview.current : null;
  const overviewReview = overviewValid ? pageOverview.currentResult ?? pageOverview.legacyReview : null;
  const overviewMissing = overviewValid && overviewCurrent === null && overviewReview === null;
  const overviewRangeReview = overviewValid ? pageOverview.rangeReview : null;

  // 첨부 문서는 사람이 그 탭을 열 때만 조회한다. 목록을 훑는 동안 문서 API를
  // 부르지 않는다.
  const bundleQuery = useQuery({
    queryKey: ["document-bundles", noticePk],
    queryFn: () => getDocumentBundles(noticePk),
    enabled: tab === "documents",
    staleTime: 30_000,
  });

  const latestBundle = [...(bundleQuery.data?.items ?? [])].sort((left, right) => right.revision - left.revision)[0] ?? null;
  const autoReason = preSpecAutoPreparationReasonLabel(item.auto_preparation_reason);
  const inherited = isInheritedTracking(item);
  // 연결이 없으면 `사업기회 미연결`, 연결은 있는데 값이 없으면 `미확인`이다.
  // 둘 중 어느 것도 사람이 고른 `미선택`으로 바꾸지 않는다.
  const trackingText = trackingLabel(item);

  // 다음 작업은 한 문장이고 그 규칙은 `lib/preSpecNextAction`이 혼자 소유한다.
  // 안내 문장일 뿐이며 추적 선택·심층 검토 승인 버튼을 숨기거나 대신하지 않는다.
  const nextAction = { title: "다음 작업", text: nextActionOf(item) };

  return (
    <div className="pre-specs-detail">
      <header className="pre-specs-detail-header">
        <div className="pre-specs-detail-agency">
          <span>발주기관</span>
          <strong>{agencyOf(item)}</strong>
        </div>
        <div className="pre-specs-detail-title">
          <Heading level={3}>{titleOf(item)}</Heading>
        </div>
        <div className="pre-specs-detail-identity">
          <span>
            사전규격 {item.pre_spec_no ? <code className="mono">{item.pre_spec_no}</code> : "번호 미확인"}
          </span>
          <span aria-hidden="true">·</span>
          <span>{originLabel(item.origin)}</span>
          <span className="pre-specs-detail-identity-end">
            <Token size="sm" label={trackingText} color="default" />
          </span>
        </div>
        <dl className="pre-specs-detail-facts">
          <div>
            <dt>사업 예산</dt>
            <dd>{exactBudget(item.budget)}</dd>
          </div>
          <div>
            <dt>의견등록 마감</dt>
            <dd className="pre-specs-detail-deadline">
              <span>{item.deadline_at ? formatDateTime(item.deadline_at) : "마감 일시 없음"}</span>
              <DeadlineMark value={item.deadline_at} />
            </dd>
          </div>
          <div>
            <dt>적합성 등급</dt>
            <dd>{gradeLabel(item.grade)}</dd>
          </div>
        </dl>
        <p className="pre-specs-detail-meta">
          {item.business_division?.trim() || "업무구분 미확인"}
          {" · SW사업대상 "}
          {item.sw_business_status === null ? "미확인" : item.sw_business_status}
          {" · 등급 출처 "}
          {gradeSourceLabel(item.grade_source)}
          {" · 게시 "}
          {formatDateTime(item.published_at)}
        </p>
      </header>

      <nav className="pre-specs-detail-tabs" aria-label="사전규격 상세 정보">
        {DETAIL_TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            className="pre-specs-detail-tab"
            aria-pressed={tab === entry.key}
            onClick={() => setTab(entry.key)}
          >
            {entry.label}
          </button>
        ))}
      </nav>

      <div className="pre-specs-detail-scroll">
        {tab === "overview" ? (
          <>
            <ol className="pre-specs-process" aria-label="자동 준비 진행">
              <li>
                <span>첨부</span>
                <strong>{item.document["완료"] > 0 ? `취득 ${item.document["완료"]}건` : item.document.attachments > 0 ? "취득 대기" : "첨부 없음"}</strong>
                {attachmentAttention(item) ? (
                  <span className="pre-specs-process-detail">{attachmentAttention(item)}</span>
                ) : null}
              </li>
              <li aria-hidden="true" className="pre-specs-process-arrow">›</li>
              <li>
                <span>개요</span>
                <Token
                  size="sm"
                  label={overviewStatusLabel(item.overview_review_status)}
                  color={overviewTokenColor(item.overview_review_status)}
                />
              </li>
              <li aria-hidden="true" className="pre-specs-process-arrow">›</li>
              <li>
                <span>심층</span>
                <strong>{PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL[item.auto_preparation_status]}</strong>
                {autoReason ? <span className="pre-specs-process-detail">{autoReason}</span> : null}
              </li>
            </ol>

            {/* 범위 확정·현재 실행·검증된 본문·이전 결과는 이 구역이 갖는다.
                아래 `OverviewResult`는 목록 전용 요약(결과 머리·확인 조건·문서 근거
                건수·상세 링크)라 역할이 다르다. */}
            <PageOverviewSection key={noticePk} noticeId={noticePk} />
            <CompanyFitSection key={`fit-${noticePk}`} noticeId={noticePk} compact />
            {/* 불러오는 중·조회 실패 문구는 위 구역이 이미 말한다. 여기서 반복하면
                같은 문장이 화면에 둘이 된다. 교차 응답·기록 없음만 이 자리가 맡는다. */}
            {overviewQuery.isSuccess && !overviewValid ? (
              <div className="pre-specs-detail-error" role="status">
                <strong>개요 검토 결과를 확인할 수 없습니다.</strong>
                <p>다른 공고의 응답이 와 개요 검토를 표시하지 않습니다.</p>
              </div>
            ) : null}
            {overviewMissing ? (
              <div className="pre-specs-detail-empty-block">
                <strong>개요 검토 기록이 없습니다.</strong>
                <p>서버가 제공한 개요 검토 기록이 없습니다. 목록의 상태와 다른 결과를 만들어 내지 않습니다.</p>
              </div>
            ) : null}
            {/* 목록 pane의 결과 본문은 이 구역 하나다(결과·확인 조건·문서 근거).
                예전에는 wrapper가 같은 주장을 한 번 더 그려 본문이 둘이었다(ADR-0055 D7). */}
            {overviewValid && !overviewMissing ? (
              <OverviewResult review={overviewReview} current={overviewCurrent} detailUrl={detailUrl} />
            ) : null}
          </>
        ) : null}

        {tab === "documents" ? (
          <div className="pre-specs-documents">
            <section className="pre-specs-overview-section" aria-labelledby="pre-specs-documents-counts">
              <div className="pre-specs-overview-section-head">
                <h4 id="pre-specs-documents-counts">첨부 원문 취득 집계</h4>
                <span>{item.document.attachments}건</span>
              </div>
              <dl className="pre-specs-document-counts">
                <div><dt>완료</dt><dd>{item.document["완료"]}건</dd></div>
                <div><dt>대기</dt><dd>{item.document["대기"]}건</dd></div>
                <div><dt>진행</dt><dd>{item.document["진행"]}건</dd></div>
                <div><dt>차단</dt><dd>{item.document["차단"]}건</dd></div>
                <div><dt>실패</dt><dd>{item.document["실패"]}건</dd></div>
              </dl>
            </section>

            <section className="pre-specs-overview-section" aria-labelledby="pre-specs-documents-bundle">
              <div className="pre-specs-overview-section-head">
                <h4 id="pre-specs-documents-bundle">문서 묶음</h4>
                <span>{latestBundle ? `수정본 ${latestBundle.revision}` : "묶음 없음"}</span>
              </div>
              {bundleQuery.isPending ? (
                <p className="pre-specs-detail-loading" role="status">문서 묶음을 불러오는 중입니다.</p>
              ) : null}
              {bundleQuery.isError ? (
                <DetailQueryError
                  error={bundleQuery.error}
                  fallback="문서 묶음 API 응답을 확인할 수 없습니다."
                  onRetry={() => { void bundleQuery.refetch(); }}
                  title="문서 묶음을 불러오지 못했습니다."
                />
              ) : null}
              {bundleQuery.isSuccess && !latestBundle ? (
                <p className="pre-specs-overview-empty">이 사전규격에는 아직 문서 묶음이 없습니다. 초안으로 보정하지 않습니다.</p>
              ) : null}
              {latestBundle ? (
                <>
                  <p className="pre-specs-document-bundle-status">
                    묶음 상태 · {BUNDLE_STATUS_LABELS[latestBundle.status]}
                  </p>
                  {latestBundle.documents.length > 0 ? (
                    <ul className="pre-specs-document-list">
                      {latestBundle.documents.map((document) => (
                        <li key={document.id}>
                          <strong>{document.original_filename}</strong>
                          <span>
                            {document.role} · {SAFETY_STATUS_LABELS[document.safety_status]} · {STRUCTURE_STATUS_LABELS[document.structure_status]}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : <p className="pre-specs-overview-empty">묶음에 등록된 문서가 없습니다.</p>}
                  {latestBundle.issues.length > 0 ? (
                    <ul className="pre-specs-document-issues">
                      {latestBundle.issues.map((issue) => (
                        <li key={issue.issue_id}>
                          <Badge label={issue.severity} variant={issue.blocking ? "danger" : "alert"} />
                          <span>{issue.message}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : null}
            </section>

            {/* 문서 등록·변경·확정과 다운로드는 상세 화면의 문서 준비가 소유한다.
                여기서 동작하는 것처럼 보이는 버튼을 만들지 않는다. */}
            <p className="pre-specs-detail-note">
              문서 등록·교체·묶음 확정과 원문 열람은 사전규격 상세의 문서 준비에서 수행합니다.
              {" "}
              <Link to={detailUrl}>상세 열기 →</Link>
            </p>
          </div>
        ) : null}

        {tab === "history" ? (
          <div className="pre-specs-history">
            <section className="pre-specs-overview-section" aria-labelledby="pre-specs-history-runs">
              <div className="pre-specs-overview-section-head">
                <h4 id="pre-specs-history-runs">개요 실행 이력</h4>
                <span>{overviewValid ? `${overviewRuns.length}건` : "확인 중"}</span>
              </div>
              {overviewQuery.isError ? (
                <DetailQueryError
                  error={overviewQuery.error}
                  fallback="개요 검토 API 응답을 확인할 수 없습니다."
                  onRetry={() => { void overviewQuery.refetch(); }}
                  title="개요 실행 이력을 불러오지 못했습니다."
                />
              ) : null}
              <p className="pre-specs-overview-note">
                현재 실행 · {overviewCurrent === null
                  ? (item.overview_review_status === null
                    ? PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL
                    : PRE_SPEC_OVERVIEW_STATUS_LABEL[item.overview_review_status])
                  : overviewCurrent.status === "stale"
                    ? "현재성 확인 필요"
                    : PRE_SPEC_OVERVIEW_ATTEMPT_STATUS_LABEL[overviewCurrent.status]}
              </p>
              {/* 결과 본문이 남은 실행만 여기 온다. 실패·취소한 실행의 사유는 위
                  개요 자리의 현재 실행 카드가 말한다. */}
              {overviewValid && overviewRuns.length === 0 ? (
                <p className="pre-specs-overview-empty">결과가 남은 개요 실행이 없습니다.</p>
              ) : null}
              {overviewValid && overviewRuns.length > 0 ? (
                <ul className="pre-specs-history-list">
                  {overviewRuns.map((review) => (
                    <li key={review.id}>
                      <span>{formatDateTime(review.created_at)}</span>
                      <Badge label={qualityStatusLabel(review.quality_status)} variant={qualityStatusVariant(review.quality_status)} />
                      <span>{PRE_SPEC_OVERVIEW_VALIDATION[review.validation_status].label}</span>
                      <span>{review.model_name}</span>
                      <span className="mono">결과 ID {review.id}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              {!overviewValid && !overviewQuery.isPending && !overviewQuery.isError ? (
                <p className="pre-specs-overview-empty">개요 실행 이력을 확인할 수 없습니다.</p>
              ) : null}
            </section>

            <section className="pre-specs-overview-section" aria-labelledby="pre-specs-history-inputs">
              <h4 id="pre-specs-history-inputs">고정 입력과 식별 해시</h4>
              {/* 절단 전략·구조 버전은 새 계약에 없다. 남은 것은 스냅샷과 결과의
                  해시, 그리고 그 결과를 만든 모델·프롬프트다. */}
              {overviewRuns[0] ? (
                <dl className="pre-specs-history-facts">
                  <div><dt>원본 해시</dt><dd className="mono">{overviewRuns[0].source_sha256 || "없음"}</dd></div>
                  <div><dt>PDF 해시</dt><dd className="mono">{overviewRuns[0].pdf_sha256 || "없음"}</dd></div>
                  <div><dt>결과 해시</dt><dd className="mono">{overviewRuns[0].payload_sha256 || "없음"}</dd></div>
                  <div><dt>프롬프트</dt><dd>{overviewRuns[0].prompt_version || "없음"}</dd></div>
                  <div><dt>모델</dt><dd>{overviewRuns[0].model_name || "없음"}</dd></div>
                  <div><dt>모델 버전</dt><dd className="mono">{overviewRuns[0].model_revision ?? "없음"}</dd></div>
                </dl>
              ) : <p className="pre-specs-overview-empty">현재 고정 입력이 없습니다.</p>}
            </section>

            <section className="pre-specs-overview-section" aria-labelledby="pre-specs-history-tracking">
              <h4 id="pre-specs-history-tracking">사람의 선택과 자동 준비</h4>
              <dl className="pre-specs-history-facts">
                <div><dt>추적 선택</dt><dd>{trackingText}</dd></div>
                <div>
                  <dt>자동 준비</dt>
                  <dd>
                    {PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL[item.auto_preparation_status]}
                    {autoReason ? ` · ${autoReason}` : ""}
                  </dd>
                </div>
                <div>
                  <dt>자동 시작된 심층 검토</dt>
                  <dd>
                    {item.latest_deep_review_id
                      ? <Link to={`/deep-reviews/${item.latest_deep_review_id}`}>보고서 열기 →</Link>
                      : "시작 기록 없음"}
                  </dd>
                </div>
              </dl>
              <p className="pre-specs-detail-note">자동 분석의 시작은 사람의 추적 선택과 별개입니다.</p>
            </section>
          </div>
        ) : null}
      </div>

      {/* 결정 블록은 본문 스크롤과 무관하게 늘 보인다. 위는 **사람의 추적 선택**,
          아래는 다음 작업이다. 두 줄은 서로 다른 결정이며 추적 선택이 모델 분석
          승인이나 최종 Go/No-Go를 뜻하지 않는다. */}
      <footer className="pre-specs-detail-actions" id="pre-specs-tracking-target">
        <div className="pre-specs-action-row">
          <div>
            <span>사람의 추적 선택</span>
            <strong>
              {trackingText}
              {inherited ? " · 발주계획에서 이어짐" : ""}
            </strong>
          </div>
          <Button
            label="추적 선택 변경"
            size="sm"
            onClick={() => onTrackingDialogChange(true)}
          />
        </div>
        <div className="pre-specs-action-row">
          <div>
            <span>{nextAction.title}</span>
            <strong>{nextAction.text}</strong>
          </div>
          <Link className="interaction-control interaction-control-primary pre-specs-detail-open" to={detailUrl}>
            상세 검토 열기 →
          </Link>
        </div>
      </footer>

      <Dialog
        isOpen={trackingDialogOpen}
        onOpenChange={(open) => onTrackingDialogChange(open)}
        purpose="form"
        width={620}
      >
        <DialogHeader
          title="추적 선택"
          subtitle={titleOf(item)}
          onOpenChange={() => onTrackingDialogChange(false)}
        />
        <div className="pre-specs-dialog-body">
          {/* 저장하지 않은 입력이 있는데 창을 닫으려 하면 이 확인이 먼저 뜬다.
              modal 창 위에는 다른 창이 올라오지 못하므로 확인을 같은 창 안에 둔다. */}
          {trackingCloseRequested ? (
            <div className="pre-specs-dialog-guard" role="alert">
              <strong>저장하지 않은 추적 결정 사유와 담당자 이름이 있습니다.</strong>
              <p>지금 닫으면 입력이 사라지며 저장된 추적 상태는 바뀌지 않습니다.</p>
              <div>
                <button className="interaction-control" type="button" onClick={onTrackingCloseCancel}>계속 편집</button>
                <button className="interaction-control" type="button" onClick={onTrackingCloseConfirm}>저장하지 않고 닫기</button>
              </div>
            </div>
          ) : null}
          <TrackingDecisionControl
            key={noticePk}
            item={item}
            isPending={false}
            isError={false}
            onRetry={() => { void overviewQuery.refetch(); }}
            headingLevel="h4"
            compact
            reasonPresets={TRACKING_REASON_PRESETS}
            onDirtyChange={onDirtyChange}
            // 발주계획에서 승계한 건은 이 화면이 추적을 다시 묻지 않으므로
            // 한 조작 진입점도 신규 건에만 준다(ADR-0046 결정 6).
            onStartedForDeepReview={inherited ? undefined : () => navigate(detailUrl)}
            onSaved={(saved) => {
              onSaved(saved);
              onTrackingDialogChange(false);
            }}
          />
        </div>
      </Dialog>
    </div>
  );
}


