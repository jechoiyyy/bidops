import type { Key, ReactNode } from "react";
import { EmptyState } from "./EmptyState";

export interface DataTableColumn<T> {
  key: string;
  header: string;
  className?: string;
  render?: (row: T, index: number) => ReactNode;
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: keyof T | ((row: T, index: number) => Key);
  emptyTitle?: string;
}

function valueOrFallback(value: ReactNode): ReactNode {
  if (value === null || value === undefined || value === "") return "값 없음";
  if (typeof value === "boolean") return value ? "예" : "아니오";
  return value;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  emptyTitle = "표시할 데이터가 없습니다.",
}: DataTableProps<T>) {
  if (rows.length === 0) return <EmptyState title={emptyTitle} compact />;

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th className={column.className} key={column.key} scope="col">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const key = typeof rowKey === "function" ? rowKey(row, index) : String(row[rowKey]);
            return (
              <tr key={key}>
                {columns.map((column) => (
                  <td className={column.className} key={column.key}>
                    {valueOrFallback(column.render ? column.render(row, index) : row[column.key as keyof T] as ReactNode)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
