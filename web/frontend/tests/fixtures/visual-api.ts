/**
 * Deterministic runtime fixtures used by visual coverage for T11–T13.
 *
 * The original fixture is intentionally kept as a capture of the legacy API.
 * These responses live separately because the runtime screens have several
 * immutable state projections (for example, 9/10 versus 10/10 reviews and
 * schedule catch-up/skip records) that are easier to audit here.
 */

export const RUN_ID = "20260817-20260823--20260824T090927.138116Z";
export const DERIVED_RUN_ID = "20260824-20260824--20260825T070000.000000Z";

const MODEL_DIGEST = "sha256:model-20260825-qwen";
const PROFILE_CURRENT = "company-profile.sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const PROFILE_BASELINE = "company-profile.sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const POLICY_ACTIVE = "screening-policy.v1.20260825";
const POLICY_CANDIDATE = "screening-policy.v1.20260826";
const ACTIVE_GATE_EVALUATION = "gateeval-11111111111111111111111111111111";
const CANDIDATE_GATE_EVALUATION = "gateeval-22222222222222222222222222222222";

function metric(
  numerator: number,
  denominator: number,
  percent: number,
  status = "통과",
  reason = "고정 표본에서 결정적으로 계산됨",
): Record<string, unknown> {
  return { numerator, denominator, percent, status, reason };
}

const operationalMetrics: Record<string, unknown> = {
  sample_count: 40,
  paired_valid_count: 40,
  grade_reproducibility: metric(36, 40, 90),
  perspective_reproducibility: {
    "기술 적합성": metric(38, 40, 95),
    "실적 정합성": metric(37, 40, 92.5),
    "공공 SI 적합성": metric(39, 40, 97.5),
    "사업성·자격 제약": metric(35, 40, 87.5),
    "전략 부합": metric(36, 40, 90),
  },
  perspective_mismatch_concentration: metric(2, 40, 5),
  discrimination: {
    pass_a: metric(6, 40, 15),
    pass_b: metric(7, 40, 17.5),
  },
  evidence_validity: {
    ...metric(8, 10, 80),
    valid_review_count: 10,
    distinct_notice_review_count: 10,
    judgment_hold_count: 0,
  },
  information_sufficiency: {
    pass_a: metric(34, 40, 85),
    pass_b: metric(33, 40, 82.5),
  },
  perspective_split: {
    pass_a: metric(24, 40, 60),
    pass_b: metric(23, 40, 57.5),
  },
  two_axis_mixing: {
    pass_a: metric(1, 40, 2.5),
    pass_b: metric(1, 40, 2.5),
  },
  counterargument_reflection: {
    pass_a: metric(32, 40, 80),
    pass_b: metric(31, 40, 77.5),
  },
  claude_alignment: {
    grade: metric(33, 40, 82.5),
    perspectives: {
      "기술 적합성": metric(35, 40, 87.5),
      "실적 정합성": metric(34, 40, 85),
      "공공 SI 적합성": metric(36, 40, 90),
      "사업성·자격 제약": metric(32, 40, 80),
      "전략 부합": metric(33, 40, 82.5),
    },
  },
  excluded_notices: [
    { notice_id: "notice-031", pass: "Pass B", reason: "모델 출력 잘림으로 사람 검토 대기" },
  ],
};

const nineOfTenMetrics: Record<string, unknown> = {
  ...operationalMetrics,
  evidence_validity: {
    ...operationalMetrics.evidence_validity as Record<string, unknown>,
    valid_review_count: 9,
    distinct_notice_review_count: 9,
    status: "보류",
    reason: "유효 리뷰와 서로 다른 공고가 각각 10건에 도달하지 않음",
  },
};

