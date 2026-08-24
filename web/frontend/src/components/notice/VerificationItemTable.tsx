import { useMemo } from "react";
import { Badge, type BadgeVariant } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import type { ReviewAnswerInput, VerificationItemResponse } from "../../lib/types";
import { present } from "../../lib/format";

interface VerificationItemTableProps {
  items: VerificationItemResponse[];
  answers: ReviewAnswerInput[];
  onAnswerChange?: (item: string, answer: string) => void;
}

function statusVariant(status: string | null): BadgeVariant {
  if (status === "확인 완료") return "evidence-confirmed";
  if (status === "미확인") return "evidence-unknown";
  return "neutral";
}

export function VerificationItemTable({ items, answers, onAnswerChange }: VerificationItemTableProps) {
  const answersByItem = useMemo(
    () => new Map(answers.map((answer) => [answer.item ?? "", answer.answer ?? ""])),
    [answers],
  );
  return (
    <Panel
      className="verification-panel"
      title="확인 항목"
      action={
        <span className={items.some((item) => item.blocking) ? "verification-blocking-note" : "panel-note"}>
          {items.some((item) => item.blocking) ? `차단 ${items.filter((item) => item.blocking).length}건` : `${items.length}건`}
        </span>
      }
    >
      {items.length === 0 ? (
        <EmptyState compact title="확인 항목이 없습니다." />
      ) : (
        <div className="verification-list">
          {items.map((item) => {
            const itemLabel = item.item ?? "";
            return (
              <div className={`verification-row ${item.blocking ? "is-blocking" : ""}`.trim()} key={item.id}>
                <div className="verification-row-main">
                  {item.blocking ? <Badge label="차단" variant="alert" /> : null}
                  <div>
                    <strong>{present(item.item, "확인 항목 미확인")}</strong>
                    <p>{present(item.why, "확인 사유 미확인")}</p>
                  </div>
                  <Badge label={present(item.status, "미확인")} variant={statusVariant(item.status)} />
                </div>
                {onAnswerChange ? (
                  <input
                    aria-label={`${present(item.item, "확인 항목")} 답변`}
                    className="verification-answer-input"
                    placeholder="답변 기록"
                    value={answersByItem.get(itemLabel) ?? ""}
                    onChange={(event) => onAnswerChange(itemLabel, event.target.value)}
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
