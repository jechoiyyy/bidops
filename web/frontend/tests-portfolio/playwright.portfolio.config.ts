import { defineConfig, devices } from "@playwright/test";

// Portfolio verification only: screenshots through the basic-auth gateway (127.0.0.1:14200).
// Credentials come from PF_USER/PF_PASS; nothing here starts a server.
const base = { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:14200", httpCredentials: { username: process.env.PF_USER ?? "", password: process.env.PF_PASS ?? "" } };
export default defineConfig({
  testDir: ".",
  testMatch: "full-cycle.spec.ts",
  outputDir: "/private/tmp/claude-502/-Users-temp-orca-bidops/ad7e67de-9121-4214-8b2d-83422aaa8e69/scratchpad/pw-out",
  reporter: [["line"]],
  timeout: 90_000,
  projects: [
    { name: "1920", use: { ...base, viewport: { width: 1920, height: 1080 } } },
    { name: "1440", use: { ...base, viewport: { width: 1440, height: 900 } } },
    { name: "1280", use: { ...base, viewport: { width: 1280, height: 800 } } },
  ],
});
