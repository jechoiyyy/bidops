import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Token } from "@astryxdesign/core/Token";
import { ArrowUpRight, Check, ChevronRight, CircleHelp, FileText } from "lucide-react";
import { Badge, type BadgeVariant } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { AgencyFeature, StickyDecisionHeader } from "../common/ReviewPrimitives";
import { MutationFeedback } from "../common/MutationFeedback";
import { api } from "../../lib/api";
import {
  linkRecordLabel,
  noticeVerificationExceptions,
  originDescription,
  type TrackingException,
} from "../../lib/opportunity";
import { qualityStatusLabel, qualityStatusVariant } from "../../lib/qualityStatus";
import type {
  NoticeDetailResponse,
  OpportunityLinkView,
  OpportunitySearchResponse,
  OpportunitySearchTarget,
} from "../../lib/types";
import { CandidateLinkDialog } from "./CandidateLinkDialog";
import { NoticeCorrectionDialog } from "./NoticeCorrectionDialog";
import { RecheckAcknowledgement } from "./RecheckAcknowledgement";
import { RecordSearchPanel } from "./RecordSearchPanel";
import { TrackingHistory } from "./TrackingHistory";
import { TrackingResetControl } from "./TrackingResetControl";
import { TrackingStatusDialog } from "./TrackingStatusDialog";
import {
  actionReasonsOf,
  connectionLabel,
  formatMoment,
  holdReviewText,
  isConfirmedLink,
  isPendingCandidate,
  isRejectedCandidate,
  latestConfirmedStage,
  nextCheckOf,
  pendingCandidateFor,
  primaryAgency,
  primaryTitle,
  recordRoute,
  recordRouteLabel,
  searchStrategyLabel,
  searchTargetKindOf,
  searchTargetLabel,
  stageOfLink,
  stageViews,
  visibleUnconfirmedSearches,
  type LifecycleStage,
  type OpportunityDetailIntent,
} from "./trackingFlow";

/**
 * 사업 추적 상세. 분할 화면의 오른쪽 pane과 단독 상세 route가 같이 쓴다.
 *
 * 세 탭.
 *   사업 흐름   — 3단계 연결 현황(찾아보기 포함), 다음 확인 하나, 연결된 공고
 *   확인 사항   — 사람이 해소해야 할 예외와 그 처리 경로(새 공고 확인 완료 포함)
 *   추적 이력   — 현재 추적 결정과, 결정 revision·재검토 신호 이벤트의 시간순 이력
 *
 * 3단계 줄의 체크 표시는 **연결 확정**만 뜻한다. 분석 완료나 입찰 참여 승인이
 * 아니며, 최종 Go/No-Go는 다른 화면이 갖는다.
 */

type DetailTab = "flow" | "checks" | "decision";

type OpenDialog =
  | { kind: "tracking" }
  | { kind: "candidate"; linkId: number }
  | { kind: "notice"; noticeId: number }
  | null;

function externalIdOf(link: OpportunityLinkView): string {
  return link.record_external_id || link.external_id || link.evidence_external_no || "식별자 미확인";
}

function LinkedRow({ link, onCompare, onOpenChecks }: {
  link: OpportunityLinkView;
  onCompare: () => void;
  onOpenChecks: () => void;
}) {
  const route = recordRoute(link);
  const unconfirmed = link.status === "검색 미확인";
  return (
    <li className="opportunity-linked-row">
      <FileText aria-hidden="true" />
      <div>
        <div className="opportunity-row opportunity-spread">
          <p><strong>{stageOfLink(link) ?? linkRecordLabel(link)}</strong></p>
          <p className="opportunity-caption">
            {isRejectedCandidate(link) ? "후보 기각" : connectionLabel(link)}
          </p>
        </div>
        <p>{unconfirmed ? "일치하는 원천 레코드 미확인" : link.title?.trim() || "제목 미확인"}</p>
        <p className="opportunity-caption">
          {unconfirmed ? "이름 검색으로 찾지 못함" : externalIdOf(link)}
        </p>
      </div>
      {isPendingCandidate(link) ? (
        <Button label="후보 비교" onClick={onCompare} size="sm" variant="ghost" />
      ) : unconfirmed ? (
        <Button label="검색 기록" onClick={onOpenChecks} size="sm" variant="ghost" />
      ) : route ? (
        <Link aria-label={recordRouteLabel(link)} className="opportunity-record-link" to={route}>
          <ArrowUpRight aria-hidden="true" />
        </Link>
      ) : (
        <p className="opportunity-caption">상세 없음</p>
      )}
    </li>
  );
}

