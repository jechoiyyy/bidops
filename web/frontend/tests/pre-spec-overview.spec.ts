import { expect, test } from "@playwright/test";
import { mockApi, mockPreSpecOverview } from "./api-mock";

// 사전규격 개요 검토(`bidops.prespec-overview.v1`)를 상세 화면이 어떻게 말하는지
// 본다. 백엔드는 아직 없으므로 route mock의 run envelope 하나가 입력이다.
// 폭과 무관한 의미 층이라 한 폭(`app` project)에서만 돈다.

const OVERVIEW = { name: "개요 검토" };

test("완료된 개요는 네 항목의 주장과 인용 쪽 링크를 함께 보여준다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecOverview(page, "completed");
  await page.goto("/pre-specs/991");

  const overview = page.getByRole("region", OVERVIEW);
  await expect(overview).toBeVisible({ timeout: 10_000 });
  await expect(overview.locator(".badge")).toHaveText("완료");
  await expect(overview).toContainText("읽은 범위 · p.3–11 · 자동 선택");

  for (const title of ["사업 개요", "주요 과업", "예산과 기간", "중요 조건"]) {
    await expect(overview.getByRole("heading", { name: title })).toBeVisible();
  }
  await expect(overview).toContainText("차세대 통합 데이터 플랫폼을 구축하는 사업이다.");

  // 인용마다 그 쪽을 여는 링크가 있고, 고정 스냅샷 PDF 경로만 연다.
  const pageLink = overview.getByRole("link", { name: "p.3" });
  await expect(pageLink).toHaveAttribute(
    "href",
    "/api/pre-specs/991/overview/runs/b1a7f0c2-1111-4a11-9c11-000000000001/pdf#page=3",
  );
  await expect(pageLink).toHaveAttribute("target", "_blank");
  await expect(overview.getByRole("link", { name: "p.6" })).toBeVisible();

  // 의견·미확인·한계는 사실과 자리를 나눈다.
  await expect(overview.getByRole("heading", { name: "검토자 분석" })).toBeVisible();
  await expect(overview).toContainText("모델이 적은 의견입니다.");
  await expect(overview.getByRole("heading", { name: "확인 못 한 항목" })).toBeVisible();
  await expect(overview.getByRole("heading", { name: "입력 한계" })).toBeVisible();

  // 비차단 경고는 접힌 채로 건수를 밝힌다.
  await expect(overview.getByText("경고 3건")).toBeVisible();
  // 완료된 결과에서도 인용 대조에 실패해 제외된 주장은 접이식으로 남긴다.
  await expect(overview.getByText("제외된 주장 1건 (원문 대조 실패)")).toBeVisible();
});

test("사람 확인이 필요한 개요는 완료 본문 대신 실패한 주장만 보여준다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecOverview(page, "needs_human_review");
  await page.goto("/pre-specs/991");

  const overview = page.getByRole("region", OVERVIEW);
  await expect(overview).toBeVisible({ timeout: 10_000 });
  await expect(overview.locator(".badge")).toHaveText("사람 검토 필요");
  await expect(overview).toContainText("근거 확인 필요");
  await expect(overview).toContainText("사업 예산은 700,000,000원이다.");
  await expect(overview).toContainText("예산과 기간");
  await expect(overview).toContainText("인용문을 원문에서 찾지 못했습니다.");
  await expect(overview).toContainText("수치가 원문과 다릅니다.");
  // 검증을 통과한 인용만 근거로 남는다.
  await expect(overview.getByRole("link", { name: "p.4" })).toBeVisible();
  // 완료 본문은 만들지 않는다.
  await expect(overview.getByRole("heading", { name: "사업 개요" })).toHaveCount(0);
  await expect(overview.getByRole("heading", { name: "검토자 분석" })).toHaveCount(0);
});

test("앞부분 fallback과 실행 대기는 사유를 밝히고 범위 폼을 잠근다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecOverview(page, "fallback_queued");
  await page.goto("/pre-specs/991");

  const overview = page.getByRole("region", OVERVIEW);
  await expect(overview).toBeVisible({ timeout: 10_000 });
  await expect(overview.locator(".badge")).toHaveText("실행 대기");
  await expect(overview).toContainText("읽은 범위 · p.1–60 · 앞부분 fallback");
  await expect(overview).toContainText("범위를 자동으로 고르지 못해 문서 앞부분을 읽었습니다.");
  await expect(overview).toContainText("개요에 해당하는 제목을 찾지 못했습니다.");

  const submit = overview.getByRole("button", { name: "이 범위로 다시 검토" });
  await expect(submit).toBeDisabled();
  await expect(overview).toContainText("실행 중이거나 대기 중인 개요 검토가 끝나야");
});

test("범위를 다시 지정하면 담당자 표식과 함께 보내고 새 run을 다시 조회한다", async ({ page }) => {
  await mockApi(page);
  const trace = await mockPreSpecOverview(page, "completed");
  await page.goto("/pre-specs/991");

  const overview = page.getByRole("region", OVERVIEW);
  await expect(overview).toBeVisible({ timeout: 10_000 });
  await overview.getByLabel("시작 쪽").fill("4");
  await overview.getByLabel("끝 쪽").fill("12");
  await overview.getByLabel("메모").fill("목차 다음부터 읽습니다.");
  await overview.getByLabel("담당자 이름").fill("범위 담당자");
  await overview.getByRole("button", { name: "이 범위로 다시 검토" }).click();

  await expect.poll(() => trace.rangePosts.length).toBe(1);
  expect(trace.rangePosts[0].body).toEqual({ page_start: 4, page_end: 12, note: "목차 다음부터 읽습니다." });
  // 담당자 이름은 감사 표식 header로만 간다. body에 담지 않는다.
  expect(trace.rangePosts[0].headers["x-bidops-actor-name"]).toBeTruthy();

  await expect(overview).toContainText("새 개요 검토를 예약했습니다");
  // 재조회한 envelope의 새 run이 현재 개요가 된다.
  await expect(overview.locator(".badge")).toHaveText("실행 대기");
  await expect(overview).toContainText("읽은 범위 · p.4–12 · 담당자 지정");
  await expect(overview).toContainText("담당자가 범위를 지정했습니다.");
});
