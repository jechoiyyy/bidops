import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans, mockPreSpecs } from "./api-mock";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("검토 대기열은 공통 필터·밀집 행·sticky 결정 헤더를 사용한다", async ({ page }) => {
  await page.goto("/queue");

  const filterBar = page.locator('[data-review-primitive="filter-bar"]');
  await expect(filterBar).toBeVisible();
  await expect(filterBar.locator('[data-review-primitive="filter-selector"]')).toHaveCount(5);
  await expect(filterBar.locator('[data-review-primitive="text-input"]')).toHaveCount(1);
  await expect(page.locator('[data-review-primitive="dense-list"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="dense-list-row"]')).not.toHaveCount(0);
  await expect(page.locator('[data-review-primitive="sticky-decision-header"]')).toBeVisible();
  // 단계 E 작업 4 이후 이 화면에는 입력이 없다. 리뷰 입력이 쓰던 segmented
  // control도 함께 사라졌고, 남은 것은 저장된 리뷰를 읽는 자리다.
  await expect(page.locator('[data-review-primitive="segmented-control"]')).toHaveCount(0);
  await expect(page.locator(".review-record")).toBeVisible();

  const headerPosition = await page.locator('[data-review-primitive="sticky-decision-header"]').evaluate((element) => getComputedStyle(element).position);
  expect(headerPosition).toBe("sticky");

  const rows = page.locator('[data-review-primitive="dense-list-row"]');
  await rows.nth(1).focus();
  await page.keyboard.press("Enter");
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");

  const grade = page.getByRole("combobox", { name: "등급", exact: true });
  await grade.click();
  await page.getByRole("option", { name: "우선 검토", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("grade")).toBe("우선 검토");
  const reset = page.getByRole("button", { name: "필터 1개 해제", exact: true });
  await expect(reset).toBeVisible();
  await reset.click();
  await expect(page).not.toHaveURL(/grade=/);
});

test("발주계획 C-2는 공통 필터·목록·상세·상태·결정 action을 한 화면에서 조합한다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  await expect(page.locator('[data-review-primitive="filter-bar"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="text-input"]')).not.toHaveCount(0);
  await expect(page.locator('[data-review-primitive="dense-list"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="dense-list-row"]')).toHaveCount(2);
  await expect(page.locator('[data-review-primitive="split-workspace"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="sticky-decision-header"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="status"]')).not.toHaveCount(0);
  await expect(page.locator('[data-review-primitive="value"]')).not.toHaveCount(0);
  // pane 바닥의 결정은 추적 결정 넷이다(ADR-0045 결정 4). 사람 판단 수정의 저장은
  // 접힌 보조 입력 영역이 소유하므로 이 바에 없다.
  await expect(page.locator('[data-review-primitive="decision-bar"] [data-review-primitive="decision-action"]')).toHaveCount(4);
  // 같은 사유로 함께 막힌 세 결정이 문구를 한 번만 그린다.
  await expect(page.getByText("담당자 이름을 입력하면 추적 결정을 기록할 수 있습니다.", { exact: true })).toHaveCount(1);
  for (const label of ["추적 시작", "보류", "추적 종료"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toHaveAttribute("aria-describedby", "c2l-tracking-decision-reason");
  }
  // 저장하지 않는 넘기기에는 사유가 붙지 않는다.
  await expect(page.getByRole("button", { name: "이번 건 넘기기", exact: true })).not.toHaveAttribute("aria-describedby", /.+/);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("사전규격 상태 그룹은 공통 collapsible primitive로 0건·미시작 상태를 보존한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");

  const groups = page.locator('[data-review-primitive="state-group"]');
  await expect(groups).toHaveCount(11);
  await expect(page.getByRole("button", { name: /^사람 검토 필요/ })).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("button", { name: /^실패/ })).toHaveAttribute("aria-expanded", "true");
  const notStarted = page.getByRole("button", { name: /^개요 검토 미시작/ });
  await expect(notStarted).toHaveAttribute("aria-expanded", "false");
  await notStarted.click();
  await expect(notStarted).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("개요 검토 미시작", { exact: true })).toBeVisible();
});

