import { useEffect, useRef, useState } from "react";
import { useQuery, type QueryKey } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { getEvidence } from "./api";
import type { EvidenceView, NarrativeReport, NarrativeRole, ValidationCheck } from "./types";
import { qualityStatusLabel } from "../../lib/qualityStatus";
import { formatDateTime } from "../../lib/format";
import "../../styles/narrative-report.css";

const ROLE: Record<NarrativeRole, string> = { source: "문서 조건", company_basis: "회사 근거", impact: "우리에게 미치는 영향", action: "확인할 일", decision_condition: "판단 갱신 조건", synthesis: "종합 해석", recommendation: "시스템 권고" };
const KIND = { fact: "사실", calculation: "계산", inference: "해석", opinion: "의견", unknown: "미확인" };

/**
 * 근거 원문을 어디서 읽을지. reader는 그대로 두고 조회 endpoint와 cache key만 바꾼다.
 * 기본은 기존 단일회사 경로(`GET /api/evidence/{id}`, `["deep-review-evidence", id]`)다.
 * 회사 보고서는 회사 근거 endpoint와 회사 key를 넘겨 다른 회사의 cache를 공유하지 않는다.
 */
export interface EvidenceSource {
  queryKey: (evidenceId: string) => QueryKey;
  fetch: (evidenceId: string) => Promise<EvidenceView>;
}

const DEFAULT_EVIDENCE_SOURCE: EvidenceSource = {
  queryKey: (evidenceId) => ["deep-review-evidence", evidenceId],
  fetch: (evidenceId) => getEvidence(evidenceId),
};

