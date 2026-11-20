import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { FEATURE_OFF_LABEL, useFeatureFlags } from "../../lib/featureFlags";
import { headerVerdictPill } from "../../lib/verdict";
import type { PractitionerVerdictView } from "../../lib/types";

/** 판정이 없을 때의 문구(2026-11-19 사전규격 단계 수정안 §3 B). 판정은 추적 중인 사업에서
 * 사람이 사업기회 레코드에서 요청한다 — 이 화면이 요청하지 않는다. */
export const PRE_SPEC_NO_VERDICT_LABEL = "판정 없음 — 추적 후 요청";

/**
 * 사전규격 상세 ④의 첫 열 `참여 판정`.
 *
 * 옛 열은 기존 심층 검토 보고서의 참여 조건 절을 읽었다. 기존 심층 검토가 화면에서 내려가며
 * (사전규격 단계 수정안 §3 B) 이 열은 사업기회의 **RL 카드 판정**(정본 분석, RL-03) 요약만
 * 옮긴다. 판정 이름·사유·차단 조건 수는 서버 응답 그대로이고 화면이 다시 계산하지 않는다.
 * 개요는 이 판정의 입력이 아니다(RL-03 결정 D1).
 *
 * - 이 환경에서 RL 분석이 꺼져 있으면 조회하지 않고 꺼져 있다고 먼저 말한다(설계고도화안 C-4).
 * - 사업기회가 없거나 판정 기록이 없으면 `판정 없음 — 추적 후 요청`이다.
 */
export function PreSpecVerdictColumn({ opportunityId }: { opportunityId: number | null }) {
  const features = useFeatureFlags();
  const rlOff = features.state("rl_analysis") === "off";
  const verdictQuery = useQuery({
    // 사업기회 레코드의 판정 탭·헤더 pill과 같은 key다 — 한 응답을 함께 읽는다.
    queryKey: ["opportunity-verdict", opportunityId],
    queryFn: ({ signal }) => api.getOpportunityVerdict(opportunityId as number, {}, { signal }),
    enabled: opportunityId !== null && features.settled && !rlOff,
    retry: false,
    staleTime: 30_000,
  });
  const view: PractitionerVerdictView | null = verdictQuery.data ?? null;
  const pill = headerVerdictPill(view);
  const result = view?.availability === "completed" ? view.result : null;

  return (
    <section className="ps-tri-col" aria-labelledby="ps-conditions-list-title">
      <div className="ps-tri-head">
        <h3 id="ps-conditions-list-title" className="ps-h-col">참여 판정</h3>
        <span className="ps-cap ps-dim">RL 카드 판정 · 사람이 확인</span>
      </div>
      {rlOff ? (
        <p className="ps-cap ps-muted">참여 판정(RL 분석) · {FEATURE_OFF_LABEL}</p>
      ) : opportunityId === null ? (
        <p className="ps-cap ps-muted">{PRE_SPEC_NO_VERDICT_LABEL}</p>
      ) : verdictQuery.isPending ? (
        <p className="ps-cap ps-muted" role="status">참여 판정을 불러오는 중이에요.</p>
      ) : verdictQuery.isError ? (
        <p className="ps-cap ps-muted" role="status">참여 판정을 확인할 수 없어요. 사업기회 레코드에서 다시 확인해 주세요.</p>
      ) : result ? (
        <div className="ps-record-verdict">
          <p><strong>{result.verdict}</strong>{view?.is_current === false ? " · 이전 입력 기준" : ""}</p>
          {result.reason.trim() ? <p className="ps-cap">{result.reason}</p> : null}
          <p className="ps-cap ps-dim">
            차단 조건 {result.blocking_condition_ids.length}건 · 주의 {result.cautions.length}건
          </p>
          <Link className="ps-ref" to={`/opportunities/${opportunityId}/verdict`}>판정 보기 →</Link>
        </div>
      ) : pill ? (
        <p className="ps-cap ps-muted">
          {pill.label}
          {" · "}<Link className="ps-ref" to={`/opportunities/${opportunityId}/verdict`}>사업기회에서 보기 →</Link>
        </p>
      ) : (
        <p className="ps-cap ps-muted">{PRE_SPEC_NO_VERDICT_LABEL}</p>
      )}
    </section>
  );
}
