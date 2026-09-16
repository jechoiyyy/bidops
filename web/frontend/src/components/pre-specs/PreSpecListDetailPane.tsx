import type { MouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Heading } from "@astryxdesign/core/Heading";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Token } from "@astryxdesign/core/Token";
import {
  isInheritedTracking,
  TrackingDecisionControl,
  updateTrackingProjection,
} from "./TrackingDecisionControl";
import { useCurrentPageOverview } from "./PageOverviewSection";
import { DeadlineMark } from "./PreSpecListRow";
import { nextActionOf } from "../../lib/preSpecNextAction";
import { api } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { gradeLabel, gradeSourceLabel } from "../../lib/grade";
import { readPreSpecLifecycle } from "../../lib/noticeLifecycle";
import { formatPreSpecCaution, preSpecCautions } from "../../lib/preSpecCautions";
import { preSpecDetailUrl } from "../../lib/preSpecSelectionReview";
import {
  agencyOf,
  exactBudget,
  originLabel,
  titleOf,
  trackingLabel,
} from "../../lib/preSpecViews";
import {
  hasCanonicalOverviewNoticeId,
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_VALIDATION,
  PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION,
} from "../../lib/preSpecOverviewStatus";
import type {
  PageOverviewCurrentStatus,
  PageOverviewPayload,
  PageOverviewView,
  PreSpecListItem,
} from "../../lib/types";

const TRACKING_REASON_PRESETS = [
  "후속 입찰공고 확인",
  "세부 과업·연계 범위 확인",
  "참여 자격·실적 확인 필요",
] as const;

/** 과업 요약은 앞 세 건만 이 자리에 온다. 나머지는 상세가 갖는다(spec §3.1 3행). */
const TASK_PREVIEW_LIMIT = 3;

/** 상세 ⑤(근거 문서·첨부)의 anchor. 상세의 id는 P3가 정하므로 지금은 이 값으로 둔다. */
const EVIDENCE_ANCHOR = "ps-evidence";

/** 새 계약에는 `stale`이 없다. 남은 자리를 위한 문장만 두고 상태를 지어내지 않는다. */
function overviewWaitingDescription(status: PageOverviewCurrentStatus): string {
  return status === "stale"
    ? "이전 입력 기준의 결과는 현재 결과로 쓸 수 없습니다. 사람 확인이 필요합니다."
    : PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION[status];
}

/**
 * 예산·일정 4칸은 좁아서 `9.16 23:59`처럼 월·일과 24시간 시:분만 쓴다
 * (spec §3.1 4행, 시안 mockups/artboards/Main.dc.html 183줄). 연도가 필요한
 * 자리는 머리줄의 `게시`가 이미 전체 일시로 갖는다. 값이 없으면 `null`이고
 * 자리 표시 문구를 지어내지 않는다.
 */
function shortDateTime(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const value_ = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? "";
  return `${value_("month")}.${value_("day")} ${value_("hour")}:${value_("minute")}`;
}

/** 결과 본문의 주장 목록. v3·v4 모두 `text`를 갖는다. */
function factTexts(facts: PageOverviewPayload["main_tasks"]): string[] {
  return facts.map((fact) => fact.text);
}

/** 근거 쪽 링크는 v4의 `evidence`에만 있다. 없으면 링크를 만들지 않는다. */
function firstEvidencePage(payload: PageOverviewPayload): number | null {
  if (payload.schema_version !== "bidops.prespec-overview-page-review.v4") return null;
  return payload.budget_and_period[0]?.evidence[0]?.page ?? null;
}

/**
 * 선택한 사전규격 하나 — 담당자가 추적을 시작할지 판단하는 데 필요한 것만
 * 위에서 아래로 한 화면에 둔다(docs/0915_ui-redesign/spec.md §3.1·§3.3).
 *
 * 순서는 머리 → 사업 설명 → 주요 과업 요약 → 예산·일정 4칸 → 일정·규모 한 줄 →
 * 주의사항이고, 추적 조작과 상세 진입은 바닥에 고정된다. **첨부 목록·처리 이력·
 * 범위 확정 같은 상세의 일은 이 자리에 없다** — 상세 화면이 소유한다.
 *
 * 값은 전부 이미 받은 응답 그대로다: 목록 projection(기관·예산·마감·등급·추적
 * 상태·첨부 집계), 개요 검토 응답의 검증된 주장, notice의 `lifecycle`뿐이며
 * 새 분석이나 추정은 하지 않는다. 없으면 `미확인` 계열로 남긴다.
 */
