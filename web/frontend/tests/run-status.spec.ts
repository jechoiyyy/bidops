import { expect, test, type Page } from "@playwright/test";
import { DERIVED_RUN_ID, RUN_ID, installRunStatusMock, LONG_TITLE } from "./run-status-fixtures";

/**
 * 실행 상태 화면(수집 실행 · 첨부 확보 · 상시 운영 · 산출물 감사 로그).
 *
 * 승인된 시안 구조로 옮긴 뒤에도 업무 의미가 그대로인지 본다: 미확인과 0의
 * 구분, 회차 상태와 판정 실행 상태의 분리, 조회 범위 명시, 확인 창의 고정 대상과
 * 담당자, 충돌 시 초안 유지, 그리고 기존 파이프라인·포털·스케줄 조작의 보존.
 *
 * 모든 쓰기는 가로챈 mock에만 도달한다. 실제 API·모델 호출은 없다.
 */

const LAPTOP = { width: 1280, height: 800 };
const DESKTOP = { width: 1440, height: 900 };

async function gotoRuns(page: Page, search = ""): Promise<void> {
  await page.goto(`/runs${search}`);
  await expect(page.getByRole("tab", { name: "수집 실행", exact: true })).toHaveAttribute("aria-selected", "true");
}

test.describe("실행 상태", () => {
  test("네 탭이 각자의 경로로 열리고 활성 탭만 무거운 조회를 낸다", async ({ page }) => {
    await installRunStatusMock(page);
    const requested: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/api/")) requested.push(url.pathname);
    });

    await gotoRuns(page);
    await expect(page.getByRole("heading", { name: "전체 후보 판정 실행" })).toBeVisible();
    // 숨은 탭의 조회는 나가지 않는다.
    expect(requested).not.toContain("/api/attachments/queue");
    expect(requested).not.toContain("/api/schedule/settings");

    await page.getByRole("tab", { name: "첨부 확보", exact: true }).click();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/attachments");
    await expect.poll(() => requested.includes("/api/attachments/queue")).toBe(true);

    await page.getByRole("tab", { name: "상시 운영", exact: true }).click();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/operations");
    await expect.poll(() => requested.includes("/api/schedule/settings")).toBe(true);

    await page.getByRole("tab", { name: "산출물 감사 로그", exact: true }).click();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/audit");
    await expect(page.getByRole("heading", { name: "산출물 검증" })).toBeVisible();
  });

  test("탭을 옮겨도 회차와 무관한 쿼리를 잃지 않는다", async ({ page }) => {
    await installRunStatusMock(page);
    await gotoRuns(page, `?run=${encodeURIComponent(RUN_ID)}&from=dashboard`);
    await page.getByRole("tab", { name: "산출물 감사 로그", exact: true }).click();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/audit");
    const params = new URL(page.url()).searchParams;
    expect(params.get("run")).toBe(RUN_ID);
    expect(params.get("from")).toBe("dashboard");
  });

  test("요약 한 줄은 조회한 범위와 현재 실행 건수를 밝힌다", async ({ page }) => {
    await installRunStatusMock(page);
    await gotoRuns(page);
    const summary = page.getByLabel("실행 상태 요약");
    await expect(summary).toContainText("현재 실행");
    await expect(summary).toContainText("1건");
    await expect(summary).toContainText("최근 3건 / 전체 3건");
    await expect(summary).toContainText("범위 밖 미확인");
  });

  test("상시 운영 조회 실패는 꺼짐이 아니라 미확인이다", async ({ page }) => {
    await installRunStatusMock(page, { alwaysOnError: true });
    await gotoRuns(page);
    const summary = page.getByLabel("실행 상태 요약");
    await expect(summary).toContainText("미확인");
    await expect(summary).toContainText("조회 실패 · 꺼짐도 켜짐도 아닙니다");
    await expect(summary).not.toContainText("설정 꺼짐");
  });

  test("경계 사실은 사라지지 않고 운영 조건 대화상자에 남는다", async ({ page }) => {
    await installRunStatusMock(page);
    await gotoRuns(page);
    await page.getByRole("button", { name: "운영 조건" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("운영 텔레메트리는 삭제하지 않았습니다");
    await expect(dialog).toContainText("model_digest");
    await expect(dialog).toContainText("duration_ms");
    await expect(dialog).toContainText("거절 사유");
    await expect(dialog).toContainText("합성 승인 조합 불일치로 상시 운영을 거부했습니다.");
    await expect(dialog).toContainText("startup은 migration·seed·정책 활성화·모델 호출을 수행하지 않습니다");
  });

  test("회차 목록은 회차 상태와 판정 실행 상태를 구분하고 조회 범위를 적는다", async ({ page }) => {
    await installRunStatusMock(page);
    await gotoRuns(page);
    const list = page.getByLabel("실행 회차 목록");
    // 회차 자체 상태와 그 회차에 연결된 판정 실행 상태는 다른 값이다.
    await expect(list).toContainText("회차 완료");
    await expect(list).toContainText("판정 실행 실행 중");
    // 조회 범위 안에 실행 기록이 없는 회차는 없음으로만 말한다.
    await expect(list).toContainText("조회 범위 안 기록 없음");
    await expect(list).toContainText("판정 실행 상태는 최근 3건 조회 범위 기준이며 범위 밖은 미확인입니다");
  });

  test("판정 실행 목록 조회가 실패하면 실행 상태를 0으로 바꾸지 않는다", async ({ page }) => {
    await installRunStatusMock(page, { executionsError: true });
    await gotoRuns(page);
    const list = page.getByLabel("실행 회차 목록");
    await expect(list).toContainText("판정 실행 미확인");
    await expect(page.getByRole("button", { name: "실행 중 미확인" })).toBeVisible();
    await expect(page.getByRole("button", { name: "확인 필요 미확인" })).toBeVisible();
    await expect(list).toContainText("판정 실행 상태는 미확인입니다");
  });

  test("진행률은 실제 건수에서 나오고 상태 값은 서로를 대신하지 않는다", async ({ page }) => {
    await installRunStatusMock(page);
    await gotoRuns(page);
    const progress = page.getByRole("progressbar", { name: "판정 처리 비율" });
    // 후보 40 · 완료 17 · 실패 1 → 처리 18건 = 45%
    await expect(progress).toHaveAttribute("aria-valuenow", "45");
    const detail = page.getByLabel("선택한 실행 회차");
    await expect(detail).toContainText("18 / 40건 처리");
    await expect(detail).toContainText("남은 대상");
    await expect(detail).toContainText("22건");
    await expect(detail).toContainText("처리 완료와 품질 검증은 별도입니다");
  });

  test("원본 회차와 게시된 파생 회차를 구분해 적는다", async ({ page }) => {
    await installRunStatusMock(page);
    await gotoRuns(page);
    const detail = page.getByLabel("선택한 실행 회차");
    await expect(detail).toContainText("원본 회차");
    await expect(detail).toContainText("게시된 파생 회차");
    await expect(detail).toContainText("수집·기존 판정을 덮어쓰지 않습니다");
    // 진행 중 실행에는 게시된 파생 회차가 없다. 없음을 게시로 바꾸지 않는다.
    await expect(detail).toContainText("게시 전이거나 게시하지 않았습니다");
  });

  test("실패 내역은 안전한 식별자·코드만 보여 주고 0건과 미확인을 구분한다", async ({ page }) => {
    await installRunStatusMock(page);
    await gotoRuns(page);
    await page.getByRole("button", { name: /실패 내역/ }).click();
    const detail = page.getByLabel("선택한 실행 회차");
    await expect(detail).toContainText("notice-031");
    await expect(detail).toContainText("모델 출력 잘림");
    // 계약에 없는 공고 제목·발주기관을 만들어 붙이지 않는다.
    await expect(detail).not.toContainText("발주기관");

    await detail.getByRole("button", { name: /notice-031/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("truncated_output");
    await expect(dialog).toContainText("사람 검토 대기");
    await expect(dialog).toContainText("내부 경로·자격증명·원문·전체 프롬프트와 모델 응답 본문은 화면에 표시하지 않습니다");
    // 관측 수치가 없으면 0이 아니라 미측정이다.
    await expect(dialog).toContainText("미측정");
  });

  test("실패 0건인 실행은 0건으로, 목록이 없으면 미확인으로 적는다", async ({ page }) => {
    await installRunStatusMock(page, { successOnly: true });
    await gotoRuns(page);
    await page.getByRole("button", { name: /실패 내역/ }).click();
    await expect(page.getByText("실패한 항목이 없습니다 · 0건")).toBeVisible();
    await expect(page.getByText("실행이 기록한 실패 건수가 실제로 0입니다.")).toBeVisible();
  });

  test("진행 중인 전량 판정이 있으면 새 실행을 시작할 수 없다", async ({ page }) => {
    await installRunStatusMock(page);
    await gotoRuns(page);
    const start = page.getByRole("button", { name: "전량 판정 대기열에 넣기" });
    await expect(start).toBeDisabled();
    await expect(page.getByText("진행 중인 전량 판정 실행이 있어 새 실행을 시작할 수 없습니다.")).toBeVisible();
  });

  test("전량 판정 요청은 정책·프로필·담당자를 고정해 기존 payload로 보낸다", async ({ page }) => {
    const trace = await installRunStatusMock(page, { terminalOnly: true });
    await gotoRuns(page);
    const start = page.getByRole("button", { name: "전량 판정 대기열에 넣기" });
    await expect(start).toBeEnabled();
    await start.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("전량 판정 실행 요청");
    const submit = dialog.getByRole("button", { name: "전량 판정 실행 요청" });
    await expect(submit).toBeDisabled();
    await dialog.getByLabel("담당자 이름 필수").fill("실행 담당자");
    await expect(dialog).toContainText("이 실행의 입력은 요청 시점에 고정됩니다");
    await expect(submit).toBeEnabled();
    await submit.click();

    await expect.poll(() => trace.judgmentPosts.length).toBe(1);
    expect(trace.judgmentPosts[0].runId).toBe(RUN_ID);
    expect(trace.judgmentPosts[0].body).toEqual({
      policy_version: "screening-policy.v1.20260825",
      profile_source: "current",
      requested_by: "실행 담당자",
    });
  });

  test("전량 판정 요청이 충돌하면 창을 닫지 않고 입력을 남긴다", async ({ page }) => {
    const trace = await installRunStatusMock(page, { terminalOnly: true, startConflict: true });
    await gotoRuns(page);
    await page.getByRole("button", { name: "전량 판정 대기열에 넣기" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("담당자 이름 필수").fill("실행 담당자");
    await dialog.getByRole("button", { name: "전량 판정 실행 요청" }).click();

    await expect(dialog.getByRole("alert")).toContainText("판정 실행 요청을 처리하지 못했습니다");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel("담당자 이름 필수")).toHaveValue("실행 담당자");
    expect(trace.judgmentPosts.length).toBe(1);
  });

  test("중단은 대상 실행과 담당자를 확인한 뒤 기존 중단 API로 보낸다", async ({ page }) => {
    const trace = await installRunStatusMock(page);
    await gotoRuns(page);
    await page.getByRole("button", { name: "실행 중단" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("scr-progress");
    await expect(dialog).toContainText("완료");
    await expect(dialog).toContainText("협력적으로 중지합니다");
    const confirm = dialog.getByRole("button", { name: "중지 요청" });
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel("중지 담당자 필수").fill("중지 담당자");
    await expect(confirm).toBeEnabled();
    await confirm.click();

    await expect.poll(() => trace.stopPosts.length).toBe(1);
    expect(trace.stopPosts[0].executionId).toBe("scr-progress");
    expect(trace.stopPosts[0].body).toEqual({ requested_by: "중지 담당자" });
  });

  test("중단이 충돌하면 초안을 유지하고 상태를 되돌리지 않는다", async ({ page }) => {
    const trace = await installRunStatusMock(page, { stopConflict: true });
    await gotoRuns(page);
    await page.getByRole("button", { name: "실행 중단" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("중지 담당자 필수").fill("중지 담당자");
    await dialog.getByRole("button", { name: "중지 요청" }).click();

    await expect(dialog.getByRole("alert")).toContainText("판정 실행 요청을 처리하지 못했습니다");
    await expect(dialog.getByLabel("중지 담당자 필수")).toHaveValue("중지 담당자");
    expect(trace.stopPosts.length).toBe(1);
  });

  test("종결된 실행에는 중단 조작이 없다", async ({ page }) => {
    await installRunStatusMock(page, { terminalOnly: true });
    await gotoRuns(page);
    await expect(page.getByRole("button", { name: "실행 중단" })).toHaveCount(0);
  });

  test("기존 파이프라인 조작이 모두 남아 있고 payload가 같다", async ({ page }) => {
    const trace = await installRunStatusMock(page);
    await gotoRuns(page);
    await page.getByRole("button", { name: "파이프라인 실행" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("원문 재분류");
    await expect(dialog).toContainText("scripts/collect.py");
    await expect(dialog.getByRole("button", { name: "표본 선정 실행" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "보고 생성 실행" })).toBeVisible();
    // 판정 단계는 실행 버튼이 아니라 판정 실행으로만 진행한다.
    await expect(dialog).toContainText("이 단계는 판정 실행으로만 진행합니다");

    await dialog.getByRole("button", { name: "원문 재분류 실행" }).click();
    await expect.poll(() => trace.pipelinePosts.length).toBe(1);
    expect(trace.pipelinePosts[0].stage).toBe("collect");
    expect(trace.pipelinePosts[0].search).toContain("from_raw=true");
    expect(trace.pipelinePosts[0].body).toEqual({ from_raw: true });

    await page.getByRole("button", { name: "파이프라인 실행" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "새 회차 수집" }).click();
    await expect.poll(() => trace.pipelinePosts.length).toBe(2);
    expect(trace.pipelinePosts[1].stage).toBe("collect");
    expect(trace.pipelinePosts[1].body).toEqual({ from_raw: false });
  });

  test("행마다 실행 상세를 조회하지 않는다", async ({ page }) => {
    const trace = await installRunStatusMock(page);
    await gotoRuns(page);
    await expect(page.getByRole("heading", { name: "전체 후보 판정 실행" })).toBeVisible();
    await page.waitForTimeout(500);
    // 고른 실행 하나만 상세를 조회한다.
    expect(new Set(trace.executionDetailGets).size).toBeLessThanOrEqual(1);
  });

  test("실행 기준 탭은 고정 입력과 관측 위치를 남긴다", async ({ page }) => {
    await installRunStatusMock(page);
    await gotoRuns(page);
    await page.getByRole("button", { name: "실행 기준" }).click();
    const detail = page.getByLabel("선택한 실행 회차");
    await expect(detail).toContainText("screening-policy.v1.20260825");
    await expect(detail).toContainText("sha256:합성모델");
    await expect(detail).toContainText("현재 판정 기준이 바뀌어도 이미 시작한 실행에 소급 적용하지 않습니다");

    await page.getByRole("button", { name: "실행 기록" }).click();
    await expect(detail).toContainText("model_digest · token 수 · duration_ms는 판정 화면의 기본 표시에서 뺐을 뿐 삭제하지 않았습니다");
  });

  // ── 첨부 확보 ──────────────────────────────────────────────────────────
  test("첨부 확보는 실제 미확보 사유만 적고 문서 종류를 추정하지 않는다", async ({ page }) => {
    await installRunStatusMock(page);
    await page.goto("/attachments");
    const detail = page.getByLabel("확인할 공고");
    await expect(detail).toContainText("등록된 첨부가 없습니다");
    await expect(detail).toContainText("미확보 문서의 종류는 확인되지 않았습니다");
    await expect(detail).not.toContainText("제안요청서 미확인");
    await expect(detail).toContainText("첨부가 없다는 사실만으로 공고의 적합성 등급이나 참여 준비 상태를 낮추지 않습니다");
    await expect(detail).toContainText("검토 권장");
    await expect(detail).toContainText("부분 확인 필요");
  });

  test("등록된 포털 0건과 포털 조회 실패를 구분한다", async ({ page }) => {
    await installRunStatusMock(page);
    await page.goto("/attachments");
    await expect(page.getByLabel("확인할 공고")).toContainText("등록된 조달시스템 없음");
    await expect(page.getByLabel("첨부 미확보 목록")).toContainText("등록된 포털 1개");

    await installRunStatusMock(page, { portalsError: true });
    await page.goto("/attachments");
    await expect(page.getByLabel("확인할 공고")).toContainText("포털 조회 실패 · 미확인");
    await expect(page.getByLabel("첨부 미확보 목록")).toContainText("등록된 포털은 조회 실패로 미확인");
  });

  test("승인된 검색 주소만 열고 등록·수정 전체 양식을 유지한다", async ({ page }) => {
    const trace = await installRunStatusMock(page);
    await page.goto("/attachments");
    await page.getByLabel("첨부 미확보 목록").getByRole("button", { name: /합성 공고 76/ }).click();
    const link = page.getByLabel("확인할 공고").getByRole("link", { name: "기관 검색 주소 열기" });
    await expect(link).toHaveAttribute("href", "https://example.invalid/?q=202676");

    await page.getByRole("button", { name: "기관 포털 관리" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("기관 매칭 문자열 필수").fill("합성기관 99");
    await dialog.getByLabel("조달시스템 이름 필수").fill("합성 조달시스템 99");
    await dialog.getByLabel("검색 주소 템플릿 필수").fill("https://example.invalid/?q={bid_no}");
    await dialog.getByLabel("담당자 이름 필수").fill("포털 담당자");
    await dialog.getByRole("button", { name: "기관 등록" }).click();

    await expect.poll(() => trace.portalPosts.length).toBe(1);
    expect(trace.portalPosts[0].body).toEqual({
      agency_pattern: "합성기관 99",
      system_name: "합성 조달시스템 99",
      search_url_template: "https://example.invalid/?q={bid_no}",
      enabled: true,
      note: null,
    });
    expect(trace.portalPosts[0].headers["x-bidops-actor-name"]).toBeTruthy();
  });

  test("첨부 확보 큐 조회 실패를 미확보 0건으로 바꾸지 않는다", async ({ page }) => {
    await installRunStatusMock(page, { attachmentQueueError: true });
    await page.goto("/attachments");
    await expect(page.getByText("첨부 확보 큐를 불러오지 못했습니다.")).toBeVisible();
    await expect(page.getByText("조회 실패는 미확보 0건이 아닙니다.")).toBeVisible();

    await installRunStatusMock(page, { emptyAttachmentQueue: true });
    await page.goto("/attachments");
    await expect(page.getByText("첨부 미확보 공고가 0건입니다.")).toBeVisible();
  });

  // ── 상시 운영 ──────────────────────────────────────────────────────────
  test("상시 운영은 설정값·실제·환경·거절을 구분하고 없는 차단 사유를 만들지 않는다", async ({ page }) => {
    await installRunStatusMock(page);
    await page.goto("/operations");
    const detail = page.getByLabel("선택한 운영 항목");
    await expect(detail).toContainText("설정값");
    await expect(detail).toContainText("실제 운영");
    await expect(detail).toContainText("환경 허용");
    await expect(detail).toContainText("상시 운영이 거부되었습니다.");
    await expect(detail).toContainText("합성 승인 조합 불일치로 상시 운영을 거부했습니다.");
    await expect(page.getByRole("alert", { name: "상시 운영 켜기 차단 사유" })).toContainText("켤 수 없는 상태입니다");
    await expect(page.getByRole("button", { name: "상시 운영 켜기" })).toHaveCount(0);
  });

  test("상시 운영 조회가 실패하면 켜거나 끌 수 없고 상태는 미확인이다", async ({ page }) => {
    await installRunStatusMock(page, { alwaysOnError: true });
    await page.goto("/operations");
    const pane = page.getByLabel("선택한 운영 항목");
    await expect(pane.getByText("상시 운영 상태를 불러오지 못했습니다")).toBeVisible();
    await expect(pane).toContainText("꺼져 있다는 뜻도 켜져 있다는 뜻도 아닙니다");
    await expect(page.getByRole("button", { name: "상시 운영 켜기" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "상시 운영 끄기" })).toHaveCount(0);
  });

  test("켜기는 담당자와 게이트 결과 ID를 확인 창에서 다시 확인한다", async ({ page }) => {
    const trace = await installRunStatusMock(page, { activationReady: true });
    await page.goto("/operations");
    const trigger = page.getByRole("button", { name: "상시 운영 켜기" });
    await expect(trigger).toBeVisible();
    await trigger.click();

    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("기존 회차와 산출물은 바뀌지 않지만");
    await expect(dialog.getByRole("button", { name: "상시 운영 켜기" })).toBeDisabled();
    await dialog.getByLabel("변경 담당자").fill("운영 담당자");
    await dialog.getByLabel("게이트 결과 ID 확인").fill("gateeval-11111111111111111111111111111111");
    await dialog.getByRole("button", { name: "상시 운영 켜기" }).click();

    await expect.poll(() => trace.alwaysOnPuts.length).toBe(1);
    expect(trace.alwaysOnPuts[0].body).toEqual({
      enabled: true,
      confirmed_by: "운영 담당자",
      quality_gate_result_id: "gateeval-11111111111111111111111111111111",
    });
  });

  test("스케줄 초안은 저장 전 현재 값에 반영되지 않고 저장이 상시 운영을 켜지 않는다", async ({ page }) => {
    const trace = await installRunStatusMock(page);
    await page.goto("/operations?pane=schedule");
    const detail = page.getByLabel("선택한 운영 항목");
    await expect(detail).toContainText("매일 02:00");

    await page.getByRole("button", { name: "스케줄 수정" }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByLabel("일간 실행 시각 필수").fill("05:30");
    await dialog.getByLabel("변경 담당자 필수").fill("설정 담당자");
    await dialog.getByRole("button", { name: "취소" }).click();
    // 취소는 현재 값을 바꾸지 않는다.
    await expect(detail).toContainText("매일 02:00");
    expect(trace.settingsPatches.length).toBe(0);

    await page.getByRole("button", { name: "스케줄 수정" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("일간 실행 시각 필수")).toHaveValue("02:00");
    await dialog.getByLabel("일간 실행 시각 필수").fill("05:30");
    await dialog.getByLabel("변경 담당자 필수").fill("설정 담당자");
    await expect(dialog).toContainText("예약 시각을 바꿔도 상시 운영은 켜지지 않습니다");
    await dialog.getByRole("button", { name: "설정 저장" }).click();

    await expect.poll(() => trace.settingsPatches.length).toBe(1);
    expect(trace.settingsPatches[0].body).toEqual({
      daily_time: "05:30",
      weekly_time: "06:00",
      prespec_enabled: false,
      updated_by: "설정 담당자",
    });
    // 저장은 상시 운영 스위치를 건드리지 않는다.
    expect(trace.alwaysOnPuts.length).toBe(0);
  });

  test("수동 실행은 상시 운영이 꺼져 있어도 요청할 수 있고 기간 규칙을 지킨다", async ({ page }) => {
    const trace = await installRunStatusMock(page);
    await page.goto("/operations");
    await expect(page.getByLabel("선택한 운영 항목")).toContainText("실제 운영");
    await page.getByRole("button", { name: "수동 실행 예약" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("수동 실행은 상시 운영과 별개입니다");
    await dialog.getByLabel("실행 종류 필수").selectOption("weekly");
    const from = await dialog.getByLabel("기간 시작 필수").inputValue();
    const to = await dialog.getByLabel("기간 종료 필수").inputValue();
    await dialog.getByLabel("요청 담당자 필수").fill("예약 담당자");
    await dialog.getByRole("button", { name: "수동 실행 예약" }).click();

    await expect.poll(() => trace.scheduleExecutionPosts.length).toBe(1);
    expect(trace.scheduleExecutionPosts[0].body).toEqual({
      job_kind: "weekly",
      window_from: from,
      window_to: to,
      recovery_of_execution_id: null,
      requested_by: "예약 담당자",
    });
    // 월요일부터 일요일까지 7일이어야 한다.
    expect(new Date(`${from}T00:00:00Z`).getUTCDay()).toBe(1);
    expect(Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000)).toBe(6);
  });

  test("정기 실행 이력은 값 없음과 실제 0을 구분한다", async ({ page }) => {
    await installRunStatusMock(page);
    await page.goto("/operations?pane=history");
    const detail = page.getByLabel("선택한 운영 항목");
    await expect(detail).toContainText("후보 값 없음");
    await expect(detail).toContainText("실패 0");
    await expect(detail).toContainText("거절되거나 건너뛴 예약을 실행 성공으로 표시하지 않습니다");
  });

  test("복구는 대상 실행을 고정한 채 복구 예약으로 보낸다", async ({ page }) => {
    const trace = await installRunStatusMock(page);
    await page.goto("/operations?pane=history");
    await page.getByRole("button", { name: "복구", exact: true }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("복구 대상 실행");
    await dialog.getByLabel("요청 담당자 필수").fill("복구 담당자");
    await dialog.getByRole("button", { name: "복구 예약" }).click();

    await expect.poll(() => trace.scheduleExecutionPosts.length).toBe(1);
    const payload = trace.scheduleExecutionPosts[0].body as { recovery_of_execution_id: string | null };
    expect(payload.recovery_of_execution_id).toBeTruthy();
  });

  // ── 산출물 감사 로그 ────────────────────────────────────────────────────
  test("산출물 감사는 부분 결과를 최종 결과로 말하지 않는다", async ({ page }) => {
    await installRunStatusMock(page);
    await page.goto("/audit");
    const detail = page.getByLabel("선택한 산출물");
    await expect(detail).toContainText("normalized.json");
    await expect(detail).toContainText("최종 결과 여부는 파일 이름으로 판단하지 않습니다");
    await expect(detail).toContainText("이 회차의 판정 실행이 아직 진행 중입니다");
    await expect(detail).toContainText("완전한 성공 결과로 발행하지 않습니다");
  });

  test("생성 전 산출물은 검증 미확인으로 남고 경고를 0으로 세지 않는다", async ({ page }) => {
    await installRunStatusMock(page);
    await page.goto("/audit");
    const list = page.getByLabel("산출물 목록");
    await expect(list).toContainText("screening-results.json");
    await expect(list).toContainText("미생성");
    await list.getByRole("button", { name: /screening-results.json/ }).click();
    const detail = page.getByLabel("선택한 산출물");
    await expect(detail).toContainText("생성 전");
    await expect(detail).toContainText("생성 전이므로 검증 경고를 셀 수 없습니다");
  });

  test("감사 회차 선택기는 조회 실패와 회차 없음을 구분한다", async ({ page }) => {
    await installRunStatusMock(page, { runsError: true });
    await page.goto("/audit");
    await expect(page.getByText("회차 목록을 불러오지 못했습니다.")).toBeVisible();

    await installRunStatusMock(page, { emptyRuns: true });
    await page.goto("/audit");
    await expect(page.getByText("적재된 회차가 없습니다. 없음을 정상으로 해석하지 않습니다.")).toBeVisible();
  });

  test("실행 기록은 회차 주소를 유지한 채 감사 탭에서도 열린다", async ({ page }) => {
    await installRunStatusMock(page);
    await page.goto(`/audit?run=${encodeURIComponent(RUN_ID)}`);
    await page.getByRole("button", { name: "실행 기록 열기" }).click();
    // 대화상자의 머리에 있는 닫기(X)와 이름이 겹치지 않도록 본문 액션은 `확인`이다.
    const logDialog = page.getByRole("dialog", { name: /실행 기록/ }).first();
    await expect(logDialog).toContainText("파이프라인 실행 기록");
    await logDialog.getByRole("button", { name: "확인", exact: true }).click();

    await page.getByRole("button", { name: "수집 실행 탭에서 보기" }).click();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/runs");
    expect(new URL(page.url()).searchParams.get("run")).toBe(RUN_ID);
  });

  // ── 폭·상태 ────────────────────────────────────────────────────────────
  test("바닥 액션이 두 지원 폭에서 화면 안에 있다", async ({ page }) => {
    await installRunStatusMock(page);
    for (const viewport of [LAPTOP, DESKTOP]) {
      await page.setViewportSize(viewport);
      await gotoRuns(page);
      const footer = page.getByLabel("선택한 실행 회차").locator(".rs-detail-foot");
      await expect(footer).toBeVisible();
      const box = await footer.boundingBox();
      expect(box).not.toBeNull();
      expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(viewport.height + 1);
      await expect(page.getByRole("button", { name: "파이프라인 실행" })).toBeVisible();
    }
  });

  test("긴 한국어 제목이 두 지원 폭에서 가로로 넘치지 않는다", async ({ page }) => {
    await installRunStatusMock(page, { longTitle: true });
    for (const viewport of [LAPTOP, DESKTOP]) {
      await page.setViewportSize(viewport);
      await page.goto("/attachments");
      await expect(page.getByLabel("확인할 공고")).toContainText(LONG_TITLE.slice(0, 12));
      const overflow = await page.evaluate(() => ({
        document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        body: document.body.scrollWidth - document.body.clientWidth,
      }));
      expect(overflow.document).toBeLessThanOrEqual(1);
      expect(overflow.body).toBeLessThanOrEqual(1);
    }
  });

  test("회차가 없거나 상세 조회가 실패해도 화면이 사실만 말한다", async ({ page }) => {
    await installRunStatusMock(page, { emptyRuns: true });
    await gotoRuns(page);
    await expect(page.getByText("적재된 실행 회차가 없습니다.")).toBeVisible();

    await installRunStatusMock(page, { runDetailError: true });
    await gotoRuns(page);
    await expect(page.getByText("회차 상세를 불러오지 못했습니다.")).toBeVisible();
    await expect(page.getByText("조회 실패를 실행 없음으로 읽지 않습니다.")).toBeVisible();
  });

  test("파생 회차 이동은 원본 회차를 지우지 않고 주소만 옮긴다", async ({ page }) => {
    await installRunStatusMock(page, { terminalOnly: true });
    await gotoRuns(page);
    await page.getByRole("button", { name: "파생 회차로 이동" }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get("run")).toBe(DERIVED_RUN_ID);
  });
});
