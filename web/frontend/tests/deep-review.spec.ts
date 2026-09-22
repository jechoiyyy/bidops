import { test, expect } from "@playwright/test";
import { FIXTURE_STRUCTURE_ID, mockApi, mockDeepReviewLifecycle } from "./api-mock";

test.describe("심층 검토 보고서 접근성·반응형 계약", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
  });

  test("키보드 focus, 좁은 화면, 긴 matrix containment", async ({ page }) => {
    await page.goto("/deep-reviews/fixture-review");
    await expect(page.getByRole("heading", { name: "심층 검토 보고서", level: 1 })).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-review-primitive="sticky-decision-header"]')).toBeVisible();
    await page.getByRole("button", { name: /근거/ }).first().focus();
    await expect(page.getByRole("button", { name: /근거/ }).first()).toBeFocused();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(page.locator("table").first()).toBeVisible();
  });

  test("queued→running→complete 동안만 polling하고 완료 뒤 report를 요청한다", async ({ page }) => {
    const trace = await mockDeepReviewLifecycle(page, "polling");
    await page.goto("/deep-reviews/fixture-review");

    await expect(page.getByText("분석 진행 상태를 제한된 간격으로 자동 갱신하고 있습니다.")).toBeVisible();
    await expect(page.getByRole("button", { name: "새 분석 회차로 재시도" })).toHaveCount(0);
    // 폴링은 1초 고정이 아니라 2초에서 시작해 경과에 따라 느려진다. 완주까지의
    // 실제 시간이 늘었으므로 대기 예산도 그만큼 준다.
    await expect(page.getByRole("heading", { name: "시스템 권고" })).toBeVisible({ timeout: 15_000 });

    expect(trace.reviewGets).toBeGreaterThanOrEqual(3);
    expect(trace.reportGets).toBe(1);
    expect(trace.events).toContain("review:queued");
    expect(trace.events).toContain("review:running");
    expect(trace.events).toContain("review:completed");
    expect(trace.events).toContain("report:completed");
    expect(trace.events).not.toContain("report:queued");
    expect(trace.events).not.toContain("report:running");

    const terminalReadCount = trace.reviewGets;
    // 가장 빠른 폴링 간격(2초)보다 길게 기다려야 "멈췄다"가 증명된다.
    await page.waitForTimeout(2_600);
    expect(trace.reviewGets).toBe(terminalReadCount);
    await expect(page.getByText("분석 진행 상태를 제한된 간격으로 자동 갱신하고 있습니다.")).toHaveCount(0);
  });

  test("completed 직후 report 409는 제한 재시도해 준비된 보고서로 복구한다", async ({ page }) => {
    const trace = await mockDeepReviewLifecycle(page, "completed");
    let reportRequests = 0;
    await page.route("**/api/deep-reviews/fixture-review/report", async (route) => {
      reportRequests += 1;
      if (reportRequests === 1) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "review_not_ready", message: "심층 검토가 아직 준비되지 않았습니다", details: null },
            request_id: null,
          }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/deep-reviews/fixture-review");
    await expect(page.getByRole("heading", { name: "시스템 권고" })).toBeVisible({ timeout: 5_000 });
    expect(reportRequests).toBe(2);
    expect(trace.reportGets).toBe(1);
  });

  test("report 409가 제한 재시도 뒤에도 남으면 명시적 재조회로 복구한다", async ({ page }) => {
    await mockDeepReviewLifecycle(page, "completed");
    let reportRequests = 0;
    await page.route("**/api/deep-reviews/fixture-review/report", async (route) => {
      reportRequests += 1;
      if (reportRequests <= 3) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "review_not_ready", message: "심층 검토가 아직 준비되지 않았습니다", details: null },
            request_id: null,
          }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/deep-reviews/fixture-review");
    const refetch = page.getByRole("button", { name: "보고서 다시 조회" });
    await expect(refetch).toBeVisible({ timeout: 5_000 });
    expect(reportRequests).toBe(3);
    await refetch.click();
    await expect(page.getByRole("heading", { name: "시스템 권고" })).toBeVisible();
    expect(reportRequests).toBe(4);
  });

  // 오류 문구는 정책 하나가 정한다(`src/lib/apiErrors.ts`). 화면은 서버 raw
  // message를 옮겨 적지 않고, 안전한 코드만 표식으로 남기며, 다음 행동을 함께
  // 말한다. 404는 지금 할 수 있는 행동이 없으므로 버튼도 없다.
  for (const fixture of [
    { status: 404, code: "not_found", message: "보고서를 찾을 수 없습니다", title: "대상을 찾을 수 없습니다.", hasRecovery: false },
    { status: 500, code: "processing_failed", message: "심층 검토를 완료할 수 없습니다", title: "작업을 완료하지 못했습니다.", hasRecovery: true },
  ]) {
    test(`report ${fixture.status}는 자동 재시도하거나 성공 처리하지 않는다`, async ({ page }) => {
      await mockDeepReviewLifecycle(page, "completed");
      let reportRequests = 0;
      await page.route("**/api/deep-reviews/fixture-review/report", async (route) => {
        reportRequests += 1;
        await route.fulfill({
          status: fixture.status,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: fixture.code, message: fixture.message, details: null },
            request_id: null,
          }),
        });
      });

      await page.goto("/deep-reviews/fixture-review");
      const alert = page.getByRole("alert");
      await expect(alert).toContainText(fixture.title);
      await expect(alert).toContainText(`오류 코드 ${fixture.code}`);
      // 서버 message는 UI 전송 계약이 아니다(docs/security.md).
      await expect(page.getByText(fixture.message)).toHaveCount(0);
      await page.waitForTimeout(1_200);
      expect(reportRequests).toBe(1);
      await expect(page.getByRole("heading", { name: "시스템 권고" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "보고서 다시 조회" }))
        .toHaveCount(fixture.hasRecovery ? 1 : 0);
      // 다음 행동 버튼이 있어도 사람이 누르기 전에는 요청이 나가지 않는다.
      expect(reportRequests).toBe(1);
    });
  }

  // 화면이 아는 안전한 코드는 코드별 한국어 문구를 갖고, 서버 문장은 버린다.
  test("오류 상태는 서버 원문을 내지 않고 다음 행동 버튼을 가진다", async ({ page }) => {
    const secret = "internal detail /srv/bidops/prompt.json";
    await mockDeepReviewLifecycle(page, "completed");
    await page.route("**/api/deep-reviews/fixture-review/report", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "service_unavailable", message: secret, details: null }, request_id: null }),
      });
    });

    await page.goto("/deep-reviews/fixture-review");
    const alert = page.getByRole("alert");
    await expect(alert).toContainText("서비스를 일시적으로 사용할 수 없습니다.");
    await expect(alert).toContainText("잠시 뒤 다시 시도");
    await expect(alert).toContainText("오류 코드 service_unavailable");
    await expect(page.getByText(secret)).toHaveCount(0);
    await expect(alert.getByRole("button", { name: "보고서 다시 조회" })).toBeVisible();
  });

  // 담당자 이름은 화면마다 다시 묻지 않는다. 감사 표식일 뿐 인증이 아니므로
  // 이 브라우저에 남겨도 권한이 생기지 않는다는 사실을 함께 적는다.
  test("담당자 이름은 새로고침 뒤에도 채워진다", async ({ page }) => {
    await mockDeepReviewLifecycle(page, "completed");
    await page.goto("/deep-reviews/fixture-review");

    const actor = page.getByLabel("담당자 이름");
    await actor.fill("기억되는 담당자");
    await expect(page.locator(".deep-review-actor-panel")).toContainText("로그인이나 신원 인증이 아닙니다");

    await page.reload();
    await expect(page.getByLabel("담당자 이름")).toHaveValue("기억되는 담당자");
  });

  // 한 화면 안에서 같은 값을 두 번 묻지 않는다. 재시도·수정본 저장·의견 저장이
  // 모두 이 하나를 쓴다.
  test("담당자 이름 입력은 화면에 하나뿐이고 비활성 사유가 다른 자리를 가리키지 않는다", async ({ page }) => {
    await mockDeepReviewLifecycle(page, "completed");
    await page.goto("/deep-reviews/fixture-review");

    await expect(page.getByLabel("담당자 이름")).toHaveCount(1);
    await expect(page.locator("#deep-review-revision-disabled")).not.toContainText("아래");
    await expect(page.locator(".deep-review-side").getByLabel("담당자 이름")).toHaveCount(0);
  });

  test("failed current attempt만 새 request ID로 한 번 재시도하고 이전 이력을 보존한다", async ({ page }) => {
    const trace = await mockDeepReviewLifecycle(page, "failed");
    await page.goto("/deep-reviews/fixture-review");

    await expect(page.getByRole("heading", { name: "새 분석 회차로 재시도" })).toBeVisible();
    await expect(page.getByText("1회차", { exact: true })).toBeVisible();
    await page.getByLabel("담당자 이름").fill("홍길동");
    await page.getByRole("button", { name: "새 분석 회차로 재시도" }).click();

    await expect(page.getByText("분석 회차 2회를 새로 시작했습니다. 기존 실패 이력은 그대로 남습니다.")).toBeVisible();
    await expect(page.getByText("1회차", { exact: true })).toBeVisible();
    await expect(page.getByText("2회차", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "새 분석 회차로 재시도" })).toHaveCount(0);
    expect(trace.attemptPosts).toHaveLength(1);
    expect(trace.attemptPosts[0].body.request_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(trace.attemptPosts[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
    expect(trace.attemptPosts[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("retry typed 오류의 안전한 code와 다음 행동을 함께 표시한다", async ({ page }) => {
    await mockDeepReviewLifecycle(page, "failed");
    await page.route("**/api/deep-reviews/fixture-review/attempts", async (route) => {
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "active_attempt_exists", message: "이미 실행 중인 attempt가 있습니다", details: null },
          request_id: "fixture-conflict",
        }),
      });
    });
    await page.goto("/deep-reviews/fixture-review");
    await page.getByLabel("담당자 이름").fill("fixture actor");
    await page.getByRole("button", { name: "새 분석 회차로 재시도" }).click();
    const alert = page.getByRole("alert");
    // 코드는 그대로 남기고 문구는 화면이 소유한다. 서버 문장을 옮겨 적지 않는다.
    await expect(alert).toContainText("이미 실행 중인 분석 회차가 있습니다.");
    await expect(alert).toContainText("오류 코드 active_attempt_exists");
    await expect(page.getByText("이미 실행 중인 attempt가 있습니다")).toHaveCount(0);
  });

  test("사전규격 심층검토 의견 초안을 이탈 보호하고 저장 결과를 live feedback으로 알린다", async ({ page }) => {
    const trace = await mockDeepReviewLifecycle(page, "completed");
    await page.goto("/deep-reviews/fixture-review");
    await expect(page.getByRole("heading", { name: "사전규격 심층검토 의견 추가" })).toBeVisible();

    await page.getByLabel("담당자 이름").fill("검토 담당자");
    await page.getByLabel("심층검토 의견 사유").fill("근거 확인 뒤 계속 검토합니다.");
    await expect(page.getByText(/저장되지 않은 심층검토 초안/)).toBeVisible();
    const blocked = await page.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    });
    expect(blocked).toBe(true);

    await page.getByRole("button", { name: "심층검토 의견 추가" }).click();
    // append-only 기록이라 저장 뒤 지울 수 없다. 확인 단계를 거쳐야 요청이 나간다.
    await page.getByRole("alertdialog").getByRole("button", { name: "심층검토 의견 저장 · 보류", exact: true }).click();
    await expect(page.getByText("사전규격 심층검토 의견을 추가했습니다. 이전 기록은 그대로 남습니다.")).toBeVisible();
    await expect(page.getByText(/저장되지 않은 심층검토 초안/)).toHaveCount(0);
    expect(trace.opinionPosts).toHaveLength(1);
    expect(trace.opinionPosts[0].body.reason).toBe("근거 확인 뒤 계속 검토합니다.");
  });

  test("의견·보고서 수정본·근거 draft의 SPA 이탈을 취소하거나 명시적으로 허용한다", async ({ page }) => {
    await mockDeepReviewLifecycle(page, "completed");
    await page.goto("/deep-reviews/fixture-review");
    await expect(page.getByRole("heading", { name: "보고서 수정본 편집" })).toBeVisible();

    await page.getByLabel("절 내용").fill("저장되지 않은 보고서 수정본");
    await page.getByLabel("수정 사유").fill("수정본 이탈 보호 확인");
    await page.getByLabel("사실을 바꾼 근거 식별자 (쉼표 구분)").fill("fixture-evidence-1");
    await page.getByLabel("심층검토 의견 사유").fill("저장되지 않은 의견");

    // 이탈 확인은 브라우저 `window.confirm`이 아니라 화면의 확인 다이얼로그다
    // (`useUnsavedGuard`). 취소하면 초안이 그대로 남고, 명시적으로 허용해야
    // 이동한다.
    // 사이드바는 항상 보인다(ADR-0047: 지원 폭 1280px 이상, 드로어 없음).
    const openDashboard = async () => {
      await page.getByRole("link", { name: "대시보드", exact: true }).click();
    };

    await openDashboard();
    const guard = page.getByRole("alertdialog");
    await expect(guard).toBeVisible();
    await expect(guard).toContainText("저장되지 않은 심층검토 초안이 있습니다.");
    await guard.getByRole("button", { name: "계속 편집", exact: true }).click();
    await expect(page.getByRole("alertdialog")).toHaveCount(0);

    await expect(page).toHaveURL(/\/deep-reviews\/fixture-review$/);
    await expect(page.getByLabel("절 내용")).toHaveValue("저장되지 않은 보고서 수정본");
    await expect(page.getByLabel("사실을 바꾼 근거 식별자 (쉼표 구분)")).toHaveValue("fixture-evidence-1");
    await expect(page.getByLabel("심층검토 의견 사유")).toHaveValue("저장되지 않은 의견");

    await openDashboard();
    const secondGuard = page.getByRole("alertdialog");
    await expect(secondGuard).toContainText("저장되지 않은 심층검토 초안이 있습니다.");
    await secondGuard.getByRole("button", { name: "저장하지 않고 이동", exact: true }).click();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/");
  });
});

