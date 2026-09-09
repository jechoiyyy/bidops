import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { LockKeyhole, Search } from "lucide-react";
import {
  CancelButton,
  CriteriaDialog,
  DataTable,
  DetailFooter,
  DetailHeader,
  DialogActions,
  Disclosure,
  Facts,
  Note,
  Queue,
  Section,
  Small,
  StateView,
  StatusToken,
  shortIdentifier,
} from "../components/criteria/CriteriaPrimitives";
import { api } from "../lib/api";
import { formatNumber } from "../lib/format";
import type {
  ProfileErrorCode,
  ProfileItem,
  ProfileSection,
  ProfileSectionState,
  ProfileSectionsResponse,
  ProfileStatus,
  ProfileUnknown,
  ProfileUnknownsResponse,
} from "../lib/types";

/**
 * 회사 프로필 탭 — 승인된 구조화 사본의 읽기 전용 표시.
 *
 * 화면이 하는 일은 API가 준 것을 그대로 보이는 것뿐이다. 편집 API가 없으므로
 * 편집·업로드 진입점을 두지 않고(`IMPLEMENTATION-CONTRACT.md` "상태와 행동"),
 * filesystem 경로·원문 블록·parser 예외는 type에도 화면에도 없다
 * (`web/frontend/AGENTS.md` "데이터 경계").
 *
 * `null`(값 미기록) · 빈 목록 · 빈 문자열 · 실제 값을 서로 다르게 적는다. 응답이
 * 계약 형태를 벗어나면 상태를 0으로 확정하지 않고 미확인으로 남긴다.
 */

type ProfileFilter = "all" | ProfileStatus;

const FILTER_LABELS: Record<ProfileFilter, string> = {
  all: "전체",
  confirmed: "확정",
  inferred: "추정",
  unknown: "미확인",
};

const STATE_LABELS: Record<ProfileSectionState, string> = {
  confirmed: "확정",
  inferred: "추정",
  unknown: "미확인",
  mixed: "혼합 상태",
  unrecorded: "상태 미기록",
};

const ERROR_LABELS: Record<ProfileErrorCode, string> = {
  profile_snapshot_unavailable: "승인된 프로필 사본을 읽지 못했습니다.",
  profile_source_unavailable: "프로필 원본을 읽지 못했습니다.",
  profile_yaml_unclosed: "YAML 블록이 닫히지 않아 해당 절을 구조화하지 못했습니다.",
  profile_yaml_invalid: "YAML 형식이 올바르지 않아 해당 절을 구조화하지 못했습니다.",
  profile_section_unstructured: "해당 절에 구조화되지 않은 내용이 있습니다.",
  profile_references_unavailable: "판정 참조 횟수를 집계할 수 없습니다.",
};

