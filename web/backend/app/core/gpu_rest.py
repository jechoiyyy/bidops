"""연속 가동 시간 기준 GPU 휴지 (docs/0918_daily-operation/spec.md §10).

작업을 쉬지 않고 처리한 시간의 합이 limit 이상이 되면 다음 claim 전에 rest만큼 쉰다.
작업 중간은 끊지 않는다. 잡을 작업이 없는 idle이 rest 이상 이어지면 그것이 휴지이므로
누적을 0으로 돌린다. 두 값 중 하나라도 0이면 꺼져 있고 동작은 이전과 같다.
"""

from __future__ import annotations


class GpuRestGate:
    def __init__(self, busy_limit_seconds: float, rest_seconds: float) -> None:
        self.busy_limit_seconds = float(busy_limit_seconds)
        self.rest_seconds = float(rest_seconds)
        self.enabled = self.busy_limit_seconds > 0 and self.rest_seconds > 0
        self.busy = 0.0
        self._idle_since: float | None = None

    def after_poll(self, *, did_work: bool, work_seconds: float, now: float) -> float | None:
        """한 poll이 끝난 뒤 부른다. 쉬어야 하면 휴지 초를, 아니면 ``None``을 낸다."""

        if not self.enabled:
            return None
        if did_work:
            self._idle_since = None
            self.busy += max(0.0, float(work_seconds))
            if self.busy >= self.busy_limit_seconds:
                self.busy = 0.0
                return self.rest_seconds
            return None
        if self._idle_since is None:
            self._idle_since = now
        elif now - self._idle_since >= self.rest_seconds:
            self.busy = 0.0
        return None
