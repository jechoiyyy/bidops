import { StatusMark, type MarkTone } from "../common/Marks";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import { ReviewEvidenceList } from "../common/ReviewPrimitives";
import type { PerspectiveResponse } from "../../lib/types";
import { present } from "../../lib/format";

interface PerspectiveTableProps {
  perspectives: PerspectiveResponse[];
}

function assessmentLevel(value: string | null): number | undefined {
  if (value === "적합") return 2;
  if (value === "부분 적합") return 3;
  if (value === "부적합") return 4;
  return undefined;
}

function evidenceTone(status: string | null): MarkTone {
  if (status === "confirmed") return "accent";
  if (status === "inferred") return "info";
  return "neutral";
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
        <EmptyState compact title="관점별 판단이 없어요" />
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
                  <td><StatusMark gradeLevel={assessmentLevel(perspective.assessment)} mark={{ label: present(perspective.assessment, "판정 미확인"), tone: "neutral" }} /></td>
                  <td>
                    <div>{present(perspective.reason, "판정 사유 미확인")}</div>
                    {perspective.evidence.length > 0 ? (
                    <details className="evidence-details" open>
                      <summary>근거 {perspective.evidence.length}개</summary>
                        <ReviewEvidenceList
                          className="evidence-list"
                          items={perspective.evidence.map((evidence) => ({
                            detail: present(evidence.fact, "근거 내용 미확인"),
                            id: evidence.id,
                            startContent: <StatusMark mark={{ label: evidenceLabel(evidence.status), tone: evidenceTone(evidence.status) }} />,
                            title: present(evidence.source, "출처 미확인"),
                          }))}
                          label={`${present(perspective.name, "관점 미확인")} 근거`}
                        />
                      </details>
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
