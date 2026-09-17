import type { Page, Route } from "@playwright/test";

/**
 * 최종 Go/No-Go 목록·결정 화면의 고정 입력.
 *
 * 공유 `api-mock.ts`를 고치지 않고 이 spec만 쓰는 route override로 둔다. 값은 API
 * 계약 형태 그대로이며 **화면에 하드코딩하지 않는다**. 승인된 시안과 같은 정보
 * 밀도(사업 10건, 완료·대기·실패·비교 없음·조회 실패·조회 중, 미결정·현재 결정·
 * 오래된 결정)를 만들어 시안 캡처와 같은 자리에서 대조할 수 있게 한다.
 *
 * 변경 비교를 계산하는 worker는 아직 구현 전이므로 `completed` 비교는 **앞으로의
 * 완료 상태를 검증하기 위한 계약 형태의 고정 입력**이다. 운영 결과가 아니다.
 */

const BASE_ID = 901;

interface Business {
  agency: string;
  title: string;
}

export const BUSINESSES: Business[] = [
  { agency: "해솔시청", title: "공공데이터 통합관리체계 고도화" },
  { agency: "도담도시공사", title: "시설관리 업무시스템 구축" },
  { agency: "한결교통공사", title: "교통정보 수집·제공 플랫폼 고도화" },
  { agency: "새온교육지원청", title: "학교 통합정보서비스 운영 및 유지관리" },
  { agency: "가온연구원", title: "연구성과 통합검색 서비스 개편" },
  { agency: "누리환경공단", title: "환경측정 데이터 품질관리 용역" },
  { agency: "다온문화재단", title: "문화시설 통합예약 서비스 구축" },
  { agency: "온빛대학교", title: "학사행정시스템 통합 유지관리" },
  { agency: "이음공공의료원", title: "의료정보 연계 기반 구축" },
  { agency: "다솜관광공사", title: "관광데이터 분석 환경 구축" },
];

export const LONG_TITLE = "공공데이터 통합관리체계와 기관 간 정보연계 플랫폼 고도화 및 데이터 품질관리 기반 구축 사업";

type CalculationStatus = "pending" | "running" | "completed" | "failed";
type ResultStatus = "changed" | "unchanged" | "unknown" | "failed";
type Currentness = "current" | "stale" | "unknown";

interface Scenario {
  /** 이 사업기회의 비교 계산 상태. `null`이면 비교 자체가 없다. */
  calculation: CalculationStatus | null;
  result?: ResultStatus;
  /** 마지막 최종 결정. 없으면 미결정. */
  decision?: { value: "go" | "no_go"; reason: string; sequence: number };
  currentness: Currentness;
  /** workspace 조회를 실패시키거나 늦춘다. */
  lookup?: "failed" | "slow";
}

export const SCENARIOS: Scenario[] = [
  { calculation: "completed", result: "changed", currentness: "unknown" },
  { calculation: "pending", currentness: "unknown" },
  {
    calculation: "pending",
    currentness: "stale",
    decision: { value: "go", reason: "과업 범위와 수행 계획을 검토한 뒤 참여를 결정했습니다.", sequence: 1 },
  },
  { calculation: null, currentness: "unknown" },
  { calculation: "completed", result: "unchanged", currentness: "unknown" },
  { calculation: "failed", result: "failed", currentness: "unknown" },
  {
    calculation: "completed",
    result: "changed",
    currentness: "current",
    decision: { value: "go", reason: "축소된 일정에도 수행 여력이 확인되어 참여합니다.", sequence: 1 },
  },
  {
    calculation: "completed",
    result: "changed",
    currentness: "current",
    decision: { value: "no_go", reason: "수행 일정과 인력 확보가 어려워 불참합니다.", sequence: 1 },
  },
  { calculation: "completed", result: "changed", currentness: "unknown", lookup: "failed" },
  { calculation: "completed", result: "changed", currentness: "unknown", lookup: "slow" },
];

function hex(seed: number, char: string): string {
  return `${char.repeat(63)}${seed.toString(16)}`.slice(-64);
}

