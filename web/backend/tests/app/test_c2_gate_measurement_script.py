"""`scripts/run-c2-gate-measurement.sh`(S5c)를 본다
(`docs/0918_daily-operation/spec.md` §4.1·§4.2, `docs/contracts.md` "품질 게이트 REST").

가짜 `curl`·`docker`·`python3`와 임시 루트는 `test_daily_lifecycle_script.py`의
`make_env`/`Env`/`_FAKE_BIN`을 그대로 빌린다. 그 가짜 curl은 `GET
/api/order-plan-screening/quality-gates`를 모르므로, 이 모듈은 `_FAKE_BIN`의 curl
case 블록에 그 경로 하나만 더한 사본을 만들어 쓴다(파일 이름은 그대로 `curl`이어야
`basename "$0"`로 갈라지는 바깥 case가 맞는다). `test_daily_lifecycle_script.py`·
`test_daily_c2_script.py`는 고치지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.app.test_daily_lifecycle_script import _FAKE_BIN, ROOT, Env, make_env

NAMESPACE = uuid.UUID("4e9f787e-8b77-500c-8957-fe046c52e9cf")
GATE_ID = "c2gate-" + "ab" * 16
POLICY_VERSION = "v3"

# `_FAKE_BIN`의 `case "${method} ${path}" in` 바로 다음에 끼워 넣는 한 arm. 없는
# gate 파일은 빈 items로 응답해 "찾지 못함" 경로를 그대로 타게 한다.
_QUALITY_GATES_ARM = (
    '      "GET /api/order-plan-screening/quality-gates")\n'
    "        respond 200 \"$(cat \"${state}/gates.json\" 2>/dev/null "
    "|| printf '{\"schema_version\":\"order-plan-quality-gate-list-response.v1\",\"items\":[]}')\" ;;\n"
)


def _patched_fake_curl() -> str:
    marker = 'case "${method} ${path}" in\n'
    assert _FAKE_BIN.count(marker) == 1, "test_daily_lifecycle_script._FAKE_BIN의 curl case 표식이 바뀌었다"
    return _FAKE_BIN.replace(marker, marker + _QUALITY_GATES_ARM, 1)


def _gate_view(gate_id: str, measurement_run_ids: list[str]) -> dict:
    zeros = "0" * 64
    return {
        "gate_id": gate_id,
        "policy_version": POLICY_VERSION,
        "policy_sha256": zeros,
        "binding_sha256": zeros,
        "gold_manifest_sha256": zeros,
        "gold_artifact_sha256": zeros,
        "gold_status": "reviewed",
        "scoring_input_sha256": zeros,
        "evaluation_basis": "product_rerun",
        "scoring_unit": "per_published_day",
        "measurement_run_ids": measurement_run_ids,
        "required_pass_count": 2,
        "thresholds": {
            "recall_pct": None,
            "precision_pct": None,
            "important_missed_max": None,
            "review_load_max": None,
        },
        "created_by": "tester",
        "created_at": "2026-09-18T00:00:00Z",
        "latest_evaluation": None,
        "measurement_executions": [],
    }


def set_gate(env: Env, gate_id: str, measurement_run_ids: list[str]) -> None:
    (env.state / "gates.json").write_text(
        json.dumps(
            {
                "schema_version": "order-plan-quality-gate-list-response.v1",
                "producer": "quality-gate-api",
                "consumer": "human-review-client",
                "policy_version": POLICY_VERSION,
                "items": [_gate_view(gate_id, measurement_run_ids)],
            }
        ),
        encoding="utf-8",
    )


def run_gate(env: Env, *args: str, **extra_env: str | None) -> subprocess.CompletedProcess[str]:
    process_env = dict(os.environ)
    process_env["BIDOPS_WEB_PORT"] = "18787"
    process_env.pop("BIDOPS_WORKFLOW_WEB_URL", None)
    process_env["FAKE_STATE"] = str(env.state)
    process_env["PATH"] = f"{env.bin_dir}{os.pathsep}{process_env.get('PATH', '')}"
    process_env["BIDOPS_C2_GATE_ACTOR"] = "gate-operator"
    process_env["BIDOPS_C2_DAILY_POLL_INTERVAL_SECONDS"] = "0"
    process_env.pop("BIDOPS_C2_DAILY_ACTOR", None)
    for key, value in extra_env.items():
        if value is None:
            process_env.pop(key, None)
        else:
            process_env[key] = value
    return subprocess.run(
        ["bash", str(env.root / "scripts" / "run-c2-gate-measurement.sh"), *args],
        cwd=env.root,
        capture_output=True,
        text=True,
        env=process_env,
        timeout=60,
    )


def _request_id(gate_id: str, pass_num: int, attempt: int, run_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"gate-measurement|{gate_id}|pass{pass_num}|attempt{attempt}|{run_id}"))


@pytest.fixture
def env(tmp_path: Path) -> Env:
    base = make_env(tmp_path)
    shutil.copy2(ROOT / "scripts" / "run-c2-gate-measurement.sh", base.root / "scripts" / "run-c2-gate-measurement.sh")
    curl_path = base.bin_dir / "curl"
    curl_path.write_text(_patched_fake_curl(), encoding="utf-8")
    curl_path.chmod(curl_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return base


# --- dry-run -----------------------------------------------------------------


def test_dry_run_prints_runs_and_request_ids_without_any_call(env: Env) -> None:
    result = run_gate(
        env,
        "--policy-version", POLICY_VERSION,
        "--gate-id", GATE_ID,
        "--pass", "1",
        "--dry-run",
        "--measurement-runs", "run-a,run-b",
        BIDOPS_C2_GATE_ACTOR=None,
    )

    assert result.returncode == 0, result.stderr
    assert "BIDOPS_C2_GATE_ACTOR is not set" in result.stdout
    assert f"would execute run-a request_id={_request_id(GATE_ID, 1, 1, 'run-a')}" in result.stdout
    assert f"would execute run-b request_id={_request_id(GATE_ID, 1, 1, 'run-b')}" in result.stdout
    assert env.calls() == []
    assert env.posts() == []


def test_measurement_runs_option_is_rejected_outside_dry_run(env: Env) -> None:
    result = run_gate(
        env,
        "--policy-version", POLICY_VERSION,
        "--gate-id", GATE_ID,
        "--pass", "1",
        "--measurement-runs", "run-a",
    )

    assert result.returncode != 0
    assert "--measurement-runs is dry-run only" in result.stderr
    assert env.calls() == []


# --- request_id: 결정적, attempt마다 다름 -------------------------------------


def test_request_id_is_deterministic_and_varies_with_attempt(env: Env) -> None:
    common_args = ["--policy-version", POLICY_VERSION, "--gate-id", GATE_ID, "--pass", "1",
                   "--dry-run", "--measurement-runs", "run-a"]
    first = run_gate(env, *common_args, "--attempt", "1")
    again = run_gate(env, *common_args, "--attempt", "1")
    other_attempt = run_gate(env, *common_args, "--attempt", "2")

    assert first.returncode == 0, first.stderr
    assert again.returncode == 0, again.stderr
    assert other_attempt.returncode == 0, other_attempt.stderr
    expected_attempt_1 = _request_id(GATE_ID, 1, 1, "run-a")
    expected_attempt_2 = _request_id(GATE_ID, 1, 2, "run-a")
    assert f"request_id={expected_attempt_1}" in first.stdout
    assert f"request_id={expected_attempt_1}" in again.stdout
    assert f"request_id={expected_attempt_2}" in other_attempt.stdout
    assert expected_attempt_1 != expected_attempt_2


# --- happy path: 회차 3개 모두 성공 -------------------------------------------


def test_all_runs_succeed_posts_three_times_in_order_and_prints_final_json(env: Env) -> None:
    set_gate(env, GATE_ID, ["run-a", "run-b", "run-c"])

    result = run_gate(env, "--policy-version", POLICY_VERSION, "--gate-id", GATE_ID, "--pass", "1")

    assert result.returncode == 0, result.stderr
    posts = env.execution_posts()
    assert [post["body"]["source_run_id"] for post in posts] == ["run-a", "run-b", "run-c"]
    for post in posts:
        headers = {h.split(": ", 1)[0]: h.split(": ", 1)[1] for h in post["headers"]}
        assert headers["X-BidOps-Trigger"] == "gate_measurement"
    assert [post["body"]["request_id"] for post in posts] == [
        _request_id(GATE_ID, 1, 1, "run-a"),
        _request_id(GATE_ID, 1, 1, "run-b"),
        _request_id(GATE_ID, 1, 1, "run-c"),
    ]
    last_line = result.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload["gate_id"] == GATE_ID
    assert payload["pass"] == 1
    assert payload["attempt"] == 1
    assert [item["source_run_id"] for item in payload["executions"]] == ["run-a", "run-b", "run-c"]
    assert all(item["execution_id"] for item in payload["executions"])
    assert env.draw_posts() == []  # 게이트 측정은 감사 표본 draw를 하지 않는다


# --- 실패·보류는 멈춘다 --------------------------------------------------------


def test_second_run_failure_stops_before_a_third_post(env: Env) -> None:
    set_gate(env, GATE_ID, ["run-a", "run-b", "run-c"])
    env.outcomes("성공", "실패")

    result = run_gate(env, "--policy-version", POLICY_VERSION, "--gate-id", GATE_ID, "--pass", "1")

    assert result.returncode != 0
    assert "run-b" in result.stderr
    assert "실패" in result.stderr
    posts = env.execution_posts()
    assert [post["body"]["source_run_id"] for post in posts] == ["run-a", "run-b"]


def test_partial_success_is_a_hold_reason_and_stops(env: Env) -> None:
    set_gate(env, GATE_ID, ["run-a", "run-b"])
    env.outcomes("부분 성공")

    result = run_gate(env, "--policy-version", POLICY_VERSION, "--gate-id", GATE_ID, "--pass", "1")

    assert result.returncode != 0
    assert "부분 성공" in result.stderr
    posts = env.execution_posts()
    assert [post["body"]["source_run_id"] for post in posts] == ["run-a"]


# --- 입력 검증 -----------------------------------------------------------------


def test_gate_not_found_for_policy_version_exits_non_zero(env: Env) -> None:
    set_gate(env, "c2gate-" + "cd" * 16, ["run-a"])

    result = run_gate(env, "--policy-version", POLICY_VERSION, "--gate-id", GATE_ID, "--pass", "1")

    assert result.returncode != 0
    assert GATE_ID in result.stderr
    assert env.execution_posts() == []


def test_missing_actor_does_not_start(env: Env) -> None:
    set_gate(env, GATE_ID, ["run-a"])

    result = run_gate(
        env, "--policy-version", POLICY_VERSION, "--gate-id", GATE_ID, "--pass", "1", BIDOPS_C2_GATE_ACTOR=None
    )

    assert result.returncode != 0
    assert "BIDOPS_C2_GATE_ACTOR is required" in result.stderr
    assert env.calls() == []


def test_invalid_pass_value_exits_non_zero(env: Env) -> None:
    result = run_gate(env, "--policy-version", POLICY_VERSION, "--gate-id", GATE_ID, "--pass", "3")

    assert result.returncode != 0
    assert "--pass" in result.stderr
    assert env.calls() == []
