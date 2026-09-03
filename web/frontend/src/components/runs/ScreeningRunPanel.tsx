import { useEffect, useRef, useState, type MouseEvent } from "react";
import type {
  CompanyProfileSnapshotResponse,
  PolicyVersionResponse,
  ProfileSource,
  ScreeningExecutionDetailResponse,
  ScreeningExecutionResponse,
  ScreeningStatus,
} from "../../lib/types";
import { formatDateTime, formatNumber, present } from "../../lib/format";

interface ScreeningRunPanelProps {
  runId: string;
  actor: string;
  onActorChange: (value: string) => void;
  policies: PolicyVersionResponse[];
  policiesLoading: boolean;
  policiesError: unknown;
  selectedPolicyVersion: string;
  onPolicyChange: (value: string) => void;
  profileSnapshots: CompanyProfileSnapshotResponse[];
  profilesLoading: boolean;
  profilesError: unknown;
  selectedProfileVersion: string;
  onProfileChange: (value: string) => void;
  selectedProfileSource: ProfileSource | null;
  execution: ScreeningExecutionDetailResponse | null;
  executionSummary: ScreeningExecutionResponse | null;
  executionLoading: boolean;
  executionError: unknown;
  listLoading: boolean;
  listError: unknown;
  listReady: boolean;
  listRefreshing: boolean;
  onRetryConfiguration: () => void;
  onStart: () => void;
  startBusy: boolean;
  actionError: string | null;
  onStop: () => void;
  stopBusy: boolean;
  onOpenPublishedRun: (runId: string) => void;
  publishedRunNavigationBusy: boolean;
  publishedRunNavigationError: string | null;
}

const statusMeta: Record<ScreeningStatus, { label: string; tone: string }> = {
  대기: { label: "대기 중", tone: "queued" },
  "실행 중": { label: "진행 중", tone: "running" },
  "중지 요청": { label: "중지 요청됨", tone: "stopping" },
  성공: { label: "성공", tone: "success" },
  "부분 성공": { label: "부분 성공", tone: "partial" },
  실패: { label: "실패", tone: "failure" },
  "중단됨": { label: "중단됨", tone: "interrupted" },
};

const stageLabels: Record<string, string> = {
  "기술 적합성": "기술 적합성",
  "실적 정합성": "실적 정합성",
  "공공 SI 적합성": "공공 SI 적합성",
  "사업성·자격 제약": "사업성·자격 제약",
  "전략 부합": "전략 부합",
  counterargument: "반론 검토",
  synthesis: "종합 판정",
  merge: "병합·검증",
  publish: "파생 회차 게시",
};

const artifactLabels: Array<{ key: "decisions" | "failures" | "telemetry" | "screening_result"; label: string }> = [
  { key: "decisions", label: "판정 결과" },
  { key: "failures", label: "실패 목록" },
  { key: "telemetry", label: "실행 관측" },
  { key: "screening_result", label: "통합 결과" },
];

function isTerminal(status: ScreeningStatus | undefined): boolean {
  return status === "성공" || status === "부분 성공" || status === "실패" || status === "중단됨";
}

function isManualFullRun(execution: ScreeningExecutionResponse): boolean {
  return execution.trigger === "manual_run" && execution.scope === "full_run";
}

function statusFor(status: ScreeningStatus | undefined): { label: string; tone: string } {
  if (status && status in statusMeta) return statusMeta[status];
  return { label: "상태 미확인", tone: "unknown" };
}

function profileLabel(snapshot: CompanyProfileSnapshotResponse): string {
  const source = snapshot.source_kind === "working_tree"
    ? "현재 프로필"
    : `Git ${snapshot.source_ref ?? "SHA 미확인"}`;
  return `${source} · ${snapshot.version}`;
}

function digestLabel(value: string): string {
  if (value.length <= 18) return value;
  return `${value.slice(0, 10)}…${value.slice(-6)}`;
}

function safeErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? `${fallback}` : fallback;
}

function ScreeningStatusBadge({ status }: { status: ScreeningStatus | undefined }) {
  const meta = statusFor(status);
  return (
    <span className={`runs-screening-status runs-screening-status-${meta.tone}`} aria-label={`판정 실행 상태: ${meta.label}`}>
      {meta.label}
    </span>
  );
}

