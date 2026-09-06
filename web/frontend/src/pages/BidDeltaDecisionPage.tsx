import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ActorField } from "../components/common/ActorField";
import {
  ConfirmDecisionDialog,
  decisionSummaryExcerpt,
  type ConfirmDecisionSummaryItem,
} from "../components/common/ConfirmDecisionDialog";
import { DisabledReason } from "../components/common/DisabledReason";
import { EmptyState } from "../components/common/EmptyState";
import { MutationFeedback } from "../components/common/MutationFeedback";
import { StatusBadge, type StatusTone } from "../components/common/StatusBadge";
import { Toast } from "../components/common/Toast";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { ReviewDecisionAction, ReviewHistoryLinkRail, StickyDecisionHeader } from "../components/common/ReviewPrimitives";
import { useToast } from "../components/common/useToast";
import { describeApiError } from "../lib/apiErrors";
import { TERM } from "../lib/glossary";
import {
  createBidDeltaComparison,
  getBidDelta,
  getBidDeltaComparison,
  retryBidDeltaAttempt,
  saveBidFinalDecision,
} from "../components/bid-delta/api";
import type {
  BidDecision,
  BidDeltaCategory,
  BidDeltaComparisonCreateRequest,
  BidDeltaComparisonView,
  BidDeltaEvidenceView,
  BidDeltaInputFence,
  BidDeltaInputRef,
  BidDeltaItemView,
  BidDeltaWorkspaceView,
  CalculationStatus,
  Currentness,
  Materiality,
  ResultStatus,
} from "../components/bid-delta/types";
import "../styles/bid-delta-decision.css";
import "../styles/detail-skeleton.css";

const CATEGORY_LABELS: Record<BidDeltaCategory, string> = {
  budget_and_economics: "금액·경제성",
  contract_period_and_schedule: "계약기간·일정",
  eligibility: "참가자격",
  joint_supply_and_subcontracting: "공동수급·하도급",
  scope_and_requirements: "과업·요구사항",
  evaluation: "평가",
  submission: "제출",
};

const CALCULATION_LABELS: Record<CalculationStatus, string> = {
  pending: "pending · 대기 중",
  running: "running · 계산 중",
  completed: "completed · 계산 완료",
  failed: "failed · 계산 실패",
};

const RESULT_LABELS: Record<ResultStatus, string> = {
  changed: "changed · 변경 있음",
  unchanged: "unchanged · 변경 없음",
  unknown: "unknown · 판단 불가",
  failed: "failed · 분석 실패",
};

const MATERIALITY_LABELS: Record<Materiality, string> = {
  material: "material · 중요 변경",
  non_material: "non_material · 비중요 변경",
  unknown: "unknown · 중요도 미확인",
};

const CURRENTNESS_LABELS: Record<Currentness, string> = {
  current: "current · 현재 유효",
  stale: "stale · 재검토 필요(오래된 결정)",
  unknown: "unknown · 현재성 미확인",
};

const LOCATOR_LABELS: Record<BidDeltaEvidenceView["locator_type"], string> = {
  page: "페이지",
  paragraph: "문단",
  table_cell: "표 셀",
  bbox: "문서 영역",
};

function formatMoment(value: string | null): string {
  if (!value) return "값 없음";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ko-KR");
}

function formatDate(value: string | null): string {
  if (!value) return "값 없음";
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("ko-KR");
}

function shortHash(value: string | null): string {
  return value ? value.slice(0, 12) : "값 없음";
}

function statusTone(status: CalculationStatus | ResultStatus | Currentness | Materiality): StatusTone {
  if (status === "completed" || status === "unchanged" || status === "current") return "success";
  if (status === "failed" || status === "stale") return "danger";
  if (status === "pending" || status === "running" || status === "changed") return "info";
  if (status === "material") return "warning";
  if (status === "non_material") return "success";
  return "warning";
}

function toFence(ref: BidDeltaInputRef): BidDeltaInputFence {
  return {
    opportunity_link_id: ref.opportunity_link_id,
    notice_id: ref.notice_id,
    bundle_id: ref.bundle_id,
    bundle_revision: ref.bundle_revision,
    bundle_version: ref.bundle_version,
    document_version_id: ref.document_version_id,
    document_version_version: ref.document_version_version,
    structure_id: ref.structure_id,
    source_sha256: ref.source_sha256,
    structure_payload_sha256: ref.structure_payload_sha256,
  };
}

function candidateKey(ref: BidDeltaInputRef): string {
  return `${ref.notice_id}:${ref.document_version_id}:${ref.structure_id}`;
}

function InputRefFacts({ input, compact = false }: { input: BidDeltaInputRef; compact?: boolean }) {
  return (
    <dl className={`bid-delta-input-facts ${compact ? "bid-delta-input-facts-compact" : ""}`.trim()}>
      <div><dt>공고 외부 식별자</dt><dd className="mono">{input.notice_external_id}</dd></div>
      <div><dt>공고 출처 유형</dt><dd className="mono">{input.notice_source_type}</dd></div>
      <div><dt>차수</dt><dd>{input.bid_ordinal ?? "값 없음"}</dd></div>
      <div><dt>공개일</dt><dd>{formatMoment(input.published_at)}</dd></div>
      <div><dt>문서 역할</dt><dd>{input.document_role || "값 없음"}</dd></div>
      <div><dt>문서 묶음 수정본 / 버전</dt><dd>{input.bundle_revision} / {input.bundle_version}</dd></div>
      <div><dt>문서 버전</dt><dd>{input.document_version_version}</dd></div>
      {!compact ? <div><dt>시행일</dt><dd>{formatDate(input.effective_date)}</dd></div> : null}
      <div><dt>문서 버전 ID</dt><dd className="mono">{input.document_version_id}</dd></div>
      {!compact ? <div><dt>사업기회 연결 / 공고 ID</dt><dd>{input.opportunity_link_id} / {input.notice_id}</dd></div> : null}
      {!compact ? <div><dt>문서 구조 ID</dt><dd className="mono">{input.structure_id}</dd></div> : null}
      <div><dt>원문 해시 {compact ? "앞 12자" : "SHA-256"}</dt><dd className="mono">{compact ? shortHash(input.source_sha256) : input.source_sha256}</dd></div>
      {!compact ? <div><dt>문서 구조 SHA-256</dt><dd className="mono">{input.structure_payload_sha256}</dd></div> : null}
    </dl>
  );
}

function CandidateCard({
  candidate,
  selected,
  onSelect,
}: {
  candidate: BidDeltaInputRef;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`bid-delta-candidate ${selected ? "bid-delta-candidate-selected" : ""}`.trim()}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="bid-delta-candidate-check">{selected ? "선택됨" : "선택"}</span>
      <strong>{candidate.notice_source_type === "pre_spec" ? "사전규격 기준 후보" : "입찰공고 비교 후보"}</strong>
      <InputRefFacts input={candidate} compact />
    </button>
  );
}

