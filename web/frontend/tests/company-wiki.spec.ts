import { expect, test, type Page } from "@playwright/test";
import { digest, mockWiki, project, summary } from "./fixtures/company-wiki";

const tab = (page: Page, name: string) => page.getByRole("group", { name: "회사 근거 보기" }).getByRole("button", { name, exact: true });

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

test("프로필 이름표와 확인 수준을 읽고 기술 정보를 펼쳐요", async ({ page }) => {
  await mockWiki(page);
  await page.goto("/company");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "예시 회사" })).toBeVisible();
  await expect(page.locator("header.topbar .topbar-view-note")).toHaveText("실적 5건 가운데 4건이 업무별 근거 지도에 들어 있어요");
  await expect(main).toContainText("마지막으로 바뀐 날 · 2026-11-22");
  for (const name of ["회사", "인력", "custom"]) await expect(main.getByRole("table", { name, exact: true })).toBeVisible();
  for (const name of ["회사명 예시 회사 확인됨", "등록 건수 0건 공개 자료", "people.lead 미확인 표시 없음", "people.total 값 없음 추정"]) {
    await expect(main.getByRole("row", { name, exact: true })).toBeVisible();
  }
  for (const label of ["확인됨 · 담당자가 확인한 값", "공개 자료 · 홈페이지 등 공개된 자료에서 옮긴 값",
    "데모값 · 시연을 위해 임의로 넣은 값", "추정 · 다른 자료에서 추정한 값", "표시 없음 · 확인 수준이 기록되지 않은 값"]) {
    await expect(main.getByRole("listitem").filter({ hasText: label })).toBeVisible();
  }
  const digestText = main.getByText(digest.slice(0, 12), { exact: true });
  await expect(digestText).toBeHidden();
  await main.getByText("기술 정보", { exact: true }).click();
  await expect(digestText).toBeVisible();
  await expect(main.getByText(/위키 식별 이름 · sample/)).toContainText("이름표 · 사용");
  await expect(main.getByText(/규칙 1쪽/)).toBeVisible();
});

test("변경 종류별 설명과 실적명 없는 기록을 읽어요", async ({ page }) => {
  await mockWiki(page);
  await page.goto("/company");
  await tab(page, "변경 이력").click();
  await expect(page).toHaveURL(/view=log$/);
  for (const text of ["규칙을 정리했어요.", "업무 분류표를 만들었어요", "분석에서 확인한 내용을 반영했어요",
    "문서 보관 실적을 넣었어요 · 요구사항 2건 · 분류되지 않은 요구사항 1건", "P2020-01 실적을 넣었어요 · 요구사항 0건"]) {
    await expect(page.getByRole("cell", { name: text, exact: true })).toBeVisible();
  }
  await page.goBack();
  await expect(tab(page, "개요")).toHaveAttribute("aria-pressed", "true");
});

test("최근 세 사업과 나머지 사업, 수행 기록이 없는 업무를 구분해요", async ({ page }) => {
  await mockWiki(page);
  await page.goto("/company?view=work-units");
  await expect(page.getByRole("heading", { name: "문서 검토" })).toHaveCount(0);
  await page.getByRole("link", { name: /문서 업무 2가지 · 실적 4건.*근거 없는 업무 1가지/ }).click();
  await expect(page).toHaveURL(/topic=read$/);
  await expect(page.getByText("4개 사업에서 수행 · 최근 2026년")).toBeVisible();
  await expect(page.getByText("수행 기록 없음")).toBeVisible();
  await expect(page.getByText(/검토 기록을 확인했어요/)).toContainText("2026-11-22");
  await expect(page.getByText(/제외 범위/)).toHaveCount(1);
  for (const name of [project.title!, "기록 정리", "문서 등록"]) await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
  const oldest = page.getByRole("link", { name: "예전 사업" });
  await expect(oldest).toHaveCount(0);
  await page.getByRole("button", { name: "나머지 1개 사업 보기" }).click();
  await expect(oldest).toBeVisible();
  await expect(page.getByRole("button", { name: "ALT-3" })).toBeVisible();
  await page.getByRole("button", { name: "사업 접기" }).click();
  await expect(oldest).toHaveCount(0);
  await page.getByRole("link", { name: project.title!, exact: true }).click();
  await expect(page).toHaveURL(/view=portfolio&project=P2026-01$/);
});

