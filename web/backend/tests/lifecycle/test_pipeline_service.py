from __future__ import annotations

import io
import threading
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.core.config import Settings
from app.lifecycle.models import Run
from app.lifecycle.services.pipeline import PipelineBusyError, PipelineService


class FakeProcess:
    def __init__(self, output: str = "완료\n", error: str = "", exit_code: int = 0, release=None):
        self.stdout = io.StringIO(output)
        self.stderr = io.StringIO(error)
        self.exit_code = exit_code
        self.release = release

    def wait(self):
        if self.release is not None:
            self.release.wait(timeout=2)
        return self.exit_code

    def poll(self):
        return self.exit_code

    def kill(self):
        return None


def source_run(tmp_path: Path) -> tuple[Settings, Run, Path]:
    settings = Settings(bidops_root=tmp_path, g2b_api_key="super-secret-key")
    directory = settings.bidops_root / "data" / "runs" / "20260817-20260823"
    (directory / "raw").mkdir(parents=True)
    run = Run(
        id="20260817-20260823--20260824T000000Z",
        window_from=date(2026, 8, 17),
        window_to=date(2026, 8, 23),
        timezone="Asia/Seoul",
        generated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )
    return settings, run, directory


def test_stage_commands_are_argument_arrays_and_from_raw_uses_new_snapshot(tmp_path):
    settings, run, directory = source_run(tmp_path)
    calls = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    service = PipelineService(settings, popen=popen)
    service._reload = lambda execution: None
    execution = service.start(run, "collect", from_raw=True)
    service.wait(execution.execution_id, timeout=2)

    assert calls[0][0][:2] == ["python3", "skills/bidops-collect/scripts/collect_notices.py"]
    assert "--from-raw" in calls[0][0]
    assert calls[0][1]["shell"] is False
    assert execution.target_directory != directory
    assert (execution.target_directory / "raw").is_symlink()

    (directory / "collected-notices.json").write_text("{}", encoding="utf-8")
    sample = service.start(run, "sample")
    service.wait(sample.execution_id, timeout=2)
    assert calls[1][0][:2] == ["python3", "skills/bidops-collect/scripts/select_validation_sample.py"]
    assert calls[1][0][-2:] == ["--output", str(directory / "validation-set.json")]

    (directory / "screening-results.json").write_text("{}", encoding="utf-8")
    report = service.start(run, "report")
    service.wait(report.execution_id, timeout=2)
    assert calls[2][0][:2] == ["python3", "skills/bidops-report/scripts/render_report.py"]
    assert "reports/20260817-20260823" in calls[2][0][-1]


def test_same_run_cannot_start_two_processes(tmp_path):
    settings, run, _ = source_run(tmp_path)
    release = threading.Event()

    def popen(command, **kwargs):
        return FakeProcess(release=release)

    service = PipelineService(settings, popen=popen)
    service._reload = lambda execution: None
    first = service.start(run, "collect", from_raw=True)
    with pytest.raises(PipelineBusyError) as error:
        service.start(run, "collect", from_raw=True)
    assert error.value.execution_id == first.execution_id
    release.set()
    service.wait(first.execution_id, timeout=2)


def test_log_lines_mask_secret_values(tmp_path):
    settings, run, _ = source_run(tmp_path)

    def popen(command, **kwargs):
        return FakeProcess(output="BIDOPS_G2B_API_KEY=super-secret-key\n", error="WARN serviceKey=super-secret-key\n")

    service = PipelineService(settings, popen=popen)
    service._reload = lambda execution: None
    execution = service.start(run, "collect", from_raw=True)
    service.wait(execution.execution_id, timeout=2)

    messages = [line.message for line in execution.lines]
    assert messages
    assert all("super-secret-key" not in message for message in messages)
    assert any(line.level == "warning" for line in execution.lines)
