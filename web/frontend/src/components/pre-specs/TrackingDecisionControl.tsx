import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Badge } from "../common/Badge";
import { Button } from "@astryxdesign/core/Button";
import { ActorField, requestActorInput, useRememberedActorName } from "../common/ActorField";
import { ConfirmDecisionDialog, trackingEndConfirmContent } from "../common/ConfirmDecisionDialog";
import { useUnsavedGuard } from "../common/useUnsavedGuard";
import { DisabledReason } from "../common/DisabledReason";
import { EmptyState } from "../common/EmptyState";
import { MutationFeedback } from "../common/MutationFeedback";
import { ReviewDecisionAction } from "../common/ReviewPrimitives";
import {
  TRACKING_DECISION_ORDER,
  TRACKING_SAVE_FAILED,
  TrackingDecisionActions,
  TrackingDecisionInputs,
  TrackingSaveError,
  trackingActionLabel,
  trackingInputBlockedReason,
  trackingReasonValue,
  trackingSavedMessage,
  type TrackingDecisionStatus,
} from "../common/TrackingDecisionForm";
import { api } from "../../lib/api";
import { describeApiError, describeCompanyApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import {
  applyCompanyTrackingSaved,
  COMPANY_TRACKING_DECISIONS,
  companyApi,
  companyKeys,
  type CompanyTrackingDTO,
  type CompanyTrackingStatus,
  type CompanyTrackingUpdateRequest,
  type Uuid,
} from "../../lib/companyApi";
import { generateRequestId } from "../../lib/requestId";
import { originOf, trackingVariant } from "../../lib/opportunity";
import { formatDateTime, present } from "../../lib/format";
import type {
  OpportunityDetailResponse,
  OpportunityTrackingStatus,
  PreSpecListItem,
  PreSpecListResponse,
} from "../../lib/types";

// 사전규격 상세(PreSpecDetailPage)와 사전규격 목록(PreSpecsPage)이 심층 추적
// 승인 업무 규칙(선택 가능한 상태값, 사유 필수, 비활성 사유)을 각자 다시
// 구현하지 않도록 이 컴포넌트로 추출한다 (docs/design/PLAN.md 3단계,
// CLAUDE.md "같은 업무 규칙을 복제하지 않는다"). ADR-0041 결정 5에 따라
// 이 컨트롤은 심층 검토 추적 선택 하나만 다루고, 적합성 등급·참여 준비
// 상태·최종 Go/No-Go를 대신하지 않는다.

/**
 * 사전규격 화면이 고를 수 있는 추적 상태는 **`계속 추적` 하나뿐이다.**
 *
 * ADR-0046 결정 6: 추적 상태를 묻는 자리를 하나로 제한한다. `보류`와 `추적 종료`는
 * 사업 추적에서만 사람이 선택하고, 발주계획에서 승계된 건은 여기서 다시 묻지 않으며,
 * 심층 검토가 정상 완료돼도 다시 묻지 않는다. 이 배열을 늘리면 그 결정이 깨진다.
 *
 * **예외(2026-11-21 사용자 결정, 결정 6 개정은 문서 작업이 기록한다):** 사전규격 상세의 `분석 완료` 화면
 * (엔진 분석 결과가 있는 건, 지금은 mock 빌드 전용) 하단 띠만 `TRACKING_DECISION_STATUSES_AFTER_ANALYSIS`
 * 세 가지를 고른다. 그 띠가 `barStatuses`로 받는다. 이 배열(분석 전 화면·목록)은 그대로 하나다.
 */
export const TRACKING_DECISION_STATUSES: OpportunityTrackingStatus[] = ["계속 추적"];

/** 분석 완료 화면 하단 띠가 고르는 세 상태(위 예외). `종료`는 기존 종료 확인 단계를 그대로 거친다. */
export const TRACKING_DECISION_STATUSES_AFTER_ANALYSIS: readonly TrackingDecisionStatus[] = ["계속 추적", "보류", "종료"];

/**
 * 회사 데모 경로(`CompanyTrackingDecision`)의 사유·담당자 필수 규칙. 사전규격 경로는 추적 결정
 * 입력 한 벌(`TrackingDecisionForm`, C-7)의 `trackingInputBlockedReason`을 쓴다. 사유는 공백을 뺀 뒤 1자 이상이어야 하며(서버도 trim 뒤 1~2000자), 담당자 이름은
 * 감사 표식일 뿐 인증이 아니다.
 */
function requiredDecisionInputReason(reason: string, actorName: string): string | null {
  if (!reason.trim()) return "추적 결정을 저장하려면 사유를 입력해 주세요.";
  if (!actorName.trim()) return "추적 결정을 저장하려면 담당자 이름을 입력해 주세요.";
  return null;
}

/** 발주계획에서 추적 상태를 물려받은 건인지. 물려받았으면 이 화면은 다시 묻지 않는다. */
export function isInheritedTracking(item: PreSpecListItem): boolean {
  return originOf(item.origin ?? "신규") === "추적"
    && item.tracking_status !== null
    && item.tracking_status !== "미선택";
}

/** 캐시에 반영된 사전규격 projection 하나의 추적 필드를 저장 결과로 갱신한다.
 * `pre-spec-detail`·`pre-specs` 두 화면의 쿼리 캐시가 같은
 * `PreSpecListResponse` 모양이므로 호출자가 각자의 queryKey에 적용한다. */
export function updateTrackingProjection(
  response: PreSpecListResponse | undefined,
  noticeId: number,
  saved: OpportunityDetailResponse,
): PreSpecListResponse | undefined {
  if (!response) return response;
  return {
    ...response,
    items: response.items.map((item) => item.notice_pk === noticeId
      ? { ...item, opportunity_id: saved.id, tracking_status: saved.tracking_status }
      : item),
  };
}

export function PreSpecDocumentSummary({ item }: { item: PreSpecListItem }) {
  const document = item.document;
  return (
    <section className="pre-spec-detail-document-summary" aria-labelledby="pre-spec-detail-document-title">
      <div className="pre-spec-detail-section-heading">
        <h4 id="pre-spec-detail-document-title">첨부 원문 취득 집계</h4>
        <strong>{document.attachments}건</strong>
      </div>
      <dl className="pre-spec-detail-document-facts">
        <div><dt>완료</dt><dd>{document["완료"]}건</dd></div>
        <div><dt>대기</dt><dd>{document["대기"]}건</dd></div>
        <div><dt>진행</dt><dd>{document["진행"]}건</dd></div>
        <div><dt>차단</dt><dd>{document["차단"]}건</dd></div>
        <div><dt>실패</dt><dd>{document["실패"]}건</dd></div>
      </dl>
      <p>첨부 취득 상태는 같은 공고의 누적 사전규격 요약 정보에서 확인했어요.</p>
    </section>
  );
}

export interface PreSpecTrackingDecisionControlProps {
  /** 기존 사전규격 경로. 회사 adapter가 없으면 이 형태다. */
  adapter?: undefined;
  item: PreSpecListItem | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  /** 저장에 성공하면 호출자가 자신의 query cache를 갱신한다. 화면마다
   * queryKey 모양이 다르므로 캐시 반영은 이 컴포넌트가 대신하지 않는다. */
  onSaved: (saved: OpportunityDetailResponse) => void;
  /** 상세 화면과 목록 화면에서 heading level이 다를 수 있어 호출자가 정한다. */
  headingLevel?: "h3" | "h4";
  /** 첨부 취득 집계(PreSpecDocumentSummary)와 긴 설명을 생략하는 밀도 변형.
   * 호출자가 그 집계를 본문에서 따로 렌더링한다고 가정한다. 선택 가능한
   * 상태값·사유 필수·비활성 사유 같은 업무 규칙은 그대로 이 컴포넌트가
   * 소유한다(CLAUDE.md "같은 업무 규칙을 복제하지 않는다"). */
  compact?: boolean;
  /** Approved record presentation; the shared mutation and input guard remain here.
   * `inline`은 목록 우측 정보 영역 바닥의 한 줄 배치다(docs/0915_ui-redesign/spec.md §3.3).
   * `record`와 **같은 업무 규칙·필드·문구**를 쓰고 CSS 배치만 다르다 — 선택 가능한
   * 상태값·사유 필수·담당자 기억·비활성 사유를 다시 구현하지 않는다.
   *
   * `bar`는 사전규격 상세의 패널 아래 고정 띠다(2026-11-21 시안 `docs/1121_prespec-detail/`). 같은 상태값·사유 필수·
   * 저장·오류·이탈 보호를 쓰고 배치만 한 줄이다. 담당자 입력 칸은 없고 사이드바 담당자 칸의 값(`bidops.actorName`)을
   * 쓴다 — 비어 있으면 저장을 막고 그 칸을 여는 단추를 둔다(발주계획 결정 영역과 같은 규칙). */
  presentation?: "default" | "record" | "inline" | "bar";
  noticeNumber?: string | null;
  /** 헤더가 같은 배지를 이미 그릴 때 중복을 피하기 위한 배치 옵션. 상태 계산은 이 컴포넌트가 계속 소유한다. */
  showRecordHeading?: boolean;
  /** 입력 한 줄 배치에서 의도 상자를 생략하는 배치 옵션. 저장되는 결정은 여전히 `계속 추적` 하나다. */
  showIntent?: boolean;
  /** 주어지면 저장 폼에 이 id가 붙어, 상세 화면의 결정 패널이 `form` 속성으로
   * 같은 submit을 쏠 수 있다. 폼 자체는 본문에 남는다 — 되돌릴 수 없는 입력
   * form을 헤더에 올리지 않는다(PLAN 단계 F 완료 게이트). */
  formId?: string;
  /** 헤더 액션의 비활성 상태를 이 폼의 전제조건과 같게 유지한다. 사유 문구도
   * 함께 넘겨 두 자리가 다른 말을 하지 않게 한다. */
  onDecisionStateChange?: (state: { ready: boolean; disabledReason: string | null; hasForm: boolean; saveLabel: string }) => void;
  /**
   * 자주 쓰는 선택 사유 예시. 주면 빈 드롭다운에서 사유를 고르고, `기타`를
   * 고른 경우에만 직접 입력한다. 주지 않으면 기존 자유 입력을 유지한다.
   * 어느 경우에도 공백만 있는 사유는 저장할 수 없다.
   */
  reasonPresets?: readonly string[];
  /**
   * 사유·담당자에 저장되지 않은 입력이 있는지 알린다.
   *
   * route 이동은 이 컴포넌트가 직접 막지만(아래 `useUnsavedGuard`), **목록 화면에서
   * 다른 행을 고르는 것**은 route 이동이 아니라 목록이 소유한 선택 변경이라 여기서
   * 막을 수 없다. 그 확인은 목록 화면이 이 콜백을 받아 걸어야 한다.
   */
  onDirtyChange?: (dirty: boolean) => void;
  /**
   * `bar` 배치에서 고를 수 있는 상태. 주지 않으면 `TRACKING_DECISION_STATUSES`(계속 추적 하나)다. 둘 이상이면
   * 띠가 이미 기록된 건에서도 상태를 바꾸는 입력을 그린다(분석 완료 화면 예외, 위 주석).
   */
  barStatuses?: readonly TrackingDecisionStatus[];
}

/**
 * 사전규격 추적 결정 컨트롤.
 *
 * - adapter 없음: 기존 사전규격 화면. 고를 수 있는 값은 `계속 추적` 하나다(ADR-0046 결정 6).
 * - `adapter`(회사 경로): 가상회사 데모의 회사별 추적. 계속 추적·보류·종료 세 상태를 저장한다
 *   (계약 §2, 2026-09-17 결정의 데모 회사 경로 한정 예외). 기존 화면의 단일 선택은 바꾸지 않는다.
 *
 * 두 경로는 사유 필수·담당자 필수·종료 확인·미저장 이탈 확인 규칙을 같은 자리에서 쓴다.
 */
/** 하단 결정 띠의 경계 문장. 추적 결정이 무엇을 정하지 않는지 띠에 한 번만 적는다(2026-11-21 시안). */
export const TRACKING_BAR_BOUNDARY = "보류·종료는 사업 추적에서, 입찰 참여는 최종 Go/No-Go에서 정해요.";
/** 세 상태를 고르는 띠(분석 완료 화면)의 경계 문장. 보류·종료를 여기서 고르므로 입찰 참여만 남는다. */
export const TRACKING_BAR_BOUNDARY_AFTER_ANALYSIS = "입찰 참여는 최종 Go/No-Go에서 정해요.";

export function TrackingDecisionControl(props: TrackingDecisionControlProps) {
  if (props.adapter) return <CompanyTrackingDecision adapter={props.adapter} headingLevel={props.headingLevel} />;
  return <PreSpecTrackingDecisionControl {...props} />;
}

function PreSpecTrackingDecisionControl({
  item,
  isPending,
  isError,
  onRetry,
  onSaved,
  headingLevel = "h3",
  compact = false,
  formId,
  onDecisionStateChange,
  onDirtyChange,
  reasonPresets,
  presentation = "default",
  noticeNumber,
  showRecordHeading = true,
  showIntent = true,
  barStatuses,
}: PreSpecTrackingDecisionControlProps) {
  const Heading = headingLevel;
  const opportunityId = item?.opportunity_id ?? null;
  const inherited = item !== undefined && isInheritedTracking(item);
  const bar = presentation === "bar";
  // 서버에 이미 추적 결정이 있는가. 하단 띠는 그 결정의 사유·담당자·시각을 사업기회에서 읽어 함께 보인다.
  const serverRecorded = opportunityId !== null && item?.tracking_status != null && item.tracking_status !== "미선택";
  const opportunityQuery = useQuery({
    queryKey: ["opportunity", opportunityId],
    queryFn: () => api.getOpportunity(opportunityId as number),
    enabled: (inherited || (bar && serverRecorded)) && opportunityId !== null && !isPending && !isError,
    retry: false,
    staleTime: 30_000,
  });
  const inheritedContext = !inherited ? null : opportunityQuery.isPending ? (
    <p role="status">승계 사유를 불러오는 중이에요.</p>
  ) : opportunityQuery.isError || opportunityQuery.data?.id !== opportunityId ? (
    <p role="status">승계 사유 확인 불가</p>
  ) : (
    <p className="pre-spec-inherited-context">
      사유 {present(opportunityQuery.data.tracking_reason, "미확인")}
      {" · "}{present(opportunityQuery.data.tracking_selected_by, "담당자 미확인")}
      {" · "}<time dateTime={opportunityQuery.data.tracking_selected_at ?? undefined}>
        {formatDateTime(opportunityQuery.data.tracking_selected_at)}
      </time>
    </p>
  );
  // spec §3.3: inline은 record 변형의 배치 변형이다. 아래의 모든 업무 규칙 분기는
  // `record`를 그대로 읽으므로 두 변형이 같은 규칙을 공유한다.
  const inline = presentation === "inline";
  const record = presentation === "record" || inline || bar;
  const inlineClass = inline ? " is-inline" : "";
  const [savedDecision, setSavedDecision] = useState<{ reason: string; actor: string } | null>(null);
  // 입력은 추적 결정 입력 한 벌(C-7)과 같다 — 드롭다운 선택 키와 `기타` 직접 입력을 나눠 두고,
  // 저장 사유는 `trackingReasonValue`가 고른다. `기타` 키는 API에 보내지 않는다.
  const [choice, setChoice] = useState("");
  // 분석 완료 화면 띠에서 사람이 고른 상태. 미리 골라 두지 않는다.
  const multiStatus = presentation === "bar" && barStatuses !== undefined && barStatuses.length > 1;
  const [picked, setPicked] = useState<TrackingDecisionStatus | null>(null);
  const [custom, setCustom] = useState("");
  const [actorName, setActorName] = useState("");
  // 하단 띠는 담당자 입력 칸을 두지 않고 사이드바 담당자 칸 하나의 값을 쓴다(ADR-0076 결정 2·10).
  const rememberedActor = useRememberedActorName();
  const effectiveActor = bar ? rememberedActor : actorName;
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);
  // `종료`만 되돌릴 수 없다. 이 화면은 `계속 추적`만 저장하므로(ADR-0046 결정 6) 확인 단계가 열릴
  // 일은 없지만, 같은 규칙을 다른 경로와 함께 둔다. 요약은 열 때의 값을 얼려 둔다.
  const [endConfirm, setEndConfirm] = useState<ReturnType<typeof trackingEndConfirmContent> | null>(null);
  const reasonValue = trackingReasonValue(choice, custom);

  // 사유는 저장 전까지 이 컴포넌트에만 있다. 화면을 떠나면 사라지므로 여기서 직접
  // route 이동을 막는다. 부르는 화면(PreSpecsPage·PreSpecDetailPage)이 같은 규칙을
  // 다시 구현하지 않게 하려는 것이며, 목록의 행 전환은 목록이 `onDirtyChange`로
  // 받아 자기 자리에서 확인해야 한다.
  //
  // dirty는 사유(예시 선택 또는 직접 입력)만 본다. 담당자 이름만 채우고 사유가
  // 비어 있으면 저장할 수 없는 입력이라 잃을 것이 없으므로, 그 상태에서 다른 공고로
  // 옮기거나 상세를 떠나도 확인 창을 띄우지 않는다. 사유가 있으면 담당자 이름도
  // 함께 잃으므로 guard summary는 계속 둘 다 보여 준다.
  //
  // 범위가 `pathname`인 이유: 두 화면 모두 선택·필터를 검색 인자로 옮기므로
  // `any`로 두면 사유를 적는 중에 목록 조작마다 이탈 확인이 뜬다.
  const dirty = choice !== "" || custom.trim().length > 0 || picked !== null;
  const guard = useUnsavedGuard(dirty, {
    blockSpaNavigation: true,
    scope: "pathname",
    title: "추적 결정을 저장하지 않고 떠나요",
    message: "저장하지 않은 추적 결정 사유와 담당자 이름이 있어요. 지금 이동하면 사라지며 저장된 추적 상태는 바뀌지 않아요.",
    summary: [
      ...(multiStatus ? [{ label: "추적 상태", value: picked ?? "값 없음" }] : []),
      { label: "사유", value: reasonValue || "값 없음" },
      { label: "담당자", value: effectiveActor.trim() || "값 없음" },
    ],
  });

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  const mutation = useMutation({
    mutationFn: (status: TrackingDecisionStatus) => api.updateOpportunityTrackingStatus(
      item?.opportunity_id as number,
      { tracking_status: status, reason: reasonValue },
      effectiveActor,
    ),
    onSuccess: (saved) => {
      if (!item) return;
      // 저장이 끝났으므로 잃을 입력이 없다. 부르는 화면이 저장 뒤 곧바로 이동할 수 있는데,
      // 그 시점의 dirty 계산은 아직 이전 렌더 값이라 먼저 푼다.
      guard.release();
      if (record) setSavedDecision({ reason: saved.tracking_reason ?? "기록된 사유 미확인", actor: saved.tracking_selected_by ?? "담당자 미확인" });
      setChoice("");
      setCustom("");
      setPicked(null);
      setActorName("");
      setProblem(null);
      // 추적 결정은 추적만 정한다(2026-11-19). 분석 실행 승인으로 이어지지 않는다.
      onSaved(saved);
    },
    onError: (caught: unknown) => {
      // 서버 응답 본문에는 provider·검증 상세가 실릴 수 있다. 화면에 내는 것은
      // `describeApiError`가 status와 안전한 오류 코드로 옮긴 문구뿐이다.
      setProblem(describeApiError(caught, TRACKING_SAVE_FAILED));
    },
  });

  // 전제조건은 조기 반환보다 앞에서 계산한다(hook 순서를 조건부 반환이 흔들지 않게).
  const hasOpportunity = item?.opportunity_id != null;
  const currentStatus = item?.tracking_status ?? null;
  const currentStatusLabel = currentStatus ?? "미확인";
  const currentStatusVariant = currentStatus === null ? "neutral" : trackingVariant(currentStatus);
  const recorded = record && !multiStatus && hasOpportunity && ((currentStatus !== null && currentStatus !== "미선택") || savedDecision !== null);
  const hasForm = Boolean(item) && !isPending && !isError && !(item && isInheritedTracking(item)) && !recorded;
  const disabledReason = !hasOpportunity && !mutation.isPending
    ? "아직 사업기회에 연결되지 않아 추적 결정을 기록할 수 없어요."
    : multiStatus && picked === null && !mutation.isPending
      ? "추적 상태(계속 추적·보류·종료)를 골라 주세요."
      : trackingInputBlockedReason({ choice, custom, actorName: effectiveActor, pending: mutation.isPending });
  const ready = hasOpportunity && disabledReason === null;
  const saveLabel = trackingActionLabel(TRACKING_DECISION_STATUSES[0] as TrackingDecisionStatus, currentStatus);

  useEffect(() => {
    onDecisionStateChange?.({ ready, disabledReason, hasForm, saveLabel });
  }, [disabledReason, hasForm, onDecisionStateChange, ready, saveLabel]);

  if (bar) {
    return (
      <TrackingDecisionBarLayout
        state={isPending ? { kind: "loading" } : isError || !item ? { kind: "error", onRetry } : !hasOpportunity ? {
          kind: "unlinked",
          disabledReason: disabledReason ?? "아직 사업기회에 연결되지 않아 추적 결정을 기록할 수 없어요.",
          currentStatus,
        } : recorded ? {
          kind: "recorded",
          headline: savedDecision
            ? trackingSavedMessage(currentStatus === null || currentStatus === "미선택" ? "계속 추적" : currentStatus)
            : inherited ? "발주계획에서 추적 결정을 이어받았어요" : "추적 결정이 기록된 사업이에요",
          statusLabel: `현재 추적 상태 ${currentStatusLabel}${inherited ? " · 발주계획에서 승계" : ""}`,
          context: opportunityQuery.isSuccess && opportunityQuery.data?.id === opportunityId ? (
            <>
              사유 {present(opportunityQuery.data.tracking_reason, "미확인")}
              {" · "}{present(opportunityQuery.data.tracking_selected_by, "담당자 미확인")}
              {" · "}<time dateTime={opportunityQuery.data.tracking_selected_at ?? undefined}>
                {formatDateTime(opportunityQuery.data.tracking_selected_at)}
              </time>
            </>
          ) : savedDecision ? (
            <>사유 {savedDecision.reason}{" · "}{savedDecision.actor}</>
          ) : opportunityQuery.isError || opportunityQuery.isSuccess ? "기록 사유 확인 불가" : "기록 사유를 불러오는 중이에요.",
          opportunityId: item.opportunity_id as number,
        } : {
          kind: "input",
          currentStatusLabel,
          disabledReason,
          actor: effectiveActor.trim(),
          savedMessage: multiStatus && savedDecision ? trackingSavedMessage(currentStatus ?? "계속 추적") : null,
          // 세 상태를 고르는 띠는 "상태를 골라 주세요" 안내를 화면 글줄로 두지 않는다(띠 높이 73px 유지). 세 단추가 그 안내이고
          // 이유 문장은 저장 단추의 aria-describedby 대상으로 남는다(낭독기용).
          reasonHidden: multiStatus && picked === null && !mutation.isPending && hasOpportunity,
          choices: multiStatus ? (
            <div className="ps-decision-bar-choices" role="group" aria-label="추적 결정">
              {TRACKING_DECISION_ORDER.filter((status) => barStatuses?.includes(status)).map((status) => (
                <button
                  key={status}
                  type="button"
                  aria-pressed={picked === status}
                  disabled={mutation.isPending}
                  onClick={() => setPicked(picked === status ? null : status)}
                >
                  {status}
                </button>
              ))}
            </div>
          ) : null,
        }}
        inputs={(
          <TrackingDecisionInputs
            presets={reasonPresets ?? []}
            choice={choice}
            onChoiceChange={setChoice}
            custom={custom}
            onCustomChange={setCustom}
            actorName={effectiveActor}
            onActorNameChange={() => undefined}
            isDisabled={mutation.isPending}
            size="md"
            isLabelHidden
            selectorPlacement="above"
            reasonClassName="ps-decision-bar-reason-field"
            // 담당자 칸은 띠에 두지 않는다(사이드바 담당자 칸 하나). `null`은 기본 입력 칸으로 떨어지므로 `false`다.
            actorSlot={false}
          />
        )}
        actions={multiStatus ? (
          <ReviewDecisionAction
            className="tracking-action is-save"
            disabledReasonId="pre-spec-tracking-save-disabled"
            isDisabled={!ready}
            label={mutation.isPending ? "저장 중…" : "추적 결정 저장하기"}
            type="submit"
            variant="primary"
          />
        ) : (
          <TrackingDecisionActions
            statuses={TRACKING_DECISION_STATUSES as TrackingDecisionStatus[]}
            current={currentStatus}
            disabledReasonId="pre-spec-tracking-save-disabled"
            isDisabled={!ready}
            pendingStatus={mutation.isPending ? (mutation.variables ?? null) : null}
            onDecide={(status) => {
              if (!ready || mutation.isPending) return;
              mutation.mutate(status);
            }}
          />
        )}
        onSubmit={() => {
          if (!ready || mutation.isPending) return;
          if (!multiStatus) {
            mutation.mutate(TRACKING_DECISION_STATUSES[0] as TrackingDecisionStatus);
            return;
          }
          if (picked === null || !item) return;
          // `종료`만 되돌릴 수 없다. 다른 경로와 같은 확인 단계를 거친다.
          if (picked === "종료") {
            setEndConfirm(trackingEndConfirmContent({ actor: effectiveActor, reason: reasonValue, target: `사업기회 #${item.opportunity_id}` }));
            return;
          }
          mutation.mutate(picked);
        }}
        problem={problem ? <TrackingSaveError problem={problem} /> : null}
        dialog={multiStatus && endConfirm ? (
          <ConfirmDecisionDialog
            confirmLabel={endConfirm.confirmLabel}
            isPending={mutation.isPending}
            onConfirm={() => mutation.mutate("종료", { onSettled: () => setEndConfirm(null) })}
            onOpenChange={(next) => { if (!next) setEndConfirm(null); }}
            open
            summary={endConfirm.summary}
            title={endConfirm.title}
          />
        ) : null}
      />
    );
  }

  if (isPending) {
    return (
      <section className="pre-spec-tracking-decision" aria-labelledby="pre-spec-tracking-decision-title">
        <Heading id="pre-spec-tracking-decision-title">추적 결정</Heading>
        <p role="status">사업기회 연결과 첨부 취득 집계를 불러오는 중이에요.</p>
      </section>
    );
  }

  if (isError || !item) {
    return (
      <section className="pre-spec-tracking-decision" aria-labelledby="pre-spec-tracking-decision-title">
        <Heading id="pre-spec-tracking-decision-title">추적 결정</Heading>
        <EmptyState
          compact
          tone="error"
          title="사업기회 연결 정보를 확인할 수 없어요"
          description="추적 상태와 첨부 취득 집계를 불러오지 못해 이 화면에서 결정을 기록하지 않아요."
          action={{ label: "다시 시도", onClick: onRetry }}
        />
      </section>
    );
  }

  const submit = (status: TrackingDecisionStatus) => {
    if (!ready || mutation.isPending) return;
    if (status === "종료") {
      setEndConfirm(trackingEndConfirmContent({ actor: effectiveActor, reason: reasonValue, target: `사업기회 #${item.opportunity_id}` }));
      return;
    }
    mutation.mutate(status);
  };

  const recordHeading = <>
    <div className="ps-record-tracking-heading"><Heading id="pre-spec-tracking-decision-title">추적 결정</Heading><span aria-label="현재 추적 상태"><Badge label={hasOpportunity ? (currentStatus === "계속 추적" ? "추적 중" : currentStatus === "종료" ? "추적 종료" : currentStatusLabel) : "사업기회 미연결"} variant="neutral" /></span></div>
    <div className="ps-record-tracking-reference"><span>사전규격번호</span><strong>{noticeNumber ?? "미확인"}</strong></div>
  </>;
  const stateManagement = <p className="pre-spec-tracking-elsewhere"><strong>보류·추적 종료</strong>는 사업 추적에서 변경해요.{hasOpportunity ? <Link to={`/opportunities/${item.opportunity_id}`}>사업 추적으로 이동 ↗</Link> : null}</p>;
  if (recorded) {
    return <section className={`pre-spec-tracking-decision is-compact is-record is-recorded${inlineClass}`} aria-labelledby="pre-spec-tracking-decision-title">
      {showRecordHeading ? recordHeading : null}
      <div className="ps-record-saved-decision">
        {/* 방금 저장한 결과도 추적 결정 입력 한 벌(C-7)의 저장 문장으로 알린다. */}
        <Heading>{savedDecision ? trackingSavedMessage(currentStatus === null || currentStatus === "미선택" ? "계속 추적" : currentStatus) : isInheritedTracking(item) ? "발주계획에서 추적 결정을 이어받았어요" : "추적 결정이 기록된 사업이에요"}</Heading>
        <p>현재 추적 상태 · {currentStatusLabel}</p>
        {inheritedContext}
        {savedDecision ? <dl><div><dt>선택 사유</dt><dd>{savedDecision.reason}</dd></div><div><dt>담당자</dt><dd>{savedDecision.actor}</dd></div></dl> : null}
        <Link to={`/opportunities/${item.opportunity_id}`}>사업 추적에서 상태 관리 ↗</Link>
      </div>
      {stateManagement}
    </section>;
  }

  // 발주계획에서 승계한 건은 이 화면이 추적 상태를 **다시 묻지 않는다**(ADR-0046 결정 6).
  // 승계 사실을 배지로 밝히고 결정 form 자체를 그리지 않는다. `보류`·`추적 종료`는
  // 사업 추적에서만 사람이 고른다.
  if (isInheritedTracking(item)) {
    return (
      <section
        className={`pre-spec-tracking-decision is-inherited${compact ? " is-compact" : ""}`}
        aria-labelledby="pre-spec-tracking-decision-title"
      >
        <div className="pre-spec-tracking-decision-header">
          <div>
            <Heading id="pre-spec-tracking-decision-title">추적 상태 · 발주계획에서 승계</Heading>
            <p>
              발주계획에서 추적 결정을 이어받았어요.
            </p>
            {inheritedContext}
          </div>
          <div className="pre-spec-tracking-current" aria-label="현재 추적 상태">
            <span>현재 추적 상태</span>
            <Badge label={`${currentStatusLabel} · 발주계획에서 승계`} variant={currentStatusVariant} />
          </div>
        </div>

        {!compact ? <PreSpecDocumentSummary item={item} /> : null}

        <p className="pre-spec-tracking-elsewhere">
          <Link to={`/opportunities/${item.opportunity_id}`}>사업 추적</Link>에서만 <strong>보류</strong>와 <strong>추적 종료</strong>를 골라요. 추적 결정은 추적만 정하며 분석 실행 승인이 아니에요.
        </p>
      </section>
    );
  }

  return (
    <section
      className={`pre-spec-tracking-decision${compact ? " is-compact" : ""}${record ? " is-record" : ""}${inlineClass}`}
      aria-labelledby="pre-spec-tracking-decision-title"
    >
      {record ? (showRecordHeading ? recordHeading : null) : (
      <div className="pre-spec-tracking-decision-header">
        <div>
          {!compact ? <span className="pre-spec-tracking-kicker">사람이 고르는 추적 결정</span> : null}
          <Heading id="pre-spec-tracking-decision-title">추적 결정</Heading>
          {/* 이 결정이 최종 Go/No-Go가 아니라는 사실은 CLAUDE.md 강제 게이트
              (네 결정은 서로를 대신하지 않는다)라, 밀도를 낮추더라도 액션 옆에서
              지우지 않는다. compact는 설명을 줄일 뿐 이 구분은 남긴다. */}
          <p>
            {compact
              ? "개요 검토 권고를 자동 반영하지 않아요. 최종 입찰 참여 결정(Go/No-Go)이 아니에요."
              : "개요 검토 권고를 자동 반영하지 않고 사람이 고르는 추적 결정이에요. 최종 입찰 참여 결정(Go/No-Go)이 아니에요."}
          </p>
        </div>
        <div className="pre-spec-tracking-current" aria-label="현재 추적 상태">
          <span>현재 추적 상태</span>
          {hasOpportunity
            ? <Badge label={currentStatusLabel} variant={currentStatusVariant} />
            : <strong>사업기회 미연결</strong>}
        </div>
      </div>
      )}

      {!compact ? <PreSpecDocumentSummary item={item} /> : null}

      {!hasOpportunity ? (
        <MutationFeedback tone="warning">
          아직 사업기회에 연결되지 않아 추적 상태를 결정할 수 없어요. 사업기회 연결이 생긴 뒤 이 화면에서 추적을 시작할 수 있어요.
        </MutationFeedback>
      ) : null}

      <form
        className={`pre-spec-tracking-form${compact ? " is-compact" : ""}${inlineClass}`}
        id={formId}
        onSubmit={(event) => {
          event.preventDefault();
          submit(TRACKING_DECISION_STATUSES[0] as TrackingDecisionStatus);
        }}
      >
        {record && showIntent ? <div className="ps-record-tracking-intent"><span>저장할 결정</span><h4>추적 시작 <span>→ 계속 추적</span></h4><p>새 문서·입찰공고·정정공고를 계속 확인해요.</p></div> : null}

        {hasOpportunity ? (
          <TrackingDecisionInputs
            presets={reasonPresets ?? []}
            choice={choice}
            onChoiceChange={setChoice}
            custom={custom}
            onCustomChange={setCustom}
            actorName={actorName}
            onActorNameChange={setActorName}
            isDisabled={mutation.isPending}
            size={record && !inline ? "md" : "sm"}
            reasonClassName="pre-spec-tracking-reason-preset"
            // 한 줄 배치에서는 라벨 줄이 화면에 보이지 않으므로(시안
            // mockups/artboards/Main.dc.html 198줄) 무슨 칸인지 placeholder가 말한다.
            actorPlaceholder={inline ? "담당자 이름 (필수)" : "예: 홍길동"}
          />
        ) : null}

        {problem ? <TrackingSaveError problem={problem} /> : null}
        {formId ? null : (
          <div className="pre-spec-tracking-action">
            <TrackingDecisionActions
              statuses={TRACKING_DECISION_STATUSES as TrackingDecisionStatus[]}
              current={currentStatus}
              disabledReasonId="pre-spec-tracking-save-disabled"
              isDisabled={!ready}
              pendingStatus={mutation.isPending ? (mutation.variables ?? null) : null}
              onDecide={submit}
            />
            {disabledReason ? <DisabledReason id="pre-spec-tracking-save-disabled">{disabledReason}</DisabledReason> : null}
          </div>
        )}
        {/* spec §3.3에서 `보류·추적 종료는 사업 추적에서 변경` 캡션은 줄 1이 소유하므로
            inline 폼은 같은 문장을 한 번 더 적지 않는다. 승계·기록된 사업의 상태 블록은
            record와 똑같이 이 문장을 그대로 그린다. */}
        {record ? (inline ? null : stateManagement) : (        <p className="pre-spec-tracking-elsewhere">
          <strong>보류</strong>와 <strong>추적 종료</strong>는 이 화면에 없어요. 사업 추적에서만 사람이 골라요.
        </p>)}
      </form>
      <ConfirmDecisionDialog
        confirmLabel={endConfirm?.confirmLabel ?? "종료 상태로 저장"}
        isPending={mutation.isPending}
        onConfirm={() => mutation.mutate("종료", { onSettled: () => setEndConfirm(null) })}
        onOpenChange={(next) => { if (!next) setEndConfirm(null); }}
        open={endConfirm !== null}
        summary={endConfirm?.summary ?? []}
        title={endConfirm?.title ?? "추적을 종료해요"}
      />
    </section>
  );
}

