import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { ActorField } from "../components/common/ActorField";
import { Badge } from "../components/common/Badge";
import { DisabledReason } from "../components/common/DisabledReason";
import { EmptyState } from "../components/common/EmptyState";
import { MutationFeedback } from "../components/common/MutationFeedback";
import {
  DenseList,
  DenseListRow,
  ReviewFilterBar,
  ReviewFilterSegmentedControl,
  ReviewFilterSelector,
  ReviewFilterTextInput,
  ReviewSecondaryInput,
  SplitWorkspace,
  StickyDecisionHeader,
} from "../components/common/ReviewPrimitives";
import { Toast } from "../components/common/Toast";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { api, ApiError } from "../lib/api";
import {
  linkExceptions,
  linkRecordLabel,
  linkStatusDescription,
  nextActionOf,
  noticeVerificationExceptions,
  originDescription,
  originOf,
  trackingDescription,
  trackingSectionDescription,
  trackingSectionOf,
  trackingVariant,
  TRACKING_SECTIONS,
  type TrackingException,
  type TrackingSection,
} from "../lib/opportunity";
import type {
  NoticeDetailResponse,
  OpportunityDetailResponse,
  OpportunityFirstRegisteredStage,
  OpportunityLinkView,
  OpportunityListItem,
  OpportunityTrackingStatus,
  ReviewUpsertRequest,
} from "../lib/types";
import "../styles/opportunities-relaxed.css";

/**
 * 사업 추적 (ADR-0045 결정 2, PLAN 단계 E 작업 3).
 *
 * `검토 대기열`이 쓰던 자리를 받는 화면이다. 목록의 단위는 회차의 공고가 아니라
 * 누적 사업기회이고, 한 사업기회는 어떤 구역에서도 한 행으로만 나타난다.
 * 주소는 이행 전과 같은 `/opportunities`여서 기존 링크와 북마크가 살아 있다.
 *
 * 이 화면이 정하지 않는 것: 적합성 등급, 참여 준비 상태, 심층 검토 실행 승인,
 * 최종 입찰 Go/No-Go. 추적 상태 하나만 사람이 여기서 고른다.
 */

// 사람이 여기서 고를 수 있는 추적 상태. `미선택`은 뺀다 — 결정을 되돌려
// "아직 아무도 안 골랐다"로 만드는 것은 이력을 지우는 일이지 결정이 아니다.
// `계속 추적`은 발주계획에서 처음 고르지만(ADR-0045 결정 4) 보류를 풀 길이
// 있어야 하므로 여기에도 남는다.
const SELECTABLE_TRACKING_STATUSES: OpportunityTrackingStatus[] = ["계속 추적", "보류", "종료"];
const STAGES: OpportunityFirstRegisteredStage[] = ["order_plan", "pre_spec", "bid_notice"];
const SORTS = ["created_at", "tracking_status", "first_registered_stage"] as const;
type OpportunitySort = (typeof SORTS)[number];
const PAGE_SIZE = 100;

type DetailTab = "records" | "history" | "signals";

function formatMoment(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ko-KR");
}

function primaryTitle(item: OpportunityListItem | OpportunityDetailResponse): string {
  const named = item.links.find((link) => link.title && link.title.trim());
  return named?.title?.trim() || "제목 미확인";
}

function primaryAgency(item: OpportunityListItem | OpportunityDetailResponse): string {
  const named = item.links.find((link) => link.agency && link.agency.trim());
  return named?.agency?.trim() || "기관 미확인";
}

function lifecycleRank(link: OpportunityLinkView): number {
  if (link.stage === "order_plan") return 0;
  if (link.source_type === "pre_spec") return 1;
  return 2;
}

function isAuthoritativeBidNotice(link: OpportunityLinkView): boolean {
  return link.source_type === "bid_notice"
    && ((link.link_type === "official" && link.status === "확정")
      || (link.link_type === "candidate" && link.status === "사람 확인 완료" && link.human_decision === "accepted"));
}

function sectionOf(item: OpportunityListItem | OpportunityDetailResponse): TrackingSection {
  return trackingSectionOf(item);
}

function LifecycleCard({ link, isSignalSource, step }: { link: OpportunityLinkView; isSignalSource: boolean; step: number }) {
  return (
    <li className={`opportunity-link ${isSignalSource ? "opportunity-link-signal" : ""}`.trim()}>
      <span className="opportunity-link-step" aria-hidden="true">{step}</span>
      <div className="opportunity-link-head">
        <span className="opportunity-link-kind">{linkRecordLabel(link)}</span>
        <Badge variant={link.status === "검색 미확인" ? "evidence-unknown" : "neutral"} label={link.status} />
        {link.link_type === "candidate" ? <Badge variant="alert" label="후보" /> : null}
        {isSignalSource ? <Badge variant="alert" label="재검토 근거" /> : null}
      </div>
      <p className="opportunity-link-title">{link.title?.trim() || "제목 미확인"}</p>
      <dl className="opportunity-link-facts">
        <div>
          <dt>기관</dt>
          <dd>{link.agency?.trim() || "미확인"}</dd>
        </div>
        <div>
          <dt>외부 식별자</dt>
          <dd className="mono">{link.record_external_id || link.external_id || link.evidence_external_no || "미확인"}</dd>
        </div>
        {link.search_strategy ? (
          <div>
            <dt>검색 전략</dt>
            <dd className="mono">{link.search_strategy}</dd>
          </div>
        ) : null}
        {link.reviewer_name ? (
          <div>
            <dt>사람 확인</dt>
            <dd>
              {link.reviewer_name} · {link.human_decision === "rejected" ? "기각" : "수용"} ·{" "}
              {formatMoment(link.reviewed_at)}
            </dd>
          </div>
        ) : null}
      </dl>
      <p className="opportunity-link-note"><strong>연결 상태</strong> · {linkStatusDescription(link)}</p>
    </li>
  );
}