function uuid(seed: number, tag: string): string {
  const body = String(seed).padStart(12, "0");
  return `${tag.repeat(8)}-${tag.repeat(4)}-4${tag.repeat(3)}-8${tag.repeat(3)}-${body}`;
}

function inputRef(index: number, side: "baseline" | "comparison") {
  const id = BASE_ID + index;
  return {
    opportunity_link_id: id * 10 + (side === "baseline" ? 1 : 2),
    notice_id: id * 100 + (side === "baseline" ? 1 : 2),
    bundle_id: uuid(id, side === "baseline" ? "b" : "c"),
    bundle_revision: side === "baseline" ? 1 : 2,
    bundle_version: side === "baseline" ? 1 : 2,
    document_version_id: uuid(id, side === "baseline" ? "2" : "5"),
    document_version_version: side === "baseline" ? 1 : 2,
    structure_id: uuid(id, side === "baseline" ? "3" : "6"),
    source_sha256: hex(id, side === "baseline" ? "a" : "b"),
    structure_payload_sha256: hex(id, side === "baseline" ? "c" : "d"),
    notice_source_type: side === "baseline" ? "pre_spec" : "bid_notice",
    notice_external_id: side === "baseline" ? `PS-2026-${id}` : `BN-2026-${id}`,
    bid_ordinal: side === "baseline" ? null : "1",
    published_at: side === "baseline" ? "2026-08-31T02:00:00Z" : "2026-09-05T02:00:00Z",
    document_role: "제안요청서",
    effective_date: side === "baseline" ? "2026-08-31" : "2026-09-05",
  };
}

function evidence(index: number, side: "baseline" | "comparison", ordinal: number, quote: string, page: number) {
  const id = BASE_ID + index;
  return {
    id: uuid(id * 10 + ordinal, side === "baseline" ? "7" : "8"),
    side,
    document_version_id: uuid(id, side === "baseline" ? "2" : "5"),
    structure_id: uuid(id, side === "baseline" ? "3" : "6"),
    source_sha256: hex(id, side === "baseline" ? "a" : "b"),
    locator_type: "page" as const,
    locator: { page },
    quote,
    verification_status: "verified" as const,
  };
}

/** 시안과 같은 갈래 분포: 중요 변경 2 · 표기 변경 1 · 확인 필요 1 · 변경 없음 3. */
function items(index: number, result: ResultStatus) {
  const base = [
    {
      category: "scope_and_requirements",
      result_status: "changed",
      materiality: "material",
      before_value: "연계 대상 시스템 3개",
      after_value: "연계 대상 시스템 5개",
      summary: "연계 대상이 2개 늘었습니다.",
      page: 12,
      error_code: null,
    },
    {
      category: "contract_period_and_schedule",
      result_status: "changed",
      materiality: "material",
      before_value: "계약일로부터 8개월",
      after_value: "계약일로부터 6개월",
      summary: "수행 기간이 2개월 줄었습니다.",
      page: 4,
      error_code: null,
    },
    {
      category: "evaluation",
      result_status: "changed",
      materiality: "non_material",
      before_value: "기술능력 평가",
      after_value: "기술능력평가",
      summary: "표기만 달라졌습니다.",
      page: 32,
      error_code: null,
    },
    {
      category: "eligibility",
      result_status: "unknown",
      materiality: "unknown",
      before_value: null,
      after_value: "직접생산확인증명서 제출",
      summary: null,
      page: null,
      error_code: "bid_delta_evidence_missing",
    },
    { category: "budget_and_economics", result_status: "unchanged", materiality: "non_material", before_value: "추정가격 12억 원", after_value: "추정가격 12억 원", summary: null, page: 3, error_code: null },
    { category: "joint_supply_and_subcontracting", result_status: "unchanged", materiality: "non_material", before_value: "공동수급 허용", after_value: "공동수급 허용", summary: null, page: 8, error_code: null },
    { category: "submission", result_status: "unchanged", materiality: "non_material", before_value: "전자 제출", after_value: "전자 제출", summary: null, page: 41, error_code: null },
  ] as const;

  return base.map((item, ordinal) => {
    // `unchanged` 시나리오는 실제 0건을 보여 준다. 7개 범주 모두 변경 없음이다.
    const resultStatus = result === "unchanged" ? "unchanged" : item.result_status;
    const materiality = result === "unchanged" ? "non_material" : item.materiality;
    const hasEvidence = item.page !== null;
    return {
      id: uuid((BASE_ID + index) * 100 + ordinal, "9"),
      ordinal: ordinal + 1,
      category: item.category,
      result_status: resultStatus,
      materiality,
      before_value: result === "unchanged" ? item.after_value : item.before_value,
      after_value: item.after_value,
      summary: result === "unchanged" ? null : item.summary,
      baseline_evidence: hasEvidence
        ? [evidence(index, "baseline", ordinal, `${item.before_value ?? item.after_value} (기준 원문 ${ordinal + 1})`, item.page as number)]
        : [],
      comparison_evidence: hasEvidence
        ? [evidence(index, "comparison", ordinal, `${item.after_value} (비교 원문 ${ordinal + 1})`, item.page as number)]
        : [],
      error_code: result === "unchanged" ? null : item.error_code,
    };
  });
}

