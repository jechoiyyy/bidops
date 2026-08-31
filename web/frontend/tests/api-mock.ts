import type { Page } from "@playwright/test";
import fixtures from "./fixtures/api.json" with { type: "json" };
import { getVisualResponse } from "./fixtures/visual-api";

const responses = fixtures as Record<string, unknown>;

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

export type DeepReviewFixtureScenario = "completed" | "polling" | "failed";

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
    const body =
      syntheticResponse(pathname) ?? responses[pathname] ?? getVisualResponse(pathname, page.url());
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
