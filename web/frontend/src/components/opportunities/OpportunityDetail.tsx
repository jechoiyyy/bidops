import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Token } from "@astryxdesign/core/Token";
import { ArrowUpRight, Building2, Check, ChevronRight, CircleHelp, FileText } from "lucide-react";
import { EmptyState } from "../common/EmptyState";
import { MutationFeedback } from "../common/MutationFeedback";
import { api } from "../../lib/api";
import {
  linkRecordLabel,
  noticeVerificationExceptions,
  originDescription,
  type TrackingException,
} from "../../lib/opportunity";
import type { NoticeDetailResponse, OpportunityDetailResponse, OpportunityLinkView } from "../../lib/types";
import { CandidateLinkDialog } from "./CandidateLinkDialog";
import { NoticeCorrectionDialog } from "./NoticeCorrectionDialog";
import { TrackingStatusDialog } from "./TrackingStatusDialog";
import {
  connectionLabel,
  formatMoment,
  isConfirmedLink,
  isPendingCandidate,
  isRejectedCandidate,
  latestConfirmedStage,
  nextCheckOf,
  primaryAgency,
  primaryTitle,
  recordRoute,
  recordRouteLabel,
  stageOfLink,
  stageViews,
} from "./trackingFlow";

/**
 * 사업 추적 상세. 분할 화면의 오른쪽 pane과 단독 상세 route가 같이 쓴다.
 *
 * 세 탭은 승인된 시안 그대로다.
 *   사업 흐름       — 3단계 연결 현황, 다음 확인 하나, 연결된 공고
 *   확인 사항       — 사람이 해소해야 할 예외와 그 처리 경로
 *   최근 추적 결정  — 서버가 여는 가장 최근 결정 한 건
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
}

export function OpportunityDetail({ onDirtyChange, onSaved, opportunityId, returnSearch }: OpportunityDetailProps) {
  const [tab, setTab] = useState<DetailTab>("flow");
  const [dialog, setDialog] = useState<OpenDialog>(null);
  // 확인 사항 패널은 늘 그려 두지만(연결 화면으로 가는 길이 항상 DOM에 있어야
  // 한다) 연결된 공고를 읽는 것은 탭을 한 번 연 뒤부터다. 목록 전체를 미리 읽으면
  // 화면이 서버 부하를 만든다.
  const [checksOpened, setChecksOpened] = useState(false);
  const [dirtySources, setDirtySources] = useState<Record<string, boolean>>({});
  const scroll = useRef<HTMLDivElement>(null);

  const setSourceDirty = useCallback((key: string, dirty: boolean) => {
    setDirtySources((current) => (Boolean(current[key]) === dirty ? current : { ...current, [key]: dirty }));
  }, []);
  const trackingDirty = useCallback((dirty: boolean) => setSourceDirty("tracking", dirty), [setSourceDirty]);
  const candidateDirty = useCallback((dirty: boolean) => setSourceDirty("candidate", dirty), [setSourceDirty]);
  const noticeDirty = useCallback((dirty: boolean) => setSourceDirty("notice", dirty), [setSourceDirty]);

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
  }, [opportunityId]);

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
  const unconfirmedSearches = links.filter((link) => link.status === "검색 미확인");
  const unstagedLinks = links.filter((link) => stageOfLink(link) === null);
  const notices = noticeQueries
    .map((query) => query.data)
    .filter((data): data is NoticeDetailResponse => Boolean(data));
  const noticesLoading = noticeQueries.some((query) => query.isPending);
  const noticesFailed = noticeQueries.filter((query) => query.isError).length;
  const verificationExceptions: TrackingException[] = notices.flatMap((notice) => noticeVerificationExceptions(notice));
  const signalLink = links.find((link) => link.id === item.recheck_signal_link_id) ?? null;
  const bidNoticeLink = links.find((link) => stageOfLink(link) === "입찰공고" && isConfirmedLink(link)) ?? null;
  const openIssueCount = item.pending_candidate_link_count
    + (item.recheck_signal ? 1 : 0)
    + item.open_blocking_item_count
    + unconfirmedSearches.length;

  const openTracking = () => setDialog({ kind: "tracking" });
  const openCandidate = (linkId: number) => setDialog({ kind: "candidate", linkId });
  const openChecks = () => {
    setChecksOpened(true);
    setTab("checks");
  };

  const primaryAction = () => {
    if (nextCheck.key === "tracking_decision") return { label: "추적 여부 선택", run: openTracking };
    if (nextCheck.key === "candidate_link" && pendingCandidates[0]) {
      const first = pendingCandidates[0];
      return { label: "후보 연결 확인", run: () => openCandidate(first.id) };
    }
    if (nextCheck.key === "recheck" || nextCheck.key === "blocking_item" || nextCheck.key === "search_unconfirmed") {
      return { label: "확인 사항 열기", run: openChecks };
    }
    if (nextCheck.key === "hold_reason" || nextCheck.key === "end_reason") {
      return { label: "최근 결정 보기", run: () => setTab("decision") };
    }
    return { label: "연결 공고 보기", run: () => setTab("flow") };
  };
  const action = primaryAction();
  const latestDecision = decisions.data?.items[0] ?? null;

  return (
    <div className="opportunity-detail">
      <header className="opportunity-detail-head">
        <div className="opportunity-agency">
          <Building2 aria-hidden="true" />
          <span className="opportunity-caption">발주기관</span>
          <span className="opportunity-agency-name">{primaryAgency(item)}</span>
        </div>
        <h3 className="opportunity-detail-title">{title}</h3>
        <div className="opportunity-row opportunity-spread">
          <p className="opportunity-caption">
            사업 #{String(item.id).padStart(3, "0")} · {originDescription(item.first_registered_stage)}
          </p>
          <Token label={item.tracking_status} size="sm" />
        </div>
      </header>

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
        <Tab label="최근 추적 결정" panelId="opportunity-panel-decision" value="decision" />
      </TabList>

      <div className="opportunity-detail-scroll" ref={scroll}>
        <div aria-label="사업 흐름" hidden={tab !== "flow"} id="opportunity-panel-flow" role="tabpanel">
          <section className="opportunity-flow-section">
            <div className="opportunity-row opportunity-spread">
              <h4>공고 연결 현황</h4>
              <p className="opportunity-caption">확정된 최근 단계 · {latestConfirmedStage(links)}</p>
            </div>
            <ol className="opportunity-lifecycle">
              {stages.map((view, index) => (
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
                </li>
              ))}
            </ol>
            <p className="opportunity-caption">
              체크 = <strong>연결 확정</strong> · 분석 완료·입찰 참여 승인은 별도입니다.
              {unstagedLinks.length > 0
                ? ` 단계를 알 수 없는 연결 ${unstagedLinks.length}건은 아래 목록에 있습니다.`
                : ""}
            </p>
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
              <p className="opportunity-caption">후보·검색 기록 포함 {links.length}건</p>
            </div>
            {links.length === 0 ? (
              <p className="opportunity-caption">저장된 연결이 없습니다. 연결이 없다는 뜻이며 레코드가 없다는 뜻은 아닙니다.</p>
            ) : (
              <ul className="opportunity-linked-rows">
                {links.map((link) => (
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

            {pendingCandidates.map((link) => (
              <div className="opportunity-check-item" key={`candidate-${link.id}`}>
                <CircleHelp aria-hidden="true" />
                <div>
                  <p><strong>연결 후보 확인 · {stageOfLink(link) ?? linkRecordLabel(link)}</strong></p>
                  <p>
                    공식 통합번호 없이 이름 검색으로 발견한 후보입니다. 원천의 사업명과 기관을 비교한 뒤 수용·기각을
                    선택합니다. 화면이 대신 확정하지 않습니다.
                  </p>
                  <div className="opportunity-check-actions">
                    <Button label="후보 연결 확인" onClick={() => openCandidate(link.id)} size="sm" />
                  </div>
                </div>
              </div>
            ))}

            {item.recheck_signal ? (
              <div className="opportunity-check-item">
                <CircleHelp aria-hidden="true" />
                <div>
                  <p><strong>새 공고 재검토</strong></p>
                  <p>
                    {formatMoment(item.recheck_signal_at)}에 새 공식 레코드가 연결됐습니다. 최종 입찰 참여 판단은 별도의
                    Go/No-Go 화면에서 검토합니다.
                  </p>
                  <p className="opportunity-caption">
                    근거 · {signalLink
                      ? `${stageOfLink(signalLink) ?? linkRecordLabel(signalLink)} · ${externalIdOf(signalLink)}`
                      : "근거 링크를 찾지 못했습니다"}
                  </p>
                  <div className="opportunity-check-actions">
                    {signalLink && recordRoute(signalLink) ? (
                      <Link className="opportunity-linked-link" to={recordRoute(signalLink) as string}>
                        {recordRouteLabel(signalLink)} →
                      </Link>
                    ) : null}
                  </div>
                  <p className="opportunity-caption">
                    변경 비교 결과 · 계산 대기. 아직 비교 결과가 없습니다.
                  </p>
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

            {unconfirmedSearches.map((link) => (
              <div className="opportunity-search-log" key={`search-${link.id}`}>
                <p><strong>연결 근거 확인 · {stageOfLink(link) ?? linkRecordLabel(link)}</strong></p>
                <p>
                  이름 검색에서 레코드를 찾지 못했습니다. 레코드가 없다는 뜻이 아니며, 이 화면이 만들어 낼 수 있는
                  연결도 아닙니다.
                </p>
                <p className="opportunity-caption">
                  검색 방식 · {link.search_strategy ?? "미확인"}
                  {link.attempted_strategies.length > 0 ? ` · 시도 ${link.attempted_strategies.join(", ")}` : ""}
                </p>
                <p className="opportunity-caption">마지막 검색 · {formatMoment(link.last_searched_at)}</p>
              </div>
            ))}

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

            <DeepReviewEntry noticePk={links.find((link) => link.notice_id !== null)?.notice_id ?? null} />
          </section>
        </div>

        <div aria-label="최근 추적 결정" hidden={tab !== "decision"} id="opportunity-panel-decision" role="tabpanel">
          <section className="opportunity-decision-panel">
            <div className="opportunity-row opportunity-spread">
              <h4>가장 최근 추적 결정</h4>
              <Token label={item.tracking_status} size="sm" />
            </div>
            {decisions.isPending ? <p className="opportunity-detail-status" role="status">불러오는 중…</p> : null}
            {decisions.isError ? (
              <MutationFeedback tone="warning">
                최근 추적 결정 기록을 불러오지 못했습니다. 아래는 사업기회에 저장된 현재 추적 값이며 결정 기록 자체가
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
            <p className="opportunity-caption">
              이 화면에서는 가장 최근 결정 한 건을 보여줍니다.
              {latestDecision?.previous_tracking_status
                ? ` 이전 상태 · ${latestDecision.previous_tracking_status} → ${latestDecision.tracking_status}.`
                : ""}
              {" "}결정 기록자는 감사 표식이며 담당자 지정이나 신원 인증이 아닙니다.
            </p>
          </section>
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
      {dialog?.kind === "candidate" && links.some((link) => link.id === dialog.linkId) ? (
        <CandidateLinkDialog
          candidate={links.find((link) => link.id === dialog.linkId) as OpportunityLinkView}
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

/**
 * 심층 검토 보고서 진입점 (docs/design/PRD.md §2.2).
 *
 * 서버 계약이 `GET /deep-reviews/{id}` 단건 조회뿐이고 사업기회·공고로 목록을
 * 받을 엔드포인트가 없어 만들어진 보고서를 자동으로 나열할 수 없다. API 계약을
 * 바꾸지 않으므로 보고서 식별자로 여는 길을 열어 두고, 나열할 수 없다는 사실을
 * 감추지 않는다.
 */
