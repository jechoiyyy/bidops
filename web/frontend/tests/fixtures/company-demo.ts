/**
 * 가상회사 데모 화면용 고정 응답(`docs/work/demo-contract.md` §1·2·4·6·7).
 *
 * 모양은 backend pydantic schema에서 옮겼다(`app/lifecycle/schemas/companies.py`,
 * `app/deep_review/schemas/company_knowledge.py`, `app/deep_review/schemas/company_analysis.py`).
 * 세 회사는 §7의 slug·이름이며 모든 값은 **fixture 작성자의 창작값**이다. 실제 회사
 * 자료나 공고 결과가 아니다. 회사마다 핏·추적·심층 검토를 다르게 두어 회사 전환 뒤
 * 다른 회사의 값이 남으면 드러나게 했다.
 */

import lunaReview from "./luna-review.json" with { type: "json" };

export interface CompanyFixture {
  company_id: string;
  slug: string;
  name: string;
  is_fictional: true;
  created_at: string;
  profile_version_id: string;
  graph_version_id: string;
}

/** slug 오름차순(계약 §2 목록 순서). */
export const COMPANY_FIXTURES: CompanyFixture[] = [
  {
    company_id: "33333333-3333-4333-8333-333333333333",
    slug: "demo-cloud-si",
    name: "데모 클라우드SI",
    is_fictional: true,
    created_at: "2026-10-09T01:00:00+00:00",
    profile_version_id: "33333333-0000-4000-8000-0000000000a1",
    graph_version_id: "33333333-0000-4000-8000-0000000000b1",
  },
  {
    company_id: "22222222-2222-4222-8222-222222222222",
    slug: "demo-data-ai",
    name: "데모 데이터AI",
    is_fictional: true,
    created_at: "2026-10-09T01:00:00+00:00",
    profile_version_id: "22222222-0000-4000-8000-0000000000a1",
    graph_version_id: "22222222-0000-4000-8000-0000000000b1",
  },
  {
    company_id: "11111111-1111-4111-8111-111111111111",
    slug: "demo-public-si",
    name: "데모 업무SI",
    is_fictional: true,
    created_at: "2026-10-09T01:00:00+00:00",
    profile_version_id: "11111111-0000-4000-8000-0000000000a1",
    graph_version_id: "11111111-0000-4000-8000-0000000000b1",
  },
];

export const COMPANY_BY_SLUG = Object.fromEntries(COMPANY_FIXTURES.map((company) => [company.slug, company])) as Record<
  "demo-cloud-si" | "demo-data-ai" | "demo-public-si",
  CompanyFixture
>;

export interface CompanyNoticeFixture {
  notice_id: number;
  opportunity_id: number | null;
  title: string;
  posted_at: string;
  deadline_at: string | null;
  document_version_id: string;
  overview_run_id: string;
  bundle_id: string;
}

/** 회사와 무관하게 공유하는 원문 공고(계약 §1). */
export const COMPANY_NOTICE_FIXTURES: CompanyNoticeFixture[] = [
  { notice_id: 7101, opportunity_id: 8101, title: "차세대 행정업무 통합 정보시스템 구축 사전규격", posted_at: "2026-10-08T09:00:00+09:00", deadline_at: "2026-10-20T18:00:00+09:00", document_version_id: "71010000-0000-4000-8000-000000000001", overview_run_id: "71010000-0000-4000-8000-0000000000e1", bundle_id: "71010000-0000-4000-8000-0000000000f1" },
  { notice_id: 7102, opportunity_id: 8102, title: "공공 데이터 분석 플랫폼 고도화 사전규격", posted_at: "2026-10-07T10:00:00+09:00", deadline_at: "2026-10-18T18:00:00+09:00", document_version_id: "71020000-0000-4000-8000-000000000001", overview_run_id: "71020000-0000-4000-8000-0000000000e1", bundle_id: "71020000-0000-4000-8000-0000000000f1" },
  { notice_id: 7103, opportunity_id: 8103, title: "클라우드 전환 인프라 통합 운영 사전규격", posted_at: "2026-10-06T11:00:00+09:00", deadline_at: null, document_version_id: "71030000-0000-4000-8000-000000000001", overview_run_id: "71030000-0000-4000-8000-0000000000e1", bundle_id: "71030000-0000-4000-8000-0000000000f1" },
  { notice_id: 7104, opportunity_id: null, title: "민원 상담 챗봇 학습데이터 구축 사전규격", posted_at: "2026-10-06T09:30:00+09:00", deadline_at: "2026-10-22T18:00:00+09:00", document_version_id: "71040000-0000-4000-8000-000000000001", overview_run_id: "71040000-0000-4000-8000-0000000000e1", bundle_id: "71040000-0000-4000-8000-0000000000f1" },
];

type FitSeed = { status: "queued" | "running" | "completed" | "failed" | "needs_human_review"; decision: "matched" | "mismatch" | "unknown" | null; summary: string | null; is_current: boolean } | null;
type ReviewSeed = { status: "queued" | "running" | "completed" | "failed"; is_current: boolean } | null;
type TrackingSeed = { tracking_status: "미선택" | "계속 추적" | "보류" | "종료"; reason: string | null; selected_by: string | null; selected_at: string | null; revision: number };

/** 회사 slug → notice_id → 핏 요약(서버가 준 값으로 쓰는 창작값). */
const FIT_SEEDS: Record<string, Record<number, FitSeed>> = {
  "demo-public-si": {
    7101: { status: "completed", decision: "matched", summary: "행정업무 통합 구축 역량과 직접 연결됩니다.", is_current: true },
    7102: { status: "completed", decision: "unknown", summary: "데이터 분석 인력 근거가 미확인입니다.", is_current: true },
    7103: { status: "completed", decision: "mismatch", summary: "클라우드 운영은 명시된 비주력 영역입니다.", is_current: true },
    7104: null,
  },
  "demo-data-ai": {
    7101: { status: "completed", decision: "mismatch", summary: "대규모 업무 시스템 구축 실적이 시나리오에 없습니다.", is_current: true },
    7102: { status: "completed", decision: "matched", summary: "데이터 분석 플랫폼 실적과 직접 연결됩니다.", is_current: true },
    7103: { status: "failed", decision: null, summary: null, is_current: true },
    7104: { status: "completed", decision: "unknown", summary: "학습데이터 품질 인증 보유가 미확인입니다.", is_current: false },
  },
  "demo-cloud-si": {
    7101: { status: "queued", decision: null, summary: null, is_current: true },
    7102: { status: "completed", decision: "mismatch", summary: "분석 플랫폼 개발은 비주력 영역입니다.", is_current: true },
    7103: { status: "completed", decision: "matched", summary: "클라우드 전환·운영 역량과 직접 연결됩니다.", is_current: true },
    7104: { status: "needs_human_review", decision: null, summary: null, is_current: true },
  },
};

