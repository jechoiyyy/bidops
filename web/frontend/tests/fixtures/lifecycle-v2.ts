import type {
  BidDeltaDecisionQueueItem,
  OpportunityDeepReviewsResponse,
  OpportunityTrackingDecisionsResponse,
  PreSpecListItem,
  WorkloadResponse,
} from "../../src/lib/types";

/** Synthetic wire projections. Production screens must not reconstruct these decisions. */
export const clickReadyUnlinkedPreSpec: PreSpecListItem = {
  notice_pk: 993, pre_spec_no: "PRE-993", title: "독립 수집된 심층 검토 클릭 대기 사전규격",
  agency: "합성 발주기관", published_at: "2026-09-01T00:00:00Z", deadline_at: null,
  budget: null, sw_business_status: "N", business_division: "일반용역",
  origin: null, opportunity_id: null, tracking_status: null, kept_by_tracking: false,
  document: { attachments: 1, 완료: 1, 대기: 0, 진행: 0, 차단: 0, 실패: 0 },
  overview_review_status: "completed", grade: "우선 검토", grade_source: "screening_judgment",
  auto_preparation_status: "deep_review_ready_for_click", auto_preparation_reason: "not_sw_business",
  latest_deep_review_id: null, first_observed_at: "2026-09-16T00:00:00Z", last_observed_at: "2026-09-16T00:00:00Z",
  next_action: "open_deep_review",
};

const queueBase = {
  agency: "합성 발주기관", tracking_status: "계속 추적", first_registered_stage: "pre_spec",
  recheck_signal: false, comparison_count: 0,
};
export const decisionQueueItems: BidDeltaDecisionQueueItem[] = [
  { ...queueBase, opportunity_id: 501, title: "최종 결정 대기 사업", bid_notice_external_id: "BID-501", latest_final_decision: null, decision_currentness: "unknown" },
  { ...queueBase, opportunity_id: 502, title: "새 공고 이후 재결정 대기 사업", bid_notice_external_id: "BID-502", comparison_count: 2, latest_final_decision: { decision: "go", decided_at: "2026-08-30T00:00:00Z", claimed_name: "합성 담당자" }, decision_currentness: "stale" },
  { ...queueBase, opportunity_id: 503, title: "현재 최종 결정 사업", bid_notice_external_id: "BID-503", comparison_count: 1, latest_final_decision: { decision: "no_go", decided_at: "2026-08-31T00:00:00Z", claimed_name: "합성 담당자" }, decision_currentness: "current" },
  { ...queueBase, opportunity_id: 504, title: "기결정 최신 여부 확인 대기 사업", bid_notice_external_id: "BID-504", comparison_count: 1, latest_final_decision: { decision: "go", decided_at: "2026-08-29T00:00:00Z", claimed_name: "합성 담당자" }, decision_currentness: "unknown" },
  { ...queueBase, opportunity_id: 505, title: "입찰공고 미연결 추적 사업", bid_notice_external_id: null, latest_final_decision: null, decision_currentness: "unknown" },
];

export const opportunityTrackingHistory: OpportunityTrackingDecisionsResponse = {
  opportunity_id: 202,
  items: [
    { decided_at: "2026-08-20T09:00:00Z", tracking_status: "종료", previous_tracking_status: "계속 추적", reason: "현재 범위 검토 완료", claimed_name: "합성 담당자", audit_event_id: "f1000000-0000-4000-8000-000000000002", cleared_recheck_signal: false },
    { decided_at: "2026-08-19T09:00:00Z", tracking_status: "계속 추적", previous_tracking_status: null, reason: null, claimed_name: null, audit_event_id: "f1000000-0000-4000-8000-000000000001", cleared_recheck_signal: false },
  ],
};
export const opportunityDeepReviews: OpportunityDeepReviewsResponse = {
  opportunity_id: 202,
  items: [
    { deep_review_id: "fixture-review", notice_id: 61, notice_title: "합성 사전규격", status: "completed", quality_status: "unmeasured_reference", created_at: "2026-08-26T00:00:00Z", current_attempt_status: "completed", latest_final_opinion: { value: "조건부 추진 검토", decided_at: "2026-08-27T00:00:00Z" } },
    { deep_review_id: "fixture-review-older", notice_id: 61, notice_title: null, status: "failed", quality_status: null, created_at: "2026-08-25T00:00:00Z", current_attempt_status: "failed", latest_final_opinion: null },
  ],
};
export const unavailableWorkload: WorkloadResponse = {
  generated_at: "2026-09-01T09:00:00Z",
  items: [
    { key: "order_plan_pending", count: null, unavailable_reason: "provider_absent" },
    { key: "pre_spec_deep_review_ready", count: null, unavailable_reason: "provider_absent" },
    { key: "tracking_action_required", count: 0, unavailable_reason: null },
    { key: "bid_final_decision_pending", count: null, unavailable_reason: "provider_absent" },
  ],
};


/** All providers present; all four queues were measured and are empty. */
export const emptyWorkload: WorkloadResponse = {
  generated_at: "2026-09-01T09:00:00Z",
  items: [
    { key: "order_plan_pending", count: 0, unavailable_reason: null },
    { key: "pre_spec_deep_review_ready", count: 0, unavailable_reason: null },
    { key: "tracking_action_required", count: 0, unavailable_reason: null },
    { key: "bid_final_decision_pending", count: 0, unavailable_reason: null },
  ],
};
