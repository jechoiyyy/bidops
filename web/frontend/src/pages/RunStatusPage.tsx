import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Text } from "@astryxdesign/core/Text";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { AuditPanel } from "../components/runs/AuditPanel";
import { Caption, Facts, Note } from "../components/runs/RunStatusPrimitives";
import { isScreeningTerminal, useRecentScreeningExecutions, RECENT_EXECUTION_LIMIT } from "../components/runs/runStatusData";
import { api } from "../lib/api";
import { AttachmentsPage } from "./AttachmentsPage";
import { OperationsPage } from "./OperationsPage";
import { RunsPage } from "./RunsPage";
import "../styles/runstatus-erp.css";

// docs/design/PLAN.md 2단계 · ADR-0041 결정 2: 수집 실행·첨부 확보·상시 운영
// 3화면과 산출물 감사 로그를 이 한 화면으로 합친다.
//
// 승인된 시안(`design-previews/bidops-criteria-runstatus-erp-20260907/`)의 구조를
// 그대로 옮긴다: 네 탭 → 요약 한 줄 → 목록 38% / 상세 62% → 짧은 경계 각주.
//
// 탭 선택은 쿼리 파라미터가 아니라 **경로**에 둔다. 옛 경로 /runs · /attachments ·
// /operations · /audit가 리다이렉트가 아니라 각 탭의 정식 주소로 남는다.
//
// 항상 켜져 있던 경계 패널(`OperationsGuardrails`)은 기본 화면을 차지하지 않는다.
// 그 안의 사실은 사라지지 않고 (1) 이 요약 한 줄, (2) 아래 `운영 조건` 대화상자,
// (3) 각 탭의 맥락 주석으로 옮겼다(COMMON-TASK §FIXED VISUALS).

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

function clockLabel(value: number | undefined): string {
  if (!value) return "아직 없음";
  return new Intl.DateTimeFormat("ko-KR", { timeStyle: "medium" }).format(new Date(value));
}

/**
 * 요약 한 줄.
 *
 * 상시 운영은 설정값·실제·환경·거절 사유를 구분한다. 조회가 실패하면 "꺼짐"이
 * 아니라 **미확인**이다 — 실패를 안전한 상태로 읽으면 안 된다.
 * 현재 실행 건수는 실제로 받은 실행 목록에서 센 값이며 그 범위를 함께 적는다.
 */
function SummaryLine({ onOpenConditions }: { onOpenConditions: () => void }) {
  const queryClient = useQueryClient();
  const alwaysOnQuery = useQuery({
    queryKey: ["always-on"],
    queryFn: ({ signal }) => api.getAlwaysOn({ signal }),
    staleTime: 15_000,
  });
  const executionsQuery = useRecentScreeningExecutions();
  const alwaysOn = alwaysOnQuery.data;
  const executions = executionsQuery.data;
  const running = executions ? executions.items.filter((item) => !isScreeningTerminal(item.status)).length : null;
  const lastLoaded = Math.max(alwaysOnQuery.dataUpdatedAt, executionsQuery.dataUpdatedAt);
  const refreshing = alwaysOnQuery.isFetching || executionsQuery.isFetching;

  const alwaysOnValue = alwaysOnQuery.isError
    ? "미확인"
    : !alwaysOn
      ? "확인 중"
      : alwaysOn.effective_enabled ? "켜짐" : "꺼짐";
  const alwaysOnDetail = alwaysOnQuery.isError
    ? "조회 실패 · 꺼짐도 켜짐도 아닙니다"
    : !alwaysOn
      ? "조회 중"
      : `설정 ${alwaysOn.configured_enabled ? "켜짐" : "꺼짐"} · 환경 ${alwaysOn.environment_enabled ? "허용" : "차단"}`;

  return (
    <div className="rs-summary" aria-label="실행 상태 요약">
      <div className="rs-summary-item">
        <Caption as="span">상시 운영</Caption>
        <Text className="rs-summary-value" as="span">{alwaysOnValue}</Text>
        <Caption as="span">{alwaysOnDetail}</Caption>
      </div>
      <div className="rs-summary-item">
        <Caption as="span">현재 실행</Caption>
        <Text className="rs-summary-value" as="span">
          {executionsQuery.isError ? "미확인" : running === null ? "확인 중" : `${running}건`}
        </Text>
      </div>
      <div className="rs-summary-item">
        <Caption as="span">조회 범위</Caption>
        <Text className="rs-summary-value" as="span">
          {executionsQuery.isError
            ? "조회 실패"
            : executions
              ? `최근 ${executions.items.length}건 / 전체 ${executions.total}건`
              : `최근 ${RECENT_EXECUTION_LIMIT}건 요청`}
        </Text>
        {/* 조회한 범위를 밝히고, 그 밖은 0이 아니라 미확인이라고 못박는다. */}
        <Caption as="span">범위 밖 미확인</Caption>
      </div>
      <div className="rs-summary-item">
        <Caption as="span">마지막 성공 조회</Caption>
        <Text className="rs-summary-value" as="span">{clockLabel(lastLoaded || undefined)}</Text>
      </div>
      <div className="rs-summary-actions">
        <Button label="운영 조건" size="sm" variant="ghost" onClick={onOpenConditions} />
        <Button
          label="새로고침"
          size="sm"
          variant="ghost"
          icon={<RefreshCw aria-hidden="true" />}
          aria-busy={refreshing}
          onClick={() => {
            // 지금 화면에 붙어 있는 조회만 다시 부른다. 닫힌 탭의 조회는
            // 활성이 아니므로 한꺼번에 나가지 않는다.
            void queryClient.invalidateQueries({ refetchType: "active" });
          }}
        />
      </div>
    </div>
  );
}