const REVIEW_SEEDS: Record<string, Record<number, ReviewSeed>> = {
  "demo-public-si": { 7101: { status: "completed", is_current: true } },
  "demo-data-ai": { 7102: { status: "running", is_current: true }, 7103: { status: "failed", is_current: true } },
  "demo-cloud-si": {},
};

const TRACKING_SEEDS: Record<string, Record<number, TrackingSeed>> = {
  "demo-public-si": {
    8101: { tracking_status: "계속 추적", reason: "주력 역량과 맞아 계속 본다", selected_by: "업무SI 담당", selected_at: "2026-10-09T02:00:00+00:00", revision: 1 },
    8102: { tracking_status: "미선택", reason: null, selected_by: null, selected_at: null, revision: 0 },
    8103: { tracking_status: "보류", reason: "비주력 영역이라 보류", selected_by: "업무SI 담당", selected_at: "2026-10-09T02:10:00+00:00", revision: 1 },
  },
  "demo-data-ai": {
    8101: { tracking_status: "종료", reason: "구축 실적 범위 밖", selected_by: "데이터AI 담당", selected_at: "2026-10-09T03:00:00+00:00", revision: 1 },
    8102: { tracking_status: "계속 추적", reason: "분석 플랫폼 실적과 맞음", selected_by: "데이터AI 담당", selected_at: "2026-10-09T03:05:00+00:00", revision: 2 },
    8103: { tracking_status: "미선택", reason: null, selected_by: null, selected_at: null, revision: 0 },
  },
  "demo-cloud-si": {
    8101: { tracking_status: "미선택", reason: null, selected_by: null, selected_at: null, revision: 0 },
    8102: { tracking_status: "미선택", reason: null, selected_by: null, selected_at: null, revision: 0 },
    8103: { tracking_status: "계속 추적", reason: "클라우드 운영 주력", selected_by: "클라우드SI 담당", selected_at: "2026-10-09T04:00:00+00:00", revision: 1 },
  },
};

/*
 * 회사 지식 그래프 seed(계약 §3). 회사 원본 파일을 흉내 낸 창작값이다.
 *
 * - 회사 노드(`company`)는 함수가 회사 이름으로 붙인다. 나머지는 아래 seed 순서다.
 * - unknown 노드·관계는 value=null, 근거 0개다. 그 밖의 사실 노드는 자기 근거 1개,
 *   evidence 노드는 가리키는 사실의 근거, 관계는 `ref`(기본 to 노드) 사실의 근거를 쓴다
 *   (§4 "evidence 노드와 관계는 source_ref가 가리키는 non-unknown fact의 evidence_id").
 * - profile fact는 evidence가 아닌 노드를 그대로 투영한다(§4).
 * - 데모 업무SI에는 긴 한글 label(공백이 거의 없는 것 포함)·추정·미확인·인원 0·금액/기간
 *   미확인을 일부러 두었다. 화면이 줄바꿈·미확인과 0의 구분을 지키는지 드러나게 한다.
 */
type GraphStatus = "confirmed" | "inferred" | "unknown";

interface GraphNodeSeed {
  id: string;
  type: "capability" | "technology" | "domain" | "staff_group" | "project" | "qualification" | "evidence";
  label: string;
  status: GraphStatus;
  value: unknown;
  quote?: string;
}

interface GraphEdgeSeed {
  id: string;
  type: string;
  from: string;
  to: string;
  status: GraphStatus;
  /** 근거를 재사용할 사실 노드 id. 생략하면 to 노드다. */
  ref?: string;
}

interface CompanyGraphSeed {
  nodes: GraphNodeSeed[];
  edges: GraphEdgeSeed[];
}

/** 데모 업무SI의 긴 한글 label. 공백이 거의 없어 줄바꿈 규칙이 없으면 가로로 넘친다. */
export const LONG_GRAPH_LABEL = "전자기록물 관리시스템고도화및장기보존포맷변환체계구축(기록관리기준표·보존기간책정·이관검증자동화포함) 역량";