test("요구사항 단추를 누른 뒤 원문을 조회하고 상태를 그 자리에서 읽어요", async ({ page }) => {
  await mockWiki(page);
  let release!: () => void;
  const delayed = new Promise<void>(resolve => { release = resolve; });
  let requests = 0;
  await page.route("**/requirements/REQ-1", async route => {
    requests++;
    await delayed;
    await route.fallback();
  });
  await page.goto("/company?view=work-units&topic=read");
  const button = page.getByRole("button", { name: "문서 분류" });
  await expect(button).toHaveAttribute("aria-expanded", "false");
  expect(requests).toBe(0);
  await button.press("Enter");
  try {
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("status").filter({ hasText: "원문을 불러오고 있어요." })).toBeVisible();
  } finally { release(); }
  await expect(page.getByText("문서 분류 원문이에요.")).toBeVisible();
  await expect(page.getByText("실적 P2026-01 · 요구사항 REQ-1")).toBeVisible();
  await button.press("Space");
  await expect(page.getByText("문서 분류 원문이에요.")).toBeHidden();
  await page.getByRole("button", { name: "문서 검색" }).click();
  await expect(page.getByRole("alert")).toHaveText("요구사항 원문을 찾을 수 없어요.");
  await page.route("**/requirements/ALT-1", route => route.fulfill({ status: 503, json: { error: { code: "company_wiki_unreadable" } } }));
  await page.getByRole("button", { name: "ALT-1" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "원문을 불러오지 못했어요." })).toBeVisible();
});

test("실적 상세와 접힌 원문에서 위키·업무 링크를 따라가요", async ({ page }) => {
  await mockWiki(page);
  await page.goto("/company?view=portfolio&project=P2026-01");
  const main = page.getByRole("main");
  await expect(main.getByRole("link", { name: /요구사항 2건 정리됨.*실적 P2026-01/ })).toHaveAttribute("aria-current", "page");
  for (const text of ["요구사항 0건 정리됨", "요구사항 목록 없음", "상세 페이지 없음"]) {
    await expect(main.getByRole("link").filter({ hasText: text })).not.toHaveCount(0);
  }
  for (const name of ["수행한 범위", "이 사업에서 수행한 업무", "요구사항"]) {
    await expect(main.getByRole("heading", { name, exact: true })).toBeVisible();
  }
  await expect(main).toContainText("유형 · 값 없음");
  await expect(main).toContainText("역할 · 미확인");
  await expect(main.getByRole("listitem").filter({ hasText: "문서 목록을 관리해요." })).toBeVisible();
  await expect(main.getByRole("link", { name: "문서 검토" })).toHaveAttribute("href", "/company?view=work-units&topic=read");
  await main.getByRole("button", { name: "문서 분류" }).click();
  await expect(main.getByText("문서 분류 원문이에요.")).toBeVisible();
  await expect(main.getByRole("heading", { name: "근거 자료" })).toBeHidden();
  await main.getByText("위키 원문 보기", { exact: true }).click();
  await expect(main.getByText("<img src=x>")).toBeVisible();
  await main.getByRole("link", { name: "guide", exact: true }).click();
  await expect(page).toHaveURL(/view=pages&page=rule%2Fguide$/);
  await page.reload();
  await expect(main.getByRole("heading", { name: "참고 실적" })).toBeVisible();
  await expect(main.getByRole("link", { name: "업무별 원문" })).toHaveCount(0);
  await main.getByRole("link", { name: "work-read" }).click();
  await expect(page).toHaveURL(/view=work-units&topic=read$/);
});

test("근거 지도가 없는 묶음은 날짜와 건수를 추정하지 않아요", async ({ page }) => {
  await mockWiki(page, { "": { ...summary, last_changed: null, work_units_available: false, counts: { ...summary.counts,
    ingested_projects: null, work_topics: null, work_units: null, evidence_links: null, units_without_evidence: null } } });
  await page.goto("/company");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("회사 근거");
  await expect(page.locator("header.topbar .topbar-view-note")).toHaveText("실적 5건이 등록돼 있어요");
  await expect(page.getByText(/마지막으로 바뀐 날/)).toHaveCount(0);
  await expect(page.getByRole("definition").filter({ hasText: "값 없음" })).toHaveCount(3);
  await tab(page, "업무별 근거").click();
  await expect(page.getByText("업무별 근거 지도가 아직 없어요.")).toBeVisible();
});

test("직접 연 실적은 목록에서 선택되고 보이는 위치로 이동해요", async ({ page }) => {
  const items = Array.from({ length: 40 }, (_, i) => ({ ...project, id: "P2026-" + String(i).padStart(2, "0"), has_page: false }));
  await mockWiki(page, { "/portfolio": { items }, "/portfolio/P2026-39": { ...items[39], scope_lines: [], requirements: [], work_units: [], domain: null } });
  await page.goto("/company?view=portfolio&project=P2026-39");
  const row = page.getByRole("link", { name: /실적 P2026-39$/ });
  await expect(row).toHaveAttribute("aria-current", "page");
  await expect(row).toBeInViewport({ ratio: 0.9 });
  await expect(row).not.toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
});
