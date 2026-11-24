import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/engineRiskLinks.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const { createEngineRiskLinker } = await import(`data:text/javascript,${encodeURIComponent(outputText)}`);
const fixture = JSON.parse(readFileSync(new URL("../tests/fixtures/engine-risk-links-4186.json", import.meta.url), "utf8"));

test("4186 사유·전제·확인 요청을 원래 리스크 순서로 연결한다", () => {
  const link = createEngineRiskLinker(fixture.risks);
  assert.deepEqual(fixture.whyNot.map(link), [3, 2, 1]);
  assert.deepEqual(fixture.preconditions.map(link), [3, 2, 4, 5, 0, 7, null]);
  assert.deepEqual(fixture.execution.map(({ title, why }) => link(`${title} ${why}`)), [3, 2, 0, 7, 6]);
});

test("최저 점수와 동점 우선순위를 적용한다", () => {
  const link = createEngineRiskLinker([
    { evidence: { quote: "검증표본" }, description: "QWK 300건" },
    { evidence: { quote: "QWK 300건" }, description: "검증표본" },
    { evidence: { quote: "QWK 300건" }, description: "검증표본" },
  ]);
  assert.equal(link("QWK"), null);
  assert.equal(link("검증표본에서 QWK 300 건"), 1);
});