const GRAPH_SEEDS: Record<string, CompanyGraphSeed> = {
  "demo-public-si": {
    nodes: [
      { id: "capability.public_admin", type: "capability", label: "행정업무 시스템 구축", status: "confirmed", value: { scope: "core", description: "중앙부처 행정업무 통합 구축" }, quote: "주력 역량: 중앙부처 행정업무 통합 구축" },
      { id: "staff.developers", type: "staff_group", label: "개발 인력군", status: "confirmed", value: { role: "응용 개발", total: 42, available: 11, as_of: "2026-09-30" }, quote: "응용 개발 인력 42명 중 11명 투입 가능(2026-09-30 기준)" },
      { id: "capability.cloud_ops", type: "capability", label: "클라우드 운영", status: "confirmed", value: { scope: "non_core", description: "명시된 비주력 영역" }, quote: "클라우드 운영은 비주력 영역으로 둔다" },
      { id: "qualification.isms", type: "qualification", label: "정보보호 관리체계 인증", status: "unknown", value: null },
      { id: "capability.records_mgmt", type: "capability", label: LONG_GRAPH_LABEL, status: "inferred", value: { scope: "non_core", description: "기록관리 실적 1건에서 추정" }, quote: "기록관리 고도화 사업을 1건 수행했다" },
      { id: "technology.egov_framework", type: "technology", label: "전자정부 표준프레임워크", status: "confirmed", value: "전자정부 표준프레임워크 4.x", quote: "민원 통합 시스템은 전자정부 표준프레임워크 4.x 기반" },
      { id: "domain.central_gov", type: "domain", label: "중앙행정기관", status: "confirmed", value: "중앙행정기관", quote: "주요 고객은 중앙행정기관" },
      { id: "staff.pm", type: "staff_group", label: "사업관리 인력군", status: "confirmed", value: { role: "사업관리", total: 6, available: 0, as_of: "2026-09-30" }, quote: "사업관리 인력 6명 전원 투입 중(가용 0명)" },
      { id: "project.minwon_2025", type: "project", label: "민원 통합 시스템 구축", status: "confirmed", value: { role: "주관", scope: "민원 통합 시스템 구축", amount_krw: 1840000000, started_on: "2025-01-06", ended_on: null }, quote: "2025년 민원 통합 시스템 구축 주관, 18.4억 원" },
      { id: "qualification.sw_business", type: "qualification", label: "소프트웨어사업자 신고", status: "confirmed", value: "보유", quote: "소프트웨어사업자 신고 보유" },
      { id: "evidence.public_admin", type: "evidence", label: "행정업무 구축 근거", status: "confirmed", value: { fact_key: "capability.public_admin" } },
    ],
    edges: [
      { id: "edge.has_capability.public_admin", type: "has_capability", from: "company", to: "capability.public_admin", status: "confirmed" },
      { id: "edge.has_capability.cloud_ops", type: "has_capability", from: "company", to: "capability.cloud_ops", status: "confirmed" },
      { id: "edge.has_capability.records_mgmt", type: "has_capability", from: "company", to: "capability.records_mgmt", status: "inferred" },
      { id: "edge.has_staff.developers", type: "has_staff", from: "company", to: "staff.developers", status: "confirmed" },
      { id: "edge.has_staff.pm", type: "has_staff", from: "company", to: "staff.pm", status: "confirmed" },
      { id: "edge.operates_in.central_gov", type: "operates_in", from: "company", to: "domain.central_gov", status: "confirmed" },
      { id: "edge.performed.minwon_2025", type: "performed", from: "company", to: "project.minwon_2025", status: "confirmed" },
      { id: "edge.holds_qualification.isms", type: "holds_qualification", from: "company", to: "qualification.isms", status: "unknown" },
      { id: "edge.holds_qualification.sw_business", type: "holds_qualification", from: "company", to: "qualification.sw_business", status: "confirmed" },
      { id: "edge.minwon.uses_technology.egov", type: "uses_technology", from: "project.minwon_2025", to: "technology.egov_framework", status: "confirmed", ref: "project.minwon_2025" },
      { id: "edge.minwon.supports_capability.public_admin", type: "supports_capability", from: "project.minwon_2025", to: "capability.public_admin", status: "confirmed", ref: "project.minwon_2025" },
      { id: "edge.minwon.operates_in.central_gov", type: "operates_in", from: "project.minwon_2025", to: "domain.central_gov", status: "confirmed", ref: "project.minwon_2025" },
      { id: "edge.public_admin.supported_by", type: "supported_by", from: "capability.public_admin", to: "evidence.public_admin", status: "confirmed", ref: "capability.public_admin" },
    ],
  },
  "demo-data-ai": {
    nodes: [
      { id: "capability.data_platform", type: "capability", label: "데이터 분석 플랫폼", status: "confirmed", value: { scope: "core", description: "공공 데이터 분석 플랫폼 구축" } },
      { id: "staff.data_scientists", type: "staff_group", label: "데이터 분석 인력군", status: "confirmed", value: { role: "데이터 분석", total: 18, available: 5, as_of: "2026-09-30" } },
      { id: "capability.large_si", type: "capability", label: "대규모 업무 시스템 구축", status: "inferred", value: { scope: "non_core", description: "소규모 실적만 있음" } },
      { id: "qualification.data_quality", type: "qualification", label: "데이터 품질 인증", status: "unknown", value: null },
      { id: "technology.spark", type: "technology", label: "Apache Spark", status: "confirmed", value: "Apache Spark 3" },
      { id: "domain.statistics", type: "domain", label: "공공 통계", status: "confirmed", value: "공공 통계" },
      { id: "project.stat_portal_2024", type: "project", label: "통계 데이터 포털 고도화", status: "confirmed", value: { role: "주관", scope: "통계 데이터 포털 고도화", amount_krw: 620000000, started_on: "2024-03-01", ended_on: "2024-12-31" } },
    ],
    edges: [
      { id: "edge.has_capability.data_platform", type: "has_capability", from: "company", to: "capability.data_platform", status: "confirmed" },
      { id: "edge.has_capability.large_si", type: "has_capability", from: "company", to: "capability.large_si", status: "inferred" },
      { id: "edge.has_staff.data_scientists", type: "has_staff", from: "company", to: "staff.data_scientists", status: "confirmed" },
      { id: "edge.holds_qualification.data_quality", type: "holds_qualification", from: "company", to: "qualification.data_quality", status: "unknown" },
      { id: "edge.operates_in.statistics", type: "operates_in", from: "company", to: "domain.statistics", status: "confirmed" },
      { id: "edge.performed.stat_portal_2024", type: "performed", from: "company", to: "project.stat_portal_2024", status: "confirmed" },
      { id: "edge.stat_portal.uses_technology.spark", type: "uses_technology", from: "project.stat_portal_2024", to: "technology.spark", status: "confirmed", ref: "project.stat_portal_2024" },
      { id: "edge.stat_portal.supports_capability.data_platform", type: "supports_capability", from: "project.stat_portal_2024", to: "capability.data_platform", status: "confirmed", ref: "project.stat_portal_2024" },
    ],
  },
  "demo-cloud-si": {
    nodes: [
      { id: "capability.cloud_migration", type: "capability", label: "클라우드 전환", status: "confirmed", value: { scope: "core", description: "공공 클라우드 전환·운영" } },
      { id: "staff.cloud_engineers", type: "staff_group", label: "클라우드 엔지니어 인력군", status: "confirmed", value: { role: "클라우드 운영", total: 27, available: null, as_of: "2026-09-30" } },
      { id: "capability.analytics", type: "capability", label: "분석 플랫폼 개발", status: "confirmed", value: { scope: "non_core", description: "명시된 비주력 영역" } },
      { id: "qualification.csap", type: "qualification", label: "클라우드 보안 인증", status: "unknown", value: null },
      { id: "technology.kubernetes", type: "technology", label: "Kubernetes", status: "confirmed", value: "Kubernetes" },
      { id: "domain.local_gov", type: "domain", label: "지방자치단체", status: "confirmed", value: "지방자치단체" },
      { id: "project.cloud_move_2025", type: "project", label: "지자체 클라우드 전환", status: "confirmed", value: { role: "공동수급", scope: "지자체 클라우드 전환", amount_krw: null, started_on: "2025-02-01", ended_on: null } },
    ],
    edges: [
      { id: "edge.has_capability.cloud_migration", type: "has_capability", from: "company", to: "capability.cloud_migration", status: "confirmed" },
      { id: "edge.has_capability.analytics", type: "has_capability", from: "company", to: "capability.analytics", status: "confirmed" },
      { id: "edge.has_staff.cloud_engineers", type: "has_staff", from: "company", to: "staff.cloud_engineers", status: "confirmed" },
      { id: "edge.holds_qualification.csap", type: "holds_qualification", from: "company", to: "qualification.csap", status: "unknown" },
      { id: "edge.operates_in.local_gov", type: "operates_in", from: "company", to: "domain.local_gov", status: "confirmed" },
      { id: "edge.performed.cloud_move_2025", type: "performed", from: "company", to: "project.cloud_move_2025", status: "confirmed" },
      { id: "edge.cloud_move.uses_technology.kubernetes", type: "uses_technology", from: "project.cloud_move_2025", to: "technology.kubernetes", status: "confirmed", ref: "project.cloud_move_2025" },
    ],
  },
};

