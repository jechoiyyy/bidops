import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Switch } from "@astryxdesign/core/Switch";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Copy } from "lucide-react";
import {
  CancelButton,
  CriteriaDialog,
  DataTable,
  DetailFooter,
  DetailHeader,
  DialogActions,
  Facts,
  Note,
  Queue,
  Section,
  Small,
  StateView,
  StatusToken,
} from "../components/criteria/CriteriaPrimitives";
import { ApiError, api } from "../lib/api";
import { describeApiError } from "../lib/apiErrors";
import { formatMoment as formatMomentBase } from "../lib/format";
import { generateRequestId } from "../lib/requestId";
import type {
  C2DailyTriggerReason,
  C2DailyTriggerStateResponse,
  C2PolicyBlocker,
  C2PolicyInspectResponse,
  C2PolicyStatus,
  C2PolicySummary,
  C2QualityGateListItem,
  C2QualityGatePassMetrics,
  C2QualityGateResultStatus,
} from "../lib/types";
import "../styles/order-plan-policy.css";

/**
 * 발주계획 선별 정책 탭 — C-2 policy의 사람 승인과 일일 자동 실행 스위치.
 *
 * `docs/0918_daily-operation/spec.md` §11, wire는 `docs/contracts.md` "C-2 일일 운영 계약".
 * 지키는 경계가 넷이다.
 *
 *  1. **활성 여부의 정본은 DB 행이다.** 화면은 서버가 준 `policy_status`·`blockers[]`·
 *     `activation_allowed`만 보여 준다. blocker를 브라우저에서 다시 계산하지 않는다.
 *  2. **`미측정`과 `미달`은 다른 표면이다.** 임계값 미정·측정 미완은 중립, 미달만 실패
 *     의미색이다. 계산 불가를 통과로도, 실패로도 바꾸지 않는다.
 *  3. **승인과 스위치만 쓴다.** gate 생성·evaluation 기록·측정 실행은 스크립트 몫이라
 *     여기에 입력 수단이 없다.
 *  4. **policy를 교체하면 자동 실행이 멈춘다.** 스위치는 버전에 묶여 있으므로 새 버전에서
 *     다시 켜야 한다. 이 사실을 스위치 옆과 활성화 확인 창에 적는다.
 */

const STATUS_LABELS: Record<C2PolicyStatus, string> = {
  draft: "초안",
  activation_candidate: "활성화 후보",
  active: "운영 활성",
  retired: "교체됨",
};

const QUALITY_GATE_STATUS_LABELS: Record<string, string> = {
  not_measured: "미측정",
  measured: "측정됨",
  passed: "통과 기록",
  failed: "미달 기록",
};

const SWITCH_GUIDE = "policy를 교체하면 자동 실행이 멈춥니다. 새 버전에서 다시 켜야 합니다.";

/** 런타임 blocker를 사람 말로. 모르는 code는 지어내지 않고 그대로 보여 준다. */
function blockerText(blocker: C2PolicyBlocker): string {
  const { code, detail } = blocker;
  switch (code) {
    case "quality_gate_missing":
      return "이 버전에 쓸 수 있는 제품 재실행 품질 게이트가 없습니다. 측정 스크립트가 게이트를 만들어야 합니다.";
    case "quality_gate_thresholds_undecided":
      return "품질 게이트 임계값 4개 중 정해지지 않은 값이 있습니다(사람 결정 D-b).";
    case "quality_gate_not_passed":
      if (detail === "미측정") return "최신 게이트 평가가 미측정입니다 — 임계값이 정해지지 않아 판정하지 않았습니다.";
      if (detail === "보류") return "최신 게이트 평가가 보류입니다 — 측정이 아직 끝나지 않았습니다.";
      if (detail === "미달") return "최신 게이트 평가가 미달입니다 — 임계값을 채우지 못한 지표가 있습니다.";
      if (detail === "none") return "게이트 평가가 아직 기록되지 않았습니다.";
      return `최신 게이트 평가가 통과가 아닙니다 (${detail ?? "상세 없음"}).`;
    case "audit_sample_policy_unapproved":
      return "policy에 감사 표본 설정(사용 여부·실행당 상한·검토 주기)이 갖춰지지 않았습니다(사람 결정 D-c).";
    case "execution_transport_not_allowed":
      return "binding의 외부 전송 승인(실행 허용·per_binding 범위·승인자·승인 시각)이 갖춰지지 않았습니다(사람 결정 D-d).";
    case "binding_digest_mismatch":
      return "binding이 이 policy의 digest·버전과 맞지 않거나 binding 상태가 허용값 밖입니다.";
    case "policy_file_missing":
      if (detail === "policy") return "운영 컨테이너 경로에 digest가 일치하는 policy 파일이 없습니다.";
      if (detail === "binding") return "운영 컨테이너 경로에 digest가 일치하는 binding 파일이 없습니다.";
      return "운영 컨테이너 경로에 digest가 일치하는 policy·binding 파일이 없습니다.";
    case "policy_not_candidate":
      return `활성화 후보 상태가 아닙니다${detail ? ` (현재 ${STATUS_LABELS[detail as C2PolicyStatus] ?? detail})` : ""}.`;
    case "quality_gate_artifact_unknown":
      return "요청한 게이트 평가 artifact digest를 찾을 수 없습니다.";
    case "quality_gate_evaluation_not_latest":
      return "요청한 게이트 평가가 그 게이트의 최신 revision이 아닙니다. 화면을 새로 고치십시오.";
    case "quality_gate_basis_not_product_rerun":
      return "참조 산출물 재채점 게이트는 활성화 근거가 될 수 없습니다.";
    case "quality_gate_digest_mismatch":
      return "게이트의 policy·binding digest가 이 policy 행과 다릅니다.";
    case "active_slot_conflict":
      return "다른 활성화와 동시에 처리돼 운영 활성 자리를 얻지 못했습니다. 최신 상태를 확인하십시오.";
    default:
      return detail ? `${code} (${detail})` : code;
  }
}

