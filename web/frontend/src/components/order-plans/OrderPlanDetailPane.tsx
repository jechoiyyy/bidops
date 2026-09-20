import type { Ref } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import {
  ReviewDecisionAction,
  ReviewDecisionBar,
  ReviewState,
  ReviewValue,
  StickyDecisionHeader,
} from "../common/ReviewPrimitives";
import { describeApiError } from "../../lib/apiErrors";
import type { OpportunityTrackingStatus, OrderPlanListItem } from "../../lib/types";
import {
  OTHER_REASON,
  TRACKING_REASONS,
  budgetValue,
  formatMoment,
  plannedTiming,
  qwenBadgeVariant,
  qwenRowLabel,
  stage1BadgeVariant,
  stage1RowLabel,
  textOrUnknown,
  trackingAvailability,
} from "./orderPlanFormat";
import type { TrackingAvailability } from "./orderPlanFormat";

const TRACKING_REASON_OPTIONS = [
  ...TRACKING_REASONS.map((value) => ({ label: value, value })),
  { label: "기타 · 직접 입력", value: OTHER_REASON },
];

function trackingStatusLabel(item: OrderPlanListItem | null): string {
  switch (trackingAvailability(item)) {
    case "contract_missing":
      return "계약 미구현";
    case "opportunity_missing":
      return "사업기회 미연결";
    default:
      return item?.tracking?.tracking_status === "미선택"
        ? "추적 결정 없음"
        : (item?.tracking?.tracking_status ?? "추적 결정 없음");
  }
}

