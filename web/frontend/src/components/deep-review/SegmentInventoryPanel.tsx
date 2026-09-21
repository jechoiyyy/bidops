import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DeepReviewApiError, getDocumentSegments, getDocumentStructurePage } from "./api";
import { TechnicalFacts, TechnicalInfo, type TechnicalFact } from "./TechnicalInfo";
import type { DocumentSegmentView, SegmentPageRange, TaxonomyLabel } from "./types";

// 심층 보고서 화면 우측 열의 문서별 inventory 요약과 `needs_human_review`
// segment 목록(명세 §6.8).
//
// **이 계약(`bidops.document-segments.v1`)에는 segment 제목이 없다.** 응답이
// 원문 text를 싣지 않기 때문이며 누락이 아니다. 그래서 목록은 계약이 실제로
// 주는 것(순번·분류·요구사항 ID·페이지)만 보여 주고, 제목을 만들어 내거나
// 다른 endpoint에서 원문을 받아 다시 짓지 않는다.
//
// 원문 열기는 기존 page endpoint(`/document-structures/{id}/pages/{page}`)를
// 그대로 쓴다. PDF 페이지 링크는 계약이 주는 `page_range`(물리 PDF 순번)만
// 쓰고, `mapping_status`가 `unavailable`이라 `page_range`가 없으면 페이지를
// 추정하지 않고 미확인으로 남긴다.

const TAXONOMY_LABEL: Record<TaxonomyLabel, string> = {
  business_eligibility_evaluation: "사업·자격·평가",
  technical_functional: "기술·기능",
  quality_security_constraints: "품질·보안·제약",
  partnership_governance: "협력·거버넌스",
};

const AMBIGUITY_REASON_LABEL: Record<string, string> = {
  prefix_unconfirmed: "접두사 확인 안 됨",
  prefix_collision: "접두사 충돌",
};

function isNotFound(error: unknown): boolean {
  return error instanceof DeepReviewApiError && error.status === 404;
}

function isUnsafeDocument(error: unknown): boolean {
  return error instanceof DeepReviewApiError && error.status === 403;
}

function pageRangeText(range: SegmentPageRange): string {
  return range.first === range.last ? `${range.first}` : `${range.first}~${range.last}`;
}

/** 접힌 곳이 싣는 구간 식별자. 계약이 준 값을 줄이지 않고 그대로 옮긴다. */
function segmentTechnicalFacts(segment: DocumentSegmentView): TechnicalFact[] {
  return [
    { label: "구간 순번", value: `segment ${segment.ordinal}` },
    { label: "시작 블록 키", value: segment.start_locator.block_key },
    {
      label: "요구사항 ID",
      value: segment.requirement_ids.length > 0 ? segment.requirement_ids.join(", ") : "값 없음",
    },
  ];
}

function taxonomyText(segment: DocumentSegmentView): string {
  if (segment.taxonomy_labels.length === 0) return "분류 없음";
  return segment.taxonomy_labels.map((label) => TAXONOMY_LABEL[label] ?? label).join(" · ");
}

export interface SegmentInventoryPanelProps {
  /** 어떤 문서의 manifest인가. 알 수 없으면 `null`이며, 그 사실을 그대로
   * 표시하고 다른 문서로 대신하지 않는다. */
  structureId: string | null;
  /** 이 구조가 어떤 근거에서 왔는지 사람에게 알리는 문장. */
  sourceNote: string;
  /** 같은 근거가 가리키는 저장 문서 버전. 접힌 `기술 정보`에 전문으로 싣는다. */
  documentVersionId?: string | null;
}

