import { useEffect } from "react";
import { TriangleAlert } from "lucide-react";
import { HintedButton } from "./HintedButton";
import { SentenceEditor } from "./SentenceEditor";
import type { ApiErrorDescription } from "../../lib/apiErrors";
import { describeProposalRunCode } from "../../lib/apiErrors";
import {
  hasSectionBody,
  sectionLabel,
  sectionStatusLabel,
  sectionStatusTone,
} from "../../lib/proposal";
import type { ProposalSection, ProposalSectionKey, ProposalSentence } from "../../lib/types";

/*
 * 절 본문 카드(ui-spec §4.5): 세리프 14px/1.8, 최대 620px. 문장은 종류에 따라 다르게 보인다.
 *
 *   statement        본문 글자 + 작은 초록 위첨자 "출처"
 *   placeholder      근거가 없어 비워 둔 자리 — warning 바탕의 "[채울 것: 힌트]" (고치면 고친 글자 + "수정됨")
 *   proposed_figure  warning 바탕 글자 + "제안 수치" 표식(아이콘 + 글자) + 위첨자 "출처"
 *
 * 문장을 누르면 그 문장이 선택되고 아래에 수정 영역과 출처가 열린다. 수정한 문장에는 "수정됨" 표식이 붙는다.
 * 본문 하단 버튼은 문장 수정 · 이 절 다시 쓰기 · 검토 완료(주)다. 생성에 실패한 절은 본문 대신 "생성 실패"
 * 카드와 "다시 쓰기"를 보이고 다른 절은 그대로 검토할 수 있다. 문장·출처는 서버가 준 값 그대로다.
 */

interface SectionBodyProps {
  sectionKey: ProposalSectionKey;
  section: ProposalSection | null;
  /** 이전 초안(superseded)은 읽기만 한다. */
  readOnly: boolean;
  /** 초안이 검토 완료·제출 준비 단계면 절 다시 쓰기를 막는다(서버 409 `stage_transition_invalid`, 결정 B50). */
  rewriteLocked: boolean;
  busy: boolean;
  pendingAction: "create" | "regenerate" | "review" | "edit" | "export" | "ready" | null;
  selectedSentenceId: string | null;
  onSelectSentence: (sentenceId: string | null) => void;
  onSaveSentence: (sentenceId: string, text: string) => Promise<ApiErrorDescription | null>;
  onRegenerate: () => void;
  onReview: () => void;
  focusedParagraphId: string | null;
  onDirtyChange?: (dirty: boolean) => void;
}

function paragraphElementId(paragraphId: string): string {
  return `pp-paragraph-${paragraphId}`;
}

function SentenceMarks({ sentence }: { sentence: ProposalSentence }) {
  return (
    <>
      {sentence.kind === "proposed_figure" ? (
        <span className="pp-mark" data-mark="figure">
          <TriangleAlert aria-hidden="true" />
          제안 수치
        </span>
      ) : null}
      {sentence.kind !== "placeholder" && sentence.sources.length > 0 ? (
        <sup className="pp-src" data-mark="source">
          출처<span className="visually-hidden"> {sentence.sources.length}건</span>
        </sup>
      ) : null}
      {sentence.edited ? <span className="pp-edited" data-mark="edited">수정됨</span> : null}
    </>
  );
}

function SentenceButton({
  sentence,
  selected,
  readOnly,
  onSelect,
}: {
  sentence: ProposalSentence;
  selected: boolean;
  readOnly: boolean;
  onSelect: () => void;
}) {
  const empty = sentence.kind === "placeholder" && !sentence.edited;
  const hint = sentence.placeholder_hint?.trim();
  return (
    <>
      <button
        aria-pressed={selected}
        className={`pp-sentence is-${sentence.kind}${selected ? " is-selected" : ""}${sentence.edited ? " is-edited" : ""}`}
        data-kind={sentence.kind}
        data-edited={sentence.edited ? "true" : undefined}
        disabled={readOnly}
        onClick={onSelect}
        type="button"
      >
        {empty ? (
          <span className="pp-gap" data-testid="placeholder-slot">{hint ? `[채울 것: ${hint}]` : "[채울 것]"}</span>
        ) : (
          <span className="pp-text">{sentence.text}</span>
        )}
        <SentenceMarks sentence={sentence} />
      </button>{" "}
    </>
  );
}

