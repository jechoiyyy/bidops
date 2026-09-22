import type { Page, Route } from "@playwright/test";
import { mockApi } from "./api-mock";
import { RUN_ID, DERIVED_RUN_ID } from "./fixtures/visual-api";

/**
 * 실행 상태 화면 전용 고정 입력.
 *
 * 공용 `mockApi`를 먼저 깔고 그 위에 이 화면이 필요한 경로만 덮어쓴다. 공용
 * mock 파일은 고치지 않는다(파일 소유 경계). 모든 값은 합성이며 실제 회사·공고·
 * 모델·평가와 무관하다. 쓰기는 가로챈 mock에만 도달하고 실제 API로 나가지
 * 않는다.
 */

export { RUN_ID, DERIVED_RUN_ID };

export interface RunStatusMockTrace {
  judgmentPosts: Array<{ runId: string; body: unknown }>;
  stopPosts: Array<{ executionId: string; body: unknown }>;
  pipelinePosts: Array<{ runId: string; stage: string; search: string; body: unknown }>;
  settingsPatches: Array<{ body: unknown }>;
  alwaysOnPuts: Array<{ body: unknown }>;
  scheduleExecutionPosts: Array<{ body: unknown }>;
  portalPosts: Array<{ body: unknown; headers: Record<string, string> }>;
  portalPatches: Array<{ portalId: string; body: unknown; headers: Record<string, string> }>;
  /** 실제로 나간 실행 목록 조회. N+1 회귀를 잡는다. */
  executionListGets: string[];
  executionDetailGets: string[];
}

export interface RunStatusMockOptions {
  /** 회차 목록을 비운다. */
  emptyRuns?: boolean;
  /** 발주계획 선별(C-2) 실행 목록 조회를 실패시킨다. */
  orderPlanScreeningListError?: boolean;
  /** 발주계획 선별 실행 **상세** 조회만 실패시킨다(목록은 그대로). */
  orderPlanScreeningDetailError?: boolean;
  /** 이 회차에 발주계획 선별 실행이 하나도 없는 상태로 둔다. */
  orderPlanScreeningEmpty?: boolean;
  /** 회차 목록 조회를 실패시킨다. */
  runsError?: boolean;
  /** 회차 상세 조회를 실패시킨다. */
  runDetailError?: boolean;
  /** 판정 실행 목록 조회를 실패시킨다. */
  executionsError?: boolean;
  /** 상시 운영 상태 조회를 실패시킨다. */
  alwaysOnError?: boolean;
  /** 정기 실행 이력 조회를 실패시킨다. */
  scheduleExecutionsError?: boolean;
  /** 기관 포털 목록 조회를 실패시킨다. */
  portalsError?: boolean;
  /** 첨부 확보 큐를 0건으로 만든다. */
  emptyAttachmentQueue?: boolean;
  /** 첨부 확보 큐 조회를 실패시킨다. */
  attachmentQueueError?: boolean;
  /** 조회를 열어 둔 채로 둔다(조회 중 상태 촬영용). */
  hangRuns?: boolean;
  /** 진행 중 실행 없이 종결 상태만 남긴다. */
  terminalOnly?: boolean;
  /** 실패 0건인 성공 실행 하나만 남긴다. */
  successOnly?: boolean;
  /** 중단 요청에 409를 돌려준다. */
  stopConflict?: boolean;
  /** 전량 판정 요청에 409를 돌려준다. */
  startConflict?: boolean;
  /** 상시 운영을 켤 수 있는 조합으로 바꾼다. */
  activationReady?: boolean;
  /** 아주 긴 한국어 제목·식별자를 쓴다. */
  longTitle?: boolean;
}

const ACTIVE_GATE_EVALUATION = "gateeval-11111111111111111111111111111111";
const POLICY_ACTIVE = "screening-policy.v1.20260825";

/** 회차 목록의 발주계획 회차. `발주계획 선별` 탭은 이 회차에서만 생긴다. */
export const ORDER_PLAN_RUN_ID = "20260810-20260816--20260817T090000.000000Z";
/** 운영 실행(성공). 측정 전용 실행보다 먼저 대기했다. */
export const C2_OPERATIONAL_EXECUTION_ID = "a2f4d7c1-0a61-4a07-8d2e-7f1d1d0a0001";
/** 품질 게이트 측정 전용 실행(부분 성공). 가장 최근이라 기본 선택이다. */
export const C2_MEASUREMENT_EXECUTION_ID = "a2f4d7c1-0a61-4a07-8d2e-7f1d1d0a0002";
export const C2_ARTIFACT_SHA256 = "3".repeat(64);
export const C2_MODEL_DIGEST = "7".repeat(64);

