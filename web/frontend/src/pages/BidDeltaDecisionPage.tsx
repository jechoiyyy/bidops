import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Heading } from "@astryxdesign/core/Heading";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Token } from "@astryxdesign/core/Token";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { ActorField } from "../components/common/ActorField";
import {
  ConfirmDecisionDialog,
  decisionSummaryExcerpt,
  type ConfirmDecisionSummaryItem,
} from "../components/common/ConfirmDecisionDialog";
import { DisabledReason } from "../components/common/DisabledReason";
import { EmptyState } from "../components/common/EmptyState";
import { MutationFeedback } from "../components/common/MutationFeedback";
import { Toast } from "../components/common/Toast";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { useToast } from "../components/common/useToast";
import { describeApiError, type ApiErrorDescription } from "../lib/apiErrors";
import { api } from "../lib/api";
import { TERM } from "../lib/glossary";
import { generateRequestId } from "../lib/requestId";
import {
  BidDeltaApiError,
  getBidConditions,
  getBidDelta,
  getBidDeltaComparison,
  recordNoticeConditionsDecision,
  retryBidDeltaAttempt,
  saveBidFinalDecision,
} from "../components/bid-delta/api";
import {
  BidConditionsSection,
  latestConditionNotice,
  noticeRoundLabel,
} from "../components/bid-delta/BidConditionsSection";
import {
  BASIS_LABELS,
  CALCULATION_LABELS,
  CATEGORY_LABELS,
  countDeltaItems,
  CURRENTNESS_LABELS,
  decisionBasisDetail,
  formatDate,
  formatMoment,
  itemKindLabel,
  evidenceLocationLabel,
  LOCATOR_LABELS,
  locatorText,
  MATERIALITY_LABELS,
  RESULT_LABELS,
  SHORT_CALCULATION_LABELS,
  shortHash,
} from "../components/bid-delta/labels";
import type {
  BidConditionsView,
  BidDecision,
  BidDeltaComparisonView,
  BidDeltaEvidenceView,
  BidDeltaInputRef,
  BidDeltaItemView,
  BidDeltaWorkspaceView,
  BidFinalDecisionCreateRequest,
  BidNoticeFinalDecisionCreateRequest,
  Currentness,
  FinalDecisionBasisKind,
} from "../components/bid-delta/types";
import "../styles/bid-delta-decision.css";

/**
 * 입찰 변경 비교 · 최종 결정.
 *
 * 승인된 시안(`design-previews/bidops-go-no-go-erp-20260907/`)의 두 번째 화면이다.
 * 최종 Go/No-Go 목록에서 들어오는 결정 작업면이며, 왼쪽 62%에서 공고 조건·변경
 * 항목과 근거를 읽고 오른쪽 38%에서 사람이 결정을 입력한다. 결정 확인 액션은
 * 오른쪽 아래에 고정되어 읽는 동안 사라지지 않는다.
 *
 * 결정의 근거는 둘이다(spec §9.2·ADR-0058). 완료된 변경 비교를 고르면 그 비교
 * 결과에 묶을 수 있고, 그렇지 않으면 최신 입찰공고 조건(`bid-conditions`)에 묶는다.
 * 실제 변경 비교를 계산하는 프로그램은 아직 운영에 없으므로 새 비교는 만들지 않고
 * 상태를 자동으로 다시 조회하지도 않는다. 계산 대기·실패·결과 미발행·조회 실패는
 * 완료·변경 없음과 구분해 그대로 표시하고, 저장 전제조건과 서버의 fence는 그대로
 * 보낸다.
 */

/** 최신 입찰공고 fence가 없을 때 저장 단추 아래에 적는 문장. */
const NOTICE_UNRESOLVED_REASON = "최신 입찰공고를 확정할 수 없어 저장할 수 없습니다";

/** 입찰공고가 그사이 바뀌어 서버가 공고 조건 결정을 거절한 코드. 공고 조건을 다시 읽는다. */
const NOTICE_CHANGED_CODES = new Set(["final_decision_notice_not_latest", "final_decision_observation_changed"]);

function statusTokenLabel(currentness: Currentness): string {
  return CURRENTNESS_LABELS[currentness];
}

function candidateKey(ref: BidDeltaInputRef): string {
  return `${ref.notice_id}:${ref.document_version_id}:${ref.structure_id}`;
}

