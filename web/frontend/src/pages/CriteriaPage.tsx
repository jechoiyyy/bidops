import { useNavigate, useLocation } from "react-router-dom";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { CriteriaGuardrails } from "../components/criteria/CriteriaGuardrails";
import { MetricsPage } from "./MetricsPage";
import { PoliciesPage } from "./PoliciesPage";
import { ProfilePage } from "./ProfilePage";
import { QualityGatesPage } from "./QualityGatesPage";
import "../styles/criteria-runstatus.css";

// docs/design/PLAN.md 2단계 · ADR-0041 결정 2: 회사 프로필·판정 정책·품질 게이트·
// 검증 지표 4화면을 이 한 화면의 탭으로 합친다. 화면 내용은 새로 만들지 않고
// 기존 페이지 컴포넌트를 그대로 옮긴다.
//
// 탭 선택을 쿼리 파라미터가 아니라 **경로**에 둔다. 이유가 둘이다.
//  1. QualityGatesPage가 게이트를 고를 때 setSearchParams({ gate })로 쿼리
//     전체를 교체하므로, 탭을 쿼리에 두면 게이트를 고르는 순간 탭이 사라진다.
//  2. 옛 경로(/profile · /policies · /quality-gates · /metrics)를 리다이렉트가
//     아니라 **그 탭의 정식 주소**로 남길 수 있다. 기존 링크와 북마크가 404를
//     내지 않고, 깜빡임 없이 해당 탭으로 바로 열린다 (PLAN 2단계 완료 게이트).

export type CriteriaTab = "profile" | "policies" | "quality-gates" | "metrics";

const TABS: { value: CriteriaTab; label: string; path: string }[] = [
  { value: "profile", label: "회사 프로필", path: "/profile" },
  { value: "policies", label: "판정 정책", path: "/policies" },
  { value: "quality-gates", label: "품질 게이트", path: "/quality-gates" },
  { value: "metrics", label: "검증 지표", path: "/metrics" },
];

export function criteriaTabFromPathname(pathname: string): CriteriaTab {
  const matched = TABS.find((tab) => pathname === tab.path || pathname.startsWith(`${tab.path}/`));
  return matched?.value ?? "profile";
}

export function CriteriaPage() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const tab = criteriaTabFromPathname(pathname);
  const panelId = `criteria-panel-${tab}`;

  return (
    <section aria-labelledby="criteria-page-title" className="ws-page" data-astryx-theme="bidops">
      <h2 className="visually-hidden" id="criteria-page-title">판정 기준</h2>
      <div className="ws-tabs">
        <TabList
          value={tab}
          onChange={(value) => {
            const next = TABS.find((item) => item.value === value);
            // 회차 파라미터를 포함한 기존 쿼리를 그대로 넘긴다. 이 화면들은
            // 회차에 기대지 않지만, 담당자가 고른 회차를 다른 화면으로
            // 돌아갈 때까지 잃지 않게 한다.
            if (next) navigate({ pathname: next.path, search });
          }}
          role="tablist"
          hasDivider
        >
          {TABS.map((item) => (
            <Tab key={item.value} label={item.label} panelId={`criteria-panel-${item.value}`} value={item.value} />
          ))}
        </TabList>
      </div>
      {/* 고른 탭만 렌더한다. 넷을 모두 마운트하면 네 화면의 조회가 한꺼번에
        * 나가고, 보이지 않는 화면의 실패까지 사용자에게 알려야 한다.
        * 반대로 경계 패널은 탭과 함께 바뀌지 않는다 — 어느 탭에 있든 "이 화면이
        * 정하지 않는 것"과 정책 차단 사유가 같은 자리에 남는다(단계 E 작업 6). */}
      <div className="ws-body">
        <div className="ws-panel" id={panelId} role="tabpanel" aria-label={TABS.find((item) => item.value === tab)?.label}>
          {tab === "profile" ? <ProfilePage /> : null}
          {tab === "policies" ? <PoliciesPage /> : null}
          {tab === "quality-gates" ? <QualityGatesPage /> : null}
          {tab === "metrics" ? <MetricsPage /> : null}
        </div>
        <CriteriaGuardrails />
      </div>
    </section>
  );
}
