import { Selector } from "@astryxdesign/core/Selector";
import { TextArea } from "@astryxdesign/core/TextArea";

/**
 * 일괄 창(발주계획 추적 시작·종료, 사전규격 검토 제외)이 함께 쓰는 사유 입력.
 *
 * 2026-09-23 승인 시안(`docs/0915_ui-redesign/mockups/0923_bulk-end-unify/`)의 정본:
 * 사유는 선택지에서 고르고 `기타 · 직접 입력`일 때만 입력칸이 열린다. `hasClear`의 ×는
 * 고른 값과 적어 둔 기타 문장을 함께 비운다. 화면은 사유를 자동으로 고르지 않는다.
 */

/** 종료·제외 사유 선택지(시안 승인본). 발주계획 일괄 종료와 사전규격 검토 제외가 쓴다. */
export const BULK_EXCLUSION_REASONS = [
  "현재 검토 범위와 맞지 않음",
  "중복·오탐으로 확인",
  "참여 자격·실적 요건 미충족",
  "사업 규모·시기가 맞지 않음",
] as const;

/** 서버 사전규격 검토 제외 사유 상한과 같다. 발주계획 일괄 사유도 같은 상한을 둔다. */
export const BULK_REASON_MAX_LENGTH = 2000;

/** 자유 입력을 여는 선택지의 값. 사유 문자열이 아니라 표식이므로 계약에 싣지 않는다. */
const OTHER_CHOICE = "__bulk_other__";
const OTHER_LABEL = "기타 · 직접 입력";

export interface BulkReasonDraft {
  /** 고른 선택지 문장, 기타 표식, 또는 아직 고르지 않음(`null`). */
  choice: string | null;
  /** `기타 · 직접 입력`에 적은 문장. 기타를 고르지 않았으면 저장 값에 쓰이지 않는다. */
  other: string;
}

/**
 * 빈 초안. 선택지가 없으면(예: 검토 목록 복원) 자유 입력만 받으므로 처음부터 기타 상태다.
 */
export function emptyBulkReason(options: readonly string[]): BulkReasonDraft {
  return { choice: options.length === 0 ? OTHER_CHOICE : null, other: "" };
}

/** 저장할 사유 문장: 고른 선택지 문장 또는 기타 문장(앞뒤 공백 제거). */
export function bulkReasonText(draft: BulkReasonDraft): string {
  if (draft.choice === null) return "";
  return draft.choice === OTHER_CHOICE ? draft.other.trim() : draft.choice;
}

/**
 * 저장돼 있던 사유 문장을 초안으로 되돌린다(대기 요청 복구). 선택지에 있는 문장이면
 * 그 선택지로, 아니면 기타 문장으로 둔다. 문장을 바꾸지 않는다.
 */
export function bulkReasonDraftFromText(text: string, options: readonly string[]): BulkReasonDraft {
  if (!text) return emptyBulkReason(options);
  return options.includes(text) ? { choice: text, other: "" } : { choice: OTHER_CHOICE, other: text };
}

/** 저장을 막는 사유 입력 문제. 없으면 `null`. */
export function bulkReasonError(draft: BulkReasonDraft, requiredMessage: string): string | null {
  if (draft.choice === null) return requiredMessage;
  if (draft.choice !== OTHER_CHOICE) return null;
  const text = draft.other.trim();
  if (!text) return "사유를 직접 입력하십시오.";
  if ([...text].length > BULK_REASON_MAX_LENGTH) return "사유는 2,000자 이하여야 합니다.";
  return null;
}

export interface BulkReasonFieldProps {
  /** 선택지(또는 선택지가 없을 때 입력칸)의 라벨. 예: `종료 사유 (필수)`. */
  label: string;
  /** 고를 문장들. 비어 있으면 드롭다운 없이 자유 입력칸만 그린다. */
  options: readonly string[];
  value: BulkReasonDraft;
  onChange: (next: BulkReasonDraft) => void;
  isDisabled?: boolean;
}

export function BulkReasonField({ label, options, value, onChange, isDisabled = false }: BulkReasonFieldProps) {
  const otherOpen = value.choice === OTHER_CHOICE;
  const otherInput = (
    <TextArea
      label={options.length === 0 ? label : "사유 직접 입력"}
      value={value.other}
      onChange={(next) => onChange({ choice: OTHER_CHOICE, other: next })}
      rows={3}
      maxLength={BULK_REASON_MAX_LENGTH}
      placeholder="사유를 직접 적어 주세요 (최대 2,000자)"
      isDisabled={isDisabled}
    />
  );
  if (options.length === 0) {
    return <div className="bulk-reason-field">{otherInput}</div>;
  }
  return (
    <div className="bulk-reason-field">
      <Selector
        hasClear
        label={label}
        options={[
          ...options.map((option) => ({ label: option, value: option })),
          { label: OTHER_LABEL, value: OTHER_CHOICE },
        ]}
        placeholder="사유를 선택하세요"
        value={value.choice}
        // ×로 지우면 기타 문장도 함께 비운다(시안 ⑥). 다른 선택지로 옮길 때는 적어 둔
        // 기타 문장을 남긴다 — 저장 값에는 기타를 고른 경우에만 쓰인다.
        onChange={(next) => onChange(next === null ? { choice: null, other: "" } : { choice: next, other: value.other })}
        isDisabled={isDisabled}
      />
      {otherOpen ? otherInput : null}
    </div>
  );
}