const TRIGGER_REASON_TEXT: Record<C2DailyTriggerReason, string> = {
  env_cap_off: "운영자가 환경 설정을 켜야 합니다 (BIDOPS_C2_DAILY_TRIGGER_ENABLED가 꺼져 있습니다).",
  no_active_policy: "운영 활성 policy가 없습니다.",
  switch_off: "이 버전의 자동 실행 스위치가 꺼져 있습니다.",
  switch_bound_to_other_version: "예전 버전에 켜 둔 스위치만 있습니다. 이 버전에서 다시 켜야 합니다.",
  quality_gate_not_passed: "운영 활성 policy의 품질 게이트 상태가 통과가 아닙니다.",
  execution_transport_not_allowed: "실행 전송이 허용되지 않았습니다 (환경 BIDOPS_C2_EXECUTION_ALLOWED 또는 binding 승인).",
  policy_file_missing: "운영 컨테이너에 digest가 일치하는 policy·binding 파일이 없습니다.",
};

function triggerReasonText(reason: string): string {
  return TRIGGER_REASON_TEXT[reason as C2DailyTriggerReason] ?? reason;
}

/** 서버가 `보류`·`미달`의 이유로 넣는 code. 모르는 code는 그대로 둔다. */
const METRIC_LABELS: Record<string, string> = {
  recall_pct: "재현율",
  precision_pct: "정밀도",
  important_missed: "중요 누락",
  review_load: "하루 검토량",
};

function evaluationReasonText(reason: string): string {
  if (reason === "thresholds_undecided") return "임계값이 정해지지 않았습니다.";
  if (reason === "pass_count_below_required") return "측정 pass가 2회에 못 미칩니다.";
  if (reason === "measurement_missing") return "측정값이 비어 있는 지표가 있습니다.";
  if (reason === "pass_execution_not_success") return "측정 실행 중 성공이 아닌 것이 있습니다(부분 성공 포함).";
  if (reason === "not_product_pipeline_result") return "제품 파이프라인이 낸 결과가 아닙니다.";
  if (reason.startsWith("threshold_not_met:")) {
    const metric = reason.slice("threshold_not_met:".length);
    return `${METRIC_LABELS[metric] ?? metric} 미달`;
  }
  return reason;
}

/** `lib/format.ts`가 정본이다(U3, 중복 통합). 이 화면의 null 문구(`기록 없음`)만 고정한다. */
function moment(value: string | null | undefined): string {
  return formatMomentBase(value, "기록 없음");
}

function shortDigest(value: string | null | undefined): string {
  return value ? value.slice(0, 12) : "없음";
}

function pct(value: number | null | undefined): string {
  return typeof value === "number" ? `${value}%` : "값 없음";
}

function count(value: number | null | undefined): string {
  return typeof value === "number" ? `${value}건` : "값 없음";
}

function yesNo(value: boolean | null | undefined, yes: string, no: string): string {
  if (value === true) return yes;
  if (value === false) return no;
  return "값 없음";
}

async function copyText(value: string): Promise<void> {
  if (window.isSecureContext && navigator.clipboard) {
    await navigator.clipboard.writeText(value);
    return;
  }
  // 사내망 HTTP에서는 Clipboard API가 없을 수 있다. 초점을 복사 단추로 돌려놓는다.
  const active = document.activeElement;
  const field = document.createElement("textarea");
  field.value = value;
  document.body.append(field);
  let copied = false;
  try { field.select(); copied = document.execCommand("copy"); }
  finally { field.remove(); if (active instanceof HTMLElement) active.focus({ preventScroll: true }); }
  if (!copied) throw new Error("clipboard-unavailable");
}

function DigestLine({ label, value, onCopied }: { label: string; value: string; onCopied: (message: string) => void }) {
  return (
    <span className="opp-digest">
      <code>{value}</code>
      <Button
        icon={<Copy aria-hidden="true" />}
        isIconOnly
        label={`${label} 복사`}
        onClick={() => {
          copyText(value)
            .then(() => onCopied(`${label}를 복사했습니다.`))
            .catch(() => onCopied("복사하지 못했습니다. 표시된 digest를 선택해 복사해 주세요."));
        }}
        size="sm"
        variant="ghost"
      />
    </span>
  );
}

/** 오류를 사람 말 몇 줄로. `activation_blocked`는 서버가 실은 blocker를 그대로 푼다. */
function mutationErrorLines(error: unknown, fallback: string): string[] {
  if (error instanceof ApiError && error.code === "activation_blocked") {
    const details = typeof error.detail === "object" && error.detail !== null && "details" in error.detail
      ? (error.detail as { details: unknown }).details
      : null;
    const blockers = typeof details === "object" && details !== null && "blockers" in details
      && Array.isArray((details as { blockers: unknown }).blockers)
      ? (details as { blockers: C2PolicyBlocker[] }).blockers
      : [];
    return ["활성화가 거부됐습니다.", ...blockers.map(blockerText)];
  }
  if (error instanceof ApiError && error.code === "actor_name_required") return ["담당자 이름을 입력하십시오."];
  if (error instanceof ApiError && error.code === "actor_name_invalid") return ["담당자 이름 형식을 확인하십시오. `system`은 쓸 수 없습니다."];
  if (error instanceof ApiError && error.code === "immutable_conflict") {
    return ["policy 상태나 digest가 그사이 바뀌었습니다. 입력은 그대로 두었습니다. 최신 상태를 확인한 뒤 다시 시도하십시오."];
  }
  const description = describeApiError(error, fallback);
  return [description.title, description.detail];
}

