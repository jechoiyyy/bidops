import { useState, type Ref } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import {
  TRACKING_OTHER_REASON,
  TrackingDecisionActions,
  TrackingDecisionInputs,
  TrackingSaveError,
} from "../common/TrackingDecisionForm";
import {
  AgencyFeature,
  ReviewDecisionAction,
  ReviewDecisionBar,
  ReviewValue,
  StickyDecisionHeader,
} from "../common/ReviewPrimitives";
import { EmptyState } from "../common/EmptyState";
import { api } from "../../lib/api";
import type { ApiErrorDescription } from "../../lib/apiErrors";
import type {
  OpportunityTrackingStatus,
  OrderPlanListItem,
  OrderPlanScreeningExecutionSummary,
} from "../../lib/types";
import {
  TRACKING_REASONS,
  budgetValue,
  detailFactValue,
  formatKstDateShort,
  formatMoment,
  hasNoModelJudgment,
  NO_MODEL_JUDGMENT_LABEL,
  noticePostedLabel,
  plannedTiming,
  qwenBadgeVariant,
  qwenRowLabel,
  stage1BadgeLabel,
  stage1BadgeVariant,
  textOrUnknown,
  trackingAvailability,
} from "./orderPlanFormat";
import type { TrackingAvailability } from "./orderPlanFormat";

/**
 * 추적 결정 상태의 실무 말(0921 명세 §3.1).
 *
 * `계약 미구현`은 "서버 API 계약이 아직 없다"는 뜻이었는데, 이 화면에서 `계약`은
 * 조달 계약(계약방법)을 가리키는 낱말이라 뜻이 겹친다. 사실은 그대로 두고
 * **이 화면에서 추적을 기록할 수 없다**는 실무 결과를 말한다. `사업기회 미연결`은
 * 소유 사업기회를 확인하지 못한 것이며 둘은 서로 다른 상태다(뭉개지 않는다).
 */
function trackingStatusLabel(item: OrderPlanListItem | null): string {
  switch (trackingAvailability(item)) {
    case "contract_missing":
      return "추적 기록 미지원";
    case "opportunity_missing":
      return "사업기회 미연결";
    default:
      return item?.tracking?.tracking_status === "미선택"
        ? "추적 결정 없음"
        : (item?.tracking?.tracking_status ?? "추적 결정 없음");
  }
}

/**
 * 상세 머리 오른쪽 상태 표식(최종 시안): 아직 추적을 정하지 않은 건은 `결정 필요`(주의색),
 * 계속 추적은 `추적 중`(브랜드 옅은 채움), 보류·종료는 회색이다. 기록할 수 없는 건(미지원·미연결)은
 * 그 사실 그대로 주의색으로 둔다. 미선택은 추적 종료가 아니다.
 */
function trackingTag(item: OrderPlanListItem): { label: string; tone: "warning" | "brand" | "muted" } {
  const availability = trackingAvailability(item);
  if (availability !== "available") return { label: trackingStatusLabel(item), tone: "warning" };
  switch (item.tracking?.tracking_status) {
    case "계속 추적":
      return { label: "추적 중", tone: "brand" };
    case "보류":
      return { label: "보류", tone: "muted" };
    case "종료":
      return { label: "추적 종료", tone: "muted" };
    default:
      return { label: "결정 필요", tone: "warning" };
  }
}

/** `모델이 관련으로 본 이유`처럼 모델 판단을 제목에 쓴다. 판단이 없으면 일반 이름이다. */
function evidenceHeading(item: OrderPlanListItem): string {
  if (hasNoModelJudgment(item)) return "관련 근거";
  switch (item.qwen_relevance) {
    case "relevant":
      return "모델이 관련으로 본 이유";
    case "uncertain":
      return "모델이 불확실로 본 이유";
    case "not_relevant":
      return "모델이 비관련으로 본 이유";
    default:
      return "관련 근거";
  }
}

/**
 * 상세 pane 바닥의 추적 결정 입력.
 *
 * 머리줄(추적 결정 · 현재 상태 · 위치) 아래에 추적 결정 입력 한 벌(`TrackingDecisionInputs`, C-7)을
 * 둔다 — 선택 사유(직접 입력 포함)와 담당자 이름. 결정 버튼과 안내 한 줄은 `ReviewDecisionBar`의
 * action·hint 자리에 있고, 저장 실패는 입력 바로 아래에 같은 모양(`TrackingSaveError`)으로 남는다.
 */
