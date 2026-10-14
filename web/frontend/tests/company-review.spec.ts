import { expect, test, type Page, type Route } from "@playwright/test";
import { mockApi, mockCompanyWorkspace } from "./api-mock";
import { COMPANY_BY_SLUG, COMPANY_NOTICE_FIXTURES, companyReviewEvidence, reviewIdFor } from "./fixtures/company-demo";

/*
 * DEMO-04 STEP-004 · spec T4(세 상태 추적 저장·409·이탈 취소)와 T5(심층 preview·승인·실행 중 전환).
 *
 * 고정 응답은 `tests/api-mock.ts`의 `mockCompanyWorkspace`이며 실제 백엔드나 모델에 연결하지
 * 않는다. 일부 검사는 서버가 돌려줄 수 있는 오류를 route로 한 번 합성한다. 그런 검사는 이름과
 * 주석에 "합성"이라고 밝히고, 실제 사용자 조작 검사와 섞지 않는다.
 */

type Slug = keyof typeof COMPANY_BY_SLUG;

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DELIVERY_CLAIM_ID = "d797cdbf-520d-5e6d-b903-25f6319844fb";

function companyId(slug: Slug): string {
  return COMPANY_BY_SLUG[slug].company_id;
}

function notice(noticeId: number) {
  const found = COMPANY_NOTICE_FIXTURES.find((entry) => entry.notice_id === noticeId);
  if (!found) throw new Error(`fixture에 없는 공고 ${noticeId}`);
  return found;
}

function detailPath(slug: Slug, noticeId: number): string {
  return `/companies/${companyId(slug)}/pre-specs/${noticeId}`;
}

function reviewId(slug: Slug, noticeId: number): string {
  return reviewIdFor(COMPANY_BY_SLUG[slug], noticeId);
}

function reviewPath(slug: Slug, noticeId: number): string {
  return `/companies/${companyId(slug)}/deep-reviews/${reviewId(slug, noticeId)}`;
}

const companySelect = (page: Page) => page.getByRole("combobox", { name: "데모 회사 선택" });
const tracking = (page: Page) => page.getByTestId("company-tracking");
const request = (page: Page) => page.getByTestId("company-deep-review-request");
const approval = (page: Page) => page.getByRole("region", { name: "외부 전송 승인" });
const approveButton = (page: Page) => page.getByRole("button", { name: "전송 승인하고 심층검토 요청" });

async function installMocks(page: Page) {
  await mockApi(page);
  return mockCompanyWorkspace(page);
}

/** 테스트가 풀어 줄 때까지 다음 한 요청을 붙잡는다. 그 뒤 요청은 그대로 mock으로 간다. */
async function holdNext(page: Page, pattern: RegExp, method: string) {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let seen = false;
  let held = false;
  await page.route(pattern, async (route: Route) => {
    if (route.request().method() !== method || held) { await route.fallback(); return; }
    held = true;
    seen = true;
    await gate;
    await route.fallback();
  });
  return { release: () => release(), seen: () => seen };
}

async function fillTrackingDraft(page: Page, status: "계속 추적" | "보류" | "종료", reason: string, actor: string) {
  await tracking(page).getByRole("radio", { name: status }).check();
  await tracking(page).getByLabel("추적 결정 사유").fill(reason);
  await tracking(page).getByLabel("추적 결정 담당자 이름").fill(actor);
}

// ---------------------------------------------------------------------------
// T4 추적 결정

