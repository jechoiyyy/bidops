import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {mockApi, mockDocumentPreparationVisual} from './api-mock';
const fixture=JSON.parse(readFileSync(new URL('./fixtures/assumption-analysis.json',import.meta.url),'utf8'));
for(const width of [1280,1440]) {
  test(`가정 분석 A안 읽기와 미연결 근거 ${width}`,async({page},info)=>{
    await page.setViewportSize({width,height:width===1280?800:900});
    await mockApi(page);
    await page.route(`**/api/assumption-analyses/${fixture.analysis.id}`,r=>r.fulfill({json:fixture.analysis}));
    await page.goto(`/assumption-analyses/${fixture.analysis.id}`);
    const reader=page.getByRole('region',{name:'가정 분석 보고서',exact:true});
    await expect(reader).toBeVisible();
    await expect(page.getByRole('navigation',{name:'보고서 목차'}).getByRole('link')).toHaveCount(8);
    await expect(reader).toContainText('실제 Luna 참조 분석 · 품질 미측정');
    await expect(reader).toContainText('가상 회사 정보 포함');
    await expect(reader.getByRole('table').getByRole('row')).toHaveCount(13);
    await page.screenshot({path:info.outputPath('report.png')});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    const trigger=reader.locator('[data-section="assessment"]').getByRole('button',{name:'근거 2개 확인'});
    await trigger.click();
    const panel=page.getByRole('complementary',{name:'원문 근거 패널'});
    await expect(panel).toContainText('근거 미연결');
    await expect(panel).toContainText('실제 근거로 취급하지 않습니다');
    await expect(panel).toContainText('승인된 입력 원문');
    await expect(panel).toContainText(fixture.analysis.sources.find((s:{id:string})=>s.id==='document-1').text);
    await page.screenshot({path:info.outputPath('unlinked-evidence.png')});
    await page.getByRole('button',{name:'근거 닫기',exact:true}).click();
    await expect(trigger).toBeFocused();
    await page.getByRole('button',{name:'글자 크게',exact:true}).click();
    await expect(reader).toHaveClass(/is-large/);
    await page.getByRole('button',{name:'본문 집중',exact:true}).click();
    await expect(page.getByRole('navigation',{name:'보고서 목차'})).toBeHidden();
    await page.getByRole('button',{name:'기본 화면',exact:true}).click();
    await page.getByRole('navigation',{name:'보고서 목차'}).getByRole('link',{name:'08 · 판단 변경 조건'}).click();
    await expect(page.getByRole('navigation',{name:'보고서 목차'}).getByRole('link',{name:'08 · 판단 변경 조건'})).toHaveAttribute('aria-current','location');
    const download=page.waitForEvent('download');
    await page.getByRole('button',{name:'본문 내려받기',exact:true}).click();
    const file=await download;
    const content=readFileSync((await file.path())!,'utf8');
    expect(content).toContain(fixture.analysis.report.sections[0].paragraphs[0].body);
    expect(content).toContain('13,799,849원');
  });
}

test('가정 분석 실패에도 앞선 부분 결과를 표시한다',async({page})=>{
  await mockApi(page);
  await page.route(`**/api/assumption-analyses/${fixture.analysis.id}`,r=>r.fulfill({json:{...fixture.analysis,status:'failed',report:null,error_code:'output_truncated',stages:fixture.analysis.stages.slice(0,1)}}));
  await page.goto(`/assumption-analyses/${fixture.analysis.id}`);
  await expect(page.getByRole('article',{name:'가정 분석 본문'})).toContainText('부분 결과 · 최종 보고서 미완료');
  await expect(page.getByRole('article',{name:'가정 분석 본문'})).toContainText(fixture.analysis.stages[0].result.sections[0].paragraphs[0].body);
});


test('1489 상세에서 승인 전 호출 금지·변경 시 무효화·중복 제출 방지', async ({page})=>{
  await mockApi(page); await mockDocumentPreparationVisual(page,'ready',1489);
  const requests: Record<string,unknown>[]=[];
  await page.route('**/api/notices/1489/assumption-analyses', async route=>{
    if(route.request().method()==='GET') return route.fulfill({json:{items:[]}});
    requests.push(route.request().postDataJSON());
    await route.fulfill({status:409,json:{error:{code:'preview_changed',message:'입력 변경 — 새 미리보기를 확인하십시오'}}});
  });
  await page.route('**/api/notices/1489/assumption-analysis-previews', route=>route.fulfill({json:fixture.preview}));
  await page.goto('/pre-specs/1489');
  await page.getByLabel('문서 준비 담당자 이름').fill('tester');
  await page.getByRole('button',{name:'가정 분석 입력 미리보기'}).click();
  const submit=page.getByRole('button',{name:'승인하고 가정 분석 요청'});
  await expect(submit).toBeDisabled();
  expect(requests).toHaveLength(0);
  await page.getByRole('checkbox',{name:'이 입력과 가정 및 같은 실행의 선행 결과를 Luna로 전송하는 데 동의합니다'}).check();
  // Same-frame synthetic submissions specifically exercise the synchronous lock.
  await submit.evaluate(button=>{(button as HTMLButtonElement).click();(button as HTMLButtonElement).click();});
  await expect(page.getByRole('region',{name:'가정 분석 요청'})).toContainText('입력 변경');
  expect(requests).toHaveLength(1);
  await expect(page.getByRole('region',{name:'가정 분석 전송 승인'})).toHaveCount(0);
});
