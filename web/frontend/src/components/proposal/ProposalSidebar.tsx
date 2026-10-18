import { ProposalStepper } from "./ProposalStepper";
import { qualityStatusLabel, qualityStatusNote } from "../../lib/qualityStatus";
import { draftStatusLabel, placeholderNeeds, totalSentenceCount } from "../../lib/proposal";
import type { ProposalDraft } from "../../lib/types";

/*
 * 제안서 탭 좌측(280px, ui-spec §4.5): 단계 4 / 숫자 3(확인할 문장 · 비어 있는 자리 · 분량) / 채워야 할 것 /
 * 한 줄 범례.
 *
 * 확인할 문장·비어 있는 자리는 서버 `counters`를 그대로 보인다. 분량은 생성이 끝난 절의 문장 수를 센 값이고
 * 채워야 할 것은 빈 자리를 힌트별로 센 값이다(ui-spec이 허용한 집계). 요구사항 연결은 서버 `requirement_coverage`
 * 그대로다. 가격·투입 인력·전략 수치는 초안에 없다는 점과 이 초안이 참고 자료라는 점만 적는다. 참조 실행
 * 표식은 문구로 말하고 성공·실패 색을 쓰지 않으며 값이 없으면 배지를 두지 않는다(없음을 미측정으로 바꾸지 않는다).
 */

export function ProposalSidebar({ draft }: { draft: ProposalDraft }) {
  const needs = placeholderNeeds(draft);
  const volume = totalSentenceCount(draft);
  const quality = draft.quality_status ?? null;
  const showReference = quality === "unmeasured_reference" || quality === "mock_reference";
  const coverage = draft.requirement_coverage;
  return (
    <>
      <section aria-label="초안 상태" className="rec-side-block" data-testid="proposal-status">
        <ProposalStepper stage={draft.stage} />
        <p className="rec-side-note" data-testid="proposal-draft-status">초안 상태 · {draftStatusLabel(draft.status)}</p>
        {showReference ? (
          <p className="pp-reference" data-testid="proposal-reference-badge" title={qualityStatusNote(quality)}>
            {qualityStatusLabel(quality)}
          </p>
        ) : null}
      </section>

      <section aria-labelledby="pp-numbers-title" className="rec-side-block" data-testid="proposal-numbers">
        <h3 className="visually-hidden" id="pp-numbers-title">초안 숫자</h3>
        <dl className="pp-numbers">
          <div className="pp-number-row" data-key="to-confirm">
            <dt>확인할 문장</dt>
            <dd className="is-warning">{draft.counters.sentences_to_confirm}</dd>
          </div>
          <div className="pp-number-row" data-key="placeholders">
            <dt>비어 있는 자리</dt>
            <dd className="is-warning">{draft.counters.placeholders}</dd>
          </div>
          <div className="pp-number-row" data-key="volume">
            <dt>분량</dt>
            <dd>{volume}문장</dd>
          </div>
          <div className="pp-number-row" data-key="coverage">
            <dt>요구사항 연결</dt>
            <dd>{coverage.linked} / {coverage.total}</dd>
          </div>
        </dl>
        {coverage.unlinked_unit_ids.length > 0 ? (
          <p className="rec-side-note" data-testid="proposal-unlinked">
            연결되지 않은 요구사항 {coverage.unlinked_unit_ids.length}건이 있습니다.
          </p>
        ) : null}
      </section>

      <section aria-labelledby="pp-needs-title" className="rec-side-block" data-testid="proposal-needs">
        <h3 className="rec-side-title" id="pp-needs-title">채워야 할 것</h3>
        {needs.length === 0 ? (
          <p className="rec-side-note">비어 있는 자리가 없습니다.</p>
        ) : (
          <ul className="pp-needs">
            {needs.map((need) => (
              <li className="pp-need" key={need.hint}>
                <span className="pp-need-hint">{need.hint}</span>
                <span className="pp-need-count">{need.count}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="rec-side-note" data-testid="proposal-legend">
        <mark className="pp-legend-mark">주황 표시</mark>는 사람이 채우거나 확인할 자리입니다. 가격·투입 인력·전략은 초안에 넣지 않으며, 초안은 참고 자료입니다.
      </p>
    </>
  );
}