test("T4: 회사 경로는 계속 추적·보류·종료 세 상태를 저장하고, 서버 성공 뒤에만 그 회사 화면만 바뀐다", async ({ page }) => {
  const trace = await installMocks(page);
  const idA = companyId("demo-public-si");
  await page.goto(detailPath("demo-public-si", 7102));
  const control = tracking(page);
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 미선택");
  // 세 상태만 고른다. 미선택은 저장 선택지가 아니다. 추적은 핏·Go/No-Go가 아니라고 적는다.
  await expect(control.getByRole("radio")).toHaveCount(3);
  for (const name of ["계속 추적", "보류", "종료"]) await expect(control.getByRole("radio", { name })).toBeVisible();
  await expect(control.getByTestId("company-tracking-boundary")).toContainText("회사 핏(적합성) 판정이나 최종 입찰 참여 결정(Go/No-Go)이 아니며");
  const facts = page.locator("main dl.cw-facts [data-tracking-status]");
  await expect(facts).toHaveAttribute("data-tracking-status", "미선택");

  // 1) 계속 추적 — 서버 응답 전에는 현재 값·목록 칸이 그대로다.
  const held = await holdNext(page, /\/api\/companies\/[^/]+\/opportunities\/\d+\/tracking$/, "PATCH");
  await fillTrackingDraft(page, "계속 추적", "행정업무 범위가 맞아 계속 본다", "업무SI 담당");
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  await expect.poll(() => held.seen()).toBe(true);
  await expect(control.getByRole("button", { name: "저장 중…" })).toBeDisabled();
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 미선택");
  await expect(facts).toHaveAttribute("data-tracking-status", "미선택");
  const before = trace.requests.length;
  const firstResponse = page.waitForResponse((response) => response.request().method() === "PATCH");
  held.release();
  expect((await firstResponse).status()).toBe(200);
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 계속 추적 · 업무SI 담당");
  await expect(control.getByTestId("company-tracking-current")).toContainText("기록 1회");
  await expect(facts).toHaveAttribute("data-tracking-status", "계속 추적");
  await expect(control.getByRole("status").filter({ hasText: "계속 추적(으)로 저장했습니다." })).toBeVisible();
  await expect(control.getByLabel("추적 결정 사유")).toHaveValue("");
  // 저장 뒤 다시 읽는 것은 시작한 회사(A)의 자원뿐이다.
  const after = trace.requests.slice(before);
  expect(after.some((entry) => entry === `GET /api/companies/${idA}/pre-specs/7102`)).toBe(true);
  for (const other of ["demo-data-ai", "demo-cloud-si"] as Slug[]) {
    expect(after.filter((entry) => entry.includes(companyId(other)))).toEqual([]);
  }

  // 2) 보류 — 서버 revision(1)을 기대 revision으로 보낸다.
  await fillTrackingDraft(page, "보류", "인력 일정 확인 전까지 보류", "업무SI 담당");
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 보류");
  await expect(control.getByTestId("company-tracking-current")).toContainText("기록 2회");

  // 3) 종료 — 되돌릴 수 없으므로 확인 창을 거친다.
  await fillTrackingDraft(page, "종료", "범위가 달라 추적 종료", "업무SI 담당");
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  const confirm = page.getByRole("alertdialog");
  await expect(confirm).toContainText("추적을 종료합니다");
  await expect(confirm).toContainText("범위가 달라 추적 종료");
  expect(trace.trackingPatches).toHaveLength(2);
  await confirm.getByRole("button", { name: "종료 상태로 저장" }).click();
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 종료");
  await expect(control.getByTestId("company-tracking-current")).toContainText("기록 3회");

  expect(trace.trackingPatches.map((patch) => [patch.companyId, patch.opportunityId, patch.body.tracking_status, patch.body.expected_revision])).toEqual([
    [idA, 8102, "계속 추적", 0],
    [idA, 8102, "보류", 1],
    [idA, 8102, "종료", 2],
  ]);
  const requestIds = trace.trackingPatches.map((patch) => String(patch.body.request_id));
  for (const id of requestIds) expect(id).toMatch(UUID_V4);
  expect(new Set(requestIds).size).toBe(3);

  // 목록도 A만 종료이고, 같은 사업기회의 다른 회사(B) 값은 그대로다.
  await page.getByTestId("company-header").getByRole("link", { name: "사전규격 목록" }).click();
  await expect(page.locator('tr[data-notice-id="7102"] [data-tracking-status]')).toHaveAttribute("data-tracking-status", "종료");
  await companySelect(page).selectOption(companyId("demo-data-ai"));
  await expect(page.getByTestId("company-header").getByTestId("company-name")).toHaveText("데모 데이터AI");
  await expect(page.locator('tr[data-notice-id="7102"] [data-tracking-status]')).toHaveAttribute("data-tracking-status", "계속 추적");
});

test("T4: 같은 저장의 재시도는 같은 request_id, 내용을 바꾸면 새 request_id다", async ({ page }) => {
  const trace = await installMocks(page);
  let aborted = false;
  // 첫 PATCH는 응답 없이 연결이 끊긴 것처럼 끝낸다(mock에 닿지 않는다).
  await page.route(/\/api\/companies\/[^/]+\/opportunities\/\d+\/tracking$/, async (route) => {
    if (route.request().method() === "PATCH" && !aborted) {
      aborted = true;
      trace.trackingPatches.push({ companyId: "network-aborted", opportunityId: 0, body: route.request().postDataJSON(), headers: route.request().headers() });
      await route.abort("failed");
      return;
    }
    await route.fallback();
  });
  await page.goto(detailPath("demo-cloud-si", 7101));
  const control = tracking(page);
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 미선택");
  await fillTrackingDraft(page, "보류", "클라우드 범위 확인 중", "클라우드SI 담당");
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  await expect(control.getByRole("alert")).toContainText("서버에 연결할 수 없습니다.");
  // 입력은 그대로 남는다. 같은 입력의 재시도는 같은 request_id다.
  await expect(control.getByLabel("추적 결정 사유")).toHaveValue("클라우드 범위 확인 중");
  await control.getByRole("button", { name: "다시 저장" }).click();
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 보류");
  expect(trace.trackingPatches).toHaveLength(2);
  expect(trace.trackingPatches[1].body.request_id).toBe(trace.trackingPatches[0].body.request_id);

  // 새 저장 의도는 새 request_id다.
  await fillTrackingDraft(page, "계속 추적", "범위 확인 완료", "클라우드SI 담당");
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 계속 추적");
  expect(trace.trackingPatches).toHaveLength(3);
  expect(trace.trackingPatches[2].body.request_id).not.toBe(trace.trackingPatches[0].body.request_id);
  expect(trace.trackingPatches[2].body.expected_revision).toBe(1);
});

