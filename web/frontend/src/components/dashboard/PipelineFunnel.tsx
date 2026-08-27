import type { ReactNode } from "react";
import { Panel } from "../common/Panel";
import type { FunnelItem } from "../../lib/types";
import { formatNumber } from "../../lib/format";

interface PipelineFunnelProps {
  funnel: FunnelItem[];
  children?: ReactNode;
}

function formatPercentage(value: number): string {
  return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}%`;
}

function formatChange(previous: number | null | undefined, current: number | null): string {
  if (previous === undefined) return "기준";
  if (previous === null || previous === 0 || current === null) return "계산 불가";
  if (current > previous) return `증가 ${formatNumber(current - previous)}건`;
  if (current === previous) return "변화 없음 · 0건";
  const drop = previous - current;
  const percentage = (drop / previous) * 100;
  return `감소 ${formatNumber(drop)}건 · ${percentage.toFixed(1)}%`;
}

type Retention =
  | { kind: "missing" }
  | { kind: "unavailable" }
  | { kind: "rate"; value: number };

function getRetention(index: number, previous: number | null | undefined, current: number | null): Retention {
  if (current === null) return { kind: "missing" };
  if (index === 0) return { kind: "rate", value: current === 0 ? 0 : 100 };
  if (previous === null || previous === undefined || previous === 0) return { kind: "unavailable" };
  if (current === 0) return { kind: "rate", value: 0 };
  return { kind: "rate", value: (current / previous) * 100 };
}

export function PipelineFunnel({ funnel, children }: PipelineFunnelProps) {
  return (
    <Panel className="dashboard-funnel-panel" title="판정 파이프라인" action={<span className="panel-note">수집 → 후보 → 표본 → 검토 대기</span>}>
      <div className="dashboard-funnel-list">
        {funnel.length === 0 ? (
          <div className="dashboard-inline-empty">퍼널 데이터 없음</div>
        ) : (
          funnel.map((item, index) => {
            const previous = index > 0 ? funnel[index - 1].count : undefined;
            const retention = getRetention(index, previous, item.count);
            const hasBar = retention.kind === "rate" && item.count !== null && item.count > 0;
            const compactBar = hasBar && retention.kind === "rate" && retention.value < 24;
            const retentionLabel = retention.kind === "missing"
              ? "값 없음"
              : retention.kind === "unavailable"
                ? "계산 불가"
                : formatPercentage(retention.value);
            const stageLabel = item.label || "단계 미확인";
            return (
              <div className="dashboard-funnel-row" key={item.key}>
                <span className="dashboard-funnel-label">{stageLabel}</span>
                <div className="dashboard-funnel-track" aria-label={`${stageLabel} 잔존율 ${retentionLabel}`}>
                  {hasBar ? (
                    <div
                      aria-label={`${stageLabel} 잔존율 ${retentionLabel}`}
                      className={`dashboard-funnel-bar dashboard-funnel-bar-${index}${compactBar ? " is-compact" : ""}`}
                      style={{ width: `${Math.min(Math.max(retention.value, 0), 100)}%` }}
                    >
                      <span className="mono tabular-nums">{retentionLabel}</span>
                    </div>
                  ) : (
                    <span className={`dashboard-funnel-state dashboard-funnel-state-${retention.kind}`}>
                      {retentionLabel}
                    </span>
                  )}
                </div>
                <span className="dashboard-funnel-change">
                  <span className="dashboard-funnel-count mono tabular-nums">
                    {item.count === null ? "값 없음" : `${formatNumber(item.count)}건`}
                  </span>
                  <span className="dashboard-funnel-drop mono tabular-nums">{formatChange(previous, item.count)}</span>
                </span>
              </div>
            );
          })
        )}
      </div>
      {funnel.length > 0 ? (
        <div className="dashboard-funnel-axis" aria-label="잔존율 기준 축: 0%, 25%, 50%, 75%, 100%">
          <div className="dashboard-funnel-axis-scale mono tabular-nums">
            <span>0%</span>
            <span>25%</span>
            <span>50%</span>
            <span>75%</span>
            <span>100%</span>
          </div>
        </div>
      ) : null}
      {children ? <div className="dashboard-funnel-extra">{children}</div> : null}
    </Panel>
  );
}
