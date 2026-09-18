"""`scripts/run-daily-lifecycle.sh`의 트랙 분리·전일 기준·1일 창·`--collect-only`를 본다
(S9a, `docs/0918_daily-operation/spec.md` §8).

`--dry-run`만 검사한다 — 실제 수집·적재는 G2B API·docker·web 컨테이너가 필요하고
이 패키지의 범위 밖이다(C-2, 자동 실행 확인, 회차 조회, `-retryN`, 따라잡기는
뒤 패키지 몫). `BIDOPS_WEB_PORT`를 주고 가짜 `docker`·`python3`·`curl`을
PATH 맨 앞에 둬서, 공통 스크립트(`manual-workflow-common.sh`)의 초기 포트 조회가
실제 docker를 부르지 않게 하고, dry-run이 아무 외부 명령도 실행하지 않는다는
계약을 확인한다.
"""

from __future__ import annotations

import os
import stat
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "run-daily-lifecycle.sh"

_FAKE_BIN_TEMPLATE = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log_path}"
exit 1
"""


@pytest.fixture
def fake_bin_dir(tmp_path: Path) -> Path:
    """호출되면 인자를 로그 파일에 한 줄 쓰고 exit 1하는 가짜 docker/python3/curl."""

    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    log_path = tmp_path / "fake-calls.log"
    for name in ("docker", "python3", "curl"):
        script_path = bin_dir / name
        script_path.write_text(
            _FAKE_BIN_TEMPLATE.format(log_path=log_path), encoding="utf-8"
        )
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run(args: list[str], fake_bin_dir: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["BIDOPS_WEB_PORT"] = "18787"
    env["PATH"] = f"{fake_bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _log_lines(fake_bin_dir: Path) -> list[str]:
    log_path = fake_bin_dir.parent / "fake-calls.log"
    if not log_path.exists():
        return []
    return [line for line in log_path.read_text(encoding="utf-8").splitlines() if line]


def test_notices_dry_run_prints_one_day_inclusive_window(fake_bin_dir: Path) -> None:
    result = _run(["--track", "notices", "--date", "2026-09-17", "--dry-run"], fake_bin_dir)
    assert result.returncode == 0, result.stderr
    assert "lifecycle-20260917-notices" in result.stdout
    assert "--from-date 2026-09-17 --to-date 2026-09-17" in result.stdout
    assert "refresh_fetch_eligibility" in result.stdout
    assert "collect_order_plans.py" not in result.stdout


def test_order_plans_dry_run_prints_one_day_exclusive_window(fake_bin_dir: Path) -> None:
    result = _run(["--track", "order-plans", "--date", "2026-09-17", "--dry-run"], fake_bin_dir)
    assert result.returncode == 0, result.stderr
    assert "lifecycle-20260917-plans" in result.stdout
    assert "--from-date 2026-09-17 --to-date 2026-09-18" in result.stdout
    assert "collect_notices.py" not in result.stdout
    assert "refresh_fetch_eligibility" not in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["--track", "notices", "--date", "2026-09-17", "--dry-run"],
        ["--track", "order-plans", "--date", "2026-09-17", "--dry-run"],
    ],
)
def test_dry_run_never_calls_docker_python3_or_curl(args: list[str], fake_bin_dir: Path) -> None:
    result = _run(args, fake_bin_dir)
    assert result.returncode == 0, result.stderr
    assert _log_lines(fake_bin_dir) == []


def test_missing_track_fails_with_required_message(fake_bin_dir: Path) -> None:
    result = _run(["--date", "2026-09-17", "--dry-run"], fake_bin_dir)
    assert result.returncode != 0
    assert "--track is required" in result.stderr


def test_invalid_track_value_fails(fake_bin_dir: Path) -> None:
    result = _run(["--track", "foo", "--dry-run"], fake_bin_dir)
    assert result.returncode != 0
    assert "--track must be order-plans or notices" in result.stderr


def test_collect_only_without_run_suffix_fails(fake_bin_dir: Path) -> None:
    result = _run(["--track", "order-plans", "--collect-only", "--dry-run"], fake_bin_dir)
    assert result.returncode != 0
    assert "requires --run-suffix" in result.stderr


def test_run_suffix_without_collect_only_fails(fake_bin_dir: Path) -> None:
    result = _run(["--track", "notices", "--run-suffix", "x", "--dry-run"], fake_bin_dir)
    assert result.returncode != 0
    assert "only valid with --collect-only" in result.stderr


def test_run_suffix_retry_n_is_rejected(fake_bin_dir: Path) -> None:
    result = _run(
        ["--track", "notices", "--collect-only", "--run-suffix", "retry1", "--dry-run"],
        fake_bin_dir,
    )
    assert result.returncode != 0
    assert "reserved for recollection" in result.stderr


def test_collect_only_dry_run_skips_ingest_and_uses_suffixed_run_id(fake_bin_dir: Path) -> None:
    result = _run(
        [
            "--track", "order-plans",
            "--collect-only",
            "--run-suffix", "late2",
            "--date", "2026-09-17",
            "--dry-run",
        ],
        fake_bin_dir,
    )
    assert result.returncode == 0, result.stderr
    assert "lifecycle-20260917-plans-late2" in result.stdout
    assert "collect-only" in result.stdout
    assert "ingest.cli" not in result.stdout


def test_default_reference_day_is_yesterday_kst(fake_bin_dir: Path) -> None:
    # 자정 경계 flake를 피하려고 실행 전후 두 번 계산해 둘 중 하나와 일치하면 통과로 한다.
    before = datetime.now(ZoneInfo("Asia/Seoul")).date() - timedelta(days=1)
    result = _run(["--track", "notices", "--dry-run"], fake_bin_dir)
    after = datetime.now(ZoneInfo("Asia/Seoul")).date() - timedelta(days=1)
    assert result.returncode == 0, result.stderr

    candidates = {before.strftime("lifecycle-%Y%m%d-notices"), after.strftime("lifecycle-%Y%m%d-notices")}
    assert any(candidate in result.stdout for candidate in candidates)
