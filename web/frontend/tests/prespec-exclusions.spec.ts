import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockPreSpecs } from "./api-mock";
import { clickReadyUnlinkedPreSpec } from "./fixtures/lifecycle-v2";
import type { PreSpecListItem, PreSpecReviewExclusionRequest } from "../src/lib/types";

async function setup(page: Page, count = 3, failFirst = false) {
  await mockApi(page);
  await mockPreSpecs(page);
  const items: PreSpecListItem[] = Array.from({ length: count }, (_, i) => ({
    ...clickReadyUnlinkedPreSpec, notice_pk: 991 + i, title: `제외 검증 ${991+i}`,
    sw_business_status: "Y", origin: "신규", opportunity_id: 78, tracking_status: "미선택",
    overview_review_status: "needs_human_review", auto_preparation_status: "not_applicable",
  }));
  const requests: PreSpecReviewExclusionRequest[] = [];
  await page.route("**/api/pre-specs**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/pre-specs/review-exclusions") {
      const body = route.request().postDataJSON() as PreSpecReviewExclusionRequest;
      requests.push(body);
      if (failFirst && requests.length === 1) { await route.fulfill({ status: 503, json: { detail: "test_unavailable" } }); return; }
      const results = body.notice_ids.map((id) => {
        const item = items.find((item) => item.notice_pk === id)!;
        const outcome = item.review_exclusion_status === body.status ? "unchanged" : "changed";
        item.review_exclusion_status = body.status;
        return { notice_id: id, status: body.status, outcome };
      });
      await route.fulfill({ json: { items: results } }); return;
    }
    if (url.pathname !== "/api/pre-specs") { await route.fallback(); return; }
    const params = url.searchParams;
    const filter = params.get("review_exclusion") ?? "all";
    const candidates = items.filter((item) => (filter === "all" || item.review_exclusion_status === filter)
      && (!params.get("notice_pk") || item.notice_pk === Number(params.get("notice_pk"))));
    const included = candidates.filter((item) => item.review_exclusion_status === "included");
    const visible = ["recent", "actionable"].includes(params.get("workspace") ?? "all") ? included : candidates;
    const offset = Number(params.get("offset") ?? 0), limit = Number(params.get("limit") ?? 200);
    await route.fulfill({ json: { items: visible.slice(offset, offset+limit), total: visible.length, offset, limit,
      workspace_counts: { all: candidates.length, actionable: included.length, recent: included.length, tracking: 0 },
      overview_status_counts: [{ status: "needs_human_review", count: visible.length }],
    }});
  });
  return { items, requests };
}
const row = (page: Page, id: number) => page.locator(`[data-row-key="${id}"]`);
async function fillDialog(page: Page) {
  const dialog = page.getByRole("dialog", { name: "검토 제외", exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("textbox", { name: /^담당자/ }).fill("검증 담당자");
  await dialog.getByRole("textbox", { name: /^사유/ }).fill("검토 범위 밖");
  return dialog;
}

test("단건 제외 실패 후 입력·선택 유지, 명시적 재시도, 다음/이전 행 초점", async ({ page }) => {
  const { requests } = await setup(page, 3, true);
  await page.goto("/pre-specs");
  await row(page, 992).click();
  await row(page, 992).getByRole("checkbox").check();
  await page.getByRole("button", { name: "검토 제외", exact: true }).click();
  const dialog = await fillDialog(page);
  await dialog.getByRole("button", { name: "검토 제외", exact: true }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(dialog.getByRole("textbox", { name: /^사유/ })).toHaveValue("검토 범위 밖");
  expect(requests).toHaveLength(1);
  await dialog.getByRole("button", { name: "다시 시도", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(row(page, 992)).toHaveCount(0);
  await expect(row(page, 993)).toBeFocused();
  await expect(page.locator('.pre-specs-selection-count')).toContainText('0');
  expect(requests).toHaveLength(2);
  await page.getByRole("button", { name: "검토 제외", exact: true }).click();
  const second = await fillDialog(page);
  await second.getByRole("button", { name: "검토 제외", exact: true }).click();
  await expect(row(page, 991)).toBeFocused();
});

test("페이지를 넘는 선택 제외와 마지막 빈 페이지 보정", async ({ page }) => {
  const { requests } = await setup(page, 201);
  await page.goto('/pre-specs');
  await row(page, 991).getByRole('checkbox').check();
  await page.getByRole('navigation', { name: '사전규격 목록 페이지' }).getByRole('button', { name: '다음', exact: true }).click();
  await row(page, 1191).getByRole('checkbox').check();
  await page.getByRole('button', { name: '선택 항목 제외', exact: true }).click();
  const dialog = await fillDialog(page);
  await expect(dialog).toContainText('대상 2건');
  await dialog.getByRole('button', { name: '검토 제외', exact: true }).click();
  await expect(page).not.toHaveURL(/offset=/);
  await expect(row(page, 1190)).toBeFocused();
  expect(requests[0].notice_ids).toEqual([991, 1191]);
  await expect(page.locator('.pre-specs-selection-count')).toContainText('0');
});

test("200건 초과 선택은 전송을 막고 선택 축소를 안내", async ({ page }) => {
  const { requests } = await setup(page, 201);
  await page.goto('/pre-specs');
  await page.getByRole('button', { name: '현재 페이지 전체 선택' }).click();
  await page.getByRole('navigation', { name: '사전규격 목록 페이지' }).getByRole('button', { name: '다음', exact: true }).click();
  await row(page, 1191).getByRole('checkbox').check();
  await expect(page.getByRole('button', { name: '선택 항목 제외' })).toBeDisabled();
  await expect(page.getByText('한 번에 200건까지 제외할 수 있습니다. 선택을 줄여 주세요.')).toBeVisible();
  expect(requests).toHaveLength(0);
});

test("전체 이력 제외 필터·단건 복원·URL 초기화·상세 표식", async ({ page }) => {
  const state = await setup(page);
  state.items[0].review_exclusion_status = 'excluded';
  await page.goto('/pre-specs?workspace=all&review_exclusion=excluded');
  await expect(row(page, 991)).toContainText('검토 제외');
  await expect(row(page, 992)).toHaveCount(0);
  await page.getByRole('link', { name: '상세 페이지 열기 →' }).click();
  await expect(page.locator('.ps-record-header-actions').getByText('검토 제외', { exact: true })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/review_exclusion=excluded/);
  await page.getByRole('button', { name: '검토 목록으로 복원', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '검토 목록으로 복원' });
  await dialog.getByRole('textbox', { name: /^담당자/ }).fill('검증 담당자');
  await dialog.getByRole('textbox', { name: /^사유/ }).fill('다시 검토');
  await dialog.getByRole('button', { name: '검토 목록으로 복원', exact: true }).click();
  await expect(row(page, 991)).toHaveCount(0);
  expect(state.requests[0].status).toBe('included');
  await page.getByRole('button', { name: /검토할 항목/ }).click();
  await expect(page).not.toHaveURL(/review_exclusion=/);
  await expect(row(page, 991)).toBeVisible();
});

test("미저장 추적 입력의 취소는 제외 창과 요청을 열지 않는다", async ({ page }) => {
  const { requests } = await setup(page);
  await page.goto('/pre-specs');
  await page.getByRole('textbox', { name: '담당자 이름 (필수)' }).fill('미저장 이름');
  await page.getByRole('button', { name: '검토 제외', exact: true }).click();
  const guard = page.getByRole('alertdialog', { name: '추적 결정 입력을 저장하지 않고 옮깁니다' });
  await expect(guard).toBeVisible();
  await guard.getByRole('button', { name: '계속 편집' }).click();
  await expect(page.getByRole('textbox', { name: '담당자 이름 (필수)' })).toHaveValue('미저장 이름');
  expect(requests).toHaveLength(0);
  await page.getByRole('button', { name: '검토 제외', exact: true }).click();
  await guard.getByRole('button', { name: '저장하지 않고 옮기기' }).click();
  await expect(page.getByRole('dialog', { name: '검토 제외', exact: true })).toBeVisible();
});


test("페이지 마지막 활성 행 제외 시 다음 페이지에서 채워진 다음 행으로 이동", async ({ page }) => {
  await setup(page, 201);
  await page.goto('/pre-specs');
  await row(page, 1190).click();
  await page.getByRole('button', { name: '검토 제외', exact: true }).click();
  const dialog = await fillDialog(page);
  await dialog.getByRole('button', { name: '검토 제외', exact: true }).click();
  await expect(row(page, 1191)).toBeFocused();
});


test("전체 이력 포함 여부 필터는 URL과 선택 범위를 함께 갱신", async ({ page }) => {
  const state = await setup(page);
  state.items[0].review_exclusion_status = 'excluded';
  await page.goto('/pre-specs?workspace=all');
  await row(page, 992).getByRole('checkbox').check();
  await page.getByRole('combobox', { name: '검토 포함 여부' }).click();
  await page.getByRole('option', { name: '검토 제외', exact: true }).click();
  await expect(page).toHaveURL(/review_exclusion=excluded/);
  await expect(row(page, 991)).toBeVisible();
  await expect(row(page, 992)).toHaveCount(0);
  await expect(page.locator('.pre-specs-selection-count')).toContainText('0');
});