function finalDecision(index: number, scenario: Scenario) {
  if (!scenario.decision) return null;
  const id = BASE_ID + index;
  return {
    // v2(ADR-0058): 이 고정 입력은 기존 비교 근거(`basis_kind: "comparison"`)만
    // 모델링한다. `notice_conditions` 근거는 `mockGoNoGo`의 `bid-conditions` 경로와
    // 별도 시나리오(§9.2)가 다룬다.
    schema_version: "bidops.bid-final-decision.v2",
    id: uuid(id, "d"),
    opportunity_id: id,
    sequence: scenario.decision.sequence,
    basis_kind: "comparison",
    comparison_id: uuid(id, "7"),
    comparison_version: 2,
    result_sha256: hex(id, "e"),
    baseline_document_version_id: uuid(id, "2"),
    comparison_document_version_id: uuid(id, "5"),
    basis_notice_id: null,
    basis_observation_sha256: null,
    supersedes_final_decision_id: null,
    decision: scenario.decision.value,
    reason: scenario.decision.reason,
    claimed_name: "기존 검토자",
    request_id: uuid(id, "f"),
    created_at: "2026-09-04T06:20:00Z",
    currentness: scenario.currentness,
    currentness_reasons: scenario.currentness === "stale"
      ? ["결정 이후 새 정정공고 문서 버전이 연결되었습니다."]
      : scenario.currentness === "unknown" ? ["비교 입력의 현재성을 확인하지 못했습니다."] : [],
  };
}

function comparisonSummary(index: number, scenario: Scenario) {
  if (!scenario.calculation) return null;
  const id = BASE_ID + index;
  return {
    id: uuid(id, "7"),
    sequence: 1,
    version: 2,
    category_policy_version: "bid-delta-policy.v1",
    calculation_status: scenario.calculation,
    result_status: scenario.calculation === "completed" ? scenario.result ?? "changed" : scenario.calculation === "failed" ? "failed" : null,
    materiality: scenario.result === "unchanged" ? "non_material" : "material",
    baseline: inputRef(index, "baseline"),
    comparison: inputRef(index, "comparison"),
    result_sha256: scenario.calculation === "completed" ? hex(id, "e") : null,
    created_at: "2026-09-05T04:00:00Z",
    started_at: scenario.calculation === "pending" ? null : "2026-09-05T04:01:00Z",
    completed_at: scenario.calculation === "completed" ? "2026-09-05T04:06:00Z" : null,
  };
}

export function workspaceFor(index: number, scenario: Scenario = SCENARIOS[index]) {
  const summary = comparisonSummary(index, scenario);
  const decision = finalDecision(index, scenario);
  return {
    schema_version: "bidops.bid-delta-workspace.v1",
    opportunity_id: BASE_ID + index,
    baseline_candidates: [inputRef(index, "baseline")],
    comparison_candidates: [inputRef(index, "comparison")],
    comparisons: summary ? [summary] : [],
    latest_final_decision: decision,
    decision_currentness: decision ? scenario.currentness : "unknown",
    currentness_reasons: decision?.currentness_reasons ?? [],
    generated_at: "2026-09-07T06:00:00Z",
  };
}

