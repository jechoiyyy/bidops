import { Panel } from "../common/Panel";
import type { NoticeDetailResponse } from "../../lib/types";
import { formatDate, formatDateTime, present } from "../../lib/format";

interface LifecycleTimelineProps {
  notice: NoticeDetailResponse;
}

type LifecycleState = "active" | "uncollected" | "missing" | "disabled";

interface LifecycleStage {
  label: string;
  detail: string;
  state: LifecycleState;
  detailMono?: boolean;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function textValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value.trim() || null;
  return String(value);
}

function stageClass(state: LifecycleState): string {
  return `lifecycle-stage lifecycle-stage-${state}`;
}

export function LifecycleTimeline({ notice }: LifecycleTimelineProps) {
  const lifecycle = record(notice.lifecycle);
  const preSpecNo = textValue(lifecycle.pre_spec_no);
  const changedAt = textValue(lifecycle.changed_at);
  const changeReason = textValue(lifecycle.change_reason);
  const review = notice.reviews.find((item) => Boolean(item.disposition?.trim()));
  const stages: LifecycleStage[] = [
    {
      label: "사전규격",
      detail: preSpecNo ? `${preSpecNo} · 본문 미수집` : "번호 없음",
      state: preSpecNo ? "uncollected" : "disabled",
      detailMono: Boolean(preSpecNo),
    },
    {
      label: "본공고",
      detail: notice.published_at ? formatDateTime(notice.published_at) : "일자 미확인",
      state: notice.published_at ? "active" : "disabled",
      detailMono: Boolean(notice.published_at),
    },
    {
      label: "정정",
      detail: changedAt ? formatDateTime(changedAt) : changeReason ? changeReason : "정정 기록 없음",
      state: changedAt || changeReason ? "active" : "disabled",
      detailMono: Boolean(changedAt),
    },
    {
      label: "판정",
      detail: notice.judgment ? "판정 기록 있음" : "미진행",
      state: notice.judgment ? "active" : "disabled",
    },
    {
      label: "승인",
      detail: review ? present(review.disposition, "리뷰 기록 있음") : "미진행",
      state: review ? "active" : "disabled",
    },
    {
      label: "마감",
      detail: notice.deadline_at ? formatDate(notice.deadline_at) : "일자 미기재",
      state: notice.deadline_at ? "active" : "missing",
      detailMono: Boolean(notice.deadline_at),
    },
  ];

  return (
    <Panel
      className="lifecycle-panel"
      title="공고 생애주기"
      action={<span className="panel-note">사전규격 본문은 미수집</span>}
    >
      <div className="lifecycle-timeline" aria-label="공고 생애주기 여섯 단계">
        {stages.map((stage, index) => (
          <div className="lifecycle-segment" key={stage.label}>
            <div className={stageClass(stage.state)}>
              <span className="lifecycle-dot" aria-hidden="true" />
              <span className="lifecycle-label">{stage.label}</span>
              <span className={`lifecycle-detail ${stage.detailMono ? "mono tabular-nums" : ""}`.trim()}>{stage.detail}</span>
            </div>
            {index < stages.length - 1 ? <span className={`lifecycle-line lifecycle-line-${stage.state}`} aria-hidden="true" /> : null}
          </div>
        ))}
      </div>
    </Panel>
  );
}
