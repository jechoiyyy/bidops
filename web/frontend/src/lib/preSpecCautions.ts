import { preSpecAutoPreparationReasonLabel } from "./preSpecAutoPreparation";
import type { PageOverviewVerification, PreSpecListItem } from "./types";

// 사전규격 목록 우측 정보 영역의 `주의사항` 한 줄을 만든다
// (docs/0915_ui-redesign/spec.md §3.2).
//
// **결정적 산출이고 모델 호출이 없다.** 이미 받은 목록 projection(`document`
// 집계·자동 준비 상태), 개요 주장 검증 기록, (읽는 화면만) 심층 검토 보고서의
// `unknowns` 건수만 세고 고른다. 개요 결과에는 더 이상 `unknowns`가 없다
// (ADR-0057 결정 1) — 참여 조건·위험·미확인은 심층 검토의 몫이다. 새 분석·정보
// 추출·문장 생성은 하지 않으며, 값이 없으면 문구를 지어내지 않고 `null`로
// 남긴다. 표시 문구는 `formatPreSpecCaution`이 정한다.

export interface PreSpecCautionInput {
  /** 목록 projection 한 건. `document.차단`·`document.실패`와 자동 준비 상태·사유를 읽는다. */
  item: PreSpecListItem;
  /** 현재 개요 실행의 주장 검증 기록. 공개할 검증이 없으면 `null`이다. */
  verification: PageOverviewVerification | null;
  /** 심층 검토 보고서의 `unknowns` 건수. 그 보고서를 실제로 읽는 화면만 채운다.
   * 읽는 경로가 없거나(예: 목록 상세) 아직 읽지 못했으면 `null`이며, `0`으로
   * 지어내 측정한 것처럼 보이지 않는다. */
  deepReviewUnknownCount: number | null;
}

export interface PreSpecCautionResult {
  /** 주의 건수 N. */
  count: number;
  /** 미확인 건수 M. 심층 검토 보고서를 읽지 않았으면 `null`이다. */
  unknownCount: number | null;
  /** 한 줄에 실을 문구. 어느 출처에도 문장이 없으면 `null`이다. */
  headline: string | null;
  tone: "caution" | "none";
}

/**
 * spec §3.2의 주의 건수와 한 줄 문구를 센다.
 *
 * "결정적 검사 실패"는 주장 하나의 `deterministic_status === "failed"`다
 * (`src/lib/types.ts:647` `PageOverviewVerificationClaim`). 화면이 이미 그 값을
 * `결정적 검사 실패`로 읽고 있으므로(`PageOverviewSection.tsx:250` 의
 * `DETERMINISTIC_STATUS_LABEL`, 그리는 자리는 같은 파일 308줄) 같은 규칙을 쓴다.
 * `semantic_status`나 `verification.status`는 여기서 세지 않는다 — 그것은 결정적
 * 검사가 아니다.
 */
export function preSpecCautions({ item, verification, deepReviewUnknownCount }: PreSpecCautionInput): PreSpecCautionResult {
  const failedClaims = (verification?.claims ?? []).filter((claim) => claim.deterministic_status === "failed");
  const blockedAttachments = item.document["차단"];
  const failedAttachments = item.document["실패"];
  // `blocked`는 자동 준비가 멈춘 상태 하나이므로 건수도 1이다.
  const blockedPreparation = item.auto_preparation_status === "blocked" ? 1 : 0;
  const count = failedClaims.length + blockedAttachments + failedAttachments + blockedPreparation;

  // 문구 우선순위는 spec §3.2 그대로다. 사유 코드는 이미 있는 라벨 표를 재사용하고,
  // 표에 없는 코드는 코드 그대로 남는다(`preSpecAutoPreparationReasonLabel`). 심층
  // 검토 미확인은 건수만 있고 문장이 없어 headline 우선순위에는 오르지 않는다.
  const attachmentHeadline = blockedAttachments + failedAttachments > 0
    ? `첨부 차단 ${blockedAttachments} · 실패 ${failedAttachments}`
    : null;
  const headline = failedClaims[0]?.text
    ?? attachmentHeadline
    ?? preSpecAutoPreparationReasonLabel(item.auto_preparation_reason)
    ?? null;

  return {
    count,
    unknownCount: deepReviewUnknownCount,
    headline,
    tone: count > 0 ? "caution" : "none",
  };
}

/**
 * spec §3.2의 표시 문자열. `미확인 {M}`은 M이 `null`이거나 0이면 붙이지
 * 않는다 — 주의도 미확인도 없는 건은 `주의 없음` 한 마디로 끝난다.
 */
export function formatPreSpecCaution(result: PreSpecCautionResult): string {
  const unknownSuffix = result.unknownCount !== null && result.unknownCount > 0 ? ` · 미확인 ${result.unknownCount}` : "";
  if (result.count === 0) return `주의 없음${unknownSuffix}`;
  const headline = result.headline ? ` · ${result.headline}` : "";
  return `주의 ${result.count}건${headline}${unknownSuffix}`;
}
