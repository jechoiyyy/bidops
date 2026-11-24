import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { wiki, type WikiMetric } from "../../lib/companyWikiApi";
import { wikiUrl } from "./WikiBody";

function MetricTable({ label, metrics }: { label: string; metrics: WikiMetric[] }) {
  return <table aria-label={label}><thead><tr><th>확인 항목</th><th>측정 결과</th></tr></thead>
        <tbody>{metrics.map(row => <tr key={row.label}><th scope="row">{row.label}</th>
          <td>{row.denominator ? `${row.numerator} / ${row.denominator} (${Math.round(row.numerator / row.denominator * 100)}%)` : "계산 대상 없음"}</td></tr>)}</tbody></table>;
}

export function WikiQuality() {
  const query = useQuery(wiki.quality);
  if (query.isError) return <p role="alert">평가 기록을 확인하지 못했어요. <button onClick={() => void query.refetch()}>다시 조회</button></p>;
  if (!query.data) return <p role="status">평가 기록을 확인하고 있어요.</p>;
  const { evaluation, metrics, status } = query.data;
  return <section className="wiki-content">
    <h2>회사 근거 답변 품질</h2>
    {!evaluation ? <p>{status === "stale" ? "평가 이후 회사 자료가 바뀌었어요. 현재 자료의 답변 품질은 미측정이에요."
      : "미측정 · 이 회사 자료로 답변을 검증한 기록이 없어요."}</p> : <>
      <p>{evaluation.reviewed_on} · 질문 {evaluation.cases.length}개 · 검수 {evaluation.reviewer}</p>
      <p>질문셋 {evaluation.dataset_version} · 모델 {evaluation.model_version} · 채점 기준 {evaluation.rubric_version}{evaluation.judge_version && ` · 채점 모델 ${evaluation.judge_version}`}</p>
      <MetricTable label="사람 검수 결과" metrics={metrics.filter(row => row.group === "answer")} />
      <details><summary>근거 탐색과 채점 모델 검증</summary>
        <MetricTable label="검증 상세" metrics={metrics.filter(row => row.group === "diagnostic")} />
      </details>
      <h3>질문별 근거 확인</h3>
      {evaluation.cases.map(c => <details key={c.id}><summary>{c.correct ? "결론 일치" : "결론 불일치"} · {c.question}</summary>
        <dl><dt>기대 답변</dt><dd>{c.expected_answer}</dd><dt>실제 답변</dt><dd>{c.answer}</dd>
          {c.judge_correct != null && <><dt>채점 모델</dt><dd>{c.judge_correct ? "결론 일치" : "결론 불일치"}</dd></>}
          <dt>사람 검수</dt><dd>{c.reviewer_note}</dd></dl>
        {c.claims.map((claim, i) => <div key={i}><strong>{claim.grounded ? "근거 확인" : "근거 없는 단정"} · {claim.text}</strong>
          {claim.citations.map((cite, j) => <p key={j}>{cite.supports_claim ? "인용 적절" : "인용 확인 필요"} · {cite.quote} <Link to={wikiUrl("pages", { page: cite.page })}>원문 보기</Link></p>)}</div>)}
        <p>필수 근거 묶음 · {c.required_groups.map(group => group.join(" 또는 ")).join(", ") || "없음"}</p>
        <p>실제 읽은 페이지 · {c.read_pages?.join(", ") || (c.read_pages ? "0개" : "미수집")}</p>
        <p>도구 호출 {c.tool_calls ?? "미수집"} · 토큰 {c.tokens ?? "미수집"} · 소요 시간 {c.duration_ms == null ? "미수집" : `${c.duration_ms}ms`}</p>
      </details>)}
    </>}
  </section>;
}
