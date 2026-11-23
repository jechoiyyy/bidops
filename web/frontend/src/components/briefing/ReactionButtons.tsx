import type { BriefingItemView, BriefingReaction } from "../../lib/types";

/*
 * 추천 항목의 반응 버튼 3개(최종 시안 `docs/1119_kstyle-shell/mockups/FinalBriefing.dc.html`).
 * 행 안에 채택 · 나중에 · 무시 순서로 둔다. 마감 전 묶음의 채택은 주 버튼(브랜드 채움),
 * 그 밖의 묶음은 옅은 채움이다.
 *
 * 선택한 버튼은 `aria-pressed`로 말한다. 이미 선택된 버튼을 다시 누르면 `대기`로 돌아간다(토글).
 * 반응은 추적 상태를 바꾸지 않는다 — 추적 결정은 별도 화면의 사람 결정이다(ux-review 결정 3).
 *
 * 저장 중에도 native disabled를 쓰지 않는다: 눌린 버튼이 disabled가 되면 초점이 사라져
 * 키보드 흐름이 끊긴다. 중복 저장은 호출자의 잠금이 막고, 여기서는 `aria-busy`로만 알린다.
 */

export const REACTION_BUTTONS: ReadonlyArray<{ reaction: BriefingReaction; label: string; shortcut: string; tone: "accept" | "later" | "ignore" }> = [
  { reaction: "채택", label: "채택", shortcut: "1", tone: "accept" },
  { reaction: "나중에", label: "나중에", shortcut: "H", tone: "later" },
  { reaction: "무시", label: "무시", shortcut: "2", tone: "ignore" },
];

interface ReactionButtonsProps {
  item: BriefingItemView;
  busy: boolean;
  /** 마감 전 묶음이면 채택이 주 버튼이다. */
  emphasis?: boolean;
  /** 눌린 버튼의 반응을 넘긴다. 이미 선택된 버튼이면 호출자가 `대기`로 바꾼다. */
  onReact: (item: BriefingItemView, reaction: BriefingReaction) => void;
}

export function ReactionButtons({ item, busy, emphasis = false, onReact }: ReactionButtonsProps) {
  // 추적 변화 행은 반응이 없다(`reaction=null`). 버튼 자체를 그리지 않는다.
  if (item.kind !== "recommendation" || item.reaction === null) return null;
  return (
    <div aria-busy={busy} aria-label={`${item.title} 반응`} className="briefing-reactions" role="group">
      {REACTION_BUTTONS.map(({ reaction, label, shortcut, tone }) => {
        const on = item.reaction === reaction;
        return (
          <button
            aria-keyshortcuts={shortcut}
            aria-pressed={on}
            className={`briefing-reaction is-${tone}${tone === "accept" && emphasis ? " is-primary" : ""}`}
            data-reaction={reaction}
            key={reaction}
            onClick={() => onReact(item, reaction)}
            type="button"
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
