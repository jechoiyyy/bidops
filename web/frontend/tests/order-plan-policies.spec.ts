import { expect, test, type Page, type Route } from "@playwright/test";
import { mockApi } from "./api-mock";

/**
 * 발주계획 선별 정책 탭(C-2 활성화 화면) — `docs/0918_daily-operation/spec.md` §11.
 *
 * 화면이 **서버가 말한 활성화 조건을 그대로 보여 주는가**를 본다: blocker가 있으면
 * 활성화 단추가 닫히고 이유가 보이는지, `미측정`·`미달`·`통과`가 서로 다른 표면인지,
 * 활성화 확인 창이 digest와 "현재 버전의 자동 실행이 꺼집니다"를 다시 보여 주는지,
 * 스위치 옆 안내문구와 환경 cap 사유가 보이는지.
 *
 * 공용 `api-mock.ts`는 고치지 않는다. C-2 응답은 이 spec의 `page.route`가 주며,
 * `mockApi`보다 나중에 등록해 먼저 처리된다. mutation은 모두 가로챈다.
 */

const hex = (seed: string) => seed.repeat(64).slice(0, 64);

const ACTIVE = "c2-policy-v3";
const CANDIDATE_BLOCKED = "c2-policy-v4-blocked";
const CANDIDATE_READY = "c2-policy-v5-ready";
const DRAFT_UNMEASURED = "c2-policy-v6-draft";

const DIGEST: Record<string, { policy: string; binding: string; artifact: string }> = {
  [ACTIVE]: { policy: hex("a1"), binding: hex("b1"), artifact: hex("c1") },
  [CANDIDATE_BLOCKED]: { policy: hex("a2"), binding: hex("b2"), artifact: hex("c2") },
  [CANDIDATE_READY]: { policy: hex("a3"), binding: hex("b3"), artifact: hex("c3") },
  [DRAFT_UNMEASURED]: { policy: hex("a4"), binding: hex("b4"), artifact: hex("c4") },
};

const STATUS: Record<string, "draft" | "activation_candidate" | "active"> = {
  [ACTIVE]: "active",
  [CANDIDATE_BLOCKED]: "activation_candidate",
  [CANDIDATE_READY]: "activation_candidate",
  [DRAFT_UNMEASURED]: "draft",
};

const RESULT: Record<string, "통과" | "미달" | "미측정"> = {
  [ACTIVE]: "통과",
  [CANDIDATE_BLOCKED]: "미달",
  [CANDIDATE_READY]: "통과",
  [DRAFT_UNMEASURED]: "미측정",
};

function summary(version: string) {
  const active = STATUS[version] === "active";
  return {
    policy_version: version,
    policy_status: STATUS[version],
    quality_gate_status: active ? "passed" : "not_measured",
    policy_sha256: DIGEST[version].policy,
    binding_sha256: DIGEST[version].binding,
    created_by: "적재 담당",
    created_at: "2026-09-18T09:00:00+09:00",
    activated_by: active ? "승인 담당" : null,
    activated_at: active ? "2026-09-10T10:00:00+09:00" : null,
  };
}

const BLOCKERS: Record<string, { code: string; detail: string | null }[]> = {
  [ACTIVE]: [],
  [CANDIDATE_BLOCKED]: [
    { code: "quality_gate_not_passed", detail: "미달" },
    { code: "execution_transport_not_allowed", detail: null },
  ],
  [CANDIDATE_READY]: [],
  [DRAFT_UNMEASURED]: [
    { code: "quality_gate_thresholds_undecided", detail: null },
    { code: "quality_gate_not_passed", detail: "미측정" },
  ],
};

function gateId(version: string) {
  return `c2gate-${version.replace(/[^0-9]/g, "").padEnd(32, "0")}`;
}

