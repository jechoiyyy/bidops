import { Link } from "react-router-dom";
import { Badge } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import type { DeadlineNotice } from "../../lib/types";
import { formatNumber } from "../../lib/format";
import { gradeVariant } from "../../lib/grade";

interface DeadlineTableProps {
  notices: DeadlineNotice[];
  referenceAt: string | null;
  timezone: string;
  runId: string | null;
}

// 3일 이내는 오늘 손을 대야 하는 구간이라 행 전체를 표시해 둔다.
function isCritical(deadline: string | null, referenceAt: string | null): boolean {
  const deadlineMs = new Date(deadline ?? "").getTime();
  const referenceMs = referenceAt ? new Date(referenceAt).getTime() : Number.NaN;
  if (Number.isNaN(deadlineMs) || Number.isNaN(referenceMs)) return false;
  return Math.ceil((deadlineMs - referenceMs) / (24 * 60 * 60 * 1000)) <= 3;
}


function daysUntil(deadline: string | null, referenceAt: string | null): string {
  if (!deadline) return "마감일 미확인";
  const deadlineMs = new Date(deadline).getTime();
  const referenceMs = referenceAt ? new Date(referenceAt).getTime() : Number.NaN;
  if (Number.isNaN(deadlineMs) || Number.isNaN(referenceMs)) return "D-?";
  const days = Math.max(0, Math.ceil((deadlineMs - referenceMs) / (24 * 60 * 60 * 1000)));
  return `D-${days}`;
}

function formatDeadline(value: string | null, timezone: string): string {
  if (!value) return "마감 시각 미확인";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "마감 시각 미확인";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: timezone,
  }).format(date);
}

function formatPrice(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "가격 미확인";
  const number = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 });
  if (value >= 100_000_000) return `${number.format(value / 100_000_000)}억`;
  if (value >= 10_000) return `${number.format(value / 10_000)}만`;
  return `${number.format(value)}원`;
}

export function DeadlineTable({ notices, referenceAt, timezone, runId }: DeadlineTableProps) {
  const search = runId ? `?run=${encodeURIComponent(runId)}` : "";
  const visibleNotices = notices.slice(0, 3);
  const queueLink = runId
    ? `/queue?run=${encodeURIComponent(runId)}&sort=deadline`
    : "/queue?sort=deadline";
  return (
    <Panel
      className="dashboard-deadline-panel"
      title="마감 임박"
      action={
        <div className="dashboard-deadline-header-action">
          <span className="panel-note">7일 이내 · <span className="mono tabular-nums">{formatNumber(notices.length)}</span>건</span>
          <Link className="dashboard-deadline-all-link" to={queueLink}>전체 보기 <span aria-hidden="true">→</span></Link>
        </div>
      }
    >
      {notices.length === 0 ? (
        <EmptyState compact title="7일 이내 마감 공고가 없습니다." description="마감일이 없는 공고는 이 목록에 포함하지 않습니다." />
      ) : (
        <div className="table-wrap">
          <table className="data-table dashboard-table">
            <thead>
              <tr>
                <th scope="col">마감</th>
                <th scope="col">등급</th>
                <th scope="col">공고</th>
                <th scope="col">추정가격</th>
                <th scope="col">확인 항목</th>
              </tr>
            </thead>
            <tbody>
              {visibleNotices.map((notice) => {
                const blockingCount = notice.blocking_verification_items.length;
                const critical = isCritical(notice.deadline_at, referenceAt);
                return (
                  <tr className={`dashboard-deadline-row ${critical ? "is-critical" : ""}`.trim()} key={notice.id}>
                    <td className="dashboard-deadline-cell">
                      <span aria-hidden="true" className="dashboard-mobile-cell-label">마감</span>
                      <span className={`dashboard-deadline-day mono tabular-nums ${critical ? "is-critical" : ""}`.trim()}>{daysUntil(notice.deadline_at, referenceAt)}</span>
                      <span className="dashboard-deadline-date mono tabular-nums">{formatDeadline(notice.deadline_at, timezone)}</span>
                    </td>
                    <td>
                      <span aria-hidden="true" className="dashboard-mobile-cell-label">등급</span>
                      <Badge label={notice.grade ?? "등급 미확인"} variant={gradeVariant(notice.grade)} />
                    </td>
                    <td className="dashboard-notice-cell">
                      <span aria-hidden="true" className="dashboard-mobile-cell-label">공고</span>
                      <Link className="dashboard-notice-link" to={`/judgments/${notice.id}${search}`}>
                        <span className="dashboard-notice-title">{notice.title?.trim() || "공고명 없음"}</span>
                        <span className="dashboard-notice-agency">{notice.agency?.trim() || "발주기관 미확인"}</span>
                      </Link>
                    </td>
                    <td className="mono tabular-nums dashboard-price-cell">
                      <span aria-hidden="true" className="dashboard-mobile-cell-label">추정가격</span>
                      {formatPrice(notice.estimated_price)}
                    </td>
                    <td>
                      <span aria-hidden="true" className="dashboard-mobile-cell-label">확인 항목</span>
                      {blockingCount > 0 ? (
                        <Badge label={`차단 ${formatNumber(blockingCount)}`} variant="danger" />
                      ) : (
                        <span className="dashboard-no-blocking">확인 없음</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
