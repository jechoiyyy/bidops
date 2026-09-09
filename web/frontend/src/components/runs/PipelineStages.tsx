import { Check, CircleDashed, Clock3, TriangleAlert } from "lucide-react";
import { Text } from "@astryxdesign/core/Text";
import type { RunCounts, PipelineStageResponse } from "../../lib/types";
import { formatNumber, present } from "../../lib/format";
import { Caption } from "./RunStatusPrimitives";

type RunnableStage = "collect" | "sample" | "report";

export const stageMeta: Record<string, { title: string; runnable?: RunnableStage }> = {
  collect_normalize: { title: "수집·정규화", runnable: "collect" },
  sample: { title: "표본 선정", runnable: "sample" },
  judgment: { title: "공고 판정" },
  report: { title: "보고 생성", runnable: "report" },
};

export function stageTitle(stage: PipelineStageResponse): string {
  return stageMeta[stage.name]?.title ?? present(stage.name, "단계 미확인");
}

export function stageStatusLabel(status: string): string {
  if (status === "running") return "진행 중";
  if (status === "pending") return "대기 중";
  if (status === "failed") return "실패";
  if (status === "not_available") return "대기";
  return "완료";
}

/** 서버가 준 단계 건수. 수집·정규화 건수와 판정 후보·시도 건수를 섞지 않는다. */
export function stageDetail(stage: PipelineStageResponse, counts: RunCounts): string {
  const collection = counts.collection;
  if (stage.name === "collect_normalize") {
    const total = typeof collection.total === "number" ? collection.total : null;
    const candidate = typeof collection.candidate_pool === "number" ? collection.candidate_pool : null;
    return `수집 ${formatNumber(total)} · 후보 ${formatNumber(candidate)}`;
  }
  if (stage.name === "sample") return `표본 ${formatNumber(counts.notices)}건`;
  if (stage.name === "judgment") return `판정 ${formatNumber(counts.judgments)}건`;
  return "보고 산출물";
}

function StageIcon({ status }: { status: string }) {
  if (status === "failed") return <TriangleAlert aria-hidden="true" />;
  if (status === "running" || status === "pending") return <Clock3 aria-hidden="true" />;
  if (status === "not_available") return <CircleDashed aria-hidden="true" />;
  return <Check aria-hidden="true" />;
}

/**
 * 파이프라인 단계 띠. 시안의 4칸 stage track이며 실제 `PipelineStageResponse`를
 * 그대로 읽는다. 단계 실행 조작은 이 띠가 아니라 `PipelineControlsDialog`에
 * 있다 — 기본 화면을 큰 실행 폼이 차지하지 않게 하되 조작을 없애지 않는다.
 */
export function PipelineStageTrack({ stages, counts }: { stages: PipelineStageResponse[]; counts: RunCounts }) {
  if (stages.length === 0) {
    return <Caption>이 회차의 파이프라인 단계 기록이 없습니다. 없음을 완료로 읽지 않습니다.</Caption>;
  }
  return (
    <div className="rs-stage-track" aria-label="파이프라인 단계">
      {stages.map((stage) => (
        <div className={`rs-stage${stage.status === "running" ? " is-current" : ""}`} key={stage.name}>
          <span className="rs-stage-name">
            <StageIcon status={stage.status} />
            <Text as="span" weight="semibold">{stageTitle(stage)}</Text>
          </span>
          <Caption as="span">{stageStatusLabel(stage.status)}</Caption>
          <Caption as="span">{stageDetail(stage, counts)}</Caption>
        </div>
      ))}
    </div>
  );
}
