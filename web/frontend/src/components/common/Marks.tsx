import type { CSSProperties } from "react";
import { Token, type TokenColor, type TokenProps } from "@astryxdesign/core/Token";
import type { DeadlineUrgency } from "../../lib/deadline";

export type MarkTone = "accent" | "warning" | "error" | "info" | "confirmed" | "success" | "neutral";

export interface Mark {
  label: string;
  tone: MarkTone;
}

const TONE_FILL: Record<MarkTone, { color: TokenColor; style?: CSSProperties }> = {
  accent: { color: "default", style: { backgroundColor: "var(--color-accent-muted)", color: "var(--color-success)" } },
  warning: { color: "default", style: { backgroundColor: "var(--color-warning-muted)", color: "var(--color-warning)" } },
  error: { color: "default", style: { backgroundColor: "var(--color-error-muted)", color: "var(--color-error)" } },
  info: { color: "purple" },
  confirmed: { color: "default", style: { backgroundColor: "var(--color-success-muted)", color: "var(--color-success)" } },
  // 운영 목록에서 완료·정상은 중립 채움을 쓴다.
  success: { color: "default" },
  neutral: { color: "default" },
};

interface StatusMarkProps extends Pick<TokenProps, "className" | "description" | "icon"> {
  mark: Mark;
  gradeLevel?: number;
  "data-mark"?: string;
  "data-testid"?: string;
}

export function StatusMark({ mark, className, description, gradeLevel, icon, "data-mark": marker, "data-testid": testId }: StatusMarkProps) {
  const fill = TONE_FILL[mark.tone];
  return (
    <Token
      className={className ? `workbench-mark ${className}` : "workbench-mark"}
      data-tone={mark.tone}
      data-grade-level={gradeLevel}
      data-review-primitive={gradeLevel === undefined ? undefined : "grade"}
      data-mark={marker}
      data-testid={testId}
      size="sm"
      color={fill.color}
      style={fill.style}
      label={mark.label}
      icon={icon}
      description={description}
    />
  );
}

export function ClassTag({ label }: { label: string }) {
  return <Token size="sm" color="default" label={label} />;
}

const DEADLINE_LEVEL: Record<DeadlineUrgency, "urgent" | "soon" | "normal" | "none"> = {
  critical: "urgent",
  soon: "soon",
  later: "normal",
  passed: "normal",
  none: "none",
};

export function DeadlineText({ text, urgency }: { text: string; urgency: DeadlineUrgency }) {
  return <span className="workbench-deadline" data-level={DEADLINE_LEVEL[urgency]}>{text}</span>;
}