export const LONG_AGENCY = "광역행정서비스통합운영지원단 공공데이터기반정보화사업추진본부";
export const LONG_TITLE = "광역 행정서비스 및 공공데이터 통합관리체계 고도화를 위한 정보시스템 연계·운영 기반 구축 및 전환 지원 용역";

async function fulfillJson(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function headerRecord(route: Route): Record<string, string> {
  return route.request().headers();
}

function requestBody(route: Route): unknown {
  try {
    return route.request().postDataJSON();
  } catch {
    return null;
  }
}

/**
 * 회차 목록. 공용 fixture는 한 회차만 주므로 목록 좁히기와 파생 회차 이동을
 * 확인할 수 있도록 세 회차를 합성한다.
 */
function runSummaries(options: RunStatusMockOptions) {
  const base = {
    timezone: "Asia/Seoul",
    screening_basis: "합성 판정 기준",
    superseded_by: null,
    counts: { notices: 40, judgments: 40, reviews: 0, collection: { total: 2546, candidate_pool: 327, audit_pool: 2219 } },
  };
  return [
    {
      ...base,
      kind: "notices",
      run_id: options.longTitle ? `${RUN_ID}--${"긴회차식별자".repeat(6)}` : RUN_ID,
      window_from: "2026-08-17",
      window_to: "2026-08-23",
      generated_at: "2026-08-24T09:09:27.138116Z",
      status: "active",
    },
    {
      ...base,
      kind: "notices",
      run_id: DERIVED_RUN_ID,
      window_from: "2026-08-24",
      window_to: "2026-08-24",
      generated_at: "2026-08-25T07:00:00.000000Z",
      status: "active",
      counts: { notices: 40, judgments: 40, reviews: 0, collection: { total: 1200, candidate_pool: 120, audit_pool: 1080 } },
    },
    {
      ...base,
      kind: "order_plans",
      run_id: "20260810-20260816--20260817T090000.000000Z",
      window_from: "2026-08-10",
      window_to: "2026-08-16",
      generated_at: "2026-08-17T09:00:00.000000Z",
      status: "superseded",
      counts: { notices: 0, judgments: 0, reviews: 0, collection: { total: 800, candidate_pool: 90, audit_pool: 710 } },
    },
  ];
}

function attachmentQueueItem(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    notice_key: `notice-${id}`,
    run_id: RUN_ID,
    title: `합성 공고 ${id}`,
    agency: `합성기관 ${id}`,
    published_at: "2026-08-20T00:00:00Z",
    deadline_at: "2026-09-30T00:00:00Z",
    estimated_price: null,
    sample_role: "분석",
    sample_stratum: "A",
    collection_bucket: "candidate",
    grade: "검토 권장",
    readiness: "부분 확인 필요",
    focus: null,
    attachment_count: 0,
    attachment_status: "none",
    bid_no: `2026${id}`,
    matched_portal: null,
    search_url: null,
    portal_message: "이 기관에 등록된 조달시스템이 없습니다.",
    ...overrides,
  };
}

