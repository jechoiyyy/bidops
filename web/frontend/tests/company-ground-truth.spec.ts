import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockRealCompany } from "./api-mock";
import {
  RL_COMPANY_ID,
  RL_GRAPH_SHA256,
  RL_GRAPH_VERSION_ID,
  RL_PROFILE_SHA256,
  RL_PROFILE_VERSION_ID,
  rlAttentionCount,
  rlFacts,
  seoulDateOffset,
  type RlFact,
} from "./fixtures/company-rl";

/*
 * RL-00 STEP-005 · spec T8 — `/company` 읽기 전용 회사 근거 화면.
 *
 * 고정 응답은 `mockApi`(미등록 경로는 404) 위에 건 `mockRealCompany`이며 실제 백엔드에
 * 연결하지 않는다. 기대값은 화면 코드를 가져오지 않고 fixture 키 목록으로 직접 적었다
 * (그룹 매핑·상태 이름이 화면과 어긋나면 여기서 드러난다).
 */

// 사실 키 → 표 그룹(spec "그룹 매핑"). 화면 코드와 별개로 손으로 적은 기대값이다.
const GROUP_KEYS = {
  qualification: ["qual:sme_certificate", "qual:sme_certificate:detail", "qual:direct_production", "qual:sw_business", "qual:credit_rating"],
  performance: ["project:2024-01", "project:2023-01", "project:certified_list"],
  staff: ["staff:dev", "staff:onsite", "staff:pm"],
  preference: ["pref:amount_floor", "pref:domain:01", "pref:agency:01", "pref:agency:02", "pref:margin", "excl:hardware"],
} as const;
const ATTENTION_KEYS = [
  "qual:sme_certificate:detail", // unknown (세부 미입력)
  "qual:credit_rating", // proposed
  "project:certified_list", // unknown
  "staff:pm", // unknown
  "pref:agency:02", // proposed
  "pref:margin", // unknown
];
const INFERRED_KEY = "qual:legacy_inferred";
const EXPECTED_COUNTS = { confirmed: 12, attention: 6, expiring: 1 };

const GROUP_LABELS = {
  attention: "확인이 필요한 것",
  qualification: "자격 서류",
  performance: "실적",
  staff: "인력",
  preference: "선호·제외 조건",
  "proposal-assets": "제안서 자료",
} as const;

/** 운영 정보 금지 문자열(ui-spec §5, spec "운영 정보 금지 검사"). */
const FORBIDDEN_TEXT = [
  "graph_sha256",
  "profile_version_id",
  "unmeasured_reference",
  "mock_reference",
  RL_GRAPH_SHA256,
  RL_PROFILE_SHA256,
  RL_PROFILE_VERSION_ID,
  RL_GRAPH_VERSION_ID,
  "qwen",
  "gpt-6-luna",
  "codex-exec",
  "c2-order-plan",
  "policy_version",
];
const INTERVIEW_NUMBER = /\b[A-G][1-6]\b/;

test.beforeEach(async ({ page, context }) => {
  // 외부로 나가는 요청이 있으면 아래 `externalRequests`에 남겨 테스트가 실패하게 한다.
  await page.route("**://fonts.googleapis.com/**", (route) => route.fulfill({ status: 200, contentType: "text/css", body: "" }));
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: `http://127.0.0.1:${process.env.PW_PORT ?? "4173"}` });
});

async function openCompany(page: Page, search = "", options: Parameters<typeof mockRealCompany>[1] = {}) {
  await mockApi(page);
  const trace = await mockRealCompany(page, options);
  const external: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.hostname !== "127.0.0.1") external.push(request.url());
  });
  await page.goto(`/company${search}`);
  return { trace, external };
}

const rows = (page: Page) => page.locator("main [data-fact-key]");
const rowKeys = async (page: Page) => rows(page).evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-fact-key")));
const rowFor = (page: Page, key: string) => page.locator(`main [data-fact-key="${key}"]`);

