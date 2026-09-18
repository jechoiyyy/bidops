import { lazy, type ReactNode } from "react";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Navigate, useParams, useSearchParams, type RouteObject } from "react-router-dom";
import { LazyRouteBoundary } from "./components/common/LazyRouteBoundary";
import { AppShell } from "./components/shell/AppShell";
import { routeHandle, routeMetadata } from "./components/shell/route-meta";

const DashboardPage = lazy(() => import("./pages/DashboardPage").then(({ DashboardPage }) => ({ default: DashboardPage })));
const OpportunitiesPage = lazy(() => import("./pages/OpportunitiesPage").then(({ OpportunitiesPage }) => ({ default: OpportunitiesPage })));
const OpportunityDetailPage = lazy(() => import("./pages/OpportunitiesPage").then(({ OpportunityDetailPage }) => ({ default: OpportunityDetailPage })));
const PreSpecsPage = lazy(() => import("./pages/PreSpecsPage").then(({ PreSpecsPage }) => ({ default: PreSpecsPage })));
const PreSpecDetailPage = lazy(() => import("./pages/PreSpecDetailPage").then(({ PreSpecDetailPage }) => ({ default: PreSpecDetailPage })));
const DeepReviewPage = lazy(() => import("./pages/DeepReviewPage").then(({ DeepReviewPage }) => ({ default: DeepReviewPage })));
const BidDeltaDecisionPage = lazy(() => import("./pages/BidDeltaDecisionPage").then(({ BidDeltaDecisionPage }) => ({ default: BidDeltaDecisionPage })));
const OrderPlansPage = lazy(() => import("./pages/OrderPlansPage").then(({ OrderPlansPage }) => ({ default: OrderPlansPage })));
const CriteriaPage = lazy(() => import("./pages/CriteriaPage").then(({ CriteriaPage }) => ({ default: CriteriaPage })));
const RunStatusPage = lazy(() => import("./pages/RunStatusPage").then(({ RunStatusPage }) => ({ default: RunStatusPage })));

// 승인된 두 관리 화면과 그 대화상자에 시안의 한국어 카탈로그를 적용한다.
function adminLocale(page: ReactNode) {
  return <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}>{page}</InternationalizationProvider>;
}
const criteriaView = adminLocale(<CriteriaPage />);
const runStatusView = adminLocale(<RunStatusPage />);
const ReviewWorkspacePage = lazy(() => import("./pages/ReviewWorkspacePage").then(({ ReviewWorkspacePage }) => ({ default: ReviewWorkspacePage })));
const GoNoGoPage = lazy(() => import("./pages/GoNoGoPage").then(({ GoNoGoPage }) => ({ default: GoNoGoPage })));

// 회차 선택은 주소의 run 파라미터에만 남아 있으므로 옮길 때 그대로 넘긴다.
function RedirectWithSearch({ to, extraParams }: { to: string; extraParams?: Record<string, string> }) {
  const [searchParams] = useSearchParams();
  const next = new URLSearchParams(searchParams);
  for (const [key, value] of Object.entries(extraParams ?? {})) next.set(key, value);
  return <Navigate replace to={{ pathname: to, search: next.toString() }} />;
}

/**
 * `/order-plans/:pk` was the old standalone detail screen. Keep old bookmarks
 * usable by entering the list's right-hand detail pane with the record selected.
 * The list resolves the record's source run when the legacy URL did not carry it.
 */
