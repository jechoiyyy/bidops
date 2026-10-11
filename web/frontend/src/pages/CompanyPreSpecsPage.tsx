import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ActorField } from "../components/common/ActorField";
import { EmptyState } from "../components/common/EmptyState";
import { ListPagerControls } from "../components/common/ReviewPrimitives";
import { CompanyFitAttempts } from "../components/company/CompanyFitAttempts";
import { CompanyHeader } from "../components/company/CompanyHeader";
import {
  CompanyFitSummaryView,
  CompanyReviewSummaryView,
  CompanyTrackingSummaryView,
} from "../components/company/CompanySummaries";
import { createCompanyLunaAdapter, LunaRequest } from "../components/deep-review/LunaRequest";
import { SourceVerificationSetting } from "../components/deep-review/SourceVerificationSetting";
import { companyTrackingAdapter, TrackingDecisionControl } from "../components/pre-specs/TrackingDecisionControl";
import { describeCompanyApiError } from "../lib/apiErrors";
import {
  COMPANY_DIRECTORY_LIMIT,
  COMPANY_FIT_FILTERS,
  COMPANY_PRE_SPEC_DEFAULT_LIMIT,
  COMPANY_PRE_SPEC_DEFAULT_SORT,
  COMPANY_PRE_SPEC_QUERY_MAX_LENGTH,
  COMPANY_TRACKING_STATUSES,
  companyApi,
  companyFitDecisionLabel,
  companyKeys,
  companyPreSpecFilterFingerprint,
  companyPreSpecListQuery,
  companyReviewStatusLabel,
  companySessionKey,
  isCompanyUuid,
  parseCompanyPreSpecListParams,
  parseNoticeId,
  type CompanyDeepReviewCreateRequest,
  type CompanyFitDecision,
  type CompanyNotice,
  type CompanyNoticeDetail,
  type CompanyPreSpecListState,
  type CompanyPreSpecSort,
  type CompanyTrackingStatus,
  type Uuid,
} from "../lib/companyApi";
import { formatDate } from "../lib/format";
import {
  createEmptyListSelection,
  nextSelectionGeneration,
  readListSelection,
  setSelectionActiveId,
  writeListSelection,
  type ListSelectionState,
} from "../lib/listSelection";
import "../styles/company-workspace.css";

/*
 * 가상회사 데모의 회사 선택·회사 사전규격 목록·상세 adapter
 * (`docs/work/groups/DEMO/features/DEMO-04-review-workspace/spec.md`, 공통 계약 §1·2·6).
 *
 * - 회사는 주소의 `companyId`가 정본이다. 화면은 회사마다 `key`로 다시 마운트되어
 *   다른 회사의 입력·선택 state가 넘어오지 않는다.
 * - 조회 key는 `companyKeys`(회사 id 포함)만 쓴다. 이전 회사 데이터를 placeholder로
 *   보여 주지 않으므로 전환 직후에는 읽는 중임을 말한다.
 * - 목록 선택은 회사별 `sessionStorage` key에 둔다(`companySessionKey`).
 * - 핏·심층 검토·추적은 서로 다른 칸이다. C-1 등급을 가상회사 판정으로 쓰지 않는다.
 */

// ---------------------------------------------------------------------------
// 회사 선택

