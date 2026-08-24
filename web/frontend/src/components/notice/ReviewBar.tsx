import type { ReviewAnswerInput, PerspectiveResponse } from "../../lib/types";

export interface ReviewDraft {
  disposition: string;
  system_judgment_review: string;
  corrected_grade: string;
  corrected_readiness: string;
  weakest_perspective: string;
  reason: string;
  verification_answers: ReviewAnswerInput[];
}

interface ReviewBarProps {
  draft: ReviewDraft;
  perspectives: PerspectiveResponse[];
  saving: boolean;
  error: string | null;
  onChange: <K extends keyof ReviewDraft>(key: K, value: ReviewDraft[K]) => void;
  onSave: () => void;
}

const judgmentOptions = ["동의", "등급 수정", "근거 부족"];

export function ReviewBar({ draft, perspectives, saving, error, onChange, onSave }: ReviewBarProps) {
  return (
    <div className="review-bar" aria-label="담당자 리뷰 입력">
      <div className="review-bar-title">
        <strong>담당자 리뷰</strong>
        <span>DB 정본</span>
      </div>
      <div className="review-segmented" role="group" aria-label="시스템 판정 검토">
        {judgmentOptions.map((option) => (
          <button
            className={draft.system_judgment_review === option ? "is-active" : ""}
            key={option}
            type="button"
            onClick={() => onChange("system_judgment_review", option)}
          >
            {option}
          </button>
        ))}
      </div>
      <label className="review-control">
        <span>최종 처리</span>
        <select value={draft.disposition} onChange={(event) => onChange("disposition", event.target.value)}>
          <option value="">선택 안 함</option>
          <option value="심층 검토 진행">심층 검토 진행</option>
          <option value="관찰">관찰</option>
          <option value="제외">제외</option>
        </select>
      </label>
      <label className="review-control">
        <span>수정 등급</span>
        <select value={draft.corrected_grade} onChange={(event) => onChange("corrected_grade", event.target.value)}>
          <option value="">수정 없음</option>
          <option value="우선 검토">우선 검토</option>
          <option value="검토 권장">검토 권장</option>
          <option value="관찰 대상">관찰 대상</option>
          <option value="제외">제외</option>
        </select>
      </label>
      <label className="review-control">
        <span>수정 준비 상태</span>
        <select value={draft.corrected_readiness} onChange={(event) => onChange("corrected_readiness", event.target.value)}>
          <option value="">수정 없음</option>
          <option value="확인 완료">확인 완료</option>
          <option value="부분 확인 필요">부분 확인 필요</option>
          <option value="참여 불가 확인">참여 불가 확인</option>
        </select>
      </label>
      <label className="review-control review-control-perspective">
        <span>근거 부족 관점</span>
        <select value={draft.weakest_perspective} onChange={(event) => onChange("weakest_perspective", event.target.value)}>
          <option value="">선택 안 함</option>
          {perspectives.map((perspective) => (
            <option key={perspective.id} value={perspective.name ?? ""}>{perspective.name ?? "관점 미확인"}</option>
          ))}
        </select>
      </label>
      <label className="review-reason">
        <span className="visually-hidden">리뷰 사유</span>
        <textarea
          aria-label="리뷰 사유"
          placeholder="리뷰 사유 또는 후속 메모"
          rows={1}
          value={draft.reason}
          onChange={(event) => onChange("reason", event.target.value)}
        />
      </label>
      <button className="review-save-button" type="button" disabled={saving} onClick={onSave}>
        {saving ? "저장 중…" : "저장하고 다음"}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M5 12h13M13 6l6 6-6 6" />
        </svg>
      </button>
      <span className="review-shortcut-hint">
        <kbd>J</kbd>
        <kbd>K</kbd>
        <span>목록 이동</span>
      </span>
      {error ? <p className="review-error" role="alert">{error}</p> : null}
    </div>
  );
}
