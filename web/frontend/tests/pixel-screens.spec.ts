import { expect, test } from "@playwright/test";
import {
  installScreenFixtures,
  lifecycleVisualTargets,
  pages,
  settleFonts,
} from "./screen-fixtures";

// 픽셀 층 — 앱이 자기 화면을 찍어 둔 **회귀** 기준선이다. 승인된 시안이 아니다
// (시안 대조는 `tests/design-snapshots/`가 따로 갖는다). 여기가 깨졌다는 것은
// "이 화면이 틀렸다"가 아니라 "지난 기준선과 달라졌다"는 뜻이고, 의도한 변경이면
// 기준선을 갈아 끼운다.
//
// 게이트에서 빠져 있고 `npm run test:pixel`로만 돈다. 기준선 교체는
// `docs/standards.md`가 정한 승인 기록을 남긴 뒤에만 한다.
//
// **화면을 전부 찍지 않는다.** 통짜 스냅샷 서른여섯 장은 화면을 건드릴 때마다
// 기준선 커밋을 끌고 오면서, 정작 잡아 주는 것은 아래 골격 여덟 가지가 거의 다다.
// 나머지 화면은 `overflow.spec.ts`(구조)와 `screen-semantics.spec.ts`(의미)가 본다.
const REPRESENTATIVE = [
  "dashboard", // 셸 · 요약 · 퍼널
  "criteria", // 기준·운영 탭 화면
  "order-plans-list", // 목록·상세 split과 pane 바닥 결정
  "order-plan-detail", // 상세 3종 골격
  "pre-specs-list", // 접이식 상태 그룹
  "opportunities-list", // 사업 추적 구역
  "deep-review-complete", // 본문 반복 목록 · 근거 rail
  "bid-delta-changed", // 비교 표
] as const;

installScreenFixtures();

const simpleTargets = pages.filter((target) => REPRESENTATIVE.includes(target.name as never));
const setupTargets = lifecycleVisualTargets.filter((target) => REPRESENTATIVE.includes(target.name as never));

test("대표 화면 목록이 실제 타깃과 어긋나지 않는다", () => {
  const resolved = [...simpleTargets, ...setupTargets].map((target) => target.name).sort();
  expect(resolved).toEqual([...REPRESENTATIVE].sort());
});

for (const target of simpleTargets) {
  test(`${target.name} 화면 스냅샷`, async ({ page }) => {
    await page.goto(target.path);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`${target.name}.png`, {
      fullPage: true,
      animations: "disabled",
    });
  });
}

for (const target of setupTargets) {
  test(`${target.name} 화면 스냅샷`, async ({ page }) => {
    await target.setup(page);
    await page.goto(target.path);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await settleFonts(page);
    if (target.name === "opportunities-list") {
      // 세 fixture 모두 미선택·재검토 신호·후보 확인 대기 중 하나를 갖고 있어
      // 기본 구역인 `조치 필요`에 모인다(ADR-0046 결정 2).
      await expect(page.locator(".opportunity-list-scroll > .review-dense-list-row")).toHaveCount(3);
    }
    await expect(page).toHaveScreenshot(`${target.name}.png`, {
      fullPage: true,
      animations: "disabled",
    });
  });
}
