import { Button } from "@astryxdesign/core/Button";
import type { VerdictFeedbackKind, VerdictMatrixRow } from "../../lib/types";
import { mappingSuffix, pageRangeLabel, panelQuotes, requirementText, sourcePanelTitle } from "../../lib/verdict";

/*
 * 우측 원문 패널(ui-spec §3 `SourcePanel`, §4.4): 제목 "원문 · N쪽", 인용 2개 이내 `<mark>`, "쪽 전체
 * 보기", 행동 2개(요구사항 아님 · 원문과 다름).
 *
 * 쪽을 모르면(`mapping_status=unavailable`) 링크 없이 제목에 "쪽 미확인"을 적는다. 상속 쪽은 "(추정)"을
 * 붙인다. "쪽 전체 보기"는 문서 구조 id를 알 때만 열린다 — 서버가 주지 않은 id를 화면이 추정하지
 * 않는다. 인용은 서버가 원문 검증을 통과시킨 근거이고 화면은 글자를 고치지 않는다.
 */

interface SourcePanelProps {
  row: VerdictMatrixRow;
  /** 쪽 전체 보기가 읽을 문서 구조. 모르면 `null`이다. */
  structureId: string | null;
  onClose: () => void;
  onViewPage: () => void;
  onFeedback: (kind: Extract<VerdictFeedbackKind, "not_requirement" | "source_mismatch">) => void;
  /** 오류 제보를 보낼 판정 실행이 없으면 행동을 막는다. */
  feedbackDisabledReason: string | null;
}

export function SourcePanel({ row, structureId, onClose, onViewPage, onFeedback, feedbackDisabledReason }: SourcePanelProps) {
  const quotes = panelQuotes(row);
  const pageLabel = pageRangeLabel(row);
  const suffix = mappingSuffix(row);
  const pageBlockedReason = !pageLabel
    ? "쪽을 알 수 없어 열 수 없습니다"
    : structureId === null
      ? "문서 구조 정보가 없어 열 수 없습니다"
      : null;
  return (
    <aside aria-label="원문 패널" className="vd-source" data-testid="source-panel">
      <div className="vd-source-head">
        <h3 className="rec-side-title">
          {sourcePanelTitle(row)}
          {suffix ? <span className="vd-source-suffix"> {suffix}</span> : null}
        </h3>
        <Button aria-label="원문 패널 닫기" label="닫기" onClick={onClose} size="sm" variant="ghost" />
      </div>
      <p className="vd-source-requirement">{requirementText(row)}</p>
      {quotes.length === 0 ? (
        <p className="rec-side-note">서버가 연결한 원문 인용이 없습니다.</p>
      ) : (
        <ul aria-label="원문 인용" className="vd-quotes">
          {quotes.map((ref, index) => (
            <li key={index}>
              <blockquote className="vd-quote"><mark>{ref.quote}</mark></blockquote>
            </li>
          ))}
        </ul>
      )}
      <div className="vd-source-actions">
        <span title={pageBlockedReason ?? undefined}>
          <Button
            isDisabled={pageBlockedReason !== null}
            label="쪽 전체 보기"
            onClick={onViewPage}
            size="sm"
          />
        </span>
        {pageBlockedReason ? <p className="rec-side-note">{pageBlockedReason}</p> : null}
      </div>
      <div className="vd-source-feedback" role="group" aria-label="원문 제보">
        <Button
          isDisabled={feedbackDisabledReason !== null}
          label="요구사항 아님"
          onClick={() => onFeedback("not_requirement")}
          size="sm"
        />
        <Button
          isDisabled={feedbackDisabledReason !== null}
          label="원문과 다름"
          onClick={() => onFeedback("source_mismatch")}
          size="sm"
        />
        {feedbackDisabledReason ? <p className="rec-side-note">{feedbackDisabledReason}</p> : null}
      </div>
    </aside>
  );
}
