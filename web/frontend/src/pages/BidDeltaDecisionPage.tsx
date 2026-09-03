import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ActorField } from "../components/common/ActorField";
import { DisabledReason } from "../components/common/DisabledReason";
import { EmptyState } from "../components/common/EmptyState";
import { MutationFeedback } from "../components/common/MutationFeedback";
import { StatusBadge, type StatusTone } from "../components/common/StatusBadge";
import { Toast } from "../components/common/Toast";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import {
  BidDeltaApiError,
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

const ERROR_MESSAGES: Record<string, string> = {
  actor_name_required: "담당자 claimed name을 입력해야 합니다.",
  actor_name_invalid: "담당자 claimed name 형식이 올바르지 않습니다.",
  bid_delta_comparison_stale: "새 비교 입력이 있어 이 결정은 현재 상태가 아닙니다.",
  bid_delta_version_conflict: "비교 버전이 바뀌었습니다.",
  bid_delta_result_digest_conflict: "비교 결과 digest가 바뀌었습니다.",
  final_decision_supersession_conflict: "직전 최종 결정이 바뀌었습니다.",
  idempotency_conflict: "같은 request_id가 다른 요청에 사용되었습니다.",
  bid_delta_currentness_unavailable: "비교 현재성을 확인할 수 없어 결정을 저장하지 않았습니다.",
  bid_delta_comparison_not_completed: "계산이 완료된 비교만 최종 결정할 수 있습니다.",
  bid_delta_comparison_not_retryable: "계산 실패 상태의 비교만 재시도할 수 있습니다.",
  active_attempt_exists: "이미 실행 중인 attempt가 있습니다.",
  bid_delta_input_not_ready: "비교 입력이 아직 준비되지 않았습니다.",
  bid_delta_input_not_authoritative: "비교 입력 연결이 authoritative 상태가 아닙니다.",
  bid_delta_category_policy_invalid: "지원하지 않는 category policy입니다.",
  bid_delta_service_unavailable: "입찰 delta 서비스를 사용할 수 없습니다.",
  bid_delta_projection_unavailable: "입찰 delta 조회를 사용할 수 없습니다.",
};

const REFRESH_ERROR_CODES = new Set([
  "bid_delta_comparison_stale",
  "bid_delta_version_conflict",
  "bid_delta_result_digest_conflict",
  "final_decision_supersession_conflict",
  "idempotency_conflict",
  "bid_delta_currentness_unavailable",
]);

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

function errorText(error: unknown, fallback: string): string {
  if (error instanceof BidDeltaApiError) {
    const message = error.code ? ERROR_MESSAGES[error.code] ?? error.message : error.message;
    return error.code ? `${message} · 오류 코드 ${error.code}` : message;
  }
  return error instanceof Error ? error.message : fallback;
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
      <div><dt>공고 external ID</dt><dd className="mono">{input.notice_external_id}</dd></div>
      <div><dt>공고 source type</dt><dd className="mono">{input.notice_source_type}</dd></div>
      <div><dt>차수</dt><dd>{input.bid_ordinal ?? "값 없음"}</dd></div>
      <div><dt>공개일</dt><dd>{formatMoment(input.published_at)}</dd></div>
      <div><dt>문서 역할</dt><dd>{input.document_role || "값 없음"}</dd></div>
      <div><dt>bundle revision / version</dt><dd>{input.bundle_revision} / {input.bundle_version}</dd></div>
      <div><dt>document version</dt><dd>{input.document_version_version}</dd></div>
      {!compact ? <div><dt>effective date</dt><dd>{formatDate(input.effective_date)}</dd></div> : null}
      <div><dt>document version ID</dt><dd className="mono">{input.document_version_id}</dd></div>
      {!compact ? <div><dt>opportunity link / notice ID</dt><dd>{input.opportunity_link_id} / {input.notice_id}</dd></div> : null}
      {!compact ? <div><dt>structure ID</dt><dd className="mono">{input.structure_id}</dd></div> : null}
      <div><dt>source hash {compact ? "앞 12자" : "SHA-256"}</dt><dd className="mono">{compact ? shortHash(input.source_sha256) : input.source_sha256}</dd></div>
      {!compact ? <div><dt>structure payload SHA-256</dt><dd className="mono">{input.structure_payload_sha256}</dd></div> : null}
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
          <p className="bid-delta-kicker">FINAL DECISION CURRENTNESS</p>
          <h3 id={titleId}>최종 결정 현재성</h3>
        </div>
        <StatusBadge label={CURRENTNESS_LABELS[currentness]} tone={statusTone(currentness)} />
      </div>
      {decision ? (
        <div className="bid-delta-latest-decision">
          <strong>{decision.decision === "go" ? "Go" : "No-Go"} · {decision.claimed_name}</strong>
          <span>결정 {formatMoment(decision.created_at)} · sequence {decision.sequence}</span>
          <p>{decision.reason}</p>
        </div>
      ) : <p>아직 최종 결정이 저장되지 않았습니다.</p>}
      <p className="bid-delta-currentness-reasons">
        <span>현재성 근거</span> {reasons.length > 0 ? reasons.join(" · ") : "확인된 재검토 사유 없음"}
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
          <p className="bid-delta-kicker">EXACT SNAPSHOT SELECTION</p>
          <h3 id="bid-delta-candidates-title">비교 문서 후보</h3>
        </div>
        <span className="bid-delta-muted">서버 자동 선택 없음</span>
      </div>
      <p className="bid-delta-help">양쪽 후보를 사람이 선택합니다. 후보가 정확히 하나인 쪽만 미리 선택했으며, 저장 요청에는 아래 snapshot fence 전체를 보냅니다.</p>
      <div className="bid-delta-candidate-columns">
        <div>
          <h4>기준 · 사전규격</h4>
          {noBaseline ? (
            <EmptyState compact tone="warning" title="기준 후보 없음" description="authoritative 사전규격과 안전한 ready bundle 문서가 없어 비교를 시작할 수 없습니다. 이를 변경 없음으로 해석하지 않습니다." />
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
            <EmptyState compact tone="warning" title="비교 후보 없음" description="authoritative 입찰공고와 안전한 ready bundle 문서가 없어 비교를 시작할 수 없습니다. 이를 변경 없음으로 해석하지 않습니다." />
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
          <p className="bid-delta-kicker">IMMUTABLE COMPARISONS</p>
          <h3 id="bid-delta-comparison-list-title">기존 비교 목록</h3>
        </div>
        <span className="bid-delta-muted">{comparisons.length}건</span>
      </div>
      {comparisons.length === 0 ? (
        <EmptyState compact title="생성된 비교가 없습니다." description="비교 입력을 직접 고른 뒤 비교 시작을 눌러 새 snapshot 비교를 만드십시오." />
      ) : (
        <ol className="bid-delta-comparison-list">
          {comparisons.map((item) => (
            <li key={item.id}>
              <Link className="bid-delta-comparison-link" to={{ pathname: `/opportunities/${opportunityId}/bid-delta`, search: (() => { const next = new URLSearchParams(baseSearch); next.set("comparison", item.id); return next.toString(); })() }}>
                <span>
                  <strong>비교 #{item.sequence}</strong>
                  <small>v{item.version} · {item.category_policy_version}</small>
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
        <p className="bid-delta-kicker">CALCULATION STATUS</p>
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
            <p>계산 담당 worker는 아직 운영에 없습니다. 결과가 발행되기 전까지 오류나 변경 없음으로 해석하지 않습니다.</p>
            <small>이 화면은 pending/running 동안만 자동으로 상태를 다시 조회합니다.</small>
          </div>
        ) : null}
      </section>
      <section className="bid-delta-status-panel" aria-labelledby="bid-delta-result-title">
        <p className="bid-delta-kicker">RESULT STATUS</p>
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
      <p className="bid-delta-evidence-locator"><span>원문 위치</span> {evidence.locator_type} · {LOCATOR_LABELS[evidence.locator_type]} · {locatorText(evidence)}</p>
      <blockquote>{evidence.quote ?? "인용 값 없음"}</blockquote>
      <details className="bid-delta-technical-details">
        <summary>기술 식별자 보기</summary>
        <dl>
          <div><dt>evidence ID</dt><dd className="mono">{evidence.id}</dd></div>
          <div><dt>document version ID</dt><dd className="mono">{evidence.document_version_id}</dd></div>
          <div><dt>structure ID</dt><dd className="mono">{evidence.structure_id}</dd></div>
          <div><dt>source SHA-256</dt><dd className="mono">{evidence.source_sha256}</dd></div>
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
          <p className="bid-delta-kicker">APPEND-ONLY ATTEMPTS</p>
          <h3 id="bid-delta-attempt-title">계산 attempt 이력</h3>
        </div>
        <span className="bid-delta-muted">{comparison.attempts.length}건</span>
      </div>
      <p className="bid-delta-help">이력은 보존되며 현재 attempt만 새로 표시됩니다.</p>
      {comparison.attempts.length === 0 ? <p>생성된 attempt가 없습니다.</p> : (
        <ol className="bid-delta-attempt-list">
          {comparison.attempts.map((attempt) => {
            const current = attempt.id === currentAttempt?.id;
            return (
              <li key={attempt.id} className={current ? "bid-delta-attempt-current" : ""}>
                <div>
                  <strong>Attempt {attempt.sequence}회</strong>
                  {current ? <span className="bid-delta-current-label">현재 attempt</span> : null}
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
          <p className="bid-delta-kicker">APPEND-ONLY HUMAN RECORDS</p>
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
                <span>sequence {decision.sequence} · {decision.claimed_name}</span>
                <StatusBadge label={CURRENTNESS_LABELS[decision.currentness]} tone={statusTone(decision.currentness)} />
              </div>
              <p>{decision.reason}</p>
              <small>{formatMoment(decision.created_at)} · comparison v{decision.comparison_version} · supersedes {decision.supersedes_final_decision_id ?? "null"}</small>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function BidDeltaErrorFeedback({ error, fallback, onRefresh, refreshing }: { error: unknown; fallback: string; onRefresh?: () => void; refreshing?: boolean }) {
  const canRefresh = error instanceof BidDeltaApiError && error.code !== null && REFRESH_ERROR_CODES.has(error.code) && onRefresh;
  return (
    <MutationFeedback tone="error">
      <p>{errorText(error, fallback)}</p>
      {canRefresh ? (
        <button className="interaction-control" type="button" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "최신 상태를 다시 조회 중" : "최신 상태 다시 불러오기"}
        </button>
      ) : null}
    </MutationFeedback>
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
  const [feedback, setFeedback] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

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
      if (!baseline || !comparison) throw new Error("비교할 양쪽 snapshot을 선택하십시오.");
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
      setFeedback(`비교 #${created.sequence}을 요청했습니다. 계산 대기 상태로 저장되었습니다.`);
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
      setFeedback("새 계산 attempt를 추가했습니다. 이전 attempt는 보존됩니다.");
      await queryClient.invalidateQueries({ queryKey: ["bid-delta", opportunityId] });
    },
  });

  const finalDecisionMutation = useMutation({
    mutationFn: () => {
      const current = comparisonQuery.data;
      if (!current || !selectedComparisonId || !current.result_sha256 || !decision) throw new Error("최종 결정 fence가 준비되지 않았습니다.");
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
      setFeedback(`${saved.decision === "go" ? "Go" : "No-Go"} 최종 결정을 append-only로 저장했습니다.`);
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
      ? "비교를 시작하려면 기준과 비교 snapshot을 각각 선택하십시오."
      : !comparisonActor.trim()
        ? "비교를 시작하려면 담당자 claimed name을 입력하십시오."
        : null;
  const comparisonView = comparisonQuery.data;
  const canRecordDecision = comparisonView?.calculation_status === "completed" && comparisonView.result_status !== "failed";
  const decisionDisabledReason = finalDecisionMutation.isPending
    ? "최종 결정 저장 요청을 처리하고 있습니다."
    : !comparisonView
      ? "비교 상세를 먼저 불러오십시오."
      : !canRecordDecision
        ? comparisonView.result_status === "failed"
          ? "결과가 failed여서 최종 Go/No-Go를 저장할 수 없습니다. 분석 실패를 변경 없음으로 해석하지 마십시오."
          : comparisonView.calculation_status === "failed"
          ? "계산이 실패하여 최종 Go/No-Go를 저장할 수 없습니다. 비교를 재시도하십시오."
          : "계산이 완료될 때까지 최종 Go/No-Go를 저장할 수 없습니다."
        : !decisionActor.trim()
          ? "최종 결정을 저장하려면 담당자 claimed name을 입력하십시오."
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
  function focusDecisionForm() {
    const panel = decisionPanelRef.current;
    if (!panel) return;
    panel.scrollIntoView({ block: "center" });
    const firstField = panel.querySelector<HTMLElement>("input, select, textarea");
    firstField?.focus();
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
      setFeedback("최신 비교와 현재성을 다시 불러왔습니다. 입력한 초안은 유지했습니다.");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    if (!feedback) return;
    const timer = window.setTimeout(() => setFeedback(null), 6_000);
    return () => window.clearTimeout(timer);
  }, [feedback]);

  if (!validOpportunityId) return <EmptyState tone="error" title="올바른 사업기회 식별자가 필요합니다." />;
  if (workspaceQuery.isPending) return <p className="bid-delta-page-status" role="status">입찰 변경 비교 workspace를 불러오는 중입니다.</p>;
  if (workspaceQuery.isError || !workspaceQuery.data) {
    return <EmptyState tone="error" title="입찰 변경 비교 workspace를 불러오지 못했습니다." description={errorText(workspaceQuery.error, "안전한 비교 후보를 확인할 수 없습니다.")} />;
  }
  const workspace = workspaceQuery.data;
  const opportunityDetailSearch = new URLSearchParams(searchParams);
  opportunityDetailSearch.delete("comparison");
  const opportunityDetailTo = { pathname: `/opportunities/${opportunityId}`, search: opportunityDetailSearch.toString() };
  return (
    <section className="bid-delta-page detail-skeleton" data-astryx-theme="neutral" aria-labelledby="bid-delta-title">
      {/* 상세 3종 공통 골격(4단계): 요약 헤더는 position:sticky로 스크롤
          위치와 무관하게 첫 화면에 남는다. 되돌릴 수 없는 최종 Go/No-Go
          저장 액션(PRD 결정 4)은 이 헤더 안에만 있고 레일에는 복제하지
          않는다. 전제조건(comparison 선택·계산 완료·담당자·사유)과 비활성
          사유는 기존 canRecordDecision/decisionDisabledReason 그대로
          유지하며, 헤더로 옮기며 느슨하게 만들지 않는다. */}
      <header className="bid-delta-page-header detail-skeleton-head">
        <div className="detail-skeleton-head-top">
          <div>
            <Link className="bid-delta-back-link" to={opportunityDetailTo}>← 사업기회 상세</Link>
            <p className="bid-delta-kicker">BID NOTICE TRANSITION · OPPORTUNITY #{workspace.opportunity_id}</p>
            <h2 id="bid-delta-title">입찰 변경 비교</h2>
          </div>
          <div className="bid-delta-page-actions">
            {selectedComparisonId ? <Link className="interaction-control bid-delta-secondary-action" to={{ pathname: `/opportunities/${opportunityId}/bid-delta`, search: opportunityDetailSearch.toString() }}>workspace로 돌아가기</Link> : null}
          </div>
        </div>

        {comparisonView ? (
          <div className="detail-skeleton-status-row">
            <StatusBadge label={CALCULATION_LABELS[comparisonView.calculation_status]} tone={statusTone(comparisonView.calculation_status)} />
            <StatusBadge label={comparisonView.result_status ? RESULT_LABELS[comparisonView.result_status] : "결과 미발행"} tone={comparisonView.result_status ? statusTone(comparisonView.result_status) : "neutral"} />
            <StatusBadge
              label={workspace.latest_final_decision ? `현재 결정 ${workspace.latest_final_decision.decision}` : "현재 결정 없음"}
              tone={workspace.latest_final_decision ? statusTone(comparisonView.decision_currentness) : "neutral"}
            />
            {/* 시안 정본(docs/design/mockups/screens_more.py biddelta_screen)의 헤더는
                저장 버튼·결정 입력으로 이동·재계산 세 액션과 비활성 사유만 담고,
                입력 폼(fence·담당자·결정·이유)은 본문에 둔다. 폼째로 sticky 헤더에
                올리면 노트북 폭에서 헤더가 뷰포트의 70%를 차지해 정작 판단 근거인
                범주별 분석을 가린다. 저장 버튼은 form 속성으로 본문 폼과 같은
                submit·같은 finalReady를 쓰므로 업무 규칙이 복제되지 않는다. */}
            <div className="detail-skeleton-actions">
              <button
                className="interaction-control bid-delta-primary-action"
                type="submit"
                form="bid-delta-final-form"
                disabled={!finalReady}
                aria-describedby={decisionDisabledReason ? "bid-delta-final-disabled" : undefined}
              >
                {finalDecisionMutation.isPending ? "결정 저장 중" : "결정 저장"}
              </button>
              {canRecordDecision ? (
                <button className="interaction-control bid-delta-secondary-action" type="button" onClick={focusDecisionForm}>
                  결정 입력으로 이동
                </button>
              ) : null}
              {decisionDisabledReason ? <DisabledReason id="bid-delta-final-disabled">{decisionDisabledReason}</DisabledReason> : null}
            </div>
          </div>
        ) : null}
      </header>

      <p className="bid-delta-page-lede">사전규격 기준 snapshot과 입찰공고 비교 snapshot을 사람이 고르고, 시스템 결과와 사람의 최종 결정을 분리해 기록합니다.</p>

      <WorkspaceCandidates workspace={workspace} baseline={baseline} comparison={comparison} onBaselineChange={setBaseline} onComparisonChange={setComparison} />

      <section className="bid-delta-create-panel" aria-labelledby="bid-delta-create-title">
        <div className="bid-delta-panel-heading">
          <div>
            <p className="bid-delta-kicker">HUMAN-APPROVED REQUEST</p>
            <h3 id="bid-delta-create-title">선택한 snapshot 비교 생성</h3>
          </div>
        </div>
        <p className="bid-delta-help">이 요청은 선택한 exact 문서 pair에 대한 건별 내부 모델 처리 승인으로 감사됩니다. 자동 추천·자동 저장·자동 시작은 하지 않습니다.</p>
        <div className="bid-delta-request-preview" aria-label="비교 요청 미리보기">
          <div><span>정확한 문서 pair</span><strong>{baseline && comparison ? `${baseline.notice_external_id} ↔ ${comparison.notice_external_id}` : "양쪽 후보를 선택하십시오."}</strong></div>
          <div><span>category policy version</span><strong className="mono">bid-delta-policy.v1</strong></div>
          <div><span>내부 모델 binding 범위</span><strong>회사 내부망 allowlist binding · 선택한 exact snapshot pair만 처리 · 외부/hosted fallback 없음</strong></div>
        </div>
        <div className="bid-delta-create-controls">
          <ActorField label="비교 요청 담당자 이름" value={comparisonActor} onChange={setComparisonActor} required placeholder="예: 홍길동" autoComplete="off" />
          <button className="interaction-control bid-delta-primary-action" type="button" onClick={() => comparisonMutation.mutate()} disabled={!comparisonReady || comparisonMutation.isPending} aria-describedby={comparisonDisabledReason ? "bid-delta-create-disabled" : undefined}>
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
                  <p className="bid-delta-kicker">COMPARISON #{comparisonView.sequence} · VERSION {comparisonView.version}</p>
                  <h3 id="bid-delta-detail-title">비교 상세</h3>
                  <p>생성 {formatMoment(comparisonView.created_at)} · category policy <code>{comparisonView.category_policy_version}</code></p>
                </div>
              </header>

              <CalculationAndResult comparison={comparisonView} />

              <section className="bid-delta-input-ref-section" aria-labelledby="bid-delta-input-ref-title">
                <div className="bid-delta-panel-heading">
                  <div>
                    <p className="bid-delta-kicker">IMMUTABLE INPUT FENCE</p>
                    <h4 id="bid-delta-input-ref-title">비교 입력 snapshot</h4>
                  </div>
                  <span className="bid-delta-muted">두 입력 모두 확인 필요</span>
                </div>
                <div className="bid-delta-input-ref-grid">
                  <article><h5>기준 · 사전규격</h5><InputRefFacts input={comparisonView.baseline} /></article>
                  <article><h5>비교 · 입찰공고</h5><InputRefFacts input={comparisonView.comparison} /></article>
                </div>
              </section>

              {comparisonView.calculation_status === "failed" ? (
                <section className="bid-delta-retry-panel" aria-labelledby="bid-delta-retry-title">
                  <div>
                    <p className="bid-delta-kicker">FAILED COMPARISON</p>
                    <h4 id="bid-delta-retry-title">새 attempt로 재시도</h4>
                    <p>실패한 attempt와 부분 결과는 보존하고 새 attempt를 추가합니다. 입력 snapshot과 정책 버전은 바꾸지 않습니다.</p>
                    {comparisonView.last_error_code ? <p>안전한 오류 코드 · <code>{comparisonView.last_error_code}</code></p> : null}
                  </div>
                  <div className="bid-delta-retry-controls">
                    <ActorField label="재시도 담당자 이름" value={retryActor} onChange={setRetryActor} required placeholder="예: 홍길동" autoComplete="off" />
                    <button className="interaction-control" type="button" onClick={() => retryMutation.mutate()} disabled={!retryActor.trim() || retryMutation.isPending} aria-describedby={!retryActor.trim() || retryMutation.isPending ? "bid-delta-retry-disabled" : undefined}>{retryMutation.isPending ? "재시도 요청 중" : "재시도"}</button>
                    {!retryActor.trim() || retryMutation.isPending ? <DisabledReason id="bid-delta-retry-disabled">{retryMutation.isPending ? "재시도 요청을 처리하고 있습니다." : "재시도하려면 담당자 claimed name을 입력하십시오."}</DisabledReason> : null}
                  </div>
                  {retryMutation.error ? <BidDeltaErrorFeedback error={retryMutation.error} fallback="비교를 재시도하지 못했습니다." onRefresh={refreshLatestState} refreshing={refreshing} /> : null}
                </section>
              ) : null}

              <section className="bid-delta-items-section" aria-labelledby="bid-delta-items-title">
                <div className="bid-delta-panel-heading">
                  <div>
                    <p className="bid-delta-kicker">SEVEN APPROVED CATEGORIES</p>
                    <h4 id="bid-delta-items-title">범주별 시스템 분석</h4>
                  </div>
                  <span className="bid-delta-muted">{comparisonView.items.length}건 반환</span>
                </div>
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
                    <p className="bid-delta-kicker">HUMAN DECISION · APPEND ONLY</p>
                    <h4 id="bid-delta-final-decision-title">최종 Go/No-Go 저장</h4>
                  </div>
                  <span className="bid-delta-human-label">사람이 별도로 결정</span>
                </div>
                <div className="bid-delta-analysis-separation">
                  <strong>시스템 분석과 사람 결정은 별도입니다.</strong>
                  <p>시스템 결과는 {comparisonView.result_status ? RESULT_LABELS[comparisonView.result_status] : "결과 미발행"}이며 사람의 Go/No-Go를 자동 제안하거나 선택하지 않습니다.</p>
                </div>
                {canRecordDecision ? (
                  <form id="bid-delta-final-form" className="bid-delta-final-form" onSubmit={(event) => { event.preventDefault(); if (finalReady) finalDecisionMutation.mutate(); }}>
                    <div className="bid-delta-form-fence" aria-label="최종 결정 저장 fence">
                      <div><span>expected comparison version</span><code>{comparisonView.version}</code></div>
                      <div><span>expected result SHA-256</span><code>{comparisonView.result_sha256 ?? "값 없음"}</code></div>
                      <div><span>양쪽 document version ID</span><code>{comparisonView.baseline.document_version_id} · {comparisonView.comparison.document_version_id}</code></div>
                      <div><span>supersedes final decision ID</span><code>{workspace.latest_final_decision?.id ?? "null"}</code></div>
                    </div>
                    <ActorField label="최종 결정 담당자 이름" value={decisionActor} onChange={setDecisionActor} required placeholder="예: 홍길동" autoComplete="off" />
                    <label className="bid-delta-form-field"><span>최종 결정</span><select aria-label="최종 결정" className="interaction-control" required value={decision} onChange={(event) => setDecision(event.target.value as BidDecision | "")}><option value="">선택하십시오</option><option value="go">Go</option><option value="no_go">No-Go</option></select></label>
                    <label className="bid-delta-form-field"><span>결정 이유</span><textarea aria-label="결정 이유" className="interaction-control" rows={4} required value={reason} onChange={(event) => setReason(event.target.value)} placeholder="시스템 분석을 검토한 사람의 최종 이유를 입력하십시오." /></label>
                    <button className="interaction-control bid-delta-primary-action" type="submit" disabled={!finalReady} aria-describedby={decisionDisabledReason ? "bid-delta-final-disabled" : undefined}>{finalDecisionMutation.isPending ? "최종 결정 저장 중" : "최종 결정 저장"}</button>
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
          <aside className="detail-skeleton-rail">
            <div className="detail-skeleton-rail-panel">
              <AttemptHistory comparison={comparisonView} />
            </div>
            <div className="detail-skeleton-rail-panel">
              <DecisionHistory decisions={comparisonView.final_decisions} workspaceLatest={workspace.latest_final_decision} />
            </div>
            <div className="detail-skeleton-rail-panel">
              <CurrentnessPanel titleId="bid-delta-detail-currentness-title" decision={comparisonView.latest_final_decision} currentness={comparisonView.decision_currentness} reasons={comparisonView.currentness_reasons} />
            </div>
            <div className="detail-skeleton-rail-panel">
              <div className="detail-skeleton-rail-links">
                <span className="detail-skeleton-rail-title">연결된 화면</span>
                <Link to={opportunityDetailTo}>사업기회 상세 →</Link>
                <Link to={{ pathname: `/opportunities/${opportunityId}/bid-delta`, search: opportunityDetailSearch.toString() }}>workspace로 돌아가기 →</Link>
              </div>
              <p className="detail-skeleton-rail-note">우측 레일은 이력과 연결만 담습니다. 되돌릴 수 없는 최종 결정 액션은 헤더에만 있습니다.</p>
            </div>
          </aside>
        </div>
      ) : null}

      {hasUnsavedDraft ? <p className="bid-delta-unsaved" role="status">저장되지 않은 입찰 최종 결정 초안이 있습니다. 저장하거나 초안 내용을 확인한 뒤 화면을 벗어나십시오.</p> : null}
      {feedback ? <Toast message={feedback} onDismiss={() => setFeedback(null)} /> : null}
    </section>
  );
}

export default BidDeltaDecisionPage;
