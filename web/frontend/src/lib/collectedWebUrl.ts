/** 수집된 절대 HTTP(S) 주소만 사용하고 URL 내 자격증명은 허용하지 않는다. */
export function collectedWebUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

/** 서버가 보관한 파일이 있을 때만 첨부 `url`이 내부 다운로드 경로다(`attachment_download_url`). */
export function storedAttachmentDownloadUrl(url: string | null): string | null {
  return url !== null && /^\/api\/attachments\/\d+\/download$/.test(url) ? url : null;
}

/**
 * 첨부 한 건의 `원본 열기` 주소. 내부 다운로드 경로가 있으면 원본 열기는 그리지 않으므로 `null`이고, 없으면
 * 검증된 절대 HTTP(S) 주소만 쓴다. 첨부 표(`PreSpecAttachmentList`)와 문제 상태 안내가 같은 판정을 쓴다.
 */
export function attachmentOriginalUrl(url: string | null): string | null {
  return storedAttachmentDownloadUrl(url) === null ? collectedWebUrl(url) : null;
}