const HEX = "0123456789abcdef";
/** 문자열에서 결정적 hex64를 만든다. 실제 hash가 아니다(모양만 계약을 따른다). */
export function fixtureSha(seed: string): string {
  let out = "";
  let state = 0;
  for (let index = 0; out.length < 64; index += 1) {
    state = (state * 31 + seed.charCodeAt(index % seed.length) + index) % 1_000_003;
    out += HEX[state % 16];
  }
  return out;
}

/** 회사·순번에서 결정적 UUID를 만든다. */
function fixtureUuid(company: CompanyFixture, kind: string, ordinal: number): string {
  const prefix = company.company_id.slice(0, 8);
  const kindHex = fixtureSha(kind).slice(0, 4);
  return `${prefix}-${kindHex}-4000-8000-${String(ordinal).padStart(12, "0")}`;
}

export function companyDto(company: CompanyFixture) {
  return {
    company_id: company.company_id,
    slug: company.slug,
    name: company.name,
    is_fictional: company.is_fictional,
    created_at: company.created_at,
  };
}

export function fitSummary(company: CompanyFixture, notice: CompanyNoticeFixture) {
  const seed = FIT_SEEDS[company.slug]?.[notice.notice_id] ?? null;
  if (!seed) return null;
  return { attempt_id: fixtureUuid(company, "fit", notice.notice_id), ...seed };
}

export function reviewSummary(company: CompanyFixture, notice: CompanyNoticeFixture) {
  const seed = REVIEW_SEEDS[company.slug]?.[notice.notice_id] ?? null;
  if (!seed) return null;
  return { review_id: fixtureUuid(company, "review", notice.notice_id), ...seed };
}

export function reviewIdFor(company: CompanyFixture, noticeId: number): string {
  return fixtureUuid(company, "review", noticeId);
}

export type CompanyTrackingRow = TrackingSeed & { company_id: string; opportunity_id: number };

/** 페이지마다 새 상태를 쓴다(PATCH가 다른 테스트로 새지 않게). */
export function initialTrackingStore(): Map<string, CompanyTrackingRow> {
  const store = new Map<string, CompanyTrackingRow>();
  for (const company of COMPANY_FIXTURES) {
    for (const [opportunityId, seed] of Object.entries(TRACKING_SEEDS[company.slug] ?? {})) {
      store.set(`${company.company_id}:${opportunityId}`, { company_id: company.company_id, opportunity_id: Number(opportunityId), ...seed });
    }
  }
  return store;
}

export function trackingDto(row: CompanyTrackingRow) {
  return {
    company_id: row.company_id,
    opportunity_id: row.opportunity_id,
    tracking_status: row.tracking_status,
    reason: row.reason,
    selected_by: row.selected_by,
    selected_at: row.selected_at,
    revision: row.revision,
  };
}

/**
 * 사실 노드의 ProfileEvidence id. 회사 안에서 노드 순번(회사 노드=1)으로 정해 서로 겹치지
 * 않는다(짧은 fixture hash를 쓰면 다른 사실끼리 같은 id가 될 수 있다).
 */
function evidenceIdFor(company: CompanyFixture, factKey: string): string {
  const order = ["company", ...graphNodeSeeds(company).map((node) => node.id)];
  const index = order.indexOf(factKey);
  if (index < 0) throw new Error(`fixture에 없는 사실 노드: ${factKey}`);
  return fixtureUuid(company, "profile-evidence", index + 1);
}

/** evidence_id → 사실 노드 id. 테스트가 근거 요청을 확인할 때 쓴다. */
export function profileEvidenceIdFor(company: CompanyFixture, factKey: string): string {
  return evidenceIdFor(company, factKey);
}

interface PublicNodeFixture {
  id: string;
  type: string;
  label: string;
  concept_id: string | null;
  status: GraphStatus;
  origin: "fictional_scenario";
  value: unknown;
  evidence_ids: string[];
}

interface PublicEdgeFixture {
  id: string;
  type: string;
  from_id: string;
  to_id: string;
  status: GraphStatus;
  origin: "fictional_scenario";
  evidence_ids: string[];
}

function graphNodeSeeds(company: CompanyFixture): GraphNodeSeed[] {
  return GRAPH_SEEDS[company.slug]?.nodes ?? [];
}

/** 회사 노드 + seed 노드를 공개형(source_refs 없음)으로 옮긴다. */
function publicNodes(company: CompanyFixture): PublicNodeFixture[] {
  const companyNode: PublicNodeFixture = {
    id: "company", type: "company", label: company.name, concept_id: null, status: "confirmed",
    origin: "fictional_scenario", value: company.name, evidence_ids: [evidenceIdFor(company, "company")],
  };
  return [companyNode, ...graphNodeSeeds(company).map((node): PublicNodeFixture => ({
    id: node.id,
    type: node.type,
    label: node.label,
    concept_id: null,
    status: node.status,
    origin: "fictional_scenario",
    value: node.status === "unknown" ? null : node.value,
    evidence_ids: node.status === "unknown"
      ? []
      : node.type === "evidence"
        ? [evidenceIdFor(company, (node.value as { fact_key: string }).fact_key)]
        : [evidenceIdFor(company, node.id)],
  }))];
}