// ---------------------------------------------------------------------------
// 탭 1 · 연결 레코드

function LinkedRecordsPanel({ item, returnSearch }: { item: OpportunityDetailResponse; returnSearch: string }) {
  const lifecycleLinks = [...item.links].sort((left, right) => lifecycleRank(left) - lifecycleRank(right));
  const noticeLink = lifecycleLinks.find((link) => link.notice_id !== null);
  return (
    <>
      <section className="opportunity-detail-block">
        <div className="opportunity-section-heading">
          <div>
            <span className="opportunity-panel-kicker">OPPORTUNITY LIFECYCLE</span>
            <h4>연결 레코드 {item.links.length}건</h4>
          </div>
          <span>서버에 저장된 관계를 그대로 표시</span>
        </div>
        {item.links.length === 0 ? (
          <EmptyState compact title="연결된 레코드가 없습니다." />
        ) : (
          <ul className="opportunity-links">
            {lifecycleLinks.map((link, index) => (
              <LifecycleCard key={link.id} link={link} step={index + 1} isSignalSource={link.id === item.recheck_signal_link_id} />
            ))}
          </ul>
        )}
      </section>

      <section className="opportunity-detail-block" aria-labelledby="opportunity-bid-delta-title">
        <div className="opportunity-section-heading">
          <div>
            <span className="opportunity-panel-kicker">BID NOTICE REVIEW</span>
            <h4 id="opportunity-bid-delta-title">입찰공고 변경 비교</h4>
          </div>
          <span>추적 상태와 별도의 최종 결정</span>
        </div>
        {lifecycleLinks.some(isAuthoritativeBidNotice) ? (
          <Link className="opportunity-card-toggle interaction-control" to={{ pathname: `/opportunities/${item.id}/bid-delta`, search: returnSearch }}>
            변경 비교
          </Link>
        ) : (
          <p className="opportunity-link-note">확정된 입찰공고 연결이 없어 변경 비교를 시작할 수 없습니다. 입찰공고가 authoritative 상태로 연결된 뒤 사용할 수 있습니다.</p>
        )}
      </section>

      <DeepReviewEntry noticePk={noticeLink?.notice_id ?? null} />
    </>
  );
}

// ---------------------------------------------------------------------------
// 탭 2 · 추적 이력

/**
 * 추적 이력.
 *
 * 서버는 추적 상태 변경마다 append-only `AuditEvent`를 남기지만 그것을 읽는
 * 엔드포인트가 없다. `GET /opportunities/{id}`가 주는 것은 **가장 최근 한 건**의
 * 상태·이유·담당자·시각뿐이다. 그래서 이 탭은 그 한 건만 보여주고, 이전 기록이
 * 없다는 뜻이 아니라는 사실을 감추지 않는다. 화면이 이전 revision을 지어내지
 * 않는다(docs/tracking/findings.md).
 */
function TrackingHistoryPanel({ item }: { item: OpportunityDetailResponse }) {
  return (
    <section className="opportunity-detail-block" aria-labelledby="opportunity-tracking-history-title">
      <div className="opportunity-section-heading">
        <div>
          <span className="opportunity-panel-kicker">TRACKING HISTORY</span>
          <h4 id="opportunity-tracking-history-title">추적 이력</h4>
        </div>
        <Badge variant={trackingVariant(item.tracking_status)} label={item.tracking_status} />
      </div>
      <dl className="opportunity-history-facts">
        <div>
          <dt>현재 상태</dt>
          <dd>{item.tracking_status} · {trackingDescription(item.tracking_status)}</dd>
        </div>
        <div>
          <dt>이유</dt>
          <dd>{item.tracking_reason || "기록된 이유 없음"}</dd>
        </div>
        <div>
          <dt>담당자 감사 표식</dt>
          <dd>{item.tracking_selected_by || "작성자 미확인"}</dd>
        </div>
        <div>
          <dt>선택 시각</dt>
          <dd>{formatMoment(item.tracking_selected_at)}</dd>
        </div>
      </dl>
      <p className="opportunity-contract-gap" role="note">
        서버가 여는 추적 이력은 <strong>가장 최근 한 건</strong>뿐입니다. 상태 변경마다 append-only 감사 기록이
        서버에 쌓이지만 그것을 읽는 계약이 아직 없어, 이전 기록을 이 화면이 만들어 내지 않습니다.
        비어 있는 것이 이전 결정이 없었다는 뜻은 아닙니다.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// 탭 3 · 시스템 신호와 예외 작업 경로 (PLAN 단계 E 작업 3-2)

/** 후보 연결 하나를 사람이 수용·기각한다. 서버 계약 `PATCH /opportunities/links/{id}/decision`. */
function CandidateDecisionForm({ exception, onResolved }: { exception: TrackingException; onResolved: (message: string) => void }) {
  const queryClient = useQueryClient();
  const [decision, setDecision] = useState<"accepted" | "rejected">("accepted");
  const [reason, setReason] = useState("");
  const [actorName, setActorName] = useState("");
  const linkId = exception.linkId as number;

  const mutation = useMutation({
    mutationFn: () => api.decideOpportunityLink(linkId, { decision, reason: reason.trim() }, actorName),
    onSuccess: async () => {
      setReason("");
      setActorName("");
      await queryClient.invalidateQueries({ queryKey: ["opportunity"] });
      await queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      onResolved(decision === "accepted" ? "후보 연결을 수용으로 기록했습니다." : "후보 연결을 기각으로 기록했습니다.");
    },
  });

  const ready = reason.trim().length > 0 && actorName.trim().length > 0 && !mutation.isPending;
  const disabledReason = mutation.isPending
    ? "후보 연결 판정을 저장하고 있습니다."
    : !reason.trim()
      ? "판정을 저장하려면 이유를 입력하십시오."
      : !actorName.trim()
        ? "판정을 저장하려면 담당자 claimed name을 입력하십시오."
        : null;

  return (
    <form
      className="opportunity-exception-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) mutation.mutate();
      }}
    >
      <label>
        <span>판정</span>
        <select className="interaction-control" value={decision} onChange={(event) => setDecision(event.target.value as "accepted" | "rejected")}>
          <option value="accepted">수용 · 이 사업기회의 관계로 확정</option>
          <option value="rejected">기각 · 관계가 아님</option>
        </select>
      </label>
      <label>
        <span>판정 이유</span>
        <textarea
          required
          className="interaction-control"
          rows={2}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="무엇을 근거로 이 관계를 판정했는지 남깁니다."
        />
      </label>
      <ActorField label="담당자 이름" required value={actorName} onChange={setActorName} placeholder="예: 홍길동" autoComplete="off" />
      {mutation.isError ? (
        <MutationFeedback tone="error">
          {mutation.error instanceof ApiError ? mutation.error.message : "후보 연결 판정을 저장하지 못했습니다."} 연결 상태는 바뀌지 않았습니다.
        </MutationFeedback>
      ) : null}
      <button
        className="interaction-control"
        type="submit"
        disabled={!ready}
        aria-describedby={disabledReason ? `candidate-decision-disabled-${linkId}` : undefined}
      >
        {mutation.isPending ? "저장 중…" : "후보 연결 판정 저장"}
      </button>
      {disabledReason ? <DisabledReason id={`candidate-decision-disabled-${linkId}`}>{disabledReason}</DisabledReason> : null}
      <p className="opportunity-form-hint">
        이 판정은 연결 관계만 바꿉니다. 추적 상태·적합성 등급·참여 준비 상태·최종 Go/No-Go를 바꾸지 않습니다.
      </p>
    </form>
  );
}

