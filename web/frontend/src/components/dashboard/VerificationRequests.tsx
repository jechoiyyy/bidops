import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import type { VerificationRequest } from "../../lib/types";
import { formatNumber } from "../../lib/format";

interface VerificationRequestsProps {
  requests: VerificationRequest[];
  runId: string;
}

function profileBasis(sections: string[]): string {
  if (sections.length === 0) return "근거 프로필 절 미확인";
  return `회사 프로필 ${sections.join(" · ")}`;
}

export function VerificationRequests({ requests, runId }: VerificationRequestsProps) {
  const sorted = [...requests].sort((left, right) => right.count - left.count || left.item.localeCompare(right.item, "ko"));
  const total = sorted.reduce((sum, request) => sum + request.count, 0);
  const [expanded, setExpanded] = useState(false);
  const remainingCount = Math.max(sorted.length - 3, 0);
  const visibleRequests = expanded ? sorted : sorted.slice(0, 3);

  return (
    <Panel
      className="dashboard-verification-panel"
      title="담당자 확인 요청"
      action={total > 0 ? <Badge label={`차단 항목 ${formatNumber(total)}건`} variant="danger" /> : <span className="panel-note">확인 요청 없음</span>}
    >
      {sorted.length === 0 ? (
        <EmptyState compact title="차단 확인 항목이 없습니다." description="차단으로 표시된 확인 항목만 집계합니다." />
      ) : (
        <>
          <ol className="dashboard-verification-list" id="dashboard-verification-list">
            {visibleRequests.map((request) => (
              <li className="dashboard-verification-item" key={request.item}>
                <div className="dashboard-verification-item-main">
                  <span>{request.item || "확인 항목 없음"}</span>
                  <strong className="mono tabular-nums">{formatNumber(request.count)}건</strong>
                </div>
                <div className="dashboard-verification-basis">{profileBasis(request.profile_sections)}</div>
              </li>
            ))}
          </ol>
          {remainingCount > 0 ? (
            <button
              aria-controls="dashboard-verification-list"
              aria-expanded={expanded}
              className="dashboard-verification-toggle"
              onClick={() => setExpanded((current) => !current)}
              type="button"
            >
              {expanded ? "나머지 접기" : `나머지 ${formatNumber(remainingCount)}건 펼치기`}
            </button>
          ) : null}
        </>
      )}
      <Link className="dashboard-profile-link" to={`/profile?run=${encodeURIComponent(runId)}`}>회사 프로필에서 확정하기 <span aria-hidden="true">→</span></Link>
    </Panel>
  );
}
