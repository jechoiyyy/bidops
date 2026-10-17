import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useLocation, useNavigate, useParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { EmptyState } from "../components/common/EmptyState";
import { Toast } from "../components/common/Toast";
import { useToast } from "../components/common/useToast";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { CandidateLinkDialog } from "../components/opportunities/CandidateLinkDialog";
import { RecheckAcknowledgement } from "../components/opportunities/RecheckAcknowledgement";
import { TrackingResetControl } from "../components/opportunities/TrackingResetControl";
import { TrackingStatusDialog } from "../components/opportunities/TrackingStatusDialog";
import { formatMoment, isPendingCandidate, recordRoute, recordRouteLabel } from "../components/opportunities/trackingFlow";
import { ActivityFeed } from "../components/record/ActivityFeed";
import { AttributeList } from "../components/record/AttributeList";
import { COMPOSER_ACTOR_ID, Composer } from "../components/record/Composer";
import { NextActions } from "../components/record/NextActions";
import { RecordHeader, type RecordMenuAction, type VerdictMenuAction } from "../components/record/RecordHeader";
import { StageBar } from "../components/record/StageBar";
import { usePublishRecordTitle } from "../components/shell/RecordTitleContext";
import { FeedbackDialog } from "../components/verdict/FeedbackDialog";
import { RunInfoDialog } from "../components/verdict/RunInfoDialog";
import { VerdictRequestDialog } from "../components/verdict/VerdictRequestDialog";
import { VerdictSummary } from "../components/verdict/VerdictSummary";
import { OpportunityVerdictTab } from "./OpportunityVerdictTab";
import { ApiError, api } from "../lib/api";
import { describeApiError, type ApiErrorDescription } from "../lib/apiErrors";
import { generateRequestId } from "../lib/requestId";
import {
  latestAuthority,
  latestNoticeLink,
  noteFingerprint,
  openActions,
  parseRecordTab,
  recordAttributes,
  recordPills,
  representativeLinks,
  RECORD_TAB_EMPTY,
  RECORD_TAB_LABEL,
  RECORD_TABS,
  SIMILAR_EMPTY_NO_NOTICE,
  type ActivityFilter,
  type RecordTab,
} from "../lib/record";
import type {
  OpportunityActivityItem,
  OpportunityActivityKind,
  OpportunityNoteKind,
  RelatedNoticeRelation,
  VerdictFeedbackKind,
} from "../lib/types";
import { hasVerdictResult, headerVerdictPill, isVerdictActive, requirementText } from "../lib/verdict";
import "../styles/opportunities-relaxed.css";
import "../styles/opportunity-record.css";

/*
 * 사업기회 레코드 `/opportunities/:id/:tab`(ui-spec §4.3, RL-02 spec "레코드 라우트"·"화면").
 *
 * 헤더(단계·마감·판정·추적 pill, 액션) · 탭 줄 · 좌측 정보(속성 8개·다음 행동·제출 서류) · 중앙
 * (활동 탭: 단계 바 → 작성기 → 활동 피드). 판정 탭(RL-03)은 서버 판정 view를 읽어 좌측을 판정
 * 요약으로 바꾸고 중앙에 요구사항 표·원문 패널을 둔다. 제안서·서류 탭은 후속 기능(RL-04)이 채울
 * 자리라 빈 상태 문장만 둔다.
 *
 * 이 화면은 값을 계산하지 않는다. 단계 6개·레코드 제목·활동 항목은 활동 응답이 주고, 연결·추적
 * 상태는 사업기회 응답이 주며, 금액·계약방법 같은 공고 사실은 공고 응답이 준다. 추적 상태 변경·
 * 되돌리기·신호 확인·후보 연결은 목록 화면과 같은 기존 대화상자를 ⋯ 메뉴에서 연다 — 저장
 * 규칙을 여기서 다시 만들지 않는다. 목록의 빠른 조작 화면(`OpportunityDetail`)은 그대로 있다.
 */

const FEED_LIMIT = 50;
const ACTION_EVENT_KINDS: readonly OpportunityActivityKind[] = ["action_added", "action_done"];
const ACTION_EVENT_LIMIT = 200;
/** 분석 중(pending·running)인 판정을 다시 읽는 간격. */
const VERDICT_POLL_MS = 5000;

