import type { OpportunityDetailResponse, OpportunityLinkView, OpportunityListItem } from "../../lib/types";

/**
 * 사업 추적 화면이 읽는 생애주기 사실.
 *
 * 여기의 함수는 **서버가 준 값만** 읽는다. 구역(`section`)·후보 수
 * (`pending_candidate_link_count`)·미해결 확인 항목 수(`open_blocking_item_count`)는
 * 서버가 계산해 주므로 화면이 다시 판정하지 않는다. 이 파일이 하는 일은 저장된
 * 연결을 시안의 3단계 줄(발주계획·사전규격·입찰공고)과 `다음 확인` 한 줄로
 * 옮기는 표시 변환뿐이다.
 *
 * 지키는 것:
 * - 체크 표시는 **연결 확정**을 뜻한다. 분석 완료나 입찰 승인을 뜻하지 않는다.
 * - 기각된 후보는 확정으로 승격하지 않는다. 이력으로만 남는다.
 * - `검색 미확인`은 "레코드가 없다"가 아니라 "이름 검색으로 못 찾았다"이다.
 * - 확정된 최근 단계는 확정 연결에서만 나온다. 대기 중 후보는 올리지 않는다.
 */

export type LifecycleStage = "발주계획" | "사전규격" | "입찰공고";

export const LIFECYCLE_STAGES: LifecycleStage[] = ["발주계획", "사전규격", "입찰공고"];

/** 연결 하나가 가리키는 생애주기 단계. 단계를 알 수 없으면 null이다. */
export function stageOfLink(link: OpportunityLinkView): LifecycleStage | null {
  if (link.stage === "order_plan") return "발주계획";
  if (link.source_type === "pre_spec") return "사전규격";
  if (link.source_type === "bid_notice") return "입찰공고";
  return null;
}

/** 사람이 기각한 후보. 확정으로 쓰지 않지만 목록에서 숨기지도 않는다. */
export function isRejectedCandidate(link: OpportunityLinkView): boolean {
  return link.human_decision === "rejected";
}

/**
 * 확정 연결. `docs/contracts.md`가 정한 authoritative 조합 그대로다:
 * `(official + 확정)` 또는 `(candidate + 사람 확인 완료 + accepted)`.
 */
export function isConfirmedLink(link: OpportunityLinkView): boolean {
  if (link.link_type === "official") return link.status === "확정";
  return link.status === "사람 확인 완료" && link.human_decision === "accepted";
}

export function isPendingCandidate(link: OpportunityLinkView): boolean {
  return link.link_type === "candidate" && link.status === "후보 확인 대기";
}

export type StageConnection = "공식 연결" | "사람 확인 완료" | "후보 확인 대기" | "검색 미확인" | "사람 확인 병합" | "연결 미확인";

export interface StageView {
  stage: LifecycleStage;
  connection: StageConnection;
  confirmed: boolean;
  candidate: boolean;
}

/** 3단계 줄 하나. 같은 단계에 연결이 여럿이면 확정을 우선해 상태를 정한다. */
export function stageViews(links: readonly OpportunityLinkView[]): StageView[] {
  return LIFECYCLE_STAGES.map((stage) => {
    const inStage = links.filter((link) => stageOfLink(link) === stage && !isRejectedCandidate(link));
    const confirmed = inStage.find(isConfirmedLink);
    if (confirmed) {
      return {
        stage,
        connection: confirmed.link_type === "official" ? "공식 연결" : "사람 확인 완료",
        confirmed: true,
        candidate: false,
      };
    }
    if (inStage.some(isPendingCandidate)) {
      return { stage, connection: "후보 확인 대기", confirmed: false, candidate: true };
    }
    if (inStage.some((link) => link.status === "검색 미확인")) {
      return { stage, connection: "검색 미확인", confirmed: false, candidate: false };
    }
    return { stage, connection: "연결 미확인", confirmed: false, candidate: false };
  });
}

/** 확정된 최근 단계. 확정 연결이 하나도 없으면 `확인 전`이다. */
export function latestConfirmedStage(links: readonly OpportunityLinkView[]): LifecycleStage | "확인 전" {
  const confirmed = stageViews(links).filter((view) => view.confirmed);
  return confirmed.length > 0 ? confirmed[confirmed.length - 1].stage : "확인 전";
}

export type NextCheckKey =
  | "tracking_decision"
  | "candidate_link"
  | "recheck"
  | "blocking_item"
  | "search_unconfirmed"
  | "hold_reason"
  | "end_reason"
  | "linked_records";

export interface NextCheck {
  key: NextCheckKey;
  label: string;
  /** 상세에서 한 문단으로 읽히는 설명. 없는 사실을 채우지 않는다. */
  description: string;
}

type TrackingFacts = Pick<
  OpportunityListItem,
  "tracking_status" | "tracking_reason" | "recheck_signal" | "pending_candidate_link_count" | "open_blocking_item_count" | "links"
>;

/**
 * 다음 확인 하나.
 *
 * 여러 개를 나열하면 무엇부터 할지 화면이 답하지 못한다. 위에서부터 처음 맞는
 * 하나에서 멈춘다.
 */
