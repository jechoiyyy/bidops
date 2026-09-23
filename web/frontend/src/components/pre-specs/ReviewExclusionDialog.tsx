import { useId, useRef, useState } from "react";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { ActorField } from "../common/ActorField";
import {
  BULK_EXCLUSION_REASONS,
  BulkReasonField,
  bulkReasonError,
  bulkReasonText,
  emptyBulkReason,
  type BulkReasonDraft,
} from "../common/BulkReasonField";
import { api } from "../../lib/api";
import { describeApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import type { PreSpecReviewExclusionResponse, PreSpecReviewExclusionStatus } from "../../lib/types";
import "../../styles/bulk-dialog.css";

/** 한 요청의 상한. 목록 선택 도구가 먼저 막고, 이 창도 같은 값으로 전송을 막는다. */
const MAX_IDS = 200;

/**
 * 복원은 종료·제외 선택지가 맞지 않으므로 자유 입력만 받는다. 선택지를 새로 짓지 않는다
 * (승인 시안은 제외 선택지만 정했다).
 */
const RESTORE_REASON_OPTIONS: readonly string[] = [];

interface DialogCopy {
  title: string;
  summaryHead: string;
  summaryDetail: string;
  guide: string | null;
  reasonLabel: string;
  reasonOptions: readonly string[];
  reasonRequiredError: string;
  saveVerb: string;
  errorFallback: string;
}

const COPY: Record<PreSpecReviewExclusionStatus, DialogCopy> = {
  excluded: {
    title: "선택한 사전규격 검토 제외",
    summaryHead: "제외",
    summaryDetail: "팀 전체의 일상 목록에서 숨깁니다. 추적 상태와 자동 분석은 그대로입니다.",
    guide: "제외한 건은 ‘전체 이력’ 보기에서 검토 제외 필터로 찾아 한 건씩 복원할 수 있습니다.",
    reasonLabel: "제외 사유 (필수)",
    reasonOptions: BULK_EXCLUSION_REASONS,
    reasonRequiredError: "제외 사유를 선택하십시오.",
    saveVerb: "검토 제외",
    errorFallback: "검토 제외를 저장하지 못했습니다.",
  },
  included: {
    title: "선택한 사전규격 검토 목록으로 복원",
    summaryHead: "복원",
    summaryDetail: "복원 후 기존 보기 조건에 맞는 건만 일상 목록에 나타납니다. 추적 상태와 자동 분석은 그대로입니다.",
    guide: null,
    reasonLabel: "복원 사유 (필수)",
    reasonOptions: RESTORE_REASON_OPTIONS,
    reasonRequiredError: "복원 사유를 입력하십시오.",
    saveVerb: "검토 목록으로 복원",
    errorFallback: "검토 목록 복원을 저장하지 못했습니다.",
  },
};

function actorProblem(value: string): string | null {
  const clean = value.trim();
  if (!clean) return "담당자 이름을 입력하십시오.";
  if ([...clean].length > 128) return "담당자 이름은 128자 이하여야 합니다.";
  return null;
}

export function ReviewExclusionDialog({ ids, status, onClose, onSaved }: {
  ids: number[];
  status: PreSpecReviewExclusionStatus;
  onClose: () => void;
  onSaved: (response: PreSpecReviewExclusionResponse) => Promise<void>;
}) {
  const copy = COPY[status];
  const [actor, setActor] = useState("");
  const [reason, setReason] = useState<BulkReasonDraft>(() => emptyBulkReason(copy.reasonOptions));
  const [pending, setPending] = useState(false);
  const submitting = useRef(false);
  const [error, setError] = useState<ApiErrorDescription | null>(null);
  const blockerId = useId();
  const count = ids.length.toLocaleString("ko-KR");
  const blocker = ids.length === 0
    ? "선택한 사전규격이 없습니다."
    : ids.length > MAX_IDS
      ? `한 번에 ${MAX_IDS}건까지 처리할 수 있습니다. 선택을 줄여 주세요.`
      : bulkReasonError(reason, copy.reasonRequiredError) ?? actorProblem(actor);
  const valid = blocker === null;

  async function submit() {
    if (submitting.current || !valid) return;
    submitting.current = true;
    setPending(true);
    setError(null);
    try {
      const response = await api.changePreSpecReviewExclusions({
        notice_ids: ids, status, actor_name: actor.trim(), reason: bulkReasonText(reason),
      });
      await onSaved(response);
    } catch (caught) {
      // 입력과 선택은 그대로 둔다. 다시 저장하는 것은 사람이 단추를 눌러야 한다.
      setError(describeApiError(caught, copy.errorFallback));
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }
  function close() { if (!submitting.current) onClose(); }

  return (
    <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}>
      <Dialog isOpen maxHeight="90dvh" onOpenChange={(open) => { if (!open) close(); }} purpose="form" width={680}>
        <form
          className="bulk-dialog"
          data-testid="pre-spec-review-exclusion-dialog"
          onSubmit={(event) => { event.preventDefault(); void submit(); }}
        >
          <DialogHeader title={copy.title} onOpenChange={close} />
          <div className="bulk-dialog-body">
            <div className="bulk-dialog-summary">
              <strong>{copy.summaryHead} {count}건</strong>
              <span className="bulk-dialog-summary-detail">{copy.summaryDetail}</span>
            </div>
            <div className="bulk-dialog-fields">
              <BulkReasonField
                label={copy.reasonLabel}
                options={copy.reasonOptions}
                value={reason}
                onChange={setReason}
                isDisabled={pending}
              />
              <ActorField
                label="담당자 이름 · 감사 표식 (필수)"
                description="감사 표식이며 로그인·신원 인증이 아닙니다."
                showRememberNote={false}
                value={actor}
                onChange={setActor}
                disabled={pending}
                placeholder="이름 입력"
              />
            </div>
            {copy.guide ? <p className="bulk-dialog-warning">{copy.guide}</p> : null}
            {error ? (
              <div className="bulk-dialog-error" role="alert">
                <strong>{error.title}</strong>
                <span>{error.detail} 입력과 선택은 그대로 두었습니다.</span>
              </div>
            ) : null}
            {blocker ? <p id={blockerId} className="bulk-dialog-blocker" role="status">{blocker}</p> : null}
          </div>
          <div className="bulk-dialog-footer">
            <p className="bulk-dialog-footer-note">담당자 이름은 이 브라우저에 기억한 값으로 미리 채웁니다.</p>
            <Button label="취소" variant="secondary" isDisabled={pending} onClick={close} />
            <Button
              aria-describedby={blocker ? blockerId : undefined}
              label={pending ? "처리 중…" : `${count}건 ${copy.saveVerb}`}
              variant="primary"
              isDisabled={!valid || pending}
              onClick={() => { void submit(); }}
            />
          </div>
        </form>
      </Dialog>
    </InternationalizationProvider>
  );
}