function TrackingDecisionFields({
  item,
  reasonChoice,
  onReasonChoiceChange,
  customReason,
  onCustomReasonChange,
  actorName,
  onActorNameChange,
  position,
  lastReason,
  onReuseLastReason,
  sectionRef,
  problem,
  isDisabled = false,
}: {
  item: OrderPlanListItem;
  reasonChoice: string;
  onReasonChoiceChange: (value: string) => void;
  customReason: string;
  onCustomReasonChange: (value: string) => void;
  actorName: string;
  onActorNameChange: (value: string) => void;
  position: string;
  /** 이 탭에서 마지막으로 **저장에 성공한** 사유. 없으면 빈 문자열이다. */
  lastReason: string;
  onReuseLastReason: () => void;
  sectionRef: Ref<HTMLElement>;
  problem: ApiErrorDescription | null;
  isDisabled?: boolean;
}) {
  /** 지금 계약에 실릴 사유. 이 값이 이미 있으면 다시 쓰기 단추를 그리지 않는다. */
  const currentReason = reasonChoice === TRACKING_OTHER_REASON ? customReason.trim() : reasonChoice;
  // 이름이 이미 있으면(탭 세션 또는 사이드바 담당자 칸) 시안대로 `… 이름으로 기록해요` 한 줄로 접는다.
  // 화면에 들어올 때 이름이 없었으면 입력 칸을 그대로 두어 적는 중에 칸이 사라지지 않게 한다.
  const [actorCollapsed, setActorCollapsed] = useState(() => actorName.trim() !== "");
  const showActorLine = actorCollapsed && actorName.trim() !== "";
  return (
    <section className="c2l-tracking" aria-labelledby={`c2l-tracking-${item.order_plan_pk}`} ref={sectionRef}>
      <header className="c2l-tracking-head">
        <h3 className="c2l-tracking-title" id={`c2l-tracking-${item.order_plan_pk}`}>이 사업을 추적할까요?</h3>
        {/* 현재 상태는 상세 머리의 표식이 보인다. 결정 묶음 안에서도 낭독기가 같은 사실을 읽게 남긴다. */}
        <span className="visually-hidden">현재 상태 {trackingStatusLabel(item)}</span>
        <p className="c2l-tracking-position">
          {position}
          {showActorLine ? ` · ${actorName.trim()} 이름으로 기록해요` : ""}
        </p>
      </header>
      <div className="c2l-tracking-fields">
        <TrackingDecisionInputs
          presets={TRACKING_REASONS}
          choice={reasonChoice}
          onChoiceChange={onReasonChoiceChange}
          custom={customReason}
          onCustomChange={onCustomReasonChange}
          actorName={actorName}
          onActorNameChange={onActorNameChange}
          isDisabled={isDisabled}
          reasonClassName="c2l-reason-field"
          // 담당자 이름은 이 탭에서만 기억한다(화면이 sessionStorage로 따로 둔다).
          rememberActor={false}
          actorPlaceholder="이름 입력"
          actorSlot={showActorLine ? (
            <p className="c2l-actor-line">
              <span className="visually-hidden">담당자 이름 {actorName.trim()} · 결정 이력에 남는 이름이며 인증이 아닙니다.</span>
              <button className="c2l-actor-change" disabled={isDisabled} onClick={() => setActorCollapsed(false)} type="button">이름 바꾸기</button>
            </p>
          ) : undefined}
          reasonExtra={lastReason && !currentReason ? (
            /* 드롭다운을 미리 채우지 않는다(PRD §3.3). 직전 사유는 **사람이 누를 때에만**
               들어가는 후보이고, 무엇이 들어갈지 단추 이름이 그대로 말한다. 긴 사유는 CSS가
               말줄임하므로 전문은 감싸는 span의 `title`이 진다(Astryx `Button`은 title을 받지 않는다). */
            <span className="c2l-reason-reuse" title={lastReason}>
              <Button
                label={`직전 사유 다시 쓰기 · ${lastReason}`}
                onClick={onReuseLastReason}
                size="sm"
                variant="ghost"
                isDisabled={isDisabled}
              />
            </span>
          ) : null}
        />
      </div>
      {problem ? <TrackingSaveError problem={problem} /> : null}
    </section>
  );
}