export function PreSpecDetail({
  item,
  listSearch,
  onDirtyChange,
  onSaved,
  onOpenDetail,
  onOpenDetailAfterSaved,
}: {
  item: PreSpecListItem;
  listSearch: string;
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (saved: Parameters<typeof updateTrackingProjection>[2]) => void;
  onOpenDetail?: () => void;
  /** Called after the tracking mutation has committed. Unlike a normal
   * detail link, this transition has no unsaved draft to guard. */
  onOpenDetailAfterSaved?: () => void;
}) {
  const navigate = useNavigate();
  const noticePk = item.notice_pk;
  const detailUrl = preSpecDetailUrl(noticePk, listSearch);

  // 개요 본문과 같은 query를 읽는다(같은 key라 요청이 늘지 않는다).
  const pageOverview = useCurrentPageOverview(noticePk);
  const overviewQuery = pageOverview.query;
  // 응답이 이 공고의 정본인지만 본다. 어긋나면 다른 공고의 결과를 그리지 않는다.
  const overviewInvalid = overviewQuery.isSuccess
    && !hasCanonicalOverviewNoticeId(overviewQuery.data, noticePk);
  const overviewValid = pageOverview.isValid && !overviewInvalid;
  const review: PageOverviewView | null = overviewValid
    ? pageOverview.currentResult ?? pageOverview.legacyReview
    : null;
  const payload = review?.payload ?? null;
  const validation = PRE_SPEC_OVERVIEW_VALIDATION[review ? review.validation_status : "pending"];

  // 본공고 번호는 목록 projection에 없고 notice의 `lifecycle`에만 있다. 상세
  // 화면과 **같은 query key**를 써서 상세로 넘어갈 때 요청이 늘지 않게 한다.
  const noticeQuery = useQuery({
    queryKey: ["pre-spec-notice", noticePk],
    queryFn: ({ signal }) => api.getNotice(noticePk, { signal }),
    retry: false,
    staleTime: 30_000,
  });
  const bidNoticeNo = noticeQuery.isSuccess && noticeQuery.data.id === noticePk
    ? readPreSpecLifecycle(noticeQuery.data.lifecycle).bid_ntice_no_list
    : null;

  // 결과 자리가 비었을 때 무엇을 기다리는지. 상태 어휘와 문장은
  // `preSpecOverviewStatus`가 소유하며 여기서 새 문장을 만들지 않는다.
  const emptyOverviewText = ((): string => {
    if (overviewQuery.isPending) return "개요 검토 결과를 불러오는 중입니다.";
    if (overviewQuery.isError) return "개요 검토 API 응답을 확인할 수 없습니다.";
    if (!overviewValid) return "개요 검토 결과를 확인할 수 없습니다.";
    if (payload) return "이번 입력에서는 확인되지 않았습니다.";
    if (pageOverview.current) return overviewWaitingDescription(pageOverview.current.status);
    if (item.overview_review_status) return PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION[item.overview_review_status];
    return PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL;
  })();

  const description = payload?.business_overview[0]?.text ?? null;
  const taskTexts = payload ? factTexts(payload.main_tasks) : [];
  const shownTasks = taskTexts.slice(0, TASK_PREVIEW_LIMIT);
  const scaleText = payload?.budget_and_period[0]?.text ?? null;
  const scalePage = payload ? firstEvidencePage(payload) : null;
  const scaleHref = review && scalePage !== null
    ? `${api.preSpecOverviewRunPdfUrl(review.notice_id, review.id)}#page=${scalePage}`
    : null;

  // spec §3.2 — 결정적 산출이고 모델 호출이 없다. 검증 기록·첨부 집계·자동 준비
  // 상태·`unknowns`만 세고 고른다.
  const caution = preSpecCautions({
    item,
    verification: overviewValid ? pageOverview.verification : null,
    unknowns: payload?.unknowns ?? [],
  });

  const inherited = isInheritedTracking(item);
  // 연결이 없으면 `사업기회 미연결`, 연결은 있는데 값이 없으면 `미확인`이다.
  // 둘 중 어느 것도 사람이 고른 `미선택`으로 바꾸지 않는다.
  const trackingText = trackingLabel(item);
  // 이미 기록된 건은 폼 대신 "현재 추적 상태" 블록이 나오고, 그 블록이
  // `보류·추적 종료는 사업 추적에서 변경합니다.`를 스스로 그린다. 같은 문장을
  // 줄 1에서 한 번 더 적지 않는다(spec §3.3 줄 1 캡션은 폼이 있을 때의 것이다).
  const trackingRecorded = item.opportunity_id !== null
    && item.tracking_status !== null
    && item.tracking_status !== "미선택";
  const trackingFormShown = !inherited && !trackingRecorded;

  const openDetailHref = (event: MouseEvent) => {
    if (!onOpenDetail || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onOpenDetail();
  };

  return (
    <div className="pre-specs-detail">
      {/* ① 머리 — 기관·구분 칩·사업명·식별 줄. 머리는 스크롤 밖에 있어 어떤
          사업을 보고 있는지가 늘 보인다(spec §3.1 1행). */}
      <header className="pre-specs-detail-header">
        <div className="pre-specs-detail-identity">
          <span className="pre-specs-detail-agency">
            <span>발주기관</span>
            <strong>{agencyOf(item)}</strong>
          </span>
          <span className="pre-specs-detail-chips">
            <Token size="sm" label={originLabel(item.origin)} color="default" />
            <Token size="sm" label={item.business_division?.trim() || "업무구분 미확인"} color="default" />
            <Token
              size="sm"
              label={item.sw_business_status === null ? "SW 미확인" : `SW사업대상 ${item.sw_business_status}`}
              color="default"
            />
            <Token size="sm" label={`추적 결정 · ${trackingText}`} color="default" />
          </span>
        </div>
        <div className="pre-specs-detail-title">
          <Heading level={3}>{titleOf(item)}</Heading>
        </div>
        <p className="pre-specs-detail-facts">
          <span>
            사전규격 {item.pre_spec_no ? <code className="mono">{item.pre_spec_no}</code> : "번호 미확인"}
          </span>
          <span aria-hidden="true">·</span>
          <span>게시 {formatDateTime(item.published_at)}</span>
          <span aria-hidden="true">·</span>
          <span>
            적합성 등급 <strong>{gradeLabel(item.grade)}</strong> ({gradeSourceLabel(item.grade_source)})
          </span>
        </p>
      </header>

      <div className="pre-specs-detail-scroll">
        {/* ② 사업 설명 — 검증 라벨을 캡션에 붙여, 검증되지 않은 문장을 판정처럼
            읽지 않게 한다(spec §3.1 2행). */}
        <section className="pre-specs-detail-block" aria-label="사업 설명">
          <p className="pre-specs-detail-caption">
            <span className="pre-specs-detail-section-label">사업 설명</span>
            <span aria-hidden="true">·</span>
            <span>개요 검토 결과 · {validation.label}</span>
          </p>
          <p className={`pre-specs-detail-summary${description ? "" : " is-empty"}`}>
            {description ?? emptyOverviewText}
          </p>
        </section>

        {/* ③ 주요 과업 요약 — 앞 세 건만이고 건수를 숨기지 않는다. */}
        <section className="pre-specs-detail-block" aria-label="주요 과업 요약">
          <p className="pre-specs-detail-caption">
            <span className="pre-specs-detail-section-label">주요 과업 요약</span>
            <span className="pre-specs-detail-caption-end">
              {taskTexts.length > 0
                ? `${taskTexts.length}건 중 ${shownTasks.length}건 · 전체는 상세에서`
                : "전체는 상세에서"}
            </span>
          </p>
          {shownTasks.length > 0 ? (
            <ol className="pre-specs-detail-tasks">
              {shownTasks.map((text, index) => (
                <li key={`${noticePk}-task-${index}`}>
                  <span aria-hidden="true">{index + 1}</span>
                  <span>{text}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="pre-specs-detail-summary is-empty">{emptyOverviewText}</p>
          )}
        </section>

        {/* ④ 예산·일정 4칸 — 구조화 필드만 온다. 모델 문장은 아래 ⑤ 한 줄이
            갖는다(spec §3.1 4행). */}
        <dl className="pre-specs-detail-figures">
          <div>
            <dt className="pre-specs-detail-field-label">사업 예산</dt>
            <dd>{exactBudget(item.budget)}</dd>
          </div>
          <div>
            <dt className="pre-specs-detail-field-label">의견등록 마감</dt>
            <dd className="pre-specs-detail-deadline">
              <span>{shortDateTime(item.deadline_at) ?? "마감 일시 없음"}</span>
              {item.deadline_at ? <DeadlineMark value={item.deadline_at} /> : null}
            </dd>
          </div>
          <div>
            <dt className="pre-specs-detail-field-label">게시</dt>
            <dd className={shortDateTime(item.published_at) ? undefined : "is-unknown"}>
              {shortDateTime(item.published_at) ?? "미확인"}
            </dd>
          </div>
          <div>
            <dt className="pre-specs-detail-field-label">본공고</dt>
            <dd className={bidNoticeNo ? undefined : "is-unknown"}>{bidNoticeNo ?? "미확인"}</dd>
          </div>
        </dl>

        {/* ⑤ 일정·규모 한 줄 — 항목이 없으면 줄 자체를 만들지 않는다. */}
        {scaleText ? (
          <p className="pre-specs-detail-scale">
            <span className="pre-specs-detail-scale-label">사업 규모·일정</span>
            <span aria-hidden="true">·</span>
            <span className="pre-specs-detail-scale-text">{scaleText}</span>
            {scaleHref ? (
              <a href={scaleHref} rel="noreferrer" target="_blank">{scalePage}쪽 ↗</a>
            ) : null}
          </p>
        ) : null}

        {/* ⑥ 주의사항 — 건수와 문구는 `preSpecCautions`가 정한다. 주의가 있을
            때만 색을 쓰고, 없을 때는 같은 줄을 중립으로 둔다. */}
        <p className={`pre-specs-detail-caution${caution.tone === "caution" ? " is-caution" : ""}`}>
          <span className="pre-specs-detail-caution-text">{formatPreSpecCaution(caution)}</span>
          <Link className="pre-specs-detail-caution-link" to={`${detailUrl}#${EVIDENCE_ANCHOR}`}>
            근거 보기 →
          </Link>
        </p>
      </div>

      {/* ⑦ 바닥 고정 — 위는 **사람의 추적 선택**, 아래는 다음 작업이다. 두 줄은
          서로 다른 결정이며 추적 선택이 모델 분석 승인이나 최종 Go/No-Go를
          뜻하지 않는다(spec §3.3). */}
      <footer className="pre-specs-detail-actions" id="pre-specs-tracking-target">
        <div className="pre-specs-action-row">
          <div className="pre-specs-tracking-head">
            <strong>추적 결정</strong>
            <span>현재 · {trackingText} → 저장하면 계속 추적</span>
          </div>
          {trackingFormShown ? (
            <span className="pre-specs-tracking-elsewhere">보류·추적 종료는 사업 추적에서 변경</span>
          ) : null}
        </div>

        {/* Astryx `Selector`가 locale 문구를 읽으므로 상세 화면과 같은 provider로 감싼다. */}
        <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}>
          <TrackingDecisionControl
            key={noticePk}
            item={item}
            isPending={false}
            isError={false}
            onRetry={() => { void overviewQuery.refetch(); }}
            headingLevel="h4"
            compact
            presentation="inline"
            showRecordHeading={false}
            showIntent={false}
            reasonPresets={TRACKING_REASON_PRESETS}
            onDirtyChange={onDirtyChange}
            // 발주계획에서 승계한 건은 이 화면이 추적을 다시 묻지 않으므로
            // 한 조작 진입점도 신규 건에만 준다(ADR-0046 결정 6).
            onStartedForDeepReview={inherited ? undefined : () => {
              if (onOpenDetailAfterSaved) onOpenDetailAfterSaved();
              else if (onOpenDetail) onOpenDetail();
              else navigate(detailUrl);
            }}
            onSaved={onSaved}
          />
        </InternationalizationProvider>

        <div className="pre-specs-action-row">
          <div className="pre-specs-next-action">
            <span>다음 작업</span>
            <strong>{nextActionOf(item)}</strong>
            <span aria-hidden="true">·</span>
            <span>입찰 참여 여부는 최종 Go/No-Go에서 결정</span>
          </div>
          <Link
            className="interaction-control interaction-control-primary pre-specs-detail-open"
            to={detailUrl}
            onClick={openDetailHref}
          >
            상세 페이지 열기 →
          </Link>
        </div>
      </footer>
    </div>
  );
}
