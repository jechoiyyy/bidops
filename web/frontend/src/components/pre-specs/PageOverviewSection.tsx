import { useQuery } from "@tanstack/react-query";
import { Token } from "@astryxdesign/core/Token";
import { Button } from "@astryxdesign/core/Button";
import { api } from "../../lib/api";
import { qualityStatusLabel } from "../../lib/qualityStatus";
import type { PageOverviewFact, PageOverviewView } from "../../lib/types";
import "../../styles/page-overview.css";

// Presentation only: preserve raw output, hide only a suffix matching the separate page links.
function displayFact(fact: PageOverviewFact): string {
  const match = fact.text.match(/\s*\((PDF\s*\d+\s*페이지(?:\s*[·,]\s*PDF\s*\d+\s*페이지)*|PDF\s*\d+(?:\s*[,·]\s*\d+)*\s*페이지)\)\s*$/);
  const pages = new Set(match?.[1].match(/\d+/g)?.map(Number) ?? []);
  return match && pages.size === new Set(fact.evidence_pages).size && fact.evidence_pages.every(n => pages.has(n))
    ? fact.text.slice(0, match.index) : fact.text;
}

export function PageOverviewResult({ review }: { review: PageOverviewView }) {
  const payload = review.payload;
  const pdfUrl = `/api/pre-specs/${review.notice_id}/overview-pages/${review.id}/pdf`;
  const facts = (title: string, items: PageOverviewFact[], ordered = false) => (
    <section className="page-overview-section">
      <h4>{title}</h4>
      {items.length === 0 ? <p className="page-overview-note">이번 입력에서는 확인되지 않았습니다.</p> : (
        <ol className={ordered ? "page-overview-tasks" : "page-overview-facts"}>
          {items.map((fact, i) => <li key={i}>
            <p>{displayFact(fact)}</p>
            <div className="page-overview-links" aria-label="PDF 페이지 근거">
              {[...new Set(fact.evidence_pages)].sort((a, b) => a - b).map(page => (
                review.reviewed_pages.includes(page) && page <= review.pdf_page_count ? <a key={page} href={`${pdfUrl}#page=${page}`} target="_blank" rel="noreferrer">PDF {page}페이지 ↗</a> : <span key={page}>PDF {page}페이지 · 근거 위치 확인 필요</span>
              ))}
            </div>
          </li>)}
        </ol>
      )}
    </section>
  );
  return <section className="page-overview" aria-label="PDF 기반 개요 검토">
    <header className="page-overview-heading">
      <h3>개요 검토 결과</h3>
      <Token label={qualityStatusLabel(review.quality_status)} size="sm" />
    </header>
    <div className="page-overview-validation" role="status">
      <strong>{review.validation_status === "failed" ? "검증 실패 · 사람 확인 필요" : "근거 검사 통과 · 참조 결과"}</strong>
      <p>사업 설명을 위한 요약입니다. 기존 권고·추적 결정과 자동 심층 검토 상태를 변경하지 않습니다.</p>
      {review.validation_status === "failed" && review.evidence_check_status === "passed" ? (
        <p>새 페이지 근거 검사는 통과했으나, 원실행의 검증 실패 기록은 유지합니다.</p>
      ) : null}
    </div>
    {facts("사업 개요", payload.business_overview)}
    {facts("주요 과업", payload.main_tasks, true)}
    {facts("사업 규모와 일정", payload.budget_and_period)}
    {facts("핵심 조건", payload.important_conditions)}
    <section className="page-overview-section"><h4>검토 포인트 <span className="page-overview-note">모델 의견</span></h4>
      {payload.reviewer_analysis.map((text, i) => <p key={i}>{text}</p>)}
    </section>
    <section className="page-overview-section"><h4>추가 확인 사항</h4>
      {payload.unknowns.length ? <ul>{payload.unknowns.map((text, i) => <li key={i}>{text}</li>)}</ul> : <p className="page-overview-note">추가 확인 사항이 제시되지 않았습니다.</p>}
    </section>
    <details className="page-overview-section"><summary>검토 범위와 실행 정보</summary>
      {payload.input_limitations.map((text, i) => <p key={i}>{text}</p>)}
      <p>표지를 포함한 변환 PDF 순번 기준 · {review.reviewed_pages.join(", ")} / 총 {review.pdf_page_count}페이지. 원본 한컴 쪽 배치와 다를 수 있습니다.</p>
      <p>{review.model_name} · {review.prompt_version}</p>
      {review.validation_errors.length ? <p>검증 사유: {review.validation_errors.join(", ")}</p> : null}
      <a href={pdfUrl} target="_blank" rel="noreferrer">전체 근거 PDF 열기 ↗</a>
    </details>
  </section>;
}

export function PageOverviewSection({ noticeId }: { noticeId: number }) {
  const query = useQuery({ queryKey: ["pre-spec-overview-pages", noticeId],
    queryFn: ({ signal }) => api.getPageOverviews(noticeId, { signal }), retry: false });
  if (query.isPending) return <p role="status">PDF 기반 개요를 불러오는 중입니다.</p>;
  if (query.isError) return <div role="alert" className="page-overview-validation">
    <p>PDF 기반 개요를 불러오지 못했습니다. 아래 기존 개요 기록과는 별도 조회입니다.</p>
    <Button label="개요 다시 불러오기" size="sm" onClick={() => { void query.refetch(); }} />
  </div>;
  if (query.data.schema_version !== "bidops.prespec-overview-pages.v1" || query.data.notice_id !== noticeId || query.data.reviews.some(r => r.notice_id !== noticeId || r.payload.schema_version !== "bidops.prespec-overview-page-review.v3")) {
    return <p role="alert">개요 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.</p>;
  }
  const review = query.data.reviews[0];
  return review ? <><PageOverviewResult review={review} /><h3 className="page-overview-legacy">기존 개요 권고·처리 기록</h3></> : null;
}
