import { useMemo, useState } from "react";
import { ApiError, api } from "../../lib/api";
import type { PolicyActivationResponse, PolicyVersionResponse, QualityGateResponse } from "../../lib/types";

interface PolicyVersionCardProps {
  policy: PolicyVersionResponse;
  operationalGates: QualityGateResponse[];
  onChanged: () => void;
  onActivated: (response: PolicyActivationResponse) => void;
}

function safeError(error: unknown, action: string): string {
  if (!(error instanceof ApiError)) return `${action}에 실패했습니다.`;
  if (error.status === 409) return `현재 정책 또는 운영 게이트 상태가 바뀌어 ${action}할 수 없습니다. 최신 목록을 확인하십시오.`;
  if (error.status === 422) return `담당자와 ${action} 조건을 확인하십시오.`;
  return error.status > 0 ? `${action}에 실패했습니다 (${error.status}).` : `${action}에 실패했습니다.`;
}

function digest(value: string | null | undefined): string {
  return value ?? "연결 없음";
}

export function PolicyVersionCard({ policy, operationalGates, onChanged, onActivated }: PolicyVersionCardProps) {
  const [candidateActor, setCandidateActor] = useState("");
  const [activationActor, setActivationActor] = useState("");
  const [selectedResultId, setSelectedResultId] = useState("");
  const [busy, setBusy] = useState<"candidate" | "activate" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const passingGates = useMemo(() => operationalGates.filter((gate) => gate.result_status === "통과" && gate.latest_evaluation_id), [operationalGates]);
  const selectedGate = passingGates.find((gate) => gate.latest_evaluation_id === selectedResultId) ?? null;
  const canActivate = policy.status === "activation_candidate" && Boolean(selectedResultId && activationActor.trim() && selectedGate);

  function designateCandidate() {
    if (!candidateActor.trim()) {
      setError("후보 지정 담당자를 입력하십시오.");
      return;
    }
    if (!window.confirm(`${policy.policy_version}을(를) 운영 활성화 후보로 지정하시겠습니까?`)) return;
    setBusy("candidate");
    setError(null);
    void api.designatePolicyCandidate(policy.policy_version, { confirmed_by: candidateActor.trim() }, candidateActor.trim())
      .then(onChanged)
      .catch((reason: unknown) => setError(safeError(reason, "후보 지정")))
      .finally(() => setBusy(null));
  }

  function activate() {
    if (!canActivate || !selectedGate) {
      setError("통과한 최신 운영 evaluation ID와 담당자 이름이 필요합니다.");
      return;
    }
    if (selectedGate.policy_version !== policy.policy_version) {
      setError("선택한 운영 게이트의 정책 버전이 대상 정책과 다릅니다.");
      return;
    }
    if (!window.confirm(`${policy.policy_version}을(를) ${selectedResultId} 근거로 활성화하시겠습니까?`)) return;
    setBusy("activate");
    setError(null);
    void api.activatePolicy(policy.policy_version, { quality_gate_result_id: selectedResultId, confirmed_by: activationActor.trim() }, activationActor.trim())
      .then((response) => {
        onActivated(response);
        onChanged();
      })
      .catch((reason: unknown) => setError(safeError(reason, "정책 활성화")))
      .finally(() => setBusy(null));
  }

  return (
    <article className={`policy-version-card policy-status-${policy.status}`}>
      <div className="policy-version-heading">
        <div><span className="policy-status-label">{policy.status === "activation_candidate" ? "활성화 후보" : policy.status === "active" ? "운영 활성" : "초안"}</span><h3 className="mono">{policy.policy_version}</h3></div>
        <span className="policy-status-badge">{policy.status}</span>
      </div>
      <dl className="policy-version-facts">
        <div><dt>content digest</dt><dd><code>{policy.content_digest}</code></dd></div>
        <div><dt>프롬프트</dt><dd className="mono">{policy.prompt_version}</dd></div>
        <div><dt>생성자</dt><dd>{policy.created_by}</dd></div>
        <div><dt>생성 시각</dt><dd>{new Date(policy.created_at).toLocaleString("ko-KR")}</dd></div>
        <div><dt>연결 게이트 evaluation</dt><dd><code>{digest(policy.quality_gate_result_id)}</code></dd></div>
      </dl>
      <details className="policy-body-details"><summary>불변 정책 본문 보기 (편집 불가)</summary><pre>{JSON.stringify({ perspective_prompts: policy.perspective_prompts, counterargument_prompt: policy.counterargument_prompt, synthesis_prompt: policy.synthesis_prompt, candidate_selection: policy.candidate_selection, thresholds: policy.thresholds }, null, 2)}</pre></details>
      {policy.status === "draft" ? (
        <div className="policy-action-block">
          <h4>draft → activation_candidate</h4>
          <p>후보 지정은 본문을 바꾸지 않으며 담당자 확인 기록만 추가합니다.</p>
          <label>확인 담당자<input value={candidateActor} onChange={(event) => setCandidateActor(event.target.value)} placeholder="예: 홍길동" /></label>
          <button className="policy-button policy-button-secondary" type="button" onClick={designateCandidate} disabled={busy !== null || !candidateActor.trim()}>{busy === "candidate" ? "지정 중…" : "활성화 후보 지정"}</button>
        </div>
      ) : null}
      {policy.status === "activation_candidate" ? (
        <div className="policy-action-block policy-activation-block">
          <h4>운영 활성화 확인</h4>
          <p>활성화에는 통과한 최신 operational_approval evaluation ID와 담당자 확인이 필요합니다. 모델 비교용 게이트는 선택할 수 없습니다.</p>
          <label>통과한 최신 운영 evaluation<select value={selectedResultId} onChange={(event) => setSelectedResultId(event.target.value)}><option value="">게이트를 선택하십시오</option>{passingGates.map((gate) => <option value={gate.latest_evaluation_id} key={gate.latest_evaluation_id}>{gate.latest_evaluation_id} · {gate.policy_version}</option>)}</select></label>
          {selectedGate ? <div className="policy-binding" aria-label="활성화에 결합되는 입력">
            <strong>결합 입력</strong>
            <dl><div><dt>정책</dt><dd className="mono">{selectedGate.policy_version} · {policy.content_digest}</dd></div><div><dt>모델</dt><dd>{selectedGate.model_name} · <code>{selectedGate.model_digest}</code></dd></div><div><dt>프로필</dt><dd className="mono">{selectedGate.company_profile_version} · <code>{selectedGate.company_profile_digest}</code></dd></div><div><dt>프롬프트</dt><dd className="mono">{selectedGate.prompt_version}</dd></div><div><dt>게이트</dt><dd><code>{selectedGate.latest_evaluation_id}</code> · {selectedGate.result_status}</dd></div></dl>
          </div> : <p className="policy-empty-binding">통과한 최신 운영 게이트를 선택하면 모델·프로필·프롬프트 digest를 확인할 수 있습니다.</p>}
          <label>활성화 담당자<input value={activationActor} onChange={(event) => setActivationActor(event.target.value)} placeholder="예: 홍길동" /></label>
          <button className="policy-button policy-button-primary" type="button" onClick={activate} disabled={busy !== null || !canActivate}>{busy === "activate" ? "활성화 중…" : "정책 활성화 확인"}</button>
        </div>
      ) : null}
      {policy.status === "active" ? <p className="policy-active-note" role="status">현재 active 정책입니다. 본문은 불변이며 새 변경은 새 버전으로 생성하십시오.</p> : null}
      {error ? <p className="policy-form-error" role="alert">{error}</p> : null}
    </article>
  );
}
