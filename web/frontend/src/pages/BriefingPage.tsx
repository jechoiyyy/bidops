import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { BriefingTable } from "../components/briefing/BriefingTable";
import { PeekPanel } from "../components/briefing/PeekPanel";
import { useRememberedActorName } from "../components/common/ActorField";
import { EmptyState } from "../components/common/EmptyState";
import { PageHeaderActions, PageHeaderTabs } from "../components/common/PageHeaderActions";
import { usePageHeader } from "../components/shell/PageHeaderContext";
import { Toast, type ToastVariant } from "../components/common/Toast";
import { useRowKeyboardNavigation } from "../components/common/useRowKeyboardNavigation";
import { ApiError, api } from "../lib/api";
import { describeApiError } from "../lib/apiErrors";
import {
  BRIEFING_TABS,
  BRIEFING_TAB_LABEL,
  BRIEFING_TAB_REACTION,
  collectionBasisLabel,
  countByTab,
  deadlineCell,
  deadlineGroup,
  formatBriefingDateLong,
  isIsoDate,
  kstToday,
  monthDayLabel,
  parseBriefingTab,
  previousWeekday,
  safeRecordPath,
  tabOfReaction,
  type BriefingTab,
} from "../lib/briefing";
import { generateRequestId } from "../lib/requestId";
import type { BriefingItemView, BriefingReaction, BriefingView } from "../lib/types";
import "../styles/briefing.css";

/*
 * 오늘의 브리핑 `/briefing`(ui-spec §4.1, RL-01 spec "화면 `/briefing`").
 *
 * - 데이터: `?date=`가 없으면 `GET /api/briefings/latest`, 있으면 `GET /api/briefings/{date}`.
 *   `?selected=<item_id>`가 있으면 그 항목의 피크를 연다(발주계획 항목은 notice가 없어 item_id).
 * - 뷰 탭은 `reaction` 필터이고 건수는 클라이언트가 센다. 추적 변화 묶음은 반응이 없어
 *   반응 대기 탭 아래에만 둔다(반응 대기 = 사람이 아직 보지 않은 것).
 * - 반응은 추적 상태를 바꾸지 않는다. 저장은 서버가 확인한 뒤 화면에 반영하고(조용한 덮어쓰기
 *   없음), 5초 토스트의 되돌리기·`Z`는 이전 값으로의 새 PATCH다.
 * - 판정 블록·다음 행동·공고 추가·공유·가져오기·보기 설정은 대응 필드가 없어 그리지 않는다.
 * - 2026-11-19 최종 시안(`docs/1119_kstyle-shell/mockups/FinalBriefing.dc.html`): 패널 헤더에 문장형
 *   제목(반응 대기 건수)·설명(마감 전 건수·가장 가까운 마감)·수집 상태(브리핑 status와 계약상 기준일
 *   D-1)·이전 브리핑 링크·탭을 올리고, 본문은 마감 전 / 마감일 없음 / 마감 지남 묶음의 행이며 반응
 *   버튼은 행 안에 있다. 담당자 이름은 사이드바 담당자 칸 하나(`bidops.actorName`)를 쓴다.
 * - 표시 금지: 정책·점수·초 단위 생성 시각·집계 분모·모델명.
 */

const NOT_FOUND_TITLE = "이 환경에서 만들어진 브리핑이 없어요";
const EMPTY_TITLE = "오늘 추천할 공고가 없어요 · 수집 정상";
const COLLECTION_TITLE = "오늘 수집이 끝나지 않았어요";
const PANEL_ID = "briefing-panel";

/** 행 묶음 순서(최종 시안): 마감 전 → 마감일 없음 → 마감 지남. 추적 변화는 따로 맨 뒤다. */
type RowGroup = "open" | "undated" | "closed";
const GROUP_ORDER: readonly RowGroup[] = ["open", "undated", "closed"];

function groupTitle(group: RowGroup, items: readonly BriefingItemView[]): string {
  if (group === "open") return "마감 전";
  if (group === "undated") return "마감일이 정해지지 않았어요";
  // 지난 마감이 모두 의견 마감이면 시안 그대로 `의견 마감이 지났어요`다.
  return items.every((item) => item.deadline_kind === "opinion_close") ? "의견 마감이 지났어요" : "마감이 지났어요";
}
/** 되돌리기 토스트가 떠 있는 시간. 이 안에서만 `Z`가 이전 값으로 되돌린다. */
const UNDO_WINDOW_MS = 5_000;
/** 반응할 곳이 없어 초점을 목록 영역 자체에 둘 때의 표식. */
const FOCUS_CONTAINER = "__container__";

