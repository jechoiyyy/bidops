import type { RunCounts, PipelineStageResponse } from "../../lib/types";
import { formatNumber, present } from "../../lib/format";

type RunnableStage = "collect" | "sample" | "report";

interface PipelineStagesProps {
  stages: PipelineStageResponse[];
  counts: RunCounts;
  onRun: (stage: RunnableStage) => void;
  busy: boolean;
}

const stageMeta: Record<string, { title: string; number: string; runnable?: RunnableStage }> = {
  collect_normalize: { title: "수집·정규화", number: "1", runnable: "collect" },
  sample: { title: "표본 선정", number: "2", runnable: "sample" },
  judgment: { title: "에이전트 판정", number: "3" },
  report: { title: "보고 생성", number: "4", runnable: "report" },
};

function statusLabel(status: string): string {
  if (status === "running") return "진행 중";
  if (status === "pending") return "대기 중";
  if (status === "failed") return "실패";
  if (status === "not_available") return "대기";
  return "완료";
}

function stageDetail(stage: PipelineStageResponse, counts: RunCounts): string[] {
  const collection = counts.collection;
  if (stage.name === "collect_normalize") {
    return [
      `${formatNumber(typeof collection.total === "number" ? collection.total : null)}건 수집`,
      `후보 ${formatNumber(typeof collection.candidate_pool === "number" ? collection.candidate_pool : null)} · 감사 ${formatNumber(typeof collection.audit_pool === "number" ? collection.audit_pool : null)}`,
    ];
  }
  if (stage.name === "sample") {
    return [`표본 ${formatNumber(counts.notices)}건`, "분석·감사 층 순환 배정"];
  }
  if (stage.name === "judgment") {
    return [`${formatNumber(counts.judgments)}건 판정`, stage.message ?? "판정 파일을 적재하면 화면에 반영됩니다."];
  }
  return ["주간 보고서와 상세 보고서", "스크립트 산출물 기준"];
}

export function PipelineStages({ stages, counts, onRun, busy }: PipelineStagesProps) {
  return (
    <section className="runs-stages" aria-label="파이프라인 단계">
      {stages.map((stage) => {
        const meta = stageMeta[stage.name] ?? { title: present(stage.name, "단계 미확인"), number: "·" };
        const runnable = meta.runnable && stage.execution_allowed;
        const details = stageDetail(stage, counts);
        return (
          <article className={`runs-stage ${stage.status === "complete" ? "is-complete" : ""} ${stage.status === "failed" ? "is-failed" : ""}`.trim()} key={stage.name}>
            <div className="runs-stage-heading">
              <span className={`runs-stage-number ${stage.status === "not_available" ? "is-idle" : ""}`.trim()}>{meta.number}</span>
              <h3>{meta.title}</h3>
              <span className={`runs-status runs-status-${stage.status}`}>{statusLabel(stage.status)}</span>
            </div>
            <div className="runs-stage-details">
              {details.map((detail) => <div key={detail}>{detail}</div>)}
              <code>{present(stage.script, "스크립트 미확인")}</code>
              {stage.exit_code !== null && stage.status === "failed" ? <div>종료 코드 {stage.exit_code}</div> : null}
            </div>
            {runnable ? (
              <button className="runs-stage-button" type="button" disabled={busy || stage.status === "running"} onClick={() => onRun(meta.runnable as RunnableStage)}>
                {stage.status === "running" ? "실행 중" : `${meta.title} 실행`}
              </button>
            ) : null}
            {stage.message ? <p className="runs-stage-message">{stage.message}</p> : null}
          </article>
        );
      })}
    </section>
  );
}
