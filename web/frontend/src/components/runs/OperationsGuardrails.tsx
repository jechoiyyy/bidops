import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";

/**
 * 실행 상태 화면의 고정 사이드 패널 (PLAN 단계 E 작업 6, `RunStatus` 아트보드).
 *
 * 두 가지를 탭과 무관하게 항상 남긴다.
 *  1. **운영 텔레메트리가 어디로 갔는지.** ADR-0041 결정 5는 판정 화면에서
 *     `model_digest`·token 수·`duration_ms`를 빼되 삭제하지 말라고 했다. 뺀 것을
 *     삭제로 오해하지 않도록 어디서 볼 수 있는지 화면이 직접 말한다.
 *  2. **상시 운영이 꺼져 있는 이유.** 서버가 준 거절 사유를 그대로 보여준다.
 *     fail-closed 기본값을 화면이 "곧 켜짐"으로 바꾸지 않는다.
 */
export function OperationsGuardrails() {
  const alwaysOnQuery = useQuery({
    queryKey: ["always-on"],
    queryFn: ({ signal }) => api.getAlwaysOn({ signal }),
    staleTime: 30_000,
  });
  const state = alwaysOnQuery.data;

  return (
    <aside className="runstatus-guardrails" aria-label="실행 상태 화면의 경계">
      <section className="runstatus-guardrail-panel" aria-labelledby="runstatus-telemetry-title">
        <h3 id="runstatus-telemetry-title">운영 텔레메트리</h3>
        <p>
          <span className="mono">model_digest</span> · token 입력/캐시/출력 · <span className="mono">duration_ms</span> ·
          error code는 판정 화면의 기본 표시에서 뺐지만 <strong>삭제하지 않았습니다.</strong> 감사 목적으로 여기서 확인합니다.
        </p>
        <Link className="runstatus-guardrail-link" to="/runs">수집 실행 탭에서 실행 선택 →</Link>
      </section>

      <section className="runstatus-guardrail-panel" aria-labelledby="runstatus-always-on-title">
        <h3 id="runstatus-always-on-title">상시 운영</h3>
        {alwaysOnQuery.isPending ? <p role="status">상시 운영 상태를 불러오는 중…</p> : null}
        {alwaysOnQuery.isError ? (
          <p role="alert">상시 운영 상태를 불러오지 못했습니다. 꺼져 있다는 뜻도 켜져 있다는 뜻도 아닙니다.</p>
        ) : null}
        {state ? (
          <>
            <p className="runstatus-guardrail-state">
              현재 <strong>{state.effective_enabled ? "켜짐" : "꺼짐"}</strong>
              {state.effective_enabled !== state.configured_enabled
                ? ` · 설정값은 ${state.configured_enabled ? "켜짐" : "꺼짐"}이고 환경이 ${state.environment_enabled ? "허용" : "차단"}합니다`
                : ""}
            </p>
            <dl className="runstatus-guardrail-facts">
              <div>
                <dt>차단 사유</dt>
                <dd>{state.rejection_reason ?? (state.effective_enabled ? "차단 없음" : "서버가 사유를 남기지 않았습니다")}</dd>
              </div>
              <div>
                <dt>품질 게이트</dt>
                <dd>{state.quality_gate_status ?? "연결 없음"}</dd>
              </div>
              <div>
                <dt>승인 조합</dt>
                <dd className="mono">
                  {state.policy_version ?? "정책 null"} · {state.model_name ?? "모델 null"} · {state.company_profile_version ?? "프로필 null"}
                </dd>
              </div>
            </dl>
          </>
        ) : null}
        <p>
          승인 조합이 맞지 않으면 켤 수 없습니다. 앱 startup은 migration·seed·정책 활성화·모델 호출을 수행하지 않습니다.
        </p>
        <Link className="runstatus-guardrail-link" to="/operations">상시 운영 탭으로 →</Link>
      </section>
    </aside>
  );
}
