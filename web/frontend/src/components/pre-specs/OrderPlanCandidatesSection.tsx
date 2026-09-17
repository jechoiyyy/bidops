import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { EmptyState } from "../common/EmptyState";
import { MutationFeedback } from "../common/MutationFeedback";
import { Toast } from "../common/Toast";
import { useToast } from "../common/useToast";
import { CandidateLinkDialog } from "../opportunities/CandidateLinkDialog";
import { ApiError, api } from "../../lib/api";
import { apiErrorRecoveryAction, describeApiError } from "../../lib/apiErrors";
import { formatNumber, present } from "../../lib/format";
import type {
  OpportunityMergeConflictState,
  OpportunitySearchStrategy,
  PreSpecOrderPlanCandidate,
  PreSpecOrderPlanCandidatesResponse,
} from "../../lib/types";
// `CandidateLinkDialog`의 배치 규칙은 사업 추적 화면 CSS가 갖는다. 그 화면을 거치지
// 않고 사전규격 상세로 바로 들어와도 대화상자가 같은 모양이어야 하므로 여기서도
// 읽는다. 선택자는 전부 `opportunit*` 접두사로 한정돼 이 화면으로 새지 않는다.
import "../../styles/opportunities-relaxed.css";

/**
 * 사전규격 상세 ⑥ 안의 `발주계획 후보 N건` 구역
 * (docs/0917_opportunity-tracking/spec.md §4.2·§4.4·§11.4).
 *
 * 이 사전규격을 target으로 하는 `후보 확인 대기` 연결과 그 owner 사업기회의 발주계획
 * 요약을 **서버가 준 그대로** 보여 준다. 이름·기관이 비슷하다는 이유로 화면이 같은
 * 사업이라고 판정하지 않으며, 연결은 사람이 `CandidateLinkDialog`에서 수용해야 생긴다.
 * 수용은 병합일 수 있다(spec §3.3). 이 구역은 추적 상태·적합성 등급·최종 Go/No-Go를
 * 바꾸지 않는다.
 *
 * 후보가 0건이면 한 줄 안내만 남긴다. 자동 대조는 SW사업대상 사전규격을 적재할 때만
 * 돌기 때문에(spec §4.2) 0건은 "발주계획이 없다"는 뜻이 아니다.
 */

const STRATEGY_LABEL: Record<OpportunitySearchStrategy, string> = {
  full: "사업명 전체 일치",
  breaking_split: "특수문자 앞뒤 조각 일치",
  normalized: "구분자·머리말 정리 후 일치",
  longest_fragment: "가장 긴 조각 일치",
  prefix12: "앞 12자 일치",
  merge_confirmation: "병합 확인",
};

/** 아는 전략만 한국어로 옮긴다. 모르는 코드는 숨기지 않고 그대로 보여 준다. */
function strategyLabel(value: string | null): string {
  if (value === null) return "미확인";
  return Object.prototype.hasOwnProperty.call(STRATEGY_LABEL, value)
    ? STRATEGY_LABEL[value as OpportunitySearchStrategy]
    : value;
}

function agencyMatchLabel(value: boolean | null): string {
  if (value === true) return "기관 일치";
  if (value === false) return "기관 불일치";
  return "기관 일치 미확인";
}

/**
 * 발주 예정 시기. 수집 값은 월만(`09`) 또는 연월(`2026-09`)이다. 같은 연도를 두 번
 * 적지 않고, 빠진 쪽은 다른 값에서 추정하지 않는다.
 */
function plannedOrderLabel(year: string | null, month: string | null): string {
  const plannedYear = year?.trim() || null;
  const plannedMonth = month?.trim() || null;
  if (plannedYear === null && plannedMonth === null) return "미확인";
  const monthOnly = plannedYear && plannedMonth && /^\d{4}-\d{2}$/.test(plannedMonth) && plannedMonth.startsWith(`${plannedYear}-`)
    ? plannedMonth.slice(5)
    : plannedMonth;
  if (plannedYear === null) return `연도 미확인 · ${monthOnly}월`;
  if (monthOnly === null) return `${plannedYear}년 · 월 미확인`;
  return `${plannedYear}년 ${monthOnly}월`;
}

/** 예산이 `null`이면 `값 없음`이다. 실제 0은 `0원`으로 남는다. */
function budgetLabel(value: number | null): string {
  return value === null ? "값 없음" : `${formatNumber(value)}원`;
}

