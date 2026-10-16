import type { CompanyProfileFact, JsonValue } from "./companyApi";

/*
 * `/company` 화면(RL-00 spec "화면 `/company`")의 순수 도우미.
 *
 * 서버가 준 사실(`GET /api/companies/{id}/profile`의 facts)을 묶고 세기만 한다.
 * 값을 판정하거나 채우지 않는다: unknown·null은 "미입력"으로 남고, 추정값(`proposed`)은
 * 확인됨으로 접지 않으며, `inferred`는 이 화면에 그리지 않는다(RL-00 파일에 없는 값).
 * 상태 3 수치와 "확인이 필요한 것"은 같은 facts를 화면이 센다 — 사이드바의 건수
 * (`GET /api/workload`의 `company_attention`)와 같은 규칙(`proposed`+`unknown`)이다.
 */

export const COMPANY_FACT_GROUPS = [
  "attention",
  "qualification",
  "performance",
  "staff",
  "preference",
  "proposal-assets",
] as const;
export type CompanyFactGroup = (typeof COMPANY_FACT_GROUPS)[number];
/** 사실 표를 가진 그룹. `attention`은 목록, `proposal-assets`는 비활성이다. */
export type CompanyFactTableGroup = "qualification" | "performance" | "staff" | "preference";

export const COMPANY_GROUP_LABEL: Record<CompanyFactGroup, string> = {
  attention: "확인이 필요한 것",
  qualification: "자격 서류",
  performance: "실적",
  staff: "인력",
  preference: "선호·제외 조건",
  "proposal-assets": "제안서 자료",
};

export const DEFAULT_COMPANY_GROUP: CompanyFactGroup = "attention";

/** 허용값 밖의 `?group=`은 기본 그룹으로 되돌린다(서버 값이 아니라 주소 값이므로). */
export function parseCompanyGroup(raw: string | null): CompanyFactGroup {
  return (COMPANY_FACT_GROUPS as readonly string[]).includes(raw ?? "") ? (raw as CompanyFactGroup) : DEFAULT_COMPANY_GROUP;
}

/**
 * 사실이 속한 표 그룹. 노드 id 접두가 계약이다(spec "루트랩 회사 파일 구성 규칙":
 * `qual:`·`cert:` 자격, `project:` 실적, `staff:` 인력, `pref:`·`excl:` 선호·제외).
 * 어느 접두에도 맞지 않는 사실(회사 노드 등)은 표 그룹이 없고 확인이 필요하면
 * "확인이 필요한 것"에만 나온다.
 */
export function companyFactGroupOf(factKey: string): CompanyFactTableGroup | null {
  if (factKey.startsWith("qual:") || factKey.startsWith("cert:")) return "qualification";
  if (factKey.startsWith("project:")) return "performance";
  if (factKey.startsWith("staff:")) return "staff";
  if (factKey.startsWith("pref:") || factKey.startsWith("excl:")) return "preference";
  return null;
}

/** 상태 이름(ui-spec §3 상태 pill). `inferred`는 그리지 않으므로 이름이 없다. */
export type CompanyDisplayStatus = "confirmed" | "proposed" | "unknown";

export const COMPANY_STATUS_LABEL: Record<CompanyDisplayStatus, string> = {
  confirmed: "확인됨",
  proposed: "추정값",
  unknown: "확인 필요",
};

export function isDisplayedFact(fact: CompanyProfileFact): fact is CompanyProfileFact & { status: CompanyDisplayStatus } {
  return fact.status === "confirmed" || fact.status === "proposed" || fact.status === "unknown";
}

export function needsAttention(fact: CompanyProfileFact): boolean {
  return fact.status === "proposed" || fact.status === "unknown";
}

export function factsOfGroup(facts: readonly CompanyProfileFact[], group: CompanyFactTableGroup): CompanyProfileFact[] {
  return facts.filter((fact) => isDisplayedFact(fact) && companyFactGroupOf(fact.fact_key) === group);
}

export function attentionFacts(facts: readonly CompanyProfileFact[]): CompanyProfileFact[] {
  return facts.filter(needsAttention);
}

// ---------------------------------------------------------------------------
// 곧 만료

/** 한국 시간 기준 오늘(`YYYY-MM-DD`). 주소·서버가 아니라 브라우저 시계다(표시용 구간 계산). */
export function todayInSeoul(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

function dayNumber(value: string): number | null {
  const match = DATE_ONLY.exec(value);
  if (!match) return null;
  return Math.floor(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) / 86_400_000);
}

