import { useMemo, type HTMLAttributes, type MouseEvent as ReactMouseEvent } from "react";
import { Table, pixel, proportional, type TablePlugin, type TableColumn } from "@astryxdesign/core/Table";
import {
  changeFieldLabel,
  deadlineCell,
  itemSubline,
  stageLabel,
  verdictTone,
} from "../../lib/briefing";
import type { BriefingItemView } from "../../lib/types";
import type { RowKeyboardNavigationRowProps } from "../common/useRowKeyboardNavigation";

/*
 * 브리핑 표 6열(ui-spec §4.1): 공고 · 단계 · 판정 · 마감 · 반응 · 담당.
 *
 * - 판정 칸은 서버가 준 `verdict_display` 글자 그대로다(화면이 판정을 만들지 않는다).
 * - 추적 변화 묶음은 같은 표이며 반응이 없으므로 반응·담당 칸에 `—`만 둔다. 버튼은 없다.
 * - 선택은 URL(`?selected=`)이 정본이다. 행의 첫 칸 버튼이 키보드 이동의 `rowProps`를 받고,
 *   선택 행은 `aria-selected`로 말한다.
 */

interface BriefingRow extends Record<string, unknown> {
  id: string;
  item: BriefingItemView;
}

interface BriefingTableProps {
  /** 표의 접근 이름(시각 제목과 같은 말). */
  label: string;
  items: readonly BriefingItemView[];
  selectedId: string | null;
  rowProps: (key: string) => RowKeyboardNavigationRowProps;
  onSelect: (itemId: string) => void;
  /** 추적 변화 묶음이면 true(반응 칸이 없고 행 바탕이 다르다). */
  tracked?: boolean;
}

function initialOf(name: string): string {
  return Array.from(name.trim())[0] ?? "";
}

function StagePill({ stage }: { stage: string }) {
  return <span className="briefing-pill is-stage">{stageLabel(stage)}</span>;
}

function ReactionPill({ item }: { item: BriefingItemView }) {
  if (item.reaction === null) return <span aria-label="반응 없음" className="briefing-none">—</span>;
  return <span className={`briefing-pill is-reaction-${item.reaction === "채택" ? "accepted" : "muted"}`}>{item.reaction}</span>;
}

function Owner({ item }: { item: BriefingItemView }) {
  if (!item.reacted_by || item.reaction === null || item.reaction === "대기") {
    return <span aria-label="담당 없음" className="briefing-none">—</span>;
  }
  return (
    <span className="briefing-avatar" role="img" aria-label={`담당 ${item.reacted_by}`} title={item.reacted_by}>
      {initialOf(item.reacted_by)}
    </span>
  );
}

export function BriefingTable({ label, items, selectedId, rowProps, onSelect, tracked = false }: BriefingTableProps) {
  const data = useMemo<BriefingRow[]>(() => items.map((item) => ({ id: item.item_id, item })), [items]);

  const columns: TableColumn<BriefingRow>[] = [
    {
      key: "title",
      header: "공고",
      width: proportional(1),
      renderCell: ({ item }) => (
        <button
          aria-current={item.item_id === selectedId ? "true" : undefined}
          className="briefing-row-main"
          onClick={() => onSelect(item.item_id)}
          type="button"
          {...rowProps(item.item_id)}
        >
          <span className="briefing-row-title">{item.title}</span>
          <span className="briefing-row-sub">{itemSubline(item)}</span>
          {tracked && item.change_fields.length > 0 ? (
            <span className="briefing-row-sub">바뀐 항목 · {item.change_fields.map(changeFieldLabel).join(", ")}</span>
          ) : null}
        </button>
      ),
    },
    { key: "stage", header: "단계", width: pixel(84), renderCell: ({ item }) => <StagePill stage={item.stage} /> },
    {
      key: "verdict",
      header: "판정",
      width: pixel(96),
      renderCell: ({ item }) => (
        <span className={`briefing-pill is-verdict-${verdictTone(item.verdict_display)}`}>{item.verdict_display}</span>
      ),
    },
    {
      key: "deadline",
      header: "마감",
      width: pixel(104),
      renderCell: ({ item }) => {
        const cell = deadlineCell(item);
        return (
          <span className="briefing-deadline">
            <span className={`briefing-deadline-main${cell.urgent ? " is-urgent" : ""}`} data-urgent={cell.urgent ? "true" : "false"}>
              {cell.main}
            </span>
            {cell.sub ? <span className="briefing-row-sub">{cell.sub}</span> : null}
          </span>
        );
      },
    },
    { key: "reaction", header: "반응", width: pixel(76), renderCell: ({ item }) => <ReactionPill item={item} /> },
    { key: "owner", header: "담당", width: pixel(60), renderCell: ({ item }) => <Owner item={item} /> },
  ];

  const plugin = useMemo<TablePlugin<BriefingRow>>(
    () => ({
      transformTable: (props) => ({
        ...props,
        htmlProps: { ...props.htmlProps, "aria-label": label },
      }),
      transformBodyRow: (props, row) => {
        const selected = row.item.item_id === selectedId;
        const onClick = (event: ReactMouseEvent<HTMLTableRowElement>) => {
          // 버튼·링크를 직접 누른 경우는 그쪽이 처리한다. 행의 빈 곳을 누르면 선택만 한다.
          if ((event.target as HTMLElement).closest("button, a, input")) return;
          onSelect(row.item.item_id);
        };
        const htmlProps = {
          ...props.htmlProps,
          "aria-selected": selected,
          "data-item-id": row.item.item_id,
          "data-kind": row.item.kind,
          className: `briefing-row${tracked ? " is-tracked" : ""}${selected ? " is-selected" : ""}`,
          onClick,
        } as HTMLAttributes<HTMLTableRowElement>;
        return { ...props, htmlProps };
      },
    }),
    [label, onSelect, selectedId, tracked],
  );

  return (
    <Table
      columns={columns}
      data={data}
      density="compact"
      dividers="rows"
      hasHover
      idKey="id"
      plugins={{ briefingRows: plugin }}
      verticalAlign="top"
    />
  );
}