/**
 * 공고 판정의 확인 항목에 담당자 답변을 남긴다.
 *
 * 사람의 수정은 사업 추적의 예외 작업 경로에서 수행한다(ADR-0045 결정 3).
 * 저장 계약은 검토 대기열이 쓰던 것과 같은 `PUT /notices/{pk}/review`이고,
 * 회차는 **그 공고가 속한 회차**(`notice.run_id`)다. 사업 추적은 누적 화면이라
 * 회차 선택기가 없으므로 회차를 사람에게 다시 묻지 않는다.
 *
 * 이 form은 확인 항목 답변과 이유만 건드린다. 등급·준비 상태·최종 처리 같은
 * 기존 리뷰 값은 그대로 되돌려 보내 예외 처리가 다른 판정을 덮지 않게 한다.
 */
function NoticeCorrectionForm({
  exceptions,
  notice,
  onResolved,
}: {
  exceptions: TrackingException[];
  notice: NoticeDetailResponse;
  onResolved: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const existing = notice.reviews.find((review) => review.run_id === notice.run_id) ?? null;
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [actorName, setActorName] = useState("");

  const mutation = useMutation({
    mutationFn: () => {
      const kept = (existing?.answers ?? [])
        .map((answer) => ({ item: answer.item, answer: answer.answer }))
        .filter((answer) => !((answer.item ?? "") in answers));
      const added = Object.entries(answers)
        .filter(([, value]) => value.trim().length > 0)
        .map(([item, value]) => ({ item, answer: value.trim() }));
      const payload: ReviewUpsertRequest = {
        run_id: notice.run_id,
        disposition: existing?.disposition ?? null,
        system_judgment_review: existing?.system_judgment_review ?? null,
        corrected_grade: existing?.corrected_grade ?? null,
        corrected_readiness: existing?.corrected_readiness ?? null,
        weakest_perspective: existing?.weakest_perspective ?? null,
        reason: reason.trim(),
        reviewer: actorName.trim(),
        verification_answers: [...kept, ...added],
      };
      return api.saveReview(notice.id, payload);
    },
    onSuccess: async () => {
      setAnswers({});
      setReason("");
      setActorName("");
      await queryClient.invalidateQueries({ queryKey: ["notice", notice.id] });
      onResolved("확인 항목 답변을 저장했습니다.");
    },
  });

  const answered = Object.values(answers).filter((value) => value.trim().length > 0).length;
  const ready = answered > 0 && reason.trim().length > 0 && actorName.trim().length > 0 && !mutation.isPending;
  const disabledReason = mutation.isPending
    ? "확인 항목 답변을 저장하고 있습니다."
    : answered === 0
      ? "확인 항목에 답을 하나 이상 입력하십시오."
      : !reason.trim()
        ? "저장하려면 수정 이유를 입력하십시오."
        : !actorName.trim()
          ? "저장하려면 담당자 claimed name을 입력하십시오."
          : null;

  return (
    <form
      className="opportunity-exception-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) mutation.mutate();
      }}
    >
      <p className="opportunity-form-hint">
        회차 <span className="mono">{notice.run_id}</span> · 이 공고가 속한 회차에 저장합니다. 기존 등급·준비 상태·최종 처리 값은 그대로 둡니다.
      </p>
      {exceptions.map((exception) => (
        <label key={exception.title}>
          <span>{exception.title}</span>
          <textarea
            className="interaction-control"
            rows={2}
            value={answers[exception.title] ?? ""}
            onChange={(event) => setAnswers((current) => ({ ...current, [exception.title]: event.target.value }))}
            placeholder="확인한 사실과 원문 위치를 남깁니다. 추정을 적지 않습니다."
          />
        </label>
      ))}
      <label>
        <span>수정 이유</span>
        <textarea
          required
          className="interaction-control"
          rows={2}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="예외 작업으로 무엇을 해소했는지 남깁니다."
        />
      </label>
      <ActorField label="담당자 이름" required value={actorName} onChange={setActorName} placeholder="예: 홍길동" autoComplete="off" />
      {mutation.isError ? (
        <MutationFeedback tone="error">
          {mutation.error instanceof ApiError ? mutation.error.message : "확인 항목 답변을 저장하지 못했습니다."} 공고 판정은 바뀌지 않았습니다.
        </MutationFeedback>
      ) : null}
      <button
        className="interaction-control"
        type="submit"
        disabled={!ready}
        aria-describedby={disabledReason ? `notice-correction-disabled-${notice.id}` : undefined}
      >
        {mutation.isPending ? "저장 중…" : "확인 항목 답변 저장"}
      </button>
      {disabledReason ? <DisabledReason id={`notice-correction-disabled-${notice.id}`}>{disabledReason}</DisabledReason> : null}
    </form>
  );
}

