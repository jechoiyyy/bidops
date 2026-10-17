import { useMemo, useState, type HTMLAttributes, type MouseEvent as ReactMouseEvent } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, pixel, proportional, type TableColumn, type TablePlugin } from "@astryxdesign/core/Table";
import type { VerdictMatrixRow } from "../../lib/types";
import {
  FIT_FILTER_OPTIONS,
  FIT_LABEL,
  FIT_TONE,
  MATRIX_PAGE_SIZE,
  companyEvidenceText,
  countFit,
  filterMatrix,
  mandatoryLabel,
  mappingSuffix,
  pageRangeLabel,
  requirementText,
  sortMatrix,
  type FitFilter,
} from "../../lib/verdict";

/*
 * 중앙(ui-spec §4.4, RL-03 spec "화면"): "요구사항 n" + 보조 "부족 a · 확인 필요 b · 충족 c" + 도구
 * (상태 select 기본 "부족·확인 필요만", 필수만 토글) + 4열 표(요구사항·대조·회사 근거·원문) + 50행
 * "n건 더 보기".
 *
 * - n은 unit 수, 세 집계는 서버가 준 `fit_status`를 세기만 한다(ui-spec이 허용한 집계).
 * - `unknown`은 "확인 필요"로만 보인다(부족 아님). 색은 의미를 거들 뿐이고 pill 글자가 상태 이름이다.
 * - 행 선택은 이 파일 밖(원문 패널)이 읽는다. unit id는 원문 hash를 포함할 수 있어 DOM에 쓰지 않고
 *   표 안의 번호(`r<순번>`)로만 행을 가리킨다.
 * - 원문 칸의 "n쪽"은 그 행을 골라 원문 패널을 연다. 쪽을 모르면 링크 없이 "쪽 미확인" 글자만 둔다.
 */

interface RequirementRow extends Record<string, unknown> {
  id: string;
  row: VerdictMatrixRow;
}

interface RequirementTableProps {
  /** 완료 판정이면 `result.matrix`, 아니면 `partial_matrix`. */
  rows: readonly VerdictMatrixRow[];
  /** 선택된 행의 unit id(메모리 상태). 보이지 않는 행이면 패널이 닫힌 것으로 본다. */
  selectedUnitId: string | null;
  onSelect: (unitId: string | null) => void;
  /** 완료가 아닐 때 제목 옆에 붙이는 설명(검증을 통과한 부분만 보인다). */
  note?: string | null;
}

function FitPill({ row }: { row: VerdictMatrixRow }) {
  return <span className={`vd-pill is-${FIT_TONE[row.fit_status] ?? "muted"}`}>{FIT_LABEL[row.fit_status] ?? row.fit_status}</span>;
}

