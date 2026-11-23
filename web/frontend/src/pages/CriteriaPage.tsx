import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { SectionNav } from "../components/common/SectionNav";
import { CriteriaSummary } from "../components/criteria/CriteriaSummary";
import { MetricsPage } from "./MetricsPage";
import { OrderPlanPolicyPage } from "./OrderPlanPolicyPage";
import { PoliciesPage } from "./PoliciesPage";
import { ProfilePage } from "./ProfilePage";
import { QualityGatesPage } from "./QualityGatesPage";
import "../styles/criteria-erp.css";

const NOTICE_SECTIONS = [
  { id: "profile", label: "판정용 프로필 사본", path: "/profile", Page: ProfilePage },
  { id: "policies", label: "판정 정책", path: "/policies", Page: PoliciesPage },
  { id: "quality-gates", label: "품질 게이트", path: "/quality-gates", Page: QualityGatesPage },
  { id: "metrics", label: "회차 검증 지표", path: "/metrics", Page: MetricsPage },
] as const;

const GROUPS = [
  { title: "발주계획 선별 (C-2)", items: [{ id: "order-plan-policies", label: "선별 정책", path: "/criteria" }] },
  { title: "공고 판정 (C-1)", items: NOTICE_SECTIONS },
];

export function CriteriaPage() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const noticeSection = NOTICE_SECTIONS.find(({ path }) => pathname === path);
  const Page = noticeSection?.Page ?? OrderPlanPolicyPage;

  function showUnknowns() {
    const next = new URLSearchParams(searchParams);
    next.set("pstatus", "unknown");
    next.delete("psection");
    next.delete("pq");
    navigate({ pathname: "/profile", search: next.toString() });
  }

  return (
    <section aria-label="판정 기준" className="workbench-admin crit-page" data-astryx-theme="bidops">
      <SectionNav label="판정 기준 구역" groups={GROUPS} current={noticeSection?.id ?? "order-plan-policies"} search={search} />
      <div className="workbench-admin-main">
        {noticeSection ? <CriteriaSummary onShowUnknowns={showUnknowns} /> : null}
        <Page />
      </div>
    </section>
  );
}
