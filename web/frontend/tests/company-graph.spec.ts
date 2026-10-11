import { expect, test, type Page, type Route } from "@playwright/test";
import { mockApi, mockCompanyWorkspace } from "./api-mock";
import { COMPANY_BY_SLUG, LONG_GRAPH_LABEL, fixtureSha, knowledgeGraphView, profileEvidenceIdFor } from "./fixtures/company-demo";

/*
 * DEMO-04 STEP-002 · spec T2(관계 목록·근거 패널·키보드·가상 표식·초점 복귀·절단 안내)와
 * T6 중 이 화면 몫(1440 폭의 긴 한글 label 가로 넘침 0, 로딩을 완료로 보이지 않음).
 * 두 폭 구조 검사(`company-layout.spec.ts`)는 STEP-005다.
 *
 * 고정 응답은 `tests/api-mock.ts`의 `mockCompanyWorkspace`(fixture `company-demo.ts`)이며
 * 실제 백엔드에 연결하지 않는다. 화면이 관계를 만들지 않는다는 것은 "그린 노드·관계 id가
 * 응답의 id와 정확히 같다"로 확인한다.
 */

const company = COMPANY_BY_SLUG["demo-public-si"];
const companyId = company.company_id;
const profilePath = `/companies/${companyId}/profile`;
const graphApi = `/api/companies/${companyId}/knowledge-graph`;
const graphBase = `GET ${graphApi}?graph_version_id=${company.graph_version_id}`;

const graph = (page: Page) => page.getByTestId("company-graph");
const panel = (page: Page) => page.getByTestId("graph-evidence-panel");
const nodeRow = (page: Page, id: string) => graph(page).locator(`li[data-node-id="${id}"]`);
const nodeTrigger = (page: Page, id: string) => graph(page).locator(`[data-graph-trigger="node:${id}"]`);
const edgeRow = (page: Page, id: string) => graph(page).locator(`li[data-edge-id="${id}"]`);
const edgeTrigger = (page: Page, id: string) => graph(page).locator(`[data-graph-trigger="edge:${id}"]`);
const relationRegion = (page: Page) => graph(page).getByRole("region", { name: "관계 목록" });
const nodeRegion = (page: Page) => graph(page).getByRole("region", { name: "노드 목록" });

async function installMocks(page: Page, options: { profileNotReadyCompanyIds?: string[] } = {}) {
  await mockApi(page);
  return mockCompanyWorkspace(page, options);
}

function graphRequests(requests: string[]): string[] {
  return requests.filter((entry) => entry.startsWith(`GET ${graphApi}`));
}

async function renderedIds(page: Page) {
  return {
    nodes: await graph(page).locator("li[data-node-id]").evaluateAll((items) => items.map((item) => item.getAttribute("data-node-id"))),
    edges: await graph(page).locator("li[data-edge-id]").evaluateAll((items) => items.map((item) => item.getAttribute("data-edge-id"))),
  };
}

type GraphBody = { nodes: Array<{ id: string; type: string }>; edges: Array<{ id: string }>; truncated: boolean; omitted_node_count: number };

function waitForGraph(page: Page) {
  return page.waitForResponse((response) => response.request().method() === "GET" && new URL(response.url()).pathname === graphApi);
}

