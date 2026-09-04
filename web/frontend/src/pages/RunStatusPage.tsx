import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Selector } from "@astryxdesign/core/Selector";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Text } from "@astryxdesign/core/Text";
import { ArtifactValidation } from "../components/runs/ArtifactValidation";
import { ExecutionLog } from "../components/runs/ExecutionLog";
import { EmptyState } from "../components/common/EmptyState";
import { api } from "../lib/api";
import { AttachmentsPage } from "./AttachmentsPage";
import { OperationsPage } from "./OperationsPage";
import { RunsPage } from "./RunsPage";
import "../styles/criteria-runstatus.css";

// docs/design/PLAN.md 2단계 · ADR-0041 결정 2: 수집 실행·첨부 확보·상시 운영
// 3화면과 산출물 감사 로그를 이 한 화면으로 합친다. 대상 사용자가 판정
// 담당자가 아니라 운영자이므로 사이드바 최상위 네 칸을 쓰지 않는다.
//
// CriteriaPage와 같은 이유로 탭을 경로에 둔다. 옛 경로 /runs · /attachments ·
// /operations · /audit가 리다이렉트가 아니라 각 탭의 정식 주소로 남는다.

export type RunStatusTab = "runs" | "attachments" | "operations" | "audit";

const TABS: { value: RunStatusTab; label: string; path: string }[] = [
  { value: "runs", label: "수집 실행", path: "/runs" },
  { value: "attachments", label: "첨부 확보", path: "/attachments" },
  { value: "operations", label: "상시 운영", path: "/operations" },
  { value: "audit", label: "산출물 감사 로그", path: "/audit" },
];

export function runStatusTabFromPathname(pathname: string): RunStatusTab {
  const matched = TABS.find((tab) => pathname === tab.path || pathname.startsWith(`${tab.path}/`));
  return matched?.value ?? "runs";
}

function formatRunOption(runId: string, from: string | null, to: string | null): string {
  if (!from && !to) return runId;
  return `${runId} · ${from ?? "null"} ~ ${to ?? "null"}`;
}

/**
 * 첨부 확보와 산출물 감사 로그는 회차 하나를 골라야 하는 화면이다. 기준과 운영
 * 묶음에서는 상단 전역 회차 선택기가 보이지 않으므로(PRD §2.1) 이 화면이 회차
 * 상태를 직접 소유한다. 고른 회차는 주소의 run 파라미터에 남겨 두어 흡수 이전과
 * 같은 링크를 그대로 쓰고, AttachmentsPage도 고치지 않고 그대로 읽게 한다.
 */
function RunPicker({ label }: { label: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const runs = runsQuery.data?.items ?? [];
  const queryRunId = searchParams.get("run");
  const selectedRunId = runs.some((run) => run.run_id === queryRunId) ? queryRunId : runs[0]?.run_id ?? null;

  function selectRun(runId: string) {
    const next = new URLSearchParams(searchParams);
    next.set("run", runId);
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="ws-run-picker">
      <div className="ws-run-picker-field">
        <Selector
          label={label}
          options={runs.map((run) => ({
            value: run.run_id,
            label: formatRunOption(run.run_id, run.window_from, run.window_to),
          }))}
          value={selectedRunId ?? undefined}
          onChange={selectRun}
          placeholder={runsQuery.isPending ? "회차를 불러오는 중…" : "회차 선택"}
          emptyText="표시할 회차가 없습니다."
          hasSearch
        />
      </div>
      <Text type="supporting" color="secondary" as="span">
        이 화면은 상단 회차 선택기를 쓰지 않고 회차를 직접 고릅니다.
      </Text>
    </div>
  );
}

/** 산출물 감사 로그. 판정 화면의 기본 표시에서 뺐을 뿐 삭제하지 않았다(ADR-0041 결정 5). */
function AuditLogPanel() {
  const [searchParams] = useSearchParams();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const runs = runsQuery.data?.items ?? [];
  const queryRunId = searchParams.get("run");
  const selectedRunId = runs.some((run) => run.run_id === queryRunId) ? queryRunId : runs[0]?.run_id ?? null;

  const detailQuery = useQuery({
    queryKey: ["run", selectedRunId],
    queryFn: () => api.getRun(selectedRunId as string),
    enabled: Boolean(selectedRunId),
    staleTime: 2_000,
  });
  const logsQuery = useQuery({
    queryKey: ["pipeline-logs", selectedRunId],
    queryFn: ({ signal }) => api.getPipelineLogs(selectedRunId as string, undefined, { signal }),
    enabled: Boolean(selectedRunId),
    staleTime: 2_000,
  });

  if (!runsQuery.isPending && !selectedRunId) {
    return (
      <div className="gng-empty">
        <EmptyState
          title="표시할 회차가 없습니다."
          description="수집 실행이 없으면 산출물 감사 로그도 없습니다. 없음을 정상으로 해석하지 않습니다."
        />
      </div>
    );
  }

  return (
    <section className="runs-page" aria-label="산출물 감사 로그">
      {detailQuery.data ? (
        <ArtifactValidation artifacts={detailQuery.data.artifacts} warningCounts={detailQuery.data.warning_counts} />
      ) : null}
      <ExecutionLog data={logsQuery.data} loading={logsQuery.isLoading} error={logsQuery.error} />
    </section>
  );
}

export function RunStatusPage() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const tab = runStatusTabFromPathname(pathname);
  const panelId = `run-status-panel-${tab}`;
  const needsRun = tab === "attachments" || tab === "audit";

  return (
    <section aria-labelledby="run-status-page-title" className="ws-page" data-astryx-theme="bidops">
      <h2 className="visually-hidden" id="run-status-page-title">실행 상태</h2>
      <div className="ws-tabs">
        <TabList
          value={tab}
          onChange={(value) => {
            const next = TABS.find((item) => item.value === value);
            if (next) navigate({ pathname: next.path, search });
          }}
          role="tablist"
          hasDivider
        >
          {TABS.map((item) => (
            <Tab key={item.value} label={item.label} panelId={`run-status-panel-${item.value}`} value={item.value} />
          ))}
        </TabList>
      </div>
      {needsRun ? <RunPicker label={tab === "attachments" ? "첨부 확보 대상 회차" : "감사 로그 대상 회차"} /> : null}
      <div className="ws-body">
        <div className="ws-panel" id={panelId} role="tabpanel" aria-label={TABS.find((item) => item.value === tab)?.label}>
          {tab === "runs" ? <RunsPage /> : null}
          {tab === "attachments" ? <AttachmentsPage /> : null}
          {tab === "operations" ? <OperationsPage /> : null}
          {tab === "audit" ? <AuditLogPanel /> : null}
        </div>
      </div>
    </section>
  );
}
