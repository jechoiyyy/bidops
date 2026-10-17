import type { RecordAttribute } from "../../lib/record";

/*
 * 좌측 속성 목록(ui-spec §3 `AttributeList`): 2열 grid(라벨 · 값), 속성 8개 순서 고정.
 * 값이 없으면 `미공개`(담당은 `미지정`)를 보조색으로 보인다. 빈 칸이나 0으로 접지 않는다.
 */
export function AttributeList({ attributes }: { attributes: readonly RecordAttribute[] }) {
  return (
    <section aria-labelledby="rec-attributes-title" className="rec-side-block">
      <h3 className="rec-side-title" id="rec-attributes-title">사업 정보</h3>
      <dl className="rec-attributes">
        {attributes.map((attribute) => (
          <div className="rec-attribute" data-attribute={attribute.key} key={attribute.key}>
            <dt>{attribute.label}</dt>
            <dd className={attribute.value === null ? "is-empty" : undefined}>
              {attribute.value ?? attribute.placeholder}
              {attribute.value !== null && attribute.note ? <span className="rec-attribute-note"> · {attribute.note}</span> : null}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
