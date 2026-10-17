export type RouteDataScope = "run" | "cumulative";

/** 상단바가 화면 이름을 그리는 방식.
 *
 * - `breadcrumb` 기본. `그룹 › 상위 화면 › 화면 이름 › 식별자` 경로를 그리고
 *   화면 이름 칸이 `<h1>`이 된다. 페이지는 자기 `<h2>` 제목 줄을 갖는다.
 * - `title`     제목 모드. 경로 대신 화면 이름 하나만 `<h1>`으로 그리고 페이지
 *   액션(`#page-header-actions`)이 그 오른쪽에 붙는다. 페이지는 제목 줄을 두지
 *   않으므로 세로 공간을 두 번 쓰지 않는다(사용자 결정 2026-09-08).
 *
 * 제목 모드는 **목록 화면에만** 준다. 상세 화면은 목록으로 돌아갈 경로가 필요해
 * 언제나 경로 모드로 남으며, 그 판단은 `resolveRouteLocation()`이 route param에서
 * 만든 `record` 칸의 유무로 자동으로 한다.
 */
export type RouteTopbarMode = "breadcrumb" | "title";

/** 상단 경로(현재 위치) 한 칸의 성격.
 *
 * - `group`   사이드바 1차 분류. 대응하는 화면이 없으므로 링크가 아니다.
 * - `ancestor` 이 화면 위의 화면. 목록으로 돌아가는 링크다.
 * - `screen`  이 화면의 이름. `<h1>`이며 뒤에 식별자가 오면 목록 링크가 된다.
 * - `record`  route param에서 만든 상세 식별자. 경로의 마지막 칸이다.
 */
export type RouteCrumbRole = "group" | "ancestor" | "screen" | "record";

export interface RouteCrumb {
  label: string;
  /** 이동할 화면이 없으면 `null`이다(그룹 라벨, 현재 위치인 마지막 칸). */
  to: string | null;
  role: RouteCrumbRole;
  /** 상세에서 목록 query를 복원해야 하는 화면만 표시한다. */
  context?: "pre-spec-list";
}

export interface RouteAncestor {
  label: string;
  path: string;
}

/** 상세 식별자 칸. route param 하나에서 만든다. */
export interface RouteRecordCrumb {
  /** `useMatches()`가 주는 param 이름. 없으면 목록 화면이므로 칸을 만들지 않는다. */
  param: string;
  label: (value: string) => string;
  /** 식별자 자체가 다른 화면을 가리킬 때만 있다(입찰 변경 비교의 사업기회). */
  to?: (value: string) => string;
  /** `before-screen`은 식별자가 이 화면의 **상위 레코드**일 때다.
   *  예: 입찰 변경 비교는 `사업기회 › #501 › 입찰 변경 비교`다. */
  placement: "leaf" | "before-screen";
}

export interface RouteMetadata {
  title: string;
  dataScope: RouteDataScope;
  /** 상단바 표시 방식. 없으면 `breadcrumb`이다(대부분의 화면은 손대지 않는다). */
  topbar?: RouteTopbarMode;
  /* 편집 범위(`… 저장 가능`)는 더 이상 route metadata가 아니다 — 상단바 칩을
     없앴고(ADR-0066 §3.3, 시안 M4 결정 2) 읽는 곳이 남지 않았다. 무엇을 저장할
     수 있는지는 각 화면의 결정 UI가 말한다. */
  runSelectorVisible: boolean;
  /** 사이드바 1차 분류 라벨. 상단 경로의 첫 칸이다. */
  navGroup: string | null;
  /** 사이드바에서 활성으로 보일 항목의 경로. */
  navPath: string | null;
  /** 화면 이름 앞에 놓는 상위 화면들. 사이드바 항목 이름을 그대로 쓴다. */
  ancestors: RouteAncestor[];
  /** 상세 식별자가 뒤에 붙을 때 화면 이름이 가리키는 목록. 상위 화면이
   *  이미 목록을 가리키면(`ancestors`) `null`이다. */
  listPath: string | null;
  record?: RouteRecordCrumb;
  /** 같은 화면을 다른 목록에서도 열 때의 대안 위치. 주소의 `from` 값으로 고른다. */
  alternateOrigin?: { from: string; navPath: string; ancestors: RouteAncestor[] };
  /**
   * 주소 param에 따라 달라지는 위치(가상회사 데모의 `/companies/:companyId/...`).
   * 값이 있으면 정적 `navPath`·`listPath`·`ancestors`보다 앞선다. 회사가 바뀌면
   * 경로 링크도 그 회사의 주소를 가리켜야 하므로 정적 문자열로 둘 수 없다.
   */
  dynamic?: (params: Readonly<Record<string, string | undefined>>) => {
    navPath?: string | null;
    listPath?: string | null;
    ancestors?: RouteAncestor[];
  };
}