test("T4: 409 version_conflict는 초안을 지우지 않고 서버 최신값을 나란히 보이며, 사람이 최신값 기준으로 다시 준비해야 저장한다", async ({ page }) => {
  const trace = await installMocks(page);
  const idA = companyId("demo-public-si");
  await page.goto(detailPath("demo-public-si", 7102));
  const control = tracking(page);
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 미선택");
  await fillTrackingDraft(page, "보류", "내 초안 사유 · 데이터 인력 확인 후", "업무SI 담당");

  // 다른 담당자가 서버에서 먼저 바꾼다(revision 0 → 1).
  trace.externalTrackingUpdate(idA, 8102, { tracking_status: "계속 추적", reason: "다른 담당자가 먼저 결정", selected_by: "다른 담당" });
  await control.getByRole("button", { name: "추적 결정 저장" }).click();

  const conflict = control.getByTestId("company-tracking-conflict");
  await expect(conflict).toBeVisible();
  await expect(control.getByRole("alert")).toContainText("이 회사의 대상이 그사이 바뀌었습니다.");
  const draft = conflict.getByTestId("company-tracking-conflict-draft");
  const latest = conflict.getByTestId("company-tracking-conflict-latest");
  await expect(draft).toContainText("보류");
  await expect(draft).toContainText("내 초안 사유 · 데이터 인력 확인 후");
  await expect(draft).toContainText("업무SI 담당");
  await expect(draft).toContainText("0회");
  await expect(latest).toContainText("계속 추적");
  await expect(latest).toContainText("다른 담당자가 먼저 결정");
  await expect(latest).toContainText("다른 담당");
  await expect(latest).toContainText("1회");
  // 입력은 자동으로 덮이지 않고, 기준을 바꾸기 전에는 저장할 수 없다.
  await expect(control.getByRole("radio", { name: "보류" })).toBeChecked();
  await expect(control.getByLabel("추적 결정 사유")).toHaveValue("내 초안 사유 · 데이터 인력 확인 후");
  await expect(control.getByRole("button", { name: "추적 결정 저장" })).toBeDisabled();
  await expect(control.locator("#company-tracking-save-disabled")).toContainText("최신값 기준으로 다시 저장 준비");
  expect(trace.trackingPatches).toHaveLength(1);
  expect(trace.trackingPatches[0].body.expected_revision).toBe(0);

  await conflict.getByRole("button", { name: "최신값 기준으로 다시 저장 준비" }).click();
  await expect(control.getByTestId("company-tracking-conflict")).toHaveCount(0);
  await expect(control.getByLabel("추적 결정 사유")).toHaveValue("내 초안 사유 · 데이터 인력 확인 후");
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 보류 · 업무SI 담당");
  await expect(control.getByTestId("company-tracking-current")).toContainText("기록 2회");
  expect(trace.trackingPatches).toHaveLength(2);
  expect(trace.trackingPatches[1].body.expected_revision).toBe(1);
  expect(trace.trackingPatches[1].body.request_id).not.toBe(trace.trackingPatches[0].body.request_id);
});

/*
 * 합성 서버 응답: 화면은 같은 저장 의도에만 request_id를 다시 쓰므로 정상 조작으로는
 * idempotency_conflict가 생기지 않는다. 서버가 "같은 request_id에 다른 body가 이미 저장됨"이라고
 * 답한 상황을 route로 한 번 만들어, 화면이 재전송 충돌로 안내하고 새 저장 의도를 요구하는지 본다.
 */
test("T4 합성 응답: 409 idempotency_conflict는 재전송 충돌로 안내하고 새 저장 요청으로만 다시 보낸다", async ({ page }) => {
  const trace = await installMocks(page);
  const seen: string[] = [];
  await page.route(/\/api\/companies\/[^/]+\/opportunities\/\d+\/tracking$/, async (route) => {
    if (route.request().method() !== "PATCH") { await route.fallback(); return; }
    const body = route.request().postDataJSON() as Record<string, unknown>;
    seen.push(String(body.request_id));
    if (seen.length === 1) {
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "idempotency_conflict", message: "합성", details: null }, request_id: body.request_id }) });
      return;
    }
    await route.fallback();
  });
  await page.goto(detailPath("demo-public-si", 7102));
  const control = tracking(page);
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 미선택");
  await fillTrackingDraft(page, "보류", "재전송 충돌 확인", "업무SI 담당");
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  await expect(control.getByRole("alert")).toContainText("같은 요청 식별자가 다른 요청에 이미 쓰였습니다.");
  await expect(control.getByTestId("company-tracking-resend-conflict")).toContainText("재전송 충돌");
  await expect(control.getByTestId("company-tracking-resend-conflict")).toContainText("새 저장 요청으로 다시 시작");
  await expect(control.getByRole("button", { name: "추적 결정 저장" })).toBeDisabled();
  await expect(control.getByLabel("추적 결정 사유")).toHaveValue("재전송 충돌 확인");

  await control.getByRole("button", { name: "새 저장 요청으로 다시 시작" }).click();
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 보류");
  expect(seen).toHaveLength(2);
  expect(seen[1]).toMatch(UUID_V4);
  expect(seen[1]).not.toBe(seen[0]);
  expect(trace.trackingPatches).toHaveLength(1);
});

