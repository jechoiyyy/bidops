import { CompanyFitSection } from "./CompanyFitSection";
import { formatDateTime } from "../../lib/format";
import type { JudgmentResponse, ReviewResponse } from "../../lib/types";

function textOrNull(value: string | null): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

export interface PreSpecBriefingSectionProps {
  noticeId: number;
  judgment: JudgmentResponse | null;
  reviews: ReviewResponse[];
}

/**
 * 상세 ④의 가운데 열 `회사 적합성`(docs/0915_ui-redesign/spec.md §4 ④).
 *
 * 등급 출처와 판정 사유, 사람 정정 사유, 그리고 `회사 업무 부합 여부`가 한 열에
 * 모인다. 반론·확인 항목은 같은 카드의 `위험 및 미확인 사항` 열이 갖고, 본공고
 * 번호는 헤더 칩이, 변경 일시·사유는 ⑥ 처리 이력이 각각 한 곳에서 소유한다.
 *
 * 등급 라벨 칩은 여기서 다시 그리지 않는다 — 화면에 등급 라벨은 ① 팩트 스트립에
 * 한 번만 나온다(spec §4 머리말).
 */
export function PreSpecBriefingSection({
  noticeId,
  judgment,
  reviews,
}: PreSpecBriefingSectionProps) {
  const perspectives = judgment?.perspectives ?? [];
  // `next_action`은 아래 `다음 행동` 한 줄이 갖는다. 이 구역이 그리지 않는 값으로
  // "사유가 있다"고 판단하면 빈 구역이 생긴다.
  const hasJudgmentReasons = Boolean(
    judgment && (textOrNull(judgment.summary) || perspectives.length > 0),
  );

  return (
    <section className="ps-tri-col ps-record-briefing" aria-labelledby="pre-spec-company-fit-title">
      <div className="ps-tri-head">
        <h3 id="pre-spec-company-fit-title" className="ps-h-col">회사 적합성</h3>
        <span className="ps-cap ps-dim">모델 참조 · 사람이 확정</span>
      </div>

      <section className="ps-briefing-group" aria-labelledby="pre-spec-briefing-title">
        <div className="ps-tri-head">
          <h4 id="pre-spec-briefing-title" className="ps-sub">등급 사유</h4>
          <span className="ps-cap ps-dim">출처 · 판정</span>
        </div>
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
          </div>
        )}
      </section>

      <section className="ps-briefing-group" aria-labelledby="pre-spec-human-reason-title">
        <h4 id="pre-spec-human-reason-title" className="ps-sub">사람 정정 사유</h4>
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

      <CompanyFitSection noticeId={noticeId} compact />

      <p className="ps-cap ps-dim ps-briefing-next-action">
        다음 행동 · {textOrNull(judgment?.next_action ?? null) ?? "다음 행동 미확인"}
      </p>
    </section>
  );
}
