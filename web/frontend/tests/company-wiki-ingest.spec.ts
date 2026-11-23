import { test, expect, type Page, type Route } from "@playwright/test";
import type { IngestDetail } from "../src/lib/companyWikiIngestApi";
import { mockWiki, project } from "./fixtures/company-wiki";

const id = "12345678-1234-4123-8123-123456789012";
const projectId = "P2025-08";
const portfolio = "/company?view=portfolio&project=" + projectId;
const history = "/company?view=ingests&run=" + id;
const now = "2026-11-23T01:00:00Z";
const review: IngestDetail = {
  id, request_id: id, project_id: projectId, project_title: "기록 관리", source_filename: "원본.pdf",
  status: "awaiting_review", quality_status: "mock_reference", error_code: null, source_size_bytes: 3,
  source_media_type: "application/pdf", requirement_count: 2, created_at: now, updated_at: now,
  unlisted_id_count: 3, units: [{ id: "read", title: "문서 검토", count: 1 }], unassigned_count: 1,
  assignments: [{ req_id: "REQ-01", name: "검토", unit_titles: ["문서 검토"] }, { req_id: "REQ-02", name: "저장", unit_titles: [] }],
  new_units: [], classification_attempts: 1, apply_allowed: true, created_by_name: "이담당",
  decided_by_name: null, decision_reason: null, decided_at: null, applied_at: null,
  wiki_sha256_before: null, wiki_sha256_after: null, backup_name: null,
};
const uploadFile = { name: "원본.pdf", mimeType: "application/pdf", buffer: Buffer.from("PDF") };
function problem(route: Route, status: number, code: string) {
  return route.fulfill({ status, json: { error: { code, message: "fixture", details: null } } });
}
async function setup(page: Page, options: {
  initial?: IngestDetail | null; actor?: string; post?: (route: Route) => Promise<void>;
} = {}) {
  const state = { run: options.initial === undefined ? { ...review } : options.initial };
  if (options.actor !== "") await page.addInitScript(name => localStorage.setItem("bidops.actorName", name), options.actor ?? "이담당");
  await mockWiki(page, { "/portfolio": { items: [{ ...project, id: projectId, title: "기록 관리", has_page: false }] } });
  await page.route(/\/api\/company-wiki\/ingests(?:[/?]|$)/, route => {
    const url = new URL(route.request().url());
    if (route.request().method() === "POST" && options.post) return options.post(route);
    if (route.request().method() !== "GET") throw new Error("예상 밖의 쓰기 요청");
    if (url.pathname.endsWith("/ingests")) {
      expect(url.searchParams.get("limit")).toBe("20");
      expect(url.searchParams.get("offset")).toBe("0");
      return route.fulfill({ json: { items: state.run ? [state.run] : [], total: state.run ? 1 : 0 } });
    }
    expect(url.pathname).toBe("/api/company-wiki/ingests/" + id);
    return state.run ? route.fulfill({ json: state.run }) : problem(route, 404, "not_found");
  });
  return state;
}