function evaluation(version: string) {
  const status = RESULT[version];
  const failing = status === "미달";
  const undecided = status === "미측정";
  return {
    evaluation_id: `eval-${version}`,
    gate_id: gateId(version),
    revision: 2,
    result_status: status,
    pass_execution_ids: { pass_1: ["11111111-1111-4111-8111-111111111111"], pass_2: ["22222222-2222-4222-8222-222222222222"] },
    measured_recall_pct: failing ? 71.5 : 92.25,
    measured_precision_pct: 40,
    measured_important_missed: failing ? 3 : 0,
    measured_review_load: 38,
    metrics: {
      pass_1: { recall_pct: failing ? 71.5 : 92.25, precision_pct: 41, important_missed: failing ? 3 : 0, review_load: 36 },
      pass_2: { recall_pct: failing ? 74 : 93, precision_pct: 40, important_missed: failing ? 2 : 0, review_load: 38 },
      agreement_pct: 96.5,
      reference_full_window: { recall_pct: 90, precision_pct: 39, important_missed: 1, review_load: 44 },
    },
    reasons: failing
      ? ["threshold_not_met:recall_pct", "threshold_not_met:important_missed"]
      : undecided ? ["thresholds_undecided"] : [],
    artifact_sha256: DIGEST[version].artifact,
    evaluated_by: "측정 스크립트",
    evaluated_at: "2026-09-17T18:00:00+09:00",
  };
}

function gate(version: string) {
  const undecided = RESULT[version] === "미측정";
  return {
    gate_id: gateId(version),
    policy_version: version,
    policy_sha256: DIGEST[version].policy,
    binding_sha256: DIGEST[version].binding,
    gold_manifest_sha256: hex("d0"),
    gold_artifact_sha256: hex("d1"),
    gold_status: "approved",
    scoring_input_sha256: hex("d2"),
    evaluation_basis: "product_rerun",
    scoring_unit: "per_published_day",
    measurement_run_ids: ["order-plans-20260915", "order-plans-20260916"],
    required_pass_count: 2,
    thresholds: undecided
      ? { recall_pct: null, precision_pct: 35, important_missed_max: null, review_load_max: 50 }
      : { recall_pct: 90, precision_pct: 35, important_missed_max: 0, review_load_max: 50 },
    created_by: "측정 스크립트",
    created_at: "2026-09-17T12:00:00+09:00",
    latest_evaluation: evaluation(version),
    measurement_executions: [
      { execution_id: "11111111-1111-4111-8111-111111111111", source_run_id: "order-plans-20260915", status: "성공", queued_at: "2026-09-17T13:00:00+09:00", finished_at: "2026-09-17T13:40:00+09:00" },
      { execution_id: "22222222-2222-4222-8222-222222222222", source_run_id: "order-plans-20260916", status: "성공", queued_at: "2026-09-17T14:00:00+09:00", finished_at: "2026-09-17T14:45:00+09:00" },
    ],
  };
}

function referenceGate(version: string) {
  return {
    ...gate(version),
    gate_id: "c2gate-ffffffffffffffffffffffffffffffff",
    evaluation_basis: "reference_artifact_rescore",
    created_at: "2026-09-16T12:00:00+09:00",
    measurement_executions: [],
    latest_evaluation: { ...evaluation(version), evaluation_id: "eval-reference", gate_id: "c2gate-ffffffffffffffffffffffffffffffff", result_status: "통과", reasons: ["not_product_pipeline_result"], artifact_sha256: hex("e9") },
  };
}

function inspect(version: string) {
  const blockers = BLOCKERS[version];
  return {
    schema_version: "policy-inspect-response.v1",
    producer: "policy-api",
    consumer: "human-review-client",
    ...summary(version),
    binding_status: STATUS[version] === "active" ? "approved" : "activation_candidate",
    policy_file_present: true,
    binding_file_present: true,
    external_transport: {
      execution_allowed: version !== CANDIDATE_BLOCKED,
      approval_scope: "per_binding",
      approved_by: version === CANDIDATE_BLOCKED ? null : "전송 승인 담당",
      approved_at: version === CANDIDATE_BLOCKED ? null : "2026-09-16T09:00:00+09:00",
      approval_required_per_execution: false,
    },
    audit_sample: { enabled: true, max_per_execution: 20, review_cadence: "weekly" },
    quality_gate: {
      gate_id: gateId(version),
      evaluation_basis: "product_rerun",
      thresholds_decided: RESULT[version] !== "미측정",
      latest_evaluation: {
        evaluation_id: `eval-${version}`,
        revision: 2,
        result_status: RESULT[version],
        artifact_sha256: DIGEST[version].artifact,
        evaluated_at: "2026-09-17T18:00:00+09:00",
      },
    },
    activation_allowed: STATUS[version] === "activation_candidate" && blockers.length === 0,
    blockers,
  };
}

interface TriggerState {
  switchEnabled: boolean;
  reasons: string[];
  effective: boolean;
}