function publicEdges(company: CompanyFixture): PublicEdgeFixture[] {
  return (GRAPH_SEEDS[company.slug]?.edges ?? []).map((edge) => ({
    id: edge.id,
    type: edge.type,
    from_id: edge.from,
    to_id: edge.to,
    status: edge.status,
    origin: "fictional_scenario",
    evidence_ids: edge.status === "unknown" ? [] : [evidenceIdFor(company, edge.ref ?? edge.to)],
  }));
}

export function profileView(company: CompanyFixture) {
  return {
    schema_version: "bidops.company-profile-view.v1",
    company: companyDto(company),
    profile_version_id: company.profile_version_id,
    profile_sha256: fixtureSha(`${company.slug}:profile`),
    graph_version_id: company.graph_version_id,
    graph_sha256: fixtureSha(`${company.slug}:graph`),
    ontology_version: "demo-ontology-v1",
    // evidence가 아닌 회사 노드를 fact로 투영한다(§4). 회사 노드가 맨 앞이다.
    facts: publicNodes(company).filter((node) => node.type !== "evidence").map((node) => ({
      fact_key: node.id,
      label: node.label,
      status: node.status,
      origin: "fictional_scenario",
      value: node.value,
      evidence_ids: node.evidence_ids,
    })),
  };
}

export interface KnowledgeGraphFixtureQuery {
  rootNodeId: string | null;
  depth: number;
  limit: number;
}

/**
 * `GET .../knowledge-graph`의 고정 응답. 같은 seed·같은 query면 언제나 같은 응답이다.
 *
 * 서버(`services/company_knowledge.company_knowledge_graph_view`)의 공개 규칙을 그대로
 * 옮겼다 — 양방향 BFS로 root에서 depth 이내 노드를 모아 (거리, id) 순으로 앞에서 `limit`개,
 * 양끝이 남은 관계만 id 순, `omitted_node_count`=도달 노드 수-반환 노드 수. 화면이
 * 이 규칙을 다시 계산하지 않는다는 것을 테스트가 query·응답으로 확인하려면 가짜 서버가
 * query마다 다른 응답을 줘야 해서 seed를 이 규칙으로 고른다. root가 없으면 null(404).
 */
export function knowledgeGraphView(company: CompanyFixture, query: KnowledgeGraphFixtureQuery = { rootNodeId: null, depth: 2, limit: 200 }) {
  const nodes = publicNodes(company);
  const edges = publicEdges(company);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const root = query.rootNodeId ?? "company";
  if (!byId.has(root)) return null;
  const neighbours = new Map<string, string[]>();
  for (const edge of edges) {
    neighbours.set(edge.from_id, [...(neighbours.get(edge.from_id) ?? []), edge.to_id]);
    neighbours.set(edge.to_id, [...(neighbours.get(edge.to_id) ?? []), edge.from_id]);
  }
  const distance = new Map<string, number>([[root, 0]]);
  const queue = [root];
  while (queue.length > 0) {
    const current = queue.shift()!;
    const next = distance.get(current)! + 1;
    if (next > query.depth) continue;
    for (const neighbour of neighbours.get(current) ?? []) {
      if (distance.has(neighbour)) continue;
      distance.set(neighbour, next);
      queue.push(neighbour);
    }
  }
  const ordered = [...distance.keys()].sort((left, right) => (distance.get(left)! - distance.get(right)!) || (left < right ? -1 : left > right ? 1 : 0));
  const returned = ordered.slice(0, query.limit);
  const kept = new Set(returned);
  const omitted = ordered.length - returned.length;
  return {
    schema_version: "bidops.company-knowledge-graph.v1",
    company_id: company.company_id,
    graph_version_id: company.graph_version_id,
    graph_sha256: fixtureSha(`${company.slug}:graph`),
    ontology_version: "demo-ontology-v1",
    nodes: returned.map((id) => byId.get(id)!),
    edges: edges.filter((edge) => kept.has(edge.from_id) && kept.has(edge.to_id)).sort((left, right) => (left.id < right.id ? -1 : left.id > right.id ? 1 : 0)),
    truncated: omitted > 0,
    omitted_node_count: omitted,
  };
}

export function profileEvidenceView(company: CompanyFixture, evidenceId: string) {
  const fact = publicNodes(company).find((node) => node.type !== "evidence" && node.status !== "unknown" && evidenceIdFor(company, node.id) === evidenceId);
  if (!fact) return null;
  const seed = graphNodeSeeds(company).find((node) => node.id === fact.id);
  return {
    evidence_id: evidenceId,
    profile_version_id: company.profile_version_id,
    fact_key: fact.id,
    origin: "fictional_scenario",
    quote: seed?.quote ?? `${fact.label}: 가상 시나리오 설정값`,
    source_sha256: fixtureSha(`${company.slug}:source`),
  };
}

function provenance(company: CompanyFixture, notice: CompanyNoticeFixture, purpose: "company_fit" | "deep_review", inputSha: string) {
  return {
    input_sha256: inputSha,
    purpose,
    company_id: company.company_id,
    profile_version_id: company.profile_version_id,
    profile_sha256: fixtureSha(`${company.slug}:profile`),
    graph_version_id: company.graph_version_id,
    graph_sha256: fixtureSha(`${company.slug}:graph`),
    ontology_version: "demo-ontology-v1",
    ontology_sha256: fixtureSha("ontology"),
    documents: [{ document_version_id: notice.document_version_id, source_sha256: fixtureSha(`${notice.notice_id}:doc`) }],
    overview_run_id: notice.overview_run_id,
    overview_sha256: fixtureSha(`${notice.notice_id}:overview`),
    bundle_id: purpose === "deep_review" ? notice.bundle_id : null,
    policy_version_id: fixtureUuid(company, `policy:${purpose}`, 1),
    policy_sha256: fixtureSha(`policy:${purpose}`),
    model_name: purpose === "deep_review" ? "gpt-5.6-luna" : "local-agent-main",
    model_revision: null,
    generation_config_sha256: fixtureSha(`generation:${purpose}`),
  };
}