test("가짜 서버 계약: 같은 request_id·같은 body는 첫 응답, 다른 body는 409 idempotency_conflict, 오래된 revision은 409 version_conflict", async ({ page }) => {
  await installMocks(page);
  await page.goto(detailPath("demo-cloud-si", 7102));
  await expect(tracking(page).getByTestId("company-tracking-current")).toContainText("현재 미선택");
  const results = await page.evaluate(async (path) => {
    const send = async (body: Record<string, unknown>) => {
      const response = await fetch(path, { method: "PATCH", headers: { "Content-Type": "application/json", "X-BidOps-Actor-Name": "contract-check" }, body: JSON.stringify(body) });
      const json = await response.json();
      return { status: response.status, code: json?.error?.code ?? null, revision: json?.revision ?? null, details: json?.error?.details ?? null };
    };
    const requestId = "6f1f3c1e-9a52-4d1b-8c0e-2b7f4f3a9d10";
    const first = await send({ tracking_status: "보류", reason: "계약 확인", expected_revision: 0, request_id: requestId });
    const replay = await send({ tracking_status: "보류", reason: "계약 확인", expected_revision: 0, request_id: requestId });
    const conflict = await send({ tracking_status: "종료", reason: "계약 확인", expected_revision: 0, request_id: requestId });
    const stale = await send({ tracking_status: "종료", reason: "계약 확인", expected_revision: 0, request_id: "0b9a8f4e-1c2d-4e5f-9a6b-7c8d9e0f1a2b" });
    return { first, replay, conflict, stale };
  }, `/api/companies/${companyId("demo-cloud-si")}/opportunities/8102/tracking`);
  expect(results.first).toMatchObject({ status: 200, revision: 1 });
  expect(results.replay).toMatchObject({ status: 200, revision: 1 });
  expect(results.conflict).toMatchObject({ status: 409, code: "idempotency_conflict" });
  expect(results.stale).toMatchObject({ status: 409, code: "version_conflict", details: { current_revision: 1 } });
});

