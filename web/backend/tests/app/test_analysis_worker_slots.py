"""합성 analysis worker의 한 poll이 슬롯 하나만 잡는지 검사한다 (명세 §6.3).

C-2 claim → 심층 검토 job → 사전규격 개요 attempt 순서이고, 앞이 잡으면 뒤는
부르지 않는다. 모델 슬롯 1개 보장이 이 순서에 걸려 있다.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.workers import analysis


class _Session:
    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False

    def rollback(self) -> None:  # pragma: no cover - 실패 경로 전용
        pass


overview_runners: list[int] = []


def _install(monkeypatch: pytest.MonkeyPatch, *, c2_result: Any, deep_claimed: bool) -> dict[str, int]:
    calls = {"c2": 0, "deep": 0, "overview": 0}
    overview_runners.clear()

    class _C2Worker:
        def __init__(self, *, settings: Any) -> None:
            self.settings = settings

        def run_once(self, _session: Any) -> Any:
            calls["c2"] += 1
            return c2_result

    def _deep(_session: Any, _worker_id: str) -> Any:
        calls["deep"] += 1
        return SimpleNamespace(claimed=deep_claimed)

    def _overview(_session: Any, _worker_id: str, *, runner: Any = None) -> Any:
        calls["overview"] += 1
        # runner는 poll loop 밖에서 만들어 넘어온다. 매 poll 새로 만들면 binding
        # 해석 캐시가 살아남지 못한다 (명세 §6.3).
        assert runner is not None
        overview_runners.append(id(runner))
        return SimpleNamespace(claimed=True)

    settings = SimpleNamespace(
        analysis_worker_concurrency=1,
        analysis_worker_poll_seconds=0.1,
        worker_id="test-analysis-worker",
    )
    monkeypatch.setattr(analysis, "get_settings", lambda: settings)
    monkeypatch.setattr(analysis, "configure", lambda _settings: None)
    monkeypatch.setattr(
        analysis, "assert_object_store_runtime", lambda **_kwargs: None
    )
    monkeypatch.setattr(analysis, "SessionLocal", _Session)
    monkeypatch.setattr(analysis, "C2ScreeningWorker", _C2Worker)
    monkeypatch.setattr(analysis, "run_deep_review_once", _deep)
    monkeypatch.setattr(analysis, "run_prespec_overview_once", _overview)
    monkeypatch.setattr("sys.argv", ["analysis", "--once"])
    return calls


def test_a_c2_claim_wins_the_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install(monkeypatch, c2_result=object(), deep_claimed=False)
    analysis.main()
    assert calls == {"c2": 1, "deep": 0, "overview": 0}


def test_a_deep_review_claim_keeps_the_overview_slot_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, c2_result=None, deep_claimed=True)
    analysis.main()
    assert calls == {"c2": 1, "deep": 1, "overview": 0}


def test_the_overview_slot_runs_only_when_both_queues_are_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, c2_result=None, deep_claimed=False)
    analysis.main()
    assert calls == {"c2": 1, "deep": 1, "overview": 1}


def test_the_worker_has_no_standalone_overview_entry_point() -> None:
    """개요 전용 process 진입점을 만들지 않는다 (명세 §6.3)."""

    from pathlib import Path

    module = Path(analysis.__file__).parent.parent / "deep_review" / "workers" / "prespec_overview.py"
    source = module.read_text(encoding="utf-8")
    assert "__main__" not in source
    assert "argparse" not in source


def test_the_overview_runner_is_built_once_and_reused_across_polls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """runner는 poll loop 밖에서 한 번 만들어 계속 쓴다 (명세 §6.3).

    poll마다 새로 만들면 binding 해석 캐시가 매번 비어, 큐가 비어 있을 때도
    policy를 다시 읽고 승인 경계 밖으로 identity 요청이 나간다.
    """

    calls = _install(monkeypatch, c2_result=None, deep_claimed=False)
    # `--once` 없이 두 바퀴 돌리고 두 번째 sleep에서 빠져나온다.
    monkeypatch.setattr("sys.argv", ["analysis"])
    slept = {"count": 0}

    def _sleep(_seconds: float) -> None:
        slept["count"] += 1
        if slept["count"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(analysis.time, "sleep", _sleep)

    with pytest.raises(KeyboardInterrupt):
        analysis.main()

    assert calls["overview"] == 2
    assert len(set(overview_runners)) == 1
