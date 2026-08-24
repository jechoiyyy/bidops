import type { RouteObject } from "react-router-dom";
import { AppShell } from "./components/shell/AppShell";

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
      { index: true, element: <PlaceholderPage title="대시보드" /> },
      { path: "queue", element: <PlaceholderPage title="검토 대기열" /> },
      { path: "deadlines", element: <PlaceholderPage title="마감 추적" /> },
      { path: "judgments", element: <PlaceholderPage title="공고 판정 이력" /> },
      { path: "reviews", element: <PlaceholderPage title="담당자 리뷰 기록" /> },
      { path: "profile", element: <PlaceholderPage title="회사 프로필" /> },
      { path: "metrics", element: <PlaceholderPage title="검증 지표" /> },
      { path: "runs", element: <PlaceholderPage title="수집 실행" /> },
      { path: "attachments", element: <PlaceholderPage title="첨부 확보" /> },
      { path: "audit", element: <PlaceholderPage title="산출물 감사 로그" /> },
    ],
  },
];
