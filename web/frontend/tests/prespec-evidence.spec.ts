import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { mockApi, mockPreSpecs } from "./api-mock";

/**
 * 완료 게이트의 live-surface 증거.
 *
 * 화면 캡처 자체는 `pre-specs.spec.ts`의 `captureRecord`(`PS_RECORD_CAPTURE_DIR`)가
 * 상세 route를 더 여러 상태로 찍는다. 이 파일은 **selector 단위 조작·단정 기록**만
 * 남긴다 — 어떤 선택자를 실제로 눌렀고 무엇을 단정했는지가 증거의 핵심이기 때문이다.
 * 새 환경변수를 만들지 않고 같은 `PS_RECORD_CAPTURE_DIR`를 쓴다.
 */
const OUT = process.env.PS_RECORD_CAPTURE_DIR ?? "";

test.skip(() => OUT === "", "PS_RECORD_CAPTURE_DIR가 없으면 증거 수집을 건너뛴다");

interface Action {
  type: string;
  selector: string;
  target: string;
  status: string;
  timestamp: string;
}

test("evidence: 사전규격 목록과 상세를 selector 단위로 조작하고 단정한다", async ({ page }) => {
  await mkdir(OUT, { recursive: true });
  const actions: Action[] = [];
  const record = (type: string, selector: string, target: string) =>
    actions.push({ type, selector, target, status: "passed", timestamp: new Date().toISOString() });

  await mockApi(page);
  await mockPreSpecs(page);

  await page.goto("/pre-specs?sw_only=false");
  record("navigate", "/pre-specs?sw_only=false", "사전규격 목록");

  const row = page.locator(".pre-specs-row").first();
  await expect(row).toBeVisible();
  record("assert.visible", ".pre-specs-row", "목록 행");

  // 등급은 색이 아니라 글자로 말한다.
  const grade = page.locator(".pre-specs-row-grade").first();
  await expect(grade).toBeVisible();
  record("assert.visible", ".pre-specs-row-grade", await grade.innerText());

  // 행을 실제로 눌러 상세 pane이 바뀌는지 본다.
  await row.click();
  record("click", ".pre-specs-row", "행 선택");
  await expect(page.locator(".pre-specs-detail")).toBeVisible();
  record("assert.visible", ".pre-specs-detail", "선택한 사전규격 상세");

  await page.goto("/pre-specs/991");
  record("navigate", "/pre-specs/991", "사전규격 상세");

  const briefing = page.getByRole("heading", { name: "등급 사유", exact: true });
  await expect(briefing).toBeVisible();
  record("assert.visible", "role=heading[name='등급 사유']", "등급 사유");

  const header = page.locator(".pre-spec-detail-header");
  await expect(header).toContainText("본공고");
  record("assert.containsText", ".pre-spec-detail-header", "본공고 칩");

  // 범위 확정 폼은 오른쪽 판단 열이 아니라 왼쪽에 항상 붙어 있다.
  await expect(page.locator("#ps-record-range")).toBeAttached();
  record("assert.attached", "#ps-record-range", "개요 입력 범위 확정 자리");

  const toggle = page.getByRole("button", { name: /문서 준비 (열기|닫기)/ });
  await expect(toggle).toBeVisible();
  record("assert.visible", "role=button[name=/문서 준비 (열기|닫기)/]", await toggle.innerText());

  await writeFile(`${OUT}/playwright-transcript.json`, JSON.stringify({
    schemaVersion: 1,
    kind: "browser-automation",
    tool: "playwright",
    project: "app",
    command: ["npx", "playwright", "test", "tests/prespec-evidence.spec.ts", "--project=app"],
    status: "passed",
    startedAt: actions[0]?.timestamp ?? new Date().toISOString(),
    actions,
  }, null, 2));
});