/**
 * 상세 pane 바닥의 추적 결정 입력.
 *
 * 시안(focus-v2)의 결정 블록은 늘 보이는 한 덩어리다: 머리줄(추적 선택 · 현재 상태 ·
 * 위치), 사유 드롭다운과 담당자 감사 표식 한 줄, `기타`일 때만 열리는 자유 입력.
 * 결정 버튼과 안내 한 줄은 `ReviewDecisionBar`의 action·hint 자리에 있다.
 *
 * 상태의 뜻을 길게 설명하는 문장은 여기 두지 않는다. 현재 상태는 badge가, 저장할 수
 * 없는 이유는 결정 줄 아래 한 문장이, 나머지 구분 규칙은 `실행 상태` 대화상자가 진다.
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
  isDisabled?: boolean;
}) {
  const availability = trackingAvailability(item);
  /** 지금 계약에 실릴 사유. 이 값이 이미 있으면 다시 쓰기 단추를 그리지 않는다. */
  const currentReason = reasonChoice === OTHER_REASON ? customReason.trim() : reasonChoice;
  return (
    <section className="c2l-tracking" aria-labelledby={`c2l-tracking-${item.order_plan_pk}`} ref={sectionRef}>
      <header className="c2l-tracking-head">
        <Text type="label" color="primary" as="p" id={`c2l-tracking-${item.order_plan_pk}`}>추적 선택</Text>
        <Badge
          variant={availability === "available" ? "neutral" : "warning"}
          label={trackingStatusLabel(item)}
        />
        <Text type="supporting" color="secondary" as="p" className="c2l-tracking-position">{position}</Text>
      </header>
      <div className="c2l-tracking-fields">
        <div className="c2l-reason-field">
          <Selector
            label="선택 사유"
            onChange={(value) => onReasonChoiceChange(value ?? "")}
            options={TRACKING_REASON_OPTIONS}
            placeholder="사유를 선택하세요"
            size="sm"
            value={reasonChoice || undefined}
            isDisabled={isDisabled}
          />
          {/* 드롭다운을 미리 채우지 않는다(PRD §3.3). 직전 사유는 **사람이 누를 때에만**
              들어가는 후보이고, 무엇이 들어갈지 단추 이름이 그대로 말한다. */}
          {lastReason && !currentReason ? (
            /* 긴 사유는 CSS가 말줄임하므로 전문은 `title`이 진다. Astryx `Button`은
               `title`을 받지 않아(BaseProps가 뺀다) 감싸는 span이 그 자리다. */
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
        </div>
        <TextInput
          label="담당자 이름 · 감사 표식"
          size="sm"
          value={actorName}
          onChange={onActorNameChange}
          placeholder="이름 입력"
          isDisabled={isDisabled}
        />
      </div>
      {reasonChoice === OTHER_REASON ? (
        <TextInput
          label="선택 사유 직접 입력"
          size="sm"
          value={customReason}
          onChange={onCustomReasonChange}
          placeholder="추적·보류·종료를 선택한 이유를 적어주세요"
          isDisabled={isDisabled}
        />
      ) : null}
    </section>
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
  bulkPending: boolean;
  onOpenFeedback: () => void;
  onOpenSignals: () => void;
  trackingIsError: boolean;
  trackingError: unknown;
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
  bulkPending,
  onOpenFeedback,
  onOpenSignals,
  trackingIsError,
  trackingError,
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
  return (
    <section className="c2l-detail-pane">
      {listPending || listError ? (
        <div className="c2l-detail-empty">
          <Text type="body" color="secondary" as="p">
            {listPending ? "목록을 불러온 뒤 상세 정보를 표시합니다." : "목록을 불러오지 못해 상세를 표시할 수 없습니다."}
          </Text>
        </div>
      ) : isExplicitDeepLink && deepLinkFailed ? (
        <div className="c2l-detail-empty">
          <ReviewState
            kind="failure"
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
          <StickyDecisionHeader className="c2l-detail-head" label="발주계획 상세 헤더">
            <div className="c2l-agency-feature">
              <Text type="supporting" color="secondary" as="p" className="c2l-agency-label">발주기관</Text>
              <Text type="body" color="primary" weight="semibold" as="p" className="c2l-agency-name">{textOrUnknown(selectedItem.agency_name)}</Text>
            </div>
            <Heading level={4}>{textOrUnknown(selectedItem.title)}</Heading>
            <div className="c2l-detail-identity">
              <Text type="supporting" color="secondary" as="p">발주계획 {selectedItem.order_plan_unty_no} · 계획 ID {selectedItem.order_plan_pk}</Text>
              <Badge
                variant={trackingAvailabilityState === "available" ? "neutral" : "warning"}
                label={trackingStatusLabel(selectedItem)}
              />
            </div>
          </StickyDecisionHeader>
          <div className="c2l-detail-scroll">
            <dl className="c2l-detail-facts">
              <div><dt>발주계획 예산</dt><dd>{budgetValue(selectedItem.budget_amount)}</dd></div>
              <div><dt>발주 예정</dt><dd>{plannedTiming(selectedItem.planned_order_year, selectedItem.planned_order_month)}</dd></div>
              <div><dt>사업 분야</dt><dd>{textOrUnknown(selectedItem.business_division)}</dd></div>
            </dl>

            {/* 기본 상세는 실제로 있는 근거만 싣는다. 제안요청서 본문·확인할 점은
                지금 API의 필드가 아니므로 만들어 넣지 않는다. */}
            <section className="c2l-evidence" aria-labelledby={`c2l-evidence-${selectedItem.order_plan_pk}`}>
              <div className="c2l-evidence-head">
                <Heading level={5} id={`c2l-evidence-${selectedItem.order_plan_pk}`}>관련 근거</Heading>
                <span className="c2l-row-badges">
                  <Badge variant={stage1BadgeVariant(selectedItem.stage1_status)} label={stage1RowLabel(selectedItem.stage1_status)} />
                  <Badge variant={qwenBadgeVariant(selectedItem)} label={qwenRowLabel(selectedItem)} />
                </span>
              </div>
              <p className="c2l-evidence-body">
                <ReviewValue value={selectedItem.qwen_reason} nullLabel="null (모델 근거 미제공)" />
              </p>
              {/* 출처는 서버가 준 값 하나뿐이다. 원문 인용이나 문서 위치를 만들지
                  않고, 어느 알려진 필드를 읽었는지만 이름으로 적는다. */}
              <dl className="c2l-evidence-source">
                <dd>{textOrUnknown(selectedItem.title)}</dd>
                <dt>근거 위치 · 발주계획 사업명</dt>
              </dl>
              <p className="c2l-evidence-scope">
                <Text type="supporting" color="secondary" as="span">
                  계획 정보 기반 탐색 신호 · 회사 적합성과 참여 자격은 미확인
                </Text>
              </p>
            </section>

            {/* 이 건에 이미 기록된 추적 선택이 있으면 한 줄로 남긴다. 값이 없으면
                줄 자체를 만들지 않는다. */}
            {selectedItem.tracking?.tracking_selected_by ? (
              <p className="c2l-detail-note">
                <Text type="supporting" color="secondary" as="span">
                  최근 추적 선택 · {selectedItem.tracking.tracking_selected_by} · {formatMoment(selectedItem.tracking.tracking_selected_at)} · 사유 <ReviewValue value={selectedItem.tracking.tracking_reason} nullLabel="null (사유 없음)" />
                </Text>
              </p>
            ) : null}

            {/* 보조 정보는 기본 동선에서 빼되 지우지 않는다. 같은 자리에서 연다. */}
            <nav className="c2l-supplementary" aria-label="추가 검토 정보 및 공고 원문">
              {selectedSourceUrl ? (
                <Button
                  label="공고 바로가기"
                  size="sm"
                  variant="ghost"
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
                size="sm"
                variant="ghost"
                isDisabled={bulkPending}
                onClick={onOpenFeedback}
              />
              <Button
                aria-label="선별 신호와 실행 기록 열기"
                label="선별 신호 · 실행 기록"
                size="sm"
                variant="ghost"
                onClick={onOpenSignals}
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
                {trackingIsError ? (
                  <span className="c2l-decision-message" role="alert">
                    {describeApiError(trackingError, "추적 결정을 저장하지 못했습니다.").title} 이 발주계획의 추적 상태는 바뀌지 않았습니다.
                  </span>
                ) : null}
                {trackingMessage?.pk === selectedItem.order_plan_pk
                  ? <span className="c2l-decision-message" role="status">{trackingMessage.text}</span>
                  : null}
                <span className="c2l-decision-hint" id="c2l-tracking-decision-reason">
                  {trackingDisabledReason ?? "선택 후 다음 후보로 이동합니다 · 목록에서 ↑↓ 이동, Ctrl+Enter로 추적 시작 · 최종 입찰 참여 결정과 별개"}
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
                isDisabled={bulkPending}
              />
            )}
            actions={(
              <>
                {/* 세 결정이 같은 사유로 함께 막힌다. 첫 액션이 그 문구를
                    한 번만 그리고 나머지는 같은 id를 가리켜, 화면에 같은
                    문장이 세 번 쌓이지 않으면서 각 버튼이 사유를 읽는다. */}
                <ReviewDecisionAction
                  disabledReasonId="c2l-tracking-decision-reason"
                  isDisabled={bulkPending || !trackingReady}
                  label="추적 시작"
                  variant="primary"
                  onClick={() => onDecideTracking("계속 추적")}
                />
                <ReviewDecisionAction
                  disabledReasonId="c2l-tracking-decision-reason"
                  isDisabled={bulkPending || !trackingReady}
                  label="보류"
                  variant="secondary"
                  onClick={() => onDecideTracking("보류")}
                />
                <ReviewDecisionAction
                  disabledReasonId="c2l-tracking-decision-reason"
                  isDisabled={bulkPending || !trackingReady}
                  label="추적 종료"
                  variant="secondary"
                  onClick={() => onDecideTracking("종료")}
                />
                {/* 아무것도 저장하지 않으므로 계약이 없어도 비활성이 아니다. */}
                <ReviewDecisionAction
                  label="이번 건 넘기기"
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
          <ReviewState
            kind="empty"
            title="조건에 맞는 계획이 없습니다"
            description="검색어나 필터를 바꿔보세요. 선택한 회차의 원본은 그대로 남아 있습니다."
            action={<Button label="필터 초기화" size="sm" onClick={onResetFilters} />}
          />
        </div>
      )}
    </section>
  );
}
