import type { ReactNode } from "react";

export type MutationFeedbackTone = "info" | "success" | "warning" | "error";

interface MutationFeedbackProps {
  children: ReactNode;
  className?: string;
  tone?: MutationFeedbackTone;
}

/** Mutation 결과를 색뿐 아니라 문구와 live-region 의미로 전달한다. */
export function MutationFeedback({ children, className = "", tone = "info" }: MutationFeedbackProps) {
  const isError = tone === "error";
  return (
    <div
      className={`mutation-feedback mutation-feedback-${tone} ${className}`.trim()}
      role={isError ? "alert" : "status"}
      aria-live={isError ? "assertive" : "polite"}
      aria-atomic="true"
    >
      {children}
    </div>
  );
}
