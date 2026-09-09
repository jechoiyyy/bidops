import type { Page, Route } from "@playwright/test";

/**
 * 판정 기준 화면(회사 프로필·판정 정책·품질 게이트·검증 지표)의 고정 입력.
 *
 * 공유 `api-mock.ts`를 고치지 않고 이 spec만 쓰는 route override로 둔다. 값은 API
 * 계약 형태 그대로이며 **화면에 하드코딩하지 않는다**. 승인된 시안과 같은 정보
 * 밀도(절 5개·정책 3개·게이트 4개·지표 5개·회차 7개)를 만들어 시안 캡처와 같은
 * 자리에서 대조할 수 있게 한다.
 *
 * 모든 식별자·수치는 합성값이다. 실제 회사자료·정책 본문·판정 결과가 아니며,
 * 이 파일의 어떤 값도 운영 사실로 읽지 않는다. mutation은 가로챈 mock만 응답하고
 * 실제 API로 나가지 않는다.
 */

const PROFILE_DIGEST = "a".repeat(64);
const PROFILE_VERSION = `company-profile.sha256:${PROFILE_DIGEST}`;

export const POLICY_DRAFT = "screening-policy.v3.20260907";
export const POLICY_CANDIDATE = "screening-policy.v2.20260904";
export const POLICY_ACTIVE = "screening-policy.v1.20260901";
export const PROMPT_CANDIDATE = "screening-prompt.v2";
export const BINDABLE_EVALUATION = "evaluation-operational-4";
export const MISMATCHED_EVALUATION = "evaluation-prompt-mismatch-2";
export const COMPARISON_EVALUATION = "evaluation-comparison-3";

export const LONG_SECTION_TITLE =
  "공공 정보화·데이터 서비스 구축 및 운영에 필요한 사업·기술 역량과 외부 시스템 통합 수행 범위";

type ProfileStatus = "confirmed" | "inferred" | "unknown";

function item(sectionId: string, sectionNumber: string | null, key: string, label: string, status: ProfileStatus, value: unknown) {
  return { key, label, section_id: sectionId, section_number: sectionNumber, status, value };
}

/**
 * 절 트리. 계층이 있고 제목·항목 수가 절마다 다르며, 상태가 섞인 절·상태를 적지
 * 않은 절·구조화하지 못한 절이 함께 있다. `null`·빈 목록·빈 문자열을 모두 넣어
 * 화면이 셋을 다르게 적는지 본다.
 */
function sections(longTitle: boolean) {
  return [
    {
      id: "overview",
      number: "1",
      title: "기본 정보",
      heading: "1. 기본 정보",
      level: 2,
      state: "confirmed",
      status_counts: { confirmed: 2 },
      items: [
        item("overview", "1", "company_name", "회사명", "confirmed", "합성 주식회사"),
        item("overview", "1", "business_area", "사업 분야", "confirmed", "공공 정보화"),
      ],
      error_codes: [],
      children: [],
    },
    {
      id: "capability",
      number: "2",
      title: longTitle ? LONG_SECTION_TITLE : "사업·기술 역량",
      heading: "2. 사업·기술 역량",
      level: 2,
      state: "mixed",
      status_counts: { confirmed: 2, inferred: 1, unknown: 1 },
      items: [
        item("capability", "2", "ai_data", "AI·데이터", "confirmed", "데이터 수집·연계, 분석 서비스 구축"),
        item("capability", "2", "public_si", "공공 SI·통합관리", "confirmed", "행정 업무시스템 구축 및 통합"),
        item("capability", "2", "blockchain_did", "블록체인·DID", "inferred", "인증·증명 서비스와의 기술 연계"),
        item("capability", "2", "cloud_ops", "클라우드 운영", "unknown", null),
      ],
      error_codes: [],
      children: [
        {
          id: "capability.tools",
          number: "2.1",
          title: "보유 도구",
          heading: "2.1 보유 도구",
          level: 3,
          state: "inferred",
          status_counts: { inferred: 1, confirmed: 1 },
          items: [
            item("capability.tools", "2.1", "internal_frameworks", "사내 프레임워크", "inferred", []),
            item("capability.tools", "2.1", "licenses", "보유 라이선스", "confirmed", ""),
          ],
          error_codes: [],
          children: [],
        },
      ],
    },
    {
      id: "performance",
      number: "3",
      title: "수행 실적",
      heading: "3. 수행 실적",
      level: 2,
      state: "unrecorded",
      status_counts: {},
      items: [
        item("performance", "3", "recent_projects", "최근 실적", "confirmed", { count: 12, years: "2023~2026" }),
        item("performance", "3", "reference_letters", "인정 범위", "unknown", null),
      ],
      error_codes: [],
      children: [],
    },
    {
      id: "certification",
      number: "4",
      title: "자격·인증",
      heading: "4. 자격·인증",
      level: 2,
      state: "unknown",
      status_counts: { unknown: 2 },
      items: [
        item("certification", "4", "iso_27001", "ISO 27001", "unknown", null),
        item("certification", "4", "software_business", "소프트웨어사업자 신고", "unknown", null),
      ],
      // 이 절만 구조화에 실패했다. 나머지 절은 정상이다.
      error_codes: ["profile_section_unstructured"],
      children: [],
    },
    {
      id: "organization",
      number: "5",
      title: "조직·인력",
      heading: "5. 조직·인력",
      level: 2,
      state: "confirmed",
      status_counts: { confirmed: 1 },
      items: [item("organization", "5", "headcount", "인원", "confirmed", 48)],
      error_codes: [],
      children: [],
    },
  ];
}

