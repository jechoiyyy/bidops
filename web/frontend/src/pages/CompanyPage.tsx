import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { PageHeaderActions, PageHeaderTabs } from "../components/common/PageHeaderActions";
import { AttentionList } from "../components/company/AttentionList";
import { expiryNote, factOriginNote, FactGroupTable, StatusPill } from "../components/company/FactGroupTable";
import { ReviewPreviewHeader } from "../components/common/ReviewPrimitives";
import { describeCompanyApiError, apiErrorRecoveryAction } from "../lib/apiErrors";
import {
  companyApi,
  companyContextQueryKey,
  companyKeys,
  getCompanyContext,
  type CompanyContextView,
  type CompanyProfileFact,
} from "../lib/companyApi";
import {
  COMPANY_FACT_GROUPS,
  COMPANY_GROUP_LABEL,
  attentionFacts,
  companyFactValueText,
  countFacts,
  factsOfGroup,
  isDisplayedFact,
  parseCompanyGroup,
  todayInSeoul,
  type CompanyFactGroup,
  type CompanyFactTableGroup,
} from "../lib/companyFacts";
import "../styles/company-ground-truth.css";

/*
 * 회사 근거 `/company`(ui-spec §4.6, RL-00 spec "화면 `/company`"). 읽기 전용이다.
 *
 * - 회사는 하나다. 회사 id를 주소에서 읽지 않고 `GET /api/company`가 준다. 선택기는 없다.
 * - 상태 3 수치(확인됨·확인 필요·곧 만료)와 "확인이 필요한 것"은 같은 사실 목록
 *   (`GET /api/companies/{id}/profile`의 facts)을 이 화면이 센다. 서버가 따로 센 값이 없다.
 * - 값은 회사 파일을 고쳐 다시 등록한다. 맞음·수정·입력·저장 버튼은 없다.
 * - 활성 버전이 없으면 수치를 0으로 적지 않고 "아직 활성화되지 않았습니다"라고 말한다.
 */

const NOTICE_LINE = "값 수정은 회사 파일을 고쳐 다시 등록해요(운영 담당자가 등록 절차를 수행)";
const TABLE_GROUPS: readonly CompanyFactTableGroup[] = ["qualification", "performance", "staff", "preference"];

/** 서버 시각을 한국 날짜로 적는다(`2026년 10월 16일`). 읽을 수 없으면 원문을 그대로 둔다. */
function formatSavedDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "long" }).format(parsed);
}

function CompanyTopbarActions({ context }: { context: CompanyContextView }) {
  const active = context.active_graph_version;
  return (
    <PageHeaderActions>
      <span className="co-topbar-meta" data-testid="company-topbar-meta">
        {context.company.name}
        {active ? ` · 활성 근거 버전 · ${formatSavedDate(active.created_at)} 저장` : " · 활성 근거 버전 없음"}
      </span>
    </PageHeaderActions>
  );
}