export function SegmentInventoryPanel({ documentVersionId = null, structureId, sourceNote }: SegmentInventoryPanelProps) {
  const [openPage, setOpenPage] = useState<number | null>(null);
  const segmentsQuery = useQuery({
    queryKey: ["document-segments", structureId],
    queryFn: () => getDocumentSegments(structureId as string),
    enabled: Boolean(structureId),
    retry: false,
    staleTime: 30_000,
  });
  const pageQuery = useQuery({
    queryKey: ["document-structure-page", structureId, openPage],
    queryFn: () => getDocumentStructurePage(structureId as string, openPage as number),
    enabled: Boolean(structureId && openPage !== null),
    retry: false,
    staleTime: 30_000,
  });

  const view = segmentsQuery.data;
  const needsReview = view?.segments.filter((segment) => segment.status === "needs_human_review") ?? [];

  return (
    <section aria-labelledby="segment-inventory-title" className="deep-review-segment-panel">
      <h3 id="segment-inventory-title" className="deep-review-section-title">문서 요구사항 inventory와 사람 확인 구간</h3>
      <p className="deep-review-section-copy">{sourceNote}</p>

      {structureId === null ? (
        <p className="deep-review-segment-empty" role="status">
          구조 ID를 확인할 수 없어 inventory를 불러오지 않았습니다. 다른 문서의 값으로 대신하지 않습니다.
        </p>
      ) : null}
      {structureId !== null && segmentsQuery.isPending ? (
        <p className="deep-review-segment-empty" role="status" aria-live="polite">문서 구간 목록을 불러오는 중입니다.</p>
      ) : null}
      {isNotFound(segmentsQuery.error) ? (
        <p className="deep-review-segment-empty" role="status">
          이 문서에는 구간 목록이 없습니다. 목록이 생기기 전에 만들어진 구조는 정상적으로 값이 없으며, 없음을 0건으로 바꾸지 않습니다.
        </p>
      ) : null}
      {isUnsafeDocument(segmentsQuery.error) ? (
        <p className="deep-review-segment-empty" role="status">
          안전 검사를 통과하지 못한 문서라 구간 목록을 열지 않았습니다.
        </p>
      ) : null}
      {segmentsQuery.error && !isNotFound(segmentsQuery.error) && !isUnsafeDocument(segmentsQuery.error) ? (
        <p className="deep-review-segment-empty" role="status">
          문서 구간 목록을 확인할 수 없습니다.
        </p>
      ) : null}

      {view ? (
        <>
          <dl className="deep-review-segment-inventory" aria-label="요구사항 inventory 요약">
            <div>
              <dt>기대 ID 수</dt>
              <dd className="mono tabular-nums">{view.inventory_summary.expected_ids.length}</dd>
            </div>
            <div>
              <dt>중복 ID</dt>
              <dd className="mono tabular-nums">{view.inventory_summary.duplicate_ids.length}</dd>
            </div>
            <div>
              <dt>모호 항목</dt>
              <dd className="mono tabular-nums">{view.inventory_summary.ambiguous_items.length}</dd>
            </div>
            <div>
              <dt>추출 항목 수</dt>
              <dd className="mono tabular-nums">{view.inventory_summary.item_count}</dd>
            </div>
          </dl>

          {/* 문서 식별자와 중복 ID 나열은 눈으로 대조할 때만 필요하므로
              접어 둔다. 건수(위 요약)와 이유 문장은 밖에 남는다(ADR-0065). */}
          <TechnicalInfo summary="기술 정보 · 문서 식별자와 중복 ID">
            <TechnicalFacts
              label="문서 식별자와 중복 요구사항 ID"
              facts={[
                { label: "문서 버전", value: documentVersionId ?? "값 없음" },
                { label: "문서 구조 ID", value: structureId ?? "값 없음" },
                ...(view.inventory_summary.duplicate_ids.length > 0
                  ? [{ label: "중복 ID", value: view.inventory_summary.duplicate_ids.join(", ") }]
                  : []),
              ]}
            />
          </TechnicalInfo>
          {view.inventory_summary.ambiguous_items.length > 0 ? (
            <ul className="deep-review-segment-ambiguous" aria-label="모호한 요구사항 항목">
              {view.inventory_summary.ambiguous_items.map((item) => (
                <li key={`${item.reason}-${item.normalized_prefix}-${item.raw_id ?? "없음"}`}>
                  <span>{AMBIGUITY_REASON_LABEL[item.reason] ?? item.reason}</span>
                  <span className="mono">{item.normalized_prefix}</span>
                  <span className="mono tabular-nums">{item.occurrence_count}회</span>
                </li>
              ))}
            </ul>
          ) : null}

          <div className="deep-review-segment-coverage">
            <strong>사람 확인 필요 구간 {view.coverage.needs_human_review_count}건</strong>
            <span>
              전체 segment {view.coverage.segment_count} · 미포함 구간 {view.coverage.gap_count} · 겹침 {view.coverage.overlap_count}
            </span>
          </div>

          <p className="deep-review-segment-note">
            이 목록은 segment 제목을 제공하지 않습니다. segment 계약에 원문 text가 없어 제목을 만들 근거가 없으므로, 순번·분류·요구사항 ID·페이지만 보여 줍니다.
          </p>

          {needsReview.length === 0 ? (
            <p className="deep-review-segment-empty">사람 확인이 필요한 segment가 없습니다.</p>
          ) : (
            <ul className="deep-review-segment-list" aria-label="사람 확인 필요 segment">
              {needsReview.map((segment) => (
                <li key={segment.segment_id} data-segment-ordinal={segment.ordinal}>
                  <div className="deep-review-segment-heading">
                    <span className="tabular-nums">{segment.ordinal}번째 구간</span>
                    <span>{taxonomyText(segment)}</span>
                  </div>
                  <div className="deep-review-segment-meta">
                    <span>요구사항 ID {segment.requirement_ids.length}개</span>
                    {segment.page_range === null ? (
                      <span>페이지 미확인</span>
                    ) : (
                      <span>
                        <a
                          href={`/api/document-structures/${structureId as string}/pdf#page=${segment.page_range.first}`}
                          target="_blank"
                          rel="noreferrer"
                          aria-label={`${segment.ordinal}번째 구간 · PDF ${pageRangeText(segment.page_range)}페이지 열기`}
                        >
                          PDF {pageRangeText(segment.page_range)}페이지 ↗
                        </a>
                        {segment.mapping_status === "partial" ? " · 일부 블록만 대응" : null}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    className="interaction-control deep-review-segment-open"
                    aria-expanded={openPage === segment.start_locator.page}
                    aria-controls="deep-review-segment-source"
                    onClick={() => setOpenPage((current) => current === segment.start_locator.page ? null : segment.start_locator.page)}
                  >
                    {segment.start_locator.page}쪽 원문 열기
                  </button>
                  {/* 계약 순번·블록 키·요구사항 ID 나열은 접어 둔다. 건수와
                      분류, 원문으로 가는 길은 밖에 남는다(ADR-0065). */}
                  <TechnicalInfo summary={`기술 정보 · ${segment.ordinal}번째 구간`}>
                    <TechnicalFacts
                      label={`${segment.ordinal}번째 구간의 식별자`}
                      facts={segmentTechnicalFacts(segment)}
                    />
                  </TechnicalInfo>
                </li>
              ))}
            </ul>
          )}

          {openPage !== null ? (
            <section id="deep-review-segment-source" className="deep-review-segment-source" aria-label="segment 원문 블록">
              <header>
                <strong>페이지 {openPage} 원문</strong>
                <button type="button" className="interaction-control" onClick={() => setOpenPage(null)}>원문 닫기</button>
              </header>
              {pageQuery.isPending ? <p role="status" aria-live="polite">페이지 {openPage}의 원문을 불러오는 중입니다.</p> : null}
              {pageQuery.error ? <p role="status">선택한 문서 페이지를 확인할 수 없습니다.</p> : null}
              {pageQuery.data ? (
                <ol className="deep-review-segment-source-blocks">
                  {pageQuery.data.blocks.map((block) => (
                    <li key={block.block_key}>
                      <code className="mono">{block.block_key}</code>
                      <p>{block.text || "추출된 text 없음"}</p>
                    </li>
                  ))}
                </ol>
              ) : null}
            </section>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

export default SegmentInventoryPanel;
