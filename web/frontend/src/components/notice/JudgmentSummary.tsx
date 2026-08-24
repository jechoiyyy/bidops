import { Badge, type BadgeVariant } from "../common/Badge";
import { Panel } from "../common/Panel";
import type { JudgmentResponse } from "../../lib/types";

interface JudgmentSummaryProps {
  judgment: JudgmentResponse | null;
}

function gradeVariant(grade: string | null): BadgeVariant {
  if (grade === "우선 검토") return "grade-1";
  if (grade === "검토 권장") return "grade-2";
  if (grade === "관찰 대상") return "grade-3";
  if (grade === "제외") return "grade-4";
  return "neutral";
}

export function JudgmentSummary({ judgment }: JudgmentSummaryProps) {
  const verificationItems = judgment?.verification_items ?? [];
  const blockingCount = verificationItems.filter((item) => item.blocking).length;
  return (
    <Panel
      className="notice-summary-panel"
      title="종합 권고"
      action={<span className="panel-note">확인 항목 {verificationItems.length} · 차단 {blockingCount}</span>}
    >
      <div className="notice-summary-badges">
        <Badge label={judgment?.grade} variant={gradeVariant(judgment?.grade ?? null)} />
        <Badge label={judgment?.readiness} variant="readiness" />
        <Badge label={judgment?.primary_focus} variant="focus" />
      </div>
      <p className="notice-summary-text">{judgment?.summary?.trim() || "종합 권고가 없습니다."}</p>
      <div className="notice-summary-next">
        <span>다음 행동</span>
        <strong>{judgment?.next_action?.trim() || "다음 행동 미확인"}</strong>
      </div>
    </Panel>
  );
}