test("T8: 세 수치는 사실 건수와 같고 확인이 필요한 것은 추정값+확인 필요 사실이다", async ({ page }) => {
  const facts = rlFacts();
  // fixture 자체가 기대 건수와 맞는지 먼저 고정한다(화면 코드와 무관한 산술).
  expect(facts.filter((fact) => fact.status === "confirmed")).toHaveLength(EXPECTED_COUNTS.confirmed);
  expect(rlAttentionCount(facts)).toBe(EXPECTED_COUNTS.attention);

  const { trace, external } = await openCompany(page);

  await expect(page.locator("header.topbar h1")).toHaveText("회사 근거");
  await expect(page.getByTestId("company-count-confirmed")).toHaveText(String(EXPECTED_COUNTS.confirmed));
  await expect(page.getByTestId("company-count-attention")).toHaveText(String(EXPECTED_COUNTS.attention));
  await expect(page.getByTestId("company-count-expiring")).toHaveText(String(EXPECTED_COUNTS.expiring));

  // 기본 그룹은 attention: 확인이 필요한 것 = proposed ∪ unknown. inferred는 없다.
  await expect(page.getByTestId("company-attention-count")).toHaveText(String(EXPECTED_COUNTS.attention));
  await expect(page.getByTestId("company-nav-attention-count")).toHaveText(String(EXPECTED_COUNTS.attention));
  expect((await rowKeys(page)).sort()).toEqual([...ATTENTION_KEYS].sort());
  await expect(rowFor(page, INFERRED_KEY)).toHaveCount(0);
  await expect(page.getByText("추론 자격")).toHaveCount(0);
  for (const key of ATTENTION_KEYS) {
    const status = facts.find((fact) => fact.fact_key === key)!.status;
    await expect(rowFor(page, key)).toHaveAttribute("data-fact-status", status);
    await expect(rowFor(page, key).locator(".co-pill")).toHaveText(status === "proposed" ? "추정값" : "확인 필요");
  }
  await expect(page.getByRole("heading", { name: /지금 확인하면 판정이 바뀌는 것/ })).toBeVisible();

  // 읽기 전용: 상단 안내 한 줄, 맞음·수정·입력·저장 버튼과 영향 공고 열은 없다.
  await expect(page.locator(".co-notice")).toHaveText("값 수정은 회사 파일을 고쳐 다시 등록합니다(설정 › 도움말)");
  for (const name of ["맞음", "수정", "입력", "저장"]) {
    await expect(page.getByRole("button", { name: new RegExp(`^${name}`) })).toHaveCount(0);
  }
  await expect(page.getByText("영향 공고")).toHaveCount(0);

  // 회사 경로 요청은 회사 컨텍스트와 한 회사의 프로필 둘뿐이다(다른 경로·외부로 새지 않는다).
  // 컨텍스트는 사이드바와 화면이 같은 key로 읽으므로 화면이 열릴 때 다시 읽을 수 있어 경로 종류로 비교한다.
  expect([...new Set(trace.requests)].sort()).toEqual([
    "GET /api/company",
    `GET /api/companies/${RL_COMPANY_ID}/profile`,
  ].sort());
  expect(external).toEqual([]);
});

