import type { RouteObject } from "react-router-dom";
import { AppShell } from "./components/shell/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { QueuePage } from "./pages/QueuePage";
import { NoticeDetailPage } from "./pages/NoticeDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { AttachmentsPage } from "./pages/AttachmentsPage";

interface PlaceholderPageProps {
  title: string;
}

function PlaceholderPage({ title }: PlaceholderPageProps) {
  return (
    <section className="placeholder-page" aria-labelledby="page-title">
      <h2 id="page-title">{title}</h2>
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
      { path: "deadlines", element: <PlaceholderPage title="마감 추적" /> },
      { path: "judgments", element: <NoticeDetailPage /> },
      { path: "judgments/:noticePk", element: <NoticeDetailPage /> },
      { path: "reviews", element: <PlaceholderPage title="담당자 리뷰 기록" /> },
      { path: "profile", element: <PlaceholderPage title="회사 프로필" /> },
      { path: "metrics", element: <PlaceholderPage title="검증 지표" /> },
      { path: "runs", element: <RunsPage /> },
      { path: "attachments", element: <AttachmentsPage /> },
      { path: "audit", element: <PlaceholderPage title="산출물 감사 로그" /> },
    ],
  },
];
