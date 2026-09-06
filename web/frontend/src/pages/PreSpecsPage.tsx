import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Badge } from "../components/common/Badge";
import { DisabledReason } from "../components/common/DisabledReason";
import { EmptyState } from "../components/common/EmptyState";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { Panel } from "../components/common/Panel";
import { DenseList, DenseListRow, ReviewStateGroup, SplitWorkspace } from "../components/common/ReviewPrimitives";
import {
  isInheritedTracking,
  PreSpecDocumentSummary,
  TrackingDecisionControl,
  updateTrackingProjection,
} from "../components/pre-specs/TrackingDecisionControl";
import { api } from "../lib/api";
import { describeDeadline } from "../lib/deadline";
import { formatDateTime, formatNumber } from "../lib/format";
import { GRADE_NONE_LABEL, GRADE_ORDER, gradeLabel, gradeVariant } from "../lib/grade";
import { originOf, trackingVariant } from "../lib/opportunity";
import {
  PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL,
  preSpecAutoPreparationVariant,
} from "../lib/preSpecAutoPreparation";
import {
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
  preSpecOverviewStatusVariant,
} from "../lib/preSpecOverviewStatus";
import type { PreSpecListItem, PreSpecListResponse, PreSpecOrigin, PreSpecOverviewReviewStatus, PreSpecSort } from "../lib/types";
import "../styles/pre-specs-relaxed.css";

// docs/design/PLAN.md 3단계: 목록을 개요 검토 상태별 접이식 그룹으로 바꾼다.
// 페이지 크기를 200으로 올려 (서버 한도 500 이내) 한 페이지 안에서 그룹이
// 실제로 채워지는 경우를 늘린다. 그래도 총 건수가 페이지 크기를 넘으면
// 그룹 헤더의 건수(overview_status_counts, 필터 전체 기준)와 그 그룹 안에
// 실제로 보이는 행 수가 달라질 수 있어, 그 경우를 각주로 명시한다 — 조용히
// 숨기지 않는다(CLAUDE.md unknown/null 보존 게이트와 같은 원칙).
const PAGE_SIZE = 200;
const BUSINESS_DIVISIONS = ["일반용역", "기술용역"] as const;
const ORIGINS: PreSpecOrigin[] = ["추적", "신규"];

// 등급 필터 URL 계약: `grade` 하나를 추가하고 기존 그룹·필터 파라미터는 그대로
// 둔다. 허용값은 계약의 등급 4값과 `판정 없음`(= `grade`가 null인 건)뿐이다.
//
// **서버 `/api/pre-specs`에는 등급 질의 파라미터가 없다.** 그래서 이 필터는
// 불러온 페이지에만 적용되고, 그룹 머리글의 건수(`overview_status_counts`,
// 서버가 필터 전체에서 센 값)는 등급 필터 이전 기준이다. 그 사실을 화면에
// 문장으로 남긴다 — 조용히 다른 뜻으로 보이게 하지 않는다.
const GRADE_FILTER_VALUES = [...GRADE_ORDER, GRADE_NONE_LABEL] as const;
type GradeFilter = (typeof GRADE_FILTER_VALUES)[number] | "";

function validGrade(value: string | null): GradeFilter {
  return value && (GRADE_FILTER_VALUES as readonly string[]).includes(value) ? (value as GradeFilter) : "";
}

function matchesGradeFilter(item: PreSpecListItem, grade: GradeFilter): boolean {
  if (!grade) return true;
  if (grade === GRADE_NONE_LABEL) return item.grade === null;
  return item.grade === grade;
}

// 그룹 표시 순서. 사람 검토 필요·실패를 맨 앞에 두고, 개요 검토 미시작(행
// 없음)을 그 다음에 두어 "아직 시작하지 않음 → 진행 중 → 종료"의 자연스러운
// 순서를 만든다. 완료·취소는 맨 뒤에 둔다.
const GROUP_ORDER: (PreSpecOverviewReviewStatus | null)[] = [
  "needs_human_review",
  "failed",
  null,
  "awaiting_document",
  "awaiting_structure",
  "preparing",
  "awaiting_model",
  "queued",
  "running",
  "completed",
  "cancelled",
];

