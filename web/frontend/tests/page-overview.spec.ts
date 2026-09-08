import { expect, test } from '@playwright/test';
import { mockApi } from './api-mock';
import type { PageOverviewResponse } from '../src/lib/types';

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
