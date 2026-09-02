import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ActorField } from "../components/common/ActorField";
import { Badge } from "../components/common/Badge";
import { DisabledReason } from "../components/common/DisabledReason";
import { EmptyState } from "../components/common/EmptyState";
import { MutationFeedback } from "../components/common/MutationFeedback";
import { Toast } from "../components/common/Toast";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { api, ApiError } from "../lib/api";
import {
  linkRecordLabel,
  linkStatusDescription,
  originDescription,
  originOf,
  trackingDescription,
  trackingVariant,
} from "../lib/opportunity";
import type {
  OpportunityDetailResponse,
  OpportunityFirstRegisteredStage,
  OpportunityLinkView,
  OpportunityListItem,
  OpportunityTrackingStatus,
} from "../lib/types";
import "../styles/opportunities-relaxed.css";

const TRACKING_STATUSES: OpportunityTrackingStatus[] = ["미선택", "계속 추적", "보류", "종료"];
const STAGES: OpportunityFirstRegisteredStage[] = ["order_plan", "pre_spec", "bid_notice"];
const SORTS = ["created_at", "tracking_status", "first_registered_stage"] as const;
type OpportunitySort = (typeof SORTS)[number];
const PAGE_SIZE = 50;

function formatMoment(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ko-KR");
}

