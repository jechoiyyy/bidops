import { expect, test } from "@playwright/test";
import {
  mockApi,
  mockPreSpecMatrix,
  mockPreSpecs,
  overviewCompletedRunFixture,
  overviewEnvelopeFixture,
} from "./api-mock";

test("행은 색 없는 등급 글자 토큰을 두고 판정 없음을 접지 않는다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecMatrix(page);
  await page.goto("/pre-specs");
  const grades = page.locator(".pre-specs-row-grade");
  await expect(grades).toHaveCount(8);
  await expect(grades.filter({ hasText: "판정 없음" })).toHaveCount(1);
  // 색이 아니라 글자로 말한다: 등급별 색 클래스를 만들지 않는다.
  const classes = await grades.evaluateAll((nodes) => nodes.map((node) => node.className));
  expect([...new Set(classes)]).toEqual(["pre-specs-row-grade"]);
});

test("자동 준비 필터는 서버 질의에 실리고 추적 결정 대기는 페이지 한정임을 밝힌다", async ({ page }) => {
  const queries: URLSearchParams[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/pre-specs") queries.push(url.searchParams);
  });
  await mockApi(page);
  await mockPreSpecs(page);

  await page.goto("/pre-specs?auto_preparation_status=deep_review_ready_for_click&sw_only=false");
  await expect.poll(() => queries.at(-1)?.get("auto_preparation_status")).toBe("deep_review_ready_for_click");
  expect(queries.at(-1)?.get("sw_only")).toBe("false");

  // 추적 결정 대기는 서버 인자가 아니므로 질의에 실리지 않고 고지만 남는다.
  await page.goto("/pre-specs?tracking_decision=pending&sw_only=false");
  await expect(page.locator(".pre-specs-grade-filter-note")).toContainText("추적 결정 필터는 불러온 페이지에만 적용됩니다");
  expect(queries.at(-1)?.has("tracking_decision")).toBe(false);

  // 허용값이 아니면 무시하고 전체로 떨어진다 — 빈 목록을 지어내지 않는다.
  await page.goto("/pre-specs?auto_preparation_status=not_a_status&tracking_decision=yes&sw_only=false");
  await expect.poll(() => queries.at(-1)?.has("auto_preparation_status")).toBe(false);
  await expect(page.locator(".pre-specs-grade-filter-note")).toHaveCount(0);
});

test("대시보드 결정 대기 링크가 같은 집합의 목록 필터로 잇는다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  // 사이드바에도 같은 이름의 링크가 있으므로 업무 바로가기 띄로 좁힌다.
  await expect(page.locator(".dash-journey-strip").getByRole("link", { name: /사전규격/ }))
    .toHaveAttribute("href", "/pre-specs?auto_preparation_status=deep_review_ready_for_click&sw_only=false&sort=deadline");
});

test("목록에서 방향키로 행을 옮기고 선택이 화면에 남는다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThan(1);

  // 첫 행이 이미 선택된 상태로 시작한다.
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  await rows.first().focus();
  await page.keyboard.press("ArrowDown");
  // 선택은 hook이 아니라 화면이 소유하므로 선택 이동을 먼저 확인한다.
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");
  await expect(rows.nth(1)).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  await expect(rows.first()).toBeFocused();
});