// ── PLAN 단계 F 작업 5 ─────────────────────────────────────────────────────

// 상단 카드는 넷이었고 명세 §6.5의 품질 표식이 다섯 번째로 붙었다. 표식은
// 실행이 참조 실행인지 측정 통과인지를 문자로 말하며, 값이 없는 옛 revision은
// `표식 없음`이다.
test("심층 검토 보고서는 상단 카드 5개와 결정 카드 요약 표를 갖는다", async ({ page }) => {
  await mockApi(page);
  await mockDeepReviewLifecycle(page, "completed");
  await page.goto("/deep-reviews/fixture-review");

  const cards = page.locator(".deep-review-summary-card");
  await expect(cards).toHaveCount(5);
  await expect(cards.nth(0)).toContainText("종합 판단");
  await expect(cards.nth(1)).toContainText("검증 결과");
  await expect(cards.nth(2)).toContainText("미확인 사항");
  await expect(cards.nth(3)).toContainText("보고서 수정본");
  await expect(cards.nth(3)).toContainText("추가만 기록");
  await expect(cards.nth(4)).toContainText("품질 표식");
  await expect(cards.nth(4)).toContainText("참조 실행 · 품질 미측정");

  // 계약에 없는 축(참여 준비 상태)을 카드로 채우지 않고 그 사실을 밝힌다.
  await expect(page.locator(".deep-review-summary-note")).toContainText("참여 준비 상태");
  await expect(page.locator(".deep-review-summary-note")).toContainText("보고서 계약에 그 값이 없으므로");

  const table = page.getByRole("table", { name: "결정 카드 요약" });
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader")).toHaveText(["항목", "내용", "근거", "검증"]);
});

