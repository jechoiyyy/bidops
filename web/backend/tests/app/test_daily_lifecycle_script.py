"""`scripts/run-daily-lifecycle.sh`의 트랙 분리·전일 기준·수집 창·`--collect-only`(S9a)와
회차 조회·`-retryN`·날짜 범위 단계별 재개(S9b)를 본다 (`docs/0918_daily-operation/spec.md` §8).
C-2 실행·감사 표본 draw 연결(S9c)은 `test_daily_c2_script.py`가 이 모듈의 fixture를 빌려 본다.

스크립트는 자기 위치의 부모를 저장소 루트로 삼고 `data/runs`를 거기서 찾는다. 그래서
네 스크립트를 임시 루트의 `scripts/`에 복사해 실행한다 — 회차 디렉터리 fixture가 실제
저장소 `data/runs`와 섞이지 않는다. `BIDOPS_WEB_PORT`를 주고 가짜 `docker`·`python3`·
`curl`을 PATH 맨 앞에 둔다. 가짜들은 호출을 로그에 한 줄씩 남기고, 상태 디렉터리로
동작한다: `python3`는 수집기 흉내(날짜별 모드: 완료 N건·불완전·실패), `docker`는 적재 때
회차 행 표식 파일을 만들고, `curl`은 그 표식으로 `GET /api/runs/{id}`에 200/404를 주며 C-2 REST
(일일 자동 실행 확인·실행 목록·생성·상세·감사 표본)를 상태 디렉터리로 흉내 낸다 — 자동 실행 확인의
기본 답은 사람 결정 전 서버의 답(`env_cap_off`)이다. `jq`는 진짜를 쓴다.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ("run-daily-lifecycle.sh", "manual-workflow-common.sh", "run-daily-c2.sh", "c2-execution-common.sh")

_FAKE_BIN = r"""#!/usr/bin/env bash
state="${FAKE_STATE:?}"
name="$(basename "$0")"
printf '%s %s\n' "${name}" "$*" >> "${state}/calls.log"
case "${name}" in
  curl)
    method=GET; data=""; headers=()
    while [[ $# -gt 1 ]]; do
      case "$1" in
        -X) method="$2"; shift 2 ;;
        -H) headers+=("$2"); shift 2 ;;
        --data-binary) data="$2"; shift 2 ;;
        --connect-timeout|--max-time|--output|-o|--write-out) shift 2 ;;
        *) shift ;;
      esac
    done
    url="$1"; path="${url#http://*/}"; path="/${path%%\?*}"
    # C-2 REST 흉내: 본문 뒤에 줄바꿈과 상태 코드를 쓴다(--write-out '\n%{http_code}').
    respond() { printf '%s\n%s' "$2" "$1"; exit 0; }
    # 파일 첫 줄이 상태 코드, 나머지가 본문이다.
    respond_file() { respond "$(head -n1 "$1")" "$(tail -n +2 "$1")"; }
    if [[ "${method}" == POST ]]; then
      jq -nc --arg path "${path}" --argjson body "${data:-null}" \
        '{path: $path, body: $body, headers: $ARGS.positional}' --args "${headers[@]}" \
        >> "${state}/posts.jsonl"
    fi
    case "${method} ${path}" in
      "GET /api/health") exit 0 ;;
      "GET /api/runs/"*)
        if [[ -e "${state}/rows/${path##*/}" ]]; then printf '200'; else printf '404'; fi
        exit 0 ;;
      "GET /api/order-plan-screening/daily-trigger")
        # 기본값은 사람 결정 전 서버의 답(환경 cap 기본 false, active policy 없음)이다.
        [[ -f "${state}/trigger.json" ]] && respond 200 "$(cat "${state}/trigger.json")"
        respond 200 '{"effective_enabled": false, "policy_version": null, "policy_sha256": null, "switch": null, "reasons": ["env_cap_off", "no_active_policy"]}' ;;
      "GET /api/order-plan-screening/executions")
        run="$(sed -E 's/.*source_run_id=([^&]+).*/\1/' <<<"${url}")"
        respond 200 "$(cat "${state}"/execs/*.json 2>/dev/null | jq -sc --arg run "${run}" \
          '[.[] | select(.source_run_id == $run) | del(._final)] as $items
           | {schema_version: "execution-list-response.v2", items: $items, total: ($items | length), limit: 500, offset: 0}')" ;;
      "POST /api/order-plan-screening/executions")
        [[ -f "${state}/post_execution" ]] && respond_file "${state}/post_execution"
        rid="$(jq -r .request_id <<<"${data}")"
        for f in "${state}"/execs/*.json; do
          [[ -f "${f}" ]] || continue
          if [[ "$(jq -r .request_id "${f}")" == "${rid}" ]]; then
            respond 202 "$(jq -c '{execution_id, request_id, status: "대기"}' "${f}")"
          fi
        done
        n="$(find "${state}/execs" -name '*.json' | wc -l)"; n=$((n + 1))
        final="성공"
        if [[ -s "${state}/outcomes" ]]; then
          final="$(head -n1 "${state}/outcomes")"; sed -i 1d "${state}/outcomes"
        fi
        id="$(printf '00000000-0000-4000-8000-%012d' "${n}")"
        jq -nc --arg id "${id}" --arg final "${final}" --argjson n "${n}" --argjson req "${data}" \
          '{execution_id: $id, request_id: $req.request_id, source_run_id: $req.source_run_id,
            policy_version: $req.policy_version, purpose: "operational", status: "대기", _final: $final,
            finished_at: ("2026-09-18T00:00:" + ($n | tostring | if length < 2 then "0" + . else . end) + "Z")}' \
          > "${state}/execs/$(printf '%03d' "${n}").json"
        respond 202 "$(jq -nc --arg id "${id}" --arg rid "${rid}" '{execution_id: $id, request_id: $rid, status: "대기"}')" ;;
      "GET /api/order-plan-screening/executions/"*/audit-sample)
        [[ -f "${state}/audit_get" ]] && respond_file "${state}/audit_get"
        respond 200 '{"status": "preview", "sample": []}' ;;
      "POST /api/order-plan-screening/executions/"*/audit-sample)
        [[ -f "${state}/audit_post" ]] && respond_file "${state}/audit_post"
        respond 201 '{"status": "drawn", "sample": [{"order_plan_pk": 1}]}' ;;
      "GET /api/order-plan-screening/executions/"*)
        id="${path##*/}"
        for f in "${state}"/execs/*.json; do
          [[ -f "${f}" ]] || continue
          if [[ "$(jq -r .execution_id "${f}")" == "${id}" ]]; then
            # 첫 조회에서 terminal 상태로 넘어간다(worker 흉내).
            jq -c 'if ._final then .status = ._final | del(._final) else . end' "${f}" > "${f}.tmp"
            mv "${f}.tmp" "${f}"
            respond 200 "$(cat "${f}")"
          fi
        done
        respond 404 '{"error": {"code": "not_found"}}' ;;
    esac
    exit 1 ;;
  docker)
    args="$*"
    case "${args}" in
      "compose version") exit 0 ;;
      *" cp "*) exit 0 ;;
      *"exec -T web test -e"*) exit 1 ;;
      *"--collection"*)
        run_id="$(sed -E 's/.*--run ([^ ]+) --collection.*/\1/' <<<"${args}")"
        : > "${state}/rows/${run_id}"
        printf '{"selection": {}}\n'; exit 0 ;;
      *"--tracked-backfill"*) printf '{"counts": {}}\n'; exit 0 ;;
      *"python -c"*) printf '{}\n'; exit 0 ;;
    esac
    exit 1 ;;
  python3)
    script="$1"; shift
    out=""
    while [[ $# -gt 0 ]]; do
      case "$1" in --output-dir) out="$2"; shift 2 ;; *) shift ;; esac
    done
    [[ -n "${out}" && ! -e "${out}" ]] || exit 3
    day="$(sed -E 's/.*lifecycle-([0-9]{8})-.*/\1/' <<<"${out##*/}")"
    mode="complete:2"
    [[ -f "${state}/modes/${day}" ]] && mode="$(cat "${state}/modes/${day}")"
    mkdir -p "${out}/raw"
    printf '{}' > "${out}/raw/page-1.json"
    [[ "${mode}" == "fail" ]] && exit 2
    complete=true; total=0
    if [[ "${mode}" == "incomplete" ]]; then complete=false; else total="${mode#complete:}"; fi
    case "${script}" in
      *collect_order_plans.py)
        printf '{"metadata": {"collection": {"complete": %s}}, "counts": {"total": %s}}' \
          "${complete}" "${total}" > "${out}/collected-order-plans.json"
        exit 0 ;;
      *collect_notices.py)
        printf '{"counts": {"total": %s}}' "${total}" > "${out}/collected-notices.json"
        printf '{"complete": %s}' "${complete}" > "${out}/collection-provenance.json"
        [[ "${complete}" == true ]] && exit 0 || exit 1 ;;
    esac
    exit 1 ;;
