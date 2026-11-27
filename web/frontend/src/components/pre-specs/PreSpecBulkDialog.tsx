import { useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Button } from "@astryxdesign/core/Button";
import { DialogHeader } from "@astryxdesign/core/Dialog";
import { Dialog } from "../common/WorkspaceDialog";
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
import { engineReviewApi, type EngineReviewBatchResult } from "../../lib/engineReviewApi";
import { engineReviewReason } from "../../lib/engineReviewCopy";
import { useFeatureFlags } from "../../lib/featureFlags";
import { generateRequestId } from "../../lib/requestId";
import { engineReviewKey } from "../../lib/useEngineReview";
import { describeApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import type { PreSpecReviewExclusionStatus } from "../../lib/types";
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
  reasonField?: { label: string; options: readonly string[]; requiredError: string };
  saveVerb: string;
  errorFallback: string;
}

export type PreSpecBulkAction = PreSpecReviewExclusionStatus | "track";

const COPY: Record<PreSpecBulkAction, DialogCopy> = {
  track: {
    title: "선택한 사전규격 추적 시작",
    summaryHead: "선택",
    summaryDetail: "사업기회에 연결된 미선택 공고만 추적을 시작해요.",
    guide: null,
    saveVerb: "추적 시작",
    errorFallback: "추적 시작 결과를 확인하지 못했어요.",
  },
  excluded: {
    title: "선택한 사전규격 검토 제외",
    summaryHead: "제외",
    summaryDetail: "팀 전체의 일상 목록에서 숨겨요. 추적 상태와 자동 분석은 그대로예요.",
    guide: "제외한 건은 ‘전체 이력’ 보기에서 검토 제외 필터로 찾아 한 건씩 복원할 수 있어요.",
    reasonField: { label: "제외 사유 (필수)", options: BULK_EXCLUSION_REASONS, requiredError: "제외 사유를 선택해 주세요." },
    saveVerb: "검토 제외",
    errorFallback: "검토 제외를 저장하지 못했어요.",
  },
  included: {
    title: "선택한 사전규격 검토 목록으로 복원",
    summaryHead: "복원",
    summaryDetail: "복원 후 기존 보기 조건에 맞는 건만 일상 목록에 나타나요. 추적 상태와 자동 분석은 그대로예요.",
    guide: null,
    reasonField: { label: "복원 사유 (필수)", options: RESTORE_REASON_OPTIONS, requiredError: "복원 사유를 입력해 주세요." },
    saveVerb: "검토 목록으로 복원",
    errorFallback: "검토 목록 복원을 저장하지 못했어요.",
  },
};

function actorProblem(value: string): string | null {
  const clean = value.trim();
  if (!clean) return "담당자 이름을 입력해 주세요.";
  if ([...clean].length > 128) return "담당자 이름은 128자 이하여야 해요.";
  return null;
}

function analysisBatchSummary(items: EngineReviewBatchResult[]) {
  const reasons = new Map<string | null, number>();
  let requested = 0;
  for (const item of items) {
    if (item.outcome === "ineligible") reasons.set(item.reason, (reasons.get(item.reason) ?? 0) + 1);
    else requested += 1;
  }
  const details = [...reasons].map(([code, count]) => {
    const reason = engineReviewReason(code);
    return `${reason.message}${reason.code ? ` · ${reason.code}` : ""} ${count}건`;
  });
  return `분석 요청 ${requested}건 · 요청 못 함 ${items.length - requested}건${details.length ? ` (${details.join(" · ")})` : ""}`;
}

