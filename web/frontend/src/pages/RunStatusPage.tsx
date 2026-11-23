import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { StatusMark } from "../components/common/Marks";
import { SectionNav } from "../components/common/SectionNav";
import { AuditPanel } from "../components/runs/AuditPanel";
import { Caption, DialogFacts, Note } from "../components/runs/RunStatusPrimitives";
import { isScreeningTerminal, useRecentScreeningExecutions, RECENT_EXECUTION_LIMIT } from "../components/runs/runStatusData";
import { api } from "../lib/api";
import { formatNumber } from "../lib/format";
import type { DailyCollectionTrackStatus } from "../lib/types";
import { AttachmentsPage } from "./AttachmentsPage";
import { OperationsPage } from "./OperationsPage";
import { RunsPage } from "./RunsPage";
import "../styles/runstatus-erp.css";

const SECTIONS = [
  { id: "runs", label: "수집 실행", path: "/runs", Page: RunsPage },
  { id: "attachments", label: "첨부 확보", path: "/attachments", Page: AttachmentsPage },
  { id: "operations", label: "상시 운영", path: "/operations", Page: OperationsPage },
  { id: "audit", label: "산출물 감사 로그", path: "/audit", Page: AuditPanel },
] as const;

const GROUPS = [{ title: "실행 상태", items: SECTIONS }];

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
function SummaryLine({ onOpenConditions, collectionRefreshing }: {
  onOpenConditions: () => void;
  collectionRefreshing: boolean;
}) {
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
  const refreshing = collectionRefreshing || alwaysOnQuery.isFetching || executionsQuery.isFetching;

  const alwaysOnValue = alwaysOnQuery.isError
    ? "미확인"
    : !alwaysOn
      ? "확인 중"
      : alwaysOn.effective_enabled ? "켜짐" : "꺼짐";
  const alwaysOnDetail = alwaysOnQuery.isError
    ? "조회 실패 · 꺼짐도 켜짐도 아니에요"
    : !alwaysOn
      ? "조회 중"
      : `설정 ${alwaysOn.configured_enabled ? "켜짐" : "꺼짐"} · 환경 ${alwaysOn.environment_enabled ? "허용" : "차단"}`;

  return (
    <>
      <div className="rs-summary" aria-label="실행 상태 요약">
        <div className="rs-summary-item">
          <Caption as="span">공고 판정(C-1) 스케줄러</Caption>
          <Text className="rs-summary-value" as="span">{alwaysOnValue}</Text>
          <Caption as="span">{alwaysOnDetail}</Caption>
        </div>
        <div className="rs-summary-item">
          <Caption as="span">C-1 현재 실행</Caption>
          <Text className="rs-summary-value" as="span">
            {executionsQuery.isError ? "미확인" : running === null ? "확인 중" : `${running}건`}
          </Text>
        </div>
        <div className="rs-summary-item">
          <Caption as="span">C-1 조회 범위</Caption>
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
      </div>
      <PageHeaderActions>
        <Button label="운영 조건" size="sm" variant="ghost" onClick={onOpenConditions} />
        <Button
          label="새로고침"
          size="sm"
          variant="ghost"
          icon={<RefreshCw aria-hidden="true" />}
          aria-busy={refreshing}
          onClick={() => {
            // 현재 구역과 공통 요약에 필요한 활성 조회만 다시 부른다.
            void queryClient.invalidateQueries({ refetchType: "active" });
          }}
        />
      </PageHeaderActions>
    </>
  );
}

const COLLECTION_STATUS = {
  complete: { label: "수집 완료", tone: "neutral" },
  incomplete: { label: "적재 확인 필요", tone: "warning" },
  missing: { label: "수집 기록 없음", tone: "neutral" },
} as const;

