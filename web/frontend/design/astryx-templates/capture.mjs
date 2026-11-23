// 시안 앱을 안×화면별로 캡처한다.
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire("/Users/temp/orca/bidops/web/frontend/");
const { chromium } = require("@playwright/test");

const BASE = process.env.MOCK_BASE ?? "http://127.0.0.1:5195";
const OUT = process.argv[2];
const W = Number(process.argv[3] ?? 1440);
const H = Number(process.argv[4] ?? 900);
// 정해진 시안 1(v=a) 위의 보기 방안: base=기준, x=크게 보기, y=훑기 길잡이, z=내 화면 맞춤
const variants = (process.argv[5] ?? "base,x,y,z").split(",");
const scheme = process.env.MOCK_SCHEME === "dark" ? "dark" : "light";
const pages = (process.argv[6] ?? "dashboard,briefing,order-plans,pre-specs,pre-spec-detail,opportunities,opportunity-record,notice-detail,bid-delta,go-no-go,company,criteria,run-status").split(",");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: W, height: H }, locale: "ko-KR", timezoneId: "Asia/Seoul", colorScheme: scheme });
const page = await context.newPage();
const problems = [];
page.on("console", (message) => { if (message.type() === "error") problems.push(`[console] ${message.text().slice(0, 300)}`); });
page.on("pageerror", (error) => problems.push(`[pageerror] ${String(error).slice(0, 300)}`));
for (const variant of variants) {
  for (const name of pages) {
    await page.goto(`${BASE}/?m=${variant}&page=${name}`, { waitUntil: "networkidle" });
    await page.waitForSelector(name === "analysis" ? ".mk-doc" : ".mk-panel", { timeout: 10000 });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(250);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (overflow > 0) problems.push(`[overflow] ${variant}/${name} ${overflow}px`);
    await page.screenshot({ path: `${OUT}/1-${variant}-${name}.png` });
  }
}
console.log(problems.length ? [...new Set(problems)].join("\n") : "no console errors, no horizontal overflow");
await browser.close();
