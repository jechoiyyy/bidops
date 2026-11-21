import { expect, test } from "@playwright/test";
import { completedView } from "./fixtures/verdict";
import { mockApi, mockFeatureFlags, mockPreSpecOverviewAbsent, openProcessSection, visualPreSpecNotice } from "./api-mock";

test("C-1 판정·정정 사유는 그리지 않고 본공고와 품명을 읽는다", async ({ page }) => {
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
      summary: "회차 판정은 데이터 연계 역량과의 부합을 확인했어요.",
      next_action: "연계 대상 기관을 확인해 주세요.",
      perspectives: [],
      counterarguments: [{ id: 1, position: 0, text: "연계 범위는 추가 확인이 필요해요." }],
      verification_items: [], matched_performances: [],
    },
    reviews: [{
      id: 1, run_id: "human-review", notice_pk: 991,
      disposition: null, system_judgment_review: null,
      corrected_grade: "우선 검토", corrected_readiness: null,
      weakest_perspective: null, reason: "사람이 기존 수행 범위를 대조했어요.",
      reviewer: "검토 담당자", created_at: "2026-09-01T01:00:00Z",
      updated_at: null, answers: [],
    }],
  } }));
  await page.goto("/pre-specs/991");
  await expect(page.locator("#ps-summary")).toBeVisible();
  // 2026-11-19(사전규격 단계 수정안 §3 B): C-1 공고 판정을 다시 돌리지 않으므로 등급 사유·사람 정정
  // 사유·판정의 반론은 사전규격 화면에서 내려갔다. 응답에 값이 있어도 그리지 않는다.
  await expect(page.getByRole("heading", { name: "등급 사유", exact: true })).toHaveCount(0);
  await expect(page.getByText("회차 판정은 데이터 연계 역량과의 부합을 확인했어요.", { exact: true })).toHaveCount(0);
  await expect(page.getByText("사람이 기존 수행 범위를 대조했어요.", { exact: true })).toHaveCount(0);
  await expect(page.getByText("연계 범위는 추가 확인이 필요해요.", { exact: true })).toHaveCount(0);
  await expect(page.locator(".pre-spec-detail-header")).toContainText("본공고 R26BD000001,R26BD000002");
  await expect(page.locator(".pre-spec-detail-header")).toContainText("정보시스템개발서비스");
});

test("판정 없음과 본공고 미확인을 부재나 임의 번호로 바꾸지 않는다", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/notices/991", route => route.fulfill({ json: {
    ...visualPreSpecNotice, judgment: null, reviews: [],
    lifecycle: { bid_ntice_no_list: ["malformed-number"] },
    procurement_class: { detail: { invalid: true } },
  } }));
  await page.goto("/pre-specs/991");
  // 참여 판정 열은 RL 판정이 없는 사업을 "판정 없음 — 추적 후 요청"으로 말한다(부재로 접지 않는다).
  // 값이 없는 열이라 `회사 관련성 참고` 구역은 없고, 이 문구는 `처리 상태·기술 정보` 안에 남는다.
  await expect(page.locator("#ps-conditions")).toHaveCount(0);
  await openProcessSection(page);
  await expect(page.locator("#ps-process").getByText("판정 없음 — 추적 후 요청")).toBeVisible();
  await expect(page.getByText("본공고 미확인", { exact: true })).toBeVisible();
  await expect(page.locator(".pre-spec-detail-header")).not.toContainText("malformed-number");
  await expect(page.locator(".pre-spec-detail-header")).not.toContainText("[object Object]");
});

