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
  const contentTypes: Array<string | undefined> = [];
  await page.route("**/api/pre-specs**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/pre-specs/review-exclusions") {
      const body = route.request().postDataJSON() as PreSpecReviewExclusionRequest;
      requests.push(body);
      contentTypes.push(route.request().headers()["content-type"]);
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
      // 계약상 항상 있는 집계다. 이 표본에는 마감 경과 건이 없으므로 전부 `current`다.
      deadline_scope_counts: { current: included.length, passed: 0 },
      overview_status_counts: [{ status: "needs_human_review", count: visible.length }],
    }});
  });
  return { items, requests, contentTypes };
}
const row = (page: Page, id: number) => page.locator(`[data-row-key="${id}"]`);
const EXCLUDE_DIALOG = "선택한 사전규격 검토 제외";
const RESTORE_DIALOG = "선택한 사전규격 검토 목록으로 복원";
/** 일괄 창 공용 구조(2026-09-23 시안 ②): 사유 선택지 + 담당자, 바닥 단추 `N건 검토 제외`. */
async function fillDialog(page: Page) {
  const dialog = page.getByRole("dialog", { name: EXCLUDE_DIALOG, exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("textbox", { name: /^담당자/ }).fill("검증 담당자");
  await dialog.getByRole("combobox", { name: "제외 사유 (필수)" }).click();
  await page.getByRole("option", { name: "현재 검토 범위와 맞지 않음", exact: true }).click();
  return dialog;
}
const saveExclusion = (dialog: import("@playwright/test").Locator) =>
  dialog.getByRole("button", { name: /^\d+건 검토 제외$/ });

test("단건 제외 실패 후 입력·선택 유지, 명시적 재시도, 다음/이전 행 초점", async ({ page }) => {
  const { requests } = await setup(page, 3, true);
  await page.goto("/pre-specs");
  await row(page, 992).click();
  await row(page, 992).getByRole("checkbox").check();
  await page.getByRole("button", { name: "검토 제외", exact: true }).click();
  const dialog = await fillDialog(page);
  await expect(dialog).toContainText("제외 1건");
  await expect(dialog).toContainText("팀 전체의 일상 목록에서 숨겨요. 추적 상태와 자동 분석은 그대로예요.");
  await saveExclusion(dialog).click();
  // 서버 응답을 오류 종류로 옮겨 보인다(503 → 서버 오류). 입력과 선택은 그대로다.
  await expect(dialog.getByRole("alert")).toContainText("서버 오류가 발생했어요.");
  await expect(dialog.getByRole("combobox", { name: "제외 사유 (필수)" })).toContainText("현재 검토 범위와 맞지 않음");
  await expect(dialog.getByRole("textbox", { name: /^담당자/ })).toHaveValue("검증 담당자");
  expect(requests).toHaveLength(1);
  await saveExclusion(dialog).click();
  await expect(dialog).not.toBeVisible();
  await expect(row(page, 992)).toHaveCount(0);
  await expect(row(page, 993)).toBeFocused();
  // 2026-11-20: 고른 것이 0건이면 일괄 바를 그리지 않는다(발주계획과 같은 규칙). 0건은 바가 없는 것으로 확인한다.
  await expect(page.locator('.pre-specs-selection-toolbar')).toContainText("선택 0건");
  expect(requests).toHaveLength(2);
  await page.getByRole("button", { name: "검토 제외", exact: true }).click();
  const second = await fillDialog(page);
  await saveExclusion(second).click();
  await expect(row(page, 991)).toBeFocused();
});

// 2026-09-23 운영 결함: 헤더 없이 보내면 FastAPI가 본문을 JSON으로 읽지 않아 422가 났다.
test("검토 제외 요청은 JSON 형식 헤더와 고른 사유 문장·기억한 담당자로 보낸다", async ({ page }) => {
  const { requests, contentTypes } = await setup(page);
  await page.goto("/pre-specs");
  await row(page, 991).getByRole("checkbox").check();
  // 창만의 기억값 채우기를 본다. 목록의 추적 결정 줄이 이미 그려진 뒤에 기억값을 넣어
  // 그 줄의 미저장 판정(다른 작업 범위)이 이 검사에 섞이지 않게 한다.
  await page.evaluate(() => window.localStorage.setItem("bidops.actorName", "기억된 담당자"));
  await page.getByRole("button", { name: "검토 목록에서 제외", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: EXCLUDE_DIALOG, exact: true });
  await expect(dialog.getByRole("textbox", { name: /^담당자/ })).toHaveValue("기억된 담당자");
  await expect(saveExclusion(dialog)).toBeDisabled();
  await expect(dialog).toContainText("제외 사유를 선택해 주세요.");
  await dialog.getByRole("combobox", { name: "제외 사유 (필수)" }).click();
  await page.getByRole("option", { name: "기타 · 직접 입력", exact: true }).click();
  await dialog.getByRole("textbox", { name: "사유 직접 입력" }).fill("  타 부서 소관  ");
  await saveExclusion(dialog).click();
  await expect(dialog).not.toBeVisible();
  expect(contentTypes).toEqual(["application/json"]);
  expect(requests[0]).toEqual({ notice_ids: [991], status: "excluded", actor_name: "기억된 담당자", reason: "타 부서 소관" });
});

test("페이지를 넘는 선택 제외와 마지막 빈 페이지 보정", async ({ page }) => {
  const { requests } = await setup(page, 201);
  await page.goto('/pre-specs');
  await row(page, 991).getByRole('checkbox').check();
  await page.getByRole('navigation', { name: '사전규격 목록 페이지' }).getByRole('button', { name: '다음', exact: true }).click();
  await row(page, 1191).getByRole('checkbox').check();
  await page.getByRole('button', { name: '검토 목록에서 제외', exact: true }).click();
  const dialog = await fillDialog(page);
  await expect(dialog).toContainText('제외 2건');
  await expect(saveExclusion(dialog)).toHaveText('2건 검토 제외');
  await saveExclusion(dialog).click();
  await expect(page).not.toHaveURL(/offset=/);
  await expect(row(page, 1190)).toBeFocused();
  expect(requests[0].notice_ids).toEqual([991, 1191]);
  // 2026-11-20: 고른 것이 0건이면 일괄 바를 그리지 않는다(발주계획과 같은 규칙). 0건은 바가 없는 것으로 확인한다.
  await expect(page.locator('.pre-specs-selection-toolbar')).toContainText("선택 0건");
});

test("200건 초과 선택은 전송을 막고 선택 축소를 안내", async ({ page }) => {
  const { requests } = await setup(page, 201);
  await page.goto('/pre-specs');
  await page.getByRole('button', { name: '현재 페이지 전체 선택' }).click();
  await page.getByRole('navigation', { name: '사전규격 목록 페이지' }).getByRole('button', { name: '다음', exact: true }).click();
  await row(page, 1191).getByRole('checkbox').check();
  await expect(page.getByRole('button', { name: '검토 목록에서 제외' })).toBeDisabled();
  await expect(page.getByText('한 번에 200건까지 일괄 처리할 수 있어요. 선택을 줄여 주세요.')).toBeVisible();
  expect(requests).toHaveLength(0);
});

test("전체 이력 제외 필터·단건 복원·URL 초기화·상세 표식", async ({ page }) => {
  const state = await setup(page);
  state.items[0].review_exclusion_status = 'excluded';
  await page.goto('/pre-specs?workspace=all&review_exclusion=excluded');
  await expect(row(page, 991)).toContainText('검토 제외');
  await expect(row(page, 992)).toHaveCount(0);
  await page.getByRole('link', { name: '상세 페이지 열기 →' }).click();
  const exclusion = page.locator('.workbench-record-main .ps-exclusion-line');
  await expect(exclusion.getByText('검토 제외', { exact: true })).toBeVisible();
  await expect(exclusion.getByText('제외 기록', { exact: true })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/review_exclusion=excluded/);
  await page.getByRole('button', { name: '검토 목록으로 복원', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: RESTORE_DIALOG, exact: true });
  await dialog.getByRole('textbox', { name: /^담당자/ }).fill('검증 담당자');
  // 복원은 제외 선택지가 맞지 않아 자유 입력만 받는다.
  await expect(dialog.getByRole('combobox')).toHaveCount(0);
  await dialog.getByRole('textbox', { name: '복원 사유 (필수)' }).fill('다시 검토');
  await dialog.getByRole('button', { name: '1건 검토 목록으로 복원', exact: true }).click();
  await expect(row(page, 991)).toHaveCount(0);
  expect(state.requests[0].status).toBe('included');
  await page.getByRole('button', { name: /검토할 항목/ }).click();
  await expect(page).not.toHaveURL(/review_exclusion=/);
  await expect(row(page, 991)).toBeVisible();
});

test("사전규격 미리보기는 추적 사유를 받지 않고 검토 제외 창을 바로 연다", async ({ page }) => {
  const { requests } = await setup(page);
  await page.goto('/pre-specs');
  const preview = page.locator('.pre-specs-detail');
  const start = preview.getByRole('button', { name: '추적 시작하기', exact: true });
  await expect(start).toBeDisabled();
  await preview.getByRole('button', { name: '담당자 이름 입력', exact: true }).click();
  await page.locator('#sidebar-actor-input').fill('검증 담당자');
  await page.locator('.sidebar-actor-done').click();
  await expect(start).toBeEnabled();
  await expect(preview.getByRole('combobox', { name: /사유/ })).toHaveCount(0);
  await expect(preview.getByRole('textbox', { name: /사유/ })).toHaveCount(0);

  await preview.getByRole('button', { name: '검토 제외', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: EXCLUDE_DIALOG, exact: true });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  expect(requests).toHaveLength(0);
  await dialog.getByRole('button', { name: '취소', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(requests).toHaveLength(0);
});


test("페이지 마지막 활성 행 제외 시 다음 페이지에서 채워진 다음 행으로 이동", async ({ page }) => {
  await setup(page, 201);
  await page.goto('/pre-specs');
  await row(page, 1190).click();
  await page.getByRole('button', { name: '검토 제외', exact: true }).click();
  const dialog = await fillDialog(page);
  await saveExclusion(dialog).click();
  await expect(row(page, 1191)).toBeFocused();
});


test("전체 이력 포함 여부 필터는 URL과 선택 범위를 함께 갱신", async ({ page }) => {
  const state = await setup(page);
  state.items[0].review_exclusion_status = 'excluded';
  await page.goto('/pre-specs?workspace=all');
  await row(page, 992).getByRole('checkbox').check();
  await page.getByRole('button', { name: '상세 필터', exact: true }).click();
  const filters = page.getByRole('region', { name: '상세 필터', exact: true });
  await filters.getByRole('combobox', { name: '검토 포함 여부', exact: true }).click();
  await page.getByRole('option', { name: '검토 제외', exact: true }).click();
  await expect(page).toHaveURL(/review_exclusion=excluded/);
  await expect(row(page, 991)).toBeVisible();
  await expect(row(page, 992)).toHaveCount(0);
  // 2026-11-20: 고른 것이 0건이면 일괄 바를 그리지 않는다(발주계획과 같은 규칙). 0건은 바가 없는 것으로 확인한다.
  await expect(page.locator('.pre-specs-selection-toolbar')).toContainText("선택 0건");
});

// F2 · spec §6.2 — 제외된 건은 **누가·언제·왜** 뺐는지 보여야 복원을 판단할 수
// 있다. 값이 없는 항목은 빼고 셋 다 없으면 `사유 미기록`이며, 빈 값을 다른
// 담당자·사유로 바꾸지 않는다. 제외 건은 전체 이력 보기에만 나온다.
test("제외 행은 상태를 보여 주고 미리보기와 상세는 누가·언제·왜를 남긴다", async ({ page }) => {
  const state = await setup(page);
  Object.assign(state.items[0], {
    review_exclusion_status: "excluded",
    review_exclusion_actor_name: "검증 담당자",
    review_exclusion_reason: "타 부서 소관",
    review_exclusion_changed_at: "2026-09-21T02:30:00+09:00",
  });
  // 같은 제외지만 기록이 없는 건. 없음을 다른 사유로 채우지 않는다.
  state.items[1].review_exclusion_status = "excluded";

  await page.goto("/pre-specs?workspace=all&review_exclusion=excluded");
  await expect(row(page, 991).locator(".pre-specs-row-state")).toContainText("검토 제외");
  await expect(row(page, 992).locator(".pre-specs-row-state")).toContainText("검토 제외");

  const detailExclusion = page.locator(".pre-specs-detail-exclusion");
  await row(page, 992).locator(".pre-specs-row-title").click();
  await expect(detailExclusion).toContainText("사유 미기록");
  await row(page, 991).locator(".pre-specs-row-title").click();
  await expect(detailExclusion).toContainText("제외 기록");
  await expect(detailExclusion).toContainText("검증 담당자 · 09.21 · 타 부서 소관");

  await page.getByRole("link", { name: "상세 페이지 열기 →" }).click();
  await expect(page.locator(".ps-record-exclusion-note")).toContainText("검증 담당자 · 09.21 · 타 부서 소관");
});

for (const [width, height] of [[1920, 1080], [1440, 900], [1280, 800]]) {
  test(`선택한 공고 일괄 추적 시작 및 미연결 선택 유지 ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await setup(page);
    await page.route("**/api/opportunities/pre-spec-tracking/bulk-start", async route => {
      expect(route.request().postDataJSON()).toEqual({
        notice_ids: [991, 992, 993], actor_name: "검토자",
      });
      await route.fulfill({ json: { items: [
        { notice_id: 991, outcome: "started" }, { notice_id: 992, outcome: "already_decided" },
        { notice_id: 993, outcome: "unavailable" },
      ] } });
    });
    await page.goto("/pre-specs");
    const action = page.getByRole("button", { name: "일괄 추적 시작" });
    await expect(action).toBeDisabled();
    await page.getByRole("button", { name: "현재 페이지 전체 선택" }).click();
    await expect(action).toBeInViewport();
    await action.click();
    const dialog = page.getByRole("dialog", { name: "선택한 사전규격 추적 시작" });
    const save = dialog.getByRole("button", { name: "3건 추적 시작" });
    await expect(save).toBeDisabled();
    await dialog.getByRole("textbox", { name: /^담당자/ }).fill("검토자");
    await expect(dialog.getByRole("combobox")).toHaveCount(0);
    await expect(save).toBeInViewport();
    await save.click();
    await expect(page.getByText("추적 시작 1건 · 기존 결정 유지 1건 · 연결 확인 필요 1건")).toBeVisible();
    await expect(row(page, 993).getByRole("checkbox")).toBeChecked();
    await expect(page.locator(".pre-specs-selection-toolbar")).toContainText("선택 1건");
  });
}
