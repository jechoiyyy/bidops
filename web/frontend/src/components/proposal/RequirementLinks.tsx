import { useMemo, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { REQUIREMENT_PAGE_SIZE, type LinkedRequirement } from "../../lib/proposal";
import { FIT_LABEL, FIT_TONE } from "../../lib/verdict";

/*
 * 우측 "이 절이 답하는 요구사항" 표(ui-spec §4.5): 요구사항 600 + 보조 "근거: …" + 상태 pill.
 *
 * 연결과 대조 상태(`fit_status`)는 서버 `requirement_links`를 그대로 읽는다. 요구사항 문장과 근거 라벨은 같은
 * 사업기회의 판정 표에서 unit으로 찾은 값이고, 찾지 못하면 문장을 지어내지 않고 "요구사항 문장 없음"으로 둔다.
 * 요구사항 식별자(원문 hash를 포함할 수 있다)는 DOM에 그리지 않는다. 행의 문단 버튼은 본문의 그 문단으로
 * 초점을 옮긴다. `unknown`은 부족이 아니라 "확인 필요"다.
 */

interface RequirementLinksProps {
  rows: readonly LinkedRequirement[];
  onGoParagraph: (paragraphId: string) => void;
}

interface Row extends Record<string, unknown> {
  id: string;
  link: LinkedRequirement;
}

export function RequirementLinks({ rows, onGoParagraph }: RequirementLinksProps) {
  const [shown, setShown] = useState(REQUIREMENT_PAGE_SIZE);
  const visible = rows.slice(0, shown);
  const remaining = rows.length - visible.length;
  const data = useMemo<Row[]>(() => visible.map((link) => ({ id: link.key, link })), [visible]);

  const columns: TableColumn<Row>[] = [
    {
      key: "requirement",
      header: "요구사항",
      width: proportional(1),
      renderCell: ({ link }) => (
        <span className="pp-req-main">
          <span className={`pp-req-title${link.text === null ? " is-empty" : ""}`}>{link.text ?? "요구사항 문장 없음"}</span>
          <span className="pp-req-sub">
            {link.factLabels.length > 0 ? `근거: ${link.factLabels.join(" · ")}` : "근거 표시 없음"}
          </span>
          {link.paragraphNumber !== null ? (
            <button className="pp-req-go" onClick={() => onGoParagraph(link.paragraphId)} type="button">
              문단 {link.paragraphNumber}로 이동
            </button>
          ) : null}
        </span>
      ),
    },
    {
      key: "fit",
      header: "대조",
      width: pixel(76),
      renderCell: ({ link }) => (
        link.fitStatus === null
          ? <span className="vd-pill is-muted">대조 없음</span>
          : <span className={`vd-pill is-${FIT_TONE[link.fitStatus] ?? "muted"}`}>{FIT_LABEL[link.fitStatus] ?? link.fitStatus}</span>
      ),
    },
  ];

  return (
    <section aria-labelledby="pp-req-title" className="pp-req" data-testid="requirement-links">
      <h3 className="rec-section-title" id="pp-req-title">이 절이 답하는 요구사항</h3>
      {rows.length === 0 ? (
        <p className="rec-side-note" role="status">이 절에 연결된 요구사항이 없습니다.</p>
      ) : (
        <div className="pp-req-scroll">
          <Table
            columns={columns}
            data={data}
            density="compact"
            dividers="rows"
            hasHover
            idKey="id"
            plugins={{
              proposalRequirements: {
                transformTable: (props) => ({ ...props, htmlProps: { ...props.htmlProps, "aria-label": "답하는 요구사항 표" } }),
              },
            }}
            verticalAlign="top"
          />
        </div>
      )}
      {remaining > 0 ? (
        <div className="rec-feed-more">
          <Button label={`${remaining}건 더 보기`} onClick={() => setShown((value) => value + REQUIREMENT_PAGE_SIZE)} size="sm" />
        </div>
      ) : null}
    </section>
  );
}
