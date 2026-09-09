import { useEffect, useRef, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import { Caption, Note } from "../runs/RunStatusPrimitives";
import type { ScheduleSettingsResponse } from "../../lib/types";

interface ScheduleSettingsDialogProps {
  open: boolean;
  onClose: () => void;
  settings: ScheduleSettingsResponse;
  busy: boolean;
  saveError: string | null;
  onSave: (payload: {
    daily_time: string;
    weekly_time: string;
    prespec_enabled: boolean;
    updated_by: string;
  }) => Promise<boolean>;
}

/**
 * 스케줄 수정 초안.
 *
 * 초안은 저장하기 전까지 현재 값에 반영되지 않는다. 취소하면 현재 값은 그대로
 * 남고, 충돌(409)이 나면 창을 닫지 않고 입력한 초안을 유지해 다시 시도할 수
 * 있게 한다. **저장이 상시 운영을 켜지 않는다.**
 */
export function ScheduleSettingsDialog({ open, onClose, settings, busy, saveError, onSave }: ScheduleSettingsDialogProps) {
  const [dailyTime, setDailyTime] = useState(settings.daily_time);
  const [weeklyTime, setWeeklyTime] = useState(settings.weekly_time);
  const [prespecEnabled, setPrespecEnabled] = useState(settings.prespec_enabled);
  const [actor, setActor] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const loadedRevision = useRef(settings.updated_at);

  // 창을 열 때만 현재 값에서 초안을 만든다. 폴링이 새 객체를 돌려줘도 사람이
  // 입력하는 중인 초안을 덮지 않는다.
  useEffect(() => {
    if (!open) return;
    loadedRevision.current = settings.updated_at;
    setDailyTime(settings.daily_time);
    setWeeklyTime(settings.weekly_time);
    setPrespecEnabled(settings.prespec_enabled);
    setValidationError(null);
    setActor("");
    // settings 는 의도적으로 의존성에서 제외한다 — 열 때 한 번만 초안을 만든다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const dirty = dailyTime !== settings.daily_time
    || weeklyTime !== settings.weekly_time
    || prespecEnabled !== settings.prespec_enabled
    || actor.trim() !== "";

  const save = async () => {
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
    const saved = await onSave({
      daily_time: dailyTime,
      weekly_time: weeklyTime,
      prespec_enabled: prespecEnabled,
      updated_by: trimmedActor,
    });
    // 저장에 실패하면 창을 닫지 않고 초안을 유지한다.
    if (saved) onClose();
  };

  return (
    <Dialog isOpen={open} onOpenChange={(next) => { if (!next && !busy) onClose(); }} purpose="form" width={640} maxHeight="90dvh">
      <div className="rs-dialog-body" data-astryx-theme="bidops">
        <DialogHeader title="스케줄 수정" onOpenChange={(next) => { if (!next && !busy) onClose(); }} />
        <div className="rs-dialog-scroll">
          <Caption>
            시간대는 <span className="rs-mono">{settings.timezone}</span>로 고정입니다. 모든 날짜 경계와 예약
            시각이 이 시간대를 따릅니다.
          </Caption>
          <div className="rs-form-grid">
            <label className="rs-field" htmlFor="rs-daily-time">
              <span>일간 실행 시각 <em>필수</em></span>
              <input
                id="rs-daily-time"
                type="time"
                value={dailyTime}
                onChange={(event) => setDailyTime(event.target.value)}
                disabled={busy}
                required
              />
              <small>전일 단일 날짜를 수집하고 판정합니다.</small>
            </label>
            <label className="rs-field" htmlFor="rs-weekly-time">
              <span>주간 실행 시각 · 월요일 <em>필수</em></span>
              <input
                id="rs-weekly-time"
                type="time"
                value={weeklyTime}
                onChange={(event) => setWeeklyTime(event.target.value)}
                disabled={busy}
                required
              />
              <small>월요일부터 일요일까지의 누계 보고를 만듭니다.</small>
            </label>
          </div>
          <label className="rs-check-field">
            <input
              type="checkbox"
              checked={prespecEnabled}
              onChange={(event) => setPrespecEnabled(event.target.checked)}
              disabled={busy}
            />
            <span>
              <Text as="span" weight="semibold">사전규격 수집</Text>
              <Caption as="span">정기 수집 범위에 사전규격을 포함합니다.</Caption>
            </span>
          </label>
          <label className="rs-field" htmlFor="rs-settings-actor">
            <span>변경 담당자 <em>필수</em></span>
            <input
              id="rs-settings-actor"
              value={actor}
              onChange={(event) => setActor(event.target.value)}
              placeholder="담당자 이름"
              autoComplete="name"
              disabled={busy}
              required
            />
          </label>
          <Note title="설정만 저장합니다">
            예약 시각을 바꿔도 상시 운영은 켜지지 않습니다. 환경 허용과 승인 조합 확인은 그대로 남습니다.
          </Note>
          {validationError ? <Text className="rs-dialog-error" as="p" role="alert">{validationError}</Text> : null}
          {saveError ? <Text className="rs-dialog-error" as="p" role="alert">{saveError}</Text> : null}
          <Caption>
            마지막 변경 <span className="rs-mono">{settings.updated_at}</span> · {settings.updated_by || "담당자 미확인"}
          </Caption>
        </div>
        <div className="rs-dialog-actions">
          <Button label="취소" isDisabled={busy} onClick={onClose} />
          <Button
            label={busy ? "저장 중…" : "설정 저장"}
            variant="primary"
            isDisabled={busy || !actor.trim() || !dirty}
            onClick={() => void save()}
          />
        </div>
      </div>
    </Dialog>
  );
}
