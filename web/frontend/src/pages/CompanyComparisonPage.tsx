import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import {
  CompanyFitSummaryView,
  CompanyReviewSummaryView,
  CompanyTrackingSummaryView,
} from "../components/company/CompanySummaries";
import { describeCompanyApiError } from "../lib/apiErrors";
import {
  COMPANY_COMPARISON_STATUS_PRIORITY,
  companyApi,
  companyComparisonStatusLabel,
  companyComparisonStatusNote,
  companyKeys,
  parseNoticeId,
  shortIdentity,
  type CompanyComparisonStatus,
} from "../lib/companyApi";
import "../styles/company-workspace.css";

/*
 * 3사 비교 (`GET /api/pre-specs/{notice_id}/company-comparison`, 공통 계약 §6).
 *
 * 서버가 정한 slug 오름차순과 `comparison_status`를 그대로 보여 준다. 브라우저는
 * 회사 순위·종합 점수·보정값을 만들지 않고, 상태를 다시 계산하거나 행을 다시 정렬하지 않는다.
 * 적합성(핏)·심층 검토·추적 결정은 회사마다 다른 칸이며 서로 대신하지 않는다. 각 실행의
 * 상태(대기·실행 중·실패·사람 검토 필요)는 비교 상태와 별도로 그 칸에 적는다.
 */

function comparisonVariant(status: CompanyComparisonStatus): BadgeVariant {
  // 색은 보조다. 뜻은 문구가 전한다. 비교 가능도 "성공"이 아니므로 성공색을 쓰지 않는다.
  return status === "comparable" ? "neutral" : "alert";
}

export function CompanyComparisonPage() {
  const { noticeId: noticeParam } = useParams();
  const noticeId = parseNoticeId(noticeParam);
  if (noticeId === null) {
    return (
      <section className="cw-page">
        <EmptyState tone="error" title="사전규격 주소가 올바르지 않습니다." action={{ label: "회사 선택", to: "/companies" }} />
      </section>
    );
  }
  return <CompanyComparison key={noticeId} noticeId={noticeId} />;
}

function CompanyComparison({ noticeId }: { noticeId: number }) {
  const comparisonQuery = useQuery({
    queryKey: companyKeys.comparison(noticeId),
    queryFn: ({ signal }) => companyApi.getComparison(noticeId, { signal }),
    retry: false,
  });
  const view = comparisonQuery.data;
  const wrongNotice = view !== undefined && view.notice_id !== noticeId;
  return (
    <section className="cw-page" aria-label="3사 비교" data-notice-id={noticeId}>
      <div className="cw-section">
        <h2 id="company-comparison-title">notice {noticeId} · 가상회사 3사 비교</h2>
        <p className="cw-caption">
          가상회사 데모입니다. 회사 순위·종합 점수·최고 회사는 만들지 않습니다. 회사는 서버가 정한 슬러그 오름차순이며,
          각 회사의 결과와 비교 상태는 서버 값 그대로입니다. 비교 상태와 각 실행의 상태는 따로 적습니다.{" "}
          <Link className="cw-link" to={`/pre-specs/${noticeId}`}>원문 사전규격 상세</Link>
        </p>
        {comparisonQuery.isPending ? (
          <p role="status">3사 비교를 불러오는 중입니다.</p>
        ) : comparisonQuery.isError ? (
          <EmptyState
            tone="error"
            title="3사 비교를 불러오지 못했습니다."
            problem={describeCompanyApiError(comparisonQuery.error, "3사 비교를 불러오지 못했습니다.")}
            action={{ label: "다시 시도", onClick: () => { void comparisonQuery.refetch(); } }}
          />
        ) : wrongNotice ? (
          <EmptyState tone="error" title="응답의 공고가 이 화면과 다릅니다." description="다른 공고의 비교를 대신 보여 주지 않습니다." />
        ) : view && view.items.length === 0 ? (
          <EmptyState title="비교할 회사가 없습니다." description="데모에 등록된 회사가 없거나 서버가 비교 대상을 주지 않았습니다." />
        ) : view ? (
          <>
            <p className="cw-caption" data-testid="company-comparison-inputs">
              공통 현재 문서 버전 {view.document_version_ids.length}개 기준으로 서버가 비교 상태를 정했습니다.
            </p>
            <table className="cw-table cw-table-comparison" aria-labelledby="company-comparison-title">
              <thead>
                <tr>
                  <th className="cw-col-company" scope="col">회사</th>
                  <th className="cw-col-status" scope="col">비교 상태</th>
                  <th scope="col">회사 핏</th>
                  <th scope="col">심층 검토</th>
                  <th scope="col">추적 결정</th>
                  <th scope="col">그래프 버전</th>
                </tr>
              </thead>
              <tbody>
                {view.items.map((item) => (
                  <tr data-company-slug={item.company.slug} key={item.company.company_id}>
                    <td>
                      <span className="cw-cell-stack">
                        <Link className="cw-link" to={`/companies/${item.company.company_id}/pre-specs/${noticeId}`}>{item.company.name}</Link>
                        <span className="cw-caption">{item.company.slug}</span>
                      </span>
                    </td>
                    <td data-comparison-status={item.comparison_status}>
                      <span className="cw-cell-stack">
                        <Badge variant={comparisonVariant(item.comparison_status)} label={companyComparisonStatusLabel(item.comparison_status)} />
                        <span className="cw-caption">{companyComparisonStatusNote(item.comparison_status)}</span>
                      </span>
                    </td>
                    <td><CompanyFitSummaryView fit={item.fit} showSummary /></td>
                    <td><CompanyReviewSummaryView review={item.review} /></td>
                    <td><CompanyTrackingSummaryView tracking={item.tracking} showReason /></td>
                    <td data-graph-version={item.graph_version_id ?? "null"}>
                      {item.graph_version_id
                        ? <code title={item.graph_version_id}>{shortIdentity(item.graph_version_id, 8)}</code>
                        : <span className="cw-caption">그래프 버전 없음</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <section aria-label="비교 상태 안내" className="cw-legend">
              <h3>비교 상태 안내</h3>
              <p className="cw-caption">여러 조건에 걸리면 서버가 다른 입력, 이전 입력, 결과 없음, 비교 가능 순으로 하나만 정합니다.</p>
              <dl className="cw-facts">
                {COMPANY_COMPARISON_STATUS_PRIORITY.map((status) => (
                  <div className="cw-legend-row" key={status}>
                    <dt>{companyComparisonStatusLabel(status)}</dt>
                    <dd className="cw-caption">{companyComparisonStatusNote(status)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          </>
        ) : null}
      </div>
    </section>
  );
}