export interface OpportunityDetailProps {
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (message: string) => void;
  opportunityId: number;
  returnSearch: string;
  /**
   * 목록 행의 주 행동이 요청한 자리. `nonce`가 바뀔 때마다 한 번 연다(같은 행을 다시
   * 눌러도 다시 열린다). 단독 상세는 넘기지 않는다.
   */
  intent?: { action: OpportunityDetailIntent; nonce: number } | null;
}

export function OpportunityDetail({ intent = null, onDirtyChange, onSaved, opportunityId, returnSearch }: OpportunityDetailProps) {
  const [tab, setTab] = useState<DetailTab>("flow");
  const [dialog, setDialog] = useState<OpenDialog>(null);
  // 확인 사항 패널은 늘 그려 두지만(연결 화면으로 가는 길이 항상 DOM에 있어야
  // 한다) 연결된 공고를 읽는 것은 탭을 한 번 연 뒤부터다. 목록 전체를 미리 읽으면
  // 화면이 서버 부하를 만든다.
  const [checksOpened, setChecksOpened] = useState(false);
  const [dirtySources, setDirtySources] = useState<Record<string, boolean>>({});
  const [searchTarget, setSearchTarget] = useState<OpportunitySearchTarget | null>(null);
  const [searchResult, setSearchResult] = useState<OpportunitySearchResponse | null>(null);
  const [recheckNotice, setRecheckNotice] = useState<string | null>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const handledIntent = useRef<number | null>(null);

  const setSourceDirty = useCallback((key: string, dirty: boolean) => {
    setDirtySources((current) => (Boolean(current[key]) === dirty ? current : { ...current, [key]: dirty }));
  }, []);
  const trackingDirty = useCallback((dirty: boolean) => setSourceDirty("tracking", dirty), [setSourceDirty]);
  const candidateDirty = useCallback((dirty: boolean) => setSourceDirty("candidate", dirty), [setSourceDirty]);
  const noticeDirty = useCallback((dirty: boolean) => setSourceDirty("notice", dirty), [setSourceDirty]);
  const recheckDirty = useCallback((dirty: boolean) => setSourceDirty("recheck", dirty), [setSourceDirty]);

  const detail = useQuery({
    queryKey: ["opportunity", opportunityId],
    queryFn: ({ signal }) => api.getOpportunity(opportunityId, { signal }),
  });

  const decisions = useQuery({
    queryKey: ["opportunity-tracking-decisions", opportunityId],
    queryFn: ({ signal }) => api.getOpportunityTrackingDecisions(opportunityId, { signal }),
  });

  const item = detail.data ?? null;
  const links = useMemo(() => item?.links ?? [], [item]);
  const noticePks = useMemo(
    () => Array.from(new Set(links.map((link) => link.notice_id).filter((id): id is number => typeof id === "number"))),
    [links],
  );
  const noticeQueries = useQueries({
    queries: checksOpened
      ? noticePks.map((pk) => ({ queryKey: ["notice", pk], queryFn: () => api.getNotice(pk), staleTime: 30_000 }))
      : [],
  });

  const anyDirty = Object.values(dirtySources).some(Boolean);
  useEffect(() => {
    onDirtyChange(anyDirty);
  }, [anyDirty, onDirtyChange]);

  useEffect(() => {
    setTab("flow");
    setChecksOpened(false);
    setDialog(null);
    setDirtySources({});
    setSearchTarget(null);
    setSearchResult(null);
    setRecheckNotice(null);
  }, [opportunityId]);

  // 목록 행의 주 행동. 상세를 읽은 뒤 요청 번호마다 한 번만 연다. 후보가 이미 처리돼
  // 목록과 상세가 어긋나면 대화상자를 지어내지 않고 확인 사항을 연다.
  useEffect(() => {
    if (!intent || !item || handledIntent.current === intent.nonce) return;
    handledIntent.current = intent.nonce;
    const action = intent.action;
    if (action.kind === "tracking") {
      setDialog({ kind: "tracking" });
      return;
    }
    if (action.kind === "candidate" && action.linkId !== null) {
      const linkId = action.linkId;
      if (item.links.some((link) => link.id === linkId && isPendingCandidate(link))) {
        setDialog({ kind: "candidate", linkId });
        return;
      }
    }
    setChecksOpened(true);
    setTab("checks");
  }, [intent, item]);

  useEffect(() => {
    if (scroll.current) scroll.current.scrollTop = 0;
  }, [opportunityId, tab]);

  if (detail.isPending) {
    return <p className="opportunity-detail-status" role="status">불러오는 중…</p>;
  }
  if (detail.isError || !item) {
    return (
      <div className="opportunity-empty">
        <EmptyState compact title="사업기회를 불러오지 못했습니다." tone="error" />
        <Button label="다시 불러오기" onClick={() => void detail.refetch()} />
      </div>
    );
  }

  const title = primaryTitle(item);
  const stages = stageViews(links);
  const nextCheck = nextCheckOf(item);
  const pendingCandidates = links.filter(isPendingCandidate);
  const unconfirmedSearches = visibleUnconfirmedSearches(links);
  const visibleLinks = links.filter((link) => link.status !== "검색 미확인" || unconfirmedSearches.includes(link));
  const unstagedLinks = visibleLinks.filter((link) => stageOfLink(link) === null);
  const notices = noticeQueries
    .map((query) => query.data)
    .filter((data): data is NoticeDetailResponse => Boolean(data));
  const noticesLoading = noticeQueries.some((query) => query.isPending);
  const noticesFailed = noticeQueries.filter((query) => query.isError).length;
  const verificationExceptions: TrackingException[] = notices.flatMap((notice) => noticeVerificationExceptions(notice));
  const signalLink = links.find((link) => link.id === item.recheck_signal_link_id) ?? null;
  const bidNoticeLink = links.find((link) => stageOfLink(link) === "입찰공고" && isConfirmedLink(link)) ?? null;
  const holdOverdue = actionReasonsOf(item).includes("hold_overdue");
  const holdText = holdReviewText(item);
  const openIssueCount = item.pending_candidate_link_count
    + (item.recheck_signal ? 1 : 0)
    + item.open_blocking_item_count
    + unconfirmedSearches.length
    + (holdOverdue ? 1 : 0);

  // 찾아보기의 기준이 되는 소유 레코드(spec §4.3). 단계가 확정됐거나 대기 후보가 있으면
  // 찾아보기 대신 그 연결을 본다.
  const ownsStage = (stage: LifecycleStage) => links.some((link) => stageOfLink(link) === stage && isConfirmedLink(link));
  const searchableTarget = (stage: LifecycleStage): OpportunitySearchTarget | null => {
    const view = stages.find((entry) => entry.stage === stage);
    if (!view || view.confirmed || view.candidate) return null;
    if (stage === "사전규격") return ownsStage("발주계획") ? "pre_spec" : null;
    if (stage === "입찰공고") return ownsStage("사전규격") || ownsStage("발주계획") ? "bid_notice" : null;
    return null;
  };

  const openTracking = () => setDialog({ kind: "tracking" });
  const openCandidate = (linkId: number) => setDialog({ kind: "candidate", linkId });
  const openChecks = () => {
    setChecksOpened(true);
    setTab("checks");
  };

  const primaryAction = () => {
    if (nextCheck.key === "tracking_decision") return { label: "추적 여부 선택", run: openTracking };
    if (nextCheck.key === "candidate_link" || nextCheck.key === "merge_confirmation") {
      const first = pendingCandidateFor(links, nextCheck.key === "merge_confirmation" ? "merge_confirmation" : "candidate_pending");
      if (first) return { label: "후보 연결 확인", run: () => openCandidate(first.id) };
    }
    if (nextCheck.key === "hold_overdue") return { label: "재검토", run: openTracking };
    if (nextCheck.key === "recheck" || nextCheck.key === "blocking_item" || nextCheck.key === "search_unconfirmed") {
      return { label: "확인 사항 열기", run: openChecks };
    }
    if (nextCheck.key === "hold_reason" || nextCheck.key === "end_reason") {
      return { label: "추적 이력 보기", run: () => setTab("decision") };
    }
    return { label: "연결 공고 보기", run: () => setTab("flow") };
  };
  const action = primaryAction();
  const latestDecision = decisions.data?.items[0] ?? null;
  const dialogCandidate = dialog?.kind === "candidate"
    ? links.find((link) => link.id === dialog.linkId)
      ?? searchResult?.candidates.find((link) => link.id === dialog.linkId)
      ?? null
    : null;

  return (
    <div className="opportunity-detail">
      {/* 상세 머리는 발주계획·사전규격과 같은 공용 부품이다(ADR-0062, 시안 M1c A안).
          본문을 스크롤해도 어느 발주기관의 어느 사업을 보고 있는지 남는다. 기관 강조
          블록은 `AgencyFeature`가 소유하므로 장식 아이콘은 두지 않는다. */}
      <StickyDecisionHeader className="review-detail-head opportunity-detail-head" label="사업 추적 상세 헤더">
        <AgencyFeature
          className="opportunity-agency"
          labelClassName="opportunity-caption"
          name={primaryAgency(item)}
          nameClassName="opportunity-agency-name"
        />
        <h3 className="opportunity-detail-title">{title}</h3>
        <div className="opportunity-row opportunity-spread">
          <p className="opportunity-caption">
            사업 #{String(item.id).padStart(3, "0")} · {originDescription(item.first_registered_stage)}
          </p>
          <Token label={item.tracking_status} size="sm" />
        </div>
      </StickyDecisionHeader>

      <TabList
        className="opportunity-detail-tabs"
        hasDivider
        onChange={(value) => {
          if (value === "checks") setChecksOpened(true);
          setTab(value as DetailTab);
        }}
        role="tablist"
        value={tab}
      >
        <Tab label="사업 흐름" panelId="opportunity-panel-flow" value="flow" />
        <Tab
          label={openIssueCount > 0 ? `확인 사항 · ${openIssueCount}` : "확인 사항"}
          panelId="opportunity-panel-checks"
          value="checks"
        />
        <Tab label="추적 이력" panelId="opportunity-panel-decision" value="decision" />
      </TabList>

      <div className="opportunity-detail-scroll" ref={scroll}>
        <div aria-label="사업 흐름" hidden={tab !== "flow"} id="opportunity-panel-flow" role="tabpanel">
          <section className="opportunity-flow-section">
            <div className="opportunity-row opportunity-spread">
              <h4>공고 연결 현황</h4>
              <p className="opportunity-caption">확정된 최근 단계 · {latestConfirmedStage(links)}</p>
            </div>
            <ol className="opportunity-lifecycle">
              {stages.map((view, index) => {
                const target = searchableTarget(view.stage);
                return (
                  <li
                    className={view.confirmed ? "is-confirmed" : view.candidate ? "is-candidate" : "is-unknown"}
                    key={view.stage}
                  >
                    <div className="opportunity-row">
                      <span aria-hidden="true" className="opportunity-step">
                        {view.confirmed ? <Check /> : index + 1}
                      </span>
                      <p><strong>{view.stage}</strong></p>
                    </div>
                    <p className="opportunity-connection-label">{view.connection}</p>
                    {target ? (
                      <Button
                        aria-expanded={searchTarget === target}
                        className="opportunity-stage-search"
                        label={`${view.stage} 찾아보기`}
                        onClick={() => setSearchTarget(searchTarget === target ? null : target)}
                        size="sm"
                        variant="ghost"
                      />
                    ) : null}
                  </li>
                );
              })}
            </ol>
            <p className="opportunity-caption">
              체크 = <strong>연결 확정</strong> · 분석 완료·입찰 참여 승인은 별도입니다.
              {unstagedLinks.length > 0
                ? ` 단계를 알 수 없는 연결 ${unstagedLinks.length}건은 아래 목록에 있습니다.`
                : ""}
            </p>
            {searchTarget ? (
              <RecordSearchPanel
                key={searchTarget}
                onClose={() => setSearchTarget(null)}
                onOpenCandidate={(candidate) => openCandidate(candidate.id)}
                onResult={setSearchResult}
                opportunityId={item.id}
                result={searchResult}
                target={searchTarget}
              />
            ) : null}
          </section>

          <section className="opportunity-next-check">
            <div className="opportunity-row">
              <CircleHelp aria-hidden="true" />
              <h4>{nextCheck.label}</h4>
            </div>
            <p className="opportunity-next-check-body">{nextCheck.description}</p>
          </section>

          <section className="opportunity-linked-section">
            <div className="opportunity-row opportunity-spread">
              <h4>연결된 공고</h4>
              <p className="opportunity-caption">후보·검색 기록 포함 {visibleLinks.length}건</p>
            </div>
            {visibleLinks.length === 0 ? (
              <p className="opportunity-caption">저장된 연결이 없습니다. 연결이 없다는 뜻이며 레코드가 없다는 뜻은 아닙니다.</p>
            ) : (
              <ul className="opportunity-linked-rows">
                {visibleLinks.map((link) => (
                  <LinkedRow key={link.id} link={link} onCompare={() => openCandidate(link.id)} onOpenChecks={openChecks} />
                ))}
              </ul>
            )}
          </section>
        </div>

        <div aria-label="확인 사항" hidden={tab !== "checks"} id="opportunity-panel-checks" role="tabpanel">
          <section className="opportunity-checks-panel">
            <div className="opportunity-row opportunity-spread">
              <h4>확인 사항</h4>
              <Token label={openIssueCount > 0 ? `미해결 ${openIssueCount}건` : "등록된 신호 없음"} size="sm" />
            </div>

            {noticesLoading ? (
              <p className="opportunity-detail-status" role="status">연결된 공고의 확인 항목을 읽는 중…</p>
            ) : null}
            {noticesFailed > 0 ? (
              <MutationFeedback tone="warning">
                연결된 공고 {noticesFailed}건을 읽지 못해 그 공고의 확인 항목은 이 목록에 없습니다. 예외가 없다는 뜻이 아닙니다.
              </MutationFeedback>
            ) : null}
            {recheckNotice ? (
              <MutationFeedback className="opportunity-recheck-notice" tone="warning">{recheckNotice}</MutationFeedback>
            ) : null}

            {pendingCandidates.map((link) => {
              const merge = link.search_strategy === "merge_confirmation";
              return (
                <div className="opportunity-check-item" key={`candidate-${link.id}`}>
                  <CircleHelp aria-hidden="true" />
                  <div>
                    <p><strong>{merge ? "병합 확인" : "연결 후보 확인"} · {stageOfLink(link) ?? linkRecordLabel(link)}</strong></p>
                    <p>
                      {merge
                        ? "공식 번호로 이어진 레코드가 사람이 고른 추적 상태를 가진 다른 사업기회에 있어 자동으로 병합하지 않았습니다. 원천 정보를 비교한 뒤 수용하면 두 사업기회가 병합됩니다."
                        : "공식 통합번호 없이 이름 검색으로 발견한 후보입니다. 원천의 사업명과 기관을 비교한 뒤 수용·기각을 선택합니다."}
                      {" "}화면이 대신 확정하지 않습니다.
                    </p>
                    <p className="opportunity-caption">검색 방식 · {searchStrategyLabel(link.search_strategy)}</p>
                    <div className="opportunity-check-actions">
                      <Button label="후보 연결 확인" onClick={() => openCandidate(link.id)} size="sm" />
                    </div>
                  </div>
                </div>
              );
            })}

            {item.recheck_signal ? (
              <div className="opportunity-check-item opportunity-recheck-item">
                <CircleHelp aria-hidden="true" />
                <div>
                  <p><strong>새 공고 재검토</strong></p>
                  <p>
                    {formatMoment(item.recheck_signal_at)}에 새 공식 레코드가 연결됐습니다. 최종 입찰 참여 판단은 별도의
                    Go/No-Go 화면에서 검토합니다.
                  </p>
                  <p className="opportunity-caption">
                    근거 · {signalLink
                      ? `${stageOfLink(signalLink) ?? linkRecordLabel(signalLink)} · ${signalLink.title?.trim() || "제목 미확인"} · ${externalIdOf(signalLink)}`
                      : "근거 링크를 찾지 못했습니다"}
                  </p>
                  <p className="opportunity-caption">신호 시각 · {formatMoment(item.recheck_signal_at)}</p>
                  {signalLink && recordRoute(signalLink) ? (
                    <div className="opportunity-check-actions">
                      <Link className="opportunity-linked-link" to={recordRoute(signalLink) as string}>
                        {recordRouteLabel(signalLink)} →
                      </Link>
                    </div>
                  ) : null}
                  <p className="opportunity-caption">
                    변경 비교 결과 · 계산 대기. 아직 비교 결과가 없습니다.
                  </p>
                  <RecheckAcknowledgement
                    key={`${item.id}:${item.recheck_signal_link_id ?? "none"}`}
                    onDirtyChange={recheckDirty}
                    onSaved={(message) => {
                      setRecheckNotice(null);
                      onSaved(message);
                    }}
                    onStale={setRecheckNotice}
                    opportunity={item}
                  />
                </div>
              </div>
            ) : null}

            {holdOverdue ? (
              <div className="opportunity-check-item">
                <CircleHelp aria-hidden="true" />
                <div>
                  <p><strong>보류 재검토 · {holdText ?? "보류 기한 지남"}</strong></p>
                  <p>
                    보류로 저장한 뒤 재검토 기한({formatMoment(item.hold_review_due_at)})이 지났습니다. 보류는 자동으로
                    풀리지 않으며, 추적 상태를 다시 저장하면 기한이 새로 시작합니다.
                  </p>
                  <div className="opportunity-check-actions">
                    <Button label="재검토" onClick={openTracking} size="sm" />
                  </div>
                </div>
              </div>
            ) : null}

            {notices.map((notice) => {
              const forNotice = verificationExceptions.filter((exception) => exception.noticeId === notice.id);
              if (forNotice.length === 0) return null;
              return (
                <div className="opportunity-check-item" key={`notice-${notice.id}`}>
                  <CircleHelp aria-hidden="true" />
                  <div>
                    <p><strong>확인 항목 답변 · {forNotice.length}건</strong></p>
                    <ul className="opportunity-dialog-list">
                      {forNotice.map((exception) => (
                        <li key={exception.title}>
                          <p><strong>{exception.title}</strong></p>
                          <p className="opportunity-caption">{exception.detail}</p>
                        </li>
                      ))}
                    </ul>
                    <div className="opportunity-check-actions">
                      <Button
                        label="확인 항목 답변 남기기"
                        onClick={() => setDialog({ kind: "notice", noticeId: notice.id })}
                        size="sm"
                      />
                      <Link
                        className="opportunity-linked-link"
                        to={{ pathname: `/judgments/${notice.id}`, search: new URLSearchParams({ run: notice.run_id }).toString() }}
                      >
                        공고 판정 이력 열기 →
                      </Link>
                    </div>
                  </div>
                </div>
              );
            })}

            {unconfirmedSearches.map((link) => {
              const target = searchTargetKindOf(link);
              return (
                <div className="opportunity-search-log" key={`search-${link.id}`}>
                  <p><strong>연결 근거 확인 · {target ? searchTargetLabel(target) : linkRecordLabel(link)}</strong></p>
                  <p>
                    이름 검색에서 레코드를 찾지 못했습니다. 레코드가 없다는 뜻이 아니며, 이 화면이 만들어 낼 수 있는
                    연결도 아닙니다.
                  </p>
                  <p className="opportunity-caption">
                    검색 방식 · {searchStrategyLabel(link.search_strategy)}
                    {link.attempted_strategies.length > 0
                      ? ` · 시도 ${link.attempted_strategies.map(searchStrategyLabel).join(", ")}`
                      : ""}
                  </p>
                  <p className="opportunity-caption">검색 미확인 · 마지막 검색 {formatMoment(link.last_searched_at)}</p>
                </div>
              );
            })}

            {openIssueCount === 0 && !noticesLoading ? (
              <div className="opportunity-quiet-state">
                <Check aria-hidden="true" />
                <p>현재 등록된 재검토 신호와 연결 예외가 없습니다.</p>
                <p className="opportunity-caption">
                  참여 자격이나 최종 입찰 가능 여부가 확인됐다는 뜻은 아닙니다.
                </p>
              </div>
            ) : null}

            <div className="opportunity-check-block">
              <h4>입찰공고 변경 비교</h4>
              {bidNoticeLink ? (
                <>
                  <Link
                    className="opportunity-linked-link"
                    to={{ pathname: `/opportunities/${item.id}/bid-delta`, search: returnSearch }}
                  >
                    변경 비교 열기 →
                  </Link>
                  <p className="opportunity-caption">
                    비교 계산은 이 화면이 하지 않습니다. 계산 결과가 없으면 대기로 표시되며 최종 Go/No-Go는 별도 화면입니다.
                  </p>
                </>
              ) : (
                <p className="opportunity-caption">
                  확정된 입찰공고 연결이 없어 변경 비교를 시작할 수 없습니다. 입찰공고가 확정 연결이 된 뒤에 열립니다.
                </p>
              )}
            </div>

            <DeepReviewEntry
              noticePk={links.find((link) => link.notice_id !== null)?.notice_id ?? null}
              opportunityId={item.id}
            />
          </section>
        </div>

        <div aria-label="추적 이력" hidden={tab !== "decision"} id="opportunity-panel-decision" role="tabpanel">
          <section className="opportunity-decision-panel">
            <div className="opportunity-row opportunity-spread">
              <h4>현재 추적 결정</h4>
              <Token label={item.tracking_status} size="sm" />
            </div>
            {decisions.isPending ? <p className="opportunity-detail-status" role="status">불러오는 중…</p> : null}
            {decisions.isError ? (
              <MutationFeedback tone="warning">
                추적 이력을 불러오지 못했습니다. 아래는 사업기회에 저장된 현재 추적 값이며 결정 기록 자체가
                없다는 뜻이 아닙니다.
              </MutationFeedback>
            ) : null}
            {decisions.isSuccess && latestDecision === null ? (
              <p className="opportunity-caption">
                기록된 추적 결정이 없습니다.
                {item.tracking_status === "미선택"
                  ? " 아직 아무도 고르지 않았습니다."
                  : " 저장된 추적 상태는 있지만 이 화면이 읽는 결정 기록에는 남아 있지 않습니다."}
              </p>
            ) : null}
            <dl className="opportunity-decision-facts">
              <div>
                <dt>선택 사유</dt>
                <dd>{latestDecision?.reason?.trim() || item.tracking_reason?.trim() || (item.tracking_status === "미선택" ? "아직 선택하지 않았습니다" : "선택 사유 미확인")}</dd>
              </div>
              <div>
                <dt>결정 기록자</dt>
                <dd>{latestDecision?.claimed_name?.trim() || item.tracking_selected_by?.trim() || "미확인"}</dd>
              </div>
              <div>
                <dt>선택 시각</dt>
                <dd>{formatMoment(latestDecision?.decided_at ?? item.tracking_selected_at)}</dd>
              </div>
            </dl>
            {holdText ? <p className="opportunity-caption">보류 재검토 기한 · {holdText} ({formatMoment(item.hold_review_due_at)})</p> : null}
            {/* 계속 추적·보류·종료는 `추적 상태 변경`이 고르고, 그 결정을 되돌리는
                일만 여기서 한다(ADR-0068). 상태 드롭다운에 `미선택`을 넣지 않는
                이유는 그대로다 — 되돌리기는 상태 선택이 아니라 결정 취소다. */}
            <div className="opportunity-decision-actions">
              <TrackingResetControl
                currentStatus={item.tracking_status}
                onReset={() => onSaved("추적 결정을 미선택으로 되돌렸습니다.")}
                opportunityId={item.id}
              />
            </div>
            <p className="opportunity-caption">결정 기록자는 감사 표식이며 담당자 지정이나 신원 인증이 아닙니다.</p>
          </section>

          {decisions.isSuccess ? (
            <section aria-labelledby="opportunity-history-title" className="opportunity-history-section">
              <div className="opportunity-row opportunity-spread">
                <h4 id="opportunity-history-title">추적 이력</h4>
                <p className="opportunity-caption">
                  결정 {decisions.data.items.length}건 · 재검토 신호 {decisions.data.recheck_events?.length ?? 0}건
                </p>
              </div>
              <p className="opportunity-caption">결정 기록과 재검토 신호 기록을 시간순(최신이 위)으로 함께 보여줍니다.</p>
              {decisions.data.items.length + (decisions.data.recheck_events?.length ?? 0) === 0 ? (
                <p className="opportunity-caption">기록된 이력이 없습니다.</p>
              ) : (
                <TrackingHistory
                  decisions={decisions.data.items}
                  events={decisions.data.recheck_events ?? []}
                  links={links}
                />
              )}
            </section>
          ) : null}
        </div>
      </div>

      <footer className="opportunity-action-footer">
        <div className="opportunity-row opportunity-spread">
          <div className="opportunity-tracking-summary">
            <div className="opportunity-row">
              <p><strong>추적 상태</strong></p>
              <Token label={item.tracking_status} size="sm" />
            </div>
            <p className="opportunity-caption">
              {item.tracking_selected_by?.trim()
                ? `${item.tracking_selected_by} · ${formatMoment(item.tracking_selected_at)}`
                : item.tracking_status === "미선택" ? "아직 사람이 선택하지 않음" : "결정 기록자 미확인"}
            </p>
          </div>
          <div className="opportunity-footer-actions">
            <Button label="추적 상태 변경" onClick={openTracking} size="sm" />
            <Button icon={<ChevronRight />} label={action.label} onClick={action.run} size="sm" variant="primary" />
          </div>
        </div>
        <p className="opportunity-caption">추적 선택과 최종 입찰 Go/No-Go는 별도의 결정입니다.</p>
      </footer>

      <TrackingStatusDialog
        key={`tracking:${item.id}:${item.tracking_selected_at ?? "unselected"}`}
        onDirtyChange={trackingDirty}
        onOpenChange={(next) => setDialog(next ? { kind: "tracking" } : null)}
        onSaved={onSaved}
        open={dialog?.kind === "tracking"}
        opportunity={item}
        title={title}
      />
      {dialog?.kind === "candidate" && dialogCandidate ? (
        <CandidateLinkDialog
          candidate={dialogCandidate}
          links={links}
          onDirtyChange={candidateDirty}
          onOpenChange={(next) => setDialog(next ? dialog : null)}
          onSaved={onSaved}
          open
        />
      ) : null}
      {dialog?.kind === "notice" && notices.some((notice) => notice.id === dialog.noticeId) ? (
        <NoticeCorrectionDialog
          exceptions={verificationExceptions.filter((exception) => exception.noticeId === dialog.noticeId)}
          notice={notices.find((notice) => notice.id === dialog.noticeId) as NoticeDetailResponse}
          onDirtyChange={noticeDirty}
          onOpenChange={(next) => setDialog(next ? dialog : null)}
          onSaved={onSaved}
          open
        />
      ) : null}
    </div>
  );
}

