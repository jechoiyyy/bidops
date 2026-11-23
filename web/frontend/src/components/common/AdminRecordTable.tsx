import { useRef, type ReactNode } from "react";
import { EmptyState } from "./EmptyState";
import { StatusMark, type Mark } from "./Marks";
import { RecordTable, type RecordTableColumn, type RecordTableState } from "./RecordTable";
import { useRowKeyboardNavigation } from "./useRowKeyboardNavigation";

export function AdminListHeader({ title, count, children, toolsClassName }: {
  title: string;
  count: string;
  children?: ReactNode;
  toolsClassName?: string;
}) {
  return (
    <header className="review-list-head workbench-admin-list-head">
      <div className="workbench-admin-list-heading">
        <strong>{title}</strong>
        <span>{count}</span>
      </div>
      {children ? <div className={["workbench-admin-list-tools", toolsClassName].filter(Boolean).join(" ")}>{children}</div> : null}
    </header>
  );
}

export interface AdminRecord<Key extends string | number> {
  id: Key;
  title: string;
  subtitle?: string;
  meta?: string;
  status?: Mark;
  statusDescription?: string;
}

function adminColumns(identifierWidth: number): RecordTableColumn<AdminRecord<string | number>>[] {
  return [
    {
      key: "name", header: "이름", title: ({ title }) => title,
      renderBelow: ({ meta }) => meta ? <div className="record-table-note" title={meta}>{meta}</div> : null,
    },
    {
      key: "identifier", header: "구분·식별", width: identifierWidth, ellipsis: true,
      renderCell: ({ subtitle }) => subtitle ?? "값 없음",
    },
    {
      key: "status", header: "상태", width: 126,
      renderCell: ({ status, statusDescription }) => status
        ? <div className="record-table-status"><StatusMark mark={status} description={statusDescription} /></div>
        : "상태 값 없음",
    },
  ];
}

export function AdminRecordTable<Key extends string | number>({
  label, rows, selectedId, onSelect, state, identifierWidth = 154,
}: {
  label: string;
  rows: readonly AdminRecord<Key>[];
  selectedId: Key | null;
  onSelect: (id: Key) => void;
  state?: RecordTableState;
  identifierWidth?: number;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const navigation = useRowKeyboardNavigation({
    containerRef: viewportRef,
    keys: rows.map(({ id }) => id),
    selectedKey: selectedId,
    onSelect,
  });

  return (
    <>
      {rows.length > 0 && state?.kind === "error" ? <EmptyState compact {...state.message} tone="error" /> : null}
      <RecordTable
        activeKey={selectedId}
        className="workbench-admin-table"
        columns={adminColumns(identifierWidth)}
        getKey={(row: AdminRecord<Key>) => row.id}
        label={label}
        navigation={navigation}
        onActivate={onSelect}
        rows={rows}
        state={rows.length === 0 ? state : undefined}
        viewportRef={viewportRef}
      />
    </>
  );
}
