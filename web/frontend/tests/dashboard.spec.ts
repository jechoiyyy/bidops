import { expect, test } from "@playwright/test";
import { DASH_RUN, HOLD_NOW, OTHER_RUN, dashboardMetrics, dashboardNotices, dashboardStats, dashboardWorkload, holdReviewItems, holdReviewList, mockDashboard } from "./dashboard-fixtures";
import { settleFonts } from "./screen-fixtures";
import { mockApi, mockOrderPlans } from "./api-mock";

const selected = `/?run=${DASH_RUN}`;
const UI_SCALE = 0.9;
const physical = (logical: number) => logical * UI_SCALE;
for (const [width,height] of [[1280,800],[1440,900]]) {
  test(`승인 시안 배치·글자·기본 세 공고가 보인다 ${width}`, async ({page},info)=>{
    const {writes}=await mockDashboard(page);
    await page.setViewportSize({width,height});await page.goto(selected);await settleFonts(page);
    await expect(page.locator('.dash-notice-link')).toHaveCount(3);
    await expect(page.getByRole('group',{name:'담당자 리뷰',exact:true})).toContainText('32');
    const measured=await page.evaluate(()=>{
      const rect=(s:string)=>document.querySelector(s)!.getBoundingClientRect();
      const title=document.querySelector('.dash-notice-title')!,agency=document.querySelector('.dash-notice-agency')!;
      const links=[...document.querySelectorAll('.dash-notice-link')];
      return {overflow:document.documentElement.scrollWidth-innerWidth,footer:rect('.dash-dashboard-foot').bottom,
        third:links[2].getBoundingClientRect().bottom,body:rect('.dash-deadlines-panel .dash-panel-body').bottom,
        font:getComputedStyle(title).fontSize,agencyFont:getComputedStyle(agency).fontSize,weight:getComputedStyle(agency).fontWeight,
        first:rect('.dash-journey-strip').top, left:rect('.dash-journey-strip').left,
        widths:[rect('.dash-deadlines-panel').width,rect('.dash-requests-panel').width]};
    });
    expect(measured.overflow).toBe(0);expect(measured.footer).toBeLessThanOrEqual(height);
    expect(measured.third).toBeLessThanOrEqual(measured.body+1);
    expect(measured.font).toBe('13.5px');expect(measured.agencyFont).toBe('13.5px');expect(measured.weight).toBe('600');
    expect(measured.first).toBeCloseTo(physical(92), 0);expect(measured.left).toBeCloseTo(physical(272), 0);
    expect(measured.widths[0]/(measured.widths[0]+measured.widths[1])).toBeCloseTo(.67,2);
    await page.screenshot({path:info.outputPath(`dashboard-${width}.png`),animations:'disabled'});expect(writes).toEqual([]);
  });
  test(`긴 한글 사업명·기관명과 하단 조작 유지 ${width}`,async({page},info)=>{
    const rows=structuredClone(dashboardNotices);
    rows[0].title='공공데이터 통합관리체계 고도화 및 산하기관 데이터 품질관리·공동활용 기반 구축 사업';
    rows[0].agency='해솔특별자치시 디지털혁신본부 공공데이터정책과';
    await mockDashboard(page,{stats:{imminent_deadlines:rows}});await page.setViewportSize({width,height});await page.goto(selected);
    await expect(page.locator('.dash-notice-title').first()).toContainText('공동활용');
    await expect(page.getByRole('button',{name:'전체 보기',exact:true})).toBeInViewport();
    await page.locator('.dash-notice-link').last().scrollIntoViewIfNeeded();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBe(0);
    await page.screenshot({path:info.outputPath(`dashboard-long-${width}.png`),animations:'disabled'});
  });
}

test('회차 미선택을 유지하면서 네 누적 업무로 이동한다',async({page})=>{
  await mockDashboard(page);await page.goto('/');
  await expect(page.getByRole('heading',{name:'확인할 회차를 선택해 주세요'})).toBeVisible();
  expect(new URL(page.url()).searchParams.has('run')).toBe(false);
  const links=page.locator('.dash-journey-item');await expect(links).toHaveCount(4);
  await expect(links.nth(0)).toContainText('검토 후보 24건');
  await expect(links.nth(1)).toContainText('결정 대기 7건');
  await expect(links.nth(2)).toContainText('조치 필요 3건');
  await expect(links.nth(3)).toContainText('결정 대기 0건');
  await expect(links.nth(2)).toHaveAttribute('href','/opportunities?section=조치 필요');
  await expect(links.nth(3)).toHaveAttribute('href','/go-no-go');
});

