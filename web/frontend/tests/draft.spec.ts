import { expect, test } from "@playwright/test";
import { mockApi } from "./api-mock";

/**
 * P0-2가 요구한 "미저장 초안이 사라지지 않는다"는 계약은 입력이 있는 자리에만
 * 의미가 있다.
 *
 * ADR-0046 결정 3으로 공고 1차 판정 화면은 읽기 전용 이력이 됐고(PLAN 단계 E
 * 작업 4), 리뷰 초안·localStorage 임시 저장·저장 버튼이 모두 사라졌다. 사람의
 * 수정은 사업 추적 상세의 예외 작업으로 옮겨갔으므로, 초안 보호도 그 자리로
 * 옮겨 확인한다.
 *
 * 이 파일은 두 가지를 함께 지킨다.
 * 1. 읽기 전용이 된 화면에 입력이 남아 있지 않다. 저장할 것이 없는데 "저장되지
 *    않은 변경" 경고가 뜨지 않는다.
 * 2. 입력이 실제로 있는 자리(사업 추적의 예외 작업·추적 상태 변경)는 화면을
 *    벗어날 때 그 입력을 지키라고 알린다.
 */

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("공고 1차 판정 화면에는 리뷰 입력이 없고 저장 경로도 없다", async ({ page }) => {
  let reviewWrites = 0;
  await page.route("**/api/notices/*/review", async (route) => {
    if (route.request().method() === "PUT") reviewWrites += 1;
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "저장 경로가 없어야 한다" }) });
  });

  await page.goto("/queue");
  await page.waitForURL(/\/queue\/\d+/);

  await expect(page.getByLabel("리뷰 사유")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "저장하고 다음" })).toHaveCount(0);
  await expect(page.getByText("저장되지 않은 변경사항")).toHaveCount(0);
  // 확인 항목 답변 입력도 사라진다. 저장할 수 없는 입력을 남겨 두지 않는다.
  await expect(page.locator(".verification-answer-input")).toHaveCount(0);

  // 저장할 것이 없으므로 이탈 확인도 걸리지 않는다.
  const blocked = await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  });
  expect(blocked).toBe(false);
  expect(reviewWrites).toBe(0);
});

test("읽기 전용 화면은 저장된 리뷰와 수정하러 갈 자리를 함께 남긴다", async ({ page }) => {
  await page.goto("/queue");
  await page.waitForURL(/\/queue\/\d+/);

  const record = page.locator(".review-record");
  await expect(record.getByRole("heading", { name: "담당자 리뷰" })).toBeVisible();
  await expect(record).toContainText("읽기 전용 이력");
  // 리뷰가 없는 것과 못 읽은 것을 섞지 않는다.
  await expect(record).toContainText(/저장된 담당자 리뷰가 없습니다|담당자 감사 표식/);
  await expect(record).toContainText("사업 추적");
  await expect(record.getByRole("link", { name: "사업 추적에서 이 사업기회 찾기 →" })).toBeVisible();
});

test("사업 추적의 추적 상태 변경은 미저장 입력을 지키라고 알린다", async ({ page }) => {
  await page.route("**/api/opportunities/501", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 501,
        tracking_status: "계속 추적",
        tracking_reason: "기존 이유",
        tracking_selected_by: "기존 담당자",
        tracking_selected_at: "2026-08-29T00:00:00Z",
        recheck_signal: false,
        recheck_signal_at: null,
        recheck_signal_link_id: null,
        first_registered_stage: "order_plan",
        links: [],
      }),
    });
  });

  // 목록 우측 pane의 빠른 조작 상세로 연다(RL-02: `/opportunities/501`은 이제 사업기회 레코드다).
  await page.goto(`/opportunities?section=${encodeURIComponent("전체")}&selected=501`);
  await page.getByRole("button", { name: "추적 상태 변경", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: "기타", exact: true }).click();
  await dialog.getByLabel("선택 사유 직접 입력").fill("검증용 미저장 메모");

  const blocked = await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  });
  expect(blocked).toBe(true);

  // 추적 변경은 대화상자 안에서 진행한다. 배경의 이동 링크는 닫기 전까지
  // 조작할 수 없고, 먼저 입력을 유지할지 버릴지 같은 창 안에서 확인한다.
  await page.keyboard.press("Escape");
  await expect(dialog).toContainText("입력한 내용을 버릴까요?");
  await expect(dialog).toContainText("저장된 추적 상태는 바뀌지 않습니다");
  await dialog.getByRole("button", { name: "계속 작성", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/opportunities");
  await expect(dialog.getByLabel("선택 사유 직접 입력")).toHaveValue("검증용 미저장 메모");

  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  await dialog.getByRole("button", { name: "입력 버리고 닫기", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".opportunity-action-footer")).toContainText("계속 추적");
  expect(await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  })).toBe(false);
  // 입력을 버린 뒤에는 다른 화면으로의 이동이 막히지 않는다(목록 화면은 상단 경로 대신 사이드바로 이동한다).
  await page.locator("aside.sidebar").getByRole("link", { name: "오늘의 브리핑", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/briefing");
});
