import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockCompanyWorkspace, mockRealCompany } from "./api-mock";
import { COMPANY_BY_SLUG } from "./fixtures/company-demo";

/*
 * DEMO-04 STEP-001 · spec T1(회사 전환·새로고침·뒤로·복수 탭)과 회사 경로 등록.
 *
 * 고정 응답은 `tests/api-mock.ts`의 `mockCompanyWorkspace`이며 실제 백엔드에 연결하지
 * 않는다. 세 회사는 같은 공고에 서로 다른 핏·추적 값을 가지므로, 회사가 바뀐 뒤 이전
 * 회사의 값이 남으면 아래 행 기대값이 깨진다.
 */

type Slug = keyof typeof COMPANY_BY_SLUG;

/** 회사별 고정 응답의 기대값(fixture `company-demo.ts`의 seed와 같다). */
const EXPECTED: Record<Slug, { name: string; rows: Record<number, { fit: string; tracking: string }> }> = {
  "demo-public-si": {
    name: "데모 업무SI",
    rows: {
      7101: { fit: "matched", tracking: "계속 추적" },
      7102: { fit: "unknown", tracking: "미선택" },
      7103: { fit: "mismatch", tracking: "보류" },
      7104: { fit: "none", tracking: "unlinked" },
    },
  },
  "demo-data-ai": {
    name: "데모 데이터AI",
    rows: {
      7101: { fit: "mismatch", tracking: "종료" },
      7102: { fit: "matched", tracking: "계속 추적" },
      7103: { fit: "null", tracking: "미선택" },
      7104: { fit: "unknown", tracking: "unlinked" },
    },
  },
  "demo-cloud-si": {
    name: "데모 클라우드SI",
    rows: {
      7101: { fit: "null", tracking: "미선택" },
      7102: { fit: "mismatch", tracking: "미선택" },
      7103: { fit: "matched", tracking: "계속 추적" },
      7104: { fit: "null", tracking: "unlinked" },
    },
  },
};

const FIT_LABEL: Record<string, string> = { matched: "부합", mismatch: "불일치", unknown: "미확인", null: "판정 없음", none: "판정 없음" };

function companyId(slug: Slug): string {
  return COMPANY_BY_SLUG[slug].company_id;
}

function listPath(slug: Slug): string {
  return `/companies/${companyId(slug)}/pre-specs`;
}

const companySelect = (page: Page) => page.getByRole("combobox", { name: "데모 회사 선택" });
const companyList = (page: Page) => page.getByRole("table", { name: "회사별 사전규격 판정" });
const row = (page: Page, noticeId: number) => companyList(page).locator(`tr[data-notice-id="${noticeId}"]`);

/** 주소·머리글·선택기·목록 네 곳이 모두 같은 회사를 말하고 다른 회사의 값이 없다. */
async function expectCompanyList(page: Page, slug: Slug) {
  const expected = EXPECTED[slug];
  await expect(page).toHaveURL(new RegExp(`${listPath(slug)}$`));
  const header = page.getByTestId("company-header");
  await expect(header).toHaveAttribute("data-company-id", companyId(slug));
  await expect(header.getByTestId("company-name")).toHaveText(expected.name);
  await expect(header.getByTestId("company-slug")).toHaveText(slug);
  await expect(companySelect(page)).toHaveValue(companyId(slug));
  await expect(companyList(page).locator("tbody tr")).toHaveCount(4);
  for (const [noticeId, values] of Object.entries(expected.rows)) {
    const target = row(page, Number(noticeId));
    await expect(target.locator("[data-fit-decision]")).toHaveAttribute("data-fit-decision", values.fit);
    await expect(target.locator("[data-fit-decision] .badge")).toHaveText(FIT_LABEL[values.fit]);
    await expect(target.locator("[data-tracking-status]")).toHaveAttribute("data-tracking-status", values.tracking);
  }
  // 다른 두 회사의 이름이 이 화면 본문 어디에도 없다.
  for (const other of Object.keys(EXPECTED) as Slug[]) {
    if (other === slug) continue;
    await expect(page.locator("main")).not.toContainText(EXPECTED[other].name);
  }
}

