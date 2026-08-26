import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { api } from "../lib/api";
import { formatNumber } from "../lib/format";
import type { ProfileSection, ProfileSectionState, ProfileSectionsResponse, ProfileStatus, ProfileUnknownsResponse } from "../lib/types";
import "../styles/reference-relaxed.css";

type ProfileFilter = "all" | ProfileStatus;

const filterLabels: Record<ProfileFilter, string> = {
  all: "전체",
  confirmed: "확정",
  inferred: "추정",
  unknown: "미확인",
};

const stateLabels: Record<ProfileSectionState, string> = {
  confirmed: "확정 (confirmed)",
  inferred: "추정 (inferred)",
  unknown: "미확인 (unknown)",
  mixed: "혼합 상태",
  unrecorded: "상태 미기록",
};

function stateVariant(state: ProfileSectionState): BadgeVariant {
  if (state === "confirmed") return "evidence-confirmed";
  if (state === "inferred") return "evidence-inferred";
  if (state === "unknown") return "evidence-unknown";
  return "neutral";
}

function valueLabel(value: unknown): string {
  if (value === null || value === undefined) return "값 미기록";
  if (Array.isArray(value) && value.length === 0) return "값 없음 (빈 목록)";
  if (typeof value === "object") return JSON.stringify(value) ?? "값 미기록";
  if (typeof value === "string" && value.trim() === "") return "값 미기록";
  return String(value);
}