function unknowns() {
  return {
    schema_version: "bidops.profile-projection.v1",
    profile_version: PROFILE_VERSION,
    profile_digest: PROFILE_DIGEST,
    items: [
      { key: "cloud_ops", label: "클라우드 운영", section_id: "capability", section_number: "2", section_title: "사업·기술 역량", status: "unknown", value: null, reference_count: 7, reference_status: "counted" },
      { key: "reference_letters", label: "인정 범위", section_id: "performance", section_number: "3", section_title: "수행 실적", status: "unknown", value: null, reference_count: 0, reference_status: "counted" },
      { key: "iso_27001", label: "ISO 27001", section_id: "certification", section_number: "4", section_title: "자격·인증", status: "unknown", value: null, reference_count: null, reference_status: "unavailable" },
      { key: "software_business", label: "소프트웨어사업자 신고", section_id: "certification", section_number: "4", section_title: "자격·인증", status: "unknown", value: null, reference_count: 2, reference_status: "counted" },
    ],
    total: 4,
    reference_fields: ["evidence.source", "evidence.fact", "verification.why"],
    error_codes: [],
  };
}

function policyBody(kind: string) {
  return {
    perspective_prompts: { technical_fit: `합성 ${kind} 관점 지시문`, experience_fit: "합성 실적 관점 지시문" },
    counterargument_prompt: { instruction: "합성 반론 지시문" },
    synthesis_prompt: { instruction: "합성 종합 지시문" },
    candidate_selection: { top_k: 20 },
    thresholds: { grade_cutoff: 0.62 },
  };
}

function policy(version: string, prompt: string, status: string, createdAt: string, digestSeed: string, gateResultId: string | null) {
  return {
    schema_version: "bidops.screening-policy.v1",
    policy_version: version,
    prompt_version: prompt,
    ...policyBody(version),
    content_digest: digestSeed.repeat(64),
    status,
    created_at: createdAt,
    created_by: "합성 담당자",
    activated_at: status === "active" ? "2026-09-01T10:00:00+09:00" : null,
    activated_by: status === "active" ? "합성 승인자" : null,
    quality_gate_result_id: gateResultId,
  };
}

function policies() {
  return {
    items: [
      policy(POLICY_DRAFT, "screening-prompt.v3", "draft", "2026-09-07T11:00:00+09:00", "d", null),
      policy(POLICY_CANDIDATE, PROMPT_CANDIDATE, "activation_candidate", "2026-09-04T14:30:00+09:00", "c", null),
      policy(POLICY_ACTIVE, "screening-prompt.v1", "active", "2026-09-01T09:10:00+09:00", "b", "evaluation-active-1"),
    ],
    total: 3,
    active_policy_version: POLICY_ACTIVE,
  };
}

