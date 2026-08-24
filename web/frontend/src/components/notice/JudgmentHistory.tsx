import { useQuery } from "@tanstack/react-query";
import { Badge } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import { api } from "../../lib/api";
import { formatDateTime, formatRunRange, present } from "../../lib/format";
import type { HistoryItemResponse } from "../../lib/types";
import { gradeVariant } from "../../lib/grade";

interface JudgmentHistoryProps {
  noticePk: number;
}


function changeLabel(item: HistoryItemResponse, previous: HistoryItemResponse | undefined): string {
  if (item.review_reason?.trim()) return item.review_reason;
  if (previous && item.grade !== previous.grade) return `${present(previous.grade, "이전 등급 미확인")}에서 변경`;
  if (previous && item.readiness !== previous.readiness) return `${present(previous.readiness, "이전 준비 상태 미확인")}에서 변경`;
  return "등급 변경 사유 없음";
}

export function JudgmentHistory({ noticePk }: JudgmentHistoryProps) {
  const historyQuery = useQuery({
    queryKey: ["notice-history", noticePk],
    queryFn: () => api.getNoticeHistory(noticePk),
    staleTime: 30_000,
  });
  const items = historyQuery.data?.items ?? [];

  return (
    <Panel className="judgment-history-panel" title="판정 이력" action={<span className="panel-note">회차별 시간순</span>}>
      {historyQuery.isLoading ? <div className="inline-loading" role="status" aria-live="polite">판정 이력을 불러오는 중입니다.</div> : null}
      {historyQuery.error ? <div className="inline-error" role="alert">판정 이력을 불러오지 못했습니다.</div> : null}
      {!historyQuery.isLoading && !historyQuery.error && items.length === 0 ? <EmptyState compact title="판정 이력이 없습니다." /> : null}
      {items.length > 0 ? (
        <ol className="judgment-history-list">
          {items.map((item, index) => {
            const previous = items[index - 1];
            return (
              <li className="judgment-history-item" key={`${item.run_id}-${item.notice_pk}`}>
                <div className="judgment-history-marker" aria-hidden="true" />
                <div className="judgment-history-content">
                  <div className="judgment-history-heading">
                    <span className="mono tabular-nums">{formatDateTime(item.generated_at)}</span>
                    <Badge label={item.grade} variant={gradeVariant(item.grade)} />
                    <Badge label={item.readiness} variant="readiness" />
                  </div>
                  <div className="judgment-history-run mono tabular-nums">
                    {formatRunRange(item.run_id, item.window_from, item.window_to)}
                  </div>
                  <p>{present(item.summary, "판정 요약 없음")}</p>
                  <div className="judgment-history-change">
                    <span>변경 사유</span>
                    <strong>{changeLabel(item, previous)}</strong>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
    </Panel>
  );
}
