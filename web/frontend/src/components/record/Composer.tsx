import type { KeyboardEvent } from "react";
import { Button } from "@astryxdesign/core/Button";
import { TextArea } from "@astryxdesign/core/TextArea";
import { ActorField } from "../common/ActorField";
import { MutationFeedback } from "../common/MutationFeedback";
import type { ApiErrorDescription } from "../../lib/apiErrors";
import type { OpportunityNoteKind } from "../../lib/types";

/*
 * 작성기(ui-spec §3): "노트 남기기…" TextArea + 버튼 `노트`·`다음 행동`. 다음 행동은 담당 이름을
 * 선택 입력으로 받는다(비우면 서버가 기록자로 채운다). ⌘/Ctrl+Enter는 `노트`로 저장한다.
 *
 * 저장은 화면이 아니라 서버가 확인한 뒤에만 반영한다. 저장에 실패하면 입력을 그대로 두고 저장되지
 * 않았다고 말한다. 담당자 이름은 감사 표식이며 로그인이나 신원 인증이 아니다. 노트 본문은 어떤
 * 모델 입력에도 쓰이지 않는다(RL-02 spec).
 */

export const NOTE_BODY_MAX = 2000;

interface ComposerProps {
  body: string;
  onBodyChange: (value: string) => void;
  owner: string;
  onOwnerChange: (value: string) => void;
  actorName: string;
  onActorChange: (value: string) => void;
  onSubmit: (kind: OpportunityNoteKind) => void;
  busy: boolean;
  problem: ApiErrorDescription | null;
  /** 이름이 비어 저장하지 못했을 때 켜진다. 입력칸 옆에 이유를 적는다. */
  actorMissing: boolean;
}

export const COMPOSER_ACTOR_ID = "record-actor";

export function Composer({
  body,
  onBodyChange,
  owner,
  onOwnerChange,
  actorName,
  onActorChange,
  onSubmit,
  busy,
  problem,
  actorMissing,
}: ComposerProps) {
  const empty = body.trim().length === 0;
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey) || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (!empty && !busy) onSubmit("note");
  };
  return (
    <section aria-label="노트 남기기" className="rec-composer">
      <div onKeyDown={onKeyDown}>
        <TextArea
          isLabelHidden
          label="노트 남기기"
          maxLength={NOTE_BODY_MAX}
          onChange={onBodyChange}
          placeholder="노트 남기기…"
          rows={3}
          value={body}
        />
      </div>
      <div className="rec-composer-bar">
        <div className="rec-composer-fields">
          <ActorField
            aria-invalid={actorMissing || undefined}
            autoComplete="off"
            description={actorMissing ? "담당자 이름을 입력한 뒤 저장하세요. 기록에 남는 이름이며 인증이 아닙니다." : "기록에 남는 이름이며 인증이 아닙니다."}
            id={COMPOSER_ACTOR_ID}
            label="담당자 이름"
            onChange={onActorChange}
            showRememberNote={false}
            value={actorName}
          />
          <label className="rec-owner">
            <span>담당</span>
            <input
              autoComplete="off"
              maxLength={128}
              onChange={(event) => onOwnerChange(event.target.value)}
              placeholder="다음 행동 담당 (선택)"
              value={owner}
            />
          </label>
        </div>
        <div className="rec-composer-buttons">
          <Button
            aria-keyshortcuts="Meta+Enter Control+Enter"
            isDisabled={empty || busy}
            label="노트"
            onClick={() => onSubmit("note")}
            size="sm"
            variant="primary"
          />
          <Button
            isDisabled={empty || busy}
            label="다음 행동"
            onClick={() => onSubmit("action")}
            size="sm"
          />
        </div>
      </div>
      {problem ? (
        <MutationFeedback problem={problem} tone="error">
          <p>저장되지 않았습니다. 입력한 내용은 그대로 남아 있습니다.</p>
        </MutationFeedback>
      ) : null}
    </section>
  );
}