export async function installRunStatusMock(page: Page, options: RunStatusMockOptions = {}): Promise<RunStatusMockTrace> {
  const trace: RunStatusMockTrace = {
    judgmentPosts: [],
    stopPosts: [],
    pipelinePosts: [],
    settingsPatches: [],
    alwaysOnPuts: [],
    scheduleExecutionPosts: [],
    portalPosts: [],
    portalPatches: [],
    executionListGets: [],
    executionDetailGets: [],
  };
  await mockApi(page);
  // 상시 운영은 쓰기 뒤 읽기가 같은 값을 돌려줘야 한다. 통합 검증이 상세와
  // 요약이 함께 바뀌는지를 보므로 이 fixture가 상태를 들고 있는다.
  let alwaysOn = alwaysOnState(options);

  // 공용 fixture 위에 이 화면이 쓰는 경로만 덮어쓴다. 나중에 등록한 route가
  // 먼저 매칭되므로 나머지 응답은 그대로 남는다.
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    const method = route.request().method();

    if (pathname === "/api/runs" && method === "GET") {
      if (options.hangRuns) return; // 응답하지 않고 열어 둔다 — 조회 중 상태.
      if (options.runsError) { await fulfillJson(route, { detail: "합성 조회 실패" }, 503); return; }
      const items = options.emptyRuns ? [] : runSummaries(options);
      await fulfillJson(route, { items, total: items.length });
      return;
    }

    const runDetailMatch = pathname.match(/^\/api\/runs\/([^/]+)$/);
    if (runDetailMatch && method === "GET") {
      if (options.runDetailError) { await fulfillJson(route, { detail: "합성 조회 실패" }, 503); return; }
      const runId = decodeURIComponent(runDetailMatch[1]);
      const summary = runSummaries(options).find((run) => run.run_id === runId) ?? runSummaries(options)[0];
      await fulfillJson(route, {
        ...summary,
        run_id: runId,
        collection_scope: {
          window_from: summary.window_from,
          window_to: summary.window_to,
          timezone: "Asia/Seoul",
          business_area: "정보화",
          pre_spec_available: false,
          pre_spec_reason: "사전규격 수집 대상이 아닙니다.",
          focus_axes: ["공공 SI", "데이터"],
          performance_reference_count: 12,
        },
        pipeline: [
          { name: "collect_normalize", status: "complete", artifact: "normalized.json", script: "scripts/collect.py", execution_id: "pipe-1", started_at: "2026-08-24T09:00:00Z", finished_at: "2026-08-24T09:05:00Z", exit_code: 0, execution_allowed: true, message: null },
          { name: "sample", status: "complete", artifact: "sample.json", script: "scripts/sample.py", execution_id: "pipe-2", started_at: "2026-08-24T09:05:00Z", finished_at: "2026-08-24T09:06:00Z", exit_code: 0, execution_allowed: true, message: null },
          { name: "judgment", status: "running", artifact: null, script: null, execution_id: null, started_at: null, finished_at: null, exit_code: null, execution_allowed: false, message: "판정 실행으로만 진행합니다." },
          { name: "report", status: "not_available", artifact: null, script: "scripts/report.py", execution_id: null, started_at: null, finished_at: null, exit_code: null, execution_allowed: true, message: null },
        ],
        artifacts: [
          { name: "normalized.json", present: true, schema_version: "bidops.normalized.v1", expected_schema_version: "bidops.normalized.v1", valid: true, warnings: [] },
          { name: "screening-results.json", present: false, schema_version: null, expected_schema_version: "bidops.screening.v1", valid: null, warnings: [] },
          { name: "screening-failures.json", present: true, schema_version: "bidops.failures.v1", expected_schema_version: "bidops.failures.v1", valid: true, warnings: ["부분 산출물입니다."] },
        ],
        warning_counts: { partial_artifact: 1 },
      });
      return;
    }

    const pipelineMatch = pathname.match(/^\/api\/runs\/([^/]+)\/pipeline\/(collect|sample|report)$/);
    if (pipelineMatch && method === "POST") {
      trace.pipelinePosts.push({
        runId: decodeURIComponent(pipelineMatch[1]),
        stage: pipelineMatch[2],
        search: url.search,
        body: requestBody(route),
      });
      await fulfillJson(route, {
        execution_id: "pipe-new",
        source_run_id: decodeURIComponent(pipelineMatch[1]),
        result_run_id: null,
        stage: pipelineMatch[2],
        status: "pending",
        started_at: null,
        finished_at: null,
        exit_code: null,
        error: null,
        log_count: 0,
      }, 202);
      return;
    }

    const judgmentMatch = pathname.match(/^\/api\/runs\/([^/]+)\/pipeline\/judgment$/);
    if (judgmentMatch && method === "POST") {
      trace.judgmentPosts.push({ runId: decodeURIComponent(judgmentMatch[1]), body: requestBody(route) });
      if (options.startConflict) {
        await fulfillJson(route, { error: { code: "execution_conflict", message: "합성 충돌", details: null } }, 409);
        return;
      }
      await fulfillJson(route, screeningExecution("scr-new", "대기", { completed: 0, failures: 0, queuePosition: 1 }), 202);
      return;
    }

    if (pathname === "/api/screening/executions" && method === "GET") {
      trace.executionListGets.push(url.search);
      if (options.executionsError) { await fulfillJson(route, { detail: "합성 조회 실패" }, 503); return; }
      const items = executionList(options);
      const runId = url.searchParams.get("run_id");
      const scoped = runId ? items.filter((item) => item.source_run_id === runId) : items;
      await fulfillJson(route, {
        items: scoped,
        total: scoped.length,
        limit: Number(url.searchParams.get("limit") ?? 50),
        offset: Number(url.searchParams.get("offset") ?? 0),
      });
      return;
    }

    const stopMatch = pathname.match(/^\/api\/screening\/executions\/([^/]+)\/stop$/);
    if (stopMatch && method === "POST") {
      trace.stopPosts.push({ executionId: decodeURIComponent(stopMatch[1]), body: requestBody(route) });
      if (options.stopConflict) {
        await fulfillJson(route, { error: { code: "execution_already_terminal", message: "합성 충돌", details: null } }, 409);
        return;
      }
      await fulfillJson(route, screeningExecution(decodeURIComponent(stopMatch[1]), "중지 요청", { completed: 17, failures: 1 }));
      return;
    }

    const detailMatch = pathname.match(/^\/api\/screening\/executions\/([^/]+)$/);
    if (detailMatch && method === "GET") {
      const executionId = decodeURIComponent(detailMatch[1]);
      trace.executionDetailGets.push(executionId);
      const item = executionList(options).find((entry) => entry.execution_id === executionId)
        ?? screeningExecution(executionId, "실행 중", { completed: 17, failures: 1 });
      await fulfillJson(route, { ...item, attempts: attempts(executionId), failures: item.failure_count > 0 ? failures() : [] });
      return;
    }

    if (pathname === "/api/schedule/always-on") {
      if (method === "PUT") {
        const body = requestBody(route) as { enabled?: boolean; confirmed_by?: string } | null;
        trace.alwaysOnPuts.push({ body });
        const enabled = Boolean(body?.enabled);
        alwaysOn = {
          ...alwaysOn,
          configured_enabled: enabled,
          // 환경이 막고 있으면 설정을 켜도 실제 운영은 켜지지 않는다.
          effective_enabled: enabled && alwaysOn.environment_enabled,
          updated_by: body?.confirmed_by ?? alwaysOn.updated_by,
        };
        await fulfillJson(route, alwaysOn);
        return;
      }
      if (options.alwaysOnError) { await fulfillJson(route, { detail: "합성 조회 실패" }, 503); return; }
      await fulfillJson(route, alwaysOn);
      return;
    }

    if (pathname === "/api/schedule/settings" && method === "PATCH") {
      trace.settingsPatches.push({ body: requestBody(route) });
      await fulfillJson(route, {
        timezone: "Asia/Seoul",
        daily_time: "02:00",
        weekly_time: "06:00",
        prespec_enabled: false,
        updated_at: "2026-08-25T08:00:00+09:00",
        updated_by: "system:migration",
      });
      return;
    }

    if (pathname === "/api/schedule/executions") {
      if (method === "POST") {
        trace.scheduleExecutionPosts.push({ body: requestBody(route) });
        await fulfillJson(route, { detail: "합성 예약 결과" }, 202);
        return;
      }
      if (options.scheduleExecutionsError) { await fulfillJson(route, { detail: "합성 조회 실패" }, 503); return; }
      await route.fallback();
      return;
    }

    if (pathname === "/api/portals") {
      if (method === "POST") {
        trace.portalPosts.push({ body: requestBody(route), headers: headerRecord(route) });
        await fulfillJson(route, { id: 99, agency_pattern: "합성기관", system_name: "합성 조달시스템", search_url_template: "https://example.invalid/?q={bid_no}", enabled: true, note: null }, 201);
        return;
      }
      if (options.portalsError) { await fulfillJson(route, { detail: "합성 조회 실패" }, 503); return; }
      await fulfillJson(route, [
        { id: 1, agency_pattern: "합성기관 1", system_name: "합성 조달시스템 1", search_url_template: "https://example.invalid/?q={bid_no}", enabled: true, note: null },
      ]);
      return;
    }

    const portalPatchMatch = pathname.match(/^\/api\/portals\/(\d+)$/);
    if (portalPatchMatch && method === "PATCH") {
      trace.portalPatches.push({ portalId: portalPatchMatch[1], body: requestBody(route), headers: headerRecord(route) });
      await fulfillJson(route, { id: Number(portalPatchMatch[1]), agency_pattern: "합성기관 1", system_name: "합성 조달시스템 1", search_url_template: "https://example.invalid/?q={bid_no}", enabled: true, note: null });
      return;
    }

    // 발주계획 선별(C-2). 이 회차의 요청만 이 fixture가 맡고 나머지는 공용
    // mock으로 넘긴다 — 같은 mock을 쓰는 다른 spec의 응답을 바꾸지 않는다.
    if (pathname === "/api/order-plan-screening/executions" && method === "GET") {
      if (url.searchParams.get("source_run_id") !== ORDER_PLAN_RUN_ID) { await route.fallback(); return; }
      if (options.orderPlanScreeningListError) { await fulfillJson(route, { detail: "합성 조회 실패" }, 503); return; }
      const items = c2Executions(options);
      await fulfillJson(route, {
        schema_version: "execution-list-response.v2",
        producer: "screening-api",
        consumer: "human-review-client",
        items,
        total: items.length,
        limit: Number(url.searchParams.get("limit") ?? 50),
        offset: Number(url.searchParams.get("offset") ?? 0),
      });
      return;
    }

    const c2DetailMatch = pathname.match(/^\/api\/order-plan-screening\/executions\/([^/]+)$/);
    if (c2DetailMatch && method === "GET") {
      const executionId = decodeURIComponent(c2DetailMatch[1]);
      const execution = c2Executions(options).find((item) => item.execution_id === executionId);
      if (!execution) { await route.fallback(); return; }
      if (options.orderPlanScreeningDetailError) { await fulfillJson(route, { detail: "합성 조회 실패" }, 503); return; }
      await fulfillJson(route, {
        schema_version: "execution-detail-response.v2",
        producer: "screening-api",
        consumer: "human-review-client",
        ...execution,
        artifacts: c2Artifacts(executionId),
        attempts: c2Attempts(executionId),
      });
      return;
    }

    if (pathname === "/api/order-plans" && method === "GET") {
      if (url.searchParams.get("source_run_id") !== ORDER_PLAN_RUN_ID) { await route.fallback(); return; }
      const items = c2PlanItems();
      const limit = Number(url.searchParams.get("limit") ?? 50);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      await fulfillJson(route, {
        schema_version: "order-plan-list-response.v5",
        producer: "order-plan-review-api",
        consumer: "order-plan-review-client",
        scope: c2ListScope(options),
        items: items.slice(offset, offset + limit),
        total: items.length,
        limit,
        offset,
      });
      return;
    }

    if (pathname === "/api/attachments/queue" && method === "GET") {
      if (options.attachmentQueueError) { await fulfillJson(route, { detail: "합성 조회 실패" }, 503); return; }
      if (options.emptyAttachmentQueue) {
        await fulfillJson(route, { run_id: RUN_ID, total: 0, items: [] });
        return;
      }
      const items = [
        attachmentQueueItem(31, options.longTitle ? { title: LONG_TITLE, agency: LONG_AGENCY } : {}),
        attachmentQueueItem(76, {
          matched_portal: { id: 1, agency_pattern: "합성기관 76", system_name: "합성 조달시스템 1", search_url_template: "https://example.invalid/?q={bid_no}", enabled: true, note: null },
          search_url: "https://example.invalid/?q=202676",
          portal_message: "등록된 조달시스템 검색 주소입니다.",
        }),
        attachmentQueueItem(88, { attachment_count: 2, attachment_status: "g2b" }),
      ];
      await fulfillJson(route, { run_id: RUN_ID, total: items.length, items });
      return;
    }

    await route.fallback();
  });

  return trace;
}

