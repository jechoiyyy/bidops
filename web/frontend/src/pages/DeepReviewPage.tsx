import { createCompanyLunaAdapter, LunaRequest } from "../components/deep-review/LunaRequest";
import { SourceVerificationSetting } from "../components/deep-review/SourceVerificationSetting";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  createDeepReviewAttempt,
  DeepReviewApiError,
  getDeepReview,
  getEvidence,
  getReport,
  saveFinalOpinion,
  saveRevision,
} from "../components/deep-review/api";
import { attemptFailureSentence } from "../components/deep-review/attemptErrors";
import { NarrativeReportReader, type EvidenceSource } from "../components/deep-review/NarrativeReportReader";
import { CompanyHeader } from "../components/company/CompanyHeader";
import { EmptyState } from "../components/common/EmptyState";
import { companyTrackingAdapter, TrackingDecisionControl } from "../components/pre-specs/TrackingDecisionControl";
import {
  companyApi,
  companyKeys,
  companyReviewStatusLabel,
  isCompanyUuid,
  shortIdentity,
  type CompanyReviewView,
  type Uuid,
} from "../lib/companyApi";
import { SegmentInventoryPanel } from "../components/deep-review/SegmentInventoryPanel";
import { TechnicalFacts, TechnicalInfo, type TechnicalFact } from "../components/common/TechnicalInfo";
import { ActorField } from "../components/common/ActorField";
import { Badge } from "../components/common/Badge";
import {
  ConfirmDecisionDialog,
  decisionSummaryExcerpt,
  type ConfirmDecisionSummaryItem,
} from "../components/common/ConfirmDecisionDialog";
import { DisabledReason } from "../components/common/DisabledReason";
import { MutationFeedback } from "../components/common/MutationFeedback";
import { SkeletonPanel } from "../components/common/Skeleton";
import { StatusBadge, type StatusTone } from "../components/common/StatusBadge";
import { Toast } from "../components/common/Toast";
import { useToast } from "../components/common/useToast";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { ReviewHistoryLinkRail, StickyDecisionHeader } from "../components/common/ReviewPrimitives";
import { describeApiError, describeCompanyApiError } from "../lib/apiErrors";
import { formatDateTime } from "../lib/format";
import { TERM } from "../lib/glossary";
import { qualityStatusLabel, qualityStatusNote, qualityStatusVariant } from "../lib/qualityStatus";
import { generateRequestId } from "../lib/requestId";
import type {
  AttemptView,
  DeepReviewReport,
  DeepReviewView,
  FinalOpinionValue,
  StageName,
} from "../components/deep-review/types";
import "../styles/deep-review-evidence.css";
import "../styles/company-workspace.css";

const STAGE_LABELS: Record<StageName, string> = {
  requirements_and_evaluation: "요구사항·평가",
  delivery_risk_economics: "수행·위험·경제성",
  synthesis_and_validation: "종합·검증",
};

const FINAL_VALUES: FinalOpinionValue[] = ["추진", "조건부 추진", "보류", "검토 종료"];
const REPORT_NOT_READY_MAX_RETRIES = 2;

/**
 * 진행 상태 폴링 간격. 1초 고정은 완료될 때까지 매초 서버를 두드렸다. 시작은
 * 빠르게, 오래 걸리는 실행에서는 느리게 — 실패도 경과로 센다.
 */
const POLL_FAST_MS = 2_000;
const POLL_MEDIUM_MS = 5_000;
const POLL_SLOW_MS = 10_000;
const POLL_FAST_ATTEMPTS = 4;
const POLL_MEDIUM_ATTEMPTS = 10;

function isReportNotReady(error: unknown): boolean {
  return error instanceof DeepReviewApiError && error.status === 409 && error.code === "review_not_ready";
}

/** 회사 경로는 공용 `ApiError`를 쓴다. 안전한 코드만 읽는다(message로 분기하지 않는다). */
function isCompanyReportNotReady(error: unknown): boolean {
  return describeCompanyApiError(error, "").code === "review_not_ready";
}

/** 진행 중 검토의 폴링 간격. 기존 화면과 같은 단계 규칙이다. */
function reviewPollInterval(data: DeepReviewView | undefined, dataUpdateCount: number, fetchFailureCount: number): number | false {
  if (!isActiveReview(data)) return false;
  const attempts = dataUpdateCount + fetchFailureCount;
  if (attempts <= POLL_FAST_ATTEMPTS) return POLL_FAST_MS;
  if (attempts <= POLL_MEDIUM_ATTEMPTS) return POLL_MEDIUM_MS;
  return POLL_SLOW_MS;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "대기", running: "진행 중", completed: "완료", failed: "실패", superseded: "대체됨",
  };
  return labels[status] ?? status;
}

/** 검증 항목의 상태 세 값. 서버가 준 값을 그대로 두고 읽는 이름만 옮긴다. */
function checkStatusLabel(status: string): string {
  const labels: Record<string, string> = { passed: "통과", warning: "경고", failed: "실패" };
  return labels[status] ?? status;
}

function statusTone(status: string): StatusTone {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "queued" || status === "running") return "info";
  return "neutral";
}

function isActiveReview(review: DeepReviewView | undefined): boolean {
  if (!review) return false;
  const attemptStatus = review.current_attempt?.status;
  return review.status === "queued" || review.status === "running" || attemptStatus === "queued" || attemptStatus === "running";
}

function attemptTime(attempt: AttemptView): string {
  if (attempt.completed_at) return `완료 ${attempt.completed_at}`;
  if (attempt.started_at) return `시작 ${attempt.started_at}`;
  return "시각 값 없음";
}

/**
 * 이 회차가 남긴 오류 코드 하나. 회차 코드가 없으면 실패한 단계의 코드를
 * 쓴다. 둘 다 없으면 `null`이고, 그때도 실패 사실은 상태가 그대로 말한다.
 */
function attemptErrorCode(attempt: AttemptView): string | null {
  if (attempt.last_error_code) return attempt.last_error_code;
  return attempt.stages.find((stage) => stage.last_error_code)?.last_error_code ?? null;
}

/** 접힌 `기술 정보`가 싣는 코드 전부. 회차 하나에서 값이 빠지지 않게 모은다. */
function attemptErrorFacts(attempt: AttemptView): TechnicalFact[] {
  const facts: TechnicalFact[] = [];
  if (attempt.last_error_code) facts.push({ label: "분석 회차 오류 코드", value: attempt.last_error_code });
  for (const stage of attempt.stages) {
    if (stage.last_error_code) {
      facts.push({ label: `${STAGE_LABELS[stage.stage]} 단계 오류 코드`, value: stage.last_error_code });
    }
  }
  return facts;
}

function updateFirstBlock(report: DeepReviewReport, sectionKey: string, body: string, blockId: string): DeepReviewReport {
  if (report.schema === "bidops.deep-review-report.v2") {
    const selected = report.sections.find(section => section.section_key === sectionKey)?.blocks.find(block => block.block_id === blockId);
    if (!selected) return report;
    return { ...report, claims: report.claims.map(claim => selected.claim_ids.includes(claim.claim_id) ? { ...claim, body } : claim),
      sections: report.sections.map(section => ({ ...section, blocks: section.blocks.map(block => block.block_id === blockId ? { ...block, body } : block) })) };
  }
  return { ...report, sections: report.sections.map(section => section.section_key !== sectionKey ? section
    : { ...section, blocks: section.blocks.map((block, index) => index === 0 ? { ...block, body } : block) }) };
}

function locatorDetails(locatorType: string, locator: Record<string, string | number | number[] | null>): string {
  if (locatorType === "page") return `${String(locator.page ?? "-")}쪽`;
  if (locatorType === "paragraph") {
    return `${String(locator.page ?? "-")}쪽 · 문단 ${String(locator.paragraph_key ?? locator.block_key ?? "-")} · 본문 ${String(locator.text_start ?? "-")}–${String(locator.text_end ?? "-")}`;
  }
  if (locatorType === "table_cell") {
    return `${String(locator.page ?? "-")}쪽 · 표 ${String(locator.table_key ?? "-")} · 행 ${String(locator.row ?? "-")} · 열 ${String(locator.column ?? "-")}`;
  }
  if (locatorType === "bbox") {
    const bbox = Array.isArray(locator.bbox) ? locator.bbox.join(", ") : "-";
    return `${String(locator.page ?? "-")}쪽 · 블록 ${String(locator.block_key ?? "-")} · 영역 [${bbox}]`;
  }
  return `고정 사실 ${String(locator.fact_key ?? "-")}`;
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
      aria-label={`근거 ${id.slice(0, 8)}${selected ? " 선택됨" : ""}`}
      className={`evidence-reference ${selected ? "evidence-reference-selected" : ""}`.trim()}
    >
      {selected ? "선택됨 · " : "근거 · "}{id.slice(0, 8)}
    </button>
  );
}

