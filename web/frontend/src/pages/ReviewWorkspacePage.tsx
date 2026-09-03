import { useEffect } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { EmptyState } from "../components/common/EmptyState";
import { NoticeDetailPage } from "./NoticeDetailPage";
import { QueuePage } from "./QueuePage";
import "../styles/criteria-runstatus.css";

// docs/design/PLAN.md 2단계 · ADR-0041 결정 2: 공고 판정 이력(/judgments)과
// 담당자 리뷰 기록(/reviews)을 검토 대기열의 탭으로 흡수한다. 같은 회차의 같은
// 자료이고, 리뷰 기록은 아직 구현 전이라 사이드바 최상위 한 칸을 쓸 이유가 없다.
//
// 옛 경로를 리다이렉트하지 않고 각 탭의 정식 주소로 남긴다. /queue/:noticePk와
// /judgments/:noticePk도 그대로 살아 있어 기존 링크가 404를 내지 않는다.

export type ReviewTab = "queue" | "judgments" | "reviews";

const TABS: { value: ReviewTab; label: string; path: string }[] = [
  { value: "queue", label: "검토 대기열", path: "/queue" },
  { value: "judgments", label: "공고 판정 이력", path: "/judgments" },
  { value: "reviews", label: "담당자 리뷰 기록", path: "/reviews" },
];

export function reviewTabFromPathname(pathname: string): ReviewTab {
  if (pathname === "/judgments" || pathname.startsWith("/judgments/")) return "judgments";
  if (pathname === "/reviews" || pathname.startsWith("/reviews/")) return "reviews";
  return "queue";
}

/** 마감 추적(/deadlines)은 검토 대기열의 저장된 뷰다. 메뉴 한 칸을 쓰던 정렬
 * 하나를 경로 하나로 남긴다. */
function isDeadlineView(pathname: string): boolean {
  return pathname === "/deadlines" || pathname.startsWith("/deadlines/");
}

/**
 * 저장된 뷰의 정렬을 주소에 적어 넣는다.
 *
 * 경로만으로 기본 정렬을 정하면 목록이 첫 공고를 자동 선택하며 /queue/:id로
 * 옮겨가는 순간 /deadlines라는 사실이 사라져 정렬이 등급순으로 되돌아간다.
 * 반대로 예전처럼 리다이렉트로 sort를 실어 보내면 AppShell의 회차 동기화와
 * 경쟁해 파라미터를 통째로 잃는다(직접 진입은 유지되고 리다이렉트만 유실됐다).
 * 그래서 화면이 뜬 뒤에 주소에 병합해 넣는다. 이후 화면 안 이동은 모두
 * searchParams를 그대로 넘기므로 뷰가 유지된다.
 */
function useDeadlineSavedView(pathname: string): void {
  const [searchParams, setSearchParams] = useSearchParams();
  const needsSort = isDeadlineView(pathname) && !searchParams.get("sort");
  useEffect(() => {
    if (!needsSort) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("sort", "deadline");
      return next;
    }, { replace: true });
  }, [needsSort, setSearchParams]);
}

/** 담당자 리뷰 기록은 아직 구현 전이다. 미구현을 구현으로 보이게 하지 않고,
 * 지금 같은 일을 할 수 있는 자리를 알려 준다. */
function ReviewLogPanel() {
  const [searchParams] = useSearchParams();
  return (
    <section className="placeholder-page" aria-labelledby="review-log-title">
      <h3 className="visually-hidden" id="review-log-title">담당자 리뷰 기록</h3>
      <EmptyState
        title="담당자 리뷰 기록은 준비 중입니다."
        description="회차별 리뷰 이력과 담당자별 처리량을 모아 보여 줄 화면입니다. 지금은 검토 대기열 탭에서 공고를 열면 그 공고의 리뷰를 확인하고 저장할 수 있습니다."
        action={{ label: "검토 대기열 탭으로 이동", to: `/queue?${searchParams.toString()}` }}
      />
    </section>
  );
}

export function ReviewWorkspacePage() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const tab = reviewTabFromPathname(pathname);
  const panelId = `review-panel-${tab}`;
  useDeadlineSavedView(pathname);

  return (
    <section aria-labelledby="review-workspace-title" className="ws-page" data-astryx-theme="neutral">
      <h2 className="visually-hidden" id="review-workspace-title">검토 대기열</h2>
      <div className="ws-tabs">
        <TabList
          value={tab}
          onChange={(value) => {
            const next = TABS.find((item) => item.value === value);
            // 회차 파라미터를 잃지 않는다. 세 탭 모두 회차 종속 화면이다.
            if (next) navigate({ pathname: next.path, search });
          }}
          role="tablist"
          hasDivider
        >
          {TABS.map((item) => (
            <Tab key={item.value} label={item.label} panelId={`review-panel-${item.value}`} value={item.value} />
          ))}
        </TabList>
      </div>
      <div className="ws-body">
        <div className="ws-panel" id={panelId} role="tabpanel" aria-label={TABS.find((item) => item.value === tab)?.label}>
          {tab === "queue" ? <QueuePage defaultSort={isDeadlineView(pathname) ? "deadline" : "grade"} /> : null}
          {tab === "judgments" ? <NoticeDetailPage /> : null}
          {tab === "reviews" ? <ReviewLogPanel /> : null}
        </div>
      </div>
    </section>
  );
}
