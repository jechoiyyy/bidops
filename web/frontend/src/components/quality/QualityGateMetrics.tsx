import { Text } from "@astryxdesign/core/Text";
import { DataTable, Note, Section, Small, StatLine, StatusToken } from "../criteria/CriteriaPrimitives";
import type { QualityGateResultStatus, RuntimeJsonObject } from "../../lib/types";

interface MetricEntry {
  key: string;
  metric: Record<string, unknown> | null;
  available: boolean;
  isGroup: boolean;
}

interface QualityGateMetricsProps {
  metrics: RuntimeJsonObject;
  resultStatus: QualityGateResultStatus;
}

const PERSPECTIVE_NAMES = ["기술 적합성", "실적 정합성", "공공 SI 적합성", "사업성·자격 제약", "전략 부합"] as const;

// These are the authoritative top-level metric groups in spec 5.11. The
// backend intentionally does not add a threshold field to each JSON object;
// the UI presents the frozen policy thresholds below instead.
const TOP_METRIC_KEYS = [
  "grade_reproducibility",
  "perspective_reproducibility",
  "perspective_mismatch_concentration",
  "discrimination",
  "evidence_validity",
  "information_sufficiency",
  "perspective_split",
  "two_axis_mixing",
  "counterargument_reflection",
  "claude_alignment",
] as const;

const EXPECTED_METRIC_KEYS = [
  ...TOP_METRIC_KEYS,
  ...PERSPECTIVE_NAMES.map((name) => `perspective_reproducibility.${name}`),
  "discrimination.pass_a",
  "discrimination.pass_b",
  "evidence_validity.agreement",
  "evidence_validity.insufficient",
  "information_sufficiency.pass_a",
  "information_sufficiency.pass_b",
  "perspective_split.pass_a",
  "perspective_split.pass_b",
  "two_axis_mixing.pass_a",
  "two_axis_mixing.pass_b",
  "counterargument_reflection.pass_a",
  "counterargument_reflection.pass_b",
  "claude_alignment.grade",
  ...PERSPECTIVE_NAMES.map((name) => `claude_alignment.perspectives.${name}`),
];

const NON_METRIC_FIELDS = new Set([
  "numerator",
  "denominator",
  "percent",
  "status",
  "threshold",
  "reason",
  "valid_review_count",
  "distinct_notice_review_count",
  "judgment_hold_count",
  "mismatch_count",
]);

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function isMetric(value: unknown): value is Record<string, unknown> {
  const item = record(value);
  return item !== null && ["numerator", "denominator", "percent", "status"].some((key) => key in item);
}

function pathValue(source: RuntimeJsonObject, path: string): unknown {
  return path.split(".").reduce<unknown>((current, part) => record(current)?.[part], source);
}

function flattenMetrics(source: RuntimeJsonObject): Map<string, Record<string, unknown>> {
  const entries = new Map<string, Record<string, unknown>>();
  function visit(value: unknown, path: string) {
    const item = record(value);
    if (!item) return;
    if (isMetric(item)) entries.set(path, item);
    Object.entries(item).forEach(([key, nested]) => {
      if (!NON_METRIC_FIELDS.has(key) && record(nested)) visit(nested, path ? `${path}.${key}` : key);
    });
  }
  Object.entries(source).forEach(([key, value]) => {
    if (key !== "excluded_notices" && key !== "sample_count" && key !== "paired_valid_count") visit(value, key);
  });
  return entries;
}