type FitDecisionValue = "matched" | "mismatch" | "unknown";
type FitReasonKind = "scope_match" | "scope_mismatch" | "information_gap";

interface FitPathSeed {
  requirement_id: string;
  node_ids: string[];
  edge_ids: string[];
  /** 프로필 근거를 가져올 사실 노드 id(회사 fixture의 evidence id로 바꾼다). */
  evidence_facts: string[];
  relation: "direct" | "partial" | "unmapped";
}

interface FitReasonSeed {
  kind: FitReasonKind;
  explanation: string;
  notice_refs: string[];
  company_refs: string[];
  graph_path_indexes: number[];
}

interface FitDetailSeed {
  reasons: FitReasonSeed[];
  paths: FitPathSeed[];
  verification_items: string[];
}

/** 이전 실행. 최신 실행은 요약 seed(`FIT_SEEDS`)에서 만든다. */
interface OlderFitSeed {
  ordinal: number;
  status: "queued" | "running" | "completed" | "failed" | "needs_human_review";
  decision: FitDecisionValue | null;
  summary: string | null;
  is_current: boolean;
  error_code: string | null;
  created_at: string;
  detail?: FitDetailSeed;
}

/*
 * 사유와 그래프 경로가 있는 최신 실행(slug → notice_id). 경로는 서버가 준 값을 흉내 낸
 * 창작값이며 화면은 `paths[graph_path_indexes[i]]`를 그대로 그린다.
 */
const LATEST_FIT_DETAIL: Record<string, Record<number, FitDetailSeed>> = {
  "demo-public-si": {
    7101: {
      paths: [
        { requirement_id: "req-001", node_ids: ["company", "capability.public_admin"], edge_ids: ["edge.has_capability.public_admin"], evidence_facts: ["capability.public_admin"], relation: "direct" },
        { requirement_id: "req-002", node_ids: ["company", "staff.developers"], edge_ids: ["edge.has_staff.developers"], evidence_facts: ["staff.developers"], relation: "partial" },
        { requirement_id: "req-003", node_ids: [], edge_ids: [], evidence_facts: [], relation: "unmapped" },
      ],
      reasons: [
        { kind: "scope_match", explanation: "행정업무 통합 구축은 이 회사의 주력 역량(행정업무 시스템 구축)과 직접 연결됩니다.", notice_refs: ["overview:req:0"], company_refs: ["company:capability.public_admin"], graph_path_indexes: [0, 1] },
        { kind: "information_gap", explanation: "정보보호 관리체계 인증 보유는 시나리오에 없어 확인이 필요합니다.", notice_refs: ["overview:req:1"], company_refs: [], graph_path_indexes: [2] },
      ],
      verification_items: ["정보보호 관리체계 인증 보유 여부 확인"],
    },
  },
};

/** 같은 (회사, 공고)의 이전 실행. 최신 실행보다 먼저 만들어졌고 서버 순서는 최신순이다. */
const OLDER_FIT_ATTEMPTS: Record<string, Record<number, OlderFitSeed[]>> = {
  "demo-public-si": {
    7101: [
      { ordinal: 2, status: "failed", decision: null, summary: null, is_current: false, error_code: "model_output_invalid", created_at: "2026-10-09T01:00:00+00:00" },
      {
        ordinal: 3, status: "completed", decision: "mismatch", summary: "이전 입력 기준: 구축 범위가 달라 불일치로 판단했습니다.", is_current: false, error_code: null, created_at: "2026-10-08T01:00:00+00:00",
        detail: {
          paths: [],
          reasons: [{ kind: "scope_mismatch", explanation: "이전 문서 버전은 인프라 운영 범위만 담고 있었습니다.", notice_refs: ["overview:req:0"], company_refs: [], graph_path_indexes: [] }],
          verification_items: [],
        },
      },
    ],
  },
  "demo-data-ai": {
    7103: [
      {
        ordinal: 2, status: "completed", decision: "unknown", summary: "이전 입력 기준: 클라우드 운영 근거가 없어 미확인이었습니다.", is_current: false, error_code: null, created_at: "2026-10-09T02:00:00+00:00",
        detail: {
          paths: [],
          reasons: [{ kind: "information_gap", explanation: "클라우드 운영 실적이 시나리오에 없습니다.", notice_refs: ["overview:req:0"], company_refs: [], graph_path_indexes: [] }],
          verification_items: ["클라우드 운영 실적 확인"],
        },
      },
    ],
  },
};

function defaultFitDetail(decision: FitDecisionValue, summary: string): FitDetailSeed {
  const kind: FitReasonKind = decision === "matched" ? "scope_match" : decision === "mismatch" ? "scope_mismatch" : "information_gap";
  return {
    paths: [],
    reasons: [{ kind, explanation: summary, notice_refs: ["overview:req:0"], company_refs: [], graph_path_indexes: [] }],
    verification_items: decision === "unknown" ? ["회사 근거 확인 필요"] : [],
  };
}

function fitResult(decision: FitDecisionValue, summary: string, detail: FitDetailSeed) {
  return {
    schema_version: "bidops.prespec-company-fit-result.v2",
    decision,
    summary,
    reasons: detail.reasons,
    verification_items: detail.verification_items,
  };
}

