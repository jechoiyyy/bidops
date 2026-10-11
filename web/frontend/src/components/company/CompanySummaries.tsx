import { Badge, type BadgeVariant } from "../common/Badge";
import {
  companyFitDecisionLabel,
  companyFitStatusLabel,
  companyReviewStatusLabel,
  type CompanyFitSummary,
  type CompanyReviewSummary,
  type CompanyTrackingDTO,
} from "../../lib/companyApi";

/*
 * 회사별 핏·심층 검토·추적 요약의 표시. 서버 값을 옮길 뿐 재판정하지 않는다.
 *
 * - 핏 판정은 matched=부합, mismatch=불일치, unknown=미확인, null=판정 없음이다. C-1
 *   공고 판정 등급(`우선 검토` 등)을 가상회사 판정으로 쓰지 않는다.
 * - 판정과 실행 상태는 다른 줄이다. 실패·대기는 판정이 아니다.
 * - `is_current=false`는 "현재 입력 기준 아님"으로 따로 말한다.
 * - 적합성(핏)·심층 검토·추적 결정은 서로 다른 칸이며 서로 대신하지 않는다.
 * 색만으로 뜻을 전하지 않도록 모든 표식에 문구를 둔다.
 */

function fitVariant(fit: CompanyFitSummary): BadgeVariant {
  if (fit.status === "failed") return "danger";
  if (fit.status === "needs_human_review") return "alert";
  return "neutral";
}

export function CompanyFitSummaryView({ fit, showSummary = false }: { fit: CompanyFitSummary | null; showSummary?: boolean }) {
  if (fit === null) {
    return (
      <span className="cw-cell-stack" data-fit-decision="none">
        <Badge variant="neutral" label="판정 없음" />
        <span className="cw-caption">핏 실행 기록 없음</span>
      </span>
    );
  }
  return (
    <span className="cw-cell-stack" data-fit-decision={fit.decision ?? "null"} data-fit-status={fit.status}>
      <Badge variant={fitVariant(fit)} label={companyFitDecisionLabel(fit.decision)} />
      <span className="cw-caption">
        실행 {companyFitStatusLabel(fit.status)}
        {fit.is_current ? "" : " · 현재 입력 기준 아님"}
      </span>
      {showSummary && fit.summary ? <span className="cw-summary-text">{fit.summary}</span> : null}
    </span>
  );
}

export function CompanyReviewSummaryView({ review }: { review: CompanyReviewSummary | null }) {
  if (review === null) {
    return <span className="cw-caption" data-review-status="none">심층 검토 없음</span>;
  }
  return (
    <span className="cw-cell-stack" data-review-status={review.status}>
      <Badge variant={review.status === "failed" ? "danger" : "neutral"} label={`심층 검토 ${companyReviewStatusLabel(review.status)}`} />
      {review.is_current ? null : <span className="cw-caption">현재 입력 기준 아님</span>}
    </span>
  );
}

export function CompanyTrackingSummaryView({ tracking, showReason = false }: { tracking: CompanyTrackingDTO | null; showReason?: boolean }) {
  if (tracking === null) {
    return <span className="cw-caption" data-tracking-status="unlinked">사업기회 미연결</span>;
  }
  return (
    <span className="cw-cell-stack" data-tracking-status={tracking.tracking_status}>
      <Badge variant="neutral" label={tracking.tracking_status} />
      {tracking.selected_by ? <span className="cw-caption">{tracking.selected_by}</span> : null}
      {showReason && tracking.reason ? <span className="cw-summary-text">{tracking.reason}</span> : null}
    </span>
  );
}
