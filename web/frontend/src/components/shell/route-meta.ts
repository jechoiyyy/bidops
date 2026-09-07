export type RouteDataScope = "run" | "cumulative";

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
   *  예: 입찰 변경 비교는 `사업 추적 › #501 › 입찰 변경 비교`다. */
  placement: "leaf" | "before-screen";
}

export interface RouteMetadata {
  title: string;
  dataScope: RouteDataScope;
  editScope: string | null;
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
}

export interface RouteMetadataHandle {
  routeMetadata: RouteMetadata;
}

export const fallbackRouteMetadata: RouteMetadata = {
  title: "BidOps Admin",
  dataScope: "cumulative",
  editScope: null,
  runSelectorVisible: false,
  navGroup: null,
  navPath: null,
  ancestors: [],
  listPath: null,
};

export const routeMetadata = {
  dashboard: {
    title: "대시보드",
    dataScope: "cumulative",
    editScope: null,
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
    editScope: null,
    runSelectorVisible: true,
    navGroup: "탐색과 추적",
    navPath: "/opportunities",
    ancestors: [{ label: "사업 추적", path: "/opportunities" }],
    listPath: "/queue",
    record: { param: "noticePk", label: (value) => `공고 ${value}`, placement: "leaf" },
  },
  // 공고 판정 이력은 사이드바 항목이 아니다. 사업 추적 상세에서 열리고,
  // 회차 축을 갖는 두 화면 중 하나다(ADR-0046 결정 7).
  noticeJudgments: {
    title: "공고 판정 이력",
    dataScope: "run",
    editScope: null,
    runSelectorVisible: true,
    navGroup: "탐색과 추적",
    navPath: "/opportunities",
    ancestors: [{ label: "사업 추적", path: "/opportunities" }],
    listPath: "/judgments",
    record: { param: "noticePk", label: (value) => `공고 ${value}`, placement: "leaf" },
  },
  // ADR-0046 결정 2: `사업기회` 화면이 이름과 구조를 바꿔 `검토 대기열`의
  // 자리를 받는다. 주소(/opportunities)는 그대로 두어 기존 링크가 살아 있다.
  // 추적 상태 저장에 더해 예외 작업(후보 연결 판정·확인 항목 답변)의 저장도
  // 이 화면이 갖는다(결정 3).
  opportunities: {
    title: "사업 추적",
    dataScope: "cumulative",
    editScope: "추적 상태·예외 작업 저장 가능",
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/opportunities",
    ancestors: [],
    listPath: "/opportunities",
    record: { param: "opportunityId", label: (value) => `#${value}`, placement: "leaf" },
  },
  orderPlans: {
    // 화면 제목은 `발주계획` 한 낱말이다(승인 시안). 상단 경로도 같은 이름을 쓴다.
    title: "발주계획",
    dataScope: "cumulative",
    // 이 화면의 결정은 추적 선택이고 사람 판단 수정은 보조 저장이다.
    editScope: "추적 선택·사람 판단 수정 저장 가능",
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/order-plans",
    ancestors: [],
    listPath: null,
  },
  orderPlanDetail: {
    title: "발주계획 C-2 상세",
    dataScope: "cumulative",
    editScope: "사람 피드백 수정본 저장 가능",
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/order-plans",
    ancestors: [{ label: "발주계획", path: "/order-plans" }],
    listPath: null,
    record: { param: "orderPlanPk", label: (value) => `#${value}`, placement: "leaf" },
  },
  bidDelta: {
    title: "입찰 변경 비교",
    dataScope: "cumulative",
    editScope: "최종 Go/No-Go 저장 가능",
    runSelectorVisible: false,
    navGroup: "탐색과 추적",
    navPath: "/opportunities",
    ancestors: [{ label: "사업 추적", path: "/opportunities" }],
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
    editScope: null,
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
    editScope: "최종 Go/No-Go 저장 가능",
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
    editScope: null,
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
    editScope: null,
    runSelectorVisible: false,
    navGroup: "기준과 운영",
    navPath: "/run-status",
    ancestors: [],
    listPath: null,
  },
  // 심층 검토 보고서는 사전규격 아래에 둔다. 사전규격 상세의 문서 준비가
  // 여는 화면이고, 자동으로 시작된 심층 검토의 진입점도 거기다(ADR-0049).
  // 사업 추적 상세에서도 보고서 ID로 열 수 있으므로, 주소에 `from=opportunities`
  // 가 있으면 그쪽을 상위로 본다.
  deepReview: {
    title: "심층 검토 보고서",
    dataScope: "cumulative",
    editScope: null,
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
      ancestors: [{ label: "사업 추적", path: "/opportunities" }],
    },
  },
} satisfies Record<string, RouteMetadata>;

export interface ResolvedRouteLocation {
  /** 사이드바에서 활성이 될 항목의 경로. */
  navPath: string | null;
  /** 상단바가 그리는 현재 위치. */
  crumbs: RouteCrumb[];
}

/**
 * 화면 metadata와 주소에서 현재 위치를 만든다.
 *
 * 순서는 `그룹 › 상위 화면 › (상위 레코드) › 화면 이름 › (상세 식별자)`다.
 * 화면 이름은 `<h1>`이 되므로 목록과 상세가 같은 metadata를 쓰는 화면
 * (사전규격·사업 추적·검토 대기열·공고 판정 이력)에서는 상세에서도 같은
 * 문자열이 남고, 그 대신 목록으로 돌아가는 링크가 된다.
 */
export function resolveRouteLocation(
  metadata: RouteMetadata,
  params: Readonly<Record<string, string | undefined>>,
  search: URLSearchParams,
): ResolvedRouteLocation {
  const alternate = metadata.alternateOrigin;
  const origin = alternate && search.get("from") === alternate.from
    ? { navPath: alternate.navPath, ancestors: alternate.ancestors }
    : { navPath: metadata.navPath, ancestors: metadata.ancestors };

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
    to: trailingRecord ? metadata.listPath : null,
    role: "screen",
  });
  if (trailingRecord) crumbs.push({ label: trailingRecord.label, to: trailingRecord.to, role: "record" });
  return { navPath: origin.navPath, crumbs };
}

export function routeHandle(metadata: RouteMetadata): RouteMetadataHandle {
  return { routeMetadata: metadata };
}

export function metadataFromHandle(handle: unknown): RouteMetadata | null {
  if (typeof handle !== "object" || handle === null || !("routeMetadata" in handle)) return null;
  return (handle as RouteMetadataHandle).routeMetadata;
}