const DEEP_REVIEW_STATUS_LABEL: Record<string, string> = {
  queued: "대기", running: "진행 중", completed: "완료", failed: "실패", superseded: "대체됨",
};

/** 서버가 준 상태 문자열을 그대로 두고 아는 값만 한글로 옮긴다. 모르는 코드는 감추지 않는다. */
function deepReviewStatusLabel(status: string): string {
  return DEEP_REVIEW_STATUS_LABEL[status] ?? status;
}

/** `quality_status`는 이 목록 계약에서 원문 문자열이다. 알려진 네 상태만
 * `lib/qualityStatus.ts`의 문구를 쓰고, 모르는 코드는 그대로 보여 준다. */
function deepReviewQualityLabel(status: string | null): string {
  if (status === null || status === "measured" || status === "unmeasured_reference" || status === "mock_reference") {
    return qualityStatusLabel(status);
  }
  return status;
}

function deepReviewQualityVariant(status: string | null): BadgeVariant {
  if (status === null || status === "measured" || status === "unmeasured_reference" || status === "mock_reference") {
    return qualityStatusVariant(status);
  }
  return "neutral";
}

/**
 * 심층 검토 보고서 진입점 (docs/design/PRD.md §2.2, docs/0917_opportunity-tracking/spec.md §11.1).
 *
 * `GET /api/opportunities/{id}/deep-reviews`로 이 사업기회에 연결된 보고서를 목록으로 받는다.
 * 목록은 만드는 화면(사전규격 상세)을 대신하지 않으며, 여기서는 열람 진입점만 제공한다.
 */
