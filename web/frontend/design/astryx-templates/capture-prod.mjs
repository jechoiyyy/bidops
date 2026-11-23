// 운영 웹(127.0.0.1:18788)을 읽기 전용으로 캡처한다. GET 이외의 요청은 모두 차단한다.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
const require = createRequire("/Users/temp/orca/bidops/web/frontend/");
const { chromium } = require("@playwright/test");

const BASE = "http://127.0.0.1:18788";
const OUT = process.argv[2];
const W = Number(process.argv[3] ?? 1440);
const H = Number(process.argv[4] ?? 900);
const ONLY = process.argv[5] ? process.argv[5].split(",") : null;
mkdirSync(OUT, { recursive: true });

const pages = [
  ["dashboard", "/"],
  ["briefing", "/briefing"],
  ["order-plans", "/order-plans"],
  ["pre-specs", "/pre-specs"],
  ["pre-spec-detail", "/pre-specs/4141"],
  ["opportunities", "/opportunities"],
  ["opportunities-selected", "/opportunities?selected=11866"],
  ["opportunity-activity", "/opportunities/11866/activity"],
  ["opportunity-verdict", "/opportunities/11866/verdict"],
  ["opportunity-proposal", "/opportunities/11866/proposal"],
  ["opportunity-documents", "/opportunities/11866/documents"],
  ["opportunity-source", "/opportunities/11866/source"],
  ["opportunity-similar", "/opportunities/11866/similar"],
  ["bid-delta", "/opportunities/11866/bid-delta"],
  ["go-no-go", "/go-no-go"],
  ["company", "/company"],
  ["criteria", "/criteria"],
  ["criteria-profile", "/profile"],
  ["criteria-metrics", "/metrics"],
  ["criteria-quality-gates", "/quality-gates"],
  ["criteria-policies", "/policies"],
  ["criteria-order-plan-policies", "/order-plan-policies"],
  ["run-status", "/run-status"],
  ["run-status-runs", "/runs"],
  ["run-status-attachments", "/attachments"],
  ["run-status-operations", "/operations"],
  ["run-status-audit", "/audit"],
  ["queue", "/queue"],
  ["judgments", "/judgments"],
];

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: W, height: H }, locale: "ko-KR", timezoneId: "Asia/Seoul" });
let blocked = 0;
await context.route("**/*", (route) => {
  const req = route.request();
  if (req.method() !== "GET") { blocked += 1; return route.abort(); }
  return route.continue();
});
const page = await context.newPage();
const report = [];
for (const [name, path] of pages) {
  if (ONLY && !ONLY.includes(name)) continue;
  const entry = { name, path };
  try {
    await page.goto(BASE + path, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => { entry.networkidle = "timeout"; });
    await page.waitForTimeout(1200);
    entry.finalUrl = page.url().replace(BASE, "");
    entry.h1 = await page.locator("h1").first().innerText({ timeout: 2000 }).catch(() => null);
    entry.text = (await page.locator("body").innerText()).replace(/\n{2,}/g, "\n").slice(0, 6000);
    await page.screenshot({ path: `${OUT}/${name}.png` });
  } catch (error) {
    entry.error = String(error).slice(0, 300);
  }
  report.push(entry);
  console.log(name, entry.finalUrl ?? "", entry.error ?? "ok");
}
writeFileSync(`${OUT}/report.json`, JSON.stringify({ blocked, report }, null, 2));
console.log("blocked non-GET:", blocked);
await browser.close();
