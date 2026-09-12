import { expect, test } from '@playwright/test';
import {
  mockApi,
  overviewCompletedRunFixture,
  overviewEnvelopeFixture,
  overviewRangeCandidatesFixture,
  overviewRangeReviewFixture,
  overviewRunFixture,
  overviewVerificationFixture,
} from './api-mock';
import type { OverviewEnvelope, OverviewRun } from '../src/lib/types';

// 개요 검토 화면(`PageOverviewSection`)이 새 계약(`bidops.prespec-overview.v1`)의
// run envelope 하나를 어떻게 말하는지 본다. 백엔드는 병행 구현 중이므로 route
// mock의 envelope이 입력이다. 화면은 이 envelope을 `toPageOverviewResponse`로
// 옮겨 읽으므로 이 spec은 어댑터까지 함께 확인한다.

const OVERVIEW_PATH = '**/api/pre-specs/991/overview';
const RANGE_PATH = '**/api/pre-specs/991/overview/range-confirmations';

/** 결과가 남은 과거 실행 하나. 현재 실행이 무엇이든 과거 본문을 현재로 쓰지 않는다. */
const historicalRun: OverviewRun = {
  ...overviewCompletedRunFixture,
  id: '00000000-0000-0000-0000-000000000614',
  result_id: '00000000-0000-0000-0000-000000000614',
  created_at: '2026-09-04T09:00:00Z',
  result: {
    ...overviewCompletedRunFixture.result!,
    business_overview: [{
      claim_id: 'c1',
      text: '과거 성공 결과의 본문이다.',
      evidence: [{ page: 3, quote: '차세대 통합 데이터 플랫폼 구축' }],
    }],
  },
};

const currentFactText = overviewCompletedRunFixture.result!.business_overview[0].text;

function envelope(current: OverviewRun | null, history: OverviewRun[] = []): OverviewEnvelope {
  return overviewEnvelopeFixture(991, current, history);
}

for (const width of [1280, 1440]) {
  test(`page overview keeps the verified body and page links at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 900 });
    await mockApi(page);
    await page.route(OVERVIEW_PATH, route => route.fulfill({
      json: envelope(overviewCompletedRunFixture, [overviewCompletedRunFixture]),
    }));
    await page.goto('/pre-specs?notice_pk=991');
    const review = page.getByRole('region', { name: 'PDF 기반 개요 검토' });
    await expect(review).toBeVisible();
    await expect(review.getByText('주장 검증 완료 · 운영 승인 아님')).toBeVisible();
    await expect(review.getByText('참조 실행 · 품질 미측정')).toBeVisible();
    await expect(review.getByText('사업 개요', { exact: true })).toBeVisible();
    await expect(review).toContainText(currentFactText);
    await expect(review.getByRole('link', { name: 'PDF 3페이지 ↗' }).first()).toHaveAttribute(
      'href',
      `/api/pre-specs/991/overview/runs/${overviewCompletedRunFixture.id}/pdf#page=3`,
    );
    await expect(review.getByText('추가 확인 사항', { exact: true })).toHaveCount(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.goto('/pre-specs/991');
    await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toBeVisible();
  });
}