export function nextCheckOf(item: TrackingFacts): NextCheck {
  if (item.tracking_status === "미선택") {
    return {
      key: "tracking_decision",
      label: "추적 결정",
      description: "아직 추적 여부를 선택하지 않았습니다. 연결된 공고를 읽고 추적 범위를 정해 주세요.",
    };
  }
  if (item.pending_candidate_link_count > 0) {
    return {
      key: "candidate_link",
      label: "연결 후보 확인",
      description: "공식 통합번호가 아니라 이름 검색으로 찾은 후보입니다. 같은 사업인지 확인하면 사업 흐름에 연결할 수 있습니다.",
    };
  }
  if (item.recheck_signal) {
    return {
      key: "recheck",
      label: "새 공고 재검토",
      description: "새 공식 레코드가 연결되어 재검토 신호가 남아 있습니다. 공고 내용과 기존 검토 내용을 확인해 주세요.",
    };
  }
  if (item.open_blocking_item_count > 0) {
    return {
      key: "blocking_item",
      label: "확인 항목 답변",
      description: "연결된 공고의 blocking 확인 항목에 담당자 답변이 없습니다. 원문에서 확인한 사실을 남겨 주세요.",
    };
  }
  if (item.links.some((link) => link.status === "검색 미확인")) {
    return {
      key: "search_unconfirmed",
      label: "연결 근거 확인",
      description: "이름 검색에서 레코드를 찾지 못했습니다. 레코드가 없다는 뜻은 아닙니다.",
    };
  }
  if (item.tracking_status === "보류") {
    return {
      key: "hold_reason",
      label: "보류 사유 확인",
      description: item.tracking_reason?.trim() || "보류로 저장돼 있지만 기록된 사유가 없습니다.",
    };
  }
  if (item.tracking_status === "종료") {
    return {
      key: "end_reason",
      label: "종료 사유 확인",
      description: item.tracking_reason?.trim() || "종료로 저장돼 있지만 기록된 사유가 없습니다.",
    };
  }
  return {
    key: "linked_records",
    label: "연결 공고 확인",
    description: "현재 연결된 공고와 추적 결정을 확인할 수 있습니다.",
  };
}

/** 행 오른쪽 열의 보조 한 줄. 숫자는 서버가 센 값만 쓴다. */
export function nextCheckNote(item: TrackingFacts & { id: number }): string {
  if (item.pending_candidate_link_count > 0) return `후보 ${item.pending_candidate_link_count}건`;
  if (item.recheck_signal) return "재검토 신호";
  if (item.open_blocking_item_count > 0) return `확인 항목 ${item.open_blocking_item_count}건`;
  return `#${String(item.id).padStart(3, "0")}`;
}

/**
 * 제목·기관은 확정 연결에서 먼저 찾는다. 기각된 후보의 제목을 사업 이름으로
 * 올리지 않기 위해서다. 확정이 없으면 대기 중 후보, 그다음이 그 밖의 기록이다.
 */
function orderedLinks(item: { links: readonly OpportunityLinkView[] }): OpportunityLinkView[] {
  const confirmed = item.links.filter(isConfirmedLink);
  const pending = item.links.filter(isPendingCandidate);
  const rest = item.links.filter((link) => !isConfirmedLink(link) && !isPendingCandidate(link) && !isRejectedCandidate(link));
  const rejected = item.links.filter(isRejectedCandidate);
  return [...confirmed, ...pending, ...rest, ...rejected];
}

export function primaryTitle(item: OpportunityListItem | OpportunityDetailResponse): string {
  const named = orderedLinks(item).find((link) => link.title && link.title.trim());
  return named?.title?.trim() || "제목 미확인";
}

export function primaryAgency(item: OpportunityListItem | OpportunityDetailResponse): string {
  const named = orderedLinks(item).find((link) => link.agency && link.agency.trim());
  return named?.agency?.trim() || "기관 미확인";
}

/**
 * 연결 하나의 상태를 3단계 줄과 같은 말로 적는다. 저장된 `status`를 다른 뜻으로
 * 바꾸지 않고 `확정`이 공식 번호로 맺어진 관계라는 것만 이름으로 드러낸다.
 */
export function connectionLabel(link: OpportunityLinkView): StageConnection {
  if (link.status === "확정") return link.link_type === "official" ? "공식 연결" : "사람 확인 완료";
  return link.status;
}

/** 날짜·시각은 시안과 같은 조밀한 표기로 적는다. 값이 없으면 채우지 않는다. */
export function formatMoment(value: string | null): string {
  if (!value) return "미확인";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${parsed.getFullYear()}.${pad(parsed.getMonth() + 1)}.${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

/** 연결이 가리키는 실제 원천 화면 route. 없는 화면을 만들어 내지 않는다. */
export function recordRoute(link: OpportunityLinkView): string | null {
  // 발주계획은 별도 상세 route 없이 목록의 우측 pane을 연다. OpportunityLinkView에는
  // source_run_id가 없으므로, 확인되지 않은 회차를 URL에 덧붙이지 않는다.
  if (link.order_plan_id !== null) return `/order-plans?selected=${link.order_plan_id}`;
  if (link.notice_id === null) return null;
  if (link.source_type === "pre_spec") return `/pre-specs/${link.notice_id}`;
  return `/judgments/${link.notice_id}`;
}

/** 링크 버튼의 이름. 화면 이름을 그대로 말한다. */
export function recordRouteLabel(link: OpportunityLinkView): string {
  if (link.order_plan_id !== null) return "발주계획 검토목록 열기";
  if (link.source_type === "pre_spec") return "사전규격 상세 열기";
  return "공고 판정 이력 열기";
}
