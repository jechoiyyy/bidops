import type { ReactNode } from "react";
import { Panel } from "../common/Panel";
import type { FunnelItem } from "../../lib/types";
import { formatNumber } from "../../lib/format";

interface PipelineFunnelProps {
  funnel: FunnelItem[];
  children?: ReactNode;
}

function formatDrop(previous: number | null, current: number | null): string {
  if (previous === null || current === null) return "감소 폭 계산 불가";
  if (current > previous) return `증가 ${formatNumber(current - previous)}건`;
  const drop = previous - current;
  if (previous === 0) return "감소율 계산 불가";
  const percentage = (drop / previous) * 100;
  return `감소 ${formatNumber(drop)}건 · ${percentage.toFixed(1)}%`;
}

export function PipelineFunnel({ funnel, children }: PipelineFunnelProps) {
  const maximum = Math.max(...funnel.map((item) => item.count ?? 0), 1);

  return (
    <Panel className="dashboard-funnel-panel" title="판정 파이프라인" action={<span className="panel-note">수집 → 후보 → 표본 → 검토 대기</span>}>
      <div className="dashboard-funnel-list">
        {funnel.length === 0 ? (
          <div className="dashboard-inline-empty">퍼널 데이터 없음</div>
        ) : (
          funnel.map((item, index) => {
            const previous = funnel[index - 1]?.count;
            // 산출물이 건수를 주지 않은 단계는 막대를 채우지 않고 값 없음으로 알린다.
            const unknown = item.count === null;
            const width = item.count ? Math.max((item.count / maximum) * 100, 8) : 8;
            return (
              <div className="dashboard-funnel-row" key={item.key}>
                <span className="dashboard-funnel-label">{item.label || "단계 미확인"}</span>
                <div className="dashboard-funnel-track">
                  <div
                    aria-label={unknown ? `${item.label} 값 없음` : `${item.label} ${formatNumber(item.count ?? 0)}건`}
                    className={`dashboard-funnel-bar dashboard-funnel-bar-${index}${unknown ? " is-unknown" : ""}`}
                    style={{ width: `${width}%` }}
                  >
                    {unknown ? (
                      <span className="dashboard-funnel-unknown">값 없음</span>
                    ) : (
                      <>
                        <span className="mono tabular-nums">{formatNumber(item.count ?? 0)}</span>
                        <span className="dashboard-funnel-unit">건</span>
                      </>
                    )}
                  </div>
                </div>
                <span className="dashboard-funnel-change mono tabular-nums">
                  {previous === undefined ? "시작" : formatDrop(previous, item.count)}
                </span>
              </div>
            );
          })
        )}
      </div>
      {children ? <div className="dashboard-funnel-extra">{children}</div> : null}
    </Panel>
  );
}
