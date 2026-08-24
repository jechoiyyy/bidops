import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import type { CounterargumentResponse } from "../../lib/types";
import { present } from "../../lib/format";

interface CounterargumentListProps {
  items: CounterargumentResponse[];
}

export function CounterargumentList({ items }: CounterargumentListProps) {
  return (
    <Panel className="counterargument-panel" title="반론 검토" action={<span className="panel-note">{items.length}건</span>}>
      {items.length === 0 ? (
        <EmptyState compact title="등록된 반론이 없습니다." />
      ) : (
        <ol className="counterargument-list">
          {items.map((item) => <li key={item.id}>{present(item.text, "반론 내용 미확인")}</li>)}
        </ol>
      )}
    </Panel>
  );
}