test("첨부 이름은 서버가 실제 파일명을 알 때만 그 이름으로 보이고, 모르면 목록 값 그대로다", async ({ page }) => {
  await mockApi(page);
  // 운영 사전규격의 실제 모양: 목록 이름은 자리표시자, 형식·크기는 null이다.
  await page.route("**/api/notices/991", route => route.fulfill({ json: {
    ...visualPreSpecNotice,
    attachments: [
      { id: 81, name: "첨부 1", url: "https://example.invalid/1", origin: "g2b", file_ext: null, size_bytes: null,
        extract_status: null, created_at: null,
        acquired_file: { filename: "제안요청서(온시스템 고도화).hwpx", file_ext: "HWPX", size_bytes: 204800 } },
      { id: 82, name: "첨부 2", url: "https://example.invalid/2", origin: "g2b", file_ext: null, size_bytes: null,
        extract_status: null, created_at: null, acquired_file: null },
      { id: 83, name: "첨부 3", url: "https://example.invalid/3", origin: "g2b", file_ext: null, size_bytes: null,
        extract_status: null, created_at: null,
        acquired_file: { filename: "붙임", file_ext: null, size_bytes: null } },
    ],
  } }));
  await page.goto("/pre-specs/991");
  const rows = page.getByRole("table", { name: "첨부 파일 목록" }).locator("tbody").getByRole("row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0).getByRole("cell").nth(0)).toHaveText("제안요청서(온시스템 고도화).hwpx");
  // 크기는 읽기 쉬운 단위로, 정확한 바이트 수는 title로 남긴다.
  await expect(rows.nth(0).getByRole("cell").nth(1)).toHaveText("HWPX · 200.0 KB");
  await expect(rows.nth(0).getByRole("cell").nth(1).locator("span[title]")).toHaveAttribute("title", "204,800 B");
  // 처리 상태 값이 하나도 없으면 그 칸을 그리지 않는다(`미확인` 칩이 줄지어 서지 않게).
  const table = page.getByRole("table", { name: "첨부 파일 목록" });
  await expect(table.getByRole("columnheader")).toHaveText(["파일", "형식 · 크기", "열기"]);
  // 나라장터에서 받은 원문은 내부 다운로드 경로가 없다. 열리지 않는 `다운로드`를 그리지 않는다.
  await expect(table.getByRole("link", { name: "다운로드" })).toHaveCount(0);
  await expect(table.getByRole("link", { name: "원본 열기" })).toHaveCount(3);
  // 아직 내려받지 않은 첨부는 자리표시자와 미확인 그대로다.
  await expect(rows.nth(1).getByRole("cell").nth(0)).toHaveText("첨부 2");
  await expect(rows.nth(1).getByRole("cell").nth(1)).toHaveText("확장자 미확인 · 크기 미확인");
  // 파일명만 알고 형식·크기를 모르면 모르는 칸만 미확인이다.
  await expect(rows.nth(2).getByRole("cell").nth(0)).toHaveText("붙임");
  await expect(rows.nth(2).getByRole("cell").nth(1)).toHaveText("확장자 미확인 · 크기 미확인");
});

test("첨부는 안전한 원본 URL과 실제로 열리는 다운로드 경로만 제공하며 0바이트를 보존한다", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/notices/991", route => route.fulfill({ json: {
    ...visualPreSpecNotice,
    attachments: [
      { id: 71, name: "공개 제안요청서.pdf", url: "https://example.invalid/rfp.pdf",
        origin: "g2b", file_ext: "pdf", size_bytes: 0, extract_status: "completed", created_at: null },
      { id: 72, name: "확인 대기.hwp", url: "javascript:alert(1)",
        origin: "g2b", file_ext: "hwp", size_bytes: null, extract_status: "pending", created_at: null },
      // 서버가 보관한 파일(수동 등록)은 `url`이 내부 다운로드 경로로 온다.
      { id: 73, name: "수동 등록.pdf", url: "/api/attachments/73/download",
        origin: "manual", file_ext: "PDF", size_bytes: 1536, extract_status: null, created_at: null },
    ],
  } }));
  await page.goto("/pre-specs/991");
  const attachments = page.getByRole("table", { name: "첨부 파일 목록" });
  const rows = attachments.locator("tbody").getByRole("row");
  await expect(rows).toHaveCount(3);
  // 열기 칸은 실제로 열리는 것만 그린다: 외부 주소는 `원본 열기`, 보관 파일은 `다운로드`, 둘 다 아니면 없다고 말한다.
  await expect(rows.nth(0).getByRole("link")).toHaveCount(1);
  await expect(rows.nth(0).getByRole("link", { name: "원본 열기" })).toHaveAttribute("href", "https://example.invalid/rfp.pdf");
  await expect(rows.nth(0).getByRole("link", { name: "원본 열기" })).toHaveAttribute("rel", "noopener noreferrer");
  await expect(rows.nth(1).getByRole("link")).toHaveCount(0);
  await expect(rows.nth(1)).toContainText("열 수 있는 주소 없음");
  await expect(rows.nth(2).getByRole("link")).toHaveCount(1);
  await expect(rows.nth(2).getByRole("link", { name: "다운로드" })).toHaveAttribute("href", "/api/attachments/73/download");
  // 처리 상태 값이 있는 표는 그 칸을 그리고, 값이 없는 행은 `미확인`이다.
  await expect(attachments.getByRole("columnheader")).toHaveText(["파일", "형식 · 크기", "처리 상태", "열기"]);
  await expect(rows.nth(0)).toContainText("본문 추출 완료");
  await expect(rows.nth(2).getByRole("cell").nth(2)).toHaveText("미확인");
  await expect(rows.nth(2).getByRole("cell").nth(1)).toHaveText("PDF · 1.5 KB");
  await expect(rows.first()).toContainText("0 B");
  await expect(rows.nth(1)).toContainText("크기 미확인");
  // `acquired_file`이 없는 응답은 목록 값을 그대로 보인다.
  await expect(rows.first()).toContainText("공개 제안요청서.pdf");

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
  // 하단 결정 띠(2026-11-21). mockApi includes the opportunity fixture and therefore preserves its actual saved context.
  const bar = page.locator("#page-footer .pre-spec-tracking-decision.is-recorded");
  await expect(bar.locator(".pre-spec-inherited-context")).toContainText("기존 담당자");
  await page.route("**/api/opportunities/202", route => route.fulfill({ status: 503, json: { detail: "service_unavailable" } }));
  await page.reload();
  await expect(bar.locator(".pre-spec-inherited-context")).toContainText("기록 사유 확인 불가");
  await expect(bar.getByRole("button", { name: "추적 상태 저장", exact: true })).toHaveCount(0);
  await expect(bar.getByRole("button", { name: "추적 시작하기", exact: true })).toHaveCount(0);
});

