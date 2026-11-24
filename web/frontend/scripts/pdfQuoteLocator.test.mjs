import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/pdfQuoteLocator.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const { createPdfQuoteLocator } = await import(`data:text/javascript,${encodeURIComponent(outputText)}`);

test("쪽을 정규화해 가장 앞의 정확한 일치 또는 인접한 두 쪽을 찾는다", () => {
  const locate = createPdfQuoteLocator([
    { number: 4, text: "공공 제안 요청서" },
    { number: 1, text: "❍ 공공 • 제안 요청서 / 검증 대상" },
    { number: 2, text: "데이터 수집" },
  ]);
  assert.deepEqual(locate("공공-제안 요청서"), { kind: "exact", page: 1 });
  assert.deepEqual(locate("대상 데이터"), { kind: "span", page: 1 });
  for (const quote of ["공 공", "다른 문장", "수집 공공"]) {
    assert.deepEqual(locate(quote), { kind: "not_found", page: null });
  }
});

