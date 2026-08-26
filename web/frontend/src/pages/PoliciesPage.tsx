import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { EmptyState } from "../components/common/EmptyState";
import { PolicyCreateForm } from "../components/policies/PolicyCreateForm";
import { PolicyVersionCard } from "../components/policies/PolicyVersionCard";
import { ApiError, api } from "../lib/api";
import type { PolicyActivationResponse } from "../lib/types";

function errorText(error: unknown, resource: string): string {
  if (error instanceof ApiError && error.status === 409) return "최신 정책·게이트 상태와 충돌했습니다. 다시 확인하십시오.";
  if (error instanceof ApiError && error.status > 0) return `${resource}을(를) 불러오지 못했습니다 (${error.status}).`;
  return `${resource}을(를) 불러오지 못했습니다.`;
}

export function PoliciesPage() {
  const queryClient = useQueryClient();
  const [activationNotice, setActivationNotice] = useState<PolicyActivationResponse | null>(null);
  const policiesQuery = useQuery({ queryKey: ["policies"], queryFn: () => api.getPolicies(), refetchInterval: 10_000, staleTime: 0 });
  const gatesQuery = useQuery({ queryKey: ["quality-gates", "operational"], queryFn: () => api.getQualityGates({ purpose: "operational_approval", limit: 100, offset: 0 }), refetchInterval: 5000, staleTime: 0 });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["policies"] });
    void queryClient.invalidateQueries({ queryKey: ["quality-gates", "operational"] });
  };
  const policies = policiesQuery.data?.items ?? [];
  const operationalGates = gatesQuery.data?.items ?? [];
  const activePolicy = policies.find((policy) => policy.status === "active") ?? null;
  const activeGate = activePolicy?.quality_gate_result_id ? operationalGates.find((gate) => gate.latest_evaluation_id === activePolicy.quality_gate_result_id) : null;

  if (policiesQuery.isLoading || gatesQuery.isLoading) return <div className="policy-loading" role="status" aria-live="polite">정책과 운영 게이트를 불러오는 중입니다.</div>;
  if (policiesQuery.error || gatesQuery.error) {
    const error = policiesQuery.error ?? gatesQuery.error;
    return <EmptyState title="정책 화면을 불러오지 못했습니다." description={errorText(error, "정책") } action={{ label: "다시 시도", onClick: () => { void policiesQuery.refetch(); void gatesQuery.refetch(); } }} />;
  }

  return (
    <div className="policy-page">
      <header className="policy-page-header">
        <div><span className="policy-eyebrow">판정 런타임 · 불변 설정</span><h1>판정 정책</h1><p>정책 본문은 버전과 digest로 고정됩니다. 후보 지정과 운영 활성화는 별도 확인 절차입니다.</p></div>
        <div className="policy-header-facts"><span>버전</span><strong>{policies.length}개</strong><span>현재 active</span><strong className="mono">{policiesQuery.data?.active_policy_version ?? "없음"}</strong></div>
      </header>
      <div className="policy-critical-note" role="note"><strong>운영 경계</strong><span>모델 비교용 게이트는 정책 활성화 근거로 사용할 수 없습니다. 운영 활성화에는 최신 operational_approval 통과 evaluation ID가 필요합니다.</span></div>
      {activationNotice ? <div className="policy-success-notice" role="status" aria-live="polite"><strong>정책이 활성화되었습니다.</strong><span>이전 active 정책: {activationNotice.previous_active_policy_version ?? "없음"} · 결합 evaluation: <code>{activationNotice.quality_gate_result_id}</code></span><button type="button" onClick={() => setActivationNotice(null)}>닫기</button></div> : null}
      <PolicyCreateForm onCreated={refresh} />
      <section className="policy-panel policy-list-panel" aria-labelledby="policy-list-heading">
        <div className="policy-panel-heading"><div><span className="policy-eyebrow">버전 목록</span><h2 id="policy-list-heading">불변 정책 버전</h2></div><span className="policy-readonly-note">수정 대신 새 버전 생성</span></div>
        {policies.length > 0 ? <div className="policy-version-list">{policies.map((policy) => <PolicyVersionCard key={policy.policy_version} policy={policy} operationalGates={operationalGates} onChanged={refresh} onActivated={setActivationNotice} />)}</div> : <p className="policy-empty-inline">생성된 정책이 없습니다.</p>}
      </section>
      <section className="policy-panel policy-active-panel" aria-labelledby="policy-active-heading">
        <div className="policy-panel-heading"><div><span className="policy-eyebrow">운영 결합</span><h2 id="policy-active-heading">현재 active 조합</h2></div><span className="policy-readonly-note">정책 본문과 게이트는 함께 변경되지 않음</span></div>
        {activePolicy ? <div className="policy-active-binding"><dl><div><dt>정책</dt><dd className="mono">{activePolicy.policy_version}</dd></div><div><dt>정책 digest</dt><dd><code>{activePolicy.content_digest}</code></dd></div><div><dt>게이트 evaluation</dt><dd><code>{activePolicy.quality_gate_result_id ?? "연결 없음"}</code></dd></div><div><dt>모델·프로필</dt><dd>{activeGate ? <>{activeGate.model_name} · <code>{activeGate.model_digest}</code><br /><span className="mono">{activeGate.company_profile_version}</span> · <code>{activeGate.company_profile_digest}</code></> : "연결된 최신 운영 게이트를 찾을 수 없음"}</dd></div><div><dt>활성화 담당자</dt><dd>{activePolicy.activated_by ?? "정보 없음"}</dd></div></dl>{!activeGate ? <p className="policy-form-error" role="alert">현재 active 정책의 게이트 결합 정보를 확인할 수 없습니다.</p> : null}</div> : <p className="policy-empty-inline">현재 active 정책이 없습니다.</p>}
      </section>
    </div>
  );
}