test('page overview errors and wrong-notice results stay distinct from a rendered review', async ({ page }) => {
  await mockApi(page);
  await page.route(OVERVIEW_PATH, route => route.fulfill({ status: 503, json: { error: { code: 'unavailable', message: 'unavailable' } } }));
  await page.goto('/pre-specs?notice_pk=991');
  await expect(page.getByText('PDF 기반 개요를 불러오지 못했습니다.', { exact: false })).toBeVisible();
  await page.route(OVERVIEW_PATH, route => route.fulfill({
    json: { ...envelope(overviewCompletedRunFixture, [overviewCompletedRunFixture]), notice_id: 992 },
  }));
  await page.getByRole('button', { name: '개요 다시 불러오기' }).click();
  await expect(page.getByText('개요 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toHaveCount(0);
});

test('current result is selected by result_id and terminal state refreshes related queries', async ({ page }) => {
  const requests: string[] = [];
  let overviewCalls = 0;
  page.on('request', request => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === '/api/pre-specs' || pathname === '/api/pre-specs/991/company-fit') requests.push(pathname);
  });
  await mockApi(page);
  const queuedRun = overviewRunFixture({
    id: '00000000-0000-0000-0000-000000000701',
    status: 'queued',
    call_count: 0,
    started_at: null,
    completed_at: null,
    created_at: '2026-09-05T09:00:00Z',
  });
  await page.route(OVERVIEW_PATH, async route => {
    overviewCalls += 1;
    const body = overviewCalls === 1
      ? envelope(queuedRun, [historicalRun])
      : envelope(overviewCompletedRunFixture, [overviewCompletedRunFixture, historicalRun]);
    await route.fulfill({ json: body });
  });

  await page.goto('/pre-specs?notice_pk=991');
  await expect(page.getByRole('region', { name: '현재 v4 개요 실행' })).toContainText('개요 검토 대기');
  await expect.poll(() => overviewCalls, { timeout: 12_000 }).toBeGreaterThan(1);
  await expect(page.getByRole('region', { name: '현재 v4 개요 실행' })).toContainText('개요 검토 완료');
  const currentRegion = page.getByRole('region', { name: 'PDF 기반 개요 검토' });
  await expect(currentRegion).toContainText(currentFactText);
  await expect(currentRegion).not.toContainText('과거 성공 결과의 본문이다.');
  await expect(currentRegion.getByRole('link', { name: 'PDF 3페이지 ↗' }).first()).toHaveAttribute(
    'href',
    new RegExp(`${overviewCompletedRunFixture.id}/pdf#page=3$`),
  );
  await expect(page.getByText('이전 개요 결과 1건', { exact: true })).toBeVisible();
  await page.getByText('이전 개요 결과 1건', { exact: true }).click();
  await expect(page.getByText(new RegExp(`결과 ID · ${historicalRun.id}`))).toBeVisible();
  await expect.poll(() => requests.filter(path => path === '/api/pre-specs').length, { timeout: 5_000 }).toBeGreaterThan(1);
  await expect.poll(() => requests.filter(path => path === '/api/pre-specs/991/company-fit').length, { timeout: 5_000 }).toBeGreaterThan(1);

  await page.goto('/pre-specs/991');
  await expect(page.getByRole('region', { name: '현재 v4 개요 실행' })).toContainText('개요 검토 완료');
  await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toContainText(currentFactText);
});

