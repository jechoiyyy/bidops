import type { MouseEvent as ReactMouseEvent } from "react";
import { changeFieldLabel, deadlineText, itemSubline, stageLabel, verdictTone } from "../../lib/briefing";
import type { BriefingItemView, BriefingReaction } from "../../lib/types";
import type { RowKeyboardNavigationRowProps } from "../common/useRowKeyboardNavigation";
import { ReactionButtons } from "./ReactionButtons";

/*
 * 브리핑 행 묶음(최종 시안 `docs/1119_kstyle-shell/mockups/FinalBriefing.dc.html`).
 *
 * 행 = 공고(제목 + 기관 · 금액 · 판정 이름) · 단계(글자) · 마감(글자, 마감 전은 굵은 D-n) · 반응 버튼 3개.
 * 묶음 안에서 행은 옅은 선으로 나뉘고, 마감 전 묶음은 채움 바탕으로 강조한다. 단계·마감은
 * 표식이 아니라 글자다. 판정 이름·반응 기록은 행을 고르면 열리는 피크가 보인다.
 *
 * - 추적 변화 행은 반응이 없으므로 버튼 대신 `반응 없음` 글자만 둔다.
 * - 선택은 URL(`?selected=`)이 정본이다. 행의 첫 칸 버튼이 키보드 이동의 `rowProps`를 받는다.
 */

interface BriefingTableProps {
  /** 묶음의 접근 이름(시각 제목과 같은 말). */
  label: string;
  items: readonly BriefingItemView[];
  selectedId: string | null;
  rowProps: (key: string) => RowKeyboardNavigationRowProps;
  onSelect: (itemId: string) => void;
  /** 추적 변화 묶음이면 true(반응 버튼이 없다). */
  tracked?: boolean;
  /** 마감 전 묶음이면 true(채움 바탕 + 채택 주 버튼). */
  emphasis?: boolean;
  busy: boolean;
  onReact: (item: BriefingItemView, reaction: BriefingReaction) => void;
}

export function BriefingTable({ label, items, selectedId, rowProps, onSelect, tracked = false, emphasis = false, busy, onReact }: BriefingTableProps) {
  return (
    <ul aria-label={label} className={`briefing-rows${emphasis ? " is-emphasis" : ""}`}>
      {items.map((item) => {
        const selected = item.item_id === selectedId;
        const deadline = deadlineText(item);
        const onClick = (event: ReactMouseEvent<HTMLLIElement>) => {
          // 버튼·링크를 직접 누른 경우는 그쪽이 처리한다. 행의 빈 곳을 누르면 선택만 한다.
          if ((event.target as HTMLElement).closest("button, a, input")) return;
          onSelect(item.item_id);
        };
        return (
          <li
            className={`briefing-row${tracked ? " is-tracked" : ""}${selected ? " is-selected" : ""}`}
            data-item-id={item.item_id}
            data-kind={item.kind}
            data-selected={selected ? "true" : "false"}
            key={item.item_id}
            onClick={onClick}
          >
            <button
              aria-current={selected ? "true" : undefined}
              className="briefing-row-main"
              onClick={() => onSelect(item.item_id)}
              type="button"
              {...rowProps(item.item_id)}
            >
              <span className="briefing-row-title">{item.title}</span>
              {/* 판정 이름은 서버 글자 그대로이며 표식이 아니라 보조 줄의 글자다(색은 의미색, 글자가 함께 말한다). */}
              <span className="briefing-row-sub">
                {itemSubline(item)} · <span className={`briefing-row-verdict is-verdict-${verdictTone(item.verdict_display)}`}>{item.verdict_display}</span>
              </span>
              {tracked && item.change_fields.length > 0 ? (
                <span className="briefing-row-sub">바뀐 항목 · {item.change_fields.map(changeFieldLabel).join(", ")}</span>
              ) : null}
            </button>
            <span className="briefing-row-stage">{stageLabel(item.stage)}</span>
            <span className="briefing-deadline" data-urgent={deadline.dday !== null ? "true" : "false"}>
              {deadline.dday ? <><strong className="briefing-dday-text">{deadline.dday}</strong> · </> : null}
              {deadline.rest}
            </span>
            <span className="briefing-row-actions">
              {tracked || item.reaction === null ? (
                <span className="briefing-none">반응 없음</span>
              ) : (
                <ReactionButtons busy={busy} emphasis={emphasis} item={item} onReact={onReact} />
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