function CurrentnessPanel({
  decision,
  currentness,
  reasons,
  titleId = "bid-delta-currentness-title",
}: {
  decision: BidDeltaWorkspaceView["latest_final_decision"] | BidDeltaComparisonView["latest_final_decision"];
  currentness: Currentness;
  reasons: string[];
  titleId?: string;
}) {
  return (
    <section className="bid-delta-currentness" aria-labelledby={titleId}>
      <div className="bid-delta-panel-heading">
        <div>
          <p className="bid-delta-kicker">최종 결정 {TERM.currentness}</p>
          <h3 id={titleId}>최종 결정 {TERM.currentness}</h3>
        </div>
        <StatusBadge label={CURRENTNESS_LABELS[currentness]} tone={statusTone(currentness)} />
      </div>
      {decision ? (
        <div className="bid-delta-latest-decision">
          <strong>{decision.decision === "go" ? "Go" : "No-Go"} · {decision.claimed_name}</strong>
          <span>결정 {formatMoment(decision.created_at)} · {decision.sequence}번째 결정</span>
          <p>{decision.reason}</p>
        </div>
      ) : <p>아직 최종 결정이 저장되지 않았습니다.</p>}
      <p className="bid-delta-currentness-reasons">
        <span>{TERM.currentness} 근거</span> {reasons.length > 0 ? reasons.join(" · ") : "확인된 재검토 사유 없음"}
      </p>
    </section>
  );
}

function WorkspaceCandidates({
  workspace,
  baseline,
  comparison,
  onBaselineChange,
  onComparisonChange,
}: {
  workspace: BidDeltaWorkspaceView;
  baseline: BidDeltaInputRef | null;
  comparison: BidDeltaInputRef | null;
  onBaselineChange: (value: BidDeltaInputRef) => void;
  onComparisonChange: (value: BidDeltaInputRef) => void;
}) {
  const noBaseline = workspace.baseline_candidates.length === 0;
  const noComparison = workspace.comparison_candidates.length === 0;
  return (
    <section className="bid-delta-workspace-panel" aria-labelledby="bid-delta-candidates-title">
      <div className="bid-delta-panel-heading">
        <div>
          <p className="bid-delta-kicker">비교할 문서 고르기</p>
          <h3 id="bid-delta-candidates-title">비교 문서 후보</h3>
        </div>
        <span className="bid-delta-muted">서버 자동 선택 없음</span>
      </div>
      <p className="bid-delta-help">비교할 문서를 양쪽에서 하나씩 사람이 고릅니다. 후보가 하나뿐인 쪽만 미리 골라 두었고, 요청에는 아래 고정 입력 값 전체를 함께 보냅니다.</p>
      <div className="bid-delta-candidate-columns">
        <div>
          <h4>기준 · 사전규격</h4>
          {noBaseline ? (
            <EmptyState compact tone="warning" title="기준 후보 없음" description="확정된 사전규격 연결과 안전 검사를 마친 문서 묶음이 없어 비교를 시작할 수 없습니다. 이를 변경 없음으로 해석하지 않습니다." />
          ) : (
            <div className="bid-delta-candidate-list">
              {workspace.baseline_candidates.map((item) => (
                <CandidateCard key={candidateKey(item)} candidate={item} selected={candidateKey(item) === (baseline ? candidateKey(baseline) : "")} onSelect={() => onBaselineChange(item)} />
              ))}
            </div>
          )}
          {workspace.baseline_candidates.length === 1 ? <p className="bid-delta-selection-note">후보가 하나여서 미리 선택했습니다.</p> : null}
        </div>
        <div>
          <h4>비교 · 입찰공고</h4>
          {noComparison ? (
            <EmptyState compact tone="warning" title="비교 후보 없음" description="확정된 입찰공고 연결과 안전 검사를 마친 문서 묶음이 없어 비교를 시작할 수 없습니다. 이를 변경 없음으로 해석하지 않습니다." />
          ) : (
            <div className="bid-delta-candidate-list">
              {workspace.comparison_candidates.map((item) => (
                <CandidateCard key={candidateKey(item)} candidate={item} selected={candidateKey(item) === (comparison ? candidateKey(comparison) : "")} onSelect={() => onComparisonChange(item)} />
              ))}
            </div>
          )}
          {workspace.comparison_candidates.length === 1 ? <p className="bid-delta-selection-note">후보가 하나여서 미리 선택했습니다.</p> : null}
        </div>
      </div>
    </section>
  );
}

