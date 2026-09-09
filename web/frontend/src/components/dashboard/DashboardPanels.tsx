import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, proportional, pixel } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { ArrowRight, ChevronRight } from "lucide-react";
import type { RunStatsResponse, ValidationMetric, VerificationRequest } from "../../lib/types";
import { formatNumber } from "../../lib/format";
import { DashboardPanel, DashboardState, LinkButton, Small, Tag } from "./DashboardPrimitives";
import { daysFromReference, metricBasis, metricStatus, metricValue, runLink, snapshotTime, type DeadlineFilter } from "./dashboardData";

export function DeadlinePanel({ stats, filter, onFilterChange }: {
  stats: RunStatsResponse; filter: DeadlineFilter; onFilterChange: (filter: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasReference = Number.isFinite(Date.parse(stats.generated_at));
  const rows = stats.imminent_deadlines.filter(item => {
    const days = daysFromReference(item.deadline_at, stats.generated_at);
    // Do not count unknown, expired or out-of-window dates as imminent.
    const difference = Date.parse(item.deadline_at ?? "") - Date.parse(stats.generated_at);
    const inWindow = days !== null && difference >= 0 && days <= (filter === "urgent" ? 3 : 7);
    return inWindow && (filter !== "checks" || item.blocking_verification_items.length > 0);
  });
  const visible = expanded ? rows : rows.slice(0, 3);
  const reference = snapshotTime(stats.generated_at, stats.timezone);
  return <DashboardPanel title="마감 공고" className="dash-deadlines-panel"
    action={<div className="dash-row"><Small>{hasReference ? `${formatNumber(rows.length)}건` : "건수 미확인"}</Small><Selector label="마감 공고 필터" isLabelHidden size="sm" value={filter}
      onChange={value => { setExpanded(false); onFilterChange(value); }}
      options={[{ value: "week", label: "7일 이내" }, { value: "urgent", label: "3일 이내" }, { value: "checks", label: "확인 항목 있음" }]} /></div>}
    footer={<><Small>{hasReference ? `${reference} 기준 · ${visible.length} / ${rows.length}건 표시` : "기준 시각 미확인"}</Small><Button label={expanded ? "접기" : "전체 보기"} size="sm" variant="ghost"
      aria-expanded={expanded} isDisabled={rows.length <= 3} onClick={() => setExpanded(value => !value)} /></>}>
    {visible.length ? <Table data={visible.map(item => ({ ...item }))} idKey="id" density="compact" dividers="rows" hasHover columns={[
      { key: "title", header: "공고명 / 발주기관", width: proportional(1), renderCell: item => <Link className="dash-notice-link" to={runLink(`/judgments/${item.id}`, stats.run_id)}>
        <Text className="dash-notice-title" weight="semibold">{item.title?.trim() || "공고명 미확인"}</Text>
        <Text className="dash-notice-agency" weight="semibold">{item.agency?.trim() || "발주기관 미확인"}</Text>
      </Link> },
      { key: "grade", header: "적합성 등급", width: pixel(100), renderCell: item => <div className="dash-cell-stack"><Tag label={item.grade ?? "판정 없음"} />
        <Small>{item.blocking_verification_items.length ? `확인 ${item.blocking_verification_items.length}개` : "확인 기록 없음"}</Small></div> },
      { key: "deadline_at", header: "마감", width: pixel(112), renderCell: item => {
        const days = daysFromReference(item.deadline_at, stats.generated_at);
        return <div className="dash-deadline-cell"><Text weight="semibold" className={days !== null && days <= 3 ? "dash-urgent" : ""}>{days === null ? "마감 미확인" : `D-${days}`}</Text><Small>{snapshotTime(item.deadline_at, stats.timezone)}</Small></div>;
      } },
    ]} /> : <DashboardState inline kind="empty" title={hasReference ? "조건에 맞는 마감 공고가 없습니다" : "마감 범위를 확인할 수 없습니다"}>{hasReference ? "회차 기준 시각의 7일 이내 목록입니다. 마감 미확인 공고는 기간 필터에서 제외됩니다." : "회차 기준 시각이 없어 마감 임박 건수를 계산할 수 없습니다."}</DashboardState>}
  </DashboardPanel>;
}

export function VerificationPanel({ requests, runId }: { requests: VerificationRequest[]; runId: string }) {
  const [expanded, setExpanded] = useState(false);
  const sorted = [...requests].sort((a, b) => b.count - a.count || a.item.localeCompare(b.item, "ko"));
  const visible = expanded ? sorted : sorted.slice(0, 3);
  return <DashboardPanel title="담당자 확인 요청" className="dash-requests-panel" action={<LinkButton label="회사 프로필" to={runLink("/profile", runId)} />}
    footer={<><Small>동일 공고에 여러 항목이 포함될 수 있습니다.</Small>{sorted.length > 3 && <Button label={expanded ? "접기" : `+${sorted.length - 3}개`} size="sm" variant="ghost" aria-label={expanded ? "확인 요청 접기" : "확인 요청 전체 보기"} aria-expanded={expanded} aria-controls="dashboard-verification-list" onClick={() => setExpanded(value => !value)} />}</>}>
    {visible.length ? <ol className="dash-request-list" id="dashboard-verification-list">{visible.map((request, index) => <li key={`${request.item}-${index}`}><Link className="dash-request-row" to={runLink("/profile", runId)}>
      <div className="dash-cell-stack"><Text weight="semibold">{request.item || "확인 항목 미확인"}</Text><Small>{request.profile_sections.length ? `회사 프로필 ${request.profile_sections.join(" · ")}` : "근거 프로필 절 미확인"}</Small></div>
      <div className="dash-row"><Text className="dash-request-count">{formatNumber(request.count)}건</Text><ChevronRight aria-hidden="true" /></div>
    </Link></li>)}</ol> : <DashboardState inline kind="empty" title="기록된 확인 요청이 없습니다">이 회차에서 확인된 요청 0개</DashboardState>}
  </DashboardPanel>;
}

export function SummaryPanel({ stats, reviewCount }: { stats: RunStatsResponse; reviewCount: number | null | undefined }) {
  const items: [string, number | null | undefined][] = [["수집", stats.collected_count], ["후보 풀", stats.candidate_count], ["판정 표본", stats.sample_count], ["담당자 리뷰", reviewCount]];
  return <DashboardPanel title="회차 요약" className="dash-summary-panel" action={<LinkButton label="공고 판정 이력" to={runLink("/queue", stats.run_id)} icon={<ArrowRight aria-hidden="true" />} />}>
    <div className="dash-pipeline-counts" aria-label="회차 처리 건수">{items.map(([label, value]) => <div className="dash-pipeline-item" key={label} role="group" aria-label={label}>
      <Small>{label}</Small><Text className={`dash-kpi-value ${value == null ? "dash-unknown-value" : ""}`} weight="semibold">{value === undefined ? "미확인" : formatNumber(value)}{typeof value === "number" && <Small>건</Small>}</Text>
    </div>)}</div>
    <div className="dash-grade-section"><Small>적합성 등급</Small><div className="dash-grade-legend">{stats.grade_distribution.length ? stats.grade_distribution.map(item => <Link key={item.key} className={`dash-grade-item dash-grade-${["우선 검토", "검토 권장", "관찰 대상", "제외"].indexOf(item.key)}`} to={runLink("/queue", stats.run_id, { grade: item.key })}>
      <i aria-hidden="true" /><Text>{item.label || item.key}</Text><Text weight="semibold">{formatNumber(item.count)}</Text>
    </Link>) : <Small>판정 분포 없음</Small>}</div></div>
  </DashboardPanel>;
}

export function ValidationPanel({ metrics, isPending, isError, onRetry, runId, auditMissed }: {
  metrics: ValidationMetric[]; isPending: boolean; isError: boolean; onRetry: () => void;
  runId: string; auditMissed: number | null;
}) {
  const sorted = [...metrics.filter(item => item.status === "fail"), ...metrics.filter(item => item.status !== "fail")];
  return <DashboardPanel title="검증 상태" className="dash-validation-panel" action={<LinkButton label="검증 지표" to={runLink("/metrics", runId)} />}>
    <div className="dash-validation-list">
      <div className="dash-validation-row" role="group" aria-label="1차 필터 누락"><div className="dash-cell-stack"><Text>1차 필터 누락</Text><Small>감사 표본 분모 미확인</Small></div><div className="dash-cell-stack dash-align-end"><Text weight="semibold">{formatNumber(auditMissed)}{auditMissed !== null && "건"}</Text><Small>누락률 계산 불가</Small></div></div>
      {isError ? <div className="dash-validation-error" role="alert"><Text>검증 지표를 불러오지 못했습니다</Text><Button label="검증 지표 다시 조회" size="sm" onClick={onRetry} /></div>
        : isPending ? <div className="dash-validation-row" role="status"><Text>검증 지표를 불러오는 중입니다</Text></div>
          : sorted.length ? sorted.map(item => <div className="dash-validation-row" key={item.key}><div className="dash-cell-stack"><Text>{item.label || item.key}</Text><Small>{metricBasis(item)}</Small></div><div className="dash-cell-stack dash-align-end">{metricValue(item) !== metricStatus(item) && <Text weight="semibold">{metricValue(item)}</Text>}<Tag label={metricStatus(item)} tone={item.status === "fail" ? "error" : item.status === "pass" ? "success" : "neutral"} /></div></div>)
            : <div className="dash-validation-row"><Text>검증 지표 없음</Text><Tag label="미확인" /></div>}
    </div>
  </DashboardPanel>;
}