function execution(id: string, status: string, completed: number, failure: number) {
  return {
    execution_id: id,
    status,
    trigger: "quality_gate",
    scope: "quality_sample",
    run_id: "run-0906-a",
    candidate_count: 40,
    completed_count: completed,
    failure_count: failure,
    queue_position: status === "대기" ? 2 : null,
    current_stage: status === "실행 중" ? "판정 생성" : null,
    current_notice_id: status === "실행 중" ? "notice-021" : null,
    error_summary: status === "실패" ? "합성 실패 요약" : null,
    heartbeat_at: "2026-09-06T09:00:00+09:00",
    published_run_id: status === "성공" ? "run-0906-a" : null,
    started_at: "2026-09-06T08:00:00+09:00",
    finished_at: status === "성공" ? "2026-09-06T09:00:00+09:00" : null,
    created_at: "2026-09-06T07:50:00+09:00",
    created_by: "합성 담당자",
  };
}

function metricsBody(pass: boolean, validReviews: number | null) {
  return {
    sample_count: 40,
    paired_valid_count: 38,
    grade_reproducibility: { numerator: pass ? 34 : 28, denominator: 38, percent: pass ? 89.47 : 73.68, status: pass ? "통과" : "미달" },
    evidence_validity: {
      numerator: validReviews ?? 0,
      denominator: 10,
      percent: validReviews === null ? null : (validReviews / 10) * 100,
      status: validReviews === null ? "미측정" : validReviews >= 10 ? "통과" : "보류",
      valid_review_count: validReviews,
      distinct_notice_review_count: validReviews,
      judgment_hold_count: 1,
      agreement: { numerator: 8, denominator: 10, percent: 80, status: "통과" },
      insufficient: { numerator: 1, denominator: 10, percent: 10, status: "통과" },
    },
    discrimination: {
      pass_a: { numerator: 6, denominator: 38, percent: 15.79, status: "통과" },
      pass_b: { numerator: 5, denominator: 38, percent: 13.16, status: "통과" },
    },
    excluded_notices: [{ notice_id: "notice-033", pass: "Pass B", reason: "합성 제외 사유 · 출력 형식 불일치" }],
  };
}

function evaluation(id: string, gateId: string, revision: number, status: string, valid: number | null, reasons: string[]) {
  return {
    evaluation_id: id,
    gate_id: gateId,
    revision,
    result_status: status,
    metrics: metricsBody(status === "통과", valid),
    reasons,
    valid_review_count: valid,
    distinct_notice_review_count: valid,
    created_at: `2026-09-0${Math.min(6, revision + 2)}T10:00:00+09:00`,
  };
}

interface GateSpec {
  gateId: string;
  purpose: "operational_approval" | "model_comparison";
  policyVersion: string;
  promptVersion: string;
  resultStatus: string;
  executionStatus: string;
  latestEvaluationId: string;
  validReviews: number | null;
}

const GATE_SPECS: GateSpec[] = [
  // 결합 가능한 유일한 게이트: 운영 승인 · 통과 · 완료 · 정책/프롬프트 일치.
  { gateId: "gate-operational-pass", purpose: "operational_approval", policyVersion: POLICY_CANDIDATE, promptVersion: PROMPT_CANDIDATE, resultStatus: "통과", executionStatus: "완료", latestEvaluationId: BINDABLE_EVALUATION, validReviews: 10 },
  // 정책은 같지만 프롬프트가 다르다. 서버도 거절하므로 화면 목록에도 오르지 않는다.
  { gateId: "gate-prompt-mismatch", purpose: "operational_approval", policyVersion: POLICY_CANDIDATE, promptVersion: "screening-prompt.v9", resultStatus: "통과", executionStatus: "완료", latestEvaluationId: MISMATCHED_EVALUATION, validReviews: 10 },
  // 운영 승인이지만 아직 보류다.
  { gateId: "gate-operational-held", purpose: "operational_approval", policyVersion: POLICY_CANDIDATE, promptVersion: PROMPT_CANDIDATE, resultStatus: "보류", executionStatus: "완료", latestEvaluationId: "evaluation-operational-3", validReviews: 7 },
  // 모델 비교는 수치가 통과여도 활성화 근거가 아니다.
  { gateId: "gate-model-comparison", purpose: "model_comparison", policyVersion: POLICY_ACTIVE, promptVersion: "screening-prompt.v1", resultStatus: "통과", executionStatus: "완료", latestEvaluationId: COMPARISON_EVALUATION, validReviews: null },
];

