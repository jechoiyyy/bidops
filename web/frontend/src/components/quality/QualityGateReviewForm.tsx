import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../lib/api";
import type { QualityGateEvaluationResponse, QualityGateEvidenceJudgment, QualityGateReviewResponse } from "../../lib/types";

interface QualityGateReviewFormProps {
  gateId: string;
  reviews: QualityGateReviewResponse[];
  latestEvaluation: QualityGateEvaluationResponse | undefined;
  onSaved: () => void;
}

function safeError(error: unknown): string {
  if (!(error instanceof ApiError)) return "근거 리뷰를 저장하지 못했습니다.";
  if (error.status === 409) return "게이트 계산이 갱신되어 리뷰가 저장되지 않았습니다. 최신 상태를 다시 확인하십시오.";
  if (error.status === 404) return "리뷰 대상 공고를 찾을 수 없습니다.";
  if (error.status === 422) return "담당자와 근거 판단을 확인하십시오.";
  return error.status > 0 ? `리뷰 저장에 실패했습니다 (${error.status}).` : "리뷰 저장에 실패했습니다.";
}

const judgmentOptions: QualityGateEvidenceJudgment[] = ["동의", "근거 부족", "판단 보류"];

export function QualityGateReviewForm({ gateId, reviews, latestEvaluation, onSaved }: QualityGateReviewFormProps) {
  const [noticeId, setNoticeId] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [evidenceJudgment, setEvidenceJudgment] = useState<QualityGateEvidenceJudgment>("동의");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const validCount = latestEvaluation?.valid_review_count ?? 0;
  const distinctCount = latestEvaluation?.distinct_notice_review_count ?? 0;
  const ready = validCount >= 10 && distinctCount >= 10;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!noticeId.trim() || !reviewer.trim()) {
      setError("공고 ID와 담당자 이름은 필수입니다.");
      return;
    }
    setSaving(true);
    setError(null);
    void api.upsertQualityGateReview(gateId, noticeId.trim(), {
      reviewer: reviewer.trim(),
      evidence_judgment: evidenceJudgment,
      note: note.trim() || null,
    }).then(() => {
      setNoticeId("");
      setNote("");
      onSaved();
    }).catch((reason: unknown) => setError(safeError(reason)))
      .finally(() => setSaving(false));
  }

  return (
    <section className="quality-panel" aria-labelledby="quality-review-heading">
      <div className="quality-panel-heading">
        <div>
          <span className="quality-eyebrow">Pass A 근거 확인</span>
          <h2 id="quality-review-heading">담당자 리뷰</h2>
        </div>
        <div className={`quality-review-readiness ${ready ? "is-ready" : "is-not-ready"}`} role="status" aria-live="polite">
          <strong>{validCount}/10 유효 리뷰</strong>
          <span>{distinctCount}/10 서로 다른 공고</span>
        </div>
      </div>
      <p className="quality-review-explanation">리뷰는 Pass A의 judgment digest에 묶입니다. 판단 보류와 digest 불일치는 유효 분모에서 제외됩니다.</p>
      <form className="quality-form quality-review-form" onSubmit={submit}>
        <div className="quality-form-grid">
          <label>
            Pass A 공고 ID
            <input required value={noticeId} onChange={(event) => setNoticeId(event.target.value)} placeholder="예: notice-001" />
          </label>
          <label>
            담당자
            <input required minLength={1} maxLength={128} value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="예: 홍길동" />
          </label>
          <label>
            근거 판단
            <select value={evidenceJudgment} onChange={(event) => setEvidenceJudgment(event.target.value as QualityGateEvidenceJudgment)}>
              {judgmentOptions.map((option) => <option value={option} key={option}>{option}</option>)}
            </select>
          </label>
          <label className="quality-field-wide">
            메모 <span className="quality-optional">선택</span>
            <textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} placeholder="추가 확인이 필요한 근거를 남길 수 있습니다." />
          </label>
        </div>
        {error ? <p className="quality-form-error" role="alert">{error}</p> : null}
        <button className="quality-button quality-button-primary" type="submit" disabled={saving || !noticeId.trim() || !reviewer.trim()}>{saving ? "저장 중…" : "근거 리뷰 저장"}</button>
      </form>
      <div className="quality-review-list">
        <h3>저장된 리뷰 {reviews.length}건</h3>
        {reviews.length > 0 ? (
          <div className="quality-table-wrap">
            <table className="quality-review-table">
              <caption className="quality-sr-only">담당자 리뷰 목록</caption>
              <thead><tr><th scope="col">공고</th><th scope="col">담당자</th><th scope="col">판단</th><th scope="col">digest</th><th scope="col">수정 시각</th></tr></thead>
              <tbody>{reviews.map((review) => <tr key={review.review_id}><th scope="row" className="mono">{review.notice_id}</th><td>{review.reviewer}</td><td>{review.evidence_judgment}</td><td><code>{review.decision_digest}</code></td><td>{new Date(review.updated_at).toLocaleString("ko-KR")}</td></tr>)}</tbody>
            </table>
          </div>
        ) : <p className="quality-empty-inline">아직 저장된 리뷰가 없습니다.</p>}
      </div>
    </section>
  );
}
