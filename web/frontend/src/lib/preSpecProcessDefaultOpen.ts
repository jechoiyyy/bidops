import type { BundleView } from "../components/deep-review/types";
import { documentPanelDefaultOpen } from "./documentPanelDefaultOpen";
import type { CompanyFitAttempt, PageOverviewCurrent, PageOverviewRangeReview, PageOverviewVerification, PreSpecAutoPreparationStatus } from "./types";

/**
 * 사전규격 상세 맨 아래 `처리 상태·기술 정보` 구역의 기본 열림 규칙(2026-11-21 시안 `docs/specs/1121_prespec-detail/`).
 *
 * 구역은 기본 닫힘이다. 문제가 있을 때만 열린 채로 들어온다. "문제"는 새로 정하지 않고, 이 구역으로 옮겨 온
 * 두 접힘이 이미 스스로 열리던 조건을 그대로 합친다:
 *
 * - 문서 준비 패널(`documentPanelDefaultOpen`) — 묶음이 없거나 확정 전이거나, 자동 준비가 막혔을 때. 패널이
 *   열려 있어야 묶음 상태를 2초마다 다시 읽으므로 이 조건을 빼면 진행 중인 준비가 화면에서 멈춘다.
 * - 접힌 `기술 정보`(`preSpecTechnicalInfoDefaultOpen`) — 개요 실패·취소·사람 확인, 회사 적합성 실패·사람 확인,
 *   묶음 실패·격리·사람 확인, 주장 검증 사람 확인.
 *
 * 예외(2026-11-21 문제 상태 안내 시안 c1~c5): 개요 구역 맨 위에 문제 상태 안내가 보이면 구역은 닫힌 채로 들어온다.
 * 안내가 사유와 할 일을 말하고, 요약 줄이 멈춘 단계를 말하며, 열면 관련 블록이 먼저 보인다.
 */
export function preSpecTechnicalInfoDefaultOpen(input: {
  bundle: BundleView | null;
  overviewCurrent: PageOverviewCurrent | null;
  companyFitAttempt: CompanyFitAttempt | null;
  verification: PageOverviewVerification | null;
}): boolean {
  const { bundle, overviewCurrent, companyFitAttempt, verification } = input;
  return overviewCurrent?.status === "failed"
    || overviewCurrent?.status === "needs_human_review"
    || overviewCurrent?.status === "cancelled"
    || companyFitAttempt?.status === "failed"
    || companyFitAttempt?.status === "needs_human_review"
    || bundle?.status === "failed"
    || bundle?.status === "quarantined"
    || bundle?.status === "needs_review"
    || verification?.status === "needs_human_review";
}

export function preSpecProcessDefaultOpen(input: {
  bundle: BundleView | null;
  autoStatus: PreSpecAutoPreparationStatus | null;
  overviewCurrent: PageOverviewCurrent | null;
  companyFitAttempt: CompanyFitAttempt | null;
  verification: PageOverviewVerification | null;
  /** 개요 입력 범위를 사람이 확정해야 하는 상태(시안 a3). 범위 폼은 개요 구역 자리에 있고 이 구역은 열린다. */
  rangeReview: PageOverviewRangeReview | null;
  /**
   * 개요 구역 맨 위에 문제 상태 안내(`lib/preSpecProblemNotice.ts`, 시안 c1~c5)가 보이는가. 보이면 이 구역은 닫힌 채로
   * 들어온다 — 무엇이 멈췄고 무엇을 할지는 안내가 말하고, 구역 요약 줄이 멈춘 단계를 말한다. 안내 링크·토글로 연다.
   */
  problemNotice?: boolean;
}): boolean {
  if (input.problemNotice) return false;
  return documentPanelDefaultOpen(input.bundle, input.autoStatus)
    || preSpecTechnicalInfoDefaultOpen(input)
    || input.rangeReview?.selection_status === "needs_human_review";
}