async function openUpload(page: Page) {
  await page.goto(portfolio);
  await page.getByRole("button", { name: "실적 넣기", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(projectId);
  await dialog.getByLabel(/제안요청서 파일/).setInputFiles(uploadFile);
  return dialog.getByRole("button", { name: "파일 제출" });
}

function checkActor(route: Route) {
  const headers = route.request().headers();
  expect(headers["x-bidops-actor-name"]).toBe("UTF-8''" + encodeURIComponent("이담당"));
  expect(headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
}

test("같은 요청으로 파일 제출을 재시도하고 선택된 넣기 기록으로 이동해요", async ({ page }) => {
  const keys: string[] = [];
  const state = await setup(page, { initial: null, post: async route => {
    expect(new URL(route.request().url()).pathname).toBe("/api/company-wiki/ingests");
    checkActor(route);
    const headers = route.request().headers();
    expect(headers["content-type"]).toMatch(/^multipart\/form-data; boundary=/);
    const body = route.request().postDataBuffer()?.toString();
    expect(body).toContain('name="project_id"\r\n\r\n' + projectId);
    expect(body).toContain('name="file"; filename="원본.pdf"');
    keys.push(headers["idempotency-key"]);
    if (keys.length === 1) return route.abort();
    state.run = { ...review, status: "queued", requirement_count: null, apply_allowed: false };
    await route.fulfill({ status: 202, json: state.run });
  } });
  const submit = await openUpload(page);
  await submit.click();
  await expect(page.getByRole("dialog").getByRole("alert")).toBeVisible();
  await submit.click();
  await expect(page).toHaveURL(new RegExp("view=ingests&run=" + id + "$"));
  await expect(page.getByRole("link", { name: /기록 관리.*접수됨.*요구사항 수 값 없음/ })).toHaveAttribute("aria-current", "page");
  expect(keys).toEqual([expect.stringMatching(/^[a-f\d]{8}-[a-f\d]{4}-4[a-f\d]{3}-[89ab][a-f\d]{3}-[a-f\d]{12}$/i), keys[0]]);
});

test("진행 상태를 다시 조회하고 사람 확인 뒤 위키 반영 기록을 보여 줘요", async ({ page }) => {
  const state = await setup(page, { initial: { ...review, status: "queued", apply_allowed: false }, post: async route => {
    checkActor(route);
    expect(route.request().url()).toMatch(/\/approve$/);
    expect(route.request().postDataJSON()).toEqual({ expected_status: "awaiting_review" });
    state.run = { ...review, status: "approved", apply_allowed: false };
    await route.fulfill({ json: state.run });
  } });
  await page.goto(history);
  const status = page.locator("main").getByRole("status").filter({ hasText: /^(접수됨|요구사항 추출 중|분류 중|검토 대기|승인됨|반영 중|반영 완료)$/ });
  await expect(status).toHaveText("접수됨");
  for (const [value, label] of [["extracting", "요구사항 추출 중"], ["classifying", "분류 중"], ["awaiting_review", "검토 대기"]] as const) {
    state.run = { ...review, status: value, apply_allowed: value === "awaiting_review" };
    await expect(status).toHaveText(label);
  }
  await expect(page.getByText("mock 참조", { exact: true })).toHaveClass(/badge-neutral/);
  await expect(page.getByText(/근거 지도에 그대로 들어가요/)).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "문서 검토 · 1건" })).toBeVisible();
  await expect(page.getByText(/미분류 건수 · 1/)).toContainText("목록에 없는 번호 수 · 3");
  await expect(page.getByRole("row", { name: "REQ-02 저장 미분류" })).toBeVisible();
  const approve = page.getByRole("button", { name: "위키에 반영", exact: true });
  await approve.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("위키를 고치기 전에 사본을 남겨요.");
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(status).toHaveText("검토 대기");
  await approve.click();
  await dialog.getByRole("button", { name: "반영 확인" }).click();
  await expect(status).toHaveText("승인됨");
  state.run = { ...review, status: "applying", apply_allowed: false };
  await expect(status).toHaveText("반영 중");
  state.run = { ...review, status: "applied", apply_allowed: false, backup_name: "wiki-copy",
    wiki_sha256_before: "1".repeat(64), wiki_sha256_after: "2".repeat(64), applied_at: now };
  await expect(status).toHaveText("반영 완료");
  await expect(page.getByText(/사본 이름 · wiki-copy/)).toContainText("반영 전 · " + "1".repeat(12));
  await expect(page.getByText(/사본 이름 · wiki-copy/)).toContainText("반영 후 · " + "2".repeat(12));
  await expect(page.getByText(/1{13}|2{13}/)).toHaveCount(0);
  await page.getByRole("link", { name: "업무별 근거 지도 보기" }).click();
  await expect(page).toHaveURL(/view=work-units$/);
});

test("참조 반영이 꺼져 있어도 사유를 입력해 반려할 수 있어요", async ({ page }) => {
  const state = await setup(page, { initial: { ...review, apply_allowed: false }, post: async route => {
    checkActor(route);
    expect(route.request().url()).toMatch(/\/reject$/);
    expect(route.request().postDataJSON()).toEqual({ expected_status: "awaiting_review", reason: "근거 부족" });
    state.run = { ...review, apply_allowed: false, status: "rejected", decision_reason: "근거 부족" };
    await route.fulfill({ json: state.run });
  } });
  await page.goto(history);
  await expect(page.getByText(/위키에 반영되지 않아요/)).toBeVisible();
  await expect(page.getByRole("button", { name: "위키에 반영" })).toBeDisabled();
  await page.getByRole("button", { name: "반려", exact: true }).click();
  const confirm = page.getByRole("button", { name: "반려 확인" });
  await page.getByRole("textbox", { name: "반려 사유" }).fill("   ");
  await expect(confirm).toBeDisabled();
  await page.getByRole("textbox", { name: "반려 사유" }).fill(" 근거 부족 ");
  await confirm.click();
  await expect(page.getByText("반려 사유 · 근거 부족")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: /^반려$/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "반려", exact: true })).toHaveCount(0);
});

