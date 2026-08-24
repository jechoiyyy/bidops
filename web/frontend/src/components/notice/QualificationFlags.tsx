import { Panel } from "../common/Panel";
import type { NoticeDetailResponse } from "../../lib/types";
import { present } from "../../lib/format";

interface QualificationFlagsProps {
  notice: NoticeDetailResponse;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function flagValue(value: unknown): string {
  if (value === null || value === undefined) return "값 없음";
  if (typeof value === "string" && value.trim() === "") return "값 없음";
  return present(value);
}

const fields: Array<[string, string]> = [
  ["participation_limited", "참가제한"],
  ["industry_limited", "업종제한"],
  ["information_business", "정보사업"],
  ["general_service", "일반용역"],
  ["service_division", "용역 구분"],
  ["joint_contract_method", "공동수급"],
  ["performance_restricted_competition", "실적제한"],
  ["pq_evaluation", "PQ 평가"],
  ["technical_evaluation", "기술평가"],
  ["technical_evaluation_rate", "기술평가 비율"],
  ["successful_bid_method", "낙찰자 결정"],
];

export function QualificationFlags({ notice }: QualificationFlagsProps) {
  const values = record(notice.qualification_flags);
  return (
    <Panel className="qualification-flags-panel" title="자격·제약 플래그" action={<span className="panel-note">API 직접 제공값</span>}>
      <dl className="qualification-flags-list">
        {fields.map(([key, label]) => {
          const value = flagValue(values[key]);
          return (
            <div className={`qualification-flag-row ${value === "값 없음" ? "is-missing" : ""}`.trim()} key={key}>
              <dt>{label}</dt>
              <dd className={value === "값 없음" ? "" : "mono tabular-nums"}>{value}</dd>
            </div>
          );
        })}
      </dl>
    </Panel>
  );
}
