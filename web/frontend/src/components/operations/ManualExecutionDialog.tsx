import { useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import { Caption, Facts, Note } from "../runs/RunStatusPrimitives";
import type { ScheduleExecutionCreateRequest, ScheduleExecutionSummary, ScheduleJobKind } from "../../lib/types";

interface ManualExecutionDialogProps {
  open: boolean;
  onClose: () => void;
  recoveryTarget: ScheduleExecutionSummary | null;
  busy: boolean;
  submitError: string | null;
  onSubmit: (payload: ScheduleExecutionCreateRequest) => Promise<boolean>;
  onCancelRecovery: () => void;
}

function seoulDate(): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function parseDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value ? null : date;
}

function addDays(value: string, days: number): string {
  const date = parseDate(value);
  if (!date) return "";
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function mondayOf(value: string): string {
  const date = parseDate(value);
  if (!date) return value;
  const day = date.getUTCDay();
  const distance = day === 0 ? -6 : 1 - day;
  date.setUTCDate(date.getUTCDate() + distance);
  return date.toISOString().slice(0, 10);
}

function initialWindow(kind: ScheduleJobKind): { from: string; to: string } {
  const today = seoulDate();
  return kind === "daily" ? { from: today, to: today } : { from: mondayOf(today), to: addDays(mondayOf(today), 6) };
}

function validWindow(kind: ScheduleJobKind, from: string, to: string): string | null {
  if (!parseDate(from) || !parseDate(to)) return "실행 기간을 올바른 날짜로 입력하십시오.";
  if (kind === "daily" && from !== to) return "일간 실행은 시작일과 종료일이 같아야 합니다.";
  if (kind === "weekly" && (parseDate(from)?.getUTCDay() !== 1 || to !== addDays(from, 6))) return "주간 실행은 월요일부터 일요일까지 7일이어야 합니다.";
  return null;
}

/**
 * 수동 정기 실행 예약.
 *
 * 상시 운영이 꺼져 있어도 이 조작은 막지 않는다. 수동 실행은 담당자가 직접
 * 요청하는 별개의 경로이며, 필요한 승인·전제 조건은 서버가 판단한다. 화면이
 * 없는 차단 사유를 만들지 않는다.
 */
export function ManualExecutionDialog({
  open,
  onClose,
  recoveryTarget,
  busy,
  submitError,
  onSubmit,
  onCancelRecovery,
}: ManualExecutionDialogProps) {
  const [jobKind, setJobKind] = useState<ScheduleJobKind>("daily");
  const [windowFrom, setWindowFrom] = useState(initialWindow("daily").from);
  const [windowTo, setWindowTo] = useState(initialWindow("daily").to);
  const [actor, setActor] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (recoveryTarget) {
      setJobKind(recoveryTarget.job_kind);
      setWindowFrom(recoveryTarget.window_from);
      setWindowTo(recoveryTarget.window_to);
    }
    setValidationError(null);
    // 열 때 한 번만 초안을 만든다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, recoveryTarget?.execution_id]);

  const changeKind = (next: ScheduleJobKind) => {
    setJobKind(next);
    const nextWindow = initialWindow(next);
    setWindowFrom(nextWindow.from);
    setWindowTo(nextWindow.to);
    setValidationError(null);
  };

  const changeFrom = (next: string) => {
    setWindowFrom(next);
    if (jobKind === "daily") setWindowTo(next);
    if (jobKind === "weekly") setWindowTo(addDays(next, 6));
  };

  const submit = async () => {
    const actorValue = actor.trim();
    const dateError = validWindow(jobKind, windowFrom, windowTo);
    if (!actorValue) {
      setValidationError("실행을 요청하려면 담당자 이름을 입력하십시오.");
      return;
    }
    if (dateError) {
      setValidationError(dateError);
      return;
    }
    setValidationError(null);
    const payload: ScheduleExecutionCreateRequest = {
      job_kind: jobKind,
      window_from: windowFrom,
      window_to: windowTo,
      recovery_of_execution_id: recoveryTarget?.execution_id ?? null,
      requested_by: actorValue,
    };
    const submitted = await onSubmit(payload);
    // 실패하면 창을 닫지 않고 입력을 유지한다.
    if (submitted) {
      setActor("");
      onClose();
    }
  };

  return (
    <Dialog isOpen={open} onOpenChange={(next) => { if (!next && !busy) onClose(); }} purpose="form" width={640} maxHeight="90dvh">
      <div className="rs-dialog-body" data-astryx-theme="bidops">
        <DialogHeader
          title={recoveryTarget ? "명시 복구 예약" : "수동 정기 실행 예약"}
          onOpenChange={(next) => { if (!next && !busy) onClose(); }}
        />
        <div className="rs-dialog-scroll">
          {recoveryTarget ? (
            <>
              <Facts
                items={[
                  ["복구 대상 실행", <span className="rs-mono" key="exec">{recoveryTarget.execution_id}</span>],
                  ["대상 상태", recoveryTarget.status],
                  ["대상 기간", `${recoveryTarget.window_from} ~ ${recoveryTarget.window_to}`],
                  ["대상 회차 키", <span className="rs-mono" key="key">{recoveryTarget.run_key}</span>],
                ]}
              />
              <Note title="이 회차만 복구합니다">
                복구는 대상 실행의 기간만 다시 요청합니다. 기존 실행 기록과 산출물은 삭제하지 않습니다.
              </Note>
              <div className="rs-dialog-actions">
                <Button label="복구 취소" size="sm" isDisabled={busy} onClick={onCancelRecovery} />
              </div>
            </>
          ) : null}

          <div className="rs-form-grid">
            <label className="rs-field" htmlFor="rs-job-kind">
              <span>실행 종류 <em>필수</em></span>
              <select
                id="rs-job-kind"
                value={jobKind}
                onChange={(event) => changeKind(event.target.value as ScheduleJobKind)}
                disabled={busy}
              >
                <option value="daily">일간</option>
                <option value="weekly">주간</option>
              </select>
            </label>
            <label className="rs-field" htmlFor="rs-window-from">
              <span>기간 시작 <em>필수</em></span>
              <input
                id="rs-window-from"
                type="date"
                value={windowFrom}
                onChange={(event) => changeFrom(event.target.value)}
                disabled={busy}
                required
              />
            </label>
            <label className="rs-field" htmlFor="rs-window-to">
              <span>기간 종료 <em>필수</em></span>
              <input
                id="rs-window-to"
                type="date"
                value={windowTo}
                onChange={(event) => setWindowTo(event.target.value)}
                disabled={busy}
                required
              />
            </label>
            <label className="rs-field" htmlFor="rs-manual-actor">
              <span>요청 담당자 <em>필수</em></span>
              <input
                id="rs-manual-actor"
                value={actor}
                onChange={(event) => setActor(event.target.value)}
                placeholder="담당자 이름"
                autoComplete="name"
                disabled={busy}
                required
              />
            </label>
          </div>

          <Caption>
            일간은 같은 날짜, 주간은 월요일~일요일 7일만 요청할 수 있습니다. 실패·부분 성공·건너뜀만
            이력에서 명시 복구할 수 있습니다.
          </Caption>
          <Note title="수동 실행은 상시 운영과 별개입니다">
            상시 운영이 꺼져 있어도 담당자가 직접 요청할 수 있습니다. 실행에 필요한 승인과 전제 조건은
            서버가 확인하며, 예약이 곧 실행 성공을 뜻하지 않습니다.
          </Note>
          {validationError ? <Text className="rs-dialog-error" as="p" role="alert">{validationError}</Text> : null}
          {submitError ? <Text className="rs-dialog-error" as="p" role="alert">{submitError}</Text> : null}
        </div>
        <div className="rs-dialog-actions">
          <Button label="취소" isDisabled={busy} onClick={onClose} />
          <Button
            label={busy ? "예약 중…" : recoveryTarget ? "복구 예약" : "수동 실행 예약"}
            variant="primary"
            isDisabled={busy || !actor.trim()}
            onClick={() => void submit()}
          />
        </div>
      </div>
    </Dialog>
  );
}
