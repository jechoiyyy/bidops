import { expect, test } from '@playwright/test';
import { mockApi } from './api-mock';
import type { PageOverviewResponse, PageOverviewView } from '../src/lib/types';

const fact = { text: '기존 RCMS 연계 모듈을 전환하고 업무 연속성을 확보한다. (PDF 3페이지)', evidence_pages: [3] };
const response: PageOverviewResponse = {
  schema_version: 'bidops.prespec-overview-pages.v1', notice_id: 991,
  reviews: [{ id: '00000000-0000-0000-0000-000000000614', notice_id: 991,
    document_version_id: '00000000-0000-0000-0000-000000000001', source_sha256: 'a'.repeat(64), pdf_sha256: 'b'.repeat(64),
    pdf_page_count: 100, reviewed_pages: [3, 4, 5, 6], payload_sha256: 'c'.repeat(64),
    validation_status: 'failed', validation_errors: ['latin_term_not_on_cited_pages'], evidence_check_status: 'passed', evidence_check_errors: [],
    quality_status: 'unmeasured_reference', model_name: 'test-Qwen', prompt_version: 'test-v4', created_at: '2026-09-07T09:00:00Z',
    payload: { schema_version: 'bidops.prespec-overview-page-review.v3', business_overview: [fact],
      main_tasks: [fact, { text: '데이터를 이관하고 통합 시험을 수행한다. (PDF 4페이지 · PDF 6페이지)', evidence_pages: [4, 6] }],
      budget_and_period: [{ text: '계약체결일로부터 6개월이다.', evidence_pages: [3] }], important_conditions: [],
      reviewer_analysis: ['회사 수행 역량은 별도 대조가 필요하다.'], unknowns: ['전환 일정 확인 필요'], input_limitations: ['PDF 3–6페이지 부분 검토'] },
  }],
};

const currentFact = { text: '현재 v4 실행은 선택 PDF의 사업 범위를 기준으로 정리한다.', evidence_pages: [4] };
const completedReview: PageOverviewView = {
  ...response.reviews[0],
  id: '00000000-0000-0000-0000-000000000615',
  validation_status: 'passed',
  validation_errors: [],
  payload: {
    ...response.reviews[0].payload,
    business_overview: [currentFact],
    input_limitations: ['선택된 PDF 4페이지를 기준으로 검토했습니다.'],
  },
  prompt_version: 'prespec-v4.20260908',
  created_at: '2026-09-08T09:00:00Z',
};

function withCurrent(
  current: NonNullable<PageOverviewResponse['current']> | null,
  reviews: PageOverviewView[] = response.reviews,
): PageOverviewResponse {
  return { ...response, reviews, current };
}