function SystemSignalPanel({
  item,
  onResolved,
}: {
  item: OpportunityDetailResponse;
  onResolved: (message: string) => void;
}) {
  const signalLink = item.links.find((link) => link.id === item.recheck_signal_link_id);
  const noticePks = useMemo(
    () => Array.from(new Set(item.links.map((link) => link.notice_id).filter((id): id is number => typeof id === "number"))),
    [item.links],
  );
  // 검증 실패는 공고 판정 안에 있으므로 연결된 공고를 읽어야 보인다. 시스템 신호
  // 탭을 열 때만 읽는다 — 목록 전체에 대해 미리 읽으면 화면이 서버 부하를 만든다.
  const noticeQueries = useQueries({
    queries: noticePks.map((pk) => ({
      queryKey: ["notice", pk],
      queryFn: () => api.getNotice(pk),
      staleTime: 30_000,
    })),
  });
  const noticesLoading = noticeQueries.some((query) => query.isPending);
  const noticesFailed = noticeQueries.filter((query) => query.isError).length;
  const notices = noticeQueries.map((query) => query.data).filter((data): data is NoticeDetailResponse => Boolean(data));

  const linkFound = linkExceptions(item.links);
  const verificationFound = notices.flatMap((notice) => noticeVerificationExceptions(notice));
  const exceptions = [...linkFound, ...verificationFound];

  return (
    <>
      <section
        className={`opportunity-signal ${item.recheck_signal ? "" : "opportunity-signal-clear"}`.trim()}
        role="status"
        aria-labelledby="recheck-signal-title"
      >
        <div className="opportunity-panel-heading">
          <span className="opportunity-panel-kicker">공식 정보 변화</span>
          <Badge variant={item.recheck_signal ? "alert" : "neutral"} label={item.recheck_signal ? "재검토 필요" : "현재 신호 없음"} />
        </div>
        <h4 id="recheck-signal-title">
          {item.recheck_signal ? "새 레코드가 연결되었습니다." : "현재 재검토 신호가 없습니다."}
        </h4>
        {item.recheck_signal ? <p>{formatMoment(item.recheck_signal_at)}에 공식 조달 레코드가 추가되어 다시 확인해야 합니다.</p> : null}
        {item.recheck_signal && signalLink ? (
          <p className="opportunity-signal-source">
            근거 · {linkRecordLabel(signalLink)} · <span className="mono">
              {signalLink.record_external_id || signalLink.external_id || signalLink.evidence_external_no || "식별자 미확인"}
            </span>
          </p>
        ) : item.recheck_signal ? <p className="opportunity-signal-source">근거 링크를 찾지 못했습니다.</p> : null}
        <p className="opportunity-signal-note">
          시스템 신호는 집계나 추적 결정을 자동으로 만들지 않습니다. 무엇을 할지는 사람이 아래 예외 작업이나 추적 상태 변경에서 정합니다.
        </p>
      </section>

      <section className="opportunity-detail-block" aria-labelledby="opportunity-exception-title">
        <div className="opportunity-section-heading">
          <div>
            <span className="opportunity-panel-kicker">EXCEPTION WORK</span>
            <h4 id="opportunity-exception-title">예외 작업 {exceptions.length}건</h4>
          </div>
          <span>근거 없음 · 검증 실패 · 연결 불확실</span>
        </div>

        {noticesLoading ? <p className="opportunity-detail-status" role="status">연결된 공고의 검증 상태를 확인하는 중…</p> : null}
        {noticesFailed > 0 ? (
          <MutationFeedback tone="warning">
            연결된 공고 {noticesFailed}건을 읽지 못해 그 공고의 검증 실패는 이 목록에 없습니다. 예외가 없다는 뜻이 아닙니다.
          </MutationFeedback>
        ) : null}

        {!noticesLoading && exceptions.length === 0 ? (
          <EmptyState compact title="처리할 예외 작업이 없습니다." description="연결 불확실·근거 없음·검증 실패가 모두 해소된 상태입니다." />
        ) : null}

        <ul className="opportunity-exceptions">
          {exceptions.map((exception, index) => (
            <li className="opportunity-exception" key={`${exception.kind}:${exception.linkId ?? exception.noticeId ?? index}:${exception.title}`}>
              <div className="opportunity-exception-head">
                <Badge variant={exception.kind === "연결 불확실" ? "alert" : "evidence-unknown"} label={exception.kind} />
                <span className="opportunity-exception-title">{exception.title}</span>
              </div>
              <p className="opportunity-exception-detail">{exception.detail}</p>
              <p className="opportunity-exception-resolution"><strong>처리 경로</strong> · {exception.resolution}</p>
              {exception.resolution === "후보 연결 판정" ? (
                <CandidateDecisionForm exception={exception} onResolved={onResolved} />
              ) : null}
              {exception.resolution === "화면 밖 확인" ? (
                <p className="opportunity-exception-detail">
                  이 예외는 이 화면이 저장으로 해소할 수 없습니다. 서버가 검색으로 찾지 못한 관계를 화면이 만들어 내지 않습니다.
                  원문에서 관계를 확인한 뒤 수집이 후보 연결을 만들면 위의 후보 연결 판정으로 처리합니다.
                </p>
              ) : null}
            </li>
          ))}
        </ul>

        {notices.map((notice) => {
          const forNotice = verificationFound.filter((exception) => exception.noticeId === notice.id);
          if (forNotice.length === 0) return null;
          return (
            <div className="opportunity-exception-notice" key={notice.id}>
              <h5>{notice.title?.trim() || "제목 미확인"} · 확인 항목 {forNotice.length}건</h5>
              <NoticeCorrectionForm exceptions={forNotice} notice={notice} onResolved={onResolved} />
              <Link
                className="opportunity-linked-link"
                to={{ pathname: `/judgments/${notice.id}`, search: new URLSearchParams({ run: notice.run_id }).toString() }}
              >
                공고 판정 이력에서 원문 확인 →
              </Link>
            </div>
          );
        })}
      </section>

      {/* 되돌릴 수 없는 결정으로 가는 길을 여기서 새로 열지 않는다. 변경 비교는
          연결 레코드 탭이 하나만 갖는다. */}
      <p className="opportunity-form-hint">
        예외를 해소해도 추적 상태는 바뀌지 않습니다. 추적 상태는 아래 <strong>추적 상태 변경</strong>에서만 사람이 고릅니다.
      </p>
    </>
  );
}

