import type { WikiFact } from "../../lib/companyWikiApi";

/** 회사 근거 개요(2026-11-25 시안 A)의 화면용 묶음. 값은 바꾸지 않고 자리만 나눈다. */

export type LevelKey = "confirmed" | "public" | "demo" | "estimate" | "none";
export const LEVELS: { key: LevelKey; label: string; note: string }[] = [
  { key: "confirmed", label: "확인됨", note: "담당자가 확인한 값" },
  { key: "public", label: "공개 자료", note: "홈페이지 등 공개된 자료에서 옮긴 값" },
  { key: "demo", label: "데모값", note: "시연을 위해 임의로 넣은 값" },
  { key: "estimate", label: "추정", note: "다른 자료에서 추정한 값" },
  { key: "none", label: "표시 없음", note: "확인 수준이 기록되지 않은 값" },
];
const known = new Set<string>(LEVELS.map(level => level.key));

export function levelKey(level: string | null): LevelKey | null {
  if (level === null) return "none";
  return known.has(level) ? level as LevelKey : null;
}

export function levelCounts(facts: WikiFact[]) {
  const counts: Record<LevelKey, number> = { confirmed: 0, public: 0, demo: 0, estimate: 0, none: 0 };
  let other = 0;
  for (const fact of facts) {
    const key = levelKey(fact.level);
    if (key) counts[key]++; else other++;
  }
  return { counts, other };
}

/** 표시값. `unknown`은 미확인, null·빈 문자열은 값 없음으로 보인다. */
export function factText(fact: WikiFact): string {
  const value = fact.display_value;
  if (value === "unknown") return "미확인";
  return value === null || value === "" ? "값 없음" : value;
}
export const isBlank = (fact: WikiFact) => fact.display_value === null || fact.display_value === "" || fact.display_value === "unknown";

export interface FactGroup {
  key: string;
  segment: string;
  title: string;
  items: { fact: WikiFact; sub: string | null }[];
}

const segmentOf = (path: string) => path.split(".")[1]?.replace(/\[.*$/, "") ?? path;
const labelOf = (fact: WikiFact) => fact.label ?? fact.path;

/**
 * 같은 대상(경로 앞 두 마디가 같은 값: 예 `registrations.venture.*`)을 한 묶음으로 모은다.
 * 묶음 이름은 이름표의 공통 앞부분이고 나머지가 세부 이름이다(벤처기업 유형·확인 시기·유효기간 → 벤처기업 / 유형·확인 시기·유효기간).
 */
export function groupFacts(facts: WikiFact[]): FactGroup[] {
  const groups = new Map<string, WikiFact[]>();
  for (const fact of facts) {
    const key = fact.path.split(".").slice(0, 2).join(".");
    groups.set(key, [...(groups.get(key) ?? []), fact]);
  }
  return [...groups].map(([key, members]) => {
    const words = members.map(fact => labelOf(fact).split(" "));
    let common = 0;
    if (members.length > 1) {
      while (common < words[0].length && words.every(w => w.length > common && w[common] === words[0][common])) common++;
      if (words.some(w => w.length === common) && common > 0 && words[0][common - 1] === "·") common--;
    }
    const title = common ? words[0].slice(0, common).join(" ").replace(/\s*·$/, "") : labelOf(members[0]);
    return {
      key, segment: segmentOf(key), title,
      items: members.map((fact, i) => {
        if (members.length === 1) return { fact, sub: null };
        const rest = common ? words[i].slice(common).join(" ").replace(/^·\s*/, "") : labelOf(fact);
        return { fact, sub: rest || null };
      }),
    };
  });
}

/** 등록·인증을 보는 순서. 지도에 없는 항목은 마지막 묶음으로 간다. */
export const REGISTRATION_BUCKETS: { title: string; segments: string[] }[] = [
  { title: "참가 자격 관련 등록", segments: ["g2b", "sw_business_report", "sme_certificate", "direct_production"] },
  { title: "기업 인증·지정", segments: ["venture", "innobiz", "mainbiz", "rnd_institute", "specialized_research_business",
    "engineering_business_report", "industrial_design_company", "performance_sharing_company", "military_designated_company", "esg_cert"] },
  { title: "품질·보안·클라우드", segments: ["iso", "cloud_certs", "other_certs", "gs_cert", "web_accessibility_certs", "egov_framework_inspection_reports"] },
  { title: "평가 등급·지식재산", segments: ["credit_rating", "tech_rating", "patents", "copyrights"] },
];
export const DISQUALIFIER_SEGMENTS = ["debarment", "tax_delinquency", "insolvency", "wage_arrears_listed", "aa_noncompliance_listed"];

export function registrationBuckets(groups: FactGroup[]) {
  const used = new Set<string>();
  const buckets = REGISTRATION_BUCKETS.map(bucket => {
    const members = groups.filter(group => bucket.segments.includes(group.segment));
    members.forEach(group => used.add(group.key));
    return { title: bucket.title, groups: members };
  });
  const disqualifiers = groups.filter(group => DISQUALIFIER_SEGMENTS.includes(group.segment));
  disqualifiers.forEach(group => used.add(group.key));
  const rest = groups.filter(group => !used.has(group.key));
  if (rest.length) buckets.push({ title: "기타 등록·인증", groups: rest });
  return { buckets: buckets.filter(bucket => bucket.groups.length), disqualifiers };
}

/** 묶음의 대표 값(상태·등록 여부 등)을 맨 앞에 둔다. */
const leading = ["status", "registered", "reported", "type", "has", "grade"];
export function leadFirst(group: FactGroup) {
  const index = group.items.findIndex(item => leading.includes(item.fact.path.split(".").at(-1) ?? ""));
  if (index <= 0) return group.items;
  return [group.items[index], ...group.items.slice(0, index), ...group.items.slice(index + 1)];
}

/** "3명" → 3. 숫자로 읽을 수 없으면 null. */
export function count(value: string | null): number | null {
  const match = value?.match(/^\s*([\d,]+)\s*(명|건)?\s*$/);
  return match ? Number(match[1].replace(/,/g, "")) : null;
}

/** "37억 6,927만 원" → 376927(만 원). 읽을 수 없으면 null. */
export function wonInManwon(value: string | null): number | null {
  const match = value?.match(/^\s*(?:([\d,]+)\s*억)?\s*(?:([\d,]+)\s*만)?\s*원\s*$/);
  if (!match || (!match[1] && !match[2])) return null;
  return Number((match[1] ?? "0").replace(/,/g, "")) * 10000 + Number((match[2] ?? "0").replace(/,/g, ""));
}

/** 쉼표 목록을 나눈다. 괄호 안의 쉼표는 나누지 않는다. */
export const splitList = (value: string) => value.split(/,\s*(?![^()]*\))/).map(part => part.trim()).filter(Boolean);
