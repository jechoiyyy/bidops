import { api } from "../../lib/api";
import { collectedWebUrl } from "../../lib/collectedWebUrl";
import { formatNumber } from "../../lib/format";
import type { AttachmentResponse } from "../../lib/types";

function extractionLabel(status: string | null): string {
  if (status === "completed") return "본문 추출 완료";
  if (status === "pending") return "본문 추출 대기";
  if (status === "failed") return "본문 추출 실패";
  return status ?? "본문 추출 미확인";
}

export function PreSpecAttachmentList({ attachments }: { attachments: AttachmentResponse[] }) {
  if (attachments.length === 0) return <p className="ps-cap ps-muted">첨부 없음 · 0건</p>;
  return (
    <ul className="pre-specs-document-list" aria-label="첨부 파일 목록">
      {attachments.map((attachment) => {
        const original = collectedWebUrl(attachment.url);
        return (
          <li key={attachment.id}>
            <strong>{attachment.name ?? "파일명 미확인"}</strong>
            <span>
              {attachment.file_ext ?? "확장자 미확인"} · {attachment.size_bytes === null
                ? "크기 미확인" : `${formatNumber(attachment.size_bytes)} B`}
              {" · "}{extractionLabel(attachment.extract_status)}
            </span>
            <span>
              <a href={api.attachmentDownloadUrl(attachment.id)}>다운로드</a>
              {original ? <> · <a href={original} target="_blank" rel="noopener noreferrer">원본 열기</a></> : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