test("T4: 보고서에서 추적 결정으로 이어지고, 미저장 입력으로 화면을 떠나려 하면 확인하며 취소하면 그대로 남는다", async ({ page }) => {
  const trace = await installMocks(page);
  const idA = companyId("demo-public-si");
  await page.goto(reviewPath("demo-public-si", 7101));
  await expect(page.getByRole("article", { name: "심층검토 보고서 본문" })).toBeVisible();
  const control = tracking(page);
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 계속 추적");
  await control.getByRole("radio", { name: "보류" }).check();
  await control.getByLabel("추적 결정 사유").fill("보고서의 인력 위험 확인 후 보류");

  // 같은 회사 안의 다른 화면으로 떠나기 → 확인 → 머물기
  await page.getByTestId("company-header").getByRole("link", { name: "사전규격 목록" }).click();
  const guard = page.getByRole("alertdialog");
  await expect(guard).toContainText("이 회사의 추적 결정을 저장하지 않았습니다");
  await guard.getByRole("button", { name: "이 회사에 머물기", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${reviewPath("demo-public-si", 7101)}$`));
  await expect(control.getByRole("radio", { name: "보류" })).toBeChecked();
  await expect(control.getByLabel("추적 결정 사유")).toHaveValue("보고서의 인력 위험 확인 후 보류");

  // 다른 회사로 전환 → 확인 → 머물기: 회사·초안이 그대로다.
  await companySelect(page).selectOption(companyId("demo-cloud-si"));
  await page.getByRole("alertdialog").getByRole("button", { name: "이 회사에 머물기", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${reviewPath("demo-public-si", 7101)}$`));
  await expect(companySelect(page)).toHaveValue(idA);
  await expect(control.getByLabel("추적 결정 사유")).toHaveValue("보고서의 인력 위험 확인 후 보류");
  expect(trace.trackingPatches).toEqual([]);

  // 보고서 → 보류 저장
  await control.getByLabel("추적 결정 담당자 이름").fill("업무SI 담당");
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 보류");
  expect(trace.trackingPatches.map((patch) => [patch.companyId, patch.opportunityId, patch.body.tracking_status, patch.body.expected_revision])).toEqual([[idA, 8101, "보류", 1]]);
  // 저장했으므로 떠날 때 묻지 않는다.
  await page.getByTestId("company-header").getByRole("link", { name: "사전규격 목록" }).click();
  await expect(page).toHaveURL(new RegExp(`/companies/${idA}/pre-specs$`));
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// T5 심층 preview·승인

test("T5: 상세와 보고서를 열기만 하면 미리보기·생성·재시도 호출이 0이고 핏 승인 UI가 없다", async ({ page }) => {
  const trace = await installMocks(page);
  const fitApproval = page.getByRole("button", { name: /핏.*(실행|생성|승인|요청)/ });
  for (const [slug, noticeId] of [["demo-public-si", 7101], ["demo-cloud-si", 7102], ["demo-data-ai", 7103]] as Array<[Slug, number]>) {
    await page.goto(detailPath(slug, noticeId));
    await expect(request(page)).toBeVisible();
    await expect(request(page).getByRole("button", { name: "전송 내용 미리보기" })).toBeVisible();
    await expect(approval(page)).toHaveCount(0);
    await expect(fitApproval).toHaveCount(0);
  }
  await page.goto(reviewPath("demo-public-si", 7101));
  await expect(page.getByRole("article", { name: "심층검토 보고서 본문" })).toBeVisible();
  await expect(fitApproval).toHaveCount(0);
  await page.goto(reviewPath("demo-data-ai", 7103));
  await expect(page.getByTestId("company-review-retry")).toBeVisible();
  await expect(approval(page)).toHaveCount(0);
  expect(trace.previewPosts).toEqual([]);
  expect(trace.reviewPosts).toEqual([]);
  expect(trace.attemptPosts).toEqual([]);
});

test("T5: 미리보기 → 승인 상자(회사·가상 표식·모델·품질·범위) → 한 번 승인하면 생성 1회, 보고서는 회사 근거 endpoint로 읽는다", async ({ page }, info) => {
  const trace = await installMocks(page);
  const globalEvidence: string[] = [];
  page.on("request", (entry) => { if (/\/api\/evidence\//.test(entry.url())) globalEvidence.push(entry.url()); });
  const idC = companyId("demo-cloud-si");
  const target = notice(7102);
  await page.goto(detailPath("demo-cloud-si", 7102));
  await expect(page.locator("main [data-review-status]")).toHaveAttribute("data-review-status", "none");
  await request(page).getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");
  await request(page).getByRole("button", { name: "전송 내용 미리보기" }).click();
  const box = approval(page);
  await expect(box.getByTestId("company-approval-company")).toHaveText("전송 대상 회사 · 데모 클라우드SI · 가상회사");
  await expect(box.getByText("gpt-6-luna · high · codex-exec")).toBeVisible();
  await expect(box.getByTestId("company-approval-quality")).toHaveText("품질 표식 · 참조 실행 · 품질 미측정");
  await expect(box.getByTestId("company-approval-verification")).toContainText("원문 대조 · 사용");
  const versions = box.locator('[aria-label="회사 지식 버전"]');
  await expect(versions).toContainText(COMPANY_BY_SLUG["demo-cloud-si"].profile_version_id);
  await expect(versions).toContainText(COMPANY_BY_SLUG["demo-cloud-si"].graph_version_id);
  const scope = box.getByTestId("company-approval-scope");
  await expect(scope).toContainText("notice 7102");
  await expect(scope).toContainText("요구사항2건");
  await expect(scope).toContainText("문서 버전1건");
  await expect(scope).toContainText("재시도 대상없음 · 새 검토");
  await expect(box).toContainText("회사 핏(적합성) 판정 승인이 아닙니다");
  expect(trace.previewPosts).toEqual([{ companyId: idC, noticeId: 7102, body: { bundle_id: target.bundle_id, source_verification_enabled: true } }]);
  expect(trace.reviewPosts).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: info.outputPath("company-approval.png") });

  await approveButton(page).click();
  await expect(page).toHaveURL(new RegExp(`${reviewPath("demo-cloud-si", 7102)}$`));
  expect(trace.reviewPosts).toHaveLength(1);
  const post = trace.reviewPosts[0];
  expect(post.companyId).toBe(idC);
  const body = post.body as Record<string, unknown>;
  expect(Object.keys(body).sort()).toEqual(["bundle_id", "preview_id", "request_id", "source_verification_enabled"]);
  expect(body).toMatchObject({ bundle_id: target.bundle_id, source_verification_enabled: true });
  expect(String(body.request_id)).toMatch(UUID_V4);
  expect(String(body.preview_id)).toMatch(/^[0-9a-f-]{36}$/);
  // 담당자 이름은 감사 표식 헤더로만 간다(인증 아님). 한글은 UTF-8 percent 형식이다.
  expect(post.headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
  expect(decodeURIComponent(post.headers["x-bidops-actor-name"].replace(/^UTF-8''/, ""))).toBe("클라우드SI 담당");

  // 대기 중 보고서는 아직 없다. worker가 완료하면 같은 화면이 회사 보고서를 reader로 그린다.
  await expect(page.getByTestId("company-report-status")).toHaveAttribute("data-review-status", "queued");
  await expect(page.getByTestId("company-report-not-ready")).toContainText("분석이 끝나면 보고서를 표시합니다.");
  trace.setReviewStatus(idC, reviewId("demo-cloud-si", 7102), "completed");
  const reader = page.getByRole("article", { name: "심층검토 보고서 본문" });
  await expect(reader).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("company-report-status")).toHaveAttribute("data-review-status", "completed");
  await reader.locator(`[data-claim-id="${DELIVERY_CLAIM_ID}"]`).getByRole("button", { name: "근거 1 확인" }).click();
  await expect(page.getByRole("complementary", { name: "선택한 원문 근거" }).locator("blockquote")).toHaveText(companyReviewEvidence.quote);
  expect(trace.requests).toContain(`GET /api/companies/${idC}/deep-reviews/${reviewId("demo-cloud-si", 7102)}/evidence/${companyReviewEvidence.evidence_id}`);
  expect(globalEvidence).toEqual([]);
  expect(trace.reviewPosts).toHaveLength(1);
});

test("T5: 승인 버튼을 빠르게 두 번 눌러도 생성 요청은 1회다(사용자 더블클릭)", async ({ page }) => {
  const trace = await installMocks(page);
  const held = await holdNext(page, /\/api\/companies\/[^/]+\/pre-specs\/\d+\/deep-reviews$/, "POST");
  await page.goto(detailPath("demo-cloud-si", 7102));
  await request(page).getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");
  await request(page).getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect(approval(page)).toBeVisible();
  await approveButton(page).dblclick();
  await expect.poll(() => held.seen()).toBe(true);
  await expect(page.getByRole("button", { name: "처리 중" })).toBeDisabled();
  held.release();
  await expect(page).toHaveURL(new RegExp(`${reviewPath("demo-cloud-si", 7102)}$`));
  expect(trace.reviewPosts).toHaveLength(1);
});

/*
 * 합성 이벤트: 같은 task 안에서 click 두 번을 보낸다. React가 버튼을 disabled로 다시 그리기
 * 전이므로 화면의 잠금(ref)만이 두 번째 전송을 막는다. 실제 사용자 조작 검사는 위 더블클릭이다.
 */
test("T5 합성 이벤트: 같은 프레임의 이중 제출도 생성 요청 1회다", async ({ page }) => {
  const trace = await installMocks(page);
  const held = await holdNext(page, /\/api\/companies\/[^/]+\/pre-specs\/\d+\/deep-reviews$/, "POST");
  await page.goto(detailPath("demo-cloud-si", 7102));
  await request(page).getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");
  await request(page).getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect(approval(page)).toBeVisible();
  await page.evaluate(() => {
    const button = Array.from(document.querySelectorAll<HTMLButtonElement>('[aria-label="외부 전송 승인"] button')).find((entry) => entry.textContent?.trim() === "전송 승인하고 심층검토 요청");
    if (!button) throw new Error("승인 버튼을 찾지 못했습니다");
    button.click();
    button.click();
  });
  await expect.poll(() => held.seen()).toBe(true);
  held.release();
  await expect(page).toHaveURL(new RegExp(`${reviewPath("demo-cloud-si", 7102)}$`));
  expect(trace.reviewPosts).toHaveLength(1);
});

test("T5: 미리보기 뒤 원문 대조를 끄면 승인을 폐기하고, 다시 켜도 새 미리보기를 거쳐야 하며 false는 보내지 않는다", async ({ page }) => {
  const trace = await installMocks(page);
  const previewIds: string[] = [];
  page.on("response", async (response) => {
    if (response.request().method() === "POST" && /\/deep-review-previews$/.test(response.url()) && response.ok()) {
      previewIds.push(String(((await response.json()) as Record<string, unknown>).preview_id));
    }
  });
  await page.goto(detailPath("demo-cloud-si", 7102));
  await request(page).getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");
  await request(page).getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect(approval(page)).toBeVisible();

  await request(page).getByRole("checkbox", { name: "원문 인용·숫자 대조" }).uncheck();
  await expect(approval(page)).toHaveCount(0);
  await expect(request(page).getByTestId("company-deep-review-verification-required")).toContainText("이전 미리보기 승인은 폐기했습니다");
  await expect(request(page).getByRole("button", { name: "전송 내용 미리보기" })).toHaveCount(0);

  await request(page).getByRole("checkbox", { name: "원문 인용·숫자 대조" }).check();
  // 다시 켜도 이전 승인은 돌아오지 않는다.
  await expect(approval(page)).toHaveCount(0);
  await expect(approveButton(page)).toHaveCount(0);
  await request(page).getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect(approval(page)).toBeVisible();
  expect(trace.previewPosts).toHaveLength(2);
  expect(trace.previewPosts.map((entry) => (entry.body as Record<string, unknown>).source_verification_enabled)).toEqual([true, true]);

  // 다시 미리보기를 만들면 그 미리보기로만 승인한다.
  await request(page).getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect.poll(() => trace.previewPosts.length).toBe(3);
  await expect(approval(page)).toBeVisible();
  await approveButton(page).click();
  await expect(page).toHaveURL(new RegExp(`${reviewPath("demo-cloud-si", 7102)}$`));
  expect(trace.reviewPosts).toHaveLength(1);
  await expect.poll(() => previewIds.length).toBe(3);
  expect(new Set(previewIds).size).toBe(3);
  expect((trace.reviewPosts[0].body as Record<string, unknown>).preview_id).toBe(previewIds[2]);
});

test("T5: gate 오류와 preview_changed는 회사 오류표로 안내하고, preview_changed는 승인을 폐기해 새 미리보기를 요구한다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto(detailPath("demo-cloud-si", 7102));
  const region = request(page);
  await region.getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");

  trace.setDeepReviewGate({ status: 409, code: "overview_not_completed" });
  await region.getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect(region.getByRole("alert")).toContainText("overview_not_completed: 개요 검토가 아직 완료되지 않았습니다.");
  await expect(approval(page)).toHaveCount(0);
  trace.setDeepReviewGate({ status: 503, code: "luna_disabled" });
  await region.getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect(region.getByRole("alert")).toContainText("luna_disabled: Luna 심층 검토가 비활성입니다.");
  trace.setDeepReviewGate(null);

  await region.getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect(approval(page)).toBeVisible();
  trace.markPreviewChanged();
  await approveButton(page).click();
  await expect(region.getByRole("alert")).toContainText("preview_changed: 미리보기 뒤에 전송 입력이 바뀌었습니다.");
  await expect(approval(page)).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`${detailPath("demo-cloud-si", 7102)}$`));

  await region.getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect(approval(page)).toBeVisible();
  await approveButton(page).click();
  await expect(page).toHaveURL(new RegExp(`${reviewPath("demo-cloud-si", 7102)}$`));
  expect(trace.reviewPosts).toHaveLength(2);
  const [first, second] = trace.reviewPosts.map((entry) => entry.body as Record<string, unknown>);
  expect(second.preview_id).not.toBe(first.preview_id);
  // 승인 의도가 새 미리보기로 바뀌었으므로 request_id도 새로 만든다.
  expect(second.request_id).not.toBe(first.request_id);
});

