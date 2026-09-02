import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Badge } from "../common/Badge";
import { ActorField } from "../common/ActorField";
import { DisabledReason } from "../common/DisabledReason";
import { EmptyState } from "../common/EmptyState";
import { MutationFeedback } from "../common/MutationFeedback";
import { api } from "../../lib/api";
import { trackingDescription, trackingVariant } from "../../lib/opportunity";
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

export const TRACKING_DECISION_STATUSES: OpportunityTrackingStatus[] = ["계속 추적", "보류", "종료"];

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
      <p>첨부 취득 상태는 같은 notice_pk의 누적 사전규격 projection에서 확인했습니다.</p>
    </section>
  );
}

export interface TrackingDecisionControlProps {
  item: PreSpecListItem | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  /** 저장에 성공하면 호출자가 자신의 query cache를 갱신한다. 화면마다
   * queryKey 모양이 다르므로 캐시 반영은 이 컴포넌트가 대신하지 않는다. */
  onSaved: (saved: OpportunityDetailResponse) => void;
  /** 상세 화면과 목록 화면에서 heading level이 다를 수 있어 호출자가 정한다. */
  headingLevel?: "h3" | "h4";
}

export function TrackingDecisionControl({
  item,
  isPending,
  isError,
  onRetry,
  onSaved,
  headingLevel = "h3",
}: TrackingDecisionControlProps) {
  const Heading = headingLevel;
  const [status, setStatus] = useState<OpportunityTrackingStatus>(item?.tracking_status ?? "미선택");
  const [reason, setReason] = useState("");
  const [actorName, setActorName] = useState("");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    if (item) setStatus(item.tracking_status ?? "미선택");
  }, [item?.notice_pk]);

  const mutation = useMutation({
    mutationFn: () => api.updateOpportunityTrackingStatus(
      item?.opportunity_id as number,
      { tracking_status: status, reason: reason.trim() },
      actorName,
    ),
    onSuccess: (saved) => {
      if (!item) return;
      setStatus(saved.tracking_status);
      setReason("");
      setActorName("");
      setFeedback({ tone: "success", message: "심층 검토 추적 상태를 저장했습니다." });
      onSaved(saved);
    },
    onError: () => {
      // Server response bodies can contain unsafe provider or validation detail.
      // This screen exposes only a stable, user-safe mutation message.
      setFeedback({ tone: "error", message: "심층 검토 추적 상태를 저장하지 못했습니다." });
    },
  });

  if (isPending) {
    return (
      <section className="pre-spec-tracking-decision" aria-labelledby="pre-spec-tracking-decision-title">
        <Heading id="pre-spec-tracking-decision-title">심층 검토 추적 선택</Heading>
        <p role="status">사업기회 연결과 첨부 취득 집계를 불러오는 중입니다.</p>
      </section>
    );
  }

  if (isError || !item) {
    return (
      <section className="pre-spec-tracking-decision" aria-labelledby="pre-spec-tracking-decision-title">
        <Heading id="pre-spec-tracking-decision-title">심층 검토 추적 선택</Heading>
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

  const hasOpportunity = item.opportunity_id !== null;
  const currentStatus = item.tracking_status ?? "미선택";
  const ready = hasOpportunity && reason.trim().length > 0 && actorName.trim().length > 0;
  const disabledReason = mutation.isPending
    ? "추적 상태 저장 요청을 처리하고 있습니다."
    : !hasOpportunity
      ? "아직 사업기회에 연결되지 않아 추적 결정을 기록할 수 없습니다."
      : !reason.trim()
        ? "추적 결정을 저장하려면 사유를 입력하십시오."
        : !actorName.trim()
          ? "추적 결정을 저장하려면 담당자 이름을 입력하십시오."
          : null;

  return (
    <section className="pre-spec-tracking-decision" aria-labelledby="pre-spec-tracking-decision-title">
      <div className="pre-spec-tracking-decision-header">
        <div>
          <span className="pre-spec-tracking-kicker">HUMAN TRACKING DECISION</span>
          <Heading id="pre-spec-tracking-decision-title">심층 검토 추적 선택</Heading>
          <p>개요 검토 권고를 자동 반영하지 않고 사람이 고르는 추적 결정입니다. 최종 입찰 참여 결정(Go/No-Go)이 아닙니다.</p>
        </div>
        <div className="pre-spec-tracking-current" aria-label="현재 추적 상태">
          <span>현재 추적 상태</span>
          {hasOpportunity
            ? <Badge label={currentStatus} variant={trackingVariant(currentStatus)} />
            : <strong>사업기회 미연결</strong>}
        </div>
      </div>

      <PreSpecDocumentSummary item={item} />

      {!hasOpportunity ? (
        <MutationFeedback tone="warning">
          아직 사업기회에 연결되지 않아 추적 상태를 결정할 수 없습니다. 사업기회 연결이 생긴 뒤 이 화면에서 심층 검토 추적을 선택할 수 있습니다.
        </MutationFeedback>
      ) : null}

      <form
        className="pre-spec-tracking-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) mutation.mutate();
        }}
      >
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

        {hasOpportunity ? (
          <>
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
            <ActorField
              label="담당자 이름 (필수)"
              required
              value={actorName}
              onChange={setActorName}
              placeholder="예: 홍길동"
              autoComplete="off"
            />
          </>
        ) : null}

        {feedback ? <MutationFeedback tone={feedback.tone}>{feedback.message}</MutationFeedback> : null}
        <button
          className="pre-spec-tracking-save interaction-control"
          type="submit"
          disabled={!ready || mutation.isPending}
          aria-describedby={disabledReason ? "pre-spec-tracking-save-disabled" : undefined}
        >
          {mutation.isPending ? "저장 중…" : "추적 상태 저장"}
        </button>
        {disabledReason ? <DisabledReason id="pre-spec-tracking-save-disabled">{disabledReason}</DisabledReason> : null}
      </form>
    </section>
  );
}
