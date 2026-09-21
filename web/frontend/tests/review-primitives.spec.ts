import { expect, test } from "@playwright/test";
import { mockApi, mockOpportunity, mockOrderPlans, mockPreSpecs } from "./api-mock";

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
  // R2(0921 명세 §3.1): 이 화면의 공용 `status` 부품은 실행 상태 표시 하나였고, 그것은
  // 최근 실행에 문제가 있을 때만 서는 칩으로 바뀌었다. 평상시 화면에는 상태 부품이 없다 —
  // 추적 상태는 badge가, 실행 상태는 운영 화면이 진다.
  await expect(page.locator('[data-review-primitive="status"]')).toHaveCount(0);
  await expect(page.locator('[data-review-primitive="value"]')).not.toHaveCount(0);
  // pane 바닥의 결정은 추적 결정 넷이다(ADR-0046 결정 4). 사람 판단 수정의 저장은
  // 접힌 보조 입력 영역이 소유하므로 이 바에 없다.
  await expect(page.locator('[data-review-primitive="decision-bar"] [data-review-primitive="decision-action"]')).toHaveCount(4);
  // 같은 사유로 함께 막힌 세 결정이 문구를 한 번만 그린다. 사유·담당자가 모두 비어 있는
  // 첫 상태에서는 둘을 한 문장으로 합쳐 말한다.
  await expect(page.getByText("선택 사유와 담당자 이름을 입력하면 추적 결정을 기록할 수 있습니다.", { exact: true })).toHaveCount(1);
  for (const label of ["추적 시작", "보류", "추적 종료"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toHaveAttribute("aria-describedby", "c2l-tracking-decision-reason");
  }
  // 저장하지 않는 넘기기에는 사유가 붙지 않는다.
  await expect(page.getByRole("button", { name: "이번 건 넘기기", exact: true })).not.toHaveAttribute("aria-describedby", /.+/);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

// 명세 §2.2 — 페이저는 네 화면이 같은 공용 부품(`ListPagerControls`)을 쓴다. 한 쪽에
// 다 들어오는 목록에서도 줄을 지우지 않고 단추만 비활성한다: 건수가 어디에 있는지
// 화면마다 찾지 않게 하려는 것이다.
test("공용 페이저는 한 쪽뿐인 목록에서도 전체 건수와 범위를 남기고 단추만 끈다", async ({ page }) => {
  for (const [path, listPane, total] of [
    ["/order-plans", ".c2l-list-pane", "전체 2건"],
    ["/pre-specs?workspace=all&sw_only=false", ".pre-specs-list-pane", "전체 3건"],
  ] as const) {
    if (path.startsWith("/order-plans")) await mockOrderPlans(page);
    else await mockPreSpecs(page);
    await page.goto(path);

    const pager = page.locator(listPane).locator('[data-review-primitive="list-pager"]');
    await expect(pager).toHaveCount(1);
    await expect(pager).toContainText(total);
    await expect(pager.locator(".review-list-pager-range")).toContainText("/");
    await expect(pager.getByRole("button", { name: "이전", exact: true })).toBeDisabled();
    await expect(pager.getByRole("button", { name: "다음", exact: true })).toBeDisabled();
  }
});

test("사전규격 고급 상태 필터는 0건인 진행·대기도 숨기지 않는다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");
  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  const pending = page.getByRole("combobox", { name: "개요 상태" });
  await pending.click();
  await page.getByRole("option", { name: "진행·대기", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("overview_view")).toBe("pending");
  await expect(page.locator(".pre-specs-row")).toHaveCount(0);
  await expect(page.getByText("조건에 맞는 사전규격이 없습니다.", { exact: true })).toBeVisible();
  await pending.click();
  await page.getByRole("option", { name: "전체 상태", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.has("overview_view")).toBe(false);
  await expect(page.locator(".pre-specs-row")).not.toHaveCount(0);
});

test("LS-02 DenseListRow native Space paths toggle once and preserve active state", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  const first = rows.first();
  const checkbox = first.getByRole("checkbox");
  await first.click();
  await first.focus();

  // A repeat keydown is consumed only to suppress browser scrolling; it must
  // not toggle the checked membership.
  await first.dispatchEvent("keydown", { key: " ", code: "Space", bubbles: true, cancelable: true, repeat: true });
  await expect(checkbox).not.toBeChecked();
  await expect(first).toHaveAttribute("data-checked", "false");
  await page.keyboard.press("Space");
  await expect(checkbox).toBeChecked();
  await expect(first).toHaveAttribute("data-checked", "true");

  // Native checkbox Space is owned by the checkbox's onChange, not the row.
  await checkbox.focus();
  await page.keyboard.press("Space");
  await expect(checkbox).not.toBeChecked();
  await expect(first).toHaveAttribute("aria-current", "true");
});

