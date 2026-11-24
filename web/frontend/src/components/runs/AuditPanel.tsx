import { AdminListHeader, AdminRecordTable } from "../common/AdminRecordTable";
import type { Mark } from "../common/Marks";
import type { RecordTableState } from "../common/RecordTable";
import { DecisionBar, ReviewPreviewHeader, SplitWorkspace } from "../common/ReviewPrimitives";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import { FileSearch } from "lucide-react";
import { api } from "../../lib/api";
import { formatDateTime, formatRunRange, present } from "../../lib/format";
import type { ArtifactValidationResponse } from "../../lib/types";
import { ExecutionLog } from "./ExecutionLog";
import { RunPickerField, useSelectedRun } from "./RunPicker";
import {
  Caption,
  DataTable,
  DetailHeader,
  Facts,
  Note,
  Section,
} from "./RunStatusPrimitives";
import { isScreeningTerminal, useRecentScreeningExecutions } from "./runStatusData";
import { screeningStatusLabel } from "./ScreeningRunPanel";

/**
 * 산출물 감사 로그.
 *
 * 회차를 고르고 그 회차에 연결된 산출물의 생성·검증·경고 상태를 확인한다.
 * 서버가 준 `ArtifactValidationResponse`만 읽는다. 파일 이름으로 "최종 결과"
 * 여부를 추정하지 않고, 부분 산출물을 완전한 성공 결과로 발행하지 않는다.
 */

function artifactMark(artifact: ArtifactValidationResponse): Mark {
  if (!artifact.present) return { label: "미생성", tone: "neutral" };
  if (artifact.valid === null) return { label: "검증 미확인", tone: "neutral" };
  if (!artifact.valid) return { label: "검증 실패", tone: "error" };
  if (artifact.warnings.length > 0) return { label: `경고 ${artifact.warnings.length}건`, tone: "warning" };
  return { label: "검증 통과", tone: "success" };
}

function schemaLabel(artifact: ArtifactValidationResponse): string {
  if (!artifact.present) return "산출물 없음";
  return present(artifact.schema_version, "스키마 미확인");
}

