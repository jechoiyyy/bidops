import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../ui/alert-dialog";
import { Caption, DataTable, Facts, Note, Section, StatusToken } from "../runs/RunStatusPrimitives";
import type { AlwaysOnSwitchResponse, PolicyVersionResponse } from "../../lib/types";

/**
 * 상시 운영 활성화 조건.
 *
 * 설정값 · 실제 운영 · 환경 허용 · 서버 거절 사유를 각각 구분해 보여 준다.
 * 차단 사유는 화면이 만들지 않고 서버가 준 값과 active 정책 대조 결과에서만
 * 나온다. 켜기는 담당자와 quality gate evaluation ID를 확인 창에서 다시
 * 확인해야 한다.
 */

function enabledLabel(value: boolean): string {
  return value ? "켜짐" : "꺼짐";
}

function valueLabel(value: string | null | undefined): string {
  return value && value.trim() ? value : "값 없음";
}

function isPresent(value: string | null | undefined): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/** 담당자가 눈으로 대조하는 값이므로 줄이지 않는다. 줄바꿈은 CSS가 처리한다. */
function identifierText(value: string | null | undefined): string {
  return value?.trim() || "값 없음";
}

function DigestValue({ value, className = "" }: { value: string | null | undefined; className?: string }) {
  return <span className={`operations-digest-value mono ${className}`.trim()}>{identifierText(value)}</span>;
}

type BindingMatch = "match" | "mismatch" | "unknown";

function bindingMatchLabel(status: BindingMatch): string {
  if (status === "match") return "active와 일치";
  if (status === "mismatch") return "active와 다름";
  return "비교 원본 없음";
}

function BindingStatus({ status, label }: { status: BindingMatch; label?: string }) {
  return <StatusToken label={label ?? bindingMatchLabel(status)} />;
}

export interface StructuralBlocker {
  key: string;
  message: string;
  detail?: string;
  href?: string;
  linkLabel?: string;
}

export interface ActivationView {
  blockers: StructuralBlocker[];
  canEnable: boolean;
  policyVersionStatus: BindingMatch;
  policyGateStatus: BindingMatch;
  policyPromptStatus: BindingMatch;
  policyDigest: string | null;
  gateId: string | null;
  hasRejection: boolean;
}

/**
 * 켜기를 막는 구조적 조건. 확인 창에서 입력하는 두 값(담당자·게이트 ID)은
 * 여기 포함하지 않는다. 없는 차단 사유를 만들지 않는다.
 */
