import { attachmentOriginalUrl, storedAttachmentDownloadUrl } from "../../lib/collectedWebUrl";
import { formatFileSize, formatNumber } from "../../lib/format";
import type { AttachmentResponse } from "../../lib/types";

// `attachment.extract_status`는 옛 본문 추출 열이다. 사전규격 첨부는 거의 모두 null이고, 값이 있을 때만
// 알려 줄 것이 있다(`provider_unsupported_excluded`: 허용 형식 밖이라 문서 준비에서 제외, contracts §prespec-overview).
const EXTRACTION_LABELS: Record<string, string> = {
  completed: "본문 추출 완료",
  pending: "본문 추출 대기",
  failed: "본문 추출 실패",
  provider_unsupported_excluded: "지원하지 않는 형식 · 문서 준비에서 제외",
};

function extractionTone(status: string): string {
  if (status === "completed") return "ps-chip-accent";
  if (status === "failed") return "ps-chip-err";
  return "ps-chip-neutral";
}

/**
 * 상세 ⑤의 첨부 표(docs/0915_ui-redesign/spec.md §4 ⑤).
 *
 * `파일 · 형식·크기 · (처리 상태) · 열기` 표다. 크기가 없으면 `크기 미확인`이고 0바이트는 `0 B`로
 * 남는다. 크기는 읽기 쉬운 단위로 적고 정확한 바이트 수는 title로 남긴다.
 *
 * 나라장터 사전규격 목록은 첨부를 주소로만 줘서 `name`이 자리표시자("첨부 1")다. 서버가
 * 원문을 내려받아 실제 파일명·형식·크기를 알면(`acquired_file`) 그 값을 보이고, 모르면
 * 목록 값 그대로 둔다 — 화면이 이름을 추정하지 않는다.
 *
 * 열기 칸은 **실제로 열리는 것만** 그린다. `다운로드`는 서버가 보관한 파일이 있을 때(`url`이 내부
 * 다운로드 경로)만, `원본 열기`는 검증된 절대 HTTP(S) 주소가 있을 때만이다. 나라장터에서 받은 원문은
 * 내부 다운로드 경로가 없어 예전에는 `다운로드`가 404였다(2026-11-21).
 *
 * 처리 상태 칸은 값이 하나라도 있을 때만 그린다. 전부 null인 표에 `미확인` 칩만 줄지어 서지 않게 한다.
 */
export function PreSpecAttachmentList({ attachments }: { attachments: AttachmentResponse[] }) {
  if (attachments.length === 0) return <p className="ps-cap ps-muted">첨부 없음 · 0건</p>;
  const showExtraction = attachments.some((attachment) => attachment.extract_status !== null);
  return (
    <table className="ps-table pre-specs-document-table" aria-label="첨부 파일 목록">
      <thead>
        <tr>
          <th scope="col">파일</th>
          <th scope="col">형식 · 크기</th>
          {showExtraction ? <th scope="col">처리 상태</th> : null}
          <th scope="col" className="ps-table-end">열기</th>
        </tr>
      </thead>
      <tbody>
        {attachments.map((attachment) => {
          const download = storedAttachmentDownloadUrl(attachment.url);
          const original = attachmentOriginalUrl(attachment.url);
          const acquired = attachment.acquired_file ?? null;
          const sizeBytes = acquired?.size_bytes ?? attachment.size_bytes;
          return (
            <tr key={attachment.id}>
              <td><strong>{acquired?.filename ?? attachment.name ?? "파일명 미확인"}</strong></td>
              <td className="ps-cap">
                {acquired?.file_ext ?? attachment.file_ext ?? "확장자 미확인"} · {sizeBytes === null
                  ? "크기 미확인"
                  : <span title={`${formatNumber(sizeBytes)} B`}>{formatFileSize(sizeBytes)}</span>}
              </td>
              {showExtraction ? (
                <td>
                  {attachment.extract_status === null
                    ? <span className="ps-cap ps-muted">미확인</span>
                    : (
                      <span className={`ps-chip ${extractionTone(attachment.extract_status)}`}>
                        {EXTRACTION_LABELS[attachment.extract_status] ?? attachment.extract_status}
                      </span>
                    )}
                </td>
              ) : null}
              <td className="ps-table-end">
                {download ? <a className="ps-ref" href={download}>다운로드</a> : null}
                {original ? <a className="ps-ref" href={original} target="_blank" rel="noopener noreferrer">원본 열기</a> : null}
                {!download && !original ? <span className="ps-cap ps-muted">열 수 있는 주소 없음</span> : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
