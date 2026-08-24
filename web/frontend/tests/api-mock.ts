import type { Page } from "@playwright/test";
import fixtures from "./fixtures/api.json" with { type: "json" };

const responses = fixtures as Record<string, unknown>;

/**
 * 갈무리해 둔 응답을 경로 이름으로 되돌려 준다.
 * 조회 문자열은 무시한다. 시각 회귀 테스트는 기본 필터 상태만 찍기 때문이다.
 */
export async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const body = responses[pathname];
    if (body === undefined) {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "고정 응답 없음" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}
