"""`scripts/run-daily-c2.sh`와 발주계획 트랙의 C-2 실행·감사 표본 draw 연결(S9c)을 본다
(`docs/0918_daily-operation/spec.md` §8, `docs/contracts.md` "C-2 일일 운영 계약").

가짜 `curl`·`docker`·`python3`와 임시 루트는 `test_daily_lifecycle_script.py`의 것을 그대로 쓴다.
가짜 REST는 실행 생성 때 `outcomes`에 적힌 terminal 상태(기본 `성공`)를 첫 상세 조회에서 돌려준다.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from app.core.config import Settings
from tests.app.test_daily_lifecycle_script import Env, make_env

GUIDANCE = "policy를 교체하면 자동 실행이 멈춥니다. 새 버전에서 다시 켜야 합니다."
NAMESPACE = uuid.UUID("4e9f787e-8b77-500c-8957-fe046c52e9cf")
RUN = "lifecycle-20260917-plans"


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return make_env(tmp_path)


def _ready_run(env: Env, run_id: str = RUN, *, total: int = 2) -> None:
    """적재까지 끝난 발주계획 회차."""

    env.plans_dir(run_id, complete=True, total=total)
    env.row(run_id)


def _header(post: dict, name: str) -> str | None:
    for header in post["headers"]:
        key, _, value = header.partition(": ")
        if key == name:
            return value
    return None


def _request_id(run_id: str, policy_version: str, attempt: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{run_id}|{policy_version}|{attempt}"))


# --- 자동 실행 확인: 꺼져 있으면 수집하지 않는다 --------------------------------


def test_before_human_decisions_the_order_plans_track_always_ends_daily_trigger_off(env: Env) -> None:
    # 환경 cap의 기본값이 false이고, 가짜 REST의 기본 답도 그 서버의 답(env_cap_off)이다.
    assert Settings.model_fields["c2_daily_trigger_enabled"].default is False

    result = env.run("--track", "order-plans", "--date", "2026-09-17")

    assert result.returncode == 0, result.stderr
    assert "daily_trigger_off: env_cap_off,no_active_policy" in result.stdout
    assert GUIDANCE in result.stdout
    assert env.collected() == []
    assert env.ingested() == []
    assert env.posts() == []
    assert not (env.runs / RUN).exists()


@pytest.mark.parametrize(
    "reasons",
    [
        ["env_cap_off"],
        ["switch_off"],
        ["switch_bound_to_other_version"],
        ["quality_gate_not_passed"],
        ["execution_transport_not_allowed"],
        ["policy_file_missing"],
    ],
)
def test_each_trigger_off_reason_is_printed_and_nothing_is_collected_or_executed(
    reasons: list[str], env: Env
) -> None:
    env.trigger(enabled=False, reasons=reasons)
    _ready_run(env, "lifecycle-20260916-plans")

    result = env.run("--track", "order-plans", "--from-date", "2026-09-16", "--to-date", "2026-09-17")

    assert result.returncode == 0, result.stderr
    assert f"daily_trigger_off: {reasons[0]}" in result.stdout
    assert GUIDANCE in result.stdout
    assert env.collected() == []
    assert env.posts() == []
    # 날짜 범위여도 확인은 시작 때 한 번이다.
    assert sum("/daily-trigger" in line for line in env.calls()) == 1


def test_missing_actor_does_not_start_the_order_plans_track(env: Env) -> None:
    env.trigger_on()

    result = env.run("--track", "order-plans", "--date", "2026-09-17", BIDOPS_C2_DAILY_ACTOR=None)

    assert result.returncode != 0
    assert "BIDOPS_C2_DAILY_ACTOR is required" in result.stderr
    assert env.calls() == []


def test_notices_track_and_collect_only_do_not_need_the_actor_or_the_trigger(env: Env) -> None:
    notices = env.run("--track", "notices", "--date", "2026-09-17", BIDOPS_C2_DAILY_ACTOR=None)
    collect_only = env.run(
        "--track", "order-plans", "--collect-only", "--run-suffix", "m0", "--date", "2026-09-17",
        BIDOPS_C2_DAILY_ACTOR=None,
    )

    assert notices.returncode == 0, notices.stderr
    assert collect_only.returncode == 0, collect_only.stderr
    assert not any("/daily-trigger" in line for line in env.calls())
    assert env.collected() == ["lifecycle-20260917-notices", "lifecycle-20260917-plans-m0"]


# --- 발주계획 트랙: 수집 → 적재 → 실행 → draw -----------------------------------


def test_daily_track_collects_ingests_executes_and_draws_in_order(env: Env) -> None:
    env.trigger_on()

    result = env.run("--track", "order-plans", "--date", "2026-09-17")

    assert result.returncode == 0, result.stderr
    assert env.collected() == [RUN]
    assert env.ingested() == [RUN]
    [post] = env.execution_posts()
    assert post["body"] == {
        "schema_version": "execution-create-request.v1",
        "producer": "human-review-client",
        "consumer": "screening-api",
        "request_id": _request_id(RUN, "v3", 1),
        "source_run_id": RUN,
        "policy_version": "v3",
    }
    assert _header(post, "X-BidOps-Trigger") == "daily_script"
    assert _header(post, "X-BidOps-Actor-Name") == "cron-operator"
    [draw] = env.draw_posts()
    assert draw["body"]["schema_version"] == "audit-sample-draw-request.v1"
    assert draw["body"]["consumer"] == "audit-sample-api"
    assert _header(draw, "X-BidOps-Trigger") == "daily_script"
    # 적재가 실행 요청보다 먼저다.
    calls = env.calls()
    ingest_at = next(i for i, line in enumerate(calls) if "--collection" in line)
    post_at = next(i for i, line in enumerate(calls) if "-X POST" in line and line.endswith("/executions"))
    assert ingest_at < post_at
    assert "audit sample drawn" in result.stdout


def test_non_ascii_actor_goes_as_utf8_percent_header(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)

    result = env.c2(RUN, BIDOPS_C2_DAILY_ACTOR="홍길동")

    assert result.returncode == 0, result.stderr
    [post] = env.execution_posts()
    assert _header(post, "X-BidOps-Actor-Name") == "UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99"
    assert _header(post, "X-BidOps-Actor-Name-Format") == "utf-8-percent-v1"


def test_zero_count_day_ends_as_empty_population_without_execution(env: Env) -> None:
    env.trigger_on()
    env.mode("20260917", "complete:0")

    result = env.run("--track", "order-plans", "--date", "2026-09-17")

    assert result.returncode == 0, result.stderr
    assert "empty_population" in result.stdout
    assert env.collected() == [RUN]
    assert env.ingested() == []
    assert env.posts() == []


def test_catch_up_resumes_a_collected_day_at_execution(env: Env) -> None:
    env.trigger_on()
    _ready_run(env, "lifecycle-20260916-plans")

    result = env.run("--track", "order-plans", "--from-date", "2026-09-16", "--to-date", "2026-09-17")

    assert result.returncode == 0, result.stderr
    # 16일은 회차가 있고 성공 실행이 없으므로 수집·적재 없이 실행부터 한다.
    assert env.collected() == [RUN]
    assert env.ingested() == [RUN]
    assert [post["body"]["source_run_id"] for post in env.execution_posts()] == [
        "lifecycle-20260916-plans",
        RUN,
    ]
    assert len(env.draw_posts()) == 2


def test_catch_up_day_with_success_only_draws(env: Env) -> None:
    env.trigger_on()
    _ready_run(env, "lifecycle-20260916-plans")
    env.execution("lifecycle-20260916-plans", "부분 성공")

    result = env.run("--track", "order-plans", "--from-date", "2026-09-16", "--to-date", "2026-09-17")

    assert result.returncode == 0, result.stderr
    assert "already_executed: lifecycle-20260916-plans" in result.stdout
    assert [post["body"]["source_run_id"] for post in env.execution_posts()] == [RUN]
    assert len(env.draw_posts()) == 2


# --- 스킵·재시도 규칙 (run-daily-c2.sh) ---------------------------------------


def test_success_exists_is_already_executed_and_draws_once(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    execution_id = env.execution(RUN, "성공")

    result = env.c2(RUN)

    assert result.returncode == 0, result.stderr
    assert "already_executed" in result.stdout
    assert env.execution_posts() == []
    [draw] = env.draw_posts()
    assert draw["path"] == f"/api/order-plan-screening/executions/{execution_id}/audit-sample"


def test_already_drawn_sample_is_not_posted_again(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.execution(RUN, "성공")
    env.respond("audit_get", 200, {"status": "drawn", "sample": []})

    result = env.c2(RUN)

    assert result.returncode == 0, result.stderr
    assert "already drawn" in result.stdout
    assert env.posts() == []


@pytest.mark.parametrize("status", ["대기", "실행 중", "중지 요청"])
def test_active_execution_skips(status: str, env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.execution(RUN, status)

    result = env.c2(RUN)

    assert result.returncode == 0, result.stderr
    assert "active_execution_exists" in result.stdout
    assert env.posts() == []


def test_one_failure_waits_then_runs_attempt_two(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.execution(RUN, "실패")

    result = env.c2(RUN, BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS="1")

    assert result.returncode == 0, result.stderr
    assert "waiting 1s before attempt 2" in result.stdout
    [post] = env.execution_posts()
    assert post["body"]["request_id"] == _request_id(RUN, "v3", 2)
    assert _header(post, "X-BidOps-Trigger") == "daily_script"
    assert len(env.draw_posts()) == 1


def test_first_attempt_failure_retries_once_the_same_day(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.outcomes("중단됨", "성공")

    result = env.c2(RUN)

    assert result.returncode == 0, result.stderr
    assert [post["body"]["request_id"] for post in env.execution_posts()] == [
        _request_id(RUN, "v3", 1),
        _request_id(RUN, "v3", 2),
    ]
    assert len(env.draw_posts()) == 1


def test_same_day_retry_failure_exits_non_zero_without_a_third_attempt(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.outcomes("실패", "실패")

    result = env.c2(RUN)

    assert result.returncode != 0
    assert "--extra-attempt" in result.stderr
    assert len(env.execution_posts()) == 2
    assert env.draw_posts() == []


def test_two_failures_reach_the_retry_limit(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.execution(RUN, "실패")
    env.execution(RUN, "중단됨")

    result = env.c2(RUN)

    assert result.returncode == 0, result.stderr
    assert "retry_limit_reached" in result.stdout
    assert f"scripts/run-daily-c2.sh {RUN} --extra-attempt" in result.stdout
    assert env.posts() == []


def test_extra_attempt_creates_attempt_three_with_manual_resume(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.execution(RUN, "실패")
    env.execution(RUN, "실패")

    result = env.c2(RUN, "--extra-attempt", BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS="600")

    assert result.returncode == 0, result.stderr
    assert "waiting" not in result.stdout
    [post] = env.execution_posts()
    assert post["body"]["request_id"] == _request_id(RUN, "v3", 3)
    assert _header(post, "X-BidOps-Trigger") == "manual_resume"
    [draw] = env.draw_posts()
    assert _header(draw, "X-BidOps-Trigger") == "manual_resume"


def test_failed_extra_attempt_does_not_retry(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.execution(RUN, "실패")
    env.execution(RUN, "실패")
    env.outcomes("실패")

    result = env.c2(RUN, "--extra-attempt")

    assert result.returncode != 0
    assert len(env.execution_posts()) == 1


def test_attempt_counts_only_operational_executions_of_the_same_policy(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.execution(RUN, "실패", policy_version="v2")
    env.execution(RUN, "성공", purpose="gate_measurement")

    result = env.c2(RUN)

    assert result.returncode == 0, result.stderr
    # 측정 전용 성공은 already_executed가 아니고, 다른 policy의 실패는 attempt에 세지 않는다.
    [post] = env.execution_posts()
    assert post["body"]["request_id"] == _request_id(RUN, "v3", 1)


# --- POST가 상태 변화를 알린 경우와 draw 결과 ----------------------------------


@pytest.mark.parametrize(
    "code,body,expected",
    [
        (503, {"error": {"code": "service_unavailable"}}, "service_unavailable"),
        (409, {"error": {"code": "policy_not_active"}}, "policy_not_active"),
        (
            409,
            {"error": {"code": "daily_trigger_off", "details": {"reasons": ["switch_bound_to_other_version"]}}},
            "daily_trigger_off: switch_bound_to_other_version",
        ),
    ],
)
def test_post_answers_that_are_normal_skips(code: int, body: dict, expected: str, env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.respond("post_execution", code, body)

    result = env.c2(RUN)

    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    assert len(env.execution_posts()) == 1
    assert env.draw_posts() == []
    assert not any(line.startswith("curl") and "/executions/" in line for line in env.calls())


def test_other_post_errors_exit_non_zero(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.respond("post_execution", 409, {"error": {"code": "source_run_incomplete"}})

    result = env.c2(RUN)

    assert result.returncode != 0
    assert "source_run_incomplete" in result.stderr


@pytest.mark.parametrize(
    "body,expected",
    [
        (
            {"status": "pending_human_approval", "pending_decision": "max_per_execution_and_review_cadence", "sample": None},
            "pending_human_approval: max_per_execution_and_review_cadence",
        ),
        ({"status": "not_applicable", "reason": "stage1.population.at_or_below_top_k", "sample": None},
         "not_applicable: stage1.population.at_or_below_top_k"),
    ],
)
def test_draw_without_sample_prints_the_reason_and_exits_zero(body: dict, expected: str, env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.respond("audit_post", 200, body)

    result = env.c2(RUN)

    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    assert len(env.draw_posts()) == 1


def test_draw_failure_exits_non_zero_and_keeps_the_execution(env: Env) -> None:
    env.trigger_on()
    _ready_run(env)
    env.respond("audit_post", 409, {"error": {"code": "immutable_conflict"}})

    result = env.c2(RUN)

    assert result.returncode != 0
    assert "execution results are kept" in result.stderr
    [post] = env.execution_posts()
    assert post["body"]["source_run_id"] == RUN
    # 실행은 성공으로 남고 중지·삭제 요청은 없다.
    assert not any("/stop" in item["path"] for item in env.posts())
    listed = env.c2(RUN)
    assert "already_executed" in listed.stdout


def test_standalone_trigger_off_and_empty_population(env: Env) -> None:
    env.trigger(enabled=False, reasons=["switch_bound_to_other_version"])
    _ready_run(env)
    off = env.c2(RUN)
    assert off.returncode == 0, off.stderr
    assert "daily_trigger_off: switch_bound_to_other_version" in off.stdout
    assert GUIDANCE in off.stdout

    env.trigger_on()
    env.plans_dir("lifecycle-20260916-plans", complete=True, total=0)
    empty = env.c2("lifecycle-20260916-plans")
    assert empty.returncode == 0, empty.stderr
    assert "empty_population" in empty.stdout
    assert env.posts() == []


def test_standalone_dry_run_calls_nothing(env: Env) -> None:
    result = env.c2(RUN, "--extra-attempt", "--dry-run", BIDOPS_C2_DAILY_ACTOR=None)

    assert result.returncode == 0, result.stderr
    assert "X-BidOps-Trigger: manual_resume" in result.stdout
    assert env.calls() == []


def test_order_plans_dry_run_prints_trigger_check_and_c2_stage_without_calls(env: Env) -> None:
    result = env.run("--track", "order-plans", "--date", "2026-09-17", "--dry-run", BIDOPS_C2_DAILY_ACTOR=None)

    assert result.returncode == 0, result.stderr
    assert "daily-trigger once before any collection" in result.stdout
    assert "X-BidOps-Trigger: daily_script" in result.stdout
    assert "/audit-sample" in result.stdout
    assert env.calls() == []


# --- request_id ------------------------------------------------------------


def test_request_id_is_uuidv5_of_run_policy_attempt_and_deterministic(env: Env) -> None:
    script = (
        f'source "{env.root}/scripts/c2-execution-common.sh"; '
        'c2_execution_request_id lifecycle-20260917-plans v3 1; '
        'c2_execution_request_id lifecycle-20260917-plans v3 1; '
        'c2_execution_request_id lifecycle-20260917-plans v3 2; '
        'c2_execution_request_id "한글-run" v3 1'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    first, again, second, korean = result.stdout.split()
    assert first == again == _request_id(RUN, "v3", 1)
    assert second == _request_id(RUN, "v3", 2)
    assert korean == _request_id("한글-run", "v3", 1)
