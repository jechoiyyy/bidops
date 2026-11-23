import { FlowSteps } from "../common/FlowSteps";
import type { NoticeDetailResponse } from "../../lib/types";
import { formatDate, formatDateTime, present } from "../../lib/format";

interface LifecycleTimelineProps {
  notice: NoticeDetailResponse;
}

type LifecycleState = "done" | "unknown" | "todo";

interface LifecycleStage {
  label: string;
  detail: string;
  state: LifecycleState;
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
      state: "unknown",
    },
    {
      label: "본공고",
      detail: notice.published_at ? formatDateTime(notice.published_at) : "일자 미확인",
      state: notice.published_at ? "done" : "unknown",
    },
    {
      label: "정정",
      detail: changedAt ? formatDateTime(changedAt) : changeReason ? changeReason : "정정 기록 없음",
      state: changedAt || changeReason ? "done" : "todo",
    },
    {
      label: "판정",
      detail: notice.judgment ? "판정 기록 있음" : "미진행",
      state: notice.judgment ? "done" : "todo",
    },
    {
      label: "승인",
      detail: review ? present(review.disposition, "리뷰 기록 있음") : "미진행",
      state: review ? "done" : "todo",
    },
    {
      label: "마감",
      detail: notice.deadline_at ? formatDate(notice.deadline_at) : "일자 미기재",
      state: notice.deadline_at ? "todo" : "unknown",
    },
  ];

  return <FlowSteps
    active={-1}
    label="공고 생애주기 여섯 단계"
    steps={stages.map(({ label, detail, state }) => ({ label, description: detail, state }))}
    vertical
  />;
}