// 명세 §6.8이 문서 inventory와 사람 확인 필요 segment를 우측 열에 더한다.
// 문서 사실을 범위 다음에 두고, 편집·이력은 그 뒤로 밀린다.
test("우측 열은 보고서 범위·문서 inventory·수정본 저장·이력 순서로 배치된다", async ({ page }) => {
  await mockApi(page);
  await mockDeepReviewLifecycle(page, "completed");
  await page.goto("/deep-reviews/fixture-review");

  const side = page.locator(".deep-review-side");
  const sections = side.locator(":scope > section, :scope > [data-review-primitive='history-link-rail']");
  await expect(sections).toHaveCount(4);
  await expect(side.getByRole("heading", { name: "보고서 범위", exact: true })).toBeVisible();
  await expect(side.getByRole("heading", { name: "문서 요구사항 inventory와 사람 확인 구간", exact: true })).toBeVisible();
  await expect(side.getByRole("heading", { name: "보고서 수정본 편집", exact: true })).toBeVisible();
  await expect(side.getByRole("heading", { name: "보고서 이력과 연결", exact: true })).toBeVisible();

  // 수정본은 새 기록으로 쌓이며 담당자 이름을 필수로 받는다.
  await expect(side).toContainText("이전 수정본을 덮어쓰지 않으며");
  const save = side.getByRole("button", { name: "새 보고서 수정본 저장", exact: true });
  await expect(save).toBeDisabled();
  await expect(page.locator("#deep-review-revision-disabled")).toContainText("이름을 입력하십시오");

  // 되돌릴 수 없는 결정(사전규격 심층검토 의견)은 본문 열에 남는다.
  await expect(side.getByRole("button", { name: "심층검토 의견 추가", exact: true })).toHaveCount(0);
  await expect(page.locator(".deep-review-report-main").getByRole("button", { name: "심층검토 의견 추가", exact: true })).toHaveCount(1);
});

