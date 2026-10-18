import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import type { ProposalConfirm } from "./useProposalController";
import { sectionLabel } from "../../lib/proposal";

/*
 * 새 초안 · 이 절 다시 쓰기 · 제출 준비 표시 확인 대화상자.
 *
 * 세 조작 모두 확인 전에는 요청하지 않는다. 새 초안과 절 다시 쓰기는 하루 생성 한도를 쓰고 이전 버전은 지워지지
 * 않고 남는다. 제출 준비 표시는 되돌릴 수 없는 표시이며 서류 준비 상태일 뿐 가격·투입 인력을 채워 주지 않는다.
 * 담당자 이름은 조작 직전에 탭 상단 기록자 칸에서 확인한다(감사 표식이며 인증이 아니다).
 */

interface ProposalConfirmDialogProps {
  confirm: ProposalConfirm | null;
  pending: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

interface Copy {
  title: string;
  confirmLabel: string;
  pendingLabel: string;
  paragraphs: string[];
}

function copyFor(confirm: ProposalConfirm): Copy {
  switch (confirm.kind) {
    case "create":
      return {
        title: "제안서 초안 만들기",
        confirmLabel: "초안 만들기",
        pendingLabel: "요청 중…",
        paragraphs: [
          "판정 결과와 회사 근거를 바탕으로 제안서 초안 6개 절을 새로 만듭니다. 생성에는 몇 분이 걸릴 수 있고 하루 생성 한도를 한 건 씁니다.",
          "지금 초안이 있으면 이전 초안으로 남고 새 초안이 최신이 됩니다. 가격·투입 인력·전략 수치는 만들지 않고 빈 자리로 둡니다. 승인된 전송 정책 범위 안에서만 만들어집니다.",
        ],
      };
    case "regenerate":
      return {
        title: `${sectionLabel(confirm.sectionKey)} 다시 쓰기`,
        confirmLabel: "다시 쓰기 요청",
        pendingLabel: "요청 중…",
        paragraphs: [
          "이 절만 새 버전으로 다시 만듭니다. 지금 버전은 지워지지 않고 기록으로 남지만 화면에는 새 버전이 보입니다.",
          "하루 생성 한도를 한 절 몫(초안 한 건의 6분의 1) 씁니다. 새 버전의 문장은 새로 생성되며 자동으로 고치지 않습니다.",
        ],
      };
    case "ready":
      return {
        title: "제출 준비로 표시",
        confirmLabel: "제출 준비로 표시",
        pendingLabel: "표시 중…",
        paragraphs: [
          "모든 절을 검토한 초안을 제출 준비 단계로 표시합니다. 되돌릴 수 없습니다.",
          "이 표시는 서류 준비 상태일 뿐입니다. 가격·투입 인력은 사람이 따로 채워야 하고, 참여 여부는 담당자가 별도로 정합니다.",
        ],
      };
  }
}

export function ProposalConfirmDialog({ confirm, pending, onConfirm, onClose }: ProposalConfirmDialogProps) {
  const copy = confirm ? copyFor(confirm) : null;
  return (
    <Dialog
      isOpen={confirm !== null}
      maxHeight="90dvh"
      onOpenChange={(next) => { if (!next && !pending) onClose(); }}
      padding={6}
      purpose="info"
      width="calc(var(--spacing-12) * 13)"
    >
      <div className="opportunity-dialog-body" data-testid="proposal-confirm">
        <DialogHeader onOpenChange={(next) => { if (!next && !pending) onClose(); }} title={copy?.title ?? "확인"} />
        {copy ? copy.paragraphs.map((text) => <p key={text}>{text}</p>) : null}
        <div className="opportunity-dialog-actions">
          <Button isDisabled={pending} label="취소" onClick={onClose} />
          <Button
            isDisabled={pending}
            label={pending ? copy?.pendingLabel ?? "처리 중…" : copy?.confirmLabel ?? "확인"}
            onClick={onConfirm}
            variant="primary"
          />
        </div>
      </div>
    </Dialog>
  );
}
