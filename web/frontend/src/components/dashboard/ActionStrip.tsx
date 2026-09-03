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
  items: ActionItem[];
}

/**
 * 회차를 열었을 때 담당자가 가장 먼저 해야 할 일을 숫자와 이동 경로로 묶는다.
 * docs/design/PRD.md §1의 네 결정(발주계획 C-2·심층 추적 승인·공고 1차
 * 판정·최종 Go/No-Go) 각각으로 가는 항목은 건수를 확인할 수 없어도(0이거나
 * null이어도) 이동 경로 자체는 항상 이 스트립에 남는다 — 회차 통계에서 계산한
 * 나머지 보조 항목(마감 임박·검증 요청)만 값이 있을 때에 한해 추가된다.
 */
export function ActionStrip({ items }: ActionStripProps) {
  return (
    <section className="dashboard-action-strip" aria-label="지금 처리할 일">
      <div className="dashboard-action-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
          <circle cx="12" cy="12" r="8" />
          <path d="M12 8v4l3 2" />
        </svg>
        <span>지금 처리할 일</span>
      </div>
      {items.length === 0 ? (
        <div className="dashboard-action-empty">현재 회차에서 즉시 처리할 항목이 없습니다.</div>
      ) : (
        <div className="dashboard-action-items">
          {items.map((item) => (
            <Link className={`dashboard-action-item ${item.tone === "alert" ? "is-alert" : ""}`.trim()} key={item.key} to={item.to}>
              <strong className={`mono tabular-nums ${item.count === null ? "is-unavailable" : ""}`.trim()}>{countText(item)}</strong>
              <span className="dashboard-action-text">
                <span className="dashboard-action-item-title">{item.title}</span>
                <span className="dashboard-action-item-description">{item.description}</span>
              </span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
                <path d="M5 12h13M13 6l6 6-6 6" />
              </svg>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