type TrackingDecisionBarState =
  | { kind: "loading" }
  | { kind: "error"; onRetry: () => void }
  | { kind: "unlinked"; disabledReason: string; currentStatus: OpportunityTrackingStatus | null }
  | { kind: "recorded"; headline: string; statusLabel: string; context: ReactNode; opportunityId: number }
  | { kind: "input"; currentStatusLabel: string; disabledReason: string | null; actor: string; savedMessage: string | null; choices: ReactNode; reasonHidden: boolean };

/**
 * 하단 결정 띠의 배치(2026-11-21 시안 `.decision-bar`). 규칙·문구·저장은 `PreSpecTrackingDecisionControl`이 정하고
 * 여기는 한 줄 배치만 한다: 왼쪽 두 줄(상태 · 경계 문장) / 선택 사유 / 주 버튼. 화면의 주 버튼은 이 띠의 하나뿐이다.
 */
function TrackingDecisionBarLayout({
  state,
  inputs,
  actions,
  onSubmit,
  problem,
  dialog,
}: {
  state: TrackingDecisionBarState;
  inputs: ReactNode;
  actions: ReactNode;
  onSubmit: () => void;
  problem: ReactNode;
  dialog: ReactNode;
}) {
  const heading = <h2 className="visually-hidden" id="pre-spec-tracking-decision-title">추적 결정</h2>;
  const boundary = <p className="ps-decision-bar-boundary">{state.kind === "input" && state.choices ? TRACKING_BAR_BOUNDARY_AFTER_ANALYSIS : TRACKING_BAR_BOUNDARY}</p>;
  const frame = (body: ReactNode, modifier: string) => (
    <section className={`pre-spec-tracking-decision is-bar ${modifier}`} aria-labelledby="pre-spec-tracking-decision-title">
      {heading}
      {body}
    </section>
  );

  if (state.kind === "loading") {
    return frame(
      <div className="ps-decision-bar-row">
        <div className="ps-decision-bar-text">
          <p className="ps-decision-bar-status" role="status">사업기회 연결과 첨부 취득 집계를 불러오는 중이에요.</p>
          {boundary}
        </div>
      </div>,
      "is-loading",
    );
  }

  if (state.kind === "error") {
    return frame(
      <div className="ps-decision-bar-row">
        <div className="ps-decision-bar-text" role="alert">
          <p className="ps-decision-bar-status"><strong>사업기회 연결 정보를 확인할 수 없어요</strong></p>
          <p className="ps-decision-bar-boundary">추적 상태를 불러오지 못해 이 화면에서 결정을 기록하지 않아요.</p>
        </div>
        <div className="ps-decision-bar-action">
          <Button label="다시 시도" onClick={state.onRetry} />
        </div>
      </div>,
      "is-error",
    );
  }

  if (state.kind === "recorded") {
    return frame(
      <div className="ps-decision-bar-row">
        <div className="ps-decision-bar-text">
          <p className="ps-decision-bar-status"><strong>{state.headline}</strong><span className="ps-decision-bar-sep" aria-hidden="true"> · </span><span>{state.statusLabel}</span></p>
          <p className="ps-decision-bar-boundary pre-spec-inherited-context">{state.context}</p>
        </div>
        <div className="ps-decision-bar-action">
          <Link className="ps-decision-bar-link" to={`/opportunities/${state.opportunityId}`}>사업 추적에서 상태 관리 ↗</Link>
        </div>
      </div>,
      "is-recorded",
    );
  }

  if (state.kind === "unlinked") {
    return frame(
      <div className="ps-decision-bar-row">
        <div className="ps-decision-bar-text">
          <p className="ps-decision-bar-status"><strong>사업기회 미연결</strong></p>
          <DisabledReason className="ps-decision-bar-boundary" id="pre-spec-tracking-save-disabled">{state.disabledReason}</DisabledReason>
        </div>
        <div className="ps-decision-bar-action">{actions}</div>
      </div>,
      "is-unlinked",
    );
  }

  return frame(
    <>
      <form
        className="ps-decision-bar-row pre-spec-tracking-form"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <div className="ps-decision-bar-text">
          <div className="ps-decision-bar-status">
            {state.savedMessage ? <strong role="status">{state.savedMessage}</strong> : null}
            {state.savedMessage ? <span className="ps-decision-bar-sep" aria-hidden="true"> · </span> : null}
            <strong>{state.choices ? "현재 추적 상태" : "추적 상태"} {state.currentStatusLabel}</strong>
            {state.reasonHidden ? null : <span className="ps-decision-bar-sep" aria-hidden="true"> · </span>}
            {state.disabledReason ? (
              <DisabledReason className={`ps-decision-bar-note${state.reasonHidden ? " visually-hidden" : ""}`} id="pre-spec-tracking-save-disabled">{state.disabledReason}</DisabledReason>
            ) : (
              <p className="ps-decision-bar-note">{state.actor} 이름으로 기록해요</p>
            )}
            {/* 이름은 사이드바 담당자 칸 하나에서만 적는다. 비어 있으면 그 칸을 열어 초점을 옮긴다. */}
            {!state.actor ? (
              <button className="ps-decision-bar-actor" data-testid="pre-spec-actor-missing" onClick={requestActorInput} type="button">사이드바에서 이름 입력하기</button>
            ) : !state.disabledReason ? (
              <button className="ps-decision-bar-actor" onClick={requestActorInput} type="button">이름 바꾸기</button>
            ) : null}
          </div>
          {boundary}
        </div>
        {state.choices}
        <div className="ps-decision-bar-fields">{inputs}</div>
        <div className="ps-decision-bar-action pre-spec-tracking-action">{actions}</div>
      </form>
      {problem}
      {dialog}
    </>,
    state.choices ? "is-input is-decide" : "is-input",
  );
}