test('회차·필터 URL 복원과 누적 집계 독립성',async({page})=>{
  await mockDashboard(page);await page.goto(`${selected}&from=bookmark`);
  await expect(page.locator('.dash-journey-item').first()).toContainText('24건');
  await page.getByRole('combobox',{name:'마감 공고 필터'}).click();await page.getByRole('option',{name:'3일 이내',exact:true}).click();
  await expect(page.locator('.dash-notice-link')).toHaveCount(2);
  await page.reload();await expect(page.getByRole('combobox',{name:'마감 공고 필터'})).toContainText('3일 이내');
  await page.getByRole('button',{name:'조회할 실행 회차'}).click();await page.getByRole('option',{name:new RegExp(OTHER_RUN)}).click();
  expect(new URL(page.url()).searchParams.get('run')).toBe(OTHER_RUN);expect(new URL(page.url()).searchParams.get('from')).toBe('bookmark');
  expect(new URL(page.url()).searchParams.has('deadline')).toBe(false);
  await expect(page.getByRole('group',{name:'수집',exact:true})).toContainText('840');
  await expect(page.locator('.dash-journey-item').first()).toContainText('24건');
  await page.goBack();expect(new URL(page.url()).searchParams.get('run')).toBe(DASH_RUN);
});

test('회차를 비우고 새로 고쳐도 자동 최신 선택하지 않는다',async({page})=>{
  await mockDashboard(page);await page.goto(selected);
  await page.getByRole('button',{name:'조회할 실행 회차'}).click();await page.getByRole('option',{name:'회차 선택 안 함',exact:true}).click();
  await page.reload();await expect(page.getByRole('heading',{name:'확인할 회차를 선택해 주세요'})).toBeVisible();
  expect(new URL(page.url()).searchParams.has('run')).toBe(false);
});

test('전체 보기와 확인 요청 펼치기',async({page})=>{
  await mockDashboard(page,{stats:{verification_requests:[...dashboardStats.verification_requests,{item:'추가 증빙',count:0,notice_pks:[],profile_sections:[]}]}});
  await page.goto(selected);await page.getByRole('button',{name:'전체 보기',exact:true}).click();await expect(page.locator('.dash-notice-link')).toHaveCount(5);
  await page.getByRole('button',{name:'확인 요청 전체 보기'}).click();await expect(page.locator('#dashboard-verification-list li')).toHaveCount(4);
  await page.getByRole('button',{name:'확인 요청 접기'}).click();await expect(page.locator('#dashboard-verification-list li')).toHaveCount(3);
});

test('미확인·값 없음·실제 0을 구분하고 검토 대기를 리뷰 수로 대신하지 않는다',async({page})=>{
  await mockDashboard(page,{stats:{collected_count:null,candidate_count:0,audit_missed_count:0,imminent_deadlines:[{...dashboardNotices[0],agency:null,grade:null}]}});
  await page.goto(selected);await expect(page.getByRole('group',{name:'수집',exact:true})).toContainText('값 없음');
  await expect(page.getByRole('group',{name:'후보 풀',exact:true})).toContainText('0건');
  await expect(page.getByRole('group',{name:'담당자 리뷰',exact:true})).toContainText('32건');
  await expect(page.getByRole('group',{name:'담당자 리뷰',exact:true})).not.toContainText('148');
  await expect(page.locator('.dash-notice-agency')).toHaveText('발주기관 미확인');await expect(page.locator('.dash-deadlines-panel')).toContainText('판정 없음');
  await expect(page.getByRole('group',{name:'1차 필터 누락'})).toContainText('누락률 계산 불가');
});

test('마감은 회차 시각으로 계산하고 지난 날짜·미확인 날짜는 임박으로 세지 않는다',async({page})=>{
  await page.clock.setFixedTime(new Date('2028-01-01T00:00:00Z'));
  await mockDashboard(page,{stats:{imminent_deadlines:[...dashboardNotices,{...dashboardNotices[0],id:98,title:'지난 공고',deadline_at:'2026-09-06T08:00:00Z'},{...dashboardNotices[0],id:99,title:'날짜 미확인',deadline_at:null}]}});
  await page.goto(selected);await expect(page.locator('.dash-deadlines-panel')).toContainText('D-1');
  await expect(page.locator('.dash-deadlines-panel .dash-panel-foot')).toContainText('3 / 5건');
});

