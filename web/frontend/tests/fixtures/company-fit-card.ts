/**
 * 사전규격 회사 핏 v2(사업 범위 카드, PS-01) mock fixture.
 *
 * 응답 모양은 `bidops.prespec-company-fit.v2`(spec C5)와 목록 요약(C6)을 그대로 따른다.
 * 카드 범위·정책 이름은 합성 값이며 실제 회사 자료가 아니다. 화면 주소의 `?fit=`가
 * 상세 판정을 고르고(`matched|unknown|mismatch|pending`), `&judge=claude`가 가져온 Claude
 * 참조 판정(`judged_by: "claude_reference"`)을 고른다.
 */
import type {
  CompanyFitAttempt,
  CompanyFitMode,
  CompanyFitResponse,
  CompanyFitResult,
  PreSpecCompanyFitGroup,
  PreSpecCompanyFitSummary,
  PreSpecListItem,
} from "../../src/lib/types";

export type CompanyFitFixtureChoice = "matched" | "unknown" | "mismatch" | "pending";
export type CompanyFitJudge = "model" | "claude_reference";

export const COMPANY_FIT_FIXTURE_CHOICES: readonly CompanyFitFixtureChoice[] = ["matched", "unknown", "mismatch", "pending"];

export const CARD_VERSION = "bidops.business-scope-card.v1.2";
export const CARD_SHA256 = "5ca1ab1e".repeat(8);
export const CARD_PROMPT_VERSION = "prespec-company-fit-v3.1";

/** 카드가 없는 공고의 목록 요약(C6 "카드 attempt가 없으면"). */
export const NO_CARD_FIT: PreSpecCompanyFitSummary = {
  group: "pending", decision: null, status: null, is_current: false, engine_suggested: false,
};

/** `?fit` 없이 쓰는 기본 응답. v1 기본 fixture(`attempts: []`, 자동 판정 비활성)를 v2 모양으로 옮겼다. */
export function defaultCompanyFitResponse(noticeId: number): CompanyFitResponse {
  return {
    schema_version: "bidops.prespec-company-fit.v2",
    notice_id: noticeId,
    attempts: [],
    automation_enabled: false,
    mode: { mode: "off", effective: false, reason_code: "company_fit_disabled", card_version: null, card_sha256: null, prompt_version: CARD_PROMPT_VERSION },
    engine_suggested: false,
    auto_deep_review_reason: "company_fit_disabled",
    deep_review_id: null,
  };
}

const CARD_FACTS: CompanyFitAttempt["company_facts"] = [
  { ref: "scope:data-platform", fact_key: "데이터 플랫폼 구축·운영", status: "confirmed", value: { summary: "공공 데이터 수집·이관·분석 플랫폼을 구축하고 운영한다." } },
  { ref: "scope:public-si", fact_key: "공공 정보시스템 구축", status: "confirmed", value: { summary: "공공기관 업무 시스템을 설계·개발한다." } },
  { ref: "policy:no-bid", fact_key: "exclude", status: "confirmed", value: { summary: "장비 납품·유지보수 단독 사업은 수행하지 않는다." } },
  { ref: "policy:onsite", fact_key: "condition", status: "confirmed", value: { summary: "상주 조건은 인력 규모를 사람이 확인한다." } },
  { ref: "policy:mixed-scope", fact_key: "exclude", status: "confirmed", value: { summary: "구매·구축이 섞이면 구축 비중으로 판단한다." } },
];

const CARD_LABELS: Record<string, string> = {
  "scope:data-platform": "데이터 플랫폼 구축·운영",
  "scope:public-si": "공공 정보시스템 구축",
  "policy:no-bid": "수행하지 않는 사업",
  "policy:onsite": "상주 조건",
  "policy:mixed-scope": "섞인 사업 판단",
};

