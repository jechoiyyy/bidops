import type { ComponentProps } from "react";
import { FlowSteps } from "../common/FlowSteps";
import { StatusMark } from "../common/Marks";
import { Link } from "react-router-dom";
import { recordRoute, stageOfLink } from "../opportunities/trackingFlow";
import { formatKstDay, stageLabelAt, STAGE_STATE_LABEL, type RecordDecisionAxis } from "../../lib/record";
import type { OpportunityLinkView, OpportunityStageEntry } from "../../lib/types";

interface StageBarProps {
  stages: readonly OpportunityStageEntry[];
  links?: readonly OpportunityLinkView[];
  /** 사람 확인 대기 후보 연결(`isPendingCandidate`). 단계별로 센다. */
  candidates?: readonly OpportunityLinkView[];
  /** 결정 축 요약의 최종 Go/No-Go(`recordDecisionAxes`의 `go_no_go`). 없으면 칸을 그리지 않는다. */
  goNoGo?: RecordDecisionAxis | null;
}

function plannedLabel(link: OpportunityLinkView): string | null {
  let year = link.planned_order_year?.trim();
  let month = link.planned_order_month?.trim();
  // 수집 원문에 따라 월이 `2026-09`처럼 연도를 품고 오기도 한다. 그 경우 그 연·월을 그대로 읽는다.
  const combined = /^(\d{4})-(\d{1,2})$/.exec(month ?? "");
  if (combined) {
    year = combined[1];
    month = combined[2];
  }
  if (!year && !month) return null;
  const monthNumber = month ? Number(month) : NaN;
  const monthText = Number.isFinite(monthNumber) && monthNumber > 0 ? `${monthNumber}월` : month ? `${month}월` : "";
  return `${year ? `${year}년 ` : ""}${monthText} 발주 예정`.trim();
}

function budgetLabel(value: number | null): string | null {
  return value === null ? null : `${Math.round(value).toLocaleString("ko-KR")}원`;
}

/** 권위 연결 한 줄: 발주계획은 발주 예정 · 예산, 공고는 제목 · 마감 · 금액. 값이 없으면 그 조각을 뺀다. */
function linkFacts(index: number, link: OpportunityLinkView): { main: string | null; sub: string | null } {
  const externalId = link.record_external_id || link.external_id || null;
  if (index === 0) {
    const main = [plannedLabel(link), budgetLabel(link.budget)].filter(Boolean).join(" · ") || null;
    return { main, sub: externalId ? `계획번호 ${externalId}` : null };
  }
  const deadline = formatKstDay(link.deadline_at);
  const main = link.title?.trim() || null;
  const sub = [deadline ? `${deadline} ${index === 1 ? "의견 마감" : "마감"}` : null, budgetLabel(link.budget), externalId].filter(Boolean).join(" · ") || null;
  return { main, sub };
}

const PENDING_NOTE: Record<number, string> = {
  1: "사전규격이 올라오면 이 흐름에 연결돼요.",
  2: "공고가 올라오면 사전규격과 달라진 점을 비교할 수 있어요.",
};

export function StageBar({ stages, links = [], candidates = [], goNoGo = null }: StageBarProps) {
  const byId = new Map(links.map((link) => [link.id, link] as const));
  const steps: ComponentProps<typeof FlowSteps>["steps"] = stages.map((stage, index) => {
    const label = stageLabelAt(index, stage);
    const day = stage.state === "pending" || stage.state === "unknown" ? null : formatKstDay(stage.at);
    const link = index < 3 && stage.link_id !== null ? byId.get(stage.link_id) ?? null : null;
    const to = link ? recordRoute(link) : null;
    const stageCandidates = index < 3 && !link ? candidates.filter((candidate) => stageOfLink(candidate) === label) : [];
    const facts = link ? linkFacts(index, link) : null;
    const awaitingSource = index < 3 && !link && stageCandidates.length === 0 && stage.state === "pending";
    return {
      label,
      state: stage.state === "pending" || stage.state === "upcoming_deadline" ? "todo" : stage.state,
      status: stage.state === "upcoming_deadline" ? "warning" : undefined,
      action: (
        <div className="rec-stage-details" data-stage={label} data-state={stage.state}>
          <div className="rec-stage-meta">
            <span>{STAGE_STATE_LABEL[stage.state]}</span>
            {day ? <span>{day}</span> : null}
            {stageCandidates.length > 0 ? <StatusMark mark={{ label: "후보 확인 대기", tone: "warning" }} /> : null}
            {awaitingSource ? <span>아직 없음</span> : null}
          </div>
          {to ? <Link className="rec-stage-link" title={`${label} 열기`} to={to}>{label} · 공식 연결</Link>
            : link ? <span>공식 연결</span> : null}
          {facts?.main ? <span>{facts.main}</span> : null}
          {facts?.sub ? <small>{facts.sub}</small> : null}
          {stageCandidates.length > 0 ? (
            <>
              <span>이름 검색으로 찾은 후보가 {stageCandidates.length}건 있어요.</span>
              <small>같은 사업으로 확인하면 이 흐름에 연결돼요.</small>
            </>
          ) : null}
          {awaitingSource && PENDING_NOTE[index] ? <small>{PENDING_NOTE[index]}</small> : null}
        </div>
      ),
    };
  });
  return (
    <div data-testid="stage-bar">
      <FlowSteps active={stages.findIndex((stage) => stage.state === "current")} label="사업 단계" steps={steps} vertical />
      {goNoGo ? (
        <div className="rec-flow-decision" data-testid="stage-flow-go-no-go">
          <strong>{goNoGo.label}</strong>
          <span>{goNoGo.value}</span>
          <small>입찰 참여는 사람이 따로 정해요. 추적을 시작해도 Go로 정해지지 않아요.</small>
        </div>
      ) : null}
    </div>
  );
}
