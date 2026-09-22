import type { Route, Page } from "@playwright/test";
import fixtures from "./fixtures/api.json" with { type: "json" };
import { getVisualResponse } from "./fixtures/visual-api";

import type {
  BidDeltaDecisionQueueItem, OpportunityListItem, OpportunitySectionCounts,
  OpportunityRecheckEventView, OpportunityTrackingDecisionItem, OpportunityTrackingStatus,
  OrderPlanListItem, OrderPlanListScope, OrderPlanScreeningExecutionSummary, OrderPlanScreeningErrorCode,
  OrderPlanTracking, OrderPlanBulkPreviewResponse, OrderPlanBulkStartResponse, OrderPlanBulkEndResponse,
  OverviewEnvelope, OverviewRun, PreSpecListItem, PreSpecOrderPlanCandidatesResponse,
  RunSummary, WorkloadKey, WorkloadResponse,
} from "../src/lib/types";
import { searchKey, searchMatches } from "../src/lib/search";
import { clickReadyUnlinkedPreSpec, decisionQueueItems, opportunityDeepReviews, opportunityTrackingHistory } from "./fixtures/lifecycle-v2";

const opportunityFixtures = new WeakMap<Page, OpportunityListItem[]>();
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * 발주계획 일괄 추적(시작·종료) mock이 성공 항목에 남기는 `tracking_status` 재정의다.
 * `mockOrderPlans`의 GET 목록은 이 페이지 범위 저장소를 먼저 본다 — 두 mock 함수가
 * 서로 다른 클로저에 있어도 같은 `page`에 걸면 종료 뒤 목록이 실제로 갱신된 것처럼
 * 보인다. bulk 계약이 반환한 `status_at_decision`만 그대로 옮기며 값을 지어내지 않는다.
 */
const bulkTrackingOverrides = new WeakMap<Page, Map<number, { tracking_status: string; opportunity_id: number }>>();
function bulkOverrideStore(page: Page): Map<number, { tracking_status: string; opportunity_id: number }> {
  let store = bulkTrackingOverrides.get(page);
  if (!store) { store = new Map(); bulkTrackingOverrides.set(page, store); }
  return store;
}
/** bulk-start·bulk-end 응답의 성공 항목을 위 저장소에 반영한다. */
function applyBulkTrackingOverrides(page: Page, response: unknown): void {
  if (!response || typeof response !== "object" || !("items" in response)) return;
  const items = (response as { items: unknown }).items;
  if (!Array.isArray(items)) return;
  const store = bulkOverrideStore(page);
  for (const raw of items) {
    if (!raw || typeof raw !== "object") continue;
    const item = raw as { order_plan_id?: unknown; opportunity_id?: unknown; outcome?: unknown; status_at_decision?: unknown };
    if (item.outcome !== "succeeded" || typeof item.order_plan_id !== "number"
      || typeof item.opportunity_id !== "number" || typeof item.status_at_decision !== "string") continue;
    store.set(item.order_plan_id, { tracking_status: item.status_at_decision, opportunity_id: item.opportunity_id });
  }
}
const workloadProviders = new WeakMap<Page, Map<WorkloadKey, () => { count: number | null; unavailable_reason: string | null }>>();
function workloadProvider(page: Page, key: WorkloadKey, provider: () => { count: number | null; unavailable_reason: string | null }) {
  let providers = workloadProviders.get(page);
  if (!providers) { providers = new Map(); workloadProviders.set(page, providers); }
  providers.set(key, provider);
}
function workloadResponse(page: Page): WorkloadResponse {
  const keys: WorkloadKey[] = ["order_plan_pending", "pre_spec_deep_review_ready", "tracking_action_required", "tracking_hold_review_due", "bid_final_decision_pending"];
  return { generated_at: "2026-09-01T09:00:00Z", items: keys.map((key) => ({ key, ...(workloadProviders.get(page)?.get(key)?.() ?? { count: null, unavailable_reason: "provider_absent" }) })) };
}
function fixtureActor(headers: Record<string, string>): string {
  const actor = headers["x-bidops-actor-name"] ?? "";
  return headers["x-bidops-actor-name-format"] === "utf-8-percent-v1" && actor.startsWith("UTF-8''") ? decodeURIComponent(actor.slice(7)) : actor;
}
function matchesValues(value: string | null, query: string | null): boolean {
  return !query || query.split(",").some((entry) => entry === "missing" ? value === null : value === entry);
}
async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}
async function trackingError(route: Route, code: "actor_name_required" | "opportunity_not_found" | "tracking_status_invalid" | "tracking_reason_required") {
  await fulfillJson(route, { error: { code, message: "합성 추적 오류", details: null }, request_id: null }, code === "actor_name_required" ? 400 : code === "opportunity_not_found" ? 404 : 422);
}

const responses = fixtures as Record<string, unknown>;
const PROFILE_PROJECTION_DIGEST = "a".repeat(64);
const PROFILE_PROJECTION_VERSION = `company-profile.sha256:${PROFILE_PROJECTION_DIGEST}`;

function fixtureRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function fixtureStringArray(value: unknown): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : [];
}

function safeProfileSection(value: unknown): Record<string, unknown> {
  const section = fixtureRecord(value) ?? {};
  const items = Array.isArray(section.items)
    ? section.items.map((item) => {
      const record = fixtureRecord(item) ?? {};
      const { source_line: _sourceLine, ...safeItem } = record;
      return safeItem;
    })
    : [];
  const children = Array.isArray(section.children) ? section.children.map(safeProfileSection) : [];
  const legacyRawBlocks = Array.isArray(section.raw_blocks) ? section.raw_blocks : [];
  const errorCodes = fixtureStringArray(section.error_codes);
  if (errorCodes.length === 0 && (legacyRawBlocks.length > 0 || (section.raw !== null && section.raw !== undefined && items.length === 0))) {
    errorCodes.push("profile_section_unstructured");
  }
  return {
    id: section.id,
    number: section.number ?? null,
    title: section.title,
    heading: section.heading,
    level: section.level,
    state: section.state,
    status_counts: section.status_counts ?? {},
    items,
    error_codes: errorCodes,
    children,
  };
}

function safeProfileProjection(pathname: string, body: unknown): unknown {
  const response = fixtureRecord(body);
  if (!response) return body;
  if (pathname === "/api/profile/sections") {
    return {
      schema_version: "bidops.profile-projection.v1",
      profile_version: PROFILE_PROJECTION_VERSION,
      profile_digest: PROFILE_PROJECTION_DIGEST,
      sections: Array.isArray(response.sections) ? response.sections.map(safeProfileSection) : [],
      status_counts: response.status_counts ?? {},
      error_codes: [],
    };
  }
  if (pathname === "/api/profile/unknowns") {
    return {
      schema_version: "bidops.profile-projection.v1",
      profile_version: PROFILE_PROJECTION_VERSION,
      profile_digest: PROFILE_PROJECTION_DIGEST,
      items: Array.isArray(response.items)
        ? response.items.map((item) => {
          const record = fixtureRecord(item) ?? {};
          const { source_line: _sourceLine, ...safeItem } = record;
          return safeItem;
        })
        : [],
      total: response.total,
      reference_fields: response.reference_fields ?? [],
      error_codes: [],
    };
  }
  return body;
}

const fixtureEvidenceId = "fixture-evidence-1";
const sectionKeys = [
  "project_overview", "eligibility_matrix", "scope_deliverables", "requirements_matrix",
  "evaluation_strategy", "delivery_plan", "technical_integration_risks", "security_legal_contract_risks",
  "economics_scenarios", "competitive_proposal_strategy", "questions_internal_actions",
  "document_bundle_limitations", "decision_card",
] as const;
const syntheticSections = sectionKeys.map((sectionKey, sectionIndex) => ({
  section_key: sectionKey,
  title: `fixture ${sectionKey}`,
  blocks: [{
    block_id: `fixture-block-${sectionIndex}`,
    type: sectionKey === "decision_card" ? "decision_card" : "matrix",
    title: "fixture matrix",
    body: `synthetic fixture section ${sectionIndex}`,
    claim_ids: ["fixture-claim-1"],
    rows: Array.from({ length: sectionKey.includes("matrix") || sectionKey === "decision_card" ? 22 : 2 }, (_, index) => ({
      row_key: `${sectionKey}-${index}`,
      label: `fixture row ${index + 1}`,
      cells: ["synthetic bounded content", "keyboard-accessible matrix content"],
      claim_ids: ["fixture-claim-1"],
    })),
  }],
}));

const syntheticReport = {
  deep_review_id: "fixture-review",
  notice_id: 1,
  bundle_id: "fixture-bundle",
  profile_version_id: "fixture-profile",
  policy_version_id: "fixture-policy",
  schema: "bidops.deep-review-report.v1",
  sections: syntheticSections,
  system_recommendation: "조건부 추진 검토",
  claims: [{ claim_id: "fixture-claim-1", category: "fact", claim_type: "fact", body: "synthetic supported fact", status: "supported", formula: null, premise_claim_ids: [], reason: null, evidence_ids: [fixtureEvidenceId] }],
  unknowns: ["synthetic unknown"],
  validation_summary: { status: "passed", failed: 0, warnings: 0, passed: 1 },
  created_at: "2026-08-26T00:00:00Z",
  quality_status: "unmeasured_reference",
};

const deepReviewStageNames = [
  "requirements_and_evaluation",
  "delivery_risk_economics",
  "synthesis_and_validation",
] as const;

function syntheticAttempt(
  sequence: number,
  status: "queued" | "running" | "completed" | "failed",
  lastErrorCode: string | null = null,
) {
  const terminal = status === "completed" || status === "failed";
  return {
    id: `fixture-attempt-${sequence}`,
    sequence,
    status,
    started_at: status === "queued" ? null : `2026-08-26T00:00:0${sequence}Z`,
    completed_at: terminal ? `2026-08-26T00:00:1${sequence}Z` : null,
    last_error_code: lastErrorCode,
    stages: deepReviewStageNames.map((stage, index) => {
      let stageStatus: "queued" | "running" | "completed" | "failed" = "queued";
      if (status === "completed") stageStatus = "completed";
      if (status === "running") stageStatus = index === 0 ? "running" : "queued";
      if (status === "failed") stageStatus = index === 0 ? "failed" : "queued";
      return {
        stage,
        sequence: index + 1,
        status: stageStatus,
        started_at: stageStatus === "queued" ? null : `2026-08-26T00:00:0${sequence}Z`,
        completed_at: stageStatus === "completed" || stageStatus === "failed" ? `2026-08-26T00:00:1${sequence}Z` : null,
        last_error_code: stageStatus === "failed" ? lastErrorCode : null,
      };
    }),
  };
}

const syntheticCompletedAttempt = syntheticAttempt(1, "completed");
const syntheticReview = {
  id: "fixture-review", notice_id: 1, bundle_id: "fixture-bundle", status: "completed",
  created_at: "2026-08-26T00:00:00Z", completed_at: "2026-08-26T00:00:01Z",
  current_attempt: syntheticCompletedAttempt,
  attempts: [syntheticCompletedAttempt],
  quality_status: "unmeasured_reference",
};

// 심층 보고서 우측 열의 segment manifest. 화면이 조회하는 경로를 고정 fixture에
// 빠짐없이 넣어야 기존 spec이 정의된 상태에서 돈다(engineering-notes.md).
export const FIXTURE_STRUCTURE_ID = "fixture-structure";

function syntheticSegmentLocator(page: number, blockKey: string, ordinal: number) {
  return { kind: "paragraph", block_key: blockKey, page, ordinal, table_key: null, row: null, column: null };
}

function syntheticSegments() {
  return {
    schema: "bidops.document-segments.v1",
    structure_id: FIXTURE_STRUCTURE_ID,
    document_version_id: "fixture-document",
    source_sha256: "a".repeat(64),
    taxonomy_version: "taxonomy.v1",
    extractor_binding: {
      name: "fixture-extractor",
      version: "1.0.0",
      taxonomy_version: "taxonomy.v1",
      rules_sha256: "b".repeat(64),
      schema: "bidops.document-segments.v1",
    },
    extractor_binding_sha256: "c".repeat(64),
    payload_sha256: "d".repeat(64),
    segments: [
      {
        segment_id: "fixture-segment-1",
        ordinal: 1,
        taxonomy_labels: ["business_eligibility_evaluation"],
        start_locator: syntheticSegmentLocator(1, "fixture-block", 0),
        end_locator: syntheticSegmentLocator(1, "fixture-block", 2),
        requirement_ids: ["SFR-1", "SFR-2"],
        source_block_keys: ["fixture-block"],
        classification_source: "deterministic",
        confidence: null,
        status: "classified",
        page_range: { first: 2, last: 2 },
        mapping_status: "mapped",
      },
      // 사람 확인 필요 segment는 대응표의 세 상태를 모두 덮는다. 논리 page와
      // 물리 PDF 순번(표지 포함)이 다르다는 점도 값이 다르게 유지한다.
      {
        segment_id: "fixture-segment-2",
        ordinal: 2,
        taxonomy_labels: ["technical_functional", "quality_security_constraints"],
        start_locator: syntheticSegmentLocator(2, "fixture-block-review", 3),
        end_locator: syntheticSegmentLocator(2, "fixture-block-review", 5),
        requirement_ids: ["SFR-3"],
        source_block_keys: ["fixture-block-review"],
        classification_source: "deterministic",
        confidence: null,
        status: "needs_human_review",
        page_range: { first: 3, last: 3 },
        mapping_status: "mapped",
      },
      {
        segment_id: "fixture-segment-3",
        ordinal: 3,
        taxonomy_labels: ["partnership_governance"],
        start_locator: syntheticSegmentLocator(4, "fixture-block-partial", 6),
        end_locator: syntheticSegmentLocator(5, "fixture-block-partial", 7),
        requirement_ids: ["SFR-5"],
        source_block_keys: ["fixture-block-partial"],
        classification_source: "deterministic",
        confidence: null,
        status: "needs_human_review",
        page_range: { first: 5, last: 7 },
        mapping_status: "partial",
      },
      {
        segment_id: "fixture-segment-4",
        ordinal: 4,
        taxonomy_labels: ["quality_security_constraints"],
        start_locator: syntheticSegmentLocator(6, "fixture-block-unmapped", 8),
        end_locator: syntheticSegmentLocator(6, "fixture-block-unmapped", 8),
        requirement_ids: ["SFR-6"],
        source_block_keys: ["fixture-block-unmapped"],
        classification_source: "deterministic",
        confidence: null,
        status: "needs_human_review",
        page_range: null,
        mapping_status: "unavailable",
      },
    ],
    inventory_summary: {
      expected_ids: ["SFR-1", "SFR-2", "SFR-3", "SFR-5", "SFR-6"],
      duplicate_ids: ["SFR-2"],
      ambiguous_items: [{
        reason: "prefix_unconfirmed",
        raw_id: "SFR- 4",
        raw_prefix: "SFR",
        normalized_prefix: "SFR",
        occurrence_count: 2,
        locator: syntheticSegmentLocator(2, "fixture-block-review", 4),
      }],
      prefixes: ["SFR"],
      item_count: 6,
    },
    coverage: {
      block_count: 10,
      covered_block_count: 9,
      segment_count: 4,
      gap_count: 1,
      overlap_count: 0,
      gaps: [{ start_ordinal: 9, end_ordinal: 9 }],
      overlaps: [],
      needs_human_review_count: 3,
      toc: { entry_count: 3, matched_heading_count: 2, unmatched_entry_count: 1 },
    },
    warnings: [],
    created_at: "2026-08-26T00:00:00Z",
  };
}

function syntheticReportView(finalOpinion: unknown = null) {
  return {
    deep_review_id: "fixture-review",
    current_revision_id: "fixture-revision",
    report: syntheticReport,
    validation: {
      schema: "bidops.deep-review-validation.v1",
      validation_run_id: "fixture-validation",
      report_revision_id: "fixture-revision",
      status: "passed",
      checks: [{
        check_type: "fixture", status: "passed", severity: "낮음", message: "synthetic fixture",
        related_claim_ids: ["fixture-claim-1"], related_evidence_ids: [fixtureEvidenceId],
      }],
      created_at: "2026-08-26T00:00:00Z",
    },
    history: [{
      revision_id: "fixture-revision", sequence: 1, origin: "machine", validation_status: "passed",
      created_by_name: null, created_at: "2026-08-26T00:00:00Z",
    }],
    final_opinion: finalOpinion,
  };
}

function syntheticResponse(pathname: string): unknown | undefined {
  if (pathname === `/api/document-structures/${FIXTURE_STRUCTURE_ID}/segments`) return syntheticSegments();
  if (pathname === "/api/deep-reviews/fixture-review") return syntheticReview;
  if (pathname === "/api/deep-reviews/fixture-review/report") return syntheticReportView();
  if (pathname === `/api/evidence/${fixtureEvidenceId}`) return { evidence_id: fixtureEvidenceId, source_kind: "document", document_version_id: "fixture-document", structure_id: "fixture-structure", profile_version_id: null, profile_evidence_id: null, locator_type: "page", locator: { page: 1 }, quote: "synthetic fixture evidence", confidence: 0.99, source_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", page: { structure_id: "fixture-structure", page: 1, metadata: { number: 1, width: 100, height: 100, image_content_object_id: null }, blocks: [{ block_key: "fixture-block", parent_block_key: null, type: "paragraph", page: 1, bbox: [0, 0, 100, 100], text: "synthetic fixture evidence", confidence: 0.99, attributes: {} }] } };
  return undefined;
}

export type DeepReviewFixtureScenario = "completed" | "polling" | "failed" | "queued" | "running";

export interface DeepReviewMockTrace {
  reviewGets: number;
  reportGets: number;
  attemptPosts: Array<{ body: Record<string, unknown>; headers: Record<string, string> }>;
  opinionPosts: Array<{ body: Record<string, unknown>; headers: Record<string, string> }>;
  events: string[];
}

/**
 * R-06 전용 상태 fixture다. mockApi 뒤에 등록하면 deep-review 경로만 덮어쓰고
 * evidence 등 기존 고정 응답은 fallback으로 그대로 사용한다.
 */
export async function mockDeepReviewLifecycle(page: Page, scenario: DeepReviewFixtureScenario): Promise<DeepReviewMockTrace> {
  const trace: DeepReviewMockTrace = { reviewGets: 0, reportGets: 0, attemptPosts: [], opinionPosts: [], events: [] };
  const failedAttempt = syntheticAttempt(1, "failed", "model_timeout");
  const queuedRetryAttempt = syntheticAttempt(2, "queued");
  let retryCreated = false;
  let lastServedStatus = scenario === "completed" ? "completed" : scenario === "failed" ? "failed" : "queued";
  let finalOpinion: unknown = null;

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const method = request.method();

    if (pathname === "/api/deep-reviews/fixture-review" && method === "GET") {
      trace.reviewGets += 1;
      let currentAttempt = syntheticCompletedAttempt;
      let attempts = [syntheticCompletedAttempt];
      let reviewStatus: "queued" | "running" | "completed" | "failed" = "completed";
      let completedAt: string | null = "2026-08-26T00:00:11Z";

      if (scenario === "polling") {
        const status = trace.reviewGets === 1 ? "queued" : trace.reviewGets === 2 ? "running" : "completed";
        currentAttempt = syntheticAttempt(1, status);
        attempts = [currentAttempt];
        reviewStatus = status;
        completedAt = status === "completed" ? "2026-08-26T00:00:11Z" : null;
      } else if (scenario === "queued" || scenario === "running") {
        currentAttempt = syntheticAttempt(1, scenario);
        attempts = [currentAttempt];
        reviewStatus = scenario;
        completedAt = null;
      } else if (scenario === "failed") {
        currentAttempt = retryCreated ? queuedRetryAttempt : failedAttempt;
        attempts = retryCreated ? [failedAttempt, queuedRetryAttempt] : [failedAttempt];
        reviewStatus = retryCreated ? "queued" : "failed";
        completedAt = null;
      }

      lastServedStatus = reviewStatus;
      trace.events.push(`review:${reviewStatus}`);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "fixture-review", notice_id: 1, bundle_id: "fixture-bundle", status: reviewStatus,
          current_attempt: currentAttempt, attempts, created_at: "2026-08-26T00:00:00Z", completed_at: completedAt,
          quality_status: "unmeasured_reference",
        }),
      });
      return;
    }

    if (pathname === "/api/deep-reviews/fixture-review/report" && method === "GET") {
      trace.reportGets += 1;
      trace.events.push(`report:${lastServedStatus}`);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(syntheticReportView(finalOpinion)) });
      return;
    }

    if (pathname === "/api/deep-reviews/fixture-review/attempts" && method === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.attemptPosts.push({ body, headers: request.headers() });
      retryCreated = true;
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify(queuedRetryAttempt) });
      return;
    }

    if (pathname === "/api/deep-reviews/fixture-review/final-opinions" && method === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.opinionPosts.push({ body, headers: request.headers() });
      finalOpinion = {
        id: "fixture-opinion-1", sequence: 1, value: body.value, reason: body.reason,
        validation_status_at_opinion: "passed", acknowledged_validation_failure: false,
        claimed_name: "fixture actor", created_at: "2026-08-26T00:01:00Z",
      };
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(finalOpinion) });
      return;
    }

    await route.fallback();
  });

  return trace;
}

