import type { ComponentProps, KeyboardEvent, ReactNode, Ref, UIEventHandler } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from "@astryxdesign/core/Table";
import { EmptyState } from "./EmptyState";
import { ReviewListViewport } from "./ReviewPrimitives";
import { SkeletonBlock } from "./Skeleton";
import type { RowKey, RowKeyboardNavigation } from "./useRowKeyboardNavigation";

interface RecordTitleColumn<Row> {
  key: string;
  header: string;
  title: (row: Row) => string;
  titleClassName?: string;
  renderTitle?: (row: Row, title: string) => ReactNode;
  renderBelow?: (row: Row) => ReactNode;
}

interface RecordValueColumn<Row> {
  key: string;
  header: string;
  width: number;
  grow?: boolean;
  numeric?: boolean;
  ellipsis?: boolean;
  className?: string;
  renderCell: (row: Row) => ReactNode;
}

export type RecordTableColumn<Row> = RecordTitleColumn<Row> | RecordValueColumn<Row>;

interface RecordSelection<Row> {
  getChecked: (row: Row) => boolean;
  getLabel: (row: Row) => string;
  onCheckedChange: (row: Row, checked: boolean) => void;
  isDisabled?: (row: Row) => boolean;
}

export type RecordTableState =
  | { kind: "loading"; label: string; lines?: number; showLabel?: boolean }
  | { kind: "empty" | "error"; message: ComponentProps<typeof EmptyState> };

interface RecordTableProps<Row, Key extends RowKey> {
  label: string;
  rows: readonly Row[];
  /** The title fills the remaining width and grows to 280px before agencies grow past 120px. */
  columns: readonly RecordTableColumn<Row>[];
  getKey: (row: Row) => Key;
  /** Omit row navigation and activation when titles are native links. */
  activeKey?: Key | null;
  onActivate?: (key: Key) => void;
  navigation?: RowKeyboardNavigation<Key>;
  viewportRef?: Ref<HTMLDivElement>;
  onScroll?: UIEventHandler<HTMLDivElement>;
  className?: string;
  rowClassName?: string | ((row: Row) => string);
  getRowLabel?: (row: Row) => string;
  getRowTitle?: (row: Row) => string | undefined;
  onRowKeyDown?: (event: KeyboardEvent<HTMLTableRowElement>, row: Row) => void;
  isRowDisabled?: (row: Row) => boolean;
  selection?: RecordSelection<Row>;
  state?: RecordTableState;
}

const SELECTION_WIDTH = 36;
const MIN_TITLE_WIDTH = 180;
const PREFERRED_TITLE_WIDTH = 280;
const PREFERRED_AGENCY_WIDTH = 120;
const MAX_AGENCY_WIDTH = 200;
const INTERACTIVE = "a,button,input,select,textarea,[contenteditable]";

