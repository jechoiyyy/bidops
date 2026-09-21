import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { Plus } from "lucide-react";
import {
  DataTable,
  DetailFooter,
  DetailHeader,
  DetailTabs,
  Disclosure,
  Facts,
  Note,
  Queue,
  Section,
  Small,
  StateView,
  StatusToken,
} from "../components/criteria/CriteriaPrimitives";
import { PolicyConfirmDialog, type PolicyConfirmSnapshot } from "../components/policies/PolicyConfirmDialog";
import { PolicyCreateDialog } from "../components/policies/PolicyCreateDialog";
import { ApiError, api } from "../lib/api";
import { formatMoment as formatMomentBase } from "../lib/format";
import type { PolicyActivationResponse, PolicyStatus, PolicyVersionResponse, QualityGateResponse, RuntimeJsonObject } from "../lib/types";

/**
 * 판정 정책 탭 — 불변 버전 목록과 운영 활성화 절차.
 *
 * 지키는 경계가 셋이다.
 *
 *  1. **본문은 불변이다.** 생성은 초안 추가이고 편집 수단이 없다.
 *  2. **후보 지정과 운영 활성화는 다른 조작이다.** 한 번의 확인으로 둘을 함께
 *     처리하지 않는다.
 *  3. **활성화 근거는 운영 승인용 게이트의 최신 통과 evaluation뿐이다.** 모델
 *     비교용 게이트는 수치가 통과해도 후보 목록에 오르지 않는다. 서버도 같은
 *     규칙을 강제한다(`app/screening/quality_gate.py` `validate_activation_in_session`:
 *     purpose·최신 revision·통과·완료·policy_version·prompt_version).
 *
 * 정책 본문의 키는 화면이 업무 의미로 해석하지 않는다. 임의의 JSON 키에 뜻을
 * 붙이면 정책이 실제로 무엇을 시키는지와 화면의 설명이 조용히 갈라진다.
 */

const STATUS_LABELS: Record<PolicyStatus, string> = {
  draft: "초안",
  activation_candidate: "활성화 후보",
  active: "운영 활성",
};

const BODY_FIELDS: [keyof PolicyVersionResponse & string, string][] = [
  ["perspective_prompts", "관점별 검토 프롬프트"],
  ["counterargument_prompt", "반론 프롬프트"],
  ["synthesis_prompt", "종합 프롬프트"],
  ["candidate_selection", "후보 선정"],
  ["thresholds", "임계값"],
];

type PolicyDetailTab = "content" | "approval" | "record";

function queryErrorText(error: unknown, resource: string): string {
  if (error instanceof ApiError && error.status === 409) return "최신 정책·게이트 상태와 충돌했습니다. 다시 확인하십시오.";
  if (error instanceof ApiError && error.status > 0) return `${resource}을(를) 불러오지 못했습니다 (${error.status}).`;
  return `${resource}을(를) 불러오지 못했습니다.`;
}

function actionErrorText(error: unknown, action: string): string {
  if (!(error instanceof ApiError)) return `${action}에 실패했습니다.`;
  if (error.status === 409) return `현재 정책 또는 운영 게이트 상태가 바뀌어 ${action}할 수 없습니다. 입력은 그대로 두었습니다. 최신 목록을 확인한 뒤 다시 시도하십시오.`;
  if (error.status === 422) return `담당자와 ${action} 조건을 확인하십시오.`;
  return error.status > 0 ? `${action}에 실패했습니다 (${error.status}).` : `${action}에 실패했습니다.`;
}

function bodyObject(policy: PolicyVersionResponse, field: string): RuntimeJsonObject | null {
  const value = (policy as unknown as Record<string, unknown>)[field];
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as RuntimeJsonObject : null;
}

/** `lib/format.ts`가 정본이다(U3, 중복 통합). 이 화면의 null 문구(`기록 없음`)만 고정한다. */
function moment(value: string | null): string {
  return formatMomentBase(value, "기록 없음");
}