const bidDeltaComparisonId = "77777777-7777-4777-8777-777777777777";
const bidDeltaBaseline = {
  opportunity_link_id: 81,
  notice_id: 991,
  notice_source_type: "pre_spec",
  notice_external_id: "R26BD00267196",
  bid_ordinal: null,
  published_at: "2026-08-29T09:00:00+09:00",
  bundle_id: "11111111-1111-4111-8111-111111111111",
  bundle_revision: 2,
  bundle_version: 4,
  document_version_id: "22222222-2222-4222-8222-222222222222",
  document_version_version: 3,
  document_role: "제안요청서",
  structure_id: "33333333-3333-4333-8333-333333333333",
  source_sha256: "a".repeat(64),
  structure_payload_sha256: "b".repeat(64),
  effective_date: null,
};
const bidDeltaComparison = {
  opportunity_link_id: 82,
  notice_id: 1102,
  notice_source_type: "bid_notice",
  notice_external_id: "R26BK00267196",
  bid_ordinal: "000",
  published_at: "2026-08-30T09:00:00+09:00",
  bundle_id: "44444444-4444-4444-8444-444444444444",
  bundle_revision: 1,
  bundle_version: 2,
  document_version_id: "55555555-5555-4555-8555-555555555555",
  document_version_version: 1,
  document_role: "공고",
  structure_id: "66666666-6666-4666-8666-666666666666",
  source_sha256: "c".repeat(64),
  structure_payload_sha256: "d".repeat(64),
  effective_date: "2026-09-01",
};
const bidDeltaCategories = [
  "budget_and_economics", "contract_period_and_schedule", "eligibility",
  "joint_supply_and_subcontracting", "scope_and_requirements", "evaluation", "submission",
] as const;

type BidDeltaCalculationFixture = "pending" | "running" | "completed" | "failed";
type BidDeltaResultFixture = "changed" | "unchanged" | "unknown" | "failed";

export interface BidDeltaMockOptions {
  calculationStatus?: BidDeltaCalculationFixture;
  resultStatus?: BidDeltaResultFixture;
  withHistory?: boolean;
  pollingStatuses?: BidDeltaCalculationFixture[];
  finalDecisionErrorCode?: string | null;
  baselineCandidates?: boolean;
  comparisonCandidates?: boolean;
}

export interface BidDeltaMockTrace {
  workspaceGets: number;
  comparisonGets: number;
  comparisonPosts: Array<{ body: Record<string, unknown>; headers: Record<string, string> }>;
  retryPosts: Array<{ body: Record<string, unknown>; headers: Record<string, string> }>;
  finalDecisionPosts: Array<{ body: Record<string, unknown>; headers: Record<string, string> }>;
}

function deltaAttempt(status: BidDeltaCalculationFixture, sequence: number) {
  const attemptStatus = status === "pending" ? "queued" : status === "running" ? "running" : status === "completed" ? "completed" : "failed";
  const terminal = attemptStatus === "completed" || attemptStatus === "failed";
  return {
    id: `77777777-7777-4777-8777-77777777777${sequence}`,
    sequence,
    status: attemptStatus,
    started_at: status === "pending" ? null : "2026-08-31T09:01:00Z",
    completed_at: terminal ? "2026-08-31T09:02:00Z" : null,
    last_error_code: status === "failed" ? "model_timeout" : null,
  };
}

function deltaEvidence(side: "baseline" | "comparison", ordinal: number) {
  const baseline = side === "baseline";
  return {
    id: `${baseline ? "99999999" : "aaaaaaaa"}-8888-4888-8888-88888888888${ordinal}`,
    side,
    document_version_id: baseline ? bidDeltaBaseline.document_version_id : bidDeltaComparison.document_version_id,
    structure_id: baseline ? bidDeltaBaseline.structure_id : bidDeltaComparison.structure_id,
    source_sha256: baseline ? bidDeltaBaseline.source_sha256 : bidDeltaComparison.source_sha256,
    locator_type: "table_cell",
    locator: { page: baseline ? 12 : 15, table_key: `table-${ordinal}`, row: ordinal, column: 2 },
    quote: baseline ? `기준 원문 ${ordinal}` : `비교 원문 ${ordinal}`,
    verification_status: "verified",
  };
}

function deltaItems(resultStatus: BidDeltaResultFixture | null) {
  if (resultStatus === null) return [];
  return bidDeltaCategories.map((category, index) => {
    const itemStatus = resultStatus === "changed" && index === 0
      ? "changed"
      : resultStatus === "unknown" && index === 0
        ? "unknown"
        : resultStatus === "failed" && index === 0
          ? "failed"
          : "unchanged";
    const isUncertain = itemStatus === "unknown" || itemStatus === "failed";
    return {
      id: `88888888-8888-4888-8888-88888888888${index + 1}`,
      ordinal: index + 1,
      category,
      result_status: itemStatus,
      materiality: itemStatus === "changed" ? "material" : isUncertain ? "unknown" : "non_material",
      before_value: isUncertain ? null : `변경 전 ${index + 1}`,
      after_value: isUncertain ? null : itemStatus === "changed" ? `변경 후 ${index + 1}` : `변경 전 ${index + 1}`,
      summary: isUncertain ? null : itemStatus === "changed" ? "참가 조건이 달라졌습니다." : "검증된 의미 차이가 없습니다.",
      baseline_evidence: isUncertain ? [] : [deltaEvidence("baseline", index + 1)],
      comparison_evidence: isUncertain ? [] : [deltaEvidence("comparison", index + 1)],
      error_code: itemStatus === "unknown" ? "evidence_unverified" : itemStatus === "failed" ? "extract_failed" : null,
    };
  });
}

function deltaDecision(sequence: number, decision: "go" | "no_go", comparisonVersion: number) {
  return {
    schema_version: "bidops.bid-final-decision.v2",
    id: `aaaaaaaa-1111-4111-8111-aaaaaaaaaaa${sequence}`,
    opportunity_id: 501,
    sequence,
    basis_kind: "comparison",
    comparison_id: bidDeltaComparisonId,
    comparison_version: comparisonVersion,
    result_sha256: "e".repeat(64),
    baseline_document_version_id: bidDeltaBaseline.document_version_id,
    comparison_document_version_id: bidDeltaComparison.document_version_id,
    basis_notice_id: null,
    basis_observation_sha256: null,
    supersedes_final_decision_id: sequence > 1 ? "aaaaaaaa-1111-4111-8111-aaaaaaaaaaa1" : null,
    decision,
    reason: sequence > 1 ? "최신 결정 이유" : "이전 결정 이유",
    claimed_name: sequence > 1 ? "이전 담당자" : "기존 담당자",
    request_id: `bd47bc02-c51c-4260-a285-68c39b991fa${sequence}`,
    created_at: `2026-08-31T09:1${sequence}:00Z`,
    currentness: "current",
    currentness_reasons: [],
  };
}

export async function mockBidDelta(page: Page, options: BidDeltaMockOptions = {}): Promise<BidDeltaMockTrace> {
  const trace: BidDeltaMockTrace = { workspaceGets: 0, comparisonGets: 0, comparisonPosts: [], retryPosts: [], finalDecisionPosts: [] };
  const initialStatus = options.calculationStatus ?? "completed";
  const resultStatus = options.resultStatus ?? (initialStatus === "failed" ? "failed" : "changed");
  const decisions = options.withHistory ? [deltaDecision(1, "no_go", 2), deltaDecision(2, "go", 2)] : [];
  let calculationStatus = initialStatus;
  let comparisonVersion = 2;
  let currentResult: BidDeltaResultFixture | null = initialStatus === "pending" || initialStatus === "running" ? null : resultStatus;
  let attemptSequence = 1;
  const workspaceBaselineCandidates = options.baselineCandidates === false ? [] : [bidDeltaBaseline];
  const workspaceComparisonCandidates = options.comparisonCandidates === false ? [] : [bidDeltaComparison];

  const snapshot = () => {
    const currentAttempt = deltaAttempt(calculationStatus, attemptSequence);
    const finalDecisions = [...decisions];
    const latest = finalDecisions.at(-1) ?? null;
    return {
      schema_version: "bidops.bid-delta-comparison.v1",
      id: bidDeltaComparisonId,
      opportunity_id: 501,
      sequence: 1,
      version: comparisonVersion,
      category_policy_version: "bid-delta-policy.v1",
      calculation_status: calculationStatus,
      result_status: currentResult,
      materiality: currentResult === "changed" ? "material" : currentResult === "unchanged" ? "non_material" : "unknown",
      baseline: bidDeltaBaseline,
      comparison: bidDeltaComparison,
      items: deltaItems(currentResult),
      attempts: Array.from({ length: attemptSequence }, (_, index) => index + 1 === attemptSequence ? currentAttempt : deltaAttempt("failed", index + 1)),
      result_sha256: currentResult && currentResult !== "failed" ? "e".repeat(64) : null,
      last_error_code: calculationStatus === "failed" ? "model_timeout" : null,
      created_at: "2026-08-31T09:00:00Z",
      started_at: calculationStatus === "pending" ? null : "2026-08-31T09:01:00Z",
      completed_at: calculationStatus === "pending" || calculationStatus === "running" ? null : "2026-08-31T09:02:00Z",
      final_decisions: finalDecisions,
      latest_final_decision: latest,
      decision_currentness: latest ? "current" : "unknown",
      currentness_reasons: latest ? [] : ["no_final_decision"],
    };
  };

  const basePath = "/api/opportunities/501/bid-delta";
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const method = request.method();
    if (pathname === basePath && method === "GET") {
      trace.workspaceGets += 1;
      const current = snapshot();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        schema_version: "bidops.bid-delta-workspace.v1",
        opportunity_id: 501,
        baseline_candidates: workspaceBaselineCandidates,
        comparison_candidates: workspaceComparisonCandidates,
        comparisons: [{
          id: current.id, sequence: current.sequence, version: current.version,
          category_policy_version: current.category_policy_version, calculation_status: current.calculation_status,
          result_status: current.result_status, materiality: current.materiality, baseline: current.baseline,
          comparison: current.comparison, result_sha256: current.result_sha256, created_at: current.created_at,
          started_at: current.started_at, completed_at: current.completed_at,
        }],
        latest_final_decision: current.latest_final_decision,
        decision_currentness: current.decision_currentness,
        currentness_reasons: current.currentness_reasons,
        generated_at: "2026-08-31T09:03:00Z",
      }) });
      return;
    }
    if (pathname === `${basePath}/comparisons/${bidDeltaComparisonId}` && method === "GET") {
      trace.comparisonGets += 1;
      const sequenceStatus = options.pollingStatuses?.[trace.comparisonGets - 1];
      if (sequenceStatus) {
        calculationStatus = sequenceStatus;
        currentResult = sequenceStatus === "completed" ? resultStatus : sequenceStatus === "failed" ? "failed" : null;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(snapshot()) });
      return;
    }
    if (pathname === `${basePath}/comparisons` && method === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.comparisonPosts.push({ body, headers: request.headers() });
      calculationStatus = "pending";
      currentResult = null;
      comparisonVersion = 1;
      attemptSequence = 1;
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify(snapshot()) });
      return;
    }
    if (pathname === `${basePath}/comparisons/${bidDeltaComparisonId}/attempts` && method === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.retryPosts.push({ body, headers: request.headers() });
      attemptSequence += 1;
      comparisonVersion += 1;
      calculationStatus = "pending";
      currentResult = null;
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify(snapshot()) });
      return;
    }
    if (pathname === "/api/opportunities/501/bid-conditions" && method === "GET") {
      // 기본 공고 조건은 비교 대상 입찰공고(1102) 한 차수다. 서버처럼 `latest_notice_id`와
      // `latest_observation_sha256`은 `bid_notices` 안의 그 차수를 가리킨다. 사업기회 501에는
      // 확정 연결된 사전규격이 없어 서버와 같이 `pre_spec`은 null, 사전규격 대비는 빈 목록이다.
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        opportunity_id: 501,
        generated_at: "2026-08-31T09:03:00Z",
        latest_notice_id: bidDeltaComparison.notice_id,
        latest_observation_sha256: "e".repeat(64),
        pre_spec: null,
        bid_notices: [{
          notice_id: bidDeltaComparison.notice_id,
          bid_no: bidDeltaComparison.notice_external_id,
          bid_ord: bidDeltaComparison.bid_ordinal,
          published_at: bidDeltaComparison.published_at,
          observation_sha256: "e".repeat(64),
          conditions: {
            budget: "150000000",
            estimated_price: null,
            deadline_at: "2026-09-10T10:00:00+09:00",
            opening_at: "2026-09-10T11:00:00+09:00",
            method: "일반경쟁",
            participation_limited: "Y",
            industry_limited: "Y",
            sw_industry_1468: "N",
            joint_contract_method: "공동이행",
            successful_bid_method: "협상에의한계약",
            technical_evaluation_rate: "90",
            region_limit_basis: null,
            joint_contract_regions: [],
            change_reason: null,
            re_notice: "N",
          },
          changes_from_previous: [],
        }],
        pre_spec_comparison: [],
        not_comparable: ["deadline_at"],
      }) });
      return;
    }
    if (pathname === "/api/opportunities/501/final-decisions" && method === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.finalDecisionPosts.push({ body, headers: request.headers() });
      const sequence = decisions.length + 1;
      const saved = {
        schema_version: "bidops.bid-final-decision.v2",
        id: `bbbbbbbb-2222-4222-8222-bbbbbbbbbbb${sequence}`,
        opportunity_id: 501,
        sequence,
        basis_kind: "notice_conditions",
        comparison_id: null,
        comparison_version: null,
        result_sha256: null,
        baseline_document_version_id: null,
        comparison_document_version_id: null,
        basis_notice_id: Number(body.expected_notice_id ?? 0),
        basis_observation_sha256: String(body.expected_observation_sha256 ?? ""),
        supersedes_final_decision_id: (body.supersedes_final_decision_id as string | null) ?? null,
        decision: body.decision === "go" ? "go" : "no_go",
        reason: String(body.reason ?? ""),
        claimed_name: "테스트 담당자",
        request_id: String(body.request_id ?? ""),
        created_at: "2026-08-31T09:15:00Z",
        currentness: "current",
        currentness_reasons: [],
      };
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(saved) });
      return;
    }
    if (pathname === `${basePath}/comparisons/${bidDeltaComparisonId}/final-decisions` && method === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.finalDecisionPosts.push({ body, headers: request.headers() });
      if (options.finalDecisionErrorCode) {
        const status = options.finalDecisionErrorCode === "bid_delta_currentness_unavailable" ? 503 : 409;
        await route.fulfill({ status, contentType: "application/json", body: JSON.stringify({
          error: { code: options.finalDecisionErrorCode, message: "고정 conflict fixture", details: null },
          request_id: body.request_id ?? null,
        }) });
        return;
      }
      const sequence = decisions.length + 1;
      const saved = { ...deltaDecision(sequence, body.decision === "go" ? "go" : "no_go", comparisonVersion), reason: String(body.reason ?? ""), claimed_name: "테스트 담당자", request_id: String(body.request_id ?? "") };
      decisions.push(saved);
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(saved) });
      return;
    }
    await route.fallback();
  });
  return trace;
}

const visualOpportunityLinksBase = {
  search_strategy: null,
  attempted_strategies: [],
  agency_match: null,
  last_searched_at: null,
  evidence_external_no: null,
  evidence_bid_no: null,
  human_decision: null,
  reviewer_name: null,
  reviewed_at: null,
  review_reason: null,
};

const visualOpportunities: OpportunityListItem[] = [
  {
    id: 101,
    section: null, pending_candidate_link_count: 0, open_blocking_item_count: 0,
    action_reasons: [], hold_review_due_at: null,
    tracking_status: "미선택",
    tracking_reason: null,
    tracking_selected_by: null,
    tracking_selected_at: null,
    recheck_signal: false,
    recheck_signal_at: null,
    recheck_signal_link_id: null,
    first_registered_stage: "order_plan",
    links: [{
      ...visualOpportunityLinksBase,
      id: 1001,
      stage: "order_plan",
      link_type: "official",
      status: "확정",
      record_type: "order_plan",
      record_id: 51,
      notice_id: null,
      order_plan_id: 51,
      source_type: null,
      title: "미선택 공공 데이터 플랫폼 구축",
      agency: "테스트 기관",
      external_id: "PLAN-101",
      record_external_id: "PLAN-101",
    }],
  },
  {
    id: 202,
    section: "조치 필요", pending_candidate_link_count: 0, open_blocking_item_count: 0,
    action_reasons: ["new_link"], hold_review_due_at: null,
    tracking_status: "종료",
    tracking_reason: "현재 범위와 맞지 않아 능동 추적을 종료함",
    tracking_selected_by: "기존 담당자",
    tracking_selected_at: "2026-08-20T09:00:00Z",
    recheck_signal: true,
    recheck_signal_at: "2026-08-31T01:30:00Z",
    recheck_signal_link_id: 2002,
    first_registered_stage: "pre_spec",
    links: [{
      ...visualOpportunityLinksBase,
      id: 2001,
      stage: "notice",
      link_type: "official",
      status: "확정",
      record_type: "pre_spec",
      record_id: 61,
      notice_id: 61,
      order_plan_id: null,
      source_type: "pre_spec",
      title: "종료된 지능형 업무 시스템 사전규격",
      agency: "테스트 기관",
      external_id: "PRE-202",
      record_external_id: "PRE-202",
    }, {
      ...visualOpportunityLinksBase,
      id: 2002,
      stage: "notice",
      link_type: "official",
      status: "확정",
      record_type: "bid_notice",
      record_id: 62,
      notice_id: 62,
      order_plan_id: null,
      source_type: "bid_notice",
      title: "종료된 지능형 업무 시스템 본공고",
      agency: "테스트 기관",
      external_id: "BID-202",
      record_external_id: "BID-202",
    }],
  },
  {
    id: 303,
    section: "조치 필요", pending_candidate_link_count: 1, open_blocking_item_count: 0,
    action_reasons: ["candidate_pending"], hold_review_due_at: null,
    tracking_status: "계속 추적",
    tracking_reason: "후보 관계를 사람이 확인할 때까지 계속 추적",
    tracking_selected_by: "검토 담당자",
    tracking_selected_at: "2026-08-29T02:00:00Z",
    recheck_signal: false,
    recheck_signal_at: null,
    recheck_signal_link_id: null,
    first_registered_stage: "order_plan",
    links: [{
      ...visualOpportunityLinksBase,
      id: 3001,
      stage: "notice",
      link_type: "candidate",
      status: "후보 확인 대기",
      search_strategy: "normalized",
      attempted_strategies: ["full", "normalized"],
      agency_match: true,
      last_searched_at: "2026-08-30T03:00:00Z",
      record_type: "pre_spec",
      record_id: 71,
      notice_id: 71,
      order_plan_id: null,
      source_type: "pre_spec",
      title: "후보 관계 사전규격",
      agency: "후보 기관",
      external_id: "PRE-303",
      record_external_id: "PRE-303",
    }],
  },
] as const;

