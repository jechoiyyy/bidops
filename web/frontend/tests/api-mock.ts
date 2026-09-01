import type { Page } from "@playwright/test";
import fixtures from "./fixtures/api.json" with { type: "json" };
import { getVisualResponse } from "./fixtures/visual-api";

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
};

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

const visualOpportunities = [
  {
    id: 101,
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

/** Deterministic opportunity list/detail fixture shared by visual coverage. */
export async function mockOpportunity(page: Page): Promise<void> {
  await page.route("**/api/opportunities**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const match = url.pathname.match(/^\/api\/opportunities\/(\d+)$/);
    if (url.pathname === "/api/opportunities" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: visualOpportunities, total: visualOpportunities.length, limit: 50, offset: 0 }),
      });
      return;
    }
    if (match && request.method() === "GET") {
      const item = visualOpportunities.find((candidate) => candidate.id === Number(match[1]));
      await route.fulfill({
        status: item ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(item ?? { detail: "사업기회를 찾을 수 없습니다" }),
      });
      return;
    }
    await route.fallback();
  });
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

const visualPreSpecItems = [
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
  },
] as const;

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
  let currentTrackingStatus: string = visualPreSpecItems[0].tracking_status;
  await page.route("**/api/pre-specs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/pre-specs" && request.method() === "GET") {
      const requestedNoticePk = Number(url.searchParams.get("notice_pk"));
      const items = visualPreSpecItems
        .map((item) => item.notice_pk === 991 ? { ...item, tracking_status: currentTrackingStatus } : item)
        .filter((item) => !url.searchParams.has("notice_pk") || item.notice_pk === requestedNoticePk);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, total: items.length, limit: 50, offset: 0 }),
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
    currentTrackingStatus = body.tracking_status;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 202,
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
        body: JSON.stringify({ items, total: items.length, limit: 50, offset: 0 }),
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
 * 갈무리해 둔 응답을 경로 이름으로 되돌려 준다.
 * 조회 문자열은 무시한다. 시각 회귀 테스트는 기본 필터 상태만 찍기 때문이다.
 */
export async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
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
}