function gateSummary(spec: GateSpec) {
  return {
    gate_id: spec.gateId,
    purpose: spec.purpose,
    execution_status: spec.executionStatus,
    result_status: spec.resultStatus,
    baseline_run_id: "run-0904-a",
    sample_artifact_digest: "e".repeat(64),
    baseline_decisions_digest: "f".repeat(64),
    policy_version: spec.policyVersion,
    prompt_version: spec.promptVersion,
    model_name: "합성-모델:27b",
    model_digest: "sha256:0011223344556677",
    company_profile_version: PROFILE_VERSION,
    company_profile_digest: PROFILE_DIGEST,
    pass_a_execution_id: `${spec.gateId}-a`,
    pass_b_execution_id: `${spec.gateId}-b`,
    created_by: "합성 담당자",
    created_at: "2026-09-04T15:00:00+09:00",
    completed_at: spec.executionStatus === "완료" ? "2026-09-04T17:20:00+09:00" : null,
    latest_evaluation_id: spec.latestEvaluationId,
    metrics: metricsBody(spec.resultStatus === "통과", spec.validReviews),
    reasons: spec.resultStatus === "보류" ? ["합성 사유 · 유효 리뷰 3건 부족"] : [],
  };
}

function gateDetail(spec: GateSpec) {
  return {
    ...gateSummary(spec),
    pass_a: execution(`${spec.gateId}-a`, "성공", 40, 0),
    pass_b: execution(`${spec.gateId}-b`, spec.resultStatus === "보류" ? "부분 성공" : "성공", 39, 1),
    evaluations: [
      evaluation(`${spec.gateId}-eval-1`, spec.gateId, 1, "미측정", 0, []),
      evaluation(`${spec.gateId}-eval-2`, spec.gateId, 2, "보류", 4, ["합성 사유 · 유효 리뷰 부족"]),
      evaluation(spec.latestEvaluationId, spec.gateId, 3, spec.resultStatus, spec.validReviews, spec.resultStatus === "보류" ? ["합성 사유 · 유효 리뷰 3건 부족"] : []),
    ],
    reviews: [
      { review_id: 1, gate_id: spec.gateId, execution_id: `${spec.gateId}-a`, notice_id: "notice-031", decision_digest: "1".repeat(64), reviewer: "합성 검토자", evidence_judgment: "동의", note: null, created_at: "2026-09-05T09:00:00+09:00", updated_at: "2026-09-05T09:00:00+09:00" },
      { review_id: 2, gate_id: spec.gateId, execution_id: `${spec.gateId}-a`, notice_id: "notice-076", decision_digest: "2".repeat(64), reviewer: "합성 검토자", evidence_judgment: "판단 보류", note: "합성 메모", created_at: "2026-09-05T10:00:00+09:00", updated_at: "2026-09-05T10:00:00+09:00" },
    ],
  };
}

function runs() {
  // 회차 7개. 최근 5개만 지표를 조회한다는 경계를 볼 수 있게 조회 범위보다 많다.
  return {
    items: Array.from({ length: 7 }, (_, index) => {
      const day = 6 - index;
      return {
        kind: "notices",
        run_id: `run-090${day}-a`,
        window_from: `2026-09-0${Math.max(1, day - 2)}`,
        window_to: `2026-09-0${day}`,
        timezone: "Asia/Seoul",
        generated_at: `2026-09-0${day}T09:00:00+09:00`,
        screening_basis: "합성 기준",
        status: index === 0 ? "완료" : "완료",
        superseded_by: null,
        counts: { notices: 120, candidates: 40, judgments: index === 6 ? 0 : 38, reviews: 12 },
      };
    }),
    total: 7,
  };
}

function metric(key: string, label: string, percentage: number | null, status: string, threshold: unknown, reason: string | null, numerator: number | null, denominator: number | null) {
  return {
    key,
    label,
    value: percentage === null ? null : percentage / 100,
    percentage,
    threshold,
    meets_threshold: percentage === null ? null : status === "pass",
    status,
    basis: { numerator, denominator, detail: { repeated_notice_keys: 0, sampled_notices: denominator } },
    reason,
  };
}