function DeepReviewEntry({ noticePk }: { noticePk: number | null }) {
  const [deepReviewId, setDeepReviewId] = useState("");
  const trimmed = deepReviewId.trim();

  return (
    <section aria-labelledby="opportunity-deep-review-title" className="opportunity-deep-review">
      <h4 id="opportunity-deep-review-title">심층 검토 보고서</h4>
      <p className="opportunity-caption">
        이 사업기회에 연결된 심층 검토 보고서는 사전규격 상세에서 만들어집니다. 서버가 사업기회별 보고서 목록을
        제공하지 않아 여기에 자동으로 나열할 수 없습니다. 목록이 없다는 것을 보고서가 없다는 뜻으로 해석하지
        마십시오.
      </p>
      <form className="opportunity-deep-review-form" onSubmit={(event) => event.preventDefault()}>
        <label htmlFor="deep-review-id"><span>심층 검토 보고서 ID</span></label>
        <input
          id="deep-review-id"
          onChange={(event) => setDeepReviewId(event.target.value)}
          placeholder="보고서 식별자"
          value={deepReviewId}
        />
        {trimmed ? (
          <Link className="opportunity-linked-link" to={`/deep-reviews/${encodeURIComponent(trimmed)}?from=opportunities`}>
            보고서 열기 →
          </Link>
        ) : (
          <span className="opportunity-caption">식별자를 입력하면 보고서로 이동할 수 있습니다.</span>
        )}
      </form>
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