function screeningExecution(
  executionId: string,
  status: "대기" | "실행 중" | "성공" | "부분 성공" | "실패",
  values: {
    completed: number;
    failures: number;
    publishedRunId?: string | null;
    currentNoticeId?: string | null;
    currentStage?: string | null;
    queuePosition?: number | null;
    errorSummary?: string | null;
  },
): Record<string, unknown> {
  const terminal = status === "성공" || status === "부분 성공" || status === "실패";
  return {
    queue_no: executionId === "scr-progress" ? 41 : executionId === "scr-partial" ? 40 : executionId === "scr-failure" ? 39 : 38,
    execution_id: executionId,
    trigger: "manual_run",
    source_run_id: RUN_ID,
    scope: "full_run",
    notice_id: null,
    status,
    requested_by: "김운영",
    policy_version: POLICY_ACTIVE,
    prompt_version: "screening-prompt.v1",
    model_name: "qwen3.8:27b",
    model_digest: MODEL_DIGEST,
    company_profile_version: PROFILE_CURRENT,
    company_profile_digest: PROFILE_CURRENT.slice("company-profile.sha256:".length),
    input_artifact_digest: "sha256:screening-input-20260825",
    queued_at: "2026-08-25T08:30:00+09:00",
    started_at: "2026-08-25T08:31:00+09:00",
    finished_at: terminal ? "2026-08-25T08:42:00+09:00" : null,
    heartbeat_at: "2026-08-25T08:41:30+09:00",
    stop_requested_at: null,
    stop_requested_by: null,
    stop_reason: null,
    candidate_count: 40,
    completed_count: values.completed,
    failure_count: values.failures,
    published_run_id: values.publishedRunId ?? null,
    error_summary: values.errorSummary ?? null,
    queue_position: values.queuePosition ?? null,
    current_notice_id: values.currentNoticeId ?? null,
    current_stage: values.currentStage ?? null,
    result_urls: {
      decisions: terminal ? `/api/screening/executions/${executionId}/artifacts/decisions` : null,
      failures: values.failures > 0 ? `/api/screening/executions/${executionId}/artifacts/failures` : null,
      telemetry: `/api/screening/executions/${executionId}/artifacts/telemetry`,
      screening_result: terminal && status !== "실패" ? `/api/screening/executions/${executionId}/artifacts/screening_result` : null,
      published_run: values.publishedRunId ? `/api/runs/${values.publishedRunId}` : null,
    },
  };
}

const progressExecution = screeningExecution("scr-progress", "실행 중", {
  completed: 17,
  failures: 1,
  currentNoticeId: "notice-017",
  currentStage: "전략 부합",
  queuePosition: null,
});
const partialExecution = screeningExecution("scr-partial", "부분 성공", {
  completed: 37,
  failures: 3,
  publishedRunId: DERIVED_RUN_ID,
});
const failedExecution = screeningExecution("scr-failure", "실패", {
  completed: 9,
  failures: 31,
  errorSummary: "전체 실행 공통 입력 검증이 실패하여 게시하지 않았습니다.",
});
const derivedExecution = screeningExecution("scr-derived", "성공", {
  completed: 40,
  failures: 0,
  publishedRunId: DERIVED_RUN_ID,
});

const attempts = [
  {
    attempt_id: 1701,
    execution_id: "scr-progress",
    notice_id: "notice-017",
    stage: "전략 부합",
    attempt_no: 1,
    status: "success",
    failure_type: null,
    done_reason: "stop sequence not requested",
    trace_id: "trace-017",
    span_id: "span-017",
    prompt_eval_count: 1840,
    eval_count: 312,
    prompt_eval_duration_ns: 420000000,
    eval_duration_ns: 1800000000,
    load_duration_ns: 700000000,
    total_duration_ns: 2920000000,
    started_at: "2026-08-25T08:41:00+09:00",
    finished_at: "2026-08-25T08:41:04+09:00",
    error_summary: null,
  },
];

const failureItems = [
  {
    notice_id: "notice-031",
    failed_stage: "종합 판정",
    failure_type: "truncated_output",
    last_attempt_at: "2026-08-25T08:40:10+09:00",
    retry_count: 1,
    status: "사람 검토 대기",
    failure_context: null,
    trace_id: "trace-031",
    span_id: "span-031",
    error_summary: "모델 출력이 제한 길이에 도달하여 JSON 문서가 완결되지 않았습니다.",
  },
];

function screeningDetail(execution: Record<string, unknown>): Record<string, unknown> {
  const id = execution.execution_id as string;
  return {
    ...execution,
    attempts: id === "scr-progress" ? attempts : [],
    failures: id === "scr-progress" || id === "scr-partial" || id === "scr-failure" ? failureItems : [],
  };
}

