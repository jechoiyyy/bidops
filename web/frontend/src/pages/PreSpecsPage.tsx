import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Heading } from "@astryxdesign/core/Heading";
import { Selector } from "@astryxdesign/core/Selector";
import { Token } from "@astryxdesign/core/Token";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { DenseList, DenseListRow, SplitWorkspace } from "../components/common/ReviewPrimitives";
import {
  WorkspaceAdvancedToggle,
  WorkspaceFilterAdvanced,
  WorkspaceFilterBar,
  WorkspaceFilterContext,
  WorkspaceFilterEnd,
  WorkspaceFilterLine,
  WorkspaceFrame,
  WorkspaceSearch,
  WorkspaceViewTabs,
} from "../components/common/WorkspaceFilters";
import { getDocumentBundles } from "../components/deep-review/api";
import {
  BUNDLE_STATUS_LABELS,
  SAFETY_STATUS_LABELS,
  STRUCTURE_STATUS_LABELS,
} from "../components/deep-review/DocumentPreparationPanel";
import {
  isInheritedTracking,
  TrackingDecisionControl,
  updateTrackingProjection,
} from "../components/pre-specs/TrackingDecisionControl";
import { api } from "../lib/api";
import { CompanyFitSection } from "../components/pre-specs/CompanyFitSection";
import { PageOverviewSection, useCurrentPageOverview } from "../components/pre-specs/PageOverviewSection";
import { describeApiError } from "../lib/apiErrors";
import { describeDeadline, formatCompactPrice, shortDateLabel } from "../lib/deadline";
import { formatDateTime, formatNumber } from "../lib/format";
import { GRADE_NONE_LABEL, GRADE_ORDER, gradeLabel, gradeSourceLabel } from "../lib/grade";
import { originOf } from "../lib/opportunity";
import {
  PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL,
  preSpecAutoPreparationReasonLabel,
  preSpecAutoPreparationVariant,
} from "../lib/preSpecAutoPreparation";
import {
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
} from "../lib/preSpecOverviewStatus";
import { qualityStatusLabel, qualityStatusVariant } from "../lib/qualityStatus";
import type {
  PreSpecListItem,
  PreSpecListResponse,
  PreSpecOrigin,
  PreSpecOverviewReviewStatus,
  PreSpecSort,
} from "../lib/types";
import "../styles/pre-specs-relaxed.css";

/**
 * 사전규격 업무 화면 — 승인 시안(`bidops-pre-specs-erp-20260907`)의 ERP 작업 표면.
 *
 * 골격은 발주계획 검토 화면과 같다: 압축 필터 한 덩어리 아래 목록 38% / 상세 62%가
 * 셸 canvas 높이를 채우고, 스크롤은 목록과 상세 본문 안에서만 일어난다. 그래서
 * 상세 바닥의 추적 선택과 다음 작업은 늘 보인다.
 *
 * 이 화면이 정하는 것은 **사람의 추적 선택 하나**다. 개요 권고, 적합성 등급,
 * 참여 준비 상태, 최종 입찰 Go/No-Go는 서로를 대신하지 않는다(CLAUDE.md 강제 게이트).
 * 화면은 서버가 준 값을 옮길 뿐 등급·상태·건수를 다시 계산하지 않는다.
 */

// 한 페이지에 200건. 서버 한도(500) 안이고, 상단 보기로 좁히는 경우가 대부분이라
// 이 크기면 한 화면에서 보기와 목록이 대체로 일치한다. 그래도 전체 건수가 페이지
// 크기를 넘으면 **보기 버튼의 건수(서버 전체 집계)와 실제로 보이는 행 수가 다르다.**
// 그 사실은 목록 바닥과 부분 표시 문구가 글자로 밝힌다 — 조용히 숨기지 않는다.
const PAGE_SIZE = 200;
const BUSINESS_DIVISIONS = ["일반용역", "기술용역"] as const;
const ORIGINS: PreSpecOrigin[] = ["추적", "신규"];

// 등급 필터 URL 계약: 허용값은 계약의 등급 4값과 `판정 없음`(= `grade`가 null)뿐이다.
//
// **서버 `GET /api/pre-specs`에는 `grade` 질의 인자가 없다**(docs/contracts.md).
// 그래서 이 필터는 불러온 페이지에만 적용되고, 서버가 준 상태별 건수
// (`overview_status_counts`)는 등급 필터 이전 기준이다. 그 비대칭을 화면이 직접
// 문장으로 밝힌다.
const GRADE_FILTER_VALUES = [...GRADE_ORDER, GRADE_NONE_LABEL] as const;
type GradeFilter = (typeof GRADE_FILTER_VALUES)[number] | "";

/**
 * 상단 보기는 **탐색 묶음**이지 새로운 업무 상태가 아니다.
 *
 * 각 행은 서버가 준 개별 개요 상태를 그대로 보여 주고, 보기는 11개 상태값을 사람이
 * 찾는 순서로 묶어 목록을 좁힐 뿐이다. `취소`는 실패와 뜻이 다르므로 실패 묶음에
 * 넣지 않고 자기 보기를 갖는다. 그래서 10값 + 미시작(null) 전부가 어느 보기에든
 * 도달한다 — 어떤 상태도 보기 밖으로 사라지지 않는다.
 */