// 2026-11-21 시안(`docs/1121_prespec-detail/`): 본문은 사실 줄 → 사업 개요와 주요 과업 → (값이 있을 때만)
// 회사 관련성 참고 → 원문·첨부 → 처리 상태·기술 정보 순이다. 추적 결정은 본문 구역이 아니라 패널 아래 하단 띠이고,
// 순회는 상단바 액션 슬롯이 가지며, 등급 라벨은 없다. 값이 없으면 회사 관련성 참고 구역은 그리지 않는다.
test("상세 본문이 시안 순서대로 있고 순회는 상단바가 가지며 등급은 없고 추적 결정은 하단 띠에만 있다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/pre-specs/991");
  await expect(page.locator("#ps-process")).toBeVisible();

  const cards = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>(".ps-record > [id]")].map(element => element.id));
  // 값이 없는 건은 `회사 관련성 참고` 구역을 그리지 않는다(판정·회사 적합성·예비 판단 근거 모두 없음).
  expect(cards).toEqual(["ps-summary", "ps-tasks", "ps-evidence", "ps-process"]);
  expect(await page.locator("#ps-tasks h2").innerText()).toContain("사업 개요와 주요 과업");
  expect(await page.locator("#ps-evidence h2").innerText()).toContain("원문·첨부");
  expect(await page.locator("#ps-process h2").innerText()).toContain("처리 상태·기술 정보");
  // 없어진 본문 구역·요소.
  await expect(page.locator("#ps-tracking")).toHaveCount(0);
  await expect(page.locator(".ps-record-tracking-card, .ps-record-chips, .ps-record-list-link")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "목록으로 돌아가기" })).toHaveCount(0);

  const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
  await expect(page.locator("header.topbar").getByRole("navigation", { name: "사전규격 선택 순회" })).toHaveCount(1);
  await expect(page.locator(".ps-record").getByRole("navigation", { name: "사전규격 선택 순회" })).toHaveCount(0);
  await expect(navigation.getByRole("button", { name: "이전 선택 사전규격" })).toBeVisible();
  await expect(navigation.getByRole("button", { name: "다음 선택 사전규격" })).toBeVisible();

  // 2026-11-19: 등급 라벨은 사전규격 상세 어디에도 없다(C-1 미가동, 사전규격 단계 수정안 §3 B).
  const gradeTexts = await page.evaluate(() => {
    const labels = ["우선 검토", "검토 권장", "관찰 대상", "제외", "판정 없음"];
    return [...document.querySelectorAll<HTMLElement>(".ps-record *")]
      .filter(element => element.children.length === 0)
      .map(element => (element.textContent ?? "").trim())
      .filter(text => labels.includes(text));
  });
  expect(gradeTexts).toEqual([]);
  await expect(page.locator(".pre-spec-detail-grade-row")).toHaveCount(0);
  // 현재 추적 상태 글자는 화면에 한 번만 나온다 — 하단 띠가 그 자리다.
  await expect(page.getByText("현재 추적 상태", { exact: false })).toHaveCount(1);
  await expect(page.locator("#page-footer").getByText("현재 추적 상태", { exact: false })).toHaveCount(1);
});