// ── 확인 대화 ──────────────────────────────────────────────────────────

interface ConfirmSnapshot {
  kind: "candidate" | "activate" | "trigger";
  key: string;
  title: string;
  facts: [string, string][];
  notes: { title: string; body: string; tone: "neutral" | "warning" }[];
  reason: { label: string; maxLength: number } | null;
  confirmLabel: string;
  submitLabel: string;
}

function ConfirmDialog({ snapshot, busy, error, onClose, onConfirm }: {
  snapshot: ConfirmSnapshot | null;
  busy: boolean;
  error: string[] | null;
  onClose: () => void;
  onConfirm: (snapshot: ConfirmSnapshot, input: { actor: string; reason: string; confirmed: boolean }) => void;
}) {
  const [actor, setActor] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const key = snapshot?.key ?? "";
  // 대상이 바뀌면 입력을 비운다. 앞 대상에 적은 이름·사유가 다음 대상의 감사 기록이 되지 않게 한다.
  useEffect(() => { setActor(""); setReason(""); setConfirmed(false); }, [key]);

  const reasonReady = snapshot?.reason ? reason.trim().length > 0 && reason.length <= snapshot.reason.maxLength : true;
  const ready = actor.trim().length > 0 && reasonReady && confirmed && !busy;

  function close() {
    // 요청이 나간 뒤에는 닫지 않는다. 응답이 창을 닫거나 오류를 남긴다.
    if (busy) return;
    onClose();
  }

  return (
    <CriteriaDialog onClose={close} open={snapshot !== null} title={snapshot?.title ?? ""}>
      {snapshot ? (
        <>
          <Facts items={snapshot.facts.map(([term, value]) => [term, <span className="crit-mono" key={term}>{value}</span>])} />
          {snapshot.notes.map((note) => (
            <Note key={note.title} role={note.tone === "warning" ? "alert" : "note"} title={note.title} tone={note.tone}>{note.body}</Note>
          ))}
          {snapshot.reason ? (
            <TextInput
              isDisabled={busy}
              description={`${reason.length}/${snapshot.reason.maxLength}자`}
              label={snapshot.reason.label}
              onChange={setReason}
              placeholder="사유"
              value={reason}
            />
          ) : null}
          <TextInput isDisabled={busy} label="확인 담당자 · 필수" onChange={setActor} placeholder="담당자 이름" value={actor} />
          <Small>담당자 이름은 감사 표식이며 로그인이나 신원 인증이 아닙니다.</Small>
          <CheckboxInput isDisabled={busy} label={snapshot.confirmLabel} onChange={setConfirmed} value={confirmed} />
          {error ? (
            <div className="crit-error" role="alert">
              {error.map((line) => <Text as="p" key={line}>{line}</Text>)}
            </div>
          ) : null}
          <DialogActions>
            <CancelButton isDisabled={busy} onClick={close} />
            <Button
              isDisabled={!ready}
              label={busy ? "요청 중…" : snapshot.submitLabel}
              onClick={() => onConfirm(snapshot, { actor: actor.trim(), reason: reason.trim(), confirmed })}
              size="sm"
              variant="primary"
            />
          </DialogActions>
        </>
      ) : null}
    </CriteriaDialog>
  );
}

// ── 게이트 결과 ─────────────────────────────────────────────────────────

function GateSurface({ gate }: { gate: C2QualityGateListItem }) {
  const evaluation = gate.latest_evaluation;
  const reference = gate.evaluation_basis === "reference_artifact_rescore";
  if (!evaluation) {
    return (
      <div className="opp-gate-surface" data-gate-result="none" data-tone="neutral">
        <span className="opp-gate-surface-head"><StatusToken label="평가 없음" /><Text weight="semibold">아직 평가가 기록되지 않았습니다</Text></span>
        <Small>측정 스크립트가 evaluation을 기록하면 여기에 나타납니다. 평가 없음은 미달이 아닙니다.</Small>
      </div>
    );
  }
  const status: C2QualityGateResultStatus = evaluation.result_status;
  const reasons = evaluation.reasons.filter((reason) => reason !== "not_product_pipeline_result");
  const tone = status === "통과" ? "success" : status === "미달" ? "error" : "neutral";
  const headline = status === "미측정"
    ? "미측정 · 임계값 미정"
    : status === "보류"
      ? "보류 · 측정 미완"
      : status === "미달"
        ? "미달 · 임계값을 채우지 못한 지표가 있습니다"
        : "통과 · 두 pass 모두 네 지표를 충족했습니다";
  const body = status === "미측정"
    ? "임계값 4개 중 정해지지 않은 값이 있어 판정하지 않았습니다. 미측정은 미달이 아닙니다."
    : status === "보류"
      ? "측정이 끝나지 않아 판정을 미뤘습니다. 보류는 미달이 아닙니다. 빠진 항목:"
      : status === "미달"
        ? "미달 지표:"
        : reference
          ? "수치는 통과지만 참조 산출물 재채점이라 활성화 근거가 아닙니다."
          : "이 평가의 artifact digest로 활성화를 요청할 수 있습니다.";
  return (
    <div className="opp-gate-surface" data-gate-result={status} data-tone={tone}>
      <span className="opp-gate-surface-head">
        <StatusToken label={status} />
        <Text weight="semibold">{headline}</Text>
      </span>
      <Small>{body}</Small>
      {(status === "보류" || status === "미달") && reasons.length > 0 ? (
        <ul className="opp-list">{reasons.map((reason) => <li key={reason}>{evaluationReasonText(reason)}</li>)}</ul>
      ) : null}
    </div>
  );
}

