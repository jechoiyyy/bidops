import { useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import {
  CancelButton,
  CriteriaDialog,
  DialogActions,
  Facts,
  Note,
} from "../criteria/CriteriaPrimitives";
import { ApiError, api } from "../../lib/api";
import type { PolicyVersionListResponse, ProfileSource, QualityGatePurpose } from "../../lib/types";

/**
 * 새 품질 게이트 생성.
 *
 * 생성 조건은 계약 그대로다: 목적, 정책 버전, 목적에 맞는 프로필 출처, 담당자.
 * 프로필 출처는 목적이 정하며 화면이 고르게 하지 않는다 — 모델 비교는 고정된 역사
 * 프로필로 재현성을 보고, 운영 승인은 현재 프로필을 쓴다.
 *
 * 생성은 A/B 두 검증 실행을 시작한다. 통과 여부는 서버의 결정적 계산 결과이며
 * 이 창이 만들지 않는다.
 */

const COMPARISON_PROFILE_SOURCE: ProfileSource = "git:ee621835db934ddac944f7a07a986ed0b73ecc7a";

function safeError(error: unknown): string {
  if (!(error instanceof ApiError)) return "게이트 생성에 실패했습니다.";
  if (error.status === 409) return "현재 상태가 변경되어 게이트를 만들 수 없습니다. 최신 목록을 다시 확인하십시오.";
  if (error.status === 422) return "게이트 목적, 정책, 프로필 조합을 확인하십시오.";
  if (error.status === 503) return "모델 확인을 완료하지 못했습니다. 잠시 후 다시 시도하십시오.";
  return error.status > 0 ? `게이트 생성에 실패했습니다 (${error.status}).` : "게이트 생성에 실패했습니다.";
}

export function QualityGateCreateDialog({ open, policies, onClose, onCreated }: {
  open: boolean;
  policies: PolicyVersionListResponse | undefined;
  onClose: () => void;
  onCreated: (gateId: string) => void;
}) {
  const [purpose, setPurpose] = useState<QualityGatePurpose>("operational_approval");
  const [policyVersion, setPolicyVersion] = useState("");
  const [createdBy, setCreatedBy] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // draft 정책으로는 검증을 시작하지 않는다.
  const availablePolicies = policies?.items.filter((policy) => policy.status !== "draft") ?? [];
  const profileSource: ProfileSource = purpose === "model_comparison" ? COMPARISON_PROFILE_SOURCE : "current";

  function close() {
    if (submitting) return;
    setError(null);
    onClose();
  }

  function submit() {
    if (submitting) return;
    if (!policyVersion || !createdBy.trim()) {
      setError("정책과 담당자 이름을 입력하십시오.");
      return;
    }
    setSubmitting(true);
    setError(null);
    void api.createQualityGate({ purpose, policy_version: policyVersion, profile_source: profileSource, created_by: createdBy.trim() })
      .then((created) => {
        setCreatedBy("");
        setPolicyVersion("");
        onCreated(created.gate_id);
      })
      .catch((reason: unknown) => setError(safeError(reason)))
      .finally(() => setSubmitting(false));
  }

  return (
    <CriteriaDialog onClose={close} open={open} title="새 품질 게이트">
      <Selector
        label="검증 목적 · 필수"
        onChange={(value) => setPurpose(value as QualityGatePurpose)}
        options={[
          { value: "operational_approval", label: "운영 승인", description: "고정 입력과 사람 리뷰로 승인 검증 · current 프로필" },
          { value: "model_comparison", label: "모델 비교", description: "운영 활성화 근거로 사용할 수 없음 · 고정된 역사 프로필" },
        ]}
        value={purpose}
      />
      <Selector
        label="정책 버전 · 필수"
        onChange={setPolicyVersion}
        options={availablePolicies.map((policy) => ({
          value: policy.policy_version,
          label: policy.policy_version,
          description: `${policy.status} · 프롬프트 ${policy.prompt_version}`,
        }))}
        placeholder={availablePolicies.length > 0 ? "정책을 선택하십시오" : "초안이 아닌 정책이 없습니다"}
        value={policyVersion}
      />
      <Facts items={[
        ["회사 프로필 출처", <span className="crit-mono" key="p">{profileSource}</span>],
        ["표본", "동결된 고정 표본 40건"],
        ["실행", "A/B 두 실행이 같은 고정 입력으로 시작"],
      ]} />
      <Note
        title={purpose === "model_comparison" ? "모델 비교용 결과는 운영 활성화에 사용할 수 없습니다" : "운영 승인용 게이트를 만듭니다"}
        tone={purpose === "model_comparison" ? "warning" : "neutral"}
      >
        {purpose === "model_comparison"
          ? "수치가 통과해도 정책 활성화와 상시 운영 승인의 근거가 되지 않습니다."
          : "통과한 최신 evaluation만 정책 활성화에 연결할 수 있습니다. 생성만으로 통과가 되지는 않습니다."}
      </Note>
      <TextInput label="생성 담당자 · 필수" onChange={setCreatedBy} placeholder="담당자 이름" value={createdBy} />
      {error ? <Text as="p" className="crit-error" role="alert">{error}</Text> : null}
      <DialogActions>
        <CancelButton onClick={close} />
        <Button
          isDisabled={submitting || !policyVersion || !createdBy.trim()}
          label={submitting ? "생성 중…" : "게이트 생성"}
          onClick={submit}
          size="sm"
          variant="primary"
        />
      </DialogActions>
    </CriteriaDialog>
  );
}