type ViewKey = "all" | "attention" | "pending" | "completed" | "failed" | "cancelled";

interface ViewDefinition {
  key: ViewKey;
  label: string;
  /** `null`이면 전체(상태로 좁히지 않음). 그 밖에는 이 상태 집합만 남긴다. */
  statuses: readonly (PreSpecOverviewReviewStatus | null)[] | null;
  description: string;
}

/**
 * 나열 순서는 **사람이 찾는 차례**다(사용자 결정 2026-09-08): 먼저 전체를 보고,
 * 끝난 건(`개요 완료`)을 확인한 뒤, 손이 필요한 건(`사람 확인`)과 아직 도는 건
 * (`진행·대기`)으로 내려가고, 예외인 `실패`·`취소`가 마지막이다. 묶음의 뜻과 key는
 * 그대로이므로 `validView`·`viewOf`·`viewCounts`는 영향을 받지 않는다.
 */
const VIEWS: readonly ViewDefinition[] = [
  { key: "all", label: "전체", statuses: null, description: "현재 필터에 맞는 사전규격 전체" },
  { key: "completed", label: "개요 완료", statuses: ["completed"], description: "개요 검토가 완료된 건" },
  { key: "attention", label: "사람 확인", statuses: ["needs_human_review"], description: "개요 입력 범위나 결과를 사람이 확인해야 하는 건" },
  {
    key: "pending",
    label: "진행·대기",
    statuses: [null, "awaiting_document", "awaiting_structure", "preparing", "awaiting_model", "queued", "running"],
    description: "개요 검토를 아직 시작하지 않았거나 준비·실행을 기다리는 건",
  },
  { key: "failed", label: "실패", statuses: ["failed"], description: "개요 검토가 실패한 건" },
  { key: "cancelled", label: "취소", statuses: ["cancelled"], description: "개요 검토 실행이 취소된 건" },
];

/**
 * 표시 순서. 기본값 `published`는 URL에 싣지 않으므로 인자가 없으면 게시 최신순이다.
 * 정렬은 서버 질의 인자이고 화면이 다시 줄 세우지 않는다.
 */
const SORT_OPTIONS: readonly { value: PreSpecSort; label: string }[] = [
  { value: "published", label: "게시 최신순" },
  { value: "deadline", label: "마감 임박순" },
];

/** 추적 결정 사유로 자주 쓰는 문장. 예시일 뿐이며 저장되는 값은 사람이 적은 사유다. */
const TRACKING_REASON_PRESETS = [
  "후속 입찰공고 확인",
  "세부 과업·연계 범위 확인",
  "참여 자격·실적 확인 필요",
] as const;

/** 상세 필터 Selector의 "전체"를 나타내는 표식값. URL에는 실리지 않는다. */
const ALL_OPTION = "__all__";

type DetailTab = "overview" | "documents" | "history";

const DETAIL_TABS: readonly { key: DetailTab; label: string }[] = [
  { key: "overview", label: "개요 검토" },
  { key: "documents", label: "첨부 문서" },
  { key: "history", label: "처리 이력" },
];

function validGrade(value: string | null): GradeFilter {
  return value && (GRADE_FILTER_VALUES as readonly string[]).includes(value) ? (value as GradeFilter) : "";
}

function matchesGradeFilter(item: PreSpecListItem, grade: GradeFilter): boolean {
  if (!grade) return true;
  if (grade === GRADE_NONE_LABEL) return item.grade === null;
  return item.grade === grade;
}

function validView(value: string | null): ViewKey {
  const found = VIEWS.find((view) => view.key === value);
  return found ? found.key : "all";
}

function viewOf(key: ViewKey): ViewDefinition {
  return VIEWS.find((view) => view.key === key) ?? VIEWS[0];
}

function matchesView(item: PreSpecListItem, key: ViewKey): boolean {
  const statuses = viewOf(key).statuses;
  if (statuses === null) return true;
  return statuses.includes(item.overview_review_status);
}

function validDivision(value: string | null): string {
  return value && BUSINESS_DIVISIONS.includes(value as (typeof BUSINESS_DIVISIONS)[number]) ? value : "";
}

function validOrigin(value: string | null): PreSpecOrigin | "" {
  return value && ORIGINS.includes(value as PreSpecOrigin) ? (value as PreSpecOrigin) : "";
}

function validSort(value: string | null): PreSpecSort {
  return value === "deadline" ? "deadline" : "published";
}

function readOffset(value: string | null): number {
  const parsed = Number(value ?? "0");
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
}

/** 목록의 예산. 좁은 pane에 맞춰 억·만 단위로 줄인다. 정확한 금액은 상세의 사실
 * 목록과 이 값의 `title`이 갖는다. 실제 0은 `0원`이고 `null`은 미확인이다 —
 * 둘을 같은 표시로 접지 않는다. */
function budgetLabel(value: number | null): string {
  return value === null || Number.isNaN(value) ? "예산 미확인" : formatCompactPrice(value);
}

