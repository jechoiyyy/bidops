import { Badge, type BadgeVariant } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import type { PerspectiveResponse } from "../../lib/types";
import { present } from "../../lib/format";

interface PerspectiveTableProps {
  perspectives: PerspectiveResponse[];
}

function assessmentVariant(value: string | null): BadgeVariant {
  if (value === "적합") return "grade-2";
  if (value === "부분 적합") return "grade-3";
  if (value === "부적합") return "grade-4";
  return "neutral";
}

function evidenceVariant(status: string | null): BadgeVariant {
  if (status === "confirmed") return "evidence-confirmed";
  if (status === "inferred") return "evidence-inferred";
  return "evidence-unknown";
}

function evidenceLabel(status: string | null): string {
  if (status === "confirmed") return "confirmed";
  if (status === "inferred") return "inferred";
  return "unknown";
}

export function PerspectiveTable({ perspectives }: PerspectiveTableProps) {
  return (
    <Panel
      className="notice-perspective-panel"
      title="관점별 판단"
      action={<span className="panel-note">{perspectives.length || "없음"}개 관점</span>}
    >
      {perspectives.length === 0 ? (
        <EmptyState compact title="관점별 판단이 없습니다." />
      ) : (
        <div className="table-wrap">
          <table className="data-table perspective-table">
            <thead>
              <tr>
                <th scope="col">관점</th>
                <th scope="col">판정</th>
                <th scope="col">사유·근거</th>
              </tr>
            </thead>
            <tbody>
              {perspectives.map((perspective) => (
                <tr key={perspective.id}>
                  <td className="perspective-name">{present(perspective.name, "관점 미확인")}</td>
                  <td><Badge label={present(perspective.assessment, "판정 미확인")} variant={assessmentVariant(perspective.assessment)} /></td>
                  <td>
                    <div>{present(perspective.reason, "판정 사유 미확인")}</div>
                    {perspective.evidence.length > 0 ? (
                      <div className="evidence-list">
                        {perspective.evidence.map((evidence) => (
                          <div className="evidence-row" key={evidence.id}>
                            <Badge label={evidenceLabel(evidence.status)} variant={evidenceVariant(evidence.status)} />
                            <span>{present(evidence.source, "출처 미확인")}</span>
                            <span className="evidence-fact">{present(evidence.fact, "근거 내용 미확인")}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="evidence-empty">근거 없음</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