/** Mock-server transitions only; screens consume the explicit section projection. */
/** Mock-server-only derivation of §7.1 action reasons from the item's own flags. */
function mockActionReasons(item: OpportunityListItem): OpportunityListItem["action_reasons"] {
  const reasons: OpportunityListItem["action_reasons"] = [];
  if (item.recheck_signal) reasons.push("new_link");
  if (item.pending_candidate_link_count > 0) {
    const mergeConfirmation = item.links.some((link) => link.status === "후보 확인 대기" && link.search_strategy === "merge_confirmation");
    reasons.push(mergeConfirmation ? "merge_confirmation" : "candidate_pending");
  }
  if (item.open_blocking_item_count > 0) reasons.push("blocking_item");
  if (item.tracking_status === "보류" && item.tracking_selected_at
    && Date.now() >= new Date(item.tracking_selected_at).getTime() + 14 * 24 * 60 * 60 * 1000) reasons.push("hold_overdue");
  return reasons;
}

const MOCK_DAY_MS = 24 * 60 * 60 * 1000;
/** `hold_review=due_soon`의 창(일). 서버 `HOLD_REVIEW_DUE_SOON_DAYS`와 같다. */
const MOCK_HOLD_DUE_SOON_DAYS = 3;

/**
 * Mock-server-only §7.3 `hold_review` 필터.
 *
 * - `overdue`: 행의 `action_reasons`에 `hold_overdue`가 있다(서버가 준 사유를 그대로 읽는다).
 * - `due_soon`: `보류`이고 기한이 지나지 않았으며 `hold_review_due_at`이 기준 시각 뒤 3일 안이다
 *   (서버의 `now < 기한 ≤ now + 3일`).
 * - `attention`: 둘의 합집합.
 *
 * 기준 시각은 이 mock이 `mockActionReasons`에서 쓰는 것과 같은 `Date.now()`다. 고정 mock
 * 시계가 따로 없으므로, 기한이 없는 `보류` 행은 어느 쪽에도 들지 않는다(서버도 선택 시각이
 * 없는 보류는 기한을 계산하지 않는다). 모르는 값은 호출자가 422로 돌려준다.
 */
function mockHoldReviewMatches(item: OpportunityListItem, kind: "overdue" | "due_soon" | "attention", now = Date.now()): boolean {
  const overdue = item.action_reasons.includes("hold_overdue");
  const due = item.hold_review_due_at === null ? Number.NaN : Date.parse(item.hold_review_due_at);
  const dueSoon = item.tracking_status === "보류" && !overdue
    && Number.isFinite(due) && due > now && due <= now + MOCK_HOLD_DUE_SOON_DAYS * MOCK_DAY_MS;
  if (kind === "overdue") return overdue;
  if (kind === "due_soon") return dueSoon;
  return overdue || dueSoon;
}

/** `sort=hold_review_due_at`: 기한 오름차순, 기한 없는 행은 마지막(서버와 같은 nulls last). */
function compareHoldReviewDue(left: OpportunityListItem, right: OpportunityListItem): number {
  const l = left.hold_review_due_at === null ? null : Date.parse(left.hold_review_due_at);
  const r = right.hold_review_due_at === null ? null : Date.parse(right.hold_review_due_at);
  if (l === null || r === null) return l === r ? 0 : l === null ? 1 : -1;
  return l - r;
}

/** Mock-server transitions only; screens consume the explicit section projection.
 * §7.2: 미선택은 `신규 입찰공고`(입찰공고로 첫 등록)·`미결정`(그 밖)으로만 가고
 * `조치 필요`에는 가지 않는다. `계속 추적`·`보류`는 사유가 있어야, `종료`는
 * `new_link`·`candidate_pending`·`merge_confirmation` 중 하나가 있어야 `조치 필요`다. */
function mockTrackingSection(item: OpportunityListItem): OpportunityListItem["section"] {
  if (item.tracking_status === "미선택") return item.first_registered_stage === "bid_notice" ? "신규 입찰공고" : null;
  const reasons = mockActionReasons(item);
  const actionable = item.tracking_status === "종료"
    ? reasons.some((code) => code === "new_link" || code === "candidate_pending" || code === "merge_confirmation")
    : reasons.length > 0;
  if (actionable) return "조치 필요";
  return item.tracking_status === "보류" ? "보류" : item.tracking_status === "종료" ? "추적 종료" : "추적 중";
}

export async function mockOpportunity(page: Page): Promise<void> {
  const items: OpportunityListItem[] = structuredClone(visualOpportunities);
  items.push(
    { ...structuredClone(items[0]), id: 304, tracking_status: "보류", section: "보류", action_reasons: [], hold_review_due_at: null, links: [] },
    { ...structuredClone(items[0]), id: 305, tracking_status: "종료", section: "추적 종료", action_reasons: [], hold_review_due_at: null, links: [] },
    { ...structuredClone(items[0]), id: 306, tracking_status: "미선택", first_registered_stage: "bid_notice", section: "신규 입찰공고", action_reasons: [], hold_review_due_at: null, links: [] },
    ...decisionQueueItems.map((item): OpportunityListItem => ({
      ...structuredClone(visualOpportunities[0]), id: item.opportunity_id,
      tracking_status: "계속 추적", section: "추적 중", first_registered_stage: "pre_spec",
      action_reasons: [], hold_review_due_at: null,
      links: item.bid_notice_external_id ? [{
        ...visualOpportunities[1].links[1], id: item.opportunity_id * 10,
        notice_id: item.opportunity_id, record_id: item.opportunity_id,
        title: item.title, agency: item.agency, external_id: item.bid_notice_external_id,
        record_external_id: item.bid_notice_external_id,
      }] : [],
    })),
  );
  opportunityFixtures.set(page, items);
  const histories = new Map<number, OpportunityTrackingDecisionItem[]>([[202, structuredClone(opportunityTrackingHistory.items)]]);
  const recheckEvents = new Map<number, OpportunityRecheckEventView[]>([[202, structuredClone(opportunityTrackingHistory.recheck_events)]]);
  workloadProvider(page, "tracking_action_required", () => ({ count: items.filter((item) => item.section === "조치 필요").length, unavailable_reason: null }));
  workloadProvider(page, "tracking_hold_review_due", () => ({ count: items.filter((item) => item.action_reasons.includes("hold_overdue")).length, unavailable_reason: null }));
  await page.route("**/api/opportunities**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/opportunities" && request.method() === "GET") {
      const search = url.searchParams;
      const holdReview = search.get("hold_review");
      if (holdReview !== null && holdReview !== "overdue" && holdReview !== "due_soon" && holdReview !== "attention") {
        await fulfillJson(route, { detail: "hold_review 값이 올바르지 않습니다" }, 422);
        return;
      }
      // 서버처럼 hold_review는 목록·집계 모두에 걸리는 기본 조건이다.
      let filtered = items.filter((item) => (!search.get("tracking_status") || item.tracking_status === search.get("tracking_status"))
        && (!search.get("first_registered_stage") || item.first_registered_stage === search.get("first_registered_stage"))
        && (holdReview === null || mockHoldReviewMatches(item, holdReview)));
      const section_counts: OpportunitySectionCounts = { "조치 필요": 0, "추적 중": 0, "보류": 0, "추적 종료": 0, "신규 입찰공고": 0, "미결정": 0 };
      const action_reason_counts: Record<string, number> = { new_link: 0, candidate_pending: 0, merge_confirmation: 0, blocking_item: 0, hold_overdue: 0 };
      for (const item of filtered) {
        section_counts[item.section ?? "미결정"] += 1;
        for (const code of item.action_reasons) action_reason_counts[code] += 1;
      }
      if (search.get("reason")) filtered = filtered.filter((item) => item.action_reasons.includes(search.get("reason") as never));
      if (search.get("section")) filtered = filtered.filter((item) => item.section === search.get("section"));
      const query = search.get("q");
      if (query && searchKey(query)) {
        filtered = filtered.filter((item) => item.links.some((link) => (
          (link.link_type === "official" && link.status === "확정") || link.status === "사람 확인 완료"
        ) && searchMatches(query, link.title, link.agency)));
      }
      if (search.get("sort") === "tracking_status") filtered.sort((a, b) => a.tracking_status.localeCompare(b.tracking_status));
      if (search.get("sort") === "first_registered_stage") filtered.sort((a, b) => a.first_registered_stage.localeCompare(b.first_registered_stage));
      if (search.get("sort") === "hold_review_due_at") filtered.sort(compareHoldReviewDue);
      const limit = Number(search.get("limit") ?? 50), offset = Number(search.get("offset") ?? 0);
      await fulfillJson(route, { items: filtered.slice(offset, offset + limit), total: filtered.length, limit, offset, section_counts, action_reason_counts });
      return;
    }
    const searchMatch = url.pathname.match(/^\/api\/opportunities\/(\d+)\/searches$/);
    if (searchMatch && request.method() === "POST") {
      const item = items.find((candidate) => candidate.id === Number(searchMatch[1]));
      if (!item) { await trackingError(route, "opportunity_not_found"); return; }
      const actor = fixtureActor(request.headers());
      if (!actor) { await trackingError(route, "actor_name_required"); return; }
      const body = fixtureRecord(request.postDataJSON()) ?? {};
      await fulfillJson(route, {
        searched_at: "2026-09-02T01:00:00Z",
        target: body.target === "bid_notice" ? "bid_notice" : "pre_spec",
        attempted_strategies: ["full", "normalized"],
        candidates: [],
        search_unconfirmed: true,
      });
      return;
    }
    const ackMatch = url.pathname.match(/^\/api\/opportunities\/(\d+)\/recheck-acknowledgements$/);
    if (ackMatch && request.method() === "POST") {
      const item = items.find((candidate) => candidate.id === Number(ackMatch[1]));
      if (!item) { await trackingError(route, "opportunity_not_found"); return; }
      const actor = fixtureActor(request.headers());
      if (!actor) { await trackingError(route, "actor_name_required"); return; }
      const body = fixtureRecord(request.postDataJSON()) ?? {};
      if (!item.recheck_signal) {
        await fulfillJson(route, { error: { code: "recheck_signal_absent", message: "합성 확인 오류", details: null }, request_id: null }, 409);
        return;
      }
      if (Number(body.expected_link_id) !== item.recheck_signal_link_id) {
        await fulfillJson(route, { error: { code: "recheck_signal_changed", message: "합성 확인 오류", details: { current_link_id: item.recheck_signal_link_id } }, request_id: null }, 409);
        return;
      }
      const events = recheckEvents.get(item.id) ?? [];
      events.unshift({ kind: "acknowledged", link_id: item.recheck_signal_link_id, actor_kind: "human", claimed_name: actor, created_at: "2026-09-02T01:00:00Z", note_present: typeof body.note === "string" && body.note.trim().length > 0 });
      recheckEvents.set(item.id, events);
      item.recheck_signal = false; item.recheck_signal_at = null; item.recheck_signal_link_id = null;
      item.action_reasons = mockActionReasons(item);
      item.section = mockTrackingSection(item);
      await fulfillJson(route, item);
      return;
    }
    const match = url.pathname.match(/^\/api\/opportunities\/(\d+)(?:\/(tracking-status|tracking-decisions|deep-reviews))?$/);
    if (!match) { await route.fallback(); return; }
    const item = items.find((candidate) => candidate.id === Number(match[1]));
    if (!item) { await fulfillJson(route, { detail: "사업기회를 찾을 수 없습니다" }, 404); return; }
    if (request.method() === "GET") {
      await fulfillJson(route, match[2] === "tracking-decisions" ? { opportunity_id: item.id, items: histories.get(item.id) ?? [], recheck_events: recheckEvents.get(item.id) ?? [] }
        : match[2] === "deep-reviews" ? { opportunity_id: item.id, items: item.id === 202 ? opportunityDeepReviews.items : [] } : item);
      return;
    }
    if (match[2] === "tracking-status" && request.method() === "PATCH") {
      const body = fixtureRecord(request.postDataJSON()) ?? {};
      const actor = fixtureActor(request.headers());
      if (!actor) { await trackingError(route, "actor_name_required"); return; }
      if (!["미선택", "계속 추적", "보류", "종료"].includes(String(body.tracking_status))) { await trackingError(route, "tracking_status_invalid"); return; }
      if (typeof body.reason !== "string" || !body.reason.trim()) { await trackingError(route, "tracking_reason_required"); return; }
      const decisions = histories.get(item.id) ?? [];
      decisions.unshift({ decided_at: "2026-09-02T01:00:00Z", tracking_status: String(body.tracking_status), previous_tracking_status: item.tracking_status, reason: body.reason, claimed_name: actor, audit_event_id: `f2000000-0000-4000-8000-${String(decisions.length + 1).padStart(12, "0")}`, cleared_recheck_signal: item.recheck_signal });
      histories.set(item.id, decisions);
      if (item.recheck_signal) {
        const events = recheckEvents.get(item.id) ?? [];
        events.unshift({ kind: "cleared_by_decision", link_id: item.recheck_signal_link_id, actor_kind: "human", claimed_name: actor, created_at: "2026-09-02T01:00:00Z", note_present: false });
        recheckEvents.set(item.id, events);
      }
      item.tracking_status = body.tracking_status as OpportunityTrackingStatus;
      item.tracking_reason = item.tracking_status === "미선택" ? null : body.reason;
      item.tracking_selected_by = item.tracking_status === "미선택" ? null : actor;
      item.tracking_selected_at = item.tracking_status === "미선택" ? null : decisions[0].decided_at;
      item.recheck_signal = false; item.recheck_signal_at = null; item.recheck_signal_link_id = null;
      item.action_reasons = mockActionReasons(item);
      item.section = mockTrackingSection(item);
      await fulfillJson(route, item);
      return;
    }
    await route.fallback();
  });
}

export async function mockBidDeltaDecisionQueue(page: Page, items: BidDeltaDecisionQueueItem[] = decisionQueueItems): Promise<void> {
  const pending = () => items.filter((item) => item.bid_notice_external_id !== null && (item.latest_final_decision === null || item.decision_currentness === "stale"));
  workloadProvider(page, "bid_final_decision_pending", () => ({ count: pending().length, unavailable_reason: null }));
  await page.route("**/api/bid-delta/decision-queue**", async (route) => {
    const search = new URL(route.request().url()).searchParams;
    const filtered = search.get("status") === "all" ? items : pending();
    const limit = Number(search.get("limit") ?? 50), offset = Number(search.get("offset") ?? 0);
    await fulfillJson(route, { items: filtered.slice(offset, offset + limit), total: filtered.length, limit, offset });
  });
}

export async function mockWorkload(page: Page, response: WorkloadResponse): Promise<void> {
  await page.route("**/api/workload", (route) => fulfillJson(route, response));
}

export const visualPreSpecNotice = {
  id: 991,
  notice_key: "pre-spec:991",
  run_id: "source-run-not-used-for-routing",
  title: "안전한 문서 준비 사전규격",
  agency: "테스트 조달기관",
  published_at: "2026-08-30T00:00:00Z",
  deadline_at: "2026-09-02T00:00:00Z",
  estimated_price: null,
  sample_role: null,
  sample_stratum: null,
  collection_bucket: null,
  grade: "우선 검토",
  readiness: null,
  focus: null,
  attachment_count: 2,
  attachment_status: "g2b",
  bid_no: null,
  bid_ord: null,
  source_type: "pre_spec",
  budget: 510_000_000,
  method: null,
  url: "https://example.invalid/pre-specs/991",
  timezone: "Asia/Seoul",
  procurement_class: null,
  region_limit: null,
  lifecycle: { pre_spec_no: "PRE-991" },
  qualification_flags: { sw_business_status: "Y" },
  focus_matches: [],
  performance_matches: [],
  performance_top_score: null,
  candidate_sources: [],
  judgment: null,
  attachments: [],
  reviews: [],
};

const visualPreSpecItems: PreSpecListItem[] = [
  {
    review_exclusion_status: "included",
    review_exclusion_actor_name: null,
    review_exclusion_reason: null,
    review_exclusion_changed_at: null,
    notice_pk: 991,
    pre_spec_no: "PRE-991",
    title: "안전한 문서 준비 사전규격",
    agency: "테스트 조달기관",
    published_at: "2026-08-30T00:00:00Z",
    deadline_at: "2026-09-02T00:00:00Z",
    budget: 510_000_000,
    sw_business_status: "N",
    business_division: "일반용역",
    origin: "추적",
    opportunity_id: 202,
    tracking_status: "종료",
    kept_by_tracking: true,
    document: { attachments: 2, "완료": 0, "대기": 0, "진행": 0, "차단": 1, "실패": 1 },
    overview_review_status: "needs_human_review",
    grade: "우선 검토",
    grade_source: "screening_judgment",
    display_assessment: {
      grade: "우선 검토", status: "graded", source: "screening_judgment",
      basis_run_id: null, assessed_at: null, quality_status: null,
      reason_codes: [], axes: [], verification_items: [], semantic_status: null, semantic_scope: [], latest_run_status: "needs_human_review",
    },
    auto_preparation_status: "blocked",
    auto_preparation_reason: "bundle_has_blocking_issues",
    latest_deep_review_id: null,
    first_observed_at: "2026-09-14T00:00:00Z",
    last_observed_at: "2026-09-15T00:00:00Z",
    next_action: "confirm_overview",
  },
  {
    review_exclusion_status: "included",
    review_exclusion_actor_name: null,
    review_exclusion_reason: null,
    review_exclusion_changed_at: null,
    notice_pk: 992,
    pre_spec_no: "PRE-992",
    title: "신규 지능형 행정 지원 사전규격",
    agency: "신규 발주기관",
    published_at: "2026-08-31T00:00:00Z",
    deadline_at: "2026-09-07T00:00:00Z",
    budget: null,
    sw_business_status: "Y",
    business_division: "일반용역",
    origin: "신규",
    opportunity_id: 78,
    tracking_status: "미선택",
    kept_by_tracking: false,
    document: { attachments: 1, "완료": 1, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
    overview_review_status: "failed",
    grade: null,
    grade_source: null,
    display_assessment: {
      grade: null, status: "none", source: "none", basis_run_id: null,
      assessed_at: null, quality_status: null, reason_codes: [], axes: [],
      verification_items: [], semantic_status: null, semantic_scope: [], latest_run_status: "failed",
    },
    auto_preparation_status: "not_applicable",
    auto_preparation_reason: null,
    latest_deep_review_id: null,
    first_observed_at: "2026-09-14T00:00:00Z",
    last_observed_at: "2026-09-14T00:00:00Z",
    next_action: null,
  },
  clickReadyUnlinkedPreSpec,
];

// 사전규격 개요 검토 상태 10값 + null(개요 검토 미시작) — PLAN.md 3단계
// 게이트("10값이 모두 그룹으로 표현됨")를 목업에서도 항상 채운다.
const ALL_OVERVIEW_STATUSES: (string | null)[] = [
  "awaiting_document",
  "awaiting_structure",
  "preparing",
  "awaiting_model",
  "queued",
  "running",
  "needs_human_review",
  "completed",
  "failed",
  "cancelled",
  null,
];

function overviewStatusCounts(items: readonly { overview_review_status: string | null }[]) {
  return ALL_OVERVIEW_STATUSES.map((status) => ({
    status,
    count: items.filter((item) => item.overview_review_status === status).length,
  }));
}

type FixtureObservation = { source_run_id: string; observed_at: string };

const PRE_SPEC_OBSERVATIONS: Record<number, FixtureObservation[]> = {
  991: [
    { source_run_id: "pre-spec-run-a", observed_at: "2026-09-14T00:00:00Z" },
    { source_run_id: "pre-spec-run-b", observed_at: "2026-09-15T00:00:00Z" },
  ],
  992: [{ source_run_id: "pre-spec-run-b", observed_at: "2026-09-14T00:00:00Z" }],
  993: [{ source_run_id: "pre-spec-run-c", observed_at: "2026-09-16T00:00:00Z" }],
};

const PRE_SPEC_RUNS: RunSummary[] = [
  {
    kind: "notices",
    run_id: "pre-spec-run-c",
    window_from: "2026-09-16",
    window_to: "2026-09-16",
    timezone: "Asia/Seoul",
    generated_at: "2026-09-16T01:00:00Z",
    screening_basis: null,
    status: "active",
    superseded_by: null,
    counts: { notices: 1, judgments: 0, reviews: 0, collection: {} },
  },
  {
    kind: "mixed",
    run_id: "pre-spec-run-b",
    window_from: "2026-09-14",
    window_to: "2026-09-15",
    timezone: "Asia/Seoul",
    generated_at: "2026-09-15T01:00:00Z",
    screening_basis: null,
    status: "active",
    superseded_by: null,
    counts: { notices: 2, judgments: 0, reviews: 0, collection: {} },
  },
  {
    kind: "notices",
    run_id: "pre-spec-run-a",
    window_from: "2026-09-14",
    window_to: "2026-09-14",
    timezone: "Asia/Seoul",
    generated_at: "2026-09-14T01:00:00Z",
    screening_basis: null,
    status: "active",
    superseded_by: null,
    counts: { notices: 1, judgments: 0, reviews: 0, collection: {} },
  },
];

function kstDate(value: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(value));
  const part = (type: string) => parts.find((entry) => entry.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function shiftDate(value: string, days: number): string {
  const [year, month, day] = value.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, day));
  shifted.setUTCDate(shifted.getUTCDate() + days);
  return shifted.toISOString().slice(0, 10);
}