test("관계 목록은 서버 노드를 유형별로 묶고 관계 행을 그대로 보여 주며 버전·가상 표식·미확인을 문자로 구분한다", async ({ page }) => {
  const trace = await installMocks(page);
  const response = waitForGraph(page);
  await page.goto(profilePath);
  const body = (await (await response).json()) as GraphBody;
  await expect(graph(page)).toHaveAttribute("data-graph-state", "ready");

  // 첫 조회는 프로필의 graph_version_id와 기본 depth 2·limit 200이며 root가 없다(회사 노드).
  expect(graphRequests(trace.requests)).toEqual([`${graphBase}&depth=2&limit=200`]);
  await expect(graph(page).getByTestId("graph-version")).toHaveText(
    `그래프 버전 ${company.graph_version_id} · 그래프 sha256 ${fixtureSha("demo-public-si:graph").slice(0, 12)} · 온톨로지 demo-ontology-v1`,
  );

  // 화면이 관계를 만들거나 빼지 않는다: 그린 관계 id = 응답 관계 id(순서까지), 노드 id 집합 = 응답 노드 id 집합.
  const ids = await renderedIds(page);
  expect(ids.edges).toEqual(body.edges.map((edge) => edge.id));
  expect([...ids.nodes].sort()).toEqual(body.nodes.map((node) => node.id).sort());
  expect(body.edges).toHaveLength(13);
  await expect(relationRegion(page).locator("li[data-edge-id]")).toHaveCount(13);

  // 노드 유형별 묶음(묶음 순서는 고정 표시 순서), 묶음 안은 서버 순서.
  const groups = await graph(page).locator("[data-node-group]").evaluateAll((items) => items.map((item) => item.getAttribute("data-node-group")));
  expect(groups).toEqual(["company", "capability", "technology", "domain", "staff_group", "project", "qualification", "evidence"]);
  const capabilityGroup = graph(page).getByRole("region", { name: "역량 노드" });
  await expect(capabilityGroup.getByRole("heading", { level: 5 })).toHaveText("역량 3개");
  const capabilityIds = await capabilityGroup.locator("li[data-node-id]").evaluateAll((items) => items.map((item) => item.getAttribute("data-node-id")));
  expect(capabilityIds).toEqual(body.nodes.filter((node) => node.type === "capability").map((node) => node.id));

  // 관계 행: from label — 관계 유형(한국어) → to label.
  const uses = edgeRow(page, "edge.minwon.uses_technology.egov");
  await expect(uses.locator("[data-edge-from]")).toHaveText("민원 통합 시스템 구축");
  await expect(uses.locator("[data-edge-label]")).toHaveText("— 사용 기술 →");
  await expect(uses.locator("[data-edge-to]")).toHaveText("전자정부 표준프레임워크");
  await expect(edgeRow(page, "edge.minwon.supports_capability.public_admin").locator("[data-edge-label]")).toHaveText("— 역량 관련 근거(충족 보증 아님) →");

  // 확실성·출처를 문자로: 가상회사 confirmed는 "시나리오 확정", inferred는 "추정", unknown은 "미확인".
  const publicAdmin = nodeRow(page, "capability.public_admin");
  await expect(publicAdmin.locator("[data-status-label]")).toHaveText("시나리오 확정");
  await expect(publicAdmin.locator("[data-origin-label]")).toHaveText("가상 설정");
  await expect(publicAdmin).toContainText("연결 근거 1개");
  await expect(nodeRow(page, "capability.records_mgmt").locator("[data-status-label]")).toHaveText("추정");
  await expect(edgeRow(page, "edge.has_capability.records_mgmt").locator("[data-status-label]")).toHaveText("추정");
  const isms = nodeRow(page, "qualification.isms");
  await expect(isms.locator("[data-status-label]")).toHaveText("미확인");
  await expect(isms.locator("[data-node-value]")).toHaveText("값 미확인");
  await expect(isms).toContainText("연결 근거 없음");
  await expect(edgeRow(page, "edge.holds_qualification.isms").locator("[data-status-label]")).toHaveText("미확인");
  // 값 0과 미확인이 다르다.
  await expect(nodeRow(page, "staff.pm").locator("[data-node-value]")).toHaveText("역할 사업관리 · 전체 6명 · 투입 가능 0명 · 기준일 2026-09-30");
  await expect(nodeRow(page, "project.minwon_2025").locator("[data-node-value]")).toHaveText(
    "역할 주관 · 범위 민원 통합 시스템 구축 · 금액 1,840,000,000원 · 기간 2025-01-06 ~ 미확인",
  );
  await expect(nodeRow(page, "qualification.sw_business").locator("[data-node-value]")).toHaveText("보유");

  // 회사 노드가 기본 중심이고 잘림이 없다.
  await expect(nodeRow(page, "company")).toHaveAttribute("aria-current", "true");
  await expect(graph(page).getByTestId("graph-center")).toHaveText("중심: 데모 업무SI (회사) · 회사 기본 중심");
  await expect(graph(page).getByTestId("graph-truncation")).toHaveCount(0);
  await expect(graph(page).getByTestId("graph-summary")).toContainText("이 깊이 안의 노드를 모두 표시했습니다");
  await expect(graph(page).getByRole("button", { name: "회사 중심으로 돌아가기" })).toHaveCount(0);
});