/** 상세와 tooltip이 쓰는 정확한 금액. */
function exactBudget(value: number | null): string {
  return value === null || Number.isNaN(value) ? "예산 미확인" : `${formatNumber(value)}원`;
}

/**
 * 사람의 추적 선택 표시. 세 경우를 서로 접지 않는다.
 *
 * - 사업기회 연결이 없으면 아직 물어볼 자리가 없다 → `사업기회 미연결`
 * - 연결은 있는데 서버 값이 `null`이면 → `미확인` (사람이 고른 `미선택`이 아니다)
 * - 그 밖에는 사람이 고른 값 그대로
 */
function trackingLabel(item: PreSpecListItem): string {
  if (item.opportunity_id === null) return "사업기회 미연결";
  return item.tracking_status ?? "미확인";
}

/** 시안의 상태 token 색. 실패는 오류, 사람 검토 필요는 경고, 나머지는 무채색이다.
 * 색만으로 뜻을 전하지 않으며 라벨이 늘 함께 있다. */
function overviewTokenColor(status: PreSpecOverviewReviewStatus | null): "red" | "orange" | "default" {
  if (status === "failed") return "red";
  if (status === "needs_human_review") return "orange";
  return "default";
}

/** 첨부 취득에서 사람이 손대야 하는 건수. 0은 실제 0이므로 아무것도 적지 않는다. */
function attachmentAttention(item: PreSpecListItem): string | null {
  const parts: string[] = [];
  if (item.document["차단"] > 0) parts.push(`차단 ${item.document["차단"]}`);
  if (item.document["실패"] > 0) parts.push(`실패 ${item.document["실패"]}`);
  return parts.length > 0 ? `첨부 ${parts.join(" · ")}` : null;
}

function titleOf(item: PreSpecListItem): string {
  return item.title?.trim() || "사업명 미확인";
}

function agencyOf(item: PreSpecListItem): string {
  return item.agency?.trim() || "발주기관 미확인";
}

function overviewStatusLabel(status: PreSpecOverviewReviewStatus | null): string {
  return status === null ? PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL : PRE_SPEC_OVERVIEW_STATUS_LABEL[status];
}

/** 발견 구분. 연결이 없으면 `구분 미확인`이며 신규로 접지 않는다. */
function originLabel(value: PreSpecOrigin | null): string {
  return value === null ? "구분 미확인" : originOf(value);
}

/** SW사업대상. 기본 보기가 이미 `Y` 중심이므로 목록은 `Y`가 아닌 경우만 적는다.
 * 값이 없는 것(`SW 미확인`)과 실제 `N`은 서로 다른 표시다. */
function swRowNote(value: string | null): string | null {
  if (value === "Y") return null;
  return value === null ? "SW 미확인" : `SW ${value}`;
}

function DeadlineMark({ value }: { value: string | null }) {
  const deadline = describeDeadline(value);
  return (
    <span aria-label={`D-day: ${deadline.label}`} className={`pre-specs-deadline is-${deadline.urgency} mono tabular-nums`}>
      {deadline.label}
    </span>
  );
}

/**
 * 목록 행 — 시안의 두 열 구조다.
 *
 * 왼쪽 열은 사업명(16px, 굵게) → 발주기관(16px) → 예산·발견 구분(14px) → 개요 상태와
 * 추적 상태(14px)를 그대로 쌓는다. 행에서 먼저 읽혀야 하는 것은 사업명이므로 시안의
 * 두 줄 차례를 뒤집었다(사용자 정정). 오른쪽 열은 의견등록 마감뿐이며 D-day와 짧은
 * 날짜만 둔다. 정확한 일시·금액과 등급·자동 준비 같은 나머지 사실은 선택한 건의
 * 상세가 보여 준다 — 목록에서 같은 사실을 강한 배지로 반복하지 않는다.
 *
 * 행은 스스로 판정하지 않는다. 서버가 준 상태를 옮길 뿐이고, 사업명을 눌러도
 * 목록을 떠나지 않고 오른쪽 상세만 바뀐다(상세 화면 진입은 상세 pane 바닥의
 * `상세 검토 열기`가 소유한다).
 */
