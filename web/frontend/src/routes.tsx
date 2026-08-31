import { lazy } from "react";
import { Navigate, useSearchParams, type RouteObject } from "react-router-dom";
import { EmptyState } from "./components/common/EmptyState";
import { LazyRouteBoundary } from "./components/common/LazyRouteBoundary";
import { AppShell } from "./components/shell/AppShell";
import { routeHandle, routeMetadata } from "./components/shell/route-meta";

const DashboardPage = lazy(() => import("./pages/DashboardPage").then(({ DashboardPage }) => ({ default: DashboardPage })));
const QueuePage = lazy(() => import("./pages/QueuePage").then(({ QueuePage }) => ({ default: QueuePage })));
const OpportunitiesPage = lazy(() => import("./pages/OpportunitiesPage").then(({ OpportunitiesPage }) => ({ default: OpportunitiesPage })));
const OpportunityDetailPage = lazy(() => import("./pages/OpportunitiesPage").then(({ OpportunityDetailPage }) => ({ default: OpportunityDetailPage })));
const PreSpecsPage = lazy(() => import("./pages/PreSpecsPage").then(({ PreSpecsPage }) => ({ default: PreSpecsPage })));
const PreSpecDetailPage = lazy(() => import("./pages/PreSpecDetailPage").then(({ PreSpecDetailPage }) => ({ default: PreSpecDetailPage })));
const NoticeDetailPage = lazy(() => import("./pages/NoticeDetailPage").then(({ NoticeDetailPage }) => ({ default: NoticeDetailPage })));
const RunsPage = lazy(() => import("./pages/RunsPage").then(({ RunsPage }) => ({ default: RunsPage })));
const AttachmentsPage = lazy(() => import("./pages/AttachmentsPage").then(({ AttachmentsPage }) => ({ default: AttachmentsPage })));
const MetricsPage = lazy(() => import("./pages/MetricsPage").then(({ MetricsPage }) => ({ default: MetricsPage })));
const ProfilePage = lazy(() => import("./pages/ProfilePage").then(({ ProfilePage }) => ({ default: ProfilePage })));
const QualityGatesPage = lazy(() => import("./pages/QualityGatesPage").then(({ QualityGatesPage }) => ({ default: QualityGatesPage })));
const PoliciesPage = lazy(() => import("./pages/PoliciesPage").then(({ PoliciesPage }) => ({ default: PoliciesPage })));
const OperationsPage = lazy(() => import("./pages/OperationsPage").then(({ OperationsPage }) => ({ default: OperationsPage })));
const DeepReviewPage = lazy(() => import("./pages/DeepReviewPage").then(({ DeepReviewPage }) => ({ default: DeepReviewPage })));
const BidDeltaDecisionPage = lazy(() => import("./pages/BidDeltaDecisionPage").then(({ BidDeltaDecisionPage }) => ({ default: BidDeltaDecisionPage })));

// 회차 선택은 주소의 run 파라미터에만 남아 있으므로 옮길 때 그대로 넘긴다.
function RedirectWithSearch({ to, extraParams }: { to: string; extraParams?: Record<string, string> }) {
  const [searchParams] = useSearchParams();
  const next = new URLSearchParams(searchParams);
  for (const [key, value] of Object.entries(extraParams ?? {})) next.set(key, value);
  return <Navigate replace to={{ pathname: to, search: next.toString() }} />;
}

// 담당자 리뷰 기록은 아직 구현 전이다. 빈 제목 대신 무엇이 준비 중이고
// 지금은 어디에서 같은 일을 할 수 있는지 알려 준다.
function ReviewLogPage() {
  const [searchParams] = useSearchParams();
  return (
    <section className="placeholder-page" aria-labelledby="page-title">
      <h2 className="visually-hidden" id="page-title">담당자 리뷰 기록</h2>
      <EmptyState
        title="담당자 리뷰 기록은 준비 중입니다."
        description="회차별 리뷰 이력과 담당자별 처리량을 모아 보여 줄 화면입니다. 지금은 검토 대기열에서 공고를 열면 그 공고의 리뷰를 확인하고 저장할 수 있습니다."
        action={{ label: "검토 대기열로 이동", to: `/queue?${searchParams.toString()}` }}
      />
    </section>
  );
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
          { path: "queue", element: <QueuePage />, handle: routeHandle(routeMetadata.queue) },
          { path: "queue/:noticePk", element: <QueuePage />, handle: routeHandle(routeMetadata.queue) },
          { path: "deadlines", element: <RedirectWithSearch to="/queue" extraParams={{ sort: "deadline" }} />, handle: routeHandle(routeMetadata.deadlines) },
          { path: "opportunities", element: <OpportunitiesPage />, handle: routeHandle(routeMetadata.opportunities) },
          { path: "opportunities/:opportunityId", element: <OpportunityDetailPage />, handle: routeHandle(routeMetadata.opportunities) },
          { path: "opportunities/:opportunityId/bid-delta", element: <BidDeltaDecisionPage />, handle: routeHandle(routeMetadata.bidDelta) },
          { path: "pre-specs", element: <PreSpecsPage />, handle: routeHandle(routeMetadata.preSpecs) },
          { path: "pre-specs/:noticeId", element: <PreSpecDetailPage />, handle: routeHandle(routeMetadata.preSpecs) },
          { path: "judgments", element: <NoticeDetailPage />, handle: routeHandle(routeMetadata.judgments) },
          { path: "judgments/:noticePk", element: <NoticeDetailPage />, handle: routeHandle(routeMetadata.judgments) },
          { path: "reviews", element: <ReviewLogPage />, handle: routeHandle(routeMetadata.reviews) },
          { path: "profile", element: <ProfilePage />, handle: routeHandle(routeMetadata.profile) },
          { path: "metrics", element: <MetricsPage />, handle: routeHandle(routeMetadata.metrics) },
          { path: "quality-gates", element: <QualityGatesPage />, handle: routeHandle(routeMetadata.qualityGates) },
          { path: "policies", element: <PoliciesPage />, handle: routeHandle(routeMetadata.policies) },
          { path: "runs", element: <RunsPage />, handle: routeHandle(routeMetadata.runs) },
          { path: "attachments", element: <AttachmentsPage />, handle: routeHandle(routeMetadata.attachments) },
          { path: "operations", element: <OperationsPage />, handle: routeHandle(routeMetadata.operations) },
          { path: "audit", element: <RedirectWithSearch to="/runs" />, handle: routeHandle(routeMetadata.audit) },
          { path: "deep-reviews/:deepReviewId", element: <DeepReviewPage />, handle: routeHandle(routeMetadata.deepReview) },
        ],
      },
    ],
  },
];
