import { useEffect, useState } from "react";
import type { ScheduleExecutionCreateRequest, ScheduleExecutionSummary, ScheduleJobKind } from "../../lib/types";

interface ScheduleExecutionFormProps {
  recoveryTarget: ScheduleExecutionSummary | null;
  busy: boolean;
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

export function ScheduleExecutionForm({ recoveryTarget, busy, onSubmit, onCancelRecovery }: ScheduleExecutionFormProps) {
  const [jobKind, setJobKind] = useState<ScheduleJobKind>(recoveryTarget?.job_kind ?? "daily");
  const [windowFrom, setWindowFrom] = useState(recoveryTarget?.window_from ?? initialWindow("daily").from);
  const [windowTo, setWindowTo] = useState(recoveryTarget?.window_to ?? initialWindow("daily").to);
  const [actor, setActor] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (!recoveryTarget) return;
    setJobKind(recoveryTarget.job_kind);
    setWindowFrom(recoveryTarget.window_from);
    setWindowTo(recoveryTarget.window_to);
    setValidationError(null);
  }, [recoveryTarget]);

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

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
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
    if (submitted) setActor("");
  };

  return (
    <section className="operations-panel operations-manual-panel" aria-labelledby="operations-manual-title">
      <div className="operations-panel-heading"><div><span className="operations-eyebrow">담당자 요청</span><h3 id="operations-manual-title">정기 실행 예약</h3></div><span className="operations-panel-note">외부 알림 없음</span></div>
      <div className="operations-panel-body">
        {recoveryTarget ? <div className="operations-recovery-banner" role="status"><strong>명시 복구</strong><span><span className="mono">{recoveryTarget.execution_id}</span> · {recoveryTarget.status} 회차만 복구합니다.</span><button type="button" onClick={onCancelRecovery} disabled={busy}>복구 취소</button></div> : null}
        <form className="operations-manual-form" onSubmit={(event) => void submit(event)}>
          <label className="operations-field"><span>실행 종류</span><select id="operations-job-kind" value={jobKind} onChange={(event) => changeKind(event.target.value as ScheduleJobKind)} disabled={busy}><option value="daily">일간</option><option value="weekly">주간</option></select></label>
          <label className="operations-field"><span>기간 시작</span><input id="operations-window-from" type="date" value={windowFrom} onChange={(event) => changeFrom(event.target.value)} disabled={busy} required /></label>
          <label className="operations-field"><span>기간 종료</span><input id="operations-window-to" type="date" value={windowTo} onChange={(event) => setWindowTo(event.target.value)} disabled={busy} required /></label>
          <label className="operations-actor-field"><span>요청 담당자</span><input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="담당자 이름" autoComplete="name" disabled={busy} required /></label>
          <button className="operations-button operations-button-primary" type="submit" disabled={busy || !actor.trim()}>{busy ? "예약 중…" : recoveryTarget ? "복구 예약" : "수동 실행 예약"}</button>
        </form>
        <p className="operations-help">일간은 같은 날짜, 주간은 월요일~일요일 7일만 요청할 수 있습니다. 실패·부분 성공·건너뜀만 이력에서 명시 복구할 수 있습니다.</p>
        {validationError ? <p className="operations-inline-error" role="alert">{validationError}</p> : null}
      </div>
    </section>
  );
}
