import { defineConfig, devices } from "@playwright/test";

// 계획서가 지정한 네 폭이다. theme.css의 전환점 1180 / 900 / 640을 각각 사이에 두고 있다.
// ADR-0046: 데스크톱·노트북만 지원한다. 1280px 미만은 가로 스크롤을 허용하고
// 별도 레이아웃을 만들지 않으므로 mobile 390 / tablet 768 project는 없앴다.
const viewports = {
  laptop: { width: 1280, height: 800 }, // 최소 지원 폭. 구조 검사와 자체 스냅샷
  desktop: { width: 1440, height: 900 }, // 시안 기준 폭. 시안 픽셀 비교
};

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
  projects: Object.entries(viewports).map(([name, viewport]) => ({
    name,
    use: { ...devices["Desktop Chrome"], viewport },
  })),
  webServer: {
    command: "npm run build && npm run preview -- --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