interface Notice {
  id: number;
  message: string;
  variant: ToastVariant;
  undo: { itemId: string; previous: BriefingReaction } | null;
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest("input, textarea, select, [contenteditable]"));
}

function replaceItem(view: BriefingView, saved: BriefingItemView): BriefingView {
  const swap = (item: BriefingItemView) => (item.item_id === saved.item_id ? saved : item);
  return { ...view, items: view.items.map(swap), tracked_changes: view.tracked_changes.map(swap) };
}

function NotFound({ invalidDate, dated }: { invalidDate: boolean; dated: boolean }) {
  return (
    <EmptyState
      action={{ label: "사전규격 목록 열기", to: "/pre-specs" }}
      description={
        invalidDate
          ? "주소의 날짜 형식이 올바르지 않아요(YYYY-MM-DD). 최신 브리핑을 열거나 날짜를 고쳐 다시 열어 주세요."
          : "브리핑은 일일 브리핑 스크립트가 실행되어야 만들어져요. 이 화면은 그 일정이 있는지 알 수 없으며, 지금까지 만들어진 브리핑이 없어요. 사전규격·발주계획 목록에서 공고를 확인하세요."
      }
      secondaryAction={dated || invalidDate ? { label: "최신 브리핑 열기", to: "/briefing" } : { label: "발주계획 열기", to: "/order-plans" }}
      title={NOT_FOUND_TITLE}
    />
  );
}