esac
exit 1
"""


@dataclass
class Env:
    root: Path
    state: Path
    bin_dir: Path

    @property
    def runs(self) -> Path:
        return self.root / "data" / "runs"

    def run(self, *args: str, script: str = "run-daily-lifecycle.sh", **extra_env: str | None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["BIDOPS_WEB_PORT"] = "18787"
        env.pop("BIDOPS_WORKFLOW_WEB_URL", None)
        env["FAKE_STATE"] = str(self.state)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["BIDOPS_C2_DAILY_ACTOR"] = "cron-operator"
        env["BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS"] = "0"
        env["BIDOPS_C2_DAILY_POLL_INTERVAL_SECONDS"] = "0"
        for key, value in extra_env.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(
            ["bash", str(self.root / "scripts" / script), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def c2(self, *args: str, **extra_env: str | None) -> subprocess.CompletedProcess[str]:
        return self.run(*args, script="run-daily-c2.sh", **extra_env)

    def trigger(self, *, enabled: bool, reasons: list[str] | None = None, policy_version: str | None = "v3") -> None:
        (self.state / "trigger.json").write_text(
            json.dumps(
                {
                    "effective_enabled": enabled,
                    "policy_version": policy_version,
                    "policy_sha256": None,
                    "switch": None,
                    "reasons": reasons or [],
                }
            ),
            encoding="utf-8",
        )

    def trigger_on(self) -> None:
        self.trigger(enabled=True)

    def execution(
        self, run_id: str, status: str, *, policy_version: str = "v3", purpose: str = "operational"
    ) -> str:
        n = len(list((self.state / "execs").glob("*.json"))) + 1
        execution_id = f"00000000-0000-4000-8000-{n:012d}"
        (self.state / "execs" / f"{n:03d}.json").write_text(
            json.dumps(
                {
                    "execution_id": execution_id,
                    "request_id": f"10000000-0000-4000-8000-{n:012d}",
                    "source_run_id": run_id,
                    "policy_version": policy_version,
                    "purpose": purpose,
                    "status": status,
                    "finished_at": f"2026-09-17T00:00:{n:02d}Z",
                }
            ),
            encoding="utf-8",
        )
        return execution_id

    def outcomes(self, *statuses: str) -> None:
        """다음 실행 생성들이 차례로 도달할 terminal 상태."""

        (self.state / "outcomes").write_text("".join(f"{status}\n" for status in statuses), encoding="utf-8")

    def respond(self, name: str, code: int, body: object) -> None:
        """`post_execution`·`audit_get`·`audit_post`의 고정 답."""

        (self.state / name).write_text(f"{code}\n{json.dumps(body)}", encoding="utf-8")

    def posts(self, suffix: str = "") -> list[dict]:
        log = self.state / "posts.jsonl"
        if not log.exists():
            return []
        items = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
        return [item for item in items if item["path"].endswith(suffix)] if suffix else items

    def execution_posts(self) -> list[dict]:
        return self.posts("/executions")

    def draw_posts(self) -> list[dict]:
        return self.posts("/audit-sample")

    def calls(self) -> list[str]:
        log = self.state / "calls.log"
        if not log.exists():
            return []
        return [line for line in log.read_text(encoding="utf-8").splitlines() if line]

    def collected(self) -> list[str]:
        """수집기 호출 순서대로 `--output-dir`의 회차 id."""

        out = []
        for line in self.calls():
            if line.startswith("python3 "):
                parts = line.split()
                out.append(Path(parts[parts.index("--output-dir") + 1]).name)
        return out

    def ingested(self) -> list[str]:
        out = []
        for line in self.calls():
            if line.startswith("docker ") and "--collection" in line:
                parts = line.split()
                out.append(parts[parts.index("--run") + 1])
        return out

    def mode(self, day: str, mode: str) -> None:
        (self.state / "modes" / day).write_text(mode, encoding="utf-8")

    def row(self, run_id: str) -> None:
        (self.state / "rows" / run_id).touch()

    def plans_dir(self, run_id: str, *, complete: bool | None, total: int = 2) -> Path:
        path = self.runs / run_id
        (path / "raw").mkdir(parents=True)
        if complete is not None:
            (path / "collected-order-plans.json").write_text(
                json.dumps({"metadata": {"collection": {"complete": complete}}, "counts": {"total": total}}),
                encoding="utf-8",
            )
        return path

    def notices_dir(self, run_id: str, *, complete: bool | None, total: int = 2) -> Path:
        path = self.runs / run_id
        (path / "raw").mkdir(parents=True)
        (path / "collected-notices.json").write_text(
            json.dumps({"counts": {"total": total}}), encoding="utf-8"
        )
        if complete is not None:
            (path / "collection-provenance.json").write_text(
                json.dumps({"complete": complete}), encoding="utf-8"
            )
        return path


def _snapshot(path: Path) -> dict[str, bytes]:
    return {
        str(item.relative_to(path)): item.read_bytes() for item in sorted(path.rglob("*")) if item.is_file()
    }


def make_env(tmp_path: Path) -> Env:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy2(ROOT / "scripts" / name, root / "scripts" / name)
    (root / "data" / "runs").mkdir(parents=True)
    state = tmp_path / "state"
    (state / "rows").mkdir(parents=True)
    (state / "modes").mkdir()
    (state / "execs").mkdir()
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    for name in ("docker", "python3", "curl"):
        path = bin_dir / name
        path.write_text(_FAKE_BIN, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return Env(root=root, state=state, bin_dir=bin_dir)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return make_env(tmp_path)


# --- S9a: 트랙·창·옵션 (dry-run) ---------------------------------------------


def test_notices_dry_run_prints_four_day_inclusive_window(env: Env) -> None:
    result = env.run("--track", "notices", "--date", "2026-09-17", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "lifecycle-20260917-notices" in result.stdout
    assert "--from-date 2026-09-14 --to-date 2026-09-17" in result.stdout
    assert "refresh_fetch_eligibility" in result.stdout
    assert "collect_order_plans.py" not in result.stdout


def test_order_plans_dry_run_prints_one_day_exclusive_window(env: Env) -> None:
    result = env.run("--track", "order-plans", "--date", "2026-09-17", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "lifecycle-20260917-plans" in result.stdout
    assert "--from-date 2026-09-17 --to-date 2026-09-18" in result.stdout
    assert "collect_notices.py" not in result.stdout
    assert "refresh_fetch_eligibility" not in result.stdout


@pytest.mark.parametrize("track", ["notices", "order-plans"])
def test_dry_run_never_calls_docker_python3_or_curl(track: str, env: Env) -> None:
    result = env.run("--track", track, "--date", "2026-09-17", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert env.calls() == []


def test_missing_track_fails_with_required_message(env: Env) -> None:
    result = env.run("--date", "2026-09-17", "--dry-run")
    assert result.returncode != 0
    assert "--track is required" in result.stderr


def test_invalid_track_value_fails(env: Env) -> None:
    result = env.run("--track", "foo", "--dry-run")
    assert result.returncode != 0
    assert "--track must be order-plans or notices" in result.stderr


def test_collect_only_without_run_suffix_fails(env: Env) -> None:
    result = env.run("--track", "order-plans", "--collect-only", "--dry-run")
    assert result.returncode != 0
    assert "requires --run-suffix" in result.stderr


def test_run_suffix_without_collect_only_fails(env: Env) -> None:
    result = env.run("--track", "notices", "--run-suffix", "x", "--dry-run")
    assert result.returncode != 0
    assert "only valid with --collect-only" in result.stderr


def test_run_suffix_retry_n_is_rejected(env: Env) -> None:
    result = env.run("--track", "notices", "--collect-only", "--run-suffix", "retry1", "--dry-run")
    assert result.returncode != 0
    assert "reserved for recollection" in result.stderr


def test_collect_only_dry_run_skips_ingest_and_uses_suffixed_run_id(env: Env) -> None:
    result = env.run(
        "--track", "order-plans", "--collect-only", "--run-suffix", "late2",
        "--date", "2026-09-17", "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    assert "lifecycle-20260917-plans-late2" in result.stdout
    assert "collect-only" in result.stdout
    assert "ingest.cli" not in result.stdout


def test_default_reference_day_is_yesterday_kst(env: Env) -> None:
    # 자정 경계 flake를 피하려고 실행 전후 두 번 계산해 둘 중 하나와 일치하면 통과로 한다.
    before = datetime.now(ZoneInfo("Asia/Seoul")).date() - timedelta(days=1)
    result = env.run("--track", "notices", "--dry-run")
    after = datetime.now(ZoneInfo("Asia/Seoul")).date() - timedelta(days=1)
    assert result.returncode == 0, result.stderr

    candidates = {before.strftime("lifecycle-%Y%m%d-notices"), after.strftime("lifecycle-%Y%m%d-notices")}
    assert any(candidate in result.stdout for candidate in candidates)


# --- S9b: 회차 조회·-retryN·날짜 범위 -----------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["--from-date", "2026-09-15", "--to-date", "2026-09-17", "--date", "2026-09-16"],
        ["--from-date", "2026-09-15"],
        ["--from-date", "2026-09-17", "--to-date", "2026-09-15"],
        ["--from-date", "2026-09-15", "--to-date", "2026-09-17", "--collect-only", "--run-suffix", "x"],
    ],
)
def test_invalid_range_options_fail_before_any_call(args: list[str], env: Env) -> None:
    result = env.run("--track", "notices", *args)
    assert result.returncode != 0
    assert env.calls() == []


def test_dry_run_prints_each_day_decision_without_web_lookup(env: Env) -> None:
    env.plans_dir("lifecycle-20260915-plans", complete=True)
    env.plans_dir("lifecycle-20260916-plans", complete=True, total=0)
    kept = env.plans_dir("lifecycle-20260917-plans", complete=False)

    result = env.run(
        "--track", "order-plans", "--from-date", "2026-09-15", "--to-date", "2026-09-18", "--dry-run"
    )

    assert result.returncode == 0, result.stderr
    assert "web lookup skipped" in result.stdout
    decisions = [line for line in result.stdout.splitlines() if "] decision " in line]
    assert decisions == [
        "[bidops-workflow] decision 2026-09-15: complete_or_ingest_pending (lifecycle-20260915-plans)",
        "[bidops-workflow] decision 2026-09-16: empty (lifecycle-20260916-plans)",
        "[bidops-workflow] decision 2026-09-17: collect_retry1 (lifecycle-20260917-plans-retry1)",
        "[bidops-workflow] decision 2026-09-18: collect_new (lifecycle-20260918-plans)",
    ]
    assert "--output-dir " + str(env.runs / "lifecycle-20260917-plans-retry1") in result.stdout
    assert env.calls() == []
    assert not (env.runs / "lifecycle-20260917-plans-retry1").exists()
    assert kept.exists()


@pytest.mark.parametrize("track,kind", [("notices", "notices"), ("order-plans", "plans")])
def test_three_day_range_collects_and_ingests_in_date_order(track: str, kind: str, env: Env) -> None:
    env.trigger_on()
    result = env.run("--track", track, "--from-date", "2026-09-15", "--to-date", "2026-09-17")

    assert result.returncode == 0, result.stderr
    expected = [f"lifecycle-2026091{d}-{kind}" for d in (5, 6, 7)]
    assert env.collected() == expected
    assert env.ingested() == expected
    # 날짜 순: 앞 날짜의 적재가 다음 날짜의 수집보다 먼저다.
    order = [line.split()[0] + ":" + ("collect" if line.startswith("python3") else "ingest")
             for line in env.calls() if line.startswith("python3") or "--collection" in line]
    assert order == ["python3:collect", "docker:ingest"] * 3


def test_complete_run_is_skipped(env: Env) -> None:
    env.notices_dir("lifecycle-20260915-notices", complete=True)
    env.row("lifecycle-20260915-notices")

    result = env.run("--track", "notices", "--from-date", "2026-09-15", "--to-date", "2026-09-16")

    assert result.returncode == 0, result.stderr
    assert "decision 2026-09-15: complete (lifecycle-20260915-notices)" in result.stdout
    assert env.collected() == ["lifecycle-20260916-notices"]
    assert env.ingested() == ["lifecycle-20260916-notices"]


def test_incomplete_directory_is_kept_and_retry1_is_collected(env: Env) -> None:
    kept = env.notices_dir("lifecycle-20260915-notices", complete=False)
    before = _snapshot(kept)

    result = env.run("--track", "notices", "--date", "2026-09-15")

    assert result.returncode == 0, result.stderr
    assert _snapshot(kept) == before
    assert env.collected() == ["lifecycle-20260915-notices-retry1"]
    assert env.ingested() == ["lifecycle-20260915-notices-retry1"]


def test_marker_missing_counts_as_incomplete_and_retry2_follows_retry1(env: Env) -> None:
    base = env.plans_dir("lifecycle-20260915-plans", complete=None)
    retry1 = env.plans_dir("lifecycle-20260915-plans-retry1", complete=False)
    snapshots = (_snapshot(base), _snapshot(retry1))
    env.trigger_on()

    result = env.run("--track", "order-plans", "--date", "2026-09-15")

    assert result.returncode == 0, result.stderr
    assert (_snapshot(base), _snapshot(retry1)) == snapshots
    assert env.collected() == ["lifecycle-20260915-plans-retry2"]
    assert env.ingested() == ["lifecycle-20260915-plans-retry2"]


def test_complete_marker_without_run_row_resumes_at_ingest(env: Env) -> None:
    env.plans_dir("lifecycle-20260915-plans", complete=False)
    env.plans_dir("lifecycle-20260915-plans-retry1", complete=True)
    env.trigger_on()

    result = env.run("--track", "order-plans", "--date", "2026-09-15")

    assert result.returncode == 0, result.stderr
    assert "decision 2026-09-15: ingest_pending (lifecycle-20260915-plans-retry1)" in result.stdout
    assert env.collected() == []
    assert env.ingested() == ["lifecycle-20260915-plans-retry1"]
    assert any("/api/runs/lifecycle-20260915-plans-retry1" in line for line in env.calls())


def test_zero_count_collection_completes_without_ingest(env: Env) -> None:
    env.mode("20260915", "complete:0")
    env.notices_dir("lifecycle-20260916-notices", complete=True, total=0)

    result = env.run("--track", "notices", "--from-date", "2026-09-15", "--to-date", "2026-09-16")

    assert result.returncode == 0, result.stderr
    assert env.collected() == ["lifecycle-20260915-notices"]
    assert env.ingested() == []
    assert not any("--tracked-backfill" in line or "python -c" in line for line in env.calls())
    # 빈 회차는 회차 행이 필요 없으므로 조회하지 않는다.
    assert not any("/api/runs/" in line for line in env.calls())
    assert "done for 2026-09-15: empty" in result.stdout
    assert "done for 2026-09-16: empty" in result.stdout


def test_collection_failure_stops_the_track_before_the_next_day(env: Env) -> None:
    env.mode("20260916", "fail")
    env.trigger_on()

    result = env.run("--track", "order-plans", "--from-date", "2026-09-15", "--to-date", "2026-09-17")

    assert result.returncode != 0
    assert env.collected() == ["lifecycle-20260915-plans", "lifecycle-20260916-plans"]
    assert env.ingested() == ["lifecycle-20260915-plans"]
    assert (env.runs / "lifecycle-20260916-plans").is_dir()
    assert not (env.runs / "lifecycle-20260917-plans").exists()


def test_incomplete_collection_with_exit_zero_still_stops_the_track(env: Env) -> None:
    # 발주계획 수집기는 부분 산출물(complete=false)에도 exit 0을 돌려준다.
    env.mode("20260915", "incomplete")
    env.trigger_on()

    result = env.run("--track", "order-plans", "--from-date", "2026-09-15", "--to-date", "2026-09-16")

    assert result.returncode != 0
    assert "not marked complete" in result.stderr
    assert env.collected() == ["lifecycle-20260915-plans"]
    assert env.ingested() == []


def test_order_plans_failure_does_not_stop_the_notices_track(env: Env) -> None:
    env.mode("20260915", "fail")
    env.trigger_on()

    plans = env.run("--track", "order-plans", "--date", "2026-09-15")
    notices = env.run("--track", "notices", "--date", "2026-09-16")

    assert plans.returncode != 0
    assert notices.returncode == 0, notices.stderr
    assert env.ingested() == ["lifecycle-20260916-notices"]


def test_collect_only_does_not_look_up_runs(env: Env) -> None:
    env.notices_dir("lifecycle-20260915-notices", complete=True)

    result = env.run("--track", "notices", "--collect-only", "--run-suffix", "m0", "--date", "2026-09-15")

    assert result.returncode == 0, result.stderr
    assert env.collected() == ["lifecycle-20260915-notices-m0"]
    assert not any(line.startswith(("curl", "docker")) for line in env.calls())