/*
 * 합성 서버 응답: 화면은 한 미리보기의 승인에 같은 request_id만 쓰므로 정상 조작으로는
 * preview_used가 생기지 않는다(다른 탭·다른 담당자가 먼저 같은 미리보기를 쓴 상황). 그 응답이
 * 왔을 때 승인을 폐기하는지만 본다.
 */
test("T5 합성 응답: 409 preview_used는 승인을 폐기하고 새 미리보기를 요구한다", async ({ page }) => {
  const trace = await installMocks(page);
  let synthesized = false;
  await page.route(/\/api\/companies\/[^/]+\/pre-specs\/\d+\/deep-reviews$/, async (route) => {
    if (route.request().method() === "POST" && !synthesized) {
      synthesized = true;
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "preview_used", message: "합성", details: null }, request_id: null }) });
      return;
    }
    await route.fallback();
  });
  await page.goto(detailPath("demo-cloud-si", 7102));
  await request(page).getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");
  await request(page).getByRole("button", { name: "전송 내용 미리보기" }).click();
  await approveButton(page).click();
  await expect(request(page).getByRole("alert")).toContainText("preview_used: 이미 승인에 쓰인 미리보기입니다.");
  await expect(approval(page)).toHaveCount(0);
  expect(trace.reviewPosts).toEqual([]);
});

