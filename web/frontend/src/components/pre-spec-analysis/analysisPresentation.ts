import type { WikiProject } from "../../lib/companyWikiApi";
import type { EngineAnalysis, EngineEvidence } from "../../lib/engineApi";

export type Requirement = EngineAnalysis["fits"][number];

const dateFormat = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

export function analysisDate(value: string | null | undefined, withTime = true) {
  if (!value || Number.isNaN(Date.parse(value))) return "미확인";
  const parts = dateFormat.formatToParts(new Date(value));
  const part = (type: string) => parts.find((item) => item.type === type)?.value;
  const date = `${part("year")}.${part("month")}.${part("day")}`;
  return withTime ? `${date} ${part("hour")}:${part("minute")}` : date;
}

export function known(value: string | null | undefined, fallback = "미확인") {
  return value && value.trim() && value.trim().toLowerCase() !== "unknown" ? value : fallback;
}

export function requirementKey(fit: Requirement) {
  return fit.instance_key ?? fit.req_id;
}

export function replaceAnalysisHash(name: "issue" | "req", value: string) {
  window.history.replaceState(window.history.state, "", `#${name}=${encodeURIComponent(value)}`);
}

export function citationLabel(evidence?: EngineEvidence | null) {
  return evidence?.verified === true ? "인용 검증됨" : evidence?.verified === false ? "인용 검증 실패" : "인용 검증 표식 없음";
}

export function knowledgeName(slug: string, portfolio: ReadonlyMap<string, WikiProject>, pages: ReadonlyMap<string, string>) {
  return portfolio.has(slug) ? known(portfolio.get(slug)?.title) : pages.get(slug) ?? slug;
}