// ---------------------------------------------------------------------------
// 회사 경로 adapter (가상회사 데모, `docs/work/demo-contract.md` §2)

/**
 * 추적 결정을 어느 API로 읽고 저장할지. 컨트롤의 규칙(세 상태·사유·담당자·종료 확인·
 * 미저장 이탈 확인·request_id·expected_revision)은 컨트롤이 소유하고, adapter는 endpoint와
 * 저장 성공 뒤 cache 반영만 정한다.
 *
 * adapter는 만들 때의 회사·사업기회를 붙잡는다. 저장 mutation은 시작할 때의 adapter를
 * 변수로 넘기므로, 사람이 그사이 다른 회사로 옮겨도 cache 반영은 시작한 회사에만 한다.
 */
export interface TrackingDecisionAdapter {
  /** 회사 경로임을 밝힌다. 화면 문구와 radio 이름의 범위다. */
  scopeKey: string;
  /** 사업기회 미연결이면 null이며 저장 form을 그리지 않는다. */
  opportunityId: number | null;
  /** 이 경로가 저장하는 결정. 회사 경로는 계속 추적·보류·종료 세 상태다. */
  decisions: readonly CompanyTrackingStatus[];
  queryKey: QueryKey;
  load: (signal: AbortSignal) => Promise<CompanyTrackingDTO>;
  save: (payload: CompanyTrackingUpdateRequest, actorName: string) => Promise<CompanyTrackingDTO>;
  /** 저장 성공 뒤 시작한 회사의 cache만 갱신한다. */
  applySaved: (queryClient: QueryClient, saved: CompanyTrackingDTO) => void;
  /** 종료 확인 창의 대상 문구. */
  targetLabel: string;
  /** 저장을 시작한 주체 문구(예: "회사 데모 업무SI"). 처리 중 이탈 확인에 쓴다. */
  ownerLabel: string;
}

