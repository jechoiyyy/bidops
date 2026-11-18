"""`scripts/cron-daily-track.sh` — crontab이 부르는 유일한 진입점(2026-11-18 독립 검증 B3).

래퍼를 임시 루트의 `scripts/`에 복사하고 그 옆에 가짜 `run-daily-lifecycle.sh`를 둔다. 가짜는
받은 인자와 래퍼가 정한 환경을 파일에 남기고 `FAKE_RC`로 끝난다(`FAKE_SLEEP`초 쉰 뒤). lock은
진짜 `flock`(Homebrew discoteq 0.4.0, `-o`·`-w`·`-E` 지원), 시간 제한은 진짜 GNU `timeout`이다.
트랙 자체의 동작은 `test_daily_lifecycle_*.py`가 본다 — 여기서는 래퍼의 설정·lock·로그·종료 코드만 본다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]

FAKE_TRACK = r"""#!/usr/bin/env bash
out="${FAKE_OUT:?}"
{
  printf 'args=%s\n' "$*"
  printf 'cwd=%s\n' "$PWD"
  for name in BIDOPS_ENV BIDOPS_WORKFLOW_WEB_URL BIDOPS_DAILY_GAP_LOOKBACK_DAYS BIDOPS_DAILY_GAP_FLOOR_DATE BIDOPS_C2_DAILY_ACTOR; do
    printf '%s=%s\n' "${name}" "${!name:-}"
  done
  printf 'path_first=%s\n' "${PATH%%:*}"
} >> "${out}"
echo "fake track output"
sleep "${FAKE_SLEEP:-0}"
exit "${FAKE_RC:-0}"
"""


@dataclass
class Cron:
    root: Path
    state: Path

    @property
    def lock(self) -> Path:
        return self.state / "daily.lock"

    @property
    def out(self) -> Path:
        return self.state / "fake-track.out"

    def run(self, *args: str, **extra: str | None) -> subprocess.CompletedProcess[str]:
        env = {
            "HOME": str(self.state / "home"),
            "PATH": "/usr/bin:/bin",  # cron의 PATH. 래퍼가 나머지를 직접 붙여야 한다.
            "BIDOPS_DAILY_LOCK_FILE": str(self.lock),
            "BIDOPS_DAILY_LOG_DIR": str(self.state / "logs"),
            "BIDOPS_DAILY_GAP_FLOOR_DATE": "2026-11-15",
            "BIDOPS_C2_DAILY_ACTOR": "cron-operator",
            "FAKE_OUT": str(self.out),
        }
        for key, value in extra.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(
            ["/bin/bash", str(self.root / "scripts" / "cron-daily-track.sh"), *args],
            capture_output=True, text=True, env=env, timeout=60,
        )

    def log(self, track: str) -> str:
        logs = list((self.state / "logs").glob(f"{track}-*.log"))
        assert len(logs) == 1, logs
        return logs[0].read_text(encoding="utf-8")

    def recorded(self) -> dict[str, str]:
        if not self.out.exists():
            return {}
        pairs = (line.split("=", 1) for line in self.out.read_text(encoding="utf-8").splitlines())
        return {key: value for key, value in pairs}

    def hold_lock(self, seconds: int = 20) -> subprocess.Popen[bytes]:
        holder = subprocess.Popen(["flock", str(self.lock), "sleep", str(seconds)], env={**os.environ, "PATH": f"/opt/homebrew/bin:{os.environ['PATH']}"})
        for _ in range(100):
            probe = subprocess.run(["flock", "-n", str(self.lock), "true"], env={**os.environ, "PATH": f"/opt/homebrew/bin:{os.environ['PATH']}"})
            if probe.returncode != 0:
                return holder
            time.sleep(0.05)
        holder.kill()
        raise AssertionError("lock holder did not take the lock")


@pytest.fixture
def cron(tmp_path: Path) -> Cron:
    if shutil.which("flock", path=f"/opt/homebrew/bin:{os.environ.get('PATH', '')}") is None:
        pytest.skip("flock is not installed")
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "cron-daily-track.sh", root / "scripts" / "cron-daily-track.sh")
    fake = root / "scripts" / "run-daily-lifecycle.sh"
    fake.write_text(FAKE_TRACK, encoding="utf-8")
    fake.chmod(0o755)
    state = tmp_path / "state"
    (state / "home").mkdir(parents=True)
    return Cron(root=root, state=state)


def _last_line(text: str) -> str:
    return text.rstrip("\n").splitlines()[-1]


@pytest.mark.parametrize("rc", [0, 2, 10])
def test_the_real_exit_status_is_the_last_log_line_and_the_wrapper_exit(cron: Cron, rc: int) -> None:
    result = cron.run("notices", FAKE_RC=str(rc))

    assert result.returncode == rc
    log = cron.log("notices")
    first = log.splitlines()[0]
    assert first.startswith("[cron] ") and " track=notices start pid=" in first
    assert "fake track output" in log
    assert _last_line(log).startswith("[cron] ") and _last_line(log).endswith(f" track=notices exit={rc}")


def test_cron_defaults_and_the_documented_path_reach_the_track(cron: Cron) -> None:
    result = cron.run("order-plans")

    assert result.returncode == 0, result.stderr
    recorded = cron.recorded()
    assert recorded["args"] == "--track order-plans --catch-up-days 3"
    assert recorded["cwd"] == str(cron.root)
    assert recorded["BIDOPS_ENV"] == "prod"
    assert recorded["BIDOPS_WORKFLOW_WEB_URL"] == "http://127.0.0.1:18788"
    assert recorded["BIDOPS_DAILY_GAP_LOOKBACK_DAYS"] == "31"
    assert recorded["BIDOPS_DAILY_GAP_FLOOR_DATE"] == "2026-11-15"
    assert recorded["BIDOPS_C2_DAILY_ACTOR"] == "cron-operator"
    assert recorded["path_first"] == "/opt/homebrew/opt/coreutils/libexec/gnubin"


def test_catch_up_days_can_be_overridden(cron: Cron) -> None:
    result = cron.run("notices", BIDOPS_DAILY_CATCH_UP_DAYS="0")

    assert result.returncode == 0, result.stderr
    assert cron.recorded()["args"] == "--track notices --catch-up-days 0"


def test_a_held_lock_ends_with_75_logged_and_nothing_run(cron: Cron) -> None:
    holder = cron.hold_lock()
    try:
        result = cron.run("order-plans", BIDOPS_DAILY_LOCK_WAIT_SECONDS="1")
    finally:
        holder.kill()
        holder.wait()

    assert result.returncode == 75
    log = cron.log("order-plans")
    assert "lock still held after 1s" in log
    assert _last_line(log).endswith(" track=order-plans exit=75")
    assert cron.recorded() == {}


def test_both_tracks_share_one_lock_file(cron: Cron) -> None:
    holder = cron.hold_lock()
    try:
        notices = cron.run("notices", BIDOPS_DAILY_LOCK_WAIT_SECONDS="1")
    finally:
        holder.kill()
        holder.wait()

    assert notices.returncode == 75
    assert f"lock={cron.lock}" in cron.log("notices").splitlines()[0]


def test_the_timeout_is_logged_as_124(cron: Cron) -> None:
    result = cron.run("notices", BIDOPS_DAILY_TRACK_TIMEOUT="1", FAKE_SLEEP="10")

    assert result.returncode == 124
    log = cron.log("notices")
    assert "hit the timeout 1" in log
    assert _last_line(log).endswith(" track=notices exit=124")


@pytest.mark.parametrize(
    "track,extra,missing",
    [
        ("notices", {"BIDOPS_DAILY_GAP_FLOOR_DATE": None}, "BIDOPS_DAILY_GAP_FLOOR_DATE is required"),
        ("order-plans", {"BIDOPS_C2_DAILY_ACTOR": None}, "BIDOPS_C2_DAILY_ACTOR is required"),
        ("order-plans", {"BIDOPS_C2_DAILY_ACTOR": "<담당자 이름>"}, "BIDOPS_C2_DAILY_ACTOR still holds a placeholder"),
        ("notices", {"BIDOPS_DAILY_GAP_FLOOR_DATE": "<YYYY-MM-DD>"}, "BIDOPS_DAILY_GAP_FLOOR_DATE still holds a placeholder"),
    ],
)
def test_missing_required_settings_fail_clearly_without_running(
    cron: Cron, track: str, extra: dict[str, str | None], missing: str
) -> None:
    result = cron.run(track, **extra)

    assert result.returncode == 2
    assert missing in result.stderr
    log = cron.log(track)
    assert missing in log
    assert _last_line(log).endswith(f" track={track} exit=2")
    assert cron.recorded() == {}


def test_notices_does_not_need_an_actor(cron: Cron) -> None:
    result = cron.run("notices", BIDOPS_C2_DAILY_ACTOR=None)

    assert result.returncode == 0, result.stderr


def test_dry_run_passes_through_without_lock_or_log(cron: Cron) -> None:
    holder = cron.hold_lock()
    try:
        result = cron.run("order-plans", "--dry-run", BIDOPS_DAILY_LOCK_WAIT_SECONDS="1")
    finally:
        holder.kill()
        holder.wait()

    assert result.returncode == 0, result.stderr
    assert cron.recorded()["args"] == "--track order-plans --catch-up-days 3 --dry-run"
    assert "a cron run would execute: flock -o -w 1 -E 75" in result.stdout
    assert "fake track output" in result.stdout
    assert not (cron.state / "logs").exists()


def test_dry_run_still_requires_the_settings(cron: Cron) -> None:
    result = cron.run("notices", "--dry-run", BIDOPS_DAILY_GAP_FLOOR_DATE=None)

    assert result.returncode == 2
    assert "BIDOPS_DAILY_GAP_FLOOR_DATE is required" in result.stderr
    assert cron.recorded() == {}


def test_print_crontab_names_this_checkout_and_both_tracks(cron: Cron) -> None:
    result = cron.run("--print-crontab")

    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line and not line.startswith("#")]
    assert lines == [
        f"30 6 * * * BIDOPS_DAILY_GAP_FLOOR_DATE=<YYYY-MM-DD> {cron.root}/scripts/cron-daily-track.sh notices",
        f"0 7 * * * BIDOPS_DAILY_GAP_FLOOR_DATE=<YYYY-MM-DD> BIDOPS_C2_DAILY_ACTOR=<담당자 이름> {cron.root}/scripts/cron-daily-track.sh order-plans",
    ]


@pytest.mark.parametrize("args", [[], ["weekly"], ["notices", "order-plans"]])
def test_bad_arguments_fail(cron: Cron, args: list[str]) -> None:
    result = cron.run(*args)

    assert result.returncode == 2
    assert cron.recorded() == {}
