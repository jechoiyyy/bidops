import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { demoConfigQueryKey, getDemoConfig, type DemoConfig } from "./lib/companyApi";
import { buildRoutes } from "./routes";

/**
 * route 표는 `GET /api/demo-config`를 읽은 뒤 한 번 만든다(`docs/work/demo-contract.md` §1).
 * 회사 route는 `enabled:true`일 때만 등록하며, 응답이 없거나 모양이 다르면 꺼진 것으로
 * 닫는다(`getDemoConfig`). 이 요청은 모델 호출·seed·migration을 일으키지 않는다.
 * 한 번 정한 뒤의 재조회가 실패하면 앞선 결정을 유지한다(쓰는 중 회사 화면이 사라지지 않게).
 * 셸의 넓은 무효화(회차 전환)도 이 key는 건드리지 않는다(`AppShell`).
 */
export default function App() {
  const queryClient = useQueryClient();
  const demoConfig = useQuery({
    queryKey: demoConfigQueryKey,
    queryFn: () => getDemoConfig(queryClient.getQueryData<DemoConfig>(demoConfigQueryKey)),
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
  if (demoConfig.isPending) {
    return <p className="app-boot-status" role="status">화면 구성을 확인하고 있습니다.</p>;
  }
  return <AppRouter demoEnabled={demoConfig.data?.enabled === true} />;
}

function AppRouter({ demoEnabled }: { demoEnabled: boolean }) {
  const router = useMemo(() => createBrowserRouter(buildRoutes(demoEnabled)), [demoEnabled]);
  return <RouterProvider router={router} />;
}