// ---------------------------------------------------------------------------
// 추적 상태 변경 (PLAN 단계 E 작업 3-3)

function TrackingStatusForm({
  opportunity,
  onSaved,
  onDirtyChange,
}: {
  opportunity: OpportunityDetailResponse;
  onSaved: (message: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const queryClient = useQueryClient();
  // 아직 아무도 고르지 않은 건에 기본값을 넣지 않는다. 넣으면 화면이 사람 대신
  // 결정을 고른 셈이 되고, 아무도 손대지 않았는데 "저장되지 않은 변경"이 떠서
  // 화면 이동까지 막힌다. 빈 값으로 열고 고를 때까지 저장을 막는다.
  const initialStatus: OpportunityTrackingStatus | "" =
    opportunity.tracking_status === "미선택" ? "" : opportunity.tracking_status;
  const [status, setStatus] = useState<OpportunityTrackingStatus | "">(initialStatus);
  const [reason, setReason] = useState("");
  const [actorName, setActorName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.updateOpportunityTrackingStatus(
        opportunity.id,
        { tracking_status: status as OpportunityTrackingStatus, reason: reason.trim() },
        actorName,
      ),
    onSuccess: async (saved) => {
      setError(null);
      setStatus(saved.tracking_status);
      setReason("");
      setActorName("");
      onDirtyChange(false);
      queryClient.setQueryData(["opportunity", opportunity.id], saved);
      await queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      onSaved("추적 상태를 저장했습니다.");
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught.message : "추적 상태를 저장하지 못했습니다.");
    },
  });

  const ready = status !== "" && reason.trim().length > 0 && actorName.trim().length > 0;
  const dirty = status !== initialStatus || reason.length > 0 || actorName.length > 0;
  const disabledReason = mutation.isPending
    ? "추적 상태 저장 요청을 처리하고 있습니다."
    : status === ""
      ? "저장하려면 추적 상태를 고르십시오."
      : !reason.trim()
        ? "추적 상태를 저장하려면 이유를 입력하십시오."
        : !actorName.trim()
          ? "추적 상태를 저장하려면 담당자 claimed name을 입력하십시오."
          : null;

  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);

  return (
    <form
      className="opportunity-tracking-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) mutation.mutate();
      }}
    >
      {dirty ? <p className="opportunity-form-unsaved" role="status">저장되지 않은 추적 상태 변경이 있습니다.</p> : null}
      <label>
        <span>추적 상태</span>
        <select className="interaction-control" value={status} onChange={(event) => setStatus(event.target.value as OpportunityTrackingStatus | "")}>
          {initialStatus === "" ? <option value="">아직 고르지 않음 · 상태를 선택하십시오</option> : null}
          {SELECTABLE_TRACKING_STATUSES.map((value) => (
            <option key={value} value={value}>
              {value === "종료" ? "종료 · 추적 종료" : value}
            </option>
          ))}
        </select>
      </label>
      <p className="opportunity-form-hint">
        {status === "" ? "아직 아무도 고르지 않았습니다. 화면이 대신 고르지 않습니다." : trackingDescription(status)}
      </p>
      <label>
        <span>이유</span>
        <textarea
          required
          className="interaction-control"
          rows={2}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="이 상태를 고른 이유를 남깁니다."
        />
      </label>
      <ActorField
        label="담당자 이름"
        required
        value={actorName}
        onChange={setActorName}
        placeholder="예: 홍길동"
        autoComplete="off"
      />
      {error ? <MutationFeedback tone="error">{error}</MutationFeedback> : null}
      <button
        className="interaction-control"
        type="submit"
        disabled={!ready || mutation.isPending}
        aria-describedby={disabledReason ? "opportunity-save-disabled-reason" : undefined}
      >
        {mutation.isPending ? "저장 중…" : "추적 상태 저장"}
      </button>
      {disabledReason ? (
        <DisabledReason id="opportunity-save-disabled-reason">{disabledReason}</DisabledReason>
      ) : null}
    </form>
  );
}

// ---------------------------------------------------------------------------
// 상세 (분할 화면의 오른쪽 pane과 단독 상세가 함께 쓴다)

