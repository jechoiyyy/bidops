import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import { present } from "../../lib/format";
import type { JsonValue, MatchedPerformanceResponse } from "../../lib/types";

/**
 * 유사 실적 — 회사 실적과 대조된 것을 보여 준다(spec §6.3).
 *
 * 출처가 **둘이고 구조가 다르다.** 한 표로 합치지 않는다:
 *
 * - `performance_matches[]`는 수집 단계의 탐색 신호다. 계약은
 *   `project_name`·`source_page`·`similarity`·`common_fragment`·
 *   `legal_qualification_status`이고(`skills/references/workflow-contract.md:105`)
 *   `legal_qualification_status`는 확인 자료가 없어 항상 `unknown`이다.
 * - `judgment.matched_performances[]`는 그 신호를 **판정이 검토한 결과**다.
 *   `name`·`match_reason`·`mismatch_or_limit`·`source`·`status`를 가지며
 *   `mismatch_or_limit`에는 유사도가 설명하지 못하는 차이를 적는다
 *   (`workflow-contract.md:188`).
 *
 * 두 목록을 잇는 공식 키가 없다(`project_name`과 `name`이 같은 문자열이라는
 * 보장이 없고, 판정이 신호에 없는 실적을 검토할 수도 있다). 이름으로 짝지으면
 * 없는 관계를 만들게 되므로 표를 둘로 나누고 각자의 열 뜻을 그대로 둔다.
 * 유사도는 수집 단계의 모델 점수이며 실적 동등성의 증거가 아니다
 * (`skills/bidops-screen/SKILL.md:44`).
 */

interface RetrievedPerformance {
  commonFragment: string | null;
  legalStatus: string | null;
  projectName: string | null;
  similarity: number | null;
  sourcePage: string | null;
}

function record(value: JsonValue): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function textValue(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function readRetrieved(value: JsonValue): RetrievedPerformance {
  const item = record(value);
  const similarity = item.similarity;
  return {
    commonFragment: textValue(item.common_fragment),
    legalStatus: textValue(item.legal_qualification_status),
    projectName: textValue(item.project_name),
    similarity: typeof similarity === "number" && Number.isFinite(similarity) ? similarity : null,
    sourcePage: textValue(item.source_page),
  };
}

/** 모델 점수는 소수 2자리로 고정한다. 숫자가 아니면 지어내지 않는다. */
function similarityLabel(value: number | null): string {
  return value === null ? "유사도 미확인" : value.toFixed(2);
}

/**
 * `unknown`은 계약이 정한 "확인 자료가 없다"는 값이므로 `미확인`으로 읽고,
 * 그 밖의 코드는 서버가 준 대로 통과시킨다(AGENTS.md — 모르는 코드는 그대로).
 */
function statusLabel(value: string | null, fallback: string): string {
  if (value === null) return fallback;
  return value === "unknown" ? "미확인" : value;
}

/**
 * 임계값 미만이라 목록에 오르지 못한 경우까지 포함한 최고 유사도
 * (`workflow-contract.md:50`). 실제 0과 값 없음을 구분한다.
 */
function topScoreLabel(value: number | null): string {
  return value === null || Number.isNaN(value)
    ? "최고 유사도 미제공"
    : `최고 유사도 ${value.toFixed(2)}`;
}

export function PerformanceMatches({
  matchedPerformances,
  performanceMatches,
  performanceTopScore,
}: {
  matchedPerformances: MatchedPerformanceResponse[];
  performanceMatches: JsonValue[];
  performanceTopScore: number | null;
}) {
  const retrieved = performanceMatches.map(readRetrieved);
  const bothEmpty = retrieved.length === 0 && matchedPerformances.length === 0;

  return (
    <Panel
      className="performance-matches-panel"
      title="유사 실적 · 회사 실적과 대조"
      action={<span className="panel-note">{topScoreLabel(performanceTopScore)}</span>}
    >
      <p className="performance-matches-note">
        유사도는 수집 단계의 모델 점수이며 판단 보조입니다. 실적 동등성이나 참여 자격의 증거가 아닙니다.
      </p>
      {bothEmpty ? (
        <EmptyState compact title="대조된 실적 없음" />
      ) : (
        <>
          <section className="performance-matches-block" aria-labelledby="performance-retrieved-title">
            <h4 className="performance-matches-subtitle" id="performance-retrieved-title">수집 탐색 신호</h4>
            {retrieved.length === 0 ? (
              <EmptyState compact title="대조된 실적 없음" />
            ) : (
              <div className="table-wrap">
                <table className="data-table performance-matches-table">
                  <thead>
                    <tr>
                      <th scope="col">회사 실적</th>
                      <th scope="col">유사도</th>
                      <th scope="col">공통 조각</th>
                      <th scope="col">회사소개서 쪽</th>
                      <th scope="col">법적 자격 확인</th>
                    </tr>
                  </thead>
                  <tbody>
                    {retrieved.map((item, index) => (
                      <tr key={`${item.projectName ?? "performance"}-${index}`}>
                        <td>{present(item.projectName, "실적명 미확인")}</td>
                        <td className="mono tabular-nums">{similarityLabel(item.similarity)}</td>
                        <td>{present(item.commonFragment, "공통 조각 없음")}</td>
                        <td className="mono tabular-nums">{item.sourcePage === null ? "쪽 미확인" : `${item.sourcePage}쪽`}</td>
                        <td>{statusLabel(item.legalStatus, "미확인")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section className="performance-matches-block" aria-labelledby="performance-judged-title">
            <h4 className="performance-matches-subtitle" id="performance-judged-title">판정 검토 결과</h4>
            {matchedPerformances.length === 0 ? (
              <EmptyState compact title="대조된 실적 없음" />
            ) : (
              <div className="table-wrap">
                <table className="data-table performance-matches-table">
                  <thead>
                    <tr>
                      <th scope="col">회사 실적</th>
                      <th scope="col">판단 근거</th>
                      <th scope="col">한계·차이</th>
                      <th scope="col">출처</th>
                      <th scope="col">확인 상태</th>
                    </tr>
                  </thead>
                  <tbody>
                    {matchedPerformances.map((item) => (
                      <tr key={item.id}>
                        <td>{present(item.name, "실적명 미확인")}</td>
                        <td>{present(item.match_reason, "판단 근거 미확인")}</td>
                        <td>{present(item.mismatch_or_limit, "한계 기록 없음")}</td>
                        <td>{present(item.source, "출처 미확인")}</td>
                        <td>{statusLabel(item.status, "미확인")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </Panel>
  );
}