function recentRange(): { from: string; to: string } {
  const to = kstDate(new Date().toISOString());
  return { from: shiftDate(to, -6), to };
}

function observationsFor(item: Pick<PreSpecListItem, "notice_pk" | "first_observed_at" | "last_observed_at">): FixtureObservation[] {
  return PRE_SPEC_OBSERVATIONS[item.notice_pk] ?? (item.first_observed_at && item.last_observed_at
    ? [{ source_run_id: "pre-spec-run-default", observed_at: item.last_observed_at }]
    : []);
}

function matchesObservation(item: PreSpecListItem, sourceRunId: string | null, from: string | null, to: string | null): boolean {
  return observationsFor(item).some((observation) => {
    if (sourceRunId && observation.source_run_id !== sourceRunId) return false;
    const day = kstDate(observation.observed_at);
    return (!from || day >= from) && (!to || day <= to);
  });
}

function matchesOverviewView(item: PreSpecListItem, view: string | null): boolean {
  if (!view || view === "all") return true;
  if (view === "attention") return item.overview_review_status === "needs_human_review";
  if (view === "pending") return ["awaiting_document", "awaiting_structure", "preparing", "awaiting_model", "queued", "running"].includes(item.overview_review_status ?? "");
  if (view === "not_started") return item.overview_review_status === null;
  return item.overview_review_status === view;
}

function isPendingTracking(item: PreSpecListItem): boolean {
  return item.origin === "신규" && (item.tracking_status === null || item.tracking_status === "미선택");
}

/**
 * 마감 판정의 기준 시각. **실제 시계가 아니라 고정 시계다.**
 *
 * 화면 검사는 `page.clock.setFixedTime`으로 브라우저 시계를 2026-08-25·08-31에
 * 고정해 두고, 이 파일의 사전규격 표본 마감(`2026-09-02`·`09-07`·`09-10`)은 그
 * 고정 시각 기준으로 "마감 전"이 되도록 쓰인 값이다. 여기서 `Date.now()`를 쓰면
 * 벽시계가 흐르는 것만으로 같은 표본이 어느 날부터 "마감 경과"가 되어 기본 보기가
 * 비고, 결함이 아닌 실패가 난다. 두 고정 시계보다 뒤이면서 표본 마감보다 앞인
 * 값 하나를 쓴다.
 *
 * `deadline_scope`와 `deadline_status`가 **같은 값**을 쓴다. 한 가짜 안에서 두
 * 술어가 서로 다른 시계를 보면 같은 표본이 구간과 상태에서 다르게 분류되고,
 * 그 불일치가 실제 결함을 가린다(가짜는 실제 계약에서 파생한다 — CLAUDE.md).
 * 실제 서버는 요청 시각을 쓰므로 이 고정 시계는 표본 노후화를 막기 위한
 * 가짜 전용 장치다. 근본 해법은 표본 마감을 `sampleNow + N일` 상대값으로 쓰는
 * 것이며(`tests/screen-fixtures.ts:197`이 이미 그 방식이다) fixture 전반 손질이라
 * 이번 범위 밖이다.
 */
const DEADLINE_FIXTURE_NOW = Date.parse("2026-09-01T00:00:00Z");

/** 서버 `deadline_scope` 술어. `deadline_at`이 null이면 `current`에 남는다. */
function matchesDeadlineScope(item: PreSpecListItem, scope: string | null): boolean {
  if (!scope || scope === "all") return true;
  const passed = item.deadline_at !== null && Date.parse(item.deadline_at) < DEADLINE_FIXTURE_NOW;
  return scope === "passed" ? passed : !passed;
}

function matchesWorkspace(
  item: PreSpecListItem,
  workspace: string | null,
  from: string | null,
  to: string | null,
  sourceRunId: string | null = null,
  deadlineScope: string | null = null,
): boolean {
  if (item.review_exclusion_status === "excluded" && (workspace === "actionable" || workspace === "recent")) return false;
  if (!workspace || workspace === "all") return true;
  if (workspace === "tracking") return item.tracking_status === "계속 추적" || item.tracking_status === "보류";
  if (workspace === "recent") return matchesObservation(item, sourceRunId, from, to);
  // 구간은 actionable 술어의 일부다(ADR-0064 결정 4). 위 세 분기는 구간을 읽지
  // 않으므로 `recent`·`tracking`·`all` 칸은 구간에 대해 불변이다.
  if (!matchesDeadlineScope(item, deadlineScope)) return false;
  return item.overview_review_status === "needs_human_review"
    || item.auto_preparation_status === "deep_review_ready_for_click"
    || (item.overview_review_status === "completed" && isPendingTracking(item));
}

function matchesDeadlineStatus(item: PreSpecListItem, status: string | null): boolean {
  if (!status) return true;
  if (item.deadline_at === null) return status === "unknown";
  // 구간과 같은 고정 시계를 쓴다 — 위 `DEADLINE_FIXTURE_NOW` 주석 참조.
  const passed = Date.parse(item.deadline_at) < DEADLINE_FIXTURE_NOW;
  return status === "passed" ? passed : status === "open" ? !passed : false;
}

function preSpecMatches(item: PreSpecListItem, search: URLSearchParams, includeWorkspace = true): boolean {
  const exclusion = search.get("review_exclusion");
  if (exclusion && exclusion !== "all" && item.review_exclusion_status !== exclusion) return false;
  const observedFrom = search.get("observed_from");
  const observedTo = search.get("observed_to");
  const workspace = search.get("workspace");
  const recentDefaults = !observedFrom && !observedTo ? recentRange() : null;
  const recentFrom = observedFrom ?? recentDefaults?.from ?? null;
  const recentTo = observedTo ?? recentDefaults?.to ?? null;
  const sourceRunId = search.get("source_run_id");
  if (includeWorkspace && !matchesWorkspace(
    item,
    workspace,
    workspace === "recent" ? recentFrom : null,
    workspace === "recent" ? recentTo : null,
    workspace === "recent" ? sourceRunId : null,
    search.get("deadline_scope"),
  )) return false;
  if (!matchesOverviewView(item, search.get("overview_view"))) return false;
  const grade = search.get("grade");
  if (grade && (grade === "판정 없음" ? item.grade !== null : item.grade !== grade)) return false;
  if (search.get("tracking_decision") === "pending" && !isPendingTracking(item)) return false;
  if (search.get("tracking_status") && item.tracking_status !== search.get("tracking_status")) return false;
  if (sourceRunId && !matchesObservation(item, sourceRunId, observedFrom, observedTo)) return false;
  if (observedFrom || observedTo) {
    if (!matchesObservation(item, null, observedFrom, observedTo)) return false;
  }
  const query = search.get("q");
  if (query && searchKey(query) && !searchMatches(query, item.title, item.agency)) return false;
  if (!matchesDeadlineStatus(item, search.get("deadline_status"))) return false;
  return true;
}

function workspaceCounts(items: readonly PreSpecListItem[], search: URLSearchParams): Record<string, number> {
  const counts: Record<string, number> = {};
  const observedFrom = search.get("observed_from");
  const observedTo = search.get("observed_to");
  const defaults = !observedFrom && !observedTo ? recentRange() : null;
  const from = observedFrom ?? defaults?.from ?? null;
  const to = observedTo ?? defaults?.to ?? null;
  const sourceRunId = search.get("source_run_id");
  for (const workspace of ["actionable", "recent", "tracking", "all"]) {
    counts[workspace] = items.filter((item) => matchesWorkspace(
      item,
      workspace,
      workspace === "recent" ? from : null,
      workspace === "recent" ? to : null,
      workspace === "recent" ? sourceRunId : null,
      // 구간은 `matchesWorkspace`의 actionable 분기에서만 걸린다. 그래서 활성
      // workspace와 무관하게 넘겨도 actionable 칸만 바뀐다.
      search.get("deadline_scope"),
    )).length;
  }
  return counts;
}

/**
 * 구간 적용 **전** actionable 집합을 두 구간으로 나눈 건수(ADR-0064 결정 5).
 * 활성 workspace·활성 구간과 무관하게 언제나 같은 값이라 `deadline_scope`를
 * 넘기지 않고 센다. 기준 집합은 `workspaceCounts`와 같은 unscoped 목록이다.
 */
function deadlineScopeCounts(items: readonly PreSpecListItem[]): { current: number; passed: number } {
  const actionable = items.filter((item) => matchesWorkspace(item, "actionable", null, null, null, "all"));
  const passed = actionable.filter((item) => !matchesDeadlineScope(item, "current")).length;
  return { current: actionable.length - passed, passed };
}

function compareFixtureItems(left: PreSpecListItem, right: PreSpecListItem, sort: string | null): number {
  const leftValue = sort === "deadline" ? left.deadline_at : sort === "observed" ? left.last_observed_at : left.published_at;
  const rightValue = sort === "deadline" ? right.deadline_at : sort === "observed" ? right.last_observed_at : right.published_at;
  if (leftValue === null && rightValue !== null) return 1;
  if (leftValue !== null && rightValue === null) return -1;
  if (leftValue !== null && rightValue !== null && leftValue !== rightValue) {
    if (sort === "deadline") {
      // 마감 3버킷 정렬도 구간·상태와 같은 고정 시계를 쓴다. 셋이 다른 시계를
      // 보면 같은 표본의 분류와 순서가 어긋난다(`DEADLINE_FIXTURE_NOW` 참조).
      const leftPassed = Date.parse(leftValue) < DEADLINE_FIXTURE_NOW;
      const rightPassed = Date.parse(rightValue) < DEADLINE_FIXTURE_NOW;
      if (leftPassed !== rightPassed) return leftPassed ? 1 : -1;
      if (leftPassed) return leftValue < rightValue ? 1 : -1;
      return leftValue < rightValue ? -1 : 1;
    }
    return leftValue < rightValue ? 1 : -1;
  }
  return sort === "deadline" ? left.notice_pk - right.notice_pk : right.notice_pk - left.notice_pk;
}

// ── 사전규격 개요 검토(`bidops.prespec-overview.v1`) ────────────────────────
// 백엔드는 아직 없다(P7 병행). 화면이 읽는 것은 계약 정본(docs/contracts.md
// "사전규격 개요 검토 (MVP, 2026-09-11)")과 그 envelope 부록의 run 하나뿐이므로
// 상태별 fixture를 여기서 만든다. 화면은 이 envelope을 `toPageOverviewResponse`로
// 옮겨 읽는다.

const OVERVIEW_SCHEMA = "bidops.prespec-overview.v1";

export function overviewRunFixture(
  overrides: Partial<OverviewRun> & Pick<OverviewRun, "id" | "status">,
): OverviewRun {
  return {
    range_source: "auto",
    page_start: 3,
    page_end: 11,
    range_reason_codes: ["heading_scope"],
    reason_codes: [],
    warnings: [],
    result: null,
    failed_claims: [],
    model_name: "qwen3.8-27B",
    model_revision: "e".repeat(64),
    call_count: 2,
    actor_name: null,
    created_at: "2026-09-05T02:00:00Z",
    started_at: "2026-09-05T02:00:05Z",
    completed_at: "2026-09-05T02:04:00Z",
    result_id: null,
    prompt_version: "prespec-overview-v6",
    verification_status: null,
    document_version_id: "00000000-0000-0000-0000-000000000001",
    source_sha256: "a".repeat(64),
    pdf_sha256: "b".repeat(64),
    pdf_page_count: 79,
    reviewed_pages: [3, 4, 5, 6, 7, 8, 9, 10, 11],
    payload_sha256: "c".repeat(64),
    quality_status: "unmeasured_reference",
    validation_status: "failed",
    validation_errors: [],
    evidence_check_status: "failed",
    evidence_check_errors: [],
    ...overrides,
  };
}

/** 완료된 run 하나. 결과 본문이 있으므로 화면의 개요 본문 자리를 채운다. */
export const overviewCompletedRunFixture = overviewRunFixture({
  id: "b1a7f0c2-1111-4a11-9c11-000000000001",
  status: "completed",
  result_id: "b1a7f0c2-1111-4a11-9c11-000000000001",
  verification_status: "passed",
  validation_status: "passed",
  evidence_check_status: "passed",
  warnings: ["quantity_metadata_mismatch", "date_mismatch", "claims_dropped"],
  failed_claims: [{
    claim_id: "c9",
    section: "important_conditions",
    text: "하도급 비율은 30% 이하여야 한다.",
    reason_codes: ["quote_not_found"],
    evidence: [],
  }],
  result: {
    business_overview: [{
      claim_id: "c1",
      text: "차세대 통합 데이터 플랫폼을 구축하는 사업이다.",
      evidence: [{ page: 3, quote: "차세대 통합 데이터 플랫폼 구축" }],
    }],
    main_tasks: [{
      claim_id: "c2",
      text: "기존 데이터를 신규 플랫폼으로 이관하고 검증한다.",
      evidence: [{ page: 5, quote: "데이터 이관 및 검증" }, { page: 6, quote: "이관 결과 검증" }],
    }],
    budget_and_period: [{
      claim_id: "c3",
      text: "사업 예산은 510,000,000원(VAT 포함)이고 수행기간은 10개월이다.",
      evidence: [{ page: 4, quote: "사업예산 510,000,000원(VAT 포함)" }],
    }],
    // v7 이후 응답은 important_conditions·reviewer_analysis·unknowns 키 자체가
    // 없다(ADR-0057 결정 1). 참여 조건·위험/미확인은 심층 검토 결과가 갖는다.
    input_limitations: ["3~11쪽의 본문 텍스트만 읽었다."],
  },
});

/** 사람 확인이 필요한 run. 결과 본문이 없고 검증 진단이 함께 온다. */
export const overviewNeedsHumanReviewRunFixture = overviewRunFixture({
  id: "b1a7f0c2-2222-4a22-9c22-000000000002",
  status: "needs_human_review",
  verification_status: "needs_human_review",
  reason_codes: ["quote_not_found"],
  created_at: "2026-09-06T02:00:00Z",
  failed_claims: [{
    claim_id: "c7",
    section: "budget_and_period",
    text: "사업 예산은 700,000,000원이다.",
    reason_codes: ["quote_not_found", "quantity_mismatch"],
    evidence: [{ page: 4, quote: "사업예산 510,000,000원(VAT 포함)" }],
  }],
});

export const overviewVerificationFixture: NonNullable<OverviewEnvelope["verification"]> = {
  verification_id: overviewNeedsHumanReviewRunFixture.id,
  status: "needs_human_review",
  reason_codes: ["required_fact_missing"],
  claims: [{
    claim_id: "c7",
    section: "budget_and_period",
    text: "사업 예산은 700,000,000원이다.",
    deterministic: { status: "failed", reason_codes: ["quantity_mismatch"] },
    semantic: { status: "not_run", reason_codes: [] },
    verified_evidence: [{ page: 4, quote: "사업예산 510,000,000원(VAT 포함)", start_char: 20, end_char: 42 }],
  }],
};

/** 앞부분 fallback으로 대기 중인 run. 활성 run이므로 범위 확정이 막힌다. */
export const overviewFallbackQueuedRunFixture = overviewRunFixture({
  id: "b1a7f0c2-3333-4a33-9c33-000000000003",
  status: "queued",
  range_source: "fallback",
  page_start: 1,
  page_end: 60,
  range_reason_codes: ["range_fallback_head", "scope_heading_missing"],
  call_count: 0,
  started_at: null,
  completed_at: null,
});

export const overviewRangeCandidatesFixture = [
  { index: 0, title: "1. 사업 개요", page: 4, char_count: 120 },
  { index: 1, title: "2. 사업 범위 및 기간", page: 6, char_count: 340 },
  { index: 2, title: "3. 제출 서류", page: 12, char_count: 90 },
];

export function overviewRangeReviewFixture(
  overrides: Partial<NonNullable<OverviewEnvelope["range_review"]>> = {},
): NonNullable<OverviewEnvelope["range_review"]> {
  return {
    target_id: null,
    status: "pending",
    document_version_id: "00000000-0000-0000-0000-000000000001",
    pdf_page_count: 79,
    mode: "clause",
    candidate_status: "complete",
    candidate_count_total: 3,
    candidate_count_returned: 3,
    candidates: overviewRangeCandidatesFixture,
    selected_pages: null,
    warning_codes: [],
    reason_code: "scope_heading_missing",
    can_confirm: true,
    assisted: null,
    confirmation: null,
    ...overrides,
  };
}

export function overviewEnvelopeFixture(
  noticeId: number,
  current: OverviewRun | null,
  history: OverviewRun[] = [],
  extra: Partial<Pick<OverviewEnvelope, "range_review" | "verification">> = {},
): OverviewEnvelope {
  return {
    schema: OVERVIEW_SCHEMA,
    notice_id: noticeId,
    current,
    history,
    range_review: null,
    verification: null,
    ...extra,
  };
}

/** 완료된 개요 + 절 후보가 있는 자동 선택 범위. */
export function overviewCompletedEnvelope(noticeId = 991): OverviewEnvelope {
  return overviewEnvelopeFixture(noticeId, overviewCompletedRunFixture, [overviewCompletedRunFixture], {
    range_review: overviewRangeReviewFixture({
      target_id: overviewCompletedRunFixture.id,
      status: "ready",
      reason_code: null,
      selected_pages: [3, 11],
    }),
  });
}

/** 사람 확인이 필요한 개요 + 주장 검증 진단. */
export function overviewNeedsHumanReviewEnvelope(noticeId = 991): OverviewEnvelope {
  return overviewEnvelopeFixture(
    noticeId,
    overviewNeedsHumanReviewRunFixture,
    [overviewNeedsHumanReviewRunFixture],
    { verification: overviewVerificationFixture },
  );
}

/** 실행은 없고 범위 확정만 기다리는 자리. */
export function overviewPendingRangeEnvelope(noticeId = 991): OverviewEnvelope {
  return overviewEnvelopeFixture(noticeId, null, [], { range_review: overviewRangeReviewFixture() });
}

/** 개요 run도 문서 snapshot도 없는 공고. 없는 것을 실패로 보이게 하지 않는다. */
export function overviewAbsentEnvelope(noticeId = 991): OverviewEnvelope {
  return overviewEnvelopeFixture(noticeId, null);
}

export interface DocumentStructurePageMockTrace {
  pageGets: Array<{ structureId: string; page: number }>;
}

const PRE_SPEC_STRUCTURE_ID = "30000000-0000-0000-0000-000000000991";