test('빈 회차의 목록과 검증 없음은 성공으로 표시하지 않는다',async({page})=>{
  await mockDashboard(page,{stats:{collected_count:0,candidate_count:0,sample_count:0,imminent_deadlines:[],verification_requests:[],grade_distribution:[]},metrics:{run_id:DASH_RUN,metrics:[]}});
  await page.goto(selected);await expect(page.getByText('조건에 맞는 마감 공고가 없습니다')).toBeVisible();
  await expect(page.locator('.dash-validation-panel')).toContainText('검증 지표 없음');
  await expect(page.locator('.dash-validation-panel')).not.toContainText('통과');
});

test('회차 조회 실패 뒤 재조회하며 누적 진입점을 유지한다',async({page})=>{
  const options={statsError:true};await mockDashboard(page,options);await page.goto(selected);
  await expect(page.getByRole('heading',{name:'회차 자료를 불러오지 못했습니다'})).toBeVisible();
  await expect(page.locator('.dash-journey-item')).toHaveCount(4);await expect(page.locator('.dash-dashboard-grid')).toHaveCount(0);
  options.statsError=false;await page.getByRole('button',{name:'회차 자료 다시 조회'}).click();await expect(page.locator('.dash-notice-link')).toHaveCount(3);
});

test('검증 지표만 실패해도 다른 회차 자료를 가리지 않는다',async({page})=>{
  const options={metricsError:true};await mockDashboard(page,options);await page.goto(selected);
  await expect(page.locator('.dash-validation-panel').getByRole('alert')).toBeVisible();await expect(page.locator('.dash-notice-link')).toHaveCount(3);
  options.metricsError=false;await page.getByRole('button',{name:'검증 지표 다시 조회'}).click();await expect(page.locator('.dash-validation-panel').getByRole('alert')).toHaveCount(0);
});

test('회차 목록과 후보 조회 실패를 0으로 표시하지 않는다',async({page})=>{
  await mockDashboard(page,{runsError:true,workloadError:true});await page.goto(selected);
  await expect(page.getByText('회차 목록을 불러오지 못했습니다.')).toBeVisible();
  await expect(page.locator('.dash-journey-item').first()).toContainText('검토 후보 건수 미확인');
  await expect(page.getByRole('group',{name:'담당자 리뷰',exact:true})).toContainText('미확인');
});

test('누적 건수를 낼 수 없으면 사유를 남기고 0으로 채우지 않는다',async({page})=>{
  await mockDashboard(page,{workload:{...dashboardWorkload,items:dashboardWorkload.items.map(item=>item.key==='order_plan_pending' ? {...item,count:null,unavailable_reason:'no_completed_execution'} : item)}});
  await page.goto(selected);const first=page.locator('.dash-journey-item').first();
  await expect(first).toContainText('검토 후보 건수 미확인');await expect(first).toContainText('완료된 선별 실행 없음');
  await expect(first).not.toContainText('건 · 누적');
});

test('계산 불가 지표를 통과로 바꾸지 않고 미달부터 표시한다',async({page})=>{
  const unavailable=dashboardMetrics.metrics[0];
  await mockDashboard(page,{metrics:{run_id:DASH_RUN,metrics:[unavailable,{...unavailable,key:'failed',label:'근거 검증',status:'fail',value:.3,percentage:30,reason:'검증 기준 미달'}]}});
  await page.goto(selected);const rows=page.locator('.dash-validation-row');await expect(rows.nth(1)).toContainText('근거 검증');
  await expect(rows.nth(1)).toContainText('미달');await expect(rows.nth(2)).toContainText('계산 불가');
});

