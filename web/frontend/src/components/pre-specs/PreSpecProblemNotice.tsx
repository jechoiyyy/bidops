import { useId, useState, type ReactNode } from "react";
import { api } from "../../lib/api";
import type { PreSpecProblemAction, PreSpecProblemNotice as Notice, PreSpecProblemTone } from "../../lib/preSpecProblemNotice";

const TAG_CLASS: Record<PreSpecProblemTone, string> = {
  error: "ps-chip-err",
  warning: "ps-chip-warn",
  neutral: "ps-chip-neutral",
};

/**
 * 사전규격 상세 `사업 개요와 주요 과업` 맨 위의 문제 상태 안내(2026-11-21 시안 `docs/specs/1121_prespec-detail/` c1~c5).
 *
 * 회색 채움 한 블록이다(네 변 테두리·왼쪽 굵은 선 없음): 상태 단어 + 무슨 일인지(굵게) → `이유` → (맞지 않는 문장) →
 * `할 일` → 조작 → 원 사유 코드(작게). 문장과 조작 종류는 `lib/preSpecProblemNotice.ts`가 정하고 여기서는 그리기만 한다.
 * 조작은 보조 버튼·글자 링크뿐이다 — 화면의 주 버튼은 하단 결정 띠 하나다.
 */
export function PreSpecProblemNotice({
  notice,
  noticeId,
  rangeForm,
  onOpenDocuments,
}: {
  notice: Notice;
  noticeId: number;
  /** 범위 확정 폼(`PageOverviewRangeReview` `presentation="notice"`). 안내가 폼을 쓰지 않으면 그리지 않는다. */
  rangeForm: ReactNode;
  onOpenDocuments: () => void;
}) {
  const leadId = useId();
  const rangeId = useId();
  const [rangeOpen, setRangeOpen] = useState(false);
  const formInline = notice.actions.some((action) => action.kind === "range_form");
  const formToggle = notice.actions.some((action) => action.kind === "range_form_toggle");
  const showRange = rangeForm !== null && (formInline || (formToggle && rangeOpen));
  const buttons = notice.actions.filter((action) => action.kind !== "range_form");

  const renderAction = (action: PreSpecProblemAction) => {
    switch (action.kind) {
      case "pdf_page":
        // 완료 개요의 `PDF n페이지 ↗`와 같은 주소(이 run이 읽은 고정 스냅샷 PDF)다.
        return (
          <a key={`pdf-${action.page}`} className="ps-btn ps-btn-sm" href={`${api.preSpecOverviewRunPdfUrl(noticeId, action.runId)}#page=${action.page}`} target="_blank" rel="noreferrer">
            PDF {action.page}페이지 열기 ↗
          </a>
        );
      case "range_form_toggle":
        return rangeForm === null ? null : (
          <button
            key="range-toggle"
            className="ps-ref"
            type="button"
            aria-expanded={rangeOpen}
            aria-controls={rangeOpen ? rangeId : undefined}
            onClick={() => setRangeOpen(!rangeOpen)}
          >
            {rangeOpen ? "범위 입력 닫기" : "다른 범위로 다시 실행하기"}
          </button>
        );
      case "open_documents":
        return <button key="documents" className="ps-btn ps-btn-sm" type="button" onClick={onOpenDocuments}>문서 준비 열기</button>;
      case "attachment_original":
        return <a key="original" className="ps-btn ps-btn-sm" href={action.url} target="_blank" rel="noopener noreferrer">원본 열기 ↗</a>;
      case "evidence_section":
        return <a key="evidence" className="ps-ref" href="#ps-evidence">원문·첨부에서 첨부 보기</a>;
      default:
        // `range_form`은 위에서 걸렀다. 폼 자체가 조작이다.
        return null;
    }
  };

  return (
    <section
      className={`ps-problem-notice is-${notice.tone}`}
      aria-labelledby={leadId}
      data-kind={notice.kind}
      data-testid="pre-spec-problem-notice"
    >
      <p className="ps-problem-lead">
        <span className={`ps-chip ${TAG_CLASS[notice.tone]}`}>{notice.tag}</span>
        <strong id={leadId}>{notice.lead}</strong>
      </p>
      <p className="ps-problem-line">
        <span className="ps-problem-key">이유</span>
        <span className="ps-problem-text" data-testid="pre-spec-problem-reason">{notice.reason.join(" ")}</span>
      </p>
      {notice.claims.length > 0 ? (
        <ul className="ps-problem-claims" aria-label="원문과 맞지 않는 문장">
          {notice.claims.map((claim) => (
            <li key={claim.claimId}>
              {/* 서버 `failed_claims[].text` 그대로다. 고쳐 쓰지 않는다. */}
              <blockquote>{claim.text}</blockquote>
              <p className="ps-problem-cap">
                {claim.pages.length > 0 ? `근거로 든 쪽 ${claim.pages.join("·")}쪽` : "근거로 든 쪽 없음"}
                {claim.reasonLabels.map((label) => ` · ${label}`).join("")}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="ps-problem-line">
        <span className="ps-problem-key">할 일</span>
        <span className="ps-problem-text" data-testid="pre-spec-problem-todo">{notice.todo}</span>
      </p>
      {buttons.length > 0 ? <div className="ps-problem-actions">{buttons.map((action) => renderAction(action))}</div> : null}
      {showRange ? (
        <div id={rangeId} className="ps-problem-range">
          {/* 종전 범위 폼 자리의 이름(`#ps-record-range`)을 그대로 쓴다. 저장·재조회 동작은 같다. */}
          <div id="ps-record-range" className="ps-record-range" tabIndex={-1}>
            {rangeForm}
          </div>
          {notice.rangeContext ? <p className="ps-problem-cap">{notice.rangeContext}</p> : null}
        </div>
      ) : null}
      <p className="ps-problem-codes" aria-label="사유 코드">{notice.codes.join(" · ")}</p>
    </section>
  );
}