interface Calls {
  activate: Record<string, unknown>[];
  trigger: Record<string, unknown>[];
}

async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function open(page: Page, path: string, trigger: TriggerState = { switchEnabled: true, reasons: ["env_cap_off"], effective: false }): Promise<Calls> {
  const calls: Calls = { activate: [], trigger: [] };
  await mockApi(page);
  await page.route("**/api/order-plan-screening/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (path === "/api/order-plan-screening/policies" && method === "GET") {
      const versions = [DRAFT_UNMEASURED, CANDIDATE_READY, CANDIDATE_BLOCKED, ACTIVE];
      await fulfill(route, { schema_version: "policy-list-response.v1", producer: "policy-api", consumer: "human-review-client", items: versions.map(summary), total: versions.length });
      return;
    }
    const activateMatch = path.match(/^\/api\/order-plan-screening\/policies\/([^/]+)\/activate$/);
    if (activateMatch && method === "POST") {
      calls.activate.push(JSON.parse(request.postData() ?? "{}"));
      // 성공 뒤 새로 고침은 이 spec의 관심사가 아니다. 창이 닫히는지만 본다.
      const version = decodeURIComponent(activateMatch[1]);
      await fulfill(route, {
        schema_version: "policy-activate-response.v1", producer: "policy-api", consumer: "human-review-client",
        request_id: "00000000-0000-4000-8000-000000000000", policy_version: version, policy_status: "active", quality_gate_status: "passed",
        policy_sha256: DIGEST[version].policy, binding_sha256: DIGEST[version].binding, gate_id: gateId(version), evaluation_id: `eval-${version}`,
        previous_active_policy_version: ACTIVE, activated_by: "승인 담당", activated_at: "2026-09-18T10:00:00+09:00", audit_event_id: "audit-1",
      });
      return;
    }
    const inspectMatch = path.match(/^\/api\/order-plan-screening\/policies\/([^/]+)$/);
    if (inspectMatch && method === "GET") {
      await fulfill(route, inspect(decodeURIComponent(inspectMatch[1])));
      return;
    }
    if (path === "/api/order-plan-screening/quality-gates" && method === "GET") {
      const version = url.searchParams.get("policy_version") ?? "";
      const items = version === CANDIDATE_BLOCKED ? [gate(version), referenceGate(version)] : [gate(version)];
      await fulfill(route, { schema_version: "order-plan-quality-gate-list-response.v1", producer: "quality-gate-api", consumer: "human-review-client", policy_version: version, items });
      return;
    }
    if (path === "/api/order-plan-screening/daily-trigger" && method === "GET") {
      await fulfill(route, {
        schema_version: "daily-trigger-state-response.v1", producer: "daily-trigger-api", consumer: "human-review-client",
        effective_enabled: trigger.effective, policy_version: ACTIVE, policy_sha256: DIGEST[ACTIVE].policy,
        switch: { enabled: trigger.switchEnabled, reason: "운영 시작", set_by: "승인 담당", set_at: "2026-09-11T09:00:00+09:00" },
        reasons: trigger.reasons,
      });
      return;
    }
    if (path === "/api/order-plan-screening/daily-trigger" && method === "POST") {
      calls.trigger.push(JSON.parse(request.postData() ?? "{}"));
      await fulfill(route, { error: { code: "invalid_request", message: "x", details: null }, request_id: null }, 422);
      return;
    }
    await fulfill(route, { error: { code: "not_found", message: "고정 응답 없음", details: null }, request_id: null }, 404);
  });
  await page.goto(path);
  return calls;
}

const queue = (page: Page) => page.getByRole("region", { name: "발주계획 선별 policy", exact: true });
const detail = (page: Page) => page.getByRole("region", { name: "선택한 발주계획 선별 policy" });
const footer = (page: Page) => page.locator(".crit-detail-foot");
const surface = (page: Page) => page.locator(".opp-gate-surface");

/** 목록·상세·게이트가 모두 도착한 뒤에만 단정한다. loading shell은 근거가 아니다. */
async function waitForDetail(page: Page, version: string) {
  await expect(detail(page).getByRole("heading", { level: 2, name: version })).toBeVisible();
  await expect(surface(page)).toBeVisible();
}

