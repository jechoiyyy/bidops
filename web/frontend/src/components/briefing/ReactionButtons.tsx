import { Button } from "@astryxdesign/core/Button";
import type { BriefingItemView, BriefingReaction } from "../../lib/types";

/*
 * 추천 항목의 반응 버튼 3개(ui-spec §4.1 피크 패널). 볼게요 = `채택`, 무시, 나중에.
 *
 * 선택한 버튼은 primary(on 스타일)이고 `aria-pressed`로 말한다. 이미 선택된 버튼을 다시
 * 누르면 `대기`로 돌아간다(토글). 반응은 추적 상태를 바꾸지 않는다 — 추적 결정은 별도 화면의
 * 사람 결정이다(ux-review 결정 3).
 *
 * 저장 중에도 `isDisabled`를 쓰지 않는다: 눌린 버튼이 native disabled가 되면 초점이 사라져
 * 키보드 흐름이 끊긴다. 중복 저장은 호출자의 잠금이 막고, 여기서는 `aria-busy`로만 알린다.
 */

export const REACTION_BUTTONS: ReadonlyArray<{ reaction: BriefingReaction; label: string; shortcut: string }> = [
  { reaction: "채택", label: "볼게요", shortcut: "1" },
  { reaction: "무시", label: "무시", shortcut: "2" },
  { reaction: "나중에", label: "나중에", shortcut: "H" },
];

interface ReactionButtonsProps {
  item: BriefingItemView;
  busy: boolean;
  /** 눌린 버튼의 반응을 넘긴다. 이미 선택된 버튼이면 호출자가 `대기`로 바꾼다. */
  onReact: (item: BriefingItemView, reaction: BriefingReaction) => void;
}

export function ReactionButtons({ item, busy, onReact }: ReactionButtonsProps) {
  // 추적 변화 행은 반응이 없다(`reaction=null`). 버튼 자체를 그리지 않는다.
  if (item.kind !== "recommendation" || item.reaction === null) return null;
  return (
    <div aria-busy={busy} aria-label="반응" className="briefing-reactions" role="group">
      {REACTION_BUTTONS.map(({ reaction, label, shortcut }) => {
        const on = item.reaction === reaction;
        return (
          <Button
            aria-keyshortcuts={shortcut}
            aria-pressed={on}
            data-reaction={reaction}
            key={reaction}
            label={label}
            onClick={() => onReact(item, reaction)}
            size="sm"
            variant={on ? "primary" : "secondary"}
          />
        );
      })}
    </div>
  );
}
