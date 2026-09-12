/**
 * Playwright fixture를 개발 서버에서 그대로 쓰기 위한 얇은 shim.
 *
 * `tests/api-mock.ts`의 mock은 `page.route(pattern, handler)`만 부르고 handler는
 * `route.request()`와 `route.fulfill()`/`route.fallback()`만 쓴다. 그 좁은 면만
 * 흉내 내면 **fixture를 한 줄도 복사하지 않고** 브라우저에서 같은 화면을 볼 수
 * 있다. fixture를 두 벌로 만들면 테스트가 보는 화면과 사람이 보는 화면이 조용히
 * 갈라지므로 그렇게 하지 않는다.
 *
 * 이 파일은 **개발 편의 전용**이다. 운영 번들에 들어가지 않으며(vite.config.ts가
 * BIDOPS_MOCK_API가 있을 때만 붙인다), 여기의 응답은 운영 데이터도 회사 역량
 * 사실도 아니다.
 */

import {
  mockApi,
  mockBidDelta,
  mockDeepReviewLifecycle,
  mockDocumentStructurePage,
  mockOpportunity,
  mockOrderPlans,
  mockPreSpecs,
  overviewAbsentEnvelope,
  overviewCompletedEnvelope,
  overviewNeedsHumanReviewEnvelope,
  overviewPendingRangeEnvelope,
} from "../tests/api-mock";

export interface MockApiRequest {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: string | null;
}

export interface MockApiResponse {
  status: number;
  headers: Record<string, string>;
  body: string;
}

type RouteHandler = (route: FakeRoute) => Promise<void> | void;
type RoutePattern = string | RegExp;

/** Playwright의 glob은 `**`가 `/`를 넘고 `*`는 넘지 않는다. 그 두 가지만 옮긴다. */
function globToRegExp(pattern: string): RegExp {
  let source = "";
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index];
    if (char === "*") {
      if (pattern[index + 1] === "*") {
        source += ".*";
        index += 1;
      } else {
        source += "[^/]*";
      }
      continue;
    }
    source += char.replace(/[.+?^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp(`^${source}$`);
}

function matches(pattern: RoutePattern, url: string): boolean {
  return pattern instanceof RegExp ? pattern.test(url) : globToRegExp(pattern).test(url);
}

class FakeRequest {
  constructor(private readonly input: MockApiRequest) {}
  url(): string { return this.input.url; }
  method(): string { return this.input.method; }
  headers(): Record<string, string> { return this.input.headers; }
  postData(): string | null { return this.input.body; }
  postDataJSON(): unknown { return this.input.body ? JSON.parse(this.input.body) : null; }
}

class FakeRoute {
  response: MockApiResponse | null = null;
  fellBack = false;

  constructor(private readonly input: MockApiRequest) {}

  request(): FakeRequest { return new FakeRequest(this.input); }

  async fulfill(options: { status?: number; contentType?: string; body?: string; headers?: Record<string, string> }) {
    this.response = {
      status: options.status ?? 200,
      headers: {
        "content-type": options.contentType ?? "application/json",
        ...(options.headers ?? {}),
      },
      body: options.body ?? "",
    };
  }

  /** 다음(더 먼저 등록된) handler로 넘긴다. Playwright와 같은 의미다. */
  async fallback() { this.fellBack = true; }
}

/**
 * `page.route`만 받는 가짜 Page.
 *
 * `page.url()`은 mockApi가 화면 주소로 fixture를 고를 때 쓴다(예: `?state=partial`).
 * 서버는 브라우저 주소를 모르므로 Referer를 그 자리에 넣는다.
 */
class FakePage {
  readonly handlers: { pattern: RoutePattern; handler: RouteHandler }[] = [];
  private referer = "";

  async route(pattern: RoutePattern, handler: RouteHandler) {
    this.handlers.push({ pattern, handler });
  }

  url(): string { return this.referer; }

  setReferer(value: string) { this.referer = value; }
}

let ready: Promise<FakePage> | null = null;

async function buildPage(): Promise<FakePage> {
  const page = new FakePage();
  // 등록 순서가 곧 우선순위다. Playwright는 **나중에 등록한 handler를 먼저**
  // 시도하므로, 넓게 받는 mockApi를 맨 먼저 등록하고 화면별 mock을 그 위에 쌓는다.
  // 각 화면별 mock은 자기 경로가 아니면 fallback으로 아래에 넘긴다.
  await mockApi(page as never);
  await mockDocumentStructurePage(page as never);
  await mockOpportunity(page as never);
  await mockPreSpecs(page as never);
  await mockOrderPlans(page as never);
  await mockDeepReviewLifecycle(page as never, "completed");
  await mockBidDelta(page as never, { calculationStatus: "completed", resultStatus: "changed", withHistory: true });

  // 사전규격 목록 fixture에는 있지만 공고 상세 fixture가 없는 건이 있다
  // (`mockPreSpecs`는 991만 상세를 준다). 브라우저로 목록의 행을 눌러 보는
  // 것이 이 서버의 목적이므로, **목록 fixture에서 파생한** 최소 상세를 만들어
  // 그 행이 막다른 길이 되지 않게 한다. 새 fixture를 손으로 짓는 것이 아니라
  // 이미 있는 값을 그대로 옮기며, 없는 값은 null로 둔다.
  await page.route(/\/api\/notices\/\d+$/, async (route) => {
    const pk = Number(new URL(route.request().url()).pathname.split("/").pop());
    const list = await resolveMockApi({ method: "GET", url: "http://127.0.0.1/api/pre-specs", headers: {}, body: null });
    const items = list.status === 200
      ? (JSON.parse(list.body) as { items?: Record<string, unknown>[] }).items ?? []
      : [];
    const row = items.find((item) => item.notice_pk === pk);
    if (!row) {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: pk,
        notice_key: `pre-spec:${pk}`,
        run_id: "mock-derived-from-pre-spec-list",
        title: row.title ?? null,
        agency: row.agency ?? null,
        published_at: row.published_at ?? null,
        deadline_at: row.deadline_at ?? null,
        estimated_price: null,
        sample_role: null,
        sample_stratum: null,
        collection_bucket: null,
        grade: null,
        readiness: null,
        focus: null,
        attachment_count: (row.document as { attachments?: number } | undefined)?.attachments ?? 0,
        attachment_status: "none",
        bid_no: null,
        bid_ord: null,
        source_type: "pre_spec",
        budget: row.budget ?? null,
        method: null,
        url: null,
        timezone: "Asia/Seoul",
        procurement_class: null,
        region_limit: null,
        lifecycle: { pre_spec_no: row.pre_spec_no ?? null },
        qualification_flags: {},
        focus_matches: [],
        performance_matches: [],
        performance_top_score: null,
        candidate_sources: [],
        judgment: null,
        attachments: [],
        reviews: [],
      }),
    });
  });

  return page;
}

