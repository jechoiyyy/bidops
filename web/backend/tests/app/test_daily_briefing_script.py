"""`scripts/run-daily-briefing.sh`의 호출 순서·인자 전달·실패 전파·`slack_send_failed` 감지(T11).

`test_daily_lifecycle_script.py`와 같은 방식이다: 스크립트를 임시 저장소 루트의 `scripts/`에 복사해
실행하고, 가짜 `docker`·`curl`·`python3`를 PATH 맨 앞에 둔다. 가짜들은 호출을 `calls.log`에 한 줄씩
남기고, 가짜 `docker`는 `exec -T web python -m app.lifecycle.cli build-briefing …`에 상태 디렉터리의
`cli_stdout`·`cli_exit`으로 답한다. 가짜 CLI의 stdout JSON은 실제 `build_briefing_command`의 출력 키
(`briefing_date, status, created, item_count, tracked_change_count, excluded, warnings, slack`)를
그대로 쓴다 — 실제 CLI 계약은 `app/lifecycle/cli.py`가 정본이고, `slack_send_failed`는
**종료 코드 0**과 함께 `warnings[]`로만 나오기 때문에(cli.py docstring) 스크립트가 JSON을 읽어
비0 종료로 바꾼다. 이 감지가 없으면 cron은 전송 실패를 성공으로 본다.

`--dry-run`은 cron과 같은 깨끗한 환경(`env -i HOME=… PATH=…`)에서 호출 순서만 출력하고 docker·curl·
python3를 한 번도 부르지 않는다. `docker compose port` 조회도 하지 않는다(그 조회도 실제 호출이다).

가짜 CLI·가짜 docker로는 증명되지 않는 것: 실제 web 컨테이너 안의 `build-briefing` 실행과 실제 Slack
전송. 그것은 감독 시운전(T12)의 몫이다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = "run-daily-briefing.sh"

EXIT_SLACK_SEND_FAILED = 3
EXIT_OUTPUT_UNREADABLE = 4

#: 실제 CLI 출력 키 그대로(`app/lifecycle/cli.py` `_output`). 값은 평일 정상 생성 한 건이다.
GOOD_OUTPUT = {
    "briefing_date": "2026-10-14",
    "status": "generated",
    "created": True,
    "item_count": 3,
    "tracked_change_count": 1,
    "excluded": {"hardware": 2, "election": 0, "design_only": 0, "staffing_only": 0, "region": 1, "amount_floor": 4},
    "warnings": [],
    "slack": {"sent": False, "message_ts": [], "skipped_reason": "not_requested"},
}

_FAKE_BIN = r"""#!/usr/bin/env bash
state="${FAKE_STATE:?}"
name="$(basename "$0")"
printf '%s %s\n' "${name}" "$*" >> "${state}/calls.log"
case "${name}" in
  docker)
    args="$*"
    case "${args}" in
      "compose version") exit 0 ;;
      *"exec -T web python -m app.lifecycle.cli build-briefing"*)
        [[ -f "${state}/cli_stderr" ]] && cat "${state}/cli_stderr" >&2
        [[ -f "${state}/cli_stdout" ]] && cat "${state}/cli_stdout"
        code=0
        [[ -f "${state}/cli_exit" ]] && code="$(cat "${state}/cli_exit")"
        exit "${code}" ;;
    esac
    exit 1 ;;