// 사람 검토 필요·실패는 기본 펼침, 완료는 기본 접힘 — PLAN.md 3단계 원문
// 그대로다. 나머지(미시작 포함 8개 상태)는 실행 중이거나 아직 조치할 일이
// 없는 상태이므로 기본 접힘으로 둔다. 이 결정으로 10값 + null 11개 그룹
// 전부가 화면에 존재하되(0건이어도 표시), 기본 화면은 조치가 필요한
// 항목에 집중된다.
const DEFAULT_EXPANDED_GROUPS: (PreSpecOverviewReviewStatus | null)[] = ["needs_human_review", "failed"];

function groupLabel(status: PreSpecOverviewReviewStatus | null): string {
  return status === null ? PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL : PRE_SPEC_OVERVIEW_STATUS_LABEL[status];
}

function groupBadgeVariant(status: PreSpecOverviewReviewStatus | null) {
  return status === null ? "neutral" : preSpecOverviewStatusVariant(status);
}

function groupStatusDotVariant(status: PreSpecOverviewReviewStatus | null): "success" | "warning" | "error" | "accent" | "neutral" {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "needs_human_review") return "warning";
  if (status === "running" || status === "queued") return "accent";
  return "neutral";
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

function formatBudget(value: number | null): string {
  return value === null || Number.isNaN(value) ? "예산 미확인" : `${formatNumber(value)}원`;
}

function titleOf(item: PreSpecListItem): string {
  return item.title?.trim() || "사업명 미확인";
}

/** 목록 행은 SW사업대상=Y만 배지로 세우고, 값이 없는 건은 `SW 미확인`으로
 * 따로 적는다. `N`은 배지를 세우지 않지만 상세 pane의 사실 목록이 값을 그대로
 * 보여 준다 — 없음(null)과 실제 `N`을 같은 표시로 접지 않는다. */
function swRowMark(value: string | null): ReactNode {
  if (value === null) return <span className="pre-specs-row-unknown">SW 미확인</span>;
  if (value === "Y") return <Badge label="SW사업대상" variant="evidence-confirmed" />;
  return null;
}

function originCell(value: PreSpecOrigin | null): ReactNode {
  if (value === null) return <Badge label="구분 미확인" variant="evidence-unknown" />;
  const origin = originOf(value);
  return <Badge label={origin} variant={origin === "추적" ? "grade-1" : "focus"} />;
}

/** 추적 상태는 사업기회에 연결된 건만 갖는다. 연결이 없으면 상태가 `없음`이
 * 아니라 아직 물어볼 자리가 없는 것이므로 배지를 세우지 않는다. */
function trackingRowBadge(item: PreSpecListItem): ReactNode {
  if (item.opportunity_id === null) return null;
  if (item.tracking_status === null) return <Badge label="미확인" variant="neutral" />;
  return <Badge label={item.tracking_status} variant={trackingVariant(item.tracking_status)} />;
}

/** 등급은 심각도가 아니라 순위이고, 농도만으로는 인접 단이 구분되지 않는다.
 * 그래서 배지는 항상 문자 라벨을 함께 갖고, 판정이 없으면 `판정 없음`이다
 * (design/PRD.md §4). 화면은 등급을 다시 계산하지 않는다. */
function gradeCell(item: PreSpecListItem): ReactNode {
  return <Badge label={gradeLabel(item.grade)} variant={gradeVariant(item.grade)} />;
}

function autoPreparationCell(item: PreSpecListItem): ReactNode {
  const status = item.auto_preparation_status;
  return (
    <Badge label={PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL[status]} variant={preSpecAutoPreparationVariant(status)} />
  );
}

function DeadlineMark({ value }: { value: string | null }) {
  const deadline = describeDeadline(value);
  return (
    <span aria-label={`D-day: ${deadline.label}`} className={`pre-specs-deadline is-${deadline.urgency} mono tabular-nums`}>
      {deadline.label}
    </span>
  );
}

interface PreSpecRowProps {
  item: PreSpecListItem;
  listSearch: string;
  isSelected: boolean;
  onSelect: () => void;
  onToggleTracking: () => void;
}

