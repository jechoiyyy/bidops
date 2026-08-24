import { Link } from "react-router-dom";
import { Badge } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import type { VerificationRequest } from "../../lib/types";
import { formatNumber } from "../../lib/format";

interface VerificationRequestsProps {
  requests: VerificationRequest[];
}

function profileBasis(sections: string[]): string {
  if (sections.length === 0) return "근거 프로필 절 미확인";
  return `회사 프로필 ${sections.join(" · ")}`;
}

export function VerificationRequests({ requests }: VerificationRequestsProps) {
  const sorted = [...requests].sort((left, right) => right.count - left.count || left.item.localeCompare(right.item, "ko"));
  const total = sorted.reduce((sum, request) => sum + request.count, 0);

  return (
    <Panel
      className="dashboard-verification-panel"
      title="담당자 확인 요청"
      action={total > 0 ? <Badge label={`차단 항목 ${formatNumber(total)}건`} variant="alert" /> : <span className="panel-note">확인 요청 없음</span>}
    >
      {sorted.length === 0 ? (
        <EmptyState compact title="차단 확인 항목이 없습니다." description="차단으로 표시된 확인 항목만 집계합니다." />
      ) : (
        <>
          <ol className="dashboard-verification-list">
            {sorted.map((request) => (
              <li className="dashboard-verification-item" key={request.item}>
                <div className="dashboard-verification-item-main">
                  <span>{request.item || "확인 항목 없음"}</span>
                  <strong className="mono tabular-nums">{formatNumber(request.count)}건</strong>
                </div>
                <div className="dashboard-verification-basis">{profileBasis(request.profile_sections)}</div>
              </li>
            ))}
          </ol>
          <Link className="dashboard-profile-link" to="/profile">회사 프로필에서 확정하기 <span aria-hidden="true">→</span></Link>
        </>
      )}
    </Panel>
  );
}
