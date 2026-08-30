import type {
  OpportunityFirstRegisteredStage,
  OpportunityLinkView,
  OpportunityTrackingStatus,
} from "./types";
import type { BadgeVariant } from "../components/common/Badge";

/**
 * `추적`인지 `신규`인지는 계약이 정한다.
 *
 * `docs/contracts.md`: "`first_registered_stage=order_plan`이면 화면 의미는
 * `추적`, 그 밖의 `pre_spec|bid_notice`이면 `신규`이며 이 매핑을 화면이 다시
 * 정하지 않는다." 그래서 이 파일 한 곳에서만 변환한다.
 */
export type OpportunityOrigin = "추적" | "신규";

export function originOf(value: OpportunityFirstRegisteredStage | OpportunityOrigin): OpportunityOrigin {
  // Pre-spec list responses already carry the server's projected data value.
  // Accepting it here keeps the display conversion in this one module without
  // inventing an origin when the opportunity is not connected.
  if (value === "추적" || value === "신규") return value;
  return value === "order_plan" ? "추적" : "신규";
}

const stageLabels: Record<OpportunityFirstRegisteredStage, string> = {
  order_plan: "발주계획에서 시작",
  pre_spec: "사전규격에서 처음 등장",
  bid_notice: "입찰공고에서 처음 등장",
};

export function originDescription(stage: OpportunityFirstRegisteredStage): string {
  return stageLabels[stage];
}

/**
 * 추적 상태는 사람이 고른 값이다. 등급이나 준비 상태에서 유추하지 않는다.
 * `미선택`은 "관심 없음"이 아니라 아직 아무도 고르지 않았다는 뜻이다.
 */
export function trackingVariant(status: OpportunityTrackingStatus): BadgeVariant {
  if (status === "계속 추적") return "grade-1";
  if (status === "보류") return "grade-3";
  if (status === "종료") return "grade-4";
  return "neutral";
}

export function trackingDescription(status: OpportunityTrackingStatus): string {
  if (status === "계속 추적") return "새 문서·입찰공고·정정공고를 감시한다. 최종 입찰 참여 승인이 아니다.";
  if (status === "보류") return "정보나 선행 조건이 부족해 현재 결정을 미룬다. 자동 제외가 아니다.";
  if (status === "종료") return "현재 사업기회에 대한 능동 추적을 끝냈다. 영구 배제가 아니다.";
  return "아직 아무도 고르지 않았다. 관심 없음이 아니다.";
}

/**
 * `검색 미확인`은 "사전규격이 없다"가 아니라 "이름 검색으로 못 찾았다"는 뜻이다.
 * ADR-0025가 이 둘을 섞어 표시하는 것을 금지했다.
 */
export function linkStatusDescription(link: OpportunityLinkView): string {
  if (link.status === "검색 미확인") {
    return "이름 검색으로 찾지 못했다. 사전규격이 없다는 뜻이 아니다.";
  }
  if (link.status === "후보 확인 대기") return "공식 번호가 아닌 후보 관계다. 사람 확인이 필요하다.";
  if (link.status === "사람 확인 완료") return "사람이 확인한 관계다.";
  return "공식 통합번호로 확정된 관계다.";
}

export function linkRecordLabel(link: OpportunityLinkView): string {
  if (link.stage === "order_plan") return "발주계획";
  if (link.source_type === "pre_spec") return "사전규격";
  if (link.source_type === "bid_notice") return "입찰공고";
  return "공고";
}
