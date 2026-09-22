import { Badge } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import type { JsonValue } from "../../lib/types";
import { present } from "../../lib/format";

interface RetrievalSignalsProps {
  matches: JsonValue[];
}

function record(value: JsonValue): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

// 산출물의 field_kind 는 title·classification 외의 값도 담는다. 알 수 없는
// 값을 제목으로 표시하면 근거의 출처를 잘못 알리게 되므로 그대로 드러낸다.
function signalSource(fieldKind: unknown): string {
  if (fieldKind === "classification") return "조달분류";
  if (fieldKind === "title") return "제목";
  if (typeof fieldKind === "string" && fieldKind) return `기타(${fieldKind})`;
  return "출처 미확인";
}

// 부제에서 응답 필드 이름(`focus_matches`)을 뺀다(ADR-0066 §3.3 한글화). 실무자가
// 읽을 것은 "이 공고가 왜 후보로 올라왔는가"이고, 신호의 출처는 아래 각 줄이 말한다.
export function RetrievalSignals({ matches }: RetrievalSignalsProps) {
  const classificationCount = matches.filter((match) => record(match).field_kind === "classification").length;
  return (
    <Panel
      className="retrieval-signals-panel"
      title="1차 검색 신호"
      action={<span className="panel-note">후보로 올라온 근거</span>}
    >
      {matches.length === 0 ? (
        <EmptyState compact title="검색 신호가 없습니다." />
      ) : (
        <>
          <div className="retrieval-signal-list">
            {matches.map((match, index) => {
              const item = record(match);
              const classification = item.field_kind === "classification";
              return (
                <div className="retrieval-signal" key={`${String(item.matched_field ?? "signal")}-${index}`}>
                  <Badge label={`${present(item.label, "신호 미확인")} · ${signalSource(item.field_kind)}`} variant={classification ? "grade-4" : "focus"} />
                  <span className="retrieval-signal-value">{present(item.matched_text, "검색어 미확인")}</span>
                  <span className="retrieval-signal-source">{present(item.matched_field, "출처 필드 미확인")}</span>
                </div>
              );
            })}
          </div>
          {classificationCount > 0 ? (
            <p className="retrieval-signal-note">조달분류에서만 나온 {classificationCount}개 신호는 모든 용역 공고에 부여될 수 있어 근거 강도가 낮습니다.</p>
          ) : null}
        </>
      )}
    </Panel>
  );
}
