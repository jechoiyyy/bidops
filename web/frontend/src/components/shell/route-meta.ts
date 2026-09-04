export type RouteDataScope = "run" | "cumulative";

export interface RouteMetadata {
  title: string;
  dataScope: RouteDataScope;
  editScope: string | null;
  runSelectorVisible: boolean;
}

export interface RouteMetadataHandle {
  routeMetadata: RouteMetadata;
}

export const fallbackRouteMetadata: RouteMetadata = {
  title: "BidOps Admin",
  dataScope: "cumulative",
  editScope: null,
  runSelectorVisible: false,
};

export const routeMetadata = {
  dashboard: {
    title: "대시보드",
    dataScope: "run",
    editScope: null,
    runSelectorVisible: true,
  },
  // ADR-0045 결정 2·3·7: `검토 대기열`은 사이드바에서 사라지지만 경로는 남는다.
  // 회차 선택기는 대시보드와 공고 판정 이력에만 두므로 여기서는 감춘다. 다만
  // dataScope는 `run` 그대로여서 AppShell이 회차를 계속 해석하고 주소에 넣는다.
  // 회차를 고르는 자리는 같은 화면의 `공고 판정 이력` 탭이다.
  //
  // `editScope`는 예외 작업 경로(PLAN 단계 E 작업 3-2)가 동작한 뒤에 바꾼다.
  // 리뷰 저장 경로가 사라진 시점이 없어야 한다.
  queue: {
    title: "검토 대기열",
    dataScope: "run",
    editScope: "리뷰 저장 가능",
    runSelectorVisible: false,
  },
  // 공고 판정 이력은 사이드바 항목이 아니다. 사업 추적 상세에서 열리고,
  // 회차 축을 갖는 두 화면 중 하나다(ADR-0045 결정 7).
  noticeJudgments: {
    title: "공고 판정 이력",
    dataScope: "run",
    editScope: "리뷰 저장 가능",
    runSelectorVisible: true,
  },
  // ADR-0045 결정 2: `사업기회` 화면이 이름과 구조를 바꿔 `검토 대기열`의
  // 자리를 받는다. 주소(/opportunities)는 그대로 두어 기존 링크가 살아 있다.
  opportunities: {
    title: "사업 추적",
    dataScope: "cumulative",
    editScope: "추적 상태 저장 가능",
    runSelectorVisible: false,
  },
  orderPlans: {
    title: "발주계획 C-2 검토",
    dataScope: "cumulative",
    editScope: "사람 피드백 revision 저장 가능",
    runSelectorVisible: false,
  },
  orderPlanDetail: {
    title: "발주계획 C-2 상세",
    dataScope: "cumulative",
    editScope: "사람 피드백 revision 저장 가능",
    runSelectorVisible: false,
  },
  bidDelta: {
    title: "입찰 변경 비교",
    dataScope: "cumulative",
    editScope: "최종 Go/No-Go 저장 가능",
    runSelectorVisible: false,
  },
  preSpecs: {
    title: "사전규격",
    dataScope: "cumulative",
    editScope: null,
    runSelectorVisible: false,
  },
  goNoGo: {
    title: "최종 Go/No-Go",
    dataScope: "cumulative",
    editScope: "최종 Go/No-Go 저장 가능",
    runSelectorVisible: false,
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
  },
  deepReview: {
    title: "심층 검토 보고서",
    dataScope: "cumulative",
    editScope: null,
    runSelectorVisible: false,
  },
} satisfies Record<string, RouteMetadata>;

export function routeHandle(metadata: RouteMetadata): RouteMetadataHandle {
  return { routeMetadata: metadata };
}

export function metadataFromHandle(handle: unknown): RouteMetadata | null {
  if (typeof handle !== "object" || handle === null || !("routeMetadata" in handle)) return null;
  return (handle as RouteMetadataHandle).routeMetadata;
}
