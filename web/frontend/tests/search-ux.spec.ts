import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans, mockPreSpecs } from "./api-mock";
import { mockGoNoGo } from "./go-no-go-fixtures";
import { mockOpportunities } from "./opportunities-fixtures";
import { opportunitySearchValid, searchKey, searchMatches, searchValidationValue } from "../src/lib/search";

test("[search-ux] 프런트 비교값은 서버 사례의 공백·ASCII·literal·길이 계약을 따른다", () => {
  const spaces = [
    ...Array.from({ length: 5 }, (_, index) => String.fromCodePoint(0x09 + index)),
    "\u0020", "\u0085", "\u00a0", "\u1680",
    ...Array.from({ length: 11 }, (_, index) => String.fromCodePoint(0x2000 + index)),
    "\u2028", "\u2029", "\u202f", "\u205f", "\u3000", "\ufeff",
  ];
  expect(spaces).toHaveLength(26);
  expect(searchKey(`A${spaces.join("")}B`)).toBe("ab");
  expect(searchKey("A\u200bB")).toBe("a\u200bb");
  expect(searchMatches("사이버 수사", "사이버수사포털시스템 고도화")).toBe(true);
  expect(searchMatches("사이버 고도화", "사이버수사포털시스템 고도화")).toBe(false);
  expect(searchMatches("사이버수사", "사이버", "수사")).toBe(false);
  expect(searchMatches("A%_\\", "a%_\\")).toBe(true);
  expect(searchMatches("A%_\\", "aXYZ")).toBe(false);
  expect(searchMatches("발주기관 미확인", null)).toBe(false);
  expect(searchMatches("ä", "Ä")).toBe(false);
  expect(searchValidationValue("  A  B  ")).toBe("A B");
  expect(opportunitySearchValid("  A  B  ")).toBe(true);
  expect(opportunitySearchValid("  A  ")).toBe(false);
  expect(opportunitySearchValid("\ufeff\u3000")).toBe(true);
  expect(opportunitySearchValid("😀".repeat(100))).toBe(true);
  expect(opportunitySearchValid("😀".repeat(101))).toBe(false);
});

/** 목록 검색 UX 의미 층 — mock도 서버의 searchKey 계약을 그대로 사용한다. */
test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("[search-ux] 발주계획 검색은 Enter 전 draft를 보존하고 raw q를 적용한다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await expect(page.locator(".c2l-row").first()).toBeVisible();

  const input = page.getByRole("textbox", { name: "사업명·발주기관·계획번호 검색", exact: true });
  const initialRows = await page.locator(".c2l-row").count();
  await input.fill("  공공 데이터  ");

  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBeNull();
  // 안내·적용 대기 문구는 화면에 그리지 않는다(2026-09-21 사용자 결정). 같은 문구는
  // 입력칸의 접근 설명으로 남아 보조기술에는 그대로 읽힌다.
  await expect(page.locator(".workspace-search-help")).toHaveCount(0);
  await expect(input).toHaveAccessibleDescription("Enter로 적용 · 띄어쓰기 무시");
  await expect(page.locator(".c2l-row")).toHaveCount(initialRows);

  await input.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("  공공 데이터  ");
  await expect(page.locator(".c2l-row").filter({ hasText: "공공데이터" })).toHaveCount(1);
  await expect(input).toHaveAccessibleDescription("Enter로 검색 · 띄어쓰기 무시");
});

test("[search-ux] 사전규격은 서버 검색 뒤 첫 검색 페이지에서 결과와 raw q를 설명한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");
  await expect(page.locator(".pre-specs-row").first()).toBeVisible();

  const input = page.getByRole("textbox", { name: "사업명·기관명 검색", exact: true });
  await input.fill("안전한 문서");
  await input.press("Enter");

  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("안전한 문서");
  await expect(input).toHaveValue("안전한 문서");
  await expect(page.locator(".pre-specs-row").filter({ hasText: "안전한 문서 준비 사전규격" })).toHaveCount(1);
});

