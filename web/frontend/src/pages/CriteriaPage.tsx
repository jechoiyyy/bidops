import { useCallback } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { CriteriaSummary } from "../components/criteria/CriteriaSummary";
import { MetricsPage } from "./MetricsPage";
import { OrderPlanPolicyPage } from "./OrderPlanPolicyPage";
import { PoliciesPage } from "./PoliciesPage";
import { ProfilePage } from "./ProfilePage";
import { QualityGatesPage } from "./QualityGatesPage";
import "../styles/criteria-erp.css";

// docs/design/PLAN.md 2단계 · ADR-0041 결정 2: 회사 프로필·판정 정책·품질 게이트·
// 검증 지표 4화면을 이 한 화면의 탭으로 합친다.
//
// 탭 선택을 쿼리 파라미터가 아니라 **경로**에 둔다. 이유가 둘이다.
//  1. 각 탭이 선택한 항목(정책 버전·게이트·지표·절)을 쿼리에 남기므로, 탭까지
//     쿼리에 두면 항목을 고르는 순간 탭이 사라질 위험이 있다.
//  2. 옛 경로(/profile · /policies · /quality-gates · /metrics)를 리다이렉트가
//     아니라 **그 탭의 정식 주소**로 남길 수 있다. 기존 링크와 북마크가 404를
//     내지 않고, 깜빡임 없이 해당 탭으로 바로 열린다 (PLAN 2단계 완료 게이트).
//
// 화면 골격은 승인된 시안(`design-previews/bidops-criteria-runstatus-erp-20260907/`)
// 그대로다: 탭 → 요약 한 줄 → 목록 38% / 상세 62% → 짧은 경계 안내.
// 옛 고정 2열 경계 패널은 없앴고, 그 문장은 아래 경계 안내 한 줄과 요약 줄,
// 그리고 판정 정책 탭의 "활성화 조건"으로 옮겼다 — 사라지지 않는다.

export type CriteriaTab = "profile" | "policies" | "quality-gates" | "order-plan-policies" | "metrics";

const TABS: { value: CriteriaTab; label: string; path: string }[] = [
  { value: "profile", label: "회사 프로필", path: "/profile" },
  { value: "policies", label: "판정 정책", path: "/policies" },
  { value: "quality-gates", label: "품질 게이트", path: "/quality-gates" },
  // C-2 발주계획 선별 policy의 사람 승인과 일일 자동 실행 스위치(docs/0918_daily-operation/spec.md §11).
  { value: "order-plan-policies", label: "발주계획 선별 정책", path: "/order-plan-policies" },
  { value: "metrics", label: "검증 지표", path: "/metrics" },
];

export function criteriaTabFromPathname(pathname: string): CriteriaTab {
  const matched = TABS.find((tab) => pathname === tab.path || pathname.startsWith(`${tab.path}/`));
  return matched?.value ?? "profile";
}

export function CriteriaPage() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const tab = criteriaTabFromPathname(pathname);

  // 회차 파라미터를 포함한 기존 쿼리를 그대로 넘긴다. 이 화면들은 회차에 기대지
  // 않지만, 담당자가 고른 회차와 각 탭의 선택 ID를 다른 화면으로 돌아갈 때까지
  // 잃지 않게 한다.
  const goToTab = useCallback((value: string) => {
    const next = TABS.find((item) => item.value === value);
    if (next) navigate({ pathname: next.path, search });
  }, [navigate, search]);

  // 요약 줄의 미확인 항목은 회사 프로필 탭의 미확인 필터를 켠다. 필터는 주소에
  // 남아 새로 고치거나 공유해도 같은 화면이 열린다.
  const showUnknowns = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    next.set("pstatus", "unknown");
    next.delete("psection");
    next.delete("pq");
    navigate({ pathname: "/profile", search: next.toString() });
  }, [navigate, searchParams]);

  return (
    <section aria-labelledby="criteria-page-title" className="crit-page" data-astryx-theme="bidops">
      <h2 className="visually-hidden" id="criteria-page-title">판정 기준</h2>
      <div className="crit-tabs">
        <TabList hasDivider onChange={goToTab} role="tablist" value={tab}>
          {TABS.map((item) => (
            <Tab key={item.value} label={item.label} panelId={`criteria-panel-${item.value}`} value={item.value} />
          ))}
        </TabList>
      </div>
      <CriteriaSummary onShowUnknowns={showUnknowns} />
      {/* 고른 탭만 렌더한다. 넷을 모두 마운트하면 네 화면의 조회가 한꺼번에
        * 나가고, 보이지 않는 화면의 실패까지 사용자에게 알려야 한다. */}
      {tab === "profile" ? <ProfilePage /> : null}
      {tab === "policies" ? <PoliciesPage /> : null}
      {tab === "quality-gates" ? <QualityGatesPage /> : null}
      {tab === "order-plan-policies" ? <OrderPlanPolicyPage /> : null}
      {tab === "metrics" ? <MetricsPage /> : null}
      {/* 1280px에서도 한 줄이어야 한다. 두 줄이 되면 작업 영역이 그만큼 짧아져
        * 상세 하단 액션이 시안보다 위로 올라온다. 자세한 조건(정책별 차단 사유,
        * 게이트 목적, 지표 조회 범위)은 각 탭의 상세와 확인 창에 있다. */}
      <p className="crit-boundary">
        기준 변경은 이후 실행에만 적용되며 과거 판정을 소급해 바꾸지 않습니다.
        적합성 등급 · 참여 준비 · 추적 선택 · 최종 Go/No-Go는 별도 판단입니다.
      </p>
    </section>
  );
}