export interface RouteMetadataHandle {
  routeMetadata: RouteMetadata;
}

export const fallbackRouteMetadata: RouteMetadata = {
  title: "BidOps Admin",
  dataScope: "cumulative",
  runSelectorVisible: false,
  navGroup: null,
  navPath: null,
  ancestors: [],
  listPath: null,
};

export const routeMetadata = {
  // RL 브리핑(시안 v26, ui-spec §4.1). 화면 본문은 RL-01이 채우고 지금은 자리만 있다.
  briefing: {
    title: "오늘의 브리핑",
    dataScope: "cumulative",
    topbar: "title",
    runSelectorVisible: false,
    navGroup: "리스트",
    navPath: "/briefing",
    ancestors: [],
    listPath: null,
  },
  // RL-00 회사 근거(ui-spec §4.6). 회사는 하나라 상위 화면이 없고, 읽기 전용이다.
  // 화면 이름 하나가 `<h1>`(제목 모드)이며 "㈜회사 · 마지막 저장"과 "이전 버전"은 액션 슬롯이 그린다.
  company: {
    title: "회사 근거",
    dataScope: "cumulative",
    topbar: "title",
    runSelectorVisible: false,
    navGroup: "레코드",
    navPath: "/company",
    ancestors: [],
    listPath: null,
  },
  dashboard: {
    title: "대시보드",
    dataScope: "cumulative",
    runSelectorVisible: false,
    navGroup: "오늘의 업무",
    navPath: "/",
    ancestors: [],
    listPath: null,
  },
  // 기존 /queue 주소도 회차별 공고 판정 이력을 연다.
  queue: {
    title: "공고 판정 이력",
    dataScope: "run",
    runSelectorVisible: true,
    navGroup: "탐색과 추적",
    navPath: "/opportunities",
    ancestors: [{ label: "사업기회", path: "/opportunities" }],
    listPath: "/queue",
    record: { param: "noticePk", label: (value) => `공고 ${value}`, placement: "leaf" },
  },
  // 공고 판정 이력은 사이드바 항목이 아니다. 사업 추적 상세에서 열리고,
  // 회차 축을 갖는 두 화면 중 하나다(ADR-0046 결정 7).
  noticeJudgments: {
    title: "공고 판정 이력",
    dataScope: "run",
    runSelectorVisible: true,
    navGroup: "탐색과 추적",
    navPath: "/opportunities",
    ancestors: [{ label: "사업기회", path: "/opportunities" }],
    listPath: "/judgments",
    record: { param: "noticePk", label: (value) => `공고 ${value}`, placement: "leaf" },
  },
  // ADR-0046 결정 2: `사업기회` 화면이 이름과 구조를 바꿔 `검토 대기열`의
  // 자리를 받는다. 주소(/opportunities)는 그대로 두어 기존 링크가 살아 있다.
  // 추적 상태 저장에 더해 예외 작업(후보 연결 판정·확인 항목 답변)의 저장도
  // 이 화면이 갖는다(결정 3).
  opportunities: {
    title: "사업기회",
    dataScope: "cumulative",
    // 목록은 제목 모드다. 레코드(`/opportunities/:opportunityId/*`)는 같은 metadata를
    // 쓰지만 record 칸이 생겨 경로 모드로 남는다. 마지막 칸 `#<id>`는 레코드 페이지가
    // 활동 응답의 제목을 `RecordTitleContext`로 올리면 그 제목으로 바뀐다(RL-02).
    topbar: "title",
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/opportunities",
    ancestors: [],
    listPath: "/opportunities",
    record: { param: "opportunityId", label: (value) => `#${value}`, placement: "leaf" },
  },
  orderPlans: {
    // 화면 제목은 `발주계획` 한 낱말이다(승인 시안). 제목 모드의 `<h1>`이 그 이름이다.
    title: "발주계획",
    dataScope: "cumulative",
    // 목록과 legacy 상세 URL redirect가 공유한다. 언제나 제목 모드다.
    topbar: "title",
    // 이 화면의 결정은 추적 선택이고 사람 판단 수정은 보조 저장이다.
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/order-plans",
    ancestors: [],
    listPath: null,
  },
  bidDelta: {
    title: "입찰 변경 비교",
    dataScope: "cumulative",
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/opportunities",
    ancestors: [{ label: "사업기회", path: "/opportunities" }],
    listPath: null,
    // 이 화면은 사업기회 하나에 매달려 있다. 식별자가 상위 레코드이므로
    // 화면 이름 앞에 두고 그 사업기회 상세로 잇는다.
    record: {
      param: "opportunityId",
      label: (value) => `#${value}`,
      to: (value) => `/opportunities/${value}`,
      placement: "before-screen",
    },
  },
  preSpecs: {
    title: "사전규격",
    dataScope: "cumulative",
    // 목록은 제목 모드, 상세(`/pre-specs/:noticeId`)는 record 칸 덕분에 경로 모드다.
    topbar: "title",
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/pre-specs",
    ancestors: [],
    listPath: "/pre-specs",
    record: { param: "noticeId", label: (value) => `notice ${value}`, placement: "leaf" },
  },
  goNoGo: {
    title: "최종 Go/No-Go",
    dataScope: "cumulative",
    topbar: "title",
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/go-no-go",
    ancestors: [],
    listPath: null,
  },
  // 기준 4화면(회사 프로필·판정 정책·품질 게이트·검증 지표)을 합친 화면이다.
  // 흡수 대상 화면은 모두 누적 자료를 다루므로(회사 프로필·정책·게이트는 원래도
  // 누적이었고, 검증 지표는 화면 자체가 회차별 추이를 비교하는 자기 완결
  // 회차 선택기를 갖고 있어 상단 회차 맥락이 필요 없다) 합친 화면 전체를
  // cumulative로 통일한다.
  criteria: {
    title: "판정 기준",
    dataScope: "cumulative",
    runSelectorVisible: false,
    navGroup: "기준과 운영",
    navPath: "/criteria",
    ancestors: [],
    listPath: null,
  },
  // 운영 3화면(수집 실행·첨부 확보·상시 운영)과 산출물 감사 로그를 합친
  // 화면이다. 수집 실행·검증 지표와 마찬가지로 실행 목록 자체가 회차를
  // 넘나드는 표이므로(실행 상태 시안의 표는 여러 run_id를 한 표에 보여준다)
  // 상단 회차 선택기에 기대지 않는다.
  runStatus: {
    title: "실행 상태",
    dataScope: "cumulative",
    runSelectorVisible: false,
    navGroup: "기준과 운영",
    navPath: "/run-status",
    ancestors: [],
    listPath: null,
  },
  // ── 가상회사 데모(`docs/work/demo-contract.md` §1) ─────────────────────────
  // `GET /api/demo-config`가 enabled일 때만 이 route들이 등록된다(`routes.tsx`).
  // 회사 식별자는 주소가 정본이므로 위치·링크는 `dynamic`이 param에서 만든다.
  companies: {
    title: "회사 선택",
    dataScope: "cumulative",
    runSelectorVisible: false,
    navGroup: "가상회사 데모",
    navPath: "/companies",
    ancestors: [],
    listPath: null,
  },
  companyPreSpecs: {
    title: "회사 사전규격",
    dataScope: "cumulative",
    topbar: "title",
    runSelectorVisible: false,
    navGroup: "가상회사 데모",
    navPath: null,
    ancestors: [{ label: "회사 선택", path: "/companies" }],
    listPath: null,
    record: { param: "noticeId", label: (value) => `notice ${value}`, placement: "leaf" },
    dynamic: (params) => {
      const list = companyPath(params.companyId, "pre-specs");
      return { navPath: list, listPath: list };
    },
  },
  companyProfile: {
    title: "회사 프로필",
    dataScope: "cumulative",
    runSelectorVisible: false,
    navGroup: "가상회사 데모",
    navPath: null,
    ancestors: [{ label: "회사 선택", path: "/companies" }],
    listPath: null,
    dynamic: (params) => ({ navPath: companyPath(params.companyId, "profile") }),
  },
  companyDeepReview: {
    title: "회사 심층 검토",
    dataScope: "cumulative",
    runSelectorVisible: false,
    navGroup: "가상회사 데모",
    navPath: null,
    ancestors: [{ label: "회사 선택", path: "/companies" }],
    listPath: null,
    record: {
      param: "reviewId",
      label: (value) => (value.length > 8 ? `${value.slice(0, 8)}…` : value),
      placement: "leaf",
    },
    dynamic: (params) => {
      const list = companyPath(params.companyId, "pre-specs");
      return {
        navPath: list,
        ancestors: list
          ? [{ label: "회사 선택", path: "/companies" }, { label: "회사 사전규격", path: list }]
          : [{ label: "회사 선택", path: "/companies" }],
      };
    },
  },
  companyComparison: {
    title: "3사 비교",
    dataScope: "cumulative",
    runSelectorVisible: false,
    navGroup: "가상회사 데모",
    navPath: "/companies",
    ancestors: [{ label: "회사 선택", path: "/companies" }],
    listPath: null,
    record: { param: "noticeId", label: (value) => `notice ${value}`, placement: "before-screen" },
  },
  // 심층 검토 보고서는 사전규격 아래에 둔다. 사전규격 상세의 문서 준비가
  // 여는 화면이고, 자동으로 시작된 심층 검토의 진입점도 거기다(ADR-0049).
  // 사업 추적 상세에서도 보고서 ID로 열 수 있으므로, 주소에 `from=opportunities`
  // 가 있으면 그쪽을 상위로 본다.
  assumptionAnalysis: {
    title: "가정 분석 보고서",
    dataScope: "cumulative",
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/pre-specs",
    ancestors: [{ label: "사전규격", path: "/pre-specs" }],
    listPath: null,
  },
  deepReview: {
    title: "심층 검토 보고서",
    dataScope: "cumulative",
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/pre-specs",
    ancestors: [{ label: "사전규격", path: "/pre-specs" }],
    listPath: null,
    // 보고서 ID는 길어서 경로 한 칸에 다 들어가지 않는다. 앞 8자만 쓰고
    // 줄였다는 사실을 말줄임표로 남긴다(잘린 값을 온전한 ID처럼 보이지 않게).
    record: {
      param: "deepReviewId",
      label: (value) => (value.length > 8 ? `${value.slice(0, 8)}…` : value),
      placement: "leaf",
    },
    alternateOrigin: {
      from: "opportunities",
      navPath: "/opportunities",
      ancestors: [{ label: "사업기회", path: "/opportunities" }],
    },
  },
} satisfies Record<string, RouteMetadata>;

