import { useMemo } from "react";
import { StatusMark } from "../common/Marks";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import type { ReviewAnswerInput, VerificationItemResponse } from "../../lib/types";
import { present } from "../../lib/format";

interface VerificationItemTableProps {
  items: VerificationItemResponse[];
  answers: ReviewAnswerInput[];
  onAnswerChange?: (item: string, answer: string) => void;
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
        <EmptyState compact title="확인 항목이 없어요" />
      ) : (
        <div className="verification-list">
          {items.map((item) => {
            const itemLabel = item.item ?? "";
            return (
              <div className={`verification-row ${item.blocking ? "is-blocking" : ""}`.trim()} key={item.id}>
                <div className="verification-row-main">
                  {item.blocking ? <StatusMark mark={{ label: "차단", tone: "error" }} /> : null}
                  <div>
                    <strong>{present(item.item, "확인 항목 미확인")}</strong>
                    <p>{present(item.why, "확인 사유 미확인")}</p>
                  </div>
                  <StatusMark mark={{ label: present(item.status, "미확인"), tone: item.status === "확인 완료" ? "accent" : "neutral" }} />
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
