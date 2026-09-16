import { expect, test } from "@playwright/test";
import { mockApi, visualPreSpecNotice } from "./api-mock";

test("담당자는 회차 판정과 사람 정정 사유를 구분하고 본공고와 품명을 읽는다", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/notices/991", route => route.fulfill({ json: {
    ...visualPreSpecNotice,
    lifecycle: {
      pre_spec_no: "PRE-991",
      bid_ntice_no_list: "R26BD000001,R26BD000002",
      changed_at: "2026-09-01T00:00:00Z",
      change_reason: "과업 범위 변경",
    },
    procurement_class: { detail: "정보시스템개발서비스", code: "8111159901" },
    judgment: {
      id: 1, schema_version: null, grade: "검토 권장", readiness: null,
      primary_focus: null, exclusion_category: null,
      summary: "회차 판정은 데이터 연계 역량과의 부합을 확인했습니다.",
      next_action: "연계 대상 기관을 확인하십시오.",
      perspectives: [],
      counterarguments: [{ id: 1, position: 0, text: "연계 범위는 추가 확인이 필요합니다." }],
      verification_items: [], matched_performances: [],
    },
    reviews: [{
      id: 1, run_id: "human-review", notice_pk: 991,
      disposition: null, system_judgment_review: null,
      corrected_grade: "우선 검토", corrected_readiness: null,
      weakest_perspective: null, reason: "사람이 기존 수행 범위를 대조했습니다.",
      reviewer: "검토 담당자", created_at: "2026-09-01T01:00:00Z",
      updated_at: null, answers: [],
    }],
  } }));
  await page.goto("/pre-specs/991");
  await expect(page.getByRole("heading", { name: "등급 사유", exact: true })).toBeVisible();
  await expect(page.getByText("회차 판정은 데이터 연계 역량과의 부합을 확인했습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("사람이 기존 수행 범위를 대조했습니다.", { exact: true })).toBeVisible();
  await expect(page.locator(".pre-spec-detail-header")).toContainText("본공고 R26BD000001,R26BD000002");
  await expect(page.locator(".pre-spec-detail-header")).toContainText("정보시스템개발서비스");
});

test("판정과 본공고 미확인을 부재나 임의 번호로 바꾸지 않는다", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/notices/991", route => route.fulfill({ json: {
    ...visualPreSpecNotice, judgment: null, reviews: [],
    lifecycle: { bid_ntice_no_list: ["malformed-number"] },
    procurement_class: { detail: { invalid: true } },
  } }));
  await page.goto("/pre-specs/991");
  await expect(page.getByText("판정 사유 없음", { exact: true })).toBeVisible();
  await expect(page.getByText("본공고 미확인", { exact: true })).toBeVisible();
  await expect(page.locator(".pre-spec-detail-header")).not.toContainText("malformed-number");
  await expect(page.locator(".pre-spec-detail-header")).not.toContainText("[object Object]");
});

test("첨부는 안전한 원본 URL과 실제 다운로드 경로만 제공하며 0바이트를 보존한다", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/notices/991", route => route.fulfill({ json: {
    ...visualPreSpecNotice,
    attachments: [
      { id: 71, name: "공개 제안요청서.pdf", url: "https://example.invalid/rfp.pdf",
        origin: "g2b", file_ext: "pdf", size_bytes: 0, extract_status: "completed", created_at: null },
      { id: 72, name: "확인 대기.hwp", url: "javascript:alert(1)",
        origin: "g2b", file_ext: "hwp", size_bytes: null, extract_status: "pending", created_at: null },
    ],
  } }));
  await page.goto("/pre-specs/991");
  const attachments = page.getByRole("table", { name: "첨부 파일 목록" });
  const rows = attachments.locator("tbody").getByRole("row");
  await expect(rows).toHaveCount(2);
  await expect(attachments.getByRole("link", { name: "다운로드" }).first()).toHaveAttribute("href", "/api/attachments/71/download");
  await expect(attachments.getByRole("link", { name: "다운로드" }).nth(1)).toHaveAttribute("href", "/api/attachments/72/download");
  await expect(attachments.getByRole("link", { name: "원본 열기" })).toHaveCount(1);
  await expect(attachments.getByRole("link", { name: "원본 열기" })).toHaveAttribute("rel", "noopener noreferrer");
  await expect(rows.first()).toContainText("0 B");
  await expect(rows.nth(1)).toContainText("크기 미확인");

  // 표는 `.ps-sec`의 세로 flex 자식이다. 폭을 `100%`로 못 박으면 형제 여백이 그
  // 바깥에 더해져 오른쪽 끝의 `열기` 칸이 카드 밖으로 나간다(2026-09-16 실측 24px).
  const bounds = await page.evaluate(() => {
    const section = document.querySelector("#ps-evidence")!;
    const table = section.querySelector(".ps-table")!;
    const end = section.querySelector("td.ps-table-end")!;
    return {
      sectionRight: section.getBoundingClientRect().right,
      tableRight: table.getBoundingClientRect().right,
      endRight: end.getBoundingClientRect().right,
    };
  });
  expect(bounds.tableRight).toBeLessThanOrEqual(bounds.sectionRight);
  expect(bounds.endRight).toBeLessThanOrEqual(bounds.sectionRight);
});

