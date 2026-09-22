import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { api } from "../../lib/api";
import { formatNumber, runStatusLabel } from "../../lib/format";
import { runOptionLabel } from "../../lib/runOptions";
import type { RunSummary } from "../../lib/types";
import {
  CancelButton,
  CriteriaDialog,
  DataTable,
  DialogActions,
  Section,
  Small,
  StateView,
} from "./CriteriaPrimitives";

/**
 * 대시보드 `담당자 확인 요청` 중 회사 역량 미확인 항목의 이식
 * (ADR-0066 결정 7·2 → spec §7.2). `verification_requests` 가운데
 * **프로필 절이 식별된 것**(`profile_sections`가 비어 있지 않은 것,
 * `app/screening/projection.py:677` 부근)만 이 절이 보여준다. 공고별로만
 * 걸리는 확인 항목(`notice_pks`만 있는 것)은 여기 넣지 않는다 — 대시보드
 * `사람 확인 필요` 패널이 맡는다(다른 패키지 H2).
 *
 * 회사 프로필 화면 자체는 회차와 무관한 승인 사본을 읽기 전용으로 보인다.
 * 확인 요청은 판정이 쌓인 회차 단위 집계라서 이 절만 회차 축이 필요하다.
 * `MetricsPage`(`/metrics?run=…`)와 같은 패턴을 따른다 — `run` 검색
 * 파라미터, 판정이 있는 최신 회차를 기본으로, 회차 선택 다이얼로그.
 */

function runLabel(run: RunSummary): string {
  return runOptionLabel(run);
}

export function VerificationRequestsPanel() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [runPickerOpen, setRunPickerOpen] = useState(false);

  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const runs = runsQuery.data?.items ?? [];

  const queryRunId = searchParams.get("run");
  // 판정이 없는 회차는 확인 요청도 없다. 명시적으로 고른 회차가 없으면
  // 판정을 갖춘 최신 회차를 기본으로 삼는다(`MetricsPage`와 같은 규칙).
  const selectedRun = runs.find((run) => run.run_id === queryRunId)
    ?? runs.find((run) => run.counts.judgments > 0)
    ?? runs[0]
    ?? null;

  const statsQuery = useQuery({
    queryKey: ["run-stats", selectedRun?.run_id],
    queryFn: () => api.getRunStats(selectedRun!.run_id),
    enabled: Boolean(selectedRun),
    staleTime: 30_000,
  });

  const updateRun = (runId: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", runId);
      return next;
    }, { replace: true });
    setRunPickerOpen(false);
  };

  const requests = (statsQuery.data?.verification_requests ?? [])
    .filter((item) => item.profile_sections.length > 0)
    .sort((a, b) => b.count - a.count || a.item.localeCompare(b.item, "ko"));

  const action = selectedRun ? (
    <Button label="회차 선택" onClick={() => setRunPickerOpen(true)} size="sm" />
  ) : undefined;

  return (
    <div className="crit-verification-requests" aria-label="확인 요청 · 프로필 절 기준">
      <Section action={action} title="확인 요청 · 프로필 절 기준">
        {runsQuery.isPending ? (
          <StateView description="확인 요청을 표시할 회차를 확인하는 중입니다." kind="loading" title="회차를 불러오는 중입니다" />
        ) : runsQuery.error ? (
          <StateView
            action={<Button label="다시 조회" onClick={() => { void runsQuery.refetch(); }} />}
            description="회차 목록을 확인할 수 없어 확인 요청을 표시할 수 없습니다. 0건이 아니라 조회 실패입니다."
            kind="error"
            title="회차 목록을 불러오지 못했습니다."
          />
        ) : !selectedRun ? (
          <StateView
            description="적재된 회차가 생기면 이 절에서 회사 역량 미확인 확인 요청을 볼 수 있습니다."
            kind="empty"
            title="확인할 회차가 없습니다."
          />
        ) : statsQuery.isPending ? (
          <StateView description="선택한 회차의 확인 요청을 확인하는 중입니다." kind="loading" title="확인 요청을 불러오는 중입니다" />
        ) : statsQuery.isError ? (
          <StateView
            action={<Button label="다시 조회" onClick={() => { void statsQuery.refetch(); }} />}
            description="이 회차의 확인 요청을 불러오지 못했습니다. 조회 실패를 0건으로 표시하지 않습니다."
            kind="error"
            title="확인 요청을 불러오지 못했습니다."
          />
        ) : (
          <>
            <Small>
              {`회차 ${runLabel(selectedRun)} · ${selectedRun.run_id} · ${runStatusLabel(selectedRun.status)} · 판정 ${formatNumber(selectedRun.counts.judgments)}건 기준`}
            </Small>
            {requests.length === 0 ? (
              <StateView
                description="공고별로만 걸리는 확인 항목은 대시보드 `사람 확인 필요` 패널에서 확인합니다."
                kind="empty"
                title="이 회차에는 프로필 절이 식별된 확인 요청이 없습니다."
              />
            ) : (
              <DataTable
                caption="확인 요청 · 프로필 절 기준"
                headings={["확인 항목", "근거 프로필 절", "건수"]}
                rows={requests.map((item) => [
                  <Text key="item" weight="semibold">{item.item || "확인 항목 미확인"}</Text>,
                  <Text key="sections">{item.profile_sections.join(" · ")}</Text>,
                  <Text key="count">{`${formatNumber(item.count)}건`}</Text>,
                ])}
              />
            )}
          </>
        )}
      </Section>
      <CriteriaDialog onClose={() => setRunPickerOpen(false)} open={runPickerOpen} title="확인 요청 대상 회차">
        <Selector
          hasSearch
          label="대상 회차"
          onChange={(value) => updateRun(value)}
          options={runs.map((run) => ({
            value: run.run_id,
            label: runOptionLabel(run),
            description: `${run.run_id} · ${runStatusLabel(run.status)} · 판정 ${formatNumber(run.counts.judgments)}건`,
          }))}
          placeholder="회차를 선택하십시오"
          value={selectedRun?.run_id ?? ""}
        />
        <Small>{`조회한 회차 목록 ${runs.length}개.`}</Small>
        <DialogActions>
          <CancelButton label="닫기" onClick={() => setRunPickerOpen(false)} />
        </DialogActions>
      </CriteriaDialog>
    </div>
  );
}
