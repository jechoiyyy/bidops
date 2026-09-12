import { formatDateTime } from "../../lib/format";
import type { JudgmentResponse, ReviewResponse } from "../../lib/types";

function textOrNull(value: string | null): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

export interface PreSpecBriefingSectionProps {
  judgment: JudgmentResponse | null;
  reviews: ReviewResponse[];
}

/** 본공고 번호는 헤더 칩이, 변경 일시·사유는 처리 이력이 각각 한 곳에서 소유한다. */
export function PreSpecBriefingSection({
  judgment,
  reviews,
}: PreSpecBriefingSectionProps) {
  const perspectives = judgment?.perspectives ?? [];
  const counterarguments = judgment?.counterarguments ?? [];
  const verificationItems = judgment?.verification_items ?? [];
  // `next_action`은 아래 `다음 행동`이 갖는다. 이 구역이 그리지 않는 값으로
  // "사유가 있다"고 판단하면 빈 구역이 생긴다.
  const hasJudgmentReasons = Boolean(
    judgment
    && (
      textOrNull(judgment.summary)
      || perspectives.length > 0
      || counterarguments.length > 0
      || verificationItems.length > 0
    ),
  );

  return (
    <section className="ps-card ps-sec ps-record-briefing" aria-labelledby="pre-spec-briefing-title">
      <div className="ps-sec-head">
        <h2 id="pre-spec-briefing-title" className="ps-h-sec">등급 사유</h2>
        <span className="ps-cap ps-dim">판정과 사람 정정을 분리해 표시</span>
      </div>

      <section className="ps-briefing-group" aria-labelledby="pre-spec-judgment-reason-title">
        <h3 id="pre-spec-judgment-reason-title" className="ps-sub">판정 사유(회차 판정)</h3>
        {!hasJudgmentReasons ? <p className="ps-muted">판정 사유 없음</p> : (
          <div className="ps-briefing-content">
            {textOrNull(judgment?.summary ?? null) ? <p>{judgment?.summary}</p> : null}
            {perspectives.length ? (
              <ul className="ps-briefing-list">
                {perspectives.map((perspective, index) => {
                  const name = textOrNull(perspective.name) ?? `관점 ${index + 1}`;
                  const assessment = textOrNull(perspective.assessment);
                  const reason = textOrNull(perspective.reason);
                  return (
                    <li key={perspective.id}>
                      <strong>{name}</strong>
                      {assessment ? <span> · {assessment}</span> : <span className="ps-muted"> · 평가 미확인</span>}
                      {reason ? <p className="ps-briefing-detail">사유 · {reason}</p> : null}
                    </li>
                  );
                })}
              </ul>
            ) : null}
            {counterarguments.length ? (
              <div className="ps-briefing-subgroup">
                <h4 className="ps-sub">반론</h4>
                <ul className="ps-briefing-list">
                  {counterarguments.map((counterargument, index) => (
                    <li key={counterargument.id}>{textOrNull(counterargument.text) ?? `반론 ${index + 1} 내용 미확인`}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {verificationItems.length ? (
              <div className="ps-briefing-subgroup">
                <h4 className="ps-sub">확인 항목</h4>
                <ul className="ps-briefing-list">
                  {verificationItems.map((item, index) => {
                    const label = textOrNull(item.item) ?? `확인 항목 ${index + 1}`;
                    const why = textOrNull(item.why);
                    return <li key={item.id}><strong>{label}</strong>{why ? <span> · {why}</span> : null}</li>;
                  })}
                </ul>
              </div>
            ) : null}
          </div>
        )}
      </section>

      <section className="ps-briefing-group" aria-labelledby="pre-spec-human-reason-title">
        <h3 id="pre-spec-human-reason-title" className="ps-sub">사람 정정 사유</h3>
        {reviews.length === 0 ? <p className="ps-muted">사람 정정 사유 없음</p> : (
          <ol className="ps-briefing-list ps-briefing-reviews">
            {reviews.map((review) => (
              <li key={review.id}>
                <p>{textOrNull(review.reason) ?? "정정 사유 미확인"}</p>
                {review.system_judgment_review ? <p className="ps-briefing-detail">판정 검토 · {review.system_judgment_review}</p> : null}
                <span className="ps-cap ps-dim">
                  {textOrNull(review.reviewer) ?? "담당자 미확인"} · {formatDateTime(review.created_at)}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="ps-briefing-group" aria-labelledby="pre-spec-next-action-title">
        <h3 id="pre-spec-next-action-title" className="ps-sub">다음 행동</h3>
        <p>{textOrNull(judgment?.next_action ?? null) ?? "다음 행동 미확인"}</p>
      </section>

    </section>
  );
}