test("LS-02 interactive children, IME, and modifiers never enter row Space handling", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  const first = page.locator(".pre-specs-row").first();
  const checkbox = first.getByRole("checkbox");
  await first.click();
  await first.focus();
  await page.keyboard.press("Space");
  await expect(checkbox).toBeChecked();

  await first.evaluate((row) => {
    for (const [tag, id] of [
      ["input", "test-child-input"],
      ["textarea", "test-child-textarea"],
      ["button", "test-child-button"],
      ["a", "test-child-link"],
      ["div", "test-child-editable"],
    ] as const) {
      const child = document.createElement(tag);
      child.id = id;
      child.setAttribute("aria-label", id);
      if (tag === "a") child.setAttribute("href", "#child");
      if (tag === "div") child.contentEditable = "true";
      row.appendChild(child);
    }
  });
  for (const id of ["test-child-input", "test-child-textarea", "test-child-button", "test-child-link", "test-child-editable"]) {
    const child = page.locator(`#${id}`);
    await child.focus();
    await page.keyboard.press("Space");
    await expect(first).toHaveAttribute("aria-current", "true");
    await expect(checkbox).toBeChecked();
  }

  await first.focus();
  for (const modifiers of [
    { ctrlKey: true },
    { metaKey: true },
    { altKey: true },
    { shiftKey: true },
    { isComposing: true },
  ]) {
    await first.dispatchEvent("keydown", {
      key: " ",
      code: "Space",
      bubbles: true,
      cancelable: true,
      ...modifiers,
    });
    await expect(checkbox).toBeChecked();
  }
});

test("LS-06 Ctrl/Cmd+Enter keeps the existing single-record detail meaning", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  const first = page.locator(".pre-specs-row").first();
  await first.focus();
  await page.keyboard.press("Control+Enter");
  await expect(page).toHaveURL(/\/pre-specs\/991\?.*sw_only=false/);
  expect(new URL(page.url()).searchParams.has("selection_review")).toBe(false);
});

// ── 단계 B에서 추가한 primitive ────────────────────────────────────────────
// 분할 화면 pane 바닥의 결정 액션, 접힌 보조 입력 영역과 그 append-only revision
// 이력, 등급 4단 스케일.

test("분할 화면의 결정 액션 바는 상세 pane 바닥에 남아 스크롤 위치와 무관하게 보인다", async ({ page }) => {
  await mockOrderPlans(page, "large");
  await page.goto("/order-plans");

  const bar = page.locator('[data-review-primitive="decision-bar"]');
  await expect(bar).toBeVisible();
  await expect(bar).toHaveCSS("position", "sticky");
  // 상세 pane의 sticky 헤더에는 결정 action을 복제하지 않는다.
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

// 승인 시안은 보조 입력을 대화상자로 연다. 현재 값은 하단에 남고 키보드로
// 열고 닫을 수 있으며, 추적 선택이 다른 결정을 바꾸지 않는다는 뜻을 보존한다.
test("추적 입력 창은 키보드로 열고 닫으며 현재 추적 값과 결정의 범위를 보존한다", async ({ page }) => {
  await mockOpportunity(page);
  await page.goto("/opportunities");
  await page.locator(".opportunity-row-business").first().click();

  const footer = page.locator(".opportunity-action-footer");
  const summary = footer.locator(".opportunity-tracking-summary");
  await expect(summary).toBeVisible();
  const before = await summary.innerText();
  const open = footer.getByRole("button", { name: "추적 상태 변경", exact: true });
  await open.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog", { name: "추적 상태 변경", exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("적합성 등급·참여 준비 상태·심층 검토 승인·최종 입찰 Go/No-Go는 바뀌지 않습니다.");
  await expect(dialog.getByRole("combobox", { name: "선택 사유" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(summary).toHaveText(before, { useInnerText: true });
});

test("append-only revision 이력은 건수와 append-only 표식을 함께 보여주고 revision을 덮어쓰지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans?selected=101");
  await page.getByRole("button", { name: "사람 판단 수정 열기" }).click();

  const feedbackDialog = page.getByRole("dialog", { name: "사람 판단 수정 (선택)", exact: true });
  await expect(feedbackDialog).toBeVisible();
  const history = feedbackDialog.locator('[data-review-primitive="revision-history"]');
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
    // docs/0915_ui-redesign/spec.md §1.3 — 포인트 초록 농도 4단.
    "1": "rgb(63, 90, 28)",
    "2": "rgb(88, 122, 43)",
    "3": "rgb(207, 223, 181)",
    "4": "rgb(238, 240, 236)",
  };
  for (const [level, colors] of byLevel) expect([...colors][0], `등급 ${level}`).toBe(ramp[level]);
});

test("긴 한글 제목이 목록 행과 상세 pane을 가로로 넘치게 하지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  const longTitle = "인공지능".repeat(60);
  await page.locator(".c2l-detail-pane").evaluate((pane, text) => {
    const heading = pane.querySelector("h4");
    if (heading) heading.textContent = text;
    const agency = pane.querySelector<HTMLElement>(".c2l-agency-name");
    if (agency) agency.textContent = text;
    const evidence = pane.querySelector<HTMLElement>(".c2l-evidence-body");
    if (evidence) evidence.textContent = text;
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
