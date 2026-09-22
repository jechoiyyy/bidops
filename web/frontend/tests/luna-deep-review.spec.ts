import { expect, test } from '@playwright/test';
import { mockApi, mockDocumentPreparationVisual } from './api-mock';
import { readFileSync } from 'node:fs';
const fixture = JSON.parse(readFileSync(new URL('./fixtures/luna-review.json', import.meta.url), 'utf8'));

for (const viewport of [{width:1280,height:800},{width:1440,height:900}]) {
  test(`Luna 미리보기·승인·보고서 ${viewport.width}`, async ({page},info) => {
    await page.setViewportSize(viewport);
    await mockApi(page);
    await mockDocumentPreparationVisual(page,'ready');
    const requests: Record<string,unknown>[]=[];
    let verification=true;
    await page.route('**/api/notices/991/deep-review-previews',async route=>{
      verification=route.request().postDataJSON().source_verification_enabled;
      await route.fulfill({json:{...fixture.preview,source_verification_enabled:verification}});
    });
    await page.route('**/api/notices/991/deep-reviews',async route=>{
      requests.push(route.request().postDataJSON());
      await route.fulfill({status:202,json:fixture.review});
    });
    await page.route(`**/api/deep-reviews/${fixture.review.id}`,route=>route.fulfill({json:fixture.review}));
    await page.route(`**/api/deep-reviews/${fixture.review.id}/report`,route=>route.fulfill({json:fixture.report}));
    await page.route(`**/api/evidence/${fixture.evidence.evidence_id}`,route=>route.fulfill({json:fixture.evidence}));
    await page.goto('/pre-specs/991');
    await page.getByLabel('문서 준비 담당자 이름').fill('Luna 검증 담당자');
    await page.getByRole('button',{name:'전송 내용 미리보기'}).click();
    const approval=page.getByRole('region',{name:'외부 전송 승인'});
    await expect(approval.getByText('gpt-5.6-luna · xhigh · codex-exec')).toBeVisible();
    await approval.getByText('전송 원천 입력과 정책 전체 확인').click();
    await expect(approval.locator('pre')).toContainText('bidops.luna-input.v1');
    await page.screenshot({path:info.outputPath('luna-preview.png')});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await page.getByRole('button',{name:'전송 승인하고 심층검토 요청'}).click();
    await expect(page).toHaveURL(new RegExp(`/deep-reviews/${fixture.review.id}`));
    await expect(page.getByRole('article',{name:'심층검토 보고서 본문'})).toBeVisible();
    expect(requests).toHaveLength(1);
    expect(requests[0].preview_id).toBe(fixture.preview.preview_id);
    expect(requests[0].source_verification_enabled).toBe(true);
    await page.screenshot({path:info.outputPath('luna-report.png')});
    await page.locator('#narrative-delivery .narrative-sources').nth(0).getByRole('button',{name:'근거 1 확인'}).click();
    const evidence=page.getByRole('complementary',{name:'선택한 원문 근거'});
    await expect(evidence.locator('blockquote')).toHaveText(fixture.evidence.quote);
    await page.screenshot({path:info.outputPath('luna-evidence.png')});
  });
}

test('Luna 설정 변경 시 미리보기 해제와 재시도 request ID 보존',async({page})=>{
  await mockApi(page); await mockDocumentPreparationVisual(page,'ready');
  let previews=0; const requestIds:string[]=[];
  await page.route('**/api/notices/991/deep-review-previews',async route=>{
    previews++;
    await route.fulfill({json:{...fixture.preview, source_verification_enabled:route.request().postDataJSON().source_verification_enabled}});
  });
  await page.route('**/api/notices/991/deep-reviews',async route=>{
    requestIds.push(route.request().postDataJSON().request_id);
    await route.fulfill({status:503,json:{error:{code:'service_unavailable'}}});
  });
  await page.goto('/pre-specs/991');
  await page.getByLabel('문서 준비 담당자 이름').fill('tester');
  await page.getByRole('button',{name:'전송 내용 미리보기'}).click();
  await page.getByRole('button',{name:'전송 승인하고 심층검토 요청'}).click();
  const region=page.getByRole('region',{name:'Luna 심층검토 요청'});
  await expect(region.getByRole('alert')).toBeVisible();
  await page.getByRole('button',{name:'전송 승인하고 심층검토 요청'}).click();
  await expect.poll(()=>requestIds.length).toBe(2);
  expect(requestIds[0]).toBe(requestIds[1]);
  expect(previews).toBe(1);
  await page.getByRole('checkbox',{name:'원문 인용·숫자 대조'}).uncheck();
  await expect(page.getByRole('region',{name:'외부 전송 승인'})).toHaveCount(0);
  await page.getByRole('button',{name:'전송 내용 미리보기'}).click();
  await expect(page.getByText('원문 대조 사용 안 함 · 품질 미측정')).toBeVisible();
  expect(previews).toBe(2);
});
