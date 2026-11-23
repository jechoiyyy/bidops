import { SideFacts } from "../common/Facts";
import type { RecordAttribute } from "../../lib/record";

export function AttributeList({ attributes }: { attributes: readonly RecordAttribute[] }) {
  return (
    <section aria-labelledby="rec-attributes-title" className="workbench-record-section">
      <h3 className="workbench-record-section-title" id="rec-attributes-title">사업 정보</h3>
      <SideFacts items={attributes.map((attribute) => ({
        label: attribute.label,
        value: (
          <span data-attribute={attribute.key} data-empty={attribute.value === null || undefined}>
            {attribute.value ?? attribute.placeholder}
            {attribute.value !== null && attribute.note ? <small> · {attribute.note}</small> : null}
          </span>
        ),
      }))} />
    </section>
  );
}
