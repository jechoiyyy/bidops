import { useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { TextArea } from "@astryxdesign/core/TextArea";
import { MutationFeedback } from "../common/MutationFeedback";
import type { ApiErrorDescription } from "../../lib/apiErrors";
import { SENTENCE_MAX, sourceKindLabel, sourceRefLabel } from "../../lib/proposal";
import type { ProposalSentence } from "../../lib/types";

/*
 * 선택한 문장의 인라인 수정 영역(ui-spec §4.5, RL-04 spec "저장"의 edit overlay).
 *
 * 저장은 append-only edit 한 건을 만든다 — 생성 원문은 바뀌지 않고 화면·PDF가 최신 edit을 덮어 보인다.
 * 이 영역은 문장의 출처도 함께 보여 준다(출처 종류 · 보조 표기 · 원문 인용). 요구사항 원문의 식별자는
 * 원문 hash를 포함할 수 있어 그리지 않고 인용문만 보인다. 글자 수는 1~400자이며 서버가 다시 검사한다.
 * 저장이 실패하면 입력을 그대로 두고 오류를 이 영역에 보인다.
 */

interface SentenceEditorProps {
  sentence: ProposalSentence;
  /** 성공이면 `null`, 실패면 이 영역에 보일 오류. */
  onSave: (text: string) => Promise<ApiErrorDescription | null>;
  onCancel: () => void;
  saving: boolean;
  /** 저장하지 않은 수정이 있는지 알린다(이탈 확인). 닫히면 `false`로 되돌린다. */
  onDirtyChange?: (dirty: boolean) => void;
}

function lengthOf(value: string): number {
  return [...value].length;
}

export function SentenceEditor({ sentence, onSave, onCancel, saving, onDirtyChange }: SentenceEditorProps) {
  const [text, setText] = useState(sentence.text);
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);

  const trimmed = text.trim();
  const length = lengthOf(text);
  const unchanged = trimmed === sentence.text.trim();

  useEffect(() => {
    onDirtyChange?.(!unchanged);
  }, [onDirtyChange, unchanged]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  const invalid = trimmed.length === 0 || length > SENTENCE_MAX;
  const reason = saving
    ? "저장하고 있습니다."
    : trimmed.length === 0
      ? "문장은 비워 둘 수 없습니다."
      : length > SENTENCE_MAX
        ? `문장은 ${SENTENCE_MAX}자까지입니다.`
        : unchanged
          ? "바뀐 내용이 없습니다."
          : null;

  const submit = async () => {
    if (invalid || unchanged || saving) return;
    setProblem(null);
    const failure = await onSave(trimmed);
    if (failure) setProblem(failure);
  };

  return (
    <section aria-label="문장 수정" className="pp-editor" data-testid="sentence-editor">
      {sentence.kind === "placeholder" ? (
        <p className="pp-editor-note" data-testid="editor-placeholder-note">
          비어 있는 자리입니다{sentence.placeholder_hint ? ` · 채울 것: ${sentence.placeholder_hint}` : ""}. 근거가 없어 비워 두었으므로 확인한 내용으로 직접 채우십시오.
        </p>
      ) : null}
      {sentence.kind === "proposed_figure" ? (
        <p className="pp-editor-note" data-testid="editor-figure-note">
          제안 수치입니다. 근거를 확인해 확정하거나 고치십시오.
        </p>
      ) : null}
      <TextArea
        hasAutoFocus
        isDisabled={saving}
        label="문장"
        maxLength={SENTENCE_MAX}
        onChange={(value) => { setText(value); setProblem(null); }}
        rows={3}
        value={text}
      />
      {problem ? (
        <MutationFeedback problem={problem} tone="error">
          <p>입력한 문장은 그대로 남아 있습니다. 저장되지 않았습니다.</p>
        </MutationFeedback>
      ) : null}
      <div className="pp-editor-actions">
        <Button isDisabled={saving} label="취소" onClick={onCancel} size="sm" />
        <Button
          aria-describedby={reason ? "pp-editor-reason" : undefined}
          isDisabled={invalid || unchanged || saving}
          label={saving ? "저장 중…" : "수정 저장"}
          onClick={() => { void submit(); }}
          size="sm"
          variant="primary"
        />
      </div>
      {reason ? <p className="rec-side-note" id="pp-editor-reason">{reason}</p> : null}

      <section aria-label="문장 출처" className="pp-sources" data-testid="sentence-sources">
        <h4 className="pp-sources-title">이 문장의 출처</h4>
        {sentence.sources.length === 0 ? (
          <p className="rec-side-note" data-testid="sources-empty">
            {sentence.kind === "placeholder" ? "출처가 없는 자리입니다. 사람이 채울 내용입니다." : "표시할 출처가 없습니다."}
          </p>
        ) : (
          <ul className="pp-source-list">
            {sentence.sources.map((source, index) => {
              const ref = sourceRefLabel(source.kind, source.ref);
              return (
                <li className="pp-source" data-kind={source.kind} key={index}>
                  <span className="pp-source-kind">{sourceKindLabel(source.kind)}{ref ? ` · ${ref}` : ""}</span>
                  <blockquote className="pp-source-quote">{source.quote}</blockquote>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </section>
  );
}
