import { readFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const here = resolve(".");
const frontendRoot = process.env.BIDOPS_FRONTEND_ROOT ?? resolve(here, "../../../web/frontend");
const playwrightUrl = pathToFileURL(resolve(frontendRoot, "node_modules/playwright/index.mjs"));
const { chromium } = await import(playwrightUrl.href);
const boards = JSON.parse(readFileSync(resolve(here, "canvas.json"), "utf8")).artboards;
mkdirSync(resolve(here, "_shots"), { recursive: true });

const browser = await chromium.launch();
for (const b of boards) {
  const name = b.file.replace(".dc.html", "");
  const page = await browser.newPage({ viewport: { width: b.w, height: b.h }, deviceScaleFactor: 1 });
  await page.goto("file://" + resolve(here, "_preview", name + ".html"));
  await page.waitForTimeout(250);
  await page.screenshot({ path: resolve(here, "_shots", name + ".png") });
  await page.close();
  console.log(name, b.w + "x" + b.h);
}
await browser.close();