function preSpecStructurePage() {
  return {
    structure_id: PRE_SPEC_STRUCTURE_ID,
    page: 2,
    metadata: {
      number: 2,
      width: 1200,
      height: 1700,
      image_content_object_id: "image-content-do-not-render",
    },
    blocks: [
      {
        block_key: "overview-heading",
        parent_block_key: null,
        type: "heading",
        page: 2,
        bbox: [910, 920, 930, 940],
        text: "1. 사업 개요와 추진 배경",
        confidence: 0.42,
        attributes: { internal_marker: "do-not-render-attributes" },
      },
      {
        block_key: "overview-intro",
        parent_block_key: "overview-heading",
        type: "paragraph",
        page: 2,
        bbox: [1010, 1020, 1030, 1040],
        text: "공공기관의 민원·행정 데이터를 통합해 현황을 분석하고 담당자가 업무 현황을 조회하는 행정 지원 플랫폼 구축 사업입니다.",
        confidence: 0.84,
        attributes: { internal_marker: "do-not-render-target-attributes" },
      },
      {
        block_key: "overview-scope",
        parent_block_key: "overview-heading",
        type: "paragraph",
        page: 2,
        bbox: [1110, 1120, 1130, 1140],
        text: "주요 수행 범위는 기존 업무 데이터 연계와 운영 화면 구축입니다.",
        confidence: 0.77,
        attributes: { internal_marker: "do-not-render-following-attributes" },
      },
    ],
  };
}

export async function mockDocumentStructurePage(page: Page): Promise<DocumentStructurePageMockTrace> {
  const trace: DocumentStructurePageMockTrace = { pageGets: [] };
  await page.route("**/api/document-structures/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const match = pathname.match(/^\/api\/document-structures\/([^/]+)\/pages\/(\d+)$/);
    if (!match || request.method() !== "GET") {
      await route.fallback();
      return;
    }

    const structureId = decodeURIComponent(match[1]);
    const pageNumber = Number(match[2]);
    trace.pageGets.push({ structureId, page: pageNumber });
    const validPage = structureId === PRE_SPEC_STRUCTURE_ID && pageNumber === 2;
    await route.fulfill({
      status: validPage ? 200 : 404,
      contentType: "application/json",
      body: JSON.stringify(validPage ? preSpecStructurePage() : { detail: "document page not found" }),
    });
  });
  return trace;
}

/** Deterministic pre-spec list/detail fixture. */
export const inheritedPreSpecOpportunity = {
  ...visualOpportunities[0],
  id: 202,
  tracking_status: "계속 추적" as const,
  tracking_reason: "발주계획 단계에서 핵심 과업 부합으로 추적 시작",
  tracking_selected_by: "발주계획 담당자",
  tracking_selected_at: "2026-08-20T09:00:00Z",
};

export async function mockPreSpecs(page: Page): Promise<void> {
  let currentTrackingStatus = visualPreSpecItems[0].tracking_status;
  await page.route("**/api/runs", async (route) => {
    const request = route.request();
    if (new URL(request.url()).pathname === "/api/runs" && request.method() === "GET") {
      // 사전규격 전용 회차만 돌려주면 다른 화면이 주소로 지정한 기본 회차
      // (예: route-context 검증의 RUN_ID)가 목록에서 사라져 셸의 기본 선택
      // 로직으로 튕긴다. 공용 기본 목록과 합쳐 run_id 기준으로 중복을
      // 제거하고, 실제 API처럼 generated_at 내림차순으로 정렬한다.
      const defaultRuns = (responses["/api/runs"] as { items?: RunSummary[] } | undefined)?.items ?? [];
      const merged = new Map<string, RunSummary>();
      for (const run of defaultRuns) merged.set(run.run_id, run);
      for (const run of PRE_SPEC_RUNS) merged.set(run.run_id, run);
      const items = [...merged.values()].sort((a, b) => b.generated_at.localeCompare(a.generated_at));
      await fulfillJson(route, { items, total: items.length });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/opportunities/202", async (route) => {
    if (opportunityFixtures.has(page) || route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await fulfillJson(route, inheritedPreSpecOpportunity);
  });
  workloadProvider(page, "pre_spec_deep_review_ready", () => ({ count: visualPreSpecItems.filter((item) => item.auto_preparation_status === "deep_review_ready_for_click").length, unavailable_reason: null }));
  await page.route("**/api/pre-specs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/pre-specs" && request.method() === "GET") {
      const requestedNoticePk = Number(url.searchParams.get("notice_pk"));
      const candidateItems = visualPreSpecItems
        .map((item) => item.notice_pk === 991 ? { ...item, tracking_status: opportunityFixtures.get(page)?.find((entry) => entry.id === 202)?.tracking_status ?? currentTrackingStatus } : item)
        .filter((item) => !url.searchParams.has("notice_pk") || item.notice_pk === requestedNoticePk)
        .filter((item) => url.searchParams.get("sw_only") === "false" || item.sw_business_status === "Y" || item.kept_by_tracking)
        .filter((item) => !url.searchParams.get("auto_preparation_status") || item.auto_preparation_status === url.searchParams.get("auto_preparation_status"))
        .filter((item) => !url.searchParams.get("business_division") || item.business_division === url.searchParams.get("business_division"))
        .filter((item) => !url.searchParams.get("origin") || item.origin === url.searchParams.get("origin"))
        .filter((item) => {
          const query = url.searchParams.get("q");
          return !query || !searchKey(query) || searchMatches(query, item.title, item.agency);
        })
      const allItems = candidateItems.filter((item) => preSpecMatches(item, url.searchParams));
      const unscoped = candidateItems.filter((item) => preSpecMatches(item, url.searchParams, false));
      const sort = url.searchParams.get("sort") ?? (url.searchParams.get("workspace") === "actionable" ? "deadline" : url.searchParams.get("workspace") === "recent" ? "observed" : "published");
      const items = [...allItems].sort((left, right) => compareFixtureItems(left, right, sort));
      const statusSearch = new URLSearchParams(url.searchParams);
      statusSearch.delete("overview_view");
      const statusItems = candidateItems.filter((item) => preSpecMatches(item, statusSearch));
      const limit = Number(url.searchParams.get("limit") ?? 50), offset = Number(url.searchParams.get("offset") ?? 0);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: items.slice(offset, offset + limit),
          total: items.length,
          limit,
          offset,
          overview_status_counts: overviewStatusCounts(statusItems),
          workspace_counts: workspaceCounts(unscoped, url.searchParams),
          deadline_scope_counts: deadlineScopeCounts(unscoped),
        }),
      });
      return;
    }
    const candidatesMatch = url.pathname.match(/^\/api\/pre-specs\/(\d+)\/order-plan-candidates$/);
    if (candidatesMatch && request.method() === "GET") {
      const notice_pk = Number(candidatesMatch[1]);
      const response: PreSpecOrderPlanCandidatesResponse = { notice_pk, items: [] };
      await fulfillJson(route, response);
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/opportunities/*/tracking-status", async (route) => {
    if (opportunityFixtures.has(page)) { await route.fallback(); return; }
    const request = route.request();
    if (request.method() !== "PATCH") {
      await route.fallback();
      return;
    }
    const match = new URL(request.url()).pathname.match(/^\/api\/opportunities\/(\d+)\/tracking-status$/);
    const body = request.postDataJSON() as { tracking_status?: string; reason?: string };
    if (!match || Number(match[1]) !== 202 || !body.tracking_status || !body.reason?.trim()) {
      await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "tracking_reason_required" }) });
      return;
    }
    currentTrackingStatus = body.tracking_status as OpportunityTrackingStatus;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 202,
        section: currentTrackingStatus === "계속 추적" ? "추적 중" : currentTrackingStatus === "보류" ? "보류" : currentTrackingStatus === "종료" ? "추적 종료" : null,
        pending_candidate_link_count: 0, open_blocking_item_count: 0,
        action_reasons: [], hold_review_due_at: null,
        tracking_status: currentTrackingStatus,
        tracking_reason: body.reason,
        tracking_selected_by: request.headers()["x-bidops-actor-name"] ?? "시각 테스트 담당자",
        tracking_selected_at: "2026-09-01T00:00:00Z",
        recheck_signal: false,
        recheck_signal_at: null,
        recheck_signal_link_id: null,
        first_registered_stage: "order_plan",
        links: [],
      }),
    });
  });
  await page.route("**/api/notices/991", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(visualPreSpecNotice) });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/notices/991/document-bundles", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) });
      return;
    }
    await route.fallback();
  });
}

// 명세 §6.8 게이트: 자동 준비 8값과 등급 4값 + `판정 없음`이 화면에 **문자로**
// 나타나는지 의미 층이 확인할 수 있게, 한 응답 안에 여덟 행을 모두 담는다.
const AUTO_PREPARATION_MATRIX = [
  { status: "not_applicable", grade: null, reason: "grade_not_priority", deepReviewId: null },
  { status: "waiting_attachments", grade: "우선 검토", reason: "awaiting_fetch", deepReviewId: null },
  { status: "bundle_draft", grade: "우선 검토", reason: "human_bundle_draft", deepReviewId: null },
  { status: "bundle_ready", grade: "검토 권장", reason: null, deepReviewId: null },
  { status: "overview_running", grade: "검토 권장", reason: "overview_not_completed", deepReviewId: null },
  { status: "deep_review_started", grade: "우선 검토", reason: null, deepReviewId: "fixture-review" },
  { status: "deep_review_ready_for_click", grade: "관찰 대상", reason: "bundle_not_auto_ready", deepReviewId: null },
  { status: "blocked", grade: "제외", reason: "bundle_has_blocking_issues", deepReviewId: null },
] as const;

const preSpecMatrixItems = AUTO_PREPARATION_MATRIX.map((entry, index) => ({
  review_exclusion_status: "included",
  review_exclusion_actor_name: null,
  review_exclusion_reason: null,
  review_exclusion_changed_at: null,
  notice_pk: 8001 + index,
  pre_spec_no: `PRE-${8001 + index}`,
  title: `자동 준비 표본 ${index + 1}`,
  agency: "표본 발주기관",
  published_at: "2026-08-30T00:00:00Z",
  deadline_at: "2026-09-10T00:00:00Z",
  budget: 100_000_000,
  sw_business_status: "Y",
  business_division: "일반용역",
  origin: "신규",
  opportunity_id: null,
  tracking_status: null,
  kept_by_tracking: false,
  document: { attachments: 1, "완료": 1, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
  overview_review_status: "needs_human_review",
  grade: entry.grade,
  grade_source: entry.grade === null ? null : "screening_judgment",
  auto_preparation_status: entry.status,
  auto_preparation_reason: entry.reason,
  latest_deep_review_id: entry.deepReviewId,
  first_observed_at: `2026-09-${String(10 + index).padStart(2, "0")}T00:00:00Z`,
  last_observed_at: `2026-09-${String(10 + index).padStart(2, "0")}T00:00:00Z`,
  next_action: entry.status === "deep_review_ready_for_click" ? "open_deep_review" : "confirm_overview",
}));

/** 등급·자동 준비 8값을 한 화면에 올리는 사전규격 목록 fixture. */
export async function mockPreSpecMatrix(page: Page): Promise<void> {
  await page.route("**/api/pre-specs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname !== "/api/pre-specs" || request.method() !== "GET") {
      await route.fallback();
      return;
    }
    const candidates = preSpecMatrixItems.filter((item) => preSpecMatches(item as PreSpecListItem, url.searchParams));
    const unscoped = preSpecMatrixItems.filter((item) => preSpecMatches(item as PreSpecListItem, url.searchParams, false));
    const limit = Number(url.searchParams.get("limit") ?? 200);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const statusSearch = new URLSearchParams(url.searchParams);
    statusSearch.delete("overview_view");
    const statusItems = preSpecMatrixItems.filter((item) => preSpecMatches(item as PreSpecListItem, statusSearch));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: candidates.slice(offset, offset + limit),
        total: candidates.length,
        limit,
        offset,
        overview_status_counts: overviewStatusCounts(statusItems),
        workspace_counts: workspaceCounts(unscoped as PreSpecListItem[], url.searchParams),
        deadline_scope_counts: deadlineScopeCounts(unscoped as PreSpecListItem[]),
      }),
    });
  });
}

/**
 * 마감 구간 전환(ADR-0064)의 표본. `검토할 항목`에 **마감 전 1 · 마감 미확인 1 ·
 * 마감 경과 2**를 둬서 구간이 목록과 건수를 실제로 가르는지 볼 수 있게 한다.
 *
 * 기존 `visualPreSpecItems`에 마감 경과 건을 더하지 않은 이유: 그 표본의 행 수와
 * 건수 문구에 기대는 spec이 여럿이라 한 행만 늘려도 이 작업과 무관한 검사가
 * 깨진다. 마감 날짜는 {@link DEADLINE_SCOPE_FIXTURE_NOW}와 실제 시계 어느 쪽으로
 * 읽어도 같은 구간이 되도록 멀찍이 잡는다.
 */
const preSpecDeadlineScopeItems: PreSpecListItem[] = ([
  { notice_pk: 8201, title: "마감 전 사전규격 표본", deadline_at: "2026-12-01T00:00:00Z" },
  { notice_pk: 8202, title: "마감 미확인 사전규격 표본", deadline_at: null },
  { notice_pk: 8203, title: "마감 경과 사전규격 표본 가", deadline_at: "2026-08-20T00:00:00Z" },
  { notice_pk: 8204, title: "마감 경과 사전규격 표본 나", deadline_at: "2026-08-18T00:00:00Z" },
] as const).map((entry) => ({
  review_exclusion_status: "included",
  review_exclusion_actor_name: null,
  review_exclusion_reason: null,
  review_exclusion_changed_at: null,
  notice_pk: entry.notice_pk,
  pre_spec_no: `PRE-${entry.notice_pk}`,
  title: entry.title,
  agency: "표본 발주기관",
  published_at: "2026-08-10T00:00:00Z",
  deadline_at: entry.deadline_at,
  budget: 100_000_000,
  sw_business_status: "Y",
  business_division: "일반용역",
  origin: "신규",
  opportunity_id: null,
  tracking_status: null,
  kept_by_tracking: false,
  document: { attachments: 1, "완료": 1, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
  // 네 건 모두 `사람 확인 필요`라 구간을 빼면 actionable 넷이다.
  overview_review_status: "needs_human_review",
  grade: "우선 검토",
  grade_source: "screening_judgment",
  auto_preparation_status: "not_applicable",
  auto_preparation_reason: null,
  latest_deep_review_id: null,
  first_observed_at: "2026-09-16T00:00:00Z",
  last_observed_at: "2026-09-16T00:00:00Z",
  next_action: "confirm_overview",
} as PreSpecListItem));

export async function mockPreSpecDeadlineScope(page: Page): Promise<void> {
  await page.route("**/api/pre-specs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname !== "/api/pre-specs" || request.method() !== "GET") {
      await route.fallback();
      return;
    }
    const items = preSpecDeadlineScopeItems.filter((item) => preSpecMatches(item, url.searchParams));
    const unscoped = preSpecDeadlineScopeItems.filter((item) => preSpecMatches(item, url.searchParams, false));
    const limit = Number(url.searchParams.get("limit") ?? 200);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: items.slice(offset, offset + limit),
        total: items.length,
        limit,
        offset,
        overview_status_counts: overviewStatusCounts(items),
        workspace_counts: workspaceCounts(unscoped, url.searchParams),
        deadline_scope_counts: deadlineScopeCounts(unscoped),
      }),
    });
  });
}

// `corrected`는 사람 정정 등급이 notice의 판정 등급과 **다른** 경우다. 화면이
// 현재 등급 하나만 보여 주는지 확인하려면 두 값이 달라야 한다(명세 §6.2).
export type PreSpecAutoDetailState = "started" | "ready_for_click" | "corrected";

/** 사전규격 상세의 자동 준비 단계 표시와 두 갈래 동선(보고서 링크 · 실행 버튼). */
export async function mockPreSpecAutoDetail(page: Page, state: PreSpecAutoDetailState): Promise<void> {
  const item = {
    ...visualPreSpecItems[0],
    tracking_status: "계속 추적",
    document: { attachments: 3, "완료": 2, "대기": 1, "진행": 0, "차단": 0, "실패": 0 },
    overview_review_status: "completed",
    // notice(`visualPreSpecNotice`)의 판정 등급은 `우선 검토`다. `corrected`는
    // 사람이 `관찰 대상`으로 정정한 상태이며 화면은 정정된 현재 등급만 보여야
    // 한다 — 판정 등급을 라벨 없이 함께 두지 않는다.
    grade: state === "corrected" ? "관찰 대상" : "우선 검토",
    grade_source: state === "started" ? "screening_judgment" : "human_review",
    auto_preparation_status: state === "started" ? "deep_review_started" : "deep_review_ready_for_click",
    auto_preparation_reason: state === "started" ? null : "bundle_not_auto_ready",
    latest_deep_review_id: state === "started" ? "fixture-review" : null,
  };
  await page.route("**/api/pre-specs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/pre-specs" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [item], total: 1, limit: 50, offset: 0, overview_status_counts: overviewStatusCounts([item]), workspace_counts: { actionable: 1, recent: 1, tracking: 1, all: 1 }, deadline_scope_counts: deadlineScopeCounts([item as PreSpecListItem]) }),
      });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/notices/991", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(visualPreSpecNotice) });
  });
  await page.route("**/api/notices/991/document-bundles", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [visualBundle("ready")] }) });
  });
}

/** 보고서 화면의 `quality_status` 네 경우(3값 + 표식 없는 옛 revision). */
export async function mockDeepReviewQuality(
  page: Page,
  quality: "measured" | "unmeasured_reference" | "mock_reference" | null,
): Promise<void> {
  await page.route("**/api/deep-reviews/fixture-review/report", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    const view = syntheticReportView();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...view, report: { ...view.report, quality_status: quality } }),
    });
  });
}

type DocumentPreparationVisualState = "draft" | "processing" | "blocked" | "ready";

function visualDocument(overrides: Record<string, unknown> = {}) {
  return {
    id: "20000000-0000-0000-0000-000000000991",
    bundle_id: "10000000-0000-0000-0000-000000000991",
    version: 1,
    role: "제안요청서",
    effective_date: "2026-09-01",
    replaces_document_version_id: null,
    is_current: true,
    safety_status: "safe",
    structure_status: "ready",
    original_filename: "제안요청서.pdf",
    ...overrides,
  };
}

function visualBundle(state: DocumentPreparationVisualState) {
  const status = state === "draft" ? "draft" : state === "processing" ? "processing" : state === "blocked" ? "needs_review" : "ready";
  const documents = state === "draft"
    ? []
    : [visualDocument(state === "processing"
      ? { safety_status: "scanning", structure_status: "processing", original_filename: "진행중-제안요청서.pdf" }
      : state === "blocked"
        ? { safety_status: "blocked", structure_status: "failed", original_filename: "차단된-부록.pdf" }
        : {})];
  return {
    id: "10000000-0000-0000-0000-000000000991",
    notice_id: 991,
    revision: state === "ready" ? 2 : 1,
    version: state === "ready" ? 5 : 1,
    status,
    documents,
    issues: state === "blocked" ? [{
      issue_id: "fixture-blocking-issue",
      code: "unsafe_document",
      severity: "차단",
      blocking: true,
      document_version_id: "20000000-0000-0000-0000-000000000991",
      message: "안전 검사에 실패한 문서가 있습니다.",
      locator_type: "none",
      locator: null,
    }] : [],
    confirmed_by: state === "ready" ? "이전 담당자" : null,
    confirmed_at: state === "ready" ? "2026-08-31T02:00:00Z" : null,
    created_at: "2026-08-31T00:00:00Z",
  };
}

/** Stable bundle response for visual draft/processing/blocked/ready snapshots. */
export async function mockDocumentPreparationVisual(page: Page, state: DocumentPreparationVisualState): Promise<void> {
  const bundle = visualBundle(state);
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/notices/991" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(visualPreSpecNotice) });
      return;
    }
    if (pathname === "/api/pre-specs" && request.method() === "GET") {
      const search = new URL(request.url()).searchParams;
      const requestedNoticePk = search.has("notice_pk") ? Number(search.get("notice_pk")) : null;
      const items = visualPreSpecItems.filter((item) => requestedNoticePk === null || item.notice_pk === requestedNoticePk);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, total: items.length, limit: 50, offset: 0, overview_status_counts: overviewStatusCounts(items), workspace_counts: { actionable: items.length, recent: items.length, tracking: items.length, all: items.length }, deadline_scope_counts: deadlineScopeCounts(items) }),
      });
      return;
    }
    if (pathname === "/api/notices/991/document-bundles" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [bundle] }) });
      return;
    }
    await route.fallback();
  });
}

