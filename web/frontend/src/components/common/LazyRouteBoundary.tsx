import { useQueryClient } from "@tanstack/react-query";
import { Component, Suspense, useCallback, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { EmptyState } from "./EmptyState";
import { SkeletonPanel } from "./Skeleton";

export function RouteLoadingFallback() {
  return <SkeletonPanel className="route-loading-skeleton" label="화면을 불러오는 중" lines={4} />;
}

interface RouteErrorBoundaryProps {
  children: ReactNode;
  /** 이 값이 바뀌면 경계 state를 스스로 비운다. 위치가 바뀌면 옛 오류를 남기지 않는다. */
  resetKey: string;
  onRetry: () => void;
}

interface RouteErrorBoundaryState {
  error: unknown | null;
  resetKey: string;
}

class RouteErrorBoundary extends Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<RouteErrorBoundaryState> {
    return { error };
  }

  static getDerivedStateFromProps(
    props: RouteErrorBoundaryProps,
    state: RouteErrorBoundaryState,
  ): Partial<RouteErrorBoundaryState> | null {
    if (props.resetKey === state.resetKey) return null;
    return { error: null, resetKey: props.resetKey };
  }

  private retry = () => {
    // `window.location.reload()`는 작성 중인 초안을 지운다. 화면을 다시 그리는
    // 데 새로고침이 필요하지 않다 — 경계 state를 비우고, 실패한 조회만 서버에
    // 다시 물어본다.
    this.setState({ error: null });
    this.props.onRetry();
  };

  render() {
    if (this.state.error !== null) {
      return (
        <EmptyState
          className="lazy-route-error"
          compact
          tone="error"
          title="화면을 불러오지 못했습니다."
          description="일시적인 네트워크 문제일 수 있습니다. 다시 시도하면 새로고침 없이 이 화면만 다시 그립니다. 입력 중인 다른 화면의 내용은 사라지지 않습니다."
          action={{ label: "다시 시도", onClick: this.retry }}
        />
      );
    }
    return this.props.children;
  }
}

export function LazyRouteBoundary() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const retry = useCallback(() => {
    void queryClient.resetQueries();
  }, [queryClient]);

  return (
    <RouteErrorBoundary onRetry={retry} resetKey={location.key}>
      <Suspense fallback={<RouteLoadingFallback />}>
        <Outlet />
      </Suspense>
    </RouteErrorBoundary>
  );
}
