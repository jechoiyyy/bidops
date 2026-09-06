import { Link } from "react-router-dom";
import { Panel } from "../common/Panel";
import type { DistributionItem } from "../../lib/types";
import { formatNumber } from "../../lib/format";

interface GradeDistributionProps {
  distribution: DistributionItem[];
  embedded?: boolean;
  /** 지정하면 막대와 범례가 해당 등급만 걸린 검토 대기열로 이어진다. */
  runId?: string | null;
}

function queueLink(runId: string | null | undefined, grade: string): string {
  const params = new URLSearchParams();
  if (runId) params.set("run", runId);
  params.set("grade", grade);
  return `/queue?${params.toString()}`;
}

const gradeClass: Record<string, string> = {
  "우선 검토": "priority",
  "검토 권장": "recommended",
  "관찰 대상": "observe",
  제외: "excluded",
};

function DistributionContent({ distribution, runId }: Pick<GradeDistributionProps, "distribution" | "runId">) {
  const total = distribution.reduce((sum, item) => sum + item.count, 0);

  if (distribution.length === 0 || total === 0) {
    return <div className="dashboard-inline-empty">분석 표본 등급 분포 없음</div>;
  }

  return (
    <>
      <div className="dashboard-grade-bar" aria-label={`분석 표본 ${formatNumber(total)}건의 등급 분포`}>
        {distribution.map((item) => {
          const width = (item.count / total) * 100;
          const tone = gradeClass[item.key] ?? "other";
          const label = `${item.label || "등급 미확인"} ${formatNumber(item.count)}건`;
          const className = `dashboard-grade-segment dashboard-grade-segment-${tone}`;
          return gradeClass[item.key] ? (
            <Link
              aria-label={`${label} 검토 대기열로 이동`}
              className={className}
              key={item.key}
              style={{ width: `${width}%` }}
              to={queueLink(runId, item.key)}
            >
              <span className="dashboard-grade-segment-count mono tabular-nums">{formatNumber(item.count)}</span>
            </Link>
          ) : (
            /* 등급 이름과 건수는 아래 legend가 글자로 적는다. 막대에 `title`
               툴팁을 겹쳐 두면 마우스에만 보이는 두 번째 설명이 된다. */
            <div className={className} key={item.key} style={{ width: `${width}%` }} />
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

export function GradeDistribution({ distribution, embedded = false, runId }: GradeDistributionProps) {
  if (embedded) {
    return (
      <section className="dashboard-grade-embedded" aria-labelledby="grade-distribution-title">
        <div className="dashboard-subsection-title" id="grade-distribution-title">
          <span>분석 표본 등급 분포</span>
          <span className="dashboard-subsection-note">막대를 누르면 해당 등급으로 대기열이 열립니다</span>
        </div>
        <DistributionContent distribution={distribution} runId={runId} />
      </section>
    );
  }

  return (
    <Panel title="등급 분포">
      <DistributionContent distribution={distribution} runId={runId} />
    </Panel>
  );
}
