import { test, expect } from '@playwright/test';
import { answers, sources, bundles, bundleInput } from '../src/mock-review/scenario';

test.skip(!process.env.BIDOPS_MOCK_UI, '개발 MOCK 서버 전용: BIDOPS_MOCK_UI=1 PW_PORT=<port>로 실행');

test('가상 근거와 요청 묶음은 여덟 질문을 누락 없이 연결한다',()=>{
  expect(new Set(answers.map(a=>a.id)).size).toBe(8);
  expect(bundles.flatMap(b=>b.answerIds).sort()).toEqual(answers.map(a=>a.id).sort());
  for(const a of answers) for(const id of a.refs) expect(sources.some(s=>s.id===id)).toBeTruthy();
  expect(bundleInput(2).previous).toHaveLength(2);
});
for(const viewport of [{width:1280,height:800},{width:1440,height:900}]) {
  test(`요청에서 보고서·근거까지 ${viewport.width}`,async({page})=>{
    await page.setViewportSize(viewport);
    const mutations:string[]=[];
    page.on('request',r=>{if(r.method()!=='GET') mutations.push(r.url());});
    await page.goto('/pre-specs');
    await page.getByRole('button',{name:'가상 사업 심층검토',exact:true}).click();
    await expect(page.getByRole('heading',{name:'2027년 가람연구원 연구정보시스템 유지관리'})).toBeVisible();
    await page.getByRole('button',{name:'심층검토 요청',exact:true}).click();
    await expect(page.getByRole('button',{name:'MOCK 분석 시작'})).toBeDisabled();
    await page.screenshot({path:`/tmp/mock-review-preview-${viewport.width}.png`});
    await page.getByRole('checkbox').check();
    await page.getByRole('button',{name:'MOCK 분석 시작'}).click();
    await expect(page.getByRole('region',{name:'분석 진행'})).toContainText('실행 대기');
    await page.screenshot({path:`/tmp/mock-review-progress-${viewport.width}.png`});
    await expect(page.getByRole('article',{name:'심층검토 보고서'})).toBeVisible({timeout:15000});
    for(const a of answers) await expect(page.getByText(a.question,{exact:true})).toBeAttached();
    await expect(page.getByRole('region',{name:'분석 진행'})).toContainText('3/3 단계 완료');
    await page.getByRole('region',{name:'수행과 비용에서 무엇이 위험한가?',exact:true}).getByRole('button',{name:'근거 C2',exact:true}).click();
    await expect(page.getByRole('complementary',{name:'가상 원문 근거'})).toContainText('추가 상근 1명은 채용이 필요하다');
    await page.screenshot({path:`/tmp/mock-review-evidence-${viewport.width}.png`});
    await page.getByRole('button',{name:'근거 닫기'}).click();
    await page.getByRole('article').scrollIntoViewIfNeeded();
    await page.screenshot({path:`/tmp/mock-review-report-${viewport.width}.png`});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    expect(mutations).toEqual([]);
  });
}
test('두 번째 묶음 실패와 재시작, 미처리 API 차단',async({page,request})=>{
  await page.goto('/pre-specs/mock-review');
  await page.getByLabel('모의 시나리오').selectOption('failure');
  await page.getByRole('button',{name:'심층검토 요청',exact:true}).click();
  await page.getByRole('checkbox').check();
  // Same-frame synthetic submission specifically tests the duplicate-click guard.
  await page.getByRole('button',{name:'MOCK 분석 시작'}).evaluate(el=>{(el as HTMLButtonElement).click();(el as HTMLButtonElement).click();});
  await expect(page.getByRole('alert')).toContainText('회사 대조 응답 시간 초과',{timeout:15000});
  await expect(page.getByRole('article',{name:'심층검토 보고서'})).toHaveCount(0);
  await page.getByRole('button',{name:'세 요청의 입력·응답 보기'}).click();
  await page.getByText('2. 우리 회사에 대입 · 2개 질문',{exact:true}).click();
  await expect(page.locator('details[open]').getByRole('heading',{name:'요청 입력',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'시안 처음으로'}).click();
  await expect(page.getByRole('button',{name:'심층검토 요청',exact:true})).toBeVisible();
  const response=await request.get('/api/mock-review-unhandled');
  expect(response.status()).toBe(404);
  expect(await response.json()).toEqual({detail:"고정 응답 없음"});
});