export interface CompanyTrackingDecisionControlProps {
  adapter: TrackingDecisionAdapter;
  headingLevel?: "h3" | "h4";
}

export type TrackingDecisionControlProps = PreSpecTrackingDecisionControlProps | CompanyTrackingDecisionControlProps;

/** 회사 경로 adapter. 회사·사업기회·공고를 만들 때 고정한다. */
export function companyTrackingAdapter({ companyId, opportunityId, noticeId, companyName = null }: { companyId: Uuid; opportunityId: number | null; noticeId: number | null; companyName?: string | null }): TrackingDecisionAdapter {
  return {
    scopeKey: `company-${companyId}-${opportunityId ?? "unlinked"}`,
    opportunityId,
    decisions: COMPANY_TRACKING_DECISIONS,
    queryKey: companyKeys.tracking(companyId, opportunityId ?? 0),
    load: (signal) => companyApi.getTracking(companyId, opportunityId as number, { signal }),
    save: (payload, actorName) => companyApi.updateTracking(companyId, opportunityId as number, payload, actorName),
    applySaved: (queryClient, saved) => applyCompanyTrackingSaved(queryClient, { companyId, opportunityId: opportunityId as number, noticeId }, saved),
    targetLabel: `사업기회 #${opportunityId ?? "미연결"} · 이 회사`,
    ownerLabel: companyName ? `회사 ${companyName}` : "저장을 시작한 회사",
  };
}