test('공고·등급·프로필·실행 링크가 회차를 보존하고 헤더는 이동 뒤 정리된다',async({page})=>{
  await mockDashboard(page);await page.goto(selected);
  await expect(page.locator('.dash-notice-link').first()).toHaveAttribute('href',`/judgments/1?run=${DASH_RUN}`);
  const gradeUrl=new URL(await page.locator('.dash-grade-item').first().getAttribute('href') ?? '', 'http://test');
  expect(gradeUrl.searchParams.get('grade')).toBe('우선 검토');expect(gradeUrl.searchParams.get('run')).toBe(DASH_RUN);
  await expect(page.getByRole('link',{name:'회사 프로필',exact:true})).toHaveAttribute('href',`/profile?run=${DASH_RUN}`);
  await expect(page.getByRole('link',{name:'회차 실행 보기',exact:true})).toHaveAttribute('href',`/runs?run=${DASH_RUN}`);
  await page.getByRole('link',{name:'회사 프로필',exact:true}).click();await expect(page.locator('.crit-page')).toBeVisible();
  await expect(page.locator('.dash-header-actions')).toHaveCount(0);
});


test('기준 시각이 없으면 마감 0건으로 확정하지 않는다', async ({page}) => {
  await mockDashboard(page, {stats: {generated_at: ''}});
  await page.goto(selected);
  const panel = page.getByRole('region', {name: '마감 공고', exact: true});
  await expect(panel).toContainText('건수 미확인');
  await expect(panel).toContainText('마감 범위를 확인할 수 없습니다');
  await expect(panel).not.toContainText('0건');
});

