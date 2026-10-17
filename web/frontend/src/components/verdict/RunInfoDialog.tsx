import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { formatKstMinute } from "../../lib/record";
import { qualityStatusLabel, qualityStatusNote } from "../../lib/qualityStatus";
import type { PractitionerVerdictView } from "../../lib/types";
import { staleReasonLabel } from "../../lib/verdict";

/*
 * ⋯ "실행 정보"(ui-spec §4.4 규칙): 정책·모델·실행 시각은 실무 화면에 없고 이 대화상자에서만 보인다.
 * 열려 있지 않으면 내용을 DOM에 두지 않는다. 품질 표식은 AGENTS의 네 상태 문구로 적고(참조 실행·mock을
 * 운영 완료처럼 보이게 하지 않으며 `표식 없음`을 미측정으로 바꾸지 않는다) 성공·실패 색을 쓰지 않는다.
 */

interface RunInfoDialogProps {
  open: boolean;
  onClose: () => void;
  view: PractitionerVerdictView | null;
}

function Row({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="vd-info-row">
      <dt>{label}</dt>
      <dd className={value === null ? "is-empty" : undefined}>{value ?? "값 없음"}</dd>
    </div>
  );
}

export function RunInfoDialog({ open, onClose, view }: RunInfoDialogProps) {
  const identity = view?.identity ?? null;
  const binding = view?.source_binding ?? null;
  return (
    <Dialog
      isOpen={open}
      maxHeight="90dvh"
      onOpenChange={(next) => { if (!next) onClose(); }}
      padding={6}
      purpose="info"
      width="calc(var(--spacing-12) * 14)"
    >
      <div className="opportunity-dialog-body">
        <DialogHeader onOpenChange={(next) => { if (!next) onClose(); }} title="실행 정보" />
        {open && view ? (
          <>
            <dl className="vd-info">
              <Row label="분석 정책" value={identity?.policy_id ?? null} />
              <Row label="정책 해시" value={identity?.policy_sha256 ?? null} />
              <Row label="모델" value={identity?.model ?? null} />
              <Row label="추론 강도" value={identity?.reasoning_effort ?? null} />
              <Row label="실행기 버전" value={identity?.cli_version ?? null} />
              <Row label="시작" value={formatKstMinute(view.started_at)} />
              <Row label="종료" value={formatKstMinute(view.finished_at)} />
              <Row label="실행 식별자" value={view.attempt_id} />
              <Row label="회사 근거 버전" value={binding?.company_version_id ?? null} />
              <Row label="회사 근거 해시" value={binding?.company_sha256 ?? null} />
              <Row label="문서 버전 수" value={binding ? String(binding.document_versions.length) : null} />
              <Row label="현재 기준" value={view.is_current ? "현재 기준" : `과거 기준 · ${view.stale_reasons.map(staleReasonLabel).join(", ") || "사유 없음"}`} />
              <Row label="품질 표식" value={qualityStatusLabel(view.quality_status)} />
            </dl>
            <p className="opportunity-caption">{qualityStatusNote(view.quality_status)}</p>
          </>
        ) : (
          <p>표시할 실행이 없습니다.</p>
        )}
        <div className="opportunity-dialog-actions">
          <Button label="닫기" onClick={onClose} />
        </div>
      </div>
    </Dialog>
  );
}