test("노드를 중심으로 다시 보면 root_node_id로 서버에 다시 묻고, 회사 중심으로 돌아올 수 있다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto(profilePath);
  await expect(graph(page)).toHaveAttribute("data-graph-state", "ready");

  const response = waitForGraph(page);
  await graph(page).getByRole("button", { name: "전자정부 표준프레임워크 중심으로 보기", exact: true }).click();
  const body = (await (await response).json()) as GraphBody;
  await expect(page).toHaveURL(/[?&]graph_root=technology\.egov_framework(&|$)/);
  expect(graphRequests(trace.requests).at(-1)).toBe(`${graphBase}&root_node_id=technology.egov_framework&depth=2&limit=200`);
  await expect(graph(page)).toHaveAttribute("data-graph-state", "ready");

  // 서버가 준 이웃만 그린다(BFS는 서버 몫).
  const ids = await renderedIds(page);
  expect([...ids.nodes].sort()).toEqual(body.nodes.map((node) => node.id).sort());
  expect(ids.edges).toEqual(body.edges.map((edge) => edge.id));
  expect([...ids.nodes].sort()).toEqual(["capability.public_admin", "company", "domain.central_gov", "project.minwon_2025", "technology.egov_framework"]);
  await expect(nodeRow(page, "technology.egov_framework")).toHaveAttribute("aria-current", "true");
  await expect(nodeRow(page, "company")).not.toHaveAttribute("aria-current", "true");
  const center = graph(page).getByTestId("graph-center");
  await expect(center).toHaveText("중심: 전자정부 표준프레임워크 (기술)");
  // 다시 그린 뒤 키보드 위치를 잃지 않도록 중심 문구로 초점을 옮긴다.
  await expect(center).toBeFocused();

  // 새로고침해도 주소의 중심이 정본이다.
  await page.reload();
  await expect(graph(page).getByTestId("graph-center")).toHaveText("중심: 전자정부 표준프레임워크 (기술)");
  expect(graphRequests(trace.requests).at(-1)).toBe(`${graphBase}&root_node_id=technology.egov_framework&depth=2&limit=200`);

  // 회사 중심으로 돌아가면 root 없이 다시 묻는다.
  await graph(page).getByRole("button", { name: "회사 중심으로 돌아가기" }).click();
  await expect(page).not.toHaveURL(/graph_root=/);
  await expect(graph(page).getByTestId("graph-center")).toHaveText("중심: 데모 업무SI (회사) · 회사 기본 중심");
  expect(graphRequests(trace.requests).at(-1)).toBe(`${graphBase}&depth=2&limit=200`);
  await expect(relationRegion(page).locator("li[data-edge-id]")).toHaveCount(13);

  // 뒤로가기는 이전 중심으로 돌아간다.
  await page.goBack();
  await expect(graph(page).getByTestId("graph-center")).toHaveText("중심: 전자정부 표준프레임워크 (기술)");
});