export function AuditPanel() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { hash } = useLocation();
  const warningDisclosure = useRef<HTMLDetailsElement>(null);
  const { runs, selectedRunId, selectRun, isPending, isError, refetch } = useSelectedRun();
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null);
  const [logsOpen, setLogsOpen] = useState(false);

  const detailQuery = useQuery({
    queryKey: ["run", selectedRunId],
    queryFn: () => api.getRun(selectedRunId as string),
    enabled: Boolean(selectedRunId),
    staleTime: 5_000,
  });
  const logsQuery = useQuery({
    queryKey: ["pipeline-logs", selectedRunId],
    queryFn: ({ signal }) => api.getPipelineLogs(selectedRunId as string, undefined, { signal }),
    enabled: Boolean(selectedRunId) && logsOpen,
    staleTime: 2_000,
  });
  const executionsQuery = useRecentScreeningExecutions();

  const detail = detailQuery.data ?? null;
  const artifacts = detail?.artifacts ?? [];
  const artifact = artifacts.find((item) => item.name === selectedArtifact) ?? artifacts[0] ?? null;
  const warningCounts = detail?.warning_counts ?? {};
  const warningTotal = Object.values(warningCounts).reduce((sum, value) => sum + value, 0);

  useEffect(() => {
    const disclosure = warningDisclosure.current;
    if (hash !== "#run-warnings" || !disclosure) return;
    disclosure.open = true;
    disclosure.scrollIntoView({ block: "nearest" });
    disclosure.querySelector("summary")?.focus({ preventScroll: true });
  }, [hash, detail?.run_id]);

  // 이 회차에 연결된 실행이 아직 진행 중이면 산출물은 부분 결과일 수 있다.
  // 조회 범위 밖이면 진행 여부 자체가 미확인이다.
  const runExecutions = (executionsQuery.data?.items ?? []).filter((item) => item.source_run_id === selectedRunId);
  const activeExecution = runExecutions.find((item) => !isScreeningTerminal(item.status)) ?? null;
  const executionScopeKnown = Boolean(executionsQuery.data) && !executionsQuery.error;

  let listState: RecordTableState | undefined;
  if (isPending || (detailQuery.isPending && selectedRunId)) {
    listState = { kind: "loading", label: "산출물 목록을 불러오는 중이에요.", showLabel: true };
  } else if (detailQuery.isError) {
    listState = { kind: "error", message: {
      title: "산출물 목록을 불러오지 못했어요.",
      description: "조회 실패는 산출물 0건이 아니에요.",
      action: { label: "다시 시도", onClick: () => { void detailQuery.refetch(); } },
    } };
  } else if (artifacts.length === 0) {
    listState = { kind: "empty", message: {
      title: selectedRunId ? "이 회차에 연결된 산출물이 없어요." : "회차를 먼저 골라 주세요.",
      description: selectedRunId ? "없음을 검증 통과로 읽지 않아요." : undefined,
    } };
  }
  return (
    <SplitWorkspace className="workbench-admin-workspace" aria-label="산출물 감사 로그">
      <section className="review-split-list" aria-label="산출물 목록">
        <AdminListHeader title="산출물 목록" count={detailQuery.isError ? "미확인" : `${artifacts.length}건`}>
          <RunPickerField
            label="감사 대상 회차"
            runs={runs}
            selectedRunId={selectedRunId}
            onSelect={(runId) => { selectRun(runId); setSelectedArtifact(null); }}
            isPending={isPending}
            isError={isError}
            onRetry={refetch}
          />
        </AdminListHeader>
        <AdminRecordTable
          label="산출물 목록"
          selectedId={artifact?.name ?? null}
          onSelect={setSelectedArtifact}
          state={listState}
          rows={artifacts.map((item) => ({
            id: item.name,
            title: item.name,
            subtitle: schemaLabel(item),
            meta: item.warnings.length ? `경고 ${item.warnings.length}건` : item.present ? "경고 없음" : "생성 전",
            status: artifactMark(item),
          }))}
        />
        <footer className="workbench-admin-list-foot">
          <Caption>
            {selectedRunId ? `회차 ${selectedRunId} 기준` : "회차를 먼저 골라요"}
            {detail ? ` · 경고 합계 ${warningTotal}건` : ""}
          </Caption>
        </footer>
      </section>

      <section className="review-split-detail rs-detail-pane" aria-label="선택한 산출물">
        <ReviewPreviewHeader />
        {detail && (
          <details className="rs-disclosure" id="run-warnings" ref={warningDisclosure}>
            <summary>회차 전체 경고 집계 · {warningTotal}건</summary>
            {Object.keys(warningCounts).length > 0 ? (
              <DataTable
                caption="회차 전체 경고 집계"
                headings={["구분", "건수"]}
                rows={Object.entries(warningCounts).map(([key, value]) => ({ id: key, cells: [key, `${value}건`] }))}
              />
            ) : (
              <Caption>집계된 경고가 없어요.</Caption>
            )}
          </details>
        )}
        {artifact && detail ? (
          <>
            <DetailHeader
              eyebrow={`산출물 감사 · ${detail.run_id}`}
              title={artifact.name}
              status={artifactMark(artifact)}
            >
              <Caption>
                {formatRunRange(detail.run_id, detail.window_from, detail.window_to)} · 생성 {formatDateTime(detail.generated_at)}
              </Caption>
            </DetailHeader>
            <div className="workbench-admin-detail-scroll rs-detail-scroll">

              <Section title="산출물 검증">
                <Facts
                  items={[
                    ["회차", <span className="rs-mono" key="run">{detail.run_id}</span>],
                    ["파일", <span className="rs-mono" key="file">{artifact.name}</span>],
                    ["생성 여부", artifact.present ? "생성됨" : "생성 전"],
                    ["스키마 버전", <span className="rs-mono" key="schema">{schemaLabel(artifact)}</span>],
                    ["기대 스키마", <span className="rs-mono" key="expected">{present(artifact.expected_schema_version, "기준 없음")}</span>],
                    ["형식 검증", artifact.valid === null ? "미확인" : artifact.valid ? "통과" : "실패"],
                  ]}
                />
              </Section>

              {artifact.warnings.length > 0 ? (
                <Section title={`검증 경고 ${artifact.warnings.length}건`}>
                  <DataTable
                    caption="산출물 검증 경고"
                    headings={["경고"]}
                    rows={artifact.warnings.map((warning, index) => ({ id: `${artifact.name}-${index}`, cells: [warning] }))}
                  />
                </Section>
              ) : (
                <Caption>{artifact.present ? "기록된 검증 경고가 없어요." : "생성 전이므로 검증 경고를 셀 수 없어요."}</Caption>
              )}

              {activeExecution ? (
                <Note title="이 회차의 판정 실행이 아직 진행 중이에요" tone="warning">
                  실행 <span className="rs-mono">{activeExecution.execution_id}</span>이 {screeningStatusLabel(activeExecution.status)}
                  {" "}상태예요. 지금 산출물은 부분 결과일 수 있으므로 완전한 성공 결과로 발행하지 않아요.
                </Note>
              ) : null}
              {!executionScopeKnown ? (
                <Note title="이 회차와 연결된 실행 상태를 확인하지 못했어요">
                  최종 결과인지 부분 결과인지 이 화면이 단정하지 않아요.
                </Note>
              ) : null}

              <Note title="최종 결과 여부는 파일 이름으로 판단하지 않아요">
                산출물이 최종인지 부분인지는 연결된 실행의 종결 상태로만 확인해요. 이 화면은 파일이 있다는
                사실을 완료로 바꾸지 않아요.
              </Note>

              <Section title="회차 수집 범위">
                <Facts
                  items={[
                    ["기간", formatRunRange(detail.run_id, detail.collection_scope.window_from, detail.collection_scope.window_to)],
                    ["시간대", present(detail.collection_scope.timezone, "시간대 미확인")],
                    ["업무 구분", present(detail.collection_scope.business_area, "업무 구분 미확인")],
                    [
                      "사전규격",
                      detail.collection_scope.pre_spec_available === true
                        ? "수집 가능"
                        : detail.collection_scope.pre_spec_available === false ? "수집되지 않음" : "확인 불가",
                    ],
                    ["사전규격 사유", present(detail.collection_scope.pre_spec_reason, "상태 기록 없음")],
                    ["판정 기준", present(detail.screening_basis, "판정 기준 미기록")],
                  ]}
                />
              </Section>
            </div>
            <DecisionBar
              stateLabel="산출물 검증"
              state={artifactMark(artifact)}
              note="내부 경로와 원문은 표시하지 않아요."
              secondaryActions={<Button label="실행 기록 열기" size="sm" onClick={() => setLogsOpen(true)} />}
              primaryAction={(
                <Button
                  label="수집 실행에서 보기"
                  size="sm"
                  variant="primary"
                  onClick={() => {
                    // 무관한 쿼리를 지우지 않고 회차만 맞춰 옮긴다.
                    const next = new URLSearchParams(searchParams);
                    next.set("run", detail.run_id);
                    navigate({ pathname: "/runs", search: next.toString() });
                  }}
                />
              )}
            />
          </>
        ) : (
          <div className="rs-detail-empty">
            <FileSearch aria-hidden="true" />
            <Text as="p">확인할 산출물을 골라 주세요.</Text>
            <Caption>회차를 고르면 그 회차에 연결된 산출물과 검증 상태를 확인할 수 있어요.</Caption>
          </div>
        )}
      </section>

      <Dialog
        isOpen={logsOpen}
        onOpenChange={(next) => { if (!next) setLogsOpen(false); }}
        purpose="info"
        width={880}
        maxHeight="90dvh"
      >
        <div className="rs-dialog-body" data-astryx-theme="bidops">
          <DialogHeader title={`실행 기록 · ${selectedRunId ?? "회차 미선택"}`} onOpenChange={(next) => { if (!next) setLogsOpen(false); }} />
          <div className="rs-dialog-scroll">
            <ExecutionLog data={logsQuery.data} loading={logsQuery.isLoading} error={logsQuery.error} />
          </div>
          <div className="rs-dialog-actions">
            <Button label="확인" onClick={() => setLogsOpen(false)} />
          </div>
        </div>
      </Dialog>
    </SplitWorkspace>
  );
}