export function PreSpecBulkDialog({ ids, status, onClose, onSaved }: {
  ids: number[];
  status: PreSpecBulkAction;
  onClose: () => void;
  onSaved: (handledIds: number[], message?: string, requestedIds?: number[]) => Promise<void>;
}) {
  const copy = COPY[status];
  const queryClient = useQueryClient();
  const flags = useFeatureFlags();
  const requestAnalysis = status === "track" && flags.engineReviewMode !== "off";
  const [actor, setActor] = useState("");
  const [reason, setReason] = useState<BulkReasonDraft>(() => emptyBulkReason(copy.reasonField?.options ?? []));
  const [pending, setPending] = useState(false);
  const submitting = useRef(false);
  const [error, setError] = useState<ApiErrorDescription | null>(null);
  const blockerId = useId();
  const count = ids.length.toLocaleString("ko-KR");
  const blocker = ids.length === 0
    ? "선택한 사전규격이 없어요."
    : ids.length > MAX_IDS
      ? `한 번에 ${MAX_IDS}건까지 처리할 수 있어요. 선택을 줄여 주세요.`
      : (copy.reasonField ? bulkReasonError(reason, copy.reasonField.requiredError) : null) ?? actorProblem(actor);
  const valid = blocker === null && (status !== "track" || flags.settled);

  async function submit() {
    if (submitting.current || !valid) return;
    submitting.current = true;
    setPending(true);
    setError(null);
    try {
      const body = { notice_ids: ids, actor_name: actor.trim() };
      if (status === "track") {
        const { items } = await api.startSelectedPreSpecs(body);
        const handled = items.filter(item => item.outcome !== "unavailable");
        const startedIds = items.filter(item => item.outcome === "started").map(item => item.notice_id);
        const started = startedIds.length;
        let requestedIds: number[] = [];
        let summary = `추적 시작 ${started}건 · 기존 결정 유지 ${handled.length - started}건 · 연결 확인 필요 ${items.length - handled.length}건`;
        if (requestAnalysis) {
          let analysisSummary = analysisBatchSummary([]);
          if (started > 0) {
            try {
              const batch = await engineReviewApi.batch({
                request_id: generateRequestId(), origin: "tracking_start", notice_ids: startedIds,
              }, body.actor_name);
              analysisSummary = analysisBatchSummary(batch.items);
              requestedIds = batch.items.filter((item) => item.outcome !== "ineligible").map((item) => item.notice_id);
            } catch {
              analysisSummary = "분석 요청은 올리지 못했어요";
            }
            for (const id of startedIds) {
              if (!requestedIds.includes(id)) void queryClient.invalidateQueries({ queryKey: engineReviewKey(id) });
            }
            if (requestedIds.length === 0) void queryClient.invalidateQueries({ queryKey: ["workload"] });
          }
          summary += ` · ${analysisSummary}`;
        }
        await onSaved(handled.map(item => item.notice_id), summary, requestedIds);
      } else {
        const { items } = await api.changePreSpecReviewExclusions({ ...body, status, reason: bulkReasonText(reason) });
        await onSaved(items.map(item => item.notice_id));
      }
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
          data-testid={status === "track" ? "pre-spec-bulk-tracking-dialog" : "pre-spec-review-exclusion-dialog"}
          onSubmit={(event) => { event.preventDefault(); void submit(); }}
        >
          <DialogHeader title={copy.title} onOpenChange={close} />
          <div className="bulk-dialog-body">
            <div className="bulk-dialog-summary">
              <strong>{copy.summaryHead} {count}건</strong>
              <span className="bulk-dialog-summary-detail">{copy.summaryDetail}</span>
            </div>
            {requestAnalysis ? <p>추적을 시작한 공고에 분석 요청을 올려요. 전송은 공고마다 따로 승인해요.</p> : null}
            <div className="bulk-dialog-fields">
              {copy.reasonField && (
                <BulkReasonField
                  label={copy.reasonField.label}
                  options={copy.reasonField.options}
                  value={reason}
                  onChange={setReason}
                  isDisabled={pending}
                />
              )}
              <ActorField
                label="담당자 이름 · 감사 표식 (필수)"
                description="감사 표식이며 로그인·신원 인증이 아니에요."
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
                <span>{error.detail} 입력과 선택은 그대로 두었어요.</span>
              </div>
            ) : null}
            {blocker ? <p id={blockerId} className="bulk-dialog-blocker" role="status">{blocker}</p> : null}
          </div>
          <div className="bulk-dialog-footer">
            <p className="bulk-dialog-footer-note">담당자 이름은 이 브라우저에 기억한 값으로 미리 채워요.</p>
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
