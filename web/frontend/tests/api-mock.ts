import type { Route, Page } from "@playwright/test";
import fixtures from "./fixtures/api.json" with { type: "json" };
import { getVisualResponse } from "./fixtures/visual-api";

import type {
  BidDeltaDecisionQueueItem, OpportunityListItem, OpportunitySectionCounts,
  OpportunityTrackingDecisionItem, OpportunityTrackingStatus, OrderPlanListItem,
  OrderPlanListScope, OrderPlanScreeningExecutionSummary, OrderPlanScreeningErrorCode,
  OrderPlanTracking, PreSpecListItem, WorkloadKey, WorkloadResponse,
} from "../src/lib/types";
import { clickReadyUnlinkedPreSpec, decisionQueueItems, opportunityDeepReviews, opportunityTrackingHistory } from "./fixtures/lifecycle-v2";

const opportunityFixtures = new WeakMap<Page, OpportunityListItem[]>();
const workloadProviders = new WeakMap<Page, Map<WorkloadKey, () => { count: number | null; unavailable_reason: string | null }>>();
function workloadProvider(page: Page, key: WorkloadKey, provider: () => { count: number | null; unavailable_reason: string | null }) {
  let providers = workloadProviders.get(page);
  if (!providers) { providers = new Map(); workloadProviders.set(page, providers); }
  providers.set(key, provider);
}
function workloadResponse(page: Page): WorkloadResponse {
  const keys: WorkloadKey[] = ["order_plan_pending", "pre_spec_deep_review_ready", "tracking_action_required", "bid_final_decision_pending"];
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
const FIXTURE_STRUCTURE_ID = "fixture-structure";

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
      },
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
      },
    ],
    inventory_summary: {
      expected_ids: ["SFR-1", "SFR-2", "SFR-3"],
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
      item_count: 4,
    },
    coverage: {
      block_count: 6,
      covered_block_count: 5,
      segment_count: 2,
      gap_count: 1,
      overlap_count: 0,
      gaps: [{ start_ordinal: 5, end_ordinal: 5 }],
      overlaps: [],
      needs_human_review_count: 1,
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
    schema_version: "bidops.bid-final-decision.v1",
    id: `aaaaaaaa-1111-4111-8111-aaaaaaaaaaa${sequence}`,
    opportunity_id: 501,
    sequence,
    comparison_id: bidDeltaComparisonId,
    comparison_version: comparisonVersion,
    result_sha256: "e".repeat(64),
    baseline_document_version_id: bidDeltaBaseline.document_version_id,
    comparison_document_version_id: bidDeltaComparison.document_version_id,
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
function mockTrackingSection(item: OpportunityListItem): OpportunityListItem["section"] {
  if ((item.tracking_status === "미선택" && item.first_registered_stage === "bid_notice") || item.recheck_signal || item.pending_candidate_link_count > 0 || item.open_blocking_item_count > 0) return "조치 필요";
  return item.tracking_status === "보류" ? "보류" : item.tracking_status === "종료" ? "추적 종료" : item.tracking_status === "계속 추적" ? "추적 중" : null;
}

export async function mockOpportunity(page: Page): Promise<void> {
  const items: OpportunityListItem[] = structuredClone(visualOpportunities);
  items.push(
    { ...structuredClone(items[0]), id: 304, tracking_status: "보류", section: "보류", links: [] },
    { ...structuredClone(items[0]), id: 305, tracking_status: "종료", section: "추적 종료", links: [] },
    { ...structuredClone(items[0]), id: 306, tracking_status: "미선택", first_registered_stage: "bid_notice", section: "조치 필요", links: [] },
    ...decisionQueueItems.map((item): OpportunityListItem => ({
      ...structuredClone(visualOpportunities[0]), id: item.opportunity_id,
      tracking_status: "계속 추적", section: "추적 중", first_registered_stage: "pre_spec",
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
  workloadProvider(page, "tracking_action_required", () => ({ count: items.filter((item) => item.section === "조치 필요").length, unavailable_reason: null }));
  await page.route("**/api/opportunities**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/opportunities" && request.method() === "GET") {
      const search = url.searchParams;
      let filtered = items.filter((item) => (!search.get("tracking_status") || item.tracking_status === search.get("tracking_status")) && (!search.get("first_registered_stage") || item.first_registered_stage === search.get("first_registered_stage")));
      const section_counts: OpportunitySectionCounts = { "조치 필요": 0, "추적 중": 0, "보류": 0, "추적 종료": 0, "미결정": 0 };
      for (const item of filtered) section_counts[item.section ?? "미결정"] += 1;
      if (search.get("section")) filtered = filtered.filter((item) => item.section === search.get("section"));
      if (search.get("sort") === "tracking_status") filtered.sort((a, b) => a.tracking_status.localeCompare(b.tracking_status));
      if (search.get("sort") === "first_registered_stage") filtered.sort((a, b) => a.first_registered_stage.localeCompare(b.first_registered_stage));
      const limit = Number(search.get("limit") ?? 50), offset = Number(search.get("offset") ?? 0);
      await fulfillJson(route, { items: filtered.slice(offset, offset + limit), total: filtered.length, limit, offset, section_counts });
      return;
    }
    const match = url.pathname.match(/^\/api\/opportunities\/(\d+)(?:\/(tracking-status|tracking-decisions|deep-reviews))?$/);
    if (!match) { await route.fallback(); return; }
    const item = items.find((candidate) => candidate.id === Number(match[1]));
    if (!item) { await fulfillJson(route, { detail: "사업기회를 찾을 수 없습니다" }, 404); return; }
    if (request.method() === "GET") {
      await fulfillJson(route, match[2] === "tracking-decisions" ? { opportunity_id: item.id, items: histories.get(item.id) ?? [] }
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
      item.tracking_status = body.tracking_status as OpportunityTrackingStatus;
      item.tracking_reason = item.tracking_status === "미선택" ? null : body.reason;
      item.tracking_selected_by = item.tracking_status === "미선택" ? null : actor;
      item.tracking_selected_at = item.tracking_status === "미선택" ? null : decisions[0].decided_at;
      item.recheck_signal = false; item.recheck_signal_at = null; item.recheck_signal_link_id = null;
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

const visualPreSpecNotice = {
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
    auto_preparation_status: "blocked",
    auto_preparation_reason: "bundle_has_blocking_issues",
    latest_deep_review_id: null,
  },
  {
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
    auto_preparation_status: "not_applicable",
    auto_preparation_reason: null,
    latest_deep_review_id: null,
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

const visualUnknownOverview = {
  schema_version: "bidops.prespec-overview-reviews.v2",
  notice_id: 991,
  reviews: [{
    id: "00000000-0000-0000-0000-000000000991",
    notice_id: 991,
    status: "needs_human_review",
    result: null,
    result_digest: null,
    binding_digest: null,
    quality_status: null,
    validation_status: "pending",
    completed_at: null,
    current_snapshot: {
      id: "10000000-0000-0000-0000-000000000991",
      document_version_id: "20000000-0000-0000-0000-000000000991",
      structure_id: "30000000-0000-0000-0000-000000000991",
      source_sha256: "a".repeat(64),
      payload_sha256: "b".repeat(64),
      cut_status: "unknown",
      strategy: null,
      start_locator: null,
      end_locator: null,
      created_at: "2026-08-31T01:00:00Z",
    },
    attempts: [],
  }],
};

function visualCompletedOverview() {
  const review = visualUnknownOverview.reviews[0];
  return {
    ...visualUnknownOverview,
    reviews: [{
      ...review,
      status: "completed",
      result: {
        schema_version: "bidops.prespec-overview-result.v1",
        recommendation: "조건부 추진 검토",
        summary: "공공기관의 민원·행정 데이터를 통합해 현황을 분석하고, 담당자가 업무 현황을 조회하는 행정 지원 플랫폼 구축 사업입니다.",
        conditions: [
          "기존 시스템 연계 범위와 기관별 데이터 제공 책임을 착수 전에 확인해야 합니다.",
          "운영 전환과 개인정보 처리 범위에 대한 발주기관의 확정 답변이 필요합니다.",
        ],
        verification_due_at: "2026-09-01T00:00:00Z",
        unknowns: [
          {
            topic: "기존 시스템 연계 범위",
            reason: "개요 입력에는 연계 대상과 제공 API의 목록이 없습니다.",
            verification_action: "심층 검토에서 연계 대상별 인터페이스 명세를 확인합니다.",
          },
          {
            topic: "개인정보 처리 책임",
            reason: "운영 주체와 개인정보 처리 역할이 개요에서 확정되지 않았습니다.",
            verification_action: null,
          },
        ],
        evidence: [{
          claim: "사업은 행정 지원 플랫폼 구축과 기존 업무 데이터 연계를 포함합니다.",
          locator: { block_key: "overview-intro", page: 2, ordinal: 7 },
        }],
        input_limitations: [
          "제안요청서 앞부분의 개요 입력만 검토했으며 상세 요구사항은 확인하지 않았습니다.",
          "참가자격, 실적요건, 평가 배점과 제출물은 이 결과에 포함하지 않습니다.",
        ],
      },
      result_digest: "c".repeat(64),
      binding_digest: "d".repeat(64),
      quality_status: "unmeasured_reference",
      validation_status: "passed",
      completed_at: "2026-08-31T02:00:00Z",
      current_snapshot: { ...review.current_snapshot, cut_status: "ready", strategy: "topic_heading" },
      attempts: [{
        id: "00000000-0000-0000-0000-000000000992",
        snapshot_id: "10000000-0000-0000-0000-000000000991",
        sequence: 1,
        status: "completed",
        reference_only: false,
        deployable: true,
        quality_status: "unmeasured_reference",
        validation_status: "passed",
        result_digest: "c".repeat(64),
        binding_digest: "d".repeat(64),
        created_at: "2026-08-31T01:30:00Z",
        started_at: "2026-08-31T01:35:00Z",
        completed_at: "2026-08-31T02:00:00Z",
      }],
    }],
  };
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

/** Deterministic pre-spec list/detail fixture, including the unknown overview. */
export async function mockPreSpecs(page: Page, overviewState: "completed" | "unknown" = "completed"): Promise<void> {
  let currentTrackingStatus = visualPreSpecItems[0].tracking_status;
  workloadProvider(page, "pre_spec_deep_review_ready", () => ({ count: visualPreSpecItems.filter((item) => item.auto_preparation_status === "deep_review_ready_for_click").length, unavailable_reason: null }));
  await page.route("**/api/pre-specs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/pre-specs" && request.method() === "GET") {
      const requestedNoticePk = Number(url.searchParams.get("notice_pk"));
      const items = visualPreSpecItems
        .map((item) => item.notice_pk === 991 ? { ...item, tracking_status: opportunityFixtures.get(page)?.find((entry) => entry.id === 202)?.tracking_status ?? currentTrackingStatus } : item)
        .filter((item) => !url.searchParams.has("notice_pk") || item.notice_pk === requestedNoticePk)
        .filter((item) => url.searchParams.get("sw_only") === "false" || item.sw_business_status === "Y" || item.kept_by_tracking)
        .filter((item) => !url.searchParams.get("auto_preparation_status") || item.auto_preparation_status === url.searchParams.get("auto_preparation_status"))
        .filter((item) => !url.searchParams.get("business_division") || item.business_division === url.searchParams.get("business_division"))
        .filter((item) => !url.searchParams.get("origin") || item.origin === url.searchParams.get("origin"))
        .filter((item) => !url.searchParams.get("q") || `${item.title} ${item.agency} ${item.pre_spec_no}`.includes(url.searchParams.get("q")!));
      const limit = Number(url.searchParams.get("limit") ?? 50), offset = Number(url.searchParams.get("offset") ?? 0);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: items.slice(offset, offset + limit), total: items.length, limit, offset, overview_status_counts: overviewStatusCounts(items) }),
      });
      return;
    }
    if (url.pathname === "/api/pre-specs/991/overview-reviews/v2" && request.method() === "GET") {
      const overview = overviewState === "unknown" ? visualUnknownOverview : visualCompletedOverview();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(overview) });
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
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: preSpecMatrixItems,
        total: preSpecMatrixItems.length,
        limit: 200,
        offset: 0,
        overview_status_counts: overviewStatusCounts(preSpecMatrixItems),
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
        body: JSON.stringify({ items: [item], total: 1, limit: 50, offset: 0, overview_status_counts: overviewStatusCounts([item]) }),
      });
      return;
    }
    if (url.pathname === "/api/pre-specs/991/overview-reviews/v2" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(visualCompletedOverview()) });
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
        body: JSON.stringify({ items, total: items.length, limit: 50, offset: 0, overview_status_counts: overviewStatusCounts(items) }),
      });
      return;
    }
    if (pathname === "/api/pre-specs/991/overview-reviews/v2" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(visualUnknownOverview) });
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
    const match = pathname.match(/^\/api\/pre-specs\/(\d+)\/overview-pages$/);
    if (match) { await fulfillJson(route, { schema_version: "bidops.prespec-overview-pages.v1", notice_id: Number(match[1]), reviews: [] }); return; }

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

