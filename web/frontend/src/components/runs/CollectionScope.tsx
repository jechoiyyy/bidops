import type { CollectionScopeResponse } from "../../lib/types";
import { formatRunRange, formatNumber, present } from "../../lib/format";

interface CollectionScopeProps {
  scope: CollectionScopeResponse;
  runId: string;
}

export function CollectionScope({ scope, runId }: CollectionScopeProps) {
  return (
    <section className="panel runs-panel">
      <div className="panel-header"><h3>수집 범위</h3><span className="panel-meta">{present(runId, "회차 미확인")}</span></div>
      <div className="panel-body runs-scope-body">
        <div className="runs-scope-row"><span>기간</span><strong className="mono">{formatRunRange(runId, scope.window_from, scope.window_to)}</strong><em>{present(scope.timezone, "시간대 미확인")}</em></div>
        <div className="runs-scope-row"><span>업무 구분</span><strong>{present(scope.business_area, "업무 구분 미확인")}</strong></div>
        <div className="runs-scope-row runs-scope-row-alert"><span>사전규격</span><strong>{scope.pre_spec_available === true ? "수집 가능" : scope.pre_spec_available === false ? "수집되지 않음" : "확인 불가"}</strong><em>{scope.pre_spec_reason ?? "상태 기록 없음"}</em></div>
        <div className="runs-scope-row"><span>역량 축</span><div className="runs-scope-tags">{scope.focus_axes.length ? scope.focus_axes.map((axis) => <span className="runs-tag" key={axis}>{axis}</span>) : <span className="runs-empty-value">기록 없음</span>}</div></div>
        <div className="runs-scope-row"><span>실적 레퍼런스</span><strong>{scope.performance_reference_count === null ? "기록 없음" : `${formatNumber(scope.performance_reference_count)}건`}</strong></div>
      </div>
    </section>
  );
}