test("[search-ux] 사업 추적의 invalid q는 기존 결과를 유지하고 field 오류를 연결한다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities");
  await expect(page.locator(".opportunity-table-scroll tbody tr").first()).toBeVisible();

  const input = page.getByRole("textbox", { name: "사업명·발주기관 검색", exact: true });
  const initialRows = await page.locator(".opportunity-table-scroll tbody tr").count();
  await input.fill("A");
  await input.press("Enter");

  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBeNull();
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await expect(input).toHaveAttribute("aria-describedby", /\S/);
  await expect(page.locator(".workspace-search-field").getByText("검색어는 공백을 정리한 뒤 2~100자여야 합니다.", { exact: true })).toBeVisible();
  await expect(page.locator(".opportunity-table-scroll tbody tr")).toHaveCount(initialRows);

  await input.fill("공공 데이터");
  await expect(input).not.toHaveAttribute("aria-invalid", "true");
  await input.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("공공 데이터");
  await expect(page.locator(".opportunity-table-scroll tbody tr").filter({ hasText: "공공데이터 통합관리체계 고도화" })).toHaveCount(1);
});

test("[search-ux] Go/No-Go는 받은 행의 실제 필드만 검색하고 null 표시문구를 검색하지 않는다", async ({ page }) => {
  await mockGoNoGo(page);
  await page.goto("/go-no-go?show=all");
  await expect(page.locator(".gng-row").first()).toBeVisible();

  const input = page.getByRole("textbox", { name: "사업명·발주기관 검색", exact: true });
  await input.fill("발주기관 미확인");
  await input.press("Enter");

  await expect(page.locator(".gng-table-scroll tbody tr")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "검색어만 지우기", exact: true })).toBeVisible();
  await expect(page.locator(".gng-list-empty")).toContainText("발주기관 미확인");
  await expect(page.locator(".gng-list-empty")).toContainText("전체에서 찾았습니다");
});

test("[search-ux] 동등 검색은 선택을 보존하고 키보드 삭제·IME Enter는 적용하지 않는다", async ({ page }) => {
  await mockGoNoGo(page);
  await page.goto("/go-no-go?show=all&selected=903&offset=0&q=교통정보");
  const input = page.getByRole("textbox", { name: "사업명·발주기관 검색", exact: true });
  await expect(page.locator(".gng-row")).toHaveCount(1);

  await input.fill("교통 정보");
  await input.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("교통 정보");
  expect(new URL(page.url()).searchParams.get("selected")).toBe("903");
  expect(new URL(page.url()).searchParams.get("offset")).toBe("0");

  await input.press("ControlOrMeta+A");
  await input.press("Backspace");
  await expect(input).toHaveValue("");
  expect(new URL(page.url()).searchParams.get("q")).toBe("교통 정보");
  await expect(page.locator(".gng-row")).toHaveCount(1);

  await input.fill("연구성과");
  await input.evaluate((element) => {
    element.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, isComposing: true }));
  });
  expect(new URL(page.url()).searchParams.get("q")).toBe("교통 정보");
  await input.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("연구성과");
  await expect(page.locator(".gng-row")).toHaveCount(1);
  expect(new URL(page.url()).searchParams.has("selected")).toBe(false);

  await page.locator(".workspace-search-field button").click();
  await expect.poll(() => new URL(page.url()).searchParams.has("q")).toBe(false);
  await expect(page.locator(".gng-row")).toHaveCount(12);
});

test("[search-ux] 사업 추적의 잘못된 직접 URL은 q를 보존하고 목록 요청을 막는다", async ({ page }) => {
  await mockOpportunities(page);
  const listRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/opportunities") listRequests.push(request.url());
  });
  await page.goto("/opportunities?q=A");
  const input = page.getByRole("textbox", { name: "사업명·발주기관 검색", exact: true });
  await expect(input).toHaveValue("A");
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator(".opportunity-table-scroll tbody tr")).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get("q")).toBe("A");
  expect(listRequests).toHaveLength(0);

  await input.fill("공공 데이터");
  await input.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("공공 데이터");
  await expect(page.locator(".opportunity-table-scroll tbody tr").filter({ hasText: "공공데이터" })).toHaveCount(1);
});
