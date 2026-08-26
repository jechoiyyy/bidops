import { Link } from "react-router-dom";
import { formatNumber } from "../../lib/format";

export interface ActionItem {
  key: string;
  count: number;
  title: string;
  description: string;
  to: string;
  tone?: "default" | "alert";
}

interface ActionStripProps {
  items: ActionItem[];
}

/**
 * 회차를 열었을 때 담당자가 가장 먼저 해야 할 일을 숫자와 이동 경로로 묶는다.
 * 세 값 모두 회차 통계 응답에서 계산하며, 각 항목은 그 숫자만 걸린 목록으로 이어진다.
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
              <strong className="mono tabular-nums">{formatNumber(item.count)}</strong>
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
