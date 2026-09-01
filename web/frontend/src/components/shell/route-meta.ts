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
  queue: {
    title: "검토 대기열",
    dataScope: "run",
    editScope: "리뷰 저장 가능",
    runSelectorVisible: true,
  },
  deadlines: {
    title: "마감 추적",
    dataScope: "run",
    editScope: null,
    runSelectorVisible: true,
  },
  opportunities: {
    title: "사업기회",
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
  judgments: {
    title: "공고 판정 이력",
    dataScope: "run",
    editScope: "판정 원문 읽기 전용",
    runSelectorVisible: true,
  },
  reviews: {
    title: "담당자 리뷰 기록",
    dataScope: "run",
    editScope: null,
    runSelectorVisible: true,
  },
  profile: {
    title: "회사 프로필",
    dataScope: "cumulative",
    editScope: "원본 문서에서 관리",
    runSelectorVisible: false,
  },
  metrics: {
    title: "검증 지표",
    dataScope: "run",
    editScope: null,
    runSelectorVisible: true,
  },
  qualityGates: {
    title: "품질 게이트",
    dataScope: "cumulative",
    editScope: null,
    runSelectorVisible: false,
  },
  policies: {
    title: "판정 정책",
    dataScope: "cumulative",
    editScope: null,
    runSelectorVisible: false,
  },
  runs: {
    title: "수집 실행",
    dataScope: "run",
    editScope: null,
    runSelectorVisible: true,
  },
  attachments: {
    title: "첨부 확보",
    dataScope: "run",
    editScope: null,
    runSelectorVisible: true,
  },
  operations: {
    title: "상시 운영",
    dataScope: "cumulative",
    editScope: null,
    runSelectorVisible: false,
  },
  audit: {
    title: "산출물 감사 로그",
    dataScope: "run",
    editScope: null,
    runSelectorVisible: true,
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