export function SectionBody({
  sectionKey,
  section,
  readOnly,
  rewriteLocked,
  busy,
  pendingAction,
  selectedSentenceId,
  onSelectSentence,
  onSaveSentence,
  onRegenerate,
  onReview,
  focusedParagraphId,
  onDirtyChange,
}: SectionBodyProps) {
  // 요구사항 표에서 "문단으로 이동"을 누르면 그 문단이 보이는 자리로 옮긴다.
  useEffect(() => {
    if (focusedParagraphId === null) return;
    document.getElementById(paragraphElementId(focusedParagraphId))?.scrollIntoView?.({ block: "center" });
  }, [focusedParagraphId]);

  const title = sectionLabel(sectionKey);

  if (section === null) {
    return (
      <article aria-label="절 본문" className="pp-card" data-section={sectionKey}>
        <h3 className="pp-card-title">{title}</h3>
        <p className="pp-card-note" role="status">이 절의 정보가 아직 없습니다.</p>
      </article>
    );
  }

  const statusPill = (
    <span className={`vd-pill is-${sectionStatusTone(section.status)}`} data-testid="section-status">
      {sectionStatusLabel(section.status)}
    </span>
  );
  const head = (
    <header className="pp-card-head">
      <h3 className="pp-card-title">{title}</h3>
      {statusPill}
      {section.revision > 1 ? <span className="pp-card-revision">다시 쓴 버전 {section.revision}</span> : null}
    </header>
  );

  if (section.status === "queued" || section.status === "running") {
    return (
      <article aria-label="절 본문" className="pp-card" data-section={sectionKey} data-status={section.status}>
        {head}
        <p className="pp-card-note" data-testid="section-progress" role="status">
          {section.status === "queued"
            ? "이 절은 생성을 기다리고 있습니다. 순서가 되면 자동으로 만들어지고 이 화면에 나타납니다."
            : "이 절을 만드는 중입니다. 끝나면 자동으로 이 화면에 나타납니다."}
        </p>
      </article>
    );
  }

  if (section.status === "failed") {
    const run = describeProposalRunCode(section.error_code);
    return (
      <article aria-label="절 본문" className="pp-card is-failed" data-section={sectionKey} data-status="failed">
        {head}
        <div className="pp-failed" data-testid="section-failed">
          <strong>생성 실패</strong>
          {run ? (
            <p>
              {run.title}
              {run.detail ? ` ${run.detail}` : ""}
              {run.code ? <span className="vd-code"> 오류 코드 {run.code}</span> : null}
            </p>
          ) : (
            <p>이 절은 만들어지지 않았습니다. 자동으로 고치지 않습니다.</p>
          )}
          <p className="rec-side-note">다시 쓰기로 새 버전을 요청하거나 사람이 직접 작성하십시오. 다른 절은 그대로 검토할 수 있습니다.</p>
          <div className="pp-toolbar">
            <HintedButton
              blockedReason={readOnly ? "이전 초안은 바꿀 수 없습니다" : busy ? "처리 중입니다" : null}
              label="다시 쓰기"
              onClick={onRegenerate}
              pendingLabel={pendingAction === "regenerate" ? "요청 중…" : null}
              variant="primary"
            />
          </div>
        </div>
      </article>
    );
  }

  const body = hasSectionBody(section) ? section : null;
  const selected = body?.paragraphs.flatMap((paragraph) => paragraph.sentences).find((sentence) => sentence.sentence_id === selectedSentenceId) ?? null;

  const focusEditor = () => {
    const field = document.querySelector<HTMLTextAreaElement>('[data-testid="sentence-editor"] textarea');
    field?.focus();
  };

  return (
    <article
      aria-label="절 본문"
      className="pp-card"
      data-revision={section.revision}
      data-section={sectionKey}
      data-status={section.status}
    >
      {head}
      {body && body.paragraphs.length === 0 ? (
        <p className="pp-card-note" role="status">이 절에는 문장이 없습니다.</p>
      ) : null}
      {body?.paragraphs.map((paragraph) => {
        const hasSelected = paragraph.sentences.some((sentence) => sentence.sentence_id === selectedSentenceId);
        return (
          <div
            className={`pp-paragraph${focusedParagraphId === paragraph.paragraph_id ? " is-focused" : ""}`}
            data-paragraph-id={paragraph.paragraph_id}
            id={paragraphElementId(paragraph.paragraph_id)}
            key={paragraph.paragraph_id}
          >
            {paragraph.heading ? <h4 className="pp-paragraph-heading">{paragraph.heading}</h4> : null}
            <p className="pp-sentences">
              {paragraph.sentences.map((sentence) => (
                <SentenceButton
                  key={sentence.sentence_id}
                  onSelect={() => onSelectSentence(sentence.sentence_id === selectedSentenceId ? null : sentence.sentence_id)}
                  readOnly={readOnly}
                  selected={sentence.sentence_id === selectedSentenceId}
                  sentence={sentence}
                />
              ))}
            </p>
            {hasSelected && selected ? (
              <SentenceEditor
                key={selected.sentence_id}
                onDirtyChange={onDirtyChange}
                onCancel={() => onSelectSentence(null)}
                onSave={async (text) => {
                  const failure = await onSaveSentence(selected.sentence_id, text);
                  if (!failure) onSelectSentence(null);
                  return failure;
                }}
                saving={pendingAction === "edit"}
                sentence={selected}
              />
            ) : null}
          </div>
        );
      })}
      <div className="pp-toolbar" data-testid="section-toolbar">
        <HintedButton
          blockedReason={readOnly ? "이전 초안은 바꿀 수 없습니다" : selected ? null : "고칠 문장을 먼저 선택하십시오"}
          label="문장 수정"
          onClick={focusEditor}
        />
        <HintedButton
          blockedReason={
            readOnly
              ? "이전 초안은 바꿀 수 없습니다"
              : rewriteLocked
                ? "검토 완료 뒤에는 새 초안으로 다시 만듭니다"
                : busy
                  ? "처리 중입니다"
                  : null
          }
          label="이 절 다시 쓰기"
          onClick={onRegenerate}
          pendingLabel={pendingAction === "regenerate" ? "요청 중…" : null}
        />
        <HintedButton
          blockedReason={
            readOnly
              ? "이전 초안은 바꿀 수 없습니다"
              : section.status === "reviewed"
                ? "이미 검토 완료로 표시했습니다"
                : busy
                  ? "처리 중입니다"
                  : null
          }
          label="검토 완료"
          onClick={onReview}
          pendingLabel={pendingAction === "review" ? "표시 중…" : null}
          variant="primary"
        />
      </div>
    </article>
  );
}