export function computeActivation(
  state: AlwaysOnSwitchResponse,
  activePolicy: PolicyVersionResponse | null,
  activePolicyVersion: string | null,
  policyLoading: boolean,
  policyRefreshing: boolean,
): ActivationView {
  const gateId = state.quality_gate_result_id;
  const metadataFields: Array<readonly [string | null | undefined, string]> = [
    [state.quality_gate_result_id, "quality gate evaluation"],
    [state.policy_version, "정책 버전"],
    [state.model_name, "모델 tag"],
    [state.model_digest, "모델 식별 해시"],
    [state.prompt_version, "prompt version"],
    [state.company_profile_version, "프로필 version"],
    [state.company_profile_digest, "프로필 식별 해시"],
    [activePolicy?.quality_gate_result_id ?? null, "active 정책의 게이트 연결"],
    [activePolicy?.prompt_version ?? null, "active 정책의 prompt version"],
    [activePolicy?.content_digest ?? null, "활성 정책 식별 해시"],
  ];
  const missingMetadata = metadataFields.filter(([value]) => !isPresent(value)).map(([, label]) => label);
  const metadataComplete = missingMetadata.length === 0;

  const policyVersionStatus: BindingMatch = activePolicy && isPresent(activePolicyVersion) && isPresent(state.policy_version)
    ? activePolicy.policy_version === activePolicyVersion && state.policy_version === activePolicyVersion ? "match" : "mismatch"
    : "unknown";
  const policyGateStatus: BindingMatch = activePolicy && isPresent(activePolicy.quality_gate_result_id) && isPresent(gateId)
    ? activePolicy.quality_gate_result_id === gateId ? "match" : "mismatch"
    : "unknown";
  const policyPromptStatus: BindingMatch = activePolicy && isPresent(activePolicy.prompt_version) && isPresent(state.prompt_version)
    ? activePolicy.prompt_version === state.prompt_version ? "match" : "mismatch"
    : "unknown";
  const policyMatches = Boolean(
    !policyLoading
      && !policyRefreshing
      && policyVersionStatus === "match"
      && policyGateStatus === "match"
      && policyPromptStatus === "match"
      && isPresent(activePolicy?.content_digest),
  );
  const hasRejection = isPresent(state.rejection_reason);

  const blockers: StructuralBlocker[] = [];
  if (!state.environment_enabled) {
    blockers.push({
      key: "environment",
      message: "환경 안전 상한이 꺼져 있습니다.",
      detail: "BIDOPS_SCHEDULER_ENABLED 설정을 확인하십시오.",
    });
  }
  if (hasRejection) {
    blockers.push({
      key: "rejection",
      message: "서버가 현재 승인 조합을 거부했습니다.",
      detail: state.rejection_reason ?? undefined,
      href: "/quality-gates",
      linkLabel: "게이트 확인",
    });
  }
  if (state.quality_gate_status !== "통과" || !gateId) {
    blockers.push({
      key: "quality-gate",
      message: "운영 승인 quality gate가 통과 상태가 아니거나 결과 ID가 없습니다.",
      detail: `현재 상태 ${valueLabel(state.quality_gate_status)} · 결과 ID ${valueLabel(gateId)}`,
      href: "/quality-gates",
      linkLabel: "quality gate 열기",
    });
  }
  if (policyLoading || policyRefreshing) {
    blockers.push({
      key: "policy-loading",
      message: "현재 active 정책을 확인하는 중입니다.",
      detail: "확인이 끝날 때까지 승인 조합을 변경할 수 없습니다.",
      href: "/policies",
      linkLabel: "정책 확인",
    });
  } else if (!activePolicy) {
    blockers.push({
      key: "active-policy",
      message: "현재 active 정책을 확인할 수 없습니다.",
      href: "/policies",
      linkLabel: "정책 확인",
    });
  } else {
    if (policyVersionStatus !== "match") {
      blockers.push({
        key: "policy-version",
        message: "active 정책 버전과 승인 조합의 정책 버전이 다릅니다.",
        detail: `active ${valueLabel(activePolicyVersion)} · 승인 조합 ${valueLabel(state.policy_version)}`,
        href: "/policies",
        linkLabel: "정책 열기",
      });
    }
    if (policyGateStatus !== "match") {
      blockers.push({
        key: "policy-gate",
        message: "active 정책의 quality gate evaluation ID가 승인 조합과 다릅니다.",
        detail: `active ${valueLabel(activePolicy.quality_gate_result_id)} · 승인 조합 ${valueLabel(gateId)}`,
        href: "/quality-gates",
        linkLabel: "게이트 확인",
      });
    }
    if (policyPromptStatus !== "match") {
      blockers.push({
        key: "policy-prompt",
        message: "active 정책의 prompt version이 승인 조합과 다릅니다.",
        detail: `active ${valueLabel(activePolicy.prompt_version)} · 승인 조합 ${valueLabel(state.prompt_version)}`,
        href: "/policies",
        linkLabel: "정책 열기",
      });
    }
    if (!isPresent(activePolicy.content_digest)) {
      blockers.push({
        key: "policy-digest",
        message: "활성 정책 식별 해시가 없습니다.",
        href: "/policies",
        linkLabel: "정책 열기",
      });
    }
    if (!metadataComplete) {
      blockers.push({
        key: "metadata",
        message: "승인 조합 메타데이터가 모두 확인되지 않았습니다.",
        detail: `확인 필요: ${missingMetadata.join(" · ")}`,
        href: "/quality-gates",
        linkLabel: "승인 조합 확인",
      });
    }
  }

  // 결합 규칙이 바뀌었는데 위의 개별 메시지가 따라오지 못한 경우를 위한 방어.
  const hasPolicyBindingBlocker = blockers.some(({ key }) =>
    ["policy-loading", "active-policy", "policy-version", "policy-gate", "policy-prompt", "policy-digest", "metadata"].includes(key));
  if (!policyMatches && !hasPolicyBindingBlocker) {
    blockers.push({
      key: "policy-binding",
      message: "active 정책과 승인 조합의 연결 상태를 확인할 수 없습니다.",
      href: "/policies",
      linkLabel: "정책 확인",
    });
  }

  return {
    blockers,
    canEnable: policyMatches && blockers.length === 0,
    policyVersionStatus,
    policyGateStatus,
    policyPromptStatus,
    policyDigest: activePolicy?.content_digest ?? null,
    gateId,
    hasRejection,
  };
}

