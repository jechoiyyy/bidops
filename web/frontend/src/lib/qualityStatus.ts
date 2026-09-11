import type { BadgeVariant } from "../components/common/Badge";
import type { QualityStatus } from "../components/deep-review/types";

// 개요 카드(사전규격 상세)와 심층 보고서(상단 카드·최종 의견 저장 form 위)가
// 같은 문구를 각자 다시 정의하지 않도록 한곳에 모은다. 문구는 명세가 정한
// 그대로이며 화면이 부드럽게 바꾸지 않는다 — 참조 실행 결과를 운영 완료나
// 품질 근거로 보이게 하는 표현을 만들지 않는다.

export const QUALITY_STATUS_LABEL: Record<QualityStatus, string> = {
  measured: "측정 통과",
  unmeasured_reference: "참조 실행 · 품질 미측정",
  mock_reference: "mock 참조",
};

/** `quality_status`가 없는 옛 revision은 `null`이다. `null`은 "미측정"이 아니라
 * "표식이 없다"이므로 미측정으로 승격시키지 않는다. */
export const QUALITY_STATUS_ABSENT_LABEL = "표식 없음";

export function qualityStatusLabel(status: QualityStatus | null | undefined): string {
  if (status === null || status === undefined) return QUALITY_STATUS_ABSENT_LABEL;
  return QUALITY_STATUS_LABEL[status];
}

/** 미측정·mock·표식 없음은 성공도 실패도 아니다. PRD §4.1이 정한 대로 무채색을
 * 쓰고, 색이 아니라 문구가 상태를 전달한다. */
export function qualityStatusVariant(
  status: QualityStatus | null | undefined,
): BadgeVariant {
  if (status === "measured") return "evidence-confirmed";
  if (status === null || status === undefined) return "evidence-unknown";
  return "neutral";
}

export function qualityStatusNote(
  status: QualityStatus | null | undefined,
): string {
  if (status === "measured") return "고정 입력의 품질 게이트를 통과한 실행입니다.";
  if (status === "mock_reference") return "mock provider로 만든 참조 실행입니다. 운영 결과가 아닙니다.";
  if (status === "unmeasured_reference") return "참조 실행이며 품질을 측정하지 않았습니다. 운영 완료로 읽지 마십시오.";
  return "이 기록에는 품질 표식이 없습니다. 없음을 미측정으로 바꾸지 않습니다.";
}
