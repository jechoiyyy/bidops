import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { getDeepReview, getEvidence, getReport, saveFinalOpinion, saveRevision } from "../components/deep-review/api";
import type {
  DeepReviewReport,
  FinalOpinionValue,
  ReportSectionKey,
  StageName,
} from "../components/deep-review/types";

const STAGE_LABELS: Record<StageName, string> = {
  requirements_and_evaluation: "요구사항·평가",
  delivery_risk_economics: "수행·위험·경제성",
  synthesis_and_validation: "종합·검증",
};

const FINAL_VALUES: FinalOpinionValue[] = ["추진", "조건부 추진", "보류", "검토 종료"];

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "대기", running: "진행 중", completed: "완료", failed: "실패", superseded: "대체됨",
  };
  return labels[status] ?? status;
}

function updateFirstBlock(report: DeepReviewReport, sectionKey: ReportSectionKey, body: string): DeepReviewReport {
  return {
    ...report,
    sections: report.sections.map((section) => section.section_key !== sectionKey
      ? section
      : { ...section, blocks: section.blocks.map((block, index) => index === 0 ? { ...block, body } : block) }),
  };
}

function locatorDetails(locatorType: string, locator: Record<string, string | number | number[] | null>): string {
  if (locatorType === "page") return `page ${String(locator.page ?? "-")}`;
  if (locatorType === "paragraph") {
    return `page ${String(locator.page ?? "-")} · paragraph ${String(locator.paragraph_key ?? locator.block_key ?? "-")} · text ${String(locator.text_start ?? "-")}–${String(locator.text_end ?? "-")}`;
  }
  if (locatorType === "table_cell") {
    return `page ${String(locator.page ?? "-")} · table ${String(locator.table_key ?? "-")} · row ${String(locator.row ?? "-")} · column ${String(locator.column ?? "-")}`;
  }
  if (locatorType === "bbox") {
    const bbox = Array.isArray(locator.bbox) ? locator.bbox.join(", ") : "-";
    return `page ${String(locator.page ?? "-")} · block ${String(locator.block_key ?? "-")} · bbox [${bbox}]`;
  }
  return `fact ${String(locator.fact_key ?? "-")}`;
}

function decisionRowHeading(label: string): string {
  const normalized = label.toLocaleLowerCase();
  if (normalized.includes("차단") || normalized.includes("risk")) return "차단 위험";
  if (normalized.includes("미확인") || normalized.includes("unknown")) return "미확인 사항";
  if (normalized.includes("조치") || normalized.includes("action")) return "다음 조치";
  return "핵심 근거";
}

function EvidenceButton({ id, selected, onSelect }: { id: string; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      style={{
        border: selected ? "2px solid #1b5e73" : "1px solid #c9d5d8", borderRadius: 4, background: "#fff",
        color: "#17343b", cursor: "pointer", fontFamily: "IBM Plex Mono, monospace", fontSize: 12, padding: "4px 7px",
      }}
    >
      근거 {id.slice(0, 8)}
    </button>
  );
}