/**
 * 시안(`tests/design-snapshots/shots/PreSpecs.png`)의 목록 행이다. 12열 표를
 * 좁은 분할 pane에 넣으면 마감·예산·추적 상태가 가로 스크롤 뒤로 사라지므로,
 * 한 건을 제목 · 배지 줄 · 기관/번호 줄로 쌓고 D-day를 오른쪽에 붙인다.
 *
 * 행이 스스로 판정하지 않는다는 점은 그대로다 — 서버가 준 등급·자동 준비
 * 상태·추적 상태를 각각 별도 배지로 적을 뿐 서로 대신하게 하지 않는다.
 */
function PreSpecRow({ item, listSearch, isSelected, onSelect, onToggleTracking }: PreSpecRowProps) {
  const title = titleOf(item);
  const document = item.document;
  const hasOpportunity = item.opportunity_id !== null;
  const reasonId = `pre-specs-tracking-disabled-${item.notice_pk}`;
  return (
    <DenseListRow
      // 행 자체가 role="button"이 되므로 접근 가능한 이름을 사업명으로 고정한다.
      // 그러지 않으면 행 안의 `추적 결정` 버튼과 이름이 겹쳐 같은 이름의 control이
      // 둘이 된다(Playwright strict mode는 이것을 결정적 결함으로 본다).
      aria-label={title}
      className="pre-specs-row"
      selected={isSelected}
      onSelect={onSelect}
      label={(
        <span className="pre-specs-row-title">
          <Link className="pre-specs-title-link" to={{ pathname: `/pre-specs/${item.notice_pk}`, search: listSearch }}>
            {title}
          </Link>
        </span>
      )}
      description={(
        <>
          <span className="pre-specs-row-badges">
            {originCell(item.origin)}
            {item.kept_by_tracking ? (
              /* 뜻은 목록 위 정책 안내(`pre-specs-policy-note`)에 글자로 적혀
                 있다. `title` 툴팁으로 겹쳐 두면 키보드·스크린리더로는 닿지
                 않으므로 그 문장을 `aria-describedby`로 가리킨다. */
              <span aria-describedby="pre-specs-tracking-exception-note" className="pre-specs-tracking-exception">
                추적 예외
              </span>
            ) : null}
            {gradeCell(item)}
            {autoPreparationCell(item)}
            {trackingRowBadge(item)}
            {swRowMark(item.sw_business_status)}
            {/* 0건은 실제 0이므로 경고로 올리지 않는다. 1건 이상일 때만 alert 배지를 세운다. */}
            {document["차단"] > 0 ? <Badge label={`차단 ${document["차단"]}`} variant="danger" /> : null}
            {document["실패"] > 0 ? <Badge label={`실패 ${document["실패"]}`} variant="danger" /> : null}
          </span>
          <span className="pre-specs-row-meta">
            <span>{item.agency?.trim() || "발주기관 미확인"}</span>
            <span aria-hidden="true">·</span>
            {item.pre_spec_no ? <code>{String(item.pre_spec_no)}</code> : <span>번호 미확인</span>}
            <span aria-hidden="true">·</span>
            <span>{item.business_division?.trim() || "미확인"}</span>
          </span>
          <span className="pre-specs-row-action pre-specs-tracking-action">
            {hasOpportunity ? (
              <button
                type="button"
                className="interaction-control interaction-control-compact pre-specs-tracking-action-button"
                aria-pressed={isSelected}
                aria-expanded={isSelected}
                aria-controls={isSelected ? "pre-specs-tracking-target" : undefined}
                onClick={onToggleTracking}
              >
                {/* 이름은 늘 행동 하나다. 눌린 상태는 aria-pressed·aria-expanded와
                    바로 아래 열리는 결정 패널이 말한다 — 버튼 이름을 상태 문장으로
                    바꾸면 같은 조작이 화면마다 다른 이름으로 읽힌다. */}
                추적 결정
              </button>
            ) : (
              <>
                {/* 사업기회가 없으면 조용히 숨기지 않고 비활성 사유를 aria-describedby로 노출한다. */}
                <button type="button" className="interaction-control interaction-control-compact pre-specs-tracking-action-button" disabled aria-describedby={reasonId}>
                  추적 결정
                </button>
                <DisabledReason id={reasonId}>아직 사업기회에 연결되지 않아 추적 결정을 기록할 수 없습니다.</DisabledReason>
              </>
            )}
          </span>
        </>
      )}
      endContent={(
        <span className="pre-specs-row-end">
          <DeadlineMark value={item.deadline_at} />
          {item.deadline_at ? <span className="pre-specs-row-deadline-at">{formatDateTime(item.deadline_at)}</span> : null}
        </span>
      )}
    />
  );
}

