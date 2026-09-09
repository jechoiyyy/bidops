import { useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import {
  CancelButton,
  CriteriaDialog,
  DialogActions,
  Note,
} from "../criteria/CriteriaPrimitives";
import { ApiError, api } from "../../lib/api";
import type { QualityGateEvidenceJudgment } from "../../lib/types";

/**
 * 담당자 근거 리뷰 저장 (`PUT /quality-gates/{gate}/reviews/{notice}`).
 *
 * 리뷰는 Pass A 판정의 식별 해시에 묶인다. 판단 보류와 식별 해시 불일치는 유효
 * 분모에서 빠지므로, 리뷰를 저장했다는 사실만으로 화면이 통과를 만들지 않는다.
 * 저장이 계산을 갱신하면 서버가 새 수정본을 덧붙인다 — 기존 평가를 덮지 않는다.
 *
 * **대상 게이트는 창이 열린 순간에 고정된다.** 대상은 `QualityGatesPage`가 열 때
 * 한 번 정해 `gateId`로 내려보내며 이 컴포넌트가 살아 있는 동안 바뀌지 않는다.
 * 그래서 저장이 나가는 중에 목록 선택이나 주소가 바뀌어도 이 창은 **처음 대상에만**
 * 저장한다. 부모가 대상마다 새로 마운트하므로 다른 게이트로 열면 공고·담당자·판단·
 * 메모가 모두 비고, 같은 창 안의 409에서는 초안이 그대로 남는다.
 */

const JUDGMENTS: QualityGateEvidenceJudgment[] = ["동의", "근거 부족", "판단 보류"];

function safeError(error: unknown): string {
  if (!(error instanceof ApiError)) return "근거 리뷰를 저장하지 못했습니다.";
  if (error.status === 409) return "게이트 계산이 갱신되어 리뷰가 저장되지 않았습니다. 입력은 그대로 두었습니다. 최신 상태를 확인한 뒤 다시 저장하십시오.";
  if (error.status === 404) return "리뷰 대상 공고를 찾을 수 없습니다.";
  if (error.status === 422) return "담당자와 근거 판단을 확인하십시오.";
  return error.status > 0 ? `리뷰 저장에 실패했습니다 (${error.status}).` : "리뷰 저장에 실패했습니다.";
}

export function QualityGateReviewDialog({ gateId, onClose, onSaved }: {
  /** 창을 여는 순간에 정해진 대상. `null`이면 창이 닫혀 있다. */
  gateId: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [noticeId, setNoticeId] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [judgment, setJudgment] = useState<QualityGateEvidenceJudgment>("동의");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function close() {
    if (saving) return;
    setError(null);
    onClose();
  }

  function submit() {
    if (saving) return;
    if (!noticeId.trim() || !reviewer.trim()) {
      setError("공고 ID와 담당자 이름은 필수입니다.");
      return;
    }
    setSaving(true);
    setError(null);
    if (!gateId) return;
    void api.upsertQualityGateReview(gateId, noticeId.trim(), {
      reviewer: reviewer.trim(),
      evidence_judgment: judgment,
      note: note.trim() || null,
    })
      .then(() => {
        setNoticeId("");
        setNote("");
        onSaved();
      })
      .catch((reason: unknown) => setError(safeError(reason)))
      .finally(() => setSaving(false));
  }

  return (
    <CriteriaDialog onClose={close} open={gateId !== null} title="담당자 근거 리뷰">
      <Note title={`저장 대상 게이트 · ${gateId ?? "선택 없음"}`}>
        리뷰는 Pass A 판정의 식별 해시에 묶입니다. 판단 보류와 식별 해시 불일치는 유효 분모에서 빠지며, 리뷰 건수가 채워졌다는 이유만으로 통과가 되지 않습니다.
      </Note>
      <div className="crit-dialog-grid">
        <TextInput label="Pass A 공고 ID · 필수" onChange={setNoticeId} placeholder="예: notice-001" value={noticeId} />
        <TextInput label="리뷰 담당자 · 필수" onChange={setReviewer} placeholder="담당자 이름" value={reviewer} />
      </div>
      <Selector
        label="근거 판단 · 필수"
        onChange={(value) => setJudgment(value as QualityGateEvidenceJudgment)}
        options={JUDGMENTS.map((value) => ({ value, label: value }))}
        value={judgment}
      />
      <TextArea
        description="추가 확인이 필요한 근거를 남길 수 있습니다."
        label="메모 (선택)"
        onChange={setNote}
        rows={4}
        value={note}
      />
      {error ? <Text as="p" className="crit-error" role="alert">{error}</Text> : null}
      <DialogActions>
        <CancelButton isDisabled={saving} onClick={close} />
        <Button
          isDisabled={saving || !gateId || !noticeId.trim() || !reviewer.trim()}
          label={saving ? "저장 중…" : "근거 리뷰 저장"}
          onClick={submit}
          size="sm"
          variant="primary"
        />
      </DialogActions>
    </CriteriaDialog>
  );
}