test("노드·관계를 클릭·Enter·Space로 열고 버튼·Escape로 닫으면 연 행으로 초점이 돌아간다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto(profilePath);
  await expect(graph(page)).toHaveAttribute("data-graph-state", "ready");
  const evidenceRequests = () => trace.requests.filter((entry) => entry.includes("/profile-evidence/"));

  // 클릭 → 근거 패널. 패널로 초점이 가고 근거를 프로필 근거 endpoint에서 읽는다.
  const publicAdmin = nodeTrigger(page, "capability.public_admin");
  await publicAdmin.click();
  await expect(panel(page)).toBeVisible();
  await expect(panel(page)).toBeFocused();
  await expect(publicAdmin).toHaveAttribute("aria-pressed", "true");
  await expect(panel(page).getByRole("heading", { level: 4 })).toHaveText("행정업무 시스템 구축");
  await expect(panel(page).locator("dd[data-status-label]")).toHaveText("시나리오 확정");
  await expect(panel(page)).toContainText("가상회사 시나리오에서 정한 값입니다. 실제 회사 사실이 아닙니다.");
  const evidence = panel(page).locator("li[data-evidence-loaded]");
  await expect(evidence).toHaveCount(1);
  await expect(evidence.locator("blockquote")).toHaveText("주력 역량: 중앙부처 행정업무 통합 구축");
  await expect(evidence.locator("[data-evidence-fact-key]")).toHaveText("capability.public_admin");
  const sourceSha = fixtureSha("demo-public-si:source");
  await expect(evidence.locator("[data-evidence-sha]")).toHaveText(sourceSha.slice(0, 12));
  await expect(panel(page)).not.toContainText(sourceSha);
  expect(evidenceRequests()).toEqual([`GET /api/companies/${companyId}/profile-evidence/${profileEvidenceIdFor(company, "capability.public_admin")}`]);

  // 닫기 버튼 → 패널이 닫히고 연 행으로 초점 복귀.
  await panel(page).getByRole("button", { name: "근거 닫기" }).click();
  await expect(panel(page)).toHaveCount(0);
  await expect(publicAdmin).toBeFocused();
  await expect(publicAdmin).toHaveAttribute("aria-pressed", "false");

  // Tab 순서: 행 → 그 행의 "중심으로 보기" → 다음 행.
  await page.keyboard.press("Tab");
  await expect(graph(page).getByRole("button", { name: "행정업무 시스템 구축 중심으로 보기", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  const records = nodeTrigger(page, "capability.records_mgmt");
  await expect(records).toBeFocused();

  // Enter로 열고 Escape로 닫는다.
  await page.keyboard.press("Enter");
  await expect(panel(page)).toBeFocused();
  await expect(panel(page).locator("dd[data-status-label]")).toHaveText("추정");
  await expect(panel(page).locator("[data-evidence-fact-key]")).toHaveText("capability.records_mgmt");
  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
  await expect(records).toBeFocused();

  // 관계 행은 Space로 연다. 관계의 근거(재사용한 사실의 근거)를 읽는다.
  const usesTechnology = edgeTrigger(page, "edge.minwon.uses_technology.egov");
  await usesTechnology.focus();
  await page.keyboard.press("Space");
  await expect(panel(page)).toBeFocused();
  await expect(panel(page).getByRole("heading", { level: 4 })).toHaveText("민원 통합 시스템 구축 — 사용 기술 → 전자정부 표준프레임워크");
  await expect(panel(page)).toContainText("근거 · 관계");
  await expect(panel(page).locator("[data-evidence-fact-key]")).toHaveText("project.minwon_2025");
  await expect(panel(page).locator("blockquote")).toHaveText("2025년 민원 통합 시스템 구축 주관, 18.4억 원");
  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
  await expect(usesTechnology).toBeFocused();

  // 미확인 노드는 근거가 없고 그 사실을 문장으로 말하며 근거 조회를 하지 않는다.
  const requestsBefore = evidenceRequests().length;
  await nodeTrigger(page, "qualification.isms").click();
  await expect(panel(page).locator("dd[data-status-label]")).toHaveText("미확인");
  await expect(panel(page).getByTestId("graph-no-evidence")).toHaveText(
    "미확인 항목이라 연결된 근거가 없습니다. 근거가 없다는 것이 미보유나 부적합을 뜻하지 않습니다.",
  );
  await expect(panel(page)).not.toContainText("실제 회사 사실이 아닙니다");
  expect(evidenceRequests()).toHaveLength(requestsBefore);
  await page.keyboard.press("Escape");
  await expect(nodeTrigger(page, "qualification.isms")).toBeFocused();
});

test("depth·limit을 바꾸면 그 query로 다시 묻고, 잘린 목록은 생략 개수와 함께 누락의 증거가 아니라고 알린다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto(profilePath);
  await expect(graph(page)).toHaveAttribute("data-graph-state", "ready");

  let response = waitForGraph(page);
  await graph(page).getByLabel("탐색 깊이").selectOption("1");
  let body = (await (await response).json()) as GraphBody;
  expect(graphRequests(trace.requests).at(-1)).toBe(`${graphBase}&depth=1&limit=200`);
  await expect(page).toHaveURL(/[?&]graph_depth=1(&|$)/);
  await expect(graph(page).getByTestId("graph-summary")).toContainText("표시 노드 10개 · 관계 11개 · 깊이 1단계 · 최대 200개");
  expect((await renderedIds(page)).edges).toEqual(body.edges.map((edge) => edge.id));
  await expect(graph(page).getByTestId("graph-truncation")).toHaveCount(0);

  await graph(page).getByLabel("탐색 깊이").selectOption("2");
  await expect(graph(page).getByTestId("graph-summary")).toContainText("표시 노드 12개");
  response = waitForGraph(page);
  await graph(page).getByLabel("최대 노드 수").selectOption("10");
  body = (await (await response).json()) as GraphBody;
  expect(graphRequests(trace.requests).at(-1)).toBe(`${graphBase}&depth=2&limit=10`);
  expect(body.truncated).toBe(true);
  expect(body.omitted_node_count).toBe(2);
  const notice = graph(page).getByRole("note", { name: "목록 잘림 안내" });
  await expect(notice).toBeVisible();
  await expect(notice.getByTestId("graph-omitted-count")).toHaveText("2");
  await expect(notice).toContainText("목록이 잘렸습니다.");
  await expect(notice).toContainText("깊이 2단계 안의 노드 중 2개를 표시하지 않았습니다(최대 10개)");
  await expect(notice).toContainText("잘림은 분석이 빠졌거나 관계가 없다는 증거가 아닙니다.");
  await expect(graph(page).locator("li[data-node-id]")).toHaveCount(10);
  // 잘린 노드(evidence·technology)를 화면이 채워 넣지 않는다.
  await expect(nodeRow(page, "technology.egov_framework")).toHaveCount(0);
  await expect(nodeRow(page, "evidence.public_admin")).toHaveCount(0);
  expect((await renderedIds(page)).edges).toEqual(body.edges.map((edge) => edge.id));
  await expect(graph(page).getByTestId("graph-summary")).not.toContainText("모두 표시했습니다");

  response = waitForGraph(page);
  await graph(page).getByLabel("탐색 깊이").selectOption("3");
  body = (await (await response).json()) as GraphBody;
  expect(graphRequests(trace.requests).at(-1)).toBe(`${graphBase}&depth=3&limit=10`);
  expect(body.omitted_node_count).toBe(2);
  await expect(notice).toContainText("깊이 3단계 안의 노드 중 2개를 표시하지 않았습니다(최대 10개)");
  await expect(page).toHaveURL(/graph_depth=3/);
  await expect(page).toHaveURL(/graph_limit=10/);
});

test("관계 목록을 읽는 중에는 완료된 목록처럼 보이지 않는다", async ({ page }) => {
  await installMocks(page);
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route(`**${graphApi}*`, async (route: Route) => {
    await gate;
    await route.fallback();
  });
  await page.goto(profilePath);
  await expect(page.getByRole("table", { name: "구조화 사실" })).toBeVisible();
  await expect(graph(page)).toHaveAttribute("data-graph-state", "loading");
  await expect(graph(page)).toHaveAttribute("aria-busy", "true");
  await expect(graph(page).getByTestId("graph-loading")).toHaveText("관계 목록을 불러오는 중입니다. 아직 완료된 목록이 아닙니다.");
  await expect(graph(page).getByTestId("graph-center")).toContainText("불러오는 중");
  await expect(nodeRegion(page)).toHaveCount(0);
  await expect(relationRegion(page)).toHaveCount(0);
  await expect(graph(page).getByTestId("graph-summary")).toHaveCount(0);
  await expect(graph(page).getByTestId("graph-empty")).toHaveCount(0);
  release();
  await expect(graph(page)).toHaveAttribute("data-graph-state", "ready");
  await expect(graph(page)).toHaveAttribute("aria-busy", "false");
  await expect(graph(page).getByTestId("graph-loading")).toHaveCount(0);
});

test("관계가 없는 응답은 빈 상태로, 판정이 아니라고 말한다", async ({ page }) => {
  await installMocks(page);
  // 같은 고정 응답에서 관계만 비운 변형(회사 노드 하나, 관계 0).
  const base = knowledgeGraphView(company)!;
  await page.route(`**${graphApi}*`, (route: Route) => route.fulfill({
    json: { ...base, nodes: base.nodes.filter((node) => node.type === "company"), edges: [], truncated: false, omitted_node_count: 0 },
  }));
  await page.goto(profilePath);
  await expect(graph(page)).toHaveAttribute("data-graph-state", "empty");
  await expect(graph(page).getByTestId("graph-empty")).toContainText("서버가 돌려준 관계가 없습니다. 관계가 없다는 판정이 아니며");
  await expect(graph(page).locator("li[data-edge-id]")).toHaveCount(0);
  await expect(graph(page).locator("li[data-node-id]")).toHaveCount(1);
});

test("없는 중심(404)·네트워크 실패·그래프 409는 오류로 보이고 다시 시도할 수 있다", async ({ page }) => {
  const trace = await installMocks(page);
  // 404 not_found: 주소의 중심 노드가 이 회사 그래프에 없다.
  await page.goto(`${profilePath}?graph_root=missing.node`);
  await expect(graph(page)).toHaveAttribute("data-graph-state", "error");
  const graphAlert = graph(page).getByRole("alert");
  await expect(graphAlert).toContainText("관계 목록을 불러오지 못했습니다.");
  await expect(graphAlert).toContainText("이 회사에서 대상을 찾을 수 없습니다.");
  await expect(graphAlert).toContainText("오류 코드 not_found");
  await expect(graph(page).locator("li[data-node-id]")).toHaveCount(0);
  expect(graphRequests(trace.requests).at(-1)).toBe(`${graphBase}&root_node_id=missing.node&depth=2&limit=200`);
  await graph(page).getByRole("button", { name: "회사 중심으로 돌아가기" }).click();
  await expect(graph(page)).toHaveAttribute("data-graph-state", "ready");

  // 네트워크 실패.
  await page.route(`**${graphApi}*`, (route: Route) => route.abort("connectionrefused"));
  await graph(page).getByLabel("탐색 깊이").selectOption("1");
  await expect(graph(page)).toHaveAttribute("data-graph-state", "error");
  await expect(graph(page).getByRole("alert")).toContainText("서버에 연결할 수 없습니다.");
  await page.unroute(`**${graphApi}*`);
  await graph(page).getByRole("button", { name: "관계 목록 다시 불러오기" }).click();
  await expect(graph(page)).toHaveAttribute("data-graph-state", "ready");
  await expect(graph(page).getByTestId("graph-summary")).toContainText("깊이 1단계");

  // 프로필은 읽혔지만 그래프가 409 company_profile_not_ready.
  await page.route(`**${graphApi}*`, (route: Route) => route.fulfill({
    status: 409,
    json: { error: { code: "company_profile_not_ready", message: "합성", details: null }, request_id: null },
  }));
  await graph(page).getByLabel("최대 노드 수").selectOption("50");
  await expect(graph(page)).toHaveAttribute("data-graph-state", "error");
  await expect(graph(page).getByRole("alert")).toContainText("회사 프로필이 아직 준비되지 않았습니다.");
  await expect(graph(page).getByRole("alert")).toContainText("오류 코드 company_profile_not_ready");
});

test("프로필이 준비되지 않은 회사(409)는 관계 목록을 읽지도 그리지도 않는다", async ({ page }) => {
  const trace = await installMocks(page, { profileNotReadyCompanyIds: [companyId] });
  await page.goto(profilePath);
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("이 회사의 프로필을 불러오지 못했습니다.");
  await expect(alert).toContainText("회사 프로필이 아직 준비되지 않았습니다.");
  await expect(graph(page)).toHaveCount(0);
  expect(graphRequests(trace.requests)).toEqual([]);
});

test("응답 그래프의 버전·hash가 프로필과 다르면 목록을 그리지 않는다", async ({ page }) => {
  await installMocks(page);
  // 같은 고정 응답에서 graph_sha256만 다른 변형.
  const base = knowledgeGraphView(company)!;
  await page.route(`**${graphApi}*`, (route: Route) => route.fulfill({ json: { ...base, graph_sha256: fixtureSha("another-graph") } }));
  await page.goto(profilePath);
  await expect(graph(page)).toHaveAttribute("data-graph-state", "error");
  await expect(graph(page).getByRole("alert")).toContainText("관계 목록의 버전이 프로필과 맞지 않습니다.");
  await expect(graph(page).locator("li[data-node-id]")).toHaveCount(0);
  await expect(graph(page).locator("li[data-edge-id]")).toHaveCount(0);
});

test("긴 한글 label은 1440 폭에서 가로로 넘치지 않는다(목록·근거 패널)", async ({ page }, info) => {
  await installMocks(page);
  await page.goto(profilePath);
  await expect(graph(page)).toHaveAttribute("data-graph-state", "ready");
  expect(page.viewportSize()?.width).toBe(1440);
  const longTitle = nodeRow(page, "capability.records_mgmt").locator(".kg-row-title");
  await expect(longTitle).toHaveText(LONG_GRAPH_LABEL);
  await expect(edgeRow(page, "edge.has_capability.records_mgmt").locator("[data-edge-to]")).toHaveText(LONG_GRAPH_LABEL);

  const overflow = () => page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    rows: Array.from(document.querySelectorAll<HTMLElement>("[data-testid='company-graph'] .kg-row, [data-testid='company-graph'] .kg-panel"))
      .filter((element) => element.scrollWidth > element.clientWidth)
      .map((element) => element.closest("[data-node-id],[data-edge-id]")?.getAttribute("data-node-id") ?? element.className),
  }));
  expect(await overflow()).toEqual({ document: 0, rows: [] });

  // 근거 패널이 열려 목록이 좁아져도 넘치지 않는다(패널 제목도 긴 label).
  await nodeTrigger(page, "capability.records_mgmt").click();
  await expect(panel(page).getByRole("heading", { level: 4 })).toHaveText(LONG_GRAPH_LABEL);
  await expect(panel(page).locator("li[data-evidence-loaded]")).toHaveCount(1);
  expect(await overflow()).toEqual({ document: 0, rows: [] });
  await page.screenshot({ path: info.outputPath("company-graph-long-label-1440.png"), fullPage: true });
});