/** 같은 저장 의도(상태·사유·기준 revision·담당자)의 재시도에는 같은 request_id를 쓴다. */
function trackingIntentFingerprint(status: CompanyTrackingStatus, reason: string, expectedRevision: number, actorName: string): string {
  return JSON.stringify([status, reason.trim(), expectedRevision, actorName.trim()]);
}

function readErrorCode(error: unknown): string | null {
  return describeCompanyApiError(error, "").code;
}

function TrackingSnapshot({ label, tracking, testId }: { label: string; tracking: { status: string; reason: string | null; actor: string | null; at?: string | null; revision: number }; testId: string }) {
  return (
    <div className="cw-tracking-snapshot" data-testid={testId}>
      <strong>{label}</strong>
      <dl className="cw-facts">
        <dt>추적 상태</dt><dd>{tracking.status}</dd>
        <dt>사유</dt><dd>{tracking.reason?.trim() ? tracking.reason : "값 없음"}</dd>
        <dt>담당자</dt><dd>{tracking.actor?.trim() ? tracking.actor : "값 없음"}</dd>
        {tracking.at !== undefined ? <><dt>기록 시각</dt><dd>{tracking.at ? formatDateTime(tracking.at) : "값 없음"}</dd></> : null}
        <dt>기준 기록</dt><dd>{tracking.revision}회</dd>
      </dl>
    </div>
  );
}

