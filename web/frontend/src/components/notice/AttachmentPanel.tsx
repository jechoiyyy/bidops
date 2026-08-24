import { Badge } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import type { AttachmentResponse } from "../../lib/types";
import { present } from "../../lib/format";

interface AttachmentPanelProps {
  attachments: AttachmentResponse[];
}

function extension(attachment: AttachmentResponse): string {
  if (attachment.file_ext?.trim()) return attachment.file_ext.toUpperCase();
  const name = attachment.name?.split(".").pop();
  return name && name !== attachment.name ? name.toUpperCase() : "파일";
}

export function AttachmentPanel({ attachments }: AttachmentPanelProps) {
  return (
    <Panel
      className="notice-attachments-panel"
      title="첨부 문서"
      action={<Badge label={attachments.length ? `확보 ${attachments.length}건` : "미확보"} variant={attachments.length ? "grade-2" : "neutral"} />}
    >
      {attachments.length === 0 ? (
        <EmptyState compact title="첨부 문서가 없습니다." description="이번 단계에서는 읽기 전용으로 표시합니다." />
      ) : (
        <div className="attachment-list">
          {attachments.map((attachment) => (
            <div className="attachment-row" key={attachment.id}>
              <span className="attachment-ext">{extension(attachment)}</span>
              <span className="attachment-name">{present(attachment.name, "파일명 미확인")}</span>
              <Badge label={attachment.extract_status === "completed" ? "본문 추출" : "원문"} variant={attachment.extract_status === "completed" ? "evidence-confirmed" : "neutral"} />
              {attachment.url ? (
                <a className="attachment-link" href={attachment.url} target="_blank" rel="noreferrer" aria-label={`${present(attachment.name, "첨부 문서")} 원문 열기`}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
                    <path d="M14 5h5v5M19 5l-8 8" />
                    <path d="M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
                  </svg>
                </a>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
