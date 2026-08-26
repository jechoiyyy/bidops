import type { Page } from "@playwright/test";
import fixtures from "./fixtures/api.json" with { type: "json" };

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

const syntheticReview = {
  id: "fixture-review", notice_id: 1, bundle_id: "fixture-bundle", status: "completed",
  created_at: "2026-08-26T00:00:00Z", completed_at: "2026-08-26T00:00:01Z",
  current_attempt: {
    id: "fixture-attempt", sequence: 1, status: "completed", started_at: "2026-08-26T00:00:00Z", completed_at: "2026-08-26T00:00:01Z", last_error_code: null,
    stages: ["requirements_and_evaluation", "delivery_risk_economics", "synthesis_and_validation"].map((stage, sequence) => ({ stage, sequence, status: "completed", started_at: "2026-08-26T00:00:00Z", completed_at: "2026-08-26T00:00:01Z", last_error_code: null })),
  },
  attempts: [],
};

function syntheticResponse(pathname: string): unknown | undefined {
  if (pathname === "/api/deep-reviews/fixture-review") return syntheticReview;
  if (pathname === "/api/deep-reviews/fixture-review/report") return { deep_review_id: "fixture-review", current_revision_id: "fixture-revision", report: syntheticReport, validation: { schema: "bidops.deep-review-validation.v1", validation_run_id: "fixture-validation", report_revision_id: "fixture-revision", status: "passed", checks: [{ check_type: "fixture", status: "passed", severity: "낮음", message: "synthetic fixture", related_claim_ids: ["fixture-claim-1"], related_evidence_ids: [fixtureEvidenceId] }], created_at: "2026-08-26T00:00:00Z" }, history: [{ revision_id: "fixture-revision", sequence: 1, origin: "machine", validation_status: "passed", created_by_name: null, created_at: "2026-08-26T00:00:00Z" }], final_opinion: null };
  if (pathname === `/api/evidence/${fixtureEvidenceId}`) return { evidence_id: fixtureEvidenceId, source_kind: "document", document_version_id: "fixture-document", structure_id: "fixture-structure", profile_version_id: null, profile_evidence_id: null, locator_type: "page", locator: { page: 1 }, quote: "synthetic fixture evidence", confidence: 0.99, source_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", page: { structure_id: "fixture-structure", page: 1, metadata: { number: 1, width: 100, height: 100, image_content_object_id: null }, blocks: [{ block_key: "fixture-block", parent_block_key: null, type: "paragraph", page: 1, bbox: [0, 0, 100, 100], text: "synthetic fixture evidence", confidence: 0.99, attributes: {} }] } };
  return undefined;
}

/**
 * 갈무리해 둔 응답을 경로 이름으로 되돌려 준다.
 * 조회 문자열은 무시한다. 시각 회귀 테스트는 기본 필터 상태만 찍기 때문이다.
 */
export async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const body = syntheticResponse(pathname) ?? responses[pathname];
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
