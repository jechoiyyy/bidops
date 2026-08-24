import { Panel } from "../common/Panel";
import type { DistributionItem } from "../../lib/types";
import { formatNumber } from "../../lib/format";

interface GradeDistributionProps {
  distribution: DistributionItem[];
  embedded?: boolean;
}

const gradeClass: Record<string, string> = {
  "우선 검토": "priority",
  "검토 권장": "recommended",
  "관찰 대상": "observe",
  제외: "excluded",
};

function DistributionContent({ distribution }: Pick<GradeDistributionProps, "distribution">) {
  const total = distribution.reduce((sum, item) => sum + item.count, 0);

  if (distribution.length === 0 || total === 0) {
    return <div className="dashboard-inline-empty">분석 표본 등급 분포 없음</div>;
  }

  return (
    <>
      <div className="dashboard-grade-bar" role="img" aria-label={`분석 표본 ${formatNumber(total)}건의 등급 분포`}>
        {distribution.map((item) => {
          const width = (item.count / total) * 100;
          const tone = gradeClass[item.key] ?? "other";
          return (
            <div
              className={`dashboard-grade-segment dashboard-grade-segment-${tone}`}
              key={item.key}
              style={{ width: `${width}%` }}
              title={`${item.label || "등급 미확인"} ${formatNumber(item.count)}건`}
            />
          );
        })}
      </div>
      <div className="dashboard-grade-legend">
        {distribution.map((item) => (
          <div className="dashboard-grade-legend-item" key={item.key}>
            <span className={`dashboard-grade-swatch dashboard-grade-swatch-${gradeClass[item.key] ?? "other"}`} aria-hidden="true" />
            <span>{item.label || "등급 미확인"}</span>
            <strong className="mono tabular-nums">{formatNumber(item.count)}건</strong>
          </div>
        ))}
      </div>
      <div className="dashboard-distribution-caption">분석 표본 기준 · 합계 <span className="mono tabular-nums">{formatNumber(total)}건</span></div>
    </>
  );
}

export function GradeDistribution({ distribution, embedded = false }: GradeDistributionProps) {
  if (embedded) {
    return (
      <section className="dashboard-grade-embedded" aria-labelledby="grade-distribution-title">
        <div className="dashboard-subsection-title" id="grade-distribution-title">분석 표본 등급 분포</div>
        <DistributionContent distribution={distribution} />
      </section>
    );
  }

  return (
    <Panel title="등급 분포">
      <DistributionContent distribution={distribution} />
    </Panel>
  );
}