function InputRefFacts({ input }: { input: BidDeltaInputRef }) {
  return (
    <dl className="bid-delta-input-facts">
      <div><dt>공고 외부 식별자</dt><dd className="mono">{input.notice_external_id}</dd></div>
      <div><dt>공고 출처 유형</dt><dd className="mono">{input.notice_source_type}</dd></div>
      <div><dt>차수</dt><dd>{input.bid_ordinal ?? "값 없음"}</dd></div>
      <div><dt>공개일</dt><dd>{formatMoment(input.published_at)}</dd></div>
      <div><dt>문서 역할</dt><dd>{input.document_role || "값 없음"}</dd></div>
      <div><dt>문서 묶음 수정본 / 버전</dt><dd>{input.bundle_revision} / {input.bundle_version}</dd></div>
      <div><dt>문서 버전</dt><dd>{input.document_version_version}</dd></div>
      <div><dt>시행일</dt><dd>{formatDate(input.effective_date)}</dd></div>
      <div><dt>문서 버전 ID</dt><dd className="mono">{input.document_version_id}</dd></div>
      <div><dt>사업기회 연결 / 공고 ID</dt><dd>{input.opportunity_link_id} / {input.notice_id}</dd></div>
      <div><dt>문서 구조 ID</dt><dd className="mono">{input.structure_id}</dd></div>
      <div><dt>원문 해시 SHA-256</dt><dd className="mono">{input.source_sha256}</dd></div>
      <div><dt>문서 구조 SHA-256</dt><dd className="mono">{input.structure_payload_sha256}</dd></div>
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
      <span className="bid-delta-candidate-line">
        <span className="mono">{candidate.notice_external_id}</span> · 문서 v{candidate.document_version_version}
        {" · 원문 해시 "}<span className="mono">{shortHash(candidate.source_sha256)}</span>
      </span>
      <span className="bid-delta-candidate-line">
        차수 {candidate.bid_ordinal ?? "값 없음"} · 공개 {formatMoment(candidate.published_at)}
      </span>
      <details className="bid-delta-technical-details">
        <summary>고정 입력 값 보기</summary>
        <InputRefFacts input={candidate} />
      </details>
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
        <h3 id={titleId}>최종 결정 {TERM.currentness}</h3>
        <Token size="sm" label={statusTokenLabel(currentness)} />
      </div>
      {decision ? (
        <div className="bid-delta-latest-decision">
          <strong>{decision.decision === "go" ? "Go" : "No-Go"} · {decision.claimed_name}</strong>
          <span>결정 {formatMoment(decision.created_at)} · {decision.sequence}번째 결정</span>
          <span className="bid-delta-decision-basis">{BASIS_LABELS[decision.basis_kind]} · {decisionBasisDetail(decision)}</span>
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
        <h3 id="bid-delta-candidates-title">비교 문서 후보</h3>
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
        <h3 id="bid-delta-comparison-list-title">기존 비교 목록</h3>
        <span className="bid-delta-muted">{comparisons.length}건 · 바뀌지 않는 기록</span>
      </div>
      {comparisons.length === 0 ? (
        <EmptyState compact title="생성된 비교가 없습니다." description="비교 계산 프로그램이 아직 없어 새 비교를 만들 수 없습니다. 비교가 없다는 것은 변경이 없다는 뜻이 아닙니다." />
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
                  <Token size="sm" label={CALCULATION_LABELS[item.calculation_status]} />
                  <Token size="sm" label={item.result_status ? RESULT_LABELS[item.result_status] : "결과 미발행"} />
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

function EvidenceCard({ evidence, side }: { evidence: BidDeltaEvidenceView | null; side: "baseline" | "comparison" }) {
  if (!evidence) {
    return (
      <article className="bid-delta-evidence-card bid-delta-evidence-missing">
        <strong>{side === "baseline" ? "기준 사전규격" : "대상 입찰공고"}</strong>
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
        <strong>{side === "baseline" ? "기준 사전규격" : "대상 입찰공고"}</strong>
        <Token size="sm" label={verificationLabel} />
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

/** 변경 항목 하나. 시안 `full-delta`: 제목·갈래 → 양쪽 값 → 양쪽 근거 보기. */
function DeltaItem({ item, onOpenEvidence }: { item: BidDeltaItemView; onOpenEvidence: (item: BidDeltaItemView) => void }) {
  const firstEvidence = item.baseline_evidence[0] ?? item.comparison_evidence[0] ?? null;
  const unverified = [...item.baseline_evidence, ...item.comparison_evidence]
    .find((evidence) => evidence.verification_status !== "verified");
  return (
    <article className="bid-delta-item" aria-labelledby={`bid-delta-item-${item.id}`}>
      <header className="bid-delta-item-heading">
        <h4 id={`bid-delta-item-${item.id}`}>{CATEGORY_LABELS[item.category]}</h4>
        <div className="bid-delta-item-statuses">
          <Token size="sm" label={itemKindLabel(item)} />
        </div>
      </header>
      <div className="bid-delta-compare-values">
        <div>
          <span>기준 사전규격</span>
          <p>{item.before_value ?? "원문 근거 미확인"}</p>
        </div>
        <div>
          <span>대상 입찰공고</span>
          <p>{item.after_value ?? "원문 근거 미확인"}</p>
        </div>
      </div>
      {item.summary ? <p className="bid-delta-item-summary">{item.summary}</p> : null}
      {/* 사실·품질 경고는 이 단계에서 보인다. 기술 식별자만 근거 대화상자의
          `기술 식별자 보기` 뒤로 간다. */}
      {item.result_status === "unknown" || item.result_status === "failed" ? (
        <p className="bid-delta-item-error">
          <strong>안전한 오류 코드</strong> <code>{item.error_code ?? "값 없음"}</code> · 이 항목은 변경 없음으로 해석하지 않습니다.
        </p>
      ) : item.error_code ? <p className="bid-delta-item-error"><strong>안전한 오류 코드</strong> <code>{item.error_code}</code></p> : null}
      {unverified ? (
        <p className="bid-delta-item-error">
          근거 검증 {unverified.verification_status === "missing" ? "missing · 근거 없음" : "mismatch · 불일치"} 항목이 있습니다.
        </p>
      ) : null}
      {item.baseline_evidence.length === 0 && item.comparison_evidence.length === 0 ? (
        <p className="bid-delta-item-error">양쪽 근거가 갖춰지지 않아 변경 여부를 확정하지 못했습니다.</p>
      ) : null}
      <Button
        label={firstEvidence
          ? `양쪽 근거 보기 · ${evidenceLocationLabel(firstEvidence)}`
          : "미확인 내용 보기"}
        size="sm"
        variant="ghost"
        icon={<ArrowUpRight aria-hidden="true" />}
        onClick={() => onOpenEvidence(item)}
      />
    </article>
  );
}

function AttemptHistory({ comparison }: { comparison: BidDeltaComparisonView }) {
  const currentAttempt = comparison.attempts.length > 0 ? comparison.attempts[comparison.attempts.length - 1] : null;
  return (
    <section className="bid-delta-attempt-panel" aria-labelledby="bid-delta-attempt-title">
      <div className="bid-delta-panel-heading">
        <h3 id="bid-delta-attempt-title">계산 회차 이력</h3>
        <span className="bid-delta-muted">{comparison.attempts.length}건 · 추가만 기록</span>
      </div>
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
                <Token size="sm" label={attempt.status === "queued" ? "대기" : attempt.status === "running" ? "진행 중" : attempt.status === "completed" ? "완료" : "실패"} />
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

/**
 * 최종 결정 저장 이력.
 *
 * 비교 상세는 그 비교에 묶인 결정만 준다. 공고 조건 근거 결정은 비교에 묶이지 않으므로
 * 사업기회의 마지막 결정(workspace)을 합쳐 보여 주고, 결정마다 근거 종류를 문자로 적는다.
 */
function DecisionHistory({
  decisions,
  workspaceLatest,
}: {
  decisions: BidDeltaComparisonView["final_decisions"];
  workspaceLatest: BidDeltaWorkspaceView["latest_final_decision"];
}) {
  const allDecisions = [...decisions];
  if (workspaceLatest && !allDecisions.some((item) => item.id === workspaceLatest.id)) allDecisions.push(workspaceLatest);
  allDecisions.sort((left, right) => right.sequence - left.sequence);
  return (
    <section className="bid-delta-decision-history" aria-labelledby="bid-delta-decision-history-title">
      <div className="bid-delta-panel-heading">
        <h3 id="bid-delta-decision-history-title">최종 Go/No-Go 저장 이력</h3>
        <span className="bid-delta-muted">{allDecisions.length}건 · 추가만 기록</span>
      </div>
      {allDecisions.length === 0 ? <p>아직 저장된 최종 결정이 없습니다.</p> : (
        <ol className="bid-delta-decision-history-list">
          {allDecisions.map((decision) => (
            <li key={decision.id}>
              <div className="bid-delta-decision-history-heading">
                <strong>{decision.decision === "go" ? "Go" : "No-Go"}</strong>
                <Token size="sm" label={CURRENTNESS_LABELS[decision.currentness]} />
              </div>
              <span>{decision.sequence}번째 결정 · {decision.claimed_name}</span>
              <span className="bid-delta-decision-basis">{BASIS_LABELS[decision.basis_kind]} · {decisionBasisDetail(decision)}</span>
              <p>{decision.reason}</p>
              <details className="bid-delta-technical-details">
                <summary>저장된 기록 값 보기</summary>
                <small>{formatMoment(decision.created_at)} · 대체한 이전 결정 {decision.supersedes_final_decision_id ?? "없음"}</small>
              </details>
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
function BidDeltaErrorFeedback({ problem, onRefresh, refreshing }: { problem: ApiErrorDescription; onRefresh?: () => void; refreshing?: boolean }) {
  return (
    <MutationFeedback
      tone="error"
      problem={problem}
      onRecover={onRefresh}
      recoverPending={refreshing}
      recoverPendingLabel="최신 상태를 다시 조회 중"
    />
  );
}

/**
 * 최종 결정 저장 오류를 typed code로 옮긴다.
 *
 * 공고 조건 근거 결정의 새 코드(spec §9.2)는 공용 문구 표에 없어 409 일반 문구로
 * 떨어진다. 사람이 무엇을 다시 해야 하는지 말하도록 이 화면에서만 코드별 문장을
 * 준다. 분기는 서버 message가 아니라 안전한 코드로만 한다.
 */
function describeFinalDecisionError(error: unknown, basis: FinalDecisionBasisKind | undefined): ApiErrorDescription {
  const base = describeApiError(error, "최종 결정을 저장하지 못했습니다.");
  if (base.code !== null && NOTICE_CHANGED_CODES.has(base.code)) {
    return {
      ...base,
      title: "입찰공고가 바뀌었습니다. 공고 조건을 다시 읽은 뒤 결정하세요.",
      detail: "화면이 보여 준 입찰공고가 더는 최신이 아니거나 관측 내용이 달라져 저장하지 않았습니다. 공고 조건을 다시 불러왔으니 바뀐 조건을 확인한 뒤 다시 확인하십시오.",
      action: "reload",
    };
  }
  if (base.code === "final_decision_bid_notice_missing") {
    return {
      ...base,
      title: "최종 결정할 입찰공고가 없습니다.",
      detail: "확정 연결된 입찰공고가 없어 공고 조건 기준으로 저장하지 않았습니다. 사업 추적에서 입찰공고 연결을 확인하십시오.",
      action: "reload",
    };
  }
  if (base.code === "bid_delta_currentness_unavailable" && basis === "notice_conditions") {
    return {
      ...base,
      title: "최신 입찰공고를 확정할 수 없습니다.",
      detail: "입찰공고의 게시 시각이나 관측 기록이 없어 최신 여부를 모르는 채로 저장하지 않았습니다. 최신 상태를 다시 불러오십시오.",
      action: "reload",
    };
  }
  return base;
}

/**
 * 확인 창을 열 때 얼려 두는 **보낼 요청 전체**.
 *
 * 왜 필요한가. 확인 창이 열려 있는 동안 창 포커스 복귀나 배경 재조회로
 * `comparisonQuery`·`workspaceQuery`·`conditionsQuery`가 새 스냅숏으로 바뀔 수 있다.
 * 저장 시점에 그 최신 값을 다시 읽으면, 사람이 읽고 확인한 것과 **다른 비교 버전·
 * 결과 해시·문서 쌍·입찰공고·관측 해시·대체 대상**이 유효한 fence를 달고 조용히
 * 저장된다. 사람이 본 화면과 저장된 기록이 갈라지는 이 창은 되돌릴 수 없는 결정에서
 * 특히 위험하다.
 *
 * 그래서 확인 창을 여는 순간의 값을 근거 종류와 함께 통째로 얼리고, 확인 버튼은 이
 * 스냅숏만 보낸다. 그 사이 서버 쪽이 실제로 바뀌었다면 **서버가 stale fence로
 * 거절**한다 — 화면이 최신 값을 대신 채워 넣어 성공을 만들지 않는다.
 */
type FrozenFinalDecision =
  | {
    basis: "comparison";
    opportunityId: number;
    comparisonId: string;
    actorName: string;
    payload: BidFinalDecisionCreateRequest;
  }
  | {
    basis: "notice_conditions";
    opportunityId: number;
    actorName: string;
    payload: BidNoticeFinalDecisionCreateRequest;
  };

/** `request_id`를 뺀 나머지가 같으면 사람이 확인한 내용이 같다. */
function frozenRequestKey(request: FrozenFinalDecision): string {
  const { request_id: _ignored, ...payload } = request.payload;
  return JSON.stringify({
    basis: request.basis,
    opportunityId: request.opportunityId,
    comparisonId: request.basis === "comparison" ? request.comparisonId : null,
    actorName: request.actorName,
    payload,
  });
}

/** 같은 내용을 다시 확인하면 앞 요청의 `request_id`를 그대로 쓴다. 한 글자라도 다르면 새 요청이다. */
function withRequestId(previous: FrozenFinalDecision | null, next: FrozenFinalDecision): FrozenFinalDecision {
  if (previous && frozenRequestKey(previous) === frozenRequestKey(next)) return previous;
  // 두 갈래의 payload 형태가 달라 근거 종류로 좁힌 뒤 같은 방식으로 새 식별자를 넣는다.
  if (next.basis === "comparison") return { ...next, payload: { ...next.payload, request_id: generateRequestId() } };
  return { ...next, payload: { ...next.payload, request_id: generateRequestId() } };
}

interface ChecklistItem {
  key: string;
  label: string;
  met: boolean;
}

/** 저장 조건 체크리스트. 충족 여부를 색이 아니라 문자(`확인됨`·`필요`)로도 적는다. */
function SaveChecklist({ items }: { items: ChecklistItem[] }) {
  return (
    <ol className="bid-delta-save-conditions" aria-label="저장 조건">
      {items.map((item) => (
        <li key={item.key} data-met={item.met ? "true" : "false"}>
          <span className="bid-delta-check-state">{item.met ? "확인됨" : "필요"}</span>
          {item.label}
        </li>
      ))}
    </ol>
  );
}

export function BidDeltaDecisionPage() {
  const { opportunityId: opportunityIdParam } = useParams();
  const opportunityId = Number(opportunityIdParam);
  const validOpportunityId = Number.isInteger(opportunityId) && opportunityId > 0;
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const selectedComparisonId = searchParams.get("comparison");
  const [baseline, setBaseline] = useState<BidDeltaInputRef | null>(null);
  const [comparison, setComparison] = useState<BidDeltaInputRef | null>(null);
  const [retryActor, setRetryActor] = useState("");
  const [decisionActor, setDecisionActor] = useState("");
  const [decision, setDecision] = useState<BidDecision | "">("");
  const [reason, setReason] = useState("");
  // 완료된 비교를 골랐을 때만 의미가 있다. 기본은 그 비교 결과이고 사람이 공고 조건으로 바꿀 수 있다.
  const [basisChoice, setBasisChoice] = useState<FinalDecisionBasisKind>("comparison");
  const [evidenceItem, setEvidenceItem] = useState<BidDeltaItemView | null>(null);
  const { toast, showToast, dismissToast } = useToast();
  const [refreshing, setRefreshing] = useState(false);
  // 되돌릴 수 없는 최종 Go/No-Go는 submit 즉시 나가지 않고 확인 단계를 거친다.
  // 확인 창을 열 때 **보낼 요청 전체**를 얼린다(위 `FrozenFinalDecision` 주석).
  const [decisionConfirm, setDecisionConfirm] = useState<
    { summary: ConfirmDecisionSummaryItem[]; confirmLabel: string; request: FrozenFinalDecision } | null
  >(null);
  // 같은 내용을 다시 확인하면 같은 `request_id`로 보낸다. 서버의 멱등 처리와
  // 사람이 읽은 내용이 어긋나지 않게 한다.
  const lastFrozenRequest = useRef<FrozenFinalDecision | null>(null);

  const workspaceQuery = useQuery<BidDeltaWorkspaceView>({
    queryKey: ["bid-delta", opportunityId],
    queryFn: () => getBidDelta(opportunityId),
    enabled: validOpportunityId,
  });
  // 변경 비교를 계산하는 프로그램이 없어 대기·진행 상태가 스스로 바뀌지 않는다.
  // 자동으로 반복 조회하지 않고, 사람이 `상태 다시 조회`로만 다시 읽는다.
  const comparisonQuery = useQuery<BidDeltaComparisonView>({
    queryKey: ["bid-delta-comparison", opportunityId, selectedComparisonId],
    queryFn: () => getBidDeltaComparison(opportunityId, selectedComparisonId as string),
    enabled: validOpportunityId && Boolean(selectedComparisonId),
  });
  // 공고 조건 요약(spec §9.1). 공고 조건 근거 결정의 fence(최신 입찰공고·관측 해시)도 여기서 온다.
  const conditionsQuery = useQuery<BidConditionsView>({
    queryKey: ["bid-conditions", opportunityId],
    queryFn: () => getBidConditions(opportunityId),
    enabled: validOpportunityId,
  });
  // 사업명·발주기관은 결정의 대상이 무엇인지 말한다. 실패해도 결정 흐름을 막지
  // 않고 식별자만 남긴다(이 화면의 정본 데이터는 workspace/comparison/conditions다).
  const opportunityQuery = useQuery({
    queryKey: ["opportunity", opportunityId],
    queryFn: ({ signal }) => api.getOpportunity(opportunityId, { signal }),
    enabled: validOpportunityId,
    staleTime: 30_000,
    retry: false,
  });
  const businessTitle = opportunityQuery.data?.links.find((link) => link.title && link.title.trim())?.title?.trim() ?? null;
  const businessAgency = opportunityQuery.data?.links.find((link) => link.agency && link.agency.trim())?.agency?.trim() ?? null;

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

  const retryMutation = useMutation({
    mutationFn: () => {
      const current = comparisonQuery.data;
      if (!current || !selectedComparisonId) throw new Error("재시도할 비교가 없습니다.");
      return retryBidDeltaAttempt(opportunityId, selectedComparisonId, retryActor, {
        schema_version: "bidops.bid-delta-attempt-create.v1",
        request_id: generateRequestId(),
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
    // 확인 창에서 얼린 스냅숏만 보낸다. 여기서 최신 query 결과를 다시 읽지 않는다.
    mutationFn: (request: FrozenFinalDecision) => request.basis === "comparison"
      ? saveBidFinalDecision(request.opportunityId, request.comparisonId, request.actorName, request.payload)
      : recordNoticeConditionsDecision(request.opportunityId, request.actorName, request.payload),
    onSuccess: async (saved) => {
      setDecisionActor("");
      setDecision("");
      setReason("");
      // 저장된 스냅숏은 다시 보낼 대상이 아니다. 다음 결정은 새 `request_id`를 받는다.
      lastFrozenRequest.current = null;
      showToast(`${saved.decision === "go" ? "Go" : "No-Go"} 최종 결정을 저장했습니다. 이전 결정은 그대로 남습니다.`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["bid-delta", opportunityId] }),
        queryClient.invalidateQueries({ queryKey: ["bid-delta-comparison", opportunityId, selectedComparisonId] }),
        queryClient.invalidateQueries({ queryKey: ["bid-conditions", opportunityId] }),
        queryClient.invalidateQueries({ queryKey: ["bid-delta-decision-queue"] }),
      ]);
    },
    onError: (error) => {
      // 입찰공고가 그사이 바뀌었다는 거절이면 사람이 새 조건을 읽을 수 있게 바로 다시 읽는다.
      // 입력한 초안은 지우지 않고, 새 fence로 다시 확인해야 저장된다.
      if (error instanceof BidDeltaApiError && error.code !== null && NOTICE_CHANGED_CODES.has(error.code)) {
        void conditionsQuery.refetch();
      }
    },
  });

  const comparisonView = comparisonQuery.data;
  const comparisonLoading = Boolean(selectedComparisonId) && comparisonQuery.isPending;
  const comparisonBasisAvailable = Boolean(
    comparisonView && comparisonView.calculation_status === "completed" && comparisonView.result_status !== "failed",
  );
  // 완료된 비교가 없으면 근거는 공고 조건 하나다(spec §11.3).
  const basis: FinalDecisionBasisKind = comparisonBasisAvailable && basisChoice === "comparison" ? "comparison" : "notice_conditions";
  const conditions = conditionsQuery.data;
  const latestNotice = latestConditionNotice(conditions);
  const noticeFence = conditions && conditions.latest_notice_id !== null && conditions.latest_observation_sha256 !== null
    ? { noticeId: conditions.latest_notice_id, observationSha256: conditions.latest_observation_sha256 }
    : null;
  const basisBlockedReason: string | null = comparisonLoading
    ? "선택한 비교 상세를 불러오는 중입니다."
    : basis === "comparison"
      ? null
      : conditionsQuery.isPending
        ? "공고 조건을 불러오는 중입니다."
        : conditionsQuery.isError || !conditions
          ? "공고 조건을 불러오지 못해 최종 Go/No-Go를 저장할 수 없습니다."
          : !noticeFence
            ? NOTICE_UNRESOLVED_REASON
            : null;
  const formAvailable = basisBlockedReason === null;
  const decisionDisabledReason = finalDecisionMutation.isPending
    ? "최종 결정 저장 요청을 처리하고 있습니다."
    : basisBlockedReason
      ?? (!decisionActor.trim()
        ? "결정 기록자 이름을 입력해 주세요."
        : !decision
          ? "최종 결정에서 Go 또는 No-Go를 선택하십시오."
          : !reason.trim()
            ? "최종 결정을 저장하려면 이유를 입력하십시오."
            : null);
  const finalReady = decisionDisabledReason === null;
  const hasUnsavedDraft = Boolean(decisionActor.trim() || retryActor.trim() || reason.trim() || decision);
  const counts = comparisonView && comparisonView.calculation_status === "completed"
    ? countDeltaItems(comparisonView.items)
    : null;
  const checklist: ChecklistItem[] = [
    basis === "comparison" && comparisonView
      ? { key: "basis", label: `비교 계산 완료 확인 · 비교 #${comparisonView.sequence} 버전 ${comparisonView.version}`, met: comparisonBasisAvailable }
      : {
        key: "basis",
        label: noticeFence
          ? `최신 차수 확인 · ${latestNotice ? noticeRoundLabel(latestNotice) : `공고 ID ${noticeFence.noticeId}`}`
          : "최신 차수 확인 · 최신 입찰공고를 확정할 수 없음",
        met: Boolean(noticeFence) && !comparisonLoading,
      },
    { key: "reason", label: "사유 입력", met: Boolean(reason.trim()) },
    { key: "actor", label: "담당자 이름", met: Boolean(decisionActor.trim()) },
  ];
  // 확인 창을 연 뒤 배경 재조회로 fence가 달라졌는지. 달라졌어도 화면이 값을
  // 바꿔치기하지 않고, 사람에게 그 사실만 알린다.
  const supersedesNow = workspaceQuery.data?.latest_final_decision?.id ?? null;
  const frozen = decisionConfirm?.request ?? null;
  const confirmDrift = Boolean(frozen && (
    frozen.basis === "comparison"
      ? comparisonView && (
        frozen.payload.expected_comparison_version !== comparisonView.version
        || frozen.payload.expected_result_sha256 !== comparisonView.result_sha256
        || frozen.payload.baseline_document_version_id !== comparisonView.baseline.document_version_id
        || frozen.payload.comparison_document_version_id !== comparisonView.comparison.document_version_id
        || frozen.payload.supersedes_final_decision_id !== supersedesNow
      )
      : conditions && (
        frozen.payload.expected_notice_id !== conditions.latest_notice_id
        || frozen.payload.expected_observation_sha256 !== conditions.latest_observation_sha256
        || frozen.payload.supersedes_final_decision_id !== supersedesNow
      )
  ));

  // 헤더의 "결정 입력으로 이동"은 오른쪽 결정 폼으로 초점을 옮긴다. 스크롤만
  // 하면 키보드 사용자가 따라가지 못하므로 결정 값 입력에 초점을 준다.
  const decisionPanelRef = useRef<HTMLElement | null>(null);
  const retryPanelRef = useRef<HTMLElement | null>(null);
  function focusPanel(panel: HTMLElement | null, selector: string) {
    if (!panel) return;
    panel.scrollIntoView({ block: "nearest" });
    const target = panel.querySelector<HTMLElement>(selector);
    target?.focus();
  }
  function focusDecisionForm() {
    focusPanel(decisionPanelRef.current, ".bid-delta-decision-choice input, textarea");
  }
  useUnsavedGuard(hasUnsavedDraft, {
    blockSpaNavigation: true,
    message: "저장되지 않은 입찰 최종 결정 초안이 있습니다. 이 페이지를 벗어나시겠습니까?",
  });

  async function refreshLatestState() {
    setRefreshing(true);
    try {
      const [workspaceResult, comparisonResult, conditionsResult] = await Promise.all([
        workspaceQuery.refetch(),
        selectedComparisonId ? comparisonQuery.refetch() : Promise.resolve(null),
        conditionsQuery.refetch(),
      ]);
      if (workspaceResult.isError || comparisonResult?.isError || conditionsResult.isError) return;
      finalDecisionMutation.reset();
      showToast("최신 비교·공고 조건과 최신 여부를 다시 불러왔습니다. 입력한 초안은 그대로 두었습니다.", "info");
    } finally {
      setRefreshing(false);
    }
  }

  function openDecisionConfirm() {
    if (!finalReady || !decision) return;
    const workspace = workspaceQuery.data;
    if (!workspace) return;
    const latestDecision = workspace.latest_final_decision;
    const target = { label: "대상 사업기회", value: businessTitle ? `${businessTitle} · #${workspace.opportunity_id}` : `#${workspace.opportunity_id}` };
    const common = [
      { label: "최종 결정", value: decision === "go" ? "Go · 참여" : "No-Go · 불참" },
      { label: "담당자", value: decisionActor.trim() },
      { label: "결정 이유", value: decisionSummaryExcerpt(reason) },
    ];
    const supersedes = { label: "대체하는 이전 결정", value: latestDecision ? `${latestDecision.sequence}번째 결정 · ${latestDecision.decision === "go" ? "Go" : "No-Go"}` : "없음" };
    let next: FrozenFinalDecision;
    let summary: ConfirmDecisionSummaryItem[];
    if (basis === "comparison") {
      if (!selectedComparisonId || !comparisonView || !comparisonView.result_sha256) return;
      next = {
        basis: "comparison",
        opportunityId,
        comparisonId: selectedComparisonId,
        actorName: decisionActor.trim(),
        payload: {
          schema_version: "bidops.bid-final-decision-create.v1",
          request_id: "",
          expected_comparison_version: comparisonView.version,
          expected_result_sha256: comparisonView.result_sha256,
          baseline_document_version_id: comparisonView.baseline.document_version_id,
          comparison_document_version_id: comparisonView.comparison.document_version_id,
          supersedes_final_decision_id: latestDecision?.id ?? null,
          decision,
          reason: reason.trim(),
        },
      };
      summary = [
        target,
        { label: "결정 근거", value: BASIS_LABELS.comparison },
        ...common,
        { label: "남은 확인 필요", value: counts ? `${counts.unresolved}건` : "확인 불가" },
        supersedes,
        { label: "기대 비교 버전", value: `버전 ${comparisonView.version}` },
        { label: "기대 결과 SHA-256", value: shortHash(comparisonView.result_sha256) },
      ];
    } else {
      if (!noticeFence) return;
      next = {
        basis: "notice_conditions",
        opportunityId,
        actorName: decisionActor.trim(),
        payload: {
          request_id: "",
          expected_notice_id: noticeFence.noticeId,
          expected_observation_sha256: noticeFence.observationSha256,
          supersedes_final_decision_id: latestDecision?.id ?? null,
          decision,
          reason: reason.trim(),
        },
      };
      summary = [
        target,
        { label: "결정 근거", value: BASIS_LABELS.notice_conditions },
        ...common,
        supersedes,
        { label: "기준 입찰공고", value: `${latestNotice ? noticeRoundLabel(latestNotice) : "차수 값 없음"} · 공고 ID ${noticeFence.noticeId}` },
        { label: "기준 관측 SHA-256", value: shortHash(noticeFence.observationSha256) },
      ];
    }
    const request = withRequestId(lastFrozenRequest.current, next);
    lastFrozenRequest.current = request;
    setDecisionConfirm({
      request,
      confirmLabel: decision === "go" ? "Go로 최종 결정 저장" : "No-Go로 최종 결정 저장",
      summary,
    });
  }

  if (!validOpportunityId) return <EmptyState tone="error" title="올바른 사업기회 식별자가 필요합니다." />;
  if (workspaceQuery.isPending) return <p className="bid-delta-page-status" role="status">입찰 변경 비교 화면을 불러오는 중입니다.</p>;
  if (workspaceQuery.isError || !workspaceQuery.data) {
    return <EmptyState tone="error" title="입찰 변경 비교 화면을 불러오지 못했습니다." description={describeApiError(workspaceQuery.error, "안전한 비교 후보를 확인할 수 없습니다.").detail} />;
  }
  const workspace = workspaceQuery.data;
  const opportunityDetailSearch = new URLSearchParams(searchParams);
  opportunityDetailSearch.delete("comparison");
  opportunityDetailSearch.delete("back");
  const backSearch = searchParams.get("back") ?? "";
  const latestDecision = workspace.latest_final_decision;

  return (
    <section className="bid-delta-page" data-astryx-theme="bidops" aria-labelledby="bid-delta-title">
      {/* 시안의 압축 헤더: 되돌아가는 길 · 화면 이름 · 결정 입력으로 이동.
          되돌릴 수 없는 저장 액션은 오른쪽 결정 칸의 고정 바닥에만 있다. */}
      <header className="bid-delta-page-header">
        <div className="bid-delta-head-line">
          <Link className="bid-delta-back-link" to={{ pathname: "/go-no-go", search: backSearch }}>
            <ArrowLeft aria-hidden="true" />
            결정 목록으로
          </Link>
          <h2 id="bid-delta-title">입찰 변경 비교 · 최종 결정</h2>
        </div>
        <div className="bid-delta-head-actions">
          {comparisonView ? <Token size="sm" label={SHORT_CALCULATION_LABELS[comparisonView.calculation_status]} /> : null}
          <button className="interaction-control" type="button" onClick={focusDecisionForm} disabled={!formAvailable}>
            결정 입력으로 이동
          </button>
        </div>
      </header>

      {/* 무엇에 대한 결정인지. 사업명 → 발주기관 → 양쪽 문서 식별자 순서다. */}
      <section className="bid-delta-business" aria-label="결정 대상 사업">
        <div className="bid-delta-business-line">
          <h3>{businessTitle ?? `사업기회 ${opportunityId}`}</h3>
          <Token size="sm" label={latestDecision
            ? `현재 결정 ${latestDecision.decision === "go" ? "Go" : "No-Go"} · ${statusTokenLabel(workspace.decision_currentness)}`
            : "현재 결정 없음"} />
        </div>
        <p className="bid-delta-business-meta">
          {businessAgency ?? "발주기관 미확인"} · 사업기회 {opportunityId}
          {comparisonView
            ? ` · 기준 ${comparisonView.baseline.notice_external_id} ↔ 대상 ${comparisonView.comparison.notice_external_id}`
            : " · 비교 미선택"}
        </p>
      </section>

      <div className="bid-delta-workspace">
        <section className="bid-delta-reading" aria-labelledby="bid-delta-reading-title">
          <header className="bid-delta-pane-head">
            <h3 id="bid-delta-reading-title">공고 조건과 변경 비교</h3>
            {/* 시안은 이 자리에 비교 계산 상태를 둔다. 아래에서 되풀이하지 않는다. */}
            <span className="bid-delta-muted" id="bid-delta-calculation-title">
              {comparisonView ? CALCULATION_LABELS[comparisonView.calculation_status] : "비교 미선택"}
            </span>
          </header>
          <div className="bid-delta-reading-scroll">
            {/* 공고 조건은 비교가 있든 없든 맨 위다. 비교 계산 프로그램이 없는 지금 최종
                결정의 근거는 대개 이 표다(spec §11.3). */}
            <BidConditionsSection
              view={conditions}
              isPending={conditionsQuery.isPending}
              error={conditionsQuery.error}
              onRetry={() => { void conditionsQuery.refetch(); }}
            />

            {!selectedComparisonId ? (
              <>
                <p className="bid-delta-help">사전규격과 입찰공고의 변경 비교와 사람의 최종 결정을 따로 기록합니다. 이 화면이 정하는 것은 최종 입찰 Go/No-Go 하나이며 적합성 등급·참여 준비 상태·추적 선택을 대신하지 않습니다.</p>
                <WorkspaceCandidates workspace={workspace} baseline={baseline} comparison={comparison} onBaselineChange={setBaseline} onComparisonChange={setComparison} />

                <section className="bid-delta-create-panel" aria-labelledby="bid-delta-create-title">
                  <div className="bid-delta-panel-heading">
                    <h3 id="bid-delta-create-title">고른 문서로 비교 만들기</h3>
                    <span className="bid-delta-muted">지금은 만들 수 없음</span>
                  </div>
                  <p className="bid-delta-help">변경 비교를 계산하는 프로그램이 아직 없어 새 비교를 만들지 않습니다. 만들어도 계산 대기에 머물기 때문입니다. 최종 결정은 오른쪽에서 공고 조건을 근거로 기록할 수 있습니다.</p>
                  <div className="bid-delta-request-preview" aria-label="비교 요청 미리보기">
                    <div><span>비교할 문서 두 건</span><strong>{baseline && comparison ? `${baseline.notice_external_id} ↔ ${comparison.notice_external_id}` : "양쪽 후보를 선택하십시오."}</strong></div>
                    <div><span>범주 정책 버전</span><strong className="mono">bid-delta-policy.v1</strong></div>
                  </div>
                  <div className="bid-delta-create-controls">
                    <button className="interaction-control interaction-control-primary" type="button" disabled aria-describedby="bid-delta-create-disabled">
                      비교 시작
                    </button>
                    <DisabledReason id="bid-delta-create-disabled">비교 계산 프로그램 미구현</DisabledReason>
                  </div>
                </section>

                <ComparisonList comparisons={workspace.comparisons} opportunityId={opportunityId} baseSearch={searchParams.toString()} />
              </>
            ) : comparisonQuery.isPending ? (
              <p className="bid-delta-page-status" role="status">선택한 비교 상세를 불러오는 중입니다.</p>
            ) : comparisonQuery.isError || !comparisonView ? (
              <BidDeltaErrorFeedback problem={describeApiError(comparisonQuery.error, "비교 상세를 불러오지 못했습니다.")} onRefresh={refreshLatestState} refreshing={refreshing} />
            ) : (
              <>
                {/* 시안의 읽기 칸은 변경 항목이 먼저다. 계산·결과 상태는 한 줄로
                    줄이고, 비교 기준·고정 입력·계산 회차는 아래 `자세히`로 접는다.
                    사실과 품질 경고(미확인·실패·오류 코드·worker 미구현)는 접지
                    않고 이 자리에 그대로 둔다. */}
                <div className="bid-delta-status-strip">
                  <section className="bid-delta-status-cell" aria-labelledby="bid-delta-result-title">
                    <h4 id="bid-delta-result-title">결과 상태</h4>
                    <Token size="sm" label={comparisonView.result_status ? RESULT_LABELS[comparisonView.result_status] : "결과 미발행"} />
                  </section>
                  {counts ? (
                    <span className="bid-delta-counts-line">
                      중요 변경 {counts.material}건 · 비중요 변경 {counts.nonMaterial}건 · 확인 필요 {counts.unresolved}건 · 변경 없음 {counts.unchanged}건
                    </span>
                  ) : null}
                </div>
                {comparisonView.result_status === "unknown" ? <p className="bid-delta-interpretation">문서 근거로 의미를 확정할 수 없어 미확인 상태입니다.</p> : null}
                {comparisonView.result_status === "failed" ? <p className="bid-delta-interpretation">계산 전체가 실패하여 결과를 확정할 수 없습니다.</p> : null}
                {comparisonView.last_error_code ? <p className="bid-delta-interpretation">안전한 오류 코드 · <code>{comparisonView.last_error_code}</code></p> : null}
                {comparisonView.calculation_status === "pending" || comparisonView.calculation_status === "running" ? (
                  <div className="bid-delta-worker-note" role="status" aria-live="polite">
                    <strong>{comparisonView.calculation_status === "pending" ? "계산 대기 상태입니다." : "계산 진행 중으로 기록되어 있습니다."}</strong>
                    <p>계산을 실행하는 프로그램이 아직 운영에 없습니다. 결과가 나오기 전까지 오류나 변경 없음으로 해석하지 않습니다.</p>
                    <small>상태를 자동으로 다시 조회하지 않습니다. 최종 결정은 오른쪽에서 공고 조건을 근거로 기록할 수 있습니다.</small>
                    <button
                      className="interaction-control"
                      type="button"
                      onClick={() => { void comparisonQuery.refetch(); }}
                      disabled={comparisonQuery.isFetching}
                    >
                      {comparisonQuery.isFetching ? "상태 조회 중" : "상태 다시 조회"}
                    </button>
                  </div>
                ) : null}

                {comparisonView.calculation_status === "failed" ? (
                  <section className="bid-delta-retry-panel" aria-labelledby="bid-delta-retry-title" ref={retryPanelRef}>
                    <div className="bid-delta-panel-heading">
                      <h4 id="bid-delta-retry-title">새 계산 회차로 재시도</h4>
                      <span className="bid-delta-muted">계산 실패</span>
                    </div>
                    <p>실패한 계산을 새 회차로 다시 실행합니다. 실패한 회차와 부분 결과는 그대로 남고 입력 값과 정책 버전은 바뀌지 않습니다.</p>
                    <div className="bid-delta-retry-controls">
                      <ActorField label="재시도 담당자 이름" value={retryActor} onChange={setRetryActor} required placeholder="예: 홍길동" autoComplete="off" />
                      <button className="interaction-control" type="button" onClick={() => retryMutation.mutate()} disabled={!retryActor.trim() || retryMutation.isPending} aria-describedby={!retryActor.trim() || retryMutation.isPending ? "bid-delta-retry-disabled" : undefined}>{retryMutation.isPending ? "재시도 요청 중" : "재시도"}</button>
                      {!retryActor.trim() || retryMutation.isPending ? <DisabledReason id="bid-delta-retry-disabled">{retryMutation.isPending ? "재시도 요청을 처리하고 있습니다." : "재시도하려면 담당자 이름을 입력하십시오."}</DisabledReason> : null}
                    </div>
                    {retryMutation.error ? <BidDeltaErrorFeedback problem={describeApiError(retryMutation.error, "비교를 재시도하지 못했습니다.")} onRefresh={refreshLatestState} refreshing={refreshing} /> : null}
                  </section>
                ) : null}

                <section className="bid-delta-items-section" aria-labelledby="bid-delta-items-title">
                  <div className="bid-delta-panel-heading">
                    <h4 id="bid-delta-items-title">범주별 시스템 분석</h4>
                    <span className="bid-delta-muted">승인된 7개 범주 · {comparisonView.items.length}건</span>
                  </div>
                  {comparisonView.items.length === 0 ? (
                    <EmptyState compact title="아직 범주별 결과가 없습니다." description="계산이 끝나 결과가 발행될 때까지 대기합니다. 결과 미발행을 변경 없음으로 해석하지 않습니다." />
                  ) : (
                    <div className="bid-delta-items-list">
                      {comparisonView.items.map((item) => (
                        <DeltaItem key={item.id} item={item} onOpenEvidence={setEvidenceItem} />
                      ))}
                    </div>
                  )}
                </section>

                <details className="bid-delta-technical-details bid-delta-input-ref-section">
                  <summary>비교 기준·고정 입력·계산 회차 자세히</summary>
                  {/* 무엇과 무엇을 언제 비교한 결과인지(PLAN 단계 F 작업 3)와 바뀌지
                      않는 입력, 회차 이력을 함께 둔다. 접혀 있어도 지워지지 않는다. */}
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
                      <dt>전체 중요도</dt>
                      <dd>{MATERIALITY_LABELS[comparisonView.materiality]}</dd>
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
                  <div className="bid-delta-input-ref-grid">
                    <article><h5>기준 · 사전규격</h5><InputRefFacts input={comparisonView.baseline} /></article>
                    <article><h5>비교 · 입찰공고</h5><InputRefFacts input={comparisonView.comparison} /></article>
                  </div>
                  <AttemptHistory comparison={comparisonView} />
                </details>

                <p className="bid-delta-help">
                  <Link className="bid-delta-inline-link" to={{ pathname: `/opportunities/${opportunityId}/bid-delta`, search: opportunityDetailSearch.toString() }}>
                    비교 목록으로 돌아가기 →
                  </Link>
                  {" "}
                  <Link className="bid-delta-inline-link" to={{ pathname: `/opportunities/${opportunityId}`, search: opportunityDetailSearch.toString() }}>
                    사업 추적 상세 →
                  </Link>
                </p>
              </>
            )}
          </div>
        </section>

        <section className="bid-delta-decision-pane" aria-labelledby="bid-delta-final-decision-title" ref={decisionPanelRef}>
          <header className="bid-delta-pane-head">
            <h3 id="bid-delta-final-decision-title">사람의 최종 결정</h3>
            <span className="bid-delta-muted">추가만 기록</span>
          </header>
          <div className="bid-delta-decision-scroll">
            <div className={`bid-delta-decision-conditions ${formAvailable ? "" : "bid-delta-decision-blocked"}`.trim()}>
              <strong>{formAvailable ? `결정 근거 · ${BASIS_LABELS[basis]}` : "지금은 결정을 기록할 수 없습니다"}</strong>
              {/* 무엇에 묶이는지는 폼 아래 안내와 `이 결정이 묶는 값 보기`가 말한다. 결정 칸의
                  첫 화면에 이유·담당자 입력까지 들어오도록 여기서는 한 줄로 줄인다. */}
              <p>
                {!formAvailable
                  ? basisBlockedReason
                  : basis === "notice_conditions" && !comparisonBasisAvailable
                    ? "완료된 변경 비교가 없습니다. 입력 가능은 참여 권고가 아닙니다."
                    : "입력 가능은 참여 권고가 아닙니다."}
              </p>
              {formAvailable && basis === "comparison" && counts && counts.unresolved > 0 ? (
                <p>미확인 {counts.unresolved}건도 검토해 결정 이유에 남겨 주세요.</p>
              ) : null}
            </div>

            {/* 완료된 비교를 골랐을 때만 근거를 고를 수 있다. 없으면 공고 조건 하나다. */}
            {comparisonBasisAvailable ? (
              <RadioList
                label="결정 근거"
                orientation="horizontal"
                size="sm"
                value={basis}
                onChange={(value) => setBasisChoice(value === "notice_conditions" ? "notice_conditions" : "comparison")}
              >
                <RadioListItem value="comparison" label={BASIS_LABELS.comparison} />
                <RadioListItem value="notice_conditions" label={BASIS_LABELS.notice_conditions} />
              </RadioList>
            ) : null}

            {/* 저장 조건 셋을 폼 바로 위에 둔다. 무엇이 갖춰져야 저장되는지 알기 위해
                비활성 사유를 하나씩 눌러 보게 하지 않는다. */}
            <SaveChecklist items={checklist} />

            {formAvailable ? (
              <form
                id="bid-delta-final-form"
                className="bid-delta-final-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  // 저장 전제조건(finalReady)은 그대로다. 통과해도 바로 저장하지 않고
                  // 무엇을 저장하는지 다시 확인시킨다.
                  openDecisionConfirm();
                }}
              >
                <div className="bid-delta-decision-choice">
                  <RadioList
                    label="최종 결정"
                    orientation="horizontal"
                    value={decision}
                    onChange={(value) => setDecision(value === "go" || value === "no_go" ? value : "")}
                  >
                    <RadioListItem value="go" label="Go" />
                    <RadioListItem value="no_go" label="No-Go" />
                  </RadioList>
                </div>
                <TextArea
                  label="결정 이유"
                  value={reason}
                  onChange={setReason}
                  rows={3}
                  placeholder={basis === "comparison" ? "변경 사항과 미확인 내용을 검토한 판단 근거" : "공고 조건과 차수 간 변경을 검토한 판단 근거"}
                />
                <ActorField label="최종 결정 담당자 이름" value={decisionActor} onChange={setDecisionActor} required placeholder="예: 홍길동" autoComplete="off" />
                {/* 담당자 이름이 감사 표식이라는 설명은 `ActorField`가 이미 한다.
                    같은 말을 두 번 적지 않는다. */}
                <p className="bid-delta-form-note">
                  {basis === "comparison"
                    ? "이 결정은 선택한 비교 결과와 양쪽 문서 버전에 연결됩니다."
                    : "이 결정은 최신 입찰공고와 그 관측 해시에 연결됩니다."}
                  {" "}보류는 최종 결정 값이 아니며 저장되지 않습니다. 이전 결정은 수정하지 않고 새 기록을 남깁니다.
                </p>
                <details className="bid-delta-technical-details">
                  <summary>이 결정이 묶는 값 보기</summary>
                  <div className="bid-delta-form-fence" aria-label="최종 결정 저장 조건">
                    {basis === "comparison" && comparisonView ? (
                      <>
                        <div><span>기대 비교 버전</span><code>{comparisonView.version}</code></div>
                        <div><span>기대 결과 SHA-256</span><code>{comparisonView.result_sha256 ?? "값 없음"}</code></div>
                        <div><span>양쪽 문서 버전 ID</span><code>{comparisonView.baseline.document_version_id} · {comparisonView.comparison.document_version_id}</code></div>
                      </>
                    ) : (
                      <>
                        <div><span>기대 입찰공고 ID</span><code>{noticeFence?.noticeId ?? "값 없음"}</code></div>
                        <div><span>기대 관측 SHA-256</span><code>{noticeFence?.observationSha256 ?? "값 없음"}</code></div>
                      </>
                    )}
                    <div><span>대체하는 이전 결정 ID</span><code>{latestDecision?.id ?? "없음"}</code></div>
                  </div>
                </details>
              </form>
            ) : null}

            {finalDecisionMutation.error ? (
              <BidDeltaErrorFeedback
                problem={describeFinalDecisionError(finalDecisionMutation.error, finalDecisionMutation.variables?.basis)}
                onRefresh={refreshLatestState}
                refreshing={refreshing}
              />
            ) : null}

            {comparisonView ? (
              <>
                <DecisionHistory decisions={comparisonView.final_decisions} workspaceLatest={workspace.latest_final_decision} />
                <CurrentnessPanel titleId="bid-delta-detail-currentness-title" decision={comparisonView.latest_final_decision} currentness={comparisonView.decision_currentness} reasons={comparisonView.currentness_reasons} />
              </>
            ) : (
              <CurrentnessPanel titleId="bid-delta-workspace-currentness-title" decision={workspace.latest_final_decision} currentness={workspace.decision_currentness} reasons={workspace.currentness_reasons} />
            )}
          </div>
          <footer className="bid-delta-decision-footer">
            <Button
              label={finalDecisionMutation.isPending ? "결정 저장 중" : "결정 확인"}
              variant="primary"
              type="submit"
              form="bid-delta-final-form"
              width="100%"
              isDisabled={!finalReady}
              aria-describedby={decisionDisabledReason ? "bid-delta-final-disabled" : undefined}
            />
            {decisionDisabledReason ? <DisabledReason id="bid-delta-final-disabled">{decisionDisabledReason}</DisabledReason> : null}
            <p className="bid-delta-footer-note">확인 후 저장하며, 저장은 되돌릴 수 없습니다.</p>
          </footer>
        </section>
      </div>

      {hasUnsavedDraft ? <p className="bid-delta-unsaved" role="status">저장되지 않은 입찰 최종 결정 초안이 있습니다. 저장하거나 초안 내용을 확인한 뒤 화면을 벗어나십시오.</p> : null}

      <Dialog isOpen={evidenceItem !== null} onOpenChange={(open) => { if (!open) setEvidenceItem(null); }} purpose="info" width={880}>
        <DialogHeader title="양쪽 원문 근거" onOpenChange={() => setEvidenceItem(null)} />
        <div className="bid-delta-dialog-body" data-astryx-theme="bidops">
          {evidenceItem ? (
            <>
              <div className="bid-delta-panel-heading">
                <Heading level={3}>{CATEGORY_LABELS[evidenceItem.category]}</Heading>
                <Token size="sm" label={itemKindLabel(evidenceItem)} />
              </div>
              <div className="bid-delta-evidence-pairs">
                {Array.from(
                  { length: Math.max(evidenceItem.baseline_evidence.length, evidenceItem.comparison_evidence.length, 1) },
                  (_, index) => (
                    <div className="bid-delta-evidence-pair" key={`${evidenceItem.id}-evidence-${index}`}>
                      <EvidenceCard evidence={evidenceItem.baseline_evidence[index] ?? null} side="baseline" />
                      <EvidenceCard evidence={evidenceItem.comparison_evidence[index] ?? null} side="comparison" />
                    </div>
                  ),
                )}
              </div>
              <p>
                {evidenceItem.baseline_evidence.length > 0 && evidenceItem.comparison_evidence.length > 0
                  ? "양쪽 문서의 검증된 위치를 그대로 표시합니다."
                  : "양쪽 근거가 갖춰지지 않았습니다. 변경 없음 또는 요건 충족으로 해석하지 않습니다."}
              </p>
              <div className="bid-delta-dialog-actions">
                <Button label="닫기" onClick={() => setEvidenceItem(null)} />
              </div>
            </>
          ) : null}
        </div>
      </Dialog>

      {/* 확인 단계. 취소하면 초안은 그대로 남고 요청은 나가지 않는다. 저장에
          실패하면 다이얼로그는 닫히고 기존 인라인 오류 표시가 그대로 보인다. */}
      <ConfirmDecisionDialog
        confirmLabel={decisionConfirm?.confirmLabel ?? "최종 결정을 저장"}
        isPending={finalDecisionMutation.isPending}
        onConfirm={() => {
          if (!decisionConfirm) return;
          finalDecisionMutation.mutate(decisionConfirm.request, { onSettled: () => setDecisionConfirm(null) });
        }}
        onOpenChange={(next) => { if (!next) setDecisionConfirm(null); }}
        open={decisionConfirm !== null}
        summary={decisionConfirm?.summary ?? []}
        title="최종 Go/No-Go를 저장합니다"
        warning={`이 결정은 저장 뒤 되돌릴 수 없습니다. 추가만 기록되어 이전 결정을 덮어쓰지 않습니다.${
          confirmDrift ? " 확인하는 동안 비교 또는 공고 조건이 갱신되었습니다. 지금 저장하면 위에 적힌 검토한 값으로 요청하며, 서버가 오래된 값이라고 판단하면 저장을 거절합니다." : ""
        }`}
      />
      {toast ? <Toast message={toast.message} variant={toast.variant} onDismiss={dismissToast} /> : null}
    </section>
  );
}

export default BidDeltaDecisionPage;