test("탭 경로 /order-plan-policies로 바로 열리고 새 탭이 선택된다", async ({ page }) => {
  await open(page, "/order-plan-policies");
  await expect(page.getByRole("tab", { name: "발주계획 선별 정책", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#criteria-panel-order-plan-policies")).toBeVisible();
  // 목록은 digest 앞 12자만, 승인 전 버전은 활성화 기록이 없다고 말한다.
  await expect(queue(page)).toContainText(`policy ${DIGEST[CANDIDATE_BLOCKED].policy.slice(0, 12)}`);
  await expect(queue(page)).not.toContainText(DIGEST[CANDIDATE_BLOCKED].policy);
  await expect(queue(page).getByRole("button", { name: new RegExp(CANDIDATE_BLOCKED) })).toContainText("활성화 기록 없음");
});

test("blocker가 있으면 활성화 단추가 닫히고 이유가 옆에 보인다", async ({ page }) => {
  await open(page, `/order-plan-policies?c2policy=${CANDIDATE_BLOCKED}`);
  await waitForDetail(page, CANDIDATE_BLOCKED);
  await expect(footer(page).getByRole("button", { name: "활성화", exact: true })).toBeDisabled();
  await expect(footer(page)).toContainText("활성화할 수 없습니다");
  await expect(footer(page)).toContainText("최신 게이트 평가가 미달입니다");
  await expect(footer(page)).toContainText("외 1건");
  const list = detail(page).getByRole("list", { name: "활성화를 막는 조건" });
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(list).toContainText("외부 전송 승인");
  // 참조 재채점 게이트는 통과여도 활성화 근거가 아니라고 적는다.
  await expect(detail(page)).toContainText("참조 재채점 · 활성화 근거 아님");
});

test("미측정 · 미달 · 통과는 서로 다른 표면이다", async ({ page }) => {
  await open(page, `/order-plan-policies?c2policy=${DRAFT_UNMEASURED}`);
  await waitForDetail(page, DRAFT_UNMEASURED);
  await expect(surface(page)).toHaveAttribute("data-gate-result", "미측정");
  await expect(surface(page)).toHaveAttribute("data-tone", "neutral");
  await expect(surface(page)).toContainText("임계값 미정");
  await expect(surface(page)).toContainText("미측정은 미달이 아닙니다");
  await expect(detail(page).getByRole("table", { name: "임계값 대 측정값" })).toContainText("미정");
  // 초안은 후보 지정만 할 수 있다.
  await expect(footer(page).getByRole("button", { name: "후보로 지정" })).toBeEnabled();
  await expect(footer(page).getByRole("button", { name: "활성화", exact: true })).toHaveCount(0);

  await queue(page).getByRole("button", { name: new RegExp(CANDIDATE_BLOCKED) }).click();
  await waitForDetail(page, CANDIDATE_BLOCKED);
  await expect(surface(page)).toHaveAttribute("data-gate-result", "미달");
  await expect(surface(page)).toHaveAttribute("data-tone", "error");
  await expect(surface(page).getByRole("listitem")).toHaveText(["재현율 미달", "중요 누락 미달"]);

  await queue(page).getByRole("button", { name: new RegExp(CANDIDATE_READY) }).click();
  await waitForDetail(page, CANDIDATE_READY);
  await expect(surface(page)).toHaveAttribute("data-gate-result", "통과");
  await expect(surface(page)).toHaveAttribute("data-tone", "success");

  // 세 표면의 테두리 색이 실제로 다르다(미측정 중립 ≠ 미달 실패 ≠ 통과 성공).
  const colors: string[] = [];
  for (const version of [DRAFT_UNMEASURED, CANDIDATE_BLOCKED, CANDIDATE_READY]) {
    await queue(page).getByRole("button", { name: new RegExp(version) }).click();
    await waitForDetail(page, version);
    colors.push(await surface(page).evaluate((node) => getComputedStyle(node).borderLeftColor));
  }
  expect(new Set(colors).size).toBe(3);
});

test("활성화 확인 창은 digest와 현재 버전의 자동 실행이 꺼진다는 문구를 보여 주고 명시 확인을 보낸다", async ({ page }) => {
  const calls = await open(page, `/order-plan-policies?c2policy=${CANDIDATE_READY}`);
  await waitForDetail(page, CANDIDATE_READY);
  await expect(footer(page)).toContainText("blocker 0건");
  await footer(page).getByRole("button", { name: "활성화", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(DIGEST[CANDIDATE_READY].policy.slice(0, 12));
  await expect(dialog).toContainText(DIGEST[CANDIDATE_READY].artifact);
  await expect(dialog).toContainText(`현재 버전 ${ACTIVE}의 자동 실행이 꺼집니다. 활성화 뒤 이 화면에서 다시 켜세요.`);
  const submit = dialog.getByRole("button", { name: "활성화", exact: true });
  await dialog.getByLabel("확인 담당자 · 필수").fill("승인 담당");
  await expect(submit).toBeDisabled();
  await dialog.getByText("운영 활성화를 승인합니다").click();
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(dialog).toBeHidden();
  expect(calls.activate).toHaveLength(1);
  expect(calls.activate[0]).toMatchObject({
    schema_version: "policy-activate-request.v1",
    consumer: "policy-api",
    policy_sha256: DIGEST[CANDIDATE_READY].policy,
    quality_gate_artifact_sha256: DIGEST[CANDIDATE_READY].artifact,
    explicit_confirmation: true,
  });
});

test("스위치는 운영 활성 버전에만 있고 옆에 안내문구와 환경 cap 사유가 보인다", async ({ page }) => {
  await open(page, `/order-plan-policies?c2policy=${CANDIDATE_READY}`);
  await waitForDetail(page, CANDIDATE_READY);
  await expect(page.getByTestId("daily-trigger-row")).toHaveCount(0);

  await queue(page).getByRole("button", { name: new RegExp(ACTIVE) }).click();
  await waitForDetail(page, ACTIVE);
  const row = page.getByTestId("daily-trigger-row");
  await expect(row.getByRole("switch", { name: "이 버전의 일일 자동 실행 스위치" })).toBeChecked();
  await expect(row).toContainText("policy를 교체하면 자동 실행이 멈춥니다. 새 버전에서 다시 켜야 합니다.");
  await expect(row).toContainText("운영자가 환경 설정을 켜야 합니다");
  await expect(row).toContainText("자동 실행 꺼짐");
});

test("스위치를 끄려면 확인 창에서 사유와 명시 확인을 받는다", async ({ page }) => {
  const calls = await open(page, `/order-plan-policies?c2policy=${ACTIVE}`, { switchEnabled: true, reasons: [], effective: true });
  await waitForDetail(page, ACTIVE);
  const row = page.getByTestId("daily-trigger-row");
  await expect(row).toContainText("자동 실행 켜짐");
  await row.getByRole("switch", { name: "이 버전의 일일 자동 실행 스위치" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("일일 자동 실행을 끕니다");
  const submit = dialog.getByRole("button", { name: "자동 실행 끄기" });
  await dialog.getByLabel("확인 담당자 · 필수").fill("승인 담당");
  await dialog.getByText("이 버전의 일일 자동 실행을 끕니다").click();
  await expect(submit).toBeDisabled();
  await dialog.getByLabel("사유 · 필수 (200자 이내)").fill("점검 기간");
  await submit.click();
  // mock은 422를 돌려준다. 창은 닫히지 않고 입력이 남는다.
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(dialog.getByLabel("사유 · 필수 (200자 이내)")).toHaveValue("점검 기간");
  expect(calls.trigger[0]).toMatchObject({ policy_version: ACTIVE, enabled: false, reason: "점검 기간", explicit_confirmation: true });
});

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test.describe(`${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });

    test(`탭 다섯 개와 상세 하단 액션이 ${viewport.width}px 안에 들어온다`, async ({ page }, testInfo) => {
      await open(page, `/order-plan-policies?c2policy=${CANDIDATE_BLOCKED}`);
      await waitForDetail(page, CANDIDATE_BLOCKED);
      await expect(page.locator(".crit-tabs [role=\"tab\"]")).toHaveCount(5);
      const action = footer(page).getByRole("button", { name: "활성화", exact: true });
      const box = await action.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
      // 상세의 표(임계값 대 측정값·측정 실행)가 상세 폭을 넘어 잘리지 않는다.
      const detailOverflow = await page.locator(".crit-detail-scroll").evaluate((node) => node.scrollWidth - node.clientWidth);
      expect(detailOverflow).toBeLessThanOrEqual(0);
      await page.screenshot({ path: testInfo.outputPath(`order-plan-policies-${viewport.width}.png`), animations: "disabled" });
    });
  });
}
