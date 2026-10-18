import { useState } from "react";
import { initialOf } from "../../lib/record";
import type { VerdictResult } from "../../lib/types";
import {
  CHECKLIST_LABEL,
  FIT_LABEL,
  FIT_TONE,
  VERDICT_DISCLAIMER,
  ownerLabel,
  verdictNameTone,
} from "../../lib/verdict";

/*
 * 판정 탭 좌측(280px, ui-spec §4.4): 판정 이름 20px/700(색) + 사유 · 체크리스트 5행 · 다음 행동 ·
 * 고지 한 줄.
 *
 * 판정 이름·사유·체크리스트 상태·다음 행동은 서버가 조립한 값이다. 화면은 이 값을 다시 계산하지
 * 않고, 종합 `reason`을 두 문장으로 자르지 않는다(길면 "더 보기"로 펼친다). 역할 의견 불일치는 별도
 * 블록 없이 사유 문장에 녹아 있다. `unknown`은 "확인 필요"이며 부족이 아니다. 판정은 보조 의견이고
 * 추적·최종 Go/No-Go를 바꾸지 않는다.
 */

/** 이보다 길면 사유를 접어 두고 "더 보기"를 둔다. */
const REASON_COLLAPSE_CHARS = 110;

export function VerdictSummary({ result }: { result: VerdictResult }) {
  const [expanded, setExpanded] = useState(false);
  const collapsible = result.reason.length > REASON_COLLAPSE_CHARS;
  const tone = verdictNameTone(result.verdict);
  return (
    <>
      <section aria-labelledby="vd-verdict-name" className="rec-side-block vd-verdict" data-testid="verdict-summary">
        <h3 className={`vd-verdict-name is-${tone}`} id="vd-verdict-name">{result.verdict}</h3>
        <p
          className="vd-verdict-reason"
          data-clamped={collapsible && !expanded ? "true" : undefined}
          id="vd-verdict-reason"
        >
          {result.reason}
        </p>
        {collapsible ? (
          <button
            aria-controls="vd-verdict-reason"
            aria-expanded={expanded}
            className="vd-text-button"
            onClick={() => setExpanded((value) => !value)}
            type="button"
          >
            {expanded ? "접기" : "더 보기"}
          </button>
        ) : null}
      </section>

      <section aria-labelledby="vd-checklist-title" className="rec-side-block" data-testid="verdict-checklist">
        <h3 className="rec-side-title" id="vd-checklist-title">조건 체크리스트</h3>
        <ul className="vd-checklist">
          {result.checklist.map((row) => (
            <li className="vd-checklist-row" data-key={row.key} key={row.key}>
              <span>{CHECKLIST_LABEL[row.key] ?? row.key}</span>
              <span className={`vd-pill is-${FIT_TONE[row.status] ?? "muted"}`}>{FIT_LABEL[row.status] ?? row.status}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="vd-actions-title" className="rec-side-block" data-testid="verdict-next-actions">
        <h3 className="rec-side-title" id="vd-actions-title">다음 행동</h3>
        {result.next_actions.length === 0 ? (
          <p className="rec-side-note">제안된 다음 행동이 없습니다.</p>
        ) : (
          <ul className="rec-next-list">
            {result.next_actions.map((action, index) => {
              const owner = ownerLabel(action);
              const assigned = action.owner?.trim();
              // 결정 B55: 코드가 붙인 행(누락 영역·격리 요구사항)은 "사람 확인" 표식으로 모델 행과 구분한다.
              const byCode = action.origin === "code";
              return (
                <li className="rec-next-item" data-origin={action.origin ?? "unknown"} key={index}>
                  {assigned ? (
                    <span aria-hidden="true" className="rec-avatar" title={`담당 ${owner}`}>{initialOf(owner)}</span>
                  ) : null}
                  <div className="rec-next-main">
                    {byCode ? <span className="vd-pill is-warning">사람 확인</span> : null}
                    <p>{action.action}</p>
                    <p className="rec-side-note" data-owner={assigned ? "assigned" : "unassigned"}>
                      {assigned ? `담당 ${owner}` : owner}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <p className="rec-side-note vd-disclaimer">{VERDICT_DISCLAIMER}</p>
    </>
  );
}
