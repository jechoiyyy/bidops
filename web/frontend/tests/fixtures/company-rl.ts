/**
 * RL-00 실회사 `/company` 화면용 고정 응답(`GET /api/company`,
 * `GET /api/companies/{id}/profile`).
 *
 * 모양은 backend pydantic schema에서 옮겼다(`app/deep_review/schemas/company_knowledge.py`의
 * `CompanyContextView`·`CompanyProfileView`·`CompanyProfileFact`). 값은 **fixture 작성자의
 * 창작값**이며 실제 회사 자료가 아니다. 확인됨·추정값·확인 필요를 모두 두고, 자격은
 * "보유는 확인(held) + 세부는 별도 unknown 노드" 분리를 그대로 담는다(spec "보유·세부 분리").
 * 인력 한 건은 `region`(상주 가능 지역)을 갖는다.
 */

export const RL_COMPANY_ID = "44444444-4444-4444-8444-444444444444";
export const RL_PROFILE_VERSION_ID = "44444444-0000-4000-8000-0000000000a1";
export const RL_GRAPH_VERSION_ID = "44444444-0000-4000-8000-0000000000b1";
export const RL_PROFILE_SHA256 = "ab".repeat(32);
export const RL_GRAPH_SHA256 = "cd".repeat(32);
export const RL_EXPIRY_WARNING_DAYS = 60;
/** 활성 버전을 저장한 시각(UTC). 한국 시간으로 2026-10-16 14:12다. */
export const RL_GRAPH_CREATED_AT = "2026-10-16T05:12:00+00:00";

export type RlFactStatus = "confirmed" | "proposed" | "inferred" | "unknown";

export interface RlFact {
  fact_key: string;
  label: string;
  status: RlFactStatus;
  origin: string;
  value: unknown;
  evidence_ids: string[];
}

/** 한국 시간 기준 오늘에서 `days`일 뒤(`YYYY-MM-DD`). 화면의 "곧 만료" 계산과 같은 시계를 쓴다. */
export function seoulDateOffset(days: number, now: Date = new Date()): string {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  const [year, month, day] = today.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

function evidenceIds(key: string, status: RlFactStatus): string[] {
  // 서버 규칙: unknown은 근거가 없고 confirmed·proposed는 하나다(spec "ProfileEvidence").
  if (status === "unknown" || status === "inferred") return [];
  const hex = Array.from(key).reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) >>> 0, 7).toString(16).padStart(8, "0");
  return [`55555555-${hex.slice(0, 4)}-4000-8000-${hex.padEnd(12, "0").slice(0, 12)}`];
}

function fact(key: string, label: string, status: RlFactStatus, origin: string, value: unknown): RlFact {
  return { fact_key: key, label, status, origin, value, evidence_ids: evidenceIds(key, status) };
}

const qualification = (extra: Record<string, unknown> = {}) => ({
  held: true, detail: null, valid_until: null, issued_on: null, file_name: null, ...extra,
});
const project = (agency: string, year: number) => ({
  role: null, scope: null, amount_krw: null, started_on: null, ended_on: null, agency, year,
});
const staff = (extra: Record<string, unknown>) => ({
  role: "dev", total: null, available: null, as_of: null, region: null, grade: null, ...extra,
});

/** 화면이 읽는 사실 목록(evidence가 아닌 노드, id 오름차순). */
export function rlFacts(now: Date = new Date()): RlFact[] {
  return [
    fact("company:rootlab", "㈜루트랩", "confirmed", "company_brochure", "㈜루트랩"),
    // 자격: 보유(확인) + 세부(미입력)를 노드 둘로 분리한다.
    fact("qual:sme_certificate", "중소기업 확인서 보유", "confirmed", "user_interview", qualification()),
    fact("qual:sme_certificate:detail", "중소기업 확인서 세부(유효기간·발급일)", "unknown", "user_interview", null),
    fact("qual:direct_production", "직접생산확인증명서", "confirmed", "user_interview", qualification({
      detail: "소프트웨어 개발", valid_until: seoulDateOffset(30, now), issued_on: "2025-11-03", file_name: "direct-production.pdf",
    })),
    fact("qual:sw_business", "소프트웨어사업자 신고", "confirmed", "company_brochure", qualification({
      valid_until: seoulDateOffset(300, now),
    })),
    fact("qual:credit_rating", "신용등급", "proposed", "agent_proposal", qualification({ detail: "제안값 등급" })),
    fact("qual:legacy_inferred", "추론 자격(표시하지 않음)", "inferred", "model_inference", qualification()),
    fact("project:2024-01", "지자체 포털 고도화", "confirmed", "homepage", project("대구시청", 2024)),
    fact("project:2023-01", "교육청 홈페이지 개편", "confirmed", "homepage", project("경북교육청", 2023)),
    fact("project:certified_list", "실적증명 발급 가능 목록", "unknown", "user_interview", null),
    fact("staff:dev", "개발 인력", "confirmed", "company_brochure", staff({ role: "dev", total: 20 })),
    fact("staff:onsite", "상주 가능 인력", "confirmed", "user_interview", staff({ role: "onsite", available: 6, region: "대구" })),
    fact("staff:pm", "PM 보유 현황", "unknown", "user_interview", null),
    fact("pref:amount_floor", "수주 금액 하한", "confirmed", "user_interview", {
      scope: "core", description: "하한 금액", params: { krw: 50_000_000 },
    }),
    fact("pref:domain:01", "선호 분야 · 웹 구축", "confirmed", "user_interview", {
      tier: 1, keywords: ["홈페이지", "포털"], excluded: false, kind: null,
    }),
    fact("pref:agency:01", "반복 발주처 · 대구시청", "confirmed", "user_interview", {
      tier: null, keywords: ["대구시청"], excluded: false, kind: null,
    }),
    fact("pref:agency:02", "반복 발주처 · 경북교육청", "proposed", "agent_proposal", {
      tier: null, keywords: ["경북교육청"], excluded: false, kind: null,
    }),
    fact("pref:margin", "마진·투찰률", "unknown", "user_interview", null),
    fact("excl:hardware", "제외 · 하드웨어 납품", "confirmed", "user_interview", {
      tier: null, keywords: ["서버 납품"], excluded: true, kind: "hardware",
    }),
  ];
}

export function rlCompany() {
  return {
    company_id: RL_COMPANY_ID,
    slug: "rootlab",
    name: "㈜루트랩",
    is_fictional: false,
    created_at: "2026-10-16T00:30:00+00:00",
  };
}

export function rlContextView(options: { noActiveVersion?: boolean } = {}) {
  return {
    schema_version: "bidops.company-context.v1",
    company: rlCompany(),
    expiry_warning_days: RL_EXPIRY_WARNING_DAYS,
    active_graph_version: options.noActiveVersion
      ? null
      : { graph_version_id: RL_GRAPH_VERSION_ID, created_at: RL_GRAPH_CREATED_AT },
  };
}

export function rlProfileView(facts: RlFact[]) {
  return {
    schema_version: "bidops.company-profile-view.v1",
    company: rlCompany(),
    profile_version_id: RL_PROFILE_VERSION_ID,
    profile_sha256: RL_PROFILE_SHA256,
    graph_version_id: RL_GRAPH_VERSION_ID,
    graph_sha256: RL_GRAPH_SHA256,
    ontology_version: "bidops.company-ontology.rl-v2",
    facts,
  };
}

/** 사이드바 건수(`company_attention`)와 같은 규칙: `proposed`+`unknown`. */
export function rlAttentionCount(facts: RlFact[]): number {
  return facts.filter((entry) => entry.status === "proposed" || entry.status === "unknown").length;
}