function CollectionTrack({ track }: { track: DailyCollectionTrackStatus }) {
  const name = track.track === "order-plans" ? "발주계획" : "공고(사전규격·입찰공고)";
  const state = COLLECTION_STATUS[track.state];
  const run = track.run_id ? encodeURIComponent(track.run_id) : null;
  return (
    <li className="rs-collection-track">
      <span className="rs-summary-label">{name}</span>
      <StatusMark mark={state} />
      <Caption as="span">{track.basis_date} 기준</Caption>
      {track.warning_count !== null && track.warning_count > 0 ? (
        <span className="rs-summary-value">적재 경고 {formatNumber(track.warning_count)}건</span>
      ) : null}
      {run ? (
        track.reasons.includes("ingest_warnings")
          ? <Link to={`/audit?run=${run}#run-warnings`} aria-label={`${name} 적재 경고 보기`}>적재 경고 보기</Link>
          : track.track === "order-plans"
            ? <Link to={`/runs?run=${run}&view=order-plan-screening`}>선별 실행 보기</Link>
            : <Link to={`/runs?run=${run}`} aria-label={`${name} 회차 보기`}>회차 보기</Link>
      ) : null}
    </li>
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
          <details><summary>판정 실행 기록 위치</summary><p>수집 실행에서 회차를 고른 뒤 공고는 실행 기록, 발주계획은 발주계획 선별 탭을 여세요. 모델 식별자(model_digest), 토큰 수, 처리 시간(duration_ms), 오류 코드를 확인할 수 있어요.</p></details>
          {alwaysOnQuery.isError ? (
            <Note title="상시 운영 상태를 불러오지 못했어요" tone="error">
              꺼져 있다는 뜻도 켜져 있다는 뜻도 아니에요. 현재 상태는 미확인이에요.
            </Note>
          ) : null}
          {state ? (
            <DialogFacts
              items={[
                ["설정값", state.configured_enabled ? "켜짐" : "꺼짐"],
                ["실제 운영", state.effective_enabled ? "켜짐" : "꺼짐"],
                ["환경 허용", state.environment_enabled ? "허용" : "차단"],
                ["품질 게이트", state.quality_gate_status ?? "연결 없음"],
                ["거절 사유", state.rejection_reason ?? (state.effective_enabled ? "차단 없음" : "서버가 사유를 남기지 않았어요")],
                [
                  "승인 조합",
                  <span className="rs-mono" key="binding">
                    {state.policy_version ?? "정책 값 없음"} · {state.model_name ?? "모델 값 없음"} · {state.company_profile_version ?? "프로필 값 없음"}
                  </span>,
                ],
              ]}
            />
          ) : null}
          <Note title="앱 시작은 아무것도 실행하지 않아요">
            startup은 migration·seed·정책 활성화·모델 호출을 수행하지 않아요. 승인 조합이 맞지
            않으면 상시 운영을 켤 수 없어요.
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
  const { id: section, Page } = SECTIONS.find(({ path }) => pathname === path || pathname.startsWith(`${path}/`)) ?? SECTIONS[0];
  const [conditionsOpen, setConditionsOpen] = useState(false);
  const collection = useQuery({
    queryKey: ["daily-collection-status"],
    queryFn: ({ signal }) => api.getDailyCollectionStatus({ signal }),
    enabled: section === "runs",
    staleTime: 30_000,
  });

  return (
    <section aria-label="실행 상태" className="workbench-admin rs-page" data-astryx-theme="bidops">
      <SectionNav label="실행 상태 구역" groups={GROUPS} current={section} search={search} />
      <div className="workbench-admin-main">
        <div className="workbench-admin-summary rs-overview">
          {section === "runs" ? (
            <section className="rs-collection" aria-label="일일 수집 상태">
              <h2>일일 수집</h2>
              {collection.isError ? (
                <p role="status">일일 수집 상태를 불러오지 못했어요.</p>
              ) : collection.isPending ? (
                <p role="status">일일 수집 상태를 확인하는 중이에요.</p>
              ) : (
                <ul>{collection.data.tracks.map((track) => <CollectionTrack key={track.track} track={track} />)}</ul>
              )}
            </section>
          ) : null}
          <SummaryLine onOpenConditions={() => setConditionsOpen(true)} collectionRefreshing={collection.isFetching} />
        </div>
        <Page />
      </div>
      <ConditionsDialog open={conditionsOpen} onClose={() => setConditionsOpen(false)} />
    </section>
  );
}