// ── 단계 B에서 추가한 primitive ────────────────────────────────────────────
// 결정 액션 배치 두 형태(분할 화면의 pane 바닥 / 단독 상세의 sticky 헤더),
// 접힌 보조 입력 영역과 그 append-only revision 이력, 등급 4단 스케일.

test("분할 화면의 결정 액션 바는 상세 pane 바닥에 남아 스크롤 위치와 무관하게 보인다", async ({ page }) => {
  await mockOrderPlans(page, "large");
  await page.goto("/order-plans");

  const bar = page.locator('[data-review-primitive="decision-bar"]');
  await expect(bar).toBeVisible();
  await expect(bar).toHaveCSS("position", "sticky");
  // 단독 상세용 sticky 헤더와 같은 화면에서 두 배치를 섞지 않는다.
  await expect(page.locator('[data-review-primitive="sticky-decision-header"] [data-review-primitive="decision-action"]')).toHaveCount(0);

  const start = page.getByRole("button", { name: "추적 시작", exact: true });
  await expect(start).toBeInViewport();

  // 상세 pane 본문을 끝까지 내려도 결정 액션은 제자리에 남는다.
  await page.locator(".c2l-detail-scroll").evaluate((element) => element.scrollTo({ top: element.scrollHeight, behavior: "instant" }));
  for (const label of ["추적 시작", "보류", "추적 종료", "이번 건 넘기기"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toBeInViewport();
  }

  const geometry = await page.locator(".c2l-detail-pane").evaluate((pane) => {
    const actions = pane.querySelector<HTMLElement>('[data-review-primitive="decision-bar"]');
    const scroll = pane.querySelector<HTMLElement>(".c2l-detail-scroll");
    if (!actions || !scroll) throw new Error("결정 액션 바 또는 상세 스크롤 영역을 찾을 수 없습니다.");
    return {
      paneBottom: pane.getBoundingClientRect().bottom,
      paneHeight: pane.getBoundingClientRect().height,
      barBottom: actions.getBoundingClientRect().bottom,
      barHeight: actions.getBoundingClientRect().height,
      scrollHeight: scroll.getBoundingClientRect().height,
    };
  });
  expect(geometry.barBottom).toBeLessThanOrEqual(geometry.paneBottom + 1);

  // 바 안에서 액션과 안내가 좁아지면 줄을 바꿔야 한다. 한쪽이 0에 가깝게 눌리면 긴 한글이
  // 한 글자씩 세로로 쌓여 바가 pane 전체를 덮고 본문이 사라진다. 실제로 겪은 회귀다.
  expect(geometry.barHeight, `결정 액션 바가 pane(${geometry.paneHeight}px)의 절반을 넘었다`).toBeLessThan(geometry.paneHeight / 2);
  expect(geometry.scrollHeight).toBeGreaterThan(geometry.barHeight);
});

test("접힌 보조 입력 영역은 닫아도 현재 값과 무엇을 바꾸지 않는지를 남기고 입력만 숨긴다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  const secondary = page.locator('[data-review-primitive="secondary-input"]');
  await expect(secondary).toHaveCount(1);

  // pane 바닥의 결정이 추적 결정이므로 사람 판단 수정은 기본이 접힘이다(ADR-0045 결정 5).
  const reopen = page.getByRole("button", { name: "사람 판단 수정 (선택) 열기" });
  await expect(secondary).toHaveAttribute("data-open", "false");
  await expect(reopen).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByLabel("담당자 claimed name")).toBeHidden();
  // 접어도 현재 사람 판단 값과 이 입력이 대신하지 않는 결정은 화면에 남는다.
  await expect(secondary.locator(".review-secondary-input-summary")).toHaveText("relevant · 우선순위 high");
  await expect(secondary.locator(".review-secondary-input-description"))
    .toHaveText("기존 사람 판단을 유지합니다. 추적 결정과는 별도 revision이며 적합성 등급·참여 준비 상태·심층 추적 승인·최종 Go/No-Go를 채우거나 대신하지 않습니다.");

  // 접힌 영역은 토글이 aria-controls로 가리키는 하나의 region이다.
  const controls = await reopen.getAttribute("aria-controls");
  expect(controls).toBeTruthy();
  await expect(page.locator(`#${controls}`)).toContainText("담당자 claimed name");

  // 키보드만으로 열 수 있고 열림 상태가 aria로도 전달된다.
  await reopen.focus();
  await page.keyboard.press("Enter");
  await expect(secondary).toHaveAttribute("data-open", "true");
  await expect(page.getByRole("button", { name: "사람 판단 수정 (선택) 닫기" })).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByLabel("담당자 claimed name")).toBeVisible();
});