function buildMetricEntries(source: RuntimeJsonObject): MetricEntry[] {
  const discovered = flattenMetrics(source);
  const keys = [...new Set([...EXPECTED_METRIC_KEYS, ...discovered.keys()])];
  return keys.map((key) => {
    const value = record(pathValue(source, key));
    const available = isMetric(value);
    return { key, metric: value, available, isGroup: TOP_METRIC_KEYS.includes(key as typeof TOP_METRIC_KEYS[number]) && !available };
  });
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function metricStatus(value: unknown, available: boolean): string {
  if (!available) return "미측정";
  const status = textValue(value);
  if (status === "통과" || status === "pass") return "통과";
  if (status === "미달" || status === "fail") return "미달";
  if (status === "보류" || status === "held") return "보류";
  if (status === "미측정" || status === "unmeasured" || status === "pending") return "미측정";
  if (status === "해당 없음") return "해당 없음";
  if (status?.startsWith("계산 불가")) return status;
  if (status === "측정 완료" || status === "measured") return "측정 완료";
  return status ?? "계산 불가";
}

function percentLabel(value: unknown): string {
  const percent = numberValue(value);
  return percent === null ? "계산 불가" : `${percent.toFixed(2)}%`;
}

function thresholdLabel(key: string): string {
  if (key === "grade_reproducibility") return "합격 · 80% 이상";
  if (key === "perspective_mismatch_concentration") return "합격 · 50% 이하";
  if (key === "discrimination.pass_a" || key === "discrimination.pass_b") return "합격 · 분모 10건 이상 · 10–25%";
  if (key === "evidence_validity") return "필수 · 유효 리뷰 10건 이상 · 서로 다른 공고 10건 이상";
  if (key === "evidence_validity.agreement") return "합격 · 동의 70% 이상 · 유효/서로 다른 공고 각 10건 이상";
  if (key === "evidence_validity.insufficient") return "합격 · 근거 부족 10% 이하 · 유효/서로 다른 공고 각 10건 이상";
  if (key === "perspective_split.pass_a" || key === "perspective_split.pass_b") return "합격 · 40% 이상";
  if (TOP_METRIC_KEYS.some((group) => key === group || key.startsWith(`${group}.`))) return "합격 threshold 없음 · 진단 지표";
  return "합격 threshold 없음 · 진단 지표";
}

function metricContext(key: string, metric: Record<string, unknown> | null): string | null {
  if (!metric) return null;
  if (key === "evidence_validity") {
    const valid = numberValue(metric.valid_review_count);
    const distinct = numberValue(metric.distinct_notice_review_count);
    const holds = numberValue(metric.judgment_hold_count);
    return `유효 리뷰 ${valid === null ? "계산 불가" : `${valid}건`} · 서로 다른 공고 ${distinct === null ? "계산 불가" : `${distinct}건`} · 판단 보류 ${holds === null ? "계산 불가" : `${holds}건`}`;
  }
  if (key.startsWith("perspective_reproducibility.") || key.startsWith("claude_alignment.perspectives.")) {
    const mismatches = numberValue(metric.mismatch_count);
    return mismatches === null ? null : `불일치 ${mismatches}건`;
  }
  return textValue(metric.reason);
}

export function QualityGateMetrics({ metrics, resultStatus }: QualityGateMetricsProps) {
  const entries = buildMetricEntries(metrics);
  const excluded = Array.isArray(metrics.excluded_notices)
    ? metrics.excluded_notices.map((item) => record(item)).filter((item): item is Record<string, unknown> => item !== null)
    : [];
  const sampleCount = numberValue(metrics.sample_count);
  const pairedCount = numberValue(metrics.paired_valid_count);

  return (
    <>
      <StatLine items={[
        ["고정 표본", sampleCount === null ? "계산 불가" : `${sampleCount}건`],
        ["A/B 유효 쌍", pairedCount === null ? "계산 불가" : `${pairedCount}건`],
        ["최종 상태", resultStatus],
      ]} />
      <Section title={`지표와 제외 근거 · ${entries.length}개`}>
        <Small>
          결정적 계산 결과입니다. 임계값이 없는 항목은 합격/불합격이 아니라 진단 지표이며, 계산하지 못한 값은 0%로 바꾸지 않습니다.
        </Small>
        <DataTable
          caption="품질 게이트의 모든 top-level 지표와 중첩 지표별 계산 결과와 명시적 임계값"
          headings={["지표", "결과", "계산 근거", "상태", "임계값·진단"]}
          rows={entries.map(({ key, metric, available, isGroup }) => {
            if (isGroup) {
              return [
                <code key="k">{key}</code>,
                <Small key="v">하위 지표를 아래에서 확인하십시오.</Small>,
                <Small key="b">—</Small>,
                <Small key="s">지표 묶음</Small>,
                <Small key="t">—</Small>,
              ];
            }
            const status = metricStatus(metric?.status, available);
            const numerator = numberValue(metric?.numerator);
            const denominator = numberValue(metric?.denominator);
            const context = metricContext(key, metric);
            return [
              <code key="k">{key}</code>,
              <Text key="v" weight="semibold">{percentLabel(metric?.percent)}</Text>,
              <Text key="b">{numerator === null || denominator === null ? "계산 불가" : `${numerator} / ${denominator}`}</Text>,
              <StatusToken key="s" label={status} />,
              <span className="crit-cell-stack" key="t">
                <Text>{thresholdLabel(key)}</Text>
                {context ? <Small>{context}</Small> : null}
              </span>,
            ];
          })}
        />
      </Section>
      <Section title={`제외된 공고와 사유 · ${excluded.length}건`}>
        {excluded.length > 0 ? (
          <DataTable
            caption="지표 계산에서 제외된 공고"
            headings={["공고", "실행", "제외 사유"]}
            rows={excluded.map((item) => [
              <code key="n">{textValue(item.notice_id) ?? "공고 ID 없음"}</code>,
              <Text key="p">{textValue(item.pass) ?? "검토"}</Text>,
              <Text key="r">{textValue(item.reason) ?? "제외 사유 없음"}</Text>,
            ])}
          />
        ) : <Note title="제외된 공고가 없습니다">표본에서 빠진 공고가 없다는 뜻이며, 계산 실패와는 다른 상태입니다.</Note>}
      </Section>
    </>
  );
}