test("담당자 이름이 비면 사이드바 칸으로 이동해요", async ({ page }) => {
  await setup(page, { actor: "" });
  for (const [url, action] of [[portfolio, "실적 넣기"], [history, "위키에 반영"], [history, "반려"]]) {
    await page.goto(url);
    await page.getByRole("button", { name: action, exact: true }).click();
    await expect(page.getByRole("textbox", { name: "담당자 이름" })).toBeFocused();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
});

test("기능이 꺼지면 기록 주소에서도 실적 보기로 돌아가요", async ({ page }) => {
  await mockWiki(page, { "/ingests": { status: 404, error: { code: "company_wiki_ingest_disabled" } } });
  await page.goto(history);
  await expect(page).toHaveURL(/view=portfolio$/);
  await page.getByRole("link", { name: /^실적 P1 / }).click();
  await expect(page.getByText("실적 넣기는 아직 켜지지 않았어요.")).toBeVisible();
  for (const name of ["넣기 기록", "실적 넣기"]) await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
});

for (const [http, code, copy] of [
  [409, "ingest_in_progress", "진행 중인 실행"], [409, "idempotency_conflict", "다른 입력"],
  [413, "input_size_limit", "크기 제한"], [422, "project_not_registered", "등록된 실적"],
  [422, "unsupported_extension", "HWPX"], [422, "mime_mismatch", "내용과 형식"],
] as const) {
  test(`제출 오류 ${code}의 사유를 안내해요`, async ({ page }) => {
    await setup(page, { post: route => problem(route, http, code) });
    await (await openUpload(page)).click();
    const alert = page.getByRole("dialog").getByRole("alert");
    await expect(alert).toContainText(copy);
    await expect(alert).toContainText(code);
  });
}
for (const [code, copy] of [["status_conflict", "상태가 바뀌었어요"], ["reference_apply_disabled", "반영할 수 없어요"]]) {
  test(`승인 오류 ${code} 뒤 최신 상세를 읽어요`, async ({ page }) => {
    const state = await setup(page, { post: async route => {
      state.run = { ...review, apply_allowed: false, status: code === "status_conflict" ? "rejected" : "awaiting_review" };
      await problem(route, 409, code);
    } });
    await page.goto(history);
    await page.getByRole("button", { name: "위키에 반영" }).click();
    await page.getByRole("button", { name: "반영 확인" }).click();
    const alert = page.getByRole("alert").filter({ hasText: code });
    await expect(alert).toContainText(copy);
    const button = page.getByRole("button", { name: "위키에 반영" });
    if (code === "status_conflict") await expect(button).toHaveCount(0);
    else await expect(button).toBeDisabled();
  });
}
for (const [status, label, code, copy] of [
  ["failed", "실패", "no_requirements", "요구사항을 추출하지 못했어요"],
  ["failed", "실패", "apply_failed", "사본에서 위키를 복구했어요"],
  ["aborted", "중단", "lease_expired", "오래 없어 실행을 중단했어요"],
] as const) {
  test(`종결된 ${label}의 ${code}를 설명해요`, async ({ page }) => {
    await setup(page, { initial: { ...review, status, error_code: code, apply_allowed: false } });
    await page.goto(history);
    await expect(page.getByRole("status").filter({ hasText: new RegExp("^" + label + "$") })).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: code })).toContainText(copy);
    await expect(page.getByRole("button", { name: "위키에 반영" })).toHaveCount(0);
  });
}

test("목록 조회 장애와 빈 기록을 구분해요", async ({ page }) => {
  await mockWiki(page);
  let unavailable = true;
  await page.route(/\/api\/company-wiki\/ingests\?/, route => unavailable
    ? problem(route, 503, "ingest_unavailable") : route.fulfill({ json: { items: [], total: 0 } }));
  await page.goto("/company?view=ingests");
  await expect(page.getByRole("alert").filter({ hasText: "ingest_unavailable" })).toBeVisible();
  await expect(page.getByRole("button", { name: "넣기 기록" })).toBeVisible();
  unavailable = false;
  await page.getByRole("button", { name: "기록 다시 조회" }).click();
  await expect(page.getByText("넣기 기록이 없어요.")).toBeVisible();
});

test("다음 기록과 이전 기록을 서버 페이지로 조회해요", async ({ page }) => {
  await mockWiki(page);
  const rows = Array.from({ length: 21 }, (_, index) => ({
    ...review, id: id.slice(0, -2) + String(index).padStart(2, "0"), project_title: "실적 " + (index + 1),
  }));
  await page.route(/\/api\/company-wiki\/ingests(?:[/?]|$)/, route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/ingests")) {
      const offset = Number(url.searchParams.get("offset"));
      expect(url.searchParams.get("limit")).toBe("20");
      return route.fulfill({ json: { total: rows.length, items: rows.slice(offset, offset + 20) } });
    }
    const run = rows.find(row => url.pathname.endsWith("/" + row.id));
    return route.fulfill({ json: run });
  });
  await page.goto("/company?view=ingests");
  await expect(page.getByRole("heading", { name: "실적 1", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "다음 기록" }).click();
  await expect(page).toHaveURL(/offset=20$/);
  await expect(page.getByRole("heading", { name: "실적 21" })).toBeVisible();
  await page.getByRole("link", { name: "이전 기록" }).click();
  await expect(page.getByRole("heading", { name: "실적 1", exact: true })).toBeVisible();
});