test("승계 사유와 담당자를 읽되 조회 오류는 미확인으로 남긴다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/pre-specs/991");
  const card = page.locator(".ps-record-tracking-card");
  // mockApi includes the opportunity fixture and therefore preserves its actual saved context.
  await expect(card.locator(".pre-spec-inherited-context")).toContainText("기존 담당자");
  await page.route("**/api/opportunities/202", route => route.fulfill({ status: 503, json: { detail: "service_unavailable" } }));
  await page.reload();
  await expect(card.getByText("승계 사유 확인 불가", { exact: true })).toBeVisible();
  await expect(card.getByRole("button", { name: "추적 상태 저장", exact: true })).toHaveCount(0);
});

// A6(docs/0915_ui-redesign/spec.md §6): 상세는 세로 보고서형 6단이고, 순회는 상단바
// 액션 슬롯이 가지며, 등급 라벨과 현재 추적 상태 글자는 화면에 각각 한 번만 나온다.
test("상세 6단이 DOM 순서대로 있고 순회는 상단바가 가지며 등급·추적 상태는 한 번만 나온다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/pre-specs/991");
  await expect(page.locator("#ps-process")).toBeVisible();

  const cards = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>(".ps-record > [id]")].map(element => element.id));
  expect(cards).toEqual(["ps-summary", "ps-tracking", "ps-tasks", "ps-conditions", "ps-evidence", "ps-process"]);
  expect(await page.locator("#ps-tasks h2").innerText()).toContain("주요 과업과 수행 범위");
  expect(await page.locator("#ps-conditions h2").innerText()).toContain("참여 조건 · 회사 적합성 · 위험 및 미확인 사항");
  expect(await page.locator("#ps-evidence h2").innerText()).toContain("근거 문서 · 첨부");
  expect(await page.locator("#ps-process h2").innerText()).toContain("처리 이력 · 문서 준비 · 검토 실행");

  const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
  await expect(page.locator("header.topbar").getByRole("navigation", { name: "사전규격 선택 순회" })).toHaveCount(1);
  await expect(page.locator(".ps-record").getByRole("navigation", { name: "사전규격 선택 순회" })).toHaveCount(0);
  await expect(navigation.getByRole("button", { name: "이전 선택 사전규격" })).toBeVisible();
  await expect(navigation.getByRole("button", { name: "다음 선택 사전규격" })).toBeVisible();

  // 등급 라벨은 ① 팩트 스트립 한 자리에만 있다(다른 자리는 등급 출처·사유만 말한다).
  const gradeTexts = await page.evaluate(() => {
    const labels = ["우선 검토", "검토 권장", "관찰 대상", "제외", "판정 없음"];
    return [...document.querySelectorAll<HTMLElement>(".ps-record *")]
      .filter(element => element.children.length === 0)
      .map(element => (element.textContent ?? "").trim())
      .filter(text => labels.includes(text));
  });
  expect(gradeTexts).toEqual(["우선 검토"]);
  await expect(page.getByText("현재 추적 상태", { exact: false })).toHaveCount(1);
});