function TrackingDetail({
  onDirtyChange,
  onSaved,
  opportunityId,
  returnSearch,
}: {
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (message: string) => void;
  opportunityId: number;
  returnSearch: string;
}) {
  const [tab, setTab] = useState<DetailTab>("records");
  const detail = useQuery({
    queryKey: ["opportunity", opportunityId],
    queryFn: ({ signal }) => api.getOpportunity(opportunityId, { signal }),
  });

  useEffect(() => {
    setTab("records");
  }, [opportunityId]);

  if (detail.isPending) return <p className="opportunity-detail-status" role="status">불러오는 중…</p>;
  if (detail.isError || !detail.data) {
    return <EmptyState compact tone="error" title="사업기회를 불러오지 못했습니다." />;
  }

  const item = detail.data;
  const section = sectionOf(item);
  const nextAction = nextActionOf(item);

  return (
    <div className="opportunity-detail">
      <StickyDecisionHeader className="opportunity-detail-head" label="사업 추적 상세 헤더">
        <p className="opportunity-detail-kicker">
          사업기회 #{item.id} · {primaryAgency(item)} · {originDescription(item.first_registered_stage)}
        </p>
        <h3 className="opportunity-detail-title">{primaryTitle(item)}</h3>
        <div className="opportunity-detail-badges">
          <Badge variant="neutral" label={section} />
          <Badge variant={trackingVariant(item.tracking_status)} label={item.tracking_status} />
          <Badge variant={nextAction.variant} label={`다음 행동 · ${nextAction.label}`} />
        </div>
        <TabList value={tab} onChange={(value) => setTab(value as DetailTab)} role="tablist" hasDivider>
          <Tab value="records" label="연결 레코드" panelId="opportunity-panel-records" />
          <Tab value="history" label="추적 이력" panelId="opportunity-panel-history" />
          <Tab value="signals" label="시스템 신호" panelId="opportunity-panel-signals" />
        </TabList>
      </StickyDecisionHeader>

      <div className="opportunity-detail-scroll">
        <div id="opportunity-panel-records" role="tabpanel" aria-label="연결 레코드" hidden={tab !== "records"}>
          <LinkedRecordsPanel item={item} returnSearch={returnSearch} />
        </div>
        <div id="opportunity-panel-history" role="tabpanel" aria-label="추적 이력" hidden={tab !== "history"}>
          <TrackingHistoryPanel item={item} />
        </div>
        <div id="opportunity-panel-signals" role="tabpanel" aria-label="시스템 신호" hidden={tab !== "signals"}>
          {tab === "signals" ? <SystemSignalPanel item={item} onResolved={onSaved} /> : null}
        </div>
      </div>

      {/* 분할 화면의 결정은 상세 pane 바닥에 고정한다(PLAN 단계 B). 추적 상태
          변경은 기본 접힘이고, 접힌 상태에서도 현재 값과 "무엇을 바꾸지 않는지"가
          그대로 보인다(PLAN 단계 E 작업 3-3). */}
      <div className="opportunity-detail-decision">
        <ReviewSecondaryInput
          description="보류와 추적 종료는 이 화면에서만 사람이 고릅니다. 필수 사유와 담당자 감사 표식을 새 기록으로 남기며, 적합성 등급·참여 준비 상태·심층 검토 승인·최종 Go/No-Go를 바꾸지 않습니다."
          summary={<Badge variant={trackingVariant(item.tracking_status)} label={item.tracking_status} />}
          title="추적 상태 변경"
        >
          <TrackingStatusForm
            key={`${item.id}:${item.tracking_selected_at ?? "unselected"}`}
            opportunity={item}
            onSaved={onSaved}
            onDirtyChange={onDirtyChange}
          />
        </ReviewSecondaryInput>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 목록

export function OpportunitiesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [toast, setToast] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [searchText, setSearchText] = useState(searchParams.get("q") ?? "");
  const handleDirtyChange = useCallback((nextDirty: boolean) => setDirty(nextDirty), []);
  useUnsavedGuard(dirty, {
    blockSpaNavigation: true,
    message: "저장되지 않은 추적 상태 변경이 있습니다. 이 페이지를 벗어나시겠습니까?",
  });

  const requestedSection = searchParams.get("section");
  const section: TrackingSection = TRACKING_SECTIONS.includes(requestedSection as TrackingSection)
    ? requestedSection as TrackingSection
    : "조치 필요";
  const stage = (searchParams.get("first_registered_stage") as OpportunityFirstRegisteredStage | null) ?? null;
  const requestedSort = searchParams.get("sort");
  const sort: OpportunitySort = SORTS.includes(requestedSort as OpportunitySort)
    ? requestedSort as OpportunitySort
    : "created_at";
  const requestedOffset = Number(searchParams.get("offset") ?? "0");
  const offset = Number.isInteger(requestedOffset) && requestedOffset >= 0 ? requestedOffset : 0;
  const search = (searchParams.get("q") ?? "").trim();

  // 구역 넷 중 셋은 저장된 추적 상태 하나에만 해당하므로 서버 필터를 그대로
  // 쓴다. `조치 필요`만은 저장된 상태가 아니라 화면 판단이라 서버가 셀 수 없어
  // 필터 없이 받아 이 화면이 나눈다. 어느 쪽이든 구역 판정은 한 곳
  // (trackingSectionOf)이 하므로 한 사업기회가 두 구역에 나타나지 않는다.
  const serverTrackingStatus: OpportunityTrackingStatus | null =
    section === "추적 중" ? "계속 추적" : section === "보류" ? "보류" : section === "추적 종료" ? "종료" : null;

  const list = useQuery({
    queryKey: ["opportunities", serverTrackingStatus, stage, sort, offset],
    queryFn: ({ signal }) =>
      api.getOpportunities(
        { tracking_status: serverTrackingStatus, first_registered_stage: stage, sort, limit: PAGE_SIZE, offset },
        { signal },
      ),
  });

  const received = useMemo(() => list.data?.items ?? [], [list.data]);
  const total = list.data?.total ?? 0;
  const inSection = useMemo(() => received.filter((item) => sectionOf(item) === section), [received, section]);
  const items = useMemo(() => {
    if (!search) return inSection;
    const needle = search.toLowerCase();
    return inSection.filter((item) => `${primaryTitle(item)} ${primaryAgency(item)}`.toLowerCase().includes(needle));
  }, [inSection, search]);

  const selectedParam = Number(searchParams.get("selected") ?? "");
  const selectedId = items.some((item) => item.id === selectedParam) ? selectedParam : items[0]?.id ?? null;
  const returnSearch = searchParams.toString();

  function applyParam(key: string, value: string | null) {
    if (dirty && !window.confirm("저장되지 않은 추적 상태 변경이 있습니다. 목록을 바꾸시겠습니까?")) return;
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    next.delete("selected");
    setSearchParams(next, { replace: true });
  }

  function selectRow(id: number) {
    const next = new URLSearchParams(searchParams);
    next.set("selected", String(id));
    setSearchParams(next, { replace: true });
  }

  return (
    <section className="opportunities-page" aria-labelledby="page-title">
      <header className="opportunities-header">
        <h2 id="page-title">사업 추적</h2>
        <p>
          발주계획·사전규격·입찰공고를 외부 식별자로 누적한 사업 단위다. 회차 목록이 아니므로 한 사업기회는
          한 행으로만 나타나고, 회차를 옮겨 다니며 같은 건을 다시 찾지 않는다. 이 화면이 정하는 것은 추적 상태
          하나이며 적합성 등급·참여 준비 상태·심층 검토 승인·최종 Go/No-Go를 대신하지 않는다.
        </p>
      </header>

      <ReviewFilterBar aria-label="사업 추적 필터" className="opportunities-filters">
        <div className="opportunity-filter-axis opportunity-sections">
          <span className="opportunity-filter-label" id="opportunity-section-label">구역</span>
          <ReviewFilterSegmentedControl
            label="구역"
            onChange={(value) => applyParam("section", value)}
            options={TRACKING_SECTIONS.map((value) => ({ label: value, value }))}
            value={section}
          />
        </div>
        <div className="opportunity-filter-axis">
          <span className="opportunity-filter-label">최초 등록</span>
          <ReviewFilterSelector
            label="최초 등록"
            onChange={(value) => applyParam("first_registered_stage", value)}
            options={STAGES.map((value) => ({ label: `${originOf(value)} · ${originDescription(value)}`, value }))}
            placeholder="전체"
            value={stage}
          />
        </div>
        <div className="opportunity-filter-axis">
          <span className="opportunity-filter-label">정렬</span>
          <ReviewFilterSelector
            clearable={false}
            label="정렬"
            onChange={(value) => applyParam("sort", value)}
            options={[
              { label: "최근 등록순", value: "created_at" },
              { label: "추적 상태순", value: "tracking_status" },
              { label: "최초 등록 단계순", value: "first_registered_stage" },
            ]}
            value={sort}
          />
        </div>
        <div className="opportunity-filter-axis">
          <ReviewFilterTextInput
            label="사업명·기관 검색"
            onChange={setSearchText}
            onEnter={() => applyParam("q", searchText.trim() || null)}
            placeholder="사업명·기관"
            value={searchText}
          />
        </div>
      </ReviewFilterBar>

      {list.isPending ? <p className="opportunity-detail-status" role="status">불러오는 중…</p> : null}
      {list.isError ? <EmptyState tone="error" title="사업 추적 목록을 불러오지 못했습니다." /> : null}

      {list.isSuccess ? (
        <SplitWorkspace aria-label="사업 추적 목록과 상세" className="opportunity-workspace">
          <aside className="opportunity-list-pane">
            <header className="opportunity-list-head">
              <p className="opportunity-list-title">{section} {items.length.toLocaleString("ko-KR")}건</p>
              <p className="opportunity-list-note">{trackingSectionDescription(section)}</p>
              <p className="opportunity-list-note">
                {serverTrackingStatus
                  ? `서버에서 추적 상태 ${serverTrackingStatus} ${total.toLocaleString("ko-KR")}건을 받아 그중 조치 필요로 옮겨간 건을 뺐습니다.`
                  : `서버가 구역별 총계를 세지 않으므로 받은 ${received.length.toLocaleString("ko-KR")}건(전체 ${total.toLocaleString("ko-KR")}건 중)에서 이 구역을 골랐습니다.`}
                {search ? ` · 검색어 "${search}"는 받은 목록 안에서만 걸립니다.` : ""}
              </p>
              {total > offset + received.length ? (
                <p className="opportunity-list-note">
                  뒤에 {(total - offset - received.length).toLocaleString("ko-KR")}건이 더 있습니다. 다음 페이지에서 확인합니다.
                </p>
              ) : null}
            </header>
            {items.length === 0 ? (
              <div className="opportunity-list-empty">
                <p>이 구역에 표시할 사업기회가 없습니다. 다른 구역이나 다음 페이지에 있을 수 있으며, 없다는 뜻이 아닙니다.</p>
              </div>
            ) : (
              <DenseList aria-label="사업 추적 목록" className="opportunity-list-scroll">
                {items.map((item) => {
                  const rowAction = nextActionOf(item);
                  return (
                    <DenseListRow
                      key={item.id}
                      selected={item.id === selectedId}
                      onSelect={() => selectRow(item.id)}
                      label={primaryTitle(item)}
                      description={(
                        <>
                          {primaryAgency(item)} · {originDescription(item.first_registered_stage)} · 연결 {item.links.length}건
                          {item.tracking_selected_by ? ` · ${item.tracking_selected_by}` : ""}
                        </>
                      )}
                      endContent={(
                        <span className="opportunity-row-badges">
                          <Badge variant={rowAction.variant} label={rowAction.label} />
                          <Badge variant={trackingVariant(item.tracking_status)} label={item.tracking_status} />
                          {item.recheck_signal ? <Badge variant="alert" label="재검토 필요" /> : null}
                          <span className="opportunity-card-id mono">#{item.id}</span>
                        </span>
                      )}
                    />
                  );
                })}
              </DenseList>
            )}
            {total > PAGE_SIZE ? (
              <nav className="opportunity-pager">
                <button
                  className="interaction-control"
                  type="button"
                  disabled={offset === 0}
                  onClick={() => {
                    const next = new URLSearchParams(searchParams);
                    next.set("offset", String(Math.max(0, offset - PAGE_SIZE)));
                    next.delete("selected");
                    setSearchParams(next, { replace: true });
                  }}
                >
                  이전
                </button>
                <span>
                  {offset + 1}–{Math.min(offset + received.length, total)} / {total}
                </span>
                <button
                  className="interaction-control"
                  type="button"
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => {
                    const next = new URLSearchParams(searchParams);
                    next.set("offset", String(offset + PAGE_SIZE));
                    next.delete("selected");
                    setSearchParams(next, { replace: true });
                  }}
                >
                  다음
                </button>
              </nav>
            ) : null}
          </aside>

          <section className="opportunity-detail-pane">
            {selectedId === null ? (
              <div className="opportunity-detail-empty">
                <p>표시할 사업기회가 없습니다.</p>
              </div>
            ) : (
              <>
                <TrackingDetail
                  key={selectedId}
                  onDirtyChange={handleDirtyChange}
                  onSaved={setToast}
                  opportunityId={selectedId}
                  returnSearch={returnSearch}
                />
                <p className="opportunity-detail-permalink">
                  <Link to={{ pathname: `/opportunities/${selectedId}`, search: returnSearch }}>
                    이 사업기회만 따로 열기 →
                  </Link>
                </p>
              </>
            )}
          </section>
        </SplitWorkspace>
      ) : null}

      {toast ? <Toast message={toast} onDismiss={() => setToast(null)} /> : null}
    </section>
  );
}