async function expectSelected(page: Page, noticeId: number | null) {
  const pressed = companyList(page).locator('button.cw-row-select[aria-pressed="true"]');
  if (noticeId === null) {
    await expect(pressed).toHaveCount(0);
    await expect(page.getByRole("complementary", { name: "선택한 사전규격" })).toContainText("목록에서 사전규격을 고르십시오.");
    return;
  }
  await expect(pressed).toHaveCount(1);
  await expect(row(page, noticeId).locator("button.cw-row-select")).toHaveAttribute("aria-pressed", "true");
}

async function installMocks(page: Page, options: { enabled?: boolean } = {}) {
  await mockApi(page);
  return mockCompanyWorkspace(page, options);
}

test("첫 진입은 회사 선택이고 기본 회사를 정하지 않는다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto("/companies");
  await expect(page.getByRole("heading", { name: "검토할 가상회사를 고르십시오" })).toBeVisible();
  await expect(page.getByRole("note", { name: "가상회사 데모 화면" })).toHaveText("가상회사 데모");
  await expect(companySelect(page)).toHaveValue("");
  const companies = page.getByRole("list", { name: "가상회사 목록" }).getByRole("listitem");
  await expect(companies).toHaveCount(3);
  await expect(companies.nth(0)).toHaveAttribute("data-company-slug", "demo-cloud-si");
  await expect(companies.nth(1)).toHaveAttribute("data-company-slug", "demo-data-ai");
  await expect(companies.nth(2)).toHaveAttribute("data-company-slug", "demo-public-si");
  // 회사를 고르기 전에는 어떤 회사의 결과도 읽지 않고 주소도 그대로다.
  await expect(page).toHaveURL(/\/companies$/);
  expect(trace.requests.filter((entry) => /\/api\/companies\/[^/?]+/.test(entry))).toEqual([]);
  const demoNav = page.getByRole("navigation", { name: "주 메뉴" });
  await expect(demoNav.getByRole("link", { name: "회사 선택", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(demoNav.getByRole("link", { name: "회사 사전규격", exact: true })).toHaveCount(0);
});

test("A→B→A 전환·새로고침·뒤로/앞으로에서 주소·머리글·목록·선택이 회사별로 유지된다", async ({ page }, info) => {
  await installMocks(page);
  await page.goto("/companies");
  await page.getByRole("link", { name: "데모 업무SI 사전규격 열기" }).click();
  await expectCompanyList(page, "demo-public-si");
  await expectSelected(page, null);
  await row(page, 7102).locator("button.cw-row-select").click();
  await expectSelected(page, 7102);
  await page.screenshot({ path: info.outputPath("company-a-list.png") });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);

  // A → B: 같은 자원(목록)으로 가며 A의 선택이 B에 남지 않는다.
  await companySelect(page).selectOption(companyId("demo-data-ai"));
  await expectCompanyList(page, "demo-data-ai");
  await expectSelected(page, null);
  await row(page, 7103).locator("button.cw-row-select").click();
  await expectSelected(page, 7103);
  // B의 선택 패널은 B의 값이다(핏 실패는 판정 없음, 추적 미선택).
  const aside = page.getByRole("complementary", { name: "선택한 사전규격" });
  await expect(aside.locator("[data-fit-decision]")).toHaveAttribute("data-fit-decision", "null");
  await expect(aside).toContainText("실행 실패");

  // B → A: A의 선택이 회사별 저장소에서 복원된다.
  await companySelect(page).selectOption(companyId("demo-public-si"));
  await expectCompanyList(page, "demo-public-si");
  await expectSelected(page, 7102);

  // 새로고침해도 주소가 정본이다.
  await page.reload();
  await expectCompanyList(page, "demo-public-si");
  await expectSelected(page, 7102);

  // 뒤로 → B, 앞으로 → A. 각 회사의 선택이 그대로다.
  await page.goBack();
  await expectCompanyList(page, "demo-data-ai");
  await expectSelected(page, 7103);
  await page.goForward();
  await expectCompanyList(page, "demo-public-si");
  await expectSelected(page, 7102);

  // 세 번째 회사도 같은 규칙이다. 회사별 선택 key가 따로 있다.
  await companySelect(page).selectOption(companyId("demo-cloud-si"));
  await expectCompanyList(page, "demo-cloud-si");
  await expectSelected(page, null);
  const keys = await page.evaluate(() => Object.keys(window.sessionStorage).filter((key) => key.startsWith("bidops.companies.")).sort());
  expect(keys).toEqual([
    `bidops.companies.${companyId("demo-public-si")}.pre-specs.selection.v1`,
    `bidops.companies.${companyId("demo-data-ai")}.pre-specs.selection.v1`,
  ].sort());
});

test("demo가 켜져 있으면 /companies/:id/profile은 세 회사 모두 /company로 가고 그 회사의 프로필을 보이지 않는다", async ({ page }) => {
  await installMocks(page);
  await mockRealCompany(page);
  for (const slug of ["demo-public-si", "demo-data-ai", "demo-cloud-si"] as const) {
    await page.goto(`/companies/${companyId(slug)}/profile`);
    // replace 이동이라 주소가 /company이고(기본 그룹 attention은 쿼리 없이 열린다) 뒤로 가기가 옛 주소로 돌아가지 않는다.
    await expect(page).toHaveURL(/\/company$/);
    await expect(page.locator("header.topbar h1")).toHaveText("회사 근거");
    await expect(page.getByTestId("company-attention")).toBeVisible();
    await expect(page.getByTestId("company-header")).toHaveCount(0);
    await expect(page.locator("main")).not.toContainText(COMPANY_BY_SLUG[slug].name);
    await expect(page.getByTestId("company-profile-version")).toHaveCount(0);
  }
});

test("demo가 꺼져 있으면 /companies/:id/profile은 /company로 가지 않는다", async ({ page }) => {
  await installMocks(page, { enabled: false });
  await mockRealCompany(page);
  await page.goto(`/companies/${companyId("demo-public-si")}/profile`);
  await expect(page.getByTestId("company-attention")).toHaveCount(0);
  await expect(page).not.toHaveURL(/\/company(?:\?|$)/);
});

test("두 탭이 서로 다른 회사를 열어도 서로의 화면·선택을 바꾸지 않는다", async ({ context }) => {
  const first = await context.newPage();
  const second = await context.newPage();
  await installMocks(first);
  await installMocks(second);
  await first.goto(listPath("demo-public-si"));
  await second.goto(listPath("demo-data-ai"));
  await expectCompanyList(first, "demo-public-si");
  await expectCompanyList(second, "demo-data-ai");

  await row(first, 7101).locator("button.cw-row-select").click();
  await row(second, 7104).locator("button.cw-row-select").click();
  await companySelect(second).selectOption(companyId("demo-cloud-si"));
  await expectCompanyList(second, "demo-cloud-si");
  await expectSelected(second, null);

  // 첫 탭은 그대로 A이고, 새로고침해도 A의 선택만 복원한다.
  await first.reload();
  await expectCompanyList(first, "demo-public-si");
  await expectSelected(first, 7101);
  // 둘째 탭이 B로 돌아오면 그 탭의 B 선택이 복원된다.
  await second.goBack();
  await expectCompanyList(second, "demo-data-ai");
  await expectSelected(second, 7104);
});

test("미저장 추적 입력이 있으면 회사 전환 전에 확인하고, 취소하면 회사 A에 남는다", async ({ page }) => {
  const trace = await installMocks(page);
  const detailA = `/companies/${companyId("demo-public-si")}/pre-specs/7102`;
  await page.goto(detailA);
  const tracking = page.getByTestId("company-tracking");
  await expect(tracking.getByTestId("company-tracking-current")).toContainText("현재 미선택");
  await tracking.getByRole("radio", { name: "보류" }).check();
  await tracking.getByLabel("추적 결정 사유").fill("데이터 인력 근거 확인 후 판단");

  await companySelect(page).selectOption(companyId("demo-data-ai"));
  const guard = page.getByRole("alertdialog");
  await expect(guard).toBeVisible();
  await expect(guard).toContainText("이 회사의 추적 결정을 저장하지 않았습니다");
  await expect(guard).toContainText("다른 회사에 저장되지 않습니다");
  await guard.getByRole("button", { name: "이 회사에 머물기", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);

  // 취소하면 주소·머리글·선택기·입력이 모두 회사 A 그대로다.
  await expect(page).toHaveURL(new RegExp(`${detailA}$`));
  await expect(page.getByTestId("company-header").getByTestId("company-name")).toHaveText("데모 업무SI");
  await expect(companySelect(page)).toHaveValue(companyId("demo-public-si"));
  await expect(tracking.getByRole("radio", { name: "보류" })).toBeChecked();
  await expect(tracking.getByLabel("추적 결정 사유")).toHaveValue("데이터 인력 근거 확인 후 판단");
  expect(trace.trackingPatches).toEqual([]);

  // 버리고 이동하면 B의 같은 공고로 가고, A의 입력은 B로 넘어가지 않으며 아무 회사에도 저장되지 않는다.
  await companySelect(page).selectOption(companyId("demo-data-ai"));
  await page.getByRole("alertdialog").getByRole("button", { name: "입력을 버리고 이동", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/companies/${companyId("demo-data-ai")}/pre-specs/7102$`));
  await expect(page.getByTestId("company-header").getByTestId("company-name")).toHaveText("데모 데이터AI");
  await expect(tracking.getByTestId("company-tracking-current")).toContainText("현재 계속 추적");
  await expect(tracking.getByLabel("추적 결정 사유")).toHaveValue("");
  await expect(tracking.getByRole("radio", { name: "보류" })).not.toBeChecked();
  expect(trace.trackingPatches).toEqual([]);
});

test("회사 A에서 시작한 저장은 A로 끝나고, 그사이 연 회사 B 화면을 무효화하거나 덮지 않는다", async ({ page }) => {
  const trace = await installMocks(page);
  let releasePatch: () => void = () => {};
  const patchGate = new Promise<void>((resolve) => { releasePatch = resolve; });
  let patchSeen = false;
  await page.route("**/api/companies/*/opportunities/*/tracking", async (route) => {
    if (route.request().method() !== "PATCH") { await route.fallback(); return; }
    patchSeen = true;
    await patchGate;
    await route.fallback();
  });

  const idA = companyId("demo-public-si");
  const idB = companyId("demo-data-ai");
  await page.goto(`/companies/${idA}/pre-specs/7102`);
  const tracking = page.getByTestId("company-tracking");
  await expect(tracking.getByTestId("company-tracking-current")).toContainText("현재 미선택");
  await tracking.getByRole("radio", { name: "보류" }).check();
  await tracking.getByLabel("추적 결정 사유").fill("A 회사 기준 보류");
  await tracking.getByLabel("추적 결정 담당자 이름").fill("업무SI 담당");
  await tracking.getByRole("button", { name: "추적 결정 저장" }).click();
  await expect.poll(() => patchSeen).toBe(true);

  // 저장 응답 전에 B로 옮긴다. 요청은 이미 보냈으므로 확인 창은 "사라진다"가 아니라
  // 보낸 요청이 회사 A에 저장될 수 있다고 말해야 한다.
  await companySelect(page).selectOption(idB);
  const pendingGuard = page.getByRole("alertdialog");
  await expect(pendingGuard).toContainText("추적 결정 저장 요청을 처리하고 있습니다");
  await expect(pendingGuard).toContainText("그 요청은 취소되지 않으며 회사 데모 업무SI에 저장될 수 있습니다");
  await expect(pendingGuard).toContainText("보류 · 처리 중");
  await expect(pendingGuard).not.toContainText("사라지며");
  await expect(pendingGuard.getByRole("button", { name: "입력을 버리고 이동", exact: true })).toHaveCount(0);
  await pendingGuard.getByRole("button", { name: "이동하기 (보낸 요청은 계속 처리)", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/companies/${idB}/pre-specs/7102$`));
  await expect(tracking.getByTestId("company-tracking-current")).toContainText("현재 계속 추적");
  const requestsBeforeRelease = trace.requests.length;

  const patchResponse = page.waitForResponse((response) => response.request().method() === "PATCH");
  releasePatch();
  expect((await patchResponse).status()).toBe(200);
  expect(trace.trackingPatches).toHaveLength(1);
  // A의 응답이 끝난 뒤에도 B 화면은 B 값 그대로이며 B 조회를 다시 부르지 않는다.
  // 없음을 확인하는 검사라 응답 직후 무효화가 요청을 낼 짧은 창만 둔다.
  await page.waitForTimeout(250);
  await expect(tracking.getByTestId("company-tracking-current")).toContainText("현재 계속 추적");
  await expect(page.getByTestId("company-header").getByTestId("company-name")).toHaveText("데모 데이터AI");
  const afterRelease = trace.requests.slice(requestsBeforeRelease);
  expect(afterRelease.filter((entry) => entry.includes(`/api/companies/${idB}`))).toEqual([]);
  expect(afterRelease.filter((entry) => entry.startsWith("PATCH"))).toEqual([`PATCH /api/companies/${idA}/opportunities/8102/tracking`]);

  const patch = trace.trackingPatches[0];
  expect(patch.companyId).toBe(idA);
  expect(patch.opportunityId).toBe(8102);
  expect(patch.body).toMatchObject({ tracking_status: "보류", reason: "A 회사 기준 보류", expected_revision: 0 });
  expect(String(patch.body.request_id)).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);

  // A로 돌아가면 A의 저장 결과가 보인다.
  await companySelect(page).selectOption(idA);
  await expect(page).toHaveURL(new RegExp(`/companies/${idA}/pre-specs/7102$`));
  await expect(tracking.getByTestId("company-tracking-current")).toContainText("현재 보류");
  await page.getByTestId("company-header").getByRole("link", { name: "사전규격 목록" }).click();
  await expect(row(page, 7102).locator("[data-tracking-status]")).toHaveAttribute("data-tracking-status", "보류");
});

/*
 * 경쟁 재현(사용자 조작 검사가 아니다). `머물기`의 blocker.reset()과 바로 다음 이동의
 * 차단이 React가 "unblocked"를 그리기 전에 일어나면(router 상태 갱신은 transition으로
 * 묶인다) 화면은 blocked→blocked만 본다. 그때도 확인 창이 다시 떠야 한다. 두 조작을
 * 한 task에서 합성 이벤트로 일으켜 그 순서를 결정적으로 만든다. 실제 사용자 흐름은
 * 위 "미저장 추적 입력이 있으면 …" 검사가 본다.
 */
test("경쟁 재현: 머물기 직후 같은 task에서 다시 회사를 바꿔도 확인 창이 다시 뜬다", async ({ page }) => {
  const trace = await installMocks(page);
  const idA = companyId("demo-public-si");
  const idB = companyId("demo-data-ai");
  const detailA = `/companies/${idA}/pre-specs/7102`;
  await page.goto(detailA);
  const tracking = page.getByTestId("company-tracking");
  await expect(tracking.getByTestId("company-tracking-current")).toContainText("현재 미선택");
  await tracking.getByLabel("추적 결정 사유").fill("경쟁 재현 입력");

  await companySelect(page).selectOption(idB);
  await expect(page.getByRole("alertdialog")).toBeVisible();

  await page.evaluate((nextCompanyId) => {
    const dialog = document.querySelector('[role="alertdialog"]');
    const stay = Array.from(dialog?.querySelectorAll("button") ?? []).find((button) => button.textContent?.trim() === "이 회사에 머물기");
    const select = document.querySelector<HTMLSelectElement>('select[aria-label="데모 회사 선택"]');
    if (!stay || !select) throw new Error("경쟁 재현 대상(머물기 버튼·회사 선택기)을 찾지 못했습니다");
    stay.click();
    select.value = nextCompanyId;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }, idB);

  const guard = page.getByRole("alertdialog");
  await expect(guard).toBeVisible({ timeout: 5_000 });
  await expect(guard).toContainText("이 회사의 추적 결정을 저장하지 않았습니다");
  await expect(page).toHaveURL(new RegExp(`${detailA}$`));

  // 다시 머물면 A에 남고, 버리고 이동하면 B로 한 번만 간다.
  await guard.getByRole("button", { name: "이 회사에 머물기", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`${detailA}$`));
  await expect(tracking.getByLabel("추적 결정 사유")).toHaveValue("경쟁 재현 입력");
  await companySelect(page).selectOption(idB);
  await page.getByRole("alertdialog").getByRole("button", { name: "입력을 버리고 이동", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/companies/${idB}/pre-specs/7102$`));
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(tracking.getByLabel("추적 결정 사유")).toHaveValue("");
  expect(trace.trackingPatches).toEqual([]);
});

test("demo-config가 꺼져 있으면 회사 메뉴·선택기·경로가 SPA에 없다", async ({ page }) => {
  const trace = await installMocks(page, { enabled: false });
  await page.goto("/pre-specs");
  const nav = page.getByRole("navigation", { name: "주 메뉴" });
  await expect(nav.getByRole("link", { name: "공고", exact: true })).toBeVisible();
  await expect(nav.getByText("가상회사 데모")).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "회사 선택", exact: true })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "데모 회사 선택" })).toHaveCount(0);
  await expect(page.getByRole("note", { name: "가상회사 데모 화면" })).toHaveCount(0);

  await page.goto(`/companies/${companyId("demo-public-si")}/pre-specs`);
  await expect(page.locator("body")).toContainText("404");
  await expect(page.getByRole("table", { name: "회사별 사전규격 판정" })).toHaveCount(0);
  await expect(page.getByTestId("company-header")).toHaveCount(0);
  await page.goto("/companies");
  await expect(page.getByRole("heading", { name: "검토할 가상회사를 고르십시오" })).toHaveCount(0);
  expect(trace.requests).toEqual([]);
});

test("demo-config가 없으면(미등록 404) 비활성으로 닫힌다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/pre-specs");
  await expect(page.getByRole("navigation", { name: "주 메뉴" }).getByRole("link", { name: "공고", exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "데모 회사 선택" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "주 메뉴" }).getByRole("link", { name: "회사 선택", exact: true })).toHaveCount(0);
});

/*
 * 회차 전환은 셸이 query를 넓게 무효화한다. 그 뒤 `/api/demo-config`가 일시적으로 실패해도
 * 이미 정한 데모 활성 상태를 끄지 않아야 한다. 끄면 route 표가 데모 없이 다시 만들어져
 * 쓰는 중에 회사 선택기·회사 메뉴·회사 경로가 사라진다(회사 화면이면 404로 바뀐다).
 * 셸이 회차 전환을 일으킬 수 있는 화면은 회차 화면(/judgments)뿐이라 그 화면에서 재현한다.
 */
test("회차 전환 뒤 demo-config 재조회가 실패해도 데모를 끄지 않고 화면을 다시 마운트하지 않는다", async ({ page }) => {
  const trace = await installMocks(page);
  const runId = "20260817-20260823--20260824T090927.138116Z";
  await page.goto(`/judgments?run=${runId}`);
  const runSelector = page.getByLabel("실행 회차", { exact: true });
  await expect(runSelector).toHaveValue(runId);
  await expect(companySelect(page)).toBeVisible();
  const options = await runSelector.locator("option").evaluateAll((nodes) => nodes.map((node) => (node as HTMLOptionElement).value));
  const otherRun = options.find((value) => value && value !== runId);
  expect(otherRun, "회차 전환을 재현하려면 고정 응답에 회차가 둘 이상 있어야 한다").toBeTruthy();

  // 이제부터 demo-config는 실패한다(일시 장애).
  let demoConfigFailures = 0;
  await page.route("**/api/demo-config", async (route) => {
    demoConfigFailures += 1;
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "service_unavailable", message: "합성", details: null }, request_id: null }) });
  });
  const runDetail = page.waitForResponse((response) => response.url().includes(`/api/runs/${encodeURIComponent(otherRun as string)}`) || response.url().includes(`/api/runs/${otherRun}`));
  await runSelector.selectOption(otherRun as string);
  await runDetail;
  // 없음을 확인하는 검사라 무효화 뒤 재조회·재구성이 일어날 짧은 창만 둔다.
  await page.waitForTimeout(400);

  await expect(runSelector).toHaveValue(otherRun as string);
  await expect(companySelect(page)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "주 메뉴" }).getByRole("link", { name: "회사 선택", exact: true })).toBeVisible();
  // 회사 경로도 그대로 열린다.
  await companySelect(page).selectOption(companyId("demo-data-ai"));
  await expect(page).toHaveURL(new RegExp(`${listPath("demo-data-ai")}$`));
  await expect(page.getByTestId("company-header").getByTestId("company-name")).toHaveText("데모 데이터AI");
  expect(trace.requests.some((entry) => entry.startsWith(`GET /api/companies/${companyId("demo-data-ai")}`))).toBe(true);
  // 실패를 몇 번 겪었든(0회 포함) 결과는 같아야 한다. 값은 기록용이다.
  test.info().annotations.push({ type: "demo-config-failures", description: String(demoConfigFailures) });
});