function countLabel(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? formatNumber(value) : "미확인";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function hasSectionsPayload(data: ProfileSectionsResponse | undefined): boolean {
  return Boolean(
    data
      && Array.isArray(data.sections)
      && isRecord(data.status_counts)
      && isStringArray(data.parse_errors),
  );
}

function hasParseFreeSectionsPayload(data: ProfileSectionsResponse | undefined): boolean {
  return Boolean(data && hasSectionsPayload(data) && data.parse_errors.length === 0);
}

function hasUnknownsPayload(data: ProfileUnknownsResponse | undefined): boolean {
  return Boolean(
    data
      && Array.isArray(data.items)
      && typeof data.total === "number"
      && Array.isArray(data.reference_fields)
      && isStringArray(data.parse_errors),
  );
}

function parseErrorMessages(value: unknown, label: string): string[] {
  if (!isStringArray(value)) return [`${label} 응답의 파싱 상태를 확인할 수 없습니다.`];
  return value;
}

function summaryCount(summary: Record<string, number>, status: ProfileStatus, available: boolean): string {
  if (!available) return "미확인";
  // The parser's Counter omits zero-valued statuses; an omitted key therefore
  // means a known zero, while a malformed/null value remains unconfirmed.
  return Object.prototype.hasOwnProperty.call(summary, status) ? countLabel(summary[status]) : countLabel(0);
}

function hasMatchingContent(section: ProfileSection, filter: ProfileFilter): boolean {
  if (filter === "all") return true;
  return section.items.some((item) => item.status === filter)
    || section.children.some((child) => hasMatchingContent(child, filter));
}

function ProfileTree({ section, filter }: { section: ProfileSection; filter: ProfileFilter }) {
  if (!hasMatchingContent(section, filter)) return null;
  const items = filter === "all" ? section.items : section.items.filter((item) => item.status === filter);
  const children = section.children
    .map((child) => <ProfileTree key={child.id} section={child} filter={filter} />)
    .filter(Boolean);
  return (
    <li className="profile-tree-node">
      <div className="profile-section-heading">
        <div className="profile-section-title">
          {section.number ? <span className="profile-section-number mono">{section.number}</span> : null}
          <strong>{section.title}</strong>
        </div>
        <div className="profile-section-meta">
          <Badge variant={stateVariant(section.state)} label={stateLabels[section.state]} />
          {isRecord(section.status_counts)
            ? Object.entries(section.status_counts).map(([status, count]) => (
              <span className="profile-count" key={status}><span className="mono">{status}</span> {countLabel(count)}</span>
            ))
            : <span className="profile-count">상태 미확인</span>}
        </div>
      </div>
      {items.length > 0 ? (
        <ul className="profile-item-list">
          {items.map((item) => (
            <li className="profile-item" key={`${item.section_id}:${item.key}`}>
              <div className="profile-item-heading">
                <span className="profile-item-label">{item.label}</span>
                <Badge variant={stateVariant(item.status)} label={stateLabels[item.status]} />
              </div>
              <div className="profile-item-detail">
                <code>{item.key}</code>
                <span>{valueLabel(item.value)}</span>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {section.raw_blocks.length > 0 ? (
        <div className="profile-parse-warning" role="alert">
          <strong>이 절의 YAML을 구조화하지 못했습니다.</strong>
          {section.raw_blocks.map((block) => (
            <div className="profile-raw-block" key={`${section.id}:${block.line_start}`}>
              <p>{block.error} · {block.line_start}행</p>
              <pre>{block.raw || "원문이 비어 있습니다."}</pre>
            </div>
          ))}
        </div>
      ) : null}
      {section.raw_blocks.length === 0 && items.length === 0 && section.raw ? (
        <div className="profile-raw-body">
          <p>이 절은 상태 항목으로 구조화되지 않았습니다. 원문을 그대로 표시합니다.</p>
          <pre>{section.raw}</pre>
        </div>
      ) : null}
      {children.length > 0 ? <ul className="profile-tree-children">{children}</ul> : null}
    </li>
  );
}

function referenceLabel(count: number | null, status: "counted" | "unavailable"): string {
  if (status === "unavailable" || count === null) return "집계 불가: 판정 원문을 읽지 못했습니다.";
  return `${formatNumber(count)}회`;
}

export function ProfilePage() {
  const [filter, setFilter] = useState<ProfileFilter>("all");
  const sectionsQuery = useQuery({ queryKey: ["profile-sections"], queryFn: api.getProfileSections, staleTime: 30_000 });
  const unknownsQuery = useQuery({ queryKey: ["profile-unknowns"], queryFn: api.getProfileUnknowns, staleTime: 30_000 });

  const sectionsResponse = sectionsQuery.data;
  const unknownsResponse = unknownsQuery.data;
  const sectionsPayloadAvailable = hasSectionsPayload(sectionsResponse);
  const sectionsSummaryAvailable = hasParseFreeSectionsPayload(sectionsResponse);
  const unknownsPayloadAvailable = hasUnknownsPayload(unknownsResponse);
  const sections = Array.isArray(sectionsResponse?.sections) ? sectionsResponse.sections : [];
  const unknowns = Array.isArray(unknownsResponse?.items) ? unknownsResponse.items : [];
  const filteredUnknowns = useMemo(
    () => filter === "unknown" || filter === "all" ? unknowns : [],
    [filter, unknowns],
  );

  if (sectionsQuery.isLoading || unknownsQuery.isLoading) return <div className="profile-loading" role="status" aria-live="polite">회사 프로필을 읽는 중입니다.</div>;
  if (sectionsQuery.error || unknownsQuery.error) {
    const error = sectionsQuery.error ?? unknownsQuery.error;
    return <EmptyState title="회사 프로필을 불러오지 못했습니다." description={error instanceof Error ? error.message : "프로필 API 응답을 확인할 수 없습니다."} action={{ label: "다시 시도", onClick: () => { void sectionsQuery.refetch(); void unknownsQuery.refetch(); } }} />;
  }

  const summary = sectionsPayloadAvailable && isRecord(sectionsResponse?.status_counts)
    ? sectionsResponse.status_counts as Record<string, number>
    : {};
  const parseErrors = [
    ...parseErrorMessages(sectionsResponse?.parse_errors, "프로필 절"),
    ...parseErrorMessages(unknownsResponse?.parse_errors, "미확인 항목"),
  ];
  const profileReadError = !sectionsPayloadAvailable || !unknownsPayloadAvailable || parseErrors.length > 0;
  const source = sectionsResponse?.source ?? unknownsResponse?.source ?? null;
  const referenceFields = Array.isArray(unknownsResponse?.reference_fields) ? unknownsResponse.reference_fields : [];
  const unknownTotal = !profileReadError && unknownsPayloadAvailable ? unknownsResponse?.total : undefined;
  return (
    <div className="profile-page">
      <header className="profile-page-header">
        <div className="profile-header-copy">
          <span className="profile-eyebrow">기준 · 읽기 전용</span>
          <h2>회사 프로필</h2>
          <p>회사소개서의 절 구조와 정보 상태를 원문 기준으로 표시합니다. 이 화면에서 프로필을 편집할 수 없습니다.</p>
          <dl className="profile-reference-meta">
            <div>
              <dt>관리 범위</dt>
              <dd>원문 기준 · 읽기 전용</dd>
            </div>
            <div className="profile-reference-source">
              <dt>기준 원문</dt>
              <dd><code>{source ?? "원문 미확인"}</code></dd>
            </div>
          </dl>
        </div>
        <div className="profile-summary" aria-label="정보 상태 요약">
          {(["confirmed", "inferred", "unknown"] as const).map((status) => (
            <div className="profile-summary-item" key={status}>
              <span>{filterLabels[status]}</span>
              <strong className="mono">{summaryCount(summary, status, sectionsSummaryAvailable)}</strong>
            </div>
          ))}
        </div>
      </header>
      {profileReadError ? (
        <div className="profile-page-warning" role="alert">
          <strong>프로필 응답 확인 필요</strong>
          <span>{parseErrors.length > 0 ? parseErrors.join(" ") : "응답 형식이 불완전하여 일부 상태를 미확인으로 표시합니다."}</span>
        </div>
      ) : null}
      <div className="profile-filter-bar" role="group" aria-label="정보 상태 필터">
        <span>상태 필터</span>
        <div className="profile-filter-options">
          {Object.entries(filterLabels).map(([key, label]) => (
            <button className={`profile-filter-button ${filter === key ? "is-selected" : ""}`.trim()} key={key} type="button" onClick={() => setFilter(key as ProfileFilter)} aria-pressed={filter === key}>
              {label}
            </button>
          ))}
        </div>
        <span className="profile-filter-current">현재: {filterLabels[filter]}</span>
      </div>
      <div className="profile-layout">
        <Panel title="프로필 절 트리" className="profile-tree-panel">
          {sections.length > 0 ? (
            <ul className="profile-tree">
              {sections.map((section) => <ProfileTree key={section.id} section={section} filter={filter} />)}
            </ul>
          ) : <p className="profile-empty-value">표시할 프로필 절이 없습니다.</p>}
        </Panel>
        <Panel title="미확인 항목 참조 횟수" action={<span className="profile-panel-count mono">{unknownTotal === undefined ? "미확인" : `${formatNumber(unknownTotal)}건`}</span>} className="profile-unknown-panel">
          <p className="profile-panel-description">판정의 근거 source·fact와 확인 항목 why에서 절 번호 또는 항목 이름이 언급된 횟수입니다.</p>
          <p className="profile-panel-scope">참조 필드: <code>{referenceFields.length > 0 ? referenceFields.join(", ") : "값 없음 (빈 목록)"}</code></p>
          {filteredUnknowns.length > 0 ? (
            <ul className="profile-unknown-list">
              {filteredUnknowns.map((item) => (
                <li className="profile-unknown-item" key={`${item.section_id}:${item.key}`}>
                  <div className="profile-unknown-heading">
                    <div>
                      <span className="profile-unknown-location">
                        {item.section_number ? `${item.section_number} · ` : ""}{item.section_title || "절 미확인"}
                      </span>
                      <strong>{item.label}</strong>
                    </div>
                    <Badge variant="evidence-unknown" label="미확인 (unknown)" />
                  </div>
                  <code>{item.key}</code>
                  <p className="profile-reference-count">값 <strong>미확인</strong> · 판정 참조 <strong className="mono">{referenceLabel(item.reference_count, item.reference_status)}</strong></p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="profile-empty-value">
              {profileReadError
                ? "미확인 항목을 표시할 수 없습니다. 프로필 원문 읽기 오류가 있습니다."
                : filter !== "all" && filter !== "unknown"
                ? `현재 ${filterLabels[filter]} 필터에서는 미확인 항목을 숨겼습니다.`
                : unknownTotal === 0
                  ? "미확인 항목이 없습니다. · 0건"
                  : "미확인 항목을 표시할 수 없습니다."}
            </p>
          )}
        </Panel>
      </div>
    </div>
  );
}