/** 회사 경로 하나. 회사 식별자가 UUID 모양이 아니면 링크를 만들지 않는다. */
function companyPath(companyId: string | undefined, resource: "pre-specs" | "profile"): string | null {
  if (!companyId || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(companyId)) return null;
  return `/companies/${companyId}/${resource}`;
}

export interface ResolvedRouteLocation {
  /** 사이드바에서 활성이 될 항목의 경로. */
  navPath: string | null;
  /** 상단바가 그리는 현재 위치. 제목 모드에서는 그리지 않는다. */
  crumbs: RouteCrumb[];
  /** 상단바 표시 방식. 목록 화면의 `topbar: "title"`만 제목 모드가 된다. */
  topbarMode: RouteTopbarMode;
  /** 제목 모드의 `<h1>` 글자. 경로 모드에서도 화면 이름과 같은 값이다. */
  title: string;
}

/**
 * 화면 metadata와 주소에서 현재 위치를 만든다.
 *
 * 순서는 `그룹 › 상위 화면 › (상위 레코드) › 화면 이름 › (상세 식별자)`다.
 * 화면 이름은 `<h1>`이 되므로 목록과 상세가 같은 metadata를 쓰는 화면
 * (사전규격·사업 추적·검토 대기열·공고 판정 이력)에서는 상세에서도 같은
 * 문자열이 남고, 그 대신 목록으로 돌아가는 링크가 된다.
 *
 * `topbarMode`는 `metadata.topbar`가 `title`이고 **상세 식별자 칸이 없을 때만**
 * `title`이다. 식별자는 route param에서 만들어지므로, 목록과 상세가 metadata를
 * 공유하는 화면(사전규격·사업 추적)은 상세에서 자동으로 경로 모드로 돌아간다 —
 * 상세는 목록으로 돌아갈 링크가 필요하고 그 링크가 경로에 있다.
 * `crumbs`는 제목 모드에서도 계속 계산한다(사이드바 활성 판단과 같은 metadata에서
 * 나오고, 모드에 따라 값이 달라지면 두 벌의 진실이 생긴다). 그리지 않는 쪽을
 * 고르는 것은 `TopBar`다.
 */