function validationMetrics(runId: string, degraded: boolean) {
  return {
    run_id: runId,
    metrics: [
      metric("evidence_link_rate", "근거 연결률", degraded ? 96.7 : 98.3, "pass", 0.95, null, 118, 120),
      metric("human_agreement_rate", "사람 판정 일치율", null, "not_measurable", 0.8, "담당자 리뷰가 기준 수에 미치지 못해 계산할 수 없습니다.", null, 12),
      metric("output_format_rate", "출력 형식 준수율", 100, "pass", 1, null, 120, 120),
      metric("grade_readiness_mixing_rate", "등급·준비 상태 혼동률", 0, "measured", null, "사전 확정 임계값이 없어 진단 지표로만 씁니다.", 0, 120),
      metric("audit_sample_miss_rate", "감사 표본 누락률", null, "not_measurable", null, "감사 표본 분모를 확인할 수 없습니다.", null, null),
    ],
  };
}

export interface CriteriaMockOptions {
  /** 프로필 응답을 깨뜨린다: 상태·미확인 수를 0으로 확정하지 않는지 본다. */
  profile?: "ok" | "invalid" | "read-error";
  /** 지표 회차 하나만 실패시킨다: 나머지 회차 값이 남는지 본다. */
  metricsFailures?: string[];
  /** 선택한 게이트 상세만 실패시킨다: 게이트 없음으로 접히지 않는지 본다. */
  gateDetailError?: string;
  /** 정책 mutation의 응답 상태. 409면 초안이 남아야 한다. */
  policyMutationStatus?: number;
  /** 긴 한글 절 제목으로 바꾼다. */
  longTitle?: boolean;
  /** 조회를 늦춘다(ms). 로딩 상태 캡처용. */
  slowMs?: number;
  /**
   * 정책 후보 지정·활성화 응답을 붙잡아 둔다. `releasePolicyMutation()`을 부를
   * 때까지 요청이 끝나지 않으므로 "요청 중"의 화면 상태를 실제로 볼 수 있다.
   */
  deferPolicyMutation?: boolean;
}

