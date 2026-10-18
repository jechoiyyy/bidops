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


def _install(monkeypatch: pytest.MonkeyPatch, *, c2_result: Any, deep_claimed: bool, fit_claimed: bool = False, assumption_claimed: bool = False, proposal_claimed: bool = False) -> dict[str, int]:
    calls = {"c2": 0, "deep": 0, "fit": 0, "overview": 0, "assumption": 0, "proposal": 0}

    class _C2Worker:
        def __init__(self, *, settings: Any) -> None:
            self.settings = settings

        def run_once(self, _session: Any) -> Any:
            calls["c2"] += 1
            return c2_result

    def _deep(_session: Any, _worker_id: str) -> Any:
        calls["deep"] += 1
        return SimpleNamespace(claimed=deep_claimed)

    class _FitRunner:
        def __init__(self, **kwargs):
            pass
        def run_once(self, session, worker_id):
            calls["fit"] += 1
            return fit_claimed

    def _overview(_session: Any, _worker_id: str) -> Any:
        calls["overview"] += 1
        # 개요 슬롯의 결과는 identity 실패 여부까지 알린다 (backoff 입력).
        return SimpleNamespace(claimed=False, identity_error=None)

    settings = SimpleNamespace(
        analysis_worker_concurrency=1,
        analysis_worker_poll_seconds=0.1,
        worker_id="test-analysis-worker",
        gpu_busy_limit_seconds=0.0,
        gpu_rest_seconds=0.0,
    )
    monkeypatch.setattr(analysis, "get_settings", lambda: settings)
    monkeypatch.setattr(analysis, "configure", lambda _settings: None)
    monkeypatch.setattr(
        analysis, "assert_object_store_runtime", lambda **_kwargs: None
    )
    monkeypatch.setattr(analysis, "SessionLocal", _Session)
    monkeypatch.setattr(analysis, "C2ScreeningWorker", _C2Worker)
    monkeypatch.setattr(analysis, "PreSpecCompanyFitRunner", _FitRunner)
    def _assumption(_session, _worker_id):
        calls["assumption"] += 1
        return assumption_claimed
    monkeypatch.setattr(analysis, "run_assumption_analysis_once", _assumption)
    monkeypatch.setattr(analysis, "run_deep_review_once", _deep)
    monkeypatch.setattr(analysis, "run_prespec_overview_once", _overview)

    def _proposal(_session, _worker_id):
        calls["proposal"] += 1
        return proposal_claimed
    monkeypatch.setattr(analysis, "run_proposal_once", _proposal)
    monkeypatch.setattr("sys.argv", ["analysis", "--once"])
    return calls


def test_a_c2_claim_wins_the_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install(monkeypatch, c2_result=object(), deep_claimed=False)
    analysis.main()
    assert calls == {"c2": 1, "deep": 0, "fit": 0, "overview": 0, "assumption": 0, "proposal": 0}


def test_a_deep_review_claim_keeps_the_overview_slot_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, c2_result=None, deep_claimed=True)
    analysis.main()
    assert calls == {"c2": 1, "deep": 1, "fit": 0, "overview": 0, "assumption": 0, "proposal": 0}


def test_the_overview_slot_runs_only_when_both_queues_are_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, c2_result=None, deep_claimed=False)
    analysis.main()
    assert calls == {"c2": 1, "deep": 1, "fit": 1, "overview": 1, "assumption": 1, "proposal": 1}


def test_company_fit_claim_keeps_overview_slot_closed(monkeypatch):
    calls = _install(monkeypatch, c2_result=None, deep_claimed=False, fit_claimed=True)
    analysis.main()
    assert calls == {"c2": 1, "deep": 1, "fit": 1, "overview": 0, "assumption": 1, "proposal": 0}


def test_the_worker_has_no_standalone_overview_entry_point() -> None:
    """개요 전용 process 진입점을 만들지 않는다 (명세 §6.3)."""

    from pathlib import Path

    module = Path(analysis.__file__).parent.parent / "deep_review" / "workers" / "prespec_overview.py"
    source = module.read_text(encoding="utf-8")
    assert "__main__" not in source
    assert "argparse" not in source


def test_assumption_claim_occupies_shared_slot(monkeypatch):
    calls = _install(monkeypatch, c2_result=None, deep_claimed=False, assumption_claimed=True)
    analysis.main()
    assert calls == {"c2": 1, "deep": 1, "assumption": 1, "fit": 0, "overview": 0, "proposal": 0}


def test_rl04_proposal_section_takes_the_shared_slot_last(monkeypatch):
    """RL-04 STEP-005: the proposal queue runs only after every other slot found nothing."""

    calls = _install(monkeypatch, c2_result=None, deep_claimed=False, proposal_claimed=True)
    analysis.main()
    assert calls == {"c2": 1, "deep": 1, "assumption": 1, "fit": 1, "overview": 1, "proposal": 1}
    calls = _install(monkeypatch, c2_result=None, deep_claimed=False, assumption_claimed=True)
    analysis.main()
    assert calls["proposal"] == 0