const RELATION_LABEL: Record<RelatedNoticeRelation, string> = {
  ordinal: "같은 공고 · 다른 차수",
  unified: "같은 사업",
  pre_spec: "같은 사전규격에서 파생",
};

type OpenDialog = "tracking" | "reset" | "signal" | { kind: "candidate"; linkId: number } | null;

type VerdictDialogState =
  | null
  | { kind: "request" }
  | { kind: "run-info" }
  | { kind: "feedback"; unit: { unitId: string; requirement: string } | null; initialKind: VerdictFeedbackKind };

function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/** 주소 검사: 식별자·탭이 올바르지 않으면 화면을 만들지 않고 올바른 주소로 보낸다. */
export function OpportunityRecordPage() {
  const { opportunityId: idParam, tab: tabParam } = useParams();
  const location = useLocation();
  const id = Number(idParam);
  const validId = /^\d+$/.test(idParam ?? "") && Number.isSafeInteger(id) && id > 0;
  const tab = parseRecordTab(tabParam);
  if (!validId) {
    return (
      <section aria-label="사업기회 레코드" className="rec-page">
        <EmptyState
          action={{ label: "사업기회 목록 열기", to: "/opportunities" }}
          compact
          title="사업기회 식별자가 올바르지 않습니다"
        />
      </section>
    );
  }
  if (tab === null) {
    return <Navigate replace to={{ pathname: `/opportunities/${id}/activity`, search: location.search }} />;
  }
  // 레코드가 바뀌면 작성 중인 입력·열린 대화상자·필터를 다시 시작한다.
  return <OpportunityRecord key={id} opportunityId={id} tab={tab} />;
}