function DeepReviewEntry({ noticePk, opportunityId }: { noticePk: number | null; opportunityId: number }) {
  const query = useQuery({
    queryKey: ["opportunity-deep-reviews", opportunityId],
    queryFn: () => api.getOpportunityDeepReviews(opportunityId),
  });
  const items = query.data?.items ?? [];

  return (
    <section aria-labelledby="opportunity-deep-review-title" className="opportunity-deep-review">
      <h4 id="opportunity-deep-review-title">심층 검토 보고서</h4>
      {query.isPending ? <p className="opportunity-detail-status" role="status">불러오는 중…</p> : null}
      {query.isError ? (
        <MutationFeedback tone="warning">
          심층 검토 보고서 목록을 불러오지 못했습니다.
          <Button label="다시 시도" onClick={() => { void query.refetch(); }} size="sm" />
        </MutationFeedback>
      ) : null}
      {query.isSuccess && items.length === 0 ? (
        <p className="opportunity-caption">
          연결된 심층 검토 보고서가 없습니다. 사전규격 상세에서 시작합니다.
        </p>
      ) : null}
      {items.length > 0 ? (
        <ul className="opportunity-deep-review-list">
          {items.map((entry) => (
            <li className="opportunity-deep-review-item" key={entry.deep_review_id}>
              <p><strong>{entry.notice_title?.trim() || "공고명 미확인"}</strong></p>
              <div className="opportunity-row">
                <Token label={deepReviewStatusLabel(entry.status)} size="sm" />
                <Badge label={deepReviewQualityLabel(entry.quality_status)} variant={deepReviewQualityVariant(entry.quality_status)} />
              </div>
              <p className="opportunity-caption">생성 · {formatMoment(entry.created_at)}</p>
              <p className="opportunity-caption">
                {entry.latest_final_opinion
                  ? `최종 의견 · ${entry.latest_final_opinion.value} · ${formatMoment(entry.latest_final_opinion.decided_at)}`
                  : "최종 의견 없음"}
              </p>
              <Link className="opportunity-linked-link" to={`/deep-reviews/${entry.deep_review_id}?from=opportunities`}>
                보고서 열기 →
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      {noticePk === null ? (
        <p className="opportunity-caption">
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
