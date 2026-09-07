import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Selector } from "@astryxdesign/core/Selector";
import { Link } from "react-router-dom";
import { ActorField } from "../common/ActorField";
import { DisabledReason } from "../common/DisabledReason";
import { MutationFeedback } from "../common/MutationFeedback";
import { api } from "../../lib/api";
import { describeApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import { linkRecordLabel } from "../../lib/opportunity";
import type { OpportunityLinkView } from "../../lib/types";
import { connectionLabel, isConfirmedLink, recordRoute, recordRouteLabel } from "./trackingFlow";

/**
 * 후보 연결 확인 (시안의 `후보 연결 확인` 대화상자).
 *
 * 공식 통합번호가 없는 이름 검색 후보를 사람이 수용·기각한다. 저장 계약은
 * `PATCH /opportunities/links/{id}/decision`이고 사유·기록자가 모두 필요하다.
 *
 * 화면은 **저장된 값만** 나란히 보여 준다. 사업명과 기관이 같아 보인다는 이유로
 * 같은 사업이라고 화면이 판정하지 않으며, 기각한 후보를 확정으로 승격시키지도
 * 않는다. 이 판정은 연결 관계만 바꾸고 추적 상태·등급·준비 상태·최종 Go/No-Go를
 * 바꾸지 않는다.
 */

const REASON_OPTIONS: Record<string, string[]> = {
  "수용": ["원천 정보를 비교해 같은 사업임을 확인", "공식 식별자 관계를 별도로 확인", "기타"],
  "기각": ["서로 다른 사업임을 확인", "연결 근거가 부족함", "기타"],
};

function externalIdOf(link: OpportunityLinkView): string {
  return link.record_external_id || link.external_id || link.evidence_external_no || "식별자 미확인";
}

function RecordFacts({ link }: { link: OpportunityLinkView }) {
  const route = recordRoute(link);
  return (
    <>
      <p><strong>{link.title?.trim() || "제목 미확인"}</strong></p>
      <p>{link.agency?.trim() || "기관 미확인"}</p>
      <p className="opportunity-caption">{externalIdOf(link)} · {connectionLabel(link)}</p>
      {route ? (
        <Link className="opportunity-linked-link" to={route}>{recordRouteLabel(link)} →</Link>
      ) : (
        <p className="opportunity-caption">원천 상세 화면으로 갈 식별자가 없습니다.</p>
      )}
    </>
  );
}

export interface CandidateLinkDialogProps {
  candidate: OpportunityLinkView;
  links: readonly OpportunityLinkView[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (message: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}

export function CandidateLinkDialog({
  candidate,
  links,
  onDirtyChange,
  onOpenChange,
  onSaved,
  open,
}: CandidateLinkDialogProps) {
  const queryClient = useQueryClient();
  const [decision, setDecision] = useState<"수용" | "기각">("수용");
  const [reason, setReason] = useState("");
  const [custom, setCustom] = useState("");
  const [actorName, setActorName] = useState("");
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);
  const [discarding, setDiscarding] = useState(false);

  const current = links.filter(isConfirmedLink).at(-1) ?? null;
  const validReason = (reason === "기타" ? custom : reason).trim();
  // 기록자 이름은 브라우저에 기억되므로 잃는 입력이 아니다(`ActorField`).
  const dirty = reason.length > 0 || custom.length > 0;
  const ready = validReason.length > 0 && actorName.trim().length > 0;

  useEffect(() => {
    onDirtyChange(open && dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange, open]);

  const reset = () => {
    setDecision("수용");
    setReason("");
    setCustom("");
    setActorName("");
    setProblem(null);
    setDiscarding(false);
  };

  const mutation = useMutation({
    mutationFn: () =>
      api.decideOpportunityLink(
        candidate.id,
        { decision: decision === "수용" ? "accepted" : "rejected", reason: validReason },
        actorName,
      ),
    onSuccess: async () => {
      const saved = decision;
      reset();
      onDirtyChange(false);
      onOpenChange(false);
      await queryClient.invalidateQueries({ queryKey: ["opportunity"] });
      await queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      onSaved(saved === "수용" ? "후보 연결을 수용으로 기록했습니다." : "후보 연결을 기각으로 기록했습니다.");
    },
    onError: (caught: unknown) => {
      setProblem(describeApiError(caught, "후보 연결 판정을 저장하지 못했습니다."));
    },
  });

  const requestClose = () => {
    if (dirty) {
      setDiscarding(true);
      return;
    }
    reset();
    onOpenChange(false);
  };

  const disabledReason = mutation.isPending
    ? "후보 연결 판정을 저장하고 있습니다."
    : !validReason
      ? "판정을 저장하려면 판단 사유를 고르거나 직접 입력하십시오."
      : !actorName.trim()
        ? "판정을 저장하려면 결정 기록자를 입력하십시오."
        : null;

  return (
    <Dialog
      isOpen={open}
      maxHeight="90dvh"
      onOpenChange={(next) => {
        if (!next) requestClose();
      }}
      padding={6}
      purpose="form"
      width="calc(var(--spacing-12) * 18)"
    >
      <div className="opportunity-dialog-body">
        <DialogHeader
          title={discarding ? "입력한 내용을 버릴까요?" : `${linkRecordLabel(candidate)} 후보 연결 확인`}
          onOpenChange={(next) => {
            if (!next) requestClose();
          }}
        />
        {discarding ? (
          <>
            <p>저장하지 않은 입력이 있습니다. 닫으면 입력한 내용이 사라지며 연결 상태는 바뀌지 않습니다.</p>
            <div className="opportunity-dialog-actions">
              <Button label="계속 작성" onClick={() => setDiscarding(false)} />
              <Button
                label="입력 버리고 닫기"
                onClick={() => {
                  reset();
                  onOpenChange(false);
                }}
              />
            </div>
          </>
        ) : (
          <>
            <p className="opportunity-caption">공식 연결 전 · 저장된 원천 정보 비교</p>
            <div className="opportunity-comparison">
              <section aria-label="현재 확정된 연결">
                <h3>현재 확정된 연결</h3>
                {current ? (
                  <RecordFacts link={current} />
                ) : (
                  <p>확정된 연결이 아직 없습니다. 비교할 확정 레코드가 없다는 뜻이며 후보가 맞다는 뜻이 아닙니다.</p>
                )}
              </section>
              <section aria-label="이름 검색으로 발견한 후보">
                <h3>이름 검색으로 발견한 후보</h3>
                <RecordFacts link={candidate} />
                {candidate.search_strategy ? (
                  <p className="opportunity-caption">검색 방식 · {candidate.search_strategy}</p>
                ) : null}
                {candidate.agency_match !== null ? (
                  <p className="opportunity-caption">
                    기관 일치 · {candidate.agency_match ? "예" : "아니오"}
                  </p>
                ) : null}
              </section>
            </div>
            <p>
              사업명과 기관이 같아도 같은 사업으로 자동 확정하지 않습니다. 원천 정보를 확인하고 연결 여부를
              선택해 주세요.
            </p>
            <div className="opportunity-form-columns">
              <Selector
                label="연결 판단"
                onChange={(value) => {
                  setDecision(value as "수용" | "기각");
                  setReason("");
                  setCustom("");
                }}
                options={["수용", "기각"]}
                value={decision}
              />
              <Selector
                label="판단 사유"
                onChange={setReason}
                options={REASON_OPTIONS[decision]}
                placeholder="사유를 선택하세요"
                value={reason}
              />
            </div>
            {reason === "기타" ? (
              <label>
                <span>판단 사유 직접 입력</span>
                <input
                  onChange={(event) => setCustom(event.target.value)}
                  placeholder="사유를 직접 입력합니다"
                  value={custom}
                />
              </label>
            ) : null}
            <ActorField
              autoComplete="off"
              label="결정 기록자"
              onChange={setActorName}
              placeholder="이름 입력"
              required
              value={actorName}
            />
            {problem ? (
              <MutationFeedback problem={problem} tone="error">
                <p>연결 상태는 바뀌지 않았습니다. 입력한 내용은 그대로 남아 있습니다.</p>
              </MutationFeedback>
            ) : null}
            <div className="opportunity-dialog-actions">
              <p className="opportunity-caption">
                이 판정은 연결 관계만 바꿉니다. 추적 상태·적합성 등급·참여 준비 상태·최종 Go/No-Go는 그대로입니다.
              </p>
              <Button label="취소" onClick={requestClose} />
              <Button
                aria-describedby={disabledReason ? "opportunity-candidate-disabled-reason" : undefined}
                isDisabled={!ready || mutation.isPending}
                label={mutation.isPending ? "저장 중…" : decision === "수용" ? "같은 사업으로 연결" : "후보 기각"}
                onClick={() => {
                  if (ready && !mutation.isPending) mutation.mutate();
                }}
                variant="primary"
              />
            </div>
            {disabledReason ? (
              <DisabledReason id="opportunity-candidate-disabled-reason">{disabledReason}</DisabledReason>
            ) : null}
          </>
        )}
      </div>
    </Dialog>
  );
}