export function NarrativeReportReader({ report, checks, revision, executionStatus, onRecords, onRefresh, onAnalysisSettings, evidenceSource = DEFAULT_EVIDENCE_SOURCE }: { report: NarrativeReport; checks: ValidationCheck[]; revision?: number; executionStatus: string; onRecords: () => void; onRefresh: () => void; onAnalysisSettings: () => void; evidenceSource?: EvidenceSource }) {
  const [large, setLarge] = useState(false);
  const [focused, setFocused] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const sourceTrigger = useRef<HTMLElement | null>(null);
  const panel = useRef<HTMLElement | null>(null);
  const article = useRef<HTMLElement | null>(null);
  const focusTrigger = useRef<HTMLElement | null>(null);
  const evidence = useQuery({ queryKey: selected === null ? ["deep-review-evidence", null] : evidenceSource.queryKey(selected), queryFn: () => evidenceSource.fetch(selected!), enabled: selected !== null });
  const resultValidationSkipped = checks.some(check => check.check_type === "result_validation_skipped");
  const sourceVerificationSkipped = checks.some(check => check.check_type === "source_verification_skipped");
  const byId = new Map(report.claims.map(row => [row.claim_id, row]));
  const sourceIds = [...new Set(report.claims.flatMap(row => row.evidence_ids))];
  const closeSource = () => { setSelected(null); sourceTrigger.current?.focus(); };
  useEffect(() => {
    if (selected) panel.current?.focus();
  }, [selected]);
  const navigate = (id: string) => {
    const target = document.getElementById(id);
    target?.scrollIntoView({ block: "start", behavior: "instant" });
    target?.focus({ preventScroll: true });
  };
  return <article ref={article} className={`narrative-report${large ? " is-large" : ""}${focused ? " is-focused" : ""}`} aria-label="심층검토 보고서 본문" onKeyDown={event => {
    if (!focused) return;
    if (event.key === "Escape") { setFocused(false); focusTrigger.current?.focus(); }
    if (event.key === "Tab") {
      const controls = Array.from(article.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], summary') ?? []).filter(element => element.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }}>
    <header className="narrative-masthead">
      <p className="narrative-eyebrow">사전규격 검토 · {revision ? `수정본 ${revision}` : "저장된 보고서"} · {formatDateTime(report.created_at)}</p>
      <h3>문서의 조건에서<br />우리의 판단까지</h3>
      <p>문서가 요구하는 일, 회사 근거와 수행 영향을 읽고 확인할 사항을 결정합니다.</p>
      <div className="narrative-tools">
        <Button label="최신 보고서 확인" variant="ghost" size="sm" onClick={onRefresh} />
        <Button label={large ? "기본 글자" : "큰 글자"} variant="ghost" size="sm" onClick={() => setLarge(!large)} aria-pressed={large} />
        <Button label={focused ? "집중 읽기 종료" : "집중 읽기"} variant="ghost" size="sm" onClick={event => { focusTrigger.current = event.currentTarget; setFocused(!focused); }} aria-pressed={focused} />
        {["completed", "failed"].includes(executionStatus) ? <Button label="분석 설정" variant="ghost" size="sm" onClick={() => { setFocused(false); onAnalysisSettings(); }} /> : null}
        <Button label="검토 의견·수정 기록" size="sm" onClick={() => { setFocused(false); onRecords(); }} />
      </div>
      <p className="narrative-note">{qualityStatusLabel(report.quality_status)} · {resultValidationSkipped ? "검증 미실시 · 내용·참조·누락을 직접 확인하십시오" : sourceVerificationSkipped ? "원문 대조 미실시" : "근거 검증"} {resultValidationSkipped ? "" : sourceVerificationSkipped ? "· 인용과 수치는 직접 확인하십시오" : report.validation_summary.status === "passed" ? (report.validation_summary.warnings ? `확인 필요 ${report.validation_summary.warnings}건` : "통과") : "실패 · 원문 재확인 필요"}. 최종 입찰 Go/No-Go는 별도 판단입니다.</p>
      {executionStatus !== "completed" ? <p role="status" className="narrative-notice">이전 완성 보고서를 표시합니다. 현재 분석은 {executionStatus === "failed" ? "실패했습니다" : "진행 중입니다"}. 새 분석이 완료되기 전에는 이 보고서를 수정하거나 의견을 저장할 수 없습니다.</p> : null}
    </header>
    <div className={`narrative-reading${selected ? " has-source" : ""}`}>
      <nav aria-label="보고서 목차" className="narrative-toc">
        <strong>읽는 순서</strong>
        <ol>{report.sections.map((section, index) => <li key={section.section_key}><a href={`#narrative-${section.section_key}`} onClick={event => { event.preventDefault(); navigate(`narrative-${section.section_key}`); }}><small>{String(index + 1).padStart(2, "0")}</small>{section.title}</a></li>)}</ol>
      </nav>
      <div className="narrative-paper">
        {report.sections.map((section, index) => <section key={section.section_key} id={`narrative-${section.section_key}`} tabIndex={-1} aria-labelledby={`narrative-title-${section.section_key}`} className="narrative-section">
          <header><span className="narrative-number">{String(index + 1).padStart(2, "0")}</span><h4 id={`narrative-title-${section.section_key}`}>{section.title}</h4></header>
          {section.status === "not_analyzed" ? <p className="narrative-notice">이 항목의 분석이 제공되지 않았습니다. 문제가 없다는 뜻이 아니며 원문 확인이 필요합니다.</p> : null}
          {[...section.blocks].sort((a, b) => Number(b.is_key_point) - Number(a.is_key_point)).map(block => {
            const claim = byId.get(block.claim_ids[0]);
            if (!claim) return null;
            const incoming = report.claims.filter(row => row.related_claim_ids.includes(claim.claim_id) || row.premise_claim_ids.includes(claim.claim_id)).map(row => row.claim_id);
            const related = [...new Set([...claim.related_claim_ids, ...claim.premise_claim_ids, ...incoming])].map(id => byId.get(id)).filter(row => row !== undefined);
            return <div key={block.block_id} id={`narrative-claim-${claim.claim_id}`} tabIndex={-1} className={`narrative-passage${block.is_key_point ? " is-key" : ""}`} data-claim-id={claim.claim_id}>
              <div className="narrative-passage-label"><strong>{block.is_key_point ? "핵심 · " : ""}{ROLE[claim.narrative_role]}</strong><span>{KIND[claim.claim_type]}{claim.status === "unsupported" ? " · 근거 부족" : claim.status === "conflicting" ? " · 근거 충돌" : ""}</span></div>
              {block.title && block.title !== "system_recommendation" ? <h5>{block.title}</h5> : null}
              <p className="narrative-body">{block.body}</p>
              {checks.filter(check => check.status !== "passed" && check.related_claim_ids.includes(claim.claim_id)).map((check, index) => <p key={`${check.check_type}-${index}`} className="narrative-notice"><strong>확인할 점</strong> {check.message}</p>)}
              {claim.reason ? <p className="narrative-reason"><strong>판단의 이유</strong> {claim.reason}</p> : null}
              {claim.formula ? <p className="narrative-reason"><strong>계산 근거</strong> {claim.formula}</p> : null}
              <div className="narrative-sources">{claim.evidence_ids.map(id => <Button key={id} label={`근거 ${sourceIds.indexOf(id) + 1} 확인`} size="sm" variant="ghost" aria-pressed={selected === id} onClick={event => { sourceTrigger.current = event.currentTarget; setSelected(id); }} />)}{claim.evidence_ids.length === 0 ? <small>연결된 원문 근거 없음</small> : null}</div>
              {related.length ? <div className="narrative-connections" aria-label="연결된 조건과 판단"><span>이 내용의 연결</span>{related.map(row => <a key={row.claim_id} href={`#narrative-claim-${row.claim_id}`} onClick={event => { event.preventDefault(); navigate(`narrative-claim-${row.claim_id}`); }}>{ROLE[row.narrative_role]} · {row.narrative_role === "recommendation" ? row.body : row.category} →</a>)}</div> : null}
            </div>;
          })}
        </section>)}
        <section className="narrative-limits" aria-label="분석 범위와 미확인 사항"><h4>판단 전에 확인할 한계</h4><ul>{report.analysis_limitations.map(text => <li key={text}>{text}</li>)}</ul><h5>아직 확인되지 않은 내용</h5>{report.unknowns.length ? <ul>{report.unknowns.map(text => <li key={text}>{text}</li>)}</ul> : <p>별도로 기록된 미확인 사항은 없습니다. 분석이 제공되지 않은 항목까지 확인되었다는 의미는 아닙니다.</p>}</section>
      </div>
      {selected ? <aside ref={panel} tabIndex={-1} className="narrative-source-panel" aria-label="선택한 원문 근거" onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); closeSource(); } }}>
        <header><h4>근거 {sourceIds.indexOf(selected) + 1}</h4><Button label="근거 닫기" size="sm" variant="ghost" onClick={closeSource} /></header>
        {evidence.isPending ? <p role="status">원문을 불러오고 있습니다.</p> : null}
        {evidence.isError ? <><p role="alert">원문 근거를 불러오지 못했습니다.</p><Button label="근거 다시 조회" onClick={() => void evidence.refetch()} /></> : null}
        {evidence.data ? <>{evidence.data.source_verification_enabled === false ? <p className="narrative-notice">원문 대조 미실시 · 모델이 인용한 내용은 아래 원문과 직접 비교하십시오.</p> : null}<p className="narrative-eyebrow">{evidence.data.source_kind === "profile" ? "승인된 회사 자료" : evidence.data.source_verification_enabled === false ? "모델이 인용한 내용" : `문서 원문 · ${evidence.data.locator.page ?? evidence.data.page?.page ?? "쪽수 미확인"}${evidence.data.locator.page || evidence.data.page ? "쪽" : ""}`}</p><blockquote>{evidence.data.quote}</blockquote>{evidence.data.page ? <details open={evidence.data.source_verification_enabled === false}><summary>같은 페이지의 문맥 보기</summary>{evidence.data.page.blocks.map(row => <p key={row.block_key}>{row.text || "추출된 본문 없음"}</p>)}</details> : null}</> : null}
      </aside> : null}
    </div>
  </article>;
}
