import { CompanyFitSection } from "./CompanyFitSection";

export interface PreSpecBriefingSectionProps {
  noticeId: number;
}

/**
 * 상세 ④의 가운데 열 `회사 적합성`(docs/specs/0915_ui-redesign/spec.md §4 ④).
 *
 * 2026-11-19(사전규격 단계 수정안 §3 B): C-1 공고 판정을 다시 돌리지 않으므로 이 열에 있던
 * `등급 사유`·`사람 정정 사유`·판정의 다음 행동 줄은 내려갔다(운영에는 판정이 0건이라 늘
 * 비어 있었다). 남는 것은 개요의 과업과 회사 정보를 대조한 `회사 업무 부합 여부`다.
 * 참여 판정은 ④ 첫 열(`PreSpecVerdictColumn`)이 갖는다.
 */
export function PreSpecBriefingSection({ noticeId }: PreSpecBriefingSectionProps) {
  return (
    <section className="ps-tri-col ps-record-briefing" aria-labelledby="pre-spec-company-fit-title">
      <div className="ps-tri-head">
        <h3 id="pre-spec-company-fit-title" className="ps-h-col">회사 적합성</h3>
        <span className="ps-cap ps-dim">모델 참조 · 사람이 확정</span>
      </div>
      <CompanyFitSection noticeId={noticeId} compact />
    </section>
  );
}