/**
 * 기존 시각 응답을 보존하고 v2 경로에는 필터·집계 가능한 합성 서버를 연결한다.
 */
export async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const fitMatch = pathname.match(/^\/api\/pre-specs\/(\d+)\/company-fit$/);
    if (fitMatch) { await fulfillJson(route, { schema_version: "bidops.prespec-company-fit.v1", notice_id: Number(fitMatch[1]), attempts: [], automation_enabled: false, auto_deep_review_reason: "company_fit_disabled", deep_review_id: null }); return; }
    // 개요 run이 없는 공고가 기본값이다. 없는 것을 실패로 보이게 하지 않는다.
    const overviewMatch = pathname.match(/^\/api\/pre-specs\/(\d+)\/overview$/);
    if (overviewMatch) { await fulfillJson(route, overviewAbsentEnvelope(Number(overviewMatch[1]))); return; }

    if (pathname === "/api/workload") { await fulfillJson(route, workloadResponse(page)); return; }
    // deep-review 합성 응답이 먼저, 그다음 갈무리 fixture, 마지막으로 T15 시각
    // 회귀용 생성 응답을 쓴다. 합성 응답은 deep-review 전용 경로만 처리하므로
    // 기존 fixture 우선순위를 가리지 않는다.
    const rawBody =
      syntheticResponse(pathname) ?? responses[pathname] ?? getVisualResponse(pathname, page.url());
    const body = pathname === "/api/profile/sections" || pathname === "/api/profile/unknowns"
      ? safeProfileProjection(pathname, rawBody)
      : rawBody;
    if (body === undefined) {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "고정 응답 없음" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await mockOpportunity(page);
  await mockPreSpecs(page);
  await mockOrderPlans(page);
  await mockBidDeltaDecisionQueue(page);
}

export type OrderPlanMockScenario = "default" | "failure" | "no-results" | "no-completed-execution" | "live-disabled" | "stopped" | "large" | "no-owning-opportunity";
export interface OrderPlanMockTrace {
  feedbackPosts: Array<{ body: unknown; headers: Record<string, string> }>;
  trackingPatches: Array<{ opportunityId: number; body: unknown; headers: Record<string, string> }>;
  executionPosts: Array<{ body: unknown; headers: Record<string, string> }>;
  stopPosts: Array<{ executionId: string; body: unknown; headers: Record<string, string> }>;
}
export interface OrderPlanMockOptions {
  /** 누적 scope의 `activated_policy_versions`. 기본은 mock이 운영 policy로 쓰는 한 버전이다.
      빈 배열이면 "활성화된 적 없는 policy의 운영 실행만 있는" 운영 DB 상태를 흉내낸다. */
  activatedPolicyVersions?: string[];
  omitTracking?: boolean;
  createErrorCode?: OrderPlanScreeningErrorCode;
  stopErrorCode?: OrderPlanScreeningErrorCode;
  errorStatus?: number;
}

interface OrderPlanFeedbackFixture {
  feedback_id: string;
  execution_id: string;
  order_plan_pk: number;
  revision: number;
  relevance: string;
  priority: string | null;
  memo: string | null;
  claimed_name: string;
  created_at: string;
}

const c2Digest = (letter: string): string => (letter.charCodeAt(0) % 16).toString(16).repeat(64);

function c2Execution(overrides: Partial<OrderPlanScreeningExecutionSummary> = {}): OrderPlanScreeningExecutionSummary {
  return {
    execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010101",
    request_id: "b2f4d7c1-0a61-4b07-8d2e-7f1d1d010101",
    source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101",
    policy_version: "c2-policy.v1",
    status: "부분 성공",
    purpose: "operational",
    requested_by: "screening-worker",
    execution_allowed: true,
    population_count: 625,
    population_sha256: c2Digest("p"),
    policy_sha256: c2Digest("a"),
    binding_sha256: c2Digest("b"),
    stage1_binding_version: "bm25-binding.v1",
    stage1_binding_sha256: c2Digest("c"),
    stage2_binding_version: "qwen-binding.v1",
    stage2_binding_sha256: c2Digest("d"),
    counts: {
      candidate_count: 625,
      completed_count: 622,
      failure_count: 3,
      stage1_selected_count: 300,
      stage1_filtered_out_count: 322,
      stage1_failed_count: 3,
      stage2_relevant_count: 1,
      stage2_not_relevant_count: 1,
      stage2_uncertain_count: 1,
      stage2_failed_count: 3,
      stage2_rejected_count: 0,
      human_review_count: 1,
    },
    partial_artifact: true,
    error_code: "batch_schema_violation",
    queued_at: "2026-09-01T02:00:00Z",
    started_at: "2026-09-01T02:00:04Z",
    heartbeat_at: "2026-09-01T02:04:00Z",
    finished_at: "2026-09-01T02:05:00Z",
    ...overrides,
  };
}

const c2OlderSuccess = c2Execution({
  execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d083101",
  request_id: "b2f4d7c1-0a61-4b07-8d2e-7f1d1d083101",
  source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0831",
  status: "성공",
  population_count: 600,
  population_sha256: c2Digest("q"),
  policy_sha256: c2Digest("e"),
  binding_sha256: c2Digest("f"),
  stage1_binding_sha256: c2Digest("g"),
  stage2_binding_sha256: c2Digest("h"),
  counts: {
    candidate_count: 600,
    completed_count: 600,
    failure_count: 0,
    stage1_selected_count: 300,
    stage1_filtered_out_count: 300,
    stage1_failed_count: 0,
    stage2_relevant_count: 2,
    stage2_not_relevant_count: 1,
    stage2_uncertain_count: 1,
    stage2_failed_count: 0,
    stage2_rejected_count: 0,
    human_review_count: 1,
  },
  partial_artifact: false,
  error_code: null,
  queued_at: "2026-08-31T02:00:00Z",
  started_at: "2026-08-31T02:00:02Z",
  heartbeat_at: "2026-08-31T02:03:00Z",
  finished_at: "2026-08-31T02:04:00Z",
});

const c2Failed = c2Execution({
  execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010201",
  request_id: "b2f4d7c1-0a61-4b07-8d2e-7f1d1d010201",
  status: "실패",
  execution_allowed: true,
  error_code: "worker_failed",
  partial_artifact: false,
  queued_at: "2026-09-01T03:00:00Z",
  started_at: "2026-09-01T03:00:02Z",
  heartbeat_at: null,
  finished_at: "2026-09-01T03:01:00Z",
});

const c2Running = c2Execution({
  execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010301",
  request_id: "b2f4d7c1-0a61-4b07-8d2e-7f1d1d010301",
  status: "실행 중",
  execution_allowed: true,
  queued_at: "2026-09-01T04:00:00Z",
  started_at: "2026-09-01T04:00:02Z",
  heartbeat_at: "2026-09-01T04:01:00Z",
  finished_at: null,
  error_code: null,
  partial_artifact: false,
});

/** `execution_id`·`policy_version`·`first_observed_at`은 `listItems()`가 요청 시점에 계산해 붙인다(누적/회차 모드 공통). */
type C2OrderPlanFixtureItem = Omit<OrderPlanListItem, "tracking" | "execution_id" | "policy_version" | "first_observed_at">;

const c2Items: C2OrderPlanFixtureItem[] = [
  {
    order_plan_pk: 101,
    order_plan_unty_no: "OP-2026-00101",
    source_url: "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-2026-00101",
    title: "인공지능 기반 공공데이터 통합·분석 플랫폼 구축 및 운영 지원 사업 발주계획(장기계속계약)",
    agency_name: "서울특별시 디지털정책관",
    business_division: "정보화",
    budget_amount: 125000000,
    planned_order_year: "2026",
    planned_order_month: "2026-11",
    contract_method: "일반경쟁",
    notice_posted: "N",
    source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101",
    observed_at: "2026-09-01T01:00:00Z",
    stage1_status: "selected",
    stage1_rank: 1,
    stage1_score: 0.92,
    nearest_capability: "데이터 플랫폼 구축·운영",
    stage2_status: "success",
    qwen_relevance: "relevant",
    qwen_score: 0.96,
    qwen_reason: "데이터 플랫폼 구축과 운영 범위가 확인됩니다.",
    human_feedback: {
      revision: 1,
      relevance: "relevant",
      priority: "high",
      memo: "제안요청서 공개 시 범위와 일정 확인",
      claimed_name: "김검토",
      created_at: "2026-09-01T05:00:00Z",
    },
  },
  {
    order_plan_pk: 102,
    order_plan_unty_no: "OP-2026-00102",
    source_url: "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-2026-00102",
    title: "지방공기업 업무혁신 및 데이터 연계 체계 고도화",
    agency_name: "경기도청",
    business_division: "행정",
    budget_amount: null,
    planned_order_year: "2027",
    planned_order_month: "03",
    contract_method: null,
    notice_posted: null,
    source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101",
    observed_at: "2026-09-01T01:01:00Z",
    stage1_status: "selected",
    stage1_rank: 7,
    stage1_score: 0.74,
    nearest_capability: "데이터 연계",
    stage2_status: "success",
    qwen_relevance: "uncertain",
    qwen_score: 0.55,
    qwen_reason: "데이터 연계는 확인되지만 당사 역량과의 직접 연결은 불충분합니다.",
    human_feedback: null,
  },
  {
    order_plan_pk: 103,
    order_plan_unty_no: "OP-2026-00103",
    source_url: "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-2026-00103",
    title: "청사 시설관리 용역 발주계획",
    agency_name: "부산광역시",
    business_division: "시설관리",
    budget_amount: 75000000,
    planned_order_year: "2026",
    planned_order_month: "12",
    contract_method: "수의계약",
    notice_posted: "Y",
    source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101",
    observed_at: "2026-09-01T01:02:00Z",
    stage1_status: "selected",
    stage1_rank: 9,
    stage1_score: 0.68,
    nearest_capability: "시설관리",
    stage2_status: "success",
    qwen_relevance: "not_relevant",
    qwen_score: 0.08,
    qwen_reason: "시설관리 용역으로 정보화 사업과 다릅니다.",
    human_feedback: null,
  },
  {
    order_plan_pk: 104,
    order_plan_unty_no: "OP-2026-00104",
    source_url: "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-2026-00104",
    title: "복지서비스 운영 지원 발주계획",
    agency_name: "대전광역시",
    business_division: "복지",
    budget_amount: null,
    planned_order_year: null,
    planned_order_month: null,
    contract_method: null,
    notice_posted: "N",
    source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101",
    observed_at: "2026-09-01T01:03:00Z",
    stage1_status: "filtered_out",
    stage1_rank: null,
    stage1_score: 0.12,
    nearest_capability: null,
    stage2_status: "not_attempted",
    qwen_relevance: null,
    qwen_score: null,
    qwen_reason: null,
    human_feedback: null,
  },
  {
    order_plan_pk: 105,
    order_plan_unty_no: "OP-2026-00105",
    source_url: "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-2026-00105",
    title: "공공기관 업무시스템 개선 검토",
    agency_name: "인천광역시",
    business_division: "정보화",
    budget_amount: 88000000,
    planned_order_year: "2027",
    planned_order_month: null,
    contract_method: "일반경쟁",
    notice_posted: null,
    source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101",
    observed_at: "2026-09-01T01:04:00Z",
    stage1_status: "selected",
    stage1_rank: 20,
    stage1_score: 0.4,
    nearest_capability: "업무시스템 개선",
    stage2_status: "failed",
    qwen_relevance: null,
    qwen_score: null,
    qwen_reason: null,
    human_feedback: null,
  },
  {
    order_plan_pk: 106,
    order_plan_unty_no: "OP-2026-00106",
    source_url: "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-2026-00106",
    title: "지역 데이터 활용 사업 사전 조사",
    agency_name: "충청북도",
    business_division: "정보화",
    budget_amount: null,
    planned_order_year: null,
    planned_order_month: null,
    contract_method: null,
    notice_posted: null,
    source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101",
    observed_at: "2026-09-01T01:05:00Z",
    stage1_status: "failed",
    stage1_rank: null,
    stage1_score: null,
    nearest_capability: null,
    stage2_status: "not_attempted",
    qwen_relevance: null,
    qwen_score: null,
    qwen_reason: null,
    human_feedback: null,
  },
  {
    order_plan_pk: 107,
    order_plan_unty_no: "OP-2026-00107",
    source_url: "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-2026-00107",
    title: "노후 전산망 재해복구체계 구축 사전 검토",
    agency_name: "강원특별자치도",
    business_division: "정보화",
    budget_amount: 61000000,
    planned_order_year: "2027",
    planned_order_month: "04",
    contract_method: "제한경쟁",
    notice_posted: "N",
    source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101",
    observed_at: "2026-09-01T01:06:00Z",
    stage1_status: "selected",
    stage1_rank: 33,
    stage1_score: 0.31,
    nearest_capability: "재해복구",
    stage2_status: "unknown",
    qwen_relevance: null,
    qwen_score: null,
    qwen_reason: null,
    human_feedback: null,
  },
  {
    order_plan_pk: 108,
    order_plan_unty_no: "OP-2026-00108",
    source_url: "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-2026-00108",
    title: "행정정보 공동이용 확대 사업 발주계획",
    agency_name: "경상남도",
    business_division: "정보화",
    budget_amount: 210000000,
    planned_order_year: "2026",
    planned_order_month: "10",
    contract_method: "일반경쟁",
    notice_posted: "Y",
    source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101",
    observed_at: "2026-09-01T01:07:00Z",
    stage1_status: "selected",
    stage1_rank: 45,
    stage1_score: 0.22,
    nearest_capability: "행정정보 공동이용",
    stage2_status: "rejected",
    qwen_relevance: null,
    qwen_score: null,
    qwen_reason: null,
    human_feedback: null,
  },
];

const c2LargeItems: C2OrderPlanFixtureItem[] = Array.from({ length: 1200 }, (_, index) => {
  const failed = index >= 900;
  return {
    ...c2Items[0],
    order_plan_pk: 1000 + index,
    order_plan_unty_no: `OP-2026-${String(20000 + index).padStart(5, "0")}`,
    title: `대규모 페이지네이션 회귀 발주계획 ${index + 1}`,
    observed_at: `2026-09-01T01:${String(Math.floor(index / 60)).padStart(2, "0")}:${String(index % 60).padStart(2, "0")}Z`,
    stage1_rank: index + 1,
    stage2_status: failed ? "failed" : "success",
    qwen_relevance: failed ? null : "relevant",
    qwen_score: failed ? null : 0.9,
    qwen_reason: failed ? null : "대규모 페이지네이션 회귀용 결과입니다.",
    human_feedback: null,
  };
});

const c2LargeExecution = c2Execution({
  population_count: 1200,
  status: "부분 성공",
  partial_artifact: true,
  counts: {
    candidate_count: 1200,
    completed_count: 900,
    failure_count: 300,
    stage1_selected_count: 1200,
    stage1_filtered_out_count: 0,
    stage1_failed_count: 0,
    stage2_relevant_count: 900,
    stage2_not_relevant_count: 0,
    stage2_uncertain_count: 0,
    stage2_failed_count: 300,
    stage2_rejected_count: 0,
    human_review_count: 900,
  },
});

function c2DetailArtifacts(executionId: string) {
  return [
    { kind: "screening_input", artifact_schema_version: "screening-input.v1", artifact_producer: "screening-api", artifact_consumer: "screening-worker", sha256: c2Digest("i"), byte_count: 12800, object_version: "v1", validation_status: "valid", created_at: "2026-09-01T02:00:01Z" },
    { kind: "ranking", artifact_schema_version: "ranking.v1", artifact_producer: "bm25-worker", artifact_consumer: "screening-api", sha256: c2Digest("j"), byte_count: 9600, object_version: "v1", validation_status: "valid", created_at: "2026-09-01T02:03:00Z" },
    { kind: "decisions", artifact_schema_version: "decisions.v1", artifact_producer: "qwen-worker", artifact_consumer: "screening-api", sha256: c2Digest("k"), byte_count: 7200, object_version: "v1", validation_status: executionId.includes("partial") ? "pending" : "valid", created_at: "2026-09-01T02:04:00Z" },
    { kind: "failures", artifact_schema_version: "failures.v1", artifact_producer: "screening-worker", artifact_consumer: "screening-api", sha256: c2Digest("l"), byte_count: 410, object_version: null, validation_status: "valid", created_at: "2026-09-01T02:05:00Z" },
  ];
}

