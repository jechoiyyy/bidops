import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../ui/alert-dialog";
import type { AlwaysOnSwitchResponse, PolicyVersionResponse } from "../../lib/types";

interface AlwaysOnPanelProps {
  state: AlwaysOnSwitchResponse;
  activePolicy: PolicyVersionResponse | null;
  activePolicyVersion: string | null;
  policyLoading: boolean;
  policyRefreshing: boolean;
  busy: boolean;
  onUpdate: (payload: { enabled: boolean; confirmed_by: string; quality_gate_result_id: string | null }) => Promise<boolean>;
}

function enabledLabel(value: boolean): string {
  return value ? "켜짐" : "꺼짐";
}

function valueLabel(value: string | null | undefined): string {
  return value && value.trim() ? value : "값 없음";
}

function isPresent(value: string | null | undefined): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function compactDigest(value: string): string {
  if (value.length <= 30) return value;
  return `${value.slice(0, 14)}…${value.slice(-12)}`;
}

function compactIdentifier(value: string | null | undefined): string {
  const normalized = value?.trim();
  if (!normalized) return "값 없음";
  if (normalized.length <= 34) return normalized;
  return `${normalized.slice(0, 16)}…${normalized.slice(-12)}`;
}

function DigestValue({ value, className = "" }: { value: string | null | undefined; className?: string }) {
  const normalized = value?.trim() ?? "";
  return (
    <span
      aria-label={normalized ? `전체 digest ${normalized}` : "digest 값 없음"}
      className={`operations-digest-value mono ${className}`.trim()}
      title={normalized || undefined}
    >
      {normalized ? compactDigest(normalized) : "값 없음"}
    </span>
  );
}

type BindingMatch = "match" | "mismatch" | "unknown";

function bindingMatchLabel(status: BindingMatch): string {
  if (status === "match") return "active와 일치";
  if (status === "mismatch") return "active와 다름";
  return "비교 원본 없음";
}

function BindingStatus({ status, label }: { status: BindingMatch; label?: string }) {
  return <span className={`operations-dialog-status is-${status}`}>{label ?? bindingMatchLabel(status)}</span>;
}

interface StructuralBlocker {
  key: string;
  message: string;
  detail?: string;
  href?: string;
  linkLabel?: string;
}

