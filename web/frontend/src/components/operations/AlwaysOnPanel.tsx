import { useEffect, useState } from "react";
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

function valueLabel(value: string | null): string {
  return value && value.trim() ? value : "값 없음";
}

export function AlwaysOnPanel({ state, activePolicy, activePolicyVersion, policyLoading, policyRefreshing, busy, onUpdate }: AlwaysOnPanelProps) {
  const [actor, setActor] = useState("");
  const [confirmedGateId, setConfirmedGateId] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (!state.quality_gate_result_id) setConfirmedGateId("");
  }, [state.quality_gate_result_id]);

  const gateId = state.quality_gate_result_id;
  const actorReady = actor.trim().length > 0;
  const metadataComplete = [
    state.quality_gate_result_id,
    state.policy_version,
    state.model_name,
    state.model_digest,
    state.prompt_version,
    state.company_profile_version,
    state.company_profile_digest,
    activePolicy?.quality_gate_result_id ?? null,
    activePolicy?.prompt_version ?? null,
    activePolicy?.content_digest ?? null,
  ].every((value) => typeof value === "string" && value.trim().length > 0);
  const policyGateMatches = Boolean(
    activePolicy?.quality_gate_result_id
      && activePolicy.quality_gate_result_id === state.quality_gate_result_id,
  );
  const policyPromptMatches = Boolean(
    activePolicy?.prompt_version
      && activePolicy.prompt_version === state.prompt_version,
  );
  const policyMatches = Boolean(
    !policyLoading
      && !policyRefreshing
      && activePolicy
      && activePolicyVersion
      && activePolicy.policy_version === activePolicyVersion
      && state.policy_version === activePolicyVersion
      && policyGateMatches
      && policyPromptMatches
      && activePolicy.content_digest.trim(),
  );
  const gateReady = Boolean(gateId) && state.quality_gate_status === "통과" && confirmedGateId.trim() === gateId;
  const hasRejection = Boolean(state.rejection_reason?.trim());
  const enableDisabled = busy || !actorReady || !state.environment_enabled || !gateReady || hasRejection || !policyMatches || !metadataComplete;
  const disableDisabled = busy || !actorReady || !state.configured_enabled;

  const update = async (enabled: boolean) => {
    if (!actorReady) {
      setValidationError("상시 운영 상태를 바꾸려면 담당자 이름을 입력하십시오.");
      return;
    }
    if (enabled && !gateReady) {
      setValidationError("최신 운영 승인 게이트의 결과 ID를 정확히 확인해야 켤 수 있습니다.");
      return;
    }
    setValidationError(null);
    const updated = await onUpdate({ enabled, confirmed_by: actor.trim(), quality_gate_result_id: enabled ? gateId : null });
    if (updated) {
      setActor("");
      if (enabled) setConfirmedGateId("");
    }
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
            <div><dt>quality gate evaluation</dt><dd className="mono">{valueLabel(state.quality_gate_result_id)}</dd></div>
            <div><dt>정책 버전 · digest</dt><dd><span className="mono">{valueLabel(state.policy_version)}</span><span className="operations-binding-digest mono">{valueLabel(policyDigest)}</span></dd></div>
            <div><dt>모델 tag · digest</dt><dd><span className="mono">{valueLabel(state.model_name)}</span><span className="operations-binding-digest mono">{valueLabel(state.model_digest)}</span></dd></div>
            <div><dt>prompt version</dt><dd className="mono">{valueLabel(state.prompt_version)}</dd></div>
            <div><dt>프로필 version · digest</dt><dd><span className="mono">{valueLabel(state.company_profile_version)}</span><span className="operations-binding-digest mono">{valueLabel(state.company_profile_digest)}</span></dd></div>
          </dl>
        </div>

        {state.rejection_reason ? <div className="operations-rejection" role="alert"><strong>상시 운영이 거부되었습니다.</strong><span>{state.rejection_reason}</span></div> : null}
        {enableDisabled ? (
          <ul className="operations-callout operations-callout-warning operations-enable-blockers" aria-label="상시 운영 켜기 차단 사유">
            {!state.environment_enabled ? <li>환경 안전 상한이 꺼져 있습니다.</li> : null}
            {hasRejection ? <li>서버가 현재 승인 조합을 거부하여 다시 확인해야 합니다.</li> : null}
            {state.quality_gate_status !== "통과" || !gateId ? <li>quality gate evaluation이 통과 상태가 아니거나 결과 ID가 없습니다.</li> : null}
            {policyRefreshing ? <li>승인 조합 확인 중입니다. 확인이 끝날 때까지 켤 수 없습니다.</li> : null}
            {policyLoading || !activePolicy ? <li>현재 active 정책을 확인할 수 없습니다.</li> : null}
            {!policyLoading && !policyRefreshing && activePolicy && !policyMatches ? <li>현재 active 정책 버전이 승인 조합의 정책 버전과 일치하지 않습니다.</li> : null}
            {!policyLoading && !policyRefreshing && activePolicy && !policyGateMatches ? <li>active 정책의 quality gate evaluation ID가 현재 승인 조합과 일치하지 않거나 없습니다.</li> : null}
            {!policyLoading && !policyRefreshing && activePolicy && !policyPromptMatches ? <li>active 정책의 prompt version이 현재 승인 조합과 일치하지 않습니다.</li> : null}
            {!metadataComplete ? <li>승인 조합의 정책·모델·prompt·프로필 메타데이터가 모두 확인되지 않았습니다.</li> : null}
            {gateId && confirmedGateId.trim() !== gateId ? <li>켜기 전에 quality gate evaluation ID를 정확히 입력하십시오.</li> : null}
          </ul>
        ) : null}

        <div className="operations-switch-actions">
          <label className="operations-actor-field"><span>변경 담당자</span><input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="담당자 이름" autoComplete="name" disabled={busy} /></label>
          <label className="operations-actor-field operations-gate-confirm"><span>켜기 확인 · 정확한 결과 ID</span><input value={confirmedGateId} onChange={(event) => setConfirmedGateId(event.target.value)} placeholder={gateId ?? "gateeval-…"} disabled={busy || !gateId} aria-describedby="operations-gate-confirm-help" /></label>
          <div className="operations-switch-buttons">
            <button className="operations-button operations-button-primary" type="button" onClick={() => void update(true)} disabled={enableDisabled}>상시 운영 켜기</button>
            <button className="operations-button operations-button-secondary" type="button" onClick={() => void update(false)} disabled={disableDisabled}>상시 운영 끄기</button>
          </div>
        </div>
        <p className="operations-help" id="operations-gate-confirm-help">켜기는 담당자와 최신 quality gate evaluation ID의 정확한 일치가 필요합니다. 끄기는 기존 실행·회차·산출물을 삭제하지 않습니다.</p>
        {validationError ? <p className="operations-inline-error" role="alert">{validationError}</p> : null}
        <p className="operations-form-meta">마지막 변경: <span className="mono">{state.updated_at}</span> · {state.updated_by || "담당자 미확인"}</p>
      </div>
    </section>
  );
}
