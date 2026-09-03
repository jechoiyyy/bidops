import { Component, Suspense, type ReactNode } from "react";
import { Outlet } from "react-router-dom";
import { EmptyState } from "./EmptyState";

export function RouteLoadingFallback() {
  return (
    <div className="empty-state empty-state-compact" role="status" aria-live="polite">
      <strong>화면을 불러오는 중입니다…</strong>
    </div>
  );
}

interface RouteErrorBoundaryState {
  error: unknown | null;
}

class RouteErrorBoundary extends Component<{ children: ReactNode }, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): RouteErrorBoundaryState {
    return { error };
  }

  private retry = () => {
    window.location.reload();
  };

  render() {
    if (this.state.error !== null) {
      return (
        <EmptyState
          compact
          tone="error"
          title="화면을 불러오지 못했습니다."
          description="일시적인 네트워크 문제일 수 있습니다. 다시 시도해 주세요."
          action={{ label: "다시 시도", onClick: this.retry }}
        />
      );
    }
    return this.props.children;
  }
}

export function LazyRouteBoundary() {
  return (
    <RouteErrorBoundary>
      <Suspense fallback={<RouteLoadingFallback />}>
        <Outlet />
      </Suspense>
    </RouteErrorBoundary>
  );
}