test('current claim verification remains visible when a previous successful result exists', async ({ page }) => {
  await mockApi(page);
  const needsReviewRun = overviewRunFixture({
    id: '00000000-0000-0000-0000-000000000702',
    status: 'needs_human_review',
    reason_codes: ['claim_verification_required'],
    verification_status: 'needs_human_review',
    created_at: '2026-09-08T10:00:00Z',
  });
  await page.route(OVERVIEW_PATH, route => route.fulfill({
    json: {
      ...envelope(needsReviewRun, [needsReviewRun, historicalRun]),
      verification: {
        ...overviewVerificationFixture,
        verification_id: needsReviewRun.id,
        claims: [{
          claim_id: 'budgetClaim',
          section: 'budget_and_period',
          text: '사업 예산은 6억원이다.',
          deterministic: { status: 'failed', reason_codes: ['quantity_mismatch'] },
          semantic: { status: 'not_run', reason_codes: [] },
          verified_evidence: [{ page: 7, quote: '사업 기간은 6개월', start_char: 20, end_char: 30 }],
        }],
      },
    },
  }));
  await page.goto('/pre-specs/991');

  const currentRegion = page.getByRole('region', { name: '현재 v4 개요 실행' });
  await expect(currentRegion).toContainText('주장과 검증된 근거를 사람이 확인해야 합니다. 입력 범위 확인 대기와는 별도 상태입니다.');
  await currentRegion.getByText('실행 정보', { exact: true }).click();
  await expect(currentRegion).toContainText('claim_verification_required');
  await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toHaveCount(0);
  const verification = page.getByRole('region', { name: '현재 주장 검증 진단' });
  await expect(verification).toContainText('근거 확인 필요');
  await expect(verification).toContainText('전체 사유 코드 · required_fact_missing');
  await expect(verification).toContainText('사업 예산은 6억원이다.');
  await expect(verification).toContainText('결정적 검사 실패 · 의미 검사 미실행');
  await expect(verification).toContainText('주장 사유 코드 · quantity_mismatch');
  await expect(verification).toContainText('사업 기간은 6개월');
  await expect(verification.getByRole('link', { name: '검증 근거 PDF 7페이지 ↗' })).toHaveAttribute(
    'href',
    `/api/pre-specs/991/overview/runs/${needsReviewRun.id}/pdf#page=7`,
  );
  await expect(verification).not.toContainText('모델 원문 인용');
  await expect(page.getByText('이전 개요 결과 1건', { exact: true })).toBeVisible();
  await page.getByText('이전 개요 결과 1건', { exact: true }).click();
  const history = page.locator('.page-overview-history');
  await expect(history.getByText(new RegExp(`결과 ID · ${historicalRun.id}`))).toBeVisible();
  await expect(page.getByText('과거 성공 결과의 본문이다.', { exact: true })).toBeHidden();
  await history.getByText(new RegExp(`결과 ID · ${historicalRun.id}`)).click();
  await expect(history).toContainText('주장 검증 v4');
  await expect(page.getByText('과거 성공 결과의 본문이다.', { exact: true })).toBeVisible();
});

for (const state of [
  { status: 'failed', label: '개요 검토에 실패했습니다. 사람 확인이 필요합니다.' },
  { status: 'cancelled', label: '개요 검토가 취소되었습니다. 사람 확인이 필요합니다.' },
] as const) {
  test(`current ${state.status} never falls back to a previous success`, async ({ page }) => {
    await mockApi(page);
    const terminalRun = overviewRunFixture({
      id: '00000000-0000-0000-0000-000000000722',
      status: state.status,
      reason_codes: [`${state.status}_reason`],
      created_at: '2026-09-08T11:00:00Z',
    });
    await page.route(OVERVIEW_PATH, route => route.fulfill({
      json: envelope(terminalRun, [terminalRun, historicalRun]),
    }));
    await page.goto('/pre-specs/991');
    await expect(page.getByRole('region', { name: '현재 v4 개요 실행' })).toContainText(state.label);
    await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toHaveCount(0);
    await expect(page.getByText('이전 개요 결과 1건', { exact: true })).toBeVisible();
  });
}

