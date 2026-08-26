import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../lib/api";
import type { PolicyVersionListResponse, ProfileSource, QualityGatePurpose } from "../../lib/types";

interface QualityGateCreateFormProps {
  policies: PolicyVersionListResponse | undefined;
  onCreated: () => void;
}

function safeError(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 409) return "현재 상태가 변경되어 게이트를 만들 수 없습니다. 최신 목록을 다시 확인하십시오.";
  if (error.status === 422) return "게이트 목적, 정책, 프로필 조합을 확인하십시오.";
  if (error.status === 503) return "모델 확인을 완료하지 못했습니다. 잠시 후 다시 시도하십시오.";
  return error.status > 0 ? `게이트 생성에 실패했습니다 (${error.status}).` : "게이트 생성에 실패했습니다.";
}

export function QualityGateCreateForm({ policies, onCreated }: QualityGateCreateFormProps) {
  const [purpose, setPurpose] = useState<QualityGatePurpose>("operational_approval");
  const [policyVersion, setPolicyVersion] = useState("");
  const [createdBy, setCreatedBy] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const availablePolicies = policies?.items.filter((policy) => policy.status !== "draft") ?? [];
  const profileSource: ProfileSource = purpose === "model_comparison"
    ? "git:ee621835db934ddac944f7a07a986ed0b73ecc7a"
    : "current";

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!policyVersion || !createdBy.trim()) {
      setError("정책과 담당자 이름을 입력하십시오.");
      return;
    }
    setSubmitting(true);
    setError(null);
    void api.createQualityGate({
      purpose,
      policy_version: policyVersion,
      profile_source: profileSource,
      created_by: createdBy.trim(),
    }).then(() => {
      setCreatedBy("");
      onCreated();
    }).catch((reason: unknown) => setError(safeError(reason, "게이트 생성에 실패했습니다.")))
      .finally(() => setSubmitting(false));
  }

  return (
    <section className="quality-panel quality-create-panel" aria-labelledby="quality-create-heading">
      <div className="quality-panel-heading">
        <div>
          <span className="quality-eyebrow">새 검증 실행</span>
          <h2 id="quality-create-heading">품질 게이트 만들기</h2>
        </div>
        <span className="quality-readonly-note">고정 표본 40건 · A/B 독립 실행</span>
      </div>
      <form className="quality-form" onSubmit={submit}>
        <div className="quality-form-grid">
          <label>
            목적
            <select value={purpose} onChange={(event) => setPurpose(event.target.value as QualityGatePurpose)}>
              <option value="operational_approval">운영 승인용</option>
              <option value="model_comparison">모델 비교용</option>
            </select>
          </label>
          <label>
            정책 버전
            <select required value={policyVersion} onChange={(event) => setPolicyVersion(event.target.value)}>
              <option value="">정책을 선택하십시오</option>
              {availablePolicies.map((policy) => <option value={policy.policy_version} key={policy.policy_version}>{policy.policy_version} · {policy.status}</option>)}
            </select>
          </label>
          <label>
            회사 프로필 출처
            <input value={profileSource} readOnly aria-describedby="quality-profile-source-help" />
            <span className="quality-help" id="quality-profile-source-help">목적에 맞는 프로필만 허용됩니다.</span>
          </label>
          <label>
            담당자
            <input required minLength={1} maxLength={128} value={createdBy} onChange={(event) => setCreatedBy(event.target.value)} placeholder="예: 홍길동" />
          </label>
        </div>
        <div className={`quality-purpose-callout quality-purpose-${purpose}`}>
          {purpose === "model_comparison" ? (
            <><strong>모델 비교용</strong><span>역사 프로필로 재현성을 비교합니다.</span><span>운영 활성화에 사용할 수 없음</span></>
          ) : (
            <><strong>운영 승인용</strong><span>최신 current 프로필을 사용하며, 통과한 최신 evaluation만 정책 활성화에 연결할 수 있습니다.</span></>
          )}
        </div>
        {error ? <p className="quality-form-error" role="alert">{error}</p> : null}
        <button className="quality-button quality-button-primary" type="submit" disabled={submitting || !policyVersion || !createdBy.trim()}>
          {submitting ? "생성 중…" : "게이트 생성"}
        </button>
      </form>
    </section>
  );
}