function kstMoment(value: string | null): string | null {
  if (!value || Number.isNaN(Date.parse(value))) return null;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  const part = (type: string) => parts.find((item) => item.type === type)?.value;
  return `${part("year")}.${part("month")}.${part("day")} ${part("hour")}:${part("minute")} KST`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 이 사전규격의 응답이고 행마다 그릴 최소 구조가 있을 때만 받는다. 일부만 그리지 않는다. */
function isCandidatesResponse(value: unknown, noticeId: number): value is PreSpecOrderPlanCandidatesResponse {
  if (!isRecord(value) || value.notice_pk !== noticeId || !Array.isArray(value.items)) return false;
  return value.items.every((item) => isRecord(item)
    && isRecord(item.link)
    && typeof item.link.id === "number"
    && typeof item.opportunity_id === "number"
    && typeof item.tracking_status === "string"
    && Array.isArray(item.order_plans));
}

function isMergeConflictState(value: unknown): value is OpportunityMergeConflictState {
  return isRecord(value)
    && typeof value.id === "number"
    && typeof value.tracking_status === "string"
    && (value.tracking_selected_by === null || typeof value.tracking_selected_by === "string")
    && (value.tracking_selected_at === null || typeof value.tracking_selected_at === "string")
    && typeof value.recheck_signal === "boolean";
}

/**
 * 후보 수락 409 `candidate_merge_state_conflict`의 `details.opportunities[]`.
 * 분기는 typed code로만 한다. 코드는 맞는데 details 모양이 다르면 빈 목록으로 두고
 * 안내 문장만 남긴다 — 없는 사업기회를 지어내지 않는다.
 */
function readMergeConflict(error: unknown): OpportunityMergeConflictState[] | null {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== "candidate_merge_state_conflict") return null;
  const details = isRecord(error.detail) ? error.detail.details : null;
  const opportunities = isRecord(details) && Array.isArray(details.opportunities) ? details.opportunities : [];
  return opportunities.filter(isMergeConflictState);
}

interface MergeConflictNotice {
  linkId: number;
  opportunities: OpportunityMergeConflictState[];
}

function MergeConflictFeedback({ conflict }: { conflict: MergeConflictNotice }) {
  return (
    <MutationFeedback className="ps-plan-candidates-conflict" tone="error">
      <strong className="mutation-feedback-title">병합할 수 없어 후보를 연결하지 않았습니다.</strong>
      <p className="mutation-feedback-detail">
        양쪽 모두 사람이 고른 추적 상태가 있어 병합할 수 없습니다. 사업 추적에서 한쪽의 추적 결정을 먼저 정리하세요.
        <span className="mutation-feedback-code"> · 오류 코드 candidate_merge_state_conflict</span>
      </p>
      {conflict.opportunities.length > 0 ? (
        <ul aria-label="병합할 수 없는 사업기회">
          {conflict.opportunities.map((opportunity) => (
            <li key={opportunity.id}>
              <Link className="ps-ref" to={`/opportunities/${opportunity.id}`}>
                사업 추적에서 사업기회 #{opportunity.id} 열기 →
              </Link>
              {" · 추적 "}{opportunity.tracking_status}
              {" · 결정 기록자 "}{present(opportunity.tracking_selected_by, "미확인")}
              {" · 결정 시각 "}{kstMoment(opportunity.tracking_selected_at) ?? "미확인"}
              {" · 재검토 신호 "}{opportunity.recheck_signal ? "있음" : "없음"}
            </li>
          ))}
        </ul>
      ) : (
        <p>충돌한 사업기회 정보가 응답에 없어 목록을 표시하지 않습니다.</p>
      )}
    </MutationFeedback>
  );
}

function CandidateRow({
  item,
  onConfirm,
}: {
  item: PreSpecOrderPlanCandidate;
  onConfirm: () => void;
}) {
  const generatedId = useId();
  const titleId = `ps-plan-candidate-title-${generatedId}`;
  const { link } = item;
  return (
    <li className="ps-plan-candidate">
      <div className="ps-plan-candidate-body">
        {item.order_plans.length === 0 ? (
          <div className="ps-plan-candidate-plan">
            <p id={titleId} className="ps-plan-candidate-title">발주계획 요약 없음</p>
            <p className="ps-plan-candidate-meta">후보를 제안한 사업기회에 확정 연결된 발주계획이 없어 요약을 표시하지 않습니다.</p>
          </div>
        ) : item.order_plans.map((plan, index) => (
          <div key={plan.order_plan_id} className="ps-plan-candidate-plan">
            <p id={index === 0 ? titleId : undefined} className="ps-plan-candidate-title">{present(plan.title, "사업명 미확인")}</p>
            <p className="ps-plan-candidate-meta">
              {present(plan.agency_name, "기관 미확인")}
              {" · 발주 예정 "}{plannedOrderLabel(plan.planned_order_year, plan.planned_order_month)}
              {" · 예산 "}{budgetLabel(plan.budget_amount)}
              {" · 통합번호 "}{present(plan.order_plan_unty_no, "미확인")}
            </p>
          </div>
        ))}
        <p className="ps-plan-candidate-facts">
          <span className="ps-chip ps-chip-neutral">대조 방식 · {strategyLabel(link.search_strategy)}</span>
          <span className={`ps-chip ${link.agency_match === false ? "ps-chip-warn" : "ps-chip-neutral"}`}>
            {agencyMatchLabel(link.agency_match)}
          </span>
          <span className="ps-chip ps-chip-neutral">후보 사업기회 추적 · {item.tracking_status}</span>
          <Link className="ps-ref" to={`/opportunities/${item.opportunity_id}`}>사업기회 #{item.opportunity_id} →</Link>
        </p>
      </div>
      <button className="ps-btn ps-btn-sm" type="button" aria-describedby={titleId} onClick={onConfirm}>
        확인
      </button>
    </li>
  );
}