export function comparisonFor(index: number, scenario: Scenario = SCENARIOS[index]) {
  const summary = comparisonSummary(index, scenario);
  if (!summary) return null;
  const decision = finalDecision(index, scenario);
  const result = scenario.calculation === "completed" ? scenario.result ?? "changed" : null;
  return {
    ...summary,
    schema_version: "bidops.bid-delta-comparison.v1",
    opportunity_id: BASE_ID + index,
    items: result ? items(index, result) : [],
    attempts: [
      {
        id: uuid(BASE_ID + index, "1"),
        sequence: 1,
        status: scenario.calculation === "completed" ? "completed" : scenario.calculation === "failed" ? "failed" : "queued",
        started_at: scenario.calculation === "pending" ? null : "2026-09-05T04:01:00Z",
        completed_at: scenario.calculation === "completed" ? "2026-09-05T04:06:00Z" : null,
        last_error_code: scenario.calculation === "failed" ? "bid_delta_calculation_failed" : null,
      },
    ],
    last_error_code: scenario.calculation === "failed" ? "bid_delta_calculation_failed" : null,
    final_decisions: decision ? [decision] : [],
    latest_final_decision: decision,
    decision_currentness: decision ? scenario.currentness : "unknown",
    currentness_reasons: decision?.currentness_reasons ?? [],
  };
}

export function opportunityFor(index: number, title?: string) {
  const id = BASE_ID + index;
  const business = BUSINESSES[index];
  return {
    section: "추적 중",
    pending_candidate_link_count: 0,
    open_blocking_item_count: 0,
    action_reasons: [],
    hold_review_due_at: null,
    id,
    tracking_status: "계속 추적",
    tracking_reason: "입찰공고를 확인하고 변경을 비교합니다.",
    tracking_selected_by: "기존 담당자",
    tracking_selected_at: "2026-08-30T01:00:00Z",
    recheck_signal: false,
    recheck_signal_at: null,
    recheck_signal_link_id: null,
    first_registered_stage: "pre_spec",
    links: [{
      id: id * 10,
      stage: "notice",
      link_type: "official",
      status: "확정",
      search_strategy: null,
      attempted_strategies: [],
      agency_match: true,
      last_searched_at: null,
      evidence_external_no: null,
      evidence_bid_no: null,
      human_decision: null,
      reviewer_name: null,
      reviewed_at: null,
      review_reason: null,
      record_type: "bid_notice",
      record_id: id * 100,
      notice_id: id * 100,
      order_plan_id: null,
      source_type: "bid_notice",
      title: title ?? business.title,
      agency: business.agency,
      external_id: `BN-2026-${id}`,
      record_external_id: `BN-2026-${id}`,
    }],
  };
}

export interface GoNoGoMockOptions {
  /** 첫 사업의 제목을 긴 한글 제목으로 바꾼다. */
  longTitle?: boolean;
  /** 사업기회 목록 자체를 실패시킨다. */
  listError?: boolean;
  /** `조회 중` 상태를 캡처할 수 있게 slow workspace 응답을 더 오래 붙든다. */
  slowMs?: number;
  /** 사업기회 수를 줄인다(페이저 없는 기본 목록). */
  count?: number;
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

/**
 * 목록·workspace·비교 상세를 한 벌로 연결한다. `mockApi(page)` 뒤에 부르면 이
 * 경로만 덮어쓴다.
 */
export async function mockGoNoGo(page: Page, options: GoNoGoMockOptions = {}): Promise<void> {
  const count = options.count ?? SCENARIOS.length;
  const opportunities = SCENARIOS.slice(0, count).map((_, index) =>
    opportunityFor(index, index === 0 && options.longTitle ? LONG_TITLE : undefined));

  await page.route(/\/api\/opportunities(\?|$)/, async (route) => {
    if (options.listError) {
      await json(route, { error: { code: "internal_error", message: "합성 실패", details: null }, request_id: null }, 500);
      return;
    }
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get("limit") ?? "25");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    await json(route, {
      items: opportunities.slice(offset, offset + limit),
      total: opportunities.length,
      limit,
      offset,
      section_counts: { "조치 필요": 0, "추적 중": opportunities.length, "보류": 0, "추적 종료": 0, "신규 입찰공고": 0, "미결정": 0 },
      action_reason_counts: { new_link: 0, candidate_pending: 0, merge_confirmation: 0, blocking_item: 0, hold_overdue: 0 },
    });
  });