// segment의 PDF 페이지 링크는 대응표가 준 물리 순번(`page_range`)만 쓴다.
// 대응이 일부뿐이면 그 사실을 문구로 밝히고, 대응이 없으면 페이지를 추정하지
// 않고 미확인으로 남긴다.
test("사람 확인 segment는 대응된 PDF 페이지만 링크하고 미확인은 미확인으로 남긴다", async ({ page }) => {
  await mockApi(page);
  await mockDeepReviewLifecycle(page, "completed");
  await page.goto("/deep-reviews/fixture-review");

  const items = page.locator(".deep-review-segment-list > li");
  await expect(items).toHaveCount(3, { timeout: 10_000 });

  // 구간은 계약 순번(`segment 2`)이 아니라 사람 말 머리로 구분한다. 계약
  // 순번·블록 키·요구사항 ID 나열은 접힌 `기술 정보` 안에 그대로 남는다.
  // mapped · 단일 페이지 — 링크는 그 구조의 native snapshot PDF를 가리킨다.
  const mapped = page.locator('.deep-review-segment-list > li[data-segment-ordinal="2"]');
  const mappedLink = mapped.getByRole("link", { name: "2번째 구간 · PDF 3페이지 열기" });
  await expect(mappedLink).toHaveAttribute("href", `/api/document-structures/${FIXTURE_STRUCTURE_ID}/pdf#page=3`);
  await expect(mappedLink).toHaveText("PDF 3페이지 ↗");
  await expect(mapped).not.toContainText("일부 블록만 대응");

  // partial · 페이지 범위 — 링크는 첫 페이지로 가고 부분 대응을 밝힌다.
  const partial = page.locator('.deep-review-segment-list > li[data-segment-ordinal="3"]');
  const partialLink = partial.getByRole("link", { name: "3번째 구간 · PDF 5~7페이지 열기" });
  await expect(partialLink).toHaveAttribute("href", `/api/document-structures/${FIXTURE_STRUCTURE_ID}/pdf#page=5`);
  await expect(partial).toContainText("일부 블록만 대응");

  // unavailable · 링크 없음. 페이지를 만들어 내지 않는다.
  const unavailable = page.locator('.deep-review-segment-list > li[data-segment-ordinal="4"]');
  await expect(unavailable).toContainText("페이지 미확인");
  await expect(unavailable.getByRole("link")).toHaveCount(0);

  // 접은 곳을 펴면 계약 순번·블록 키·요구사항 ID가 그대로 있다.
  await expect(partial.getByText("fixture-block-partial")).toBeHidden();
  await partial.getByText("기술 정보 · 3번째 구간").click();
  await expect(partial.getByText("fixture-block-partial")).toBeVisible();
  await expect(partial.getByText("segment 3", { exact: true })).toBeVisible();
  await expect(partial.getByText("SFR-5", { exact: true })).toBeVisible();
});

