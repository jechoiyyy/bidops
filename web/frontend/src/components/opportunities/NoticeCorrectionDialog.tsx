import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Link } from "react-router-dom";
import { ActorField } from "../common/ActorField";
import { DisabledReason } from "../common/DisabledReason";
import { MutationFeedback } from "../common/MutationFeedback";
import { TechnicalFacts, TechnicalInfo } from "../common/TechnicalInfo";
import { api } from "../../lib/api";
import { describeApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import type { TrackingException } from "../../lib/opportunity";
import type { NoticeDetailResponse, ReviewUpsertRequest } from "../../lib/types";

/**
 * 공고 판정의 확인 항목에 담당자 답변을 남긴다 (ADR-0046 결정 3).
 *
 * 저장 계약은 검토 대기열이 쓰던 것과 같은 `PUT /notices/{pk}/review`이고,
 * 회차는 **그 공고가 속한 회차**(`notice.run_id`)다. 사업 추적은 누적 화면이라
 * 회차를 사람에게 다시 묻지 않는다.
 *
 * 이 form은 확인 항목 답변과 이유만 건드린다. 등급·준비 상태·최종 처리 같은
 * 기존 리뷰 값은 그대로 되돌려 보내 예외 처리가 다른 판정을 덮지 않게 한다.
 */
export interface NoticeCorrectionDialogProps {
  exceptions: TrackingException[];
  notice: NoticeDetailResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (message: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}

export function NoticeCorrectionDialog({
  exceptions,
  notice,
  onDirtyChange,
  onOpenChange,
  onSaved,
  open,
}: NoticeCorrectionDialogProps) {
  const queryClient = useQueryClient();
  const existing = notice.reviews.find((review) => review.run_id === notice.run_id) ?? null;
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [actorName, setActorName] = useState("");
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);
  const [discarding, setDiscarding] = useState(false);

  const answered = Object.values(answers).filter((value) => value.trim().length > 0).length;
  // 기록자 이름은 브라우저에 기억되므로 잃는 입력이 아니다(`ActorField`).
  const dirty = reason.length > 0 || Object.values(answers).some((value) => value.length > 0);
  const ready = answered > 0 && reason.trim().length > 0 && actorName.trim().length > 0;

  useEffect(() => {
    onDirtyChange(open && dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange, open]);

  const reset = () => {
    setAnswers({});
    setReason("");
    setActorName("");
    setProblem(null);
    setDiscarding(false);
  };

  const mutation = useMutation({
    mutationFn: () => {
      const kept = (existing?.answers ?? [])
        .map((answer) => ({ item: answer.item, answer: answer.answer }))
        .filter((answer) => !((answer.item ?? "") in answers));
      const added = Object.entries(answers)
        .filter(([, value]) => value.trim().length > 0)
        .map(([item, value]) => ({ item, answer: value.trim() }));
      const payload: ReviewUpsertRequest = {
        run_id: notice.run_id,
        disposition: existing?.disposition ?? null,
        system_judgment_review: existing?.system_judgment_review ?? null,
        corrected_grade: existing?.corrected_grade ?? null,
        corrected_readiness: existing?.corrected_readiness ?? null,
        weakest_perspective: existing?.weakest_perspective ?? null,
        reason: reason.trim(),
        reviewer: actorName.trim(),
        verification_answers: [...kept, ...added],
      };
      return api.saveReview(notice.id, payload);
    },
    onSuccess: async () => {
      reset();
      onDirtyChange(false);
      onOpenChange(false);
      await queryClient.invalidateQueries({ queryKey: ["notice", notice.id] });
      onSaved("확인 항목 답변을 저장했습니다.");
    },
    onError: (caught: unknown) => {
      setProblem(describeApiError(caught, "확인 항목 답변을 저장하지 못했습니다."));
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
    ? "확인 항목 답변을 저장하고 있습니다."
    : answered === 0
      ? "확인 항목에 답을 하나 이상 입력하십시오."
      : !reason.trim()
        ? "저장하려면 수정 이유를 입력하십시오."
        : !actorName.trim()
          ? "저장하려면 결정 기록자를 입력하십시오."
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
      width="calc(var(--spacing-12) * 13)"
    >
      <div className="opportunity-dialog-body">
        <DialogHeader
          title={discarding ? "입력한 내용을 버릴까요?" : "확인 항목 답변"}
          onOpenChange={(next) => {
            if (!next) requestClose();
          }}
        />
        {discarding ? (
          <>
            <p>저장하지 않은 입력이 있습니다. 닫으면 입력한 내용이 사라지며 공고 판정은 바뀌지 않습니다.</p>
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
            {/* 회차 식별자 원문은 접힌 `기술 정보`로 내린다(ADR-0066 §3.3, 시안 M4).
                이 다이얼로그는 공고 상세가 준 `run_id` 문자열만 갖고 있고 회차의 수집
                기간·생성 시각은 받지 않으므로, 실무자가 아는 회차 이름(`09-16~09-20
                수집`)을 여기서 만들 수 없다 — 날짜를 지어내지 않고 사실만 문장으로
                적는다. 값은 지우지 않고 접힌 곳에 **전문** 그대로 남긴다. */}
            <p className="opportunity-caption">
              {notice.title?.trim() || "제목 미확인"}
            </p>
            <p className="opportunity-caption">
              이 공고가 속한 수집 회차에 저장합니다. 기존 등급·준비 상태·최종 처리 값은 그대로 둡니다.
            </p>
            <TechnicalInfo summary="기술 정보 · 저장 대상 회차">
              <TechnicalFacts
                facts={[{ label: "수집 회차 식별자", value: notice.run_id }]}
                label="저장 대상 회차 식별자"
              />
            </TechnicalInfo>
            {exceptions.map((exception) => (
              <label key={exception.title}>
                <span>{exception.title}</span>
                <textarea
                  onChange={(event) => setAnswers((current) => ({ ...current, [exception.title]: event.target.value }))}
                  placeholder="확인한 사실과 원문 위치를 남깁니다. 추정을 적지 않습니다."
                  rows={2}
                  value={answers[exception.title] ?? ""}
                />
              </label>
            ))}
            <label>
              <span>수정 이유</span>
              <textarea
                onChange={(event) => setReason(event.target.value)}
                placeholder="예외 작업으로 무엇을 해소했는지 남깁니다."
                required
                rows={2}
                value={reason}
              />
            </label>
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
                <p>공고 판정은 바뀌지 않았습니다. 입력한 내용은 그대로 남아 있습니다.</p>
              </MutationFeedback>
            ) : null}
            <Link
              className="opportunity-linked-link"
              to={{ pathname: `/judgments/${notice.id}`, search: new URLSearchParams({ run: notice.run_id }).toString() }}
            >
              공고 판정 이력에서 원문 확인 →
            </Link>
            <div className="opportunity-dialog-actions">
              <Button label="취소" onClick={requestClose} />
              <Button
                aria-describedby={disabledReason ? "opportunity-notice-correction-disabled-reason" : undefined}
                isDisabled={!ready || mutation.isPending}
                label={mutation.isPending ? "저장 중…" : "확인 항목 답변 저장"}
                onClick={() => {
                  if (ready && !mutation.isPending) mutation.mutate();
                }}
                variant="primary"
              />
            </div>
            {disabledReason ? (
              <DisabledReason id="opportunity-notice-correction-disabled-reason">{disabledReason}</DisabledReason>
            ) : null}
          </>
        )}
      </div>
    </Dialog>
  );
}