export function BriefingPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const dateParam = searchParams.get("date");
  const invalidDate = dateParam !== null && !isIsoDate(dateParam);
  const validDate = dateParam !== null && !invalidDate ? dateParam : null;
  const briefingKey = useMemo(() => ["briefing", validDate ?? "latest"] as const, [validDate]);

  const query = useQuery({
    queryKey: briefingKey,
    queryFn: ({ signal }) => (validDate ? api.getBriefing(validDate, { signal }) : api.getLatestBriefing({ signal })),
    enabled: !invalidDate,
    retry: false,
  });
  const briefing = query.data;

  // 담당자 이름은 사이드바 담당자 칸 하나(`bidops.actorName`)를 쓴다(최종 시안). 감사 표식이며 인증이 아니다.
  const actorName = useRememberedActorName().trim();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const lockRef = useRef(false);
  const noticeSeq = useRef(0);
  const pendingFocusRef = useRef<string | null>(null);
  const pageRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const recommendations = useMemo(() => briefing?.items ?? [], [briefing]);
  const trackedChanges = useMemo(() => briefing?.tracked_changes ?? [], [briefing]);
  const byId = useMemo(() => {
    const map = new Map<string, BriefingItemView>();
    for (const item of [...recommendations, ...trackedChanges]) map.set(item.item_id, item);
    return map;
  }, [recommendations, trackedChanges]);

  const selectedParam = searchParams.get("selected");
  const selectedItem = selectedParam !== null ? byId.get(selectedParam) ?? null : null;
  const selectedId = selectedItem?.item_id ?? null;

  // 탭은 주소의 `view`가 정한다. 없으면 선택된 항목이 속한 탭(Slack 링크로 들어온 경우), 그것도
  // 없으면 반응 대기다. 허용값 밖의 `view`는 없는 값으로 본다.
  const viewParam = parseBriefingTab(searchParams.get("view"));
  const activeTab: BriefingTab = viewParam
    ?? (selectedItem?.kind === "recommendation" && selectedItem.reaction !== null ? tabOfReaction(selectedItem.reaction) : "pending");
  const counts = useMemo(() => countByTab(recommendations), [recommendations]);

  const tabReaction = BRIEFING_TAB_REACTION[activeTab];
  const visibleRecommendations = useMemo(
    () => recommendations.filter((item) => item.reaction === tabReaction),
    [recommendations, tabReaction],
  );
  const visibleTracked = useMemo(
    () => (activeTab === "pending" ? trackedChanges : []),
    [activeTab, trackedChanges],
  );
  const keys = useMemo(
    () => [...visibleRecommendations, ...visibleTracked].map((item) => item.item_id),
    [visibleRecommendations, visibleTracked],
  );

  const select = useCallback(
    (itemId: string | null) => {
      setSearchParams((previous) => {
        const next = new URLSearchParams(previous);
        if (itemId === null) next.delete("selected");
        else next.set("selected", itemId);
        return next;
      }, { replace: true });
    },
    [setSearchParams],
  );

  // 선택 링크(`?selected=`, Slack 링크 등)로 `view` 없이 들어오면 항목이 속한 탭을 주소에 못 박는다.
  // 그렇지 않으면 항목의 반응이 바뀔 때(다른 담당자가 먼저 반응해 다시 읽을 때 등) 보는 탭이
  // 사용자 아래에서 바뀐다.
  const hasBriefing = briefing !== undefined;
  useEffect(() => {
    if (!hasBriefing || viewParam !== null || selectedId === null) return;
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("view", activeTab);
      return next;
    }, { replace: true });
  }, [activeTab, hasBriefing, selectedId, setSearchParams, viewParam]);

  const changeTab = useCallback(
    (value: string) => {
      const tab = parseBriefingTab(value);
      if (tab === null) return;
      setSearchParams((previous) => {
        const next = new URLSearchParams(previous);
        next.set("view", tab);
        // 보는 범위가 바뀌면 선택은 비운다(다른 탭의 행에 피크가 남지 않게).
        next.delete("selected");
        return next;
      }, { replace: true });
    },
    [setSearchParams],
  );

  const rowNavigation = useRowKeyboardNavigation<string>({
    containerRef: listRef,
    keys,
    selectedKey: selectedId,
    onSelect: select,
  });

  // 키 처리기와 비동기 저장이 최신 값을 읽도록 렌더마다 갱신하는 참조다.
  const live = useRef({ byId, selectedId, keys, activeTab, actorName, notice, ready: false });
  live.current = { byId, selectedId, keys, activeTab, actorName, notice, ready: briefing !== undefined };

  const showNotice = useCallback((message: string, variant: ToastVariant, undo: Notice["undo"] = null) => {
    noticeSeq.current += 1;
    setNotice({ id: noticeSeq.current, message, variant, undo });
  }, []);

  const react = useCallback(
    async (itemId: string, requested: BriefingReaction, source: "key" | "pointer", mode: "react" | "undo") => {
      const state = live.current;
      const current = state.byId.get(itemId);
      // 추적 변화 행에는 반응이 없다(서버도 409 `reaction_not_allowed`로 거절한다).
      if (!current || current.kind !== "recommendation" || current.reaction === null) return;
      if (lockRef.current) return;
      if (!state.actorName.trim()) {
        showNotice("담당자 이름을 입력한 뒤 다시 눌러 주세요. 사이드바 담당자 칸의 이름이 기록에 남아요(인증이 아니에요).", "warning");
        // 이름은 사이드바 담당자 칸에서 받는다. 칸이 닫혀 있으면 열어 입력에 초점을 둔다.
        const field = document.getElementById("sidebar-actor-input");
        if (field) field.focus();
        else document.querySelector<HTMLButtonElement>(".sidebar-actor-trigger")?.click();
        return;
      }
      // 이미 선택된 반응을 다시 누르면 `대기`로 돌아간다(토글). 되돌리기는 이전 값 그대로다.
      const target: BriefingReaction = mode === "react" && current.reaction === requested ? "대기" : requested;
      if (target === current.reaction) return;
      const previous = current.reaction;
      lockRef.current = true;
      setBusy(true);
      try {
        const saved = await api.reactBriefingItem(
          itemId,
          { reaction: target, expected_revision: current.revision, request_id: generateRequestId() },
          state.actorName,
        );
        queryClient.setQueryData<BriefingView>(briefingKey, (old) => (old ? replaceItem(old, saved) : old));
        void queryClient.invalidateQueries({ queryKey: ["workload"] });
        if (mode === "undo") {
          // 되돌린 행으로 선택을 돌려놓는다. 키보드로 되돌렸다면 초점도 따라간다.
          select(itemId);
          if (source === "key") pendingFocusRef.current = itemId;
          showNotice(`되돌렸어요 · ${saved.reaction ?? ""}`, "info");
        } else {
          const stays = saved.reaction === BRIEFING_TAB_REACTION[state.activeTab];
          if (!stays) {
            // 행이 이 탭을 떠났다. 다음 행(없으면 앞 행)으로 선택·초점을 옮긴다.
            const index = state.keys.indexOf(itemId);
            const next = state.keys[index + 1] ?? (index > 0 ? state.keys[index - 1] : null);
            if (state.selectedId === itemId) select(next);
            if (source === "key") pendingFocusRef.current = next ?? FOCUS_CONTAINER;
          }
          showNotice(
            saved.reaction === "대기" ? "반응을 취소했어요" : `반응을 저장했어요 · ${saved.reaction ?? ""}`,
            "success",
            { itemId, previous },
          );
        }
      } catch (error) {
        const code = error instanceof ApiError ? error.code : null;
        if (code === "version_conflict" || code === "idempotency_conflict") {
          // 조용히 덮어쓰지 않는다: 최신 상태를 다시 읽고 사람이 확인한 뒤 다시 누르게 한다.
          void queryClient.invalidateQueries({ queryKey: briefingKey });
          showNotice("다른 담당자가 먼저 반응했어요. 최신 상태를 불러왔으니 확인한 뒤 다시 눌러 주세요.", "warning");
        } else {
          const problem = describeApiError(error, "반응을 저장하지 못했어요.");
          showNotice(`${problem.title} ${problem.detail}`, "error");
        }
      } finally {
        lockRef.current = false;
        setBusy(false);
      }
    },
    [briefingKey, queryClient, select, showNotice],
  );

  const onReactPointer = useCallback(
    (item: BriefingItemView, reaction: BriefingReaction) => {
      void react(item.item_id, reaction, "pointer", "react");
    },
    [react],
  );

  const undo = useCallback((source: "key" | "pointer") => {
    const target = live.current.notice?.undo;
    if (!target) return;
    void react(target.itemId, target.previous, source, "undo");
  }, [react]);

  // 저장 뒤 사라진 행의 다음 행으로 초점을 옮긴다(키보드로 이어서 처리할 수 있게).
  useEffect(() => {
    const key = pendingFocusRef.current;
    const container = listRef.current;
    if (key === null || !container) return;
    const element = key === FOCUS_CONTAINER
      ? container
      : container.querySelector<HTMLElement>(`[data-row-key="${key.replace(/["\\]/g, "\\$&")}"]`);
    if (!element) return;
    pendingFocusRef.current = null;
    element.focus({ preventScroll: true });
    element.scrollIntoView({ block: "nearest" });
  });

  // 단축키: 1 볼게요 · 2 무시 · H 나중에 · Enter 열기 · Esc 닫기 · Z 되돌리기.
  // 페이지 안(또는 body)에 초점이 있을 때만, 글자를 입력하는 중이 아닐 때만 동작한다.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return;
      if (event.ctrlKey || event.altKey || event.metaKey) return;
      const target = event.target;
      if (isTypingTarget(target)) return;
      const inPage = target === document.body || (target instanceof Node && pageRef.current?.contains(target) === true);
      if (!inPage || !live.current.ready) return;
      const state = live.current;
      const focusedRow = target instanceof HTMLElement
        ? target.closest<HTMLElement>("[data-row-key]")?.getAttribute("data-row-key") ?? null
        : null;
      // 반응 단축키는 피크가 보여 주는 선택 항목에 걸린다. 선택이 없을 때만 초점이 있는 행이다.
      const reactTargetId = state.selectedId ?? focusedRow;

      if (event.key === "Escape") {
        if (state.selectedId !== null) {
          event.preventDefault();
          select(null);
        }
        return;
      }
      if (event.key === "Enter") {
        // 링크·버튼 위의 Enter는 그 요소의 동작이다. 행 버튼(또는 아무 초점이 없을 때)만 가로챈다.
        const enterId = focusedRow ?? state.selectedId;
        if (!(target === document.body || focusedRow !== null) || enterId === null) return;
        const item = state.byId.get(enterId);
        if (!item) return;
        event.preventDefault();
        const path = safeRecordPath(item.record_path);
        // 피크가 이미 열린 행에서 한 번 더 Enter면 레코드로 간다.
        if (state.selectedId === item.item_id && path) navigate(path);
        else select(item.item_id);
        return;
      }
      if (event.repeat) return;
      const code = event.code;
      const key = event.key.toLowerCase();
      let requested: BriefingReaction | null = null;
      if (key === "1" || code === "Digit1" || code === "Numpad1") requested = "채택";
      else if (key === "2" || code === "Digit2" || code === "Numpad2") requested = "무시";
      else if (key === "h" || code === "KeyH") requested = "나중에";
      if (requested !== null) {
        if (reactTargetId === null) return;
        event.preventDefault();
        void react(reactTargetId, requested, "key", "react");
        return;
      }
      if (key === "z" || code === "KeyZ") {
        if (state.notice?.undo) {
          event.preventDefault();
          undo("key");
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate, react, select, undo]);

  // ---- 패널 헤더 ------------------------------------------------------------
  const notFound = invalidDate || (query.isError && query.error instanceof ApiError && query.error.status === 404);
  const previousDate = briefing ? previousWeekday(briefing.briefing_date) : null;
  // 문장의 숫자는 이미 받은 응답에서만 센다: 반응 대기 건수(탭 건수와 같은 값)와 그 가운데 마감 전인 건.
  const openPending = useMemo(
    () => recommendations
      .filter((item) => item.reaction === "대기" && deadlineGroup(item) === "open")
      .sort((left, right) => (deadlineCell(left).days ?? 0) - (deadlineCell(right).days ?? 0)),
    [recommendations],
  );
  const headerContent = briefing ? (() => {
    const today = briefing.briefing_date === kstToday() ? "오늘 " : "";
    const pending = counts.pending;
    const title = briefing.status === "empty"
      ? `${today}추천할 공고가 없어요`
      : pending > 0
        ? `${today}반응할 추천이 ${pending.toLocaleString("ko-KR")}건 있어요`
        : `${today}추천에 모두 반응했어요`;
    const nearest = openPending[0]?.deadline_at ? monthDayLabel(openPending[0].deadline_at) : null;
    const description = briefing.status === "empty" || pending === 0
      ? null
      : openPending.length === 0
        ? "반응을 기다리는 추천 가운데 마감 전인 건은 없어요."
        : openPending.length === 1
          ? `마감 전인 건은 1건이고, ${nearest}에 마감돼요.`
          : `마감 전인 건은 ${openPending.length.toLocaleString("ko-KR")}건이고, 가장 가까운 마감은 ${nearest}이에요.`;
    return { eyebrow: `오늘의 브리핑 · ${formatBriefingDateLong(briefing.briefing_date)}`, title, description };
  })() : null;
  usePageHeader(headerContent);
  const basis = briefing ? collectionBasisLabel(briefing.briefing_date) : null;
  const grouped = useMemo(() => {
    const result: Record<RowGroup, BriefingItemView[]> = { open: [], undated: [], closed: [] };
    for (const item of visibleRecommendations) result[deadlineGroup(item)].push(item);
    return result;
  }, [visibleRecommendations]);

  let body;
  if (notFound) {
    body = <NotFound dated={validDate !== null} invalidDate={invalidDate} />;
  } else if (query.isPending) {
    body = <p className="briefing-status" role="status">브리핑을 불러오는 중이에요.</p>;
  } else if (query.isError || !briefing) {
    const problem = describeApiError(query.error, "브리핑을 불러오지 못했어요.");
    body = (
      <EmptyState
        action={{ label: "다시 시도", onClick: () => { void query.refetch(); } }}
        problem={problem}
        title="브리핑을 불러오지 못했어요"
        tone="error"
      />
    );
  } else {
    const emptyBriefing = briefing.status === "empty";
    const tabEmpty = visibleRecommendations.length === 0;
    body = (
      <>
        <PageHeaderTabs>
          <TabList onChange={changeTab} role="tablist" size="md" value={activeTab}>
            {BRIEFING_TABS.map((tab) => (
              <Tab
                endContent={<span className="briefing-tab-count" data-testid={`briefing-count-${tab}`}>{counts[tab]}</span>}
                key={tab}
                label={BRIEFING_TAB_LABEL[tab]}
                panelId={PANEL_ID}
                value={tab}
              />
            ))}
          </TabList>
        </PageHeaderTabs>


        {briefing.status === "collection_incomplete" ? (
          <section aria-label="수집 상태" className="briefing-warning" role="status">
            <strong>{COLLECTION_TITLE}</strong>
            {briefing.collection_note ? <p>{briefing.collection_note}</p> : null}
          </section>
        ) : null}

        <div className={`briefing-workspace${selectedItem ? " has-peek" : ""}`}>
          <div
            aria-label={`${BRIEFING_TAB_LABEL[activeTab]} 목록`}
            className="briefing-list"
            id={PANEL_ID}
            onKeyDown={rowNavigation.onKeyDown}
            onPointerDownCapture={rowNavigation.onPointerDownCapture}
            ref={listRef}
            role="tabpanel"
            tabIndex={-1}
          >
            {emptyBriefing ? (
              <EmptyState compact title={EMPTY_TITLE} />
            ) : tabEmpty ? (
              <EmptyState
                compact
                description={activeTab === "pending" ? "모든 추천에 반응했어요." : "이 반응을 남긴 추천이 없어요."}
                title={`${BRIEFING_TAB_LABEL[activeTab]} 항목이 없어요`}
              />
            ) : (
              GROUP_ORDER.map((group) => {
                const items = grouped[group];
                if (items.length === 0) return null;
                const titleId = `briefing-group-${group}`;
                const heading = groupTitle(group, items);
                return (
                  <section aria-labelledby={titleId} className={`briefing-group is-${group}`} key={group}>
                    <div className="briefing-group-head">
                      <h2 className="briefing-group-title" id={titleId}>{heading}</h2>
                      <span className="briefing-count" data-testid={`briefing-group-count-${group}`}>{items.length.toLocaleString("ko-KR")}건</span>
                    </div>
                    <BriefingTable
                      busy={busy}
                      emphasis={group === "open"}
                      items={items}
                      label={`${heading} 추천`}
                      onReact={onReactPointer}
                      onSelect={select}
                      rowProps={rowNavigation.rowProps}
                      selectedId={selectedId}
                    />
                  </section>
                );
              })
            )}
            {visibleTracked.length > 0 ? (
              <section aria-labelledby="briefing-tracked-title" className="briefing-group is-tracked">
                <div className="briefing-group-head">
                  <h2 className="briefing-group-title" id="briefing-tracked-title">추적 중인 사업의 변화</h2>
                  <span className="briefing-count" data-testid="briefing-tracked-count">{visibleTracked.length}</span>
                </div>
                <BriefingTable
                  busy={busy}
                  items={visibleTracked}
                  label="추적 중인 사업의 변화"
                  onReact={onReactPointer}
                  onSelect={select}
                  rowProps={rowNavigation.rowProps}
                  selectedId={selectedId}
                  tracked
                />
              </section>
            ) : null}
          </div>
          {selectedItem ? (
            <PeekPanel item={selectedItem} onClose={() => select(null)} />
          ) : null}
        </div>
      </>
    );
  }

  return (
    <section aria-labelledby="briefing-page-title" className="briefing-page" ref={pageRef}>
      <span className="visually-hidden" id="briefing-page-title">오늘의 브리핑</span>
      {briefing ? (
        <PageHeaderActions>
          {/* 수집 상태: 브리핑 status가 수집 회차(계약상 D-1)의 완료 여부를 말한다. */}
          <span className="panel-header-status" data-testid="briefing-collection-status">
            {briefing.status === "collection_incomplete" ? (
              <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} viewBox="0 0 24 24"><path d="M12 3 2 20h20z" /><path d="M12 10v4M12 17h.01" /></svg>
            ) : (
              <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.6} viewBox="0 0 24 24"><path d="m5 12 5 5 9-10" /></svg>
            )}
            <span>
              <strong>{briefing.status === "collection_incomplete" ? "수집이 끝나지 않았어요" : "수집 완료"}</strong>
              {basis ? ` · ${basis} 기준` : null}
            </span>
          </span>
          {previousDate ? (
            <Link className="panel-header-link briefing-topbar-link" to={{ pathname: "/briefing", search: `?date=${previousDate}` }}>이전 브리핑</Link>
          ) : null}
          {validDate ? <Link className="panel-header-link briefing-topbar-link" to="/briefing">최신 브리핑</Link> : null}
        </PageHeaderActions>
      ) : null}
      {body}
      {notice ? (
        <Toast
          actionLabel={notice.undo ? "되돌리기" : undefined}
          autoDismissMs={notice.undo ? UNDO_WINDOW_MS : undefined}
          key={notice.id}
          message={notice.message}
          onAction={notice.undo ? () => undo("pointer") : undefined}
          onDismiss={() => setNotice(null)}
          variant={notice.variant}
        />
      ) : null}
    </section>
  );
}