const RESULTS: Record<Exclude<CompanyFitFixtureChoice, "pending">, CompanyFitResult> = {
  matched: {
    schema_version: "bidops.prespec-company-fit-result.v1",
    decision: "matched",
    summary: "공고 과업이 회사 사업 범위의 데이터 플랫폼 구축과 맞아요.",
    reasons: [
      { kind: "scope_match", explanation: "기존 데이터를 새 플랫폼으로 이관·검증하는 과업이 데이터 플랫폼 구축 범위에 들어요.", notice_refs: ["notice:title", "claim:c2"], company_refs: ["scope:data-platform"] },
      { kind: "scope_match", explanation: "상주 조건이 있으나 정책상 확인 대상일 뿐 수행 제외 사유가 아니에요.", notice_refs: ["claim:c2"], company_refs: ["policy:onsite"] },
    ],
    verification_items: ["상주 인력 규모와 기간은 사람이 확인해야 해요."],
  },
  unknown: {
    schema_version: "bidops.prespec-company-fit-result.v1",
    decision: "unknown",
    summary: "장비 구매와 구축의 비중을 확인할 수 없어 판단을 보류해요.",
    reasons: [
      { kind: "information_gap", explanation: "개요에 구매 품목과 구축 과업의 금액 비중이 없어요.", notice_refs: ["notice:title"], company_refs: ["policy:mixed-scope"] },
    ],
    verification_items: ["제안요청서에서 구매·구축 금액 비중을 확인해야 해요."],
  },
  mismatch: {
    schema_version: "bidops.prespec-company-fit-result.v1",
    decision: "mismatch",
    summary: "장비 유지보수 단독 사업이라 회사가 수행하지 않는 사업이에요.",
    reasons: [
      { kind: "scope_mismatch", explanation: "과업이 기존 장비의 유지보수뿐이고 시스템 구축이 없어요.", notice_refs: ["notice:title"], company_refs: ["policy:no-bid"] },
    ],
    verification_items: [],
  },
};

export function cardMode(): CompanyFitMode {
  return { mode: "suggest", effective: true, reason_code: null, card_version: CARD_VERSION, card_sha256: CARD_SHA256, prompt_version: CARD_PROMPT_VERSION };
}

export function cardAttempt(args: {
  noticeId: number;
  title: string;
  choice: CompanyFitFixtureChoice;
  judge?: CompanyFitJudge;
  overviewId: string;
}): CompanyFitAttempt {
  const judge = args.judge ?? "model";
  const running = args.choice === "pending";
  return {
    id: `fit-card-${args.noticeId}`,
    notice_id: args.noticeId,
    status: running ? "running" : "completed",
    result: running ? null : RESULTS[args.choice as Exclude<CompanyFitFixtureChoice, "pending">],
    error_code: null,
    is_current: true,
    lineage: "card",
    card_version: CARD_VERSION,
    card_sha256: CARD_SHA256,
    judged_by: judge,
    company_fact_labels: CARD_LABELS,
    overview_kind: "overview_run",
    overview_id: args.overviewId,
    document_version_id: "d0c00000-0000-4000-8000-000000000001",
    overview_sha256: "a".repeat(64),
    profile_version_id: null,
    profile_sha256: null,
    policy_digest: "c".repeat(64),
    model_name: judge === "claude_reference" ? "claude-reference-judgment" : "local-agent-main",
    model_revision: judge === "claude_reference" ? "f".repeat(64) : "d".repeat(64),
    prompt_version: CARD_PROMPT_VERSION,
    quality_status: "unmeasured_reference",
    notice_facts: [
      { ref: "notice:title", text: args.title, pages: [], block_key: null },
      { ref: "claim:c2", text: "기존 데이터를 신규 플랫폼으로 이관하고 검증한다.", pages: [5, 6], block_key: null },
    ],
    company_facts: CARD_FACTS,
    created_at: "2026-11-27T01:00:00Z",
    completed_at: running ? null : "2026-11-27T01:00:48Z",
    prompt_tokens: running ? null : 6120,
    output_tokens: running ? null : 412,
    latency_ms: running ? null : 48_000,
  };
}

/** 카드 lineage 상세 응답(C5, MVP 4). `engine_suggested`는 현재 부합이고 모드가 추천일 때만 true다. */
export function cardCompanyFitResponse(args: {
  noticeId: number;
  title: string;
  choice: CompanyFitFixtureChoice;
  judge?: CompanyFitJudge;
  overviewId: string;
}): CompanyFitResponse {
  return {
    schema_version: "bidops.prespec-company-fit.v2",
    notice_id: args.noticeId,
    attempts: [cardAttempt(args)],
    automation_enabled: true,
    mode: cardMode(),
    engine_suggested: args.choice === "matched",
    auto_deep_review_reason: "company_fit_suggest_only",
    deep_review_id: null,
  };
}