// 값이 있으면(RL 판정 요약) `회사 관련성 참고`가 개요 바로 다음, 원문·첨부 앞에 온다.
test("회사 관련성 참고는 값이 있을 때만 개요 다음 구역으로 나온다", async ({ page }) => {
  await mockApi(page);
  const view = completedView({ opportunity_id: 202 });
  await page.route("**/api/opportunities/202/verdict", (route) => route.fulfill({ json: view }));
  await page.goto("/pre-specs/991");
  await expect(page.locator("#ps-conditions")).toBeVisible();
  const cards = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>(".ps-record > [id]")].map(element => element.id));
  expect(cards).toEqual(["ps-summary", "ps-tasks", "ps-conditions", "ps-evidence", "ps-process"]);
  expect(await page.locator("#ps-conditions h2").innerText()).toContain("회사 관련성 참고");
});

// 설계고도화안 C-4: 개요 자동 검토가 이 환경에서 꺼져 있으면 실행 기록이 없는 이유를 먼저 말한다.
test("개요 검토가 꺼진 환경은 실행 기록이 없는 이유로 꺼짐을 먼저 말한다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecOverviewAbsent(page);
  await mockFeatureFlags(page, { rl_analysis: false, prespec_overview: false });
  await page.goto("/pre-specs/991");
  await expect(page.locator(".pre-spec-overview-waiting")).toContainText("개요 검토 · 이 환경에서 꺼져 있음");
});

test("개요 검토가 켜진 환경은 꺼짐을 말하지 않는다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecOverviewAbsent(page);
  await mockFeatureFlags(page, { rl_analysis: true, prespec_overview: true });
  await page.goto("/pre-specs/991");
  await expect(page.locator(".pre-spec-overview-waiting")).toContainText("개요 검토 실행 기록이 없어 주요 과업을 표시할 수 없어요.");
  await expect(page.locator(".pre-spec-overview-waiting")).not.toContainText("이 환경에서 꺼져 있음");
});
