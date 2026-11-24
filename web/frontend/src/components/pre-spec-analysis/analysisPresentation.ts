import type { WikiProject } from "../../lib/companyWikiApi";
import type { EngineAnalysis, EngineEvidence } from "../../lib/engineApi";

export type Requirement = EngineAnalysis["fits"][number];
export type WorkUnits = NonNullable<EngineAnalysis["work_units"]>;
type WorkAssignment = WorkUnits["assignments"][number];

export function linkWorkAssignments(fits: Requirement[], workUnits: WorkUnits | null | undefined) {
  const assignments = new Map<Requirement, WorkAssignment>();
  if (workUnits?.status !== "classified") return assignments;

  const byId = new Map<string, WorkAssignment[]>();
  for (const assignment of workUnits.assignments) {
    const group = byId.get(assignment.req_id) ?? [];
    group.push(assignment);
    byId.set(assignment.req_id, group);
  }
  for (const fit of fits) {
    // The engine writes the instance key into assignment.req_id when one exists.
    const instance = fit.instance_key ? byId.get(fit.instance_key)?.shift() : undefined;
    const assignment = instance ?? byId.get(fit.req_id)?.shift();
    if (assignment) assignments.set(fit, assignment);
  }
  return assignments;
}

export function isOutsideWorkUnits(assignment: WorkAssignment) {
  return assignment.units.length === 0 && assignment.uncovered.length > 0;
}

export function workUnitsNotice(workUnits: WorkUnits) {
  return `요구사항마다 업무 근거 지도(실적 ${workUnits.basis_projects}건 기준)로 근거 실적을 연결했어요. 지도에 없는 실적은 판단에 들어가지 않았어요.`;
}

export function knowledgeReadNotice(pageCount: number, projectCount: number | null) {
  const pages = `회사 근거 위키 ${pageCount}쪽`;
  const read = projectCount === null ? `${pages}을 읽었어요. 관련 실적 수는 미확인이에요.`
    : `${pages}과 관련 실적 ${projectCount}건을 읽었어요.`;
  return `${read} ‘회사 근거 없음’이 실적이 없다는 뜻은 아니에요.`;
}

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
