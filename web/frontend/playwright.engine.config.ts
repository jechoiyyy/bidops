import { defineConfig, devices } from "@playwright/test";
// Explicit isolated backend URL only; never fall back to the operational stack.
const baseURL = process.env.BIDOPS_ENGINE_E2E_URL;
if (!baseURL || !process.env.BIDOPS_ENGINE_E2E_NOTICE_ID) throw new Error("Set isolated BIDOPS_ENGINE_E2E_URL and BIDOPS_ENGINE_E2E_NOTICE_ID");
export default defineConfig({
  testDir: "./tests-real", testMatch: "engine-api.spec.ts", workers: 1, retries: 0,
  reporter: [["list"]], timeout: 90_000,
  use: { ...devices["Desktop Chrome"], baseURL, trace: "retain-on-failure" },
  projects: [
    { name: "engine-laptop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "engine-desktop", use: { viewport: { width: 1440, height: 900 } } },
  ],
});
