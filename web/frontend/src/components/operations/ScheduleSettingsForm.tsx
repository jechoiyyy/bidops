import { useEffect, useRef, useState } from "react";
import type { ScheduleSettingsResponse } from "../../lib/types";

interface ScheduleSettingsFormProps {
  settings: ScheduleSettingsResponse;
  busy: boolean;
  onSave: (payload: {
    daily_time: string;
    weekly_time: string;
    prespec_enabled: boolean;
    updated_by: string;
  }) => Promise<void>;
}

export function ScheduleSettingsForm({ settings, busy, onSave }: ScheduleSettingsFormProps) {
  const [dailyTime, setDailyTime] = useState(settings.daily_time);
  const [weeklyTime, setWeeklyTime] = useState(settings.weekly_time);
  const [prespecEnabled, setPrespecEnabled] = useState(settings.prespec_enabled);
  const [actor, setActor] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const loadedRevision = useRef(settings.updated_at);

  // Polling returns fresh objects. Only reset the editor when the server's
  // updated_at changes so a person typing is not interrupted by a read.
  useEffect(() => {
    if (loadedRevision.current === settings.updated_at) return;
    loadedRevision.current = settings.updated_at;
    setDailyTime(settings.daily_time);
    setWeeklyTime(settings.weekly_time);
    setPrespecEnabled(settings.prespec_enabled);
  }, [settings]);

  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedActor = actor.trim();
    if (!trimmedActor) {
      setValidationError("설정을 저장하려면 담당자 이름을 입력하십시오.");
      return;
    }
    if (!dailyTime || !weeklyTime) {
      setValidationError("일간·주간 실행 시각을 모두 입력하십시오.");
      return;
    }
    setValidationError(null);
    await onSave({ daily_time: dailyTime, weekly_time: weeklyTime, prespec_enabled: prespecEnabled, updated_by: trimmedActor });
    setActor("");
  };

  return (
    <form className="operations-settings-form" onSubmit={(event) => void save(event)}>
      <div className="operations-settings-grid">
        <label className="operations-field">
          <span>시간대</span>
          <output className="operations-readonly-value mono" aria-label="고정 시간대">{settings.timezone}</output>
          <small>모든 날짜 경계와 예약 시각은 Asia/Seoul 기준입니다.</small>
        </label>
        <label className="operations-field">
          <span>일간 실행 시각</span>
          <input id="operations-daily-time" type="time" value={dailyTime} onChange={(event) => setDailyTime(event.target.value)} disabled={busy} required />
          <small>전일 단일 날짜를 수집하고 판정합니다.</small>
        </label>
        <label className="operations-field">
          <span>주간 실행 시각</span>
          <input id="operations-weekly-time" type="time" value={weeklyTime} onChange={(event) => setWeeklyTime(event.target.value)} disabled={busy} required />
          <small>월요일부터 일요일까지의 누계 보고를 만듭니다.</small>
        </label>
        <label className="operations-checkbox-field">
          <input type="checkbox" checked={prespecEnabled} onChange={(event) => setPrespecEnabled(event.target.checked)} disabled={busy} />
          <span><strong>사전규격 수집</strong><small>정기 수집 범위에 사전규격을 포함합니다.</small></span>
        </label>
      </div>
      <div className="operations-form-footer">
        <label className="operations-actor-field">
          <span>저장 담당자</span>
          <input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="담당자 이름" autoComplete="name" disabled={busy} />
        </label>
        <button className="operations-button operations-button-primary" type="submit" disabled={busy || !actor.trim()}>
          {busy ? "저장 중…" : "설정 저장"}
        </button>
      </div>
      {validationError ? <p className="operations-inline-error" role="alert">{validationError}</p> : null}
      <p className="operations-form-meta">마지막 변경: <span className="mono">{settings.updated_at}</span> · {settings.updated_by || "담당자 미확인"}</p>
    </form>
  );
}