const review = (id: number, noticeId: string, reviewer: string) => ({
  review_id: id,
  gate_id: "gate-operational",
  execution_id: "scr-operational-a",
  notice_id: noticeId,
  decision_digest: `sha256:decision-${String(id).padStart(3, "0")}`,
  reviewer,
  evidence_judgment: "동의",
  note: id === 1 ? "원문 위치와 판단 근거를 대조했습니다." : null,
  created_at: `2026-08-25T0${Math.min(id, 9)}:00:00+09:00`,
  updated_at: `2026-08-25T0${Math.min(id, 9)}:00:00+09:00`,
});

const operationalReviews = Array.from({ length: 10 }, (_, index) => review(index + 1, `notice-${String(index + 1).padStart(3, "0")}`, index === 0 ? "이검토" : "김운영"));
const comparisonReviews = operationalReviews.slice(0, 9).map((item) => ({ ...item, gate_id: "gate-model-comparison" }));

function gate(
  gateId: string,
  purpose: "model_comparison" | "operational_approval",
  policyVersion: string,
  latestEvaluationId: string,
  resultStatus: "통과" | "보류",
  validReviews: number,
  distinctReviews: number,
): Record<string, unknown> {
  const operational = purpose === "operational_approval";
  return {
    gate_id: gateId,
    purpose,
    execution_status: "완료",
    result_status: resultStatus,
    baseline_run_id: RUN_ID,
    sample_artifact_digest: "sha256:validation-set-40-notices",
    baseline_decisions_digest: "sha256:claude-decisions-40-notices",
    policy_version: policyVersion,
    prompt_version: "screening-prompt.v1",
    model_name: "qwen3.8:27b",
    model_digest: MODEL_DIGEST,
    company_profile_version: operational ? PROFILE_CURRENT : PROFILE_BASELINE,
    company_profile_digest: operational ? PROFILE_CURRENT.slice("company-profile.sha256:".length) : PROFILE_BASELINE.slice("company-profile.sha256:".length),
    pass_a_execution_id: operational ? "scr-operational-a" : "scr-comparison-a",
    pass_b_execution_id: operational ? "scr-operational-b" : "scr-comparison-b",
    created_by: "이검토",
    created_at: "2026-08-25T09:00:00+09:00",
    completed_at: "2026-08-25T09:30:00+09:00",
    latest_evaluation_id: latestEvaluationId,
    metrics: operational ? operationalMetrics : nineOfTenMetrics,
    reasons: purpose === "model_comparison" ? ["운영 활성화에 사용할 수 없는 모델 비교용 결과입니다."] : [],
  };
}

const operationalGate = gate("gate-operational", "operational_approval", POLICY_ACTIVE, ACTIVE_GATE_EVALUATION, "통과", 10, 10);
const candidateGate = gate("gate-operational-candidate", "operational_approval", POLICY_CANDIDATE, CANDIDATE_GATE_EVALUATION, "통과", 10, 10);
const comparisonGate = gate("gate-model-comparison", "model_comparison", POLICY_ACTIVE, "gateeval-33333333333333333333333333333333", "보류", 9, 9);

function gateDetail(base: Record<string, unknown>): Record<string, unknown> {
  const gateId = base.gate_id as string;
  const isComparison = gateId === "gate-model-comparison";
  const isCandidate = gateId === "gate-operational-candidate";
  const evaluationId = base.latest_evaluation_id as string;
  const currentReviews = isComparison ? comparisonReviews : operationalReviews;
  const evaluations = isComparison
    ? [
      { evaluation_id: "gateeval-33333333333333333333333333333333", gate_id: gateId, revision: 1, result_status: "보류", metrics: nineOfTenMetrics, reasons: ["유효 리뷰 9/10건으로 계산 불가"], valid_review_count: 9, distinct_notice_review_count: 9, created_at: "2026-08-25T09:20:00+09:00" },
    ]
    : [
      { evaluation_id: `${evaluationId.slice(0, -1)}0`, gate_id: gateId, revision: 1, result_status: "보류", metrics: nineOfTenMetrics, reasons: ["유효 리뷰 9/10건으로 계산 불가"], valid_review_count: 9, distinct_notice_review_count: 9, created_at: "2026-08-25T09:10:00+09:00" },
      { evaluation_id: evaluationId, gate_id: gateId, revision: 2, result_status: "통과", metrics: operationalMetrics, reasons: [], valid_review_count: 10, distinct_notice_review_count: 10, created_at: "2026-08-25T09:30:00+09:00" },
    ];
  const passA = screeningExecution(isComparison ? "scr-comparison-a" : isCandidate ? "scr-candidate-a" : "scr-operational-a", "성공", { completed: 40, failures: 0 });
  const passB = screeningExecution(isComparison ? "scr-comparison-b" : isCandidate ? "scr-candidate-b" : "scr-operational-b", "성공", { completed: 40, failures: 0 });
  return {
    ...base,
    pass_a: { ...passA, trigger: "quality_gate", scope: "quality_sample", source_run_id: RUN_ID },
    pass_b: { ...passB, trigger: "quality_gate", scope: "quality_sample", source_run_id: RUN_ID },
    evaluations,
    reviews: currentReviews.map((item) => ({ ...item, gate_id: gateId, execution_id: passA.execution_id })),
  };
}