/**
 * `운영 조건` 대화상자. 옛 경계 패널이 항상 자리를 차지하며 말하던 두 가지를
 * 그대로 담는다: 운영 텔레메트리를 어디서 보는지, 상시 운영이 꺼져 있는 이유가
 * 무엇인지. 서버가 준 거절 사유를 그대로 보여주고 "곧 켜짐"으로 바꾸지 않는다.
 */
function ConditionsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const alwaysOnQuery = useQuery({
    queryKey: ["always-on"],
    queryFn: ({ signal }) => api.getAlwaysOn({ signal }),
    staleTime: 15_000,
    enabled: open,
  });
  const state = alwaysOnQuery.data;
  return (
    <Dialog isOpen={open} onOpenChange={(next) => { if (!next) onClose(); }} purpose="info" width={640} maxHeight="90dvh">
      {/* 본문은 닫혀 있어도 마운트한 채로 둔다. Astryx Dialog는 마운트 시점에
        * `DialogHeader`의 제목으로 접근 이름을 잡으므로, 열릴 때만 그리면
        * 대화상자에 이름이 붙지 않는다. 닫힌 `<dialog>`는 브라우저가
        * `display: none`으로 숨기므로 접근성 트리에도 남지 않는다. */}
      <div className="rs-dialog-body" data-astryx-theme="bidops">
        <DialogHeader title="운영 조건과 경계" onOpenChange={(next) => { if (!next) onClose(); }} />
        <div className="rs-dialog-scroll">
          <Note title="운영 텔레메트리는 삭제하지 않았습니다">
            model_digest · token 입력/캐시/출력 · duration_ms · 오류 코드는 판정 화면의 기본 표시에서
            뺐을 뿐입니다. 수집 실행 탭에서 실행을 고르고 실행 기록·실행 기준 탭에서 확인합니다.
          </Note>
          {alwaysOnQuery.isError ? (
            <Note title="상시 운영 상태를 불러오지 못했습니다" tone="error">
              꺼져 있다는 뜻도 켜져 있다는 뜻도 아닙니다. 현재 상태는 미확인입니다.
            </Note>
          ) : null}
          {state ? (
            <Facts
              items={[
                ["설정값", state.configured_enabled ? "켜짐" : "꺼짐"],
                ["실제 운영", state.effective_enabled ? "켜짐" : "꺼짐"],
                ["환경 허용", state.environment_enabled ? "허용" : "차단"],
                ["품질 게이트", state.quality_gate_status ?? "연결 없음"],
                ["거절 사유", state.rejection_reason ?? (state.effective_enabled ? "차단 없음" : "서버가 사유를 남기지 않았습니다")],
                [
                  "승인 조합",
                  <span className="rs-mono" key="binding">
                    {state.policy_version ?? "정책 값 없음"} · {state.model_name ?? "모델 값 없음"} · {state.company_profile_version ?? "프로필 값 없음"}
                  </span>,
                ],
              ]}
            />
          ) : null}
          <Note title="앱 시작은 아무것도 실행하지 않습니다">
            startup은 migration·seed·정책 활성화·모델 호출을 수행하지 않습니다. 승인 조합이 맞지
            않으면 상시 운영을 켤 수 없습니다.
          </Note>
        </div>
        <div className="rs-dialog-actions">
          <Button label="확인" onClick={onClose} />
        </div>
      </div>
    </Dialog>
  );
}

export function RunStatusPage() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const tab = runStatusTabFromPathname(pathname);
  const panelId = `run-status-panel-${tab}`;
  const [conditionsOpen, setConditionsOpen] = useState(false);

  return (
    <section aria-labelledby="run-status-page-title" className="rs-page" data-astryx-theme="bidops">
      <h2 className="visually-hidden" id="run-status-page-title">실행 상태</h2>
      <div className="rs-tabs">
        <TabList
          value={tab}
          onChange={(value) => {
            const next = TABS.find((item) => item.value === value);
            // 회차·선택 ID를 포함한 기존 쿼리를 그대로 넘긴다.
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

      <SummaryLine onOpenConditions={() => setConditionsOpen(true)} />

      {/* 고른 탭만 렌더한다. 넷을 모두 마운트하면 네 화면의 무거운 조회가 한꺼번에
        * 나가고, 보이지 않는 화면의 실패까지 알려야 한다. */}
      {tab === "runs" ? <RunsPage panelId={panelId} /> : null}
      {tab === "attachments" ? <AttachmentsPage panelId={panelId} /> : null}
      {tab === "operations" ? <OperationsPage panelId={panelId} /> : null}
      {tab === "audit" ? <AuditPanel panelId={panelId} /> : null}

      <div className="rs-boundary">
        <Caption>
          진행 상태와 품질 표식은 별도입니다. 미확인·미측정을 0이나 성공으로 표시하지 않습니다.
          추적 승인과 최종 입찰 Go/No-Go는 이 화면에서 결정하지 않습니다.
        </Caption>
      </div>

      <ConditionsDialog open={conditionsOpen} onClose={() => setConditionsOpen(false)} />
    </section>
  );
}