function fitAttemptView(
  company: CompanyFixture,
  notice: CompanyNoticeFixture,
  seed: { id: string; status: OlderFitSeed["status"]; decision: FitDecisionValue | null; summary: string | null; is_current: boolean; error_code: string | null; created_at: string; detail: FitDetailSeed | null; ordinal: number },
) {
  const inputSha = fixtureSha(`${company.slug}:${notice.notice_id}:fit-input:${seed.ordinal}`);
  const completed = seed.status === "completed" && seed.decision !== null && seed.summary !== null;
  const detail = seed.detail ?? (completed ? defaultFitDetail(seed.decision as FitDecisionValue, seed.summary as string) : null);
  const usedFacts = new Set<string>();
  for (const reason of detail?.reasons ?? []) {
    for (const ref of reason.company_refs) usedFacts.add(ref.replace(/^company:/, ""));
  }
  const noticeRefs = new Set<string>(["overview:req:0"]);
  for (const reason of detail?.reasons ?? []) for (const ref of reason.notice_refs) noticeRefs.add(ref);
  return {
    id: seed.id,
    notice_id: notice.notice_id,
    status: seed.status,
    result: completed && detail ? fitResult(seed.decision as FitDecisionValue, seed.summary as string, detail) : null,
    error_code: seed.error_code,
    is_current: seed.is_current,
    overview_kind: "overview_run",
    overview_id: notice.overview_run_id,
    document_version_id: notice.document_version_id,
    overview_sha256: fixtureSha(`${notice.notice_id}:overview`),
    profile_version_id: company.profile_version_id,
    profile_sha256: fixtureSha(`${company.slug}:profile`),
    policy_digest: fixtureSha("policy:company_fit"),
    model_name: "local-agent-main",
    model_revision: null,
    prompt_version: "company-fit-demo-v3",
    quality_status: "unmeasured_reference",
    notice_facts: [...noticeRefs].map((ref, index) => ({ ref, text: index === 0 ? notice.title : `${notice.title} 요구사항 ${index}`, pages: [index + 1], block_key: null })),
    company_facts: [...usedFacts].map((factKey) => ({ ref: `company:${factKey}`, fact_key: factKey, status: "confirmed", value: null })),
    created_at: seed.created_at,
    completed_at: completed ? seed.created_at : null,
    prompt_tokens: null,
    output_tokens: null,
    latency_ms: null,
    company_id: company.company_id,
    graph_version_id: company.graph_version_id,
    graph_sha256: fixtureSha(`${company.slug}:graph`),
    ontology_version: "demo-ontology-v1",
    input_sha256: inputSha,
    paths: (detail?.paths ?? []).map((path) => ({
      requirement_id: path.requirement_id,
      node_ids: path.node_ids,
      edge_ids: path.edge_ids,
      profile_evidence_ids: path.evidence_facts.map((factKey) => evidenceIdFor(company, factKey)),
      relation: path.relation,
    })),
    provenance: provenance(company, notice, "company_fit", inputSha),
  };
}

/**
 * `GET base/pre-specs/{notice_id}/company-fit`: 최신순(created_at DESC) 실행 목록.
 * 첫 항목은 목록·상세 요약(`fitSummary`)과 같은 실행이다.
 */
export function companyFitAttempts(company: CompanyFixture, notice: CompanyNoticeFixture) {
  const summary = fitSummary(company, notice);
  const attempts = [] as ReturnType<typeof fitAttemptView>[];
  if (summary !== null) {
    attempts.push(fitAttemptView(company, notice, {
      id: summary.attempt_id,
      status: summary.status,
      decision: summary.decision,
      summary: summary.summary,
      is_current: summary.is_current,
      error_code: summary.status === "failed" ? "model_output_invalid" : null,
      created_at: "2026-10-10T01:00:00+00:00",
      detail: LATEST_FIT_DETAIL[company.slug]?.[notice.notice_id] ?? null,
      ordinal: 1,
    }));
    for (const older of OLDER_FIT_ATTEMPTS[company.slug]?.[notice.notice_id] ?? []) {
      attempts.push(fitAttemptView(company, notice, {
        id: fixtureUuid(company, `fit-older-${older.ordinal}`, notice.notice_id),
        status: older.status,
        decision: older.decision,
        summary: older.summary,
        is_current: older.is_current,
        error_code: older.error_code,
        created_at: older.created_at,
        detail: older.detail ?? null,
        ordinal: older.ordinal,
      }));
    }
  }
  return { company_id: company.company_id, notice_id: notice.notice_id, attempts };
}

/*
 * 3사 비교 상태(계약 §6). 이 fixture는 문서 버전 집합을 계산하지 않으므로
 * `different_input`만 정해 둔 값으로 준다. 나머지는 서버 규칙(다른 입력 > 이전 입력 >
 * 결과 없음 > 비교 가능)을 같은 순서로 따른다.
 */
const COMPARISON_DIFFERENT_INPUT: Record<number, string[]> = { 7101: ["demo-data-ai"] };

export type ComparisonStatusValue = "comparable" | "stale" | "missing" | "different_input";

export function comparisonStatusFor(
  company: CompanyFixture,
  notice: CompanyNoticeFixture,
  fit: ReturnType<typeof fitSummary>,
  review: ReturnType<typeof reviewSummary>,
): ComparisonStatusValue {
  if ((fit || review) && COMPARISON_DIFFERENT_INPUT[notice.notice_id]?.includes(company.slug)) return "different_input";
  if ((fit && !fit.is_current) || (review && !review.is_current)) return "stale";
  if (!fit || !review) return "missing";
  return "comparable";
}

type LunaReview = typeof lunaReview;

export type CompanyReviewStatus = "queued" | "running" | "completed" | "failed";

/**
 * `GET base/deep-reviews/{review_id}`: 기존 DeepReviewView + 회사 identity.
 *
 * `attemptStatuses`는 분석 회차 상태를 오래된 순서로 준다(마지막이 현재 회차). 생략하면
 * 회차 하나다. 검토 상태는 현재 회차 상태와 같다(기존 Luna 검토 규칙).
 */
export function companyReviewView(company: CompanyFixture, notice: CompanyNoticeFixture, status: CompanyReviewStatus, isCurrent: boolean, attemptStatuses: CompanyReviewStatus[] = [status]) {
  const base: LunaReview["review"] = lunaReview.review;
  const inputSha = fixtureSha(`${company.slug}:${notice.notice_id}:review-input`);
  const reviewId = reviewIdFor(company, notice.notice_id);
  const attempts = attemptStatuses.map((attemptStatus, index) => ({
    ...base.current_attempt,
    id: index === 0 ? base.current_attempt.id : fixtureUuid(company, `attempt:${reviewId}`, index + 1),
    sequence: index + 1,
    status: attemptStatus,
    stages: base.current_attempt.stages.map((stage) => ({
      ...stage,
      status: attemptStatus === "completed" ? stage.status : attemptStatus === "failed" ? "failed" : "queued",
      started_at: attemptStatus === "queued" ? null : stage.started_at,
      completed_at: attemptStatus === "completed" ? stage.completed_at : null,
    })),
    last_error_code: attemptStatus === "failed" ? "model_output_invalid" : null,
    started_at: attemptStatus === "queued" ? null : base.current_attempt.started_at,
    completed_at: attemptStatus === "completed" ? base.current_attempt.completed_at : null,
  }));
  const attempt = attempts[attempts.length - 1];
  return {
    ...base,
    id: reviewId,
    notice_id: notice.notice_id,
    bundle_id: notice.bundle_id,
    status,
    current_attempt: attempt,
    attempts,
    completed_at: status === "completed" ? base.completed_at : null,
    quality_status: "unmeasured_reference",
    company_id: company.company_id,
    profile_version_id: company.profile_version_id,
    graph_version_id: company.graph_version_id,
    graph_sha256: fixtureSha(`${company.slug}:graph`),
    ontology_version: "demo-ontology-v1",
    input_sha256: inputSha,
    is_current: isCurrent,
    provenance: provenance(company, notice, "deep_review", inputSha),
  };
}

