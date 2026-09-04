import type {
  NoticeDetailResponse,
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

// ---------------------------------------------------------------------------
// 사업 추적 화면의 구역·다음 행동·예외 작업 (ADR-0046 결정 2, PLAN 단계 E 작업 3)
//
// 여기의 함수는 서버가 준 값만 읽어 화면 구역을 정한다. 추적 상태를 유추하거나
// 집계를 만들어 내지 않는다. `조치 필요`는 저장된 상태가 아니라 "지금 사람이
// 손대야 하는 것이 남아 있다"는 화면 판단이며, 그 근거를 항상 함께 보여 준다.

export type TrackingSection = "조치 필요" | "추적 중" | "보류" | "추적 종료";

export const TRACKING_SECTIONS: TrackingSection[] = ["조치 필요", "추적 중", "보류", "추적 종료"];

/** 예외 작업 한 건. `kind`는 PLAN 단계 E 작업 3-2가 열거한 세 종류다. */
export type TrackingExceptionKind = "연결 불확실" | "근거 없음" | "검증 실패";

export interface TrackingException {
  kind: TrackingExceptionKind;
  /** 후보 연결 판정 대상. 그 밖의 예외는 고칠 연결이 없으므로 null이다. */
  linkId: number | null;
  /** 예외를 만든 레코드. 공고가 아니면 null이다. */
  noticeId: number | null;
  title: string;
  /** 무엇이 예외인지. 해석이 아니라 서버 값의 설명이다. */
  detail: string;
  /** 이 예외를 사람이 처리하는 길. 화면이 그 길을 실제로 갖고 있어야 한다. */
  resolution: "후보 연결 판정" | "공고 판정 수정" | "화면 밖 확인";
}

/**
 * 이 사업기회에 남아 있는 예외 작업.
 *
 * `재검토 신호`는 예외 작업이 아니다. 그것은 "다시 보라"는 신호일 뿐 고칠 대상이
 * 지정돼 있지 않으므로 시스템 신호로만 표시하고 여기에 섞지 않는다.
 */
export function linkExceptions(links: readonly OpportunityLinkView[]): TrackingException[] {
  const found: TrackingException[] = [];
  for (const link of links) {
    if (link.link_type === "candidate" && link.status === "후보 확인 대기") {
      found.push({
        kind: "연결 불확실",
        linkId: link.id,
        noticeId: link.notice_id,
        title: link.title?.trim() || "제목 미확인",
        detail: `${linkRecordLabel(link)} 후보 관계입니다. 공식 번호가 아니라 이름 검색으로 찾은 관계이므로 사람이 수용·기각을 정해야 합니다.`,
        resolution: "후보 연결 판정",
      });
      continue;
    }
    if (link.status === "검색 미확인") {
      found.push({
        kind: "근거 없음",
        linkId: link.id,
        noticeId: link.notice_id,
        title: link.title?.trim() || "제목 미확인",
        detail: "이름 검색으로 근거 레코드를 찾지 못했습니다. 레코드가 없다는 뜻이 아니며, 이 화면이 만들어 낼 수 있는 연결도 아닙니다.",
        resolution: "화면 밖 확인",
      });
    }
  }
  return found;
}

/**
 * 구역은 하나만 고른다. 한 사업기회가 목록에 두 행으로 나타나지 않게, 구역
 * 판정은 위에서부터 처음 맞는 하나에서 멈춘다(PLAN 단계 E 완료 게이트).
 *
 * `조치 필요`가 저장된 상태보다 앞선다. 사람이 `종료`를 골라 둔 뒤 새 공고가
 * 붙어도 그 사실이 구역 밖으로 사라지면 안 되기 때문이다. 행에는 저장된 추적
 * 상태 배지가 그대로 남아 무엇을 골라 뒀는지 감추지 않는다.
 */
export function trackingSectionOf(
  item: { tracking_status: OpportunityTrackingStatus; recheck_signal: boolean; links: readonly OpportunityLinkView[] },
): TrackingSection {
  if (item.tracking_status === "미선택") return "조치 필요";
  if (item.recheck_signal) return "조치 필요";
  if (linkExceptions(item.links).length > 0) return "조치 필요";
  if (item.tracking_status === "보류") return "보류";
  if (item.tracking_status === "종료") return "추적 종료";
  return "추적 중";
}

export function trackingSectionDescription(section: TrackingSection): string {
  if (section === "조치 필요") return "추적 결정이 미선택이거나, 재검토 신호나 예외 작업이 남아 있는 건입니다.";
  if (section === "추적 중") return "계속 추적으로 저장돼 있고 지금 사람이 손댈 것이 없는 건입니다.";
  if (section === "보류") return "사람이 보류를 골라 결정을 미뤄 둔 건입니다. 자동 제외가 아닙니다.";
  return "사람이 능동 추적을 끝낸 건입니다. 영구 배제가 아닙니다.";
}

/**
 * 다음 행동은 하나만 말한다. 여러 개를 나열하면 무엇부터 할지 화면이 답하지
 * 못하고, 사람은 결국 상세를 다시 읽어야 한다.
 */
export function nextActionOf(
  item: { tracking_status: OpportunityTrackingStatus; recheck_signal: boolean; links: readonly OpportunityLinkView[] },
): { label: string; variant: BadgeVariant } {
  if (item.tracking_status === "미선택") return { label: "추적 결정", variant: "alert" };
  const exceptions = linkExceptions(item.links);
  if (exceptions.some((entry) => entry.kind === "연결 불확실")) return { label: "연결 확인", variant: "alert" };
  if (item.recheck_signal) return { label: "재검토", variant: "alert" };
  if (exceptions.length > 0) return { label: "근거 확인", variant: "evidence-unknown" };
  if (item.tracking_status === "보류") return { label: "보류 유지", variant: "neutral" };
  if (item.tracking_status === "종료") return { label: "조치 없음", variant: "neutral" };
  return { label: "추적 유지", variant: "focus" };
}

/**
 * 공고 한 건이 남긴 검증 실패.
 *
 * 판정의 확인 항목 중 `blocking`인데 아직 답이 없거나 실패로 남은 것이다.
 * 담당자 리뷰의 답변이 그 항목을 해소하므로, 리뷰에 같은 이름의 답이 있으면
 * 해소된 것으로 본다. 답의 내용을 판정으로 읽지 않는다 — 답이 있는지 없는지만
 * 본다.
 */
export function noticeVerificationExceptions(notice: NoticeDetailResponse): TrackingException[] {
  const items = notice.judgment?.verification_items ?? [];
  const answered = new Set(
    notice.reviews.flatMap((review) => review.answers.map((answer) => (answer.item ?? "").trim()).filter(Boolean)),
  );
  return items
    .filter((item) => item.blocking && !answered.has((item.item ?? "").trim()))
    .map((item) => ({
      kind: "검증 실패" as const,
      linkId: null,
      noticeId: notice.id,
      title: item.item?.trim() || "확인 항목 이름 미확인",
      detail: item.why?.trim()
        ? `${item.why.trim()} · 현재 상태 ${item.status?.trim() || "unknown"}`
        : `blocking 확인 항목에 담당자 답변이 없습니다 · 현재 상태 ${item.status?.trim() || "unknown"}`,
      resolution: "공고 판정 수정" as const,
    }));
}