function primaryTitle(item: OpportunityListItem | OpportunityDetailResponse): string {
  const named = item.links.find((link) => link.title && link.title.trim());
  return named?.title?.trim() || "제목 미확인";
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

function TrackingForm({
  opportunity,
  onSaved,
  onDirtyChange,
}: {
  opportunity: OpportunityDetailResponse;
  onSaved: (message: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<OpportunityTrackingStatus>(opportunity.tracking_status);
  const [reason, setReason] = useState("");
  const [actorName, setActorName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.updateOpportunityTrackingStatus(
        opportunity.id,
        { tracking_status: status, reason: reason.trim() },
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

  const ready = reason.trim().length > 0 && actorName.trim().length > 0;
  const dirty = status !== opportunity.tracking_status || reason.length > 0 || actorName.length > 0;
  const disabledReason = mutation.isPending
    ? "추적 상태 저장 요청을 처리하고 있습니다."
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
      <h4>추적 상태 변경</h4>
      <p className="opportunity-form-note">
        선택한 상태와 이유는 사람의 추적 판단 기록으로 남는다.
      </p>
      {dirty ? <p className="opportunity-form-unsaved" role="status">저장되지 않은 추적 상태 변경이 있습니다.</p> : null}
      <label>
        <span>추적 상태</span>
        <select className="interaction-control" value={status} onChange={(event) => setStatus(event.target.value as OpportunityTrackingStatus)}>
          {TRACKING_STATUSES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      <p className="opportunity-form-hint">{trackingDescription(status)}</p>
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

function OpportunityDetail({
  opportunityId,
  returnSearch,
  onSaved,
  onDirtyChange,
}: {
  opportunityId: number;
  returnSearch: string;
  onSaved: (message: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [editorOpen, setEditorOpen] = useState(false);
  const [formDirty, setFormDirty] = useState(false);
  const detail = useQuery({
    queryKey: ["opportunity", opportunityId],
    queryFn: ({ signal }) => api.getOpportunity(opportunityId, { signal }),
  });
  const handleFormDirtyChange = useCallback((nextDirty: boolean) => {
    setFormDirty(nextDirty);
    onDirtyChange(nextDirty);
  }, [onDirtyChange]);

  if (detail.isPending) return <p className="opportunity-detail-status">불러오는 중…</p>;
  if (detail.isError || !detail.data) {
    return <EmptyState compact tone="error" title="사업기회를 불러오지 못했습니다." />;
  }

  const item = detail.data;
  const signalLink = item.links.find((link) => link.id === item.recheck_signal_link_id);
  const lifecycleLinks = [...item.links].sort((left, right) => lifecycleRank(left) - lifecycleRank(right));

  return (
    <div className="opportunity-detail">
      <div className="opportunity-decision-grid">
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
        </section>

        <section className="opportunity-human-decision" aria-labelledby="tracking-decision-title">
          <div className="opportunity-panel-heading">
            <span className="opportunity-panel-kicker">사람의 추적 판단</span>
            <Badge variant={trackingVariant(item.tracking_status)} label={item.tracking_status} />
          </div>
          <h4 id="tracking-decision-title">기존 판정 유지 · 자동 변경 없음</h4>
          <p className="opportunity-human-reason">{item.tracking_reason || "기록된 이유 없음"}</p>
          <p className="opportunity-decision-meta">
            {item.tracking_selected_by || "작성자 미확인"} · {formatMoment(item.tracking_selected_at)}
          </p>
        </section>
      </div>

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

      <section className="opportunity-tracking-editor">
        <button
          className="opportunity-tracking-editor-toggle interaction-control"
          type="button"
          aria-expanded={editorOpen}
          onClick={() => {
            if (editorOpen && formDirty && !window.confirm("저장되지 않은 추적 상태 변경을 버리고 입력 영역을 닫으시겠습니까?")) return;
            if (editorOpen && formDirty) handleFormDirtyChange(false);
            setEditorOpen((current) => !current);
          }}
        >
          사람 추적 상태 변경
        </button>
        {editorOpen ? (
          <TrackingForm
            key={`${item.id}:${item.tracking_selected_at ?? "unselected"}`}
            opportunity={item}
            onSaved={onSaved}
            onDirtyChange={handleFormDirtyChange}
          />
        ) : null}
      </section>
    </div>
  );
}

export function OpportunitiesPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // 필터가 비어 있으면 `종료`를 포함한 전부가 보인다. 기본으로 숨기는 것이 있으면
  // 놓친 건을 사람이 확인할 방법이 없다.
  const trackingStatus = (searchParams.get("tracking_status") as OpportunityTrackingStatus | null) ?? null;
  const stage = (searchParams.get("first_registered_stage") as OpportunityFirstRegisteredStage | null) ?? null;
  const requestedSort = searchParams.get("sort");
  const sort: OpportunitySort = SORTS.includes(requestedSort as OpportunitySort)
    ? requestedSort as OpportunitySort
    : "created_at";
  const requestedOffset = Number(searchParams.get("offset") ?? "0");
  const offset = Number.isInteger(requestedOffset) && requestedOffset >= 0 ? requestedOffset : 0;

  const list = useQuery({
    queryKey: ["opportunities", trackingStatus, stage, sort, offset],
    queryFn: ({ signal }) =>
      api.getOpportunities(
        { tracking_status: trackingStatus, first_registered_stage: stage, sort, limit: PAGE_SIZE, offset },
        { signal },
      ),
  });

  const items = useMemo(() => list.data?.items ?? [], [list.data]);
  const total = list.data?.total ?? 0;
  const signalCount = items.filter((item) => item.recheck_signal).length;

  function applyFilter(key: string, value: string | null) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  return (
    <section className="opportunities-page" aria-labelledby="page-title">
      <header className="opportunities-header">
        <h2 id="page-title">사업기회</h2>
        <p>
          발주계획·사전규격·입찰공고를 외부 식별자로 누적한 단위다. 회차 목록이 아니라 사업 단위로 본다.
          {signalCount > 0 ? ` 재검토가 필요한 건이 ${signalCount}건 있다.` : ""}
        </p>
      </header>

      <div className="opportunities-filters">
        <label>
          <span>추적 상태</span>
          <select value={trackingStatus ?? ""} onChange={(event) => applyFilter("tracking_status", event.target.value || null)}>
            <option value="">전체 (종료 포함)</option>
            {TRACKING_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>최초 등록</span>
          <select
            value={stage ?? ""}
            onChange={(event) => applyFilter("first_registered_stage", event.target.value || null)}
          >
            <option value="">전체</option>
            {STAGES.map((value) => (
              <option key={value} value={value}>
                {originOf(value)} · {originDescription(value)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>정렬</span>
          <select value={sort} onChange={(event) => applyFilter("sort", event.target.value)}>
            <option value="created_at">최근 등록순</option>
            <option value="tracking_status">추적 상태순</option>
            <option value="first_registered_stage">최초 등록 단계순</option>
          </select>
        </label>
      </div>

      {list.isPending ? <p className="opportunity-detail-status">불러오는 중…</p> : null}
      {list.isError ? <EmptyState tone="error" title="사업기회 목록을 불러오지 못했습니다." /> : null}

      {list.isSuccess && items.length === 0 ? (
        <EmptyState
          title="조건에 맞는 사업기회가 없습니다."
          description="필터를 지우면 종료된 것을 포함한 전체를 볼 수 있습니다."
        />
      ) : null}

      {items.length > 0 ? (
        <ol className="opportunity-list">
          {items.map((item) => {
            const origin = originOf(item.first_registered_stage);
            return (
              <li key={item.id} className={`opportunity-card ${item.recheck_signal ? "opportunity-card-signal" : ""}`.trim()}>
                <div className="opportunity-card-head">
                  <Badge
                    variant={origin === "추적" ? "grade-1" : "focus"}
                    label={origin}
                    title={originDescription(item.first_registered_stage)}
                  />
                  <Badge variant={trackingVariant(item.tracking_status)} label={item.tracking_status} />
                  {item.recheck_signal ? <Badge variant="alert" label="재검토 필요" /> : null}
                  <span className="opportunity-card-id mono">#{item.id}</span>
                </div>
                <h3 className="opportunity-card-title">{primaryTitle(item)}</h3>
                <p className="opportunity-card-meta">
                  {originDescription(item.first_registered_stage)} · 연결 {item.links.length}건
                  {item.tracking_selected_by ? ` · ${item.tracking_selected_by}` : ""}
                </p>
                <Link
                  className="opportunity-card-toggle interaction-control"
                  to={{ pathname: `/opportunities/${item.id}`, search: searchParams.toString() }}
                >
                  자세히 보기
                </Link>
              </li>
            );
          })}
        </ol>
      ) : null}

      {total > PAGE_SIZE ? (
        <nav className="opportunity-pager">
          <button
            className="interaction-control"
            type="button"
            disabled={offset === 0}
            onClick={() => {
              const next = new URLSearchParams(searchParams);
              next.set("offset", String(Math.max(0, offset - PAGE_SIZE)));
              setSearchParams(next, { replace: true });
            }}
          >
            이전
          </button>
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} / {total}
          </span>
          <button
            className="interaction-control"
            type="button"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => {
              const next = new URLSearchParams(searchParams);
              next.set("offset", String(offset + PAGE_SIZE));
              setSearchParams(next, { replace: true });
            }}
          >
            다음
          </button>
        </nav>
      ) : null}

    </section>
  );
}

/**
 * 심층 검토 보고서 진입점 (docs/design/PRD.md §2.2).
 *
 * 보고서를 만든 뒤 다시 찾아갈 길이 없던 문제를 사업기회 화면에서 연다.
 * 다만 서버 계약이 `GET /deep-reviews/{id}` 단건 조회뿐이고 사업기회·공고로
 * 목록을 받을 엔드포인트가 없어(routers/deep_reviews.py) 만들어진 보고서를
 * 자동으로 나열할 수 없다. 2단계는 API 계약을 바꾸지 않으므로 보고서 식별자로
 * 여는 길을 열어 두고, 나열할 수 없다는 사실을 감추지 않고 그대로 알린다.
 * 구조 문제는 docs/tracking/findings.md에 기록했다.
 */
function DeepReviewEntry() {
  const [deepReviewId, setDeepReviewId] = useState("");
  const trimmed = deepReviewId.trim();

  return (
    <section className="opportunity-deep-review" aria-labelledby="opportunity-deep-review-title">
      <h3 id="opportunity-deep-review-title">심층 검토 보고서</h3>
      <p>
        이 사업기회에 연결된 심층 검토 보고서는 공고 판정 이력에서 만들어집니다. 서버가 사업기회별 보고서
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
          ← 사업기회 목록
        </Link>
        <h2 id="page-title">사업기회 상세{validOpportunityId ? ` #${opportunityId}` : ""}</h2>
        <p>목록의 필터·정렬·페이지 문맥을 유지한 누적 사업기회 상세다.</p>
      </header>

      {validOpportunityId ? (
        <OpportunityDetail opportunityId={opportunityId} returnSearch={searchParams.toString()} onSaved={setToast} onDirtyChange={handleDirtyChange} />
      ) : (
        <EmptyState tone="error" title="사업기회 식별자가 올바르지 않습니다." />
      )}

      {/* 최종 Go/No-Go로 가는 링크는 OpportunityDetail이 이미 하나 갖고 있다.
        * 되돌릴 수 없는 결정으로 가는 길을 둘로 늘리지 않는다. */}
      {validOpportunityId ? <DeepReviewEntry /> : null}

      {toast ? <Toast message={toast} onDismiss={() => setToast(null)} /> : null}
    </section>
  );
}
