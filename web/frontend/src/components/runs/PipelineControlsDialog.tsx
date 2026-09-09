import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import type { PipelineStageResponse } from "../../lib/types";
import { present } from "../../lib/format";
import { Caption, Note } from "./RunStatusPrimitives";
import { stageMeta, stageStatusLabel, stageTitle } from "./PipelineStages";

type RunnableStage = "collect" | "sample" | "report";

interface PipelineControlsDialogProps {
  open: boolean;
  onClose: () => void;
  runId: string;
  stages: PipelineStageResponse[];
  busy: boolean;
  actionError: string | null;
  onRun: (stage: RunnableStage, fromRaw?: boolean) => void;
}

/**
 * 파이프라인 실행 조작. 시안이 기본 화면에서 뺀 실행 폼을 **없애지 않고** 이
 * 대화상자로 옮겼다. 기존 조작을 그대로 유지한다:
 *
 * - 새 회차 수집 (`collect`)
 * - 원문 재분류 (`collect` + `from_raw=true`)
 * - 표본 선정 (`sample`) · 보고 생성 (`report`)
 *
 * 실행 가능 여부는 화면이 정하지 않고 서버가 준 `execution_allowed`와 현재
 * 진행 중인 실행 여부만 본다. 새 수집기를 만들거나 날짜 입력을 새로 만들지
 * 않는다.
 */
export function PipelineControlsDialog({
  open,
  onClose,
  runId,
  stages,
  busy,
  actionError,
  onRun,
}: PipelineControlsDialogProps) {
  const collectStage = stages.find((stage) => stage.name === "collect_normalize") ?? null;
  const collectAllowed = Boolean(collectStage?.execution_allowed);

  return (
    <Dialog isOpen={open} onOpenChange={(next) => { if (!next) onClose(); }} purpose="form" width={640} maxHeight="90dvh">
      <div className="rs-dialog-body" data-astryx-theme="bidops">
        <DialogHeader title="파이프라인 실행" onOpenChange={(next) => { if (!next) onClose(); }} />
        <div className="rs-dialog-scroll">
          <Caption>
            원본 회차 <span className="rs-mono">{runId}</span>의 수집 스크립트를 실행합니다. 기존 회차 원본과
            판정 기록은 덮어쓰지 않습니다.
          </Caption>

          {stages.map((stage) => {
            const runnable = stageMeta[stage.name]?.runnable;
            const disabled = busy || !stage.execution_allowed || stage.status === "running";
            return (
              <div className="rs-note" key={stage.name}>
                <div className="rs-note-copy">
                  <strong>{stageTitle(stage)} · {stageStatusLabel(stage.status)}</strong>
                  <Caption>
                    <span className="rs-mono">{present(stage.script, "스크립트 미확인")}</span>
                    {stage.exit_code !== null && stage.status === "failed" ? ` · 종료 코드 ${stage.exit_code}` : ""}
                    {stage.message ? ` · ${stage.message}` : ""}
                  </Caption>
                </div>
                {runnable ? (
                  <Button
                    label={stage.status === "running" ? "실행 중" : `${stageTitle(stage)} 실행`}
                    size="sm"
                    isDisabled={disabled}
                    onClick={() => onRun(runnable)}
                  />
                ) : (
                  <Caption as="span">이 단계는 판정 실행으로만 진행합니다</Caption>
                )}
              </div>
            );
          })}

          <div className="rs-note">
            <div className="rs-note-copy">
              <strong>원문 재분류 <span className="rs-mono">--from-raw</span></strong>
              <Caption>보관한 원문을 다시 분류합니다. 나라장터에 새로 요청하지 않습니다.</Caption>
            </div>
            <Button
              label="원문 재분류 실행"
              size="sm"
              isDisabled={busy || !collectAllowed}
              onClick={() => onRun("collect", true)}
            />
          </div>

          <Note title="새 회차 수집은 새 원본을 만듭니다" tone="warning">
            지금 고른 회차의 원본과 기존 판정은 그대로 남습니다. 실행 결과는 실행 기록 탭에서 확인합니다.
          </Note>
          {actionError ? <Text className="rs-dialog-error" as="p" role="alert">{actionError}</Text> : null}
        </div>
        <div className="rs-dialog-actions">
          <Button label="취소" onClick={onClose} />
          <Button
            label="새 회차 수집"
            variant="primary"
            isDisabled={busy || !collectAllowed}
            onClick={() => onRun("collect")}
          />
        </div>
      </div>
    </Dialog>
  );
}
