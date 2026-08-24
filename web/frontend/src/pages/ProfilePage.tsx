import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { api } from "../lib/api";
import type { ProfileSection, ProfileSectionState, ProfileStatus } from "../lib/types";

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
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
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
          {Object.entries(section.status_counts).map(([status, count]) => (
            <span className="profile-count" key={status}>{status} {count}</span>
          ))}
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
  return `${count}회`;
}

export function ProfilePage() {
  const [filter, setFilter] = useState<ProfileFilter>("all");
  const sectionsQuery = useQuery({ queryKey: ["profile-sections"], queryFn: api.getProfileSections, staleTime: 30_000 });
  const unknownsQuery = useQuery({ queryKey: ["profile-unknowns"], queryFn: api.getProfileUnknowns, staleTime: 30_000 });

  const sections = sectionsQuery.data?.sections ?? [];
  const unknowns = unknownsQuery.data?.items ?? [];
  const filteredUnknowns = useMemo(
    () => filter === "unknown" || filter === "all" ? unknowns : [],
    [filter, unknowns],
  );

  if (sectionsQuery.isLoading || unknownsQuery.isLoading) return <div className="profile-loading">회사 프로필을 읽는 중입니다.</div>;
  if (sectionsQuery.error || unknownsQuery.error) {
    const error = sectionsQuery.error ?? unknownsQuery.error;
    return <EmptyState title="회사 프로필을 불러오지 못했습니다." description={error instanceof Error ? error.message : "프로필 API 응답을 확인할 수 없습니다."} />;
  }

  const summary = sectionsQuery.data?.status_counts ?? {};
  const parseErrors = [...(sectionsQuery.data?.parse_errors ?? []), ...(unknownsQuery.data?.parse_errors ?? [])];
  return (
    <div className="profile-page">
      <header className="profile-page-header">
        <div>
          <span className="profile-eyebrow">기준 · 읽기 전용</span>
          <h2>회사 프로필</h2>
          <p>회사소개서의 절 구조와 정보 상태를 원문 기준으로 표시합니다. 이 화면에서 프로필을 편집할 수 없습니다.</p>
        </div>
        <div className="profile-summary" aria-label="정보 상태 요약">
          {(["confirmed", "inferred", "unknown"] as const).map((status) => (
            <div className="profile-summary-item" key={status}>
              <span>{filterLabels[status]}</span>
              <strong className="mono">{summary[status] ?? 0}</strong>
            </div>
          ))}
        </div>
      </header>
      {parseErrors.length > 0 ? (
        <div className="profile-page-warning" role="alert">
          <strong>파싱 경고</strong>
          <span>{parseErrors.join(" ")}</span>
        </div>
      ) : null}
      <div className="profile-filter-bar" role="group" aria-label="정보 상태 필터">
        <span>상태 필터</span>
        {Object.entries(filterLabels).map(([key, label]) => (
          <button className={`profile-filter-button ${filter === key ? "is-selected" : ""}`.trim()} key={key} type="button" onClick={() => setFilter(key as ProfileFilter)} aria-pressed={filter === key}>
            {label}
          </button>
        ))}
      </div>
      <div className="profile-layout">
        <Panel title="프로필 절 트리" className="profile-tree-panel">
          {sections.length > 0 ? (
            <ul className="profile-tree">
              {sections.map((section) => <ProfileTree key={section.id} section={section} filter={filter} />)}
            </ul>
          ) : <p className="profile-empty-value">표시할 프로필 절이 없습니다.</p>}
        </Panel>
        <Panel title="미확인 항목 참조 횟수" action={<span className="profile-panel-count mono">{unknownsQuery.data?.total ?? 0}건</span>} className="profile-unknown-panel">
          <p className="profile-panel-description">판정의 근거 source·fact와 확인 항목 why에서 절 번호 또는 항목 이름이 언급된 횟수입니다.</p>
          {filteredUnknowns.length > 0 ? (
            <ul className="profile-unknown-list">
              {filteredUnknowns.map((item) => (
                <li className="profile-unknown-item" key={`${item.section_id}:${item.key}`}>
                  <div className="profile-unknown-heading">
                    <div><span className="mono">{item.section_number ? `${item.section_number} · ` : ""}</span><strong>{item.label}</strong></div>
                    <Badge variant="evidence-unknown" label="미확인 (unknown)" />
                  </div>
                  <code>{item.key}</code>
                  <p className="profile-reference-count">판정 참조 <strong className="mono">{referenceLabel(item.reference_count, item.reference_status)}</strong></p>
                </li>
              ))}
            </ul>
          ) : <p className="profile-empty-value">미확인 항목을 표시할 수 없습니다.</p>}
        </Panel>
      </div>
    </div>
  );
}