test("경계에서 방향키가 페이지를 넘기고 필터 변경은 첫 페이지로 돌린다", async ({ page }) => {
  // 한 페이지(200건)를 넘는 모집단이어야 경계 이동이 의미를 갖는다.
  const total = 260;
  await mockApi(page);
  await page.route("**/api/pre-specs**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname !== "/api/pre-specs" || route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    const limit = Number(url.searchParams.get("limit") ?? 200);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const items = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, index) => ({
      notice_pk: 9000 + offset + index,
      pre_spec_no: `PRE-${9000 + offset + index}`,
      title: `페이지 표본 ${offset + index + 1}`,
      agency: "표본 발주기관",
      published_at: "2026-08-30T00:00:00Z", deadline_at: null, budget: null,
      sw_business_status: "Y", business_division: "일반용역", origin: "신규",
      opportunity_id: null, tracking_status: null, kept_by_tracking: false,
      document: { attachments: 0, "완료": 0, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
      overview_review_status: "completed", grade: null, grade_source: null,
      auto_preparation_status: "not_applicable", auto_preparation_reason: null,
      latest_deep_review_id: null,
    }));
    await route.fulfill({ json: { items, total, limit, offset, overview_status_counts: [{ status: "completed", count: total }] } });
  });

  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await expect(rows).toHaveCount(200);
  // 마지막 행에서 한 번 더 내려가면 다음 페이지로 넘어간다.
  await rows.last().click();
  await rows.last().focus();
  await page.keyboard.press("ArrowDown");
  await expect.poll(() => new URL(page.url()).searchParams.get("offset")).toBe("200");
  await expect(rows).toHaveCount(60);

  // 반대로 필터를 바꾸면 사람이 요청한 적 없는 3페이지째를 보여 주지 않는다.
  await page.getByRole("button", { name: "상세 필터" }).click();
  await page.getByRole("combobox", { name: "발견 구분" }).click();
  await page.getByRole("option", { name: "신규", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("offset")).toBeNull();
});

test("개요 결과 본문과 첫 주장은 한 번만 렌더된다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  // 결과가 있는 개요 응답을 준다. 기본 mock은 결과 없음(absent) envelope이라
  // 중복 렌더 자체가 드러나지 않는다.
  // 이전 결과를 **다른 id**로 하나 더 둔다. 같은 run을 두 번 주면 history filter가
  // 그것을 걸러 내 이력이 비고, 그러면 anchor 중복을 검사할 수 없다.
  const previousRun = {
    ...overviewCompletedRunFixture,
    id: "00000000-0000-0000-0000-0000000009a1",
    result_id: "00000000-0000-0000-0000-0000000009a1",
    created_at: "2026-09-01T00:00:00Z",
  };
  await page.route("**/api/pre-specs/991/overview", (route) => route.fulfill({
    json: overviewEnvelopeFixture(991, overviewCompletedRunFixture, [overviewCompletedRunFixture, previousRun]),
  }));
  await page.goto("/pre-specs?notice_pk=991&sw_only=false");
  await expect(page.locator(".pre-specs-detail")).toBeVisible();
  // 결과 본문 구역이 둘이면 같은 주장이 두 번 보인다(ADR-0055 D7).
  await expect(page.locator(".pre-specs-overview-section.is-result")).toHaveCount(1);
  // 결과 머리줄이 이미 첫 주장을 말하므로 `문서 근거` 목록은 그것을 다시 적지 않는다.
  const firstClaim = overviewCompletedRunFixture.result!.business_overview[0].text;
  await expect(page.locator(".pre-specs-overview").getByText(firstClaim, { exact: false })).toHaveCount(1);
  // 구역 밖까지 넓혀, 미확인 목록이 탭 안에서 두 번 나오지 않는지도 본다(ADR-0055 D7).
  // 접힌 이력 안의 과거 결과는 그 회차의 내용을 갖는 것이 정상이다. 중복이란
  // 한 번에 **보이는** 자리에서 같은 문장을 두 번 읽는 것을 말한다.
  const unknowns = overviewCompletedRunFixture.result!.unknowns;
  if (unknowns.length > 0) {
    const visible = page.locator(".pre-specs-detail-pane")
      .getByText(unknowns[0], { exact: false })
      .locator("visible=true");
    await expect(visible).toHaveCount(1);
  }
  // 이전 결과가 실제로 한 건 그려진 상태여야 이 검사가 의미를 갖는다.
  await expect(page.getByText("이전 개요 결과 1건", { exact: true })).toBeVisible();
  // 근거 링크가 가리키는 anchor id는 문서 안에서 유일해야 한다 — 이력까지
  // anchor를 달면 같은 id가 둘이 되고 근거 링크가 엉뚜곳으로 뛰다.
  const anchorIds = await page.evaluate(() =>
    [...document.querySelectorAll('[id^="claim-"]')].map((node) => node.id));
  expect(anchorIds.length).toBeGreaterThan(0);
  expect(anchorIds.length).toBe(new Set(anchorIds).size);
});