function policy(
  policyVersion: string,
  status: "draft" | "activation_candidate" | "active",
  digest: string,
  gateEvaluation: string | null,
): Record<string, unknown> {
  return {
    schema_version: "bidops.screening-policy.v1",
    policy_version: policyVersion,
    prompt_version: "screening-prompt.v1",
    perspective_prompts: { "기술 적합성": { template: "기술 요구사항을 근거와 대조", input_fields: ["notice_json"], profile_sections: ["기술 역량"], output_schema: "perspective.v1" } },
    counterargument_prompt: { template: "반론을 검토" },
    synthesis_prompt: { template: "다섯 관점을 종합" },
    candidate_selection: { focus_axes: ["AI/데이터", "공공 SI"] },
    thresholds: { grade_reproducibility: 0.8, evidence_agreement: 0.7 },
    content_digest: digest,
    status,
    created_at: status === "active" ? "2026-08-25T08:00:00+09:00" : "2026-08-25T10:00:00+09:00",
    created_by: status === "active" ? "seed:screening" : "이검토",
    activated_at: status === "active" ? "2026-08-25T09:35:00+09:00" : null,
    activated_by: status === "active" ? "이검토" : null,
    quality_gate_result_id: gateEvaluation,
  };
}

const activePolicy = policy(POLICY_ACTIVE, "active", "sha256:policy-active-20260825", ACTIVE_GATE_EVALUATION);
const candidatePolicy = policy(POLICY_CANDIDATE, "activation_candidate", "sha256:policy-candidate-20260826", null);
const draftPolicy = policy("screening-policy.v1.draft", "draft", "sha256:policy-draft-20260826", null);

