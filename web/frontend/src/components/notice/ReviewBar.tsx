import { useState } from "react";
import { ReviewFilterSelector, ReviewFilterSegmentedControl } from "../common/ReviewPrimitives";
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
  dirty: boolean;
  error: string | null;
  onChange: <K extends keyof ReviewDraft>(key: K, value: ReviewDraft[K]) => void;
  onDiscard: () => void;
  onSave: () => void;
}

const judgmentOptions = ["동의", "등급 수정", "근거 부족"];

export function ReviewBar({ draft, perspectives, saving, dirty, error, onChange, onDiscard, onSave }: ReviewBarProps) {
  const [showMore, setShowMore] = useState(false);
  // 보조 영역에 값이 들어 있으면 개수를 표시해 입력한 값이 사라진 것으로 오인하지 않게 한다.
  const secondaryFilled = [draft.corrected_grade, draft.corrected_readiness, draft.weakest_perspective]
    .filter((value) => value !== "").length;

  return (
    <section className="review-bar" aria-label="담당자 리뷰 입력">
      <div className="review-bar-title">
        <strong>담당자 리뷰</strong>
        <span>DB 정본</span>
        {dirty ? (
          <span className="review-dirty" role="status">
            저장되지 않은 변경사항
            <button type="button" onClick={onDiscard}>되돌리기</button>
          </span>
        ) : null}
      </div>
      <ReviewFilterSegmentedControl
        className="review-segmented"
        isDisabled={saving}
        label="시스템 판정 검토"
        onChange={(value) => onChange("system_judgment_review", value)}
        options={judgmentOptions.map((option) => ({ label: option, value: option }))}
        value={draft.system_judgment_review || "__not_selected__"}
      />
      <div className="review-control review-control-selector">
        <span className="review-control-label">최종 처리</span>
        <ReviewFilterSelector
          isDisabled={saving}
          label="최종 처리"
          onChange={(value) => onChange("disposition", value ?? "")}
          options={[
            { value: "심층 검토 진행", label: "심층 검토 진행" },
            { value: "관찰", label: "관찰" },
            { value: "제외", label: "제외" },
          ]}
          placeholder="선택 안 함"
          value={draft.disposition || null}
        />
      </div>
      <div className={`review-secondary ${showMore ? "is-open" : ""}`.trim()} id="review-secondary-fields">
        <div className="review-control review-control-selector">
          <span className="review-control-label">수정 등급</span>
          <ReviewFilterSelector
            isDisabled={saving}
            label="수정 등급"
            onChange={(value) => onChange("corrected_grade", value ?? "")}
            options={[
              { value: "우선 검토", label: "우선 검토" },
              { value: "검토 권장", label: "검토 권장" },
              { value: "관찰 대상", label: "관찰 대상" },
              { value: "제외", label: "제외" },
            ]}
            placeholder="수정 없음"
            value={draft.corrected_grade || null}
          />
        </div>
        <div className="review-control review-control-selector">
          <span className="review-control-label">수정 준비 상태</span>
          <ReviewFilterSelector
            isDisabled={saving}
            label="수정 준비 상태"
            onChange={(value) => onChange("corrected_readiness", value ?? "")}
            options={[
              { value: "확인 완료", label: "확인 완료" },
              { value: "부분 확인 필요", label: "부분 확인 필요" },
              { value: "참여 불가 확인", label: "참여 불가 확인" },
            ]}
            placeholder="수정 없음"
            value={draft.corrected_readiness || null}
          />
        </div>
        <div className="review-control review-control-selector review-control-perspective">
          <span className="review-control-label">근거 부족 관점</span>
          <ReviewFilterSelector
            isDisabled={saving}
            label="근거 부족 관점"
            onChange={(value) => onChange("weakest_perspective", value ?? "")}
            options={perspectives
              .filter((perspective) => Boolean(perspective.name))
              .map((perspective) => ({ value: perspective.name as string, label: perspective.name as string }))}
            placeholder="선택 안 함"
            value={draft.weakest_perspective || null}
          />
        </div>
      </div>
      <button
        aria-controls="review-secondary-fields"
        aria-expanded={showMore}
        className="review-more-toggle"
        type="button"
        onClick={() => setShowMore((current) => !current)}
      >
        등급·준비 상태 수정
        {secondaryFilled > 0 ? <span className="mono tabular-nums">{secondaryFilled}</span> : null}
      </button>
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
    </section>
  );
}
