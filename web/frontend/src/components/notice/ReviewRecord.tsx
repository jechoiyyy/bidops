import { Link } from "react-router-dom";
import { EmptyState } from "../common/EmptyState";
import { SideFacts } from "../common/Facts";
import { StatusMark } from "../common/Marks";
import { present } from "../../lib/format";
import type { ReviewResponse } from "../../lib/types";

/**
 * 공고 1차 판정에 남은 담당자 리뷰를 **읽기 전용**으로 보여준다.
 *
 * ADR-0046 결정 3: 공고 1차 판정 화면은 읽기 전용 이력이 되고, 사람의 수정은
 * 사업 추적의 예외 작업 경로에서 한다. 그 경로가 먼저 동작한 뒤에 이 화면의
 * 저장을 잠갔다(PLAN 단계 E 작업 3-2 → 4 순서).
 *
 * 저장 버튼을 감추기만 하지 않는다. 저장된 값이 무엇인지, 없으면 없다는 것을,
 * 고치려면 어디로 가야 하는지를 함께 남긴다. 리뷰가 없는 것과 리뷰를 못 읽은
 * 것은 다른 상태이므로 섞지 않는다.
 */
export function ReviewRecord({ review, correctionSearch }: { review: ReviewResponse | undefined; correctionSearch: string }) {
  return (
    <section className="workbench-record-section review-record" aria-labelledby="review-record-title">
      <div className="review-record-head">
        <h2 className="workbench-record-section-title" id="review-record-title">담당자 리뷰</h2>
        <StatusMark mark={{ label: "읽기 전용 이력", tone: "neutral" }} />
      </div>

      {review === undefined ? (
        <EmptyState
          compact
          title="이 회차에 저장된 담당자 리뷰가 없어요"
          description="아무도 아직 이 공고를 리뷰하지 않았다는 뜻이에요. 리뷰를 못 읽었다는 뜻이 아니에요."
        />
      ) : (
        <>
          <SideFacts items={[
            { label: "시스템 판정 검토", value: present(review.system_judgment_review, "기록 없음") },
            { label: "최종 처리", value: present(review.disposition, "기록 없음") },
            { label: "수정 등급", value: present(review.corrected_grade, "수정 없음") },
            { label: "수정 참여 준비 상태", value: present(review.corrected_readiness, "수정 없음") },
            { label: "가장 약한 관점", value: present(review.weakest_perspective, "기록 없음") },
            { label: "사유", value: present(review.reason, "기록 없음") },
            { label: "담당자 감사 표식", value: present(review.reviewer, "작성자 미확인") },
            { label: "최종 수정", value: present(review.updated_at ?? review.created_at, "시각 미확인") },
          ]} />
          {review.answers.length > 0 ? (
            <ul className="review-record-answers">
              {review.answers.map((answer) => (
                <li key={answer.id}>
                  <strong>{present(answer.item, "확인 항목 미확인")}</strong>
                  <span>{present(answer.answer, "답변 없음")}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}

      <p className="review-record-note">
        이 화면은 회차별 판정 이력이에요. 사람의 수정은 <strong>사업 추적</strong>의 상세에서 <strong>시스템 신호</strong> 탭을 열어
        예외 작업으로 해요. 거기서 저장한 확인 항목 답변은 이 공고가 속한 회차에 그대로 기록돼요.
      </p>
      <Link className="review-record-link" to={{ pathname: "/opportunities", search: correctionSearch }}>
        사업 추적에서 이 사업기회 찾기 →
      </Link>
    </section>
  );
}
