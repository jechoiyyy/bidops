import { StatusMark } from "../common/Marks";
import { agencyText, amountText, changeFieldLabel, deadlineText, stageLabel, verdictTone } from "../../lib/briefing";
import type { BriefingItemView, BriefingReaction } from "../../lib/types";
import { RecordTable, type RecordTableColumn } from "../common/RecordTable";
import type { RowKeyboardNavigation } from "../common/useRowKeyboardNavigation";
import { ReactionButtons } from "./ReactionButtons";

interface BriefingTableProps {
  label: string;
  items: readonly BriefingItemView[];
  selectedId: string | null;
  navigation: RowKeyboardNavigation<string>;
  onSelect: (itemId: string) => void;
  onOpen: (item: BriefingItemView) => void;
  emphasis?: boolean;
  busy: boolean;
  onReact: (item: BriefingItemView, reaction: BriefingReaction) => void;
}

export function BriefingTable({ label, items, selectedId, navigation, onSelect, onOpen, emphasis = false, busy, onReact }: BriefingTableProps) {
  const columns: RecordTableColumn<BriefingItemView>[] = [
    {
      key: "title", header: "사업명", title: (item) => item.title, titleClassName: "briefing-row-title",
      renderBelow: (item) => (
        <>
          <ul aria-label="사업 요약" className="briefing-row-sub briefing-row-facts" role="list">
            <li className="briefing-row-stage">{stageLabel(item.stage)}</li>
            <li className="briefing-row-amount">{amountText(item.amount_krw)}</li>
            <li data-item-id={item.item_id}>
              <StatusMark className="briefing-row-verdict" mark={{ label: item.verdict_display, tone: verdictTone(item.verdict_display) }} />
            </li>
          </ul>
          {item.kind === "tracked_change" && item.change_fields.length > 0 ? (
            <span className="briefing-row-sub">바뀐 항목 · {item.change_fields.map(changeFieldLabel).join(", ")}</span>
          ) : null}
        </>
      ),
    },
    {
      key: "agency", header: "발주기관", width: 98, ellipsis: true, className: "briefing-row-agency",
      renderCell: (item) => agencyText(item.agency),
    },
    {
      key: "reaction", header: "반응", width: 155,
      renderCell: (item) => item.kind === "tracked_change" || item.reaction === null
        ? <span className="briefing-none">반응 없음</span>
        : <ReactionButtons busy={busy} emphasis={emphasis} item={item} onReact={onReact} />,
    },
    {
      key: "deadline", header: "마감", width: 160,
      renderCell: (item) => {
        const deadline = deadlineText(item);
        return (
          <span className="briefing-deadline" data-urgent={deadline.dday !== null ? "true" : "false"}>
            {deadline.dday ? <><strong className="briefing-dday-text">{deadline.dday}</strong> · </> : null}
            {deadline.rest}
          </span>
        );
      },
    },
  ];

  return (
    <RecordTable
      activeKey={selectedId}
      className="briefing-table"
      columns={columns}
      getKey={(item) => item.item_id}
      label={label}
      navigation={navigation}
      onActivate={onSelect}
      onRowKeyDown={(event, item) => {
        if (event.key !== "Enter" || event.ctrlKey || event.metaKey || event.altKey || event.nativeEvent.isComposing) return;
        event.preventDefault();
        onOpen(item);
      }}
      rowClassName="briefing-row"
      rows={items}
      viewportRef={null}
    />
  );
}