function metricRows(gate: C2QualityGateListItem): ReactNode[][] {
  const evaluation = gate.latest_evaluation;
  const pass1: C2QualityGatePassMetrics | null = evaluation?.metrics.pass_1 ?? null;
  const pass2: C2QualityGatePassMetrics | null = evaluation?.metrics.pass_2 ?? null;
  const threshold = (value: number | null, format: (v: number | null) => string, sign: string) =>
    value === null ? "미정" : `${sign} ${format(value)}`;
  const rows: [string, string, (m: C2QualityGatePassMetrics | null) => string, string][] = [
    ["재현율", threshold(gate.thresholds.recall_pct, pct, "≥"), (m) => (m ? pct(m.recall_pct) : "pass 없음"), pct(evaluation?.measured_recall_pct)],
    ["정밀도", threshold(gate.thresholds.precision_pct, pct, "≥"), (m) => (m ? pct(m.precision_pct) : "pass 없음"), pct(evaluation?.measured_precision_pct)],
    ["중요 누락", threshold(gate.thresholds.important_missed_max, count, "≤"), (m) => (m ? count(m.important_missed) : "pass 없음"), count(evaluation?.measured_important_missed)],
    ["하루 검토량", threshold(gate.thresholds.review_load_max, count, "≤"), (m) => (m ? count(m.review_load) : "pass 없음"), count(evaluation?.measured_review_load)],
  ];
  // 상세 폭(1280px에서 약 590px)에 표가 넘치지 않도록 지표와 임계값을 한 칸에 쌓는다.
  return rows.map(([label, limit, read, worst]) => [
    <span className="crit-cell-stack" key="l">
      <Text weight="semibold">{label}</Text>
      <Small>{`임계값 ${limit}`}</Small>
    </span>,
    <Text key="p1">{evaluation ? read(pass1) : "평가 없음"}</Text>,
    <Text key="p2">{evaluation ? read(pass2) : "평가 없음"}</Text>,
    <Text key="w" weight="semibold">{evaluation ? worst : "평가 없음"}</Text>,
  ]);
}

/** 4일치 일괄 채점은 참고값이다. 판정 규칙은 두 pass만 본다. */
function fullWindowText(metrics: C2QualityGatePassMetrics | null): string {
  if (!metrics) return "값 없음";
  return `재현율 ${pct(metrics.recall_pct)} · 정밀도 ${pct(metrics.precision_pct)} · 중요 누락 ${count(metrics.important_missed)} · 하루 검토량 ${count(metrics.review_load)} (활성화 판정에 쓰지 않음)`;
}

function GateResult({ gate, selectedGateId }: { gate: C2QualityGateListItem; selectedGateId: string | null }) {
  const evaluation = gate.latest_evaluation;
  const reference = gate.evaluation_basis === "reference_artifact_rescore";
  return (
    <>
      {reference ? (
        <Note role="note" title="활성화 근거 아님 · 참조 산출물 재채점" tone="warning">
          이 게이트는 제품 파이프라인을 다시 돌린 결과가 아닙니다. 수치가 통과여도 활성화를 열지 못합니다.
        </Note>
      ) : null}
      <GateSurface gate={gate} />
      <DataTable
        caption="임계값 대 측정값"
        headings={["지표 · 임계값", "pass 1", "pass 2", "나쁜 쪽"]}
        rows={metricRows(gate)}
      />
      <Facts items={[
        ["두 pass 일치율", pct(evaluation?.metrics.agreement_pct)],
        ["4일치 일괄 참고값", fullWindowText(evaluation?.metrics.reference_full_window ?? null)],
        ["게이트", <span className="crit-mono" key="g">{`${gate.gate_id}${gate.gate_id === selectedGateId ? " · 서버가 고른 게이트" : ""}`}</span>],
        ["평가 근거", reference ? "참조 산출물 재채점 (활성화 근거 아님)" : "제품 재실행"],
        ["최신 평가", evaluation ? `revision ${evaluation.revision} · ${moment(evaluation.evaluated_at)} · ${evaluation.evaluated_by}` : "없음"],
        ["평가 artifact digest", evaluation ? <code key="a">{evaluation.artifact_sha256}</code> : "없음"],
      ]} />
    </>
  );
}

// ── 화면 ──────────────────────────────────────────────────────────────