function LegacyOrderPlanRedirect() {
  const { orderPlanPk } = useParams();
  return <RedirectWithSearch to="/order-plans" extraParams={orderPlanPk ? { selected: orderPlanPk } : undefined} />;
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      {
        element: <LazyRouteBoundary />,
        children: [
          { index: true, element: <DashboardPage />, handle: routeHandle(routeMetadata.dashboard) },
          // 검토 대기열 · 공고 판정 이력 · 담당자 리뷰 기록은 한 화면의 세 탭이다.
          // 옛 경로를 리다이렉트하지 않고 각 탭의 정식 주소로 남겨 404를 막는다.
          //
          // 공고 판정 이력만 다른 화면 맥락을 쓴다. ADR-0046 결정 7이 회차 축을
          // 대시보드와 공고 판정 이력 두 화면으로 제한하므로 회차 선택기가 이
          // 탭에만 있고, 화면 제목도 그 탭의 것을 쓴다.
          { path: "queue", element: <ReviewWorkspacePage />, handle: routeHandle(routeMetadata.queue) },
          { path: "queue/:noticePk", element: <ReviewWorkspacePage />, handle: routeHandle(routeMetadata.queue) },
          { path: "judgments", element: <ReviewWorkspacePage />, handle: routeHandle(routeMetadata.noticeJudgments) },
          { path: "judgments/:noticePk", element: <ReviewWorkspacePage />, handle: routeHandle(routeMetadata.noticeJudgments) },
          { path: "reviews", element: <ReviewWorkspacePage />, handle: routeHandle(routeMetadata.queue) },
          // 마감 추적은 검토 대기열의 저장된 뷰다(정렬 하나가 메뉴 한 칸을 쓰고 있었다).
          // 리다이렉트가 아니라 그 뷰의 주소다: 리다이렉트는 AppShell의 회차 동기화와
          // 경쟁해 sort 파라미터를 잃었고, 그러면 저장된 뷰가 저장되지 않는다.
          { path: "deadlines", element: <ReviewWorkspacePage />, handle: routeHandle(routeMetadata.queue) },
          { path: "opportunities", element: <OpportunitiesPage />, handle: routeHandle(routeMetadata.opportunities) },
          { path: "opportunities/:opportunityId", element: <OpportunityDetailPage />, handle: routeHandle(routeMetadata.opportunities) },
          { path: "opportunities/:opportunityId/bid-delta", element: <BidDeltaDecisionPage />, handle: routeHandle(routeMetadata.bidDelta) },
          // 최종 Go/No-Go는 되돌릴 수 없는 결정인데 지금까지 사이드바 진입점이 없었다.
          { path: "go-no-go", element: <GoNoGoPage />, handle: routeHandle(routeMetadata.goNoGo) },
          { path: "order-plans", element: <OrderPlansPage />, handle: routeHandle(routeMetadata.orderPlans) },
          { path: "order-plans/:orderPlanPk", element: <LegacyOrderPlanRedirect />, handle: routeHandle(routeMetadata.orderPlans) },
          { path: "pre-specs", element: <PreSpecsPage />, handle: routeHandle(routeMetadata.preSpecs) },
          { path: "pre-specs/:noticeId", element: <PreSpecDetailPage />, handle: routeHandle(routeMetadata.preSpecs) },
          // 기준 4화면은 판정 기준 한 화면의 탭이다. 옛 경로가 각 탭의 주소다.
          { path: "criteria", element: criteriaView, handle: routeHandle(routeMetadata.criteria) },
          { path: "profile", element: criteriaView, handle: routeHandle(routeMetadata.criteria) },
          { path: "metrics", element: criteriaView, handle: routeHandle(routeMetadata.criteria) },
          { path: "quality-gates", element: criteriaView, handle: routeHandle(routeMetadata.criteria) },
          { path: "policies", element: criteriaView, handle: routeHandle(routeMetadata.criteria) },
          { path: "order-plan-policies", element: criteriaView, handle: routeHandle(routeMetadata.criteria) },
          // 운영 3화면과 산출물 감사 로그는 실행 상태 한 화면의 탭이다.
          { path: "run-status", element: runStatusView, handle: routeHandle(routeMetadata.runStatus) },
          { path: "runs", element: runStatusView, handle: routeHandle(routeMetadata.runStatus) },
          { path: "attachments", element: runStatusView, handle: routeHandle(routeMetadata.runStatus) },
          { path: "operations", element: runStatusView, handle: routeHandle(routeMetadata.runStatus) },
          { path: "audit", element: runStatusView, handle: routeHandle(routeMetadata.runStatus) },
          { path: "deep-reviews/:deepReviewId", element: <DeepReviewPage />, handle: routeHandle(routeMetadata.deepReview) },
        ],
      },
    ],
  },
];
