import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import type { PolicyVersionResponse } from "../../lib/types";

/**
 * 판정 기준 화면의 고정 사이드 패널 (PLAN 단계 E 작업 6, `Criteria` 아트보드).
 *
 * 두 가지를 탭과 무관하게 항상 남긴다.
 *  1. **이 화면이 정하지 않는 것.** 기준을 고치는 화면과 판정을 내리는 화면이
 *     같아 보이면 담당자가 기준 편집으로 판정이 바뀐다고 오해한다. 네 판단은
 *     각각 별도 조작이고 기준 편집이 이미 내려진 판정을 소급해 바꾸지 않는다.
 *  2. **정책이 활성화되지 못하는 이유.** `active`가 아닌 정책의 status를 그대로
 *     보여준다. 상태를 화면이 다시 해석하거나 "곧 활성화됨" 같은 말로 바꾸지
 *     않는다.
 */

function blockReason(policy: PolicyVersionResponse): string {
  if (policy.status === "activation_candidate") {
    return policy.quality_gate_result_id
      ? "활성화 후보입니다. 품질 게이트 결과가 연결돼 있으며 활성화는 사람이 별도로 확인합니다."
      : "활성화 후보이지만 연결된 품질 게이트 결과가 없습니다. 게이트 없이 활성화하지 않습니다.";
  }
  return "draft입니다. 승인 gold와 품질 게이트를 통과하기 전에는 활성화 후보가 되지 않습니다.";
}

export function CriteriaGuardrails() {
  const policiesQuery = useQuery({
    queryKey: ["policies"],
    queryFn: ({ signal }) => api.getPolicies({}, { signal }),
    staleTime: 60_000,
  });

  const items = policiesQuery.data?.items ?? [];
  const activeVersion = policiesQuery.data?.active_policy_version ?? null;
  const waiting = items.filter((policy) => policy.status !== "active");

  return (
    <aside className="criteria-guardrails" aria-label="판정 기준 화면의 경계">
      <section className="criteria-guardrail-panel" aria-labelledby="criteria-not-decided-title">
        <h3 id="criteria-not-decided-title">이 화면이 정하지 않는 것</h3>
        <ul>
          <li>적합성 등급 4값</li>
          <li>참여 준비 상태 4값</li>
          <li>심층 검토 실행 승인</li>
          <li>최종 입찰 Go/No-Go</li>
        </ul>
        <p>네 판단은 각각 별도 조작으로 남습니다. 기준 편집이 이미 내려진 판정을 소급해 바꾸지 않습니다.</p>
      </section>

      <section className="criteria-guardrail-panel" aria-labelledby="criteria-policy-block-title">
        <h3 id="criteria-policy-block-title">활성화 대기 판정 정책</h3>
        {policiesQuery.isPending ? <p role="status">정책 목록을 불러오는 중…</p> : null}
        {policiesQuery.isError ? (
          <p role="alert">정책 목록을 불러오지 못했습니다. 대기 중인 정책이 없다는 뜻이 아닙니다.</p>
        ) : null}
        {policiesQuery.isSuccess ? (
          <>
            <p className="criteria-guardrail-active">
              현재 active · <span className="mono">{activeVersion ?? "없음"}</span>
            </p>
            {waiting.length === 0 ? (
              <p>활성화를 기다리는 정책이 없습니다.</p>
            ) : (
              <ul className="criteria-guardrail-policies">
                {waiting.map((policy) => (
                  <li key={policy.policy_version}>
                    <span className="mono">{policy.policy_version}</span>
                    <span className="criteria-guardrail-status">{policy.status}</span>
                    <span>{blockReason(policy)}</span>
                  </li>
                ))}
              </ul>
            )}
            <Link className="criteria-guardrail-link" to="/policies">판정 정책 탭으로 →</Link>
          </>
        ) : null}
      </section>
    </aside>
  );
}
