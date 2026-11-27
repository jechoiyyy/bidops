import type { MouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { ClassTag, StatusMark } from "../common/Marks";
import { SideFacts } from "../common/Facts";
import { StickyDecisionHeader } from "../common/ReviewPrimitives";
import { PreSpecAgencyFeature, PreSpecExclusionRecord } from "./PreSpecAgency";
import {
  TrackingDecisionControl,
  type PreSpecTrackingDecisionControlProps,
} from "./TrackingDecisionControl";
import { useCurrentPageOverview } from "./PageOverviewSection";
import { DeadlineMark } from "./PreSpecListRow";
import { api } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { readPreSpecLifecycle } from "../../lib/noticeLifecycle";
import { preSpecAutoPreparationReasonLabel } from "../../lib/preSpecAutoPreparation";
import { formatPreSpecCaution, preSpecCautions } from "../../lib/preSpecCautions";
import { preSpecDetailUrl } from "../../lib/preSpecSelectionReview";
import {
  companyFitMark,
  exactBudget,
  originLabel,
  titleOf,
  trackingLabel,
} from "../../lib/preSpecViews";
import {
  hasCanonicalOverviewNoticeId,
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
  PRE_SPEC_OVERVIEW_VALIDATION,
  PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION,
} from "../../lib/preSpecOverviewStatus";
import type {
  PageOverviewPayload,
  PageOverviewView,
  PreSpecListItem,
} from "../../lib/types";

/** 과업 요약은 앞 세 건만 이 자리에 온다. 나머지는 상세가 갖는다(spec §3.1 3행). */
const TASK_PREVIEW_LIMIT = 3;

/** 상세 ⑤(근거 문서·첨부)의 anchor. 상세의 id는 P3가 정하므로 지금은 이 값으로 둔다. */
const EVIDENCE_ANCHOR = "ps-evidence";

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
  onReviewExclusion,
}: {
  item: PreSpecListItem;
  onReviewExclusion?: () => void;
  listSearch: string;
  onDirtyChange: (dirty: boolean) => void;
  onSaved: PreSpecTrackingDecisionControlProps["onSaved"];
  onOpenDetail?: () => void;
}) {
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

  const overviewStatus = overviewValid && !overviewQuery.isError
    ? pageOverview.current?.status ?? item.overview_review_status
    : null;
  const overviewState = (() => {
    if (overviewQuery.isPending) return { title: "개요 검토 결과를 불러오는 중" };
    if (overviewQuery.isError || !overviewValid) return { title: "개요 검토 결과를 확인할 수 없어요" };
    if (overviewStatus === null) return {
      title: PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
      description: "아직 개요 검토 실행 기록이 없어요.",
    };
    if (overviewStatus === "failed") return {
      title: "개요 검토 실패",
      description: "상세 페이지의 ‘처리 상태·기술 정보’에서 마지막 실행을 확인할 수 있어요.",
    };
    if (overviewStatus === "stale") return {
      title: "개요 검토 결과 확인 필요",
      description: "이전 입력의 개요 검토 결과는 사람 확인이 필요해요.",
    };
    return {
      title: `개요 검토 · ${PRE_SPEC_OVERVIEW_STATUS_LABEL[overviewStatus]}`,
      description: PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION[overviewStatus],
    };
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
  // 상태만 세고 고른다. 이 목록 상세는 심층 검토 보고서를 읽지 않으므로
  // 미확인 건수는 `null`(알 수 없음)로 남기고 지어내지 않는다(ADR-0057).
  const caution = preSpecCautions({
    item,
    verification: overviewValid ? pageOverview.verification : null,
    deepReviewUnknownCount: null,
  });
  const preparationNote = item.auto_preparation_reason === "engine_review_request" && caution.count === 0
    ? preSpecAutoPreparationReasonLabel(item.auto_preparation_reason) : null;
  const showCaution = caution.count > 0 || payload !== null || preparationNote !== null;

  // 연결이 없으면 `사업기회 미연결`, 연결은 있는데 값이 없으면 `미확인`이다.
  // 둘 중 어느 것도 사람이 고른 `미선택`으로 바꾸지 않는다.
  const trackingText = trackingLabel(item);
  // 목록과 상세가 서로 다른 우선순위를 계산하지 않도록 서버가 정한
  // nullable next_action 코드 하나만 표시한다. null은 추가 행동이 없다는
  // 뜻이며 실패·마감 문구를 클라이언트에서 새로 만들지 않는다.
  const openDetailHref = (event: MouseEvent) => {
    if (!onOpenDetail || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onOpenDetail();
  };

  return (
    <div className="pre-specs-detail">
      {/* ① 머리 — 기관·구분 칩·사업명·식별 줄. 머리는 스크롤 밖에 있어 어떤
          사업을 보고 있는지가 늘 보인다(spec §3.1 1행). */}
      <StickyDecisionHeader className="review-detail-head pre-specs-detail-header" label="사전규격 상세 헤더">
        {/* A안(승인 시안) — 기관 블록이 전체 폭을 쓰고, 사업명 → 칩 → 식별 줄이
            이어진다. 강조 블록은 발주계획 상세와 같은 공용 primitive다(ADR-0062). */}
        {/* 수요기관과 대행 공고기관은 같은 보조 글자 단으로 한 줄에 둔다. */}
        <PreSpecAgencyFeature
          agency={item.agency}
          className="pre-specs-detail-agency"
          demandAgency={item.demand_agency}
        />
        <div className="pre-specs-detail-title">
          <Heading level={3}>{titleOf(item)}</Heading>
        </div>
        <span className="pre-specs-detail-chips">
          {item.review_exclusion_status === "excluded" ? <StatusMark mark={{ label: "검토 제외", tone: "neutral" }} /> : null}
          <ClassTag label={originLabel(item.origin)} />
          <ClassTag label={item.business_division?.trim() || "업무구분 미확인"} />
          <ClassTag label={item.sw_business_status === null ? "SW 미확인" : `SW사업대상 ${item.sw_business_status}`} />
          <StatusMark mark={{ label: `추적 결정 · ${trackingText}`, tone: "neutral" }} />
        </span>
        {/* 제외 기록은 칩이 말한 상태의 근거다 — 누가·언제·왜(spec §6.2). */}
        <PreSpecExclusionRecord className="pre-specs-detail-exclusion" item={item} />
        <p className="pre-specs-detail-facts review-detail-identity">
          <span>
            사전규격 {item.pre_spec_no ? <code className="mono">{item.pre_spec_no}</code> : "번호 미확인"}
          </span>
          <span aria-hidden="true">·</span>
          <span>게시 {formatDateTime(item.published_at)}</span>
        </p>
      </StickyDecisionHeader>

      <div className="pre-specs-detail-scroll">
        <SideFacts className="pre-specs-detail-figures" items={[
          { label: "사업 예산", value: exactBudget(item.budget) },
          { label: "의견등록 마감", value: (
            <span className="pre-specs-detail-deadline">
              <span>{shortDateTime(item.deadline_at) ?? "마감 일시 없음"}</span>
              {item.deadline_at ? <DeadlineMark value={item.deadline_at} /> : null}
            </span>
          ) },
          { label: "게시", value: shortDateTime(item.published_at) ?? "미확인" },
          { label: "본공고", value: bidNoticeNo ?? "미확인" },
        ]} />

        {review && payload ? (
          <>
            {/* ② 사업 설명 — 검증 라벨을 캡션에 붙여, 검증되지 않은 문장을 판정처럼
                읽지 않게 한다(spec §3.1 2행). */}
            <section className="pre-specs-detail-block" aria-label="사업 설명">
              <p className="pre-specs-detail-caption">
                <span className="pre-specs-detail-section-label">사업 설명</span>
                <span aria-hidden="true">·</span>
                <span>개요 검토 결과 · {PRE_SPEC_OVERVIEW_VALIDATION[review.validation_status].label}</span>
              </p>
              <p className={`pre-specs-detail-summary${description ? "" : " is-empty"}`}>
                {description ?? "이번 입력에서는 확인되지 않았어요."}
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
                <p className="pre-specs-detail-summary is-empty">이번 입력에서는 확인되지 않았어요.</p>
              )}
            </section>
          </>
        ) : (
          <section
            aria-label="개요 검토 상태"
            className={`pre-specs-detail-overview-state${overviewStatus === "failed" ? " is-failed" : ""}`}
          >
            <Heading level={4}>
              {overviewStatus === "failed" ? <StatusMark mark={{ label: overviewState.title, tone: "error" }} /> : overviewState.title}
            </Heading>
            {overviewState.description ? <p>{overviewState.description}</p> : null}
          </section>
        )}



        {/* 회사 핏 한 줄(PS-01). 서버 그룹 그대로이고, 추천은 표시만 한다 — 분석 요청 버튼·링크는 두지 않는다. */}
        <p className="pre-specs-detail-fit" aria-label="회사 핏">
          <span className="pre-specs-detail-section-label">회사 핏</span>
          <StatusMark mark={companyFitMark(item)} />
          {item.company_fit?.engine_suggested ? <span className="pre-specs-detail-fit-suggested">엔진 분석 추천</span> : null}
        </p>

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
        <p className={`pre-specs-detail-caution${caution.tone === "caution" ? " is-caution" : ""}${showCaution ? "" : " is-source-only"}`}>
          {showCaution ? (
            <span className="pre-specs-detail-caution-text">{preparationNote ?? formatPreSpecCaution(caution)}</span>
          ) : null}
          <Link className="pre-specs-detail-caution-link" to={`${detailUrl}#${EVIDENCE_ANCHOR}`}>
            {payload ? "근거 보기 →" : "원문·첨부 보기 →"}
          </Link>
        </p>
      </div>

      <TrackingDecisionControl
        key={noticePk}
        item={item}
        isPending={false}
        isError={false}
        onRetry={() => { void overviewQuery.refetch(); }}
        compact
        presentation="preview"
        onDirtyChange={onDirtyChange}
        onSaved={onSaved}
        previewActions={(
          <>
            {onReviewExclusion ? <Button size="md" variant="secondary"
              label={item.review_exclusion_status === "excluded" ? "검토 목록으로 복원" : "검토 제외"}
              onClick={onReviewExclusion} /> : null}
            <Link
              className="interaction-control pre-specs-detail-open"
              to={detailUrl}
              onClick={openDetailHref}
            >
              상세 페이지 열기 →
            </Link>
          </>
        )}
      />
    </div>
  );
}
