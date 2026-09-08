#!/usr/bin/env node

/* Render one HWP/HWPX input into page SVG files for the credential-free worker.
 *
 * The script deliberately writes only to a worker-created temporary directory
 * and returns bounded metadata on stdout.  It never accepts a URL, command, or
 * caller-selected output file.  Chromium is invoked by the Python worker
 * after these SVGs have been checked and assembled into a local print sheet.
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

function safeOutputDirectory(value) {
  if (!value || value.includes("\0")) throw new Error("invalid output directory");
  const resolved = path.resolve(value);
  fs.mkdirSync(resolved, { recursive: true });
  if (!fs.statSync(resolved).isDirectory()) throw new Error("invalid output directory");
  return resolved;
}

function validateSvg(svg) {
  if (typeof svg !== "string" || !svg.startsWith("<svg")) throw new Error("invalid page SVG");
  // SVG namespaces use an http URI by definition.  Only resource-bearing
  // attributes are restricted here; local fragment links and embedded image
  // data remain valid, while network/file/script targets are rejected.
  if (
    /<\s*script\b/i.test(svg)
    || /(?:href|src)\s*=\s*["']\s*(?:https?:|file:|javascript:|\/\/)/i.test(svg)
    || /url\(\s*(?:https?:|file:|javascript:|\/\/)/i.test(svg)
  ) {
    throw new Error("external SVG content is not allowed");
  }
  const dimensions = svg.match(/<svg\b[^>]*\b(?:width|height|viewBox)=/g);
  if (!dimensions || dimensions.length === 0) throw new Error("page SVG dimensions are missing");
}

async function main() {
  const inputPath = argument("--input");
  const outputDir = safeOutputDirectory(argument("--output-dir"));
  const maxPagesRaw = argument("--max-pages");
  const maxPages = Number.parseInt(maxPagesRaw ?? "0", 10);
  const maxOutputBytesRaw = argument("--max-output-bytes");
  const maxOutputBytes = Number.parseInt(maxOutputBytesRaw ?? "0", 10);
  if (!inputPath || !Number.isInteger(maxPages) || maxPages < 1 || !Number.isInteger(maxOutputBytes) || maxOutputBytes < 1) {
    throw new Error("usage: rhwp_render_pages.mjs --input <file> --output-dir <dir> --max-pages <n> --max-output-bytes <n>");
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
    let totalOutputBytes = 0;
    for (let index = 0; index < pageCount; index += 1) {
      const info = JSON.parse(document.getPageInfo(index));
      const svg = document.renderPageSvg(index);
      validateSvg(svg);
      const svgBytes = Buffer.byteLength(svg, "utf8");
      if (svgBytes > maxOutputBytes - totalOutputBytes) {
        throw new Error("render output size limit");
      }
      const fileName = `page-${String(index + 1).padStart(4, "0")}.svg`;
      const destination = path.join(outputDir, fileName);
      const handle = fs.openSync(destination, "wx", 0o600);
      try {
        fs.writeFileSync(handle, svg, { encoding: "utf8" });
      } finally {
        fs.closeSync(handle);
      }
      totalOutputBytes += svgBytes;
      pages.push({
        number: index + 1,
        width: Number(info.width),
        height: Number(info.height),
        file: fileName,
      });
    }
    process.stdout.write(JSON.stringify({
      schema: "bidops.hwp-page-svg.v1",
      renderer: "rhwp",
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
  process.stderr.write(`rhwp page render failed: ${message}\n`);
  process.exitCode = message === "render output size limit" ? 2 : 1;
}