/** 이 정책이 왜 아직 운영 활성이 아닌가. 상태를 화면이 다시 해석하지 않는다. */
function blockReason(policy: PolicyVersionResponse): string {
  if (policy.status === "active") return "현재 운영 활성 정책입니다. 본문은 불변이며 변경은 새 버전으로 만듭니다.";
  if (policy.status === "activation_candidate") {
    return policy.quality_gate_result_id
      ? "활성화 후보입니다. 품질 게이트 결과가 연결돼 있으며 활성화는 사람이 별도로 확인합니다."
      : "활성화 후보이지만 연결된 품질 게이트 결과가 없습니다. 게이트 없이 활성화하지 않습니다.";
  }
  return "draft입니다. 승인 gold와 품질 게이트를 통과하기 전에는 활성화 후보가 되지 않습니다.";
}

export function PoliciesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [pending, setPending] = useState<PolicyConfirmSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [selectedEvaluationId, setSelectedEvaluationId] = useState("");
  const [activationNotice, setActivationNotice] = useState<PolicyActivationResponse | null>(null);
  const confirmGenerationRef = useRef(0);

  const policiesQuery = useQuery({
    queryKey: ["policies"],
    queryFn: ({ signal }) => api.getPolicies({}, { signal }),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  // 활성화 근거가 될 수 있는 것은 운영 승인용 게이트뿐이므로 그것만 조회한다.
  const gatesQuery = useQuery({
    queryKey: ["quality-gates", "operational"],
    queryFn: ({ signal }) => api.getQualityGates({ purpose: "operational_approval", limit: 100, offset: 0 }, { signal }),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });

  const policies = policiesQuery.data?.items ?? [];
  const operationalGates: QualityGateResponse[] = gatesQuery.data?.items ?? [];
  const selectedVersion = searchParams.get("policy");
  const selected = policies.find((policy) => policy.policy_version === selectedVersion) ?? policies[0] ?? null;
  const rawDetailTab = searchParams.get("ptab");
  const detailTab: PolicyDetailTab = rawDetailTab === "approval" || rawDetailTab === "record" ? rawDetailTab : "content";

  function updateParams(changes: Record<string, string | null>) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      }
      return next;
    }, { replace: true });
  }

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["policies"] });
    void queryClient.invalidateQueries({ queryKey: ["quality-gates"] });
  }

  // 서버 규칙과 같은 조건만 후보로 올린다. 목적·최신 evaluation·통과·완료·
  // 정책·프롬프트 결합이 모두 맞아야 한다.
  const bindableGates = selected
    ? operationalGates.filter((gate) => (
      gate.purpose === "operational_approval"
      && gate.result_status === "통과"
      && gate.execution_status === "완료"
      && Boolean(gate.latest_evaluation_id)
      && gate.policy_version === selected.policy_version
      && gate.prompt_version === selected.prompt_version
    ))
    : [];
  const selectedGate = bindableGates.find((gate) => gate.latest_evaluation_id === selectedEvaluationId) ?? null;
  const linkedGate = selected?.quality_gate_result_id
    ? operationalGates.find((gate) => gate.latest_evaluation_id === selected.quality_gate_result_id) ?? null
    : null;
  const canActivate = Boolean(selected && selected.status === "activation_candidate" && selectedGate);

  if (policiesQuery.isPending || gatesQuery.isPending) {
    return (
      <div className="crit-workspace" id="criteria-panel-policies" role="tabpanel">
        <StateView description="정책 목록과 운영 승인 게이트를 확인하는 중입니다." kind="loading" title="판정 정책을 불러오는 중입니다" />
      </div>
    );
  }
  if (policiesQuery.error || gatesQuery.error) {
    return (
      <div className="crit-workspace" id="criteria-panel-policies" role="tabpanel">
        <StateView
          action={<Button label="다시 조회" onClick={() => { void policiesQuery.refetch(); void gatesQuery.refetch(); }} />}
          description={queryErrorText(policiesQuery.error ?? gatesQuery.error, "정책 화면")}
          kind="error"
          title="정책 화면을 불러오지 못했습니다."
        />
      </div>
    );
  }

  function runConfirm(snapshot: PolicyConfirmSnapshot, actor: string) {
    if (busy) return;
    // 늦게 온 응답이 그 사이에 열린 **다른** 확인 창을 닫거나 그 창에 오류를
    // 붙이지 않게, 요청을 낸 세대를 기억하고 응답에서 다시 확인한다.
    const generation = ++confirmGenerationRef.current;
    setBusy(true);
    setConfirmError(null);
    const request: Promise<PolicyActivationResponse | PolicyVersionResponse> = snapshot.kind === "candidate"
      ? api.designatePolicyCandidate(snapshot.policyVersion, { confirmed_by: actor }, actor)
      : api.activatePolicy(snapshot.policyVersion, { quality_gate_result_id: snapshot.evaluationId as string, confirmed_by: actor }, actor);
    void request
      .then((response) => {
        if (generation !== confirmGenerationRef.current) return;
        setPending(null);
        setSelectedEvaluationId("");
        if (snapshot.kind === "activate") setActivationNotice(response as PolicyActivationResponse);
        refresh();
      })
      // 충돌·실패에서는 창을 닫지 않는다. 담당자가 다시 입력하지 않도록 초안을 남긴다.
      .catch((reason: unknown) => {
        if (generation !== confirmGenerationRef.current) return;
        setConfirmError(actionErrorText(reason, snapshot.kind === "candidate" ? "후보 지정" : "정책 활성화"));
      })
      .finally(() => {
        if (generation === confirmGenerationRef.current) setBusy(false);
      });
  }

  return (
    <div className="crit-workspace" id="criteria-panel-policies" role="tabpanel">
      <Queue
        count={policies.length}
        emptyText="생성된 정책이 없습니다."
        footer="기존 버전은 보존됩니다 · 변경은 새 버전으로"
        items={policies.map((policy) => ({
          id: policy.policy_version,
          title: policy.policy_version,
          subtitle: `프롬프트 ${policy.prompt_version}`,
          status: STATUS_LABELS[policy.status],
          meta: `${moment(policy.created_at)} · ${policy.created_by}`,
        }))}
        onSelect={(id) => updateParams({ policy: id })}
        selectedId={selected?.policy_version ?? null}
        title="정책 버전"
        tools={<Button icon={<Plus aria-hidden="true" />} label="새 정책 버전" onClick={() => setCreateOpen(true)} size="sm" width="100%" />}
      />
      <section aria-label="선택한 정책" className="crit-detail">
        {selected ? (
          <>
            <DetailHeader eyebrow="판정 정책 · 불변 버전" status={STATUS_LABELS[selected.status]} title={selected.policy_version}>
              <Small>{`프롬프트 ${selected.prompt_version} · 생성 ${moment(selected.created_at)} · ${selected.created_by}`}</Small>
            </DetailHeader>
            <DetailTabs
              id="criteria-policy"
              items={[["content", "정책 내용"], ["approval", "활성화 조건"], ["record", "버전 정보"]]}
              onChange={(value) => updateParams({ ptab: value === "content" ? null : value })}
              value={detailTab}
            />
            <div className="crit-detail-scroll" id={`criteria-policy-${detailTab}`} role="tabpanel">
              {activationNotice ? (
                <Note
                  action={<Button label="닫기" onClick={() => setActivationNotice(null)} size="sm" />}
                  role="status"
                  title="정책이 활성화되었습니다"
                >
                  {`이전 active 정책 ${activationNotice.previous_active_policy_version ?? "없음"} · 결합 evaluation ${activationNotice.quality_gate_result_id} · ${moment(activationNotice.activated_at)}`}
                </Note>
              ) : null}
              {detailTab === "content" ? (
                <>
                  <Section title="불변 본문 다섯 항목">
                    <DataTable
                      caption="정책 본문 항목"
                      headings={["본문 항목", "최상위 키", "형태"]}
                      rows={BODY_FIELDS.map(([field, label]) => {
                        const body = bodyObject(selected, field);
                        const keys = body ? Object.keys(body) : [];
                        return [
                          <span className="crit-cell-stack" key="field">
                            <Text weight="semibold">{label}</Text>
                            <Small><code>{field}</code></Small>
                          </span>,
                          <Text key="keys">{body === null ? "JSON object가 아닙니다" : keys.length === 0 ? "값 없음 (빈 object)" : keys.join(", ")}</Text>,
                          <Text key="shape">{body === null ? "확인 불가" : `키 ${keys.length}개`}</Text>,
                        ];
                      })}
                    />
                  </Section>
                  <Note title="화면은 정책 본문의 키를 업무 의미로 해석하지 않습니다">
                    본문의 키 이름과 값은 그대로 보여 줍니다. 임의의 키나 버전명으로 무엇을 판정하는지 추정하지 않습니다.
                  </Note>
                  <Note title="등급과 참여 준비 상태는 별도로 판단합니다">
                    자격이 미확인이라는 이유만으로 적합성 등급을 낮추지 않습니다.
                  </Note>
                  <Disclosure summary="불변 정책 본문 원문 (편집 불가)">
                    <pre>{JSON.stringify(Object.fromEntries(BODY_FIELDS.map(([field]) => [field, bodyObject(selected, field)])), null, 2)}</pre>
                    <Small>식별 해시 · <code>{selected.content_digest}</code></Small>
                  </Disclosure>
                </>
              ) : null}

              {detailTab === "approval" ? (
                <>
                  <Section title="운영 활성화 조건">
                    <DataTable
                      caption="운영 활성화 확인 항목"
                      headings={["확인 항목", "연결된 내용", "상태"]}
                      rows={[
                        [
                          <Text key="l">정책 상태</Text>,
                          <span className="crit-mono" key="v">{selected.status}</span>,
                          <StatusToken key="s" label={STATUS_LABELS[selected.status]} />,
                        ],
                        [
                          <Text key="l">게이트 목적</Text>,
                          <span className="crit-mono" key="v">operational_approval</span>,
                          <Text key="s">모델 비교용은 근거가 될 수 없음</Text>,
                        ],
                        [
                          <Text key="l">연결된 게이트 평가</Text>,
                          <code key="v">{selected.quality_gate_result_id ?? "연결 없음"}</code>,
                          <Text key="s">{selected.quality_gate_result_id ? (linkedGate ? "게이트 확인됨" : "조회 범위에서 게이트 미확인") : "연결 없음"}</Text>,
                        ],
                        [
                          <Text key="l">정책 결합</Text>,
                          <span className="crit-mono" key="v">{selected.policy_version}</span>,
                          <StatusToken key="s" label={bindableGates.length > 0 ? "일치" : "결합 가능한 게이트 없음"} />,
                        ],
                        [
                          <Text key="l">프롬프트 결합</Text>,
                          <span className="crit-mono" key="v">{selected.prompt_version}</span>,
                          <StatusToken key="s" label={bindableGates.some((gate) => gate.prompt_version === selected.prompt_version) ? "일치" : "확인 필요"} />,
                        ],
                        [
                          <Text key="l">통과한 최신 운영 평가</Text>,
                          <Text key="v">{`${bindableGates.length}건`}</Text>,
                          <Text key="s">{bindableGates.length > 0 ? "선택 가능" : "없음"}</Text>,
                        ],
                      ]}
                    />
                  </Section>
                  {selected.status === "activation_candidate" ? (
                    <Section title="활성화에 결합할 평가 선택">
                      <Selector
                        label="통과한 최신 운영 evaluation"
                        onChange={setSelectedEvaluationId}
                        options={bindableGates.map((gate) => ({
                          value: gate.latest_evaluation_id,
                          label: gate.latest_evaluation_id,
                          description: `${gate.gate_id} · ${gate.policy_version} · ${gate.prompt_version}`,
                        }))}
                        placeholder={bindableGates.length > 0 ? "게이트 평가를 선택하십시오" : "결합할 수 있는 통과 평가가 없습니다"}
                        value={selectedEvaluationId}
                      />
                      {selectedGate ? (
                        <Facts items={[
                          ["정책", `${selectedGate.policy_version}`],
                          ["정책 식별 해시", selected.content_digest],
                          ["프롬프트", selectedGate.prompt_version],
                          ["모델", `${selectedGate.model_name} · ${selectedGate.model_digest}`],
                          ["회사 프로필", `${selectedGate.company_profile_version} · ${selectedGate.company_profile_digest}`],
                          ["게이트 평가", `${selectedGate.latest_evaluation_id} · ${selectedGate.result_status} · 실행 ${selectedGate.execution_status}`],
                        ]} />
                      ) : (
                        <Small>
                          통과한 최신 운영 게이트를 고르면 정책·프롬프트·모델·프로필 식별 해시를 확인할 수 있습니다.
                          목적·최신 평가·통과·완료와 정책·프롬프트 결합이 모두 맞는 게이트만 목록에 오릅니다.
                        </Small>
                      )}
                    </Section>
                  ) : null}
                  <Note
                    title={bindableGates.length > 0 ? "통과한 최신 운영 평가가 있습니다" : "연결할 수 있는 통과 운영 평가가 없습니다"}
                    tone={bindableGates.length > 0 ? "neutral" : "warning"}
                  >
                    모델 비교용 평가나 참조 실행만으로 정책을 활성화할 수 없습니다. 결과 수치가 통과여도 운영 승인용 게이트의 최신 통과 평가가 아니면 근거가 되지 않습니다.
                  </Note>
                  <Note title="지금 이 정책의 상태" tone="neutral">{blockReason(selected)}</Note>
                </>
              ) : null}

              {detailTab === "record" ? (
                <>
                  <Section title="고정된 버전 정보">
                    <Facts items={[
                      ["정책 버전", <span className="crit-mono" key="v">{selected.policy_version}</span>],
                      ["프롬프트 버전", <span className="crit-mono" key="p">{selected.prompt_version}</span>],
                      ["상태", `${STATUS_LABELS[selected.status]} · ${selected.status}`],
                      ["식별 해시", <code key="d">{selected.content_digest}</code>],
                      ["생성 시각", moment(selected.created_at)],
                      ["생성 담당자", selected.created_by],
                      ["활성화 시각", moment(selected.activated_at)],
                      ["활성화 담당자", selected.activated_by ?? "기록 없음"],
                      ["연결된 게이트 평가", <code key="g">{selected.quality_gate_result_id ?? "연결 없음"}</code>],
                      ["응답 규격", <code key="s">{selected.schema_version}</code>],
                    ]} />
                  </Section>
                  <Note title="본문 변경은 새 버전으로 기록됩니다">
                    새 기준은 이후 시작한 실행에 적용되며 기존 판정 결과를 소급해 바꾸지 않습니다.
                  </Note>
                </>
              ) : null}
            </div>
            <DetailFooter note={blockReason(selected)}>
              {selected.status === "draft" ? (
                <Button
                  label="활성화 후보 지정"
                  onClick={() => {
                    setConfirmError(null);
                    setPending({
                      kind: "candidate",
                      policyVersion: selected.policy_version,
                      evaluationId: null,
                      facts: [
                        ["대상 정책", selected.policy_version],
                        ["정책 식별 해시", selected.content_digest],
                        ["프롬프트", selected.prompt_version],
                        ["바뀌는 것", "draft → activation_candidate · 본문은 바뀌지 않습니다"],
                      ],
                    });
                  }}
                  size="sm"
                />
              ) : null}
              {selected.status === "activation_candidate" ? (
                <Button
                  isDisabled={!canActivate}
                  label="정책 활성화 확인"
                  onClick={() => {
                    if (!selectedGate) return;
                    setConfirmError(null);
                    setPending({
                      kind: "activate",
                      policyVersion: selected.policy_version,
                      evaluationId: selectedGate.latest_evaluation_id,
                      facts: [
                        ["대상 정책", selected.policy_version],
                        ["정책 식별 해시", selected.content_digest],
                        ["근거 게이트 평가", `${selectedGate.latest_evaluation_id} · ${selectedGate.result_status}`],
                        ["프롬프트", selectedGate.prompt_version],
                        ["모델", `${selectedGate.model_name} · ${selectedGate.model_digest}`],
                        ["회사 프로필", `${selectedGate.company_profile_version} · ${selectedGate.company_profile_digest}`],
                        ["바뀌는 것", "activation_candidate → active · 이후 시작하는 실행에만 적용"],
                      ],
                    });
                  }}
                  size="sm"
                  variant="primary"
                />
              ) : null}
              {selected.status === "active" ? <StatusToken label="운영 활성" size="md" /> : null}
            </DetailFooter>
          </>
        ) : (
          <StateView
            action={<Button icon={<Plus aria-hidden="true" />} label="새 정책 버전" onClick={() => setCreateOpen(true)} />}
            description="정책을 만들면 목록과 상세에서 불변 본문과 활성화 조건을 확인할 수 있습니다."
            kind="empty"
            title="생성된 정책이 없습니다."
          />
        )}
      </section>
      <PolicyCreateDialog
        onClose={() => setCreateOpen(false)}
        onCreated={(policyVersion) => {
          setCreateOpen(false);
          updateParams({ policy: policyVersion, ptab: null });
          refresh();
        }}
        open={createOpen}
      />
      <PolicyConfirmDialog
        busy={busy}
        error={confirmError}
        onClose={() => { ++confirmGenerationRef.current; setBusy(false); setPending(null); setConfirmError(null); }}
        onConfirm={runConfirm}
        snapshot={pending}
      />
    </div>
  );
}