interface CompanyTrackingSaveVariables {
  adapter: TrackingDecisionAdapter;
  payload: CompanyTrackingUpdateRequest;
  actorName: string;
}

/**
 * 회사 경로의 추적 결정 입력.
 *
 * - 화면은 서버가 성공을 돌려준 뒤에만 바뀐다(낙관적 갱신 없음).
 * - 409 `version_conflict`: 초안을 그대로 두고 서버 최신값을 다시 읽어 나란히 보여 준다.
 *   자동으로 덮어쓰지 않으며, 사람이 `최신값 기준으로 다시 저장 준비`를 눌러야 그 revision으로 저장한다.
 * - 409 `idempotency_conflict`: 같은 request_id로 다른 내용을 보낸 재전송 충돌이다. 그 request_id는
 *   버리고, 사람이 새 저장 요청으로 다시 시작해야 저장한다.
 * - 저장하지 않은 입력이 있으면 회사 전환을 포함한 경로 이동 전에 확인한다. 취소하면 그대로 남는다.
 */
function CompanyTrackingDecision({ adapter, headingLevel = "h3" }: CompanyTrackingDecisionControlProps) {
  const Heading = headingLevel;
  const queryClient = useQueryClient();
  const opportunityId = adapter.opportunityId;
  const trackingQuery = useQuery({
    queryKey: adapter.queryKey,
    queryFn: ({ signal }) => adapter.load(signal),
    enabled: opportunityId !== null,
    retry: false,
  });
  const latest = trackingQuery.data;
  const [status, setStatus] = useState<CompanyTrackingStatus | null>(null);
  const [reason, setReason] = useState("");
  const [actorName, setActorName] = useState("");
  /** 초안이 기준으로 삼은 서버 값. 초안이 있는 동안 서버 값이 바뀌어도 몰래 바꾸지 않는다. */
  const [base, setBase] = useState<CompanyTrackingDTO | null>(null);
  const [pendingRequest, setPendingRequest] = useState<{ requestId: string; fingerprint: string } | null>(null);
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);
  const [versionConflict, setVersionConflict] = useState(false);
  const [resendConflict, setResendConflict] = useState(false);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [endConfirm, setEndConfirm] = useState<ReturnType<typeof trackingEndConfirmContent> | null>(null);

  const dirty = status !== null || reason.trim().length > 0;

  useEffect(() => {
    // 잃을 초안이 없을 때만 기준을 서버 최신값으로 맞춘다.
    if (latest && (!dirty || base === null)) setBase(latest);
  }, [latest, dirty, base]);

  useEffect(() => {
    if (dirty) setSavedMessage(null);
  }, [dirty]);

  useEffect(() => {
    // 사람이 초안을 모두 지우면 비교할 초안이 없다. 충돌 표시는 거두고 기준은 위에서 최신값으로 맞춘다.
    if (!dirty && versionConflict) {
      setVersionConflict(false);
      setProblem(null);
    }
  }, [dirty, versionConflict]);

  const mutation = useMutation({
    mutationFn: (variables: CompanyTrackingSaveVariables) => variables.adapter.save(variables.payload, variables.actorName),
    // hook 단위 콜백은 화면이 다른 회사로 바뀌어 이 컴포넌트가 사라진 뒤에도 실행된다.
    // 그래서 cache 반영은 시작할 때의 adapter(시작한 회사)로만 한다.
    onSuccess: (saved, variables) => variables.adapter.applySaved(queryClient, saved),
  });

  const pendingStatus = mutation.isPending ? mutation.variables?.payload.tracking_status ?? null : null;
  const owner = adapter.ownerLabel;
  // 저장 요청을 이미 보낸 뒤에는 "입력이 사라진다"가 틀린 말이다. 보낸 요청은 이동해도
  // 취소되지 않고 시작한 회사에 저장될 수 있으므로 그 사실을 그대로 적는다.
  const guard = useUnsavedGuard(dirty, mutation.isPending ? {
    blockSpaNavigation: true,
    scope: "pathname",
    title: "추적 결정 저장 요청을 처리하고 있어요",
    message: `저장 요청을 이미 보냈어요. 지금 이동해도 그 요청은 취소되지 않으며 ${owner}에 저장될 수 있어요. 다른 회사에는 저장되지 않아요. 저장 결과는 ${owner} 화면에서 다시 확인해 주세요.`,
    confirmLabel: "이동하기 (보낸 요청은 계속 처리)",
    cancelLabel: "이 회사에 머물기",
    summary: [
      { label: "보낸 요청", value: `${pendingStatus ?? "추적 결정"} · 처리 중` },
      { label: "사유", value: reason.trim() || "값 없음" },
    ],
  } : {
    blockSpaNavigation: true,
    scope: "pathname",
    title: "이 회사의 추적 결정을 저장하지 않았어요",
    message: "저장하지 않은 추적 결정 입력이 있어요. 다른 화면이나 다른 회사로 옮기면 이 입력은 사라지며, 다른 회사에 저장되지 않아요.",
    confirmLabel: "입력을 버리고 이동",
    cancelLabel: "이 회사에 머물기",
    summary: [
      { label: "추적 상태", value: status ?? "값 없음" },
      { label: "사유", value: reason.trim() || "값 없음" },
    ],
  });

  if (opportunityId === null) {
    return (
      <section className="cw-section" aria-labelledby="company-tracking-title" data-testid="company-tracking-unlinked">
        <Heading id="company-tracking-title">이 회사의 추적 결정</Heading>
        <p className="cw-caption">아직 사업기회에 연결되지 않아 추적 결정을 기록할 수 없어요.</p>
      </section>
    );
  }

  const needsNewIntent = versionConflict || resendConflict;
  const ready = base !== null && status !== null && requiredDecisionInputReason(reason, actorName) === null
    && reason.trim().length <= 2000 && !mutation.isPending && !needsNewIntent;
  const disabledReason = mutation.isPending
    ? "저장 요청을 처리하고 있어요."
    : base === null
      ? "현재 추적 상태를 확인한 뒤 저장할 수 있어요."
      : versionConflict
        ? "서버 최신값과 초안을 비교한 뒤 ‘최신값 기준으로 다시 저장 준비’를 눌러야 저장해요."
        : resendConflict
          ? "재전송 충돌을 확인한 뒤 ‘새 저장 요청으로 다시 시작’을 눌러야 저장해요."
          : status === null
            ? "추적 상태(계속 추적·보류·종료)를 골라 주세요."
            : requiredDecisionInputReason(reason, actorName);

  const send = () => {
    if (!ready || base === null || status === null) return;
    const fingerprint = trackingIntentFingerprint(status, reason, base.revision, actorName);
    let requestId: string;
    try {
      requestId = pendingRequest?.fingerprint === fingerprint ? pendingRequest.requestId : generateRequestId();
    } catch {
      setProblem({
        title: "안전한 요청 식별자를 만들 수 없어요.",
        detail: "이 브라우저에서 암호학적 난수를 쓸 수 없어 저장하지 않았어요. 다른 브라우저에서 다시 시도해 주세요.",
        action: null,
        code: null,
      });
      return;
    }
    setPendingRequest({ requestId, fingerprint });
    setProblem(null);
    mutation.mutate(
      {
        adapter,
        payload: { tracking_status: status, reason: reason.trim(), expected_revision: base.revision, request_id: requestId },
        actorName: actorName.trim(),
      },
      {
        // 이 컴포넌트가 아직 같은 회사 화면에 있을 때만 입력을 비운다.
        onSuccess: (saved) => {
          guard.release();
          setStatus(null);
          setReason("");
          setPendingRequest(null);
          setBase(saved);
          setSavedMessage(`${saved.tracking_status}(으)로 저장했어요.`);
        },
        onError: (caught) => {
          const code = readErrorCode(caught);
          if (code === "version_conflict") {
            // 초안은 그대로 둔다. 서버 최신값을 다시 읽어 나란히 보여 주되 기준은 바꾸지 않는다.
            setVersionConflict(true);
            void trackingQuery.refetch();
          } else if (code === "idempotency_conflict") {
            // 그 request_id는 다시 쓰지 않는다. 새 저장 요청으로만 다시 보낸다.
            setResendConflict(true);
            setPendingRequest(null);
            void trackingQuery.refetch();
          }
          // 그 밖의 실패는 입력과 request_id를 그대로 둔다. 같은 입력의 재시도는 같은 request_id다.
          setProblem(describeCompanyApiError(caught, "추적 결정을 저장하지 못했어요."));
        },
      },
    );
  };

  const rebaseOnLatest = () => {
    if (!latest) return;
    setBase(latest);
    setVersionConflict(false);
    setProblem(null);
    setPendingRequest(null);
  };

  const startNewIntent = () => {
    setResendConflict(false);
    setProblem(null);
    setPendingRequest(null);
  };

  return (
    <section className="cw-section" aria-labelledby="company-tracking-title" data-testid="company-tracking">
      <Heading id="company-tracking-title">이 회사의 추적 결정</Heading>
      <p className="cw-caption" data-testid="company-tracking-boundary">
        계속 추적·보류·종료는 이 회사의 사업 추적 결정이에요. 회사 핏(적합성) 판정이나 최종 입찰 참여 결정(Go/No-Go)이 아니며 서로 대신하지 않아요.
        세 상태 저장은 가상회사 데모 경로에만 있어요.
      </p>
      {trackingQuery.isPending ? (
        <p role="status">현재 추적 상태를 불러오는 중이에요.</p>
      ) : trackingQuery.isError && !latest ? (
        <EmptyState
          compact
          tone="error"
          title="현재 추적 상태를 확인할 수 없어요"
          problem={describeCompanyApiError(trackingQuery.error, "추적 상태를 불러오지 못했어요.")}
          action={{ label: "다시 시도", onClick: () => { void trackingQuery.refetch(); } }}
        />
      ) : latest ? (
        <p data-testid="company-tracking-current">
          현재 {latest.tracking_status}
          {latest.selected_by ? ` · ${latest.selected_by}` : ""}
          {latest.selected_at ? ` · ${formatDateTime(latest.selected_at)}` : ""}
          <span className="cw-caption"> · 기록 {latest.revision}회</span>
        </p>
      ) : null}

      {versionConflict && base ? (
        <div className="cw-tracking-conflict" role="group" aria-label="추적 결정 저장 충돌" data-testid="company-tracking-conflict">
          <p>
            다른 사람이 먼저 이 회사의 추적 결정을 바꿨어요. 초안은 지우지 않았고 서버 값으로 자동 덮어쓰지 않아요.
            두 값을 비교한 뒤 최신값을 기준으로 다시 저장할지 정해 주세요.
          </p>
          <div className="cw-tracking-conflict-grid">
            <TrackingSnapshot
              label="내 초안 · 저장 안 됨"
              testId="company-tracking-conflict-draft"
              tracking={{ status: status ?? "선택 안 함", reason, actor: actorName, revision: base.revision }}
            />
            {latest && latest.revision !== base.revision ? (
              <TrackingSnapshot
                label="서버 최신값"
                testId="company-tracking-conflict-latest"
                tracking={{ status: latest.tracking_status, reason: latest.reason, actor: latest.selected_by, at: latest.selected_at, revision: latest.revision }}
              />
            ) : trackingQuery.isFetching ? (
              <p role="status">서버 최신값을 불러오는 중이에요.</p>
            ) : (
              <p className="cw-caption">서버 최신값을 확인하지 못했어요. 다시 불러온 뒤 비교해 주세요.</p>
            )}
          </div>
          <div className="cw-tracking-actions">
            <button
              className="cw-button"
              type="button"
              disabled={!latest || latest.revision === base.revision || trackingQuery.isFetching}
              onClick={rebaseOnLatest}
            >
              최신값 기준으로 다시 저장 준비
            </button>
            <button className="cw-button" type="button" disabled={trackingQuery.isFetching} onClick={() => { void trackingQuery.refetch(); }}>
              서버 최신값 다시 불러오기
            </button>
          </div>
        </div>
      ) : null}

      <form
        className="cw-tracking-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!ready || status === null) return;
          if (status === "종료") {
            setEndConfirm(trackingEndConfirmContent({ actor: actorName, reason, target: adapter.targetLabel }));
            return;
          }
          send();
        }}
      >
        <fieldset disabled={mutation.isPending}>
          <legend>추적 상태</legend>
          {adapter.decisions.map((value) => (
            <label key={value}>
              <input
                checked={status === value}
                name={`company-tracking-${adapter.scopeKey}`}
                type="radio"
                value={value}
                onChange={() => setStatus(value)}
              />{" "}
              {value}
            </label>
          ))}
        </fieldset>
        <label>
          <span>사유 (필수)</span>
          <textarea
            aria-label="추적 결정 사유"
            maxLength={2000}
            readOnly={mutation.isPending}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <ActorField label="추적 결정 담당자 이름" value={actorName} onChange={setActorName} readOnly={mutation.isPending} />
        <div className="cw-tracking-actions">
          <button
            className="cw-button"
            disabled={!ready}
            type="submit"
            aria-describedby={disabledReason ? "company-tracking-save-disabled" : undefined}
          >
            {mutation.isPending ? "저장 중…" : problem && !needsNewIntent ? "다시 저장" : "추적 결정 저장"}
          </button>
          {disabledReason ? <DisabledReason id="company-tracking-save-disabled">{disabledReason}</DisabledReason> : null}
        </div>
      </form>
      {problem ? (
        <MutationFeedback
          tone="error"
          problem={problem}
          onRecover={needsNewIntent ? undefined : () => { void trackingQuery.refetch(); }}
        >
          {resendConflict ? (
            <p data-testid="company-tracking-resend-conflict">
              같은 요청 식별자로 다른 내용을 보낸 재전송 충돌이에요. 앞선 요청이 이미 저장됐을 수 있으니 위의 현재 상태를 확인해 주세요.
              이 요청 식별자는 다시 쓰지 않아요. 저장하려면 새 저장 요청으로 다시 시작해 주세요.
            </p>
          ) : null}
        </MutationFeedback>
      ) : null}
      {resendConflict ? (
        <div className="cw-tracking-actions">
          <button className="cw-button" type="button" onClick={startNewIntent}>새 저장 요청으로 다시 시작</button>
        </div>
      ) : null}
      {savedMessage ? <p role="status">{savedMessage}</p> : null}
      {/* 확인 창은 종료를 고른 순간에만 둔다. 닫힌 확인 창을 문서에 남겨 두면 같은 화면의
          미저장 이탈 확인 창과 함께 alertdialog가 둘이 된다. */}
      {endConfirm ? (
        <ConfirmDecisionDialog
          confirmLabel={endConfirm.confirmLabel}
          isPending={mutation.isPending}
          onConfirm={() => { setEndConfirm(null); send(); }}
          onOpenChange={(next) => { if (!next) setEndConfirm(null); }}
          open
          summary={endConfirm.summary}
          title={endConfirm.title}
        />
      ) : null}
    </section>
  );
}