/**
 * 개요 검토 상태 전환 (`?overview=`).
 *
 * 기본 fixture의 사전규격은 991(`needs_human_review`)·992(`failed`) 둘뿐이라
 * **성공한 개요를 브라우저로 볼 수 없었다**. 상태별 envelope fixture는 이미
 * `tests/api-mock.ts`에 있으므로(spec이 쓰는 것과 같은 값) 그것을 그대로 고른다.
 * fixture를 새로 짓지 않는다.
 */
const OVERVIEW_ENVELOPES: Record<string, (noticeId: number) => unknown> = {
  completed: overviewCompletedEnvelope,
  needs_human_review: overviewNeedsHumanReviewEnvelope,
  pending_range: overviewPendingRangeEnvelope,
  absent: overviewAbsentEnvelope,
};

/** 목록 행의 상태 표시도 같이 맞춘다. 상세만 바뀌면 목록과 어긋나 보인다. */
function patchOverviewStatus(body: string, status: string): string {
  const parsed = JSON.parse(body) as {
    items?: { overview_review_status?: string | null }[];
    overview_status_counts?: { status: string | null; count: number }[];
  };
  if (!Array.isArray(parsed.items)) return body;
  for (const item of parsed.items) item.overview_review_status = status;
  if (Array.isArray(parsed.overview_status_counts)) {
    // 상태 키 집합(게이트가 요구하는 10값)은 그대로 두고 개수만 다시 센다.
    parsed.overview_status_counts = parsed.overview_status_counts.map((entry) => ({
      ...entry,
      count: parsed.items!.filter((item) => item.overview_review_status === entry.status).length,
    }));
  }
  return JSON.stringify(parsed);
}

export async function resolveMockApi(input: MockApiRequest): Promise<MockApiResponse> {
  ready ??= buildPage();
  const page = await ready;
  page.setReferer(input.headers.referer ?? "");

  // 화면 주소의 `?overview=`를 읽는다. 서버는 브라우저 주소를 모르므로 Referer를 쓴다.
  const referer = input.headers.referer ? new URL(input.headers.referer) : null;
  const overviewChoice = referer?.searchParams.get("overview") ?? null;
  const envelopeFor = overviewChoice ? OVERVIEW_ENVELOPES[overviewChoice] : undefined;

  if (envelopeFor) {
    const overviewPath = new URL(input.url).pathname.match(/^\/api\/pre-specs\/(\d+)\/overview$/);
    if (overviewPath) {
      return {
        status: 200,
        headers: { "content-type": "application/json" },
        body: JSON.stringify(envelopeFor(Number(overviewPath[1]))),
      };
    }
  }

  const candidates = page.handlers.filter((entry) => matches(entry.pattern, input.url));
  for (let index = candidates.length - 1; index >= 0; index -= 1) {
    const route = new FakeRoute(input);
    await candidates[index].handler(route);
    if (route.response) {
      const isList = new URL(input.url).pathname === "/api/pre-specs";
      if (envelopeFor && isList && overviewChoice !== "absent" && route.response.status === 200) {
        return { ...route.response, body: patchOverviewStatus(route.response.body, overviewChoice!) };
      }
      return route.response;
    }
    if (!route.fellBack) break;
  }

  return {
    status: 404,
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ detail: "고정 응답 없음 (mock)" }),
  };
}