export function RequirementTable({ rows, selectedUnitId, onSelect, note = null }: RequirementTableProps) {
  const [fit, setFit] = useState<FitFilter>("default");
  const [mandatoryOnly, setMandatoryOnly] = useState(false);
  const [shown, setShown] = useState(MATRIX_PAGE_SIZE);

  const sorted = useMemo(() => sortMatrix(rows), [rows]);
  const counts = useMemo(() => countFit(sorted), [sorted]);
  const filtered = useMemo(() => filterMatrix(sorted, fit, mandatoryOnly), [sorted, fit, mandatoryOnly]);
  const visible = filtered.slice(0, shown);
  const remaining = filtered.length - visible.length;

  const data = useMemo<RequirementRow[]>(() => visible.map((row, index) => ({ id: `r${index}`, row })), [visible]);

  const selectedId = data.find((entry) => entry.row.unit_id === selectedUnitId)?.id ?? null;

  const columns: TableColumn<RequirementRow>[] = [
    {
      key: "requirement",
      header: "요구사항",
      width: proportional(1.4),
      renderCell: ({ id, row }) => (
        <button
          aria-current={id === selectedId ? "true" : undefined}
          className="vd-row-main"
          onClick={() => onSelect(row.unit_id)}
          type="button"
        >
          <span className="vd-row-title">{requirementText(row)}</span>
          <span className="vd-row-sub">{row.type} · {mandatoryLabel(row)}</span>
        </button>
      ),
    },
    { key: "fit", header: "대조", width: pixel(76), renderCell: ({ row }) => <FitPill row={row} /> },
    {
      key: "company",
      header: "회사 근거",
      width: proportional(1),
      renderCell: ({ row }) => {
        const reason = companyEvidenceText(row);
        const facts = (row.fact_labels ?? []).filter((label) => label.trim().length > 0);
        return (
          <span className="vd-row-company">
            {reason ? <span className="vd-row-reason" title={reason}>{reason}</span> : <span className="vd-none">회사 근거 없음</span>}
            {facts.length > 0 ? <span className="vd-row-sub">{facts.join(" · ")}</span> : null}
          </span>
        );
      },
    },
    {
      key: "source",
      header: "원문",
      width: pixel(92),
      renderCell: ({ row }) => {
        const label = pageRangeLabel(row);
        if (!label) return <span className="vd-none">쪽 미확인</span>;
        const suffix = mappingSuffix(row);
        return (
          <span className="vd-row-source">
            <button className="vd-page-link" onClick={() => onSelect(row.unit_id)} type="button">{label}</button>
            {suffix ? <span className="vd-row-sub">{suffix}</span> : null}
          </span>
        );
      },
    },
  ];

  const plugin = useMemo<TablePlugin<RequirementRow>>(
    () => ({
      transformTable: (props) => ({
        ...props,
        htmlProps: { ...props.htmlProps, "aria-label": "요구사항 대조표" },
      }),
      transformBodyRow: (props, entry) => {
        const selected = entry.id === selectedId;
        const onClick = (event: ReactMouseEvent<HTMLTableRowElement>) => {
          if ((event.target as HTMLElement).closest("button, a, input")) return;
          onSelect(entry.row.unit_id);
        };
        const htmlProps = {
          ...props.htmlProps,
          "aria-selected": selected,
          "data-fit": entry.row.fit_status,
          className: `vd-row${selected ? " is-selected" : ""}`,
          onClick,
        } as HTMLAttributes<HTMLTableRowElement>;
        return { ...props, htmlProps };
      },
    }),
    [onSelect, selectedId],
  );

  // 조건이 바뀌면 보이는 행이 달라지므로 쪽 수를 처음으로 돌리고 원문 패널을 닫는다.
  const resetView = () => {
    setShown(MATRIX_PAGE_SIZE);
    onSelect(null);
  };

  return (
    <section aria-labelledby="vd-req-title" className="vd-requirements">
      <div className="vd-req-head">
        <div className="vd-req-heading">
          <h3 className="rec-section-title" id="vd-req-title">요구사항 {counts.total}</h3>
          <p className="vd-req-counts" data-testid="verdict-counts">
            부족 {counts.gap} · 확인 필요 {counts.unknown} · 충족 {counts.met}
          </p>
          {note ? <p className="rec-side-note">{note}</p> : null}
        </div>
        <div className="vd-req-tools">
          <Selector
            isLabelHidden
            label="상태"
            onChange={(value) => { setFit(value as FitFilter); resetView(); }}
            options={FIT_FILTER_OPTIONS.map((option) => ({ value: option.value, label: option.label }))}
            size="sm"
            value={fit}
          />
          <button
            aria-pressed={mandatoryOnly}
            className="rec-chip"
            onClick={() => { setMandatoryOnly((value) => !value); resetView(); }}
            type="button"
          >
            필수만
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="vd-req-empty" role="status">
          {counts.total === 0
            ? "대조한 요구사항이 아직 없습니다."
            : "이 조건에 해당하는 요구사항이 없습니다. 상태나 필수만 조건을 바꿔 보세요."}
        </p>
      ) : (
        <div className="vd-table-scroll">
          <Table
            columns={columns}
            data={data}
            density="compact"
            dividers="rows"
            hasHover
            idKey="id"
            plugins={{ verdictRows: plugin }}
            verticalAlign="top"
          />
        </div>
      )}

      {remaining > 0 ? (
        <div className="rec-feed-more">
          <Button label={`${remaining}건 더 보기`} onClick={() => setShown((value) => value + MATRIX_PAGE_SIZE)} size="sm" />
        </div>
      ) : null}
    </section>
  );
}
