import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans, mockPreSpecs } from "./api-mock";

test("공통 상세 필터는 조건을 URL에 적용하고 닫으면 열기 버튼으로 돌아간다", async ({ page }) => {
  await mockApi(page);
  await mockOrderPlans(page);

  for (const route of ["order-plans", "pre-specs", "opportunities"]) {
    await page.goto(`/${route}`);
    const toggle = page.getByRole("button", { name: "상세 필터", exact: true });
    await toggle.click();
    const panel = page.getByRole("region", { name: "상세 필터", exact: true });
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(panel).toBeVisible();
    if (route === "order-plans") {
      await panel.getByRole("button", { name: "불확실", exact: true }).click();
      await expect(page).toHaveURL(/qwen=[^&]*uncertain/);
    } else if (route === "pre-specs") {
      await panel.getByRole("combobox", { name: "개요 상태" }).click();
      await page.getByRole("option", { name: "개요 완료", exact: true }).click();
      await expect(page).toHaveURL(/overview_view=completed/);
      await panel.getByRole("button", { name: "기본값으로" }).click();
      await expect(page).not.toHaveURL(/overview_view=/);
    } else {
      await panel.getByRole("combobox", { name: "표시 순서" }).click();
      await page.getByRole("option", { name: "마감 임박순" }).click();
      await expect(page).toHaveURL(/sort=/);
    }
    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(toggle).toBeFocused();
  }
});

test("적용 필터를 해제하면 해당 축만 풀고 체크 선택을 초기화한다", async ({ page }) => {
  await mockApi(page);
  await mockOrderPlans(page);
  await mockPreSpecs(page);

  const tokens = page.getByRole("group", { name: "적용한 필터", exact: true });
  const remove = (label: string) => tokens.locator(".astryx-token", { hasText: label }).getByRole("button");

  await page.goto("/order-plans");
  const orderRows = page.getByRole("table", { name: "발주계획 검토 목록", exact: true });
  await expect(orderRows.getByRole("checkbox")).toHaveCount(1);
  await orderRows.getByRole("checkbox").check();
  const orderSelection = page.getByRole("group", { name: "발주계획 선택 작업", exact: true });
  await expect(orderSelection).toContainText("선택 1건");
  await remove("추적 선택 · 미선택").click();
  await expect(page).toHaveURL((url) => url.searchParams.get("tracking") === "" && url.searchParams.get("qwen") === "relevant");
  await expect(orderSelection).toContainText("선택 0건");

  await page.goto("/pre-specs?workspace=all&sw_only=false&origin=신규");
  const preSpecRow = page.getByRole("table", { name: "사전규격", exact: true })
    .getByRole("row", { name: "신규 지능형 행정 지원 사전규격", exact: true });
  await preSpecRow.getByRole("checkbox").check();
  const preSpecSelection = page.getByRole("group", { name: "사전규격 선택 작업", exact: true });
  await expect(preSpecSelection).toContainText("선택 1건");
  await remove("발견 구분 · 독립 발견").click();
  await expect(page).toHaveURL((url) => !url.searchParams.has("origin") && url.searchParams.get("sw_only") === "false");
  await expect(preSpecSelection).toContainText("선택 0건");
  await expect(preSpecRow.getByRole("checkbox")).not.toBeChecked();
});
