import { expect, test, type Page } from "@playwright/test";
import { digest, mockWiki, project, summary } from "./fixtures/company-wiki";

const tab = (page: Page, name: string) => page.getByRole("group", { name: "회사 근거 보기" }).getByRole("button", { name, exact: true });

test("개요의 확인 수준·빈 값과 변경 이력은 서버 값과 같아요", async ({ page }) => {
  await mockWiki(page);
  await page.goto("/company");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("실적 3건 가운데 1건이 업무별 근거 지도에 들어 있어요");
  await expect(page.getByText(digest.slice(0, 12))).toBeVisible();
  await expect(page.getByRole("row", { name: "people.lead 미확인 표시 없음" })).toBeVisible();
  await expect(page.getByRole("row", { name: "people.total 값 없음 추정" })).toBeVisible();
  await expect(page.getByRole("row", { name: "company.name 예시 회사 확인됨" })).toBeVisible();
  await tab(page, "변경 이력").click();
  await expect(page).toHaveURL(/view=log$/);
  await expect(page.getByRole("row", { name: "2026-11-22 규칙을 정리했어요." })).toBeVisible();
  await page.goBack();
  await expect(tab(page, "개요")).toHaveAttribute("aria-pressed", "true");
});

test("주제 선택·근거 없는 단위·실적·위키 본문 링크가 주소를 따라요", async ({ page }) => {
  await mockWiki(page);
  await page.goto("/company?view=work-units");
  await expect(page.getByRole("heading", { name: "문서 검토" })).toHaveCount(0);
  await page.getByRole("link", { name: "문서 단위 2개 · 근거 없는 단위 1개" }).click();
  await expect(page).toHaveURL(/topic=read$/);
  await expect(page.getByText("기록 없음", { exact: true })).toBeVisible();
  await expect(page.getByText(/검토 기록을 확인했어요/)).toBeVisible();
  await expect(page.getByText(/REQ-1/)).toBeVisible();
  await page.getByRole("link", { name: "P1", exact: true }).click();
  await expect(page).toHaveURL(/view=portfolio&project=P1$/);
  await expect(page.getByText("근거 지도 반영 · 넣음 · 요구사항 0건")).toBeVisible();
  await expect(page.getByText(/미반영 · 요구사항 목록 없음/)).toBeVisible();
  await expect(page.getByText(/미반영 · 페이지 없음/)).toBeVisible();
  await expect(page.getByText("<img src=x>")).toBeVisible();
  await page.getByRole("link", { name: "guide", exact: true }).click();
  await expect(page).toHaveURL(/view=pages&page=rule%2Fguide$/);
  await page.reload();
  await expect(page.getByRole("heading", { name: "참고 실적" })).toBeVisible();
  await expect(page.getByRole("link", { name: "업무별 원문" })).toHaveCount(0);
  await page.getByRole("link", { name: "P1", exact: true }).click();
  await expect(page.getByRole("heading", { name: "근거 자료" })).toBeVisible();
  await page.goBack();
  await page.getByRole("link", { name: "work-read" }).click();
  await expect(page).toHaveURL(/view=work-units&topic=read$/);
});

test("근거 지도가 없는 묶음의 건수와 반영 여부를 구분해요", async ({ page }) => {
  await mockWiki(page, { "": { ...summary, work_units_available: false, counts: { ...summary.counts, ingested_projects: null,
    work_topics: null, work_units: null, evidence_links: null, units_without_evidence: null } },
    "/portfolio": { items: [{ ...project, ingested: null, ingested_at: null, evidence_links: null }] } });
  await page.goto("/company");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("실적 3건이 등록돼 있어요");
  await expect(page.locator("dt").filter({ hasText: "업무 주제" }).locator("+ dd")).toHaveText("값 없음");
  await tab(page, "업무별 근거").click();
  await expect(page.getByText("업무별 근거 지도가 아직 없어요.")).toBeVisible();
  await tab(page, "실적").click();
  await expect(page.getByText(/근거 지도 반영 · 근거 지도 없음/)).toBeVisible();
});

for (const [status, code, message] of [
  [404, "company_wiki_unavailable", "회사 위키가 아직 연결되지 않았어요"],
  [503, "company_wiki_unreadable", "회사 위키를 읽을 수 없어요"],
  [404, "company_wiki_work_units_unavailable", "업무별 근거 지도가 아직 없어요"],
] as const) {
  test(`${status} ${code} 상태를 안내해요`, async ({ page }) => {
    const map = code === "company_wiki_work_units_unavailable";
    await mockWiki(page, { [map ? "/work-units" : ""]: { status, error: { code, message: "fixture", details: null } } });
    await page.goto("/company?view=work-units");
    await expect(page.locator("main")).toContainText(message);
  });
}

test("프로필 묶음 이름과 내부 항목, 빈 제외 범위를 구분해요", async ({ page }) => {
  await mockWiki(page);
  await page.goto("/company");
  for (const name of ["회사", "인력", "custom"]) await expect(page.getByRole("table", { name, exact: true })).toBeVisible();
  await expect(page.getByText("schema_version")).toHaveCount(0);
  await page.goto("/company?view=work-units&topic=read");
  await expect(page.getByText("제외 범위 · 값 없음")).toBeVisible();
  await expect(page.getByText(/제외 범위/)).toHaveCount(1);
});

test("직접 연 실적은 목록에서 선택되고 보이는 위치로 이동해요", async ({ page }) => {
  const items = Array.from({ length: 40 }, (_, i) => ({ ...project, id: "P" + i, has_page: false }));
  await mockWiki(page, { "/portfolio": { items } });
  await page.goto("/company?view=portfolio&project=P39");
  const row = page.getByRole("link", { name: /^실적 P39 / });
  await expect(row).toHaveAttribute("aria-current", "page");
  await expect(row).toBeInViewport({ ratio: 0.9 });
  await expect(row).not.toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
});