export function DeepReviewPage() {
  const { deepReviewId } = useParams();
  const reviewId = deepReviewId ?? "";
  const queryClient = useQueryClient();
  const reviewQuery = useQuery({
    queryKey: ["deep-review", reviewId],
    queryFn: () => getDeepReview(reviewId),
    enabled: Boolean(reviewId),
    refetchInterval: (query) => {
      if (!isActiveReview(query.state.data)) return false;
      const attempts = query.state.dataUpdateCount + query.state.fetchFailureCount;
      if (attempts <= POLL_FAST_ATTEMPTS) return POLL_FAST_MS;
      if (attempts <= POLL_MEDIUM_ATTEMPTS) return POLL_MEDIUM_MS;
      return POLL_SLOW_MS;
    },
    refetchIntervalInBackground: false,
  });
  const reportQuery = useQuery({
    queryKey: ["deep-review-report", reviewId],
    queryFn: () => getReport(reviewId),
    enabled: Boolean(reviewId) && Boolean(reviewQuery.data),
    staleTime: 10_000,
    retry: (failureCount, error) => reviewQuery.data?.status === "completed" && isReportNotReady(error) && failureCount < REPORT_NOT_READY_MAX_RETRIES,
    retryDelay: 500,
  });
  const reportView = reportQuery.data;
  const isNarrative = reportView?.report.schema === "bidops.deep-review-report.v2";
  const records = useRef<HTMLDetailsElement | null>(null);
  const [draftBase, setDraftBase] = useState<string | null>(null);
  const [editBlock, setEditBlock] = useState("");
  useEffect(() => { if (reviewQuery.data?.status === "completed") void queryClient.invalidateQueries({ queryKey: ["deep-review-report", reviewId] }); }, [reviewQuery.data?.status, reviewId, queryClient]);
  const [draft, setDraft] = useState<DeepReviewReport | null>(null);
  const [reportDraftDirty, setReportDraftDirty] = useState(false);
  const [actorName, setActorName] = useState("");
  const [revisionReason, setRevisionReason] = useState("");
  const [factualEvidenceText, setFactualEvidenceText] = useState("");
  const [editSection, setEditSection] = useState<string>("project_overview");
  const [opinionValue, setOpinionValue] = useState<FinalOpinionValue | "">("");
  const [opinionReason, setOpinionReason] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  // 저장 성공 알림은 화면마다 같은 방식으로 뜬다. 자동 소멸과 hover·focus 중
  // 멈춤은 Toast가 소유하므로 여기에는 타이머가 없다.
  const { toast, showToast, dismissToast } = useToast();
  // 심층검토 의견은 append-only라 저장 뒤 지울 수 없다. 클릭 즉시 보내지 않고
  // 무엇을 남기는지 확인시킨다. 저장에 성공하면 입력이 비워지므로 요약은 열 때의
  // 값을 얼려 둔다.
  const [opinionConfirm, setOpinionConfirm] = useState<
    { summary: ConfirmDecisionSummaryItem[]; confirmLabel: string; actor: string; payload: Parameters<typeof saveFinalOpinion>[2] } | null
  >(null);

  useEffect(() => {
    if (reportView?.report && !reportDraftDirty) {
      setDraft(reportView.report);
      setDraftBase(reportView.current_revision_id);
      setEditSection(reportView.report.sections[0]?.section_key ?? "project_overview");
      setEditBlock(reportView.report.sections[0]?.blocks[0]?.block_id ?? "");
    }
  }, [reportView, reportDraftDirty]);

  const hasUnsavedDraft = reportDraftDirty
    || Boolean(revisionReason.trim())
    || Boolean(factualEvidenceText.trim())
    || Boolean(opinionReason.trim())
    || opinionValue !== ""
    || acknowledged;

  useUnsavedGuard(hasUnsavedDraft, {
    blockSpaNavigation: true,
    message: "저장되지 않은 심층검토 초안이 있습니다. 이 페이지를 벗어나시겠습니까?",
  });

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

  useEffect(() => {
    if (!selectedEvidenceId && evidenceIds.length > 0) setSelectedEvidenceId(evidenceIds[0]);
  }, [evidenceIds, selectedEvidenceId]);

  const [sourceVerificationEnabled, setSourceVerificationEnabled] = useState(true);
  const retryMutation = useMutation({
    mutationFn: (consent?: { previewId: string; requestId: string }) => createDeepReviewAttempt(reviewId, actorName, consent?.requestId, sourceVerificationEnabled, consent?.previewId),
    onSuccess: async (newAttempt) => {
      showToast(`분석 회차 ${newAttempt.sequence}회를 새로 시작했습니다. 기존 실패 이력은 그대로 남습니다.`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["deep-review", reviewId] }),
        queryClient.invalidateQueries({ queryKey: ["deep-review-report", reviewId] }),
      ]);
    },
  });

  const revisionMutation = useMutation({
    mutationFn: () => {
      if (!draft || !reportView) throw new Error("수정할 보고서가 없습니다.");
      const ids = factualEvidenceText.split(",").map((value) => value.trim()).filter(Boolean);
      return saveRevision(reviewId, actorName, {
        request_id: generateRequestId(), base_revision_id: draftBase ?? reportView.current_revision_id, report: draft,
        reason: revisionReason, factual_change_evidence_ids: ids,
      });
    },
    onSuccess: async () => {
      setRevisionReason(""); setFactualEvidenceText("");
      setReportDraftDirty(false);
      showToast("보고서 수정본을 새로 저장했습니다. 이전 수정본은 그대로 남습니다.");
      await queryClient.invalidateQueries({ queryKey: ["deep-review-report", reviewId] });
    },
  });
  const opinionMutation = useMutation({
    mutationFn: () => {
      if (!opinionConfirm) throw new Error("확인한 의견이 없습니다.");
      return saveFinalOpinion(reviewId, opinionConfirm.actor, opinionConfirm.payload);
    },
    onSuccess: async () => {
      setOpinionReason(""); setAcknowledged(false); setOpinionValue("");
      showToast("사전규격 심층검토 의견을 추가했습니다. 이전 기록은 그대로 남습니다.");
      await queryClient.invalidateQueries({ queryKey: ["deep-review-report", reviewId] });
    },
  });
  const retryDisabledReason = retryMutation.isPending
    ? "새 분석 회차 시작 요청을 처리하고 있습니다."
    : !actorName.trim()
      ? "새 분석 회차를 시작하려면 담당자 이름을 입력하십시오."
      : null;
  const staleDraft = draftBase !== null && draftBase !== reportView?.current_revision_id;
  const editingBlocked = reviewQuery.data?.status !== "completed";
  const revisionDisabledReason = editingBlocked ? "현재 분석이 완료된 뒤 수정할 수 있습니다." : staleDraft ? "새 보고서가 도착했습니다. 현재 초안을 별도로 보관한 뒤 최신 보고서를 다시 불러오십시오." : revisionMutation.isPending
    ? "보고서 수정본 저장 요청을 처리하고 있습니다."
    : !actorName.trim()
      ? "보고서 수정본을 저장하려면 담당자 이름을 입력하십시오."
      : !revisionReason.trim()
        ? "보고서 수정본을 저장하려면 수정 사유를 입력하십시오."
        : null;

  if (!reviewId) {
    return <section aria-labelledby="deep-review-title"><h2 id="deep-review-title">심층 검토 보고서</h2><p>심층 검토 식별자가 없습니다.</p></section>;
  }
  const review = reviewQuery.data;
  const attempt = review?.current_attempt;
  const reportProblem = reportQuery.error
    ? describeApiError(reportQuery.error, "보고서를 확인할 수 없습니다.")
    : null;
  const reviewProblem = reviewQuery.error
    ? describeApiError(reviewQuery.error, "심층 검토 상태를 확인할 수 없습니다.")
    : null;
  const reportNotReady = isReportNotReady(reportQuery.error);
  const validationFailed = reportView?.validation.status === "failed";
  // 실패한 check가 가리키는 첫 근거. 없으면 원문으로 갈 길이 없다는 사실을
  // 그대로 표시하고 다른 근거로 대신하지 않는다.
  const firstFailedEvidenceId = reportView?.validation.checks
    .filter((check) => check.status === "failed")
    .flatMap((check) => check.related_evidence_ids)[0] ?? null;
  const opinionDisabledReason = editingBlocked ? "현재 분석이 완료된 뒤 의견을 기록할 수 있습니다." : !opinionValue ? "심층검토 의견을 선택하십시오." : opinionMutation.isPending
    ? "심층검토 의견 저장 요청을 처리하고 있습니다."
    : !actorName.trim()
      ? "심층검토 의견을 저장하려면 담당자 이름을 입력하십시오."
      : !opinionReason.trim()
        ? "심층검토 의견을 저장하려면 사유를 입력하십시오."
        : validationFailed && !acknowledged
          ? "검증 실패를 확인해야 심층검토 의견을 저장할 수 있습니다."
          : null;
  const decisionCard = reportView?.report.sections.find((section) => section.section_key === "decision_card");
  const decisionBlocks = decisionCard?.blocks ?? [];

  return (
    <section aria-labelledby="deep-review-title" className={`deep-review-page detail-skeleton${isNarrative ? " is-narrative" : ""}`} data-astryx-theme="bidops">
      <StickyDecisionHeader className="deep-review-header detail-skeleton-head" label="심층 검토 보고서 상태 헤더">
        <div className="detail-skeleton-head-top">
          <div>
            <p className="deep-review-kicker">{isNarrative ? "사전규격 · 문서 검토" : `보고서 식별자 · ${reviewId.slice(0, 8)}`}</p>
            <h2 id="deep-review-title">심층 검토 보고서</h2>
          </div>
          <div aria-label="보고서 범위" className="deep-review-scope">공고 {review?.notice_id ?? "확인 중"}{isNarrative ? " · 확정 문서 기준" : ` · 문서 묶음 ${review?.bundle_id.slice(0, 8) ?? "확인 중"}`}</div>
        </div>
        <div className="detail-skeleton-status-row">
          <StatusBadge label={review ? `상태 · ${statusLabel(review.status)}` : "상태 · 확인 중"} tone={review ? statusTone(review.status) : "neutral"} />
          {attempt ? <StatusBadge label={`현재 ${TERM.attempt} · ${statusLabel(attempt.status)}`} tone={statusTone(attempt.status)} /> : <StatusBadge label={`현재 ${TERM.attempt} · 없음`} tone="neutral" />}
        </div>
      </StickyDecisionHeader>

      {reportView?.report.schema === "bidops.deep-review-report.v2" ? <NarrativeReportReader report={reportView.report} checks={reportView.validation.checks} revision={reportView.history.find(item => item.revision_id === reportView.current_revision_id)?.sequence} executionStatus={review?.status ?? "running"} onAnalysisSettings={() => { if (records.current) records.current.open = true; const panel = document.getElementById("deep-review-analysis-settings"); panel?.setAttribute("open", ""); panel?.scrollIntoView({ block: "start" }); panel?.querySelector("input")?.focus(); }} onRefresh={() => { void reportQuery.refetch(); void reviewQuery.refetch(); }} onRecords={() => { if (records.current) { records.current.open = true; records.current.scrollIntoView({ block: "start" }); } }} /> : null}
      <details ref={records} className="narrative-records" open={!isNarrative}>
        <summary>{isNarrative ? "검증·분석 진행·수정·의견 기록" : "보고서와 검토 기록"}</summary>
      {reportView && !isNarrative && reportView.validation.checks.some(check => check.check_type === "source_verification_skipped") ? <p className="narrative-notice">원문 대조 미실시 · 본문의 인용과 수치는 원문을 직접 확인하십시오.</p> : null}
      {reportView && !isNarrative ? <p className="narrative-notice">이전 형식의 저장된 보고서입니다. 자동 분류한 요약과 차단 위험 항목은 원문을 함께 확인하십시오. 분석 근거의 부족은 사업 자체의 위험 확정과 다릅니다.</p> : null}
      {/* 담당자 이름은 이 화면에서 한 번만 받는다. 재시도·수정본 저장·의견
          저장이 모두 같은 값을 쓰는데도 패널마다 입력을 되풀이해서 물었고,
          비활성 사유는 "아래 보고서 수정본 저장의 담당자 이름"처럼 다른 자리를
          가리켜야 했다. 자리 하나로 합치고, 그 값은 ActorField가 이 브라우저에
          기억한다. 감사 표식일 뿐 인증이 아니라는 사실은 그대로 적는다. */}
      <section aria-labelledby="deep-review-actor-title" className="deep-review-actor-panel">
        <div>
          <h3 className="deep-review-section-title" id="deep-review-actor-title">이 화면의 담당자</h3>
          <p>이 화면의 재시도·보고서 수정본·심층검토 의견은 모두 이 이름으로 기록됩니다.</p>
        </div>
        <ActorField value={actorName} onChange={setActorName} autoComplete="off" />
      </section>

      {/* 시안 `DeepReview`의 상단 카드 4개(PLAN 단계 F 작업 5). 시안의 두 번째
          카드는 `참여 준비 상태`이지만 이 보고서 계약(bidops.deep-review-report.v1)에
          그 축이 없다. 없는 값을 카드로 채우지 않고, 자리는 계약이 실제로 답할 수
          있는 검증 결과가 받는다. 참여 준비 상태가 여기 없다는 사실은 카드 아래
          한 줄로 밝힌다 — 빈칸이나 추정으로 두지 않는다. */}
      {reportView ? (
        <section aria-label="보고서 요약 카드" className="deep-review-summary-cards">
          <article className="deep-review-summary-card">
            <span>종합 판단</span>
            <strong>{reportView.report.system_recommendation}</strong>
            <small>모델 제안 · 사람 확정 전</small>
          </article>
          <article className="deep-review-summary-card">
            <span>검증 결과</span>
            <strong>{reportView.validation.checks.some(check => check.check_type === "source_verification_skipped") ? "원문 대조 미실시" : reportView.validation.status === "passed" ? "통과" : "실패"}</strong>
            <small>실패 {reportView.report.validation_summary.failed}건 · 경고 {reportView.report.validation_summary.warnings}건</small>
          </article>
          <article className="deep-review-summary-card">
            <span>미확인 사항</span>
            <strong>{reportView.report.unknowns.length}건</strong>
            <small>미확인 그대로 유지 · 자동 보정 없음</small>
          </article>
          <article className="deep-review-summary-card">
            <span>보고서 수정본</span>
            <strong>{reportView.history.length > 0 ? `${reportView.history.find(item => item.revision_id === reportView.current_revision_id)?.sequence}차` : "확인 불가"}</strong>
            <small>추가만 기록 · 덮어쓰기 없음</small>
          </article>
          {/* 품질 표식(명세 §6.5·§8). 참조 실행과 mock 참조를 운영 완료로 보이게
              하지 않고, 표식이 없는 옛 revision은 `표식 없음`이다. */}
          <article className="deep-review-summary-card deep-review-quality-card">
            <span>품질 표식</span>
            <Badge
              label={qualityStatusLabel(reportView.report.quality_status)}
              variant={qualityStatusVariant(reportView.report.quality_status)}
            />
            <small>{qualityStatusNote(reportView.report.quality_status)}</small>
          </article>
        </section>
      ) : null}
      {reportView ? (
        <p className="deep-review-summary-note">
          <strong>참여 준비 상태</strong>는 공고 판정이 소유하는 별도 축이라 이 보고서가 답하지 않습니다.
          보고서 계약에 그 값이 없으므로 비슷한 값을 대신 채우지 않습니다.
        </p>
      ) : null}

      <section aria-labelledby="preparation-title" className="deep-review-preparation">
        <h3 id="preparation-title" className="deep-review-section-title">문서 준비 및 분석 진행</h3>
        <p className="deep-review-section-lede">서버가 고정한 문서 묶음과 안전 검사 결과로 준비 상태를 확인합니다. 화면이 준비 상태를 다시 판정하지 않습니다.</p>
        <div className="deep-review-preparation-grid">
          <div><strong>검토 상태</strong><br />{review ? statusLabel(review.status) : "불러오는 중"}</div>
          <div><strong>현재 {TERM.attempt}</strong><br />{attempt ? `${attempt.sequence}회 · ${statusLabel(attempt.status)}` : "없음"}</div>
          {(attempt?.stages ?? []).map((stage) => (
            <div key={stage.stage} className="deep-review-preparation-stage">
              <strong>{STAGE_LABELS[stage.stage]}</strong><br />{statusLabel(stage.status)}
            </div>
          ))}
        </div>
        {/* 실패는 사람 말 한 문장이 먼저 말하고, 서버가 정한 코드는 그 아래
            접힌 `기술 정보`에 전문으로 남는다(ADR-0066). 사전에 없는 코드는
            문장 안에 그대로 실려 다른 사유로 바뀌거나 숨지 않는다. */}
        {attempt && (attemptErrorCode(attempt) || attempt.status === "failed") ? (
          <div className="deep-review-failure">
            <p className="deep-review-failure-note">
              {attemptErrorCode(attempt)
                ? attemptFailureSentence(attemptErrorCode(attempt) as string)
                : "분석을 마치지 못했습니다. 오류 코드는 기록되지 않았습니다."}
            </p>
            {attemptErrorFacts(attempt).length > 0 ? (
              <TechnicalInfo summary="기술 정보 · 오류 코드">
                <TechnicalFacts facts={attemptErrorFacts(attempt)} label="현재 분석 회차 오류 코드" />
              </TechnicalInfo>
            ) : null}
          </div>
        ) : null}
        {isActiveReview(review) ? <p className="deep-review-polling" role="status" aria-live="polite">분석 진행 상태를 제한된 간격으로 자동 갱신하고 있습니다.</p> : null}
        {reviewProblem ? (
          <MutationFeedback
            className="deep-review-inline-error"
            onRecover={() => { void reviewQuery.refetch(); }}
            problem={reviewProblem}
            recoverPending={reviewQuery.isFetching}
            recoverLabel="상태 다시 확인"
            recoverPendingLabel="상태 확인 중"
            tone="error"
          />
        ) : null}
      </section>

      {review ? (
        <section aria-labelledby="attempt-history-title" className="deep-review-attempt-history">
          <div className="deep-review-section-heading">
            <div>
              <h3 id="attempt-history-title">{TERM.attempt} 이력</h3>
              <p>회차별 실행 결과를 확인합니다. 회차와 단계는 추가만 기록하며, 현재 회차 표시만 지금 실행 중인 것을 가리킵니다.</p>
            </div>
            <span>{review.attempts.length}개 이력</span>
          </div>
          {review.attempts.length > 0 ? (
            <ol className="deep-review-attempt-list">
              {review.attempts.map((historyAttempt) => {
                const current = historyAttempt.id === review.current_attempt?.id;
                return (
                  <li key={historyAttempt.id} className={current ? "deep-review-attempt-current" : ""}>
                    <div className="deep-review-attempt-heading">
                      <div><strong>{historyAttempt.sequence}회차</strong><span>{attemptTime(historyAttempt)}</span></div>
                      <div><StatusBadge className={`deep-review-attempt-status deep-review-attempt-${historyAttempt.status}`} tone={statusTone(historyAttempt.status)} label={statusLabel(historyAttempt.status)} />{current ? <span className="deep-review-current-label">현재 회차</span> : null}</div>
                    </div>
                    {attemptErrorCode(historyAttempt) ? (
                      <>
                        <p className="deep-review-attempt-error">
                          {attemptFailureSentence(attemptErrorCode(historyAttempt) as string)}
                        </p>
                        <TechnicalInfo summary={`기술 정보 · ${historyAttempt.sequence}회차 오류 코드`}>
                          <TechnicalFacts
                            facts={attemptErrorFacts(historyAttempt)}
                            label={`${historyAttempt.sequence}회차 오류 코드`}
                          />
                        </TechnicalInfo>
                      </>
                    ) : null}
                    <ol className="deep-review-stage-list">
                      {historyAttempt.stages.map((stage) => (
                        <li key={`${historyAttempt.id}-${stage.stage}`}>
                          <span>{STAGE_LABELS[stage.stage]}</span>
                          <strong>{statusLabel(stage.status)}</strong>
                        </li>
                      ))}
                    </ol>
                  </li>
                );
              })}
            </ol>
          ) : <p>아직 실행한 분석 회차가 없습니다.</p>}
        </section>
      ) : null}

      {attempt && ["failed", "completed"].includes(attempt.status) ? (
        <details id="deep-review-analysis-settings" open={attempt.status === "failed"} className="deep-review-retry-panel deep-review-analysis-settings">
          <summary>분석 설정 · 새 분석 실행</summary>
          <div>
            <p className="deep-review-panel-kicker">현재 회차 · 원문 대조 {attempt.source_verification_enabled === false ? "미실시" : "사용"}</p>
            {attempt.provider ? <p>실행 출처: {attempt.provider} · {attempt.model} · {attempt.reasoning_effort}</p> : null}
            <h3 id="retry-title">새 분석 회차로 재시도</h3>
            <p>선택한 설정으로 새 분석을 시작합니다. 기존 보고서와 실행 이력은 보존됩니다.</p>
            <SourceVerificationSetting value={sourceVerificationEnabled} onChange={setSourceVerificationEnabled} disabled={retryMutation.isPending} />
          </div>
          {attempt.provider === "codex-exec" && reviewQuery.data ? <LunaRequest key={`${reviewId}:${sourceVerificationEnabled}:${actorName}`} noticeId={reviewQuery.data.notice_id} bundleId={reviewQuery.data.bundle_id} reviewId={reviewId} verification={sourceVerificationEnabled} actor={actorName} onSubmit={(previewId, requestId) => retryMutation.mutateAsync({ previewId, requestId })} /> : null}
          <div className="deep-review-retry-controls">
            <button
              className="interaction-control"
              type="button"
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending || !actorName.trim() || attempt.provider === "codex-exec"}
              aria-describedby={retryDisabledReason ? "deep-review-retry-disabled" : undefined}
            >
              {retryMutation.isPending ? "새 분석 회차 시작 중" : "새 분석 회차로 재시도"}
            </button>
            {retryDisabledReason ? <DisabledReason id="deep-review-retry-disabled">{retryDisabledReason}</DisabledReason> : null}
          </div>
          {retryMutation.error ? (
            <MutationFeedback
              onRecover={() => { void reviewQuery.refetch(); }}
              problem={describeApiError(retryMutation.error, "새 분석 회차를 시작할 수 없습니다.")}
              recoverPending={reviewQuery.isFetching}
              tone="error"
            />
          ) : null}
        </details>
      ) : null}

      {reportProblem && !reportView && !(reportNotReady && isActiveReview(review)) ? (
        <MutationFeedback
          onRecover={() => { void reportQuery.refetch(); }}
          problem={reportProblem}
          recoverPending={reportQuery.isFetching}
          recoverLabel="보고서 다시 조회"
          recoverPendingLabel="보고서 다시 조회 중"
          tone={reportNotReady ? "warning" : "error"}
        />
      ) : null}
      {review?.status === "completed" && reportQuery.isLoading ? (
        <SkeletonPanel label="분석이 완료되어 보고서를 불러오는 중" lines={5} />
      ) : null}
      {reportView ? (
        <div className="detail-skeleton-grid deep-review-report-grid">
          <div className="detail-skeleton-main deep-review-report-main">
          <section aria-labelledby="decision-title" className="deep-review-decision-grid">
            <div className="deep-review-system-card">
              <h3 id="decision-title" className="deep-review-section-title">시스템 권고</h3>
              <p className="deep-review-recommendation">{reportView.report.system_recommendation}</p>
              <p className="deep-review-section-copy">모델이 제안한 권고를 그대로 보여 줍니다. 사람의 심층검토 의견과 별도이며, 서버가 저장한 주장과 검증을 화면이 다시 판정하지 않습니다.</p>
              {/* 시안 `DeepReview`의 결정 카드 요약은 항목·내용·근거·검증 네 열
                  표다(PLAN 단계 F 작업 5). 검증 열은 서버가 준 validation check를
                  그 행의 claim으로 이어 읽을 뿐, 화면이 다시 판정하지 않는다. */}
              {!isNarrative ? <div className="deep-review-decision-table-wrap" tabIndex={0} aria-label="결정 카드 요약 표를 좌우로 이동할 수 있습니다">
                <table aria-label="결정 카드 요약" className="deep-review-decision-table">
                  <thead>
                    <tr>
                      <th scope="col">항목</th>
                      <th scope="col">내용</th>
                      <th scope="col">근거</th>
                      <th scope="col">검증</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decisionBlocks.flatMap((block) => block.rows).map((row) => {
                      const evidenceIdsForRow = row.claim_ids.flatMap(
                        (claimId) => reportView.report.claims.find((claim) => claim.claim_id === claimId)?.evidence_ids ?? [],
                      );
                      const rowChecks = reportView.validation.checks.filter(
                        (check) => check.related_claim_ids.some((claimId) => row.claim_ids.includes(claimId)),
                      );
                      const worst = rowChecks.find((check) => check.status === "failed")
                        ?? rowChecks.find((check) => check.status === "warning")
                        ?? rowChecks[0];
                      return (
                        <tr key={row.row_key}>
                          <th scope="row">{decisionRowHeading(row.label)}</th>
                          <td>{row.cells.join(" · ")}</td>
                          <td>
                            <div className="deep-review-evidence-actions">
                              {evidenceIdsForRow.length > 0
                                ? evidenceIdsForRow.map((id) => (
                                  <EvidenceButton key={`${row.row_key}-${id}`} id={id} selected={id === selectedEvidenceId} onSelect={() => setSelectedEvidenceId(id)} />
                                ))
                                : <span className="deep-review-missing-evidence">근거를 확인할 수 없습니다.</span>}
                            </div>
                          </td>
                          <td>
                            {worst
                              ? <StatusBadge label={checkStatusLabel(worst.status)} tone={worst.status === "passed" ? "success" : worst.status === "warning" ? "warning" : "danger"} />
                              : <span className="deep-review-missing-evidence">검증 결과 없음</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div> : null}
            </div>
            <div className="deep-review-opinion-card">
              <h3 className="deep-review-section-title">사전규격 심층검토 의견</h3>
              {reportView.final_opinion ? <p><strong>{reportView.final_opinion.value}</strong> · {reportView.final_opinion.reason}</p> : <p>아직 기록되지 않았습니다.</p>}
              <p className="deep-review-section-copy">현재 검증 결과 <strong>{reportView.validation.checks.some(check => check.check_type === "source_verification_skipped") ? "원문 대조 미실시" : reportView.validation.status === "passed" ? "통과" : "실패"}</strong>. 최종 입찰 Go/No-Go와 별도이며, 검증이 실패하면 확인 표시를 해야 저장됩니다.</p>
            </div>
          </section>

          <section aria-labelledby="validation-title" className={`deep-review-validation-panel${validationFailed ? " is-failed" : ""}`}>
            <h3 id="validation-title" className="deep-review-section-title">검증 결과와 미확인 사항</h3>
            <p>상태: <strong>{reportView.validation.checks.some(check => check.check_type === "source_verification_skipped") ? "원문 대조 미실시" : reportView.validation.status === "passed" ? "통과" : "실패"}</strong> · 실패 {reportView.validation.checks.filter(check => check.status === "failed").length} · 경고 {reportView.validation.checks.filter(check => check.status === "warning").length}</p>
            {/* 시안의 Validation 실패 블록은 두 조작을 함께 갖는다(PLAN 단계 F 작업 5).
                실패를 자동 보정하지 않으므로, 사람이 갈 수 있는 길은 원문 확인과
                새 attempt 두 가지뿐이다. */}
            {validationFailed ? (
              <div className="deep-review-validation-failed" role="alert">
                <p>
                  이 항목을 판정으로 읽지 마십시오. 실패를 확인해야 심층검토 의견을 저장할 수 있고, 화면이 자동으로 보정하지 않습니다.
                </p>
                <div className="deep-review-validation-actions">
                  <button
                    className="interaction-control"
                    type="button"
                    disabled={firstFailedEvidenceId === null}
                    aria-describedby={firstFailedEvidenceId === null ? "deep-review-validation-source-disabled" : undefined}
                    onClick={() => { if (firstFailedEvidenceId) setSelectedEvidenceId(firstFailedEvidenceId); }}
                  >
                    원문에서 확인
                  </button>
                  {firstFailedEvidenceId === null ? (
                    <DisabledReason id="deep-review-validation-source-disabled">
                      실패한 검증 항목에 연결된 근거가 없어 원문 위치로 갈 수 없습니다. 근거가 없다는 사실을 다른 값으로 바꾸지 않습니다.
                    </DisabledReason>
                  ) : null}
                  <button
                    className="interaction-control"
                    type="button"
                    onClick={() => { const panel = document.getElementById("deep-review-analysis-settings"); panel?.setAttribute("open", ""); panel?.scrollIntoView({ block: "start" }); panel?.querySelector("input")?.focus(); }}
                  >
                    분석 설정으로 이동
                  </button>
                  {!actorName.trim() ? (
                    <DisabledReason id="deep-review-validation-retry-disabled">
                      새 분석 회차를 시작하려면 담당자 이름을 입력하십시오.
                    </DisabledReason>
                  ) : null}
                </div>
              </div>
            ) : null}
            {reportView.report.unknowns.length > 0 ? <ul>{reportView.report.unknowns.map((unknown) => <li key={unknown}>{unknown}</li>)}</ul> : <p>미확인 사항이 없습니다.</p>}
            <ul>{reportView.validation.checks.map((check) => <li key={`${check.check_type}-${check.message}`}>{checkStatusLabel(check.status)} · {check.message}</li>)}</ul>
          </section>

          {!isNarrative ? <><div className="deep-review-report-sections">
            {reportView.report.sections.map((section) => (
              <section key={section.section_key} aria-labelledby={`section-${section.section_key}`} className="deep-review-report-section">
                <h3 id={`section-${section.section_key}`} className="deep-review-section-title">{section.title}</h3>
                {section.blocks.map((block) => (
                  <div key={block.block_id} className="deep-review-report-block">
                    {block.title ? <h4>{block.title}</h4> : null}
                    {block.body ? <p className="deep-review-report-block-body">{block.body}</p> : null}
                    {block.rows.length > 0 ? (
                      <div className="deep-review-report-table-wrap" tabIndex={0} aria-label={`${section.title} 표를 좌우로 이동할 수 있습니다`}>
                        <table className="deep-review-report-table">
                          <thead><tr><th scope="col" className="deep-review-report-table-head">항목</th><th scope="col" className="deep-review-report-table-head">내용</th><th scope="col" className="deep-review-report-table-head">근거</th></tr></thead>
                          <tbody>{block.rows.map((row) => <tr key={row.row_key}><th scope="row" className="deep-review-report-table-cell deep-review-report-table-label">{row.label}</th><td className="deep-review-report-table-cell deep-review-report-table-value">{row.cells.join(" · ")}</td><td className="deep-review-report-table-cell deep-review-report-table-evidence">{row.claim_ids.flatMap((claimId) => reportView.report.claims.find((claim) => claim.claim_id === claimId)?.evidence_ids ?? []).map((id) => <EvidenceButton key={id} id={id} selected={id === selectedEvidenceId} onSelect={() => setSelectedEvidenceId(id)} />)}</td></tr>)}</tbody>
                        </table>
                      </div>
                    ) : null}
                  </div>
                ))}
              </section>
            ))}
          </div>

          <section aria-labelledby="evidence-title" className="evidence-viewer">
            <header className="evidence-viewer-header">
              <div>
                <p className="evidence-viewer-kicker">원문까지 추적</p>
                <h3 id="evidence-title">원문 근거 뷰어</h3>
                <p>보고서의 근거를 저장된 문서 버전과 원문 위치까지 되짚어 봅니다. 화면이 근거를 새로 만들거나 고치지 않습니다.</p>
              </div>
              <div className="evidence-viewer-statuses">
                <span className="evidence-analysis-status">분석 {review?.status === "completed" ? "완료" : statusLabel(review?.status ?? "queued")}</span>
                <span className={`evidence-validation evidence-validation-${reportView.validation.status}`}>
                  검증 {reportView.validation.status === "passed" ? "통과" : "실패"}
                </span>
              </div>
            </header>
            <div className="evidence-reference-list" aria-label="보고서 근거 선택">
              {evidenceIds.length > 0 ? evidenceIds.map((id) => <EvidenceButton key={id} id={id} selected={id === selectedEvidenceId} onSelect={() => setSelectedEvidenceId(id)} />) : <span>연결된 근거가 없습니다.</span>}
            </div>
            {evidenceQuery.isLoading ? (
              <SkeletonPanel label="선택한 근거를 불러오는 중" lines={4} />
            ) : null}
            {evidenceQuery.error ? (
              <MutationFeedback
                className="deep-review-evidence-error"
                onRecover={() => { void evidenceQuery.refetch(); }}
                problem={describeApiError(evidenceQuery.error, "근거를 확인할 수 없습니다.")}
                recoverPending={evidenceQuery.isFetching}
                tone="error"
              />
            ) : null}
            {evidenceQuery.data ? <div className="evidence-compare-grid">
              <article className="evidence-source-card" aria-label="선택된 근거 정보">
                <div className="evidence-source-heading">
                  <div>
                    <span>선택한 근거의 {TERM.locator}</span>
                    <strong>{locatorDetails(evidenceQuery.data.locator_type, evidenceQuery.data.locator)}</strong>
                  </div>
                  <span className="evidence-source-kind">
                    {evidenceQuery.data.source_kind === "document" ? "문서 원문" : "고정된 회사 프로필 사실"}
                  </span>
                </div>
                <dl className="evidence-source-facts">
                  <div><dt>근거 신뢰도</dt><dd>{evidenceQuery.data.confidence === null ? "값 없음" : evidenceQuery.data.confidence.toFixed(3)}</dd></div>
                </dl>
                <div className="evidence-quote">
                  <span>{evidenceQuery.data.source_verification_enabled === false && evidenceQuery.data.source_kind === "document" ? "모델이 인용한 내용 · 원문 대조 미실시" : "선택한 근거의 원문 인용"}</span>
                  <blockquote>{evidenceQuery.data.quote}</blockquote>
                  {evidenceQuery.data.source_verification_enabled === false ? <p>원문 대조 미실시 · 아래 원문과 직접 비교하십시오.</p> : null}
                </div>
                {/* 식별자와 해시는 지우지 않고 접는다. 눈으로 대조하는 값이므로
                    전문을 줄바꿈해 싣는다(ADR-0066 결정 2). */}
                <TechnicalInfo className="evidence-technical" summary="기술 정보 · 근거 식별자와 해시">
                  <TechnicalFacts
                    label="선택한 근거의 식별자와 해시"
                    facts={[
                      { label: "선택한 근거 식별자", value: evidenceQuery.data.evidence_id },
                      { label: "저장 문서 버전", value: evidenceQuery.data.document_version_id ?? "값 없음" },
                      { label: `원문 ${TERM.digest} · SHA-256`, value: evidenceQuery.data.source_sha256 },
                    ]}
                  />
                </TechnicalInfo>
              </article>
              {evidenceQuery.data.page ? (
                <div className="evidence-page" aria-label="안전하게 투영한 페이지">
                  <header>
                    <div><span>안전하게 투영한 페이지 블록</span><strong>{evidenceQuery.data.page.page}쪽</strong></div>
                    <span>블록 {evidenceQuery.data.page.blocks.length}개</span>
                  </header>
                  {evidenceQuery.data.page.blocks.map((block, index) => (
                    <article key={block.block_key} className="evidence-page-block">
                      <div><strong>{index + 1}번째 블록</strong><span>{block.type}</span></div>
                      <p>{block.text || "추출된 본문 없음"}</p>
                      <TechnicalInfo summary={`기술 정보 · ${index + 1}번째 블록 식별자와 위치`}>
                        <TechnicalFacts
                          label={`${index + 1}번째 블록의 식별자와 위치`}
                          facts={[
                            { label: "블록 식별자", value: block.block_key },
                            { label: "글자 인식 신뢰도", value: block.confidence === null ? "값 없음" : block.confidence.toFixed(3) },
                            { label: "원문 영역 · bbox", value: block.bbox ? `[${block.bbox.join(", ")}]` : "값 없음" },
                          ]}
                        />
                      </TechnicalInfo>
                    </article>
                  ))}
                </div>
              ) : <div className="evidence-page-empty">안전하게 투영할 페이지 블록이 없습니다.</div>}
            </div> : null}
          </section>

          </> : null}
          <section aria-labelledby="opinion-title" className="deep-review-opinion-panel">
            <h3 id="opinion-title" className="deep-review-section-title">사전규격 심층검토 의견 추가</h3>
            {/* 상단 카드와 같은 문구를 저장 form 위에도 둔다(명세 §6.5). 표식이
                무엇이든 최종 의견 저장을 막지 않는다 — 사람의 기록을 품질
                표식으로 잠그지 않는다. */}
            <p className="deep-review-opinion-quality">
              <span>이 보고서의 품질 표식</span>
              <Badge
                label={qualityStatusLabel(reportView.report.quality_status)}
                variant={qualityStatusVariant(reportView.report.quality_status)}
              />
              <span>{qualityStatusNote(reportView.report.quality_status)}</span>
            </p>
            <p>현재 보고서 수정본에 사람의 의견을 남깁니다. 추가만 기록되어 지울 수 없으며, 최종 입찰 Go/No-Go가 아닙니다.</p>
            <div className="deep-review-opinion-form">
              <label>심층검토 의견<select aria-label="심층검토 의견" className="interaction-control deep-review-section-select" value={opinionValue} onChange={(event) => setOpinionValue(event.target.value as FinalOpinionValue)}><option value="">의견 선택</option>{FINAL_VALUES.map((value) => <option key={value}>{value}</option>)}</select></label>
              <label>심층검토 의견 사유<textarea className="deep-review-form-textarea" aria-label="심층검토 의견 사유" rows={3} value={opinionReason} onChange={(event) => setOpinionReason(event.target.value)} /></label>
              {validationFailed ? <label className="interaction-check"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /> 검증 실패를 확인했으며 실패 표시를 그대로 둡니다.</label> : null}
              <button
                className="interaction-control deep-review-form-action"
                type="button"
                onClick={() => {
                  // 전제조건(담당자·사유·validation acknowledge)은 그대로 버튼의
                  // disabled가 소유한다. 여기서는 확인 단계만 연다.
                  if (!opinionValue) return;
                  setOpinionConfirm({
                    actor: actorName,
                    payload: { request_id: generateRequestId(), report_revision_id: reportView.current_revision_id, validation_run_id: reportView.validation.validation_run_id, value: opinionValue, reason: opinionReason, acknowledged_validation_failure: acknowledged },
                    confirmLabel: `심층검토 의견 저장 · ${opinionValue}`,
                    summary: [
                      { label: "심층검토 의견", value: opinionValue },
                      { label: "담당자", value: actorName.trim() },
                      { label: "의견 사유", value: decisionSummaryExcerpt(opinionReason) },
                      { label: "검증 상태", value: reportView.validation.status === "passed" ? "통과" : "실패" },
                      {
                        label: "검증 실패 확인",
                        value: validationFailed
                          ? (acknowledged ? "확인함 · 실패 표시 유지" : "확인하지 않음")
                          : "해당 없음 · 실패한 검증 항목 없음",
                      },
                    ],
                  });
                }}
                disabled={opinionDisabledReason !== null}
                aria-describedby={opinionDisabledReason ? "deep-review-opinion-disabled" : undefined}
              >
                심층검토 의견 추가
              </button>
              {opinionDisabledReason ? <DisabledReason id="deep-review-opinion-disabled">{opinionDisabledReason}</DisabledReason> : null}
              {opinionMutation.error ? (
                <MutationFeedback
                  onRecover={() => { void reportQuery.refetch(); }}
                  problem={describeApiError(opinionMutation.error, "사전규격 심층검토 의견을 저장할 수 없습니다.")}
                  recoverPending={reportQuery.isFetching}
                  tone="error"
                />
              ) : null}
            </div>
          </section>
          </div>
          {/* 시안 `DeepReview`의 우측 열은 보고서 범위 · 수정본 저장 · 이력
              셋이다(PLAN 단계 F 작업 5). 수정본 저장은 네 결정 중 하나가 아니라
              보고서 본문의 append-only 편집이므로, "레일에 결정 액션을 두지
              않는다"(작업 1)를 어기지 않는다. 되돌릴 수 없는 결정(사전규격
              심층검토 의견)은 본문 열에 그대로 남는다. */}
          <div className="deep-review-side">
            <section aria-labelledby="report-scope-title" className="deep-review-scope-panel">
              <h3 id="report-scope-title" className="deep-review-section-title">보고서 범위</h3>
              <p className="deep-review-scope-summary">
                공고 1건 · {TERM.bundle} 1개 · {formatDateTime(reportView.report.created_at)} 생성
              </p>
              <dl className="deep-review-scope-facts">
                <div><dt>현재 {TERM.attempt}</dt><dd>{attempt ? `${attempt.sequence}회 · ${statusLabel(attempt.status)}` : "없음"}</dd></div>
              </dl>
              <p className="detail-skeleton-rail-note">이 범위 밖의 문서는 보고서에 들어가지 않았습니다. 범위가 좁다는 것을 사실이 없다는 뜻으로 읽지 마십시오.</p>
              {/* 식별자와 버전은 운영자가 눈으로 대조하는 값이라 지우지 않고
                  접는다. 시각은 원문 ISO도 함께 남긴다. */}
              <TechnicalInfo summary="기술 정보 · 정책·회사 프로필 버전">
                <TechnicalFacts
                  label="보고서 범위의 식별자와 버전"
                  facts={[
                    { label: "공고 ID", value: String(reportView.report.notice_id) },
                    { label: TERM.bundle, value: reportView.report.bundle_id },
                    { label: "정책 버전", value: reportView.report.policy_version_id },
                    { label: "회사 프로필 버전", value: reportView.report.profile_version_id },
                    { label: "보고서 생성 시각 원문", value: reportView.report.created_at },
                  ]}
                />
              </TechnicalInfo>
            </section>
            {/* 문서별 inventory와 사람 확인 필요 segment(명세 §6.8). 이 화면의
                계약에는 bundle → 문서 구조 ID를 주는 자리가 없으므로, 지금
                선택된 근거가 가리키는 구조 ID를 쓴다. 다른 문서의 값으로
                대신하지 않고 어느 문서인지 문장으로 밝힌다. */}
            <SegmentInventoryPanel
              documentVersionId={evidenceQuery.data?.document_version_id ?? null}
              structureId={evidenceQuery.data?.structure_id ?? null}
              sourceNote={evidenceQuery.data?.structure_id
                ? "현재 선택한 근거가 가리키는 문서의 구간 목록입니다."
                : "근거를 선택하면 그 근거가 가리키는 문서의 구간 목록을 표시합니다."}
            />
            <section aria-labelledby="editor-title" className="deep-review-editor-panel">
            <h3 id="editor-title" className="deep-review-section-title">보고서 수정본 편집</h3>
            <p>보고서 본문을 고쳐 새 수정본으로 남깁니다. 이전 수정본을 덮어쓰지 않으며, 담당자 이름은 이 화면 위쪽에서 한 번 입력하는 감사 표식이고 인증이 아닙니다.</p>
            <div className="deep-review-editor-form">
              <label>수정할 절<select className="interaction-control deep-review-section-select" aria-label="수정 절 선택" value={editSection} onChange={(event) => { setEditSection(event.target.value); setEditBlock(currentReport?.sections.find(section => section.section_key === event.target.value)?.blocks[0]?.block_id ?? ""); }}>{(currentReport?.sections ?? []).map((section) => <option key={section.section_key} value={section.section_key}>{section.title}</option>)}</select></label>
              {isNarrative ? <label>수정할 문장<select className="interaction-control" aria-label="수정 문장 선택" value={editBlock} onChange={event => setEditBlock(event.target.value)}>{currentSection?.blocks.map((block, index) => <option key={block.block_id} value={block.block_id}>{index + 1}. {block.title}</option>)}</select></label> : null}
              <label>절 내용<textarea className="deep-review-form-textarea" aria-label="절 내용" rows={5} value={(isNarrative ? currentSection?.blocks.find(block => block.block_id === editBlock)?.body : currentSection?.blocks[0]?.body) ?? ""} onChange={(event) => { setReportDraftDirty(true); setDraft((value) => value ? updateFirstBlock(value, editSection, event.target.value, editBlock) : value); }} /></label>
              <label>수정 사유<textarea className="deep-review-form-textarea" aria-label="수정 사유" rows={3} value={revisionReason} onChange={(event) => setRevisionReason(event.target.value)} /></label>
              <fieldset><legend>수정에 사용한 근거</legend>{evidenceIds.map((id, index) => <label key={id} className="interaction-check"><input type="checkbox" checked={factualEvidenceText.split(",").includes(id)} onChange={event => setFactualEvidenceText((current) => { const ids = current.split(",").filter(Boolean).filter(value => value !== id); return (event.target.checked ? [...ids, id] : ids).join(","); })} />근거 {index + 1} · {currentReport?.claims.find(claim => claim.evidence_ids.includes(id))?.category}</label>)}</fieldset>
              <button className="interaction-control deep-review-form-action" type="button" onClick={() => revisionMutation.mutate()} disabled={revisionDisabledReason !== null} aria-describedby={revisionDisabledReason ? "deep-review-revision-disabled" : undefined}>새 보고서 수정본 저장</button>
              {revisionDisabledReason ? <DisabledReason id="deep-review-revision-disabled">{revisionDisabledReason}</DisabledReason> : null}
              {revisionMutation.error ? (
                <MutationFeedback
                  onRecover={() => { void reportQuery.refetch(); }}
                  problem={describeApiError(revisionMutation.error, "보고서 수정본을 저장할 수 없습니다.")}
                  recoverPending={reportQuery.isFetching}
                  tone="error"
                />
              ) : null}
            </div>
          </section>
            <ReviewHistoryLinkRail
              className="detail-skeleton-rail"
              footer={<p className="detail-skeleton-rail-note">보고서 수정본은 추가만 기록합니다. 실패한 분석 회차나 이전 수정본을 덮어쓰지 않습니다.</p>}
              historySections={[{
              empty: <p className="detail-skeleton-rail-note">보고서 수정본 이력이 없습니다.</p>,
              entries: reportView.history.map((item) => ({
                detail: `검증 ${item.validation_status ?? "값 없음"} · ${item.created_by_name ?? "시스템 생성"}`,
                id: item.revision_id,
                label: `수정본 ${item.sequence} · ${item.origin === "machine" ? "시스템" : "사람"}`,
              })),
              label: "보고서 수정본 이력",
              listClassName: "detail-skeleton-rail-history",
            }]}
              links={[
              ...(typeof review?.notice_id === "number" ? [{ href: `/pre-specs/${review.notice_id}`, label: "사전규격 상세 →" }] : []),
              { href: "/opportunities", label: "사업 추적 목록 →" },
            ]}
              linksClassName="detail-skeleton-rail-links"
              title="보고서 이력과 연결"
            />
          </div>
        </div>
      ) : null}
      </details>
      {staleDraft ? <div><p role="alert">새 보고서가 도착했습니다. 작성 중인 초안은 보존했으며 이전 보고서를 기준으로 한 저장은 차단했습니다.</p><button className="interaction-control" type="button" onClick={() => { setReportDraftDirty(false); setRevisionReason(""); setFactualEvidenceText(""); }}>초안을 버리고 최신본으로 편집</button></div> : null}
      {hasUnsavedDraft ? <p className="deep-review-unsaved" role="status">저장되지 않은 심층검토 초안이 있습니다. 화면을 벗어나기 전에 저장하십시오.</p> : null}
      {/* 확인 단계. 취소하면 초안은 그대로 남고 요청은 나가지 않는다. 저장에
          실패하면 다이얼로그는 닫히고 기존 인라인 오류 표시가 그대로 보인다. */}
      <ConfirmDecisionDialog
        confirmLabel={opinionConfirm?.confirmLabel ?? "심층검토 의견 저장"}
        isPending={opinionMutation.isPending}
        onConfirm={() => opinionMutation.mutate(undefined, { onSettled: () => setOpinionConfirm(null) })}
        onOpenChange={(next) => { if (!next) setOpinionConfirm(null); }}
        open={opinionConfirm !== null}
        summary={opinionConfirm?.summary ?? []}
        title="심층검토 의견을 기록합니다"
        warning="이 기록은 저장 뒤 되돌릴 수 없습니다. 추가만 기록되어 지울 수 없습니다."
      />
      {toast ? <Toast message={toast.message} variant={toast.variant} onDismiss={dismissToast} /> : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// 회사 심층 검토 보고서 adapter (가상회사 데모, `docs/work/demo-contract.md` §6·§9)
//
// 같은 `NarrativeReportReader`를 쓰되 보고서는 회사 wrapper의 `view`에서, 근거는 회사 근거
// endpoint와 회사 query key에서 읽는다. 기존 단일회사 화면(`DeepReviewPage`)과 cache를
// 공유하지 않는다. 보고서 수정본·심층검토 의견 저장은 회사 경로 계약에 endpoint가 없어
// 이 화면에서 제공하지 않는다(기존 unscoped 쓰기 경로로 보내지 않는다).

function CompanyAddressProblem({ title, companyId }: { title: string; companyId?: string }) {
  return (
    <section className="cw-page">
      <EmptyState
        tone="error"
        title={title}
        description="주소의 식별자를 확인할 수 없어 아무 회사의 결과도 보여 주지 않습니다."
        action={companyId ? { label: "회사 사전규격 목록", to: `/companies/${companyId}/pre-specs` } : { label: "회사 다시 고르기", to: "/companies" }}
      />
    </section>
  );
}

export function CompanyDeepReviewPage() {
  const { companyId, reviewId } = useParams();
  if (!isCompanyUuid(companyId)) return <CompanyAddressProblem title="회사 주소가 올바르지 않습니다." />;
  if (!isCompanyUuid(reviewId)) return <CompanyAddressProblem title="심층 검토 주소가 올바르지 않습니다." companyId={companyId} />;
  // 회사·검토가 바뀌면 다시 마운트한다. 다른 회사의 입력·승인 state가 넘어오지 않는다.
  return <CompanyDeepReviewReport companyId={companyId} key={`${companyId}:${reviewId}`} reviewId={reviewId} />;
}

interface CompanyAttemptVariables {
  companyId: Uuid;
  reviewId: Uuid;
  previewId: string;
  requestId: string;
  actorName: string;
}

function CompanyDeepReviewReport({ companyId, reviewId }: { companyId: Uuid; reviewId: Uuid }) {
  const queryClient = useQueryClient();
  const reviewQuery = useQuery({
    queryKey: companyKeys.deepReview(companyId, reviewId),
    queryFn: ({ signal }) => companyApi.getDeepReview(companyId, reviewId, { signal }),
    retry: false,
    refetchInterval: (query) => reviewPollInterval(query.state.data, query.state.dataUpdateCount, query.state.fetchFailureCount),
    refetchIntervalInBackground: false,
  });
  const fetchedReview = reviewQuery.data;
  // 응답이 다른 회사 소속이면 이 화면에 그리지 않는다(서버도 404를 낸다).
  const review: CompanyReviewView | undefined = fetchedReview && fetchedReview.company_id === companyId ? fetchedReview : undefined;
  const reviewMismatch = fetchedReview !== undefined && review === undefined;
  const reportQuery = useQuery({
    queryKey: companyKeys.report(companyId, reviewId),
    queryFn: ({ signal }) => companyApi.getReport(companyId, reviewId, { signal }),
    enabled: review !== undefined,
    retry: false,
    staleTime: 10_000,
  });
  useEffect(() => {
    if (review?.status === "completed") void queryClient.invalidateQueries({ queryKey: companyKeys.report(companyId, reviewId) });
  }, [companyId, queryClient, review?.status, reviewId]);
  const wrapper = reportQuery.data && reportQuery.data.company_id === companyId ? reportQuery.data : undefined;
  const reportView = wrapper?.view;
  const noticeId = review?.notice_id ?? null;
  const detailQuery = useQuery({
    queryKey: companyKeys.preSpec(companyId, noticeId ?? 0),
    queryFn: ({ signal }) => companyApi.getPreSpec(companyId, noticeId as number, { signal }),
    enabled: noticeId !== null,
    retry: false,
  });
  const companyQuery = useQuery({
    queryKey: companyKeys.detail(companyId),
    queryFn: ({ signal }) => companyApi.getCompany(companyId, { signal }),
    retry: false,
  });
  const company = companyQuery.data && companyQuery.data.company_id === companyId ? companyQuery.data : null;
  const trackingAdapter = useMemo(
    () => (detailQuery.data ? companyTrackingAdapter({ companyId, opportunityId: detailQuery.data.opportunity_id, noticeId: detailQuery.data.notice_id, companyName: company?.name ?? null }) : null),
    [company?.name, companyId, detailQuery.data],
  );
  const evidenceSource = useMemo<EvidenceSource>(() => ({
    queryKey: (evidenceId) => companyKeys.reviewEvidence(companyId, reviewId, evidenceId),
    fetch: (evidenceId) => companyApi.getReviewEvidence(companyId, reviewId, evidenceId),
  }), [companyId, reviewId]);

  const [actorName, setActorName] = useState("");
  const [sourceVerificationEnabled, setSourceVerificationEnabled] = useState(true);
  const settings = useRef<HTMLDetailsElement | null>(null);
  const records = useRef<HTMLDetailsElement | null>(null);
  const { toast, showToast, dismissToast } = useToast();
  const attemptMutation = useMutation({
    mutationFn: (variables: CompanyAttemptVariables) => companyApi.createDeepReviewAttempt(
      variables.companyId,
      variables.reviewId,
      { preview_id: variables.previewId, source_verification_enabled: true, request_id: variables.requestId },
      variables.actorName,
    ),
    // 시작한 회사·검토의 key만 무효화한다.
    onSuccess: async (_attempt, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: companyKeys.deepReview(variables.companyId, variables.reviewId) }),
        queryClient.invalidateQueries({ queryKey: companyKeys.report(variables.companyId, variables.reviewId) }),
        queryClient.invalidateQueries({ queryKey: companyKeys.preSpecLists(variables.companyId) }),
      ]);
    },
  });

  const attempt = review?.current_attempt ?? null;
  const reportNotReady = isCompanyReportNotReady(reportQuery.error);
  const isNarrative = reportView?.report.schema === "bidops.deep-review-report.v2";
  const openSettings = () => {
    if (settings.current) {
      settings.current.open = true;
      settings.current.scrollIntoView({ block: "start" });
      settings.current.querySelector("input")?.focus();
    }
  };
  const openRecords = () => {
    if (records.current) {
      records.current.open = true;
      records.current.scrollIntoView({ block: "start" });
    }
  };
  const identity = wrapper ?? review;

  return (
    <section className="cw-page deep-review-page is-narrative" aria-label="회사 심층 검토" data-company-id={companyId} data-astryx-theme="bidops">
      <CompanyHeader companyId={companyId} screen="deep-review" />
      {reviewQuery.isPending ? (
        <p role="status">이 회사의 심층 검토를 불러오는 중입니다.</p>
      ) : reviewQuery.isError || reviewMismatch ? (
        <EmptyState
          tone="error"
          title="이 회사의 심층 검토를 불러오지 못했습니다."
          problem={describeCompanyApiError(reviewQuery.error, "심층 검토를 불러오지 못했습니다.")}
          action={{ label: "회사 사전규격 목록", to: `/companies/${companyId}/pre-specs` }}
        />
      ) : review ? (
        <>
          <div className="cw-section cw-report-identity" data-testid="company-report-identity">
            <h3>회사 심층 검토 보고서</h3>
            <dl className="cw-facts">
              <dt>회사</dt>
              <dd data-testid="company-report-company">
                {company ? `${company.name} · ${company.is_fictional ? "가상회사" : "가상회사 표식 없음"}` : "회사 확인 중"}
              </dd>
              <dt>검토 상태</dt>
              <dd data-testid="company-report-status" data-review-status={review.status}>
                <Badge variant={review.status === "failed" ? "danger" : "neutral"} label={companyReviewStatusLabel(review.status)} />
                {attempt ? <span className="cw-caption"> · 현재 분석 회차 {attempt.sequence}회 · {statusLabel(attempt.status)}</span> : <span className="cw-caption"> · 분석 회차 없음</span>}
              </dd>
              <dt>입력 기준</dt>
              <dd data-testid="company-report-current" data-is-current={String(review.is_current)}>
                {review.is_current ? "현재 회사 지식·문서 기준" : "현재 입력 기준 아님 · 이전 회사 지식 또는 문서로 만든 결과입니다"}
              </dd>
              <dt>품질 표식</dt>
              <dd>{qualityStatusLabel(review.quality_status)} · <span className="cw-caption">{qualityStatusNote(review.quality_status)}</span></dd>
              <dt>공고</dt>
              <dd><Link className="cw-link" to={`/companies/${companyId}/pre-specs/${review.notice_id}`}>notice {review.notice_id} · 이 회사 기준 상세</Link></dd>
              <dt>프로필 버전</dt><dd data-testid="company-report-profile-version">{identity?.profile_version_id ?? "확인 불가"}</dd>
              <dt>그래프 버전</dt><dd data-testid="company-report-graph-version">{identity?.graph_version_id ?? "확인 불가"}</dd>
              <dt>그래프 해시</dt><dd title={identity?.graph_sha256}>{shortIdentity(identity?.graph_sha256)}</dd>
              <dt>온톨로지</dt><dd>{identity?.ontology_version ?? "확인 불가"}</dd>
              <dt>입력 해시</dt><dd title={review.input_sha256}>{shortIdentity(review.input_sha256)}</dd>
            </dl>
            {wrapper && (wrapper.profile_version_id !== review.profile_version_id || wrapper.graph_version_id !== review.graph_version_id) ? (
              <p role="alert">보고서의 회사 지식 버전이 검토 기록과 다릅니다. 이 보고서를 이 검토의 결과로 읽지 마십시오.</p>
            ) : null}
            <p className="cw-caption">
              심층 검토는 참고 분석이며 추적 결정이나 최종 입찰 Go/No-Go를 대신하지 않습니다. 보고서 수정본·심층검토 의견 저장은 회사 경로 계약에 없어 이 화면에서 제공하지 않습니다.
            </p>
            {isActiveReview(review) ? <p role="status" aria-live="polite">분석 진행 상태를 제한된 간격으로 자동 갱신하고 있습니다.</p> : null}
          </div>

          {reportView && isNarrative && reportView.report.schema === "bidops.deep-review-report.v2" ? (
            <NarrativeReportReader
              checks={reportView.validation.checks}
              evidenceSource={evidenceSource}
              executionStatus={review.status}
              onAnalysisSettings={openSettings}
              onRecords={openRecords}
              onRefresh={() => { void reportQuery.refetch(); void reviewQuery.refetch(); }}
              report={reportView.report}
              revision={reportView.history.find((item) => item.revision_id === reportView.current_revision_id)?.sequence}
            />
          ) : reportView ? (
            <p className="cw-section" role="status">회사 보고서 계약은 서술형 보고서(v2)입니다. 이 보고서 형식은 이 화면에서 표시하지 않습니다.</p>
          ) : reportQuery.isFetching && !reportQuery.data ? (
            <p className="cw-section" role="status">보고서를 불러오는 중입니다.</p>
          ) : reportNotReady ? (
            <p className="cw-section" role="status" data-testid="company-report-not-ready">
              {isActiveReview(review) ? "분석이 끝나면 보고서를 표시합니다." : "이 검토에는 아직 완성된 보고서가 없습니다."} 결과가 없는 것을 부적합이나 실패로 읽지 마십시오.
            </p>
          ) : reportQuery.isError ? (
            <MutationFeedback
              onRecover={() => { void reportQuery.refetch(); }}
              problem={describeCompanyApiError(reportQuery.error, "보고서를 확인할 수 없습니다.")}
              recoverLabel="보고서 다시 조회"
              recoverPending={reportQuery.isFetching}
              tone="error"
            />
          ) : null}

          <details ref={records} className="cw-section" id="company-review-records">
            <summary>검증·분석 회차 기록</summary>
            {reportView ? (
              <p>
                검증 상태 · {reportView.validation.checks.some((check) => check.check_type === "source_verification_skipped") ? "원문 대조 미실시" : reportView.validation.status === "passed" ? "통과" : "실패"}
                {" · "}실패 {reportView.validation.checks.filter((check) => check.status === "failed").length}건 · 경고 {reportView.validation.checks.filter((check) => check.status === "warning").length}건
              </p>
            ) : null}
            {review.attempts.length > 0 ? (
              <ol aria-label="분석 회차 이력">
                {review.attempts.map((item) => (
                  <li key={item.id}>
                    {item.sequence}회차 · {statusLabel(item.status)} · {attemptTime(item)}
                    {attemptErrorCode(item) ? ` · ${attemptFailureSentence(attemptErrorCode(item) as string)}` : ""}
                    {item.id === review.current_attempt?.id ? " · 현재 회차" : ""}
                  </li>
                ))}
              </ol>
            ) : <p>아직 실행한 분석 회차가 없습니다.</p>}
          </details>

          {attempt && ["failed", "completed"].includes(attempt.status) ? (
            <details ref={settings} className="cw-section" id="company-review-analysis-settings" open={attempt.status === "failed"} data-testid="company-review-retry">
              <summary>분석 설정 · 새 분석 회차</summary>
              <p>같은 회사·문서 기준으로 새 분석 회차를 요청합니다. 기존 보고서와 실패 이력은 덮어쓰지 않으며 새 회차가 따로 남습니다.</p>
              <SourceVerificationSetting value={sourceVerificationEnabled} onChange={setSourceVerificationEnabled} disabled={attemptMutation.isPending} />
              <ActorField label="재시도 담당자 이름" value={actorName} onChange={setActorName} autoComplete="off" />
              {sourceVerificationEnabled ? (
                <LunaRequest
                  key={`${companyId}:${reviewId}:${sourceVerificationEnabled}:${actorName}`}
                  adapter={createCompanyLunaAdapter({ companyId, company, noticeId: review.notice_id, bundleId: review.bundle_id, reviewId })}
                  actor={actorName}
                  bundleId={review.bundle_id}
                  noticeId={review.notice_id}
                  reviewId={reviewId}
                  verification={sourceVerificationEnabled}
                  onSubmit={async (previewId, requestId) => {
                    const created = await attemptMutation.mutateAsync({ companyId, reviewId, previewId, requestId, actorName: actorName.trim() });
                    showToast(`분석 회차 ${created.sequence}회를 새로 요청했습니다. 기존 이력은 그대로 남습니다.`);
                    return created;
                  }}
                />
              ) : (
                <p role="status">회사 경로는 원문 대조를 사용하는 요청만 받습니다. 이 설정으로는 미리보기와 요청을 보내지 않으며 이전 미리보기 승인은 폐기했습니다.</p>
              )}
            </details>
          ) : null}

          {trackingAdapter ? (
            <TrackingDecisionControl adapter={trackingAdapter} />
          ) : detailQuery.isError ? (
            <MutationFeedback
              onRecover={() => { void detailQuery.refetch(); }}
              problem={describeCompanyApiError(detailQuery.error, "추적 결정을 위한 사업기회 연결을 확인할 수 없습니다.")}
              tone="error"
            />
          ) : (
            <p className="cw-section" role="status">추적 결정을 위한 사업기회 연결을 확인하는 중입니다.</p>
          )}
        </>
      ) : null}
      {toast ? <Toast message={toast.message} variant={toast.variant} onDismiss={dismissToast} /> : null}
    </section>
  );
}

export default DeepReviewPage;