/**
 * 판정을 낸 실행의 경고 한 줄. 부분 산출물이 있거나 실행이 실패·부분 성공일 때만 그린다
 * (0921 명세 §3.1, 경고 ③·④). 평상시에는 아무것도 그리지 않는다.
 *
 * 실행 요약이 없으면(목록에 그 실행이 없으면) 줄을 그리지 않는다 — 문구를 만들려고
 * 실행을 추가로 조회하지 않고, 없는 사실을 "문제 없음"으로 적지도 않는다.
 */
function ExecutionWarningLine({ execution }: { execution: OrderPlanScreeningExecutionSummary | null }) {
  if (!execution) return null;
  const failed = execution.status === "실패" || execution.status === "부분 성공";
  if (!execution.partial_artifact && !failed) return null;
  const fact = execution.partial_artifact
    ? "이 판정의 실행에 부분 산출물이 있습니다"
    : `이 판정의 실행이 ${execution.status}입니다`;
  return (
    <p className="c2l-detail-warn c2l-exec-warn" role="note">
      <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} viewBox="0 0 24 24"><path d="M12 3 2 20h20z" /><path d="M12 10v4M12 17h.01" /></svg>
      <Link
        className="c2l-scope-link"
        to={`/runs?run=${encodeURIComponent(execution.source_run_id)}&execution=${encodeURIComponent(execution.execution_id)}`}
      >
        {fact} · 운영 화면에서 확인 →
      </Link>
    </p>
  );
}

export interface OrderPlanDetailPaneProps {
  listPending: boolean;
  listError: boolean;
  isExplicitDeepLink: boolean;
  deepLinkFailed: boolean;
  invalidSelectedParam: boolean;
  isCumulative: boolean;
  explicitTargetInFilteredItems: boolean;
  selectedItem: OrderPlanListItem | null;
  trackingAvailabilityState: TrackingAvailability;
  selectedSourceUrl: string | null;
  feedbackSummaryLabel: string;
  /**
   * 이 행의 결과를 낸 실행 요약. 이미 받아 둔 실행 목록에서 찾은 것이며, 목록에 없으면
   * `null`이다 — 경고 한 줄을 그리려고 실행을 따로 조회하지 않는다.
   */
  rowExecution: OrderPlanScreeningExecutionSummary | null;
  bulkPending: boolean;
  onOpenFeedback: () => void;
  /** 추적 결정 저장 실패. `describeApiError`가 옮긴 설명이며 없으면 `null`이다. */
  trackingProblem: ApiErrorDescription | null;
  trackingMessage: { pk: number; text: string } | null;
  trackingDisabledReason: string | undefined;
  trackingActor: string;
  onActorNameChange: (value: string) => void;
  customReason: string;
  onCustomReasonChange: (value: string) => void;
  reasonChoice: string;
  onReasonChoiceChange: (value: string) => void;
  lastReason: string;
  onReuseLastReason: () => void;
  selectedIndex: number;
  total: number;
  trackingSectionRef: Ref<HTMLElement>;
  trackingReady: boolean;
  onDecideTracking: (status: Exclude<OpportunityTrackingStatus, "미선택">) => void;
  onSkipCurrent: () => void;
  onResetFilters: () => void;
}