export function DeepReviewPage() {
  const { deepReviewId } = useParams();
  const reviewId = deepReviewId ?? "";
  const queryClient = useQueryClient();
  const reviewQuery = useQuery({
    queryKey: ["deep-review", reviewId], queryFn: () => getDeepReview(reviewId), enabled: Boolean(reviewId), staleTime: 10_000,
  });
  const reportQuery = useQuery({
    queryKey: ["deep-review-report", reviewId], queryFn: () => getReport(reviewId), enabled: Boolean(reviewId), staleTime: 10_000,
  });
  const reportView = reportQuery.data;
  const [draft, setDraft] = useState<DeepReviewReport | null>(null);
  const [actorName, setActorName] = useState("");
  const [revisionReason, setRevisionReason] = useState("");
  const [factualEvidenceText, setFactualEvidenceText] = useState("");
  const [editSection, setEditSection] = useState<ReportSectionKey>("project_overview");
  const [opinionValue, setOpinionValue] = useState<FinalOpinionValue>("보류");
  const [opinionReason, setOpinionReason] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);

  useEffect(() => {
    if (reportView?.report) setDraft(reportView.report);
  }, [reportView]);

  const currentReport = draft ?? reportView?.report ?? null;
  const currentSection = currentReport?.sections.find((section) => section.section_key === editSection) ?? null;
  const evidenceIds = useMemo(() => {
    const values = currentReport?.claims.flatMap((claim) => claim.evidence_ids) ?? [];
    return [...new Set(values)];
  }, [currentReport]);
  const evidenceQuery = useQuery({
    queryKey: ["deep-review-evidence", selectedEvidenceId],
    queryFn: () => getEvidence(selectedEvidenceId as string),
    enabled: Boolean(selectedEvidenceId),
  });

  const revisionMutation = useMutation({
    mutationFn: () => {
      if (!draft || !reportView) throw new Error("수정할 report가 없습니다.");
      const ids = factualEvidenceText.split(",").map((value) => value.trim()).filter(Boolean);
      return saveRevision(reviewId, actorName, {
        request_id: crypto.randomUUID(), base_revision_id: reportView.current_revision_id, report: draft,
        reason: revisionReason, factual_change_evidence_ids: ids,
      });
    },
    onSuccess: async () => {
      setRevisionReason(""); setFactualEvidenceText("");
      await queryClient.invalidateQueries({ queryKey: ["deep-review-report", reviewId] });
    },
  });
  const opinionMutation = useMutation({
    mutationFn: () => {
      if (!reportView) throw new Error("현재 report가 없습니다.");
      return saveFinalOpinion(reviewId, actorName, {
        request_id: crypto.randomUUID(), report_revision_id: reportView.current_revision_id,
        validation_run_id: reportView.validation.validation_run_id, value: opinionValue,
        reason: opinionReason, acknowledged_validation_failure: acknowledged,
      });
    },
    onSuccess: async () => {
      setOpinionReason(""); setAcknowledged(false);
      await queryClient.invalidateQueries({ queryKey: ["deep-review-report", reviewId] });
    },
  });

  if (!reviewId) {
    return <section aria-labelledby="deep-review-title"><h2 id="deep-review-title">심층 검토 보고서</h2><p>심층 검토 식별자가 없습니다.</p></section>;
  }
  const review = reviewQuery.data;
  const attempt = review?.current_attempt;
  const reportError = reportQuery.error ? errorText(reportQuery.error, "보고서를 확인할 수 없습니다.") : null;
  const validationFailed = reportView?.validation.status === "failed";
  const decisionCard = reportView?.report.sections.find((section) => section.section_key === "decision_card");
  const decisionBlocks = decisionCard?.blocks ?? [];

  return (
    <section aria-labelledby="deep-review-title" style={{ display: "grid", gap: 18, maxWidth: 1500 }}>
      <header style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 12, alignItems: "end" }}>
        <div>
          <p style={{ color: "#527078", fontSize: 12, letterSpacing: ".08em", margin: 0 }}>DEEP REVIEW · {reviewId.slice(0, 8)}</p>
          <h2 id="deep-review-title" style={{ margin: "5px 0 0" }}>심층 검토 보고서</h2>
        </div>
        <div aria-label="보고서 범위" style={{ color: "#527078", fontSize: 13 }}>공고 {review?.notice_id ?? "확인 중"} · bundle {review?.bundle_id.slice(0, 8) ?? "확인 중"}</div>
      </header>

      <section aria-labelledby="preparation-title" style={{ border: "1px solid #d4e0e2", borderRadius: 8, padding: 16, background: "#f8fbfb" }}>
        <h3 id="preparation-title" style={{ marginTop: 0 }}>문서 준비 및 분석 진행</h3>
        <p style={{ marginBottom: 12 }}>문서 준비 상태는 서버가 고정한 bundle과 안전 검사 결과를 기준으로 표시됩니다.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
          <div><strong>검토 상태</strong><br />{review ? statusLabel(review.status) : "불러오는 중"}</div>
          <div><strong>현재 attempt</strong><br />{attempt ? `${attempt.sequence}회 · ${statusLabel(attempt.status)}` : "없음"}</div>
          {(attempt?.stages ?? []).map((stage) => (
            <div key={stage.stage} style={{ borderLeft: "3px solid #6b9da5", paddingLeft: 9 }}>
              <strong>{STAGE_LABELS[stage.stage]}</strong><br />{statusLabel(stage.status)}
              {stage.last_error_code ? <small style={{ display: "block" }}>안전한 오류 코드: {stage.last_error_code}</small> : null}
            </div>
          ))}
        </div>
      </section>

      {reportError && !reportView ? <p role="status" style={{ color: "#8a3b3b" }}>{reportError}</p> : null}
      {reportView ? (
        <>
          <section aria-labelledby="decision-title" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
            <div style={{ border: "2px solid #1b5e73", borderRadius: 8, padding: 16, background: "#eef7f8" }}>
              <h3 id="decision-title" style={{ marginTop: 0 }}>시스템 권고</h3>
              <p style={{ fontSize: 24, fontWeight: 600, margin: "7px 0" }}>{reportView.report.system_recommendation}</p>
              <p style={{ marginBottom: 0 }}>자동 권고는 사람의 최종 의견과 별도이며, 서버가 저장한 claim·validation을 재판정하지 않습니다.</p>
              <div aria-label="결정 카드 요약" style={{ display: "grid", gap: 9, marginTop: 14 }}>
                {decisionBlocks.flatMap((block) => block.rows).map((row) => (
                  <div key={row.row_key} style={{ borderTop: "1px solid #b8d0d4", paddingTop: 8 }}>
                    <strong>{decisionRowHeading(row.label)}</strong>
                    <p style={{ margin: "3px 0", whiteSpace: "pre-wrap" }}>{row.cells.join(" · ")}</p>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                      {row.claim_ids.flatMap((claimId) => reportView.report.claims.find((claim) => claim.claim_id === claimId)?.evidence_ids ?? []).map((id) => (
                        <EvidenceButton key={`${row.row_key}-${id}`} id={id} selected={id === selectedEvidenceId} onSelect={() => setSelectedEvidenceId(id)} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ border: "1px solid #d4e0e2", borderRadius: 8, padding: 16 }}>
              <h3 style={{ marginTop: 0 }}>사람 최종 의견</h3>
              {reportView.final_opinion ? <p><strong>{reportView.final_opinion.value}</strong> · {reportView.final_opinion.reason}</p> : <p>아직 기록되지 않았습니다.</p>}
              <p style={{ marginBottom: 0 }}>현재 validation: <strong>{reportView.validation.status === "passed" ? "통과" : "실패"}</strong> · 실패 시 acknowledge가 필요합니다.</p>
            </div>
          </section>

          <section aria-labelledby="validation-title" style={{ border: "1px solid #d4e0e2", borderRadius: 8, padding: 16 }}>
            <h3 id="validation-title" style={{ marginTop: 0 }}>검증 결과와 unknown</h3>
            <p>상태: <strong>{reportView.validation.status === "passed" ? "통과" : "실패"}</strong> · 실패 {reportView.report.validation_summary.failed} · 경고 {reportView.report.validation_summary.warnings}</p>
            {reportView.report.unknowns.length > 0 ? <ul>{reportView.report.unknowns.map((unknown) => <li key={unknown}>{unknown}</li>)}</ul> : <p>미확인 사항이 없습니다.</p>}
            <ul>{reportView.validation.checks.map((check) => <li key={`${check.check_type}-${check.message}`}>{check.status} · {check.message}</li>)}</ul>
          </section>

          <div style={{ display: "grid", gap: 16 }}>
            {reportView.report.sections.map((section) => (
              <section key={section.section_key} aria-labelledby={`section-${section.section_key}`} style={{ border: "1px solid #d4e0e2", borderRadius: 8, padding: 16 }}>
                <h3 id={`section-${section.section_key}`} style={{ marginTop: 0 }}>{section.title}</h3>
                {section.blocks.map((block) => (
                  <div key={block.block_id} style={{ marginBottom: 12 }}>
                    {block.title ? <h4>{block.title}</h4> : null}
                    {block.body ? <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.65 }}>{block.body}</p> : null}
                    {block.rows.length > 0 ? (
                      <div style={{ overflowX: "auto", maxWidth: "100%" }} tabIndex={0} aria-label={`${section.title} 표를 좌우로 이동할 수 있습니다`}>
                        <table style={{ borderCollapse: "collapse", minWidth: 720, width: "100%" }}>
                          <thead><tr><th scope="col" style={{ textAlign: "left", padding: 8, borderBottom: "2px solid #9eb5ba" }}>항목</th><th scope="col" style={{ textAlign: "left", padding: 8, borderBottom: "2px solid #9eb5ba" }}>내용</th><th scope="col" style={{ textAlign: "left", padding: 8, borderBottom: "2px solid #9eb5ba" }}>근거</th></tr></thead>
                          <tbody>{block.rows.map((row) => <tr key={row.row_key}><th scope="row" style={{ textAlign: "left", verticalAlign: "top", padding: 8, borderBottom: "1px solid #d4e0e2", whiteSpace: "nowrap" }}>{row.label}</th><td style={{ padding: 8, borderBottom: "1px solid #d4e0e2", whiteSpace: "pre-wrap" }}>{row.cells.join(" · ")}</td><td style={{ padding: 8, borderBottom: "1px solid #d4e0e2" }}>{row.claim_ids.flatMap((claimId) => reportView.report.claims.find((claim) => claim.claim_id === claimId)?.evidence_ids ?? []).map((id) => <EvidenceButton key={id} id={id} selected={id === selectedEvidenceId} onSelect={() => setSelectedEvidenceId(id)} />)}</td></tr>)}</tbody>
                        </table>
                      </div>
                    ) : null}
                  </div>
                ))}
              </section>
            ))}
          </div>

          <section aria-labelledby="evidence-title" style={{ border: "1px solid #d4e0e2", borderRadius: 8, padding: 16 }}>
            <h3 id="evidence-title" style={{ marginTop: 0 }}>원문 근거 뷰어</h3>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {evidenceIds.length > 0 ? evidenceIds.map((id) => <EvidenceButton key={id} id={id} selected={id === selectedEvidenceId} onSelect={() => setSelectedEvidenceId(id)} />) : <span>연결된 근거가 없습니다.</span>}
            </div>
            {evidenceQuery.isLoading ? <p role="status">근거를 불러오는 중입니다.</p> : null}
            {evidenceQuery.error ? <p role="status" style={{ color: "#8a3b3b" }}>{errorText(evidenceQuery.error, "근거를 확인할 수 없습니다.")}</p> : null}
            {evidenceQuery.data ? <div style={{ marginTop: 14, display: "grid", gap: 6 }}>
              <p><strong>출처:</strong> {evidenceQuery.data.source_kind === "document" ? "확인된 문서" : "고정 profile fact"} · <strong>locator:</strong> {locatorDetails(evidenceQuery.data.locator_type, evidenceQuery.data.locator)}</p>
              <blockquote style={{ margin: 0, borderLeft: "3px solid #6b9da5", paddingLeft: 12 }}>{evidenceQuery.data.quote}</blockquote>
              <p style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: 12, overflowWrap: "anywhere" }}>source hash: {evidenceQuery.data.source_sha256} · 근거 confidence: {evidenceQuery.data.confidence === null ? "값 없음" : evidenceQuery.data.confidence.toFixed(3)}</p>
              {evidenceQuery.data.page ? (
                <div aria-label="안전한 페이지 projection" style={{ display: "grid", gap: 8 }}>
                  <p style={{ margin: 0 }}>page {evidenceQuery.data.page.page} · {evidenceQuery.data.page.blocks.length}개 안전한 block</p>
                  {evidenceQuery.data.page.blocks.map((block) => (
                    <article key={block.block_key} style={{ border: "1px solid #d4e0e2", borderRadius: 5, padding: 8 }}>
                      <strong>{block.block_key}</strong>
                      <p style={{ whiteSpace: "pre-wrap", margin: "4px 0" }}>{block.text || "추출된 text 없음"}</p>
                      <small>OCR confidence: {block.confidence === null ? "값 없음" : block.confidence.toFixed(3)} · bbox: {block.bbox ? `[${block.bbox.join(", ")}]` : "값 없음"}</small>
                    </article>
                  ))}
                </div>
              ) : null}
            </div> : null}
          </section>

          <section aria-labelledby="history-title" style={{ border: "1px solid #d4e0e2", borderRadius: 8, padding: 16 }}>
            <h3 id="history-title" style={{ marginTop: 0 }}>revision 이력</h3>
            <ol>{reportView.history.map((item) => <li key={item.revision_id}>v{item.sequence} · {item.origin === "machine" ? "시스템" : "사람"} · validation {item.validation_status ?? "값 없음"} · {item.created_by_name ?? "시스템 생성"}</li>)}</ol>
          </section>

          <section aria-labelledby="editor-title" style={{ border: "1px solid #d4e0e2", borderRadius: 8, padding: 16 }}>
            <h3 id="editor-title" style={{ marginTop: 0 }}>사람 revision 편집</h3>
            <p>저장은 전체 report snapshot을 새 immutable revision으로 추가합니다. 담당자 이름은 인증이 아닌 입력된 claimed name입니다.</p>
            <div style={{ display: "grid", gap: 10, maxWidth: 900 }}>
              <label>담당자 claimed name<input value={actorName} onChange={(event: ChangeEvent<HTMLInputElement>) => setActorName(event.target.value)} style={{ display: "block", width: "100%", maxWidth: 420, padding: 8, marginTop: 4 }} /></label>
              <label>수정할 절<select aria-label="수정 절 선택" value={editSection} onChange={(event) => setEditSection(event.target.value as ReportSectionKey)} style={{ display: "block", maxWidth: 420, padding: 8, marginTop: 4 }}>{(currentReport?.sections ?? []).map((section) => <option key={section.section_key} value={section.section_key}>{section.title}</option>)}</select></label>
              <label>절 내용<textarea aria-label="절 내용" rows={5} value={currentSection?.blocks[0]?.body ?? ""} onChange={(event) => setDraft((value) => value ? updateFirstBlock(value, editSection, event.target.value) : value)} style={{ width: "100%", padding: 8 }} /></label>
              <label>수정 사유<textarea aria-label="수정 사유" rows={3} value={revisionReason} onChange={(event) => setRevisionReason(event.target.value)} style={{ width: "100%", padding: 8 }} /></label>
              <label>사실 변경 evidence ID (쉼표 구분)<input value={factualEvidenceText} onChange={(event) => setFactualEvidenceText(event.target.value)} style={{ width: "100%", padding: 8, fontFamily: "IBM Plex Mono, monospace" }} /></label>
              <button type="button" onClick={() => revisionMutation.mutate()} disabled={revisionMutation.isPending || !actorName.trim() || !revisionReason.trim()} style={{ justifySelf: "start", padding: "9px 14px" }}>전체 snapshot revision 저장</button>
              {revisionMutation.error ? <p role="alert">{errorText(revisionMutation.error, "revision을 저장할 수 없습니다.")}</p> : null}
            </div>
          </section>

          <section aria-labelledby="opinion-title" style={{ border: "1px solid #d4e0e2", borderRadius: 8, padding: 16 }}>
            <h3 id="opinion-title" style={{ marginTop: 0 }}>최종 의견 추가</h3>
            <div style={{ display: "grid", gap: 10, maxWidth: 900 }}>
              <label>최종 의견<select value={opinionValue} onChange={(event) => setOpinionValue(event.target.value as FinalOpinionValue)} style={{ display: "block", padding: 8, marginTop: 4 }}>{FINAL_VALUES.map((value) => <option key={value}>{value}</option>)}</select></label>
              <label>최종 의견 사유<textarea aria-label="최종 의견 사유" rows={3} value={opinionReason} onChange={(event) => setOpinionReason(event.target.value)} style={{ width: "100%", padding: 8 }} /></label>
              {validationFailed ? <label><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /> validation 실패를 확인했으며 실패 label을 유지합니다.</label> : null}
              <button type="button" onClick={() => opinionMutation.mutate()} disabled={opinionMutation.isPending || !actorName.trim() || !opinionReason.trim() || (validationFailed && !acknowledged)} style={{ justifySelf: "start", padding: "9px 14px" }}>최종 의견 append</button>
              {opinionMutation.error ? <p role="alert">{errorText(opinionMutation.error, "최종 의견을 저장할 수 없습니다.")}</p> : null}
            </div>
          </section>
        </>
      ) : null}
    </section>
  );
}

export default DeepReviewPage;
