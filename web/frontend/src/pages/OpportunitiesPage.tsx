import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { Toast } from "../components/common/Toast";
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

function LinkRow({ link, isSignalSource }: { link: OpportunityLinkView; isSignalSource: boolean }) {
  return (
    <li className={`opportunity-link ${isSignalSource ? "opportunity-link-signal" : ""}`.trim()}>
      <div className="opportunity-link-head">
        <span className="opportunity-link-kind">{linkRecordLabel(link)}</span>
        <Badge variant={link.status === "검색 미확인" ? "evidence-unknown" : "neutral"} label={link.status} />
        {link.link_type === "candidate" ? <Badge variant="alert" label="후보" /> : null}
        {isSignalSource ? <Badge variant="alert" label="이 레코드가 재검토 신호의 근거" /> : null}
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
      <p className="opportunity-link-note">{linkStatusDescription(link)}</p>
    </li>
  );
}

function TrackingForm({
  opportunity,
  onSaved,
}: {
  opportunity: OpportunityDetailResponse;
  onSaved: (message: string) => void;
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
    onSuccess: async () => {
      setError(null);
      setReason("");
      await queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      await queryClient.invalidateQueries({ queryKey: ["opportunity", opportunity.id] });
      onSaved("추적 상태를 저장했습니다.");
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught.message : "추적 상태를 저장하지 못했습니다.");
    },
  });

  const ready = reason.trim().length > 0 && actorName.trim().length > 0;

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
        담당자 이름은 감사 표식이며 로그인이 아니다. 이유는 기록으로 남는다.
      </p>
      <label>
        <span>추적 상태</span>
        <select value={status} onChange={(event) => setStatus(event.target.value as OpportunityTrackingStatus)}>
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
          rows={2}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="이 상태를 고른 이유를 남깁니다."
        />
      </label>
      <label>
        <span>담당자 이름</span>
        <input
          required
          maxLength={128}
          value={actorName}
          onChange={(event) => setActorName(event.target.value)}
          placeholder="예: 홍길동"
        />
      </label>
      {error ? <p className="opportunity-form-error">{error}</p> : null}
      <button type="submit" disabled={!ready || mutation.isPending}>
        {mutation.isPending ? "저장 중…" : "추적 상태 저장"}
      </button>
    </form>
  );
}

function OpportunityDetail({ opportunityId, onSaved }: { opportunityId: number; onSaved: (message: string) => void }) {
  const detail = useQuery({
    queryKey: ["opportunity", opportunityId],
    queryFn: ({ signal }) => api.getOpportunity(opportunityId, { signal }),
  });

  if (detail.isPending) return <p className="opportunity-detail-status">불러오는 중…</p>;
  if (detail.isError || !detail.data) {
    return <EmptyState compact tone="error" title="사업기회를 불러오지 못했습니다." />;
  }

  const item = detail.data;
  const signalLink = item.links.find((link) => link.id === item.recheck_signal_link_id);

  return (
    <div className="opportunity-detail">
      {item.recheck_signal ? (
        <div className="opportunity-signal" role="status">
          <strong>재검토가 필요합니다.</strong>
          <p>
            {formatMoment(item.recheck_signal_at)}에 이 사업기회로 새 공식 레코드가 들어왔습니다.
            사람이 고른 <b>{item.tracking_status}</b> 판정은 그대로 남아 있습니다.
          </p>
          {signalLink ? (
            <p className="opportunity-signal-source">
              근거: {linkRecordLabel(signalLink)} · {signalLink.title?.trim() || "제목 미확인"} ·{" "}
              <span className="mono">
                {signalLink.record_external_id || signalLink.external_id || signalLink.evidence_external_no || "식별자 미확인"}
              </span>
            </p>
          ) : (
            <p className="opportunity-signal-source">근거 링크를 찾지 못했습니다.</p>
          )}
        </div>
      ) : null}

      <section className="opportunity-detail-block">
        <h4>사람 판정</h4>
        <dl className="opportunity-link-facts">
          <div>
            <dt>추적 상태</dt>
            <dd>
              <Badge variant={trackingVariant(item.tracking_status)} label={item.tracking_status} />
            </dd>
          </div>
          <div>
            <dt>작성자</dt>
            <dd>{item.tracking_selected_by || "—"}</dd>
          </div>
          <div>
            <dt>선택 시각</dt>
            <dd>{formatMoment(item.tracking_selected_at)}</dd>
          </div>
          <div>
            <dt>이유</dt>
            <dd>{item.tracking_reason || "—"}</dd>
          </div>
        </dl>
      </section>

      <section className="opportunity-detail-block">
        <h4>연결된 레코드 {item.links.length}건</h4>
        {item.links.length === 0 ? (
          <EmptyState compact title="연결된 레코드가 없습니다." />
        ) : (
          <ul className="opportunity-links">
            {item.links.map((link) => (
              <LinkRow key={link.id} link={link} isSignalSource={link.id === item.recheck_signal_link_id} />
            ))}
          </ul>
        )}
      </section>

      <TrackingForm opportunity={item} onSaved={onSaved} />
    </div>
  );
}

export function OpportunitiesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // 필터가 비어 있으면 `종료`를 포함한 전부가 보인다. 기본으로 숨기는 것이 있으면
  // 놓친 건을 사람이 확인할 방법이 없다.
  const trackingStatus = (searchParams.get("tracking_status") as OpportunityTrackingStatus | null) ?? null;
  const stage = (searchParams.get("first_registered_stage") as OpportunityFirstRegisteredStage | null) ?? null;
  const offset = Number(searchParams.get("offset") ?? "0") || 0;

  const list = useQuery({
    queryKey: ["opportunities", trackingStatus, stage, offset],
    queryFn: ({ signal }) =>
      api.getOpportunities(
        { tracking_status: trackingStatus, first_registered_stage: stage, limit: PAGE_SIZE, offset },
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
    setSelectedId(null);
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
            const open = selectedId === item.id;
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
                <button
                  className="opportunity-card-toggle"
                  type="button"
                  aria-expanded={open}
                  onClick={() => setSelectedId(open ? null : item.id)}
                >
                  {open ? "접기" : "자세히 보기"}
                </button>
                {open ? <OpportunityDetail opportunityId={item.id} onSaved={setToast} /> : null}
              </li>
            );
          })}
        </ol>
      ) : null}

      {total > PAGE_SIZE ? (
        <nav className="opportunity-pager">
          <button
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

      {toast ? <Toast message={toast} onDismiss={() => setToast(null)} /> : null}
    </section>
  );
}