export function resolveRouteLocation(
  metadata: RouteMetadata,
  params: Readonly<Record<string, string | undefined>>,
  search: URLSearchParams,
): ResolvedRouteLocation {
  const alternate = metadata.alternateOrigin;
  const dynamic = metadata.dynamic?.(params) ?? {};
  const origin = alternate && search.get("from") === alternate.from
    ? { navPath: alternate.navPath, ancestors: alternate.ancestors }
    : {
      navPath: dynamic.navPath !== undefined ? dynamic.navPath : metadata.navPath,
      ancestors: dynamic.ancestors ?? metadata.ancestors,
    };
  const listPath = dynamic.listPath !== undefined ? dynamic.listPath : metadata.listPath;

  const recordValue = metadata.record ? params[metadata.record.param] ?? null : null;
  const record = metadata.record && recordValue
    ? {
      label: metadata.record.label(recordValue),
      to: metadata.record.to?.(recordValue) ?? null,
      placement: metadata.record.placement,
    }
    : null;

  const crumbs: RouteCrumb[] = [];
  if (metadata.navGroup) crumbs.push({ label: metadata.navGroup, to: null, role: "group" });
  for (const ancestor of origin.ancestors) crumbs.push({ label: ancestor.label, to: ancestor.path, role: "ancestor" });
  if (record && record.placement === "before-screen") {
    crumbs.push({ label: record.label, to: record.to, role: "ancestor" });
  }
  const trailingRecord = record && record.placement === "leaf" ? record : null;
  crumbs.push({
    label: metadata.title,
    to: trailingRecord ? listPath : null,
    role: "screen",
    ...(trailingRecord && listPath === "/pre-specs" ? { context: "pre-spec-list" as const } : {}),
  });
  if (trailingRecord) crumbs.push({ label: trailingRecord.label, to: trailingRecord.to, role: "record" });
  const topbarMode: RouteTopbarMode = metadata.topbar === "title" && record === null ? "title" : "breadcrumb";
  return { navPath: origin.navPath, crumbs, topbarMode, title: metadata.title };
}