// 심층검토 의견은 append-only라 저장 뒤 지울 수 없다. 클릭 한 번에 나가지 않고
// 확인 단계를 거치며, 취소하면 요청도 초안 손실도 없다.
test("심층검토 의견은 확인 없이는 요청이 나가지 않고 취소하면 초안만 남는다", async ({ page }) => {
  await mockApi(page);
  const trace = await mockDeepReviewLifecycle(page, "completed");
  await page.goto("/deep-reviews/fixture-review");
  await expect(page.getByRole("heading", { name: "사전규격 심층검토 의견 추가" })).toBeVisible();

  await page.getByLabel("담당자 이름").fill("검토 담당자");
  await page.getByLabel("심층검토 의견 사유").fill("근거를 다시 확인한 뒤 보류합니다.");
  await page.getByRole("button", { name: "심층검토 의견 추가" }).click();

  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("되돌릴 수 없습니다");
  await expect(dialog).toContainText("추가만 기록");
  await expect(dialog).toContainText("보류");
  await expect(dialog).toContainText("근거를 다시 확인한 뒤 보류합니다.");
  await expect(dialog).toContainText("검증");
  expect(trace.opinionPosts).toHaveLength(0);

  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(trace.opinionPosts).toHaveLength(0);
  await expect(page.getByLabel("심층검토 의견 사유")).toHaveValue("근거를 다시 확인한 뒤 보류합니다.");

  await page.getByRole("button", { name: "심층검토 의견 추가" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "심층검토 의견 저장 · 보류", exact: true }).click();
  await expect(page.getByText("사전규격 심층검토 의견을 추가했습니다. 이전 기록은 그대로 남습니다.")).toBeVisible();
  expect(trace.opinionPosts).toHaveLength(1);
});