function GroupNav({ group, attentionCount }: { group: CompanyFactGroup; attentionCount: number | null }) {
  return (
    <nav aria-label="회사 근거 항목" className="co-nav">
      {COMPANY_FACT_GROUPS.map((value) => {
        const label = COMPANY_GROUP_LABEL[value];
        if (value === "proposal-assets") {
          // 제안서 자료는 RL-04가 채운다. 자리만 두고 링크로 만들지 않는다.
          return (
            <span aria-disabled="true" className={`co-nav-item is-disabled${group === value ? " is-active" : ""}`} key={value} title="RL-04에서 채워요">
              {label}
            </span>
          );
        }
        const active = group === value;
        return (
          <Link
            aria-current={active ? "page" : undefined}
            className={`co-nav-item${active ? " is-active" : ""}`}
            key={value}
            replace
            to={{ pathname: "/company", search: value === "attention" ? "" : `?group=${value}` }}
          >
            <span>{label}</span>
            {value === "attention" && attentionCount !== null ? (
              <span className="co-nav-count" data-testid="company-nav-attention-count">{attentionCount}</span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

function CountList({ confirmed, attention, expiring }: { confirmed: number; attention: number; expiring: number }) {
  const items: Array<[string, string, number]> = [
    ["confirmed", "확인됨", confirmed],
    ["attention", "확인 필요", attention],
    ["expiring", "곧 만료", expiring],
  ];
  return (
    <dl aria-label="상태 요약" className="co-counts">
      {items.map(([key, label, value]) => (
        <div className="co-count" key={key}>
          <dt>{label}</dt>
          <dd data-testid={`company-count-${key}`}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function GroupBody({ group, facts, today, warningDays, selectedKey, onSelect }: {
  group: CompanyFactGroup;
  facts: readonly CompanyProfileFact[];
  today: string;
  warningDays: number;
  selectedKey?: string;
  onSelect: (key: string) => void;
}) {
  if (group === "attention") return <AttentionList facts={attentionFacts(facts)} today={today} warningDays={warningDays} selectedKey={selectedKey} onSelect={onSelect} />;
  if (group === "proposal-assets") {
    return (
      <section aria-labelledby="co-group-title" className="co-group">
        <h2 className="co-block-title" id="co-group-title">{COMPANY_GROUP_LABEL[group]}</h2>
        <p className="co-empty" role="status">RL-04에서 채워요</p>
      </section>
    );
  }
  const tableGroup = TABLE_GROUPS.find((value) => value === group) as CompanyFactTableGroup;
  const rows = factsOfGroup(facts, tableGroup);
  return (
    <section aria-labelledby="co-group-title" className="co-group">
      <h2 className="co-block-title" id="co-group-title">
        {COMPANY_GROUP_LABEL[group]}
        <span className="co-block-count">{rows.length}</span>
      </h2>
      <FactGroupTable caption={COMPANY_GROUP_LABEL[group]} facts={rows} today={today} warningDays={warningDays} selectedKey={selectedKey} onSelect={onSelect} />
    </section>
  );
}

export function CompanyPage() {
  const [searchParams] = useSearchParams();
  const group = parseCompanyGroup(searchParams.get("group"));
  const [selectedFactKey, setSelectedFactKey] = useState<string | null>(null);
  const contextQuery = useQuery({
    queryKey: companyContextQueryKey,
    queryFn: ({ signal }) => getCompanyContext({ signal }),
    retry: false,
  });
  const context = contextQuery.data;
  const companyId = context?.company.company_id ?? null;
  const activeVersionId = context?.active_graph_version?.graph_version_id ?? null;
  const profileQuery = useQuery({
    queryKey: companyKeys.profile(companyId ?? "", null),
    queryFn: ({ signal }) => companyApi.getProfile(companyId as string, null, { signal }),
    enabled: companyId !== null && activeVersionId !== null,
    retry: false,
  });
  const profile = profileQuery.data;

  let body;
  let ready = false;
  if (contextQuery.isPending) {
    body = <p className="co-status" role="status">회사 근거를 불러오는 중이에요.</p>;
  } else if (contextQuery.isError && describeCompanyApiError(contextQuery.error, "").code === "company_not_registered") {
    body = (
      <EmptyState
        description="운영 담당자가 회사 근거를 등록하고 활성화하면 자격·실적·인력과 각 항목의 확인 상태를 볼 수 있어요."
        title="운영 회사 근거가 등록되지 않았어요"
      />
    );
  } else if (contextQuery.isError || !context) {
    const problem = describeCompanyApiError(contextQuery.error, "회사 근거를 불러오지 못했어요.");
    body = (
      <EmptyState
        action={apiErrorRecoveryAction(problem, () => { void contextQuery.refetch(); }, "다시 시도")}
        problem={problem}
        title="회사 근거를 불러오지 못했어요"
        tone="error"
      />
    );
  } else if (activeVersionId === null) {
    // 활성 버전이 없으면 수치를 0으로 적지 않는다(값 없음과 0은 다르다).
    body = (
      <EmptyState
        description="회사는 등록됐어요. 운영 담당자가 근거 버전을 활성화하면 확인된 항목과 확인이 필요한 항목을 볼 수 있어요."
        title="회사 근거가 아직 활성화되지 않았어요"
      />
    );
  } else if (profileQuery.isPending) {
    body = <p className="co-status" role="status">회사 근거를 불러오는 중이에요.</p>;
  } else if (profileQuery.isError || !profile) {
    const problem = describeCompanyApiError(profileQuery.error, "회사 근거를 불러오지 못했어요.");
    body = (
      <EmptyState
        action={apiErrorRecoveryAction(problem, () => { void profileQuery.refetch(); }, "다시 시도")}
        problem={problem}
        title="회사 근거를 불러오지 못했어요"
        tone="error"
      />
    );
  } else if (profile.graph_version_id !== activeVersionId || profile.company.company_id !== context.company.company_id) {
    // 두 응답 사이에 활성 버전이 바뀐 경우다. 어느 쪽 값도 섞어 보여 주지 않고 다시 읽게 한다.
    body = (
      <EmptyState
        action={{ label: "다시 불러오기", onClick: () => { void contextQuery.refetch(); void profileQuery.refetch(); } }}
        description="회사 근거 버전이 읽는 사이에 바뀌었어요. 다시 불러오면 같은 버전으로 보여 드려요."
        title="회사 근거 버전이 일치하지 않아요"
        tone="warning"
      />
    );
  } else {
    const today = todayInSeoul();
    const warningDays = context.expiry_warning_days;
    const counts = countFacts(profile.facts, today, warningDays);
    const groupFacts = group === "attention" ? attentionFacts(profile.facts)
      : group === "proposal-assets" ? [] : factsOfGroup(profile.facts, group);
    const displayed = groupFacts.filter(isDisplayedFact);
    const selectedFact = displayed.find((fact) => fact.fact_key === selectedFactKey) ?? displayed[0];
    const origin = selectedFact ? factOriginNote(selectedFact) : null;
    const expiry = selectedFact ? expiryNote(selectedFact, today, warningDays) : null;
    ready = true;
    body = (
      <>
        <PageHeaderTabs><GroupNav attentionCount={counts.attention} group={group} /></PageHeaderTabs>
        <section aria-label="회사 근거 목록" className="co-side">
          <CountList attention={counts.attention} confirmed={counts.confirmed} expiring={counts.expiring} />
          <GroupBody facts={profile.facts} group={group} today={today} warningDays={warningDays}
            selectedKey={selectedFact?.fact_key} onSelect={setSelectedFactKey} />
        </section>
        <section aria-label="선택한 회사 근거" className="co-main">
          <ReviewPreviewHeader />
          <div className="co-preview-body">
            {selectedFact && isDisplayedFact(selectedFact) ? (
              <>
                <h2>{selectedFact.label}</h2>
                <StatusPill status={selectedFact.status} />
                <p className="co-preview-value">{companyFactValueText(selectedFact)}</p>
                {origin ? <p className="co-row-sub">{origin}</p> : null}
                {expiry ? <p className="co-row-sub is-warning">{expiry}</p> : null}
                <p className="co-notice">{NOTICE_LINE}</p>
              </>
            ) : <EmptyState compact title="표시할 회사 근거가 없어요" />}
          </div>
        </section>
      </>
    );
  }

  return (
    <section aria-label="회사 근거" className={`co-page${ready ? " is-ready" : ""}`} data-company-page>
      {context ? <CompanyTopbarActions context={context} /> : null}
      {body}
    </section>
  );
}