const scheduleExecutions = [
  {
    run_key: "20260825",
    run_id: DERIVED_RUN_ID,
    window_from: "2026-08-25",
    window_to: "2026-08-25",
    job_kind: "daily",
    status: "성공",
    execution_id: "sched-success",
    trigger: "schedule",
    duplicate_of_execution_id: null,
    recovery_of_execution_id: null,
    skip_reason: null,
    failure_reason: null,
    requested_by: "system:scheduler",
    started_at: "2026-08-25T02:00:00+09:00",
    finished_at: "2026-08-25T02:18:00+09:00",
    candidate_count: 40,
    result_count: 40,
    failure_count: 0,
    partial_artifact: false,
    policy_version: POLICY_ACTIVE,
    model_name: "qwen3.8:27b",
    model_digest: MODEL_DIGEST,
    prompt_version: "screening-prompt.v1",
    company_profile_version: PROFILE_CURRENT,
    company_profile_digest: PROFILE_CURRENT.slice("company-profile.sha256:".length),
  },
  {
    run_key: "20260824",
    run_id: null,
    window_from: "2026-08-24",
    window_to: "2026-08-24",
    job_kind: "daily",
    status: "부분 성공",
    execution_id: "sched-partial",
    trigger: "schedule",
    duplicate_of_execution_id: null,
    recovery_of_execution_id: null,
    skip_reason: null,
    failure_reason: "3건 모델 출력 검증 실패",
    requested_by: "system:scheduler",
    started_at: "2026-08-24T02:00:00+09:00",
    finished_at: "2026-08-24T02:20:00+09:00",
    candidate_count: 40,
    result_count: 37,
    failure_count: 3,
    partial_artifact: true,
    policy_version: POLICY_ACTIVE,
    model_name: "qwen3.8:27b",
    model_digest: MODEL_DIGEST,
    prompt_version: "screening-prompt.v1",
    company_profile_version: PROFILE_CURRENT,
    company_profile_digest: PROFILE_CURRENT.slice("company-profile.sha256:".length),
  },
  {
    run_key: "weekly:20260817-20260823",
    run_id: null,
    window_from: "2026-08-17",
    window_to: "2026-08-23",
    job_kind: "weekly",
    status: "실패",
    execution_id: "sched-failure",
    trigger: "manual",
    duplicate_of_execution_id: null,
    recovery_of_execution_id: null,
    skip_reason: null,
    failure_reason: "수집 API 시간 초과",
    requested_by: "이검토",
    started_at: "2026-08-24T06:00:00+09:00",
    finished_at: "2026-08-24T06:07:00+09:00",
    candidate_count: 0,
    result_count: 0,
    failure_count: 1,
    partial_artifact: false,
    policy_version: null,
    model_name: null,
    model_digest: null,
    prompt_version: null,
    company_profile_version: null,
    company_profile_digest: null,
  },
  {
    run_key: "20260823",
    run_id: null,
    window_from: "2026-08-23",
    window_to: "2026-08-23",
    job_kind: "daily",
    status: "건너뜀",
    execution_id: "sched-skipped",
    trigger: "schedule",
    duplicate_of_execution_id: "sched-success",
    recovery_of_execution_id: null,
    skip_reason: "동일 run_key 예약이 이미 존재합니다.",
    failure_reason: null,
    requested_by: "system:scheduler",
    started_at: null,
    finished_at: "2026-08-23T02:00:00+09:00",
    candidate_count: null,
    result_count: null,
    failure_count: null,
    partial_artifact: null,
    policy_version: null,
    model_name: null,
    model_digest: null,
    prompt_version: null,
    company_profile_version: null,
    company_profile_digest: null,
  },
  {
    run_key: "20260822",
    run_id: null,
    window_from: "2026-08-22",
    window_to: "2026-08-22",
    job_kind: "daily",
    status: "예약",
    execution_id: "sched-queued",
    trigger: "schedule",
    duplicate_of_execution_id: null,
    recovery_of_execution_id: null,
    skip_reason: null,
    failure_reason: null,
    requested_by: "system:scheduler",
    started_at: null,
    finished_at: null,
    candidate_count: null,
    result_count: null,
    failure_count: null,
    partial_artifact: null,
    policy_version: POLICY_ACTIVE,
    model_name: "qwen3.8:27b",
    model_digest: MODEL_DIGEST,
    prompt_version: "screening-prompt.v1",
    company_profile_version: PROFILE_CURRENT,
    company_profile_digest: PROFILE_CURRENT.slice("company-profile.sha256:".length),
  },
  {
    run_key: "20260821",
    run_id: null,
    window_from: "2026-08-21",
    window_to: "2026-08-21",
    job_kind: "daily",
    status: "실행 중",
    execution_id: "sched-running",
    trigger: "manual",
    duplicate_of_execution_id: null,
    recovery_of_execution_id: null,
    skip_reason: null,
    failure_reason: null,
    requested_by: "김운영",
    started_at: "2026-08-25T08:45:00+09:00",
    finished_at: null,
    candidate_count: 40,
    result_count: 12,
    failure_count: 1,
    partial_artifact: false,
    policy_version: POLICY_ACTIVE,
    model_name: "qwen3.8:27b",
    model_digest: MODEL_DIGEST,
    prompt_version: "screening-prompt.v1",
    company_profile_version: PROFILE_CURRENT,
    company_profile_digest: PROFILE_CURRENT.slice("company-profile.sha256:".length),
  },
];

