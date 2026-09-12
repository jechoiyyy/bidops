/** 수집된 절대 HTTP(S) 주소만 사용하고 URL 내 자격증명은 허용하지 않는다. */
export function collectedWebUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