test("T5: 생성 요청 중 회사를 바꾸면 응답이 와도 새 회사 화면을 바꾸지 않고, 각 회사의 검토 상태가 섞이지 않는다", async ({ page }) => {
  const trace = await installMocks(page);
  const idA = companyId("demo-public-si");
  const idC = companyId("demo-cloud-si");
  const held = await holdNext(page, /\/api\/companies\/[^/]+\/pre-specs\/\d+\/deep-reviews$/, "POST");
  await page.goto(detailPath("demo-cloud-si", 7102));
  await request(page).getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");
  await request(page).getByRole("button", { name: "전송 내용 미리보기" }).click();
  await approveButton(page).click();
  await expect.poll(() => held.seen()).toBe(true);

  // C의 생성 응답 전에 A로 옮긴다(같은 공고 상세).
  await companySelect(page).selectOption(idA);
  await expect(page).toHaveURL(new RegExp(`${detailPath("demo-public-si", 7102)}$`));
  await expect(page.getByTestId("company-header").getByTestId("company-name")).toHaveText("데모 업무SI");
  const created = page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes(`/api/companies/${idC}/`));
  held.release();
  expect((await created).status()).toBe(202);
  // 응답 뒤에도 A 화면에 머물며 C의 검토를 A에 보여 주지 않는다.
  await page.waitForTimeout(250);
  await expect(page).toHaveURL(new RegExp(`${detailPath("demo-public-si", 7102)}$`));
  await expect(page.locator("main [data-review-status]")).toHaveAttribute("data-review-status", "none");
  await expect(request(page).getByTestId("company-deep-review-existing")).toHaveCount(0);
  await expect(approval(page)).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText(reviewId("demo-cloud-si", 7102));

  // C로 돌아오면 C의 검토가 대기로 보인다.
  await companySelect(page).selectOption(idC);
  await expect(page).toHaveURL(new RegExp(`${detailPath("demo-cloud-si", 7102)}$`));
  await expect(page.locator("main dl.cw-facts [data-review-status]")).toHaveAttribute("data-review-status", "queued");
  await expect(request(page).getByTestId("company-deep-review-existing").getByRole("link", { name: "보고서·분석 회차 보기" })).toHaveAttribute("href", reviewPath("demo-cloud-si", 7102));
  // C의 보고서 화면에서 회사를 바꾸면 A의 목록으로 가고, A에는 C의 검토가 없다.
  await page.goto(reviewPath("demo-cloud-si", 7102));
  await expect(page.getByTestId("company-report-status")).toHaveAttribute("data-review-status", "queued");
  await companySelect(page).selectOption(idA);
  await expect(page).toHaveURL(new RegExp(`/companies/${idA}/pre-specs$`));
  await expect(page.locator('tr[data-notice-id="7102"] [data-review-status]')).toHaveAttribute("data-review-status", "none");
  expect(trace.reviewPosts.map((entry) => entry.companyId)).toEqual([idC]);
});

test("T5: 실패한 회사 검토는 보고서 화면에서 미리보기 후 새 분석 회차를 요청하고, 같은 승인의 재시도는 같은 request_id다", async ({ page }) => {
  const trace = await installMocks(page);
  const idB = companyId("demo-data-ai");
  const failedReviewId = reviewId("demo-data-ai", 7103);
  let aborted = false;
  await page.route(/\/api\/companies\/[^/]+\/deep-reviews\/[^/]+\/attempts$/, async (route) => {
    if (route.request().method() === "POST" && !aborted) {
      aborted = true;
      trace.attemptPosts.push({ companyId: "network-aborted", reviewId: "", body: route.request().postDataJSON(), headers: route.request().headers() });
      await route.abort("failed");
      return;
    }
    await route.fallback();
  });
  await page.goto(reviewPath("demo-data-ai", 7103));
  await expect(page.getByTestId("company-report-status")).toHaveAttribute("data-review-status", "failed");
  await expect(page.getByTestId("company-report-not-ready")).toContainText("아직 완성된 보고서가 없습니다");
  const retry = page.getByTestId("company-review-retry");
  await retry.getByLabel("재시도 담당자 이름").fill("데이터AI 담당");
  await retry.getByRole("button", { name: "전송 내용 미리보기" }).click();
  expect(trace.previewPosts).toEqual([{ companyId: idB, noticeId: 7103, body: { bundle_id: notice(7103).bundle_id, source_verification_enabled: true, review_id: failedReviewId } }]);
  await expect(approval(page).getByTestId("company-approval-scope")).toContainText(`재시도 대상${failedReviewId}`);
  await expect(approval(page).getByTestId("company-approval-company")).toHaveText("전송 대상 회사 · 데모 데이터AI · 가상회사");

  await approveButton(page).click();
  await expect(retry.getByRole("alert")).toContainText("서버에 연결할 수 없습니다.");
  await approveButton(page).click();
  await expect(page.getByTestId("company-report-status")).toHaveAttribute("data-review-status", "queued");
  expect(trace.attemptPosts).toHaveLength(2);
  const [first, second] = trace.attemptPosts.map((entry) => entry.body as Record<string, unknown>);
  expect(second.request_id).toBe(first.request_id);
  expect(second.preview_id).toBe(first.preview_id);
  expect(Object.keys(second).sort()).toEqual(["preview_id", "request_id", "source_verification_enabled"]);
  expect(trace.attemptPosts[1].companyId).toBe(idB);
  await page.getByText("검증·분석 회차 기록").click();
  await expect(page.getByRole("list", { name: "분석 회차 이력" }).getByRole("listitem")).toHaveCount(2);
  expect(trace.reviewPosts).toEqual([]);
});