function OpportunityRecord({ opportunityId, tab }: { opportunityId: number; tab: RecordTab }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const { toast, showToast, dismissToast } = useToast();

  const detail = useQuery({
    queryKey: ["opportunity", opportunityId],
    queryFn: ({ signal }) => api.getOpportunity(opportunityId, { signal }),
    retry: false,
  });
  const feed = useInfiniteQuery({
    queryKey: ["opportunity-activity", opportunityId, "feed"],
    queryFn: ({ pageParam, signal }) =>
      api.getOpportunityActivity(opportunityId, { before: pageParam, limit: FEED_LIMIT }, { signal }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_before ?? undefined,
    retry: false,
  });
  const actionEvents = useQuery({
    queryKey: ["opportunity-activity", opportunityId, "actions"],
    queryFn: ({ signal }) =>
      api.getOpportunityActivity(opportunityId, { kinds: ACTION_EVENT_KINDS, limit: ACTION_EVENT_LIMIT }, { signal }),
    retry: false,
  });

  const firstPage = feed.data?.pages[0] ?? null;
  const items = useMemo<OpportunityActivityItem[]>(() => {
    const seen = new Set<string>();
    const merged: OpportunityActivityItem[] = [];
    for (const page of feed.data?.pages ?? []) {
      for (const item of page.items) {
        if (seen.has(item.item_id)) continue;
        seen.add(item.item_id);
        merged.push(item);
      }
    }
    return merged;
  }, [feed.data]);

  const item = detail.data ?? null;
  const links = useMemo(() => item?.links ?? [], [item]);
  // 단계 대표 연결은 서버가 활동 응답 `stages[].link_id`로 준다. 응답 전에는 `null`이다.
  const stages = firstPage?.stages ?? null;
  const reps = useMemo(() => representativeLinks(links, stages), [links, stages]);
  const noticeLink = useMemo(() => latestNoticeLink(reps), [reps]);
  const noticePk = noticeLink?.notice_id ?? null;

  const notice = useQuery({
    queryKey: ["notice", noticePk],
    queryFn: () => api.getNotice(noticePk as number),
    enabled: noticePk !== null,
    staleTime: 30_000,
    retry: false,
  });
  const related = useQuery({
    queryKey: ["notice-related", noticePk],
    queryFn: () => api.getRelatedNotices(noticePk as number),
    enabled: noticePk !== null && tab === "similar",
    staleTime: 30_000,
    retry: false,
  });

  // 참여 판정(RL-03). 헤더 판정 pill·`판정 보기`와 판정 탭이 같은 응답을 읽는다. 분석 중이면 주기적으로 다시 읽는다.
  const verdictQuery = useQuery({
    queryKey: ["opportunity-verdict", opportunityId],
    queryFn: ({ signal }) => api.getOpportunityVerdict(opportunityId, {}, { signal }),
    retry: false,
    refetchInterval: (query) => (isVerdictActive(query.state.data) ? VERDICT_POLL_MS : false),
  });
  const verdictView = verdictQuery.data ?? null;

  usePublishRecordTitle(opportunityId, firstPage?.title ?? null);

  // ── 입력·대화상자 상태 ─────────────────────────────────────────────
  const [dialog, setDialog] = useState<OpenDialog>(null);
  // 판정 대화상자(RL-03). 열 때마다 새로 마운트해 요청 식별자·입력이 새로 시작된다.
  const [verdictDialog, setVerdictDialog] = useState<VerdictDialogState>(null);
  const [dirtySources, setDirtySources] = useState<Record<string, boolean>>({});
  const setSourceDirty = useCallback((key: string, dirty: boolean) => {
    setDirtySources((current) => (Boolean(current[key]) === dirty ? current : { ...current, [key]: dirty }));
  }, []);
  const trackingDirty = useCallback((dirty: boolean) => setSourceDirty("tracking", dirty), [setSourceDirty]);
  const candidateDirty = useCallback((dirty: boolean) => setSourceDirty("candidate", dirty), [setSourceDirty]);
  const recheckDirty = useCallback((dirty: boolean) => setSourceDirty("recheck", dirty), [setSourceDirty]);

  const [filter, setFilter] = useState<ActivityFilter>("all");
  const [body, setBody] = useState("");
  const [owner, setOwner] = useState("");
  const [actorName, setActorName] = useState("");
  const [actorMissing, setActorMissing] = useState(false);
  const [noteProblem, setNoteProblem] = useState<ApiErrorDescription | null>(null);
  const [pendingNoteId, setPendingNoteId] = useState<string | null>(null);
  const noteLock = useRef(false);
  /** 같은 입력의 재전송은 같은 요청 식별자를 쓴다(응답을 잃은 저장이 중복되지 않게). */
  const pendingRequest = useRef<{ fingerprint: string; requestId: string } | null>(null);

  const composerDirty = body.trim().length > 0;
  const dirty = composerDirty || Object.values(dirtySources).some(Boolean);
  useUnsavedGuard(dirty, {
    blockSpaNavigation: true,
    title: "사업기회 레코드를 떠납니다",
    message: "저장하지 않은 입력이 있습니다. 지금 이동하면 사라지며 이미 저장된 노트와 추적 상태는 바뀌지 않습니다.",
  });

  const refreshRecord = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["opportunity-activity", opportunityId] }),
      queryClient.invalidateQueries({ queryKey: ["opportunity", opportunityId] }),
      queryClient.invalidateQueries({ queryKey: ["opportunities"] }),
    ]);
  }, [opportunityId, queryClient]);

  const afterSaved = useCallback((message: string) => {
    setDialog(null);
    showToast(message);
    void refreshRecord();
  }, [refreshRecord, showToast]);

  // ── 노트·다음 행동 저장 ───────────────────────────────────────────
  const createNote = useMutation({
    mutationFn: (input: { kind: OpportunityNoteKind; body: string; owner: string; actor: string; requestId: string }) =>
      api.createOpportunityNote(
        opportunityId,
        {
          kind: input.kind,
          body: input.body,
          ...(input.kind === "action" && input.owner ? { owner: input.owner } : {}),
          request_id: input.requestId,
        },
        input.actor,
      ),
  });

  const submitNote = useCallback(async (kind: OpportunityNoteKind) => {
    const text = body.trim();
    if (text.length === 0 || noteLock.current) return;
    if (!actorName.trim()) {
      setActorMissing(true);
      document.getElementById(COMPOSER_ACTOR_ID)?.focus();
      return;
    }
    setActorMissing(false);
    const ownerName = kind === "action" ? owner.trim() : "";
    const fingerprint = noteFingerprint(kind, text, ownerName, actorName.trim());
    if (pendingRequest.current?.fingerprint !== fingerprint) {
      pendingRequest.current = { fingerprint, requestId: generateRequestId() };
    }
    noteLock.current = true;
    setNoteProblem(null);
    try {
      await createNote.mutateAsync({
        kind,
        body: text,
        owner: ownerName,
        actor: actorName.trim(),
        requestId: pendingRequest.current.requestId,
      });
      pendingRequest.current = null;
      setBody("");
      if (kind === "action") setOwner("");
      showToast(kind === "action" ? "다음 행동을 남겼습니다." : "노트를 남겼습니다.");
      await refreshRecord();
    } catch (error) {
      // 실패한 입력은 그대로 두고, 같은 입력의 재시도는 같은 요청 식별자를 쓴다.
      setNoteProblem(describeApiError(error, "노트를 저장하지 못했습니다."));
    } finally {
      noteLock.current = false;
    }
  }, [actorName, body, createNote, owner, refreshRecord, showToast]);

  const completeAction = useMutation({
    mutationFn: (input: { noteId: string; actor: string }) =>
      api.completeOpportunityNoteAction(opportunityId, input.noteId, generateRequestId(), input.actor),
  });

  const onCompleteAction = useCallback(async (noteId: string) => {
    if (noteLock.current || pendingNoteId !== null) return;
    if (!actorName.trim()) {
      setActorMissing(true);
      showToast("완료로 표시하려면 담당자 이름을 먼저 입력하세요. 이름은 기록에 남는 표식이며 인증이 아닙니다.", "warning");
      document.getElementById(COMPOSER_ACTOR_ID)?.focus();
      return;
    }
    setActorMissing(false);
    setPendingNoteId(noteId);
    try {
      await completeAction.mutateAsync({ noteId, actor: actorName.trim() });
      showToast("다음 행동을 완료로 표시했습니다.");
      await refreshRecord();
    } catch (error) {
      const problem = describeApiError(error, "완료로 표시하지 못했습니다.");
      showToast(`${problem.title} ${problem.detail}`, "error");
    } finally {
      setPendingNoteId(null);
    }
  }, [actorName, completeAction, pendingNoteId, refreshRecord, showToast]);

  // ── 탭 이동 ────────────────────────────────────────────────────────
  const goTab = useCallback((next: string) => {
    const target = parseRecordTab(next);
    if (target === null || target === tab) return;
    navigate({ pathname: `/opportunities/${opportunityId}/${target}`, search: location.search });
  }, [location.search, navigate, opportunityId, tab]);
  // ←→는 초점만 옮기는 roving tabindex다. 방향키로 옮긴 초점은 그 탭을 연다(자동 활성).
  const arrowIntent = useRef(false);

  // ── 병합·오류·로딩 ────────────────────────────────────────────────
  const mergedInto = firstPage?.merged_into_opportunity_id ?? null;
  useEffect(() => {
    // 병합 대상으로 옮겨 간 뒤에는 이 레코드의 입력을 이어 쓰지 않는다.
    if (mergedInto !== null) setDialog(null);
  }, [mergedInto]);
  if (mergedInto !== null) {
    return <Navigate replace to={{ pathname: `/opportunities/${mergedInto}/${tab}`, search: location.search }} />;
  }

  if (isNotFound(detail.error) || isNotFound(feed.error)) {
    return (
      <section aria-label="사업기회 레코드" className="rec-page">
        <EmptyState
          action={{ label: "사업기회 목록 열기", to: "/opportunities" }}
          compact
          description="없거나 이미 지워진 사업기회입니다. 목록에서 다시 여십시오."
          title="사업기회를 찾을 수 없습니다"
        />
      </section>
    );
  }
  if (detail.isError || !item) {
    if (detail.isPending) {
      return (
        <section aria-label="사업기회 레코드" className="rec-page">
          <p className="rec-status" role="status">사업기회를 불러오는 중입니다.</p>
        </section>
      );
    }
    return (
      <section aria-label="사업기회 레코드" className="rec-page">
        <EmptyState
          action={{ label: "다시 시도", onClick: () => { void detail.refetch(); } }}
          compact
          problem={describeApiError(detail.error, "사업기회를 불러오지 못했습니다.")}
          title="사업기회를 불러오지 못했습니다"
          tone="error"
        />
      </section>
    );
  }

  const now = new Date();
  const title = firstPage?.title ?? `#${opportunityId}`;
  const latest = latestAuthority(reps);
  const pills = recordPills(item, reps, now, headerVerdictPill(verdictView));
  const attributes = recordAttributes({ item, reps, notice: notice.data ?? null, activityItems: items });
  const pendingCandidate = links.find(isPendingCandidate) ?? null;
  const open = openActions(actionEvents.data?.items ?? []);
  const hasActionHistory = (actionEvents.data?.items.length ?? 0) > 0;

  const onMenuSelect = (action: RecordMenuAction) => {
    if (action === "candidate") {
      if (pendingCandidate) setDialog({ kind: "candidate", linkId: pendingCandidate.id });
      return;
    }
    setDialog(action);
  };
  const verdictActive = isVerdictActive(verdictView);
  const hasFeedbackTarget = verdictView !== null && verdictView.availability !== "none" && verdictView.attempt_id !== null;
  const onVerdictMenu = (action: VerdictMenuAction) => {
    if (action === "verdict-run-info") setVerdictDialog({ kind: "run-info" });
    else setVerdictDialog({ kind: "feedback", unit: null, initialKind: "wrong_verdict" });
  };
  const afterVerdictRequested = () => {
    setVerdictDialog(null);
    showToast("판정을 요청했습니다. 분석이 끝나면 이 탭에 결과가 보입니다.");
    void queryClient.invalidateQueries({ queryKey: ["opportunity-verdict", opportunityId] });
    void queryClient.invalidateQueries({ queryKey: ["opportunity-activity", opportunityId] });
  };
  const dialogCandidate = typeof dialog === "object" && dialog !== null
    ? links.find((link) => link.id === dialog.linkId) ?? null
    : null;

  const feedProblem = feed.isError ? describeApiError(feed.error, "활동을 불러오지 못했습니다.") : null;
  const sourceLink = noticeLink ?? latest?.link ?? null;
  const sourcePath = sourceLink ? recordRoute(sourceLink) : null;
  const externalUrl = notice.data?.url && /^https?:\/\//i.test(notice.data.url) ? notice.data.url : null;

  return (
    <section aria-label="사업기회 레코드" className="rec-page" data-opportunity-id={opportunityId}>
      <RecordHeader
        agency={attributes.find((attribute) => attribute.key === "agency")?.value ?? null}
        menu={{
          resetBlockedReason: item.tracking_status === "미선택" ? "이미 미선택입니다" : null,
          signalBlockedReason: item.recheck_signal ? null : "확인할 신호가 없습니다",
          candidateBlockedReason: pendingCandidate ? null : "확인할 후보가 없습니다",
          onSelect: onMenuSelect,
        }}
        pills={pills}
        title={title}
        verdict={{
          onVerdictTab: tab === "verdict",
          hasResult: hasVerdictResult(verdictView),
          onOpenVerdict: () => goTab("verdict"),
          requestBlockedReason: verdictView?.notice_id === null
            ? "연결된 사전규격이 없습니다"
            : verdictActive ? "분석이 진행 중입니다" : null,
          onRequestVerdict: () => setVerdictDialog({ kind: "request" }),
          feedbackBlockedReason: hasFeedbackTarget ? null : "제보할 판정이 없습니다",
          runInfoBlockedReason: verdictView?.identity ? null : "표시할 실행 정보가 없습니다",
          onVerdictMenu,
        }}
      />

      <TabList
        className="rec-tabs"
        hasDivider
        onChange={goTab}
        onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") arrowIntent.current = true; }}
        onKeyUp={() => { arrowIntent.current = false; }}
        role="tablist"
        value={tab}
      >
        {RECORD_TABS.map((value) => (
          <Tab
            id={`record-tab-${value}`}
            key={value}
            label={RECORD_TAB_LABEL[value]}
            onFocus={() => {
              if (!arrowIntent.current) return;
              arrowIntent.current = false;
              goTab(value);
            }}
            panelId="record-panel"
            value={value}
          />
        ))}
      </TabList>

      <div className="rec-body">
        {tab === "verdict" && verdictView?.availability === "completed" && verdictView.result ? (
          <aside aria-label="판정 요약" className="rec-side">
            <VerdictSummary result={verdictView.result} />
          </aside>
        ) : (
          <aside aria-label="사업 정보" className="rec-side">
            <AttributeList attributes={attributes} />
            <NextActions
              actions={open}
              failed={actionEvents.isError}
              hasHistory={hasActionHistory}
              loading={actionEvents.isPending}
              onComplete={(noteId) => { void onCompleteAction(noteId); }}
              onShowAll={() => {
                setFilter("action");
                goTab("activity");
              }}
              pendingNoteId={pendingNoteId}
            />
            <section aria-labelledby="rec-docs-title" className="rec-side-block">
              <h3 className="rec-side-title" id="rec-docs-title">제출 서류</h3>
              <p aria-disabled="true" className="rec-side-note is-disabled">제출 서류 체크는 준비 중입니다</p>
            </section>
          </aside>
        )}

        <div aria-labelledby={`record-tab-${tab}`} className="rec-main" id="record-panel" role="tabpanel">
          {tab === "activity" ? (
            <>
              {firstPage ? (
                <StageBar stages={firstPage.stages} />
              ) : feed.isPending ? (
                <p className="rec-status" role="status">활동을 불러오는 중입니다.</p>
              ) : null}
              <Composer
                actorMissing={actorMissing}
                actorName={actorName}
                body={body}
                busy={createNote.isPending}
                onActorChange={(value) => { setActorName(value); if (value.trim()) setActorMissing(false); }}
                onBodyChange={setBody}
                onOwnerChange={setOwner}
                onSubmit={(kind) => { void submitNote(kind); }}
                owner={owner}
                problem={noteProblem}
              />
              {firstPage || feedProblem ? (
                <ActivityFeed
                  filter={filter}
                  hasMore={Boolean(feed.hasNextPage)}
                  isFetchingMore={feed.isFetchingNextPage}
                  items={items}
                  now={now}
                  onFilterChange={setFilter}
                  onLoadMore={() => { void feed.fetchNextPage(); }}
                  onRetry={() => { void feed.refetch(); }}
                  problem={feedProblem}
                />
              ) : null}
            </>
          ) : null}

          {tab === "verdict" ? (
            <OpportunityVerdictTab
              onFeedback={({ row, kind }) =>
                setVerdictDialog({ kind: "feedback", unit: { unitId: row.unit_id, requirement: requirementText(row) }, initialKind: kind })
              }
              onRequest={() => setVerdictDialog({ kind: "request" })}
              query={verdictQuery}
            />
          ) : null}

          {tab === "proposal" || tab === "documents" ? (
            <EmptyState compact title={RECORD_TAB_EMPTY[tab] ?? ""} />
          ) : null}

          {tab === "source" ? (
            <>
              <EmptyState
                action={sourcePath && sourceLink ? { label: `${recordRouteLabel(sourceLink)} →`, to: sourcePath } : undefined}
                compact
                title={RECORD_TAB_EMPTY.source ?? ""}
              />
              {externalUrl ? (
                <p className="rec-source-external">
                  <a href={externalUrl} rel="noopener noreferrer" target="_blank">나라장터 공고 원문 열기 ↗</a>
                </p>
              ) : null}
            </>
          ) : null}

          {tab === "similar" ? (
            noticePk === null ? (
              <EmptyState compact title={SIMILAR_EMPTY_NO_NOTICE} />
            ) : related.isPending ? (
              <p className="rec-status" role="status">비슷한 공고를 찾는 중입니다.</p>
            ) : related.isError ? (
              <EmptyState
                action={{ label: "다시 시도", onClick: () => { void related.refetch(); } }}
                compact
                problem={describeApiError(related.error, "비슷한 공고를 불러오지 못했습니다.")}
                title="비슷한 공고를 불러오지 못했습니다"
                tone="error"
              />
            ) : related.data.items.length === 0 ? (
              <EmptyState compact description="비어 있는 식별자는 연결 기준으로 사용하지 않습니다." title="비슷한 공고가 없습니다" />
            ) : (
              <ul aria-label="비슷한 공고" className="rec-similar-list">
                {related.data.items.map((entry) => (
                  <li className="rec-similar-item" key={entry.notice_pk}>
                    <Link className="rec-similar-title" to={`/judgments/${entry.notice_pk}`}>
                      {entry.title?.trim() || "공고명 미확인"}
                    </Link>
                    <p className="rec-similar-meta">
                      {RELATION_LABEL[entry.relation] ?? entry.relation}
                      {" · "}
                      {entry.published_at ? formatMoment(entry.published_at).slice(0, 10) : "공고일 미확인"}
                      {" · "}
                      {entry.notice_key || "식별자 미확인"}
                    </p>
                    <p className="rec-similar-meta">정정 사유: {entry.change_reason?.trim() || "없음"}</p>
                  </li>
                ))}
              </ul>
            )
          ) : null}
        </div>
      </div>

      <TrackingStatusDialog
        key={`tracking:${item.id}:${item.tracking_selected_at ?? "unselected"}`}
        onDirtyChange={trackingDirty}
        onOpenChange={(next) => setDialog(next ? "tracking" : null)}
        onSaved={afterSaved}
        open={dialog === "tracking"}
        opportunity={item}
        title={title}
      />

      <Dialog
        isOpen={dialog === "reset"}
        maxHeight="90dvh"
        onOpenChange={(next) => { if (!next) setDialog(null); }}
        padding={6}
        purpose="info"
        width="calc(var(--spacing-12) * 11)"
      >
        <div className="opportunity-dialog-body">
          <DialogHeader onOpenChange={(next) => { if (!next) setDialog(null); }} title="추적 되돌리기" />
          <TrackingResetControl
            currentStatus={item.tracking_status}
            onReset={() => afterSaved("추적 결정을 미선택으로 되돌렸습니다.")}
            opportunityId={item.id}
          />
        </div>
      </Dialog>

      <Dialog
        isOpen={dialog === "signal"}
        maxHeight="90dvh"
        onOpenChange={(next) => { if (!next) setDialog(null); }}
        padding={6}
        purpose="form"
        width="calc(var(--spacing-12) * 11)"
      >
        <div className="opportunity-dialog-body">
          <DialogHeader onOpenChange={(next) => { if (!next) setDialog(null); }} title="새 공고 신호 확인" />
          {item.recheck_signal ? (
            <>
              <p>
                {formatMoment(item.recheck_signal_at)}에 새 공식 레코드가 연결됐습니다. 최종 입찰 참여 판단은
                별도의 Go/No-Go 화면에서 검토합니다.
              </p>
              <RecheckAcknowledgement
                key={`${item.id}:${item.recheck_signal_link_id ?? "none"}`}
                onDirtyChange={recheckDirty}
                onSaved={afterSaved}
                onStale={(message) => { setDialog(null); showToast(message, "warning"); }}
                opportunity={item}
              />
            </>
          ) : (
            <p className="opportunity-caption">확인할 재검토 신호가 이미 없습니다.</p>
          )}
          <div className="opportunity-dialog-actions">
            <Button label="닫기" onClick={() => setDialog(null)} size="sm" />
          </div>
        </div>
      </Dialog>

      {dialogCandidate ? (
        <CandidateLinkDialog
          candidate={dialogCandidate}
          links={links}
          onDirtyChange={candidateDirty}
          onOpenChange={(next) => { if (!next) setDialog(null); }}
          onSaved={afterSaved}
          open
        />
      ) : null}

      {verdictDialog?.kind === "request" ? (
        <VerdictRequestDialog
          onClose={() => setVerdictDialog(null)}
          onRequested={afterVerdictRequested}
          opportunityId={opportunityId}
        />
      ) : null}

      {verdictDialog?.kind === "feedback" && verdictView && verdictView.attempt_id && verdictView.notice_id !== null ? (
        <FeedbackDialog
          attemptId={verdictView.attempt_id}
          companyId={verdictView.company_id}
          initialKind={verdictDialog.initialKind}
          noticeId={verdictView.notice_id}
          onClose={() => setVerdictDialog(null)}
          onSaved={() => { setVerdictDialog(null); showToast("판정 오류 제보를 남겼습니다."); }}
          unit={verdictDialog.unit}
        />
      ) : null}

      <RunInfoDialog onClose={() => setVerdictDialog(null)} open={verdictDialog?.kind === "run-info"} view={verdictView} />

      {toast ? <Toast message={toast.message} onDismiss={dismissToast} variant={toast.variant} /> : null}
    </section>
  );
}