// ── 패키지 R5 · 기술 정보 접기(ADR-0066, spec §3.2) ────────────────────────

// 실패는 사람 말 한 문장이 먼저 말한다. 서버가 정한 코드는 사라지지 않고 같은
// 자리의 접힌 `기술 정보` 안에 전문으로 남는다.
test("실패한 분석은 사람 말 문장을 먼저 보이고 오류 코드는 접힌 기술 정보에 남는다", async ({ page }) => {
  await mockApi(page);
  await mockDeepReviewLifecycle(page, "failed");
  await page.goto("/deep-reviews/fixture-review");

  const preparation = page.locator(".deep-review-preparation");
  await expect(preparation).toContainText("모델 응답이 제한 시간 안에 오지 않아 분석을 마치지 못했습니다.", { timeout: 10_000 });
  // 옛 표기는 화면에서 사라졌다.
  await expect(page.getByText("안전한 오류 코드")).toHaveCount(0);

  const codes = preparation.locator(".deep-review-technical-body");
  await expect(codes).toHaveCount(1);
  await expect(codes).toBeHidden();
  await preparation.getByText("기술 정보 · 오류 코드").click();
  await expect(codes).toBeVisible();
  await expect(codes).toContainText("분석 회차 오류 코드");
  await expect(codes).toContainText("model_timeout");
  await expect(codes).toContainText("요구사항·평가 단계 오류 코드");

  // 회차 이력도 같은 규칙이다 — 문장이 먼저, 코드는 접힌 곳에.
  const history = page.locator(".deep-review-attempt-history");
  await expect(history).toContainText("모델 응답이 제한 시간 안에 오지 않아 분석을 마치지 못했습니다.");
  const historyCodes = history.locator(".deep-review-technical-body");
  await expect(historyCodes).toBeHidden();
  await history.getByText("기술 정보 · 1회차 오류 코드").click();
  await expect(historyCodes).toBeVisible();
  await expect(historyCodes).toContainText("model_timeout");
});