/** 목록 요약(C6). 진행 중인 attempt는 그룹이 `pending`이고 판정이 없다. */
export function cardFitSummary(choice: CompanyFitFixtureChoice | null): PreSpecCompanyFitSummary {
  if (choice === null) return NO_CARD_FIT;
  if (choice === "pending") return { group: "pending", decision: null, status: "running", is_current: true, engine_suggested: false };
  return { group: choice, decision: choice, status: "completed", is_current: true, engine_suggested: choice === "matched" };
}

/**
 * `검토할 항목`에 드는 회사 핏 표본 여섯 건. 네 그룹과 마감 전·null 마감을 섞어 `회사 핏순`과
 * `마감 임박순`이 서로 다른 순서가 되게 한다. 마감은 mock 고정 시계(2026-09-01) 기준 마감 전이다.
 * `fit`이 `null`이면 카드 attempt가 없는 공고다(판정 전).
 */
const FIT_SAMPLES: { id: number; title: string; deadline: string | null; fit: CompanyFitFixtureChoice | null }[] = [
  { id: 9101, title: "통합 데이터 플랫폼 고도화 사전규격", deadline: "2026-09-05T08:00:00Z", fit: "matched" },
  { id: 9102, title: "행정 장비 도입과 연계 구축 사전규격", deadline: "2026-09-03T08:00:00Z", fit: "unknown" },
  { id: 9103, title: "민원 처리 시스템 개선 사전규격", deadline: "2026-09-02T08:00:00Z", fit: "pending" },
  { id: 9104, title: "청사 영상장비 유지보수 사전규격", deadline: "2026-09-04T08:00:00Z", fit: "mismatch" },
  { id: 9105, title: "공공 데이터 개방 포털 구축 사전규격", deadline: "2026-09-08T08:00:00Z", fit: "matched" },
  { id: 9106, title: "지역 정보화 전략 수립 사전규격", deadline: null, fit: null },
];

export const COMPANY_FIT_LIST_IDS: readonly number[] = FIT_SAMPLES.map((sample) => sample.id);

export function companyFitSampleChoice(noticeId: number): CompanyFitFixtureChoice | null | undefined {
  const sample = FIT_SAMPLES.find((entry) => entry.id === noticeId);
  return sample ? sample.fit : undefined;
}

export function companyFitSampleTitle(noticeId: number): string | null {
  return FIT_SAMPLES.find((entry) => entry.id === noticeId)?.title ?? null;
}

export const companyFitListItems: PreSpecListItem[] = FIT_SAMPLES.map((sample, index) => ({
  review_exclusion_status: "included",
  review_exclusion_actor_name: null,
  review_exclusion_reason: null,
  review_exclusion_changed_at: null,
  notice_pk: sample.id,
  pre_spec_no: `PRE-${sample.id}`,
  title: sample.title,
  agency: "합성 발주기관",
  demand_agency: null,
  published_at: `2026-08-2${index}T00:00:00Z`,
  deadline_at: sample.deadline,
  budget: 300_000_000 + index * 50_000_000,
  sw_business_status: "Y",
  business_division: "일반용역",
  origin: "신규",
  opportunity_id: null,
  tracking_status: null,
  kept_by_tracking: false,
  document: { attachments: 1, "완료": 1, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
  overview_review_status: "completed",
  grade: null,
  grade_source: null,
  display_assessment: {
    grade: null, status: "none", source: "none", basis_run_id: null, assessed_at: null, quality_status: null,
    reason_codes: [], axes: [], verification_items: [], semantic_status: null, semantic_scope: [], latest_run_status: "completed",
  },
  auto_preparation_status: "overview_settled",
  auto_preparation_reason: null,
  latest_deep_review_id: null,
  first_observed_at: `2026-08-2${index}T00:00:00Z`,
  last_observed_at: `2026-08-2${index}T00:00:00Z`,
  next_action: "review_overview",
  company_fit: cardFitSummary(sample.fit),
}));

const FIT_GROUP_RANK: Record<PreSpecCompanyFitGroup, number> = { matched: 0, unknown: 1, pending: 2, mismatch: 3 };

/** 서버 `sort=fit`의 그룹 순위. 요약이 없으면 `pending`이다(C7). */
export function companyFitRank(item: Pick<PreSpecListItem, "company_fit">): number {
  return FIT_GROUP_RANK[item.company_fit?.group ?? "pending"];
}