/** `GET base/deep-reviews/{review_id}/report`: 기존 ReportView를 `view`에 그대로 담는다. */
export function companyReportView(company: CompanyFixture, noticeId: number) {
  const view = structuredClone(lunaReview.report) as LunaReview["report"];
  view.deep_review_id = reviewIdFor(company, noticeId);
  (view.report as { profile_version_id: string }).profile_version_id = company.profile_version_id;
  return {
    schema_version: "bidops.company-report-view.v1",
    company_id: company.company_id,
    graph_version_id: company.graph_version_id,
    graph_sha256: fixtureSha(`${company.slug}:graph`),
    ontology_version: "demo-ontology-v1",
    profile_version_id: company.profile_version_id,
    view,
  };
}

export const companyReviewEvidence = lunaReview.evidence;

/** `POST base/pre-specs/{notice_id}/deep-review-previews`: 기존 Luna preview + 회사 identity. */
export function companyPreviewView(company: CompanyFixture, notice: CompanyNoticeFixture, previewOrdinal: number, reviewId: string | null) {
  const previewId = fixtureUuid(company, `preview:${notice.notice_id}`, previewOrdinal);
  return {
    preview_id: previewId,
    input_sha256: fixtureSha(`${company.slug}:${notice.notice_id}:preview:${previewOrdinal}`),
    provider: "codex-exec",
    model: "gpt-5.6-luna",
    reasoning_effort: "xhigh",
    quality_status: "unmeasured_reference",
    source_verification_enabled: true,
    // CompanyAnalysisInput(purpose=deep_review)의 전체 key 집합(`services/company_analysis_input.py`
    // `COMPANY_ANALYSIS_INPUT_KEYS`). 값은 모양만 맞춘 창작값이며 원문 text는 싣지 않는다.
    input: {
      schema_version: "bidops.company-analysis-input.v1",
      purpose: "deep_review",
      execution_nonce: previewId,
      target_review_id: reviewId,
      company_id: company.company_id,
      profile_version_id: company.profile_version_id,
      profile_sha256: fixtureSha(`${company.slug}:profile`),
      graph_version_id: company.graph_version_id,
      graph_sha256: fixtureSha(`${company.slug}:graph`),
      ontology_version: "demo-ontology-v1",
      ontology_sha256: fixtureSha("ontology"),
      notice_id: notice.notice_id,
      document_version_ids: [notice.document_version_id],
      bundle_id: notice.bundle_id,
      overview_run_id: notice.overview_run_id,
      overview_sha256: fixtureSha(`${notice.notice_id}:overview`),
      policy_version_id: fixtureUuid(company, "policy:deep_review", 1),
      policy_sha256: fixtureSha("policy:deep_review"),
      model_name: "gpt-5.6-luna",
      model_revision: null,
      generation_config_sha256: fixtureSha("generation:deep_review"),
      requirements: [
        { requirement_id: "req-001", document_version_id: notice.document_version_id, pages: [3] },
        { requirement_id: "req-002", document_version_id: notice.document_version_id, pages: [5] },
      ],
      profile_facts: [
        { fact_key: "company", status: "confirmed" },
        { fact_key: "capability.primary", status: "confirmed" },
        { fact_key: "qualification.unknown", status: "unknown" },
      ],
      profile_evidence: [{ evidence_id: fixtureUuid(company, "profile-evidence", 1) }],
      graph_nodes: [{ id: "company" }, { id: "capability.primary" }],
      graph_edges: [{ id: "edge.has_capability.primary" }],
      graph_paths: [{ requirement_id: "req-001", relation: "direct" }],
      coverage: { included_requirement_ids: ["req-001", "req-002"], unmapped_requirement_ids: ["req-002"], excluded_fact_keys: [], excluded_path_count_by_requirement: [] },
    },
    company_id: company.company_id,
    profile_version_id: company.profile_version_id,
    graph_version_id: company.graph_version_id,
    graph_sha256: fixtureSha(`${company.slug}:graph`),
    ontology_version: "demo-ontology-v1",
  };
}

export function companyAttemptView(company: CompanyFixture, reviewId: string, previewId: string, sequence: number) {
  const base = lunaReview.review.current_attempt;
  return {
    ...base,
    // `companyReviewView`가 같은 회차를 같은 id로 돌려주도록 같은 규칙을 쓴다.
    id: fixtureUuid(company, `attempt:${reviewId}`, sequence),
    last_error_code: null,
    sequence,
    status: "queued",
    stages: base.stages.map((stage) => ({ ...stage, status: "queued", started_at: null, completed_at: null })),
    started_at: null,
    completed_at: null,
    preview_id: previewId,
  };
}

/*
 * 긴 한글 문구(`mockCompanyWorkspace({ longText: true })`). 공백이 거의 없어 줄바꿈 규칙이
 * 없으면 표·카드 밖으로 넘친다. 모두 fixture 작성자의 창작값이다.
 */
export const LONG_NOTICE_TITLE =
  "차세대행정업무통합정보시스템구축및고도화사업(공공데이터연계·민원통합창구·전자결재개편·기록관리이관검증자동화포함)을위한사전규격공개에관한제안요청서검토대상공고";
export const LONG_SUMMARY =
  "행정업무통합구축역량과직접연결되지만정보보호관리체계인증보유여부와대규모동시접속부하시험실적은시나리오에명시되지않아담당자가원문과회사설정을대조해확인해야하는항목으로남아있습니다";
export const LONG_COMPANY_NAME_SUFFIX = "공공정보화사업전담컨소시엄주식회사긴이름점검용";