// 화면이 모르는 코드는 다른 사유로 바꾸거나 숨기지 않는다(ADR-0066 결정 3).
test("사전에 없는 오류 코드는 문장 안에 그대로 보인다", async ({ page }) => {
  await mockApi(page);
  await mockDeepReviewLifecycle(page, "failed");
  // 이 테스트에서만 회차 응답의 코드를 사전에 없는 값으로 바꾼다. 나중에 건
  // route가 이긴다.
  const unmappedAttempt = {
    id: "fixture-attempt-1",
    sequence: 1,
    status: "failed",
    started_at: "2026-08-26T00:00:01Z",
    completed_at: "2026-08-26T00:00:11Z",
    last_error_code: "fixture_unmapped_reason",
    stages: [
      { stage: "requirements_and_evaluation", sequence: 1, status: "failed", started_at: "2026-08-26T00:00:01Z", completed_at: "2026-08-26T00:00:11Z", last_error_code: "fixture_unmapped_reason" },
      { stage: "delivery_risk_economics", sequence: 2, status: "queued", started_at: null, completed_at: null, last_error_code: null },
      { stage: "synthesis_and_validation", sequence: 3, status: "queued", started_at: null, completed_at: null, last_error_code: null },
    ],
  };
  await page.route("**/api/deep-reviews/fixture-review", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "fixture-review", notice_id: 1, bundle_id: "fixture-bundle", status: "failed",
        current_attempt: unmappedAttempt, attempts: [unmappedAttempt],
        created_at: "2026-08-26T00:00:00Z", completed_at: null, quality_status: "unmeasured_reference",
      }),
    });
  });
  await page.goto("/deep-reviews/fixture-review");

  const preparation = page.locator(".deep-review-preparation");
  await expect(preparation).toContainText("분석을 마치지 못했습니다 · 코드 fixture_unmapped_reason", { timeout: 10_000 });
  // 실패가 성공·완료로 읽히는 문구로 바뀌지 않는다.
  await expect(preparation).toContainText("실패");
});

