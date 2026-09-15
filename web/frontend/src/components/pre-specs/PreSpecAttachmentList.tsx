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

function extractionTone(status: string | null): string {
  if (status === "completed") return "ps-chip-accent";
  if (status === "failed") return "ps-chip-err";
  return "ps-chip-neutral";
}

/**
 * 상세 ⑤의 첨부 표(docs/0915_ui-redesign/spec.md §4 ⑤).
 *
 * 목록이던 것을 `파일 · 형식·크기 · 본문 추출 · 열기` 네 칸 표로 바꾼다. 말하는
 * 사실은 그대로다 — 크기가 없으면 `크기 미확인`이고 0바이트는 `0 B`로 남으며,
 * 원본 열기는 검증된 절대 HTTP(S) 주소가 있을 때만 그린다.
 */
export function PreSpecAttachmentList({ attachments }: { attachments: AttachmentResponse[] }) {
  if (attachments.length === 0) return <p className="ps-cap ps-muted">첨부 없음 · 0건</p>;
  return (
    <table className="ps-table pre-specs-document-table" aria-label="첨부 파일 목록">
      <thead>
        <tr>
          <th scope="col">파일</th>
          <th scope="col">형식 · 크기</th>
          <th scope="col">본문 추출</th>
          <th scope="col" className="ps-table-end">열기</th>
        </tr>
      </thead>
      <tbody>
        {attachments.map((attachment) => {
          const original = collectedWebUrl(attachment.url);
          return (
            <tr key={attachment.id}>
              <td><strong>{attachment.name ?? "파일명 미확인"}</strong></td>
              <td className="ps-cap">
                {attachment.file_ext ?? "확장자 미확인"} · {attachment.size_bytes === null
                  ? "크기 미확인" : `${formatNumber(attachment.size_bytes)} B`}
              </td>
              <td>
                <span className={`ps-chip ${extractionTone(attachment.extract_status)}`}>
                  {extractionLabel(attachment.extract_status)}
                </span>
              </td>
              <td className="ps-table-end">
                <a className="ps-ref" href={api.attachmentDownloadUrl(attachment.id)}>다운로드</a>
                {original ? <a className="ps-ref" href={original} target="_blank" rel="noopener noreferrer">원본 열기</a> : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