const c2Items: Omit<OrderPlanListItem, "tracking">[] = [
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

const c2LargeItems: Omit<OrderPlanListItem, "tracking">[] = Array.from({ length: 1200 }, (_, index) => {
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
  schema_version: "order-plan-detail-response.v3",
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
  observations: [
    { source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101", observed_at: "2026-09-01T01:00:00Z", source_sha256: c2Digest("m") },
    { source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0831", observed_at: "2026-08-31T01:00:00Z", source_sha256: null },
  ],
  screening_history: [
    {
      execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010101", source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101", policy_version: "c2-policy.v1", policy_sha256: c2Digest("a"), binding_sha256: c2Digest("b"), execution_status: "부분 성공", stage1_status: "selected", stage1_rank: 1, stage1_score: 0.92, nearest_capability: "데이터 플랫폼 구축·운영", batch_id: "batch-20260901-01", attempt_no: 2, stage2_status: "success", qwen_relevance: "relevant", qwen_score: 0.96, qwen_reason: "데이터 플랫폼 구축과 운영 범위가 확인됩니다.", feedback_revision_count: 1,
    },
    {
      execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d083101", source_run_id: "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0831", policy_version: "c2-policy.v1", policy_sha256: c2Digest("e"), binding_sha256: c2Digest("f"), execution_status: "성공", stage1_status: "selected", stage1_rank: 4, stage1_score: 0.88, nearest_capability: "데이터 플랫폼 구축", batch_id: "batch-20260831-01", attempt_no: 1, stage2_status: "success", qwen_relevance: "uncertain", qwen_score: 0.62, qwen_reason: "이전 실행에서는 범위 확인이 필요했습니다.", feedback_revision_count: 0,
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
    schema_version: "execution-detail-response.v1",
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
  const planItems: Omit<OrderPlanListItem, "tracking">[] = scenario === "no-results" ? [] : scenario === "large" ? c2LargeItems : [...c2Items, {
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
  function scopeFor(sourceRunId: string | null): OrderPlanListScope | null {
    const eligible = executions.filter((item) => (item.status === "성공" || item.status === "부분 성공") && (!sourceRunId || item.source_run_id === sourceRunId));
    eligible.sort((a, b) => (b.finished_at ?? "").localeCompare(a.finished_at ?? "") || b.queued_at.localeCompare(a.queued_at) || b.execution_id.localeCompare(a.execution_id));
    const latest = eligible[0];
    return latest ? { execution_id: latest.execution_id, source_run_id: latest.source_run_id, status: latest.status as OrderPlanListScope["status"], finished_at: latest.finished_at } : null;
  }
  function trackingProjection(orderPlanPk: number): OrderPlanTracking | null {
    if (scenario === "no-owning-opportunity") return null;
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
        links: [{ ...visualOpportunities[0].links[0], id: 5000 + plan.order_plan_pk,
          record_id: plan.order_plan_pk, order_plan_id: plan.order_plan_pk,
          title: plan.title, agency: plan.agency_name,
          external_id: plan.order_plan_unty_no, record_external_id: plan.order_plan_unty_no }],
      })));
    }
  }
  function listItems(search: URLSearchParams): OrderPlanListItem[] {
    const scope = scopeFor(search.get("source_run_id"));
    return planItems.map((item): OrderPlanListItem => {
      const feedback = feedbackItems.filter((entry) => entry.order_plan_pk === item.order_plan_pk && entry.execution_id === scope?.execution_id).at(-1);
      return {
        ...item,
        ...(!scope ? { stage1_status: null, stage1_rank: null, stage1_score: null, stage2_status: null, qwen_relevance: null, qwen_score: null, qwen_reason: null } : {}),
        human_feedback: feedback ? { revision: feedback.revision, relevance: feedback.relevance as "relevant" | "not_relevant" | "uncertain", priority: feedback.priority as "high" | "medium" | "low" | null, memo: feedback.memo, claimed_name: feedback.claimed_name, created_at: feedback.created_at } : null,
        tracking: trackingProjection(item.order_plan_pk),
      };
    }).filter((item) => (!search.get("source_run_id") || item.source_run_id === search.get("source_run_id"))
      && matchesValues(item.stage1_status, search.get("stage1_status"))
      && matchesValues(item.stage2_status, search.get("stage2_status"))
      && matchesValues(item.qwen_relevance, search.get("qwen_relevance"))
      && matchesValues(item.human_feedback?.relevance ?? null, search.get("human_relevance"))
      && (!search.get("tracking_status") || (item.tracking !== null && matchesValues(item.tracking.tracking_status, search.get("tracking_status"))))
      && (search.get("issue") !== "true" || ["failed", "rejected"].includes(item.stage1_status ?? "") || ["failed", "rejected"].includes(item.stage2_status ?? ""))
      && (!search.get("q") || `${item.title} ${item.agency_name} ${item.order_plan_unty_no}`.toLocaleLowerCase("ko-KR").includes(search.get("q")!.toLocaleLowerCase("ko-KR"))));
  }
  workloadProvider(page, "order_plan_pending", () => scopeFor(null)
    ? { count: listItems(new URLSearchParams({ stage1_status: "selected", qwen_relevance: "relevant,uncertain", tracking_status: "미선택" })).length, unavailable_reason: null }
    : { count: null, unavailable_reason: "no_completed_execution" });

  const createdRequests = new Map<string, { payload: string; response: unknown }>();
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  async function error(route: Route, code: OrderPlanScreeningErrorCode, requestId: unknown = null, status = 409) {
    await fulfillJson(route, { error: { code, message: "합성 안정 오류", details: null }, request_id: typeof requestId === "string" && uuidPattern.test(requestId) ? requestId : null }, status);
  }
  await page.route("**/api/**", async (route) => {
    const request = route.request(), method = request.method();
    const url = new URL(request.url()), pathname = url.pathname, search = url.searchParams;
    if (pathname === "/api/order-plan-screening/executions" && method === "GET") {
      const filtered = executions.filter((item) => (!search.get("source_run_id") || item.source_run_id === search.get("source_run_id")) && (!search.get("status") || item.status === search.get("status")));
      const limit = Number(search.get("limit") ?? 100), offset = Number(search.get("offset") ?? 0);
      await fulfillJson(route, { schema_version: "execution-list-response.v1", producer: "screening-api", consumer: "human-review-client", items: filtered.slice(offset, offset + limit), total: filtered.length, limit, offset }); return;
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
    if (pathname === "/api/order-plans" && method === "GET") {
      const items = listItems(search), limit = Number(search.get("limit") ?? 100), offset = Number(search.get("offset") ?? 0);
      await fulfillJson(route, { schema_version: "order-plan-list-response.v3", producer: "order-plan-review-api", consumer: "order-plan-review-client", scope: scopeFor(search.get("source_run_id")), items: items.slice(offset, offset + limit).map((item) => {
        if (!options.omitTracking) return item;
        const { tracking: _tracking, ...legacy } = item;
        return legacy;
      }), total: items.length, limit, offset }); return;
    }
    const planMatch = pathname.match(/^\/api\/order-plans\/(\d+)(?:\/(screening-history|screening-feedback))?$/);
    if (planMatch) {
      const orderPlanPk = Number(planMatch[1]), plan = listItems(new URLSearchParams()).find((item) => item.order_plan_pk === orderPlanPk);
      if (!plan) { await error(route, "not_found", null, 404); return; }
      const history = scopeFor(null) && orderPlanPk === 101 ? c2Detail.screening_history : [];
      if (method === "GET" && !planMatch[2]) {
        await fulfillJson(route, { ...c2Detail, order_plan_pk: orderPlanPk, order_plan_unty_no: plan.order_plan_unty_no, source_url: plan.source_url, title: plan.title, agency_name: plan.agency_name, budget_amount: plan.budget_amount, business_division: plan.business_division, planned_order_year: plan.planned_order_year, planned_order_month: plan.planned_order_month, screening_history: history, latest_human_feedback: plan.human_feedback, tracking: plan.tracking }); return;
      }
      if (method === "GET" && planMatch[2] === "screening-history") { await fulfillJson(route, { schema_version: "order-plan-detail-response.v1", producer: "screening-api", consumer: "order-plan-review-client", order_plan_pk: orderPlanPk, items: history }); return; }
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
