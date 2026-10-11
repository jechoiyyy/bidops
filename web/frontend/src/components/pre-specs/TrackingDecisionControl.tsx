import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Selector } from "@astryxdesign/core/Selector";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Badge } from "../common/Badge";
import { ActorField } from "../common/ActorField";
import { ConfirmDecisionDialog, trackingEndConfirmContent } from "../common/ConfirmDecisionDialog";
import { useUnsavedGuard } from "../common/useUnsavedGuard";
import { DisabledReason } from "../common/DisabledReason";
import { EmptyState } from "../common/EmptyState";
import { MutationFeedback } from "../common/MutationFeedback";
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
import { originOf, trackingDescription, trackingVariant } from "../../lib/opportunity";
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
 */
export const TRACKING_DECISION_STATUSES: OpportunityTrackingStatus[] = ["계속 추적"];

/**
 * 사유·담당자 필수 규칙. 기존 사전규격 경로와 회사 경로가 같은 문구로 막는다.
 * 사유는 공백을 뺀 뒤 1자 이상이어야 하며(서버도 trim 뒤 1~2000자), 담당자 이름은
 * 감사 표식일 뿐 인증이 아니다.
 */
function requiredDecisionInputReason(reason: string, actorName: string): string | null {
  if (!reason.trim()) return "추적 결정을 저장하려면 사유를 입력하십시오.";
  if (!actorName.trim()) return "추적 결정을 저장하려면 담당자 이름을 입력하십시오.";
  return null;
}

