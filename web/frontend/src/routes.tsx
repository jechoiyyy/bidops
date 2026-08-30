import { Navigate, useSearchParams, type RouteObject } from "react-router-dom";
import { EmptyState } from "./components/common/EmptyState";
import { AppShell } from "./components/shell/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { QueuePage } from "./pages/QueuePage";
import { OpportunitiesPage } from "./pages/OpportunitiesPage";
import { PreSpecsPage } from "./pages/PreSpecsPage";
import { NoticeDetailPage } from "./pages/NoticeDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { AttachmentsPage } from "./pages/AttachmentsPage";
import { MetricsPage } from "./pages/MetricsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { QualityGatesPage } from "./pages/QualityGatesPage";
import { PoliciesPage } from "./pages/PoliciesPage";
import { OperationsPage } from "./pages/OperationsPage";
import { DeepReviewPage } from "./pages/DeepReviewPage";

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
      { index: true, element: <DashboardPage /> },
      { path: "queue", element: <QueuePage /> },
      { path: "queue/:noticePk", element: <QueuePage /> },
      { path: "deadlines", element: <RedirectWithSearch to="/queue" extraParams={{ sort: "deadline" }} /> },
      { path: "opportunities", element: <OpportunitiesPage /> },
      { path: "pre-specs", element: <PreSpecsPage /> },
      { path: "judgments", element: <NoticeDetailPage /> },
      { path: "judgments/:noticePk", element: <NoticeDetailPage /> },
      { path: "reviews", element: <ReviewLogPage /> },
      { path: "profile", element: <ProfilePage /> },
      { path: "metrics", element: <MetricsPage /> },
      { path: "quality-gates", element: <QualityGatesPage /> },
      { path: "policies", element: <PoliciesPage /> },
      { path: "runs", element: <RunsPage /> },
      { path: "attachments", element: <AttachmentsPage /> },
      { path: "operations", element: <OperationsPage /> },
      { path: "audit", element: <RedirectWithSearch to="/runs" /> },
      { path: "deep-reviews/:deepReviewId", element: <DeepReviewPage /> },
    ],
  },
];
