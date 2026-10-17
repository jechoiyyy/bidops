import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { initialOf, type OpenAction } from "../../lib/record";

/*
 * 다음 행동(좌측): 완료되지 않은 다음 행동 목록(체크 + 머리글자), 최대 5건 + `모두 보기`.
 * 체크하면 서버에 완료를 저장하고 다시 읽는다. 저장 전에는 체크를 확정으로 그리지 않는다.
 *
 * 머리글자는 담당 이름이다. 활동 응답은 `action_added`의 `detail`에 "담당 <이름>"을 싣는다
 * (run rla-20261016 결정 #14). 그 형식이 아니면 기록자(`actor`)의 머리글자로 대신한다.
 */

function ownerOf(action: OpenAction): string | null {
  const match = action.detail ? /^담당 (.+)$/.exec(action.detail.trim()) : null;
  return match ? match[1] : null;
}

export const NEXT_ACTION_LIMIT = 5;

interface NextActionsProps {
  actions: readonly OpenAction[];
  /** 활동 피드에 다음 행동 사건이 하나라도 있으면 `모두 보기`를 둔다(완료 이력까지 본다). */
  hasHistory: boolean;
  loading: boolean;
  failed: boolean;
  pendingNoteId: string | null;
  onComplete: (noteId: string) => void;
  onShowAll: () => void;
}

export function NextActions({ actions, hasHistory, loading, failed, pendingNoteId, onComplete, onShowAll }: NextActionsProps) {
  const shown = actions.slice(0, NEXT_ACTION_LIMIT);
  return (
    <section aria-labelledby="rec-next-title" className="rec-side-block" data-testid="next-actions">
      <h3 className="rec-side-title" id="rec-next-title">다음 행동</h3>
      {loading ? <p className="rec-side-note" role="status">불러오는 중…</p> : null}
      {failed ? <p className="rec-side-note">다음 행동을 불러오지 못했습니다. 없다는 뜻이 아닙니다.</p> : null}
      {!loading && !failed && shown.length === 0 ? <p className="rec-side-note">남은 다음 행동이 없습니다.</p> : null}
      {shown.length > 0 ? (
        <ul className="rec-next-list">
          {shown.map((action) => {
            const owner = ownerOf(action);
            return (
            <li className="rec-next-item" key={action.noteId}>
              <span aria-hidden="true" className="rec-avatar" title={owner ? `담당 ${owner}` : action.actor ? `기록자 ${action.actor}` : undefined}>
                {initialOf(owner ?? action.actor)}
              </span>
              <div className="rec-next-main">
                {/* 저장이 끝나기 전에는 완료로 확정하지 않는다: 저장 중에만 체크로 보이고 실패하면 풀린다. */}
                <CheckboxInput
                  isDisabled={pendingNoteId === action.noteId}
                  label={action.body}
                  onChange={(checked) => { if (checked) onComplete(action.noteId); }}
                  value={pendingNoteId === action.noteId}
                />
                {action.detail ? <p className="rec-side-note">{action.detail}</p> : null}
              </div>
            </li>
            );
          })}
        </ul>
      ) : null}
      {actions.length > NEXT_ACTION_LIMIT ? (
        <p className="rec-side-note">남은 다음 행동 {actions.length}건 중 {NEXT_ACTION_LIMIT}건을 보여 줍니다.</p>
      ) : null}
      {hasHistory ? (
        <Button label="모두 보기" onClick={onShowAll} size="sm" variant="ghost" />
      ) : null}
    </section>
  );
}