test("T8: 상단바는 회사 이름·마지막 저장 날짜와 이전 버전(현재 버전만)을 그리고 저장 버튼은 없다", async ({ page }) => {
  await openCompany(page);

  const topbar = page.locator("header.topbar");
  await expect(topbar.getByTestId("company-topbar-meta")).toHaveText("㈜루트랩 · 마지막 저장 2026년 10월 16일");
  await expect(topbar.getByRole("button", { name: "저장" })).toHaveCount(0);
  const trigger = topbar.getByRole("button", { name: "이전 버전" });
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await trigger.click();
  const panel = page.getByRole("region", { name: "회사 근거 버전" });
  await expect(panel).toContainText("현재 버전 · 2026년 10월 16일 저장");
  await expect(panel).toContainText("현재 버전만 볼 수 있습니다");
  await expect(panel.getByRole("option")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(page.locator("h1")).toHaveCount(1);
});

test("T8: 그룹 탭은 ?group=으로 열리고 보유·세부 분리와 상주 지역(대구)을 그대로 보인다", async ({ page }) => {
  await openCompany(page);
  const nav = page.getByRole("navigation", { name: "회사 근거 항목" });
  await expect(nav.getByRole("link", { name: /^확인이 필요한 것/ })).toHaveAttribute("aria-current", "page");

  for (const [group, label] of [["qualification", "자격 서류"], ["performance", "실적"], ["staff", "인력"], ["preference", "선호·제외 조건"]] as const) {
    await nav.getByRole("link", { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/company\\?group=${group}$`));
    await expect(nav.getByRole("link", { name: label, exact: true })).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("heading", { level: 2, name: new RegExp(`^${label}`) })).toBeVisible();
    await expect(page.getByRole("table", { name: label })).toBeVisible();
    expect((await rowKeys(page)).sort()).toEqual([...GROUP_KEYS[group]].sort());
    await expect(rowFor(page, INFERRED_KEY)).toHaveCount(0);
    // 표 머리는 항목·상태·내용 + 복사 열뿐이다(영향 공고 열 없음).
    await expect(page.locator(".co-table thead th")).toHaveText(["항목", "상태", "내용", "항목 키 복사"]);
  }

  // 자격: 보유(확인됨)와 세부(확인 필요)는 서로 다른 행이다. 세부 미입력을 부족·보유로 접지 않는다.
  await page.goto("/company?group=qualification");
  const held = rowFor(page, "qual:sme_certificate");
  await expect(held.locator(".co-pill")).toHaveText("확인됨");
  await expect(held).toContainText("보유");
  const detail = rowFor(page, "qual:sme_certificate:detail");
  await expect(detail.locator(".co-pill")).toHaveText("확인 필요");
  await expect(detail).toContainText("미입력");
  await expect(rowFor(page, "qual:credit_rating").locator(".co-pill")).toHaveText("추정값");
  await expect(rowFor(page, "qual:direct_production")).toContainText("소프트웨어 개발");
  await expect(rowFor(page, "qual:direct_production")).toContainText("direct-production.pdf");

  // 인력: 상주 가능 지역 값이 그대로 보인다.
  await page.goto("/company?group=staff");
  await expect(rowFor(page, "staff:onsite")).toContainText("가용 6명");
  await expect(rowFor(page, "staff:onsite")).toContainText("지역 대구");
  await expect(rowFor(page, "staff:pm")).toContainText("미입력");

  // 선호·제외: 수치 조건과 제외 분류를 읽을 수 있는 말로 옮긴다.
  await page.goto("/company?group=preference");
  await expect(rowFor(page, "pref:amount_floor")).toContainText("50,000,000원");
  await expect(rowFor(page, "excl:hardware")).toContainText("제외 · 하드웨어");

  // 실적: 홈페이지 실적은 기관·연도만 있고 없는 역할·금액을 지어내지 않는다.
  await page.goto("/company?group=performance");
  await expect(rowFor(page, "project:2024-01")).toContainText("대구시청 · 2024년");
  await expect(rowFor(page, "project:2024-01")).not.toContainText("원");
});

test("T8: 제안서 자료는 비활성이고 직접 주소는 빈 상태, 모르는 group은 기본 그룹이다", async ({ page }) => {
  await openCompany(page);
  const nav = page.getByRole("navigation", { name: "회사 근거 항목" });
  const disabled = nav.locator(".co-nav-item.is-disabled", { hasText: "제안서 자료" });
  await expect(disabled).toHaveAttribute("aria-disabled", "true");
  await expect(nav.getByRole("link", { name: "제안서 자료" })).toHaveCount(0);

  await page.goto("/company?group=proposal-assets");
  await expect(page.getByText("RL-04에서 채웁니다")).toBeVisible();
  await expect(rows(page)).toHaveCount(0);

  await page.goto("/company?group=nonexistent");
  await expect(page.getByTestId("company-attention")).toBeVisible();
  expect((await rowKeys(page)).sort()).toEqual([...ATTENTION_KEYS].sort());
});

test("T8: 상태 pill은 지정한 테마 토큰 색을 쓴다(확인됨 success, 추정값 blue, 확인 필요 warning)", async ({ page }) => {
  await openCompany(page, "?group=qualification");
  await expect(rowFor(page, "qual:credit_rating")).toBeVisible();

  const colors = await page.evaluate(() => {
    const shell = document.querySelector(".app-shell") as HTMLElement;
    // 토큰을 실제로 풀어 보는 탐침. 색 값을 테스트가 따로 적지 않는다.
    const resolve = (background: string, color: string) => {
      const probe = document.createElement("span");
      probe.style.backgroundColor = `var(${background})`;
      probe.style.color = `var(${color})`;
      shell.appendChild(probe);
      const style = getComputedStyle(probe);
      const resolved = { background: style.backgroundColor, color: style.color };
      probe.remove();
      return resolved;
    };
    const pill = (status: string) => {
      const node = document.querySelector(`.co-pill[data-status="${status}"]`) as HTMLElement;
      const style = getComputedStyle(node);
      return { background: style.backgroundColor, color: style.color, text: node.textContent, radius: style.borderTopLeftRadius };
    };
    return {
      confirmed: { actual: pill("confirmed"), expected: resolve("--color-success-muted", "--color-success") },
      proposed: { actual: pill("proposed"), expected: resolve("--color-background-blue", "--color-text-blue") },
      unknown: { actual: pill("unknown"), expected: resolve("--color-warning-muted", "--color-warning") },
      error: resolve("--color-error-muted", "--color-error"),
    };
  });
  for (const status of ["confirmed", "proposed", "unknown"] as const) {
    expect(colors[status].actual.background, `${status} 배경`).toBe(colors[status].expected.background);
    expect(colors[status].actual.color, `${status} 글자`).toBe(colors[status].expected.color);
  }
  expect([colors.confirmed.actual.text, colors.proposed.actual.text, colors.unknown.actual.text]).toEqual(["확인됨", "추정값", "확인 필요"]);
  // 세 pill은 서로 다른 색이고, 확인 필요는 error 색이 아니다(unknown은 부족이 아니다).
  expect(new Set([colors.confirmed.actual.background, colors.proposed.actual.background, colors.unknown.actual.background]).size).toBe(3);
  expect(colors.unknown.actual.background).not.toBe(colors.error.background);
  expect(colors.unknown.actual.color).not.toBe(colors.error.color);
});

test("T8: 곧 만료는 유효기간이 경고 일수 이내인 자격만 센다(지난 날짜 포함, 먼 날짜 제외)", async ({ page }) => {
  const facts: RlFact[] = rlFacts().filter((fact) => !fact.fact_key.startsWith("qual:"));
  const qualification = (key: string, label: string, validUntil: string | null): RlFact => ({
    fact_key: key, label, status: "confirmed", origin: "user_interview", evidence_ids: [],
    value: { held: true, detail: null, valid_until: validUntil, issued_on: null, file_name: null },
  });
  facts.push(
    qualification("qual:expired", "지난 자격", seoulDateOffset(-3)),
    qualification("qual:boundary", "경계 자격", seoulDateOffset(60)),
    qualification("qual:beyond", "경계 밖 자격", seoulDateOffset(61)),
    qualification("qual:none", "유효기간 없는 자격", null),
  );
  await openCompany(page, "?group=qualification", { facts });

  await expect(page.getByTestId("company-count-expiring")).toHaveText("2");
  await expect(rowFor(page, "qual:expired")).toContainText("만료됨");
  await expect(rowFor(page, "qual:boundary")).toContainText("60일 후 만료");
  await expect(rowFor(page, "qual:beyond")).not.toContainText("만료");
  await expect(rowFor(page, "qual:none")).not.toContainText("만료");
});

test("T8: 행마다 항목 키 복사 버튼 하나가 있고 키 자체는 글자로 보이지 않는다", async ({ page }) => {
  await openCompany(page);
  const row = rowFor(page, "pref:margin");
  const copy = row.getByRole("button");
  await expect(copy).toHaveCount(1);
  await expect(copy).toHaveText("키 복사");
  await expect(page.locator("main")).not.toContainText("pref:margin");
  await copy.click();
  await expect(copy).toHaveText("복사됨");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("pref:margin");
  // 모든 행이 같은 형식의 버튼 하나만 갖는다.
  for (const key of ATTENTION_KEYS) await expect(rowFor(page, key).getByRole("button")).toHaveCount(1);
});

test("T8: 운영 정보(해시·버전 ID·참조 표식·모델·정책·인터뷰 번호)는 어느 그룹에도 없다", async ({ page }) => {
  await openCompany(page);
  const groups = ["", "?group=qualification", "?group=performance", "?group=staff", "?group=preference", "?group=proposal-assets"];
  for (const search of groups) {
    await page.goto(`/company${search}`);
    await expect(page.locator("header.topbar h1")).toHaveText("회사 근거");
    await expect(page.getByTestId("company-count-confirmed")).toBeVisible();
    await page.getByRole("button", { name: "이전 버전" }).click();
    const text = await page.evaluate(() => document.body.innerText);
    const html = await page.evaluate(() => document.documentElement.outerHTML);
    for (const forbidden of FORBIDDEN_TEXT) {
      expect(text.toLowerCase(), `${search || "attention"} 글자에 ${forbidden}`).not.toContain(forbidden.toLowerCase());
      expect(html.toLowerCase(), `${search || "attention"} DOM에 ${forbidden}`).not.toContain(forbidden.toLowerCase());
    }
    expect(text, `${search || "attention"} 인터뷰 번호`).not.toMatch(INTERVIEW_NUMBER);
  }
});

test("T8: 사이드바 회사 근거는 /company로 가고 건수와 워크스페이스 이름을 API에서 읽는다", async ({ page }) => {
  await openCompany(page);
  const sidebar = page.locator("aside.sidebar");
  const link = sidebar.getByRole("link", { name: "회사 근거", exact: true });
  await expect(link).toHaveAttribute("href", "/company");
  await expect(link).toHaveAttribute("aria-current", "page");
  await expect(link.locator(".sidebar-item-count")).toHaveText(String(EXPECTED_COUNTS.attention));
  await expect(sidebar.locator(".sidebar-brand strong")).toHaveText("루트랩");
  await expect(sidebar.locator(".sidebar-brand-mark")).toHaveText("루");
  // 같은 이름의 항목이 하나뿐이다(설정 아래 판정 기준 `/profile`은 사이드바 항목이 아니다).
  await expect(sidebar.getByRole("link", { name: "회사 근거", exact: true })).toHaveCount(1);

  await page.goto("/briefing");
  await sidebar.getByRole("link", { name: "회사 근거", exact: true }).click();
  await expect(page).toHaveURL(/\/company$/);
  await expect(page.locator("header.topbar h1")).toHaveText("회사 근거");
});

test("T8: 실회사가 없거나 활성 버전이 없으면 수치를 0으로 적지 않고 이유를 말한다", async ({ page }) => {
  await openCompany(page, "", { notRegistered: true });
  await expect(page.getByRole("alert")).toContainText("등록된 회사가 없습니다");
  await expect(page.getByTestId("company-count-confirmed")).toHaveCount(0);
  await expect(page.locator("aside.sidebar .sidebar-brand strong")).toHaveText("BidOps");
  await expect(page.locator("aside.sidebar").getByRole("link", { name: "회사 근거", exact: true }).locator(".sidebar-item-count")).toHaveCount(0);

  const second = await page.context().newPage();
  await mockApi(second);
  await mockRealCompany(second, { noActiveVersion: true });
  await second.goto("/company");
  await expect(second.getByText("회사 근거가 아직 활성화되지 않았습니다")).toBeVisible();
  await expect(second.getByTestId("company-count-confirmed")).toHaveCount(0);
  await expect(second.getByTestId("company-topbar-meta")).toContainText("아직 저장된 버전이 없습니다");
  await expect(second.locator("aside.sidebar").getByRole("link", { name: "회사 근거", exact: true }).locator(".sidebar-item-count")).toHaveCount(0);
});

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`T8: ${viewport.width}x${viewport.height} 구조 — 좌측 요약·중앙 본문이 폭 안에 있고 가로로 넘치지 않는다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openCompany(page, "?group=preference");
    await expect(rowFor(page, "pref:margin")).toBeVisible();

    const layout = await page.evaluate(() => {
      const box = (selector: string) => {
        const node = document.querySelector(selector);
        if (!node) throw new Error(`missing ${selector}`);
        const rect = node.getBoundingClientRect();
        return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width };
      };
      const canvas = document.querySelector('[data-shell-region="canvas"]') as HTMLElement;
      const table = box(".co-table");
      const lastColumn = box(".co-table thead th:last-child");
      return {
        sidebar: box('[data-shell-region="sidebar"]'),
        topbar: box('[data-shell-region="topbar"]'),
        side: box(".co-side"),
        main: box(".co-main"),
        table,
        lastColumn,
        h1Count: document.querySelectorAll("h1").length,
        docOverflow: document.documentElement.scrollWidth - window.innerWidth,
        canvasOverflow: canvas.scrollWidth - canvas.clientWidth,
        viewportWidth: window.innerWidth,
      };
    });
    expect(layout.h1Count).toBe(1);
    expect(layout.docOverflow).toBeLessThanOrEqual(0);
    expect(layout.canvasOverflow).toBeLessThanOrEqual(0);
    expect(layout.topbar.bottom - layout.topbar.top).toBeCloseTo(44, 0);
    // 좌측 요약은 사이드바 오른쪽·본문 왼쪽에 있고 둘은 겹치지 않는다.
    expect(layout.side.left).toBeGreaterThanOrEqual(layout.sidebar.right);
    expect(layout.main.left).toBeGreaterThanOrEqual(layout.side.right);
    expect(layout.main.right).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.table.right).toBeLessThanOrEqual(layout.main.right + 1);
    expect(layout.lastColumn.right).toBeLessThanOrEqual(layout.table.right + 1);

    // 확인이 필요한 것 목록도 같은 폭 안에서 행 구조를 지킨다.
    await page.goto("/company");
    await expect(rowFor(page, "staff:pm")).toBeVisible();
    const attention = await page.evaluate(() => {
      const list = document.querySelector(".co-attention")!.getBoundingClientRect();
      const rowsOk = Array.from(document.querySelectorAll(".co-attention-row")).every((row) => {
        const rect = row.getBoundingClientRect();
        return rect.left >= list.left && rect.right <= list.right + 1;
      });
      return { rowsOk, overflow: document.documentElement.scrollWidth - window.innerWidth };
    });
    expect(attention.rowsOk).toBe(true);
    expect(attention.overflow).toBeLessThanOrEqual(0);
  });
}
