import type { ArtifactValidationResponse } from "../../lib/types";
import { present } from "../../lib/format";

interface ArtifactValidationProps {
  artifacts: ArtifactValidationResponse[];
  warningCounts: Record<string, number>;
}

export function ArtifactValidation({ artifacts, warningCounts }: ArtifactValidationProps) {
  const warningTotal = Object.values(warningCounts).reduce((sum, value) => sum + value, 0);
  return (
    <section className="panel runs-panel">
      <div className="panel-header">
        <h3>산출물과 스키마 검증</h3>
        <span className={`runs-status ${warningTotal ? "runs-status-failed" : "runs-status-complete"}`}>
          {warningTotal ? `경고 ${warningTotal}건` : "계약 통과"}
        </span>
      </div>
      <div className="panel-body runs-artifact-body">
        <div className="runs-artifact-table-scroll">
          <table className="runs-artifact-table">
            <thead><tr><th>파일</th><th>스키마</th><th>검증</th></tr></thead>
            <tbody>
              {artifacts.map((artifact) => (
                <tr key={artifact.name}>
                  <td><code>{artifact.name}</code></td>
                  <td><code>{present(artifact.schema_version, artifact.present ? "스키마 미확인" : "산출물 없음")}</code></td>
                  <td>
                    <span className={`runs-status ${artifact.valid === true && artifact.warnings.length === 0 ? "runs-status-complete" : artifact.present ? "runs-status-failed" : "runs-status-idle"}`}>
                      {artifact.valid === true && artifact.warnings.length === 0 ? "통과" : artifact.present ? "경고" : "미생성"}
                    </span>
                    {artifact.warnings.map((warning) => <div className="runs-artifact-warning" key={warning}>{warning}</div>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {artifacts.length === 0 ? <p className="runs-empty-value">검증할 산출물이 없습니다.</p> : null}
      </div>
    </section>
  );
}