/** 사유 예시 드롭다운에서 "직접 입력"을 뜻하는 값. 계약에 실리지 않는다. */
const OTHER_REASON_PRESET = "__other__";

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
      <p>첨부 취득 상태는 같은 공고의 누적 사전규격 요약 정보에서 확인했습니다.</p>
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
   * 상태값·사유 필수·담당자 기억·비활성 사유를 다시 구현하지 않는다. */
  presentation?: "default" | "record" | "inline";
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
   * 신규 사전규격에서 `추적 시작하고 심층 검토`를 한 조작으로 제공할 때 이어지는 자리.
   *
   * 주어지면 저장 버튼 이름이 `추적 시작하고 심층 검토`가 되고 저장 성공 뒤 호출된다.
   * **이력에는 추적 시작과 심층 검토 실행이 별도 항목으로 남는다**(ADR-0046 결정 6) —
   * 이 조작은 두 결정을 한 기록으로 합치지 않고, 추적 시작만 지금 기록한 뒤 심층 검토
   * 실행 승인 자리로 데려간다.
   */
  onStartedForDeepReview?: () => void;
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
  onStartedForDeepReview,
  onDirtyChange,
  reasonPresets,
  presentation = "default",
  noticeNumber,
  showRecordHeading = true,
  showIntent = true,
}: PreSpecTrackingDecisionControlProps) {
  const Heading = headingLevel;
  const opportunityId = item?.opportunity_id ?? null;
  const inherited = item !== undefined && isInheritedTracking(item);
  const opportunityQuery = useQuery({
    queryKey: ["opportunity", opportunityId],
    queryFn: () => api.getOpportunity(opportunityId as number),
    enabled: inherited && opportunityId !== null && !isPending && !isError,
    retry: false,
    staleTime: 30_000,
  });
  const inheritedContext = !inherited ? null : opportunityQuery.isPending ? (
    <p role="status">승계 사유를 불러오는 중입니다.</p>
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
  const record = presentation === "record" || inline;
  const inlineClass = inline ? " is-inline" : "";
  const [savedDecision, setSavedDecision] = useState<{ reason: string; actor: string } | null>(null);
  const hasPresets = Boolean(reasonPresets && reasonPresets.length > 0);
  // 사전규격에서 고를 수 있는 값은 `계속 추적` 하나뿐이다(ADR-0046 결정 6).
  const [status, setStatus] = useState<OpportunityTrackingStatus>(
    item?.tracking_status && item.tracking_status !== "미선택" ? item.tracking_status : TRACKING_DECISION_STATUSES[0],
  );
  const [reason, setReason] = useState("");
  // 드롭다운 선택 키와 실제 저장 사유를 구분한다. `기타` 키는 API에 보내지 않는다.
  const [presetChoice, setPresetChoice] = useState("");
  const [actorName, setActorName] = useState("");
  const [feedback, setFeedback] = useState<{ tone: "success"; message: string } | null>(null);
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);
  // `종료`만 되돌릴 수 없다. `계속 추적`과 `보류`는 다시 고를 수 있으므로 확인
  // 단계를 두지 않는다. 저장에 성공하면 사유·담당자가 비워지므로 요약은 열 때의
  // 값을 얼려 둔다.
  const [endConfirm, setEndConfirm] = useState<ReturnType<typeof trackingEndConfirmContent> | null>(null);

  useEffect(() => {
    if (!item) return;
    setStatus(item.tracking_status && item.tracking_status !== "미선택" ? item.tracking_status : TRACKING_DECISION_STATUSES[0]);
  }, [item?.notice_pk]);

  // 사유는 저장 전까지 이 컴포넌트에만 있다. 화면을 떠나면 사라지므로 여기서 직접
  // route 이동을 막는다. 부르는 화면(PreSpecsPage·PreSpecDetailPage)이 같은 규칙을
  // 다시 구현하지 않게 하려는 것이며, 목록의 행 전환은 목록이 `onDirtyChange`로
  // 받아 자기 자리에서 확인해야 한다.
  //
  // dirty는 사유(프리셋 선택 또는 자유 입력)만 본다. 담당자 이름만 채우고 사유가
  // 비어 있으면 저장할 수 없는 입력이라 잃을 것이 없으므로, 그 상태에서 다른 공고로
  // 옮기거나 상세를 떠나도 확인 창을 띄우지 않는다. 사유가 있으면 담당자 이름도
  // 함께 잃으므로 guard summary는 계속 둘 다 보여 준다.
  //
  // 범위가 `pathname`인 이유: 두 화면 모두 선택·필터를 검색 인자로 옮기므로
  // `any`로 두면 사유를 적는 중에 목록 조작마다 이탈 확인이 뜬다.
  const dirty = presetChoice !== "" || reason.trim().length > 0;
  const guard = useUnsavedGuard(dirty, {
    blockSpaNavigation: true,
    scope: "pathname",
    title: "심층 검토 추적 선택을 저장하지 않고 떠납니다",
    message: "저장하지 않은 추적 결정 사유와 담당자 이름이 있습니다. 지금 이동하면 사라지며 저장된 추적 상태는 바뀌지 않습니다.",
    summary: [
      { label: "사유", value: reason.trim() || "값 없음" },
      { label: "담당자", value: actorName.trim() || "값 없음" },
    ],
  });

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  const mutation = useMutation({
    mutationFn: () => api.updateOpportunityTrackingStatus(
      item?.opportunity_id as number,
      { tracking_status: status, reason: reason.trim() },
      actorName,
    ),
    onSuccess: (saved) => {
      if (!item) return;
      // 저장이 끝났으므로 잃을 입력이 없다. `onStartedForDeepReview`가 곧바로
      // 이동시키는데, 그 시점의 dirty 계산은 아직 이전 렌더 값이라 먼저 푼다.
      guard.release();
      if (record) setSavedDecision({ reason: saved.tracking_reason ?? "기록된 사유 미확인", actor: saved.tracking_selected_by ?? "담당자 미확인" });
      setStatus(saved.tracking_status);
      setReason("");
      setPresetChoice("");
      setActorName("");
      setProblem(null);
      setFeedback({ tone: "success", message: "심층 검토 추적 상태를 저장했습니다." });
      onSaved(saved);
      // 추적 시작이 기록된 뒤에만 심층 검토 실행 자리로 넘어간다. 두 결정은 별개다.
      onStartedForDeepReview?.();
    },
    onError: (caught: unknown) => {
      // 서버 응답 본문에는 provider·검증 상세가 실릴 수 있다. 화면에 내는 것은
      // `describeApiError`가 status와 안전한 오류 코드로 옮긴 문구뿐이다.
      setFeedback(null);
      setProblem(describeApiError(caught, "심층 검토 추적 상태를 저장하지 못했습니다."));
    },
  });

  // 전제조건은 조기 반환보다 앞에서 계산한다. 상세 화면의 결정 패널이 같은
  // 값을 읽어 액션의 비활성 여부와 사유를 이 컴포넌트와 똑같이 유지하기
  // 때문이다(hook 순서를 조건부 반환이 흔들지 않게 하려는 목적도 같다).
  const hasOpportunity = item?.opportunity_id != null;
  const currentStatus = item?.tracking_status ?? null;
  const currentStatusLabel = currentStatus ?? "미확인";
  const currentStatusVariant = currentStatus === null ? "neutral" : trackingVariant(currentStatus);
  const recorded = record && hasOpportunity && ((currentStatus !== null && currentStatus !== "미선택") || savedDecision !== null);
  const hasForm = Boolean(item) && !isPending && !isError && !(item && isInheritedTracking(item)) && !recorded;
  const ready = hasOpportunity && reason.trim().length > 0 && actorName.trim().length > 0 && !mutation.isPending;
  const saveLabel = record ? (mutation.isPending ? "저장 중…" : problem ? "다시 저장" : "추적 시작") : onStartedForDeepReview ? "추적 시작하고 심층 검토" : "추적 상태 저장";
  const disabledReason = mutation.isPending
    ? "추적 상태 저장 요청을 처리하고 있습니다."
    : !hasOpportunity
      ? "아직 사업기회에 연결되지 않아 추적 결정을 기록할 수 없습니다."
      : requiredDecisionInputReason(reason, actorName);

  useEffect(() => {
    onDecisionStateChange?.({ ready, disabledReason, hasForm, saveLabel });
  }, [disabledReason, hasForm, onDecisionStateChange, ready, saveLabel]);

  if (isPending) {
    return (
      <section className="pre-spec-tracking-decision" aria-labelledby="pre-spec-tracking-decision-title">
        <Heading id="pre-spec-tracking-decision-title">{record ? "추적 결정" : "심층 검토 추적 선택"}</Heading>
        <p role="status">사업기회 연결과 첨부 취득 집계를 불러오는 중입니다.</p>
      </section>
    );
  }

  if (isError || !item) {
    return (
      <section className="pre-spec-tracking-decision" aria-labelledby="pre-spec-tracking-decision-title">
        <Heading id="pre-spec-tracking-decision-title">{record ? "추적 결정" : "심층 검토 추적 선택"}</Heading>
        <EmptyState
          compact
          tone="error"
          title="사업기회 연결 정보를 확인할 수 없습니다."
          description="추적 상태와 첨부 취득 집계를 불러오지 못해 이 화면에서 결정을 기록하지 않습니다."
          action={{ label: "다시 시도", onClick: onRetry }}
        />
      </section>
    );
  }

  const recordHeading = <>
    <div className="ps-record-tracking-heading"><Heading id="pre-spec-tracking-decision-title">추적 결정</Heading><span aria-label="현재 추적 상태"><Badge label={hasOpportunity ? (currentStatus === "계속 추적" ? "추적 중" : currentStatus === "종료" ? "추적 종료" : currentStatusLabel) : "사업기회 미연결"} variant="neutral" /></span></div>
    <div className="ps-record-tracking-reference"><span>사전규격번호</span><strong>{noticeNumber ?? "미확인"}</strong></div>
  </>;
  const stateManagement = <p className="pre-spec-tracking-elsewhere"><strong>보류·추적 종료</strong>는 사업 추적에서 변경합니다.{hasOpportunity ? <Link to={`/opportunities/${item.opportunity_id}`}>사업 추적으로 이동 ↗</Link> : null}</p>;
  if (recorded) {
    return <section className={`pre-spec-tracking-decision is-compact is-record is-recorded${inlineClass}`} aria-labelledby="pre-spec-tracking-decision-title">
      {showRecordHeading ? recordHeading : null}
      <div className="ps-record-saved-decision">
        <Heading>{savedDecision ? "추적 시작을 저장했습니다" : isInheritedTracking(item) ? "발주계획에서 추적 결정을 이어받았습니다" : "추적 결정이 기록된 사업입니다"}</Heading>
        <p>현재 추적 상태 · {currentStatusLabel}</p>
        {inheritedContext}
        {savedDecision ? <dl><div><dt>선택 사유</dt><dd>{savedDecision.reason}</dd></div><div><dt>담당자</dt><dd>{savedDecision.actor}</dd></div></dl> : null}
        <Link to={`/opportunities/${item.opportunity_id}`}>사업 추적에서 상태 관리 ↗</Link>
      </div>
      {stateManagement}
    </section>;
  }

  // 발주계획에서 승계한 건은 이 화면이 추적 상태를 **다시 묻지 않는다**(ADR-0046 결정 6).
  // 승계 사실을 배지로 밝히고 결정 form 자체를 그리지 않는다. 심층 검토가 정상
  // 완료돼도 마찬가지이며, `보류`·`추적 종료`는 사업 추적에서만 사람이 고른다.
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
              발주계획에서 추적 결정을 이어받았습니다.
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
          <Link to={`/opportunities/${item.opportunity_id}`}>사업 추적</Link>에서만 <strong>보류</strong>와 <strong>추적 종료</strong>를 고릅니다. 이 화면의 결정은 심층 검토 실행 승인입니다.
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
          <Heading id="pre-spec-tracking-decision-title">{record ? "추적 결정" : "심층 검토 추적 선택"}</Heading>
          {/* 이 결정이 최종 Go/No-Go가 아니라는 사실은 CLAUDE.md 강제 게이트
              (네 결정은 서로를 대신하지 않는다)라, 밀도를 낮추더라도 액션 옆에서
              지우지 않는다. compact는 설명을 줄일 뿐 이 구분은 남긴다. */}
          <p>
            {compact
              ? "개요 검토 권고를 자동 반영하지 않습니다. 최종 입찰 참여 결정(Go/No-Go)이 아닙니다."
              : "개요 검토 권고를 자동 반영하지 않고 사람이 고르는 추적 결정입니다. 최종 입찰 참여 결정(Go/No-Go)이 아닙니다."}
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
          아직 사업기회에 연결되지 않아 추적 상태를 결정할 수 없습니다. 사업기회 연결이 생긴 뒤 이 화면에서 심층 검토 추적을 선택할 수 있습니다.
        </MutationFeedback>
      ) : null}

      <form
        className={`pre-spec-tracking-form${compact ? " is-compact" : ""}${inlineClass}`}
        id={formId}
        onSubmit={(event) => {
          event.preventDefault();
          if (!ready) return;
          if (status === "종료") {
            setEndConfirm(trackingEndConfirmContent({
              actor: actorName,
              reason,
              target: `사업기회 #${item.opportunity_id}`,
            }));
            return;
          }
          mutation.mutate();
        }}
      >
        {record ? (showIntent ? <div className="ps-record-tracking-intent"><span>저장할 결정</span><h4>추적 시작 <span>→ 계속 추적</span></h4><p>새 문서·입찰공고·정정공고를 계속 확인합니다.</p></div> : null) : (
        <fieldset>
          <legend>결정할 추적 상태</legend>
          <div className="pre-spec-tracking-options">
            {TRACKING_DECISION_STATUSES.map((option, index) => (
              <button
                key={option}
                type="button"
                className={`pre-spec-tracking-option ${status === option ? "is-selected" : ""}`.trim()}
                aria-label={option}
                aria-describedby={`pre-spec-tracking-option-description-${index}`}
                aria-pressed={status === option}
                disabled={!hasOpportunity || mutation.isPending}
                onClick={() => setStatus(option)}
              >
                <strong>{option}</strong>
                <span id={`pre-spec-tracking-option-description-${index}`}>{trackingDescription(option)}</span>
              </button>
            ))}
          </div>
        </fieldset>
        )}

        {hasOpportunity ? (
          <>
            {hasPresets ? (
              <div className="pre-spec-tracking-reason-preset">
                <Selector
                  label="선택 사유"
                  size={record && !inline ? "md" : "sm"}
                  placeholder={record ? "추적을 시작하는 사유를 선택하세요" : "사유를 선택하세요"}
                  isRequired={record}
                  isDisabled={mutation.isPending}
                  hasClear
                  options={[
                    ...(reasonPresets ?? []).map((preset) => ({ value: preset, label: preset })),
                    { value: OTHER_REASON_PRESET, label: "기타 · 직접 입력" },
                  ]}
                  value={presetChoice || null}
                  onChange={(next) => {
                    const chosen = next ?? "";
                    setPresetChoice(chosen);
                    setReason(chosen === OTHER_REASON_PRESET || chosen === "" ? "" : chosen);
                  }}
                />
                {presetChoice === OTHER_REASON_PRESET ? (
                  record ? <label className="pre-spec-tracking-reason"><span>선택 사유 직접 입력 <em>(필수)</em></span><textarea required rows={3} value={reason} disabled={mutation.isPending} onChange={event => setReason(event.target.value)} placeholder="추가로 확인할 내용과 추적이 필요한 이유" /></label> : (
                  <TextInput
                    label="선택 사유 직접 입력"
                    size="sm"
                    value={reason}
                    onChange={setReason}
                    placeholder="이 상태를 고른 사유를 남깁니다."
                  />
                  )
                ) : null}
              </div>
            ) : (
              <label className="pre-spec-tracking-reason">
                <span>사유 <em>(필수)</em></span>
                <textarea
                  required
                  rows={3}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="이 상태를 고른 사유를 남깁니다."
                />
              </label>
            )}
            <ActorField
              label="담당자 이름 (필수)"
              required
              value={actorName}
              onChange={setActorName}
              // 한 줄 배치에서는 라벨 줄이 화면에 보이지 않으므로(시안
              // mockups/artboards/Main.dc.html 198줄) 무슨 칸인지 placeholder가 말한다.
              // 라벨 자체는 문서에 그대로 남는다.
              placeholder={inline ? "담당자 이름 (필수)" : "예: 홍길동"}
              autoComplete="off"
              description={record ? "이 이름을 결정 이력에 기록하며 이 브라우저에 기억합니다." : undefined}
              showRememberNote={!record}
              disabled={record && mutation.isPending}
            />
          </>
        ) : null}

        {feedback ? <MutationFeedback tone={feedback.tone}>{feedback.message}</MutationFeedback> : null}
        {problem ? <MutationFeedback tone="error" problem={problem} /> : null}
        {formId ? null : (
          <div className="pre-spec-tracking-action">
            <button
              className="pre-spec-tracking-save interaction-control"
              type="submit"
              disabled={!ready}
              aria-describedby={disabledReason ? "pre-spec-tracking-save-disabled" : undefined}
            >
              {mutation.isPending ? "저장 중…" : saveLabel}
            </button>
            {disabledReason ? <DisabledReason id="pre-spec-tracking-save-disabled">{disabledReason}</DisabledReason> : null}
          </div>
        )}
        {onStartedForDeepReview ? (
          <p className="pre-spec-tracking-combined-note">
            한 조작이지만 기록은 둘입니다. 추적 시작을 지금 남기고, 심층 검토 실행 승인은 문서 묶음이 준비된 상세에서 이어서 남깁니다.
          </p>
        ) : null}
        {/* spec §3.3에서 `보류·추적 종료는 사업 추적에서 변경` 캡션은 줄 1이 소유하므로
            inline 폼은 같은 문장을 한 번 더 적지 않는다. 승계·기록된 사업의 상태 블록은
            record와 똑같이 이 문장을 그대로 그린다. */}
        {record ? (inline ? null : stateManagement) : (        <p className="pre-spec-tracking-elsewhere">
          <strong>보류</strong>와 <strong>추적 종료</strong>는 이 화면에 없습니다. 사업 추적에서만 사람이 고릅니다.
        </p>)}
      </form>
      <ConfirmDecisionDialog
        confirmLabel={endConfirm?.confirmLabel ?? "종료 상태로 저장"}
        isPending={mutation.isPending}
        onConfirm={() => mutation.mutate(undefined, { onSettled: () => setEndConfirm(null) })}
        onOpenChange={(next) => { if (!next) setEndConfirm(null); }}
        open={endConfirm !== null}
        summary={endConfirm?.summary ?? []}
        title={endConfirm?.title ?? "추적을 종료합니다"}
      />
    </section>
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
    title: "추적 결정 저장 요청을 처리하고 있습니다",
    message: `저장 요청을 이미 보냈습니다. 지금 이동해도 그 요청은 취소되지 않으며 ${owner}에 저장될 수 있습니다. 다른 회사에는 저장되지 않습니다. 저장 결과는 ${owner} 화면에서 다시 확인하십시오.`,
    confirmLabel: "이동하기 (보낸 요청은 계속 처리)",
    cancelLabel: "이 회사에 머물기",
    summary: [
      { label: "보낸 요청", value: `${pendingStatus ?? "추적 결정"} · 처리 중` },
      { label: "사유", value: reason.trim() || "값 없음" },
    ],
  } : {
    blockSpaNavigation: true,
    scope: "pathname",
    title: "이 회사의 추적 결정을 저장하지 않았습니다",
    message: "저장하지 않은 추적 결정 입력이 있습니다. 다른 화면이나 다른 회사로 옮기면 이 입력은 사라지며, 다른 회사에 저장되지 않습니다.",
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
        <p className="cw-caption">아직 사업기회에 연결되지 않아 추적 결정을 기록할 수 없습니다.</p>
      </section>
    );
  }

  const needsNewIntent = versionConflict || resendConflict;
  const ready = base !== null && status !== null && requiredDecisionInputReason(reason, actorName) === null
    && reason.trim().length <= 2000 && !mutation.isPending && !needsNewIntent;
  const disabledReason = mutation.isPending
    ? "저장 요청을 처리하고 있습니다."
    : base === null
      ? "현재 추적 상태를 확인한 뒤 저장할 수 있습니다."
      : versionConflict
        ? "서버 최신값과 초안을 비교한 뒤 ‘최신값 기준으로 다시 저장 준비’를 눌러야 저장합니다."
        : resendConflict
          ? "재전송 충돌을 확인한 뒤 ‘새 저장 요청으로 다시 시작’을 눌러야 저장합니다."
          : status === null
            ? "추적 상태(계속 추적·보류·종료)를 고르십시오."
            : requiredDecisionInputReason(reason, actorName);

  const send = () => {
    if (!ready || base === null || status === null) return;
    const fingerprint = trackingIntentFingerprint(status, reason, base.revision, actorName);
    let requestId: string;
    try {
      requestId = pendingRequest?.fingerprint === fingerprint ? pendingRequest.requestId : generateRequestId();
    } catch {
      setProblem({
        title: "안전한 요청 식별자를 만들 수 없습니다.",
        detail: "이 브라우저에서 암호학적 난수를 쓸 수 없어 저장하지 않았습니다. 다른 브라우저에서 다시 시도하십시오.",
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
          setSavedMessage(`${saved.tracking_status}(으)로 저장했습니다.`);
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
          setProblem(describeCompanyApiError(caught, "추적 결정을 저장하지 못했습니다."));
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
        계속 추적·보류·종료는 이 회사의 사업 추적 결정입니다. 회사 핏(적합성) 판정이나 최종 입찰 참여 결정(Go/No-Go)이 아니며 서로 대신하지 않습니다.
        세 상태 저장은 가상회사 데모 경로에만 있습니다.
      </p>
      {trackingQuery.isPending ? (
        <p role="status">현재 추적 상태를 불러오는 중입니다.</p>
      ) : trackingQuery.isError && !latest ? (
        <EmptyState
          compact
          tone="error"
          title="현재 추적 상태를 확인할 수 없습니다."
          problem={describeCompanyApiError(trackingQuery.error, "추적 상태를 불러오지 못했습니다.")}
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
            다른 사람이 먼저 이 회사의 추적 결정을 바꿨습니다. 초안은 지우지 않았고 서버 값으로 자동 덮어쓰지 않습니다.
            두 값을 비교한 뒤 최신값을 기준으로 다시 저장할지 정하십시오.
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
              <p role="status">서버 최신값을 불러오는 중입니다.</p>
            ) : (
              <p className="cw-caption">서버 최신값을 확인하지 못했습니다. 다시 불러온 뒤 비교하십시오.</p>
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
              같은 요청 식별자로 다른 내용을 보낸 재전송 충돌입니다. 앞선 요청이 이미 저장됐을 수 있으니 위의 현재 상태를 확인하십시오.
              이 요청 식별자는 다시 쓰지 않습니다. 저장하려면 새 저장 요청으로 다시 시작하십시오.
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