export function RecordTable<Row, Key extends RowKey>({
  label, rows, columns, getKey, activeKey, onActivate, navigation,
  viewportRef, onScroll, className, rowClassName, getRowLabel, getRowTitle, onRowKeyDown, isRowDisabled,
  selection, state,
}: RecordTableProps<Row, Key>) {
  const minWidth = columns.reduce(
    (width, column) => width + ("width" in column ? column.width : MIN_TITLE_WIDTH),
    selection ? SELECTION_WIDTH : 0,
  );
  // Keep 180px for title text after padding as the agency column narrows.
  const titleInsets = columns.some((column) => "width" in column && column.grow)
    ? `${selection ? "var(--spacing-2)" : "var(--record-inset, var(--spacing-6))"} + var(--spacing-2)`
    : "0px";
  function valueColumnWidth(column: RecordValueColumn<Row>) {
    if (!column.grow) return column.width;
    const fixedWidth = minWidth - column.width - MIN_TITLE_WIDTH;
    const compact = `calc(100cqi - ${fixedWidth + MIN_TITLE_WIDTH}px - (${titleInsets}))`;
    const spacious = `calc(100cqi - ${fixedWidth + PREFERRED_TITLE_WIDTH}px)`;
    return `clamp(${column.width}px, max(min(${PREFERRED_AGENCY_WIDTH}px, ${compact}), ${spacious}), ${MAX_AGENCY_WIDTH}px)`;
  }
  return (
    <ReviewListViewport
      className={["record-table-viewport", className].filter(Boolean).join(" ")}
      onKeyDown={navigation?.onKeyDown}
      onPointerDownCapture={navigation?.onPointerDownCapture}
      onScroll={onScroll}
      ref={viewportRef}
    >
      {state ? (
        <div className="record-table-state">
          {state.kind === "loading" ? (
            state.showLabel ? (
              <div role="status">
                <p>{state.label}</p>
                <SkeletonBlock label={null} lines={state.lines ?? 5} />
              </div>
            ) : <SkeletonBlock label={state.label} lines={state.lines ?? 5} />
          ) : <EmptyState compact {...state.message} tone={state.kind === "error" ? "error" : state.message.tone} />}
        </div>
      ) : (
        <Table
          aria-label={label}
          className="record-table"
          density="compact"
          dividers="rows"
          hasHover={onActivate !== undefined}
          style={{ minWidth: `calc(${minWidth}px + ${titleInsets})` }}
          verticalAlign="top"
          plugins={{
            // The viewport above scrolls on both axes and owns keyboard navigation.
            viewport: { transformScrollWrapper: (props) => ({
              ...props,
              htmlProps: { ...props.htmlProps, tabIndex: -1 },
            }) },
          }}
        >
          <colgroup>
            {selection ? <col style={{ width: SELECTION_WIDTH }} /> : null}
            {columns.map((column) => (
              <col key={column.key} style={"width" in column ? { width: valueColumnWidth(column) } : undefined} />
            ))}
          </colgroup>
          <TableHeader>
            <TableRow isHeaderRow>
              {selection ? <TableHeaderCell className="record-table-check" scope="col"><span className="visually-hidden">선택</span></TableHeaderCell> : null}
              {columns.map((column) => (
                <TableHeaderCell className={"width" in column ? ["record-table-value", column.numeric && "record-table-number"].filter(Boolean).join(" ") : undefined} key={column.key} scope="col">
                  {column.header}
                </TableHeaderCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const key = getKey(row);
              const active = key === activeKey;
              const disabled = isRowDisabled?.(row) ?? false;
              const checkDisabled = disabled || selection?.isDisabled?.(row);
              const checked = selection?.getChecked(row) ?? false;
              const rowProps = navigation?.rowProps(key);
              // Astryx forwards native row attributes but omits title from TableRowProps.
              const rowTooltip: Pick<ComponentProps<"tr">, "title"> = { title: getRowTitle?.(row) };

              function handleKeyDown(event: KeyboardEvent<HTMLTableRowElement>) {
                // Let the native checkbox handle its own Space and change events.
                if (event.target !== event.currentTarget) {
                  if (selection && event.target instanceof Element && event.target.closest(INTERACTIVE)) {
                    event.stopPropagation();
                  }
                  return;
                }
                onRowKeyDown?.(event, row);
                if (event.defaultPrevented || disabled || event.nativeEvent.isComposing
                  || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
                if (event.key === " " && selection) {
                  if (!active || checkDisabled) return;
                  event.preventDefault();
                  if (!event.repeat) selection.onCheckedChange(row, !checked);
                } else if (onActivate && (event.key === "Enter" || event.key === " ")) {
                  event.preventDefault();
                  onActivate(key);
                }
              }

              return (
                <TableRow
                  {...rowProps}
                  {...rowTooltip}
                  aria-current={active ? "true" : undefined}
                  aria-disabled={disabled || undefined}
                  aria-label={getRowLabel?.(row)}
                  className={typeof rowClassName === "function" ? rowClassName(row) : rowClassName}
                  data-checked={selection ? String(checked) : undefined}
                  key={key}
                  onClick={onActivate ? (event) => {
                    if (disabled || (event.target instanceof Element && event.target.closest(INTERACTIVE))) return;
                    onActivate(key);
                  } : undefined}
                  onKeyDown={onActivate || onRowKeyDown || selection ? handleKeyDown : undefined}
                >
                  {selection ? (
                    <TableCell className="record-table-check">
                      <input
                        aria-label={selection.getLabel(row)}
                        checked={checked}
                        data-checked={checked ? "true" : "false"}
                        disabled={checkDisabled}
                        onChange={(event) => selection.onCheckedChange(row, event.currentTarget.checked)}
                        type="checkbox"
                      />
                    </TableCell>
                  ) : null}
                  {columns.map((column) => {
                    if ("title" in column) {
                      const title = column.title(row);
                      return (
                        <TableCell key={column.key}>
                          <span className={["record-table-title", column.titleClassName].filter(Boolean).join(" ")} title={title}>
                            {column.renderTitle ? column.renderTitle(row, title) : title}
                          </span>
                          {column.renderBelow?.(row)}
                        </TableCell>
                      );
                    }
                    const value = column.renderCell(row);
                    return (
                      <TableCell className={["record-table-value", column.numeric && "record-table-number", column.className].filter(Boolean).join(" ")} key={column.key}>
                        {column.ellipsis && typeof value === "string"
                          ? <span className="record-table-ellipsis" title={value}>{value}</span>
                          : value}
                      </TableCell>
                    );
                  })}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </ReviewListViewport>
  );
}
