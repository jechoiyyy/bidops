import { defineConfig, devices } from "@playwright/test";

// ADR-0047: 데스크톱·노트북만 지원한다. 1280px 미만은 가로 스크롤을 허용하고
// 별도 레이아웃을 만들지 않으므로 mobile 390 / tablet 768 project는 없다.
const viewports = {
  laptop: { width: 1280, height: 800 }, // 최소 지원 폭
  desktop: { width: 1440, height: 900 }, // 시안 기준 폭
};

// 화면 검사는 세 층이고 층마다 실패의 뜻이 다르다(`docs/standards.md`).
//
// - 의미·계약: 폭과 무관하다. 한 폭에서만 돌린다. 나머지 spec 전부가 여기다.
// - 구조: 폭에 따라 달라지므로 두 폭에서 돌린다.
// - 픽셀: 기준 이미지 대조. 게이트에서 빠져 있고 `npm run test:pixel`로만 돈다.
//
// 층을 나누기 전에는 모든 spec이 두 폭으로 돌았는데, 폭에 실제로 의존하는 것은
// 아래 두 파일뿐이라 실행 시간의 절반이 같은 검사의 재실행이었다.
const LAYOUT_SPECS = ["**/overflow.spec.ts", "**/design-shell.spec.ts"];
const PIXEL_SPECS = ["**/pixel-screens.spec.ts"];

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "app",
      use: { ...devices["Desktop Chrome"], viewport: viewports.desktop },
      testIgnore: [...LAYOUT_SPECS, ...PIXEL_SPECS],
    },
    {
      name: "layout-laptop",
      use: { ...devices["Desktop Chrome"], viewport: viewports.laptop },
      testMatch: LAYOUT_SPECS,
    },
    {
      name: "layout-desktop",
      use: { ...devices["Desktop Chrome"], viewport: viewports.desktop },
      testMatch: LAYOUT_SPECS,
    },
    {
      name: "pixel",
      use: { ...devices["Desktop Chrome"], viewport: viewports.desktop },
      testMatch: PIXEL_SPECS,
    },
  ],
  webServer: {
    command: "npm run build && npm run preview -- --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