/**
 * 심층 검토 보고서 진입점 (docs/design/PRD.md §2.2).
 *
 * 보고서를 만든 뒤 다시 찾아갈 길이 없던 문제를 사업 추적 화면에서 연다.
 * 다만 서버 계약이 `GET /deep-reviews/{id}` 단건 조회뿐이고 사업기회·공고로
 * 목록을 받을 엔드포인트가 없어(routers/deep_reviews.py) 만들어진 보고서를
 * 자동으로 나열할 수 없다. API 계약을 바꾸지 않으므로 보고서 식별자로 여는
 * 길을 열어 두고, 나열할 수 없다는 사실을 감추지 않고 그대로 알린다.
 * 구조 문제는 docs/tracking/findings.md에 기록했다.
 */
function DeepReviewEntry({ noticePk }: { noticePk: number | null }) {
  const [deepReviewId, setDeepReviewId] = useState("");
  const trimmed = deepReviewId.trim();

  return (
    <section className="opportunity-deep-review" aria-labelledby="opportunity-deep-review-title">
      <h4 id="opportunity-deep-review-title">심층 검토 보고서</h4>
      <p>
        이 사업기회에 연결된 심층 검토 보고서는 사전규격 상세에서 만들어집니다. 서버가 사업기회별 보고서
        목록을 제공하지 않아 여기에 자동으로 나열할 수 없습니다. 목록이 없다는 것을 보고서가 없다는 뜻으로
        해석하지 마십시오.
      </p>
      <form
        className="opportunity-deep-review-form"
        onSubmit={(event) => {
          event.preventDefault();
        }}
      >
        <label htmlFor="deep-review-id">심층 검토 보고서 ID</label>
        <input
          id="deep-review-id"
          value={deepReviewId}
          onChange={(event) => setDeepReviewId(event.target.value)}
          placeholder="보고서 식별자"
        />
        {trimmed ? (
          <Link className="opportunity-linked-link" to={`/deep-reviews/${encodeURIComponent(trimmed)}`}>
            보고서 열기 →
          </Link>
        ) : (
          <span className="opportunity-deep-review-hint">식별자를 입력하면 보고서로 이동할 수 있습니다.</span>
        )}
      </form>
      {noticePk === null ? (
        <p className="opportunity-deep-review-hint">
          연결된 공고가 없어 심층 검토를 실행할 자리로 갈 수 없습니다. 사전규격이 연결된 뒤에 열립니다.
        </p>
      ) : (
        <Link className="opportunity-linked-link" to={`/pre-specs/${noticePk}`}>
          사전규격 상세에서 심층 검토 실행 →
        </Link>
      )}
    </section>
  );
}