test("T5: 회사 보고서는 NarrativeReportReader로 그리고 회사·그래프·프로필 버전과 현재 여부를 함께 보인다", async ({ page }, info) => {
  const trace = await installMocks(page);
  const globalReads: string[] = [];
  page.on("request", (entry) => { if (/\/api\/(evidence|deep-reviews)\//.test(entry.url())) globalReads.push(entry.url()); });
  const idA = companyId("demo-public-si");
  await page.goto(reviewPath("demo-public-si", 7101));
  const reader = page.getByRole("article", { name: "심층검토 보고서 본문" });
  await expect(reader).toBeVisible();
  const identity = page.getByTestId("company-report-identity");
  await expect(identity.getByTestId("company-report-company")).toHaveText("데모 업무SI · 가상회사");
  await expect(identity.getByTestId("company-report-profile-version")).toHaveText(COMPANY_BY_SLUG["demo-public-si"].profile_version_id);
  await expect(identity.getByTestId("company-report-graph-version")).toHaveText(COMPANY_BY_SLUG["demo-public-si"].graph_version_id);
  await expect(identity.getByTestId("company-report-current")).toHaveAttribute("data-is-current", "true");
  await expect(identity).toContainText("참조 실행 · 품질 미측정");
  await expect(reader.locator(".narrative-note")).toContainText("최종 입찰 Go/No-Go는 별도 판단입니다.");
  await reader.locator(`[data-claim-id="${DELIVERY_CLAIM_ID}"]`).getByRole("button", { name: "근거 1 확인" }).click();
  await expect(page.getByRole("complementary", { name: "선택한 원문 근거" }).locator("blockquote")).toHaveText(companyReviewEvidence.quote);
  expect(trace.requests).toContain(`GET /api/companies/${idA}/deep-reviews/${reviewId("demo-public-si", 7101)}/report`);
  expect(trace.requests).toContain(`GET /api/companies/${idA}/deep-reviews/${reviewId("demo-public-si", 7101)}/evidence/${companyReviewEvidence.evidence_id}`);
  // 기존 단일회사 보고서·근거 endpoint는 부르지 않는다.
  expect(globalReads).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: info.outputPath("company-report.png") });
});

test("T5: 전송 대상 회사 이름을 확인하기 전(조회 중·실패)에는 승인할 수 없고 이유를 보인다", async ({ page }) => {
  const trace = await installMocks(page);
  const idC = companyId("demo-cloud-si");
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  // 회사 identity 조회(`GET /api/companies/{id}`)를 붙잡는다. 상세·미리보기는 그대로 응답한다.
  await page.route(new RegExp(`/api/companies/${idC}$`), async (route) => {
    await gate;
    await route.fallback();
  });
  await page.goto(detailPath("demo-cloud-si", 7102));
  await request(page).getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");
  await request(page).getByRole("button", { name: "전송 내용 미리보기" }).click();
  const box = approval(page);
  await expect(box.getByTestId("company-approval-company")).toContainText("회사 이름 확인 중");
  await expect(approveButton(page)).toBeDisabled();
  await expect(box.getByRole("alert")).toContainText("전송 대상 회사 정보를 아직 확인하지 못했습니다");
  expect(trace.reviewPosts).toEqual([]);

  release();
  await expect(box.getByTestId("company-approval-company")).toHaveText("전송 대상 회사 · 데모 클라우드SI · 가상회사");
  await expect(box.getByRole("alert")).toHaveCount(0);
  await expect(approveButton(page)).toBeEnabled();
  await approveButton(page).click();
  await expect(page).toHaveURL(new RegExp(`${reviewPath("demo-cloud-si", 7102)}$`));
  expect(trace.reviewPosts).toHaveLength(1);
});

test("T5: 회사 이름 조회가 실패하면 승인 버튼은 계속 막힌다", async ({ page }) => {
  const trace = await installMocks(page);
  const idC = companyId("demo-cloud-si");
  await page.route(new RegExp(`/api/companies/${idC}$`), (route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "processing_failed", message: "합성", details: null }, request_id: null }) }));
  await page.goto(detailPath("demo-cloud-si", 7102));
  await request(page).getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");
  await request(page).getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect(approval(page).getByRole("alert")).toContainText("회사 이름이 확인될 때까지 승인할 수 없습니다");
  await expect(approveButton(page)).toBeDisabled();
  expect(trace.reviewPosts).toEqual([]);
});