export interface CriteriaMockCalls {
  policyCreate: unknown[];
  policyCandidate: { policyVersion: string; body: unknown; actor: string | undefined }[];
  policyActivate: { policyVersion: string; body: unknown; actor: string | undefined }[];
  gateCreate: unknown[];
  reviewUpsert: { gateId: string; noticeId: string; body: unknown }[];
  /** `deferPolicyMutation`으로 붙잡아 둔 응답을 내보낸다. */
  releasePolicyMutation: () => void;
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

/**
 * `**\/api\/**`를 가로챈다. 공유 mock을 먼저 등록한 뒤 이 함수를 부르면 판정 기준
 * 화면이 쓰는 경로만 이 고정 입력이 이긴다.
 */
export async function mockCriteria(page: Page, options: CriteriaMockOptions = {}): Promise<CriteriaMockCalls> {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  const calls: CriteriaMockCalls = {
    policyCreate: [], policyCandidate: [], policyActivate: [], gateCreate: [], reviewUpsert: [],
    releasePolicyMutation: () => release(),
  };
  const mutationStatus = options.policyMutationStatus ?? 200;

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (options.slowMs) await new Promise((resolve) => setTimeout(resolve, options.slowMs));

    if (path === "/api/profile/sections") {
      if (options.profile === "read-error") { await json(route, { detail: "합성 읽기 실패" }, 500); return; }
      await json(route, {
        schema_version: "bidops.profile-projection.v1",
        profile_version: PROFILE_VERSION,
        profile_digest: PROFILE_DIGEST,
        sections: options.profile === "invalid" ? [] : sections(Boolean(options.longTitle)),
        status_counts: options.profile === "invalid" ? {} : { confirmed: 6, inferred: 2, unknown: 4 },
        error_codes: options.profile === "invalid" ? ["profile_yaml_invalid"] : [],
      });
      return;
    }
    if (path === "/api/profile/unknowns") { await json(route, unknowns()); return; }
    if (path === "/api/policies" && method === "GET") { await json(route, policies()); return; }
    if (path === "/api/policies" && method === "POST") {
      calls.policyCreate.push(route.request().postDataJSON());
      if (mutationStatus !== 200) { await json(route, { detail: "합성 충돌" }, mutationStatus); return; }
      const body = route.request().postDataJSON() as { policy_version: string; prompt_version: string };
      await json(route, policy(body.policy_version, body.prompt_version, "draft", "2026-09-07T12:00:00+09:00", "9", null), 201);
      return;
    }
    const candidateMatch = path.match(/^\/api\/policies\/(.+)\/candidate$/);
    if (candidateMatch && method === "POST") {
      calls.policyCandidate.push({
        policyVersion: decodeURIComponent(candidateMatch[1]),
        body: route.request().postDataJSON(),
        actor: route.request().headers()["x-bidops-actor-name"],
      });
      if (options.deferPolicyMutation) await held;
      if (mutationStatus !== 200) { await json(route, { detail: "합성 충돌" }, mutationStatus); return; }
      await json(route, policy(POLICY_DRAFT, "screening-prompt.v3", "activation_candidate", "2026-09-07T11:00:00+09:00", "d", null));
      return;
    }
    const activateMatch = path.match(/^\/api\/policies\/(.+)\/activate$/);
    if (activateMatch && method === "POST") {
      calls.policyActivate.push({
        policyVersion: decodeURIComponent(activateMatch[1]),
        body: route.request().postDataJSON(),
        actor: route.request().headers()["x-bidops-actor-name"],
      });
      if (options.deferPolicyMutation) await held;
      if (mutationStatus !== 200) { await json(route, { detail: "합성 충돌" }, mutationStatus); return; }
      await json(route, {
        policy: policy(POLICY_CANDIDATE, PROMPT_CANDIDATE, "active", "2026-09-04T14:30:00+09:00", "c", BINDABLE_EVALUATION),
        previous_active_policy_version: POLICY_ACTIVE,
        quality_gate_result_id: BINDABLE_EVALUATION,
        activation_status: "activated",
        activated_at: "2026-09-07T13:00:00+09:00",
      });
      return;
    }
    if (path === "/api/quality-gates" && method === "GET") {
      const purpose = url.searchParams.get("purpose");
      const items = GATE_SPECS.filter((spec) => !purpose || spec.purpose === purpose).map(gateSummary);
      await json(route, { items, total: items.length, limit: 100, offset: 0 });
      return;
    }
    if (path === "/api/quality-gates" && method === "POST") {
      calls.gateCreate.push(route.request().postDataJSON());
      await json(route, gateSummary(GATE_SPECS[0]), 201);
      return;
    }
    const reviewMatch = path.match(/^\/api\/quality-gates\/([^/]+)\/reviews\/([^/]+)$/);
    if (reviewMatch && method === "PUT") {
      calls.reviewUpsert.push({
        gateId: decodeURIComponent(reviewMatch[1]),
        noticeId: decodeURIComponent(reviewMatch[2]),
        body: route.request().postDataJSON(),
      });
      if (mutationStatus !== 200) { await json(route, { detail: "합성 충돌" }, mutationStatus); return; }
      await json(route, gateDetail(GATE_SPECS[0]));
      return;
    }
    const gateMatch = path.match(/^\/api\/quality-gates\/([^/]+)$/);
    if (gateMatch && method === "GET") {
      const gateId = decodeURIComponent(gateMatch[1]);
      if (options.gateDetailError === gateId) { await json(route, { detail: "합성 상세 조회 실패" }, 500); return; }
      const spec = GATE_SPECS.find((item) => item.gateId === gateId);
      if (!spec) { await json(route, { detail: "없음" }, 404); return; }
      await json(route, gateDetail(spec));
      return;
    }
    if (path === "/api/runs") { await json(route, runs()); return; }
    if (path === "/api/metrics/validation") {
      const runId = url.searchParams.get("run_id") ?? "";
      if ((options.metricsFailures ?? []).includes(runId)) { await json(route, { detail: "합성 지표 조회 실패" }, 500); return; }
      await json(route, validationMetrics(runId, runId !== "run-0906-a"));
      return;
    }
    await route.fallback();
  });

  return calls;
}
