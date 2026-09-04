from __future__ import annotations

from types import SimpleNamespace

from app.screening.cli import main


ARGS = [
    "run-one", "--run-id", "run-1", "--notice-id", "notice-1",
    "--policy-version", "policy-v1", "--profile-source", "current",
    "--requested-by", "tester",
]


def _created(status: str = "대기") -> SimpleNamespace:
    return SimpleNamespace(
        execution_id="scr-" + "a" * 32,
        status=status,
        model_name="qwen3.8-27B",
        model_digest="a" * 64,
        profile_version="company-profile.sha256:" + "b" * 64,
        profile_digest="b" * 64,
        artifact_dir="data/screening-executions/scr-" + "a" * 32,
        input_artifact_path="data/screening-executions/scr-" + "a" * 32 + "/screening-input.json",
    )


class FakeService:
    def __init__(self, created: SimpleNamespace):
        self.created = created

    def create_execution(self, **_kwargs):
        return self.created


class FakeWorker:
    def __init__(self, final: SimpleNamespace):
        self.final = final
        self.target: str | None = None

    def run_until(self, execution_id: str):
        self.target = execution_id
        return self.final


def test_run_one_without_wait_prints_safe_binding(capsys):
    created = _created()
    code = main(ARGS, service=FakeService(created))
    assert code == 0
    output = capsys.readouterr().out
    assert created.execution_id in output
    assert created.model_digest in output and created.profile_digest in output
    assert "result_artifact_path" in output and "failure_artifact_path" in output
    assert "prompt" not in output and "company profile" not in output


def test_run_one_wait_maps_terminal_exit_codes_and_reuses_target(capsys):
    for status, expected in (("성공", 0), ("부분 성공", 2), ("실패", 1), ("중단됨", 1)):
        created = _created()
        final = _created(status)
        worker = FakeWorker(final)
        assert main([*ARGS, "--wait"], service=FakeService(created), worker=worker) == expected
        assert worker.target == created.execution_id
    assert "중단됨" in capsys.readouterr().out


def test_invalid_profile_source_is_rejected_before_service(capsys):
    class ExplodingService:
        def create_execution(self, **_kwargs):
            raise AssertionError("must not enqueue")

    bad_args = [
        "run-one", "--run-id", "run-1", "--notice-id", "notice-1",
        "--policy-version", "policy-v1", "--profile-source", "git:bad",
        "--requested-by", "tester",
    ]
    assert main(bad_args, service=ExplodingService()) == 1
    assert "input_error" in capsys.readouterr().out
