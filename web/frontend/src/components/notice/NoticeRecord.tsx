import { Link } from "react-router-dom";
import { GridFacts } from "../common/Facts";
import { ClassTag, DeadlineText, StatusMark } from "../common/Marks";
import { RecordFrame } from "../common/RecordFrame";
import { AttachmentPanel } from "./AttachmentPanel";
import { CounterargumentList } from "./CounterargumentList";
import { JudgmentBanner } from "./JudgmentBanner";
import { JudgmentHistory } from "./JudgmentHistory";
import { LifecycleTimeline } from "./LifecycleTimeline";
import { NoticeFacts } from "./NoticeFacts";
import { NoticeGradeMark } from "./NoticeMarks";
import { PerformanceMatches } from "./PerformanceMatches";
import { PerspectiveTable } from "./PerspectiveTable";
import { QualificationFlags } from "./QualificationFlags";
import { RelatedNotices } from "./RelatedNotices";
import { RetrievalSignals } from "./RetrievalSignals";
import { ReviewRecord } from "./ReviewRecord";
import { VerificationItemTable } from "./VerificationItemTable";
import { describeDeadline } from "../../lib/deadline";
import { formatDate, formatDateTime, formatNumber, formatPrice, present } from "../../lib/format";
import { gradeLabel } from "../../lib/grade";
import type { NoticeDetailResponse, ReviewResponse } from "../../lib/types";

interface NoticeRecordProps {
  notice: NoticeDetailResponse;
  queueContext?: { search: string; review: ReviewResponse | undefined };
}

export function NoticeRecord({ notice, queueContext }: NoticeRecordProps) {
  const judgment = notice.judgment;
  const title = present(notice.title, "공고명 미확인");
  const agency = present(notice.agency, "발주기관 미확인");
  const kind = notice.source_type === "pre_spec" ? "사전규격" : notice.source_type === "bid_notice" ? "입찰공고" : "공고";
  const grade = judgment?.grade?.trim() ? judgment.grade : null;
  const deadline = describeDeadline(notice.deadline_at);
  const answers = queueContext?.review?.answers ?? [];
  return (
    <RecordFrame
      heading={{
        eyebrow: `${kind} · ${agency}`,
        title,
        description: notice.published_at ? `공고 ${formatDate(notice.published_at)}` : "공고일 미확인",
      }}
      intro={
        <>
          <div className="workbench-record-heading-marks">
            <NoticeGradeMark grade={grade} />
            <StatusMark mark={{ label: present(judgment?.readiness, "준비 상태 미확인"), tone: "neutral" }} />
            <ClassTag label={present(judgment?.primary_focus, "역량 축 미확인")} />
          </div>
          <p className="notice-record-key">{present(notice.notice_key, "식별자 미확인")}</p>
        </>
      }
    >
      <section className="workbench-record-section notice-record-summary" aria-labelledby="notice-summary-title">
        <h2 className="workbench-record-section-title" id="notice-summary-title">공고 요약</h2>
        <GridFacts columns={3} items={[
          { label: "입찰 마감", value: <>
            {notice.deadline_at ? formatDateTime(notice.deadline_at) : "마감 미확인"}
            {notice.deadline_at ? <small><DeadlineText text={deadline.label} urgency={deadline.urgency} /></small> : null}
          </> },
          { label: "추정가격", value: formatPrice(notice.estimated_price) },
          { label: "판정 등급", value: gradeLabel(grade) },
          // Review corrections appear in the saved review, separately from the screening grade.
          { label: "등급 출처", value: grade === null ? "없음" : "판정" },
          { label: "다음 행동 안내", value: present(judgment?.next_action, "미확인") },
          { label: "첨부", value: notice.attachment_status === "none" ? "첨부 미확보"
            : `${notice.attachment_status === "manual" ? "수동 첨부" : "첨부"} ${formatNumber(notice.attachment_count)}건` },
        ]} />
      </section>
      <section className="workbench-record-section" aria-labelledby="notice-source-title">
        <h2 className="workbench-record-section-title" id="notice-source-title">원문·판정 자료</h2>
        {queueContext ? (
          <Link to={{ pathname: `/judgments/${notice.id}`, search: queueContext.search }}>판정 상세</Link>
        ) : null}
        {notice.url ? <a href={notice.url} target="_blank" rel="noreferrer">나라장터 원문</a> : null}
        <a href="#notice-attachments">기존 첨부 출처 이력 보기</a>
      </section>
      <section className="workbench-record-section" aria-labelledby="notice-flow-title">
        <h2 className="workbench-record-section-title" id="notice-flow-title">공고 생애주기</h2>
        <LifecycleTimeline notice={notice} />
      </section>
      <section className="workbench-record-section" aria-labelledby="notice-judgment-title">
        <h2 className="workbench-record-section-title" id="notice-judgment-title">판정 요약</h2>
        <JudgmentBanner judgment={judgment} />
      </section>
      <section className="workbench-record-section" aria-labelledby="notice-information-title">
        <h2 className="workbench-record-section-title" id="notice-information-title">공고 정보</h2>
        <p className="notice-record-source">나라장터 제공 값</p>
        <NoticeFacts notice={notice} />
      </section>
      <section className="workbench-record-section" aria-labelledby="notice-qualification-title">
        <h2 className="workbench-record-section-title" id="notice-qualification-title">자격·제약 플래그</h2>
        <p className="notice-record-source">나라장터 제공 값</p>
        <QualificationFlags notice={notice} />
      </section>
      {queueContext ? null : (
        <section className="workbench-record-section" aria-labelledby="notice-history-title">
          <h2 className="workbench-record-section-title" id="notice-history-title">판정 이력과 관련 공고</h2>
          <JudgmentHistory noticePk={notice.id} />
          <RelatedNotices noticePk={notice.id} />
        </section>
      )}
      <section className="workbench-record-section" aria-labelledby="notice-basis-title">
        <h2 className="workbench-record-section-title" id="notice-basis-title">첨부 문서와 판정 근거</h2>
        <div id="notice-attachments" tabIndex={-1}>
          <AttachmentPanel noticePk={notice.id} attachments={notice.attachments} />
        </div>
        <PerspectiveTable perspectives={judgment?.perspectives ?? []} />
        <CounterargumentList items={judgment?.counterarguments ?? []} />
        <VerificationItemTable items={judgment?.verification_items ?? []} answers={answers} />
      </section>
      <section className="workbench-record-section" aria-labelledby="notice-support-title">
        <h2 className="workbench-record-section-title" id="notice-support-title">{queueContext ? "추가 확인" : "추가 검색 신호"}</h2>
        <RetrievalSignals matches={notice.focus_matches} />
        {queueContext ? null : (
          <PerformanceMatches
            matchedPerformances={judgment?.matched_performances ?? []}
            performanceMatches={notice.performance_matches}
            performanceTopScore={notice.performance_top_score}
          />
        )}
      </section>
      {queueContext ? <ReviewRecord review={queueContext.review} correctionSearch={`q=${encodeURIComponent(notice.title ?? "")}`} /> : null}
    </RecordFrame>
  );
}