export function CompanyPickerPage() {
  const companiesQuery = useQuery({
    queryKey: companyKeys.directory(),
    queryFn: ({ signal }) => companyApi.listCompanies({ limit: COMPANY_DIRECTORY_LIMIT, offset: 0 }, { signal }),
    staleTime: 60_000,
  });
  return (
    <section className="cw-page" aria-labelledby="company-picker-title">
      <div className="cw-section">
        <h2 id="company-picker-title">검토할 가상회사를 고르십시오</h2>
        <p className="cw-caption">
          가상회사 데모입니다. 기본 회사를 미리 정하지 않습니다. 회사를 고르면 그 회사의 프로필과
          사전규격 판정만 보이며, 다른 회사의 결과를 대신 채우지 않습니다.
        </p>
        {companiesQuery.isPending ? (
          <p role="status">회사 목록을 불러오는 중입니다.</p>
        ) : companiesQuery.isError ? (
          <EmptyState
            tone="error"
            title="회사 목록을 불러오지 못했습니다."
            problem={describeCompanyApiError(companiesQuery.error, "회사 목록을 불러오지 못했습니다.")}
            action={{ label: "다시 시도", onClick: () => { void companiesQuery.refetch(); } }}
          />
        ) : companiesQuery.data.items.length === 0 ? (
          <EmptyState title="등록된 회사가 없습니다." description="회사 등록은 데모 CLI로만 합니다. 이 화면은 회사를 만들지 않습니다." />
        ) : (
          <ul className="cw-company-list" aria-label="가상회사 목록">
            {companiesQuery.data.items.map((company) => (
              <li className="cw-company-row" key={company.company_id} data-company-slug={company.slug}>
                <span className="cw-cell-stack">
                  <strong>{company.name}</strong>
                  <span className="cw-caption">
                    {company.slug} · {company.is_fictional ? "가상회사" : "가상회사 표식 없음"}
                  </span>
                </span>
                <span className="cw-company-row-actions">
                  <Link className="cw-link" to={`/companies/${company.company_id}/pre-specs`} aria-label={`${company.name} 사전규격 열기`}>
                    사전규격 열기
                  </Link>
                  <Link className="cw-link" to={`/companies/${company.company_id}/profile`} aria-label={`${company.name} 프로필 열기`}>
                    프로필 열기
                  </Link>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// 공용: 주소의 회사 식별자

function InvalidCompanyAddress() {
  return (
    <section className="cw-page">
      <EmptyState
        tone="error"
        title="회사 주소가 올바르지 않습니다."
        description="주소의 회사 식별자를 확인할 수 없어 아무 회사의 결과도 보여 주지 않습니다."
        action={{ label: "회사 다시 고르기", to: "/companies" }}
      />
    </section>
  );
}

// ---------------------------------------------------------------------------
// 회사 사전규격 목록

export function CompanyPreSpecsPage() {
  const { companyId } = useParams();
  if (!isCompanyUuid(companyId)) return <InvalidCompanyAddress />;
  // 회사가 바뀌면 화면을 새로 마운트한다. 선택·입력 state가 다른 회사로 넘어가지 않는다.
  return <CompanyPreSpecList companyId={companyId} key={companyId} />;
}

function readSelection(companyId: Uuid): { state: ListSelectionState | null; available: boolean } {
  const result = readListSelection(companySessionKey(companyId, "pre-specs.selection"));
  return { state: result.state, available: result.status === "restored" || result.status === "missing" };
}

const FIT_FILTER_OPTIONS: ReadonlyArray<{ value: CompanyFitDecision | "all"; label: string }> = [
  { value: "all", label: "전체" },
  ...COMPANY_FIT_FILTERS.map((value) => ({ value, label: companyFitDecisionLabel(value) })),
];
const TRACKING_FILTER_OPTIONS: ReadonlyArray<{ value: CompanyTrackingStatus | "all"; label: string }> = [
  { value: "all", label: "전체" },
  ...COMPANY_TRACKING_STATUSES.map((value) => ({ value, label: value })),
];
const SORT_OPTIONS: ReadonlyArray<{ value: CompanyPreSpecSort; label: string }> = [
  { value: "posted_at_desc", label: "게시일 최신순" },
  { value: "deadline_asc", label: "마감 임박순(마감일 없음은 뒤)" },
];

/** 주소에 쓰는 검색 인자. 기본값은 쓰지 않아 주소가 짧고, 허용값 밖은 다시 쓰지 않는다. */
function canonicalListParams(state: CompanyPreSpecListState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.fit) params.set("fit", state.fit);
  if (state.trackingStatus) params.set("tracking_status", state.trackingStatus);
  if (state.q) params.set("q", state.q);
  if (state.sort !== COMPANY_PRE_SPEC_DEFAULT_SORT) params.set("sort", state.sort);
  if (state.limit !== COMPANY_PRE_SPEC_DEFAULT_LIMIT) params.set("limit", String(state.limit));
  if (state.offset > 0) params.set("offset", String(state.offset));
  return params;
}

function postedLabel(value: string | null): string {
  return value ? `게시 ${formatDate(value)}` : "게시일 미확인";
}

function deadlineLabel(value: string | null): string {
  return value ? `마감 ${formatDate(value)}` : "마감일 미확인";
}

function CompanyPreSpecList({ companyId }: { companyId: Uuid }) {
  const [searchParams, setSearchParams] = useSearchParams();
  // 주소가 정본이다. 허용값 밖의 값은 기본값(전체)으로 복원하고, 모든 조건은 서버에 보낸다.
  const state = useMemo(() => parseCompanyPreSpecListParams(searchParams), [searchParams]);
  const fingerprint = companyPreSpecFilterFingerprint(state);
  const listParams = companyPreSpecListQuery(state);
  const listQuery = useQuery({
    queryKey: companyKeys.preSpecList(companyId, listParams),
    queryFn: ({ signal }) => companyApi.listPreSpecs(companyId, listParams, { signal }),
    retry: false,
  });

  const [draftQ, setDraftQ] = useState(state.q);
  const [searchProblem, setSearchProblem] = useState<string | null>(null);
  useEffect(() => {
    setDraftQ(state.q);
    setSearchProblem(null);
  }, [state.q]);

  const update = useCallback((changes: Partial<Record<"fit" | "tracking_status" | "q" | "sort" | "offset", string | null>>) => {
    const next = canonicalListParams(state);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === undefined || value === "") next.delete(key);
      else next.set(key, value);
    }
    // 쪽 이동이 아닌 변경은 첫 쪽으로 돌아간다(의미 필터 변경은 offset을 초기화한다).
    if (!("offset" in changes)) next.delete("offset");
    setSearchParams(next, { replace: true });
  }, [setSearchParams, state]);

  // 선택은 회사별 저장소에 둔다. 의미 필터(핏·추적·검색)가 바뀌면 선택을 비운다.
  const [selection, setSelection] = useState(() => readSelection(companyId));
  const [storageProblem, setStorageProblem] = useState<string | null>(
    selection.available ? null : "이 탭의 선택 저장소를 읽지 못해 새로고침 뒤 선택을 복원하지 않습니다.",
  );
  const stored = selection.state;
  const currentSelection = stored !== null && stored.filterFingerprint === fingerprint ? stored : null;
  useEffect(() => {
    if (stored === null || stored.filterFingerprint === fingerprint) return;
    const reset = createEmptyListSelection(fingerprint, { selectionGeneration: nextSelectionGeneration(stored.selectionGeneration) });
    const written = writeListSelection(companySessionKey(companyId, "pre-specs.selection"), reset);
    setStorageProblem(written.ok ? null : "이 탭의 선택 저장소에 쓰지 못해 새로고침 뒤 선택을 복원하지 않습니다.");
    setSelection({ state: reset, available: written.ok });
  }, [companyId, fingerprint, stored]);
  const activeId = currentSelection?.activeId ?? null;

  const select = useCallback((noticeId: number) => {
    const base = currentSelection
      ?? createEmptyListSelection(fingerprint, { selectionGeneration: stored ? nextSelectionGeneration(stored.selectionGeneration) : 0 });
    const next = setSelectionActiveId(base, noticeId);
    const written = writeListSelection(companySessionKey(companyId, "pre-specs.selection"), next);
    setStorageProblem(written.ok ? null : "이 탭의 선택 저장소에 쓰지 못해 새로고침 뒤 선택을 복원하지 않습니다.");
    setSelection({ state: next, available: written.ok });
  }, [companyId, currentSelection, fingerprint, stored]);

  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? 0;
  const activeItem = items.find((item) => item.notice_id === activeId) ?? null;
  const activeFilterCount = (state.fit ? 1 : 0) + (state.trackingStatus ? 1 : 0) + (state.q ? 1 : 0);

  const applySearch = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = draftQ.trim();
    if (Array.from(trimmed).length > COMPANY_PRE_SPEC_QUERY_MAX_LENGTH) {
      setSearchProblem(`검색어는 ${COMPANY_PRE_SPEC_QUERY_MAX_LENGTH}자 이하로 입력하십시오. 적용하지 않았습니다.`);
      return;
    }
    setSearchProblem(null);
    if (trimmed === state.q) return;
    update({ q: trimmed });
  };

  return (
    <section className="cw-page" aria-label="회사 사전규격" data-company-id={companyId}>
      <CompanyHeader companyId={companyId} screen="pre-specs" />
      {storageProblem ? <p className="cw-caption" role="status">{storageProblem}</p> : null}
      <div className="cw-workspace">
        <div className="cw-section">
          <h3 id="company-pre-spec-list-title">회사별 사전규격 판정</h3>
          <p className="cw-caption">
            회사 핏 판정·심층 검토·추적 결정은 이 회사 기준이며 서로 다른 칸입니다. 공고 판정 등급(C-1)은 가상회사 판정으로 쓰지 않습니다.
          </p>
          <form className="cw-filters" role="search" aria-label="회사 사전규격 필터" onSubmit={applySearch}>
            <label className="cw-filter">
              <span>핏 판정</span>
              <select
                aria-label="핏 판정 필터"
                value={state.fit ?? "all"}
                onChange={(event) => update({ fit: event.target.value === "all" ? null : event.target.value })}
              >
                {FIT_FILTER_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="cw-filter">
              <span>추적 결정</span>
              <select
                aria-label="추적 결정 필터"
                value={state.trackingStatus ?? "all"}
                onChange={(event) => update({ tracking_status: event.target.value === "all" ? null : event.target.value })}
              >
                {TRACKING_FILTER_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="cw-filter">
              <span>정렬</span>
              <select
                aria-label="정렬"
                value={state.sort}
                onChange={(event) => update({ sort: event.target.value === COMPANY_PRE_SPEC_DEFAULT_SORT ? null : event.target.value })}
              >
                {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="cw-filter cw-filter-search">
              <span>검색</span>
              <input
                aria-label="사전규격 검색"
                maxLength={COMPANY_PRE_SPEC_QUERY_MAX_LENGTH * 2}
                placeholder="제목·기관"
                type="search"
                value={draftQ}
                onChange={(event) => setDraftQ(event.target.value)}
              />
            </label>
            <button className="cw-button cw-button-compact" type="submit">검색</button>
            <button
              className="cw-button cw-button-compact"
              disabled={activeFilterCount === 0}
              type="button"
              onClick={() => update({ fit: null, tracking_status: null, q: null })}
            >
              필터 초기화
            </button>
          </form>
          {searchProblem ? <p className="cw-caption" role="alert">{searchProblem}</p> : null}
          <p className="cw-caption">
            핏 필터는 서버가 현재 완료된 판정만 대상으로 합니다. 대기·실행 중·실패·사람 검토 필요·기록 없음은 &lsquo;전체&rsquo;에서 봅니다.
            모든 조건은 서버가 쪽 나누기 전에 적용합니다.
          </p>
          {listQuery.isPending ? (
            <p role="status">이 회사의 사전규격을 불러오는 중입니다.</p>
          ) : listQuery.isError ? (
            <EmptyState
              tone="error"
              title="회사 사전규격을 불러오지 못했습니다."
              problem={describeCompanyApiError(listQuery.error, "회사 사전규격을 불러오지 못했습니다.")}
              action={{ label: "다시 시도", onClick: () => { void listQuery.refetch(); } }}
            />
          ) : items.length === 0 ? (
            total === 0 ? (
              activeFilterCount > 0 ? (
                <EmptyState
                  title="조건에 맞는 사전규격이 없습니다."
                  description="필터를 풀면 이 회사의 다른 사전규격이 보일 수 있습니다. 조건에 맞는 항목이 없다는 뜻이며 판정 결과가 없다는 뜻이 아닙니다."
                  action={{ label: "필터 초기화", onClick: () => update({ fit: null, tracking_status: null, q: null }) }}
                />
              ) : (
                <EmptyState title="이 회사에 표시할 사전규격이 없습니다." description="적재된 SW사업대상 사전규격이 없습니다." />
              )
            ) : (
              <EmptyState
                title="이 쪽에 표시할 항목이 없습니다."
                description={`조건에 맞는 항목은 전체 ${total}건이지만 요청한 위치(${state.offset + 1}번째부터)에는 없습니다.`}
                action={{ label: "첫 쪽으로", onClick: () => update({ offset: null }) }}
              />
            )
          ) : (
            <>
              <table className="cw-table" aria-labelledby="company-pre-spec-list-title">
                <thead>
                  <tr>
                    <th className="cw-col-title" scope="col">사전규격</th>
                    <th scope="col">회사 핏</th>
                    <th scope="col">심층 검토</th>
                    <th scope="col">추적 결정</th>
                    <th scope="col">열기</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <CompanyPreSpecRow
                      active={item.notice_id === activeId}
                      companyId={companyId}
                      item={item}
                      key={item.notice_id}
                      onSelect={select}
                    />
                  ))}
                </tbody>
              </table>
            </>
          )}
          {listQuery.isSuccess ? (
            <ListPagerControls
              className="cw-pager"
              label="회사 사전규격 페이지"
              offset={state.offset}
              onNext={() => update({ offset: String(state.offset + state.limit) })}
              onPrevious={() => update({ offset: state.offset - state.limit > 0 ? String(state.offset - state.limit) : null })}
              total={total}
              visibleCount={items.length}
            />
          ) : null}
        </div>
        <aside className="cw-section cw-selected" aria-label="선택한 사전규격">
          <h3>선택한 사전규격</h3>
          {activeItem ? (
            <>
              <p data-testid="company-selected-title">{activeItem.title ?? `notice ${activeItem.notice_id} · 제목 미확인`}</p>
              <dl className="cw-facts">
                <dt>회사 핏</dt><dd><CompanyFitSummaryView fit={activeItem.fit} showSummary /></dd>
                <dt>심층 검토</dt><dd><CompanyReviewSummaryView review={activeItem.review} /></dd>
                <dt>추적 결정</dt><dd><CompanyTrackingSummaryView tracking={activeItem.tracking} /></dd>
              </dl>
              <Link className="cw-link" to={`/companies/${companyId}/pre-specs/${activeItem.notice_id}`}>상세 검토 열기</Link>
            </>
          ) : activeId !== null && listQuery.isSuccess ? (
            <p className="cw-caption">선택했던 notice {activeId}가 이 쪽 목록에 없습니다. 선택을 지우지 않았습니다.</p>
          ) : (
            <p className="cw-caption">목록에서 사전규격을 고르십시오.</p>
          )}
        </aside>
      </div>
    </section>
  );
}

function CompanyPreSpecRow({
  item,
  active,
  companyId,
  onSelect,
}: {
  item: CompanyNotice;
  active: boolean;
  companyId: Uuid;
  onSelect: (noticeId: number) => void;
}) {
  return (
    <tr className={active ? "is-active" : undefined} data-notice-id={item.notice_id}>
      <td>
        <button
          aria-pressed={active}
          className="cw-row-select"
          type="button"
          onClick={() => onSelect(item.notice_id)}
        >
          <strong>{item.title ?? "제목 미확인"}</strong>
          <span className="cw-caption">
            notice {item.notice_id} · <span data-posted-at={item.posted_at ?? "null"}>{postedLabel(item.posted_at)}</span>
            {" · "}
            <span data-deadline-at={item.deadline_at ?? "null"}>{deadlineLabel(item.deadline_at)}</span>
          </span>
        </button>
      </td>
      <td><CompanyFitSummaryView fit={item.fit} /></td>
      <td><CompanyReviewSummaryView review={item.review} /></td>
      <td><CompanyTrackingSummaryView tracking={item.tracking} /></td>
      <td>
        <Link className="cw-link" to={`/companies/${companyId}/pre-specs/${item.notice_id}`} aria-label={`notice ${item.notice_id} 상세 검토`}>
          상세
        </Link>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// 회사 사전규격 상세

export function CompanyPreSpecDetailPage() {
  const { companyId, noticeId: noticeParam } = useParams();
  const noticeId = parseNoticeId(noticeParam);
  if (!isCompanyUuid(companyId)) return <InvalidCompanyAddress />;
  if (noticeId === null) {
    return (
      <section className="cw-page">
        <EmptyState
          tone="error"
          title="사전규격 주소가 올바르지 않습니다."
          action={{ label: "회사 사전규격 목록", to: `/companies/${companyId}/pre-specs` }}
        />
      </section>
    );
  }
  return <CompanyPreSpecDetail companyId={companyId} key={`${companyId}:${noticeId}`} noticeId={noticeId} />;
}

function CompanyPreSpecDetail({ companyId, noticeId }: { companyId: Uuid; noticeId: number }) {
  const detailQuery = useQuery({
    queryKey: companyKeys.preSpec(companyId, noticeId),
    queryFn: ({ signal }) => companyApi.getPreSpec(companyId, noticeId, { signal }),
    retry: false,
  });
  const detail = detailQuery.data;
  return (
    <section className="cw-page" aria-label="회사 사전규격 상세" data-company-id={companyId}>
      <CompanyHeader companyId={companyId} screen="pre-spec-detail" />
      {detailQuery.isPending ? (
        <p role="status">이 회사 기준 사전규격을 불러오는 중입니다.</p>
      ) : detailQuery.isError ? (
        <EmptyState
          tone="error"
          title="이 회사 기준 사전규격을 불러오지 못했습니다."
          problem={describeCompanyApiError(detailQuery.error, "회사 사전규격을 불러오지 못했습니다.")}
          action={{ label: "회사 사전규격 목록", to: `/companies/${companyId}/pre-specs` }}
        />
      ) : detail ? (
        <>
          <div className="cw-section">
            <h3 data-testid="company-pre-spec-title">{detail.title ?? `notice ${detail.notice_id} · 제목 미확인`}</h3>
            <dl className="cw-facts">
              <dt>공고</dt><dd>notice {detail.notice_id} · {postedLabel(detail.posted_at)} · {deadlineLabel(detail.deadline_at)}</dd>
              <dt>회사 핏</dt><dd><CompanyFitSummaryView fit={detail.fit} showSummary /></dd>
              <dt>심층 검토</dt>
              <dd>
                <CompanyReviewSummaryView review={detail.review} />
                {detail.review ? (
                  <Link className="cw-link" to={`/companies/${companyId}/deep-reviews/${detail.review.review_id}`}>회사 심층 검토 열기</Link>
                ) : null}
              </dd>
              <dt>추적 결정</dt><dd><CompanyTrackingSummaryView tracking={detail.tracking} /></dd>
            </dl>
            <p className="cw-caption">
              원문 공고는 회사와 무관하게 공유합니다.{" "}
              <Link className="cw-link" to={`/pre-specs/${detail.notice_id}`}>원문 사전규격 상세</Link>
              {" · "}
              <Link className="cw-link" to={`/pre-specs/${detail.notice_id}/company-comparison`}>3사 비교</Link>
            </p>
          </div>
          <CompanyFitAttempts companyId={companyId} noticeId={detail.notice_id} />
          <CompanyDeepReviewRequest companyId={companyId} detail={detail} />
          <CompanyTrackingSection companyId={companyId} noticeId={detail.notice_id} opportunityId={detail.opportunity_id} />
        </>
      ) : null}
    </section>
  );
}


// ---------------------------------------------------------------------------
// 회사별 추적 결정 — 기존 `TrackingDecisionControl`을 회사 adapter로 쓴다(세 상태).

export function CompanyTrackingSection({ companyId, noticeId, opportunityId }: { companyId: Uuid; noticeId: number; opportunityId: number | null }) {
  // 회사 머리글과 같은 cache를 읽는다. 처리 중 이탈 확인이 어느 회사에 저장되는지 이름으로 말한다.
  const companyQuery = useQuery({
    queryKey: companyKeys.detail(companyId),
    queryFn: ({ signal }) => companyApi.getCompany(companyId, { signal }),
    retry: false,
  });
  const companyName = companyQuery.data?.company_id === companyId ? companyQuery.data.name : null;
  const adapter = useMemo(
    () => companyTrackingAdapter({ companyId, opportunityId, noticeId, companyName }),
    [companyId, companyName, noticeId, opportunityId],
  );
  return <TrackingDecisionControl adapter={adapter} />;
}

// ---------------------------------------------------------------------------
// 회사별 심층 검토 요청 — 기존 `LunaRequest`를 회사 endpoint adapter로 쓴다.

interface CompanyReviewCreateVariables {
  companyId: Uuid;
  noticeId: number;
  payload: CompanyDeepReviewCreateRequest;
  actorName: string;
}

/**
 * 이 회사 기준 Luna 심층 검토 요청.
 *
 * - 화면을 열기만 해서는 미리보기·생성을 부르지 않는다. 사람이 `전송 내용 미리보기`를 눌러야
 *   미리보기를, 승인 버튼을 눌러야 생성 요청을 한 번 보낸다(`LunaRequest`).
 * - 원문 대조 설정·담당자·문서 묶음이 바뀌면 `key`가 바뀌어 이전 미리보기 승인을 버린다.
 * - 생성 응답은 시작한 회사의 cache에만 반영하고, 그 회사 화면에 아직 있을 때만 보고서로 이동한다.
 * - 회사 핏은 CLI로만 실행하므로 이 화면에 핏 승인은 없다.
 */
function CompanyDeepReviewRequest({ companyId, detail }: { companyId: Uuid; detail: CompanyNoticeDetail }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const companyQuery = useQuery({
    queryKey: companyKeys.detail(companyId),
    queryFn: ({ signal }) => companyApi.getCompany(companyId, { signal }),
    retry: false,
  });
  const [verification, setVerification] = useState(true);
  const [actorName, setActorName] = useState("");
  const createMutation = useMutation({
    mutationFn: (variables: CompanyReviewCreateVariables) =>
      companyApi.createDeepReview(variables.companyId, variables.noticeId, variables.payload, variables.actorName),
    onSuccess: (review, variables) => {
      if (review.company_id !== variables.companyId) {
        void queryClient.invalidateQueries({ queryKey: companyKeys.scope(variables.companyId) });
        return;
      }
      queryClient.setQueryData(companyKeys.deepReview(variables.companyId, review.id), review);
      void queryClient.invalidateQueries({ queryKey: companyKeys.preSpec(variables.companyId, variables.noticeId) });
      void queryClient.invalidateQueries({ queryKey: companyKeys.preSpecLists(variables.companyId) });
      void queryClient.invalidateQueries({ queryKey: companyKeys.comparison(variables.noticeId) });
    },
  });
  const bundleId = detail.bundle_id;
  const company = companyQuery.data && companyQuery.data.company_id === companyId ? companyQuery.data : null;
  const adapter = useMemo(
    () => (bundleId === null ? null : createCompanyLunaAdapter({ companyId, company, noticeId: detail.notice_id, bundleId })),
    [bundleId, company, companyId, detail.notice_id],
  );

  return (
    <section className="cw-section cw-deep-review-request" aria-labelledby="company-deep-review-request-title" data-testid="company-deep-review-request">
      <h3 id="company-deep-review-request-title">이 회사 기준 심층 검토 요청</h3>
      <p className="cw-caption">
        사람이 요청할 때만 Luna 참조 분석을 시작합니다. 화면을 여는 것만으로는 전송 미리보기나 요청을 보내지 않습니다.
        심층 검토는 최종 입찰 Go/No-Go가 아니며, 회사 핏은 CLI로만 실행하므로 이 화면에 핏 승인이 없습니다.
      </p>
      {detail.review ? (
        <p className="cw-caption" data-testid="company-deep-review-existing">
          이 회사의 기존 심층 검토가 있습니다({companyReviewStatusLabel(detail.review.status)}{detail.review.is_current ? "" : " · 현재 입력 기준 아님"}).{" "}
          <Link className="cw-link" to={`/companies/${companyId}/deep-reviews/${detail.review.review_id}`}>보고서·분석 회차 보기</Link>
          {" "}같은 입력의 검토가 이미 있으면 서버가 새 검토를 막습니다. 다시 분석하려면 보고서 화면의 분석 설정에서 새 회차를 요청하십시오.
        </p>
      ) : null}
      {bundleId === null || adapter === null ? (
        <p className="cw-caption" data-testid="company-deep-review-no-bundle">확정된 문서 묶음이 없어 심층 검토를 요청할 수 없습니다.</p>
      ) : (
        <>
          <SourceVerificationSetting value={verification} onChange={setVerification} disabled={createMutation.isPending} />
          <ActorField label="심층 검토 요청 담당자 이름" value={actorName} onChange={setActorName} autoComplete="off" />
          {verification ? (
            <LunaRequest
              key={`${companyId}:${detail.notice_id}:${bundleId}:${verification}:${actorName}`}
              adapter={adapter}
              actor={actorName}
              bundleId={bundleId}
              noticeId={detail.notice_id}
              verification={verification}
              onSubmit={async (previewId, requestId) => {
                const review = await createMutation.mutateAsync({
                  companyId,
                  noticeId: detail.notice_id,
                  payload: { preview_id: previewId, source_verification_enabled: true, request_id: requestId, bundle_id: bundleId },
                  actorName: actorName.trim(),
                });
                // 이 회사 화면에 아직 있을 때만 이동한다. 다른 회사로 옮긴 뒤 온 응답이 화면을 바꾸지 않는다.
                if (mounted.current && review.company_id === companyId) {
                  navigate(`/companies/${companyId}/deep-reviews/${review.id}`);
                }
                return review;
              }}
            />
          ) : (
            <p role="status" data-testid="company-deep-review-verification-required">
              회사 경로는 원문 대조를 사용하는 요청만 받습니다. 이 설정으로는 미리보기와 요청을 보내지 않으며 이전 미리보기 승인은 폐기했습니다.
              원문 대조를 다시 켜면 새 미리보기부터 시작합니다.
            </p>
          )}
        </>
      )}
    </section>
  );
}
