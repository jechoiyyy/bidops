"""연속 가동 시간 기준 GPU 휴지 (docs/0918_daily-operation/spec.md §10) 검사.

`GpuRestGate` 자체의 규칙, `ScreeningWorker.run_forever`의 배선, 분석 워커
`main()`의 SIGTERM 응답성을 각각 확인한다.
"""

from __future__ import annotations

import itertools
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.gpu_rest import GpuRestGate
from app.screening.worker import ScreeningWorker
from app.workers import analysis


# --- GpuRestGate -----------------------------------------------------------


def test_disabled_when_either_value_is_zero() -> None:
    for busy_limit, rest in ((0.0, 0.0), (5.0, 0.0), (0.0, 7.0)):
        gate = GpuRestGate(busy_limit, rest)
        assert gate.enabled is False
        assert gate.after_poll(did_work=True, work_seconds=100.0, now=0.0) is None
        assert gate.after_poll(did_work=False, work_seconds=0.0, now=1000.0) is None


def test_busy_accumulates_across_jobs_until_limit_then_rests() -> None:
    gate = GpuRestGate(5.0, 7.0)
    assert gate.after_poll(did_work=True, work_seconds=2.0, now=0.0) is None
    assert gate.after_poll(did_work=True, work_seconds=2.0, now=1.0) is None
    assert gate.busy == 4.0
    rest = gate.after_poll(did_work=True, work_seconds=2.0, now=2.0)
    assert rest == 7.0
    assert gate.busy == 0.0


def test_a_single_long_job_still_rests_only_after_it_finishes() -> None:
    gate = GpuRestGate(5.0, 7.0)
    rest = gate.after_poll(did_work=True, work_seconds=8.0, now=0.0)
    assert rest == 7.0
    assert gate.busy == 0.0


def test_idle_shorter_than_rest_keeps_busy_but_long_enough_idle_clears_it() -> None:
    gate = GpuRestGate(5.0, 7.0)
    gate.busy = 4.0
    assert gate.after_poll(did_work=False, work_seconds=0.0, now=100.0) is None
    assert gate.busy == 4.0
    assert gate.after_poll(did_work=False, work_seconds=0.0, now=103.0) is None
    assert gate.busy == 4.0
    assert gate.after_poll(did_work=False, work_seconds=0.0, now=107.0) is None
    assert gate.busy == 0.0


# --- ScreeningWorker.run_forever --------------------------------------------


class _RecordingEvent(Event):
    def __init__(self) -> None:
        super().__init__()
        self.waits: list[float] = []

    def wait(self, timeout: float | None = None) -> bool:  # type: ignore[override]
        self.waits.append(timeout)
        self.set()
        return True


def test_screening_worker_run_forever_rests_on_the_gpu_gate() -> None:
    settings = SimpleNamespace(gpu_busy_limit_seconds=5.0, gpu_rest_seconds=7.0)
    rows = iter([object(), object()])

    def fake_run_once() -> Any:
        return next(rows, None)

    clocks = iter([0.0, 3.0, 3.0, 6.0, 6.0, 9.0])

    def fake_monotonic() -> float:
        return next(clocks)

    worker = ScreeningWorker(
        settings,
        store=object(),
        session_factory=object(),
        model_client=object(),
        sleep=lambda _delay: None,
        monotonic=fake_monotonic,
    )
    worker.run_once = fake_run_once  # type: ignore[method-assign]

    event = _RecordingEvent()
    worker.run_forever(stop_event=event)

    assert event.waits == [7.0]


# --- analysis.main() ---------------------------------------------------------


class _Session:
    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False

    def rollback(self) -> None:  # pragma: no cover - 실패 경로 전용
        pass


class _AlwaysWorkC2Worker:
    def __init__(self, *, settings: Any) -> None:
        self.settings = settings

    def run_once(self, _session: Any) -> Any:
        return object()


class _FitRunner:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    def run_once(self, _session: Any, _worker_id: str) -> bool:  # pragma: no cover - 이 시나리오에서 호출되지 않는다
        return False


class _FakeEvent:
    def __init__(self) -> None:
        self.waits: list[float] = []
        self._is_set = False

    def wait(self, timeout: float | None = None) -> bool:  # overridden per-test after construction
        self.waits.append(timeout)
        return True

    def set(self) -> None:
        self._is_set = True

    def is_set(self) -> bool:
        return self._is_set


def test_analysis_main_rests_on_the_gpu_gate_and_still_answers_sigterm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        analysis_worker_concurrency=1,
        analysis_worker_poll_seconds=0.1,
        worker_id="test-analysis-worker",
        gpu_busy_limit_seconds=1.0,
        gpu_rest_seconds=100.0,
    )
    monkeypatch.setattr(analysis, "get_settings", lambda: settings)
    monkeypatch.setattr(analysis, "configure", lambda _settings: None)
    monkeypatch.setattr(analysis, "assert_object_store_runtime", lambda **_kwargs: None)
    monkeypatch.setattr(analysis, "SessionLocal", _Session)
    monkeypatch.setattr(analysis, "C2ScreeningWorker", _AlwaysWorkC2Worker)
    monkeypatch.setattr(analysis, "PreSpecCompanyFitRunner", _FitRunner)
    monkeypatch.setattr("sys.argv", ["analysis"])

    captured: dict[str, Any] = {}

    def fake_signal(sig: int, handler: Any) -> None:
        if sig == analysis.signal.SIGTERM:
            captured["handler"] = handler

    monkeypatch.setattr(analysis.signal, "signal", fake_signal)

    fake_event = _FakeEvent()
    monkeypatch.setattr(analysis.threading, "Event", lambda: fake_event)

    clocks = iter(itertools.count(0.0, 2.0))
    monkeypatch.setattr(analysis.time, "monotonic", lambda: next(clocks))

    def deliver_sigterm(timeout: float | None = None) -> bool:
        fake_event.waits.append(timeout)
        captured["handler"](analysis.signal.SIGTERM, None)
        return True

    fake_event.wait = deliver_sigterm  # type: ignore[method-assign]

    analysis.main()

    assert fake_event.waits == [100.0]
