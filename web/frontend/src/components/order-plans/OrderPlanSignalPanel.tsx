import { Heading } from "@astryxdesign/core/Heading";
import { ReviewValue } from "../common/ReviewPrimitives";
import type { OrderPlanListItem } from "../../lib/types";
import { formatMoment, stage1RowLabel, stage2Label } from "./orderPlanFormat";

function formatScore(value: number | null): string {
  return value === null ? "null (값 없음/미측정)" : value.toLocaleString("ko-KR", { maximumFractionDigits: 4 });
}

/** BM25 rank/score/nearest capability와 Qwen score/reason. 목록 행에서 뺀 신호 세부다. */
export function OrderPlanSignalPanel({ item }: { item: OrderPlanListItem }) {
  return (
    <div className="c2l-verdict">
      {/* source run·관측 시각은 기본 상세에서 뺐지만(시안) 삭제하지 않고 여기 남긴다(F3). */}
      <dl className="c2l-signal-facts">
        <div><dt>source run</dt><dd className="c2l-digest"><ReviewValue value={item.source_run_id} nullLabel="null (미제공)" /></dd></div>
        <div><dt>관측 시각</dt><dd>{formatMoment(item.observed_at)}</dd></div>
      </dl>
      <div className="c2l-signal-grid">
        <section className="c2l-signal" aria-labelledby={`c2l-bm25-${item.order_plan_pk}`}>
          <Heading level={5} id={`c2l-bm25-${item.order_plan_pk}`}>BM25 후보 신호</Heading>
          <dl className="c2l-signal-facts">
            <div><dt>status</dt><dd>{stage1RowLabel(item.stage1_status)}</dd></div>
            <div><dt>rank</dt><dd>{item.stage1_rank === null ? "null (값 없음/미측정)" : item.stage1_rank}</dd></div>
            <div><dt>score</dt><dd>{formatScore(item.stage1_score)}</dd></div>
            <div><dt>nearest capability</dt><dd><ReviewValue value={item.nearest_capability} nullLabel="null (미제공)" /></dd></div>
          </dl>
        </section>
        <section className="c2l-signal" aria-labelledby={`c2l-qwen-${item.order_plan_pk}`}>
          <Heading level={5} id={`c2l-qwen-${item.order_plan_pk}`}>Qwen relevance 신호</Heading>
          <dl className="c2l-signal-facts">
            {/* status(stage2_status)는 relevance와 별도 축이다: not_attempted·failed·rejected·unknown을
                relevance null 하나로 뭉개지 않는다(F1). */}
            <div><dt>status</dt><dd>{stage2Label(item.stage2_status)}</dd></div>
            <div><dt>relevance</dt><dd>{item.qwen_relevance ?? "null (값 없음/미적용)"}</dd></div>
            <div><dt>score</dt><dd>{formatScore(item.qwen_score)}</dd></div>
            <div><dt>reason</dt><dd><ReviewValue value={item.qwen_reason} nullLabel="null (근거 미제공)" /></dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
}
