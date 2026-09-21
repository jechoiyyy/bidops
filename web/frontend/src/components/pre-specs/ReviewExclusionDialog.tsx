import { useRef, useState } from "react";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { TextInput } from "@astryxdesign/core/TextInput";
import { TextArea } from "@astryxdesign/core/TextArea";
import { api } from "../../lib/api";
import type { PreSpecReviewExclusionResponse, PreSpecReviewExclusionStatus } from "../../lib/types";

export function ReviewExclusionDialog({ ids, status, onClose, onSaved }: {
  ids: number[];
  status: PreSpecReviewExclusionStatus;
  onClose: () => void;
  onSaved: (response: PreSpecReviewExclusionResponse) => Promise<void>;
}) {
  const [actor, setActor] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const submitting = useRef(false);
  const [error, setError] = useState(false);
  const action = status === "excluded" ? "검토 제외" : "검토 목록으로 복원";
  const valid = actor.trim().length > 0 && [...actor.trim()].length <= 128
    && reason.trim().length > 0 && [...reason.trim()].length <= 2000 && ids.length > 0 && ids.length <= 200;
  async function submit() {
    if (submitting.current || !valid) return;
    submitting.current = true;
    setPending(true);
    setError(false);
    try {
      const response = await api.changePreSpecReviewExclusions({ notice_ids: ids, status, actor_name: actor.trim(), reason: reason.trim() });
      await onSaved(response);
    } catch {
      setError(true);
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }
  function close() { if (!submitting.current) onClose(); }
  return <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}><Dialog isOpen onOpenChange={(open) => { if (!open) close(); }} purpose="form">
    <DialogHeader title={action} onOpenChange={close} />
    <form className="pre-specs-dialog-body" onSubmit={(event) => { event.preventDefault(); void submit(); }} style={{ display: "grid", gap: "var(--spacing-4)" }}>
      <p>대상 {ids.length}건 · 팀 전체에 적용됩니다.</p>
      <p>{status === "excluded" ? "일상 목록에서 숨겨지며 추적 상태와 자동 분석은 유지됩니다" : "복원 후 기존 보기 조건에 맞는 건만 일상 목록에 나타납니다. 추적 상태와 자동 분석은 유지됩니다."}</p>
      <TextInput label="담당자" description="최대 128자" value={actor} onChange={setActor} isRequired isDisabled={pending} />
      <TextArea label="사유" description="최대 2,000자" value={reason} onChange={setReason} isRequired isDisabled={pending} />
      {error ? <p role="alert">처리 결과를 확인하지 못했습니다. 입력과 선택을 유지했습니다. 다시 시도해 주세요.</p> : null}
      <Button label="취소" variant="secondary" isDisabled={pending} onClick={close} />
      <Button label={pending ? "처리 중…" : error ? "다시 시도" : action} isDisabled={!valid || pending} onClick={() => { void submit(); }} />
    </form>
  </Dialog></InternationalizationProvider>;
}
