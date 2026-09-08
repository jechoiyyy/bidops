import { useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import type {
  CompanyProfileSnapshotResponse,
  PolicyVersionResponse,
  ProfileSource,
  ScreeningExecutionResponse,
} from "../../lib/types";
import { formatDateTime } from "../../lib/format";
import { Caption, Facts, Note } from "./RunStatusPrimitives";
import { countLabel, remainingCount } from "./runStatusData";
import { screeningStatusLabel } from "./ScreeningRunPanel";

function profileLabel(snapshot: CompanyProfileSnapshotResponse): string {
  const source = snapshot.source_kind === "working_tree" ? "현재 프로필" : `Git ${snapshot.source_ref ?? "SHA 미확인"}`;
  return `${source} · ${snapshot.version}`;
}

interface JudgmentStartDialogProps {
  open: boolean;
  onClose: () => void;
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
  /** 조회 범위 안에 진행 중인 전량 판정 실행이 있는가. */
  executionBusy: boolean;
  listReady: boolean;
  onRetryConfiguration: () => void;
  onStart: () => void;
  startBusy: boolean;
  actionError: string | null;
}

/**
 * 전량 판정 실행 요청.
 *
 * 시안이 기본 화면에서 뺀 정책·프로필·담당자 전체 양식을 그대로 담는다. 실행에
 * 쓰는 입력(정책 버전 · 프로필 출처 · 담당자)은 요청 순간에 고정되며, 확인
 * 창에서 담당자가 그 조합을 눈으로 대조한 뒤 요청한다.
 */
export function JudgmentStartDialog({
  open,
  onClose,
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
  executionBusy,
  listReady,
  onRetryConfiguration,
  onStart,
  startBusy,
  actionError,
}: JudgmentStartDialogProps) {
  const [discardOpen, setDiscardOpen] = useState(false);
  const selectedPolicy = policies.find((policy) => policy.policy_version === selectedPolicyVersion) ?? null;
  const selectedProfile = profileSnapshots.find((snapshot) => snapshot.version === selectedProfileVersion) ?? null;
  const configurationBroken = Boolean(policiesError || profilesError);
  const submitDisabled = startBusy
    || executionBusy
    || !listReady
    || !actor.trim()
    || !selectedPolicy
    || !selectedProfile
    || !selectedProfileSource
    || configurationBroken
    || policiesLoading
    || profilesLoading;

  useEffect(() => {
    if (!open) setDiscardOpen(false);
  }, [open]);

  const requestClose = () => {
    if (actor.trim()) {
      setDiscardOpen(true);
      return;
    }
    onClose();
  };

  return (
    <Dialog isOpen={open} onOpenChange={(next) => { if (!next) requestClose(); }} purpose="form" width={640} maxHeight="90dvh">
      <div className="rs-dialog-body" data-astryx-theme="bidops">
        <DialogHeader
          title={discardOpen ? "작성 중인 입력을 닫을까요?" : "전량 판정 실행 요청"}
          onOpenChange={(next) => { if (!next) requestClose(); }}
        />
        {discardOpen ? (
          <>
            <Text as="p">아직 요청하지 않은 담당자 입력이 있습니다. 닫으면 입력한 이름이 사라집니다.</Text>
            <div className="rs-dialog-actions">
              <Button label="계속 작성" onClick={() => setDiscardOpen(false)} />
              <Button label="입력 버리고 닫기" onClick={() => { setDiscardOpen(false); onActorChange(""); onClose(); }} />
            </div>
          </>
        ) : (
          <>
            <div className="rs-dialog-scroll">
              <Caption>
                원본 회차 <span className="rs-mono">{runId}</span>의 후보를 고정된 정책·프로필 조합으로 판정하고
                새 파생 회차로 게시합니다. 원본 회차의 수집·기존 판정은 덮어쓰지 않습니다.
              </Caption>

              <div className="rs-form-grid">
                <label className="rs-field">
                  <span>판정 정책 <em>필수</em></span>
                  <select
                    value={selectedPolicyVersion}
                    onChange={(event) => onPolicyChange(event.target.value)}
                    disabled={!policies.length || startBusy}
                    required
                  >
                    {!policies.length ? <option value="">선택 가능한 정책 없음</option> : null}
                    {policies.map((policy) => (
                      <option value={policy.policy_version} key={policy.policy_version}>
                        {policy.policy_version} · {policy.status === "active" ? "active" : "activation candidate"}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="rs-field">
                  <span>프로필 사본 <em>필수</em></span>
                  <select
                    value={selectedProfileVersion}
                    onChange={(event) => onProfileChange(event.target.value)}
                    disabled={!profileSnapshots.length || startBusy}
                    required
                  >
                    {!profileSnapshots.length ? <option value="">선택 가능한 사본 없음</option> : null}
                    {profileSnapshots.map((snapshot) => (
                      <option value={snapshot.version} key={snapshot.version}>{profileLabel(snapshot)}</option>
                    ))}
                  </select>
                </label>
              </div>

              <label className="rs-field">
                <span>담당자 이름 <em>필수</em></span>
                <input
                  value={actor}
                  onChange={(event) => onActorChange(event.target.value)}
                  placeholder="예: 홍길동"
                  autoComplete="name"
                  disabled={startBusy}
                  required
                />
                <small>실행·중지 감사 기록에 사용됩니다. 인증이나 권한을 대신하지 않습니다.</small>
              </label>

              {policiesLoading || profilesLoading ? (
                <Caption>정책과 프로필 사본을 불러오는 중입니다.</Caption>
              ) : null}
              {configurationBroken ? (
                <div className="rs-inline-error" role="alert">
                  <Text as="span">판정 실행 설정을 불러오지 못했습니다.</Text>
                  <Button label="다시 시도" size="sm" onClick={onRetryConfiguration} />
                </div>
              ) : null}
              {!configurationBroken && !policiesLoading && !profilesLoading && (policies.length === 0 || profileSnapshots.length === 0) ? (
                <Note title="실행 가능한 설정이 없습니다" tone="warning">
                  {policies.length === 0
                    ? "activation candidate 또는 active 정책이 필요합니다."
                    : "사용할 수 있는 프로필 사본이 필요합니다."}
                </Note>
              ) : null}

              {selectedPolicy && selectedProfile ? (
                <Facts
                  items={[
                    ["정책", <span className="rs-mono" key="p">{selectedPolicy.policy_version}</span>],
                    ["정책 상태", selectedPolicy.status === "active" ? "active" : "activation candidate"],
                    ["정책 식별 해시", <span className="rs-mono" key="pd">{selectedPolicy.content_digest}</span>],
                    ["프로필 출처", selectedProfile.source_kind === "working_tree" ? "현재 프로필" : `Git blob ${selectedProfile.source_ref ?? "SHA 미확인"}`],
                    ["프로필 version", <span className="rs-mono" key="pv">{selectedProfile.version}</span>],
                    ["프로필 식별 해시", <span className="rs-mono" key="pdg">{selectedProfile.digest}</span>],
                    ["사본 생성", formatDateTime(selectedProfile.created_at)],
                  ]}
                />
              ) : null}

              <Note title="이 실행의 입력은 요청 시점에 고정됩니다">
                이후 판정 기준이 바뀌어도 이미 시작한 실행에 소급 적용하지 않습니다.
              </Note>
              {executionBusy ? (
                <Note title="이미 진행 중인 전량 판정 실행이 있습니다" tone="warning">
                  진행 중인 실행이 종결된 뒤에 새 실행을 요청할 수 있습니다.
                </Note>
              ) : null}
              {!listReady ? (
                <Note title="현재 회차의 판정 실행 목록을 확인하는 중입니다" tone="warning">
                  목록을 확인하기 전에는 중복 실행을 막을 수 없어 요청하지 않습니다.
                </Note>
              ) : null}
              {actionError ? <Text className="rs-dialog-error" as="p" role="alert">{actionError}</Text> : null}
            </div>
            <div className="rs-dialog-actions">
              <Button label="취소" onClick={requestClose} />
              <Button
                label={startBusy ? "실행 요청 중…" : "전량 판정 실행 요청"}
                variant="primary"
                isDisabled={submitDisabled}
                onClick={onStart}
              />
            </div>
          </>
        )}
      </div>
    </Dialog>
  );
}

interface JudgmentStopDialogProps {
  open: boolean;
  onClose: () => void;
  runId: string;
  /** 확인 창이 열릴 때 고정된 대상. 뒤에서 목록이 바뀌어도 대상이 바뀌지 않는다. */
  target: ScreeningExecutionResponse | null;
  actor: string;
  onActorChange: (value: string) => void;
  stopBusy: boolean;
  actionError: string | null;
  onConfirm: () => void;
}

/**
 * 중지 확인. 대상 실행과 담당자를 고정해 보여 준 뒤 기존 중단 API로 요청한다.
 * 409 같은 충돌이 나면 창을 닫지 않고 입력을 유지해 다시 시도할 수 있게 한다.
 */
export function JudgmentStopDialog({
  open,
  onClose,
  runId,
  target,
  actor,
  onActorChange,
  stopBusy,
  actionError,
  onConfirm,
}: JudgmentStopDialogProps) {
  const terminalOrStopping = !target
    || target.status === "성공"
    || target.status === "부분 성공"
    || target.status === "실패"
    || target.status === "중단됨"
    || target.status === "중지 요청";

  return (
    <Dialog isOpen={open} onOpenChange={(next) => { if (!next && !stopBusy) onClose(); }} purpose="form" width={620} maxHeight="90dvh">
      <div className="rs-dialog-body" data-astryx-theme="bidops">
        <DialogHeader title="판정 실행 중지" onOpenChange={(next) => { if (!next && !stopBusy) onClose(); }} />
        <div className="rs-dialog-scroll">
          {target ? (
            <Facts
              items={[
                ["원본 회차", <span className="rs-mono" key="run">{runId}</span>],
                ["대상 실행", <span className="rs-mono" key="exec">{target.execution_id}</span>],
                ["현재 상태", screeningStatusLabel(target.status)],
                ["완료", countLabel(target.completed_count)],
                ["실패", countLabel(target.failure_count)],
                ["남은 대상", countLabel(remainingCount(target))],
              ]}
            />
          ) : (
            <Note title="중지할 실행을 확인할 수 없습니다" tone="warning">
              실행 목록을 다시 확인한 뒤 요청해 주세요.
            </Note>
          )}
          <Note title="협력적으로 중지합니다" tone="warning">
            현재 모델 호출이 끝나면 다음 공고를 시작하지 않고 <strong>중단됨</strong>으로 남습니다. 이미 완료된
            결과와 실패 기록은 삭제되지 않으며 자동으로 다시 시작하지 않습니다.
          </Note>
          <label className="rs-field">
            <span>중지 담당자 <em>필수</em></span>
            <input
              value={actor}
              onChange={(event) => onActorChange(event.target.value)}
              placeholder="담당자 이름"
              autoComplete="name"
              disabled={stopBusy}
              required
            />
            <small>중지 요청 감사 기록에 남는 이름입니다.</small>
          </label>
          {terminalOrStopping && target ? (
            <Note title="이 실행은 더 이상 중지할 수 없습니다">
              이미 종결됐거나 중지 요청이 기록된 실행입니다. 상태를 되돌리지 않습니다.
            </Note>
          ) : null}
          {actionError ? <Text className="rs-dialog-error" as="p" role="alert">{actionError}</Text> : null}
        </div>
        <div className="rs-dialog-actions">
          <Button label="계속 실행" isDisabled={stopBusy} onClick={onClose} />
          <Button
            label={stopBusy ? "중지 요청 중…" : "중지 요청"}
            variant="destructive"
            isDisabled={stopBusy || terminalOrStopping || !actor.trim()}
            onClick={onConfirm}
          />
        </div>
      </div>
    </Dialog>
  );
}