function ExecutionProgress({ execution }: { execution: ScreeningExecutionResponse }) {
  const candidate = Math.max(0, execution.candidate_count);
  const completed = Math.max(0, execution.completed_count);
  const failures = Math.max(0, execution.failure_count);
  const percent = candidate > 0 ? Math.min(100, Math.max(0, Math.round((completed / candidate) * 100))) : null;
  const currentStage = execution.current_stage ? stageLabels[execution.current_stage] ?? "단계 미확인" : "대기 중";
  const queuePosition = execution.status === "대기" && execution.queue_position !== null
    ? execution.queue_position
    : null;

  return (
    <div className="runs-screening-progress" aria-live="polite">
      <div className="runs-screening-progress-heading">
        <strong>전량 판정 진행</strong>
        <span>{percent === null ? "진행률 계산 불가" : `${percent}%`}</span>
      </div>
      <div className="runs-screening-progress-track" role="progressbar" aria-label="전량 판정 진행률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent === null ? undefined : percent}>
        <span style={{ width: `${percent ?? 0}%` }} />
      </div>
      <div className="runs-screening-progress-grid">
        <div><span>대기 순번</span><strong>{queuePosition === null ? "-" : formatNumber(queuePosition)}</strong></div>
        <div><span>현재 단계</span><strong>{currentStage}</strong></div>
        <div><span>후보</span><strong>{formatNumber(candidate)}건</strong></div>
        <div><span>완료</span><strong>{formatNumber(completed)}건</strong></div>
        <div><span>실패</span><strong>{formatNumber(failures)}건</strong></div>
        <div><span>현재 공고</span><strong className="mono">{present(execution.current_notice_id, "없음")}</strong></div>
      </div>
    </div>
  );
}

function ConfigurationState({
  policies,
  policiesLoading,
  policiesError,
  profileSnapshots,
  profilesLoading,
  profilesError,
  onRetry,
}: Pick<ScreeningRunPanelProps, "policies" | "policiesLoading" | "policiesError" | "profileSnapshots" | "profilesLoading" | "profilesError"> & { onRetry: () => void }) {
  if (policiesLoading || profilesLoading) {
    return <p className="runs-screening-muted" role="status" aria-live="polite">정책과 프로필 snapshot을 불러오는 중입니다.</p>;
  }
  if (policiesError || profilesError) {
    return (
      <div className="runs-screening-inline-error" role="alert">
        <span>{safeErrorMessage(policiesError ?? profilesError, "판정 실행 설정을 불러오지 못했습니다.")}</span>
        <button className="runs-screening-text-button" type="button" onClick={onRetry}>다시 시도</button>
      </div>
    );
  }
  if (policies.length === 0 || profileSnapshots.length === 0) {
    return (
      <div className="runs-screening-empty" role="status">
        <strong>실행 가능한 설정이 없습니다.</strong>
        <p>{policies.length === 0 ? "activation candidate 또는 active 정책이 필요합니다." : "사용할 수 있는 프로필 snapshot이 필요합니다."}</p>
      </div>
    );
  }
  return null;
}