export function OrderPlanCandidatesSection({ noticeId }: { noticeId: number }) {
  const queryClient = useQueryClient();
  const headingId = `ps-plan-candidates-title-${useId()}`;
  const { toast, showToast, dismissToast } = useToast();
  const [active, setActive] = useState<PreSpecOrderPlanCandidate | null>(null);
  const [conflict, setConflict] = useState<MergeConflictNotice | null>(null);
  const [dialogDirty, setDialogDirty] = useState(false);

  const candidatesQuery = useQuery({
    queryKey: ["pre-spec-order-plan-candidates", noticeId],
    queryFn: ({ signal }) => api.getPreSpecOrderPlanCandidates(noticeId, { signal }),
    staleTime: 30_000,
  });

  // 대화상자의 "현재 확정된 연결"은 owner 사업기회의 연결에서 읽는다. §4.4 응답은
  // 대기 후보만 싣기 때문에 그것만 넘기면 발주계획이 확정돼 있는데도 "확정된 연결이
  // 아직 없습니다"라고 말하게 된다. 사업 추적 상세와 같은 query key를 쓴다.
  const activeOwnerId = active?.opportunity_id ?? null;
  const ownerQuery = useQuery({
    queryKey: ["opportunity", activeOwnerId],
    queryFn: ({ signal }) => api.getOpportunity(activeOwnerId as number, { signal }),
    enabled: activeOwnerId !== null,
    staleTime: 30_000,
  });

  // `CandidateLinkDialog`는 판정 오류를 자기 안에서 일반 409 문구로만 보여 주고 부모에
  // 알리지 않는다(그 컴포넌트는 이 작업의 소유가 아니다). 대화상자가 열린 동안에만
  // mutation 오류를 듣고, 병합 충돌 typed code일 때 details를 이 구역에 남긴다.
  const activeLinkId = active?.link.id ?? null;
  useEffect(() => {
    if (activeLinkId === null) return undefined;
    return queryClient.getMutationCache().subscribe((event) => {
      if (event.type !== "updated" || event.action.type !== "error") return;
      const opportunities = readMergeConflict(event.action.error);
      if (opportunities === null) return;
      setConflict({ linkId: activeLinkId, opportunities });
    });
  }, [activeLinkId, queryClient]);

  // route 이동 확인(`useBlocker`)은 라우터당 하나만 동작하고 이 화면은 추적 결정 폼이
  // 이미 갖고 있다. 여기서 하나를 더 걸면 그 폼의 보호가 조용히 꺼지므로, 대화상자
  // 입력은 새로고침·창 닫기만 native 경고로 지킨다.
  useEffect(() => {
    if (!dialogDirty) return undefined;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dialogDirty]);

  const openCandidate = (item: PreSpecOrderPlanCandidate) => {
    setConflict(null);
    if (active?.link.id === item.link.id) {
      void ownerQuery.refetch();
      return;
    }
    setActive(item);
  };

  const onSaved = (message: string) => {
    setConflict(null);
    showToast(message);
    void queryClient.invalidateQueries({ queryKey: ["pre-spec-order-plan-candidates", noticeId] });
    void queryClient.invalidateQueries({ queryKey: ["pre-spec-detail"] });
    void queryClient.invalidateQueries({ queryKey: ["pre-specs"] });
    void queryClient.invalidateQueries({ queryKey: ["opportunity"] });
  };

  // 저장 알림은 화면 고정 위치에 뜬다. 후보가 사라져 빈 안내로 바뀌어도 같은 자리에서
  // 알림이 남도록 모든 상태가 같은 틀을 쓴다.
  const frame = (content: ReactNode, labelledBy?: string) => (
    <section
      id="ps-record-plan-candidates"
      className="ps-record-section ps-plan-candidates"
      aria-label={labelledBy ? undefined : "발주계획 후보"}
      aria-labelledby={labelledBy}
    >
      {content}
      {toast ? <Toast message={toast.message} onDismiss={dismissToast} variant={toast.variant} /> : null}
    </section>
  );

  if (candidatesQuery.isPending) {
    return frame(<p className="ps-cap ps-muted" role="status">발주계획 후보를 확인하는 중입니다.</p>);
  }

  const invalid = candidatesQuery.isSuccess && !isCandidatesResponse(candidatesQuery.data, noticeId);
  if (candidatesQuery.isError || invalid) {
    const problem = describeApiError(candidatesQuery.error, "발주계획 후보를 확인할 수 없습니다.");
    return frame(invalid ? (
      <EmptyState
        compact
        tone="error"
        title="발주계획 후보를 표시하지 않았습니다."
        description="응답의 사전규격 번호 또는 구조가 이 화면과 맞지 않습니다. 후보가 없다는 뜻이 아닙니다."
        action={{ label: "다시 시도", onClick: () => { void candidatesQuery.refetch(); } }}
      />
    ) : (
      <EmptyState
        compact
        tone="error"
        title="발주계획 후보를 불러오지 못했습니다."
        description="후보가 없다는 뜻이 아닙니다."
        problem={problem}
        action={apiErrorRecoveryAction(problem, () => { void candidatesQuery.refetch(); })}
      />
    ));
  }

  const items = candidatesQuery.data.items;
  if (items.length === 0) {
    return frame(<p className="ps-cap ps-muted">발주계획 후보 없음 (자동 대조는 SW사업대상 사전규격에서만 합니다)</p>);
  }

  const visibleConflict = conflict && items.some((item) => item.link.id === conflict.linkId) ? conflict : null;
  const owner = activeOwnerId !== null && ownerQuery.isSuccess
    && ownerQuery.data?.id === activeOwnerId && Array.isArray(ownerQuery.data.links)
    ? ownerQuery.data
    : null;
  const ownerFailed = active !== null && (ownerQuery.isError || (ownerQuery.isSuccess && owner === null));
  const ownerProblem = ownerFailed
    ? ownerQuery.isError
      ? describeApiError(ownerQuery.error, "후보 사업기회의 연결 정보를 확인할 수 없습니다.")
      : {
        title: "후보 사업기회 응답이 요청한 사업기회와 맞지 않습니다.",
        detail: "다른 사업기회의 연결로 대신 비교하지 않습니다. 다시 불러온 뒤 확인하십시오.",
        action: "reload" as const,
        code: null,
      }
    : null;

  return frame(
    <>
      <div className="ps-plan-candidates-head">
        <h3 id={headingId} className="ps-sub">발주계획 후보 {items.length}건</h3>
        <p className="ps-cap ps-muted">공고명과 기관이 비슷한 발주계획입니다. 같은 사업인지 사람이 확인해야 연결됩니다.</p>
      </div>
      {visibleConflict ? <MergeConflictFeedback conflict={visibleConflict} /> : null}
      <ul className="ps-plan-candidate-list">
        {items.map((item) => (
          <CandidateRow key={item.link.id} item={item} onConfirm={() => openCandidate(item)} />
        ))}
      </ul>
      {active !== null && ownerQuery.isPending ? (
        <p className="ps-cap ps-muted" role="status">후보 사업기회 #{active.opportunity_id}의 연결 정보를 불러오는 중입니다.</p>
      ) : null}
      {ownerProblem && active !== null ? (
        <MutationFeedback
          problem={ownerProblem}
          tone="error"
          onRecover={() => { void ownerQuery.refetch(); }}
        >
          <p>후보 사업기회 #{active.opportunity_id}의 연결을 읽지 못해 확인 대화상자를 열지 않았습니다. 연결 상태는 바뀌지 않았습니다.</p>
          <button className="interaction-control" type="button" onClick={() => setActive(null)}>닫기</button>
        </MutationFeedback>
      ) : null}
      {active !== null && owner !== null ? (
        <CandidateLinkDialog
          key={active.link.id}
          candidate={owner.links.find((link) => link.id === active.link.id) ?? active.link}
          links={owner.links}
          onDirtyChange={setDialogDirty}
          onOpenChange={(next) => {
            if (!next) setActive(null);
          }}
          onSaved={onSaved}
          open
        />
      ) : null}
    </>,
    headingId,
  );
}
