import { EmptyState } from "../components/common/EmptyState";

/**
 * 오늘의 브리핑(ui-spec §4.1). 리스트 뷰·피크 패널·반응 저장은 RL-01이 구현한다.
 * 셸(사이드바·상단바)이 먼저 들어왔으므로 이 화면은 자리와 안내만 둔다 —
 * 추천 데이터를 흉내 내지 않는다.
 */
export function BriefingPage() {
  return (
    <section aria-label="오늘의 브리핑" className="briefing-page">
      <EmptyState
        action={{ label: "사전규격 목록 열기", to: "/pre-specs" }}
        description="추천 목록과 반응(볼게요·무시·나중에)은 아직 준비 중입니다. 지금은 사전규격·발주계획 목록에서 공고를 확인하세요."
        secondaryAction={{ label: "발주계획 열기", to: "/order-plans" }}
        title="브리핑은 아직 발송되지 않았습니다"
      />
    </section>
  );
}
