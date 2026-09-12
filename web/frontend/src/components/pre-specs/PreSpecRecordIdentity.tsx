import { useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { ArrowUpRight, Copy } from "lucide-react";
import { collectedWebUrl } from "../../lib/collectedWebUrl";

export function PreSpecRecordIdentity({ number, url }: { number: string | null; url: string | null }) {
  const [message, setMessage] = useState("");
  const href = collectedWebUrl(url);
  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(() => setMessage(""), 4500);
    return () => window.clearTimeout(timer);
  }, [message]);
  async function copy() {
    if (!number) return;
    try {
      if (window.isSecureContext && navigator.clipboard) await navigator.clipboard.writeText(number);
      else {
        // Private-network HTTP may not expose Clipboard API. Restore focus after
        // the fallback so keyboard users stay at the copy action.
        const active = document.activeElement;
        const field = document.createElement("textarea");
        field.value = number; field.className = "ps-record-clipboard-helper";
        document.body.append(field);
        let copied = false;
        try { field.select(); copied = document.execCommand("copy"); }
        finally { field.remove(); if (active instanceof HTMLElement) active.focus({ preventScroll: true }); }
        if (!copied) throw new Error("clipboard-unavailable");
      }
      setMessage("사전규격번호를 복사했습니다.");
    } catch { setMessage("복사하지 못했습니다. 표시된 번호를 선택해 복사해 주세요."); }
  }
  return <div className="ps-record-identity">
    <div className="ps-record-number-group"><span>사전규격번호</span><strong className="ps-record-number">{number ?? "미확인"}</strong><Button label="번호 복사" variant="ghost" size="sm" icon={<Copy />} isDisabled={!number} onClick={() => { void copy(); }} /></div>
    {href ? <Button label="나라장터 원문" size="sm" icon={<ArrowUpRight />} href={href} target="_blank" rel="noopener noreferrer" tooltip="새 탭에서 원문 열기" /> : <span className="ps-record-source-unavailable">{url ? "원문 URL 확인 불가" : "원문 URL 없음"}</span>}
    {message ? <span className="ps-record-copy-feedback" role="status">{message}</span> : null}
  </div>;
}