const c2Detail = {
  schema_version: "order-plan-detail-response.v4",
  producer: "screening-api",
  consumer: "order-plan-review-client",
  order_plan_pk: 101,
  order_plan_unty_no: "OP-2026-00101",
  source_url: c2Items[0].source_url,
  title: c2Items[0].title,
  agency_name: c2Items[0].agency_name,
  business_division: c2Items[0].business_division,
  business_division_code: "IT",
  service_type: "구축·운영",
  budget_amount: 125000000,
  planned_order_year: "2026",
  planned_order_month: "11",
  // v4: 누적 발주계획 행의 계약·공고 열. `notice_posted`는 원문 `Y`/`N` 문자열이고
  // `bid_ntice_no_list`는 쪼개지 않은 수집 원문이다.
  supervising_agency_name: "조달청",
  procurement_method: "자체조달",
  contract_method: c2Items[0].contract_method,
  notice_posted: c2Items[0].notice_posted,
  bid_ntice_no_list: null,
  published_at: "2026-09-01T00:00:00Z",
  observations: [
    { source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101", observed_at: "2026-09-01T01:00:00Z", source_sha256: c2Digest("m") },
    { source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0831", observed_at: "2026-08-31T01:00:00Z", source_sha256: null },
  ],
  screening_history: [
    {
      execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010101", source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101", policy_version: "c2-policy.v1", policy_sha256: c2Digest("a"), binding_sha256: c2Digest("b"), execution_status: "부분 성공", stage1_status: "selected", stage1_rank: 1, stage1_score: 0.92, nearest_capability: "데이터 플랫폼 구축·운영", batch_id: "batch-20260901-01", attempt_no: 2, stage2_status: "success", qwen_relevance: "relevant", qwen_score: 0.96, qwen_reason: "데이터 플랫폼 구축과 운영 범위가 확인됩니다.", feedback_revision_count: 1,
      execution_purpose: "operational", execution_started_at: "2026-09-01T02:00:04Z", execution_finished_at: "2026-09-01T02:05:00Z",
    },
    {
      execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d083101", source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0831", policy_version: "c2-policy.v1", policy_sha256: c2Digest("e"), binding_sha256: c2Digest("f"), execution_status: "성공", stage1_status: "selected", stage1_rank: 4, stage1_score: 0.88, nearest_capability: "데이터 플랫폼 구축", batch_id: "batch-20260831-01", attempt_no: 1, stage2_status: "success", qwen_relevance: "uncertain", qwen_score: 0.62, qwen_reason: "이전 실행에서는 범위 확인이 필요했습니다.", feedback_revision_count: 0,
      execution_purpose: "operational", execution_started_at: "2026-08-31T02:00:02Z", execution_finished_at: "2026-08-31T02:04:00Z",
    },
  ],
  latest_human_feedback: c2Items[0].human_feedback,
};

function c2ExecutionDetail(execution: OrderPlanScreeningExecutionSummary) {
  const executionId = String(execution.execution_id);
  const attempts = executionId === "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010101"
    ? [
      {
        attempt_id: "c2f4d7c1-0a61-4e07-8d2e-000000000101",
        batch_id: "batch-20260901-01",
        sequence: 1,
        attempt_no: 1,
        model_name: "qwen3.8-27B",
        model_digest: c2Digest("q"),
        prompt_version: "prompt-v3",
        prompt_sha256: c2Digest("r"),
        company_profile_version: "profile-v1",
        company_profile_sha256: c2Digest("s"),
        generation_config_sha256: c2Digest("t"),
        attempt_status: "failed",
        failure_type: "timeout",
        failure_code: "qwen_timeout",
        input_tokens: 620,
        cached_input_tokens: null,
        output_tokens: null,
        total_tokens: null,
        duration_ms: 120000,
        started_at: "2026-09-01T02:02:00Z",
        finished_at: "2026-09-01T02:04:00Z",
      },
      {
        attempt_id: "c2f4d7c1-0a61-4e07-8d2e-000000000102",
        batch_id: "batch-20260901-01",
        sequence: 1,
        attempt_no: 2,
        model_name: "qwen3.8-27B",
        model_digest: c2Digest("q"),
        prompt_version: "prompt-v3",
        prompt_sha256: c2Digest("r"),
        company_profile_version: "profile-v1",
        company_profile_sha256: c2Digest("s"),
        generation_config_sha256: c2Digest("t"),
        attempt_status: "success",
        failure_type: null,
        failure_code: null,
        input_tokens: 620,
        cached_input_tokens: 120,
        output_tokens: 80,
        total_tokens: 700,
        duration_ms: 4800,
        started_at: "2026-09-01T02:04:10Z",
        finished_at: "2026-09-01T02:04:15Z",
      },
    ]
    : [{
      attempt_id: "c2f4d7c1-0a61-4e07-8d2e-000000000201",
      batch_id: "batch-20260831-01",
      sequence: 1,
      attempt_no: 1,
      model_name: "qwen3.8-27B",
      model_digest: c2Digest("u"),
      prompt_version: "prompt-v3",
      prompt_sha256: c2Digest("v"),
      company_profile_version: "profile-v1",
      company_profile_sha256: c2Digest("w"),
      generation_config_sha256: c2Digest("x"),
      attempt_status: "success",
      failure_type: null,
      failure_code: null,
      input_tokens: 580,
      cached_input_tokens: 100,
      output_tokens: 60,
      total_tokens: 640,
      duration_ms: 4200,
      started_at: "2026-08-31T02:02:00Z",
      finished_at: "2026-08-31T02:02:05Z",
    }];
  return {
    schema_version: "execution-detail-response.v2",
    producer: "screening-api",
    consumer: "human-review-client",
    ...execution,
    artifacts: c2DetailArtifacts(String(execution.execution_id)),
    attempts,
  };
}

/** C-2 v3 mock server. Queries filter before counting and pagination. */
export async function mockOrderPlans(page: Page, scenario: OrderPlanMockScenario = "default", options: OrderPlanMockOptions = {}): Promise<OrderPlanMockTrace> {
  const trace: OrderPlanMockTrace = { feedbackPosts: [], trackingPatches: [], executionPosts: [], stopPosts: [] };
  const trackingState = new Map<number, OrderPlanTracking>();
  const trackingDecisions = new Map<number, OpportunityTrackingDecisionItem[]>();
  const feedbackItems: OrderPlanFeedbackFixture[] = [{
    feedback_id: "c2f4d7c1-0a61-4c07-8d2e-000000000001", execution_id: c2Execution().execution_id,
    order_plan_pk: 101, revision: 1, relevance: "relevant", priority: "high", memo: "합성 검토 메모",
    claimed_name: "합성 담당자", created_at: "2026-09-01T05:00:00Z",
  }];
  const partial = scenario === "live-disabled" ? c2Execution({ execution_allowed: false }) : c2Execution();
  const executions: OrderPlanScreeningExecutionSummary[] = scenario === "no-results" || scenario === "no-completed-execution" ? []
    : scenario === "failure" ? [c2Failed]
      : scenario === "stopped" ? [c2Execution({ execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010401", status: "중단됨", finished_at: "2026-09-01T05:00:00Z", error_code: "user_requested" })]
        : scenario === "large" ? [c2LargeExecution] : [c2Running, c2Failed, partial, c2OlderSuccess];
  const planItems: C2OrderPlanFixtureItem[] = scenario === "no-results" ? [] : scenario === "large" ? c2LargeItems : [...c2Items, {
    ...c2Items[0], order_plan_pk: 109, order_plan_unty_no: "OP-2026-00109", title: "아직 선별 관측값이 없는 합성 발주계획",
    stage1_status: null, stage1_rank: null, stage1_score: null, stage2_status: null, qwen_relevance: null,
    qwen_score: null, qwen_reason: null, human_feedback: null,
  }];
  if (scenario !== "large") {
    partial.population_count = planItems.length || 1;
    partial.counts = {
      candidate_count: 6, completed_count: 3, failure_count: 4,
      stage1_selected_count: 6, stage1_filtered_out_count: 1, stage1_failed_count: 1,
      stage2_relevant_count: 1, stage2_not_relevant_count: 1, stage2_uncertain_count: 1,
      stage2_failed_count: 1, stage2_rejected_count: 1, human_review_count: 1,
    };
  }
  /** v3까지의 "회차 스코프" 계산. v4 wire `scope`뿐 아니라 항목별 결과 연결에도 쓴다. */
  function latestCompletedExecution(sourceRunId: string | null): OrderPlanScreeningExecutionSummary | null {
    const eligible = executions.filter((item) => (item.status === "성공" || item.status === "부분 성공") && (!sourceRunId || item.source_run_id === sourceRunId));
    eligible.sort((a, b) => (b.finished_at ?? "").localeCompare(a.finished_at ?? "") || b.queued_at.localeCompare(a.queued_at) || b.execution_id.localeCompare(a.execution_id));
    return eligible[0] ?? null;
  }
  /** v4 wire `scope`. `source_run_id`가 있으면 회차 모드, 없으면 누적 모드다. */
  function scopeFor(sourceRunId: string | null): OrderPlanListScope | null {
    const latest = latestCompletedExecution(sourceRunId);
    if (sourceRunId) {
      return latest ? {
        mode: "run", execution_id: latest.execution_id, source_run_id: latest.source_run_id,
        status: latest.status as "성공" | "부분 성공", finished_at: latest.finished_at,
        policy_version: latest.policy_version, purpose: latest.purpose,
      } : null;
    }
    // `policy_versions`는 판정 유무(범위에 완료 실행이 있는 버전), `activated_policy_versions`는
    // 실행 상태를 보일 범위(활성화된 적 있는 버전 전부)다. 서버처럼 앞을 뒤의 부분집합으로 둔다 —
    // 활성화된 적 없는 policy의 완료 실행은 누적 판정이 아니다.
    const activated = options.activatedPolicyVersions ?? [c2Execution().policy_version];
    return {
      mode: "cumulative",
      policy_versions: latest && activated.includes(latest.policy_version) ? [latest.policy_version] : [],
      activated_policy_versions: activated,
    };
  }
  function trackingProjection(orderPlanPk: number): OrderPlanTracking | null {
    if (scenario === "no-owning-opportunity") return null;
    const bulkOverride = bulkOverrideStore(page).get(orderPlanPk);
    if (bulkOverride) {
      return {
        opportunity_id: bulkOverride.opportunity_id,
        tracking_status: bulkOverride.tracking_status as OpportunityTrackingStatus,
        tracking_reason: null, tracking_selected_by: null, tracking_selected_at: null,
      };
    }
    return trackingState.get(orderPlanPk) ?? { opportunity_id: 5000 + orderPlanPk, tracking_status: "미선택", tracking_reason: null, tracking_selected_by: null, tracking_selected_at: null };
  }
  const sharedOpportunities = opportunityFixtures.get(page);
  if (sharedOpportunities) {
    for (let index = sharedOpportunities.length - 1; index >= 0; index -= 1) {
      if (sharedOpportunities[index].id >= 5000) sharedOpportunities.splice(index, 1);
    }
    if (scenario !== "no-owning-opportunity") {
      sharedOpportunities.push(...planItems.map((plan): OpportunityListItem => ({
        id: 5000 + plan.order_plan_pk, tracking_status: "미선택", tracking_reason: null,
        tracking_selected_by: null, tracking_selected_at: null,
        recheck_signal: false, recheck_signal_at: null, recheck_signal_link_id: null,
        first_registered_stage: "order_plan", section: null,
        pending_candidate_link_count: 0, open_blocking_item_count: 0,
        action_reasons: [], hold_review_due_at: null,
        links: [{ ...visualOpportunities[0].links[0], id: 5000 + plan.order_plan_pk,
          record_id: plan.order_plan_pk, order_plan_id: plan.order_plan_pk,
          title: plan.title, agency: plan.agency_name,
          external_id: plan.order_plan_unty_no, record_external_id: plan.order_plan_unty_no }],
      })));
    }
  }
  function listItems(search: URLSearchParams): OrderPlanListItem[] {
    const sourceRunId = search.get("source_run_id");
    const latest = latestCompletedExecution(sourceRunId);
    return planItems.map((item): OrderPlanListItem => {
      const feedback = feedbackItems.filter((entry) => entry.order_plan_pk === item.order_plan_pk && entry.execution_id === latest?.execution_id).at(-1);
      return {
        ...item,
        ...(!latest ? { stage1_status: null, stage1_rank: null, stage1_score: null, stage2_status: null, qwen_relevance: null, qwen_score: null, qwen_reason: null } : {}),
        human_feedback: feedback ? { revision: feedback.revision, relevance: feedback.relevance as "relevant" | "not_relevant" | "uncertain", priority: feedback.priority as "high" | "medium" | "low" | null, memo: feedback.memo, claimed_name: feedback.claimed_name, created_at: feedback.created_at } : null,
        tracking: trackingProjection(item.order_plan_pk),
        execution_id: latest ? latest.execution_id : null,
        policy_version: latest ? latest.policy_version : null,
        first_observed_at: item.observed_at,
      };
    }).filter((item) => (!search.get("source_run_id") || item.source_run_id === search.get("source_run_id"))
      && matchesValues(item.stage1_status, search.get("stage1_status"))
      && matchesValues(item.stage2_status, search.get("stage2_status"))
      && matchesValues(item.qwen_relevance, search.get("qwen_relevance"))
      && matchesValues(item.human_feedback?.relevance ?? null, search.get("human_relevance"))
      && (!search.get("tracking_status") || (item.tracking !== null && matchesValues(item.tracking.tracking_status, search.get("tracking_status"))))
      && (search.get("issue") !== "true" || ["failed", "rejected"].includes(item.stage1_status ?? "") || ["failed", "rejected"].includes(item.stage2_status ?? ""))
      && (!search.get("q") || !searchKey(search.get("q")!) || searchMatches(search.get("q")!, item.title, item.agency_name, item.order_plan_unty_no)));
  }
  workloadProvider(page, "order_plan_pending", () => latestCompletedExecution(null)
    ? { count: listItems(new URLSearchParams({ stage1_status: "selected", qwen_relevance: "relevant,uncertain", tracking_status: "미선택" })).length, unavailable_reason: null }
    : { count: null, unavailable_reason: "no_completed_execution" });

  const createdRequests = new Map<string, { payload: string; response: unknown }>();
  async function error(route: Route, code: OrderPlanScreeningErrorCode, requestId: unknown = null, status = 409) {
    await fulfillJson(route, { error: { code, message: "합성 안정 오류", details: null }, request_id: typeof requestId === "string" && uuidPattern.test(requestId) ? requestId : null }, status);
  }
  await page.route("**/api/**", async (route) => {
    const request = route.request(), method = request.method();
    const url = new URL(request.url()), pathname = url.pathname, search = url.searchParams;
    if (pathname === "/api/order-plan-screening/executions" && method === "GET") {
      const filtered = executions.filter((item) => (!search.get("source_run_id") || item.source_run_id === search.get("source_run_id")) && (!search.get("status") || item.status === search.get("status")));
      const limit = Number(search.get("limit") ?? 100), offset = Number(search.get("offset") ?? 0);
      await fulfillJson(route, { schema_version: "execution-list-response.v2", producer: "screening-api", consumer: "human-review-client", items: filtered.slice(offset, offset + limit), total: filtered.length, limit, offset }); return;
    }
    if (pathname === "/api/order-plan-screening/executions" && method === "POST") {
      const body = fixtureRecord(request.postDataJSON()) ?? {};
      trace.executionPosts.push({ body, headers: request.headers() });
      if (!fixtureActor(request.headers())) { await error(route, "actor_name_required", body.request_id, 422); return; }
      if (body.schema_version !== "execution-create-request.v1" || body.producer !== "human-review-client" || body.consumer !== "screening-api" || !uuidPattern.test(String(body.request_id)) || typeof body.source_run_id !== "string" || !body.source_run_id.trim() || typeof body.policy_version !== "string" || !body.policy_version.trim() || Object.keys(body).some((key) => !["schema_version", "producer", "consumer", "request_id", "source_run_id", "policy_version"].includes(key))) { await error(route, "invalid_request", body.request_id, 422); return; }
      if (options.createErrorCode) { await error(route, options.createErrorCode, body.request_id, options.errorStatus ?? (options.createErrorCode === "service_unavailable" ? 503 : 409)); return; }
      const previous = createdRequests.get(String(body.request_id));
      if (previous) { if (previous.payload !== JSON.stringify(body)) await error(route, "idempotency_conflict", body.request_id); else await fulfillJson(route, previous.response, 202); return; }
      if (executions.some((item) => ["대기", "실행 중", "중지 요청"].includes(item.status))) { await error(route, "active_execution_exists", body.request_id); return; }
      const execution = c2Execution({ execution_id: "a2000000-0000-4000-8000-000000000001", request_id: String(body.request_id), source_run_id: body.source_run_id, policy_version: body.policy_version, requested_by: fixtureActor(request.headers()), status: "대기", queued_at: "2026-09-02T02:00:00Z", started_at: null, heartbeat_at: null, finished_at: null, error_code: null, partial_artifact: false });
      executions.unshift(execution);
      const response = { schema_version: "execution-create-response.v1", producer: "screening-api", consumer: "human-review-client", execution_id: execution.execution_id, request_id: execution.request_id, source_run_id: execution.source_run_id, policy_version: execution.policy_version, status: "대기", binding_sha256: execution.binding_sha256, stage1_binding_sha256: execution.stage1_binding_sha256, stage2_binding_sha256: execution.stage2_binding_sha256, execution_allowed: execution.execution_allowed };
      createdRequests.set(execution.request_id, { payload: JSON.stringify(body), response });
      await fulfillJson(route, response, 202); return;
    }
    const executionMatch = pathname.match(/^\/api\/order-plan-screening\/executions\/([^/]+)(\/stop)?$/);
    if (executionMatch) {
      const executionId = decodeURIComponent(executionMatch[1]);
      const execution = executions.find((item) => item.execution_id === executionId);
      if (!execution) { await error(route, "not_found", null, 404); return; }
      if (method === "GET" && !executionMatch[2]) { await fulfillJson(route, c2ExecutionDetail(execution)); return; }
      if (method === "POST" && executionMatch[2]) {
        const body = fixtureRecord(request.postDataJSON()) ?? {};
        trace.stopPosts.push({ executionId, body, headers: request.headers() });
        if (!fixtureActor(request.headers())) { await error(route, "actor_name_required", body.request_id, 422); return; }
        if (body.schema_version !== "execution-stop-request.v1" || body.producer !== "human-review-client" || body.consumer !== "screening-api" || !uuidPattern.test(String(body.request_id)) || body.reason !== "user_requested" || Object.keys(body).some((key) => !["schema_version", "producer", "consumer", "request_id", "reason"].includes(key))) { await error(route, "invalid_request", body.request_id, 422); return; }
        if (options.stopErrorCode) { await error(route, options.stopErrorCode, body.request_id, options.errorStatus ?? 409); return; }
        if (!["대기", "실행 중", "중지 요청"].includes(execution.status)) { await error(route, "execution_not_stoppable", body.request_id); return; }
        execution.status = execution.status === "대기" ? "중단됨" : "중지 요청";
        if (execution.status === "중단됨") execution.finished_at = "2026-09-02T02:01:00Z";
        await fulfillJson(route, { schema_version: "execution-stop-response.v1", producer: "screening-api", consumer: "human-review-client", execution_id: executionId, request_id: body.request_id, status: execution.status }, 202); return;
      }
    }
    // C-2 일일 운영 계약 기본 handler. 다른 spec이 필요한 policy·게이트·스위치
    // 상태를 만들려면 이 route보다 나중에 등록한 page.route로 덮어쓴다.
    if (pathname === "/api/order-plan-screening/daily-trigger" && method === "GET") {
      await fulfillJson(route, {
        schema_version: "daily-trigger-state-response.v1",
        producer: "daily-trigger-api",
        consumer: "human-review-client",
        effective_enabled: false,
        policy_version: null,
        policy_sha256: null,
        switch: null,
        reasons: ["env_cap_off", "no_active_policy"],
      }); return;
    }
    if (pathname === "/api/order-plan-screening/policies" && method === "GET") {
      await fulfillJson(route, {
        schema_version: "policy-list-response.v1",
        producer: "policy-api",
        consumer: "human-review-client",
        items: [],
        total: 0,
      }); return;
    }
    if (pathname === "/api/order-plan-screening/quality-gates" && method === "GET") {
      await fulfillJson(route, {
        schema_version: "order-plan-quality-gate-list-response.v1",
        producer: "quality-gate-api",
        consumer: "human-review-client",
        policy_version: search.get("policy_version"),
        items: [],
      }); return;
    }
    if (pathname === "/api/order-plans" && method === "GET") {
      const items = listItems(search), limit = Number(search.get("limit") ?? 100), offset = Number(search.get("offset") ?? 0);
      await fulfillJson(route, { schema_version: "order-plan-list-response.v5", producer: "order-plan-review-api", consumer: "order-plan-review-client", scope: scopeFor(search.get("source_run_id")), items: items.slice(offset, offset + limit).map((item) => {
        if (!options.omitTracking) return item;
        const { tracking: _tracking, ...legacy } = item;
        return legacy;
      }), total: items.length, limit, offset }); return;
    }
    const planMatch = pathname.match(/^\/api\/order-plans\/(\d+)(?:\/(screening-history|screening-feedback))?$/);
    if (planMatch) {
      const orderPlanPk = Number(planMatch[1]), plan = listItems(new URLSearchParams()).find((item) => item.order_plan_pk === orderPlanPk);
      if (!plan) { await error(route, "not_found", null, 404); return; }
      const history = latestCompletedExecution(null) && orderPlanPk === 101 ? c2Detail.screening_history : [];
      if (method === "GET" && !planMatch[2]) {
        await fulfillJson(route, { ...c2Detail, order_plan_pk: orderPlanPk, order_plan_unty_no: plan.order_plan_unty_no, source_url: plan.source_url, title: plan.title, agency_name: plan.agency_name, budget_amount: plan.budget_amount, business_division: plan.business_division, planned_order_year: plan.planned_order_year, planned_order_month: plan.planned_order_month, contract_method: plan.contract_method, notice_posted: plan.notice_posted, screening_history: history, latest_human_feedback: plan.human_feedback, tracking: plan.tracking }); return;
      }
      if (method === "GET" && planMatch[2] === "screening-history") { await fulfillJson(route, { schema_version: "order-plan-detail-response.v5", producer: "screening-api", consumer: "order-plan-review-client", order_plan_pk: orderPlanPk, items: history }); return; }
      if (method === "GET" && planMatch[2] === "screening-feedback") { await fulfillJson(route, { schema_version: "feedback-list-response.v1", producer: "screening-api", consumer: "order-plan-review-client", items: feedbackItems.filter((item) => item.order_plan_pk === orderPlanPk && (!search.get("execution_id") || item.execution_id === search.get("execution_id"))).slice().reverse() }); return; }
      if (method === "POST" && planMatch[2] === "screening-feedback") {
        const body = fixtureRecord(request.postDataJSON()) ?? {};
        trace.feedbackPosts.push({ body, headers: request.headers() });
        const revision = Math.max(0, ...feedbackItems.filter((item) => item.order_plan_pk === orderPlanPk).map((item) => item.revision)) + 1;
        const saved: OrderPlanFeedbackFixture = { feedback_id: `c2f4d7c1-0a61-4c07-8d2e-${String(revision).padStart(12, "0")}`, execution_id: String(body.execution_id ?? ""), order_plan_pk: orderPlanPk, revision, relevance: String(body.relevance ?? ""), priority: typeof body.priority === "string" ? body.priority : null, memo: typeof body.memo === "string" ? body.memo : null, claimed_name: fixtureActor(request.headers()), created_at: "2026-09-02T00:00:00Z" };
        feedbackItems.push(saved);
        await fulfillJson(route, { schema_version: "feedback-create-response.v1", producer: "human-review-api", consumer: "postgres-history", ...saved }, 201); return;
      }
    }
    const trackingMatch = pathname.match(/^\/api\/opportunities\/(\d+)\/(tracking-status|tracking-decisions|deep-reviews)$/);
    if (trackingMatch) {
      const opportunityId = Number(trackingMatch[1]), orderPlanPk = opportunityId - 5000;
      if (!planItems.some((item) => item.order_plan_pk === orderPlanPk)) { await route.fallback(); return; }
      const projection = trackingProjection(orderPlanPk);
      if (!projection) { await trackingError(route, "opportunity_not_found"); return; }
      if (method === "GET" && trackingMatch[2] !== "tracking-status") { await fulfillJson(route, { opportunity_id: opportunityId, items: trackingMatch[2] === "deep-reviews" ? [] : trackingDecisions.get(orderPlanPk) ?? [] }); return; }
      if (method === "PATCH" && trackingMatch[2] === "tracking-status") {
        const body = fixtureRecord(request.postDataJSON()) ?? {};
        trace.trackingPatches.push({ opportunityId, body, headers: request.headers() });
        if (!fixtureActor(request.headers())) { await trackingError(route, "actor_name_required"); return; }
        if (!["미선택", "계속 추적", "보류", "종료"].includes(String(body.tracking_status))) { await trackingError(route, "tracking_status_invalid"); return; }
        if (typeof body.reason !== "string" || !body.reason.trim()) { await trackingError(route, "tracking_reason_required"); return; }
        const status = body.tracking_status as OpportunityTrackingStatus, claimedName = fixtureActor(request.headers()), decidedAt = "2026-09-02T01:00:00Z";
        const decisions = trackingDecisions.get(orderPlanPk) ?? [];
        decisions.unshift({ decided_at: decidedAt, tracking_status: status, previous_tracking_status: projection.tracking_status, reason: body.reason, claimed_name: claimedName, audit_event_id: `f2f4d7c1-0a61-4f07-8d2e-${String(decisions.length + 1).padStart(12, "0")}`, cleared_recheck_signal: false });
        trackingDecisions.set(orderPlanPk, decisions);
        const saved: OrderPlanTracking = { opportunity_id: opportunityId, tracking_status: status, tracking_reason: status === "미선택" ? null : body.reason, tracking_selected_by: status === "미선택" ? null : claimedName, tracking_selected_at: status === "미선택" ? null : decidedAt };
        trackingState.set(orderPlanPk, saved);
        const shared = sharedOpportunities?.find((item) => item.id === opportunityId);
        if (shared) {
          shared.tracking_status = saved.tracking_status; shared.tracking_reason = saved.tracking_reason;
          shared.tracking_selected_by = saved.tracking_selected_by; shared.tracking_selected_at = saved.tracking_selected_at;
          shared.recheck_signal = false; shared.recheck_signal_at = null; shared.recheck_signal_link_id = null;
          shared.section = mockTrackingSection(shared);
        }
        await fulfillJson(route, { id: opportunityId, tracking_status: saved.tracking_status, tracking_reason: saved.tracking_reason, tracking_selected_by: saved.tracking_selected_by, tracking_selected_at: saved.tracking_selected_at, recheck_signal: false, recheck_signal_at: null, recheck_signal_link_id: null, first_registered_stage: "order_plan", section: status === "계속 추적" ? "추적 중" : status === "보류" ? "보류" : status === "종료" ? "추적 종료" : null, pending_candidate_link_count: 0, open_blocking_item_count: 0, links: [] }); return;
      }
    }
    await route.fallback();
  });
  return trace;
}

/**
 * Named v1 fixture for the order-plan bulk tracking endpoints.  It is
 * deliberately separate from mockOrderPlans so existing C-2 route fixtures
 * retain their original behavior.
 */
export type OrderPlanBulkMockScenario =
  | "mixed"
  | "all-eligible"
  | "malformed-preview"
  | "malformed-start"
  | "server-error"
  | "validation-error";

export interface OrderPlanBulkMockOptions {
  previewResponse?: unknown;
  startResponse?: unknown;
  /** bulk-end 최종 receipt를 대신한다. 미지정이면 `bulkMockEnd`가 만든다. */
  endResponse?: unknown;
  errorStatus?: number;
}

export interface OrderPlanBulkMockTrace {
  previewPosts: Array<{ body: unknown }>;
  startPosts: Array<{ body: unknown; headers: Record<string, string> }>;
  /** ADR-0063 bulk-end로 간 요청. start와 별도 idempotency 저장소를 쓴다(실제 계약과 같다). */
  endPosts: Array<{ body: unknown; headers: Record<string, string> }>;
}

const BULK_MOCK_AUDIT_ID = "f2f4d7c1-0a61-4f07-8d2e-000000000001";

function bulkMockIds(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter((item): item is number => typeof item === "number" && Number.isInteger(item) && item > 0))]
    .sort((left, right) => left - right);
}

function validBulkIdList(value: unknown): value is number[] {
  return Array.isArray(value)
    && value.length > 0
    && value.every((item) => typeof item === "number" && Number.isInteger(item) && item > 0);
}

function hasBulkKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => actual.includes(key));
}

function bulkMockPreview(ids: readonly number[], allEligible = false): OrderPlanBulkPreviewResponse {
  const items: OrderPlanBulkPreviewResponse["items"] = ids.map((orderPlanId) => {
    if (!allEligible && orderPlanId === 999) {
      return {
        order_plan_id: orderPlanId, opportunity_id: null, tracking_status: null,
        eligibility: "failed" as const, code: "order_plan_not_found" as const,
      };
    }
    if (!allEligible && orderPlanId === 103) {
      return {
        order_plan_id: orderPlanId, opportunity_id: 5103, tracking_status: "보류" as const,
        eligibility: "excluded" as const, code: null,
      };
    }
    if (!allEligible && orderPlanId === 104) {
      return {
        order_plan_id: orderPlanId, opportunity_id: 5104, tracking_status: "종료" as const,
        eligibility: "excluded" as const, code: null,
      };
    }
    return {
      order_plan_id: orderPlanId, opportunity_id: 5101, tracking_status: "미선택" as const,
      eligibility: "eligible" as const, code: null,
    };
  });
  const eligible = items.filter((item) => item.eligibility === "eligible");
  const excluded = items.filter((item) => item.eligibility === "excluded");
  const failed = items.filter((item) => item.eligibility === "failed");
  const excludedByStatus = {
    "계속 추적": {
      plan_count: excluded.filter((item) => item.tracking_status === "계속 추적").length,
      owner_count: new Set(excluded.filter((item) => item.tracking_status === "계속 추적").map((item) => item.opportunity_id)).size,
    },
    "보류": {
      plan_count: excluded.filter((item) => item.tracking_status === "보류").length,
      owner_count: new Set(excluded.filter((item) => item.tracking_status === "보류").map((item) => item.opportunity_id)).size,
    },
    "종료": {
      plan_count: excluded.filter((item) => item.tracking_status === "종료").length,
      owner_count: new Set(excluded.filter((item) => item.tracking_status === "종료").map((item) => item.opportunity_id)).size,
    },
  };
  return {
    schema_version: "order-plan-bulk-preview-response.v1",
    selected_plan_count: ids.length,
    unique_owner_count: new Set(items.flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id])).size,
    eligible_plan_count: eligible.length,
    eligible_owner_count: new Set(eligible.flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id])).size,
    excluded_by_status: excludedByStatus,
    failure_plan_count: failed.length,
    items,
  };
}