export function AlwaysOnPanel({ state, activePolicy, activePolicyVersion, policyLoading, policyRefreshing, busy, onUpdate }: AlwaysOnPanelProps) {
  const [disableActor, setDisableActor] = useState("");
  const [enableActor, setEnableActor] = useState("");
  const [enableConfirmedGateId, setEnableConfirmedGateId] = useState("");
  const [enableDialogOpen, setEnableDialogOpen] = useState(false);
  const [enableDialogBusy, setEnableDialogBusy] = useState(false);
  const [enableDialogError, setEnableDialogError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (!state.quality_gate_result_id) setEnableConfirmedGateId("");
  }, [state.quality_gate_result_id]);

  const gateId = state.quality_gate_result_id;
  const disableActorReady = disableActor.trim().length > 0;
  const enableActorReady = enableActor.trim().length > 0;
  const enableGateConfirmed = Boolean(gateId) && enableConfirmedGateId.trim() === gateId;

  const metadataFields: Array<readonly [string | null | undefined, string]> = [
    [state.quality_gate_result_id, "quality gate evaluation"],
    [state.policy_version, "정책 버전"],
    [state.model_name, "모델 tag"],
    [state.model_digest, "모델 digest"],
    [state.prompt_version, "prompt version"],
    [state.company_profile_version, "프로필 version"],
    [state.company_profile_digest, "프로필 digest"],
    [activePolicy?.quality_gate_result_id ?? null, "active 정책의 게이트 연결"],
    [activePolicy?.prompt_version ?? null, "active 정책의 prompt version"],
    [activePolicy?.content_digest ?? null, "active 정책 digest"],
  ];
  const missingMetadata = metadataFields.filter(([value]) => !isPresent(value)).map(([, label]) => label);
  const metadataComplete = missingMetadata.length === 0;

  const policyVersionStatus: BindingMatch = activePolicy && isPresent(activePolicyVersion) && isPresent(state.policy_version)
    ? activePolicy.policy_version === activePolicyVersion && state.policy_version === activePolicyVersion ? "match" : "mismatch"
    : "unknown";
  const policyGateStatus: BindingMatch = activePolicy && isPresent(activePolicy.quality_gate_result_id) && isPresent(gateId)
    ? activePolicy.quality_gate_result_id === gateId ? "match" : "mismatch"
    : "unknown";
  const policyPromptStatus: BindingMatch = activePolicy && isPresent(activePolicy.prompt_version) && isPresent(state.prompt_version)
    ? activePolicy.prompt_version === state.prompt_version ? "match" : "mismatch"
    : "unknown";
  const policyMatches = Boolean(
    !policyLoading
      && !policyRefreshing
      && policyVersionStatus === "match"
      && policyGateStatus === "match"
      && policyPromptStatus === "match"
      && isPresent(activePolicy?.content_digest),
  );
  const hasRejection = isPresent(state.rejection_reason);

  // These blockers require a different screen or an operator/configuration fix.
  // The two values entered in the confirmation dialog are intentionally not here.
  const structuralBlockers: StructuralBlocker[] = [];
  if (!state.environment_enabled) {
    structuralBlockers.push({
      key: "environment",
      message: "환경 안전 상한이 꺼져 있습니다.",
      detail: "BIDOPS_SCHEDULER_ENABLED 설정을 확인하십시오.",
    });
  }
  if (hasRejection) {
    structuralBlockers.push({
      key: "rejection",
      message: "서버가 현재 승인 조합을 거부했습니다.",
      detail: state.rejection_reason ?? undefined,
      href: "/quality-gates",
      linkLabel: "게이트 확인",
    });
  }
  if (state.quality_gate_status !== "통과" || !gateId) {
    structuralBlockers.push({
      key: "quality-gate",
      message: "운영 승인 quality gate가 통과 상태가 아니거나 결과 ID가 없습니다.",
      detail: `현재 상태 ${valueLabel(state.quality_gate_status)} · 결과 ID ${valueLabel(gateId)}`,
      href: "/quality-gates",
      linkLabel: "quality gate 열기",
    });
  }
  if (policyLoading || policyRefreshing) {
    structuralBlockers.push({
      key: "policy-loading",
      message: "현재 active 정책을 확인하는 중입니다.",
      detail: "확인이 끝날 때까지 승인 조합을 변경할 수 없습니다.",
      href: "/policies",
      linkLabel: "정책 확인",
    });
  } else if (!activePolicy) {
    structuralBlockers.push({
      key: "active-policy",
      message: "현재 active 정책을 확인할 수 없습니다.",
      href: "/policies",
      linkLabel: "정책 확인",
    });
  } else {
    if (policyVersionStatus !== "match") {
      structuralBlockers.push({
        key: "policy-version",
        message: "active 정책 버전과 승인 조합의 정책 버전이 다릅니다.",
        detail: `active ${valueLabel(activePolicyVersion)} · 승인 조합 ${valueLabel(state.policy_version)}`,
        href: "/policies",
        linkLabel: "정책 열기",
      });
    }
    if (policyGateStatus !== "match") {
      structuralBlockers.push({
        key: "policy-gate",
        message: "active 정책의 quality gate evaluation ID가 승인 조합과 다릅니다.",
        detail: `active ${valueLabel(activePolicy.quality_gate_result_id)} · 승인 조합 ${valueLabel(gateId)}`,
        href: "/quality-gates",
        linkLabel: "게이트 확인",
      });
    }
    if (policyPromptStatus !== "match") {
      structuralBlockers.push({
        key: "policy-prompt",
        message: "active 정책의 prompt version이 승인 조합과 다릅니다.",
        detail: `active ${valueLabel(activePolicy.prompt_version)} · 승인 조합 ${valueLabel(state.prompt_version)}`,
        href: "/policies",
        linkLabel: "정책 열기",
      });
    }
    if (!isPresent(activePolicy.content_digest)) {
      structuralBlockers.push({
        key: "policy-digest",
        message: "active 정책 digest가 없습니다.",
        href: "/policies",
        linkLabel: "정책 열기",
      });
    }
    if (!metadataComplete) {
      structuralBlockers.push({
        key: "metadata",
        message: "승인 조합 메타데이터가 모두 확인되지 않았습니다.",
        detail: `확인 필요: ${missingMetadata.join(" · ")}`,
        href: "/quality-gates",
        linkLabel: "승인 조합 확인",
      });
    }
  }

  // Keep the aggregate check as a guard if the binding rules evolve without a
  // corresponding dedicated message above.
  const hasPolicyBindingBlocker = structuralBlockers.some(({ key }) =>
    ["policy-loading", "active-policy", "policy-version", "policy-gate", "policy-prompt", "policy-digest", "metadata"].includes(key),
  );
  if (!policyMatches && !hasPolicyBindingBlocker) {
    structuralBlockers.push({
      key: "policy-binding",
      message: "active 정책과 승인 조합의 연결 상태를 확인할 수 없습니다.",
      href: "/policies",
      linkLabel: "정책 확인",
    });
  }

  const disableDisabled = busy || !disableActorReady || !state.configured_enabled;
  const canShowEnable = policyMatches && structuralBlockers.length === 0;

  const update = async (enabled: boolean) => {
    if (enabled) {
      if (structuralBlockers.length > 0) {
        setEnableDialogError("구조적 차단 조건을 먼저 해결해야 합니다.");
        return;
      }
      if (!enableActorReady) {
        setEnableDialogError("상시 운영을 켜려면 담당자 이름을 입력하십시오.");
        return;
      }
      if (!enableGateConfirmed) {
        setEnableDialogError("최신 운영 승인 게이트의 결과 ID를 정확히 확인하십시오.");
        return;
      }
      setEnableDialogError(null);
      setEnableDialogBusy(true);
      try {
        const updated = await onUpdate({ enabled: true, confirmed_by: enableActor.trim(), quality_gate_result_id: gateId });
        if (updated) {
          setEnableActor("");
          setEnableConfirmedGateId("");
          setEnableDialogOpen(false);
        } else {
          setEnableDialogError("상시 운영을 켜지 못했습니다. 화면 상단의 오류 내용을 확인하십시오.");
        }
      } catch {
        setEnableDialogError("상시 운영을 켜지 못했습니다. 잠시 후 다시 시도하십시오.");
      } finally {
        setEnableDialogBusy(false);
      }
      return;
    }

    if (!disableActorReady) {
      setValidationError("상시 운영을 끄려면 담당자 이름을 입력하십시오.");
      return;
    }
    setValidationError(null);
    try {
      const updated = await onUpdate({ enabled: false, confirmed_by: disableActor.trim(), quality_gate_result_id: null });
      if (updated) setDisableActor("");
    } catch {
      setValidationError("상시 운영을 끄지 못했습니다. 잠시 후 다시 시도하십시오.");
    }
  };

  const handleEnableDialogOpenChange = (open: boolean) => {
    if (!open && enableDialogBusy) return;
    setEnableDialogOpen(open);
    if (open) {
      setValidationError(null);
      setEnableDialogError(null);
      return;
    }
    setEnableDialogError(null);
    setEnableActor("");
    setEnableConfirmedGateId("");
  };

  const policyDigest = activePolicy?.content_digest ?? null;
  return (
    <section className="operations-panel operations-always-on" aria-labelledby="operations-always-on-title">
      <div className="operations-panel-heading">
        <div><span className="operations-eyebrow">승인형 자동화</span><h3 id="operations-always-on-title">상시 운영</h3></div>
        <span className={`operations-toggle-state ${state.effective_enabled ? "is-on" : "is-off"}`} role="status" aria-live="polite">
          <span className="operations-status-dot" aria-hidden="true" />효과 상태 {enabledLabel(state.effective_enabled)}
        </span>
      </div>
      <div className="operations-panel-body">
        <div className="operations-switch-grid" aria-label="상시 운영 상태">
          <div><span>설정 상태</span><strong>{enabledLabel(state.configured_enabled)}</strong><small>담당자가 저장한 DB 스위치</small></div>
          <div><span>효과 상태</span><strong>{enabledLabel(state.effective_enabled)}</strong><small>환경·게이트·버전 일치 후에만 실행</small></div>
          <div><span>환경 허용</span><strong>{enabledLabel(state.environment_enabled)}</strong><small>BIDOPS_SCHEDULER_ENABLED</small></div>
        </div>

        <div className="operations-approval-binding" aria-labelledby="operations-binding-title">
          <div className="operations-subheading"><h4 id="operations-binding-title">현재 승인 조합</h4><span className="operations-binding-status">게이트 {valueLabel(state.quality_gate_status)}</span></div>
          <dl className="operations-binding-list">
            <div><dt>quality gate evaluation</dt><dd className="mono" title={gateId ?? undefined}>{compactIdentifier(gateId)}</dd></div>
            <div><dt>정책 버전 · digest</dt><dd><span className="mono">{valueLabel(state.policy_version)}</span><DigestValue value={policyDigest} className="operations-binding-digest" /></dd></div>
            <div><dt>모델 tag · digest</dt><dd><span className="mono">{valueLabel(state.model_name)}</span><DigestValue value={state.model_digest} className="operations-binding-digest" /></dd></div>
            <div><dt>prompt version</dt><dd className="mono">{valueLabel(state.prompt_version)}</dd></div>
            <div><dt>프로필 version · digest</dt><dd><span className="mono">{valueLabel(state.company_profile_version)}</span><DigestValue value={state.company_profile_digest} className="operations-binding-digest" /></dd></div>
          </dl>
        </div>

        {hasRejection ? <div className="operations-rejection" role="alert"><strong>상시 운영이 거부되었습니다.</strong><span>{state.rejection_reason}</span></div> : null}
        {structuralBlockers.length > 0 ? (
          <div className="operations-callout operations-callout-warning operations-enable-blockers" role="alert" aria-label="상시 운영 켜기 차단 사유">
            <strong>켤 수 없는 상태입니다 · 조건 {structuralBlockers.length}건 미충족</strong>
            <ul>
              {structuralBlockers.map((blocker) => (
                <li key={blocker.key}>
                  <div className="operations-enable-blocker-copy"><span>{blocker.message}</span>{blocker.detail ? <small>{blocker.detail}</small> : null}</div>
                  {blocker.href ? <Link className="operations-blocker-link" to={blocker.href}>{blocker.linkLabel ?? "확인하기"}</Link> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="operations-switch-actions">
          <div className="operations-enable-control">
            {canShowEnable ? (
              <>
                <span className="operations-enable-control-label">모든 구조 조건이 확인되었습니다.</span>
                <AlertDialog open={enableDialogOpen} onOpenChange={handleEnableDialogOpenChange}>
                  <AlertDialogTrigger asChild>
                    <button className="operations-button operations-button-primary" type="button" disabled={busy} aria-haspopup="dialog">상시 운영 켜기</button>
                  </AlertDialogTrigger>
                  <AlertDialogContent className="operations-alert-dialog" aria-describedby="operations-enable-dialog-description">
                    <AlertDialogHeader className="operations-alert-dialog-header">
                      <span className="operations-dialog-kicker">승인 경계 · 최종 확인</span>
                      <AlertDialogTitle>상시 운영을 켭니다</AlertDialogTitle>
                      <AlertDialogDescription id="operations-enable-dialog-description">
                        기존 회차와 산출물은 바뀌지 않지만, 이후 새 회차가 담당자 확인 없이 자동으로 생성됩니다. 아래 승인 조합과 담당자 기록을 확인한 뒤 켜십시오.
                      </AlertDialogDescription>
                    </AlertDialogHeader>

                    <div className="operations-dialog-binding" aria-label="상시 운영 승인 조합 요약">
                      <div className="operations-dialog-binding-row">
                        <span>정책 버전</span>
                        <div><span className="mono">{valueLabel(state.policy_version)}</span><BindingStatus status={policyVersionStatus} /><small>active {valueLabel(activePolicyVersion)}</small></div>
                      </div>
                      <div className="operations-dialog-binding-row">
                        <span>정책 digest</span>
                        <div><DigestValue value={policyDigest} className="operations-dialog-digest" /><BindingStatus status="unknown" label={isPresent(policyDigest) ? "active 정책 기준값" : "값 없음"} /></div>
                      </div>
                      <div className="operations-dialog-binding-row">
                        <span>게이트 결과 ID</span>
                        <div><span className="mono" title={gateId ?? undefined}>{compactIdentifier(gateId)}</span><BindingStatus status={policyGateStatus} /><small>현재 상태 {valueLabel(state.quality_gate_status)}</small></div>
                      </div>
                      <div className="operations-dialog-binding-row">
                        <span>모델 · digest</span>
                        <div><span className="mono">{valueLabel(state.model_name)}</span><DigestValue value={state.model_digest} className="operations-dialog-digest" /><BindingStatus status="unknown" /></div>
                      </div>
                      <div className="operations-dialog-binding-row">
                        <span>prompt version</span>
                        <div><span className="mono">{valueLabel(state.prompt_version)}</span><BindingStatus status={policyPromptStatus} /></div>
                      </div>
                      <div className="operations-dialog-binding-row">
                        <span>프로필 · digest</span>
                        <div><span className="mono">{valueLabel(state.company_profile_version)}</span><DigestValue value={state.company_profile_digest} className="operations-dialog-digest" /><BindingStatus status="unknown" /></div>
                      </div>
                    </div>

                    <div className="operations-dialog-fields">
                      <label className="operations-dialog-field" htmlFor="operations-enable-actor">
                        <span>변경 담당자</span>
                        <input id="operations-enable-actor" value={enableActor} onChange={(event) => setEnableActor(event.target.value)} placeholder="담당자 이름" autoComplete="name" disabled={enableDialogBusy || busy} aria-describedby="operations-enable-actor-help" />
                        <small id="operations-enable-actor-help">운영 변경 기록에 남는 담당자 이름입니다.</small>
                      </label>
                      <label className="operations-dialog-field" htmlFor="operations-enable-gate-id">
                        <span>게이트 결과 ID 확인</span>
                        <input id="operations-enable-gate-id" value={enableConfirmedGateId} onChange={(event) => setEnableConfirmedGateId(event.target.value)} placeholder={gateId ?? "gateeval-…"} disabled={enableDialogBusy || busy || !gateId} aria-describedby="operations-enable-gate-id-help" />
                        <small id="operations-enable-gate-id-help">위 요약의 ID와 정확히 일치해야 합니다.</small>
                      </label>
                    </div>
                    {enableDialogError ? <p className="operations-dialog-error" role="alert">{enableDialogError}</p> : null}
                    <AlertDialogFooter className="operations-alert-dialog-footer">
                      <AlertDialogCancel className="operations-dialog-cancel" disabled={enableDialogBusy || busy}>취소</AlertDialogCancel>
                      <AlertDialogAction
                        className="operations-dialog-confirm"
                        disabled={!enableActorReady || !enableGateConfirmed || enableDialogBusy || busy}
                        onClick={(event) => {
                          event.preventDefault();
                          void update(true);
                        }}
                      >
                        {enableDialogBusy ? "켜는 중…" : "상시 운영 켜기"}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </>
            ) : (
              <span className="operations-enable-control-label">차단 사유를 해결하면 켜기 버튼이 나타납니다.</span>
            )}
          </div>
          <label className="operations-actor-field"><span>끄기 담당자</span><input value={disableActor} onChange={(event) => setDisableActor(event.target.value)} placeholder="담당자 이름" autoComplete="name" disabled={busy || !state.configured_enabled} aria-describedby="operations-disable-help" /></label>
          <div className="operations-switch-buttons">
            <button className="operations-button operations-button-secondary" type="button" onClick={() => void update(false)} disabled={disableDisabled}>상시 운영 끄기</button>
          </div>
        </div>
        <p className="operations-help" id="operations-disable-help">켜기는 승인 조합 확인 대화상자에서 담당자와 quality gate evaluation ID를 확인합니다. 끄기는 기존 실행·회차·산출물을 삭제하지 않습니다.</p>
        {validationError ? <p className="operations-inline-error" role="alert">{validationError}</p> : null}
        <p className="operations-form-meta">마지막 변경: <span className="mono">{state.updated_at}</span> · {state.updated_by || "담당자 미확인"}</p>
      </div>
    </section>
  );
}