for (const width of [1280, 1440]) {
  test(`page overview preserves reference failure and page links at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 900 });
    await mockApi(page);
    await page.route('**/api/pre-specs/991/overview-pages', route => route.fulfill({ json: response }));
    await page.goto('/pre-specs?notice_pk=991');
    const review = page.getByRole('region', { name: 'PDF 기반 개요 검토' });
    await expect(review).toBeVisible();
    await expect(review.getByText('검증 실패 · 사람 확인 필요')).toBeVisible();
    await expect(review.getByText('참조 실행 · 품질 미측정')).toBeVisible();
    await expect(review.getByText('사업 개요', { exact: true })).toBeVisible();
    await expect(review.getByText(fact.text)).toHaveCount(0);
    await expect(review.getByRole('link', { name: 'PDF 3페이지 ↗' }).first()).toHaveAttribute('href', /\/991\/overview-pages\/[^/]+\/pdf#page=3$/);
    await expect(review.getByText('추가 확인 사항', { exact: true })).toHaveCount(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.goto('/pre-specs/991');
    await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toBeVisible();
  });
}

test('page overview errors and wrong-notice results remain distinct from legacy records', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/pre-specs/991/overview-pages', route => route.fulfill({ status: 503, json: { error: { code: 'unavailable', message: 'unavailable' } } }));
  await page.goto('/pre-specs?notice_pk=991');
  await expect(page.getByText('PDF 기반 개요를 불러오지 못했습니다.', { exact: false })).toBeVisible();
  await page.route('**/api/pre-specs/991/overview-pages', route => route.fulfill({ json: { ...response, notice_id: 992 } }));
  await page.getByRole('button', { name: '개요 다시 불러오기' }).click();
  await expect(page.getByText('개요 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toHaveCount(0);
});

test('v4 current result is selected by result_id and terminal state refreshes related queries', async ({ page }) => {
  const requests: string[] = [];
  let overviewCalls = 0;
  page.on('request', request => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === '/api/pre-specs' || pathname === '/api/pre-specs/991/company-fit') requests.push(pathname);
  });
  await mockApi(page);
  await page.route('**/api/pre-specs/991/overview-pages', async route => {
    overviewCalls += 1;
    const body = overviewCalls === 1
      ? withCurrent({
        attempt_id: '00000000-0000-0000-0000-000000000701', status: 'queued', result_id: null,
        reason_code: null, prompt_version: 'prespec-v4.20260908', created_at: '2026-09-08T09:00:00Z',
      })
      : withCurrent({
        attempt_id: '00000000-0000-0000-0000-000000000701', status: 'completed', result_id: completedReview.id,
        reason_code: null, prompt_version: completedReview.prompt_version, created_at: completedReview.created_at,
      }, [response.reviews[0], completedReview]);
    await route.fulfill({ json: body });
  });

  await page.goto('/pre-specs?notice_pk=991');
  await expect(page.getByRole('region', { name: '현재 v4 개요 실행' })).toContainText('개요 검토 대기');
  await expect.poll(() => overviewCalls, { timeout: 12_000 }).toBeGreaterThan(1);
  await expect(page.getByRole('region', { name: '현재 v4 개요 실행' })).toContainText('개요 검토 완료');
  const currentRegion = page.getByRole('region', { name: 'PDF 기반 개요 검토' });
  await expect(currentRegion).toContainText(currentFact.text);
  await expect(currentRegion).not.toContainText(fact.text);
  await expect(currentRegion.getByRole('link', { name: 'PDF 4페이지 ↗' }).first()).toHaveAttribute('href', /00000000-0000-0000-0000-000000000615\/pdf#page=4$/);
  await expect(page.getByText('이전 개요 결과 1건', { exact: true })).toBeVisible();
  await page.getByText('이전 개요 결과 1건', { exact: true }).click();
  await expect(page.getByText(new RegExp(`결과 ID · ${response.reviews[0].id}`))).toBeVisible();
  await expect.poll(() => requests.filter(path => path === '/api/pre-specs').length, { timeout: 5_000 }).toBeGreaterThan(1);
  await expect.poll(() => requests.filter(path => path === '/api/pre-specs/991/company-fit').length, { timeout: 5_000 }).toBeGreaterThan(1);

  await page.goto('/pre-specs/991');
  await expect(page.getByRole('region', { name: '현재 v4 개요 실행' })).toContainText('개요 검토 완료');
  await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toContainText(currentFact.text);
});

test('current failure remains visible when a previous successful result exists', async ({ page }) => {
  const historicalSuccess: PageOverviewView = {
    ...completedReview,
    id: '00000000-0000-0000-0000-000000000616',
    payload: { ...completedReview.payload, business_overview: [{ text: '과거 성공 결과의 본문이다.', evidence_pages: [3] }] },
  };
  await mockApi(page);
  await page.route('**/api/pre-specs/991/overview-pages', route => route.fulfill({
    json: withCurrent({
      attempt_id: '00000000-0000-0000-0000-000000000702', status: 'failed', result_id: null,
      reason_code: 'model_validation_failed', prompt_version: 'prespec-v4.20260908', created_at: '2026-09-08T10:00:00Z',
    }, [historicalSuccess]),
  }));
  await page.goto('/pre-specs/991');

  const currentRegion = page.getByRole('region', { name: '현재 v4 개요 실행' });
  await expect(currentRegion).toContainText('개요 검토에 실패했습니다. 사람 확인이 필요합니다.');
  await currentRegion.getByText('실행 정보', { exact: true }).click();
  await expect(currentRegion).toContainText('model_validation_failed');
  await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toHaveCount(0);
  await expect(page.getByText('이전 개요 결과 1건', { exact: true })).toBeVisible();
  await page.getByText('이전 개요 결과 1건', { exact: true }).click();
  const history = page.locator('.page-overview-history');
  await expect(history.getByText(new RegExp(`결과 ID · ${historicalSuccess.id}`))).toBeVisible();
  await expect(page.getByText('과거 성공 결과의 본문이다.', { exact: true })).toBeHidden();
  await history.getByText(new RegExp(`결과 ID · ${historicalSuccess.id}`)).click();
  await expect(page.getByText('과거 성공 결과의 본문이다.', { exact: true })).toBeVisible();
});

test('current v4 body keeps long text and limitations without client truncation', async ({ page }) => {
  const longText = `${'긴 본문을 임의로 줄이지 않고 그대로 표시해야 합니다. '.repeat(80)}끝 문장`;
  const longReview: PageOverviewView = {
    ...completedReview,
    id: '00000000-0000-0000-0000-000000000617',
    payload: { ...completedReview.payload, business_overview: [{ text: longText, evidence_pages: [4] }] },
  };
  await mockApi(page);
  await page.route('**/api/pre-specs/991/overview-pages', route => route.fulfill({
    json: withCurrent({
      attempt_id: '00000000-0000-0000-0000-000000000703', status: 'completed', result_id: longReview.id,
      reason_code: null, prompt_version: longReview.prompt_version, created_at: longReview.created_at,
    }, [longReview]),
  }));
  await page.goto('/pre-specs?notice_pk=991');
  const currentRegion = page.getByRole('region', { name: 'PDF 기반 개요 검토' });
  await expect(currentRegion).toContainText(longText);
  await expect(currentRegion.getByRole('link', { name: 'PDF 4페이지 ↗' }).first()).toHaveAttribute('href', /00000000-0000-0000-0000-000000000617\/pdf#page=4$/);
  await expect(currentRegion).toContainText('선택된 PDF 4페이지를 기준으로 검토했습니다.');
});

/** R7 범위 확인: 결정적 선택기가 범위를 못 정한 target을 사람이 확정한다. */
const rangeCandidates = [
  { index: 0, title: '1. 사업 개요', page: 4, char_count: 120 },
  { index: 1, title: '2. 사업 범위 및 기간', page: 6, char_count: 340 },
  { index: 2, title: '3. 제출 서류', page: 12, char_count: 90 },
];
const pendingRangeReview: NonNullable<PageOverviewResponse['range_review']> = {
  target_id: '00000000-0000-0000-0000-000000000801',
  snapshot_id: '00000000-0000-0000-0000-000000000802',
  selection_status: 'needs_human_review',
  reason_code: 'scope_heading_missing',
  pdf_page_count: 79,
  created_at: '2026-09-10T01:00:00Z',
  candidates_mode: 'clause',
  candidates: rangeCandidates,
  assisted: { start_index: 1, end_index: 2, model_name: 'test-Qwen', quality_status: 'unmeasured_reference', created_at: '2026-09-10T01:05:00Z' },
  confirmation: null,
};

test('pending range review confirms a clause range and refetches the overview', async ({ page }) => {
  const posts: Array<{ body: unknown; actor: string | undefined; method: string }> = [];
  let overviewCalls = 0;
  await mockApi(page);
  await page.route('**/api/pre-specs/991/overview-pages/range-confirmations', async route => {
    const request = route.request();
    posts.push({ body: request.postDataJSON(), actor: request.headers()['x-bidops-actor-name'], method: request.method() });
    await route.fulfill({
      status: 201,
      json: { target_id: '00000000-0000-0000-0000-000000000803', selection_status: 'ready', first_page: 6, last_page: 12, page_numbers: [6, 7, 8, 9, 10, 11, 12], attempt_enqueued: false },
    });
  });
  await page.route('**/api/pre-specs/991/overview-pages', async route => {
    overviewCalls += 1;
    await route.fulfill({ json: { ...response, range_review: pendingRangeReview } });
  });

  await page.goto('/pre-specs?notice_pk=991');
  const region = page.getByRole('region', { name: '개요 범위 확인' });
  await expect(region).toContainText('범위 확인 필요');
  await expect(region).toContainText('범위 제목을 찾지 못함');
  await expect(region).toContainText('확정해도 개요 검토는 자동 실행되지 않습니다.');
  // 제안은 미리 고르기만 한다. 모델이 적은 사유 문장은 계약에 없으므로 없다.
  await expect(region).toContainText('모델 제안 · 참조 실행 · 품질 미측정: 시작 #1 → 끝 #2');
  const table = region.getByRole('table');
  for (const candidate of rangeCandidates) await expect(table).toContainText(candidate.title);
  await expect(table).toContainText('12쪽');

  const confirm = region.getByRole('button', { name: '범위 확정' });
  await expect(confirm).toBeDisabled();
  // 끝이 시작보다 앞이면 저장할 수 없다.
  await region.getByRole('radio', { name: '끝 #0' }).check();
  await region.getByRole('radio', { name: '시작 #1' }).check();
  await expect(region.getByText('끝 절은 시작 절과 같거나 뒤여야 합니다')).toBeVisible();
  await expect(confirm).toBeDisabled();

  await region.getByRole('radio', { name: '끝 #2' }).check();
  await expect(region.getByText('끝 절은 시작 절과 같거나 뒤여야 합니다')).toHaveCount(0);
  await expect(confirm).toBeDisabled();
  await region.getByLabel('담당자 이름 (필수)').fill('최정인');
  await expect(confirm).toBeEnabled();

  const callsBeforeConfirm = overviewCalls;
  await confirm.click();
  await expect(region.getByText('범위가 확정되었습니다 · 개요 검토는 자동 실행되지 않습니다')).toBeVisible();
  expect(posts).toHaveLength(1);
  expect(posts[0].method).toBe('POST');
  expect(posts[0].body).toEqual({
    target_id: pendingRangeReview.target_id,
    start_index: 1,
    end_index: 2,
    first_page: null,
    last_page: null,
    note: null,
  });
  // 담당자 이름은 감사 표식이다. 비ASCII는 계약대로 percent 인코딩돼 실린다.
  const actorHeader = posts[0].actor ?? '';
  expect(actorHeader.startsWith("UTF-8''")).toBe(true);
  expect(decodeURIComponent(actorHeader.slice(7))).toBe('최정인');
  await expect.poll(() => overviewCalls, { timeout: 5_000 }).toBeGreaterThan(callsBeforeConfirm);
});

test('range review without clause candidates confirms a page range', async ({ page }) => {
  const posts: unknown[] = [];
  await mockApi(page);
  await page.route('**/api/pre-specs/991/overview-pages/range-confirmations', async route => {
    posts.push(route.request().postDataJSON());
    await route.fulfill({
      status: 201,
      json: { target_id: '00000000-0000-0000-0000-000000000804', selection_status: 'ready', first_page: 4, last_page: 9, page_numbers: [4, 5, 6, 7, 8, 9], attempt_enqueued: false },
    });
  });
  await page.route('**/api/pre-specs/991/overview-pages', route => route.fulfill({
    json: { ...response, range_review: { ...pendingRangeReview, candidates_mode: null, candidates: [], assisted: null } },
  }));

  await page.goto('/pre-specs?notice_pk=991');
  const region = page.getByRole('region', { name: '개요 범위 확인' });
  await expect(region).toContainText('절 후보가 없어 쪽 범위로 확정합니다.');
  await expect(region.getByRole('table')).toHaveCount(0);

  const confirm = region.getByRole('button', { name: '범위 확정' });
  await region.getByLabel('시작 쪽').fill('4');
  await region.getByLabel('시작 쪽').press('Enter');
  await region.getByLabel('끝 쪽').fill('9');
  await region.getByLabel('끝 쪽').press('Enter');
  await region.getByLabel('담당자 이름 (필수)').fill('hong');
  await expect(confirm).toBeEnabled();
  await confirm.click();

  await expect(region.getByText('범위가 확정되었습니다 · 개요 검토는 자동 실행되지 않습니다')).toBeVisible();
  expect(posts).toEqual([{
    target_id: pendingRangeReview.target_id,
    start_index: null,
    end_index: null,
    first_page: 4,
    last_page: 9,
    note: null,
  }]);
});

test('confirmed range review renders the read-only summary on the detail record', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/pre-specs/991/overview-pages', route => route.fulfill({
    json: {
      ...response,
      range_review: {
        ...pendingRangeReview,
        selection_status: 'ready',
        reason_code: null,
        assisted: null,
        confirmation: {
          target_id: '00000000-0000-0000-0000-000000000805',
          confirmed_from_target_id: pendingRangeReview.target_id,
          start_index: 1,
          end_index: 2,
          first_page: 6,
          last_page: 12,
          page_numbers: [6, 7, 8, 9, 10, 11, 12],
          actor: '최정인',
          note: null,
          created_at: '2026-09-10T02:00:00Z',
        },
      },
    },
  }));

  await page.goto('/pre-specs/991');
  const region = page.getByRole('region', { name: '개요 범위 확인' });
  await expect(region).toContainText('범위 확정됨');
  await expect(region).toContainText('6~12쪽');
  await expect(region).toContainText('2. 사업 범위 및 기간');
  await expect(region).toContainText('3. 제출 서류');
  await expect(region).toContainText('최정인');
  await expect(region).toContainText('개요 검토(attempt)는 별도 승인으로만 실행됩니다');
  await expect(region.getByRole('button', { name: '범위 확정' })).toHaveCount(0);
});