/** 활성화 조건 pane의 본문. */
export function ActivationPaneBody({
  state,
  view,
  policyLoading,
  policyError,
}: {
  state: AlwaysOnSwitchResponse;
  view: ActivationView;
  policyLoading: boolean;
  policyError: boolean;
}) {
  return (
    <>
      <div className="rs-stat-line">
        <div>
          <Caption as="span">설정값</Caption>
          <Text className="rs-stat-value" as="span">{enabledLabel(state.configured_enabled)}</Text>
          <Caption as="span">담당자가 저장한 DB 스위치</Caption>
        </div>
        <div>
          <Caption as="span">실제 운영</Caption>
          <Text className="rs-stat-value" as="span">{enabledLabel(state.effective_enabled)}</Text>
          <Caption as="span">환경·게이트·버전이 모두 맞을 때만 켜짐</Caption>
        </div>
        <div>
          <Caption as="span">환경 허용</Caption>
          <Text className="rs-stat-value" as="span">{state.environment_enabled ? "허용" : "차단"}</Text>
          {/* 긴 설정 키는 4칸 요약 줄이 아니라 아래 상태 대조·차단 사유에 둔다. */}
          <Caption as="span">배포 환경 안전 상한</Caption>
        </div>
        <div>
          <Caption as="span">서버 거절</Caption>
          <Text className="rs-stat-value" as="span">{view.hasRejection ? "있음" : "없음"}</Text>
          <Caption as="span">서버가 남긴 사유만 표시합니다</Caption>
        </div>
      </div>

      {view.hasRejection ? (
        <Note title="상시 운영이 거부되었습니다." tone="error">{state.rejection_reason}</Note>
      ) : null}

      <Section title="활성화 전 확인">
        {view.blockers.length > 0 ? (
          <div className="rs-note is-warning" role="alert" aria-label="상시 운영 켜기 차단 사유">
            <div className="rs-note-copy">
              <strong>켤 수 없는 상태입니다 · 조건 {view.blockers.length}건 미충족</strong>
              <ul className="rs-blocker-list">
                {view.blockers.map((blocker) => (
                  <li key={blocker.key}>
                    <span className="rs-blocker-copy">
                      <span>{blocker.message}</span>
                      {blocker.detail ? <small>{blocker.detail}</small> : null}
                    </span>
                    {blocker.href ? <Link className="operations-blocker-link" to={blocker.href}>{blocker.linkLabel ?? "확인하기"}</Link> : null}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : (
          <Note title="모든 구조 조건이 확인되었습니다">
            켜기 전에 담당자와 quality gate evaluation ID를 확인 창에서 다시 확인합니다.
          </Note>
        )}
        {policyError ? (
          <Caption>활성 정책 digest를 조회할 수 없습니다. 상시 운영 응답의 정책 버전만 표시합니다.</Caption>
        ) : null}
        {policyLoading ? <Caption>현재 active 정책을 확인하는 중입니다.</Caption> : null}
      </Section>

      <Section title="현재 승인 조합" action={<Caption as="span">게이트 {valueLabel(state.quality_gate_status)}</Caption>}>
        <dl className="rs-binding-list">
          <div>
            <dt>quality gate evaluation</dt>
            <dd><span className="rs-mono">{identifierText(view.gateId)}</span></dd>
          </div>
          <div>
            <dt>정책 버전 · 식별 해시</dt>
            <dd>
              <span className="rs-mono">{valueLabel(state.policy_version)}</span>
              <span className="rs-mono">{identifierText(view.policyDigest)}</span>
            </dd>
          </div>
          <div>
            <dt>모델 이름 · 식별 해시</dt>
            <dd>
              <span className="rs-mono">{valueLabel(state.model_name)}</span>
              <span className="rs-mono">{identifierText(state.model_digest)}</span>
            </dd>
          </div>
          <div>
            <dt>prompt version</dt>
            <dd><span className="rs-mono">{valueLabel(state.prompt_version)}</span></dd>
          </div>
          <div>
            <dt>프로필 버전 · 식별 해시</dt>
            <dd>
              <span className="rs-mono">{valueLabel(state.company_profile_version)}</span>
              <span className="rs-mono">{identifierText(state.company_profile_digest)}</span>
            </dd>
          </div>
        </dl>
      </Section>

      <Section title="상태 대조">
        <DataTable
          caption="활성화 전 확인 항목과 현재 값"
          headings={["항목", "현재 값", "확인 결과"]}
          rows={[
            {
              id: "environment",
              cells: [
                <span key="env">
                  배포 환경 허용
                  <span className="rs-row-sub rs-mono">BIDOPS_SCHEDULER_ENABLED</span>
                </span>,
                state.environment_enabled ? "활성" : "비활성",
                state.environment_enabled ? "허용" : "차단",
              ],
            },
            {
              id: "policy",
              cells: ["운영 정책", valueLabel(state.policy_version), bindingMatchLabel(view.policyVersionStatus)],
            },
            {
              id: "gate",
              cells: ["최신 운영 품질 평가", valueLabel(state.quality_gate_status), bindingMatchLabel(view.policyGateStatus)],
            },
            {
              id: "prompt",
              cells: ["prompt version", valueLabel(state.prompt_version), bindingMatchLabel(view.policyPromptStatus)],
            },
          ]}
        />
      </Section>

      <Facts
        items={[
          ["마지막 변경", <span className="rs-mono" key="updated">{state.updated_at}</span>],
          ["변경 담당자", state.updated_by || "담당자 미확인"],
        ]}
      />
      <Caption>
        끄기는 기존 실행·회차·산출물을 삭제하지 않습니다. model_comparison 통과를 운영 승인 통과로 쓸 수
        없습니다.
      </Caption>
    </>
  );
}

interface AlwaysOnActionsProps {
  state: AlwaysOnSwitchResponse;
  view: ActivationView;
  busy: boolean;
  onUpdate: (payload: { enabled: boolean; confirmed_by: string; quality_gate_result_id: string | null }) => Promise<boolean>;
  activePolicyVersion: string | null;
}

/** 바닥 고정 액션의 켜기·끄기. 두 조작 모두 담당자 확인을 요구한다. */
export function AlwaysOnActions({ state, view, busy, onUpdate, activePolicyVersion }: AlwaysOnActionsProps) {
  const [disableActor, setDisableActor] = useState("");
  const [disableDialogOpen, setDisableDialogOpen] = useState(false);
  const [enableActor, setEnableActor] = useState("");
  const [enableConfirmedGateId, setEnableConfirmedGateId] = useState("");
  const [enableDialogOpen, setEnableDialogOpen] = useState(false);
  const [enableDialogBusy, setEnableDialogBusy] = useState(false);
  const [enableDialogError, setEnableDialogError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const gateId = view.gateId;
  useEffect(() => {
    if (!state.quality_gate_result_id) setEnableConfirmedGateId("");
  }, [state.quality_gate_result_id]);

  const enableActorReady = enableActor.trim().length > 0;
  const disableActorReady = disableActor.trim().length > 0;
  const enableGateConfirmed = Boolean(gateId) && enableConfirmedGateId.trim() === gateId;

  const update = async (enabled: boolean) => {
    if (enabled) {
      if (view.blockers.length > 0) {
        setEnableDialogError("구조적 차단 조건을 먼저 해결해야 합니다.");
        return;
      }
      if (!enableActorReady) {
        setEnableDialogError("상시 운영을 켜려면 담당자 이름을 입력하십시오.");
        return;
      }
      if (!enableGateConfirmed) {
        setEnableDialogError("최신 운영 승인 게이트의 결과 ID를 정확히 확인하십시오.");
        return;
      }
      setEnableDialogError(null);
      setEnableDialogBusy(true);
      try {
        const updated = await onUpdate({ enabled: true, confirmed_by: enableActor.trim(), quality_gate_result_id: gateId });
        if (updated) {
          setEnableActor("");
          setEnableConfirmedGateId("");
          setEnableDialogOpen(false);
        } else {
          setEnableDialogError("상시 운영을 켜지 못했습니다. 화면 상단의 오류 내용을 확인하십시오.");
        }
      } catch {
        setEnableDialogError("상시 운영을 켜지 못했습니다. 잠시 후 다시 시도하십시오.");
      } finally {
        setEnableDialogBusy(false);
      }
      return;
    }

    if (!disableActorReady) {
      setValidationError("상시 운영을 끄려면 담당자 이름을 입력하십시오.");
      return;
    }
    setValidationError(null);
    try {
      const updated = await onUpdate({ enabled: false, confirmed_by: disableActor.trim(), quality_gate_result_id: null });
      if (updated) {
        setDisableActor("");
        setDisableDialogOpen(false);
      } else {
        setValidationError("상시 운영을 끄지 못했습니다. 화면 상단의 오류 내용을 확인하십시오.");
      }
    } catch {
      setValidationError("상시 운영을 끄지 못했습니다. 잠시 후 다시 시도하십시오.");
    }
  };

  const handleEnableDialogOpenChange = (open: boolean) => {
    if (!open && enableDialogBusy) return;
    setEnableDialogOpen(open);
    if (open) {
      setValidationError(null);
      setEnableDialogError(null);
      return;
    }
    setEnableDialogError(null);
    setEnableActor("");
    setEnableConfirmedGateId("");
  };

  return (
    <>
      <Button
        label="상시 운영 끄기"
        size="sm"
        isDisabled={busy || !state.configured_enabled}
        onClick={() => { setValidationError(null); setDisableDialogOpen(true); }}
      />
      {view.canEnable ? (
        <AlertDialog open={enableDialogOpen} onOpenChange={handleEnableDialogOpenChange}>
          <AlertDialogTrigger asChild>
            <button className="operations-button operations-button-primary" type="button" disabled={busy} aria-haspopup="dialog">상시 운영 켜기</button>
          </AlertDialogTrigger>
          <AlertDialogContent className="operations-alert-dialog rs-enable-dialog" data-astryx-theme="bidops" aria-describedby="operations-enable-dialog-description">
            <AlertDialogHeader className="operations-alert-dialog-header">
              <span className="operations-dialog-kicker">승인 경계 · 최종 확인</span>
              <AlertDialogTitle>상시 운영을 켭니다</AlertDialogTitle>
              <AlertDialogDescription id="operations-enable-dialog-description">
                기존 회차와 산출물은 바뀌지 않지만, 이후 새 회차가 담당자 확인 없이 자동으로 생성됩니다. 아래 승인 조합과 담당자 기록을 확인한 뒤 켜십시오.
              </AlertDialogDescription>
            </AlertDialogHeader>

            <div className="operations-dialog-binding" aria-label="상시 운영 승인 조합 요약">
              <div className="operations-dialog-binding-row">
                <span>정책 버전</span>
                <div><span className="mono">{valueLabel(state.policy_version)}</span><BindingStatus status={view.policyVersionStatus} /><small>active {valueLabel(activePolicyVersion)}</small></div>
              </div>
              <div className="operations-dialog-binding-row">
                <span>정책 식별 해시</span>
                <div><DigestValue value={view.policyDigest} className="operations-dialog-digest" /><BindingStatus status="unknown" label={isPresent(view.policyDigest) ? "활성 정책 기준값" : "값 없음"} /></div>
              </div>
              <div className="operations-dialog-binding-row">
                <span>게이트 결과 ID</span>
                <div><span className="mono">{identifierText(gateId)}</span><BindingStatus status={view.policyGateStatus} /><small>현재 상태 {valueLabel(state.quality_gate_status)}</small></div>
              </div>
              <div className="operations-dialog-binding-row">
                <span>모델 · 식별 해시</span>
                <div><span className="mono">{valueLabel(state.model_name)}</span><DigestValue value={state.model_digest} className="operations-dialog-digest" /><BindingStatus status="unknown" /></div>
              </div>
              <div className="operations-dialog-binding-row">
                <span>prompt version</span>
                <div><span className="mono">{valueLabel(state.prompt_version)}</span><BindingStatus status={view.policyPromptStatus} /></div>
              </div>
              <div className="operations-dialog-binding-row">
                <span>프로필 · 식별 해시</span>
                <div><span className="mono">{valueLabel(state.company_profile_version)}</span><DigestValue value={state.company_profile_digest} className="operations-dialog-digest" /><BindingStatus status="unknown" /></div>
              </div>
            </div>

            <div className="operations-dialog-fields">
              <label className="operations-dialog-field" htmlFor="operations-enable-actor">
                <span>변경 담당자</span>
                <input id="operations-enable-actor" value={enableActor} onChange={(event) => setEnableActor(event.target.value)} placeholder="담당자 이름" autoComplete="name" disabled={enableDialogBusy || busy} aria-describedby="operations-enable-actor-help" />
                <small id="operations-enable-actor-help">운영 변경 기록에 남는 담당자 이름입니다.</small>
              </label>
              <label className="operations-dialog-field" htmlFor="operations-enable-gate-id">
                <span>게이트 결과 ID 확인</span>
                <input id="operations-enable-gate-id" value={enableConfirmedGateId} onChange={(event) => setEnableConfirmedGateId(event.target.value)} placeholder={gateId ?? "gateeval-…"} disabled={enableDialogBusy || busy || !gateId} aria-describedby="operations-enable-gate-id-help" />
                <small id="operations-enable-gate-id-help">위 요약의 ID와 정확히 일치해야 합니다.</small>
              </label>
            </div>
            {enableDialogError ? <p className="operations-dialog-error" role="alert">{enableDialogError}</p> : null}
            <AlertDialogFooter className="operations-alert-dialog-footer">
              <AlertDialogCancel className="operations-dialog-cancel" disabled={enableDialogBusy || busy}>취소</AlertDialogCancel>
              <AlertDialogAction
                className="operations-dialog-confirm"
                disabled={!enableActorReady || !enableGateConfirmed || enableDialogBusy || busy}
                onClick={(event) => {
                  event.preventDefault();
                  void update(true);
                }}
              >
                {enableDialogBusy ? "켜는 중…" : "상시 운영 켜기"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      ) : null}

      <Dialog
        isOpen={disableDialogOpen}
        onOpenChange={(next) => { if (!next && !busy) setDisableDialogOpen(false); }}
        purpose="form"
        width={560}
        maxHeight="90dvh"
      >
        <div className="rs-dialog-body" data-astryx-theme="bidops">
          <DialogHeader title="상시 운영 끄기" onOpenChange={(next) => { if (!next && !busy) setDisableDialogOpen(false); }} />
          <div className="rs-dialog-scroll">
            <Note title="기존 실행·회차·산출물은 삭제하지 않습니다">
              이후 새 예약 실행만 멈춥니다. 이미 끝난 회차와 판정 기록은 그대로 남습니다.
            </Note>
            <label className="rs-field" htmlFor="rs-disable-actor">
              <span>끄기 담당자 <em>필수</em></span>
              <input
                id="rs-disable-actor"
                value={disableActor}
                onChange={(event) => setDisableActor(event.target.value)}
                placeholder="담당자 이름"
                autoComplete="name"
                disabled={busy}
                required
              />
            </label>
            {validationError ? <Text className="rs-dialog-error" as="p" role="alert">{validationError}</Text> : null}
          </div>
          <div className="rs-dialog-actions">
            <Button label="취소" isDisabled={busy} onClick={() => setDisableDialogOpen(false)} />
            <Button
              label={busy ? "끄는 중…" : "상시 운영 끄기 확인"}
              variant="destructive"
              isDisabled={busy || !disableActorReady || !state.configured_enabled}
              onClick={() => void update(false)}
            />
          </div>
        </div>
      </Dialog>
    </>
  );
}
