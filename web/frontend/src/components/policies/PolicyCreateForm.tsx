import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../lib/api";
import type { PolicyVersionCreateRequest, RuntimeJsonObject } from "../../lib/types";

interface PolicyCreateFormProps {
  onCreated: () => void;
}

const initialJson: Record<keyof Omit<PolicyVersionCreateRequest, "policy_version" | "created_by" | "prompt_version">, string> = {
  perspective_prompts: "{}",
  counterargument_prompt: "{}",
  synthesis_prompt: "{}",
  candidate_selection: "{}",
  thresholds: "{}",
};

function safeError(error: unknown): string {
  if (!(error instanceof ApiError)) return "새 정책 버전을 만들지 못했습니다.";
  if (error.status === 409) return "같은 정책 버전이 이미 있거나 상태가 충돌했습니다. 새 버전명을 사용하십시오.";
  if (error.status === 422) return "정책 본문과 필수 필드를 확인하십시오.";
  return error.status > 0 ? `정책 생성에 실패했습니다 (${error.status}).` : "정책 생성에 실패했습니다.";
}

function parseObject(raw: string, fieldLabel: string): RuntimeJsonObject {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`${fieldLabel}의 JSON 문법이 올바르지 않습니다.`);
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error(`${fieldLabel}은 JSON object여야 합니다.`);
  return parsed as RuntimeJsonObject;
}

export function PolicyCreateForm({ onCreated }: PolicyCreateFormProps) {
  const [policyVersion, setPolicyVersion] = useState("");
  const [promptVersion, setPromptVersion] = useState("");
  const [createdBy, setCreatedBy] = useState("");
  const [jsonFields, setJsonFields] = useState(initialJson);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateJsonField(field: keyof typeof jsonFields, value: string) {
    setJsonFields((current) => ({ ...current, [field]: value }));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!policyVersion.trim() || !promptVersion.trim() || !createdBy.trim()) {
      setError("정책 버전, 프롬프트 버전, 생성자를 입력하십시오.");
      return;
    }
    let parsed: Record<keyof typeof jsonFields, RuntimeJsonObject>;
    try {
      parsed = Object.fromEntries(Object.entries(jsonFields).map(([key, value]) => [key, parseObject(value, key)])) as Record<keyof typeof jsonFields, RuntimeJsonObject>;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "JSON을 검증하지 못했습니다.");
      return;
    }
    const payload: PolicyVersionCreateRequest = {
      policy_version: policyVersion.trim(),
      created_by: createdBy.trim(),
      prompt_version: promptVersion.trim(),
      ...parsed,
    };
    setSubmitting(true);
    setError(null);
    void api.createPolicy(payload, createdBy.trim()).then(() => {
      setPolicyVersion("");
      setPromptVersion("");
      setCreatedBy("");
      setJsonFields(initialJson);
      onCreated();
    }).catch((reason: unknown) => setError(safeError(reason)))
      .finally(() => setSubmitting(false));
  }

  return (
    <section className="policy-panel policy-create-panel" aria-labelledby="policy-create-heading">
      <div className="policy-panel-heading"><div><span className="policy-eyebrow">불변 저장</span><h2 id="policy-create-heading">새 정책 버전 생성</h2></div><span className="policy-readonly-note">기존 본문은 편집할 수 없음</span></div>
      <p className="policy-form-intro">정책은 저장하면 본문 식별 해시가 고정됩니다. 바꾸려면 새 버전으로 다시 만드십시오.</p>
      <form className="policy-form" onSubmit={submit}>
        <div className="policy-form-grid">
          <label>정책 버전<input required value={policyVersion} onChange={(event) => setPolicyVersion(event.target.value)} placeholder="예: screening-policy.v1.20260826" /></label>
          <label>프롬프트 버전<input required value={promptVersion} onChange={(event) => setPromptVersion(event.target.value)} placeholder="예: screening-prompt.v1" /></label>
          <label>생성자<input required minLength={1} maxLength={128} value={createdBy} onChange={(event) => setCreatedBy(event.target.value)} placeholder="예: 홍길동" /></label>
        </div>
        <div className="policy-json-grid">
          {(Object.keys(initialJson) as Array<keyof typeof jsonFields>).map((field) => <label key={field}><span>{field} <em>JSON object</em></span><textarea required rows={5} spellCheck={false} value={jsonFields[field]} onChange={(event) => updateJsonField(field, event.target.value)} aria-describedby={`${field}-help`} /><small id={`${field}-help`}>문법 오류나 배열은 저장할 수 없습니다.</small></label>)}
        </div>
        {error ? <p className="policy-form-error" role="alert">{error}</p> : null}
        <button className="policy-button policy-button-primary" type="submit" disabled={submitting}>{submitting ? "저장 중…" : "새 불변 버전 저장"}</button>
      </form>
    </section>
  );
}