/** 사본 자체를 읽지 못한 상태. 빈 목록과 뜻이 다르므로 따로 센다. */
const READ_FAILURE_CODES: ProfileErrorCode[] = [
  "profile_snapshot_unavailable",
  "profile_source_unavailable",
  "profile_yaml_unclosed",
  "profile_yaml_invalid",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

/** 값 없음·빈 목록·빈 문자열·실제 값을 접지 않는다. */
function valueLabel(value: unknown): string {
  if (value === null || value === undefined) return "값 미기록";
  if (Array.isArray(value)) return value.length === 0 ? "값 없음 (빈 목록)" : value.map((item) => valueLabel(item)).join(", ");
  if (typeof value === "object") return JSON.stringify(value) ?? "값 미기록";
  if (typeof value === "string" && value.trim() === "") return "값 미기록";
  return String(value);
}

function countLabel(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? formatNumber(value) : "미확인";
}

function hasSectionsPayload(data: ProfileSectionsResponse | undefined): boolean {
  return Boolean(
    data
    && data.schema_version === "bidops.profile-projection.v1"
    && typeof data.profile_version === "string"
    && typeof data.profile_digest === "string"
    && Array.isArray(data.sections)
    && isRecord(data.status_counts)
    && isStringArray(data.error_codes),
  );
}

/** 구조화하지 못한 절이 있는 것과 응답 자체가 깨진 것은 다르다. */
function hasUsableSummary(data: ProfileSectionsResponse | undefined): boolean {
  if (!data || !hasSectionsPayload(data)) return false;
  return data.error_codes.every((code) => code === "profile_section_unstructured");
}

function hasUnknownsPayload(data: ProfileUnknownsResponse | undefined): boolean {
  return Boolean(
    data
    && data.schema_version === "bidops.profile-projection.v1"
    && typeof data.profile_version === "string"
    && typeof data.profile_digest === "string"
    && Array.isArray(data.items)
    && typeof data.total === "number"
    && Array.isArray(data.reference_fields)
    && isStringArray(data.error_codes),
  );
}

function errorMessages(value: unknown, label: string): string[] {
  if (!isStringArray(value)) return [`${label} 응답의 오류 코드를 확인할 수 없습니다.`];
  return value.map((code) => {
    if (!Object.prototype.hasOwnProperty.call(ERROR_LABELS, code)) return `확인되지 않은 프로필 오류 코드입니다 (코드: ${code}).`;
    return `${ERROR_LABELS[code as ProfileErrorCode]} (코드: ${code})`;
  });
}

function summaryCount(summary: Record<string, number>, status: ProfileStatus, available: boolean): string {
  if (!available) return "미확인";
  // 파서의 Counter는 0인 상태를 아예 넣지 않는다. 키가 없으면 아는 0이고,
  // 응답이 깨졌으면 미확인이다.
  return Object.prototype.hasOwnProperty.call(summary, status) ? countLabel(summary[status]) : countLabel(0);
}

/**
 * `heading`이 `번호 + 제목`을 그대로 되풀이하면 보조줄에 쓰지 않는다. 같은 문장을
 * 두 줄에 적으면 목록의 한 줄이 아무 정보도 더하지 않는다.
 */
function distinctHeading(section: ProfileSection): string | undefined {
  const normalize = (value: string) => value.replace(/[^\p{L}\p{N}]/gu, "");
  const heading = typeof section.heading === "string" ? section.heading : "";
  if (!heading) return undefined;
  return normalize(heading) === normalize(`${section.number ?? ""}${section.title}`) ? undefined : heading;
}

function sectionText(section: ProfileSection): string {
  return `${section.number ?? ""} ${section.title} ${section.heading}`;
}

function itemText(item: ProfileItem): string {
  return `${item.label} ${item.key} ${valueLabel(item.value)}`;
}

function matchesQuery(text: string, query: string): boolean {
  const needle = query.trim().toLowerCase();
  return needle === "" || text.toLowerCase().includes(needle);
}

interface SectionCounts {
  items: number;
  confirmed: number;
  inferred: number;
  unknown: number;
  children: number;
  errors: number;
}

function countSection(section: ProfileSection): SectionCounts {
  const items = Array.isArray(section.items) ? section.items : [];
  const children = Array.isArray(section.children) ? section.children : [];
  const base: SectionCounts = {
    items: items.length,
    confirmed: items.filter((item) => item.status === "confirmed").length,
    inferred: items.filter((item) => item.status === "inferred").length,
    unknown: items.filter((item) => item.status === "unknown").length,
    children: children.length,
    errors: (section.error_codes ?? []).length,
  };
  return children.reduce((total, child) => {
    const nested = countSection(child);
    return {
      items: total.items + nested.items,
      confirmed: total.confirmed + nested.confirmed,
      inferred: total.inferred + nested.inferred,
      unknown: total.unknown + nested.unknown,
      children: total.children + nested.children,
      errors: total.errors + nested.errors,
    };
  }, base);
}

/** 필터·검색이 이 절이나 하위 절에 남기는 것이 있는가. 구조화 실패는 항상 남긴다. */
function sectionMatches(section: ProfileSection, filter: ProfileFilter, query: string): boolean {
  if ((section.error_codes ?? []).length > 0 && matchesQuery(sectionText(section), query)) return true;
  const items = Array.isArray(section.items) ? section.items : [];
  const hit = items.some((item) => (
    (filter === "all" || item.status === filter)
    && matchesQuery(`${sectionText(section)} ${itemText(item)}`, query)
  ));
  if (hit) return true;
  return (section.children ?? []).some((child) => sectionMatches(child, filter, query));
}

function visibleItems(section: ProfileSection, filter: ProfileFilter, query: string): ProfileItem[] {
  const items = Array.isArray(section.items) ? section.items : [];
  return items.filter((item) => (
    (filter === "all" || item.status === filter)
    && matchesQuery(`${sectionText(section)} ${itemText(item)}`, query)
  ));
}

function referenceLabel(item: ProfileUnknown): string {
  if (item.reference_status === "unavailable" || item.reference_count === null) return "집계 불가 · 판정 원문을 읽지 못했습니다";
  return `${formatNumber(item.reference_count)}회`;
}

/** 절 하나와 그 하위 절. 제목·항목 수는 응답이 정하며 화면이 만들지 않는다. */
function SectionTree({ section, filter, query, unknowns, depth }: {
  section: ProfileSection;
  filter: ProfileFilter;
  query: string;
  unknowns: ProfileUnknown[];
  depth: number;
}) {
  if (!sectionMatches(section, filter, query)) return null;
  const items = visibleItems(section, filter, query);
  const codes = section.error_codes ?? [];
  const children = (section.children ?? []).filter((child) => sectionMatches(child, filter, query));
  const counts = countSection(section);
  const sectionUnknowns = unknowns.filter((item) => item.section_id === section.id);

  return (
    <li className="crit-section">
      {depth > 0 ? (
        <div className="crit-tree-heading">
          <span className="crit-tree-title">
            {section.number ? <Small>{section.number}</Small> : null}
            <Text weight="semibold">{section.title}</Text>
          </span>
          <StatusToken label={STATE_LABELS[section.state] ?? "상태 미기록"} />
        </div>
      ) : null}
      {items.length > 0 ? (
        <DataTable
          caption={`${section.title} 구조화 항목`}
          headings={["항목", "내용", "확인 상태"]}
          rows={items.map((item) => [
            <Text key="label" weight="semibold">{item.label}</Text>,
            <span className="crit-cell-stack" key="value">
              <Text>{valueLabel(item.value)}</Text>
              {/* 확정 항목에는 덧붙이지 않는다. 상태 자체는 오른쪽 칸이 말한다. */}
              {item.status === "unknown" ? <Small>확인 전까지 확정된 회사 역량으로 사용하지 않습니다.</Small> : null}
              {item.status === "inferred" ? <Small>원문과 증빙 확인 전까지 추정입니다.</Small> : null}
            </span>,
            <StatusToken key="status" label={STATE_LABELS[item.status]} />,
          ])}
        />
      ) : (
        <Small>{counts.items === 0 ? "이 절에는 구조화된 항목이 없습니다." : "현재 필터·검색에 맞는 항목이 이 절에 없습니다."}</Small>
      )}
      {codes.length > 0 ? (
        <Note role="alert" title="이 절의 일부 내용을 구조화하지 못했습니다" tone="warning">
          {`위치 ${section.id}${section.number ? ` · ${section.number}` : ""} · ${section.title} — ${errorMessages(codes, "이 절").join(" ")}`}
        </Note>
      ) : null}
      {sectionUnknowns.length > 0 || items.length > 0 ? (
        <Disclosure summary={`기술 키와 판정 참조 횟수 · ${section.title}`}>
          {items.length > 0 ? (
            <DataTable
              caption={`${section.title} 기술 키`}
              headings={["항목", "기술 키"]}
              rows={items.map((item) => [<Text key="label">{item.label}</Text>, <code key="key">{item.key}</code>])}
            />
          ) : null}
          {sectionUnknowns.length > 0 ? (
            <DataTable
              caption={`${section.title} 미확인 항목 참조 횟수`}
              headings={["미확인 항목", "기술 키", "판정 참조"]}
              rows={sectionUnknowns.map((item) => [
                <Text key="label">{item.label}</Text>,
                <code key="key">{item.key}</code>,
                <Text key="count">{referenceLabel(item)}</Text>,
              ])}
            />
          ) : null}
          {isRecord(section.status_counts) ? (
            <Small>
              {`이 절의 상태 집계 · ${Object.entries(section.status_counts).map(([status, count]) => `${status} ${countLabel(count)}`).join(" · ") || "값 없음 (빈 목록)"}`}
            </Small>
          ) : <Small>이 절의 상태 집계를 확인할 수 없습니다.</Small>}
        </Disclosure>
      ) : null}
      {children.length > 0 ? (
        <ul className="crit-tree-child">
          {children.map((child) => (
            <SectionTree depth={depth + 1} filter={filter} key={child.id} query={query} section={child} unknowns={unknowns} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function ProfilePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [snapshotOpen, setSnapshotOpen] = useState(false);
  const sectionsQuery = useQuery({ queryKey: ["profile-sections"], queryFn: api.getProfileSections, staleTime: 30_000 });
  const unknownsQuery = useQuery({ queryKey: ["profile-unknowns"], queryFn: api.getProfileUnknowns, staleTime: 30_000 });

  const rawFilter = searchParams.get("pstatus");
  const filter: ProfileFilter = rawFilter === "confirmed" || rawFilter === "inferred" || rawFilter === "unknown" ? rawFilter : "all";
  const query = searchParams.get("pq") ?? "";

  // 필터·검색·선택은 주소에 남긴다. 다른 화면이 넘겨 준 회차 등 무관한 파라미터는
  // 지우지 않는다.
  function updateParams(changes: Record<string, string | null>) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      }
      return next;
    }, { replace: true });
  }

  const sectionsResponse = sectionsQuery.data;
  const unknownsResponse = unknownsQuery.data;
  const sectionsPayloadAvailable = hasSectionsPayload(sectionsResponse);
  const sectionsSummaryAvailable = hasUsableSummary(sectionsResponse);
  const unknownsPayloadAvailable = hasUnknownsPayload(unknownsResponse);
  const sections = useMemo(() => (Array.isArray(sectionsResponse?.sections) ? sectionsResponse.sections : []), [sectionsResponse]);
  const unknowns = useMemo(() => (Array.isArray(unknownsResponse?.items) ? unknownsResponse.items : []), [unknownsResponse]);
  const visibleSections = useMemo(
    () => sections.filter((section) => sectionMatches(section, filter, query)),
    [sections, filter, query],
  );

  const selectedId = searchParams.get("psection");
  const selected = visibleSections.find((section) => section.id === selectedId) ?? visibleSections[0] ?? null;

  if (sectionsQuery.isPending || unknownsQuery.isPending) {
    return (
      <div className="crit-workspace" id="criteria-panel-profile" role="tabpanel">
        <StateView
          description="확인되지 않은 항목 수와 상태는 조회가 끝난 뒤 표시합니다."
          kind="loading"
          title="회사 프로필을 읽는 중입니다"
        />
      </div>
    );
  }
  if (sectionsQuery.error || unknownsQuery.error) {
    return (
      <div className="crit-workspace" id="criteria-panel-profile" role="tabpanel">
        <StateView
          action={<Button label="다시 조회" onClick={() => { void sectionsQuery.refetch(); void unknownsQuery.refetch(); }} />}
          description="승인된 프로필 사본과 구조화 상태를 확인할 수 없습니다. 조회 실패를 0건이나 정상 상태로 표시하지 않습니다."
          kind="error"
          title="회사 프로필을 불러오지 못했습니다."
        />
      </div>
    );
  }

  const summary = sectionsPayloadAvailable && isRecord(sectionsResponse?.status_counts)
    ? sectionsResponse.status_counts as Record<string, number>
    : {};
  const responseMessages = [
    ...errorMessages(sectionsResponse?.error_codes, "프로필 절"),
    ...errorMessages(unknownsResponse?.error_codes, "미확인 항목"),
  ];
  const readFailure = !sectionsPayloadAvailable
    || !unknownsPayloadAvailable
    || [...(sectionsResponse?.error_codes ?? []), ...(unknownsResponse?.error_codes ?? [])]
      .some((code) => READ_FAILURE_CODES.includes(code));
  const profileVersion = sectionsResponse?.profile_version ?? unknownsResponse?.profile_version ?? null;
  const profileDigest = sectionsResponse?.profile_digest ?? unknownsResponse?.profile_digest ?? null;
  const referenceFields = Array.isArray(unknownsResponse?.reference_fields) ? unknownsResponse.reference_fields : [];
  const unknownTotal = !readFailure && unknownsPayloadAvailable ? unknownsResponse?.total ?? null : null;
  const selectedCounts = selected ? countSection(selected) : null;

  return (
    <div className="crit-workspace" id="criteria-panel-profile" role="tabpanel">
      <Queue
        count={!readFailure && sectionsPayloadAvailable ? visibleSections.length : null}
        emptyText={readFailure ? "프로필 응답을 확인할 수 없습니다." : sections.length === 0 ? "표시할 프로필 절이 없습니다." : "검색·필터 조건에 맞는 절이 없습니다."}
        footer={
          <span className="crit-profile-summary">
            {(["confirmed", "inferred", "unknown"] as const).map((status, index) => (
              <span key={status}>
                {index > 0 ? " · " : ""}
                {FILTER_LABELS[status]} <strong>{summaryCount(summary, status, sectionsSummaryAvailable)}</strong>
              </span>
            ))}
            {" · 승인된 구조화 사본 · 읽기 전용"}
          </span>
        }
        items={visibleSections.map((section) => {
          const counts = countSection(section);
          return {
            id: section.id,
            title: section.number ? `${section.number} ${section.title}` : section.title,
            subtitle: distinctHeading(section),
            status: STATE_LABELS[section.state] ?? "상태 미기록",
            meta: `${counts.items}개 항목 · 하위 절 ${counts.children}개 · 미확인 ${counts.unknown}개${counts.errors > 0 ? ` · 구조화 실패 ${counts.errors}건` : ""}`,
          };
        })}
        onSelect={(id) => updateParams({ psection: id })}
        selectedId={selected?.id ?? null}
        title="기준 항목"
        tools={
          <>
            <TextInput
              hasClear
              isLabelHidden
              label="프로필 항목 검색"
              onChange={(value) => updateParams({ pq: value, psection: null })}
              placeholder="항목·내용 검색"
              size="sm"
              startIcon={Search}
              value={query}
            />
            <div aria-label="확인 상태 필터" className="crit-filters" role="group">
              {(Object.keys(FILTER_LABELS) as ProfileFilter[]).map((value) => (
                <Button
                  aria-pressed={filter === value}
                  key={value}
                  label={FILTER_LABELS[value]}
                  onClick={() => updateParams({ pstatus: value === "all" ? null : value, psection: null })}
                  size="sm"
                />
              ))}
            </div>
          </>
        }
      />
      <section aria-label="선택한 프로필 항목" className="crit-detail">
        {/* 응답이 깨진 사실은 고를 절이 하나도 없을 때에도 사라지면 안 된다.
          * 빈 목록과 읽기 실패는 다른 상태다. */}
        {readFailure && selected ? (
          <div className="crit-detail-alert">
            <Note role="alert" title="프로필 응답 확인 필요" tone="error">
              {responseMessages.length > 0 ? responseMessages.join(" ") : "응답 형식이 불완전하여 일부 상태를 미확인으로 표시합니다."}
            </Note>
          </div>
        ) : null}
        {selected && selectedCounts ? (
          <>
            <DetailHeader
              eyebrow="회사 프로필 · 승인 사본"
              status="읽기 전용"
              title={selected.number ? `${selected.number} ${selected.title}` : selected.title}
            >
              {/* 상세 제목 밑줄은 시안처럼 짧게 둔다. 사본 버전과 식별 해시
                * 전문은 "사본 정보" 창에 있고 여기서 되풀이하지 않는다. */}
              <Small>{`구조화 항목 ${selectedCounts.items}개 · 미확인 ${selectedCounts.unknown}개`}</Small>
            </DetailHeader>
            <div className="crit-detail-scroll" id="criteria-profile-detail">
              <ul className="crit-tree">
                <SectionTree depth={0} filter={filter} query={query} section={selected} unknowns={unknowns} />
              </ul>
              {selectedCounts.confirmed < selectedCounts.items ? (
                <Note title={`추가 확인 필요 · ${selectedCounts.items - selectedCounts.confirmed}개 항목`}>
                  추정·미확인 항목은 원문과 증빙 확인 전까지 확정된 회사 역량으로 사용하지 않습니다.
                </Note>
              ) : null}
              <Section title="미확인 항목 참조 횟수">
                <Small>
                  {`판정의 근거 source·fact와 확인 항목 why에서 절 번호 또는 항목 이름이 언급된 횟수입니다. 참조 필드 · ${referenceFields.length > 0 ? referenceFields.join(", ") : "값 없음 (빈 목록)"}`}
                </Small>
                <Facts items={[
                  ["프로필 전체 미확인 항목", unknownTotal === null ? "미확인" : `${formatNumber(unknownTotal)}건`],
                  ["이 절의 미확인 항목", `${unknowns.filter((item) => item.section_id === selected.id).length}건`],
                ]} />
                {unknownTotal === null ? (
                  <Note role="alert" title="미확인 항목 수를 확정할 수 없습니다" tone="warning">
                    프로필 사본 읽기 오류가 있어 0건으로 표시하지 않습니다.
                  </Note>
                ) : null}
              </Section>
            </div>
            <DetailFooter note={<><LockKeyhole aria-hidden="true" /> 승인 사본은 이 화면에서 편집할 수 없습니다.</>}>
              <Button label="사본 정보" onClick={() => setSnapshotOpen(true)} size="sm" />
            </DetailFooter>
          </>
        ) : (
          <StateView
            action={readFailure
              ? <Button label="다시 조회" onClick={() => { void sectionsQuery.refetch(); void unknownsQuery.refetch(); }} />
              : <Button label="필터 초기화" onClick={() => updateParams({ pq: null, pstatus: null, psection: null })} />}
            description={readFailure
              ? responseMessages.join(" ") || "응답 형식이 불완전하여 항목 수와 상태를 확인할 수 없습니다."
              : sections.length === 0
              ? "승인된 사본에 표시할 절이 없습니다. 조회 실패와 빈 사본은 다른 상태입니다."
              : "검색어와 확인 상태 필터를 바꾸면 다른 절을 볼 수 있습니다."}
            kind={readFailure ? "error" : "empty"}
            title={readFailure ? "프로필 응답 확인 필요" : sections.length === 0 ? "표시할 프로필 절이 없습니다." : "조건에 맞는 절이 없습니다."}
          />
        )}
      </section>
      <CriteriaDialog onClose={() => setSnapshotOpen(false)} open={snapshotOpen} title="승인 사본 정보">
        <Facts items={[
          ["프로필 버전", <span className="crit-mono" key="v">{profileVersion ?? "사본 미확인"}</span>],
          ["식별 해시", <code key="d">{profileDigest ?? "미확인"}</code>],
          ["응답 규격", <code key="s">{sectionsResponse?.schema_version ?? "미확인"}</code>],
          ["관리 범위", "승인된 구조화 항목 · 읽기 전용"],
          ["절 수", sectionsPayloadAvailable ? `${sections.length}개` : "미확인"],
          ["미확인 항목", unknownTotal === null ? "미확인" : `${formatNumber(unknownTotal)}건`],
        ]} />
        <Note title="이 화면에는 프로필 편집 API가 없습니다">
          원본 파일 경로와 원문 블록은 응답에 포함되지 않으며 화면도 보관하지 않습니다.
        </Note>
        {responseMessages.length > 0 ? (
          <Disclosure summary="응답 오류 코드">
            <ul>{responseMessages.map((message) => <li key={message}>{message}</li>)}</ul>
          </Disclosure>
        ) : null}
        <DialogActions>
          <CancelButton label="닫기" onClick={() => setSnapshotOpen(false)} />
        </DialogActions>
      </CriteriaDialog>
    </div>
  );
}