function PreSpecRow({
  item,
  isSelected,
  onSelect,
}: {
  item: PreSpecListItem;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const title = titleOf(item);
  const swNote = swRowNote(item.sw_business_status);
  const attention = attachmentAttention(item);
  const shortDeadline = shortDateLabel(item.deadline_at);
  return (
    <DenseListRow
      // 행 자체가 role="button"이 되므로 접근 가능한 이름을 사업명으로 고정한다.
      aria-label={title}
      className="pre-specs-row"
      selected={isSelected}
      onSelect={onSelect}
      label={<span className="pre-specs-row-title">{title}</span>}
      description={(
        <>
          <span className="pre-specs-row-agency">{agencyOf(item)}</span>
          <span className="pre-specs-row-meta">
            <span title={exactBudget(item.budget)}>{budgetLabel(item.budget)}</span>
            <span aria-hidden="true">·</span>
            <span>{originLabel(item.origin)}</span>
            {swNote ? (
              <>
                <span aria-hidden="true">·</span>
                <span>{swNote}</span>
              </>
            ) : null}
            {item.kept_by_tracking ? (
              <>
                <span aria-hidden="true">·</span>
                {/* 뜻은 `표시 범위` 대화상자가 문장으로 갖는다. 목록에는 짧은 표식만
                    두고 그 뜻을 접근 가능한 이름으로 함께 남긴다. */}
                <span
                  aria-label="추적 예외 · SW사업대상 Y가 아니지만 추적 중인 발주계획에 연결됨"
                  className="pre-specs-tracking-exception"
                >
                  추적 예외
                </span>
              </>
            ) : null}
          </span>
          <span className="pre-specs-row-state">
            <Token
              size="sm"
              label={overviewStatusLabel(item.overview_review_status)}
              color={overviewTokenColor(item.overview_review_status)}
            />
            <span className="pre-specs-row-tracking">{trackingLabel(item)}</span>
            {/* 0건은 실제 0이므로 아무것도 적지 않는다. 1건 이상일 때만 남긴다. */}
            {attention ? <span className="pre-specs-row-attention">{attention}</span> : null}
          </span>
        </>
      )}
      endContent={(
        <span className="pre-specs-row-end">
          <DeadlineMark value={item.deadline_at} />
          <span
            className="pre-specs-row-deadline-at"
            title={item.deadline_at ? formatDateTime(item.deadline_at) : undefined}
          >
            {shortDeadline ?? "일시 없음"}
          </span>
        </span>
      )}
    />
  );
}

/** 조회 실패 한 자리. 서버 raw message는 여기까지 오지 않고 `describeApiError`가
 * 옮긴 안전한 문구만 나온다(docs/security.md). 같은 화면에 alert가 여럿 생기지
 * 않도록 이 자리는 polite status로 알린다. */
function DetailQueryError({
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

/**
 * 선택한 사전규격 하나.
 *
 * 목록 응답에 있는 사실(기관·예산·마감·등급·자동 준비·첨부 집계·추적 상태)과
 * 별도 endpoint인 개요 검토 응답을 각자 자리에서 보여 준다. 목록 응답만으로 개요
 * 본문을 만들지 않는다.
 */
function PreSpecDetail({
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
  const overviewRuns = pageOverview.isValid
    ? [...(pageOverview.currentResult ? [pageOverview.currentResult] : []), ...pageOverview.history]
    : [];

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

  // 다음 작업은 하나만 말한다. 서버가 준 개요 상태에서 고르고, 여기서 상태를
  // 새로 판정하지 않는다.
  const nextAction = item.overview_review_status === "completed"
    ? { title: "다음 작업", text: "개요 결과의 근거와 심층 검토를 상세에서 확인" }
    : item.overview_review_status === "needs_human_review"
      ? { title: "확인할 작업", text: "개요 입력 문서와 범위를 사람이 확인" }
      : item.overview_review_status === "failed" || item.overview_review_status === "cancelled"
        ? { title: "확인할 작업", text: "실행 기록에서 실패·취소 내용을 확인" }
        : { title: "확인할 작업", text: "현재 처리 상태를 확인" };

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

            <PageOverviewSection key={noticePk} noticeId={noticePk} />
            <CompanyFitSection key={`fit-${noticePk}`} noticeId={noticePk} />
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
                <span>{pageOverview.isValid ? `${overviewRuns.length}건` : "확인 중"}</span>
              </div>
              <p className="pre-specs-overview-note">
                현재 상태 · {item.overview_review_status === null
                  ? PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL
                  : PRE_SPEC_OVERVIEW_STATUS_LABEL[item.overview_review_status]}
              </p>
              {/* 결과 본문이 남은 실행만 여기 온다. 실패·취소한 실행의 사유는 위
                  개요 자리의 현재 실행 카드가 말한다. */}
              {pageOverview.isValid && overviewRuns.length === 0 ? (
                <p className="pre-specs-overview-empty">결과가 남은 개요 실행이 없습니다.</p>
              ) : null}
              {pageOverview.isValid && overviewRuns.length > 0 ? (
                <ul className="pre-specs-history-list">
                  {overviewRuns.map((review) => (
                    <li key={review.id}>
                      <span>{formatDateTime(review.created_at)}</span>
                      <Badge label={qualityStatusLabel(review.quality_status)} variant={qualityStatusVariant(review.quality_status)} />
                      <span>{review.model_name}</span>
                      <span className="mono">결과 ID {review.id}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              {pageOverview.query.isError || (!pageOverview.isValid && !pageOverview.query.isPending) ? (
                <p className="pre-specs-overview-empty">개요 실행 이력을 확인할 수 없습니다.</p>
              ) : null}
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
            onRetry={() => {}}
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

export function PreSpecsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const swOnly = searchParams.get("sw_only") !== "false";
  const businessDivision = validDivision(searchParams.get("business_division"));
  const origin = validOrigin(searchParams.get("origin"));
  const gradeFilter = validGrade(searchParams.get("grade"));
  const view = validView(searchParams.get("view"));
  const queryText = searchParams.get("q") ?? "";
  const sort = validSort(searchParams.get("sort"));
  const offset = readOffset(searchParams.get("offset"));

  const [searchText, setSearchText] = useState(queryText);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [scopeDialogOpen, setScopeDialogOpen] = useState(false);
  const [trackingDialogOpen, setTrackingDialogOpen] = useState(false);
  // 저장하지 않은 입력이 있는 채로 창을 닫으려 한 상태. 창은 열린 채로 두고
  // 같은 창 안에서 확인을 받는다.
  const [trackingCloseRequested, setTrackingCloseRequested] = useState(false);
  const [selectedPk, setSelectedPk] = useState<number | null>(null);
  // 대화상자의 추적 결정 입력(사유·담당자)은 행을 바꾸거나 창을 닫으면 사라진다.
  // route 이동은 컨트롤이 스스로 막으므로 여기서는 행 전환·닫기만 확인한다.
  const [trackingDirty, setTrackingDirty] = useState(false);
  const trackingGuard = useUnsavedGuard(trackingDirty, {
    scope: "pathname",
    title: "추적 결정 입력을 저장하지 않고 옮깁니다",
    message: "저장하지 않은 추적 결정 사유와 담당자 이름이 있습니다. 지금 옮기면 사라지며 저장된 추적 상태는 바뀌지 않습니다.",
    confirmLabel: "저장하지 않고 옮기기",
  });

  useEffect(() => setSearchText(queryText), [queryText]);

  const listQuery = useMemo(
    () => ({
      sw_only: swOnly,
      business_division: businessDivision || null,
      origin: origin || null,
      q: queryText || null,
      sort,
      limit: PAGE_SIZE,
      offset,
    }),
    [businessDivision, offset, origin, queryText, sort, swOnly],
  );
  const result = useQuery({
    queryKey: ["pre-specs", listQuery],
    queryFn: ({ signal }) => api.getPreSpecs(listQuery, { signal }),
    // 기본값으로 돌아왔을 때도 sw_only=true 요청을 다시 보내 ADR-0031의 서버 기본
    // projection과 화면 상태가 같은지 확인한다.
    staleTime: 0,
  });

  const loadedItems = useMemo(() => result.data?.items ?? [], [result.data]);
  // 서버에 등급 질의가 없으므로 여기서 고른다. 판정의 재계산이 아니라 서버가 준
  // `grade` 값으로 행을 고르는 것뿐이다.
  const gradeFiltered = useMemo(
    () => loadedItems.filter((item) => matchesGradeFilter(item, gradeFilter)),
    [gradeFilter, loadedItems],
  );
  const items = useMemo(
    () => gradeFiltered.filter((item) => matchesView(item, view)),
    [gradeFiltered, view],
  );
  const total = result.data?.total ?? 0;
  const overviewStatusCounts = useMemo(() => result.data?.overview_status_counts ?? [], [result.data]);
  const listSearch = searchParams.toString();
  const isDefaultView = swOnly && !businessDivision && !origin && !gradeFilter && !queryText
    && view === "all" && sort === "published" && offset === 0;

  /** 보기 버튼의 건수는 **서버 전체 집계**다. 등급 필터와 페이지 범위는 반영하지
   * 않으므로 실제로 보이는 행 수와 다를 수 있고, 그 사실을 화면이 밝힌다. */
  const viewCounts = useMemo(() => {
    const byStatus = new Map<PreSpecOverviewReviewStatus | null, number>();
    for (const row of overviewStatusCounts) byStatus.set(row.status, row.count);
    const counts = new Map<ViewKey, number>();
    for (const definition of VIEWS) {
      counts.set(
        definition.key,
        definition.statuses === null
          ? total
          : definition.statuses.reduce((sum, status) => sum + (byStatus.get(status) ?? 0), 0),
      );
    }
    return counts;
  }, [overviewStatusCounts, total]);
  const serverViewCount = viewCounts.get(view) ?? 0;

  const selectedItem = items.find((item) => item.notice_pk === selectedPk) ?? null;

  // 목록이 바뀌어 선택이 사라지면 첫 행을 고른다. 사람이 고르는 중이던 입력은
  // 대화상자 안에 있고, 그 확인은 아래 `selectPk`가 맡는다.
  useEffect(() => {
    if (items.length === 0) {
      if (selectedPk !== null) setSelectedPk(null);
      return;
    }
    if (!items.some((item) => item.notice_pk === selectedPk)) {
      setSelectedPk(items[0].notice_pk);
      setTrackingDialogOpen(false);
      setTrackingCloseRequested(false);
    }
  }, [items, selectedPk]);

  const selectPk = useCallback((next: number) => {
    trackingGuard.confirmDiscard(() => {
      setSelectedPk(next);
      setTrackingDialogOpen(false);
      setTrackingCloseRequested(false);
    });
  }, [trackingGuard]);

  const changeTrackingDialog = useCallback((open: boolean) => {
    if (open) {
      setTrackingDialogOpen(true);
      setTrackingCloseRequested(false);
      return;
    }
    // 저장하지 않은 입력이 있으면 창을 닫지 않고 확인을 먼저 보여 준다.
    if (trackingDirty) {
      setTrackingCloseRequested(true);
      return;
    }
    setTrackingDialogOpen(false);
    setTrackingCloseRequested(false);
  }, [trackingDirty]);

  function updateSearchParams(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    // 필터가 바뀌면 페이지를 처음으로 돌린다. 좁힌 조건에서 3페이지째를 보여 주는
    // 것은 사람이 요청한 적 없는 상태다.
    next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  function restoreDefaults() {
    updateSearchParams({
      sw_only: null,
      business_division: null,
      origin: null,
      grade: null,
      q: null,
      sort: null,
      view: null,
    });
    setSearchText("");
  }

  function showAllPreSpecs() {
    updateSearchParams({ sw_only: "false" });
  }

  function emptyDescription(): string {
    if (isDefaultView) return "SW 중심 기본 보기에 맞는 항목이 없습니다. 전체 보기는 SW사업대상과 무관한 사전규격까지 명시적으로 요청합니다.";
    if (view !== "all") return `현재 보기(${viewOf(view).label})와 필터에 맞는 행이 불러온 목록에 없습니다. 보기를 바꾸거나 조건을 넓혀 보십시오.`;
    if (swOnly) return "SW 중심 기본 보기와 추가 필터가 함께 적용되어 있습니다. 기본값으로 돌아가거나 조건을 조정해 보십시오.";
    if (businessDivision || origin || gradeFilter || queryText) return "현재 선택한 업무구분·구분·등급·검색어 조건에 맞는 누적 데이터가 없습니다.";
    return "누적 수집된 사전규격 데이터가 아직 없습니다.";
  }

  const rangeEnd = Math.min(offset + loadedItems.length, total);
  // 보이는 행 수와 서버 집계가 다른 경우. 페이지 범위나 등급 필터 때문이며,
  // 어느 쪽이든 그 이유를 함께 적는다.
  const isPartial = serverViewCount !== items.length;

  return (
    <section className="pre-specs-page" data-astryx-theme="bidops" aria-labelledby="page-title">
      {/* 화면 제목은 셸 상단바가 그린다(제목 모드). 페이지는 같은 이름을 세로로 한 번
          더 쓰지 않고, `aria-labelledby`가 가리킬 숨긴 제목만 남긴다. 페이지 상태를
          쓰는 액션(`표시 범위`)은 상단바 슬롯으로 portal한다. */}
      <h2 className="visually-hidden" id="page-title">사전규격</h2>
      <PageHeaderActions>
        <div className="pre-specs-header-actions">
          <Button label="표시 범위" size="sm" variant="ghost" onClick={() => setScopeDialogOpen(true)} />
        </div>
      </PageHeaderActions>

      <WorkspaceFrame>
        <WorkspaceFilterBar aria-label="사전규격 필터" className="pre-specs-filters">
          <WorkspaceFilterLine>
            {/* 건수는 서버 전체 집계다. 아직 못 불러왔으면 0으로 채우지 않고 `–`로
                남긴다(`null`) — 미로딩과 0건은 서로 다른 사실이다. `취소`는 실패와
                뜻이 달라 자기 보기를 갖되, 건수가 0이고 지금 보고 있지도 않으면
                자리만 차지하므로 감춘다. */}
            <WorkspaceViewTabs
              className="pre-specs-views"
              label="개요 검토 상태 보기"
              onChange={(key) => updateSearchParams({ view: key === "all" ? null : key })}
              tabs={VIEWS.filter((definition) => (
                definition.key !== "cancelled" || view === "cancelled" || (viewCounts.get("cancelled") ?? 0) > 0
              )).map((definition) => ({
                key: definition.key,
                label: definition.label,
                count: result.isSuccess ? viewCounts.get(definition.key) ?? 0 : null,
              }))}
              value={view}
            />
            <WorkspaceFilterEnd>
              {/* `q`는 서버 질의 인자다. 글자를 칠 때마다 목록을 다시 부르지 않고
                  Enter로 적용한다(적용 시점은 데이터 원천이 정한다). */}
              <WorkspaceSearch
                label="사업명·기관명 검색"
                onChange={setSearchText}
                onEnter={() => updateSearchParams({ q: searchText.trim() || null })}
                value={searchText}
              />
              <WorkspaceAdvancedToggle
                controlsId="pre-specs-advanced-filters"
                isOpen={advancedOpen}
                onToggle={() => setAdvancedOpen((open) => !open)}
              />
            </WorkspaceFilterEnd>
          </WorkspaceFilterLine>

          <WorkspaceFilterContext className="pre-specs-filter-context">
            <div className="pre-specs-filter-context-start">
              <label className="pre-specs-switch">
                <input
                  checked={swOnly}
                  type="checkbox"
                  onChange={(event) => updateSearchParams({ sw_only: event.target.checked ? null : "false" })}
                />
                <span>SW 중심 · 추적 예외 포함</span>
              </label>
              <span className="pre-specs-filter-help">
                {swOnly
                  ? "일반·기술용역 / SW사업대상 Y + 추적 예외"
                  : "SW사업대상과 무관한 사전규격까지 조회"}
              </span>
            </div>
            {/* 기본 화면에는 설명 문단을 두지 않는다. 필터의 적용 범위는 목록
                바닥의 짧은 문구와 `표시 범위` 대화상자가 갖는다. 등급 필터는 서버가
                거르지 못하는 필터라 켜져 있을 때만 한 줄로 밝힌다. */}
            {gradeFilter ? (
              <p className="pre-specs-grade-filter-note" role="status">
                등급 필터는 불러온 페이지에만 적용됩니다. 보기 건수는 서버 전체 집계입니다.
              </p>
            ) : null}
          </WorkspaceFilterContext>

          {advancedOpen ? (
            <WorkspaceFilterAdvanced
              columns={4}
              id="pre-specs-advanced-filters"
              onReset={restoreDefaults}
              resetLabel="기본값으로"
            >
              {/* `전체`는 값이 없는 상태이지 다섯 번째 선택지가 아니다. Selector에는
                  빈 문자열을 줄 수 없어 표식값(ALL_OPTION)으로 두고, URL에는 인자를
                  지우는 것으로 옮긴다. */}
              <Selector
                label="업무구분"
                size="sm"
                options={[
                  { value: ALL_OPTION, label: "전체" },
                  ...BUSINESS_DIVISIONS.map((value) => ({ value, label: value })),
                ]}
                value={businessDivision || ALL_OPTION}
                onChange={(value) => updateSearchParams({ business_division: value === ALL_OPTION ? null : value })}
              />
              <Selector
                label="발견 구분"
                size="sm"
                options={[
                  { value: ALL_OPTION, label: "전체" },
                  ...ORIGINS.map((value) => ({ value, label: value })),
                ]}
                value={origin || ALL_OPTION}
                onChange={(value) => updateSearchParams({ origin: value === ALL_OPTION ? null : value })}
              />
              <Selector
                label="적합성 등급"
                size="sm"
                options={[
                  { value: ALL_OPTION, label: "전체" },
                  ...GRADE_FILTER_VALUES.map((value) => ({ value, label: value })),
                ]}
                value={gradeFilter || ALL_OPTION}
                onChange={(value) => updateSearchParams({ grade: value === ALL_OPTION ? null : value })}
              />
              {/* 정렬은 사업 추적과 같은 자리(상세 필터 안 Selector)로 옮겼다. 접혀
                  있어도 지금 어떤 순서인지는 목록 머리가 글자로 밝힌다. */}
              <Selector
                label="표시 순서"
                size="sm"
                options={SORT_OPTIONS.map(({ value, label }) => ({ value, label }))}
                value={sort}
                onChange={(value) => updateSearchParams({ sort: value === "published" ? null : value })}
              />
            </WorkspaceFilterAdvanced>
          ) : null}
        </WorkspaceFilterBar>

        {result.isPending ? (
          <div className="pre-specs-loading" role="status" aria-live="polite">사전규격 목록을 불러오는 중입니다.</div>
        ) : null}
        {result.isError ? (
          <EmptyState
            tone="error"
            title="사전규격 목록을 불러오지 못했습니다."
            description="사전규격 API 응답을 확인할 수 없습니다."
            action={{ label: "다시 시도", onClick: () => { void result.refetch(); } }}
          />
        ) : null}

        {result.isSuccess ? (
          <SplitWorkspace className="pre-specs-split-workspace">
            <section className="review-split-list pre-specs-list-pane" aria-label="사전규격 목록">
              <header className="pre-specs-list-head">
                <strong>
                  사전규격 목록 <span className="mono tabular-nums">{items.length}</span>건
                </strong>
                {/* 정렬은 상세 필터 안에 있어 접히면 보이지 않는다. 지금 어떤
                    순서로 줄 세웠는지는 목록 머리가 늘 글자로 밝힌다(대시보드가
                    `/pre-specs?sort=deadline`로 곧장 연결한다). */}
                <span>{viewOf(view).description}{sort === "deadline" ? " · 마감 임박순" : ""}</span>
              </header>
              <div className="pre-specs-list-columns" aria-hidden="true">
                <span>사업명 / 발주기관</span>
                <span>의견 마감</span>
              </div>
              <div className="pre-specs-list-scroll">
                {items.length === 0 ? (
                  <EmptyState
                    compact
                    title="조건에 맞는 사전규격이 없습니다."
                    description={emptyDescription()}
                    action={isDefaultView
                      ? { label: "전체 사전규격 보기", onClick: showAllPreSpecs }
                      : { label: "기본값으로", onClick: restoreDefaults }}
                  />
                ) : (
                  <DenseList aria-label="사전규격" className="pre-specs-list">
                    {items.map((item) => (
                      <PreSpecRow
                        key={item.notice_pk}
                        item={item}
                        isSelected={item.notice_pk === selectedPk}
                        onSelect={() => selectPk(item.notice_pk)}
                      />
                    ))}
                  </DenseList>
                )}
              </div>
              <footer className="pre-specs-list-foot">
                <span>
                  불러온 {loadedItems.length}건 중 {items.length}건 표시
                  {total > loadedItems.length ? ` · 전체 ${total}건 중 ${offset + 1}–${rangeEnd}` : ""}
                </span>
                {isPartial ? (
                  <span className="pre-specs-list-foot-note">
                    보기 <strong>{viewOf(view).label}</strong>의 서버 집계는 {serverViewCount}건입니다. 이 수는 필터 전체 기준이고 목록은 불러온 페이지 기준이라 서로 다를 수 있습니다.
                    {gradeFilter ? " 등급 필터는 불러온 페이지에만 적용됩니다." : ""}
                  </span>
                ) : null}
              </footer>
            </section>

            <section className="review-split-detail pre-specs-detail-pane" aria-label="선택한 사전규격">
              {selectedItem ? (
                <PreSpecDetail
                  key={selectedItem.notice_pk}
                  item={selectedItem}
                  listSearch={listSearch}
                  trackingDialogOpen={trackingDialogOpen}
                  onTrackingDialogChange={changeTrackingDialog}
                  trackingCloseRequested={trackingCloseRequested}
                  onTrackingCloseCancel={() => setTrackingCloseRequested(false)}
                  onTrackingCloseConfirm={() => {
                    setTrackingCloseRequested(false);
                    setTrackingDialogOpen(false);
                  }}
                  onDirtyChange={setTrackingDirty}
                  onSaved={(saved) => {
                    const noticePk = selectedItem.notice_pk;
                    queryClient.setQueryData<PreSpecListResponse>(
                      ["pre-spec-detail", noticePk],
                      (current) => updateTrackingProjection(current, noticePk, saved),
                    );
                    queryClient.setQueriesData<PreSpecListResponse>(
                      { queryKey: ["pre-specs"] },
                      (current) => updateTrackingProjection(current, noticePk, saved),
                    );
                    void queryClient.invalidateQueries({ queryKey: ["pre-spec-detail", noticePk] });
                    void queryClient.invalidateQueries({ queryKey: ["pre-specs"] });
                    void queryClient.invalidateQueries({ queryKey: ["opportunity", saved.id] });
                  }}
                />
              ) : (
                <div className="pre-specs-detail-empty">
                  <EmptyState
                    compact
                    title="사전규격을 선택하십시오."
                    description="왼쪽 목록에서 행을 선택하면 개요 검토 결과와 추적 선택을 확인할 수 있습니다. 이 선택은 최종 Go/No-Go와 별개입니다."
                  />
                </div>
              )}
            </section>
          </SplitWorkspace>
        ) : null}

        {result.isSuccess && total > PAGE_SIZE ? (
          <nav className="pre-specs-pager" aria-label="사전규격 목록 페이지">
            <button
              className="interaction-control interaction-control-primary"
              type="button"
              disabled={offset === 0}
              onClick={() => {
                const next = new URLSearchParams(searchParams);
                if (offset - PAGE_SIZE > 0) next.set("offset", String(offset - PAGE_SIZE));
                else next.delete("offset");
                setSearchParams(next, { replace: true });
              }}
            >
              이전
            </button>
            <span>{offset + 1}–{rangeEnd} / {total}</span>
            <button
              className="interaction-control interaction-control-primary"
              type="button"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => {
                const next = new URLSearchParams(searchParams);
                next.set("offset", String(offset + PAGE_SIZE));
                setSearchParams(next, { replace: true });
              }}
            >
              다음
            </button>
          </nav>
        ) : null}
      </WorkspaceFrame>

      <Dialog isOpen={scopeDialogOpen} onOpenChange={(open) => { if (!open) setScopeDialogOpen(false); }} purpose="info" width={620}>
        <DialogHeader title="표시 범위" onOpenChange={() => setScopeDialogOpen(false)} />
        <div className="pre-specs-dialog-body">
          <p>
            현재 조건의 서버 전체 건수는 <strong>{total}건</strong>이고, 한 번에 최대 {PAGE_SIZE}건을 불러옵니다.
            지금 화면에는 불러온 {loadedItems.length}건 가운데 {items.length}건이 보입니다.
          </p>
          <ul>
            <li>상단 보기 건수는 서버가 필터 전체에서 센 값(<code className="mono">overview_status_counts</code>)이며 페이지 범위와 등급 필터를 반영하지 않습니다.</li>
            <li>적합성 등급 필터는 서버에 질의 인자가 없어 이미 불러온 페이지만 좁힙니다.</li>
            <li>보기는 상태를 묶어 찾기 위한 탐색 도구입니다. 각 행의 개요 상태·등급·자동 준비·추적 상태는 서버 값 그대로입니다.</li>
            <li>SW 중심 기본 보기는 SW사업대상=Y와 추적 중인 발주계획에 연결된 예외를 함께 남깁니다. 목록의 <strong>추적 예외</strong>는 SW사업대상이 Y가 아니지만 추적 중인 발주계획에 연결된 건이고, 값이 없는 SW사업대상은 <strong>SW 미확인</strong>으로 적습니다.</li>
            <li>추적 상태는 사업기회 연결이 없으면 <strong>사업기회 미연결</strong>, 연결은 있는데 서버 값이 없으면 <strong>미확인</strong>입니다. 사람이 고른 <strong>미선택</strong>과 다릅니다.</li>
            <li>품질 표식 · 참조 실행과 mock 참조는 운영 완료가 아니고, 표식 없음을 미측정으로 바꾸지 않습니다. 선택한 건의 현재 표식은 개요 검토 결과 머리줄에 있습니다.</li>
          </ul>
        </div>
      </Dialog>
    </section>
  );
}