test("append-only revision 이력은 건수와 append-only 표식을 함께 보여주고 revision을 덮어쓰지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/101");

  const history = page.locator('[data-review-primitive="revision-history"]');
  await expect(history).toBeVisible();
  await expect(history).toHaveAttribute("data-revision-count", "1");
  await expect(history).toContainText("append-only · 1건");
  await expect(history.locator("[data-revision]")).toHaveCount(1);
  await expect(history.locator('[data-revision="1"]')).toContainText("revision 1");
});

test("등급 4단은 한 벌의 농도 스케일을 쓰고 색만이 아니라 라벨을 함께 쓴다", async ({ page }) => {
  await page.goto("/queue");

  const grades = page.locator('[data-review-primitive="grade"]');
  await expect(grades).not.toHaveCount(0);

  const rendered = await grades.evaluateAll((nodes) => nodes.map((node) => ({
    level: node.getAttribute("data-grade-level"),
    text: (node.textContent ?? "").trim(),
    background: getComputedStyle(node).backgroundColor,
  })));

  // 라벨 없이 색만으로 등급을 나타내는 배지가 없다.
  for (const badge of rendered) expect(badge.text.length).toBeGreaterThan(0);

  // 각 단은 grade-ramp.css 의 값 하나로만 칠해진다. 같은 단은 같은 색이고
  // 다른 단은 다른 색이다.
  const byLevel = new Map<string, Set<string>>();
  for (const badge of rendered) {
    if (!badge.level) continue;
    const bucket = byLevel.get(badge.level) ?? new Set<string>();
    bucket.add(badge.background);
    byLevel.set(badge.level, bucket);
  }
  expect(byLevel.size).toBeGreaterThan(0);
  for (const [level, colors] of byLevel) expect(colors, `등급 ${level}`).toHaveProperty("size", 1);
  const distinct = new Set([...byLevel.values()].map((colors) => [...colors][0]));
  expect(distinct.size).toBe(byLevel.size);

  const ramp: Record<string, string> = {
    "1": "rgb(47, 58, 76)",
    "2": "rgb(91, 104, 124)",
    "3": "rgb(147, 160, 176)",
    "4": "rgb(211, 217, 225)",
  };
  for (const [level, colors] of byLevel) expect([...colors][0], `등급 ${level}`).toBe(ramp[level]);
});

test("긴 한글 제목이 목록 행과 접힌 보조 입력을 가로로 넘치게 하지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  const longTitle = "인공지능".repeat(60);
  await page.locator(".c2l-detail-pane").evaluate((pane, text) => {
    const heading = pane.querySelector("h4");
    if (heading) heading.textContent = text;
    const title = pane.querySelector<HTMLElement>(".review-secondary-input-title");
    if (title) title.textContent = text;
  }, longTitle);

  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    pane: (() => {
      const pane = document.querySelector<HTMLElement>(".c2l-detail-pane");
      return pane ? pane.scrollWidth - pane.clientWidth : 0;
    })(),
  }));
  expect(overflow.document).toBeLessThanOrEqual(1);
  expect(overflow.pane).toBeLessThanOrEqual(1);
});