export function OrderPlanPolicyPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<ConfirmSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copyMessage, setCopyMessage] = useState("");
  const generationRef = useRef(0);
  // 같은 대상·같은 입력의 재시도는 같은 request_id로 보내 서버 replay를 받는다.
  const requestIdRef = useRef<{ bodyKey: string; id: string } | null>(null);

  const policiesQuery = useQuery({
    queryKey: ["c2-policies"],
    queryFn: ({ signal }) => api.listC2Policies({ signal }),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  const triggerQuery = useQuery({
    queryKey: ["c2-daily-trigger"],
    queryFn: ({ signal }) => api.getC2DailyTrigger({ signal }),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });

  const policies: C2PolicySummary[] = policiesQuery.data?.items ?? [];
  const selectedVersion = searchParams.get("c2policy");
  const selected = policies.find((policy) => policy.policy_version === selectedVersion) ?? policies[0] ?? null;
  const version = selected?.policy_version ?? null;

  const inspectQuery = useQuery({
    queryKey: ["c2-policy", version],
    queryFn: ({ signal }) => api.getC2Policy(version as string, { signal }),
    enabled: Boolean(version),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  const gatesQuery = useQuery({
    queryKey: ["c2-quality-gates", version],
    queryFn: ({ signal }) => api.listC2QualityGates(version as string, { signal }),
    enabled: Boolean(version),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });

  useEffect(() => {
    if (!copyMessage) return;
    const timer = window.setTimeout(() => setCopyMessage(""), 4500);
    return () => window.clearTimeout(timer);
  }, [copyMessage]);

  function selectPolicy(id: string) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("c2policy", id);
      return next;
    }, { replace: true });
    setNotice(null);
  }

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["c2-policies"] });
    void queryClient.invalidateQueries({ queryKey: ["c2-policy"] });
    void queryClient.invalidateQueries({ queryKey: ["c2-quality-gates"] });
    void queryClient.invalidateQueries({ queryKey: ["c2-daily-trigger"] });
  }

  if (policiesQuery.isPending) {
    return (
      <div className="crit-workspace" id="criteria-panel-order-plan-policies" role="tabpanel">
        <StateView description="발주계획 선별 policy 목록을 확인하는 중입니다." kind="loading" title="발주계획 선별 정책을 불러오는 중입니다" />
      </div>
    );
  }
  if (policiesQuery.error) {
    const description = describeApiError(policiesQuery.error, "policy 목록을 불러오지 못했습니다.");
    return (
      <div className="crit-workspace" id="criteria-panel-order-plan-policies" role="tabpanel">
        <StateView
          action={<Button label="다시 조회" onClick={() => { void policiesQuery.refetch(); }} />}
          description={`${description.title} ${description.detail}`}
          kind="error"
          title="발주계획 선별 정책을 불러오지 못했습니다."
        />
      </div>
    );
  }

  const trigger: C2DailyTriggerStateResponse | null = triggerQuery.data ?? null;
  const activePolicy = policies.find((policy) => policy.policy_status === "active") ?? null;
  const inspect: C2PolicyInspectResponse | null = inspectQuery.data && inspectQuery.data.policy_version === version ? inspectQuery.data : null;
  const gates: C2QualityGateListItem[] = gatesQuery.data?.items ?? [];
  const selectedGateId = inspect?.quality_gate?.gate_id ?? null;
  const shownGate = gates.find((gate) => gate.gate_id === selectedGateId) ?? gates[0] ?? null;
  const blockers = inspect?.blockers ?? [];
  const latestEvaluation = inspect?.quality_gate?.latest_evaluation ?? null;
  const canActivate = Boolean(inspect && inspect.policy_status === "activation_candidate" && inspect.activation_allowed && latestEvaluation);
  const measurementRows = gates.flatMap((gate) => gate.measurement_executions.map((execution) => ({ gate, execution })));
  const triggerForSelected = Boolean(trigger && selected && selected.policy_status === "active" && trigger.policy_version === selected.policy_version);

  function openCandidate(policy: C2PolicySummary) {
    setConfirmError(null);
    setPending({
      kind: "candidate",
      key: `candidate:${policy.policy_version}:${policy.policy_sha256}`,
      title: "활성화 후보로 지정합니다",
      facts: [
        ["대상 policy", policy.policy_version],
        ["policy digest", policy.policy_sha256],
        ["현재 운영 활성", activePolicy ? `${activePolicy.policy_version} · ${shortDigest(activePolicy.policy_sha256)}` : "없음"],
        ["바뀌는 것", "draft → activation_candidate · 운영 활성화가 아닙니다"],
      ],
      notes: [{ title: "후보 지정은 운영 활성화가 아닙니다", body: "활성화는 게이트 통과와 blocker 0건을 확인한 뒤 따로 승인합니다.", tone: "neutral" }],
      reason: { label: "후보 지정 사유 · 필수 (500자 이내)", maxLength: 500 },
      confirmLabel: "대상 policy와 digest를 확인했습니다",
      submitLabel: "후보로 지정",
    });
  }

  function openActivate(target: C2PolicyInspectResponse) {
    if (!latestEvaluation) return;
    setConfirmError(null);
    const oldSwitchOn = Boolean(
      trigger?.policy_version && trigger.policy_version !== target.policy_version && trigger.switch?.enabled === true,
    );
    const notes: ConfirmSnapshot["notes"] = [];
    if (oldSwitchOn && trigger?.policy_version) {
      notes.push({
        title: `현재 버전 ${trigger.policy_version}의 자동 실행이 꺼집니다. 활성화 뒤 이 화면에서 다시 켜세요.`,
        body: SWITCH_GUIDE,
        tone: "warning",
      });
    }
    notes.push({
      title: "이후 시작하는 실행의 policy가 바뀝니다",
      body: "기존 운영 활성 버전은 교체됨으로 내려가며 이미 기록된 판정과 사람의 결정은 바뀌지 않습니다.",
      tone: "neutral",
    });
    setPending({
      kind: "activate",
      key: `activate:${target.policy_version}:${target.policy_sha256}:${latestEvaluation.artifact_sha256}`,
      title: "발주계획 선별 policy를 운영에 활성화합니다",
      facts: [
        ["대상 policy", target.policy_version],
        ["policy digest 앞자리", shortDigest(target.policy_sha256)],
        ["게이트 평가 artifact digest", latestEvaluation.artifact_sha256],
        ["게이트 평가", `${latestEvaluation.result_status} · revision ${latestEvaluation.revision}`],
        ["현재 운영 활성", activePolicy ? activePolicy.policy_version : "없음"],
        ["바뀌는 것", "activation_candidate → active"],
      ],
      notes,
      reason: null,
      confirmLabel: "위 policy digest와 게이트 평가 digest를 확인했고 운영 활성화를 승인합니다",
      submitLabel: "활성화",
    });
  }

  function openTrigger(next: boolean) {
    if (!trigger?.policy_version) return;
    setConfirmError(null);
    setPending({
      kind: "trigger",
      key: `trigger:${trigger.policy_version}:${next ? "on" : "off"}`,
      title: next ? "일일 자동 실행을 켭니다" : "일일 자동 실행을 끕니다",
      facts: [
        ["대상 policy", trigger.policy_version],
        ["policy digest 앞자리", shortDigest(trigger.policy_sha256)],
        ["바뀌는 것", next ? "이 버전의 스위치 켬" : "이 버전의 스위치 끔"],
      ],
      notes: [{ title: SWITCH_GUIDE, body: "스위치를 켜도 환경 설정·전송 승인·파일 조건이 모두 맞아야 실제로 실행됩니다.", tone: "neutral" }],
      reason: { label: "사유 · 필수 (200자 이내)", maxLength: 200 },
      confirmLabel: next ? "이 버전의 일일 자동 실행을 켭니다" : "이 버전의 일일 자동 실행을 끕니다",
      submitLabel: next ? "자동 실행 켜기" : "자동 실행 끄기",
    });
  }

  function requestIdFor(bodyKey: string): string {
    const current = requestIdRef.current;
    if (current && current.bodyKey === bodyKey) return current.id;
    const id = generateRequestId();
    requestIdRef.current = { bodyKey, id };
    return id;
  }

  function runConfirm(snapshot: ConfirmSnapshot, input: { actor: string; reason: string; confirmed: boolean }) {
    if (busy) return;
    const generation = ++generationRef.current;
    const bodyKey = JSON.stringify([snapshot.key, input.actor, input.reason, input.confirmed]);
    let requestId: string;
    try {
      requestId = requestIdFor(bodyKey);
    } catch {
      setConfirmError(["브라우저가 안전한 요청 식별자를 만들 수 없어 요청을 보내지 않았습니다."]);
      return;
    }
    let request: Promise<unknown>;
    let done: string;
    if (snapshot.kind === "candidate" && selected) {
      request = api.designateC2PolicyCandidate({
        schema_version: "policy-candidate-request.v1",
        producer: "human-review-client",
        consumer: "policy-api",
        request_id: requestId,
        policy_version: selected.policy_version,
        base_policy_sha256: activePolicy?.policy_sha256 ?? null,
        candidate_sha256: selected.policy_sha256,
        reason: input.reason,
      }, input.actor);
      done = `${selected.policy_version}을(를) 활성화 후보로 지정했습니다.`;
    } else if (snapshot.kind === "activate" && inspect && latestEvaluation) {
      request = api.activateC2Policy(inspect.policy_version, {
        schema_version: "policy-activate-request.v1",
        producer: "human-review-client",
        consumer: "policy-api",
        request_id: requestId,
        policy_sha256: inspect.policy_sha256,
        quality_gate_artifact_sha256: latestEvaluation.artifact_sha256,
        explicit_confirmation: input.confirmed,
      }, input.actor);
      done = `${inspect.policy_version}을(를) 운영에 활성화했습니다. 일일 자동 실행은 이 버전에서 다시 켜야 합니다.`;
    } else if (snapshot.kind === "trigger" && trigger?.policy_version) {
      const enabled = snapshot.key.endsWith(":on");
      request = api.setC2DailyTrigger({
        schema_version: "daily-trigger-set-request.v1",
        producer: "human-review-client",
        consumer: "daily-trigger-api",
        request_id: requestId,
        policy_version: trigger.policy_version,
        enabled,
        reason: input.reason,
        explicit_confirmation: input.confirmed,
      }, input.actor);
      done = enabled ? "일일 자동 실행 스위치를 켰습니다." : "일일 자동 실행 스위치를 껐습니다.";
    } else {
      return;
    }
    setBusy(true);
    setConfirmError(null);
    void request
      .then(() => {
        if (generation !== generationRef.current) return;
        requestIdRef.current = null;
        setPending(null);
        setNotice(done);
        refresh();
      })
      // 실패하면 창을 닫지 않는다. 담당자가 다시 입력하지 않도록 초안을 남긴다.
      .catch((reason: unknown) => {
        if (generation !== generationRef.current) return;
        setConfirmError(mutationErrorLines(reason, "요청에 실패했습니다."));
        if (reason instanceof ApiError && reason.status > 0) refresh();
      })
      .finally(() => {
        if (generation === generationRef.current) setBusy(false);
      });
  }

  const footerNote = (() => {
    if (!selected) return "";
    if (selected.policy_status === "draft") return "초안입니다. 후보로 지정해도 운영 활성화가 아닙니다.";
    if (selected.policy_status === "retired") return "교체된 버전입니다. 다시 활성화하지 않습니다 — 새 버전을 적재합니다.";
    if (selected.policy_status === "active") return "운영 활성 버전입니다. 교체하려면 새 버전을 후보로 지정해 활성화합니다.";
    if (!inspect) return "활성화 조건을 확인하는 중입니다.";
    if (blockers.length > 0) {
      return `활성화할 수 없습니다 · ${blockerText(blockers[0])}${blockers.length > 1 ? ` 외 ${blockers.length - 1}건` : ""}`;
    }
    if (!latestEvaluation) return "활성화할 수 없습니다 · 근거가 될 게이트 평가가 없습니다.";
    return "blocker 0건 · 확인 창에서 digest를 다시 확인한 뒤 활성화합니다.";
  })();

  return (
    <div className="crit-workspace" id="criteria-panel-order-plan-policies" role="tabpanel">
      <Queue
        count={policies.length}
        emptyText="적재된 발주계획 선별 policy가 없습니다."
        footer="policy는 적재 CLI가 만듭니다 · 활성 여부의 정본은 DB 행"
        items={policies.map((policy) => ({
          id: policy.policy_version,
          title: policy.policy_version,
          subtitle: `policy ${shortDigest(policy.policy_sha256)} · binding ${shortDigest(policy.binding_sha256)}`,
          status: STATUS_LABELS[policy.policy_status],
          meta: policy.activated_at
            ? `${policy.policy_status === "active" ? "활성화" : "활성화 이력"} ${moment(policy.activated_at)} · ${policy.activated_by ?? "담당자 기록 없음"}`
            : `활성화 기록 없음 · 적재 ${moment(policy.created_at)}`,
        }))}
        onSelect={selectPolicy}
        selectedId={selected?.policy_version ?? null}
        title="발주계획 선별 policy"
      />
      <section aria-label="선택한 발주계획 선별 policy" className="crit-detail">
        {!selected ? (
          <StateView
            description="policy는 적재 CLI(`python -m app.screening.c2_policy load`)가 draft로 만듭니다. 이 화면은 승인과 스위치만 다룹니다."
            kind="empty"
            title="적재된 발주계획 선별 policy가 없습니다."
          />
        ) : (
          <>
            <DetailHeader
              eyebrow={selected.policy_status === "active" ? "발주계획 선별 정책 · 운영 활성" : "발주계획 선별 정책 · 운영 승인 전"}
              status={STATUS_LABELS[selected.policy_status]}
              title={selected.policy_version}
            >
              <Small>{`policy ${shortDigest(selected.policy_sha256)} · 적재 ${moment(selected.created_at)} · ${selected.created_by}`}</Small>
            </DetailHeader>
            <div className="crit-detail-scroll" id="criteria-order-plan-policy-detail">
              {notice ? (
                <Note action={<Button label="닫기" onClick={() => setNotice(null)} size="sm" />} role="status" title={notice} />
              ) : null}
              {copyMessage ? <Small><span role="status">{copyMessage}</span></Small> : null}

              {selected.policy_status === "active" ? (
                <Section title="일일 자동 실행">
                  {triggerQuery.isPending ? <Small>자동 실행 상태를 확인하는 중입니다.</Small> : null}
                  {triggerQuery.error ? (
                    <Note
                      action={<Button label="다시 조회" onClick={() => { void triggerQuery.refetch(); }} size="sm" />}
                      role="alert"
                      title="자동 실행 상태를 불러오지 못했습니다"
                      tone="error"
                    >
                      상태를 확인하지 못한 것이며 꺼져 있다는 뜻이 아닙니다.
                    </Note>
                  ) : null}
                  {trigger && !triggerForSelected ? (
                    <Small>서버가 말하는 현재 운영 활성 버전이 이 버전과 다릅니다. 목록을 새로 고치십시오.</Small>
                  ) : null}
                  {trigger && triggerForSelected ? (
                    <div className="opp-switch-row" data-testid="daily-trigger-row">
                      <Switch
                        description={trigger.switch ? `${trigger.switch.enabled ? "켬" : "끔"} · ${trigger.switch.set_by} · ${moment(trigger.switch.set_at)}` : "이 버전에는 아직 기록이 없습니다"}
                        isDisabled={busy}
                        label="이 버전의 일일 자동 실행 스위치"
                        onChange={(next) => openTrigger(next)}
                        value={trigger.switch?.enabled === true}
                      />
                      <div className="opp-switch-guide">
                        <span className="opp-gate-surface-head">
                          <StatusToken label={trigger.effective_enabled ? "자동 실행 켜짐" : "자동 실행 꺼짐"} />
                          <Text weight="semibold">{trigger.effective_enabled ? "다음 일일 스크립트가 이 버전으로 실행합니다" : "일일 스크립트가 실행하지 않습니다"}</Text>
                        </span>
                        {trigger.reasons.length > 0 ? (
                          <ul className="opp-list" aria-label="자동 실행이 꺼진 이유">
                            {trigger.reasons.map((reason) => <li key={reason}>{triggerReasonText(reason)}</li>)}
                          </ul>
                        ) : null}
                        <Small>{SWITCH_GUIDE}</Small>
                      </div>
                    </div>
                  ) : null}
                </Section>
              ) : null}

              {inspectQuery.isPending ? (
                <StateView description="blocker·파일·전송 승인을 확인하는 중입니다." kind="loading" title="policy 상세를 불러오는 중입니다" />
              ) : null}
              {inspectQuery.error ? (
                <StateView
                  action={<Button label="다시 조회" onClick={() => { void inspectQuery.refetch(); }} />}
                  description={`${describeApiError(inspectQuery.error, "policy 상세를 불러오지 못했습니다.").detail} 활성화 조건을 확인하지 못했으므로 활성화 단추를 열지 않습니다.`}
                  kind="error"
                  title="policy 상세를 불러오지 못했습니다."
                />
              ) : null}

              {inspect ? (
                <>
                  <Section title={selected.policy_status === "activation_candidate" ? "활성화 조건" : "현재 조건 점검"}>
                    {blockers.length > 0 ? (
                      <>
                        <Note role="note" title={`활성화를 막는 조건 ${blockers.length}건`} tone="warning">
                          하나라도 남아 있으면 활성화 단추가 열리지 않습니다. 조건은 서버가 매번 다시 계산합니다.
                        </Note>
                        <ul className="opp-list" aria-label="활성화를 막는 조건">
                          {blockers.map((blocker) => <li key={`${blocker.code}:${blocker.detail ?? ""}`}>{blockerText(blocker)}</li>)}
                        </ul>
                      </>
                    ) : (
                      <Small>서버가 계산한 런타임 blocker가 없습니다.</Small>
                    )}
                  </Section>

                  <Section title="게이트 결과">
                    {gatesQuery.isPending ? <Small>게이트 목록을 확인하는 중입니다.</Small> : null}
                    {gatesQuery.error ? (
                      <Note
                        action={<Button label="다시 조회" onClick={() => { void gatesQuery.refetch(); }} size="sm" />}
                        role="alert"
                        title="게이트 목록을 불러오지 못했습니다"
                        tone="error"
                      >
                        게이트가 없는 것이 아니라 확인하지 못한 것입니다.
                      </Note>
                    ) : null}
                    {gatesQuery.data && !shownGate ? <Small>이 버전의 품질 게이트가 없습니다. 측정 스크립트가 게이트를 만듭니다.</Small> : null}
                    {shownGate ? <GateResult gate={shownGate} selectedGateId={selectedGateId} /> : null}
                    {gates.length > 1 ? (
                      <DataTable
                        caption="이 버전의 게이트 전체"
                        headings={["게이트", "평가 근거", "최신 결과", "생성"]}
                        rows={gates.map((gate) => [
                          <code key="g">{gate.gate_id}</code>,
                          <Text key="b">{gate.evaluation_basis === "reference_artifact_rescore" ? "참조 재채점 · 활성화 근거 아님" : "제품 재실행"}</Text>,
                          <StatusToken key="r" label={gate.latest_evaluation?.result_status ?? "평가 없음"} />,
                          <Text key="c">{`${moment(gate.created_at)} · ${gate.created_by}`}</Text>,
                        ])}
                      />
                    ) : null}
                  </Section>

                  <Section title="선택한 policy">
                    <Facts items={[
                      ["policy digest", <DigestLine key="p" label="policy digest" onCopied={setCopyMessage} value={inspect.policy_sha256} />],
                      ["binding digest", <DigestLine key="b" label="binding digest" onCopied={setCopyMessage} value={inspect.binding_sha256} />],
                      ["binding 상태", inspect.binding_status ?? "값 없음"],
                      ["policy 파일", inspect.policy_file_present ? "운영 컨테이너에 있음 (digest 일치)" : "없음 또는 digest 불일치"],
                      ["binding 파일", inspect.binding_file_present ? "운영 컨테이너에 있음 (digest 일치)" : "없음 또는 digest 불일치"],
                      ["품질 게이트 상태(행)", inspect.quality_gate_status ? QUALITY_GATE_STATUS_LABELS[inspect.quality_gate_status] ?? inspect.quality_gate_status : "값 없음"],
                      ["활성화", inspect.activated_at ? `${moment(inspect.activated_at)} · ${inspect.activated_by ?? "담당자 기록 없음"}` : "기록 없음"],
                    ]} />
                  </Section>
                  <Section title="전송 승인 (binding)">
                    {inspect.external_transport ? (
                      <Facts items={[
                        ["실행 허용", yesNo(inspect.external_transport.execution_allowed, "허용", "허용 안 함")],
                        ["승인 범위", inspect.external_transport.approval_scope ?? "값 없음"],
                        ["승인자", inspect.external_transport.approved_by ?? "값 없음"],
                        ["승인 시각", inspect.external_transport.approved_at ? moment(inspect.external_transport.approved_at) : "값 없음"],
                      ]} />
                    ) : <Small>binding에 전송 승인 항목이 없습니다.</Small>}
                  </Section>
                  <Section title="감사 표본 설정 (policy)">
                    {inspect.audit_sample ? (
                      <Facts items={[
                        ["사용", yesNo(inspect.audit_sample.enabled, "사용", "사용 안 함")],
                        ["실행당 상한", count(inspect.audit_sample.max_per_execution)],
                        ["검토 주기", inspect.audit_sample.review_cadence ?? "값 없음"],
                      ]} />
                    ) : <Small>policy에 감사 표본 설정이 없습니다.</Small>}
                  </Section>
                </>
              ) : null}

              <Section title={`측정 실행 · ${measurementRows.length}건`}>
                {measurementRows.length > 0 ? (
                  <DataTable
                    caption="게이트 측정 실행 목록"
                    headings={["실행", "회차", "상태", "대기 → 종료"]}
                    rows={measurementRows.map(({ execution }) => [
                      <code key="e">{execution.execution_id}</code>,
                      <span className="crit-mono" key="r">{execution.source_run_id}</span>,
                      <StatusToken key="s" label={execution.status} />,
                      <span className="crit-cell-stack" key="t">
                        <Text>{moment(execution.queued_at)}</Text>
                        <Small>{execution.finished_at ? moment(execution.finished_at) : "끝나지 않음"}</Small>
                      </span>,
                    ])}
                  />
                ) : <Small>{gatesQuery.data ? "측정 실행이 없습니다." : "게이트를 확인한 뒤 표시합니다."}</Small>}
                <Small>읽기 전용입니다. 게이트 생성·evaluation 기록·측정 실행은 측정 스크립트가 합니다.</Small>
              </Section>
            </div>
            <DetailFooter note={footerNote}>
              {selected.policy_status === "draft" ? (
                <Button label="후보로 지정" onClick={() => openCandidate(selected)} size="sm" />
              ) : null}
              {selected.policy_status === "activation_candidate" ? (
                <Button
                  isDisabled={!canActivate || busy}
                  label="활성화"
                  onClick={() => { if (inspect) openActivate(inspect); }}
                  size="sm"
                  variant="primary"
                />
              ) : null}
              {selected.policy_status === "active" ? <StatusToken label="운영 활성" size="md" /> : null}
            </DetailFooter>
          </>
        )}
      </section>
      <ConfirmDialog
        busy={busy}
        error={confirmError}
        onClose={() => { ++generationRef.current; setBusy(false); setPending(null); setConfirmError(null); }}
        onConfirm={runConfirm}
        snapshot={pending}
      />
    </div>
  );
}