export const visualResponses: Record<string, unknown> = {
  "/api/profile/snapshots": {
    items: [
      { version: PROFILE_CURRENT, digest: PROFILE_CURRENT.slice("company-profile.sha256:".length), source_kind: "working_tree", source_ref: "docs/reference/company-profile.md", created_at: "2026-08-25T08:00:00+09:00" },
      { version: PROFILE_BASELINE, digest: PROFILE_BASELINE.slice("company-profile.sha256:".length), source_kind: "git_blob", source_ref: "ee621835db934ddac944f7a07a986ed0b73ecc7a", created_at: "2026-08-25T08:00:00+09:00" },
    ],
    total: 2,
  },
  "/api/screening/executions": { items: [progressExecution, partialExecution, failedExecution, derivedExecution], total: 4, limit: 25, offset: 0 },
  "/api/quality-gates": { items: [operationalGate, comparisonGate, candidateGate], total: 3, limit: 100, offset: 0 },
  "/api/policies": { items: [activePolicy, candidatePolicy, draftPolicy], total: 3, active_policy_version: POLICY_ACTIVE },
  "/api/schedule/settings": { timezone: "Asia/Seoul", daily_time: "02:00", weekly_time: "06:00", prespec_enabled: false, updated_at: "2026-08-25T08:00:00+09:00", updated_by: "system:migration" },
  "/api/schedule/always-on": {
    configured_enabled: false,
    effective_enabled: false,
    environment_enabled: true,
    quality_gate_status: "통과",
    quality_gate_result_id: ACTIVE_GATE_EVALUATION,
    policy_version: POLICY_CANDIDATE,
    model_name: "qwen3.8:27b",
    model_digest: MODEL_DIGEST,
    prompt_version: "screening-prompt.v1",
    company_profile_version: PROFILE_CURRENT,
    company_profile_digest: PROFILE_CURRENT.slice("company-profile.sha256:".length),
    updated_at: "2026-08-25T08:00:00+09:00",
    updated_by: "system:migration",
    rejection_reason: "현재 active 정책(screening-policy.v1.20260825)과 승인 조합의 정책 버전이 일치하지 않습니다.",
  },
  "/api/schedule/executions": { items: scheduleExecutions, total: scheduleExecutions.length, limit: 100, offset: 0 },
  "/api/screening/executions/scr-progress": screeningDetail(progressExecution),
  "/api/screening/executions/scr-partial": screeningDetail(partialExecution),
  "/api/screening/executions/scr-failure": screeningDetail(failedExecution),
  "/api/screening/executions/scr-derived": screeningDetail(derivedExecution),
  "/api/quality-gates/gate-operational": gateDetail(operationalGate),
  "/api/quality-gates/gate-model-comparison": gateDetail(comparisonGate),
  "/api/quality-gates/gate-operational-candidate": gateDetail(candidateGate),
};

/** Return a new response for a known dynamic runtime path. */
export function getVisualResponse(pathname: string, pageUrl: string): unknown | undefined {
  // Focused `/runs?state=...` checks select one terminal projection before
  // falling back to the complete list used by the normal screenshot.
  if (pathname === "/api/screening/executions" && pageUrl.includes("state=partial")) {
    return { items: [partialExecution], total: 1, limit: 25, offset: 0 };
  }
  if (pathname === "/api/screening/executions" && pageUrl.includes("state=failure")) {
    return { items: [failedExecution], total: 1, limit: 25, offset: 0 };
  }
  if (pathname === "/api/screening/executions" && pageUrl.includes("state=derived")) {
    return { items: [derivedExecution], total: 1, limit: 25, offset: 0 };
  }

  // Keep the missing-evaluation path explicit: the review readiness indicator
  // must not turn an absent count into a real zero.
  if (pathname === "/api/quality-gates/gate-model-comparison" && pageUrl.includes("state=null-review")) {
    const detail = visualResponses["/api/quality-gates/gate-model-comparison"] as Record<string, unknown>;
    const evaluations = detail.evaluations as Array<Record<string, unknown>>;
    return {
      ...detail,
      evaluations: evaluations.map((evaluation) => ({
        ...evaluation,
        valid_review_count: null,
        distinct_notice_review_count: null,
      })),
    };
  }

  const exact = visualResponses[pathname];
  if (exact !== undefined) return exact;

  const screeningMatch = pathname.match(/^\/api\/screening\/executions\/(scr-[^/]+)$/);
  if (screeningMatch) return visualResponses[`/api/screening/executions/${screeningMatch[1]}`];

  const gateMatch = pathname.match(/^\/api\/quality-gates\/(gate-[^/]+)$/);
  if (gateMatch) return visualResponses[`/api/quality-gates/${gateMatch[1]}`];

  // RunsPage can navigate to the immutable derived run after a successful
  // full-run execution. Keep that navigation renderable without duplicating
  // the large legacy run fixture in the visual fixture file.
  if (/^\/api\/runs\/[^/]+$/.test(pathname)) return undefined;

  return undefined;
}