  await page.route(/\/api\/opportunities\/\d+(\?|$)/, async (route) => {
    const id = Number(/\/api\/opportunities\/(\d+)/.exec(new URL(route.request().url()).pathname)?.[1] ?? 0);
    const item = opportunities.find((candidate) => candidate.id === id);
    if (!item) { await json(route, { detail: "사업기회를 찾을 수 없습니다" }, 404); return; }
    await json(route, item);
  });

  await page.route(/\/api\/opportunities\/\d+\/bid-delta$/, async (route) => {
    const id = Number(/\/api\/opportunities\/(\d+)\/bid-delta/.exec(new URL(route.request().url()).pathname)?.[1] ?? 0);
    const index = id - BASE_ID;
    const scenario = SCENARIOS[index];
    if (!scenario) { await json(route, { detail: "사업기회를 찾을 수 없습니다" }, 404); return; }
    if (scenario.lookup === "failed") {
      await json(route, { error: { code: "internal_error", message: "합성 실패", details: null }, request_id: null }, 500);
      return;
    }
    if (scenario.lookup === "slow") {
      await new Promise((resolve) => { setTimeout(resolve, options.slowMs ?? 30_000); });
    }
    await json(route, workspaceFor(index, scenario));
  });

  await page.route(/\/api\/opportunities\/\d+\/bid-delta\/comparisons\/[^/]+$/, async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const id = Number(/\/api\/opportunities\/(\d+)\//.exec(pathname)?.[1] ?? 0);
    const index = id - BASE_ID;
    const view = SCENARIOS[index] ? comparisonFor(index) : null;
    if (!view) { await json(route, { detail: "비교를 찾을 수 없습니다" }, 404); return; }
    await json(route, view);
  });