export function OrderPlanDetailPane({
  listPending,
  listError,
  isExplicitDeepLink,
  deepLinkFailed,
  invalidSelectedParam,
  isCumulative,
  explicitTargetInFilteredItems,
  selectedItem,
  trackingAvailabilityState,
  selectedSourceUrl,
  feedbackSummaryLabel,
  rowExecution,
  bulkPending,
  onOpenFeedback,
  trackingProblem,
  trackingMessage,
  trackingDisabledReason,
  trackingActor,
  onActorNameChange,
  customReason,
  onCustomReasonChange,
  reasonChoice,
  onReasonChoiceChange,
  lastReason,
  onReuseLastReason,
  selectedIndex,
  total,
  trackingSectionRef,
  trackingReady,
  onDecideTracking,
  onSkipCurrent,
  onResetFilters,
}: OrderPlanDetailPaneProps) {
  const selectedPk = selectedItem?.order_plan_pk ?? null;
  /**
   * 선택한 행의 상세 응답(`order-plan-detail-response.v4`, spec §6.1).
   *
   * 행마다 **1회**이고 선택이 바뀔 때만 다시 조회한다 — 키가 발주계획 PK 하나이므로
   * 같은 행을 다시 골라도 `staleTime` 안에서는 요청이 나가지 않는다. 목록이 이미 준
   * 값(제목·기관·예산·발주 예정·분야·근거·추적 결정)은 이 응답을 기다리지 않으며,
   * 상세 응답만 싣는 값(총괄기관·조달방식·용역 구분·연관 공고번호)만 응답 뒤에 채운다.
   */
  const detailQuery = useQuery({
    queryKey: ["order-plan-c2", "detail", selectedPk],
    queryFn: ({ signal }) => api.getOrderPlan(selectedPk as number, { signal }),
    enabled: selectedPk !== null,
    staleTime: 15_000,
  });
  /** 지금 선택한 행의 상세만 쓴다. 이전 선택의 응답을 다른 행의 값으로 그리지 않는다. */
  const detail = selectedPk !== null && detailQuery.data?.order_plan_pk === selectedPk
    ? detailQuery.data
    : null;
  const detailState = {
    pending: selectedPk !== null && detail === null && !detailQuery.isError,
    failed: selectedPk !== null && detailQuery.isError,
  };
  /** 총괄기관은 값이 있을 때만 그린다(시안 M5 ①) — 없는 기관을 `미제공`으로 적지 않는다. */
  const supervisingAgency = detail?.supervising_agency_name?.trim() ? detail.supervising_agency_name : null;
  /** 신규·계속 구분(`service_type`). 값이 없거나 아직 받지 못했으면 절 자체를 만들지 않는다. */
  const serviceType = detail?.service_type?.trim() ? detail.service_type : null;
  return (
    <section className="review-split-detail c2l-detail-pane">
      {listPending || listError ? (
        <div className="c2l-detail-empty">
          <Text type="body" color="secondary" as="p">
            {listPending ? "목록을 불러온 뒤 상세 정보를 표시합니다." : "목록을 불러오지 못해 상세를 표시할 수 없습니다."}
          </Text>
        </div>
      ) : isExplicitDeepLink && deepLinkFailed ? (
        <div className="c2l-detail-empty">
          <EmptyState
            compact
            tone="error"
            title={invalidSelectedParam
              ? "발주계획 식별자가 올바르지 않습니다."
              : isCumulative ? "요청한 발주계획을 누적 목록에서 찾을 수 없습니다." : "요청한 발주계획을 이 회차에서 찾을 수 없습니다."}
            description="요청한 대상을 첫 번째 행으로 바꾸지 않았습니다. 회차와 선택한 식별자를 확인하십시오."
          />
        </div>
      ) : isExplicitDeepLink && !explicitTargetInFilteredItems ? (
        <div className="c2l-detail-empty">
          <Text type="body" color="secondary" as="p">선택한 발주계획을 표시할 수 있도록 필터를 정리하는 중…</Text>
        </div>
      ) : selectedItem ? (
        <>
          {/* 시안 §4: 발주기관을 라벨과 함께 강조 블록으로 먼저 읽히고, 사업명은
              그다음이다. 식별자와 추적 상태는 한 줄로 붙인다. */}
          <StickyDecisionHeader className="review-detail-head c2l-detail-head" label="발주계획 상세 헤더">
            {/* 총괄기관은 발주기관 바로 아래에서 작게 읽힌다(시안 M5 ①). 공용 블록의
                부제 슬롯이라 배경·여백을 발주기관과 함께 쓴다. 값이 없으면 줄 자체를
                만들지 않는다 — 없는 기관을 `미제공`으로 적지 않는다. */}
            <AgencyFeature
              className="c2l-agency-feature"
              fallback="미확인"
              labelClassName="c2l-agency-label"
              name={selectedItem.agency_name}
              nameClassName="c2l-agency-name"
              sub={supervisingAgency ? `총괄기관 ${supervisingAgency}` : null}
              subClassName="c2l-agency-supervising"
            />
            <span className={`bo-tag is-${trackingTag(selectedItem).tone} c2l-detail-tag`} data-testid="order-plan-detail-tag">{trackingTag(selectedItem).label}</span>
            <h2 className="c2l-detail-title">{textOrUnknown(selectedItem.title)}</h2>
            <div className="c2l-detail-identity">
              {/* 외부 계획번호 하나만 둔다. 내부 계획 ID는 실무 판단에 쓰이지 않으며
                  주소(`?selected=`)와 운영 화면이 그대로 들고 있다(0921 명세 §3.1).
                  첫 수집일은 목록이 이미 준 값이라 상세 응답을 기다리지 않는다.
                  신규·계속 구분은 상세 전용이므로 값이 온 뒤에만 절이 붙는다. */}
              <Text type="supporting" color="secondary" as="p">
                계획번호 {selectedItem.order_plan_unty_no}
                {` · 첫 수집 ${formatKstDateShort(selectedItem.first_observed_at)}`}
                {serviceType ? ` · ${serviceType}` : ""}
              </Text>
            </div>
          </StickyDecisionHeader>
          <div className="c2l-detail-scroll">
            {/* 상세 조회가 실패하면 목록에서 받은 값은 그대로 두고 **못 불러왔다는 사실**만
                알린다. 실패를 `미제공`으로 낮추지 않으며(경고 ④) 같은 자리에서 다시 시도한다. */}
            {detailState.failed ? (
              <p className="c2l-detail-error" role="alert">
                <span>상세 정보를 불러오지 못했습니다 · 목록에서 받은 값만 보입니다</span>
                <Button
                  label="다시 시도"
                  size="sm"
                  variant="ghost"
                  onClick={() => { void detailQuery.refetch(); }}
                />
              </p>
            ) : null}
            {/* 계약 조건은 참여 판단을 좌우한다(시안 M5 ①): 수의계약인지, 이미 공고가
                났는지, 추적을 시작한 사업기회가 있는지. 예산·발주 예정·사업 분야는
                목록이 이미 준 값이라 상세 응답을 기다리지 않는다. */}
            <dl className="c2l-detail-facts">
              <div><dt>발주계획 예산</dt><dd>{budgetValue(selectedItem.budget_amount)}</dd></div>
              <div><dt>발주 예정</dt><dd>{plannedTiming(selectedItem.planned_order_year, selectedItem.planned_order_month)}</dd></div>
              <div><dt>사업 분야</dt><dd>{textOrUnknown(selectedItem.business_division)}</dd></div>
              {/* 계약방법은 목록 응답(v5)에도 있는 같은 열이므로 즉시 보인다. */}
              <div><dt>계약방법</dt><dd>{detailFactValue(selectedItem.contract_method)}</dd></div>
              <div><dt>조달방식</dt><dd>{detailFactValue(detail?.procurement_method ?? null, detailState)}</dd></div>
              <div>
                <dt>공고 게시</dt>
                <dd>
                  {noticePostedLabel(selectedItem.notice_posted)}
                  {/* 연관 공고번호는 수집 원문 문자열 그대로다 — 서버가 쪼개지 않으므로
                      화면도 쪼개지 않는다(contracts.md). */}
                  {detail?.bid_ntice_no_list ? (
                    <span className="c2l-detail-facts-sub">공고번호 {detail.bid_ntice_no_list}</span>
                  ) : null}
                </dd>
              </div>
              <div>
                <dt>연결된 사업기회</dt>
                <dd>
                  {selectedItem.tracking
                    ? (
                      <Link className="c2l-detail-opportunity" to={`/opportunities/${selectedItem.tracking.opportunity_id}`}>
                        사업 추적에서 보기 →
                      </Link>
                    )
                    /* 소유 사업기회를 확인하지 못한 것과 추적을 고르지 않은 것은 다른
                       상태다(`OrderPlanTracking` 계약 — `null`은 `미선택`이 아니다).
                       머리 badge와 같은 문구를 써서 둘을 뭉개지 않는다. */
                    : trackingStatusLabel(selectedItem)}
                </dd>
              </div>
            </dl>

            {/* 기본 상세는 실제로 있는 근거만 싣는다. 제안요청서 본문·확인할 점은
                지금 API의 필드가 아니므로 만들어 넣지 않는다. */}
            <section className="c2l-evidence" aria-labelledby={`c2l-evidence-${selectedItem.order_plan_pk}`}>
              <div className="c2l-evidence-head">
                <h3 className="c2l-evidence-title" id={`c2l-evidence-${selectedItem.order_plan_pk}`}>{evidenceHeading(selectedItem)}</h3>
                <span className="c2l-row-badges">
                  {stage1BadgeLabel(selectedItem.stage1_status) ? (
                    <Badge variant={stage1BadgeVariant(selectedItem.stage1_status)} label={stage1BadgeLabel(selectedItem.stage1_status) as string} />
                  ) : null}
                  {/* 모델 판단은 정보색(보라) 표식이다. 판단이 없으면 사람이 봐야 하는 사실이라 주의색이다. */}
                  {qwenBadgeVariant(selectedItem) === "error" ? (
                    <Badge variant="error" label={qwenRowLabel(selectedItem)} />
                  ) : (
                    <span className={`bo-tag ${hasNoModelJudgment(selectedItem) ? "is-warning" : "is-info"}`}>{qwenRowLabel(selectedItem)}</span>
                  )}
                </span>
              </div>
              {/* 모델 판정이 없는 건(배치 실패 포함)은 비관련이 아니다. 이유와 할 일을 한 줄로 남긴다. */}
              {hasNoModelJudgment(selectedItem) ? (
                <p className="c2l-detail-warn" role="note">
                  {NO_MODEL_JUDGMENT_LABEL} · {qwenRowLabel(selectedItem)}. 모델 판단이 없으므로 비관련으로 보지 않습니다. 사업명·발주기관을 직접 보고 추적 여부를 정하십시오.
                </p>
              ) : null}
              {/* 없앤 `선별 신호 · 실행 기록` 다이얼로그에서 판단에 쓰는 두 값만 본문으로
                  올렸다(시안 M3 결정 3 승인). 나머지 신호(순위·점수·실행 기록)는 운영
                  화면의 `발주계획 선별` 탭이 진다. */}
              {/* 시안의 채움 블록 하나: 근거 문장 → 근거 위치 → 가까운 회사 역량. */}
              <div className="c2l-evidence-block">
                <div className="c2l-evidence-item">
                  <p className="visually-hidden">모델 판단 근거</p>
                  <p className="c2l-evidence-body">
                    <ReviewValue value={selectedItem.qwen_reason} nullLabel="모델 근거 미제공" />
                  </p>
                </div>
                {/* 출처는 서버가 준 값 하나뿐이다. 원문 인용이나 문서 위치를 만들지
                    않고, 어느 알려진 필드를 읽었는지만 이름으로 적는다. */}
                <dl className="c2l-evidence-source">
                  <dd>{textOrUnknown(selectedItem.title)}</dd>
                  <dt>근거 위치 · 발주계획 사업명</dt>
                </dl>
                <p className="c2l-evidence-item c2l-evidence-capability-line">
                  <span>가까운 회사 역량 · </span>
                  <span className="c2l-evidence-capability">
                    <ReviewValue value={selectedItem.nearest_capability} nullLabel="미제공" />
                  </span>
                </p>
              </div>
              <p className="c2l-evidence-scope">
                <Text type="supporting" color="secondary" as="span">
                  계획 정보 기반 탐색 신호 · 회사 적합성과 참여 자격은 미확인
                </Text>
              </p>
            </section>

            {/* 이 판정을 낸 실행에 문제가 있을 때만 한 줄로 알린다(경고 ③·④). 값 자체는
                운영 화면이 진다 — 여기서는 "이 판정을 그대로 믿어도 되는가"만 말한다. */}
            <ExecutionWarningLine execution={rowExecution} />

            {/* 이 건에 이미 기록된 추적 선택이 있으면 한 줄로 남긴다. 값이 없으면
                줄 자체를 만들지 않는다. */}
            {selectedItem.tracking?.tracking_selected_by ? (
              <p className="c2l-detail-note">
                <Text type="supporting" color="secondary" as="span">
                  최근 추적 선택 · {selectedItem.tracking.tracking_selected_by} · {formatMoment(selectedItem.tracking.tracking_selected_at)} · 사유 <ReviewValue value={selectedItem.tracking.tracking_reason} nullLabel="사유 미제공" />
                </Text>
              </p>
            ) : null}

            {/* 보조 정보는 기본 동선에서 빼되 지우지 않는다. 같은 자리에서 연다. */}
            <nav className="c2l-supplementary" aria-label="공고 원문과 사람 판단 수정">
              {selectedSourceUrl ? (
                <Button
                  label="공고 바로가기"
                  size="md"
                  variant="secondary"
                  href={selectedSourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  tooltip="새 탭에서 발주계획 공고 열기"
                />
              ) : (
                <Text type="supporting" color="secondary" as="span">
                  {selectedItem.source_url ? "공고 URL 확인 불가" : "공고 URL 없음"}
                </Text>
              )}
              <Button
                aria-label="사람 판단 수정 열기"
                label={`사람 판단 수정 · ${feedbackSummaryLabel}`}
                size="md"
                variant="secondary"
                isDisabled={bulkPending}
                onClick={onOpenFeedback}
              />
            </nav>
          </div>
          {/* 분할 화면의 결정 액션은 상세 pane 바닥에 둔다. 여기의 결정은
              **추적 결정 하나**다(ADR-0046 결정 4). 사람 판단 수정은
              별도 대화상자가 자기 저장을 소유한다. */}
          <ReviewDecisionBar
            className="c2l-detail-actions"
            // 비활성 사유는 세 결정이 함께 읽는 한 문장이다. 버튼 옆이 아니라
            // 여기 한 곳에서 그리고, 각 버튼은 같은 id를 `aria-describedby`로 가리킨다.
            hint={(
              <>
                {trackingMessage?.pk === selectedItem.order_plan_pk
                  ? <span className="c2l-decision-message" role="status">{trackingMessage.text}</span>
                  : null}
                <span className="c2l-decision-hint" id="c2l-tracking-decision-reason">
                  {trackingDisabledReason ?? "선택 후 다음 후보로 이동합니다 · 목록에서 ↑↓ 이동, Ctrl+Enter로 추적 시작하기 · 최종 입찰 참여 결정과 별개"}
                </span>
              </>
            )}
            label="발주계획 추적 결정"
            status={(
              <TrackingDecisionFields
                actorName={trackingActor}
                customReason={customReason}
                item={selectedItem}
                lastReason={lastReason}
                onActorNameChange={onActorNameChange}
                onCustomReasonChange={onCustomReasonChange}
                onReasonChoiceChange={onReasonChoiceChange}
                onReuseLastReason={onReuseLastReason}
                position={`${selectedIndex} / ${total.toLocaleString("ko-KR")}건`}
                reasonChoice={reasonChoice}
                sectionRef={trackingSectionRef}
                problem={trackingProblem}
                isDisabled={bulkPending}
              />
            )}
            actions={(
              <>
                {/* 세 결정이 같은 사유로 함께 막힌다. 문장은 hint 자리에 한 번만 있고 버튼은 모두
                    같은 id를 가리킨다. 버튼의 순서·이름은 추적 결정 입력 한 벌(C-7)이 정한다. */}
                <TrackingDecisionActions
                  statuses={["계속 추적", "보류", "종료"]}
                  current={selectedItem.tracking?.tracking_status ?? null}
                  disabledReasonId="c2l-tracking-decision-reason"
                  isDisabled={bulkPending || !trackingReady}
                  onDecide={onDecideTracking}
                />
                {/* 아무것도 저장하지 않으므로 계약이 없어도 비활성이 아니다. */}
                <ReviewDecisionAction
                  label="넘기기"
                  variant="ghost"
                  isDisabled={bulkPending}
                  onClick={onSkipCurrent}
                />
              </>
            )}
          />
        </>
      ) : (
        <div className="c2l-detail-empty">
          <EmptyState
            compact
            title="조건에 맞는 계획이 없습니다"
            description="검색어나 필터를 바꿔보세요. 선택한 회차의 원본은 그대로 남아 있습니다."
            action={{ label: "필터 초기화", onClick: onResetFilters }}
          />
        </div>
      )}
    </section>
  );
}
