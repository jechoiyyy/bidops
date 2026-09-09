#!/usr/bin/env node

/* Inspect one HWP/HWPX input for the browser Canvas print path.
 *
 * The browser owns the actual page painting because rhwp's Canvas binding
 * uses DOM canvas/image primitives.  This small adapter only produces bounded
 * page geometry metadata; it never writes a page artifact or accepts a URL.
 */

import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const scriptDir = path.dirname(url.fileURLToPath(import.meta.url));

function estimateTextWidth(font, text) {
  const match = String(font ?? "").match(/([0-9.]+)px/);
  const size = match ? Number.parseFloat(match[1]) : 12;
  let width = 0;
  for (const character of String(text ?? "")) {
    const codepoint = character.codePointAt(0) ?? 0;
    width += codepoint >= 0x1100 && codepoint <= 0xffdc ? size : size * 0.55;
  }
  return width;
}

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) return null;
  return process.argv[index + 1];
}

async function main() {
  const inputPath = argument("--input");
  const maxPagesRaw = argument("--max-pages");
  const maxPages = Number.parseInt(maxPagesRaw ?? "0", 10);
  const maxOutputBytesRaw = argument("--max-output-bytes");
  const maxOutputBytes = Number.parseInt(maxOutputBytesRaw ?? "0", 10);
  if (
    !inputPath
    || !Number.isInteger(maxPages)
    || maxPages < 1
    || !Number.isInteger(maxOutputBytes)
    || maxOutputBytes < 1
  ) {
    throw new Error(
      "usage: rhwp_render_canvas.mjs --input <file> --max-pages <n> --max-output-bytes <n>",
    );
  }
  const source = fs.readFileSync(path.resolve(inputPath));
  globalThis.measureTextWidth = estimateTextWidth;
  const rhwp = await import("./rhwp/rhwp.js");
  const wasm = fs.readFileSync(path.join(scriptDir, "rhwp", "rhwp_bg.wasm"));
  await rhwp.default({ module_or_path: wasm });
  const document = new rhwp.HwpDocument(new Uint8Array(source));
  try {
    const pageCount = document.pageCount();
    if (!Number.isInteger(pageCount) || pageCount < 1 || pageCount > maxPages) {
      throw new Error("page count is outside the configured limit");
    }
    const pages = [];
    let metadataBytes = 0;
    for (let index = 0; index < pageCount; index += 1) {
      const info = JSON.parse(document.getPageInfo(index));
      const width = Number(info.width);
      const height = Number(info.height);
      if (
        !Number.isFinite(width)
        || !Number.isFinite(height)
        || width <= 0
        || height <= 0
        || width * height > 100_000_000
      ) {
        throw new Error("page dimensions are outside the configured limit");
      }
      const page = { number: index + 1, width, height };
      metadataBytes += Buffer.byteLength(JSON.stringify(page), "utf8");
      if (metadataBytes > maxOutputBytes) throw new Error("render metadata size limit");
      pages.push(page);
    }
    process.stdout.write(JSON.stringify({
      schema: "bidops.hwp-page-canvas.v1",
      renderer: "rhwp-canvas",
      scale: 1,
      pages,
    }));
  } finally {
    document.free();
  }
}

try {
  await main();
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`rhwp canvas page inspection failed: ${message}\n`);
  process.exitCode = message === "render metadata size limit" ? 2 : 1;
}