for (const width of [1280, 1440]) {
  test(`input capacity failure explains non-execution and approval boundaries at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 900 });
    await mockApi(page);
    const failedRun = overviewRunFixture({
      id: '00000000-0000-0000-0000-000000000726',
      status: 'failed',
      reason_codes: ['input_capacity_exceeded'],
      created_at: '2026-09-10T12:00:00Z',
    });
    await page.route(OVERVIEW_PATH, route => route.fulfill({ json: envelope(failedRun, [failedRun]) }));

    await page.goto('/pre-specs/991');
    const current = page.getByRole('region', { name: '현재 v4 개요 실행' });
    await expect(current).toContainText('입력 용량 초과로 미실행');
    await expect(current).toContainText('선택 범위와 요청 예산을 확인해 주세요.');
    await expect(current).toContainText('안전 한도를 확인할 수 없어');
    await expect(current).toContainText('단계별 payload 상한은 정책이 정하며');
    await expect(current).toContainText('같은 시도의 앞선 초안 호출 여부를 뜻하지 않습니다.');
    await expect(current).toContainText('원문을 몰래 자르거나 사전 요약·자동 분할하지 않습니다.');
    await expect(current).toContainText('사람이 새 범위를 확정해야 하고');
    await expect(current).toContainText('모델 호출 증가가 필요하면 별도 승인');
    await expect(current).not.toContainText('개요 검토에 실패했습니다. 사람 확인이 필요합니다.');
    await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toHaveCount(0);
    await expect(page.getByRole('region', { name: '현재 주장 검증 진단' })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  });
}

test('current body keeps long text and limitations without client truncation', async ({ page }) => {
  const longText = `${'긴 본문을 임의로 줄이지 않고 그대로 표시해야 합니다. '.repeat(80)}끝 문장`;
  const longRun: OverviewRun = {
    ...overviewCompletedRunFixture,
    id: '00000000-0000-0000-0000-000000000617',
    result_id: '00000000-0000-0000-0000-000000000617',
    result: {
      ...overviewCompletedRunFixture.result!,
      business_overview: [{
        claim_id: 'c1',
        text: longText,
        evidence: [{ page: 3, quote: '차세대 통합 데이터 플랫폼 구축' }],
      }],
      input_limitations: ['선택된 PDF 3~11페이지를 기준으로 검토했습니다.'],
    },
  };
  await mockApi(page);
  await page.route(OVERVIEW_PATH, route => route.fulfill({ json: envelope(longRun, [longRun]) }));
  await page.goto('/pre-specs?notice_pk=991');
  const currentRegion = page.getByRole('region', { name: 'PDF 기반 개요 검토' });
  await expect(currentRegion).toContainText(longText);
  await expect(currentRegion.getByRole('link', { name: 'PDF 3페이지 ↗' }).first()).toHaveAttribute(
    'href',
    new RegExp(`${longRun.id}/pdf#page=3$`),
  );
  await expect(currentRegion).toContainText('선택된 PDF 3~11페이지를 기준으로 검토했습니다.');
});