function bulkMockStart(
  requestId: string,
  ids: readonly number[],
  scenario: OrderPlanBulkMockScenario,
): unknown {
  const preview = bulkMockPreview(ids, scenario === "all-eligible");
  const items = preview.items.map((item) => item.eligibility === "eligible"
    ? {
      order_plan_id: item.order_plan_id, opportunity_id: item.opportunity_id,
      outcome: "succeeded" as const, status_at_decision: "계속 추적" as const,
      code: null, audit_event_id: BULK_MOCK_AUDIT_ID,
    }
    : item.eligibility === "excluded"
      ? {
        order_plan_id: item.order_plan_id, opportunity_id: item.opportunity_id,
        outcome: "excluded" as const, status_at_decision: item.tracking_status!,
        code: null, audit_event_id: null,
      }
      : {
        order_plan_id: item.order_plan_id, opportunity_id: item.opportunity_id,
        outcome: "failed" as const, status_at_decision: item.tracking_status,
        code: item.code!, audit_event_id: null,
      });
  const excluded = items.filter((item) => item.outcome === "excluded");
  const response: OrderPlanBulkStartResponse = {
    schema_version: "order-plan-bulk-start-response.v1",
    request_id: requestId,
    completed_at: "2026-09-02T01:00:00.123456Z",
    items,
    summary: {
      selected_plan_count: ids.length,
      unique_owner_count: new Set(items.flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id])).size,
      succeeded_plan_count: items.filter((item) => item.outcome === "succeeded").length,
      succeeded_owner_count: new Set(items.filter((item) => item.outcome === "succeeded").flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id])).size,
      excluded_plan_count: excluded.length,
      excluded_by_status: {
        "계속 추적": {
          plan_count: excluded.filter((item) => item.status_at_decision === "계속 추적").length,
          owner_count: new Set(excluded.filter((item) => item.status_at_decision === "계속 추적").map((item) => item.opportunity_id)).size,
        },
        "보류": {
          plan_count: excluded.filter((item) => item.status_at_decision === "보류").length,
          owner_count: new Set(excluded.filter((item) => item.status_at_decision === "보류").map((item) => item.opportunity_id)).size,
        },
        "종료": {
          plan_count: excluded.filter((item) => item.status_at_decision === "종료").length,
          owner_count: new Set(excluded.filter((item) => item.status_at_decision === "종료").map((item) => item.opportunity_id)).size,
        },
      },
      failed_plan_count: items.filter((item) => item.outcome === "failed").length,
    },
  };
  if (scenario === "malformed-start") {
    return withBulkMockExtraField(response);
  }
  return response;
}

/**
 * bulk-end 최종 receipt(ADR-0063). `bulkMockStart`와 같은 eligibility 판정을 재사용하고
 * 성공 항목의 목표 상태만 `종료`로 바꾼다 — 실제 서버가 두 endpoint에 같은 상태
 * 기계를 쓰는 것과 같은 모양이다.
 */
function bulkMockEnd(
  requestId: string,
  ids: readonly number[],
  scenario: OrderPlanBulkMockScenario,
): unknown {
  const preview = bulkMockPreview(ids, scenario === "all-eligible");
  const items = preview.items.map((item) => item.eligibility === "eligible"
    ? {
      order_plan_id: item.order_plan_id, opportunity_id: item.opportunity_id,
      outcome: "succeeded" as const, status_at_decision: "종료" as const,
      code: null, audit_event_id: BULK_MOCK_AUDIT_ID,
    }
    : item.eligibility === "excluded"
      ? {
        order_plan_id: item.order_plan_id, opportunity_id: item.opportunity_id,
        outcome: "excluded" as const, status_at_decision: item.tracking_status!,
        code: null, audit_event_id: null,
      }
      : {
        order_plan_id: item.order_plan_id, opportunity_id: item.opportunity_id,
        outcome: "failed" as const, status_at_decision: item.tracking_status,
        code: item.code!, audit_event_id: null,
      });
  const excluded = items.filter((item) => item.outcome === "excluded");
  const response: OrderPlanBulkEndResponse = {
    schema_version: "order-plan-bulk-end-response.v1",
    request_id: requestId,
    completed_at: "2026-09-20T07:55:51.560908Z",
    items,
    summary: {
      selected_plan_count: ids.length,
      unique_owner_count: new Set(items.flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id])).size,
      succeeded_plan_count: items.filter((item) => item.outcome === "succeeded").length,
      succeeded_owner_count: new Set(items.filter((item) => item.outcome === "succeeded").flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id])).size,
      excluded_plan_count: excluded.length,
      excluded_by_status: {
        "계속 추적": {
          plan_count: excluded.filter((item) => item.status_at_decision === "계속 추적").length,
          owner_count: new Set(excluded.filter((item) => item.status_at_decision === "계속 추적").map((item) => item.opportunity_id)).size,
        },
        "보류": {
          plan_count: excluded.filter((item) => item.status_at_decision === "보류").length,
          owner_count: new Set(excluded.filter((item) => item.status_at_decision === "보류").map((item) => item.opportunity_id)).size,
        },
        "종료": {
          plan_count: excluded.filter((item) => item.status_at_decision === "종료").length,
          owner_count: new Set(excluded.filter((item) => item.status_at_decision === "종료").map((item) => item.opportunity_id)).size,
        },
      },
      failed_plan_count: items.filter((item) => item.outcome === "failed").length,
    },
  };
  if (scenario === "malformed-start") {
    return withBulkMockExtraField(response);
  }
  return response;
}

/** 실제 422(bulk-end 201건)의 FastAPI 기본 형식. `input`은 보낸 배열 전체를 되돌린다. */
function bulkEndTooLongError(ids: unknown[]): unknown {
  return {
    detail: [{
      type: "too_long",
      loc: ["body", "order_plan_ids"],
      msg: `List should have at most 200 items after validation, not ${ids.length}`,
      input: ids,
      ctx: { field_type: "List", max_length: 200, actual_length: ids.length },
    }],
  };
}

function withBulkMockExtraField(value: unknown): unknown {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return { private_debug: "must-not-leak" };
  }
  return Object.assign({}, value, { private_debug: "must-not-leak" });
}

/** Register only the explicit order-plan bulk v1 routes. */
export async function mockOrderPlanBulkTracking(
  page: Page,
  scenario: OrderPlanBulkMockScenario = "mixed",
  options: OrderPlanBulkMockOptions = {},
): Promise<OrderPlanBulkMockTrace> {
  const trace: OrderPlanBulkMockTrace = { previewPosts: [], startPosts: [], endPosts: [] };
  const receipts = new Map<string, { fingerprint: string; response: unknown }>();
  // ADR-0063: bulk-end는 자기 request_id 공간을 쓴다 — start와 같은 request_id를
  // 보내도 서로 replay·conflict를 일으키지 않는다(별도 Map으로 그 계약을 반영한다).
  const endReceipts = new Map<string, { fingerprint: string; response: unknown }>();
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const method = request.method();
    if (pathname === "/api/opportunities/order-plan-tracking/preview" && method === "POST") {
      const body = fixtureRecord(request.postDataJSON()) ?? {};
      trace.previewPosts.push({ body });
      if (scenario === "server-error") {
        await fulfillJson(route, {
          error: { code: "processing_failed", message: "합성 안정 오류", details: null },
          request_id: null,
        }, options.errorStatus ?? 500);
        return;
      }
      if (scenario === "validation-error") {
        await fulfillJson(route, {
          detail: [{ type: "literal_error", loc: ["body", "schema_version"], msg: "invalid", input: body.schema_version }],
        }, 422);
        return;
      }
      if (
        !hasBulkKeys(body, ["schema_version", "order_plan_ids"])
        || body.schema_version !== "order-plan-bulk-preview-request.v1"
        || !validBulkIdList(body.order_plan_ids)
      ) {
        await fulfillJson(route, {
          detail: [{ type: "value_error", loc: ["body"], msg: "invalid", input: body }],
        }, 422);
        return;
      }
      const ids = bulkMockIds(body.order_plan_ids);
      const response = options.previewResponse ?? bulkMockPreview(ids, scenario === "all-eligible");
      if (scenario === "malformed-preview" && options.previewResponse === undefined) {
        await fulfillJson(route, withBulkMockExtraField(response));
        return;
      }
      await fulfillJson(route, response);
      return;
    }
    if (pathname === "/api/opportunities/order-plan-tracking/bulk-start" && method === "POST") {
      const body = fixtureRecord(request.postDataJSON()) ?? {};
      const headers = request.headers();
      trace.startPosts.push({ body, headers });
      const requestId = typeof body.request_id === "string" ? body.request_id : null;
      if (scenario === "server-error") {
        await fulfillJson(route, {
          error: { code: "processing_failed", message: "합성 안정 오류", details: null },
          request_id: requestId,
        }, options.errorStatus ?? 500);
        return;
      }
      if (!fixtureActor(headers)) {
        await fulfillJson(route, {
          error: { code: "actor_name_required", message: "합성 안정 오류", details: null },
          request_id: requestId,
        }, 400);
        return;
      }
      if (
        scenario === "validation-error"
        || !hasBulkKeys(body, ["schema_version", "request_id", "order_plan_ids", "reason"])
        || body.schema_version !== "order-plan-bulk-start-request.v1"
        || !requestId
        || !uuidPattern.test(requestId)
        || !validBulkIdList(body.order_plan_ids)
        || typeof body.reason !== "string"
        || !body.reason.trim()
      ) {
        await fulfillJson(route, {
          detail: [{ type: "uuid_parsing", loc: ["body", "request_id"], msg: "invalid", input: requestId }],
        }, 422);
        return;
      }
      const ids = bulkMockIds(body.order_plan_ids);
      const fingerprint = JSON.stringify({ body, actor: fixtureActor(headers) });
      const previous = receipts.get(requestId);
      if (previous) {
        if (previous.fingerprint !== fingerprint) {
          await fulfillJson(route, {
            error: { code: "idempotency_conflict", message: "합성 안정 오류", details: null },
            request_id: requestId,
          }, 409);
          return;
        }
        await fulfillJson(route, previous.response);
        return;
      }
      const response = options.startResponse ?? bulkMockStart(requestId, ids, scenario);
      receipts.set(requestId, { fingerprint, response });
      applyBulkTrackingOverrides(page, response);
      await fulfillJson(route, response);
      return;
    }
    if (pathname === "/api/opportunities/order-plan-tracking/bulk-end" && method === "POST") {
      const body = fixtureRecord(request.postDataJSON()) ?? {};
      const headers = request.headers();
      trace.endPosts.push({ body, headers });
      const requestId = typeof body.request_id === "string" ? body.request_id : null;
      if (scenario === "server-error") {
        await fulfillJson(route, {
          error: { code: "processing_failed", message: "합성 안정 오류", details: null },
          request_id: requestId,
        }, options.errorStatus ?? 500);
        return;
      }
      if (!fixtureActor(headers)) {
        await fulfillJson(route, {
          error: { code: "actor_name_required", message: "합성 안정 오류", details: null },
          request_id: requestId,
        }, 400);
        return;
      }
      // 실제 계약: 201건 이상은 FastAPI 기본 422(`too_long`)이고, 그 밖의 형식 오류보다
      // 앞서 검사한다(실제 서버가 pydantic 필드 검증을 먼저 거치는 것과 같은 순서).
      const rawIds = Array.isArray(body.order_plan_ids) ? body.order_plan_ids : [];
      if (rawIds.length > 200) {
        await fulfillJson(route, bulkEndTooLongError(rawIds), 422);
        return;
      }
      if (
        scenario === "validation-error"
        || !hasBulkKeys(body, ["schema_version", "request_id", "order_plan_ids", "reason"])
        || body.schema_version !== "order-plan-bulk-end-request.v1"
        || !requestId
        || !uuidPattern.test(requestId)
        || !validBulkIdList(body.order_plan_ids)
        || typeof body.reason !== "string"
        || !body.reason.trim()
      ) {
        await fulfillJson(route, {
          detail: [{ type: "uuid_parsing", loc: ["body", "request_id"], msg: "invalid", input: requestId }],
        }, 422);
        return;
      }
      const ids = bulkMockIds(body.order_plan_ids);
      const fingerprint = JSON.stringify({ body, actor: fixtureActor(headers) });
      const previous = endReceipts.get(requestId);
      if (previous) {
        if (previous.fingerprint !== fingerprint) {
          await fulfillJson(route, {
            error: { code: "idempotency_conflict", message: "합성 안정 오류", details: null },
            request_id: requestId,
          }, 409);
          return;
        }
        await fulfillJson(route, previous.response);
        return;
      }
      const response = options.endResponse ?? bulkMockEnd(requestId, ids, scenario);
      endReceipts.set(requestId, { fingerprint, response });
      applyBulkTrackingOverrides(page, response);
      await fulfillJson(route, response);
      return;
    }
    await route.fallback();
  });
  return trace;
}