/** `run` 질의 파라미터를 읽지 않는 화면의 경로.
 *  셸이 만드는 이동 링크는 이 경로로 갈 때 회차 선택을 넘기지 않는다.
 *  거부 목록인 이유: `/metrics`·`/runs`·`/attachments`는 metadata상 `cumulative`여도
 *  페이지가 `run`을 직접 읽으므로 `dataScope`로는 구분할 수 없고, 모르는 경로는
 *  회차를 쓰는 쪽(현행 동작)으로 남겨야 안전하다. */
const RUN_FREE_PATHS = ["/briefing", "/company", "/opportunities", "/order-plans", "/pre-specs", "/go-no-go", "/deep-reviews", "/companies"];

function isRunFreePath(path: string): boolean {
  return RUN_FREE_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}

/** 목적지가 회차를 읽지 않으면 빈 문자열을 준다. `runSearch`는 `?run=...` 형태다. */
export function runSearchFor(path: string, runSearch: string): string {
  return isRunFreePath(path) ? "" : runSearch;
}

export function routeHandle(metadata: RouteMetadata): RouteMetadataHandle {
  return { routeMetadata: metadata };
}

export function metadataFromHandle(handle: unknown): RouteMetadata | null {
  if (typeof handle !== "object" || handle === null || !("routeMetadata" in handle)) return null;
  return (handle as RouteMetadataHandle).routeMetadata;
}