function alwaysOnState(options: RunStatusMockOptions) {
  if (options.activationReady) {
    return {
      configured_enabled: false,
      effective_enabled: false,
      environment_enabled: true,
      quality_gate_status: "통과",
      quality_gate_result_id: ACTIVE_GATE_EVALUATION,
      policy_version: POLICY_ACTIVE,
      model_name: "합성-모델",
      model_digest: "sha256:합성모델",
      prompt_version: "screening-prompt.v1",
      company_profile_version: "company-profile.v1.20260825",
      company_profile_digest: "a".repeat(64),
      updated_at: "2026-08-25T08:00:00+09:00",
      updated_by: "system:migration",
      rejection_reason: null,
    };
  }
  return {
    configured_enabled: false,
    effective_enabled: false,
    environment_enabled: false,
    quality_gate_status: "보류",
    quality_gate_result_id: null,
    policy_version: null,
    model_name: null,
    model_digest: null,
    prompt_version: null,
    company_profile_version: null,
    company_profile_digest: null,
    updated_at: "2026-08-25T08:00:00+09:00",
    updated_by: "system:migration",
    rejection_reason: "합성 승인 조합 불일치로 상시 운영을 거부했습니다.",
  };
}

export function screeningExecution(
  executionId: string,
  status: string,
  values: {
    completed: number;
    failures: number;
    candidate?: number;
    publishedRunId?: string | null;
    currentNoticeId?: string | null;
    currentStage?: string | null;
    queuePosition?: number | null;
    errorSummary?: string | null;
    queueNo?: number;
    sourceRunId?: string;
  },
) {
  const terminal = ["성공", "부분 성공", "실패", "중단됨"].includes(status);
  return {
    queue_no: values.queueNo ?? 40,
    execution_id: executionId,
    trigger: "manual_run",
    source_run_id: values.sourceRunId ?? RUN_ID,
    scope: "full_run",
    notice_id: null,
    status,
    requested_by: "합성 담당자",
    policy_version: POLICY_ACTIVE,
    prompt_version: "screening-prompt.v1",
    model_name: "합성-모델",
    model_digest: "sha256:합성모델",
    company_profile_version: "company-profile.v1.20260825",
    company_profile_digest: "a".repeat(64),
    input_artifact_digest: "sha256:합성입력",
    queued_at: "2026-08-25T08:30:00+09:00",
    started_at: "2026-08-25T08:31:00+09:00",
    finished_at: terminal ? "2026-08-25T08:42:00+09:00" : null,
    heartbeat_at: "2026-08-25T08:41:30+09:00",
    stop_requested_at: null,
    stop_requested_by: null,
    stop_reason: null,
    candidate_count: values.candidate ?? 40,
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

function executionList(options: RunStatusMockOptions) {
  if (options.successOnly) {
    return [screeningExecution("scr-success", "성공", { completed: 40, failures: 0, queueNo: 44, publishedRunId: DERIVED_RUN_ID })];
  }
  if (options.terminalOnly) {
    return [
      screeningExecution("scr-partial", "부분 성공", { completed: 37, failures: 3, queueNo: 43, publishedRunId: DERIVED_RUN_ID }),
      screeningExecution("scr-failure", "실패", { completed: 9, failures: 31, queueNo: 42, errorSummary: "합성 입력 검증이 실패하여 게시하지 않았습니다." }),
    ];
  }
  return [
    screeningExecution("scr-progress", "실행 중", { completed: 17, failures: 1, queueNo: 45, currentNoticeId: "notice-017", currentStage: "전략 부합" }),
    screeningExecution("scr-partial", "부분 성공", { completed: 37, failures: 3, queueNo: 43, publishedRunId: DERIVED_RUN_ID }),
    screeningExecution("scr-derived", "성공", { completed: 40, failures: 0, queueNo: 41, sourceRunId: DERIVED_RUN_ID, publishedRunId: null }),
  ];
}

// ── 발주계획 선별(C-2) ──────────────────────────────────────────────────
// 실제 계약(`lib/types.ts`의 `OrderPlanScreeningExecution*`·`OrderPlanListItem`)과
// 공용 mock(`api-mock.ts`의 C-2 fixture)이 내려주는 shape에서 그대로 파생했다.
// 값만 이 회차에 맞게 합성한다.

const c2Sha = (letter: string): string => (letter.charCodeAt(0) % 16).toString(16).repeat(64);

const C2_POLICY_VERSION = "c2-order-plan-screening-v4";

function c2Counts(overrides: Record<string, number> = {}) {
  return {
    candidate_count: 412,
    completed_count: 410,
    failure_count: 2,
    stage1_selected_count: 80,
    stage1_filtered_out_count: 330,
    stage1_failed_count: 2,
    stage2_relevant_count: 29,
    stage2_not_relevant_count: 38,
    stage2_uncertain_count: 13,
    stage2_failed_count: 2,
    stage2_rejected_count: 0,
    human_review_count: 4,
    ...overrides,
  };
}

/** 운영 실행 하나와 측정 전용 실행 하나. 회차 하나에 실행이 여럿인 상태다. */
function c2Executions(options: RunStatusMockOptions) {
  if (options.orderPlanScreeningEmpty) return [];
  const base = {
    source_run_id: ORDER_PLAN_RUN_ID,
    policy_version: C2_POLICY_VERSION,
    requested_by: "합성 운영자",
    execution_allowed: true,
    population_count: 412,
    population_sha256: c2Sha("p"),
    policy_sha256: c2Sha("a"),
    binding_sha256: c2Sha("b"),
    stage1_binding_version: "bm25-binding.v3",
    stage1_binding_sha256: c2Sha("c"),
    stage2_binding_version: "qwen-binding.v5",
    stage2_binding_sha256: c2Sha("d"),
  };
  return [
    {
      ...base,
      execution_id: C2_OPERATIONAL_EXECUTION_ID,
      request_id: "b2f4d7c1-0a61-4b07-8d2e-7f1d1d0a0001",
      status: "성공",
      purpose: "operational",
      counts: c2Counts({ failure_count: 0, stage1_failed_count: 0, stage2_failed_count: 0, completed_count: 412 }),
      partial_artifact: false,
      error_code: null,
      queued_at: "2026-08-17T07:00:00Z",
      started_at: "2026-08-17T07:00:05Z",
      heartbeat_at: "2026-08-17T07:41:00Z",
      finished_at: "2026-08-17T07:42:00Z",
    },
    {
      ...base,
      execution_id: C2_MEASUREMENT_EXECUTION_ID,
      request_id: "b2f4d7c1-0a61-4b07-8d2e-7f1d1d0a0002",
      status: "부분 성공",
      purpose: "gate_measurement",
      counts: c2Counts(),
      partial_artifact: true,
      error_code: "batch_schema_violation",
      queued_at: "2026-08-17T09:00:00Z",
      started_at: "2026-08-17T09:00:04Z",
      heartbeat_at: "2026-08-17T09:14:00Z",
      finished_at: "2026-08-17T09:15:00Z",
    },
  ];
}

function c2Attempts(executionId: string) {
  const shared = {
    model_name: "qwen3.8-27B",
    model_digest: C2_MODEL_DIGEST,
    prompt_version: "c2-prompt.v4",
    prompt_sha256: c2Sha("r"),
    company_profile_version: "company-profile.v1.20260825",
    company_profile_sha256: c2Sha("s"),
    generation_config_sha256: c2Sha("t"),
  };
  if (executionId === C2_OPERATIONAL_EXECUTION_ID) {
    return [{
      ...shared,
      attempt_id: "c2f4d7c1-0a61-4e07-8d2e-000000000001",
      batch_id: "batch-20260817-01",
      sequence: 1,
      attempt_no: 1,
      attempt_status: "success",
      failure_type: null,
      failure_code: null,
      input_tokens: 48210,
      cached_input_tokens: 12004,
      output_tokens: 3911,
      total_tokens: 64125,
      duration_ms: 81402,
      started_at: "2026-08-17T07:01:00Z",
      finished_at: "2026-08-17T07:02:21Z",
    }];
  }
  return [
    {
      ...shared,
      attempt_id: "c2f4d7c1-0a61-4e07-8d2e-000000000002",
      batch_id: "batch-20260817-02",
      sequence: 2,
      attempt_no: 1,
      attempt_status: "success",
      failure_type: null,
      failure_code: null,
      input_tokens: 47100,
      cached_input_tokens: 9800,
      output_tokens: 3010,
      total_tokens: 59910,
      duration_ms: 74010,
      started_at: "2026-08-17T09:01:00Z",
      finished_at: "2026-08-17T09:02:14Z",
    },
    {
      ...shared,
      attempt_id: "c2f4d7c1-0a61-4e07-8d2e-000000000003",
      batch_id: "batch-20260817-03",
      sequence: 3,
      attempt_no: 2,
      attempt_status: "failed",
      failure_type: "timeout",
      failure_code: "model_timeout",
      input_tokens: 47880,
      cached_input_tokens: 0,
      // 실패한 시도는 출력 토큰을 남기지 않는다. 0이 아니라 미측정이다.
      output_tokens: null,
      total_tokens: null,
      duration_ms: 120000,
      started_at: "2026-08-17T09:10:00Z",
      finished_at: "2026-08-17T09:12:00Z",
    },
  ];
}

function c2Artifacts(executionId: string) {
  const partial = executionId === C2_MEASUREMENT_EXECUTION_ID;
  return [
    {
      kind: "screening_input",
      artifact_schema_version: "screening-input.v1",
      artifact_producer: "screening-api",
      artifact_consumer: "screening-worker",
      sha256: C2_ARTIFACT_SHA256,
      byte_count: 128000,
      object_version: "v1",
      validation_status: "valid",
      created_at: "2026-08-17T07:00:10Z",
    },
    {
      kind: "decisions",
      artifact_schema_version: "decisions.v1",
      artifact_producer: "screening-worker",
      artifact_consumer: "screening-api",
      sha256: c2Sha("k"),
      byte_count: 7200,
      object_version: null,
      validation_status: partial ? "pending" : "valid",
      created_at: "2026-08-17T07:41:00Z",
    },
  ];
}

/** 회차의 최신 완료 실행 하나가 계획별 신호의 기준이다(서버와 같은 규칙). */
function c2ListScope(options: RunStatusMockOptions) {
  const completed = c2Executions(options)
    .filter((item) => item.status === "성공" || item.status === "부분 성공")
    .sort((left, right) => (right.finished_at ?? "").localeCompare(left.finished_at ?? ""));
  const latest = completed[0];
  if (!latest) return null;
  return {
    mode: "run",
    execution_id: latest.execution_id,
    source_run_id: ORDER_PLAN_RUN_ID,
    status: latest.status,
    finished_at: latest.finished_at,
    policy_version: latest.policy_version,
    purpose: latest.purpose,
  };
}

function c2PlanItems() {
  const base = {
    source_url: "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-2026-00201",
    business_division: "정보화",
    contract_method: "일반경쟁",
    notice_posted: "N",
    source_run_id: ORDER_PLAN_RUN_ID,
    human_feedback: null,
    tracking: null,
    execution_id: C2_MEASUREMENT_EXECUTION_ID,
    policy_version: C2_POLICY_VERSION,
    first_observed_at: "2026-08-17T01:00:00Z",
  };
  return [
    {
      ...base,
      order_plan_pk: 201,
      order_plan_unty_no: "OP-2026-00201",
      title: "행정정보 공동이용 확대 사업 발주계획",
      agency_name: "합성 행정기관",
      budget_amount: 310000000,
      planned_order_year: "2026",
      planned_order_month: "2026-11",
      observed_at: "2026-08-17T01:00:00Z",
      stage1_status: "selected",
      stage1_rank: 3,
      stage1_score: 18.42,
      nearest_capability: "데이터 연계·공동이용",
      stage2_status: "success",
      qwen_relevance: "relevant",
      qwen_score: 0.91,
      qwen_reason: "행정정보 공동이용 연계 구축 범위가 확인됩니다.",
    },
    {
      ...base,
      order_plan_pk: 202,
      order_plan_unty_no: "OP-2026-00202",
      title: "청사 시설관리 용역 발주계획",
      agency_name: "합성 광역시",
      budget_amount: null,
      planned_order_year: "2026",
      planned_order_month: null,
      contract_method: null,
      notice_posted: null,
      observed_at: "2026-08-17T01:02:00Z",
      stage1_status: "filtered_out",
      stage1_rank: 214,
      stage1_score: 1.07,
      nearest_capability: null,
      stage2_status: "not_attempted",
      qwen_relevance: null,
      qwen_score: null,
      qwen_reason: null,
    },
    {
      ...base,
      order_plan_pk: 203,
      order_plan_unty_no: "OP-2026-00203",
      title: "아직 선별 관측값이 없는 합성 발주계획",
      agency_name: "합성 기초자치단체",
      budget_amount: 42000000,
      planned_order_year: null,
      planned_order_month: null,
      observed_at: "2026-08-17T01:03:00Z",
      stage1_status: null,
      stage1_rank: null,
      stage1_score: null,
      nearest_capability: null,
      stage2_status: null,
      qwen_relevance: null,
      qwen_score: null,
      qwen_reason: null,
      execution_id: null,
      policy_version: null,
    },
  ];
}

function attempts(executionId: string) {
  return [
    {
      attempt_id: 1701,
      execution_id: executionId,
      notice_id: "notice-031",
      stage: "종합 판정",
      attempt_no: 1,
      status: "failure",
      failure_type: "truncated_output",
      done_reason: null,
      trace_id: "trace-031",
      span_id: "span-031",
      prompt_eval_count: 1840,
      eval_count: null,
      prompt_eval_duration_ns: 420000000,
      eval_duration_ns: null,
      load_duration_ns: 700000000,
      total_duration_ns: 2920000000,
      started_at: "2026-08-25T08:41:00+09:00",
      finished_at: "2026-08-25T08:41:04+09:00",
      error_summary: "모델 출력이 제한 길이에 도달했습니다.",
    },
  ];
}

function failures() {
  return [
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
}