function isRecord(value: JsonValue): value is { [key: string]: JsonValue } {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 자격 값의 `valid_until`(없거나 날짜 모양이 아니면 `null`). */
export function validUntilOf(fact: CompanyProfileFact): string | null {
  if (!isRecord(fact.value)) return null;
  const raw = fact.value.valid_until;
  return typeof raw === "string" && dayNumber(raw) !== null ? raw : null;
}

/**
 * 오늘부터 `valid_until`까지 남은 일 수(지났으면 음수). 유효기간이 없으면 `null`.
 */
export function daysUntilExpiry(fact: CompanyProfileFact, today: string): number | null {
  const until = validUntilOf(fact);
  const base = dayNumber(today);
  if (until === null || base === null) return null;
  return (dayNumber(until) as number) - base;
}

/**
 * "곧 만료": 자격 사실의 `valid_until`이 있고 `warningDays` 이내(이미 지난 것 포함)다.
 * 지난 유효기간을 세지 않으면 가장 급한 자격이 이 수치에서 빠진다.
 */
export function isExpiringSoon(fact: CompanyProfileFact, today: string, warningDays: number): boolean {
  if (companyFactGroupOf(fact.fact_key) !== "qualification") return false;
  const days = daysUntilExpiry(fact, today);
  return days !== null && days <= warningDays;
}

export interface CompanyFactCounts {
  confirmed: number;
  /** 추정값(`proposed`) + 확인 필요(`unknown`). */
  attention: number;
  expiring: number;
}

export function countFacts(facts: readonly CompanyProfileFact[], today: string, warningDays: number): CompanyFactCounts {
  return {
    confirmed: facts.filter((fact) => fact.status === "confirmed").length,
    attention: facts.filter(needsAttention).length,
    expiring: facts.filter((fact) => isExpiringSoon(fact, today, warningDays)).length,
  };
}

// ---------------------------------------------------------------------------
// 값 표시. 서버 값을 옮길 뿐 고치거나 채우지 않는다.

const EXCLUSION_KIND_LABEL: Record<string, string> = {
  hardware: "하드웨어",
  staffing_only: "인력 파견만",
  design_only: "디자인만",
  election: "선거",
  region: "지역",
  amount_floor: "금액 하한",
};

const PARAM_LABEL: Record<string, string> = {
  krw: "금액",
  min_krw: "최소 금액",
  max_krw: "최대 금액",
  over_krw: "기준 금액",
  over_onsite_count: "기준 상주 인원",
  count: "건수",
  onsite_count: "상주 건수",
  min_months: "최소 개월",
  max_months: "최대 개월",
  allowed: "허용",
  max_ratio_percent: "최대 비율(%)",
};

function formatKrw(amount: number): string {
  return `${amount.toLocaleString("ko-KR")}원`;
}

function paramText(key: string, value: JsonValue): string {
  const label = PARAM_LABEL[key] ?? key;
  if (typeof value === "number" && key.endsWith("krw")) return `${label} ${formatKrw(value)}`;
  if (typeof value === "boolean") return `${label} ${value ? "예" : "아니오"}`;
  return `${label} ${plainText(value)}`;
}

function plainText(value: JsonValue): string {
  if (value === null) return "값 없음";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(plainText).join(", ");
  return Object.entries(value)
    .map(([key, entry]) => `${key}: ${entry === null ? "값 없음" : plainText(entry)}`)
    .join(" · ");
}

function present(value: JsonValue | undefined): value is string | number | boolean {
  return value !== undefined && value !== null && value !== "";
}

function qualificationText(value: { [key: string]: JsonValue }): string {
  const parts: string[] = [value.held === true ? "보유" : value.held === false ? "미보유" : ""];
  if (present(value.detail)) parts.push(String(value.detail));
  if (present(value.valid_until)) parts.push(`유효기간 ${String(value.valid_until)}`);
  if (present(value.issued_on)) parts.push(`발급 ${String(value.issued_on)}`);
  if (present(value.file_name)) parts.push(`파일 ${String(value.file_name)}`);
  return parts.filter(Boolean).join(" · ");
}

function projectText(value: { [key: string]: JsonValue }): string {
  const parts: string[] = [];
  if (present(value.agency)) parts.push(String(value.agency));
  if (present(value.year)) parts.push(`${String(value.year)}년`);
  if (present(value.role)) parts.push(String(value.role));
  if (present(value.scope)) parts.push(String(value.scope));
  if (typeof value.amount_krw === "number") parts.push(formatKrw(value.amount_krw));
  if (present(value.started_on) || present(value.ended_on)) {
    parts.push(`${present(value.started_on) ? String(value.started_on) : "?"} ~ ${present(value.ended_on) ? String(value.ended_on) : "?"}`);
  }
  return parts.join(" · ");
}

function staffText(value: { [key: string]: JsonValue }): string {
  const parts: string[] = [];
  if (typeof value.total === "number") parts.push(`총 ${value.total}명`);
  if (typeof value.available === "number") parts.push(`가용 ${value.available}명`);
  if (present(value.region)) parts.push(`지역 ${String(value.region)}`);
  if (present(value.grade)) parts.push(`등급 ${String(value.grade)}`);
  if (present(value.as_of)) parts.push(`${String(value.as_of)} 기준`);
  return parts.join(" · ");
}

function domainText(value: { [key: string]: JsonValue }): string {
  const keywords = Array.isArray(value.keywords) ? value.keywords.map(plainText).join(", ") : "";
  if (value.excluded === true) {
    const kind = typeof value.kind === "string" ? EXCLUSION_KIND_LABEL[value.kind] ?? value.kind : null;
    return ["제외", kind, keywords].filter(Boolean).join(" · ");
  }
  return [typeof value.tier === "number" ? `${value.tier}단계` : null, keywords].filter(Boolean).join(" · ");
}

function capabilityText(value: { [key: string]: JsonValue }): string {
  const parts: string[] = [];
  if (present(value.description)) parts.push(String(value.description));
  const params = value.params;
  if (params !== undefined && isRecord(params)) {
    for (const [key, entry] of Object.entries(params)) parts.push(paramText(key, entry));
  }
  return parts.join(" · ");
}

/** 표의 "내용" 칸. 확인 필요(`unknown`)나 값이 `null`이면 "미입력"이다(0·없음으로 바꾸지 않는다). */
export function companyFactValueText(fact: CompanyProfileFact): string {
  const value = fact.value;
  if (fact.status === "unknown" || value === null) return "미입력";
  if (!isRecord(value)) return plainText(value);
  if ("held" in value) return qualificationText(value) || "미입력";
  if ("keywords" in value && "excluded" in value) return domainText(value) || "미입력";
  if ("description" in value) return capabilityText(value) || "미입력";
  if ("agency" in value || "started_on" in value) return projectText(value) || "미입력";
  if ("total" in value || "available" in value || "region" in value) return staffText(value) || "미입력";
  return plainText(value);
}
