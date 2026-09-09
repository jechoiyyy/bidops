import { useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import {
  CancelButton,
  CriteriaDialog,
  DialogActions,
  Note,
} from "../criteria/CriteriaPrimitives";
import { ApiError, api } from "../../lib/api";
import type { PolicyVersionCreateRequest, RuntimeJsonObject } from "../../lib/types";

/**
 * 새 정책 버전 생성.
 *
 * 시안은 본문을 한 칸으로 줄여 그렸지만 계약은 다섯 개의 독립 JSON object다
 * (`POST /api/policies`). 축약한 시안이 필드를 지워도 된다는 뜻이 아니므로
 * (`COMMON-TASK.md`) 다섯 칸을 그대로 두고 대화상자 안으로 옮기기만 했다.
 *
 * 생성은 **초안 추가**다. 후보 지정과 운영 활성화는 각각 별도 확인 절차다.
 */

const JSON_FIELDS = {
  perspective_prompts: "관점별 검토 프롬프트",
  counterargument_prompt: "반론 프롬프트",
  synthesis_prompt: "종합 프롬프트",
  candidate_selection: "후보 선정",
  thresholds: "임계값",
} as const;

type JsonField = keyof typeof JSON_FIELDS;

const EMPTY_JSON: Record<JsonField, string> = {
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

function parseObject(raw: string, label: string): RuntimeJsonObject {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`${label}의 JSON 문법이 올바르지 않습니다.`);
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error(`${label}은(는) JSON object여야 합니다.`);
  return parsed as RuntimeJsonObject;
}

export function PolicyCreateDialog({ open, onClose, onCreated }: {
  open: boolean;
  onClose: () => void;
  onCreated: (policyVersion: string) => void;
}) {
  const [policyVersion, setPolicyVersion] = useState("");
  const [promptVersion, setPromptVersion] = useState("");
  const [createdBy, setCreatedBy] = useState("");
  const [jsonFields, setJsonFields] = useState<Record<JsonField, string>>(EMPTY_JSON);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setPolicyVersion("");
    setPromptVersion("");
    setCreatedBy("");
    setJsonFields(EMPTY_JSON);
    setError(null);
  }

  function close() {
    if (submitting) return;
    reset();
    onClose();
  }

  function submit() {
    if (submitting) return;
    if (!policyVersion.trim() || !promptVersion.trim() || !createdBy.trim()) {
      setError("정책 버전, 프롬프트 버전, 생성 담당자를 입력하십시오.");
      return;
    }
    let parsed: Record<JsonField, RuntimeJsonObject>;
    try {
      parsed = Object.fromEntries(
        (Object.keys(JSON_FIELDS) as JsonField[]).map((field) => [field, parseObject(jsonFields[field], `${JSON_FIELDS[field]} (${field})`)]),
      ) as Record<JsonField, RuntimeJsonObject>;
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
    void api.createPolicy(payload, createdBy.trim())
      .then((created) => {
        const version = created.policy_version;
        reset();
        onCreated(version);
      })
      .catch((reason: unknown) => setError(safeError(reason)))
      .finally(() => setSubmitting(false));
  }

  return (
    <CriteriaDialog onClose={close} open={open} title="새 정책 버전" width={820}>
      <Note title="새 초안으로 저장합니다">
        저장하면 본문과 식별 해시가 고정됩니다. 바꾸려면 새 버전을 만들어야 하며, 후보 지정과 운영 활성화는 별도로 진행합니다.
      </Note>
      <div className="crit-dialog-grid">
        <TextInput label="정책 버전 · 필수" onChange={setPolicyVersion} placeholder="예: screening-policy.v1.20260907" value={policyVersion} />
        <TextInput label="프롬프트 버전 · 필수" onChange={setPromptVersion} placeholder="예: screening-prompt.v1" value={promptVersion} />
      </div>
      <div className="crit-dialog-scroll">
        <div className="crit-dialog-json">
          {(Object.keys(JSON_FIELDS) as JsonField[]).map((field) => (
            <TextArea
              description={`${field} · JSON object만 저장할 수 있습니다. 배열과 문법 오류는 저장되지 않습니다.`}
              hasSpellCheck={false}
              key={field}
              label={`${JSON_FIELDS[field]} · 필수`}
              onChange={(value) => setJsonFields((current) => ({ ...current, [field]: value }))}
              rows={4}
              value={jsonFields[field]}
            />
          ))}
        </div>
      </div>
      <TextInput label="생성 담당자 · 필수" onChange={setCreatedBy} placeholder="담당자 이름" value={createdBy} />
      {error ? <Text as="p" className="crit-error" role="alert">{error}</Text> : null}
      <DialogActions>
        <CancelButton onClick={close} />
        <Button
          isDisabled={submitting || !policyVersion.trim() || !promptVersion.trim() || !createdBy.trim()}
          label={submitting ? "저장 중…" : "새 불변 버전 저장"}
          onClick={submit}
          size="sm"
          variant="primary"
        />
      </DialogActions>
    </CriteriaDialog>
  );
}