esac
# curl·python3 등 이 스크립트가 부르면 안 되는 도구: 부르면 호출 기록이 남고 실패한다.
exit 99
"""


@dataclass
class Env:
    root: Path
    state: Path
    bin_dir: Path

    def run(
        self,
        *args: str,
        clean_env: bool = False,
        **extra_env: str | None,
    ) -> subprocess.CompletedProcess[str]:
        """`clean_env=True`면 cron과 같은 `env -i HOME=… PATH=…`로 시작한다(`FAKE_STATE`만 더해 가짜가
        상태 디렉터리를 찾는다 — 스크립트가 읽는 값이 아니다)."""

        script = str(self.root / "scripts" / SCRIPT)
        path = f"{self.bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"
        if clean_env:
            command = [
                "env", "-i", f"HOME={self.root}", f"PATH={path}", f"FAKE_STATE={self.state}",
                shutil.which("bash") or "/bin/bash", script, *args,
            ]
            env = None
        else:
            command = ["bash", script, *args]
            env = dict(os.environ)
            env["FAKE_STATE"] = str(self.state)
            env["PATH"] = f"{self.bin_dir}{os.pathsep}{env.get('PATH', '')}"
            for key, value in extra_env.items():
                if value is None:
                    env.pop(key, None)
                else:
                    env[key] = value
        return subprocess.run(
            command, cwd=self.root, capture_output=True, text=True, env=env, timeout=60
        )

    def cli(self, output: object | str | None = None, *, exit_code: int = 0, stderr: str | None = None) -> None:
        """가짜 CLI의 stdout JSON(또는 날 문자열)·종료 코드·stderr."""

        if output is not None:
            (self.state / "cli_stdout").write_text(
                output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        (self.state / "cli_exit").write_text(str(exit_code), encoding="utf-8")
        if stderr is not None:
            (self.state / "cli_stderr").write_text(stderr, encoding="utf-8")

    def calls(self) -> list[str]:
        log = self.state / "calls.log"
        if not log.exists():
            return []
        return [line for line in log.read_text(encoding="utf-8").splitlines() if line]

    def cli_calls(self) -> list[str]:
        return [line for line in self.calls() if "app.lifecycle.cli build-briefing" in line]


def make_env(tmp_path: Path) -> Env:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / SCRIPT, root / "scripts" / SCRIPT)
    state = tmp_path / "state"
    state.mkdir()
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    for name in ("docker", "curl", "python3"):
        path = bin_dir / name
        path.write_text(_FAKE_BIN, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return Env(root=root, state=state, bin_dir=bin_dir)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    made = make_env(tmp_path)
    made.cli(GOOD_OUTPUT)
    return made


def _kst_today() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


# --- dry-run: 호출 순서 출력, 실제 호출 0 -------------------------------------------


def test_dry_run_in_a_clean_environment_prints_the_call_order_and_calls_nothing(env: Env) -> None:
    result = env.run("--date", "2026-10-14", "--send", "--dry-run", clean_env=True)

    assert result.returncode == 0, result.stderr
    out = result.stdout
    # 호출 순서: compose 확인 → web 컨테이너 안 build-briefing → JSON 검사.
    compose = out.index("docker compose version")
    cli = out.index(
        "docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.cli build-briefing "
        "--date 2026-10-14 --json --send"
    )
    check = out.index("slack_send_failed")
    assert compose < cli < check
    assert "COMPOSE_PROJECT_NAME=bidops" in out
    # 실제 호출 0: docker·curl·python3 어느 것도 불리지 않았다(`docker compose port` 포함).
    assert env.calls() == []


def test_dry_run_without_send_does_not_print_the_send_flag(env: Env) -> None:
    result = env.run("--date", "2026-10-14", "--dry-run", clean_env=True)

    assert result.returncode == 0, result.stderr
    assert "build-briefing --date 2026-10-14 --json" in result.stdout
    assert "--send" not in result.stdout
    assert env.calls() == []


def test_dry_run_does_not_require_docker_or_jq_to_exist(tmp_path: Path) -> None:
    """dry-run은 도구가 없어도 계획을 보여 준다(깨끗한 환경에서 PATH가 좁아도 실패하지 않는다)."""

    made = make_env(tmp_path)
    for name in ("docker", "curl", "python3"):
        (made.bin_dir / name).unlink()

    result = made.run("--date", "2026-10-14", "--dry-run", clean_env=True)

    assert result.returncode == 0, result.stderr
    assert made.calls() == []


# --- 인자 전달 ---------------------------------------------------------------------


def test_arguments_are_forwarded_to_the_cli_inside_the_web_container(env: Env) -> None:
    result = env.run("--date", "2026-10-14", "--send")

    assert result.returncode == 0, result.stderr
    assert env.cli_calls() == [
        "docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.cli "
        "build-briefing --date 2026-10-14 --json --send"
    ]
    # 성공하면 CLI의 JSON이 그대로 stdout에 남는다(cron 로그의 증거).
    assert json.loads(result.stdout[result.stdout.index("{"):]) == GOOD_OUTPUT


def test_without_send_the_flag_is_not_forwarded_and_default_date_is_today_in_kst(env: Env) -> None:
    before = _kst_today()
    result = env.run()
    after = _kst_today()

    assert result.returncode == 0, result.stderr
    (call,) = env.cli_calls()
    assert "--send" not in call
    assert "--dry-run" not in call
    # 브리핑 날짜 D의 기본값은 오늘(KST)이다(수집 회차는 D-1, CLI가 안다).
    date_value = re.search(r"--date (\d{4}-\d{2}-\d{2})", call)
    assert date_value is not None and date_value.group(1) in {before, after}


def test_compose_project_defaults_to_bidops_and_can_be_overridden(env: Env) -> None:
    default = env.run("--date", "2026-10-14", "--dry-run", clean_env=True)
    overridden = env.run("--date", "2026-10-14", "--dry-run", COMPOSE_PROJECT_NAME="bidops-local")

    assert "COMPOSE_PROJECT_NAME=bidops docker compose" in default.stdout
    assert "COMPOSE_PROJECT_NAME=bidops-local docker compose" in overridden.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("--date", "2026-02-30"),
        ("--date", "2026-13-01"),
        ("--date", "20261014"),
        ("--date",),
        ("--bogus",),
        ("--date", "2026-10-14", "--from-date", "2026-10-01"),
    ],
)
def test_bad_arguments_exit_2_before_any_call(env: Env, args: tuple[str, ...]) -> None:
    result = env.run(*args)

    assert result.returncode == 2
    assert env.calls() == []


def test_leap_day_is_a_valid_date(env: Env) -> None:
    result = env.run("--date", "2028-02-29", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "--date 2028-02-29" in result.stdout


def test_help_exits_zero_and_documents_the_exit_codes(env: Env) -> None:
    result = env.run("--help")

    assert result.returncode == 0
    assert "slack_send_failed" in result.stdout
    assert env.calls() == []


# --- 락·timeout은 cron 줄의 몫: 문서 예시가 두 트랙과 같은 락 파일을 쓴다 ------------------


def test_cron_example_reuses_the_track_lock_and_wraps_in_timeout() -> None:
    """스크립트는 락을 잡지 않는다(두 트랙 스크립트도 그렇다). cron 줄이 `flock`과 `timeout`을
    붙이고, 브리핑 줄은 두 트랙(수집 회차를 만드는 notices, C-2 결과를 만드는 order-plans)과
    **같은 락 파일 둘 다**를 잡는다 — 수집·적재·C-2 실행이 도는 동안 브리핑이 끼어들지 않는다."""

    text = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    cron_lines = [line for line in text.splitlines() if re.match(r"^[0-9*/,-]+( [0-9*/,-]+){4} cd /", line)]
    notices = next(line for line in cron_lines if "run-daily-lifecycle.sh --track notices" in line)
    briefing = next(line for line in cron_lines if "run-daily-briefing.sh" in line)

    plans = next(line for line in cron_lines if "run-daily-lifecycle.sh --track order-plans" in line)
    for track_line in (notices, plans):
        lock = re.search(r"flock\s+(?:-\S+\s+)*(?:\d+\s+)?(\S+\.lock)", track_line)
        assert lock is not None
        assert lock.group(1) in briefing
    assert "flock" in briefing and "timeout" in briefing and "--send" in briefing
    # 설치는 사람이 한다: 스크립트는 crontab을 부르지 않는다.
    script = (ROOT / "scripts" / SCRIPT).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:sudo\s+)?crontab\b", script, re.MULTILINE)


# --- 실패 전파 ---------------------------------------------------------------------


@pytest.mark.parametrize("code", [1, 2, 3, 137])
def test_nonzero_cli_exit_propagates_and_the_output_is_kept(env: Env, code: int) -> None:
    failed = {**GOOD_OUTPUT, "status": None, "created": False, "item_count": 0, "warnings": ["company_not_registered"]}
    env.cli(failed, exit_code=code, stderr="build-briefing failed: company_not_registered\n")

    result = env.run("--date", "2026-10-14", "--send")

    assert result.returncode == code
    assert "company_not_registered" in result.stdout
    assert "build-briefing failed: company_not_registered" in result.stderr


def test_a_cli_failure_whose_output_mentions_slack_send_failed_keeps_the_cli_exit_code(env: Env) -> None:
    """CLI가 이미 비0이면 그 코드가 우선이다(감지 코드로 덮지 않는다)."""

    env.cli({**GOOD_OUTPUT, "warnings": ["slack_send_failed"]}, exit_code=1)

    assert env.run("--date", "2026-10-14", "--send").returncode == 1


def test_docker_exec_failure_without_output_propagates(env: Env) -> None:
    (env.state / "cli_stdout").unlink()
    env.cli(exit_code=1, stderr="service \"web\" is not running\n")

    result = env.run("--date", "2026-10-14", "--send")

    assert result.returncode == 1
    assert "is not running" in result.stderr


# --- slack_send_failed: CLI는 0으로 끝나므로 스크립트가 비0으로 바꾼다 -------------------


def test_slack_send_failed_with_exit_zero_makes_the_script_exit_nonzero(env: Env) -> None:
    sent_failed = {
        **GOOD_OUTPUT,
        "warnings": ["orphan_candidate", "slack_send_failed"],
        "slack": {"sent": False, "message_ts": [], "skipped_reason": None},
    }
    env.cli(sent_failed, exit_code=0, stderr="build-briefing slack: slack_send_failed (slack_transport_error)\n")

    result = env.run("--date", "2026-10-14", "--send")

    assert result.returncode == EXIT_SLACK_SEND_FAILED
    # 브리핑은 남아 있고 `--send` 재실행이 재전송한다는 안내가 cron 로그에 남는다.
    assert "slack_send_failed" in result.stderr
    assert "--send" in result.stderr
    assert json.loads(result.stdout[result.stdout.index("{"):])["warnings"] == ["orphan_candidate", "slack_send_failed"]
    assert len(env.cli_calls()) == 1  # 스크립트가 스스로 재시도하지 않는다


@pytest.mark.parametrize(
    "warnings",
    [
        [],
        ["collection_run_missing"],
        ["run_ambiguous", "collection_run_warnings"],
        ["order_plan_provider_absent", "orphan_candidate"],
    ],
)
def test_other_warnings_are_not_failures(env: Env, warnings: list[str]) -> None:
    """수집 회차·후보 경고는 `status`로 보이는 데이터 상태이며 스크립트 실패가 아니다."""

    env.cli({**GOOD_OUTPUT, "warnings": warnings})

    result = env.run("--date", "2026-10-14", "--send")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "skipped_reason",
    ["weekend", "dry_run", "not_requested", "slack_disabled", "token_missing", "channel_missing",
     "host_not_allowed", "empty", "already_sent"],
)
def test_every_skip_reason_exits_zero(env: Env, skipped_reason: str) -> None:
    """`skipped_reason`은 전부 정상 건너뜀이다(실패는 `slack_send_failed` 하나뿐)."""

    env.cli({**GOOD_OUTPUT, "slack": {"sent": False, "message_ts": [], "skipped_reason": skipped_reason}})

    result = env.run("--date", "2026-10-14", "--send")

    assert result.returncode == 0, result.stderr
    assert skipped_reason in result.stderr  # cron 로그에서 보낸 것인지 건너뛴 것인지 보인다


def test_weekend_output_with_null_status_is_a_normal_success(env: Env) -> None:
    env.cli(
        {**GOOD_OUTPUT, "briefing_date": "2026-10-17", "status": None, "created": False, "item_count": 0,
         "tracked_change_count": 0, "excluded": {},
         "slack": {"sent": False, "message_ts": [], "skipped_reason": "weekend"}}
    )

    assert env.run("--date", "2026-10-17", "--send").returncode == 0


@pytest.mark.parametrize("stdout", ["", "not json at all", '{"warnings": "slack_send_failed"}', "[]", "null"])
def test_unreadable_or_unexpected_output_fails_closed(env: Env, stdout: str) -> None:
    """종료 코드 0이어도 전송 실패 여부를 확인할 수 없으면 성공으로 두지 않는다."""

    env.cli(stdout, exit_code=0)

    result = env.run("--date", "2026-10-14", "--send")

    assert result.returncode == EXIT_OUTPUT_UNREADABLE


def test_single_line_json_is_also_read(env: Env) -> None:
    """`--json` 한 줄 출력과 들여쓴 출력 모두 같은 감지를 탄다."""

    env.cli(json.dumps({**GOOD_OUTPUT, "warnings": ["slack_send_failed"]}, ensure_ascii=False), exit_code=0)

    assert env.run("--date", "2026-10-14", "--send").returncode == EXIT_SLACK_SEND_FAILED


# --- 사전 점검 ----------------------------------------------------------------------


def test_missing_docker_stops_before_the_cli(tmp_path: Path) -> None:
    made = make_env(tmp_path)
    (made.bin_dir / "docker").unlink()
    path = f"{made.bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"
    if shutil.which("docker", path=path):  # 실제 docker가 시스템 PATH에 있으면 이 검사는 의미가 없다
        pytest.skip("docker exists on the system PATH")

    result = made.run("--date", "2026-10-14", clean_env=True)

    assert result.returncode == 2
    assert "docker" in result.stderr
    assert made.calls() == []
