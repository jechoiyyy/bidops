"""`scripts/run-daily-lifecycle.sh`의 누락일 감지와 `--catch-up-days` 따라잡기(A-3, findings W-3·W-4).

가짜 `curl`·`docker`·`python3`와 임시 루트는 `test_daily_lifecycle_script.py`의 것을 그대로
쓴다 — 회차 행 기본키 `<디렉터리>--<generated_at>Z`, `GET /api/runs/<디렉터리>`만 alias를 풀고
C-2는 정규 id만 받는 실제 계약이다. 감지는 web을 부르지 않고 로컬 회차 디렉터리만 읽는다:
완결 표식이 있는 디렉터리(기본 또는 `-retry<N>`, 0건 포함)가 하나라도 있으면 그날은 있는 것이다.

규칙: 그날 몫을 끝낸 뒤 기준일과 그 앞 `BIDOPS_DAILY_GAP_LOOKBACK_DAYS`일(기본 7, 0은 끔) 중
`BIDOPS_DAILY_GAP_FLOOR_DATE` 이후 날짜를 보고, 빠진 날마다 `gap_detected track=… date=…` 한 줄을
찍은 뒤 exit 10으로 끝난다. 진짜 실패(exit 2 등)와 겹치지 않는다.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.app.test_daily_lifecycle_script import Env, make_env

GAP_EXIT = 10
REF = "2026-09-17"


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return make_env(tmp_path)


def _days(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [(first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1)]


def _run_id(day: str, kind: str) -> str:
    return f"lifecycle-{day.replace('-', '')}-{kind}"


def _complete_days(env: Env, kind: str, days: list[str]) -> None:
    """적재까지 끝난 날들(회차 행도 있어 다시 돌면 할 일이 없다)."""

    for day in days:
        run_id = _run_id(day, kind)
        if kind == "notices":
            env.notices_dir(run_id, complete=True)
        else:
            env.plans_dir(run_id, complete=True)
        env.row(run_id)


def _gap_lines(stdout: str) -> list[str]:
    return [line[line.index("gap_detected track="):] for line in stdout.splitlines() if "gap_detected track=" in line]


def _unjudged_lines(stdout: str) -> list[str]:
    return [line[line.index("unjudged_detected track="):] for line in stdout.splitlines() if "unjudged_detected track=" in line]


def _judged(env: Env, days: list[str], status: str = "성공") -> None:
    """그날 회차 행(기본키)에 판정 결과가 있는 실행 하나."""

    for day in days:
        execution_id = env.execution(_run_id(day, "plans"), status)
        if status in {"성공", "부분 성공"}:
            env.drawn(execution_id)


def _gaps(env: Env, *args: str, lookback: str | None = "7", floor: str | None = None, **extra: str | None):
    return env.run(
        *args,
        BIDOPS_DAILY_GAP_LOOKBACK_DAYS=lookback,
        BIDOPS_DAILY_GAP_FLOOR_DATE=floor,
        **extra,
    )


# --- 감지 -----------------------------------------------------------------------


def test_missing_days_are_reported_after_the_day_is_done_with_a_distinct_exit(env: Env) -> None:
    _complete_days(env, "notices", [d for d in _days("2026-09-10", "2026-09-16") if d not in {"2026-09-12", "2026-09-14"}])
    # 불완전한 디렉터리만 있는 날도 그날 몫이 없는 것이다.
    env.notices_dir(_run_id("2026-09-12", "notices"), complete=False)

    result = _gaps(env, "--track", "notices", "--date", REF)

    assert result.returncode == GAP_EXIT, result.stderr
    # 기준일 몫은 감지보다 먼저 끝났다.
    assert env.collected() == [_run_id(REF, "notices")]
    assert env.ingested() == [_run_id(REF, "notices")]
    assert f"daily notices track done for {REF}" in result.stdout
    assert _gap_lines(result.stdout) == [
        "gap_detected track=notices date=2026-09-12",
        "gap_detected track=notices date=2026-09-14",
    ]
    stdout = result.stdout
    assert stdout.index("daily notices track done for") < stdout.index("gap_detected track=")


def test_no_missing_day_exits_zero(env: Env) -> None:
    _complete_days(env, "notices", _days("2026-09-10", "2026-09-16"))

    result = _gaps(env, "--track", "notices", "--date", REF)

    assert result.returncode == 0, result.stderr
    assert _gap_lines(result.stdout) == []


def test_default_lookback_is_seven_days(env: Env) -> None:
    result = _gaps(env, "--track", "notices", "--date", REF, lookback=None)

    assert result.returncode == GAP_EXIT, result.stderr
    assert [line.rsplit("=", 1)[1] for line in _gap_lines(result.stdout)] == _days("2026-09-10", "2026-09-16")


def test_floor_date_excludes_the_acknowledged_outage(env: Env) -> None:
    _complete_days(env, "notices", ["2026-09-15", "2026-09-16"])

    result = _gaps(env, "--track", "notices", "--date", REF, floor="2026-09-15")

    assert result.returncode == 0, result.stderr
    assert _gap_lines(result.stdout) == []


def test_lookback_zero_disables_detection(env: Env) -> None:
    result = _gaps(env, "--track", "notices", "--date", REF, lookback="0")

    assert result.returncode == 0, result.stderr
    assert _gap_lines(result.stdout) == []


def test_a_shorter_lookback_only_looks_that_far(env: Env) -> None:
    _complete_days(env, "notices", ["2026-09-16"])

    result = _gaps(env, "--track", "notices", "--date", REF, lookback="2")

    assert result.returncode == GAP_EXIT, result.stderr
    assert _gap_lines(result.stdout) == ["gap_detected track=notices date=2026-09-15"]


def test_a_failing_day_keeps_its_own_failure_exit(env: Env) -> None:
    env.mode(REF.replace("-", ""), "fail")

    result = _gaps(env, "--track", "notices", "--date", REF)

    assert result.returncode not in (0, GAP_EXIT)
    assert _gap_lines(result.stdout) == []


def test_range_mode_checks_the_days_before_the_range(env: Env) -> None:
    _complete_days(env, "notices", _days("2026-09-11", "2026-09-14"))

    result = _gaps(env, "--track", "notices", "--from-date", "2026-09-15", "--to-date", REF, lookback="7")

    assert result.returncode == GAP_EXIT, result.stderr
    assert env.collected() == [_run_id(d, "notices") for d in _days("2026-09-15", REF)]
    assert _gap_lines(result.stdout) == ["gap_detected track=notices date=2026-09-10"]


def test_order_plans_checks_gaps_after_the_c2_stage(env: Env) -> None:
    env.trigger_on()
    _complete_days(env, "plans", _days("2026-09-11", "2026-09-16"))
    _judged(env, _days("2026-09-11", "2026-09-16"))

    result = _gaps(env, "--track", "order-plans", "--date", REF)

    assert result.returncode == GAP_EXIT, result.stderr
    assert len(env.execution_posts()) == 1
    assert len(env.draw_posts()) == 1
    assert _gap_lines(result.stdout) == ["gap_detected track=order-plans date=2026-09-10"]
    assert result.stdout.index("C-2 stage for") < result.stdout.index("gap_detected track=")


def test_order_plans_trigger_off_ends_before_collection_without_gap_detection(env: Env) -> None:
    result = _gaps(env, "--track", "order-plans", "--date", REF)

    assert result.returncode == 0, result.stderr
    assert "daily_trigger_off" in result.stdout
    assert env.collected() == []
    assert _gap_lines(result.stdout) == []


def test_a_track_stopping_skip_still_runs_gap_detection(env: Env) -> None:
    """`active_execution_exists`처럼 트랙을 멈추는 정상 스킵 뒤에도 누락일은 보인다."""

    env.trigger_on()
    env.plans_dir(_run_id(REF, "plans"), complete=True)
    env.row(_run_id(REF, "plans"))
    env.execution(_run_id(REF, "plans"), "대기")

    result = _gaps(env, "--track", "order-plans", "--date", REF, lookback="1")

    assert result.returncode == GAP_EXIT, result.stderr
    assert "active_execution_exists" in result.stdout
    assert f"track stopped at {REF}: active_execution_exists (normal skip)" in result.stdout
    assert _gap_lines(result.stdout) == ["gap_detected track=order-plans date=2026-09-16"]


def test_a_track_stopping_skip_without_a_missing_day_still_surfaces_the_unjudged_day(env: Env) -> None:
    """디렉터리 누락은 없어도 오늘 판정이 없으면(정상 스킵) 오늘 드러난다(exit 10)."""

    env.trigger_on()
    _complete_days(env, "plans", ["2026-09-16"])
    _judged(env, ["2026-09-16"])
    env.plans_dir(_run_id(REF, "plans"), complete=True)
    env.row(_run_id(REF, "plans"))
    env.execution(_run_id(REF, "plans"), "대기")

    result = _gaps(env, "--track", "order-plans", "--date", REF, lookback="1")

    assert result.returncode == GAP_EXIT, result.stderr
    assert _gap_lines(result.stdout) == []
    assert _unjudged_lines(result.stdout) == [
        f"unjudged_detected track=order-plans date={REF} run={_run_id(REF, 'plans')} reason=active:대기",
    ]


@pytest.mark.parametrize(
    "extra",
    [
        {"BIDOPS_DAILY_GAP_LOOKBACK_DAYS": "x"},
        {"BIDOPS_DAILY_GAP_LOOKBACK_DAYS": "-1"},
        {"BIDOPS_DAILY_GAP_FLOOR_DATE": "2026-02-30"},
        {"BIDOPS_DAILY_GAP_FLOOR_DATE": "20260915"},
    ],
)
def test_invalid_gap_settings_fail_before_any_call(env: Env, extra: dict[str, str]) -> None:
    result = env.run("--track", "notices", "--date", REF, **extra)

    assert result.returncode not in (0, GAP_EXIT)
    assert env.calls() == []


# --- --catch-up-days ------------------------------------------------------------


def test_catch_up_fills_missing_days_oldest_first_before_the_reference_day(env: Env) -> None:
    _complete_days(env, "notices", ["2026-09-15"])
    env.notices_dir(_run_id("2026-09-16", "notices"), complete=False)

    result = _gaps(env, "--track", "notices", "--date", REF, "--catch-up-days", "3", floor="2026-09-14")

    assert result.returncode == 0, result.stderr
    assert env.collected() == [
        _run_id("2026-09-14", "notices"),
        _run_id("2026-09-16", "notices") + "-retry1",
        _run_id(REF, "notices"),
    ]
    assert _gap_lines(result.stdout) == []


def test_catch_up_leaves_days_beyond_its_reach_to_gap_detection(env: Env) -> None:
    result = _gaps(env, "--track", "notices", "--date", REF, "--catch-up-days", "2", lookback="4")

    assert result.returncode == GAP_EXIT, result.stderr
    assert env.collected() == [_run_id(d, "notices") for d in ("2026-09-15", "2026-09-16", REF)]
    assert _gap_lines(result.stdout) == [
        "gap_detected track=notices date=2026-09-13",
        "gap_detected track=notices date=2026-09-14",
    ]


def test_catch_up_does_not_reach_before_the_floor(env: Env) -> None:
    result = _gaps(env, "--track", "notices", "--date", REF, "--catch-up-days", "3", floor="2026-09-16")

    assert result.returncode == 0, result.stderr
    assert env.collected() == [_run_id("2026-09-16", "notices"), _run_id(REF, "notices")]


def test_catch_up_stops_the_track_at_the_first_failing_day(env: Env) -> None:
    env.mode("20260915", "fail")

    result = _gaps(env, "--track", "notices", "--date", REF, "--catch-up-days", "3")

    assert result.returncode not in (0, GAP_EXIT)
    assert env.collected() == [_run_id("2026-09-14", "notices"), _run_id("2026-09-15", "notices")]
    assert not (env.runs / _run_id(REF, "notices")).exists()


def test_order_plans_catch_up_executes_c2_on_each_day_with_the_canonical_id(env: Env) -> None:
    env.trigger_on()

    result = _gaps(env, "--track", "order-plans", "--date", REF, "--catch-up-days", "2", floor="2026-09-15")

    assert result.returncode == 0, result.stderr
    assert env.collected() == [_run_id(d, "plans") for d in ("2026-09-15", "2026-09-16", REF)]
    sources = [post["body"]["source_run_id"] for post in env.execution_posts()]
    assert [source.split("--")[0] for source in sources] == [_run_id(d, "plans") for d in ("2026-09-15", "2026-09-16", REF)]
    assert all("--" in source for source in sources)


@pytest.mark.parametrize(
    "args,extra",
    [
        (["--date", REF, "--catch-up-days", "8"], {}),
        (["--date", REF, "--catch-up-days", "1"], {"BIDOPS_DAILY_GAP_LOOKBACK_DAYS": "0"}),
        (["--date", REF, "--catch-up-days", "x"], {}),
        (["--from-date", "2026-09-15", "--to-date", REF, "--catch-up-days", "1"], {}),
        (["--collect-only", "--run-suffix", "m0", "--catch-up-days", "1"], {}),
    ],
)
def test_invalid_catch_up_fails_before_any_call(env: Env, args: list[str], extra: dict[str, str]) -> None:
    result = env.run("--track", "notices", *args, **{"BIDOPS_DAILY_GAP_LOOKBACK_DAYS": "7", **extra})

    assert result.returncode not in (0, GAP_EXIT)
    assert env.calls() == []


# --- --dry-run ------------------------------------------------------------------


def test_dry_run_prints_the_catch_up_plan_and_the_gaps_a_real_run_would_report(env: Env) -> None:
    _complete_days(env, "notices", ["2026-09-15"])

    result = _gaps(env, "--track", "notices", "--date", REF, "--catch-up-days", "3", "--dry-run", lookback="4")

    assert result.returncode == 0, result.stderr
    assert env.calls() == []
    decisions = [line for line in result.stdout.splitlines() if "] decision " in line]
    assert decisions == [
        f"[bidops-workflow] decision 2026-09-14: collect_new ({_run_id('2026-09-14', 'notices')})",
        f"[bidops-workflow] decision 2026-09-16: collect_new ({_run_id('2026-09-16', 'notices')})",
        f"[bidops-workflow] decision {REF}: collect_new ({_run_id(REF, 'notices')})",
    ]
    # 실제 실행은 위 세 날을 먼저 처리하므로, 남는 누락일만 보고한다.
    assert _gap_lines(result.stdout) == ["gap_detected track=notices date=2026-09-13"]
    assert "[dry-run] would report: gap_detected track=notices date=2026-09-13" in result.stdout
    assert f"would exit {GAP_EXIT}" in result.stdout
    assert not (env.runs / _run_id("2026-09-14", "notices")).exists()


def test_dry_run_without_gaps_says_so(env: Env) -> None:
    _complete_days(env, "notices", _days("2026-09-10", "2026-09-16"))

    result = _gaps(env, "--track", "notices", "--date", REF, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert _gap_lines(result.stdout) == []
    assert "no gap" in result.stdout


# --- 판정 없는 발주계획 날 (unjudged, 2026-11-18 추가) ------------------------------
#
# 발주계획 트랙은 완결·비어 있지 않은 회차가 있어도 `성공`·`부분 성공` C-2 실행이 없으면 그날을
# `unjudged_detected`로 보고한다(날짜별 재개가 "실행부터"로 판단하는 기준과 같다). web 조회는 실제
# 계약대로 `GET /api/runs/<디렉터리>`로 정규 id를 받고 실행 목록은 정규 id로만 부른다.


def _summary(stdout: str) -> str:
    return next(line for line in stdout.splitlines() if "gap check:" in line and "missing" in line)


def test_order_plans_reports_complete_days_without_a_judged_result(env: Env) -> None:
    env.trigger_on()
    days = _days("2026-09-10", "2026-09-16")
    _complete_days(env, "plans", [d for d in days if d != "2026-09-12"])
    env.plans_dir(_run_id("2026-09-12", "plans"), complete=True, total=0)  # 빈 회차는 판정이 필요 없다
    _judged(env, ["2026-09-10", "2026-09-11", "2026-09-16"])
    _judged(env, ["2026-09-13"], status="부분 성공")
    env.execution(_run_id("2026-09-14", "plans"), "실패")
    env.execution(_run_id("2026-09-15", "plans"), "실패")
    env.execution(_run_id("2026-09-15", "plans"), "실행 중")

    result = _gaps(env, "--track", "order-plans", "--date", REF)

    assert result.returncode == GAP_EXIT, result.stderr
    assert _gap_lines(result.stdout) == []
    assert _unjudged_lines(result.stdout) == [
        "unjudged_detected track=order-plans date=2026-09-14 run=lifecycle-20260914-plans reason=last:실패",
        "unjudged_detected track=order-plans date=2026-09-15 run=lifecycle-20260915-plans reason=active:실행 중",
    ]
    assert "0 missing" in _summary(result.stdout) and "2 unjudged" in _summary(result.stdout)
    # 정규 id로만 실행 목록을 읽는다.
    lists = [line for line in env.calls() if "executions?source_run_id=" in line]
    assert lists and all("--" in line.split("source_run_id=", 1)[1] for line in lists)


def test_a_normal_skip_today_surfaces_today(env: Env) -> None:
    env.trigger_on()
    _complete_days(env, "plans", ["2026-09-16"])
    _judged(env, ["2026-09-16"])
    env.respond("post_execution", 503, {"error": {"code": "service_unavailable", "message": "x", "details": None}})

    result = _gaps(env, "--track", "order-plans", "--date", REF, lookback="1")

    assert result.returncode == GAP_EXIT, result.stderr
    assert "service_unavailable" in result.stdout
    assert _unjudged_lines(result.stdout) == [
        f"unjudged_detected track=order-plans date={REF} run={_run_id(REF, 'plans')} reason=no_execution",
    ]


def test_a_collected_but_not_ingested_day_is_unjudged(env: Env) -> None:
    env.trigger_on()
    env.plans_dir(_run_id("2026-09-16", "plans"), complete=True)

    result = _gaps(env, "--track", "order-plans", "--date", REF, lookback="1")

    assert result.returncode == GAP_EXIT, result.stderr
    assert _unjudged_lines(result.stdout) == [
        "unjudged_detected track=order-plans date=2026-09-16 run=lifecycle-20260916-plans reason=not_ingested",
    ]


def test_two_run_rows_for_one_directory_are_reported_not_guessed(env: Env) -> None:
    env.trigger_on()
    env.plans_dir(_run_id("2026-09-16", "plans"), complete=True)
    env.row(_run_id("2026-09-16", "plans") + "--20260916T010000Z", exact=True)
    env.row(_run_id("2026-09-16", "plans") + "--20260917T010000Z", exact=True)

    result = _gaps(env, "--track", "order-plans", "--date", REF, lookback="1")

    assert result.returncode == GAP_EXIT, result.stderr
    assert _unjudged_lines(result.stdout) == [
        "unjudged_detected track=order-plans date=2026-09-16 run=lifecycle-20260916-plans reason=multiple_run_rows:2",
    ]
    assert not any("source_run_id=lifecycle-20260916-plans" in line for line in env.calls())


def test_unjudged_days_before_the_floor_are_not_counted(env: Env) -> None:
    env.trigger_on()
    _complete_days(env, "plans", ["2026-09-15", "2026-09-16"])
    _judged(env, ["2026-09-16"])

    result = _gaps(env, "--track", "order-plans", "--date", REF, floor="2026-09-16")

    assert result.returncode == 0, result.stderr
    assert _unjudged_lines(result.stdout) == []


def test_a_web_read_failure_in_the_gap_check_fails_instead_of_passing(env: Env) -> None:
    env.trigger_on()
    _complete_days(env, "plans", ["2026-09-16"])
    _judged(env, ["2026-09-16"])
    # 기준일은 빈 회차(empty_population)라 C-2 목록을 읽지 않는다 — 실행 목록 GET은 감지에서만 난다.
    env.mode(REF.replace("-", ""), "complete:0")
    (env.state / "get_fail").write_text("/api/order-plan-screening/executions", encoding="utf-8")

    result = _gaps(env, "--track", "order-plans", "--date", REF, lookback="1")

    assert result.returncode not in (0, GAP_EXIT)
    assert "HTTP 500" in result.stderr
    assert "no gap" not in result.stdout


def test_catch_up_runs_only_the_c2_stage_of_an_unjudged_day(env: Env) -> None:
    env.trigger_on()
    _complete_days(env, "plans", ["2026-09-16"])

    result = _gaps(env, "--track", "order-plans", "--date", REF, "--catch-up-days", "1", floor="2026-09-16")

    assert result.returncode == 0, result.stderr
    assert env.collected() == [_run_id(REF, "plans")]
    sources = [post["body"]["source_run_id"] for post in env.execution_posts()]
    assert [source.split("--")[0] for source in sources] == [_run_id("2026-09-16", "plans"), _run_id(REF, "plans")]
    assert _unjudged_lines(result.stdout) == []


def test_catch_up_leaves_a_day_with_an_active_execution_to_the_report(env: Env) -> None:
    env.trigger_on()
    _complete_days(env, "plans", ["2026-09-16"])
    env.execution(_run_id("2026-09-16", "plans"), "실행 중")

    result = _gaps(env, "--track", "order-plans", "--date", REF, "--catch-up-days", "1", floor="2026-09-16")

    assert result.returncode == GAP_EXIT, result.stderr
    assert [post["body"]["source_run_id"].split("--")[0] for post in env.execution_posts()] == [_run_id(REF, "plans")]
    assert _unjudged_lines(result.stdout) == [
        "unjudged_detected track=order-plans date=2026-09-16 run=lifecycle-20260916-plans reason=active:실행 중",
    ]


def test_notices_track_does_not_read_judged_state(env: Env) -> None:
    _complete_days(env, "notices", _days("2026-09-10", "2026-09-16"))

    result = _gaps(env, "--track", "notices", "--date", REF)

    assert result.returncode == 0, result.stderr
    assert _unjudged_lines(result.stdout) == []
    assert not any("order-plan-screening/executions" in line for line in env.calls())


def test_order_plans_dry_run_says_it_would_check_judged_state_without_calls(env: Env) -> None:
    _complete_days(env, "plans", _days("2026-09-10", "2026-09-16"))

    result = _gaps(env, "--track", "order-plans", "--date", REF, "--catch-up-days", "2", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert env.calls() == []
    assert "would also check judged state" in result.stdout
    assert _unjudged_lines(result.stdout) == []


# --- 감사 표본이 빠진 성공일 (2026-11-18 감독 시운전) -------------------------------
#
# 성공 실행이 있으면 빠진 날도 판정 없는 날도 아니어서, 폴링이 끊긴 날의 표본 draw가 영영 빠졌다.
# 그날의 최신 `성공`·`부분 성공` 실행의 감사 표본 GET(읽기 전용)이 `preview`(뽑을 수 있는데 기록 없음)면
# `reason=audit_sample_missing`으로 보고하고 따라잡기가 재개해 draw한다. `pending_human_approval`·
# `not_applicable`은 뽑을 것이 없으므로 보고하지 않는다.


def test_a_successful_day_without_a_drawn_sample_is_reported(env: Env) -> None:
    env.trigger_on()
    _complete_days(env, "plans", ["2026-09-16"])
    env.execution(_run_id("2026-09-16", "plans"), "성공")

    result = _gaps(env, "--track", "order-plans", "--date", REF, lookback="1")

    assert result.returncode == GAP_EXIT, result.stderr
    assert _unjudged_lines(result.stdout) == [
        "unjudged_detected track=order-plans date=2026-09-16 run=lifecycle-20260916-plans reason=audit_sample_missing",
    ]
    assert "1 unjudged" in _summary(result.stdout)


def test_a_sample_waiting_for_a_human_decision_is_not_reported(env: Env) -> None:
    env.trigger_on()
    _complete_days(env, "plans", ["2026-09-16"])
    env.execution(_run_id("2026-09-16", "plans"), "성공")
    env.respond("audit_get", 200, {"status": "pending_human_approval", "pending_decision": "audit_sample_settings"})

    result = _gaps(env, "--track", "order-plans", "--date", REF, lookback="1")

    assert result.returncode == 0, result.stderr
    assert _unjudged_lines(result.stdout) == []


def test_catch_up_draws_the_missing_sample_without_a_new_execution(env: Env) -> None:
    env.trigger_on()
    _complete_days(env, "plans", ["2026-09-16"])
    execution_id = env.execution(_run_id("2026-09-16", "plans"), "성공")

    result = _gaps(env, "--track", "order-plans", "--date", REF, "--catch-up-days", "1", floor="2026-09-16")

    assert result.returncode == 0, result.stderr
    assert env.collected() == [_run_id(REF, "plans")]
    assert [post["body"]["source_run_id"].split("--")[0] for post in env.execution_posts()] == [_run_id(REF, "plans")]
    draws = [post["path"] for post in env.draw_posts()]
    assert draws[0] == f"/api/order-plan-screening/executions/{execution_id}/audit-sample"
    assert len(draws) == 2
    assert _unjudged_lines(result.stdout) == []


def test_an_audit_sample_read_failure_in_the_gap_check_fails(env: Env) -> None:
    env.trigger_on()
    _complete_days(env, "plans", ["2026-09-16"])
    execution_id = env.execution(_run_id("2026-09-16", "plans"), "성공")
    env.mode(REF.replace("-", ""), "complete:0")
    env.fail_gets(f"/api/order-plan-screening/executions/{execution_id}/audit-sample")

    result = _gaps(env, "--track", "order-plans", "--date", REF, lookback="1")

    assert result.returncode not in (0, GAP_EXIT)
    assert "HTTP 500" in result.stderr
