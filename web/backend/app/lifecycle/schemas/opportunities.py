"""REST contracts for cumulative business-opportunity tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, Field, StrictInt, field_validator, model_validator

from ...core.schema_base import AwareDateTime, RuntimeContractModel


# ``신규 입찰공고``는 입찰공고로 처음 등록된 미선택 사업이다. ``미결정``은 그 밖의
# 미선택 사업이며 집계 전용이라 목록 필터로는 받지 않는다(spec §7.2).
OpportunitySection = Literal["조치 필요", "추적 중", "보류", "추적 종료", "신규 입찰공고"]
OpportunitySectionCountKey = Literal[
    "조치 필요", "추적 중", "보류", "추적 종료", "신규 입찰공고", "미결정"
]
#: 조치 필요 사유 (spec §7.1). 모든 행에 계산하며 구역과 별개의 축이다.
OpportunityActionReason = Literal[
    "new_link", "candidate_pending", "merge_confirmation", "blocking_item", "hold_overdue"
]
#: 보류 재검토 기한 필터 (spec §7.3). ``attention``은 ``overdue``와 ``due_soon``의 합집합이다.
OpportunityHoldReview = Literal["overdue", "due_soon", "attention"]
#: 찾아보기 대상 (spec §4.3).
OpportunitySearchTarget = Literal["pre_spec", "bid_notice"]

OpportunityTrackingStatus = Literal["미선택", "계속 추적", "보류", "종료"]
OpportunityFirstRegisteredStage = Literal["order_plan", "pre_spec", "bid_notice"]
OpportunityLinkStage = Literal["order_plan", "notice"]
OpportunityLinkType = Literal["official", "candidate"]
# ``사람 확인 병합``은 병합으로 끝난 후보 수락(비소유 행), ``merge_confirmation``은
# 사람 상태가 있는 사업기회끼리 자동 병합을 거부했을 때 만든 병합 확인 후보다(spec §3).
OpportunityLinkStatus = Literal[
    "확정", "후보 확인 대기", "사람 확인 완료", "검색 미확인", "사람 확인 병합"
]
OpportunitySearchStrategy = Literal[
    "full",
    "breaking_split",
    "normalized",
    "longest_fragment",
    "prefix12",
    "merge_confirmation",
]


class OpportunityLinkView(RuntimeContractModel):
    """Safe projection of one lifecycle link and, when present, its target."""

    id: int = Field(ge=1)
    stage: OpportunityLinkStage
    link_type: OpportunityLinkType
    status: OpportunityLinkStatus
    search_strategy: OpportunitySearchStrategy | None = None
    attempted_strategies: list[OpportunitySearchStrategy] = Field(default_factory=list)
    agency_match: bool | None = None
    last_searched_at: AwareDateTime | None = None
    evidence_external_no: str | None = None
    evidence_bid_no: str | None = None
    # ``검색 미확인`` 행이 어느 찾아보기 대상의 기록인지(spec §3.3·§4.3). 다른 행은 ``None``이다.
    search_target_kind: OpportunitySearchTarget | None = None
    human_decision: Literal["accepted", "rejected"] | None = None
    reviewer_name: str | None = None
    reviewed_at: AwareDateTime | None = None
    review_reason: str | None = None

    # The following fields are a deliberately small, safe record projection.
    # They contain identifiers/titles only; raw_source, URLs, filesystem
    # references, and object-store metadata are not part of this contract.
    record_type: str | None = None
    record_id: int | None = Field(default=None, ge=1)
    notice_id: int | None = Field(default=None, ge=1)
    order_plan_id: int | None = Field(default=None, ge=1)
    source_type: str | None = None
    title: str | None = None
    agency: str | None = None
    external_id: str | None = None
    record_external_id: str | None = None


class OpportunityStateView(RuntimeContractModel):
    id: int = Field(ge=1)
    tracking_status: OpportunityTrackingStatus
    tracking_reason: str | None = None
    tracking_selected_by: str | None = None
    tracking_selected_at: AwareDateTime | None = None
    section: OpportunitySection | None = None
    pending_candidate_link_count: int = Field(default=0, ge=0)
    open_blocking_item_count: int = Field(default=0, ge=0)
    recheck_signal: bool
    recheck_signal_at: AwareDateTime | None = None
    recheck_signal_link_id: int | None = Field(default=None, ge=1)
    first_registered_stage: OpportunityFirstRegisteredStage
    merged_into_opportunity_id: int | None = Field(default=None, ge=1)
    merged_at: AwareDateTime | None = None
    merge_reason: str | None = None
    action_reasons: list[OpportunityActionReason] = Field(default_factory=list)
    # ``보류``일 때만 ``tracking_selected_at + 14일``이다. 저장하지 않는 파생값이다.
    hold_review_due_at: AwareDateTime | None = None


class OpportunityListItem(OpportunityStateView):
    """Opportunity row with link/record summaries for the list screen."""

    links: list[OpportunityLinkView] = Field(default_factory=list)


class OpportunityDetailResponse(OpportunityStateView):
    """Single opportunity with every stored link, including search failures."""

    links: list[OpportunityLinkView] = Field(default_factory=list)


class OpportunityTrackingDecisionView(RuntimeContractModel):
    decided_at: AwareDateTime
    tracking_status: str
    previous_tracking_status: str | None = None
    reason: str | None = None
    claimed_name: str | None = None
    audit_event_id: UUID
    cleared_recheck_signal: bool


OpportunityRecheckEventKind = Literal["created", "acknowledged", "cleared_by_decision"]


class OpportunityRecheckEventView(RuntimeContractModel):
    """One recheck-signal event projected from the audit trail (spec §6.3).

    ``note_present`` says only whether an acknowledgement carried a note; the
    note text is never stored.
    """

    kind: OpportunityRecheckEventKind
    link_id: int | None = Field(default=None, ge=1)
    actor_kind: Literal["human", "system"]
    claimed_name: str | None = None
    created_at: AwareDateTime
    note_present: bool


class OpportunityTrackingDecisionsResponse(RuntimeContractModel):
    opportunity_id: int = Field(ge=1)
    items: list[OpportunityTrackingDecisionView] = Field(default_factory=list)
    recheck_events: list[OpportunityRecheckEventView] = Field(default_factory=list)


class OpportunityListResponse(RuntimeContractModel):
    section_counts: dict[OpportunitySectionCountKey, int]
    # 활성 ``reason`` 필터만 뺀 조건으로 센 사유별 건수. 한 행은 여러 사유에 들어간다.
    action_reason_counts: dict[OpportunityActionReason, int]
    items: list[OpportunityListItem] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class TrackingStatusUpdateRequest(RuntimeContractModel):
    """Human tracking choice; actor identity comes only from request headers."""

    tracking_status: str = Field(
        validation_alias=AliasChoices("tracking_status", "status"),
        min_length=1,
    )
    reason: str = Field(
        validation_alias=AliasChoices("reason", "tracking_reason"),
        min_length=1,
    )


class RecheckAcknowledgementRequest(RuntimeContractModel):
    """Acknowledge the current recheck signal without a new tracking decision.

    ``expected_link_id`` is the evidence link the person looked at; a signal
    that moved on to another link is not cleared.  Actor identity comes only
    from request headers.
    """

    expected_link_id: StrictInt = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


class CandidateDecisionRequest(RuntimeContractModel):
    """Human decision for one pending candidate lifecycle link."""

    decision: Literal["accepted", "rejected"]
    reason: str = Field(min_length=1)


class OpportunitySearchRequest(RuntimeContractModel):
    """Server-side name search over the archived collection index (spec §4.3)."""

    target: OpportunitySearchTarget


class OpportunitySearchResponse(RuntimeContractModel):
    """One synchronous search.

    ``search_unconfirmed`` means the search could not confirm a record; it is
    not a claim that no record exists (ADR-0025).
    """

    searched_at: AwareDateTime
    target: OpportunitySearchTarget
    attempted_strategies: list[OpportunitySearchStrategy] = Field(default_factory=list)
    candidates: list[OpportunityLinkView] = Field(default_factory=list)
    search_unconfirmed: bool


OpportunitySort = Literal[
    "created_at", "tracking_status", "first_registered_stage", "hold_review_due_at"
]

# The bulk wire contracts deliberately have their own versioned vocabulary.
# ``OpportunityTrackingStatus`` includes the reset state used by the single
# PATCH, while a bulk start can only create the one human choice below.
OrderPlanBulkExcludedStatus = Literal["계속 추적", "보류", "종료"]
OrderPlanBulkEligibility = Literal["eligible", "excluded", "failed"]
OrderPlanBulkOutcome = Literal["succeeded", "excluded", "failed"]
OrderPlanBulkFailureCode = Literal[
    "order_plan_not_found",
    "owning_opportunity_missing",
    "owner_changed",
    "ownership_conflict",
    "processing_failed",
    "temporarily_unavailable",
]


#: 일괄 종료 한 요청이 받는 발주계획 수 상한.  PoC 값이며 되돌리기가 단건뿐인
#: 작업의 오조작 폭을 제한한다.  v1 계약인 bulk-start에는 상한을 더하지 않는다.
ORDER_PLAN_BULK_END_MAX_SELECTION = 200


def _positive_plan_ids(value: list[int]) -> list[int]:
    """Require a JSON array of positive integers, but retain duplicates.

    Deduplication is a server-side operation because the request hash and the
    response identity are based on the normalized set.  Keeping duplicate
    values in this DTO lets callers receive a normal validation error only for
    malformed values, never for a harmless repeated checkbox selection.
    """

    if not value:
        raise ValueError("order_plan_ids must not be empty")
    if any(item <= 0 for item in value):
        raise ValueError("order_plan_ids must contain positive integers")
    return value


class OrderPlanBulkPreviewRequest(RuntimeContractModel):
    """Read-only preview input for a selected set of order plans."""

    schema_version: Literal["order-plan-bulk-preview-request.v1"]
    order_plan_ids: list[StrictInt] = Field(min_length=1)

    _validate_plan_ids = field_validator("order_plan_ids")(_positive_plan_ids)


def _nonblank_reason(value: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError("reason must not be blank")
    return clean


class OrderPlanBulkStartRequest(RuntimeContractModel):
    """A versioned, deterministic bulk tracking-start request."""

    schema_version: Literal["order-plan-bulk-start-request.v1"]
    request_id: UUID
    order_plan_ids: list[StrictInt] = Field(min_length=1)
    reason: str = Field(min_length=1)

    _validate_plan_ids = field_validator("order_plan_ids")(_positive_plan_ids)
    _trim_reason = field_validator("reason")(_nonblank_reason)


class OrderPlanBulkEndRequest(RuntimeContractModel):
    """A versioned, deterministic bulk tracking-end request.

    The wire has no status field: the target is the fixed ``종료``.  Unlike the
    v1 start contract this request caps its selection, because a bulk end has
    no bulk undo.
    """

    schema_version: Literal["order-plan-bulk-end-request.v1"]
    request_id: UUID
    order_plan_ids: list[StrictInt] = Field(
        min_length=1, max_length=ORDER_PLAN_BULK_END_MAX_SELECTION
    )
    reason: str = Field(min_length=1)

    _validate_plan_ids = field_validator("order_plan_ids")(_positive_plan_ids)
    _trim_reason = field_validator("reason")(_nonblank_reason)


class OrderPlanBulkStatusCount(RuntimeContractModel):
    """Plan and unique-owner counts for one excluded tracking status."""

    plan_count: StrictInt = Field(ge=0)
    owner_count: StrictInt = Field(ge=0)


class OrderPlanBulkPreviewItem(RuntimeContractModel):
    order_plan_id: int = Field(gt=0, strict=True)
    opportunity_id: int | None = Field(..., gt=0, strict=True)
    tracking_status: OpportunityTrackingStatus | None = Field(...)
    eligibility: OrderPlanBulkEligibility
    code: OrderPlanBulkFailureCode | None = Field(...)


class OrderPlanBulkPreviewResponse(RuntimeContractModel):
    schema_version: Literal["order-plan-bulk-preview-response.v1"]
    selected_plan_count: StrictInt = Field(ge=1)
    unique_owner_count: StrictInt = Field(ge=0)
    eligible_plan_count: StrictInt = Field(ge=0)
    eligible_owner_count: StrictInt = Field(ge=0)
    excluded_by_status: dict[OrderPlanBulkExcludedStatus, OrderPlanBulkStatusCount]
    failure_plan_count: StrictInt = Field(ge=0)
    items: list[OrderPlanBulkPreviewItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_counts(self) -> "OrderPlanBulkPreviewResponse":
        if set(self.excluded_by_status) != {"계속 추적", "보류", "종료"}:
            raise ValueError("excluded_by_status must contain all excluded statuses")
        if len(self.items) != self.selected_plan_count:
            raise ValueError("selected_plan_count must match items")
        if len({item.order_plan_id for item in self.items}) != self.selected_plan_count:
            raise ValueError("preview items must contain unique order plans")

        eligible = [item for item in self.items if item.eligibility == "eligible"]
        excluded = [item for item in self.items if item.eligibility == "excluded"]
        failed = [item for item in self.items if item.eligibility == "failed"]
        if len(eligible) != self.eligible_plan_count:
            raise ValueError("eligible_plan_count must match items")
        if len(failed) != self.failure_plan_count:
            raise ValueError("failure_plan_count must match items")
        if len({item.opportunity_id for item in eligible if item.opportunity_id is not None}) != self.eligible_owner_count:
            raise ValueError("eligible_owner_count must match items")
        if self.unique_owner_count != len(
            {item.opportunity_id for item in self.items if item.opportunity_id is not None}
        ):
            raise ValueError("unique_owner_count must match items")
        if any(
            item.tracking_status != "미선택" or item.code is not None
            for item in eligible
        ):
            raise ValueError("eligible items must be unselected and have no code")
        if any(item.opportunity_id is None for item in eligible):
            raise ValueError("eligible items must identify their owner")
        if any(
            item.tracking_status not in {"계속 추적", "보류", "종료"}
            or item.code is not None
            for item in excluded
        ):
            raise ValueError("excluded items must expose their current status")
        if any(item.opportunity_id is None for item in excluded):
            raise ValueError("excluded items must identify their owner")
        if any(item.code is None for item in failed):
            raise ValueError("failed items must expose a safe code")

        for status, count in self.excluded_by_status.items():
            matching = [
                item
                for item in excluded
                if item.tracking_status == status
            ]
            if count.plan_count != len(matching):
                raise ValueError("excluded plan count must match items")
            if count.owner_count != len(
                {item.opportunity_id for item in matching if item.opportunity_id is not None}
            ):
                raise ValueError("excluded owner count must match items")
        return self


class OrderPlanBulkStartItem(RuntimeContractModel):
    order_plan_id: int = Field(gt=0, strict=True)
    opportunity_id: int | None = Field(..., gt=0, strict=True)
    outcome: OrderPlanBulkOutcome
    status_at_decision: OpportunityTrackingStatus | None = Field(...)
    code: OrderPlanBulkFailureCode | None = Field(...)
    audit_event_id: UUID | None = Field(...)


class OrderPlanBulkSummary(RuntimeContractModel):
    selected_plan_count: StrictInt = Field(ge=1)
    unique_owner_count: StrictInt = Field(ge=0)
    succeeded_plan_count: StrictInt = Field(ge=0)
    succeeded_owner_count: StrictInt = Field(ge=0)
    excluded_plan_count: StrictInt = Field(ge=0)
    excluded_by_status: dict[OrderPlanBulkExcludedStatus, OrderPlanBulkStatusCount]
    failed_plan_count: StrictInt = Field(ge=0)


def _validate_bulk_receipt(model: Any, *, succeeded_status: str) -> Any:
    """Check one bulk receipt against its own summary and target status.

    Start and end share every field name, failure code and fan-out rule; only
    the status a successful owner ends up in differs.  Keeping one checker
    means a new operation cannot quietly lose a receipt invariant.
    """

    summary = model.summary
    items = model.items
    if set(summary.excluded_by_status) != {"계속 추적", "보류", "종료"}:
        raise ValueError("excluded_by_status must contain all excluded statuses")
    if len(items) != summary.selected_plan_count:
        raise ValueError("selected_plan_count must match items")
    if len({item.order_plan_id for item in items}) != summary.selected_plan_count:
        raise ValueError("receipt items must contain unique order plans")

    by_outcome = {
        outcome: [item for item in items if item.outcome == outcome]
        for outcome in ("succeeded", "excluded", "failed")
    }
    if len(by_outcome["succeeded"]) != summary.succeeded_plan_count:
        raise ValueError("succeeded_plan_count must match items")
    if len(by_outcome["excluded"]) != summary.excluded_plan_count:
        raise ValueError("excluded_plan_count must match items")
    if len(by_outcome["failed"]) != summary.failed_plan_count:
        raise ValueError("failed_plan_count must match items")
    if summary.selected_plan_count != (
        summary.succeeded_plan_count
        + summary.excluded_plan_count
        + summary.failed_plan_count
    ):
        raise ValueError("receipt outcome counts must add up")
    if summary.unique_owner_count != len(
        {item.opportunity_id for item in items if item.opportunity_id is not None}
    ):
        raise ValueError("unique_owner_count must match items")
    if summary.succeeded_owner_count != len(
        {
            item.opportunity_id
            for item in by_outcome["succeeded"]
            if item.opportunity_id is not None
        }
    ):
        raise ValueError("succeeded_owner_count must match items")

    # A shared owner is fanned out to each selected plan.  Every fan-out
    # row must carry the same result and audit ID, never a second decision.
    owner_results: dict[int, tuple[str, str | None, str | None, UUID | None]] = {}
    for item in items:
        if item.opportunity_id is None:
            continue
        value = (
            item.outcome,
            item.status_at_decision,
            item.code,
            item.audit_event_id,
        )
        previous = owner_results.setdefault(item.opportunity_id, value)
        if previous != value:
            raise ValueError("all plans for one owner must share one result")

    for item in by_outcome["succeeded"]:
        if (
            item.opportunity_id is None
            or item.status_at_decision != succeeded_status
            or item.code is not None
            or item.audit_event_id is None
        ):
            raise ValueError("succeeded items must carry their tracking audit")
    for item in by_outcome["excluded"]:
        if (
            item.opportunity_id is None
            or item.status_at_decision not in {"계속 추적", "보류", "종료"}
            or item.code is not None
            or item.audit_event_id is not None
        ):
            raise ValueError("excluded items must preserve their status")
    for item in by_outcome["failed"]:
        if item.code is None or item.audit_event_id is not None:
            raise ValueError("failed items must expose a safe code without an audit")

    for status, count in summary.excluded_by_status.items():
        matching = [
            item
            for item in by_outcome["excluded"]
            if item.status_at_decision == status
        ]
        if count.plan_count != len(matching):
            raise ValueError("excluded plan count must match items")
        if count.owner_count != len(
            {item.opportunity_id for item in matching if item.opportunity_id is not None}
        ):
            raise ValueError("excluded owner count must match items")
    return model


class OrderPlanBulkStartResponse(RuntimeContractModel):
    """Final durable receipt returned by bulk start and exact replay."""

    schema_version: Literal["order-plan-bulk-start-response.v1"]
    request_id: UUID
    completed_at: AwareDateTime
    items: list[OrderPlanBulkStartItem] = Field(min_length=1)
    summary: OrderPlanBulkSummary

    @model_validator(mode="after")
    def _validate_receipt(self) -> "OrderPlanBulkStartResponse":
        return _validate_bulk_receipt(self, succeeded_status="계속 추적")


class OrderPlanBulkEndResponse(RuntimeContractModel):
    """Final durable receipt returned by bulk end and exact replay.

    Field names, failure codes and the fan-out rule are the bulk-start ones;
    a succeeded owner is in ``종료`` instead of ``계속 추적``.
    """

    schema_version: Literal["order-plan-bulk-end-response.v1"]
    request_id: UUID
    completed_at: AwareDateTime
    items: list[OrderPlanBulkStartItem] = Field(min_length=1)
    summary: OrderPlanBulkSummary

    @model_validator(mode="after")
    def _validate_receipt(self) -> "OrderPlanBulkEndResponse":
        return _validate_bulk_receipt(self, succeeded_status="종료")


__all__ = [
    "CandidateDecisionRequest",
    "OpportunityActionReason",
    "OpportunityHoldReview",
    "OpportunitySearchRequest",
    "OpportunitySearchResponse",
    "OpportunitySearchTarget",
    "OpportunityDetailResponse",
    "OpportunityFirstRegisteredStage",
    "OpportunityLinkView",
    "OpportunityListItem",
    "OpportunityListResponse",
    "OpportunityLinkStage",
    "OpportunityRecheckEventKind",
    "OpportunityRecheckEventView",
    "OpportunityLinkStatus",
    "OpportunityLinkType",
    "OpportunitySearchStrategy",
    "OpportunitySort",
    "OpportunitySection",
    "OpportunityTrackingDecisionView",
    "OpportunityTrackingDecisionsResponse",
    "OpportunityStateView",
    "OpportunityTrackingStatus",
    "ORDER_PLAN_BULK_END_MAX_SELECTION",
    "OrderPlanBulkEndRequest",
    "OrderPlanBulkEndResponse",
    "OrderPlanBulkExcludedStatus",
    "OrderPlanBulkEligibility",
    "OrderPlanBulkFailureCode",
    "OrderPlanBulkOutcome",
    "OrderPlanBulkStatusCount",
    "OrderPlanBulkPreviewItem",
    "OrderPlanBulkPreviewRequest",
    "OrderPlanBulkPreviewResponse",
    "OrderPlanBulkStartItem",
    "OrderPlanBulkStartRequest",
    "OrderPlanBulkStartResponse",
    "OrderPlanBulkSummary",
    "RecheckAcknowledgementRequest",
    "TrackingStatusUpdateRequest",
]