test('회차 자료를 기다리는 동안 누적 바로가기를 사용할 수 있다', async ({page}) => {
  await mockDashboard(page);
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/runs/*/stats', async route => {
    await pending;
    await route.fallback();
  });
  try {
    await page.goto(selected);
    await expect(page.getByRole('heading', {name: '회차 자료를 불러오는 중입니다'})).toBeVisible();
    await expect(page.locator('.dash-journey-item')).toHaveCount(4);
    await expect(page.locator('.dash-dashboard-grid')).toHaveCount(0);
  } finally { release(); }
  await expect(page.locator('.dash-notice-link')).toHaveCount(3);
});

const holdWorkload = (count: number | null) => ({...dashboardWorkload,items:dashboardWorkload.items.map(item=>item.key==='tracking_hold_review_due' ? {...item,count,unavailable_reason:count===null ? 'provider_absent' : null} : item)});

test('보류 재검토는 회차 없이 기한순 5건을 한국 날짜 D+n·D-n으로 보여 준다', async ({page}) => {
  await page.clock.setFixedTime(new Date(HOLD_NOW));
  const {holdRequests} = await mockDashboard(page, {holdReviews: holdReviewList(holdReviewItems, 7), workload: holdWorkload(2)});
  await page.goto('/');
  await expect(page.getByRole('heading', {name: '확인할 회차를 선택해 주세요'})).toBeVisible();
  const panel = page.getByRole('region', {name: '보류 재검토', exact: true});
  await expect(panel).toContainText('보류는 선택 후 14일이 지나면 다시 검토합니다.');
  await expect(panel.locator('.dash-panel-head')).toContainText('기한 지남 2건');
  const rows = panel.getByRole('row');
  await expect(rows).toHaveCount(6);
  expect(holdRequests).toHaveLength(1);
  expect(Object.fromEntries(holdRequests[0])).toEqual({hold_review: 'attention', sort: 'hold_review_due_at', limit: '5'});
  await expect(rows.nth(1)).toContainText('공공데이터 통합관리체계 고도화');
  await expect(rows.nth(1)).toContainText('예산 편성 결과를 확인한 뒤 다시 검토');
  await expect(rows.nth(1)).toContainText('기한 지남 D+3');
  await expect(rows.nth(1)).toContainText('김보류');
  // 같은 한국 날짜에 지난 기한은 D+0이고, 사유·선택자·제목이 없으면 미확인으로 남긴다.
  await expect(rows.nth(2)).toContainText('제목 미확인');
  await expect(rows.nth(2)).toContainText('사유 미확인');
  await expect(rows.nth(2)).toContainText('기한 지남 D+0');
  await expect(rows.nth(2)).toContainText('선택자 미확인');
  // UTC로는 같은 날이지만 한국 시간으로는 다음 날 00:30이다.
  await expect(rows.nth(3)).toContainText('D-1');
  await expect(rows.nth(3)).toContainText('09.18 00:30');
  await expect(rows.nth(3)).not.toContainText('기한 지남');
  await expect(rows.nth(4)).toContainText('D-2');
  await expect(rows.nth(4)).toContainText('사유 미확인');
  await expect(rows.nth(5)).toContainText('D-3');
  await expect(rows.nth(1).getByRole('link')).toHaveAttribute('href', '/opportunities/401');
  await expect(rows.nth(2).getByRole('link')).toHaveAttribute('href', '/opportunities/402');
  await expect(panel.locator('.dash-panel-foot')).toContainText('기한 지남·임박 7건 중 5건 표시');
  const all = new URL(await panel.getByRole('link', {name: '사업 추적에서 모두 보기', exact: true}).getAttribute('href') ?? '', 'http://test');
  expect(all.pathname).toBe('/opportunities');
  expect(Object.fromEntries(all.searchParams)).toEqual({section: '조치 필요', reason: 'hold_overdue'});
});

test('보류 기한 지남 건수를 받지 못하면 0건으로 채우지 않는다', async ({page}) => {
  await mockDashboard(page, {holdReviews: holdReviewList(holdReviewItems.slice(0, 1)), workload: holdWorkload(null)});
  await page.goto(selected);
  const head = page.getByRole('region', {name: '보류 재검토', exact: true}).locator('.dash-panel-head');
  await expect(head).toContainText('기한 지남 건수 미확인');
  await expect(head).not.toContainText('0건');
  await expect(page.locator('.dash-journey-item').nth(2)).toContainText('조치 필요 3건');
});

test('보류 재검토의 로딩·조회 실패·빈 목록을 문자로 구분하고 다시 조회한다', async ({page}) => {
  const options = {holdReviewError: true};
  await mockDashboard(page, options);
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route(url => url.pathname === '/api/opportunities', async route => { await pending; await route.fallback(); });
  const panel = page.getByRole('region', {name: '보류 재검토', exact: true});
  // Astryx Button은 자기 live region(role=status)을 품으므로 상태 문구는 패널 본문에서 찾는다.
  const body = panel.locator('.dash-panel-body');
  try {
    await page.goto('/');
    await expect(body.getByRole('status')).toHaveText('보류 재검토 목록을 불러오는 중입니다.');
    await expect(panel.locator('.dash-panel-foot')).toContainText('건수 확인 중');
  } finally { release(); }
  await expect(panel.getByRole('alert')).toContainText('보류 재검토 목록을 불러오지 못했습니다.');
  await expect(panel.locator('.dash-panel-foot')).toContainText('건수 미확인');
  await expect(panel).not.toContainText('재검토가 필요한 보류 사업이 없습니다.');
  options.holdReviewError = false;
  await panel.getByRole('button', {name: '보류 재검토 다시 조회', exact: true}).click();
  await expect(body.getByRole('status')).toHaveText('재검토가 필요한 보류 사업이 없습니다.');
  await expect(panel.getByRole('alert')).toHaveCount(0);
  await expect(panel.locator('.dash-panel-foot')).toContainText('기한 지남·임박 0건');
  await expect(panel.getByRole('link', {name: '사업 추적에서 모두 보기', exact: true})).toBeVisible();
});

// 대시보드의 `발주계획 · 검토 후보 N건 · 누적`은 발주계획 화면의 누적 기본 보기와 같은 집합이다(spec §7).
// 회차를 고르지 않고 들어가도 화면이 누적으로 열려 같은 건수를 보여야 `누적` 문구가 사실이다.
for (const [width,height] of [[1280,800],[1440,900]]) {
  test(`발주계획 바로가기는 회차 없이 누적 기본 보기로 열고 검토 후보 건수와 같다 ${width}`, async ({page}) => {
    await mockApi(page);await mockOrderPlans(page);
    await page.setViewportSize({width,height});await page.goto('/');
    const entry=page.locator('.dash-journey-item').first();
    await expect(entry).toContainText('검토 후보 2건');
    await entry.click();
    await expect.poll(()=>new URL(page.url()).pathname).toBe('/order-plans');
    expect(new URL(page.url()).searchParams.has('source_run_id')).toBe(false);
    await expect(page.getByTestId('order-plan-list-scope')).toHaveText('누적 · 판정 policy c2-policy.v1');
    await expect(page.locator('.c2l-list-head')).toContainText('현재 필터 결과 2건');
    await expect(page.locator('.c2l-row')).toHaveCount(2);
  });
}