/** 선택한 건의 사실만 모은다. 결정은 아래의 TrackingDecisionControl이 소유하며
 * 이 표는 서버가 준 값을 옮길 뿐 비어 있는 값을 채우지 않는다. */
function PreSpecDetailFacts({ item }: { item: PreSpecListItem }) {
  return (
    <dl className="pre-specs-detail-facts">
      <div>
        <dt>업무구분</dt>
        <dd>{item.business_division?.trim() || <span className="pre-specs-muted">미확인</span>}</dd>
      </div>
      <div>
        <dt>SW사업대상</dt>
        <dd>{item.sw_business_status === null ? <span className="pre-specs-muted">미확인</span> : item.sw_business_status}</dd>
      </div>
      <div>
        <dt>게시</dt>
        <dd>{formatDateTime(item.published_at)}</dd>
      </div>
      <div>
        <dt>의견등록 마감</dt>
        <dd className="pre-specs-detail-deadline">
          <span>{item.deadline_at ? formatDateTime(item.deadline_at) : "마감 일시 없음"}</span>
          <DeadlineMark value={item.deadline_at} />
        </dd>
      </div>
      <div>
        <dt>예산</dt>
        <dd>{formatBudget(item.budget)}</dd>
      </div>
    </dl>
  );
}

export function PreSpecsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const swOnly = searchParams.get("sw_only") !== "false";
  const businessDivision = validDivision(searchParams.get("business_division"));
  const origin = validOrigin(searchParams.get("origin"));
  const gradeFilter = validGrade(searchParams.get("grade"));
  const queryText = searchParams.get("q") ?? "";
  const sort = validSort(searchParams.get("sort"));
  const offset = readOffset(searchParams.get("offset"));
  const [searchText, setSearchText] = useState(queryText);
  const [selectedTrackingPk, setSelectedTrackingPk] = useState<number | null>(null);
  // 상세 pane의 추적 결정 입력(사유·담당자)은 행을 바꾸면 사라진다. route 이동은
  // 컨트롤이 스스로 막으므로 여기서는 행 전환·닫기만 확인한다.
  const [trackingDirty, setTrackingDirty] = useState(false);
  const trackingGuard = useUnsavedGuard(trackingDirty, {
    scope: "pathname",
    title: "추적 결정 입력을 저장하지 않고 다른 사전규격으로 옮깁니다",
    message: "저장하지 않은 추적 결정 사유와 담당자 이름이 있습니다. 지금 옮기면 사라지며 저장된 추적 상태는 바뀌지 않습니다.",
    confirmLabel: "저장하지 않고 옮기기",
  });
  const selectTrackingPk = useCallback((next: number | null | ((current: number | null) => number | null)) => {
    trackingGuard.confirmDiscard(() => setSelectedTrackingPk(next));
  }, [trackingGuard]);

  useEffect(() => setSearchText(queryText), [queryText]);
  useEffect(() => {
    setSelectedTrackingPk(null);
  }, [businessDivision, gradeFilter, offset, origin, queryText, sort, swOnly]);

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
    // 기본값으로 돌아왔을 때도 sw_only=true 요청을 다시 보내 ADR-0031의
    // 서버 기본 projection과 화면 상태가 같은지 확인한다.
    staleTime: 0,
  });
  const loadedItems = result.data?.items ?? [];
  // 서버에 등급 질의가 없으므로 여기서 고른다. 이것은 판정의 재계산이 아니라
  // 서버가 준 `grade` 값으로 행을 고르는 것뿐이다.
  const items = useMemo(
    () => loadedItems.filter((item) => matchesGradeFilter(item, gradeFilter)),
    [gradeFilter, loadedItems],
  );
  const total = result.data?.total ?? 0;
  const overviewStatusCounts = result.data?.overview_status_counts ?? [];
  const isDefaultView = swOnly && !businessDivision && !origin && !gradeFilter && !queryText && sort === "published" && offset === 0;
  const listSearch = searchParams.toString();

  const countByStatus = useMemo(() => {
    const map = new Map<PreSpecOverviewReviewStatus | null, number>();
    for (const row of overviewStatusCounts) map.set(row.status, row.count);
    return map;
  }, [overviewStatusCounts]);
  const itemsByStatus = useMemo(() => {
    const map = new Map<PreSpecOverviewReviewStatus | null, PreSpecListItem[]>();
    for (const item of items) {
      const key = item.overview_review_status;
      const bucket = map.get(key);
      if (bucket) bucket.push(item);
      else map.set(key, [item]);
    }
    return map;
  }, [items]);
  const selectedTrackingItem = items.find((item) => item.notice_pk === selectedTrackingPk);

  function updateSearchParams(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  function restoreDefaults() {
    updateSearchParams({ sw_only: null, business_division: null, origin: null, grade: null, q: null, sort: null });
    setSearchText("");
  }

  function showAllPreSpecs() {
    updateSearchParams({ sw_only: "false" });
  }

  function emptyDescription(): string {
    if (isDefaultView) return "SW 중심 기본 보기에 맞는 항목이 없습니다. 전체 보기는 SW사업대상과 무관한 사전규격까지 명시적으로 요청합니다.";
    if (swOnly) return "SW 중심 기본 보기와 추가 필터가 함께 적용되어 있습니다. 기본값으로 돌아가거나 조건을 조정해 보십시오.";
    if (businessDivision || origin || gradeFilter || queryText) return "현재 선택한 업무구분·구분·등급·검색어 조건에 맞는 누적 데이터가 없습니다.";
    return "누적 수집된 사전규격 데이터가 아직 없습니다.";
  }

  return (
    <section className="pre-specs-page" data-astryx-theme="bidops" aria-labelledby="page-title">
      <header className="pre-specs-page-header">
        <div>
          <h2 id="page-title">사전규격</h2>
          <p>
            누적 사전규격을 확인하고 심층 검토 추적을 시작합니다. SW사업대상은 화면 필터일 뿐이어서 추적 중인 발주계획
            연결은 라벨과 관계없이 그대로 남으며, 이 화면이 정하는 것은 추적 선택 하나입니다.
          </p>
        </div>
        <div className="pre-specs-count" aria-live="polite">
          <strong className="mono">{total}</strong>
          <span>건</span>
        </div>
      </header>

      <section className="pre-specs-filter-panel" aria-label="사전규격 필터">
        <div className="pre-specs-filter-row">
          <label className="pre-specs-switch">
            <input
              checked={swOnly}
              type="checkbox"
              onChange={(event) => updateSearchParams({ sw_only: event.target.checked ? null : "false" })}
            />
            <span>SW 중심 · 추적 예외 포함</span>
          </label>
          <span className="pre-specs-filter-help">기본 보기 · 해제 시 전체 사전규격을 명시적으로 요청</span>
          <label>
            <span>업무구분</span>
            <select
              value={businessDivision}
              onChange={(event) => updateSearchParams({ business_division: event.target.value || null })}
            >
              <option value="">전체</option>
              {BUSINESS_DIVISIONS.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>
            <span>구분</span>
            <select value={origin} onChange={(event) => updateSearchParams({ origin: event.target.value || null })}>
              <option value="">전체</option>
              {ORIGINS.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>
            <span>적합성 등급</span>
            <select value={gradeFilter} onChange={(event) => updateSearchParams({ grade: event.target.value || null })}>
              <option value="">전체</option>
              {GRADE_FILTER_VALUES.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>
            <span>정렬</span>
            <select value={sort} onChange={(event) => updateSearchParams({ sort: event.target.value || null })}>
              <option value="published">게시 최신순</option>
              <option value="deadline">마감 임박순</option>
            </select>
          </label>
          <form
            className="pre-specs-search"
            onSubmit={(event) => {
              event.preventDefault();
              updateSearchParams({ q: searchText.trim() || null });
            }}
          >
            <label htmlFor="pre-spec-search">사업명·기관명 검색</label>
            <div>
              <input
                id="pre-spec-search"
                value={searchText}
                placeholder="부분일치"
                onChange={(event) => setSearchText(event.target.value)}
              />
              <button className="interaction-control interaction-control-primary" type="submit">검색</button>
            </div>
          </form>
          <button className="interaction-control pre-specs-reset" type="button" onClick={restoreDefaults}>기본값으로</button>
        </div>
        {gradeFilter ? (
          <p className="pre-specs-grade-filter-note" role="status">
            등급 필터 <strong>{gradeFilter}</strong>는 현재 불러온 페이지에만 적용됩니다. 그룹 머리글의 건수는 서버가 등급 필터 이전 조건으로 센 값이므로 두 숫자가 다를 수 있습니다.
          </p>
        ) : null}
        <p className="pre-specs-policy-note" id="pre-specs-tracking-exception-note">
          추적 예외는 <strong>SW사업대상=Y가 아니지만 추적 중인 발주계획에 연결됨</strong>을 뜻합니다. 값이 없는 SW사업대상은 미확인으로 표시합니다.
        </p>
      </section>

      {result.isPending ? <div className="pre-specs-loading" role="status" aria-live="polite">사전규격 목록을 불러오는 중입니다.</div> : null}
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
            <Panel
              className="pre-specs-table-panel"
              title="누적 사전규격 목록 · 개요 검토 상태별"
              action={total > 0 ? <span className="panel-meta">{total}건 · {offset + 1}–{Math.min(offset + loadedItems.length, total)}</span> : undefined}
            >
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
                <div className="pre-specs-groups" role="list" aria-label="개요 검토 상태 그룹">
                  {GROUP_ORDER.map((status) => {
                    const count = countByStatus.get(status) ?? 0;
                    const groupItems = itemsByStatus.get(status) ?? [];
                    const groupKeyText = status ?? "null";
                    const isPartial = count > 0 && groupItems.length !== count;
                    return (
                      <div className="pre-specs-group" role="listitem" key={groupKeyText}>
                        <ReviewStateGroup
                          count={count}
                          defaultIsOpen={DEFAULT_EXPANDED_GROUPS.includes(status)}
                          label={
                            <span className="pre-specs-group-trigger">
                              <Badge label={groupLabel(status)} variant={groupBadgeVariant(status)} />
                            </span>
                          }
                          status={{ label: groupLabel(status), variant: groupStatusDotVariant(status) }}
                          value={groupKeyText}
                        >
                          {count === 0 ? (
                            <p className="pre-specs-group-empty">이 상태의 사전규격이 현재 필터에 없습니다.</p>
                          ) : (
                            <>
                              {isPartial ? (
                                <p className="pre-specs-group-partial">
                                  전체 {count}건 중 {groupItems.length}건이 보입니다.
                                  {gradeFilter
                                    ? " 등급 필터가 불러온 페이지에만 적용되고 이 건수는 등급 필터 이전 서버 집계입니다."
                                    : " 페이지를 이동하거나 검색 조건을 좁혀 나머지를 확인하십시오."}
                                </p>
                              ) : null}
                              {groupItems.length === 0 ? (
                                <p className="pre-specs-group-empty">
                                  전체 {count}건이 있지만 현재 보이는 목록에는 없습니다.
                                  {gradeFilter
                                    ? " 등급 필터가 불러온 페이지에만 적용되고 이 건수는 등급 필터 이전 서버 집계입니다."
                                    : " 페이지를 이동하거나 검색 조건을 좁혀 보십시오."}
                                </p>
                              ) : (
                                <DenseList aria-label={`${groupLabel(status)} 사전규격`} className="pre-specs-list">
                                  {groupItems.map((item) => (
                                    <PreSpecRow
                                      key={item.notice_pk}
                                      item={item}
                                      listSearch={listSearch}
                                      isSelected={item.notice_pk === selectedTrackingPk}
                                      onSelect={() => selectTrackingPk(item.notice_pk)}
                                      onToggleTracking={() => selectTrackingPk(
                                        (current) => (current === item.notice_pk ? null : item.notice_pk),
                                      )}
                                    />
                                  ))}
                                </DenseList>
                              )}
                            </>
                          )}
                        </ReviewStateGroup>
                      </div>
                    );
                  })}
                </div>
              )}
            </Panel>
          </section>

          <section className="review-split-detail pre-specs-detail-pane" aria-label="선택한 사전규격 상세">
            {selectedTrackingItem ? (
              <div id="pre-specs-tracking-target">
                <Panel
                  className="pre-specs-tracking-target-panel"
                  title={titleOf(selectedTrackingItem)}
                  action={(
                    <span className="pre-specs-detail-actions">
                      {/* 이 화면의 결정은 심층 검토 실행 승인이다(PLAN 단계 D 작업 3).
                          문서 묶음 준비와 승인은 상세가 소유하므로 그 자리로 보낸다. */}
                      <Link to={`/pre-specs/${selectedTrackingItem.notice_pk}${listSearch ? `?${listSearch}` : ""}`}>
                        심층 검토 실행 →
                      </Link>
                      <button type="button" onClick={() => selectTrackingPk(null)}>닫기</button>
                    </span>
                  )}
                >
                  <p className="pre-specs-detail-identity">
                    <span>{selectedTrackingItem.agency?.trim() || "발주기관 미확인"}</span>
                    <span aria-hidden="true">·</span>
                    {selectedTrackingItem.pre_spec_no
                      ? <code>{String(selectedTrackingItem.pre_spec_no)}</code>
                      : <span>번호 미확인</span>}
                  </p>
                  <span className="pre-specs-detail-badges">
                    {originCell(selectedTrackingItem.origin)}
                    {gradeCell(selectedTrackingItem)}
                    {autoPreparationCell(selectedTrackingItem)}
                    {trackingRowBadge(selectedTrackingItem)}
                  </span>
                  <PreSpecDetailFacts item={selectedTrackingItem} />
                  {/* 첨부 집계는 상세 pane이 직접 그리므로 결정 컨트롤은 compact로
                      부른다 — 같은 집계를 한 화면에 두 번 그리지 않는다. */}
                  <PreSpecDocumentSummary item={selectedTrackingItem} />
                  {/* 신규 사전규격에만 `추적 시작하고 심층 검토`를 한 조작으로 준다
                      (ADR-0046 결정 6, PLAN 단계 D 작업 4). 승계된 건은 컨트롤이
                      추적 상태를 다시 묻지 않으므로 이 prop이 쓰이지 않는다. */}
                  <TrackingDecisionControl
                    key={selectedTrackingItem.notice_pk}
                    item={selectedTrackingItem}
                    onDirtyChange={setTrackingDirty}
                    isPending={result.isPending}
                    isError={result.isError}
                    onRetry={() => { void result.refetch(); }}
                    headingLevel="h4"
                    compact
                    onStartedForDeepReview={isInheritedTracking(selectedTrackingItem)
                      ? undefined
                      : () => navigate(`/pre-specs/${selectedTrackingItem.notice_pk}${listSearch ? `?${listSearch}` : ""}`)}
                    onSaved={(saved) => {
                      const noticePk = selectedTrackingItem.notice_pk;
                      queryClient.setQueryData<PreSpecListResponse>(
                        ["pre-spec-detail", noticePk],
                        (current) => updateTrackingProjection(current, noticePk, saved),
                      );
                      queryClient.setQueriesData<PreSpecListResponse>(
                        { queryKey: ["pre-specs"] },
                        (current) => updateTrackingProjection(current, noticePk, saved),
                      );
                      void queryClient.invalidateQueries({ queryKey: ["pre-spec-overview-reviews-v2", noticePk] });
                      void queryClient.invalidateQueries({ queryKey: ["pre-spec-detail", noticePk] });
                      void queryClient.invalidateQueries({ queryKey: ["pre-specs"] });
                      void queryClient.invalidateQueries({ queryKey: ["opportunity", saved.id] });
                    }}
                  />
                </Panel>
              </div>
            ) : (
              <Panel className="pre-specs-selection-empty-panel" title="선택한 사전규격">
                <EmptyState
                  compact
                  title="사전규격을 선택하십시오."
                  description="왼쪽 목록에서 행을 선택하면 추적 상태와 승인 사유를 기록할 수 있습니다. 이 선택은 최종 Go/No-Go와 별개입니다."
                />
              </Panel>
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
          <span>{offset + 1}–{Math.min(offset + loadedItems.length, total)} / {total}</span>
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
    </section>
  );
}
