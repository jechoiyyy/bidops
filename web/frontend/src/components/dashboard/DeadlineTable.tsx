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

export function DeadlineTable({ notices, referenceAt, timezone }: DeadlineTableProps) {
  return (
    <Panel
      className="dashboard-deadline-panel"
      title="마감 임박"
      action={<span className="panel-note">7일 이내 · <span className="mono tabular-nums">{formatNumber(notices.length)}</span>건</span>}
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
              {notices.map((notice) => {
                const blockingCount = notice.blocking_verification_items.length;
                return (
                  <tr key={notice.id}>
                    <td className="dashboard-deadline-cell">
                      <span className="dashboard-deadline-day mono tabular-nums">{daysUntil(notice.deadline_at, referenceAt)}</span>
                      <span className="dashboard-deadline-date mono tabular-nums">{formatDeadline(notice.deadline_at, timezone)}</span>
                    </td>
                    <td><Badge label={notice.grade ?? "등급 미확인"} variant={gradeVariant(notice.grade)} /></td>
                    <td className="dashboard-notice-cell">
                      <span className="dashboard-notice-title">{notice.title?.trim() || "공고명 없음"}</span>
                      <span className="dashboard-notice-agency">{notice.agency?.trim() || "발주기관 미확인"}</span>
                    </td>
                    <td className="mono tabular-nums dashboard-price-cell">{formatPrice(notice.estimated_price)}</td>
                    <td>
                      {blockingCount > 0 ? (
                        <Badge label={`차단 ${formatNumber(blockingCount)}`} variant="alert" />
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