// 근거 인용문·쪽·신뢰도는 판단에 쓰는 값이라 밖에 남고, 식별자와 해시는 접힌
// 곳에 전문 그대로 있다 — 8자 축약이나 말줄임을 만들지 않는다.
test("근거 카드는 인용문·쪽·신뢰도를 바로 보이고 SHA-256 전문은 접힌 곳에 둔다", async ({ page }) => {
  await mockApi(page);
  await mockDeepReviewLifecycle(page, "completed");
  await page.goto("/deep-reviews/fixture-review");

  const card = page.locator(".evidence-source-card");
  await expect(card).toBeVisible({ timeout: 10_000 });
  await expect(card.locator("blockquote")).toContainText("synthetic fixture evidence");
  await expect(card).toContainText("1쪽");
  await expect(card).toContainText("근거 신뢰도");
  await expect(card).toContainText("0.990");

  const expectedSha = "a".repeat(64);
  const hash = card.getByText(expectedSha, { exact: true });
  await expect(hash).toHaveCount(1);
  await expect(hash).toBeHidden();
  await card.getByText("기술 정보 · 근거 식별자와 해시").click();
  await expect(hash).toBeVisible();
  // 잘리지 않은 전문이다.
  expect(await hash.textContent()).toBe(expectedSha);
  expect((await hash.textContent())?.length).toBe(64);
  await expect(card.getByText("fixture-evidence-1", { exact: true })).toBeVisible();
  await expect(card.getByText("fixture-document", { exact: true })).toBeVisible();

  // 우측 `보고서 범위`도 같다 — 사람 말 요약은 밖, 버전과 식별자는 접힌 곳에.
  const scope = page.locator(".deep-review-scope-panel");
  await expect(scope).toContainText("공고 1건 · 문서 묶음 1개");
  const policy = scope.getByText("fixture-policy", { exact: true });
  await expect(policy).toBeHidden();
  await scope.getByText("기술 정보 · 정책·회사 프로필 버전").click();
  await expect(policy).toBeVisible();
  await expect(scope.getByText("2026-08-26T00:00:00Z", { exact: true })).toBeVisible();
});

// 지우면 안 되는 경고는 접힘과 무관하게 늘 보인다(ADR-0066 결정 5).
test("품질 표식·범위 주석·검증 요약은 접힘 밖에 그대로 남는다", async ({ page }) => {
  await mockApi(page);
  await mockDeepReviewLifecycle(page, "completed");
  await page.goto("/deep-reviews/fixture-review");

  await expect(page.locator(".deep-review-quality-card")).toContainText("참조 실행 · 품질 미측정", { timeout: 10_000 });
  await expect(page.locator(".deep-review-opinion-quality")).toContainText("참조 실행 · 품질 미측정");
  await expect(page.locator(".deep-review-scope-panel")).toContainText(
    "이 범위 밖의 문서는 보고서에 들어가지 않았습니다. 범위가 좁다는 것을 사실이 없다는 뜻으로 읽지 마십시오.",
  );
  await expect(page.locator(".deep-review-validation-panel")).toContainText("상태: 통과");
  await expect(page.locator(".deep-review-validation-panel")).toContainText("실패 0");
  await expect(page.locator(".deep-review-validation-panel")).toContainText("경고 0");
  const revisionCard = page.locator(".deep-review-summary-card").nth(3);
  await expect(revisionCard).toContainText("1차");
  await expect(revisionCard).toContainText("추가만 기록 · 덮어쓰기 없음");
  await expect(page.locator(".detail-skeleton-rail-history")).toContainText("수정본 1");
});

// 접은 곳을 모두 펴도 지원 폭 두 곳에서 가로로 넘치지 않는다. 전문 해시는
// 잘리지 않고 줄바꿈으로 흐른다.
test("기술 정보를 모두 펴도 1280·1440에서 가로로 넘치지 않는다", async ({ page }) => {
  await mockApi(page);
  await mockDeepReviewLifecycle(page, "completed");
  await page.goto("/deep-reviews/fixture-review");
  await expect(page.locator(".evidence-source-card")).toBeVisible({ timeout: 10_000 });

  await page.evaluate(() => {
    document.querySelectorAll("details.deep-review-technical").forEach((item) => {
      (item as HTMLDetailsElement).open = true;
    });
  });

  for (const width of [1280, 1440]) {
    await page.setViewportSize({ width, height: 800 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${width}px에서 가로 넘침`).toBeLessThanOrEqual(1);
  }
});
