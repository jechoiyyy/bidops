import type { HTMLAttributes } from "react";

/**
 * 화면 배지는 한 벌이다. `Badge`가 그 한 벌이고 `StatusBadge`는 tone 이름만
 * 바꿔 주는 얇은 alias다(`StatusBadge.tsx`). 스타일은 `theme.css`의 `.badge-*`
 * 규칙 한 집합만 쓴다.
 *
 * 의미색 다섯 갈래를 서로 대신하지 않는다.
 *
 * - `neutral`  상태를 아직 모르거나 성패가 아닌 값
 * - `info`     안내·참고(준비 상태, 추론 근거)
 * - `success`  확인된 것
 * - `alert`    **경고** — 사람이 확인해야 하지만 아직 실패가 아니다
 *              (후보 연결, 재검토 근거, 검증 대기, 첨부 없음…)
 * - `danger`   **오류·실패·차단·격리** — 이미 잘못됐거나 진행을 막는 것
 *
 * 경고와 오류를 같은 노랑으로 칠하면 "확인해 보세요"와 "이건 실패했습니다"가
 * 한 색이 된다. 두 색은 문구와 함께 쓰이며 색만으로 상태를 말하지 않는다
 * (`web/frontend/AGENTS.md` "상태 표현").
 *
 * 참조 실행(`unmeasured_reference`)·mock·표식 없음은 성공도 실패도 아니므로
 * 여기의 success/danger를 쓰지 않는다. `lib/qualityStatus.ts`가 그 규칙을
 * 소유한다.
 */
export type BadgeVariant =
  | "grade-1"
  | "grade-2"
  | "grade-3"
  | "grade-4"
  | "readiness"
  | "focus"
  | "info"
  | "success"
  | "alert"
  | "danger"
  | "neutral"
  | "evidence-confirmed"
  | "evidence-inferred"
  | "evidence-unknown";

const defaultLabels: Record<BadgeVariant, string> = {
  "grade-1": "우선 검토",
  "grade-2": "검토 권장",
  "grade-3": "관찰 대상",
  "grade-4": "제외",
  readiness: "준비 상태 미확인",
  focus: "역량 축 미확인",
  info: "참고",
  success: "확인됨",
  alert: "확인 필요",
  danger: "실패",
  neutral: "상태 미확인",
  "evidence-confirmed": "confirmed",
  "evidence-inferred": "inferred",
  "evidence-unknown": "unknown",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant: BadgeVariant;
  label?: string | null;
}

/** 등급 4단은 심각도가 아니라 우선순위 순서다. 색은 grade-ramp.css 의
 * `--bo-grade-*` 농도 한 벌만 쓰고, 인접 단의 대비가 1.9~2.1 이라 색만으로는
 * 구분되지 않으므로 라벨을 지울 수 없게 여기서 기본값을 채운다(ADR-0048 §3). */
const GRADE_LEVELS: Partial<Record<BadgeVariant, number>> = {
  "grade-1": 1,
  "grade-2": 2,
  "grade-3": 3,
  "grade-4": 4,
};

export function Badge({ variant, label, className = "", ...props }: BadgeProps) {
  const text = label && label.trim() ? label : defaultLabels[variant];
  const gradeLevel = GRADE_LEVELS[variant];
  return (
    <span
      className={`badge badge-${variant} ${className}`.trim()}
      data-grade-level={gradeLevel}
      data-review-primitive={gradeLevel === undefined ? undefined : "grade"}
      {...props}
    >
      {text}
    </span>
  );
}