function ComparisonList({ comparisons, opportunityId, baseSearch }: { comparisons: BidDeltaWorkspaceView["comparisons"]; opportunityId: number; baseSearch: string }) {
  return (
    <section className="bid-delta-comparison-list-panel" aria-labelledby="bid-delta-comparison-list-title">
      <div className="bid-delta-panel-heading">
        <div>
          <p className="bid-delta-kicker">바뀌지 않는 비교 기록</p>
          <h3 id="bid-delta-comparison-list-title">기존 비교 목록</h3>
        </div>
        <span className="bid-delta-muted">{comparisons.length}건</span>
      </div>
      {comparisons.length === 0 ? (
        <EmptyState compact title="생성된 비교가 없습니다." description="비교할 문서를 직접 고른 뒤 비교 시작을 눌러 새 비교를 만드십시오." />
      ) : (
        <ol className="bid-delta-comparison-list">
          {comparisons.map((item) => (
            <li key={item.id}>
              <Link className="bid-delta-comparison-link" to={{ pathname: `/opportunities/${opportunityId}/bid-delta`, search: (() => { const next = new URLSearchParams(baseSearch); next.set("comparison", item.id); return next.toString(); })() }}>
                <span>
                  <strong>비교 #{item.sequence}</strong>
                  <small>버전 {item.version} · 범주 정책 {item.category_policy_version}</small>
                </span>
                <span className="bid-delta-comparison-link-status">
                  <StatusBadge label={CALCULATION_LABELS[item.calculation_status]} tone={statusTone(item.calculation_status)} />
                  <StatusBadge label={item.result_status ? RESULT_LABELS[item.result_status] : "결과 미발행"} tone={item.result_status ? statusTone(item.result_status) : "neutral"} />
                  <StatusBadge label={MATERIALITY_LABELS[item.materiality]} tone={statusTone(item.materiality)} />
                </span>
              </Link>
              <div className="bid-delta-comparison-summary">
                <span>기준 {item.baseline.notice_external_id}</span>
                <span>비교 {item.comparison.notice_external_id}</span>
                <span>생성 {formatMoment(item.created_at)}</span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function CalculationAndResult({ comparison }: { comparison: BidDeltaComparisonView }) {
  const pending = comparison.calculation_status === "pending";
  const running = comparison.calculation_status === "running";
  return (
    <div className="bid-delta-status-grid">
      <section className="bid-delta-status-panel" aria-labelledby="bid-delta-calculation-title">
        <p className="bid-delta-kicker">시스템 계산</p>
        <h3 id="bid-delta-calculation-title">계산 상태</h3>
        <StatusBadge label={CALCULATION_LABELS[comparison.calculation_status]} tone={statusTone(comparison.calculation_status)} />
        <dl className="bid-delta-status-facts">
          <div><dt>시작 시각</dt><dd>{formatMoment(comparison.started_at)}</dd></div>
          <div><dt>완료 시각</dt><dd>{formatMoment(comparison.completed_at)}</dd></div>
          {comparison.last_error_code ? <div><dt>안전한 오류 코드</dt><dd className="mono">{comparison.last_error_code}</dd></div> : null}
        </dl>
        {pending || running ? (
          <div className="bid-delta-worker-note" role="status" aria-live="polite">
            <strong>{pending ? "계산 대기 상태입니다." : "계산 진행 상태를 확인하고 있습니다."}</strong>
            <p>계산을 실행하는 프로그램이 아직 운영에 없습니다. 결과가 나오기 전까지 오류나 변경 없음으로 해석하지 않습니다.</p>
            <small>대기·진행 중일 때만 상태를 자동으로 다시 조회합니다.</small>
          </div>
        ) : null}
      </section>
      <section className="bid-delta-status-panel" aria-labelledby="bid-delta-result-title">
        <p className="bid-delta-kicker">시스템 결과</p>
        <h3 id="bid-delta-result-title">결과 상태</h3>
        {comparison.result_status ? (
          <StatusBadge label={RESULT_LABELS[comparison.result_status]} tone={statusTone(comparison.result_status)} />
        ) : <StatusBadge label="결과 미발행" tone="neutral" />}
        <dl className="bid-delta-status-facts">
          <div><dt>전체 중요도</dt><dd>{MATERIALITY_LABELS[comparison.materiality]}</dd></div>
          <div><dt>결과 SHA-256</dt><dd className="mono">{comparison.result_sha256 ?? "값 없음"}</dd></div>
        </dl>
        {comparison.result_status === "unknown" ? <p className="bid-delta-interpretation">문서 근거로 의미를 확정할 수 없어 미확인 상태입니다.</p> : null}
        {comparison.result_status === "failed" ? <p className="bid-delta-interpretation">계산 전체가 실패하여 결과를 확정할 수 없습니다.</p> : null}
      </section>
    </div>
  );
}

function locatorText(evidence: BidDeltaEvidenceView): string {
  const locator = evidence.locator;
  const page = typeof locator.page === "number" ? `페이지 ${locator.page}` : null;
  const detail = evidence.locator_type === "bbox" && Array.isArray(locator.bbox)
    ? `bbox [${locator.bbox.map((value) => String(value)).join(", ")}]`
    : evidence.locator_type === "table_cell"
      ? `표 ${String(locator.table_key ?? "값 없음")} · 행 ${String(locator.row ?? "값 없음")} · 열 ${String(locator.column ?? "값 없음")}`
      : evidence.locator_type === "paragraph"
        ? `문단 ${String(locator.paragraph_key ?? locator.block_key ?? "값 없음")}`
        : null;
  return [page, detail].filter(Boolean).join(" · ") || JSON.stringify(locator);
}

function EvidenceCard({ evidence, side }: { evidence: BidDeltaEvidenceView | null; side: "baseline" | "comparison" }) {
  if (!evidence) {
    return (
      <article className="bid-delta-evidence-card bid-delta-evidence-missing">
        <strong>{side === "baseline" ? "사전규격 기준 근거" : "입찰공고 비교 근거"}</strong>
        <p>연결된 원문 근거가 없습니다.</p>
        <span>이 상태를 검증된 결과로 표시하지 않습니다.</span>
      </article>
    );
  }
  const verificationLabel = evidence.verification_status === "verified"
    ? "verified · 검증됨"
    : evidence.verification_status === "missing" ? "missing · 근거 없음" : "mismatch · 불일치";
  return (
    <article className={`bid-delta-evidence-card bid-delta-evidence-${evidence.verification_status}`.trim()}>
      <div className="bid-delta-evidence-heading">
        <strong>{side === "baseline" ? "사전규격 기준 근거" : "입찰공고 비교 근거"}</strong>
        <StatusBadge label={verificationLabel} tone={evidence.verification_status === "verified" ? "success" : "warning"} />
      </div>
      <p className="bid-delta-evidence-locator"><span>원문 위치</span> {LOCATOR_LABELS[evidence.locator_type]} · {locatorText(evidence)}</p>
      <blockquote>{evidence.quote ?? "인용 값 없음"}</blockquote>
      <details className="bid-delta-technical-details">
        <summary>기술 식별자 보기</summary>
        <dl>
          <div><dt>근거 ID</dt><dd className="mono">{evidence.id}</dd></div>
          <div><dt>문서 버전 ID</dt><dd className="mono">{evidence.document_version_id}</dd></div>
          <div><dt>문서 구조 ID</dt><dd className="mono">{evidence.structure_id}</dd></div>
          <div><dt>원문 SHA-256</dt><dd className="mono">{evidence.source_sha256}</dd></div>
        </dl>
      </details>
    </article>
  );
}

function DeltaItem({ item }: { item: BidDeltaItemView }) {
  const evidenceCount = Math.max(item.baseline_evidence.length, item.comparison_evidence.length, 1);
  return (
    <article className="bid-delta-item" aria-labelledby={`bid-delta-item-${item.id}`}>
      <header className="bid-delta-item-heading">
        <div>
          <span className="bid-delta-item-ordinal">{item.ordinal}</span>
          <h4 id={`bid-delta-item-${item.id}`}>{CATEGORY_LABELS[item.category]}</h4>
        </div>
        <div className="bid-delta-item-statuses">
          <StatusBadge label={RESULT_LABELS[item.result_status]} tone={statusTone(item.result_status)} />
          <StatusBadge label={MATERIALITY_LABELS[item.materiality]} tone={item.materiality === "material" ? "warning" : statusTone(item.materiality)} />
        </div>
      </header>
      <div className="bid-delta-item-values">
        <div><span>변경 전</span><p>{item.before_value ?? "값 없음"}</p></div>
        <div><span>변경 후</span><p>{item.after_value ?? "값 없음"}</p></div>
        <div><span>업무 요약</span><p>{item.summary ?? "값 없음"}</p></div>
      </div>
      {item.result_status === "unknown" || item.result_status === "failed" ? (
        <p className="bid-delta-item-error"><strong>안전한 오류 코드</strong> <code>{item.error_code ?? "값 없음"}</code> · 이 항목은 변경 없음으로 해석하지 않습니다.</p>
      ) : item.error_code ? <p className="bid-delta-item-error"><strong>안전한 오류 코드</strong> <code>{item.error_code}</code></p> : null}
      <div className="bid-delta-evidence-pairs">
        <h5>양쪽 원문 근거</h5>
        {Array.from({ length: evidenceCount }, (_, index) => (
          <div className="bid-delta-evidence-pair" key={`${item.id}-evidence-${index}`}>
            <EvidenceCard evidence={item.baseline_evidence[index] ?? null} side="baseline" />
            <EvidenceCard evidence={item.comparison_evidence[index] ?? null} side="comparison" />
          </div>
        ))}
      </div>
    </article>
  );
}

function AttemptHistory({ comparison }: { comparison: BidDeltaComparisonView }) {
  const currentAttempt = comparison.attempts.length > 0 ? comparison.attempts[comparison.attempts.length - 1] : null;
  return (
    <section className="bid-delta-attempt-panel" aria-labelledby="bid-delta-attempt-title">
      <div className="bid-delta-panel-heading">
        <div>
          <p className="bid-delta-kicker">계산 회차 · 추가만 기록</p>
          <h3 id="bid-delta-attempt-title">계산 회차 이력</h3>
        </div>
        <span className="bid-delta-muted">{comparison.attempts.length}건</span>
      </div>
      <p className="bid-delta-help">지난 회차를 모두 남기고 지금 회차만 따로 표시합니다.</p>
      {comparison.attempts.length === 0 ? <p>아직 실행한 계산 회차가 없습니다.</p> : (
        <ol className="bid-delta-attempt-list">
          {comparison.attempts.map((attempt) => {
            const current = attempt.id === currentAttempt?.id;
            return (
              <li key={attempt.id} className={current ? "bid-delta-attempt-current" : ""}>
                <div>
                  <strong>{attempt.sequence}회차</strong>
                  {current ? <span className="bid-delta-current-label">현재 회차</span> : null}
                </div>
                <StatusBadge label={attempt.status === "queued" ? "대기" : attempt.status === "running" ? "진행 중" : attempt.status === "completed" ? "완료" : "실패"} tone={statusTone(attempt.status === "queued" ? "pending" : attempt.status === "running" ? "running" : attempt.status)} />
                <span>시작 {formatMoment(attempt.started_at)} · 완료 {formatMoment(attempt.completed_at)}</span>
                {attempt.last_error_code ? <code>오류 코드 {attempt.last_error_code}</code> : null}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function DecisionHistory({
  decisions,
  workspaceLatest,
}: {
  decisions: BidDeltaComparisonView["final_decisions"];
  workspaceLatest: BidDeltaWorkspaceView["latest_final_decision"];
}) {
  const allDecisions = [...decisions];
  if (workspaceLatest && !allDecisions.some((item) => item.id === workspaceLatest.id)) allDecisions.push(workspaceLatest);
  allDecisions.sort((left, right) => left.sequence - right.sequence);
  return (
    <section className="bid-delta-decision-history" aria-labelledby="bid-delta-decision-history-title">
      <div className="bid-delta-panel-heading">
        <div>
          <p className="bid-delta-kicker">사람 기록 · 추가만 기록</p>
          <h3 id="bid-delta-decision-history-title">최종 Go/No-Go 저장 이력</h3>
        </div>
        <span className="bid-delta-muted">{allDecisions.length}건</span>
      </div>
      {allDecisions.length === 0 ? <p>아직 저장된 최종 결정이 없습니다.</p> : (
        <ol className="bid-delta-decision-history-list">
          {allDecisions.map((decision) => (
            <li key={decision.id}>
              <div className="bid-delta-decision-history-heading">
                <strong>{decision.decision === "go" ? "Go" : "No-Go"}</strong>
                <span>{decision.sequence}번째 결정 · {decision.claimed_name}</span>
                <StatusBadge label={CURRENTNESS_LABELS[decision.currentness]} tone={statusTone(decision.currentness)} />
              </div>
              <p>{decision.reason}</p>
              <small>{formatMoment(decision.created_at)} · 비교 버전 {decision.comparison_version} · 대체한 이전 결정 {decision.supersedes_final_decision_id ?? "없음"}</small>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/**
 * 이 화면의 오류 표시 하나.
 *
 * 화면마다 문구 규칙을 따로 두지 않는다. 서버가 준 status와 안전한 오류 코드를
 * `describeApiError`가 제목·설명·다음 행동으로 옮기고, 복구 버튼은 그 행동이
 * `다시 시도`·`최신 상태 다시 불러오기`일 때만 생긴다. 서버 raw message는
 * 화면에 내지 않는다.
 */
function BidDeltaErrorFeedback({ error, fallback, onRefresh, refreshing }: { error: unknown; fallback: string; onRefresh?: () => void; refreshing?: boolean }) {
  return (
    <MutationFeedback
      tone="error"
      problem={describeApiError(error, fallback)}
      onRecover={onRefresh}
      recoverPending={refreshing}
      recoverPendingLabel="최신 상태를 다시 조회 중"
    />
  );
}

export function BidDeltaDecisionPage() {
  const { opportunityId: opportunityIdParam } = useParams();
  const opportunityId = Number(opportunityIdParam);
  const validOpportunityId = Number.isInteger(opportunityId) && opportunityId > 0;
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const selectedComparisonId = searchParams.get("comparison");
  const [baseline, setBaseline] = useState<BidDeltaInputRef | null>(null);
  const [comparison, setComparison] = useState<BidDeltaInputRef | null>(null);
  const [comparisonActor, setComparisonActor] = useState("");
  const [retryActor, setRetryActor] = useState("");
  const [decisionActor, setDecisionActor] = useState("");
  const [decision, setDecision] = useState<BidDecision | "">("");
  const [reason, setReason] = useState("");
  const { toast, showToast, dismissToast } = useToast();
  const [refreshing, setRefreshing] = useState(false);
  // 되돌릴 수 없는 최종 Go/No-Go는 submit 즉시 나가지 않고 확인 단계를 거친다.
  // 저장에 성공하면 입력이 비워지므로, 다이얼로그가 보여 줄 요약은 열 때의 값을
  // 그대로 얼려 둔다(저장 도중 요약이 빈칸으로 바뀌지 않게).
  const [decisionConfirm, setDecisionConfirm] = useState<
    { summary: ConfirmDecisionSummaryItem[]; confirmLabel: string } | null
  >(null);

  const workspaceQuery = useQuery<BidDeltaWorkspaceView>({
    queryKey: ["bid-delta", opportunityId],
    queryFn: () => getBidDelta(opportunityId),
    enabled: validOpportunityId,
  });
  const comparisonQuery = useQuery<BidDeltaComparisonView>({
    queryKey: ["bid-delta-comparison", opportunityId, selectedComparisonId],
    queryFn: () => getBidDeltaComparison(opportunityId, selectedComparisonId as string),
    enabled: validOpportunityId && Boolean(selectedComparisonId),
    refetchInterval: (query) => {
      const calculationStatus = query.state.data?.calculation_status;
      return calculationStatus === "pending" || calculationStatus === "running" ? 1_000 : false;
    },
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    const view = workspaceQuery.data;
    if (!view) return;
    setBaseline((current) => {
      if (current && view.baseline_candidates.some((item) => candidateKey(item) === candidateKey(current))) return current;
      return view.baseline_candidates.length === 1 ? view.baseline_candidates[0] : null;
    });
    setComparison((current) => {
      if (current && view.comparison_candidates.some((item) => candidateKey(item) === candidateKey(current))) return current;
      return view.comparison_candidates.length === 1 ? view.comparison_candidates[0] : null;
    });
  }, [workspaceQuery.data]);

  const comparisonMutation = useMutation({
    mutationFn: () => {
      if (!baseline || !comparison) throw new Error("비교할 문서를 양쪽에서 하나씩 고르십시오.");
      const payload: BidDeltaComparisonCreateRequest = {
        schema_version: "bidops.bid-delta-comparison-create.v1",
        request_id: crypto.randomUUID(),
        category_policy_version: "bid-delta-policy.v1",
        baseline: toFence(baseline),
        comparison: toFence(comparison),
      };
      return createBidDeltaComparison(opportunityId, comparisonActor, payload);
    },
    onSuccess: async (created) => {
      queryClient.setQueryData(["bid-delta-comparison", opportunityId, created.id], created);
      await queryClient.invalidateQueries({ queryKey: ["bid-delta", opportunityId] });
      setComparisonActor("");
      showToast(`비교 #${created.sequence}을 요청했습니다. 계산 대기 상태로 저장되었습니다.`);
      navigate({ pathname: `/opportunities/${opportunityId}/bid-delta`, search: `comparison=${encodeURIComponent(created.id)}` });
    },
  });

  const retryMutation = useMutation({
    mutationFn: () => {
      const current = comparisonQuery.data;
      if (!current || !selectedComparisonId) throw new Error("재시도할 비교가 없습니다.");
      return retryBidDeltaAttempt(opportunityId, selectedComparisonId, retryActor, {
        schema_version: "bidops.bid-delta-attempt-create.v1",
        request_id: crypto.randomUUID(),
        expected_comparison_version: current.version,
      });
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData(["bid-delta-comparison", opportunityId, updated.id], updated);
      setRetryActor("");
      showToast("새 계산 회차를 시작했습니다. 이전 회차는 그대로 남습니다.");
      await queryClient.invalidateQueries({ queryKey: ["bid-delta", opportunityId] });
    },
  });

  const finalDecisionMutation = useMutation({
    mutationFn: () => {
      const current = comparisonQuery.data;
      if (!current || !selectedComparisonId || !current.result_sha256 || !decision) throw new Error("최종 결정 저장 조건이 준비되지 않았습니다.");
      return saveBidFinalDecision(opportunityId, selectedComparisonId, decisionActor, {
        schema_version: "bidops.bid-final-decision-create.v1",
        request_id: crypto.randomUUID(),
        expected_comparison_version: current.version,
        expected_result_sha256: current.result_sha256,
        baseline_document_version_id: current.baseline.document_version_id,
        comparison_document_version_id: current.comparison.document_version_id,
        supersedes_final_decision_id: workspaceQuery.data?.latest_final_decision?.id ?? null,
        decision,
        reason: reason.trim(),
      });
    },
    onSuccess: async (saved) => {
      setDecisionActor("");
      setDecision("");
      setReason("");
      showToast(`${saved.decision === "go" ? "Go" : "No-Go"} 최종 결정을 저장했습니다. 이전 결정은 그대로 남습니다.`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["bid-delta", opportunityId] }),
        queryClient.invalidateQueries({ queryKey: ["bid-delta-comparison", opportunityId, selectedComparisonId] }),
      ]);
    },
  });

  const comparisonReady = Boolean(baseline && comparison && comparisonActor.trim());
  const comparisonDisabledReason = comparisonMutation.isPending
    ? "비교 시작 요청을 처리하고 있습니다."
    : !baseline || !comparison
      ? "비교를 시작하려면 기준 문서와 비교 문서를 각각 고르십시오."
      : !comparisonActor.trim()
        ? "비교를 시작하려면 담당자 이름을 입력하십시오."
        : null;
  const comparisonView = comparisonQuery.data;
  const canRecordDecision = comparisonView?.calculation_status === "completed" && comparisonView.result_status !== "failed";
  const decisionDisabledReason = finalDecisionMutation.isPending
    ? "최종 결정 저장 요청을 처리하고 있습니다."
    : !comparisonView
      ? "비교 상세를 먼저 불러오십시오."
      : !canRecordDecision
        ? comparisonView.result_status === "failed"
          ? "결과가 분석 실패여서 최종 Go/No-Go를 저장할 수 없습니다. 분석 실패를 변경 없음으로 해석하지 마십시오."
          : comparisonView.calculation_status === "failed"
          ? "계산이 실패하여 최종 Go/No-Go를 저장할 수 없습니다. 비교를 재시도하십시오."
          : "계산이 완료될 때까지 최종 Go/No-Go를 저장할 수 없습니다."
        : !decisionActor.trim()
          ? "최종 결정을 저장하려면 담당자 이름을 입력하십시오."
          : !decision
            ? "최종 결정에서 Go 또는 No-Go를 선택하십시오."
            : !reason.trim()
              ? "최종 결정을 저장하려면 이유를 입력하십시오."
              : null;
  const finalReady = canRecordDecision && Boolean(decisionActor.trim() && decision && reason.trim()) && !finalDecisionMutation.isPending;
  const hasUnsavedDraft = Boolean(comparisonActor.trim() || decisionActor.trim() || retryActor.trim() || reason.trim() || decision);
  // 헤더의 "결정 입력으로 이동"은 본문 결정 폼으로 초점을 옮긴다. 스크롤만
  // 하면 키보드 사용자가 따라가지 못하므로 첫 입력에 초점을 준다.
  const decisionPanelRef = useRef<HTMLElement | null>(null);
  const retryPanelRef = useRef<HTMLElement | null>(null);
  function focusPanel(panel: HTMLElement | null) {
    if (!panel) return;
    panel.scrollIntoView({ block: "center" });
    panel.querySelector<HTMLElement>("input, select, textarea")?.focus();
  }
  function focusDecisionForm() {
    focusPanel(decisionPanelRef.current);
  }
  function focusRetryForm() {
    focusPanel(retryPanelRef.current);
  }
  useUnsavedGuard(hasUnsavedDraft, {
    blockSpaNavigation: true,
    message: "저장되지 않은 입찰 최종 결정 초안이 있습니다. 이 페이지를 벗어나시겠습니까?",
  });

  async function refreshLatestState() {
    setRefreshing(true);
    try {
      const workspaceResult = await workspaceQuery.refetch();
      const comparisonResult = selectedComparisonId ? await comparisonQuery.refetch() : null;
      if (workspaceResult.isError || comparisonResult?.isError) return;
      finalDecisionMutation.reset();
      showToast("최신 비교와 최신 여부를 다시 불러왔습니다. 입력한 초안은 그대로 두었습니다.", "info");
    } finally {
      setRefreshing(false);
    }
  }

  if (!validOpportunityId) return <EmptyState tone="error" title="올바른 사업기회 식별자가 필요합니다." />;
  if (workspaceQuery.isPending) return <p className="bid-delta-page-status" role="status">입찰 변경 비교 화면을 불러오는 중입니다.</p>;
  if (workspaceQuery.isError || !workspaceQuery.data) {
    return <EmptyState tone="error" title="입찰 변경 비교 화면을 불러오지 못했습니다." description={describeApiError(workspaceQuery.error, "안전한 비교 후보를 확인할 수 없습니다.").detail} />;
  }
  const workspace = workspaceQuery.data;
  const opportunityDetailSearch = new URLSearchParams(searchParams);
  opportunityDetailSearch.delete("comparison");
  const opportunityDetailTo = { pathname: `/opportunities/${opportunityId}`, search: opportunityDetailSearch.toString() };
  return (
    <section className="bid-delta-page detail-skeleton" data-astryx-theme="bidops" aria-labelledby="bid-delta-title">
      {/* 상세 3종 공통 골격(4단계): 요약 헤더는 position:sticky로 스크롤
          위치와 무관하게 첫 화면에 남는다. 되돌릴 수 없는 최종 Go/No-Go
          저장 액션(PRD 결정 4)은 이 헤더 안에만 있고 레일에는 복제하지
          않는다. 전제조건(comparison 선택·계산 완료·담당자·사유)과 비활성
          사유는 기존 canRecordDecision/decisionDisabledReason 그대로
          유지하며, 헤더로 옮기며 느슨하게 만들지 않는다. */}
      <StickyDecisionHeader className="bid-delta-page-header detail-skeleton-head" label="입찰 변경 비교 결정 헤더">
        <div className="detail-skeleton-head-top">
          <div>
            {/* 상단 경로가 `탐색과 추적 › 사업 추적 › #ID › 입찰 변경 비교`이므로
                되돌아가기 링크와 kicker를 여기서 되풀이하지 않는다. 사업 추적
                상세로 가는 길은 상단 경로의 `#ID` 칸과 우측 레일이다. */}
            <h2 id="bid-delta-title">입찰 변경 비교</h2>
          </div>
          <div className="bid-delta-page-actions">
            {selectedComparisonId ? <Link className="interaction-control" to={{ pathname: `/opportunities/${opportunityId}/bid-delta`, search: opportunityDetailSearch.toString() }}>비교 목록으로 돌아가기</Link> : null}
          </div>
        </div>

        {comparisonView ? (
          <div className="detail-skeleton-status-row">
            <StatusBadge label={CALCULATION_LABELS[comparisonView.calculation_status]} tone={statusTone(comparisonView.calculation_status)} />
            <StatusBadge label={comparisonView.result_status ? RESULT_LABELS[comparisonView.result_status] : "결과 미발행"} tone={comparisonView.result_status ? statusTone(comparisonView.result_status) : "neutral"} />
            <StatusBadge
              label={workspace.latest_final_decision ? `현재 결정 ${workspace.latest_final_decision.decision === "go" ? "Go" : "No-Go"}` : "현재 결정 없음"}
              tone={workspace.latest_final_decision ? statusTone(comparisonView.decision_currentness) : "neutral"}
            />
            {/* 시안 정본(docs/design/mockups/screens_more.py biddelta_screen)의 헤더는
                저장 버튼·결정 입력으로 이동·재계산 세 액션과 비활성 사유만 담고,
                입력 폼(fence·담당자·결정·이유)은 본문에 둔다. 폼째로 sticky 헤더에
                올리면 노트북 폭에서 헤더가 뷰포트의 70%를 차지해 정작 판단 근거인
                범주별 분석을 가린다. 저장 버튼은 form 속성으로 본문 폼과 같은
                submit·같은 finalReady를 쓰므로 업무 규칙이 복제되지 않는다. */}
            <div className="detail-skeleton-actions">
              <ReviewDecisionAction
                className="interaction-control interaction-control-primary"
                disabledReason={decisionDisabledReason}
                disabledReasonId="bid-delta-final-disabled"
                form="bid-delta-final-form"
                isDisabled={!finalReady}
                label={finalDecisionMutation.isPending ? "결정 저장 중" : "결정 저장"}
                type="submit"
                variant="primary"
              />
              {canRecordDecision ? (
                <button className="interaction-control" type="button" onClick={focusDecisionForm}>
                  결정 입력으로 이동
                </button>
              ) : null}
              {/* 시안 정본의 헤더 액션 셋 중 마지막이다. 재계산도 담당자 이름을
                  받아야 하므로 헤더에서 바로 실행하지 않고 본문의 재시도 입력으로
                  데려간다 — 되돌릴 수 없는 입력 form을 헤더에 올리지 않는다. */}
              {comparisonView.calculation_status === "failed" ? (
                <button className="interaction-control" type="button" onClick={focusRetryForm}>
                  비교 재계산
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
      </StickyDecisionHeader>

      <p className="bid-delta-page-lede">사전규격과 입찰공고에서 비교할 문서를 사람이 고르고, 시스템 분석 결과와 사람의 최종 결정을 따로 기록합니다. 이 화면이 정하는 것은 최종 입찰 Go/No-Go 하나이며 적합성 등급·참여 준비 상태·추적 선택을 대신하지 않습니다.</p>

      <WorkspaceCandidates workspace={workspace} baseline={baseline} comparison={comparison} onBaselineChange={setBaseline} onComparisonChange={setComparison} />

      <section className="bid-delta-create-panel" aria-labelledby="bid-delta-create-title">
        <div className="bid-delta-panel-heading">
          <div>
            <p className="bid-delta-kicker">사람이 건별로 승인</p>
            <h3 id="bid-delta-create-title">고른 문서로 비교 만들기</h3>
          </div>
        </div>
        <p className="bid-delta-help">고른 문서 두 건에 대한 내부 모델 처리를 건별로 승인하고 그 사실을 감사 기록에 남깁니다. 화면이 자동으로 추천하거나 저장하거나 시작하지 않습니다.</p>
        <div className="bid-delta-request-preview" aria-label="비교 요청 미리보기">
          <div><span>비교할 문서 두 건</span><strong>{baseline && comparison ? `${baseline.notice_external_id} ↔ ${comparison.notice_external_id}` : "양쪽 후보를 선택하십시오."}</strong></div>
          <div><span>범주 정책 버전</span><strong className="mono">bid-delta-policy.v1</strong></div>
          <div><span>내부 모델 연결 범위</span><strong>회사 내부망 허용 목록의 모델만 사용 · 고른 문서 두 건만 처리 · 외부 서비스로 자동 전환 없음</strong></div>
        </div>
        <div className="bid-delta-create-controls">
          <ActorField label="비교 요청 담당자 이름" value={comparisonActor} onChange={setComparisonActor} required placeholder="예: 홍길동" autoComplete="off" />
          <button className="interaction-control interaction-control-primary" type="button" onClick={() => comparisonMutation.mutate()} disabled={!comparisonReady || comparisonMutation.isPending} aria-describedby={comparisonDisabledReason ? "bid-delta-create-disabled" : undefined}>
            {comparisonMutation.isPending ? "비교 시작 요청 중" : "비교 시작"}
          </button>
          {comparisonDisabledReason ? <DisabledReason id="bid-delta-create-disabled">{comparisonDisabledReason}</DisabledReason> : null}
        </div>
        {comparisonMutation.error ? <BidDeltaErrorFeedback error={comparisonMutation.error} fallback="비교를 시작하지 못했습니다." onRefresh={refreshLatestState} refreshing={refreshing} /> : null}
      </section>

      <ComparisonList comparisons={workspace.comparisons} opportunityId={opportunityId} baseSearch={searchParams.toString()} />
      <CurrentnessPanel titleId="bid-delta-workspace-currentness-title" decision={workspace.latest_final_decision} currentness={workspace.decision_currentness} reasons={workspace.currentness_reasons} />

      {selectedComparisonId && comparisonQuery.isPending ? <p className="bid-delta-page-status" role="status">선택한 비교 상세를 불러오는 중입니다.</p> : null}
      {selectedComparisonId && comparisonQuery.isError ? <BidDeltaErrorFeedback error={comparisonQuery.error} fallback="비교 상세를 불러오지 못했습니다." /> : null}
      {comparisonView ? (
        <div className="detail-skeleton-grid">
          <div className="detail-skeleton-main">
            <section className="bid-delta-detail" aria-labelledby="bid-delta-detail-title">
              <header className="bid-delta-detail-header">
                <div>
                  <p className="bid-delta-kicker">비교 #{comparisonView.sequence} · 버전 {comparisonView.version}</p>
                  <h3 id="bid-delta-detail-title">비교 상세</h3>
                  <p>생성 {formatMoment(comparisonView.created_at)} · 범주 정책 <code>{comparisonView.category_policy_version}</code></p>
                </div>
              </header>

              <CalculationAndResult comparison={comparisonView} />

              <section className="bid-delta-input-ref-section" aria-labelledby="bid-delta-input-ref-title">
                <div className="bid-delta-panel-heading">
                  <div>
                    <p className="bid-delta-kicker">바뀌지 않는 입력</p>
                    <h4 id="bid-delta-input-ref-title">비교 입력 고정 값</h4>
                  </div>
                  <span className="bid-delta-muted">두 입력 모두 확인 필요</span>
                </div>
                <div className="bid-delta-input-ref-grid">
                  <article><h5>기준 · 사전규격</h5><InputRefFacts input={comparisonView.baseline} /></article>
                  <article><h5>비교 · 입찰공고</h5><InputRefFacts input={comparisonView.comparison} /></article>
                </div>
              </section>

              {comparisonView.calculation_status === "failed" ? (
                <section className="bid-delta-retry-panel" aria-labelledby="bid-delta-retry-title" ref={retryPanelRef}>
                  <div>
                    <p className="bid-delta-kicker">계산 실패</p>
                    <h4 id="bid-delta-retry-title">새 계산 회차로 재시도</h4>
                    <p>실패한 계산을 새 회차로 다시 실행합니다. 실패한 회차와 부분 결과는 그대로 남고 입력 값과 정책 버전은 바뀌지 않습니다.</p>
                    {comparisonView.last_error_code ? <p>안전한 오류 코드 · <code>{comparisonView.last_error_code}</code></p> : null}
                  </div>
                  <div className="bid-delta-retry-controls">
                    <ActorField label="재시도 담당자 이름" value={retryActor} onChange={setRetryActor} required placeholder="예: 홍길동" autoComplete="off" />
                    <button className="interaction-control" type="button" onClick={() => retryMutation.mutate()} disabled={!retryActor.trim() || retryMutation.isPending} aria-describedby={!retryActor.trim() || retryMutation.isPending ? "bid-delta-retry-disabled" : undefined}>{retryMutation.isPending ? "재시도 요청 중" : "재시도"}</button>
                    {!retryActor.trim() || retryMutation.isPending ? <DisabledReason id="bid-delta-retry-disabled">{retryMutation.isPending ? "재시도 요청을 처리하고 있습니다." : "재시도하려면 담당자 이름을 입력하십시오."}</DisabledReason> : null}
                  </div>
                  {retryMutation.error ? <BidDeltaErrorFeedback error={retryMutation.error} fallback="비교를 재시도하지 못했습니다." onRefresh={refreshLatestState} refreshing={refreshing} /> : null}
                </section>
              ) : null}

              <section className="bid-delta-items-section" aria-labelledby="bid-delta-items-title">
                <div className="bid-delta-panel-heading">
                  <div>
                    <p className="bid-delta-kicker">승인된 7개 범주</p>
                    <h4 id="bid-delta-items-title">범주별 시스템 분석</h4>
                  </div>
                  <span className="bid-delta-muted">{comparisonView.items.length}건</span>
                </div>
                {/* 무엇과 무엇을 언제 비교한 결과인지 목록 바로 위에 남긴다
                    (PLAN 단계 F 작업 3). 아래 항목만 읽으면 어떤 snapshot 쌍의
                    결과인지 화면이 답하지 못한다. */}
                <dl className="bid-delta-basis" aria-label="비교 기준">
                  <div>
                    <dt>기준 사전규격</dt>
                    <dd><span className="mono">{comparisonView.baseline.notice_external_id}</span> · 문서 v{comparisonView.baseline.document_version_version}</dd>
                  </div>
                  <div>
                    <dt>대상 입찰공고</dt>
                    <dd><span className="mono">{comparisonView.comparison.notice_external_id}</span> · 문서 v{comparisonView.comparison.document_version_version}</dd>
                  </div>
                  <div>
                    <dt>문서 묶음 상태</dt>
                    <dd>
                      기준 문서 묶음 수정본 {comparisonView.baseline.bundle_revision} / 버전 {comparisonView.baseline.bundle_version} ·
                      {" "}대상 문서 묶음 수정본 {comparisonView.comparison.bundle_revision} / 버전 {comparisonView.comparison.bundle_version}
                    </dd>
                  </div>
                  <div>
                    <dt>계산 시각</dt>
                    <dd>
                      {comparisonView.completed_at
                        ? `완료 ${formatMoment(comparisonView.completed_at)}`
                        : comparisonView.started_at
                          ? `시작 ${formatMoment(comparisonView.started_at)} · 아직 완료되지 않음`
                          : "아직 시작하지 않음"}
                      {" · "}범주 정책 <span className="mono">{comparisonView.category_policy_version}</span>
                    </dd>
                  </div>
                </dl>
                {comparisonView.items.length === 0 ? <EmptyState compact title="아직 범주별 결과가 없습니다." description="계산이 끝나 결과가 발행될 때까지 대기합니다. 결과 미발행을 변경 없음으로 해석하지 않습니다." /> : (
                  <div className="bid-delta-items-list">{comparisonView.items.map((item) => <DeltaItem key={item.id} item={item} />)}</div>
                )}
              </section>

              {/* 결정 입력은 본문에 둔다(시안 정본 biddelta_screen의 decide 블록).
                  헤더의 저장 버튼이 form 속성으로 이 폼을 submit하므로 전제조건과
                  비활성 사유는 canRecordDecision/decisionDisabledReason 하나만
                  쓰고, 사유는 헤더에서 항상 보인다. */}
              <section className="bid-delta-final-decision-panel" aria-labelledby="bid-delta-final-decision-title" ref={decisionPanelRef}>
                <div className="bid-delta-panel-heading">
                  <div>
                    <p className="bid-delta-kicker">사람 결정 · 추가만 기록</p>
                    <h4 id="bid-delta-final-decision-title">최종 Go/No-Go 저장</h4>
                  </div>
                  <span className="bid-delta-human-label">사람이 별도로 결정</span>
                </div>
                <div className="bid-delta-analysis-separation">
                  <strong>시스템 분석과 사람 결정은 별도입니다.</strong>
                  <p>시스템 결과는 {comparisonView.result_status ? RESULT_LABELS[comparisonView.result_status] : "결과 미발행"}이며 사람의 Go/No-Go를 자동 제안하거나 선택하지 않습니다.</p>
                </div>
                {/* 저장 조건 셋을 폼 바로 위에 둔다(PLAN 단계 F 작업 2). 무엇이
                    갖춰져야 저장되는지 알기 위해 비활성 사유를 하나씩 눌러 보게
                    하지 않는다. */}
                <ol className="bid-delta-save-conditions" aria-label="저장 조건">
                  <li data-met={comparisonView.calculation_status === "completed" ? "true" : "false"}>
                    계산이 <strong>완료</strong>돼야 합니다. 현재 {CALCULATION_LABELS[comparisonView.calculation_status]}.
                  </li>
                  <li data-met={comparisonView.result_status && comparisonView.result_status !== "failed" ? "true" : "false"}>
                    결과가 나와 있고 <strong>분석 실패가 아니어야</strong> 합니다. 현재 {comparisonView.result_status ? RESULT_LABELS[comparisonView.result_status] : "결과 미발행"}.
                  </li>
                  <li data-met={decisionActor.trim() && decision && reason.trim() ? "true" : "false"}>
                    담당자 이름 · Go 또는 No-Go · 결정 이유를 <strong>모두</strong> 입력해야 합니다. 보류는 최종 결정 값이 아니며 저장되지 않습니다.
                  </li>
                </ol>
                {canRecordDecision ? (
                  <form
                    id="bid-delta-final-form"
                    className="bid-delta-final-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      // 저장 전제조건(finalReady)은 그대로다. 통과해도 바로
                      // 저장하지 않고 무엇을 저장하는지 다시 확인시킨다.
                      if (!finalReady || !decision) return;
                      setDecisionConfirm({
                        confirmLabel: decision === "go" ? "Go로 최종 결정 저장" : "No-Go로 최종 결정 저장",
                        summary: [
                          { label: "대상 사업기회", value: `#${workspace.opportunity_id}` },
                          { label: "최종 결정", value: decision === "go" ? "Go · 참여" : "No-Go · 불참" },
                          { label: "담당자", value: decisionActor.trim() },
                          { label: "결정 이유", value: decisionSummaryExcerpt(reason) },
                          { label: "기대 비교 버전", value: `버전 ${comparisonView.version}` },
                        ],
                      });
                    }}
                  >
                    <div className="bid-delta-form-fence" aria-label="최종 결정 저장 조건">
                      <div><span>기대 비교 버전</span><code>{comparisonView.version}</code></div>
                      <div><span>기대 결과 SHA-256</span><code>{comparisonView.result_sha256 ?? "값 없음"}</code></div>
                      <div><span>양쪽 문서 버전 ID</span><code>{comparisonView.baseline.document_version_id} · {comparisonView.comparison.document_version_id}</code></div>
                      <div><span>대체하는 이전 결정 ID</span><code>{workspace.latest_final_decision?.id ?? "없음"}</code></div>
                    </div>
                    <ActorField label="최종 결정 담당자 이름" value={decisionActor} onChange={setDecisionActor} required placeholder="예: 홍길동" autoComplete="off" />
                    <label className="bid-delta-form-field"><span>최종 결정</span><select aria-label="최종 결정" className="interaction-control" required value={decision} onChange={(event) => setDecision(event.target.value as BidDecision | "")}><option value="">선택하십시오</option><option value="go">Go</option><option value="no_go">No-Go</option></select></label>
                    <label className="bid-delta-form-field"><span>결정 이유</span><textarea aria-label="결정 이유" className="interaction-control" rows={4} required value={reason} onChange={(event) => setReason(event.target.value)} placeholder="시스템 분석을 검토한 사람의 최종 이유를 입력하십시오." /></label>
                    <button className="interaction-control interaction-control-primary" type="submit" disabled={!finalReady} aria-describedby={decisionDisabledReason ? "bid-delta-final-disabled" : undefined}>{finalDecisionMutation.isPending ? "최종 결정 저장 중" : "최종 결정 저장"}</button>
                  </form>
                ) : (
                  <div className="bid-delta-final-blocked">
                    <button className="interaction-control" type="button" disabled aria-describedby={decisionDisabledReason ? "bid-delta-final-disabled" : undefined}>최종 결정 저장</button>
                  </div>
                )}
                {finalDecisionMutation.error ? <BidDeltaErrorFeedback error={finalDecisionMutation.error} fallback="최종 결정을 저장하지 못했습니다." onRefresh={refreshLatestState} refreshing={refreshing} /> : null}
              </section>
            </section>
          </div>

          {/* 우측 레일은 이력과 연결만 담는다(시안 주석 원문). 되돌릴 수
              없는 최종 결정 액션은 헤더에만 있고 여기서 복제하지 않는다. */}
          <ReviewHistoryLinkRail
            className="detail-skeleton-rail"
            footer={<p className="detail-skeleton-rail-note">우측 레일은 이력과 연결만 담습니다. 되돌릴 수 없는 최종 결정 액션은 헤더에만 있습니다.</p>}
            historySections={[
              {
                className: "detail-skeleton-rail-panel",
                content: <AttemptHistory comparison={comparisonView} />,
                entries: [],
                label: "계산 회차 이력",
                showHeading: false,
              },
              {
                className: "detail-skeleton-rail-panel",
                content: <DecisionHistory decisions={comparisonView.final_decisions} workspaceLatest={workspace.latest_final_decision} />,
                entries: [],
                label: "최종 Go/No-Go 저장 이력",
                showHeading: false,
              },
              {
                className: "detail-skeleton-rail-panel",
                content: <CurrentnessPanel titleId="bid-delta-detail-currentness-title" decision={comparisonView.latest_final_decision} currentness={comparisonView.decision_currentness} reasons={comparisonView.currentness_reasons} />,
                entries: [],
                label: "최종 결정 최신 여부",
                showHeading: false,
              },
            ]}
            links={[
              {
                href: `${opportunityDetailTo.pathname}${opportunityDetailTo.search ? `?${opportunityDetailTo.search}` : ""}`,
                label: "사업 추적 상세 →",
              },
              {
                href: `/opportunities/${opportunityId}/bid-delta${opportunityDetailSearch.toString() ? `?${opportunityDetailSearch.toString()}` : ""}`,
                label: "비교 목록으로 돌아가기 →",
              },
            ]}
            linksClassName="detail-skeleton-rail-links"
            title="이력과 연결"
          />
        </div>
      ) : null}

      {hasUnsavedDraft ? <p className="bid-delta-unsaved" role="status">저장되지 않은 입찰 최종 결정 초안이 있습니다. 저장하거나 초안 내용을 확인한 뒤 화면을 벗어나십시오.</p> : null}
      {/* 확인 단계. 취소하면 초안은 그대로 남고 요청은 나가지 않는다. 저장에
          실패하면 다이얼로그는 닫히고 기존 인라인 오류 표시가 그대로 보인다. */}
      <ConfirmDecisionDialog
        confirmLabel={decisionConfirm?.confirmLabel ?? "최종 결정을 저장"}
        isPending={finalDecisionMutation.isPending}
        onConfirm={() => finalDecisionMutation.mutate(undefined, { onSettled: () => setDecisionConfirm(null) })}
        onOpenChange={(next) => { if (!next) setDecisionConfirm(null); }}
        open={decisionConfirm !== null}
        summary={decisionConfirm?.summary ?? []}
        title="최종 Go/No-Go를 저장합니다"
        warning="이 결정은 저장 뒤 되돌릴 수 없습니다. 추가만 기록되어 이전 결정을 덮어쓰지 않습니다."
      />
      {toast ? <Toast message={toast.message} variant={toast.variant} onDismiss={dismissToast} /> : null}
    </section>
  );
}

export default BidDeltaDecisionPage;