test('an envelope that does not match the contract fails closed', async ({ page }) => {
  await mockApi(page);
  const complete = envelope(overviewCompletedRunFixture, [overviewCompletedRunFixture]);
  const { current: _current, ...missingCurrent } = complete;
  await page.route(OVERVIEW_PATH, route => route.fulfill({ json: missingCurrent }));
  await page.goto('/pre-specs/991');
  await expect(page.getByText('개요 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: '현재 v4 개요 실행' })).toHaveCount(0);
});

/** 범위 확인: 결정적 선택기가 범위를 못 정하면 사람이 시작·끝을 확정한다. */
const pendingRangeEnvelope = overviewEnvelopeFixture(991, null, [], {
  range_review: overviewRangeReviewFixture(),
});

test('detail range notification leads to the live confirmation form outside the verdict rail', async ({ page }) => {
  await mockApi(page);
  let confirmed: unknown;
  let calls = 0;
  await page.route(OVERVIEW_PATH, route => {
    calls += 1;
    return route.fulfill({ json: pendingRangeEnvelope });
  });
  await page.route(RANGE_PATH, route => {
    confirmed = route.request().postDataJSON();
    return route.fulfill({
      status: 201,
      json: { run_id: '00000000-0000-0000-0000-000000000803', attempt_enqueued: true, page_start: 6, page_end: 12 },
    });
  });
  await page.goto('/pre-specs/991');
  // 오른쪽 `현재 판단`에는 알림 한 줄만 있고 조작 폼은 왼쪽 열이 소유한다(ADR-0055 결정 4).
  const verdict = page.locator('.ps-record-aside');
  await expect(verdict.getByRole('radio')).toHaveCount(0);
  const link = verdict.locator('a[href="#ps-record-range"]');
  await expect(link).toContainText('확정하기');
  await link.click();
  const region = page.locator('#ps-record-range').getByRole('region', { name: '개요 범위 확인' });
  await expect(region).toBeVisible();
  await region.getByRole('radio', { name: '시작 #1' }).check();
  await region.getByRole('radio', { name: '끝 #2' }).check();
  await region.getByLabel('담당자 이름 (필수)').fill('최정인');
  const before = calls;
  await region.getByRole('button', { name: '범위 확정' }).click();
  // 폼은 위치만 옮겼을 뿐 저장과 재조회 동작은 그대로다.
  await expect.poll(() => confirmed).toEqual({ candidate_indices: [1, 2] });
  await expect.poll(() => calls).toBeGreaterThan(before);
});

test('pending range review confirms a clause range and refetches the overview', async ({ page }) => {
  const posts: Array<{ body: unknown; actor: string | undefined; method: string }> = [];
  let overviewCalls = 0;
  await mockApi(page);
  await page.route(RANGE_PATH, async route => {
    const request = route.request();
    posts.push({ body: request.postDataJSON(), actor: request.headers()['x-bidops-actor-name'], method: request.method() });
    await route.fulfill({
      status: 201,
      json: { run_id: '00000000-0000-0000-0000-000000000803', attempt_enqueued: true, page_start: 6, page_end: 12 },
    });
  });
  await page.route(OVERVIEW_PATH, async route => {
    overviewCalls += 1;
    await route.fulfill({ json: pendingRangeEnvelope });
  });

  await page.goto('/pre-specs?notice_pk=991');
  const region = page.getByRole('region', { name: '개요 범위 확인' });
  await expect(region).toContainText('범위 확인 필요');
  await expect(region).toContainText('범위 제목을 찾지 못함');
  await expect(region).toContainText('확정하면 그 범위로 개요 검토 실행 하나를 예약합니다.');
  const table = region.getByRole('table');
  for (const candidate of overviewRangeCandidatesFixture) await expect(table).toContainText(candidate.title);
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
  await expect(region.getByText('범위가 확정되었습니다 · 그 범위로 개요 검토를 예약했습니다')).toBeVisible();
  expect(posts).toHaveLength(1);
  expect(posts[0].method).toBe('POST');
  expect(posts[0].body).toEqual({ candidate_indices: [1, 2] });
  // 담당자 이름은 감사 표식이다. 비ASCII는 계약대로 percent 인코딩돼 실린다.
  const actorHeader = posts[0].actor ?? '';
  expect(actorHeader.startsWith("UTF-8''")).toBe(true);
  expect(decodeURIComponent(actorHeader.slice(7))).toBe('최정인');
  await expect.poll(() => overviewCalls, { timeout: 5_000 }).toBeGreaterThan(callsBeforeConfirm);
});

test('range review without clause candidates confirms a page range', async ({ page }) => {
  const posts: unknown[] = [];
  await mockApi(page);
  await page.route(RANGE_PATH, async route => {
    posts.push(route.request().postDataJSON());
    await route.fulfill({
      status: 201,
      json: { run_id: '00000000-0000-0000-0000-000000000804', attempt_enqueued: true, page_start: 4, page_end: 9 },
    });
  });
  await page.route(OVERVIEW_PATH, route => route.fulfill({
    json: overviewEnvelopeFixture(991, null, [], {
      range_review: overviewRangeReviewFixture({ mode: null, candidates: [], candidate_count_total: 0, candidate_count_returned: 0 }),
    }),
  }));

  await page.goto('/pre-specs?notice_pk=991');
  const region = page.getByRole('region', { name: '개요 범위 확인' });
  await expect(region).toContainText('쪽 범위로 직접 확정합니다.');
  await expect(region.getByRole('link', { name: '변환 PDF 열기 ↗' })).toHaveAttribute(
    'href',
    '/api/pre-specs/991/overview/snapshot/pdf',
  );
  await expect(region.getByRole('table')).toHaveCount(0);

  const confirm = region.getByRole('button', { name: '범위 확정' });
  await region.getByLabel('시작 쪽').fill('4');
  await region.getByLabel('시작 쪽').press('Enter');
  await region.getByLabel('끝 쪽').fill('9');
  await region.getByLabel('끝 쪽').press('Enter');
  await region.getByLabel('담당자 이름 (필수)').fill('hong');
  await expect(confirm).toBeEnabled();
  await confirm.click();

  await expect(region.getByText('범위가 확정되었습니다 · 그 범위로 개요 검토를 예약했습니다')).toBeVisible();
  expect(posts).toEqual([{ page_start: 4, page_end: 9 }]);
});

test('complete candidates keep clause default but allow an exact page pair', async ({ page }) => {
  const posts: unknown[] = [];
  await mockApi(page);
  await page.route(RANGE_PATH, async route => {
    posts.push(route.request().postDataJSON());
    await route.fulfill({
      status: 201,
      json: { run_id: '00000000-0000-0000-0000-000000000806', attempt_enqueued: true, page_start: 4, page_end: 9 },
    });
  });
  await page.route(OVERVIEW_PATH, route => route.fulfill({ json: pendingRangeEnvelope }));

  await page.goto('/pre-specs?notice_pk=991');
  const region = page.getByRole('region', { name: '개요 범위 확인' });
  await expect(region.getByRole('radio', { name: '시작 #0' })).toBeVisible();
  await region.getByRole('button', { name: '쪽 직접 선택' }).click();
  await expect(region.getByRole('radio', { name: '시작 #0' })).toHaveCount(0);
  await expect(region.getByRole('table')).toContainText('1. 사업 개요');
  await region.getByLabel('시작 쪽').fill('4');
  await region.getByLabel('시작 쪽').press('Enter');
  await region.getByLabel('끝 쪽').fill('9');
  await region.getByLabel('끝 쪽').press('Enter');
  await region.getByLabel('담당자 이름 (필수)').fill('hong');
  await region.getByRole('button', { name: '범위 확정' }).click();

  expect(posts).toEqual([{ page_start: 4, page_end: 9 }]);
});

test('partial candidates are reference-only and page selection remains available', async ({ page }) => {
  await mockApi(page);
  await page.route(OVERVIEW_PATH, route => route.fulfill({
    json: overviewEnvelopeFixture(991, null, [], {
      range_review: overviewRangeReviewFixture({
        candidate_status: 'partial',
        candidate_count_total: 8,
        candidate_count_returned: 3,
        warning_codes: ['section_candidates_incomplete'],
      }),
    }),
  }));

  await page.goto('/pre-specs?notice_pk=991');
  const region = page.getByRole('region', { name: '개요 범위 확인' });
  await expect(region.getByRole('button', { name: '절 후보 선택' })).toHaveCount(0);
  await expect(region.getByLabel('시작 쪽')).toBeVisible();
  await expect(region.getByRole('table')).toContainText('1. 사업 개요');
  await expect(region.getByRole('radio')).toHaveCount(0);
  await expect(region).toContainText('일부 후보이므로 표는 참고용입니다');
  await expect(region).toContainText('후보 표는 참고하고 쪽 범위를 직접 입력하십시오');
});

test('ready automatic range with failed capacity keeps PDF and separates preparation from validation at both widths', async ({ page }) => {
  await mockApi(page);
  const failedRun = overviewRunFixture({
    id: '00000000-0000-0000-0000-000000000807',
    status: 'failed',
    reason_codes: ['input_capacity_exceeded'],
    created_at: '2026-09-11T01:00:00Z',
  });
  await page.route(OVERVIEW_PATH, route => route.fulfill({
    json: overviewEnvelopeFixture(991, failedRun, [failedRun], {
      range_review: overviewRangeReviewFixture({
        target_id: failedRun.id,
        status: 'ready',
        reason_code: null,
        selected_pages: [2, 18],
        warning_codes: ['ambiguous_scope_boundary'],
      }),
    }),
  }));

  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.goto('/pre-specs?notice_pk=991');
    const region = page.getByRole('region', { name: '개요 범위 확인' });
    await expect(region).toContainText('변환 완료 · 자동 선택 · 내용 검증 상태는 개요 상태에서 확인');
    await expect(region).toContainText('자동 선택 범위 2~18쪽');
    await expect(region.getByRole('link', { name: '변환 PDF 열기 ↗' })).toHaveAttribute(
      'href',
      '/api/pre-specs/991/overview/snapshot/pdf',
    );
    const current = page.getByRole('region', { name: '현재 v4 개요 실행' });
    await expect(current).toContainText('입력 용량 초과로 미실행');
    await expect(current).toContainText('단계별 payload 상한은 정책이 정하며');
    await expect(current).toContainText('모델 컨텍스트 한도는 실제 요청 전체');
    await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});

test('unsafe or active ready target explains why confirmation is blocked without hiding PDF', async ({ page }) => {
  await mockApi(page);
  await page.route(OVERVIEW_PATH, route => route.fulfill({
    json: overviewEnvelopeFixture(991, null, [], {
      range_review: overviewRangeReviewFixture({
        status: 'ready',
        selected_pages: [4, 6],
        can_confirm: false,
        warning_codes: ['target_execution_active'],
      }),
    }),
  }));

  await page.goto('/pre-specs?notice_pk=991');
  const region = page.getByRole('region', { name: '개요 범위 확인' });
  await expect(region).toContainText('실행 중인 개요가 있어 새 범위를 저장할 수 없습니다');
  await expect(region.getByRole('button', { name: '범위 확정' })).toBeDisabled();
  await expect(region.getByRole('link', { name: '변환 PDF 열기 ↗' })).toBeVisible();
});

test('confirmed range review renders the read-only summary on the detail record', async ({ page }) => {
  await mockApi(page);
  await page.route(OVERVIEW_PATH, route => route.fulfill({
    json: overviewEnvelopeFixture(991, null, [], {
      range_review: overviewRangeReviewFixture({
        status: 'human_confirmed',
        reason_code: null,
        selected_pages: [6, 12],
        confirmation: {
          page_start: 6,
          page_end: 12,
          actor_name: '최정인',
          note: null,
          created_at: '2026-09-10T02:00:00Z',
        },
      }),
    }),
  }));

  await page.goto('/pre-specs/991');
  const region = page.getByRole('region', { name: '개요 범위 확인' });
  await expect(region).toContainText('범위 확정됨');
  await expect(region).toContainText('변환 완료 · 범위 확정 · 내용 검증 상태는 개요 상태에서 확인');
  await expect(region).toContainText('6~12쪽');
  // 확정 기록은 쪽만 남는다. 절 제목을 지어내지 않는다.
  await expect(region).toContainText('쪽 범위 직접 입력');
  await expect(region).toContainText('최정인');
  await expect(region).toContainText('확정된 범위로 개요 검토 실행 하나가 예약됩니다');
  await expect(region.getByRole('button', { name: '범위 확정' })).toHaveCount(0);
});

test('completed overview alongside the latest range target does not claim content is unverified', async ({ page }) => {
  await mockApi(page);
  await page.route(OVERVIEW_PATH, route => route.fulfill({
    json: overviewEnvelopeFixture(991, overviewCompletedRunFixture, [overviewCompletedRunFixture], {
      range_review: overviewRangeReviewFixture({
        target_id: overviewCompletedRunFixture.id,
        status: 'ready',
        reason_code: null,
        selected_pages: [3, 11],
      }),
    }),
  }));

  await page.goto('/pre-specs/991');
  const range = page.getByRole('region', { name: '개요 범위 확인' });
  await expect(range).toContainText('내용 검증 상태는 개요 상태에서 확인');
  await expect(range).not.toContainText('내용 미검증');
  await expect(page.getByRole('region', { name: '현재 v4 개요 실행' })).toContainText('개요 검토 완료');
  await expect(page.getByRole('region', { name: 'PDF 기반 개요 검토' })).toContainText(currentFactText);
});