export function OpportunityDetailPage() {
  const { opportunityId: opportunityIdParam } = useParams();
  const [searchParams] = useSearchParams();
  const [toast, setToast] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const opportunityId = Number(opportunityIdParam);
  const validOpportunityId = Number.isInteger(opportunityId) && opportunityId > 0;
  const handleDirtyChange = useCallback((nextDirty: boolean) => setDirty(nextDirty), []);
  useUnsavedGuard(dirty, {
    blockSpaNavigation: true,
    message: "저장되지 않은 추적 상태 변경이 있습니다. 이 페이지를 벗어나시겠습니까?",
  });

  return (
    <section className="opportunities-page opportunity-detail-page" aria-labelledby="page-title">
      <header className="opportunities-header opportunity-detail-header">
        <Link className="opportunity-back-link" to={{ pathname: "/opportunities", search: searchParams.toString() }}>
          ← 사업 추적 목록
        </Link>
        <h2 id="page-title">사업 추적 상세{validOpportunityId ? ` #${opportunityId}` : ""}</h2>
        <p>목록의 구역·필터·정렬·페이지 문맥을 유지한 누적 사업기회 상세다.</p>
      </header>

      <div className="opportunity-standalone-pane">
        {validOpportunityId ? (
          <TrackingDetail
            onDirtyChange={handleDirtyChange}
            onSaved={setToast}
            opportunityId={opportunityId}
            returnSearch={searchParams.toString()}
          />
        ) : (
          <EmptyState tone="error" title="사업기회 식별자가 올바르지 않습니다." />
        )}
      </div>

      {toast ? <Toast message={toast} onDismiss={() => setToast(null)} /> : null}
    </section>
  );
}
