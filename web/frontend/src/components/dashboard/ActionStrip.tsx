import { Link } from "react-router-dom";
import { formatNumber } from "../../lib/format";

export interface ActionItem {
  key: string;
  /** null이면 이 항목의 건수를 확인할 수 없다(서버에 집계 API가 없거나
   * 회차를 아직 선택하지 않음). 0(실제 확인된 값)과 다르며 0으로 대체하지
   * 않는다 — docs/design/PRD.md §4. */
  count: number | null;
  /** true면 count가 아직 조회 중이라 "확인 불가"와 다르게 로딩으로 보여야
   * 한다. count가 null이면서 loading이 false면 서버에 집계 자체가 없다는
   * 뜻이다(예: Go/No-Go 대기 — 아래 DashboardPage 주석 참조). */
  loading?: boolean;
  title: string;
  description: string;
  to: string;
  tone?: "default" | "alert";
}

function countText(item: ActionItem): string {
  if (item.loading) return "확인 중";
  if (item.count === null) return "확인 불가";
  return formatNumber(item.count);
}

interface ActionStripProps {
  /** 네 결정(발주계획 추적 결정 · 사전규격 심층 검토 승인 · 예외 조치 ·
   *  최종 Go/No-Go)으로 가는 항목. 건수를 확인할 수 없어도 네 칸이 그대로
   *  남는다. */
  decisions: ActionItem[];
  /** 회차 통계에서만 나오는 보조 항목(우선 검토 이력 · 마감 임박 · 검증 요청).
   *  값이 있을 때만 늘어나고, 네 결정과 같은 무게로 보이지 않게 아래 줄에 둔다. */
  runScoped: ActionItem[];
}

/**
 * 회차를 열었을 때 담당자가 가장 먼저 해야 할 일을 이동 경로로 묶는다.
 * docs/design/PRD.md §1의 네 결정으로 가는 항목은 건수를 확인할 수 없어도
 * (0이거나 null이어도) 항상 첫 줄에 남고, 회차 통계에서 계산한 보조 항목만
 * 값이 있을 때 둘째 줄에 붙는다.
 *
 * 건수는 **확인된 값일 때만** 큰 숫자로 나온다. `확인 불가`와 `확인 중`은
 * 숫자 자리를 차지하지 않고 작은 보조 문구로 남는다 — 큰 글자로 두면 오류나
 * 0처럼 읽힌다.
 */
export function ActionStrip({ decisions, runScoped }: ActionStripProps) {
  return (
    <section className="dashboard-action-strip" aria-label="지금 처리할 일">
      <div className="dashboard-action-head">
        <span className="dashboard-action-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <circle cx="12" cy="12" r="8" />
            <path d="M12 8v4l3 2" />
          </svg>
          <span>지금 처리할 일</span>
        </span>
        <span className="dashboard-action-scope">네 결정 · 회차와 무관한 누적 추적</span>
      </div>
      <div className="dashboard-action-decisions">
        {decisions.map((item) => (
          <ActionCell item={item} key={item.key} />
        ))}
      </div>
      <div className="dashboard-action-secondary">
        <span className="dashboard-action-secondary-label">회차 자료에서 확인</span>
        {runScoped.length === 0 ? (
          <span className="dashboard-action-empty">이 회차에서 확인할 보조 항목이 없습니다.</span>
        ) : (
          runScoped.map((item) => <ActionCell compact item={item} key={item.key} />)
        )}
      </div>
      {/* PLAN 단계 E 작업 7: 회차 자료가 읽기 전용임을 밝히고 계산 불가를 0으로
        * 바꾸지 않는다. `확인 불가`는 서버에 집계가 없다는 뜻이고 0과 다르다. */}
      <p className="dashboard-action-note">
        네 결정으로 가는 항목은 건수를 확인할 수 없어도 항상 남습니다. <strong>확인 불가</strong>는 서버에 집계가 없다는 뜻이며 0건이 아닙니다.
        회차 판정 자료는 읽기 전용 이력이고, 사람의 수정은 사업 추적의 예외 작업에서 합니다.
      </p>
    </section>
  );
}

function ActionCell({ item, compact = false }: { item: ActionItem; compact?: boolean }) {
  const unavailable = item.count === null;
  // 숫자에만 mono·tabular를 쓴다. 한글 문구에 mono를 씌우면 글자 사이가 벌어져
  // `확인 불가`가 두 낱말로 찢어져 읽힌다.
  const numeric = !unavailable && !item.loading;
  const className = [
    "dashboard-action-item",
    compact ? "is-compact" : "",
    item.tone === "alert" ? "is-alert" : "",
  ].filter(Boolean).join(" ");
  return (
    <Link className={className} to={item.to}>
      <span className="dashboard-action-item-title">{item.title}</span>
      <span className="dashboard-action-metric">
        <strong className={[numeric ? "mono tabular-nums" : "", unavailable ? "is-unavailable" : ""].filter(Boolean).join(" ")}>
          {countText(item)}
        </strong>
        {/* 단위는 확인된 건수에만 붙인다. `확인 불가`·`확인 중` 뒤에 `건`을
          * 붙이면 세어 본 값처럼 읽힌다. */}
        {unavailable || item.loading ? null : <span className="dashboard-action-unit">건</span>}
      </span>
      <span className="dashboard-action-item-description">{item.description}</span>
      <svg className="dashboard-action-go" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
        <path d="M5 12h13M13 6l6 6-6 6" />
      </svg>
    </Link>
  );
}