  // 공고 조건 요약(spec §9.1)과 조건만으로 한 최종 결정(spec §9.2). 현재 화면은
  // 아직 이 경로를 부르지 않지만(F1-F4에서 연결), 계약 형태의 최소 응답을 둔다.
  await page.route(/\/api\/opportunities\/\d+\/bid-conditions$/, async (route) => {
    const id = Number(/\/api\/opportunities\/(\d+)\//.exec(new URL(route.request().url()).pathname)?.[1] ?? 0);
    const index = id - BASE_ID;
    const item = opportunities.find((candidate) => candidate.id === id);
    const link = item?.links.find((entry) => entry.record_type === "bid_notice") ?? null;
    if (!item) { await json(route, { detail: "사업기회를 찾을 수 없습니다" }, 404); return; }
    await json(route, {
      opportunity_id: id,
      generated_at: "2026-09-07T06:00:00Z",
      latest_notice_id: link?.notice_id ?? null,
      latest_observation_sha256: link ? hex(BASE_ID + index, "e") : null,
      pre_spec: null,
      bid_notices: [],
      pre_spec_comparison: [],
      not_comparable: ["deadline_at"],
    });
  });

  await page.route(/\/api\/opportunities\/\d+\/final-decisions$/, async (route) => {
    const id = Number(/\/api\/opportunities\/(\d+)\//.exec(new URL(route.request().url()).pathname)?.[1] ?? 0);
    const body = route.request().postDataJSON() as Record<string, unknown>;
    await json(route, {
      schema_version: "bidops.bid-final-decision.v2",
      id: uuid(id, "n"),
      opportunity_id: id,
      sequence: 1,
      basis_kind: "notice_conditions",
      comparison_id: null,
      comparison_version: null,
      result_sha256: null,
      baseline_document_version_id: null,
      comparison_document_version_id: null,
      basis_notice_id: Number(body.expected_notice_id ?? 0),
      basis_observation_sha256: String(body.expected_observation_sha256 ?? ""),
      supersedes_final_decision_id: (body.supersedes_final_decision_id as string | null) ?? null,
      decision: body.decision === "go" ? "go" : "no_go",
      reason: String(body.reason ?? ""),
      claimed_name: "테스트 담당자",
      request_id: String(body.request_id ?? ""),
      created_at: "2026-09-07T06:05:00Z",
      currentness: "current",
      currentness_reasons: [],
    }, 201);
  });
}

export interface DecisionRaceTrace {
  posts: Array<{ body: Record<string, unknown>; headers: Record<string, string> }>;
  comparisonGets: number;
  /** 확인 창이 열린 뒤 서버 쪽 비교·결정이 새 스냅숏으로 바뀌는 순간. */
  bump: () => void;
}

const RACE_ID = 901;
const RACE_COMPARISON_ID = "77777777-7777-4777-8777-000000000901";
const OLD_SHA = "e".repeat(64);
const NEW_SHA = "f".repeat(64);
const SUPERSEDED_ID = "dddddddd-dddd-4ddd-8ddd-000000000901";

/**
 * 확인 창이 열려 있는 동안 비교 버전·결과 해시·대체 대상이 바뀌는 상황.
 *
 * 사람이 읽고 확인한 스냅숏이 그대로 저장되는지(그리고 화면이 최신 값을 몰래
 * 채워 넣지 않는지) 검사하기 위한 고정 입력이다. 실제 저장은 하지 않는다.
 */
export async function mockDecisionRace(page: Page): Promise<DecisionRaceTrace> {
  const trace: DecisionRaceTrace = { posts: [], comparisonGets: 0, bump: () => { bumped = true; } };
  let bumped = false;

  const baseline = inputRef(0, "baseline");
  const comparison = inputRef(0, "comparison");
  const newBaseline = { ...baseline, document_version_id: uuid(RACE_ID, "4"), document_version_version: 3 };
  const newComparison = { ...comparison, document_version_id: uuid(RACE_ID, "9"), document_version_version: 4 };

  const priorDecision = {
    schema_version: "bidops.bid-final-decision.v2",
    id: SUPERSEDED_ID,
    opportunity_id: RACE_ID,
    sequence: 1,
    basis_kind: "comparison",
    comparison_id: RACE_COMPARISON_ID,
    comparison_version: 3,
    result_sha256: NEW_SHA,
    baseline_document_version_id: newBaseline.document_version_id,
    comparison_document_version_id: newComparison.document_version_id,
    basis_notice_id: null,
    basis_observation_sha256: null,
    supersedes_final_decision_id: null,
    decision: "go",
    reason: "확인 창이 열린 뒤 다른 담당자가 저장한 결정",
    claimed_name: "다른 담당자",
    request_id: uuid(RACE_ID, "a"),
    created_at: "2026-09-07T05:00:00Z",
    currentness: "current",
    currentness_reasons: [],
  };

  const comparisonView = () => ({
    schema_version: "bidops.bid-delta-comparison.v1",
    id: RACE_COMPARISON_ID,
    opportunity_id: RACE_ID,
    sequence: 1,
    version: bumped ? 3 : 2,
    category_policy_version: "bid-delta-policy.v1",
    calculation_status: "completed",
    result_status: "changed",
    materiality: "material",
    baseline: bumped ? newBaseline : baseline,
    comparison: bumped ? newComparison : comparison,
    items: items(0, "changed"),
    attempts: [{
      id: uuid(RACE_ID, "1"),
      sequence: 1,
      status: "completed",
      started_at: "2026-09-05T04:01:00Z",
      completed_at: "2026-09-05T04:06:00Z",
      last_error_code: null,
    }],
    result_sha256: bumped ? NEW_SHA : OLD_SHA,
    last_error_code: null,
    created_at: "2026-09-05T04:00:00Z",
    started_at: "2026-09-05T04:01:00Z",
    completed_at: "2026-09-05T04:06:00Z",
    final_decisions: bumped ? [priorDecision] : [],
    latest_final_decision: bumped ? priorDecision : null,
    decision_currentness: bumped ? "current" : "unknown",
    currentness_reasons: [],
  });

  await page.route(/\/api\/opportunities\/901$/, async (route) => {
    await json(route, opportunityFor(0));
  });
  await page.route(/\/api\/opportunities\/901\/bid-delta$/, async (route) => {
    const view = comparisonView();
    await json(route, {
      schema_version: "bidops.bid-delta-workspace.v1",
      opportunity_id: RACE_ID,
      baseline_candidates: [view.baseline],
      comparison_candidates: [view.comparison],
      comparisons: [{
        id: view.id,
        sequence: view.sequence,
        version: view.version,
        category_policy_version: view.category_policy_version,
        calculation_status: view.calculation_status,
        result_status: view.result_status,
        materiality: view.materiality,
        baseline: view.baseline,
        comparison: view.comparison,
        result_sha256: view.result_sha256,
        created_at: view.created_at,
        started_at: view.started_at,
        completed_at: view.completed_at,
      }],
      latest_final_decision: view.latest_final_decision,
      decision_currentness: view.decision_currentness,
      currentness_reasons: view.currentness_reasons,
      generated_at: "2026-09-07T06:00:00Z",
    });
  });
  await page.route(/\/api\/opportunities\/901\/bid-delta\/comparisons\/[^/]+$/, async (route) => {
    trace.comparisonGets += 1;
    await json(route, comparisonView());
  });
  await page.route(/\/api\/opportunities\/901\/bid-delta\/comparisons\/[^/]+\/final-decisions$/, async (route) => {
    const request = route.request();
    trace.posts.push({ body: request.postDataJSON() as Record<string, unknown>, headers: request.headers() });
    // 서버는 오래된 fence를 스스로 거절한다. 화면이 최신 값으로 갈아 끼우지
    // 않았는지 보려면 이 거절이 그대로 보여야 한다.
    await json(route, {
      error: { code: "bid_delta_comparison_stale", message: "비교가 갱신되었습니다.", details: null },
      request_id: null,
    }, 409);
  });

  return trace;
}

export const RACE_COMPARISON = { id: RACE_COMPARISON_ID, oldSha: OLD_SHA, newSha: NEW_SHA, supersededId: SUPERSEDED_ID };

export interface WorkspaceRecoveryTrace {
  /** 실패로 응답한 횟수(react-query 기본 재시도 1회 포함). */
  failures: number;
  gets: number;
  /** 이 시점 이후의 조회는 성공한다. */
  recover: () => void;
}

/**
 * 사업기회 하나의 결정 상태(workspace) 조회만 실패했다가 회복되는 상황.
 *
 * `mockGoNoGo` 뒤에 등록해 그 사업기회 경로만 덮어쓴다. 실패한 것이 목록이
 * 아니라 이 행의 조회라는 점을 검사하기 위한 고정 입력이다.
 */
export async function mockWorkspaceRecovery(page: Page, index = 8): Promise<WorkspaceRecoveryTrace> {
  const trace: WorkspaceRecoveryTrace = { failures: 0, gets: 0, recover: () => { recovered = true; } };
  let recovered = false;
  const id = BASE_ID + index;
  const scenario: Scenario = { calculation: "completed", result: "changed", currentness: "unknown" };

  await page.route(new RegExp(`/api/opportunities/${id}/bid-delta$`), async (route) => {
    trace.gets += 1;
    if (!recovered) {
      trace.failures += 1;
      await json(route, {
        error: { code: "internal_error", message: "합성 실패", details: null },
        request_id: null,
      }, 503);
      return;
    }
    await json(route, workspaceFor(index, scenario));
  });
  await page.route(new RegExp(`/api/opportunities/${id}/bid-delta/comparisons/[^/]+$`), async (route) => {
    await json(route, comparisonFor(index, scenario));
  });

  return trace;
}