export function ScreeningRunPanel({
  runId,
  actor,
  onActorChange,
  policies,
  policiesLoading,
  policiesError,
  selectedPolicyVersion,
  onPolicyChange,
  profileSnapshots,
  profilesLoading,
  profilesError,
  selectedProfileVersion,
  onProfileChange,
  selectedProfileSource,
  execution,
  executionSummary,
  executionLoading,
  executionError,
  listLoading,
  listError,
  listReady,
  listRefreshing,
  onRetryConfiguration,
  onStart,
  startBusy,
  actionError,
  onStop,
  stopBusy,
  onOpenPublishedRun,
  publishedRunNavigationBusy,
  publishedRunNavigationError,
}: ScreeningRunPanelProps) {
  const [stopDialogOpen, setStopDialogOpen] = useState(false);
  const stopDialogRef = useRef<HTMLDialogElement>(null);
  const stopOpenerRef = useRef<HTMLButtonElement>(null);
  const stopCancelRef = useRef<HTMLButtonElement>(null);
  const selectedPolicy = policies.find((policy) => policy.policy_version === selectedPolicyVersion) ?? null;
  const selectedProfile = profileSnapshots.find((snapshot) => snapshot.version === selectedProfileVersion) ?? null;
  const detailExecution = execution && isManualFullRun(execution) ? execution : null;
  const summaryExecution = executionSummary && isManualFullRun(executionSummary) ? executionSummary : null;
  const currentExecution = detailExecution ?? summaryExecution;
  const currentStatus = currentExecution?.status;
  const stopDisabled = !currentExecution || isTerminal(currentStatus) || currentStatus === "중지 요청" || !actor.trim() || stopBusy;
  const executionBusy = Boolean(currentExecution && !isTerminal(currentStatus));
  const executionListUnavailable = listLoading || Boolean(listError) || !listReady;
  const startDisabled = startBusy || executionBusy || executionListUnavailable || !actor.trim() || !selectedPolicy || !selectedProfile || !selectedProfileSource || Boolean(policiesError || profilesError) || policiesLoading || profilesLoading;

  useEffect(() => {
    const dialog = stopDialogRef.current;
    if (!dialog) return undefined;
    if (stopDialogOpen) {
      if (!dialog.open) dialog.showModal();
      window.requestAnimationFrame(() => stopCancelRef.current?.focus());
    } else if (dialog.open) {
      dialog.close();
    }
    return () => {
      if (dialog.open) dialog.close();
    };
  }, [stopDialogOpen]);

  const closeStopDialog = () => {
    if (stopDialogRef.current?.open) stopDialogRef.current.close();
    setStopDialogOpen(false);
    window.requestAnimationFrame(() => stopOpenerRef.current?.focus());
  };

  const openStopDialog = (event: MouseEvent<HTMLButtonElement>) => {
    if (stopDisabled) return;
    stopOpenerRef.current = event.currentTarget;
    setStopDialogOpen(true);
  };

  const confirmStop = () => {
    const latestStatus = detailExecution?.status ?? summaryExecution?.status;
    if (!currentExecution || !latestStatus || isTerminal(latestStatus) || latestStatus === "중지 요청" || stopBusy || !actor.trim()) {
      closeStopDialog();
      return;
    }
    closeStopDialog();
    onStop();
  };

  return (
    <section className="runs-screening-panel" aria-labelledby="runs-screening-title">
      <div className="runs-screening-header">
        <div>
          <span className="runs-eyebrow">전량 판정</span>
          <h3 id="runs-screening-title">전체 후보 판정 실행</h3>
          <p>선택한 원본 회차의 후보를 고정된 정책·프로필 조합으로 판정하고 새 파생 회차로 게시합니다.</p>
        </div>
        {currentExecution ? <ScreeningStatusBadge status={currentStatus} /> : <span className="runs-screening-status runs-screening-status-idle">실행 기록 없음</span>}
      </div>

      <div className="runs-screening-source-note">
        <strong>원본 회차</strong>
        <code>{runId}</code>
        <span>이 회차의 수집·기존 판정은 덮어쓰지 않습니다.</span>
      </div>

      <form className="runs-screening-form" onSubmit={(event) => { event.preventDefault(); onStart(); }}>
        <div className="runs-screening-form-grid">
          <label className="runs-screening-field">
            <span>담당자 이름 <em>필수</em></span>
            <input value={actor} onChange={(event) => onActorChange(event.target.value)} placeholder="예: 홍길동" autoComplete="name" required aria-describedby="runs-screening-actor-help" />
            <small id="runs-screening-actor-help">실행·중지 감사 기록에 사용됩니다. 인증이나 권한을 대신하지 않습니다.</small>
          </label>
          <label className="runs-screening-field">
            <span>판정 정책 <em>필수</em></span>
            <select value={selectedPolicyVersion} onChange={(event) => onPolicyChange(event.target.value)} required disabled={!policies.length}>
              {!policies.length ? <option value="">선택 가능한 정책 없음</option> : null}
              {policies.map((policy) => <option value={policy.policy_version} key={policy.policy_version}>{policy.policy_version} · {policy.status === "active" ? "active" : "activation candidate"}</option>)}
            </select>
          </label>
          <label className="runs-screening-field">
            <span>프로필 snapshot <em>필수</em></span>
            <select value={selectedProfileVersion} onChange={(event) => onProfileChange(event.target.value)} required disabled={!profileSnapshots.length}>
              {!profileSnapshots.length ? <option value="">선택 가능한 snapshot 없음</option> : null}
              {profileSnapshots.map((snapshot) => <option value={snapshot.version} key={snapshot.version}>{profileLabel(snapshot)}</option>)}
            </select>
          </label>
        </div>

        <ConfigurationState
          policies={policies}
          policiesLoading={policiesLoading}
          policiesError={policiesError}
          profileSnapshots={profileSnapshots}
          profilesLoading={profilesLoading}
          profilesError={profilesError}
          onRetry={onRetryConfiguration}
        />

        {selectedPolicy && selectedProfile ? (
          <dl className="runs-screening-selection" aria-label="판정 실행에 사용할 고정 입력">
            <div><dt>정책</dt><dd><strong>{selectedPolicy.policy_version}</strong><span>{selectedPolicy.status === "active" ? "active" : "activation candidate"} · digest {digestLabel(selectedPolicy.content_digest)}</span></dd></div>
            <div><dt>프로필 출처</dt><dd><strong>{selectedProfile.source_kind === "working_tree" ? "현재 프로필" : "Git blob"}</strong><span>{selectedProfile.source_kind === "git_blob" && selectedProfile.source_ref ? `${selectedProfile.source_ref} · ` : ""}version {selectedProfile.version}</span></dd></div>
            <div><dt>프로필 digest</dt><dd><code>{digestLabel(selectedProfile.digest)}</code><span>생성 {formatDateTime(selectedProfile.created_at)}</span></dd></div>
          </dl>
        ) : null}

        <div className="runs-screening-form-actions">
          <button className="runs-primary-button runs-screening-start-button" type="submit" disabled={startDisabled}>
            {startBusy ? "실행 요청 중…" : "전량 판정 대기열에 넣기"}
          </button>
          {startDisabled && !startBusy ? <span className="runs-screening-required-note">{executionListUnavailable ? "현재 회차의 판정 실행 목록을 확인할 때까지 실행할 수 없습니다." : executionBusy ? "진행 중인 전량 판정 실행이 있어 새 실행을 시작할 수 없습니다." : "담당자·정책·프로필을 모두 선택해야 실행할 수 있습니다."}</span> : null}
        </div>
      </form>

      {actionError ? <p className="runs-screening-error" role="alert">{actionError}</p> : null}
      {listLoading ? <p className="runs-screening-muted" role="status" aria-live="polite">판정 실행 기록을 불러오는 중입니다. 목록 확인 전에는 새 실행을 시작할 수 없습니다.</p> : null}
      {listError ? (
        <div className="runs-screening-inline-error" role="alert" aria-live="assertive" aria-busy={listRefreshing} tabIndex={-1}>
          <span>판정 실행 기록을 불러오지 못했습니다. 목록을 다시 확인한 뒤 실행해 주세요.</span>
          <button className="runs-screening-text-button" type="button" onClick={onRetryConfiguration} disabled={listRefreshing}>
            {listRefreshing ? "다시 확인 중…" : "다시 시도"}
          </button>
        </div>
      ) : null}
      {executionLoading && currentExecution ? <p className="runs-screening-muted" role="status" aria-live="polite">실행 상세를 갱신하는 중입니다.</p> : null}
      {executionError && currentExecution ? <p className="runs-screening-error" role="alert">실행 상세를 갱신하지 못했습니다. 자동 갱신을 계속 시도합니다.</p> : null}

      {currentExecution ? (
        <div className="runs-screening-execution" aria-label="판정 실행 상태">
          <div className="runs-screening-execution-heading">
            <div><span>실행 ID</span><code>{currentExecution.execution_id}</code></div>
            <time dateTime={currentExecution.queued_at}>대기열 등록 {formatDateTime(currentExecution.queued_at)}</time>
          </div>
          <ExecutionProgress execution={currentExecution} />
          {currentExecution.status === "중지 요청" ? <p className="runs-screening-stop-note" role="status" aria-live="polite">중지 요청을 기록했습니다. 현재 모델 호출이 끝난 뒤 다음 공고를 시작하지 않고 중단됩니다.</p> : null}
          {!isTerminal(currentExecution.status) ? (
            <div className="runs-screening-stop-area">
              <button className="runs-secondary-button runs-screening-stop-button" type="button" disabled={stopDisabled} onClick={openStopDialog} aria-haspopup="dialog">
                {stopBusy || currentExecution.status === "중지 요청" ? "중지 요청 처리 중…" : "협력적으로 중지"}
              </button>
              {!actor.trim() ? <span>중지를 요청하려면 담당자 이름을 입력하세요.</span> : <span>현재 호출이 끝나는 지점에서 안전하게 멈춥니다.</span>}
            </div>
          ) : null}
          {isTerminal(currentExecution.status) ? <p className="runs-screening-terminal-note">종결된 실행은 다시 중지하거나 상태를 되돌릴 수 없습니다.</p> : null}

          {currentExecution.published_run_id ? (
            <div className="runs-screening-derived-run">
              <div><strong>게시된 파생 회차</strong><span>원본 회차 <code>{runId}</code>는 유지되며, 아래 회차에 새 판정 결과가 게시되었습니다.</span></div>
              <button className="runs-screening-text-button" type="button" disabled={publishedRunNavigationBusy} onClick={() => onOpenPublishedRun(currentExecution.published_run_id as string)} aria-busy={publishedRunNavigationBusy}>
                {publishedRunNavigationBusy ? "파생 회차 확인 중…" : "파생 회차 보기"} <code>{currentExecution.published_run_id}</code>
              </button>
            </div>
          ) : null}
          {publishedRunNavigationError && currentExecution.published_run_id ? (
            <div className="runs-screening-inline-error" role="alert" aria-live="assertive">
              <span>{publishedRunNavigationError}</span>
              <button className="runs-screening-text-button" type="button" onClick={() => onOpenPublishedRun(currentExecution.published_run_id as string)} disabled={publishedRunNavigationBusy}>
                {publishedRunNavigationBusy ? "다시 확인 중…" : "다시 시도"}
              </button>
            </div>
          ) : null}
          {detailExecution?.result_urls.published_run ? <a className="runs-screening-published-link" href={detailExecution.result_urls.published_run} target="_blank" rel="noreferrer">게시 결과 링크 열기</a> : null}

          {detailExecution ? (
            <>
              <div className="runs-screening-artifacts">
                <h4>안전한 산출물 링크</h4>
                <div className="runs-screening-artifact-links">
                  {artifactLabels.map(({ key, label }) => detailExecution.result_urls[key] ? <a href={detailExecution.result_urls[key] as string} key={key} target="_blank" rel="noreferrer">{label}</a> : null)}
                  {!artifactLabels.some(({ key }) => Boolean(detailExecution.result_urls[key])) ? <span className="runs-screening-muted">사용 가능한 산출물 링크가 없습니다.</span> : null}
                </div>
              </div>
              {detailExecution.failure_count > 0 ? (
                <div className="runs-screening-failures">
                  <h4>사람 검토 대기 실패 목록 <span>{detailExecution.failure_count}건</span></h4>
                  {detailExecution.failures.length ? (
                    <ul>
                      {detailExecution.failures.map((failure) => <li key={`${failure.notice_id}-${failure.failed_stage}`}><div><code>{failure.notice_id}</code><strong>{failure.failed_stage}</strong><span>{failure.failure_type}</span></div><p>{failure.error_summary}</p></li>)}
                    </ul>
                  ) : <p className="runs-screening-muted">실패 건수는 기록되었지만 세부 목록을 아직 불러오지 못했습니다.</p>}
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}

      <dialog ref={stopDialogRef} className="runs-screening-stop-dialog" onCancel={(event) => { event.preventDefault(); closeStopDialog(); }} aria-labelledby="runs-screening-stop-title">
        <div className="runs-screening-dialog-body">
          <h4 id="runs-screening-stop-title">판정 실행을 중지할까요?</h4>
          <p>중지는 협력적으로 처리됩니다. 현재 모델 호출이 끝나면 다음 공고를 시작하지 않고 <strong>중단됨</strong>으로 남습니다. 이미 완료된 결과는 삭제되지 않습니다.</p>
          <form method="dialog" className="runs-screening-dialog-actions" onSubmit={(event) => { event.preventDefault(); confirmStop(); }}>
            <button ref={stopCancelRef} className="runs-secondary-button" type="button" onClick={closeStopDialog}>계속 실행</button>
            <button className="runs-primary-button runs-screening-danger-button" type="submit">중지 요청</button>
          </form>
        </div>
      </dialog>
    </section>
  );
}
