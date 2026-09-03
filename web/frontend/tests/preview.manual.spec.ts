import { test } from "@playwright/test";
import {
  mockApi,
  mockBidDelta,
  mockDocumentPreparationVisual,
  mockOrderPlans,
  mockPreSpecs,
} from "./api-mock";

/**
 * 사람이 직접 화면을 눌러 보기 위한 수동 미리보기 harness다. 자동 검증이
 * 아니므로 BIDOPS_PREVIEW가 없으면 통째로 skip한다 — `npx playwright test`
 * 전체 실행과 CI는 이 파일을 건너뛴다.
 *
 * 백엔드·PostgreSQL·MinIO 없이 시각 회귀와 같은 목 픽스처로 화면을 띄운다.
 * 실제 데이터 흐름까지 확인하려면 docker-compose.t7.yml 스택을 쓴다.
 *
 *   cd web/frontend
 *   BIDOPS_PREVIEW=1 npx playwright test tests/preview.manual.spec.ts \
 *     --headed --project=laptop --grep "발주계획"
 *
 * 브라우저가 열린 채 멈추고 Playwright Inspector의 Resume를 누르면 끝난다.
 * --project는 laptop(1024x768) · desktop(1440x900) · tablet · mobile 중 고른다.
 */
test.skip(!process.env.BIDOPS_PREVIEW, "수동 미리보기 harness (BIDOPS_PREVIEW=1로 실행)");

test.describe.configure({ timeout: 0 });

test("발주계획 C-2 목록과 상세", async ({ page }) => {
  await mockApi(page);
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.pause();
});

test("사전규격 목록 · 개요 검토 상태별 그룹", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  await page.goto("/pre-specs");
  await page.pause();
});

test("사전규격 상세 · 추적 결정 헤더 고정", async ({ page }) => {
  await mockApi(page);
  await mockDocumentPreparationVisual(page, "ready");
  await page.goto("/pre-specs/991");
  await page.pause();
});

test("입찰 변경 비교 · 최종 Go/No-Go", async ({ page }) => {
  await mockApi(page);
  await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed" });
  await page.goto("/opportunities/501/bid-delta?comparison=77777777-7777-4777-8777-777777777777");
  await page.pause();
});

test("대시보드 · 지금 처리할 일 스트립", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await page.pause();
});
