"""Render-only integration checks: no containers, model calls, or real env files."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess

import pytest
from pydantic import ValidationError

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def selection_env(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BIDOPS_", "COMPOSE_"))}
    env_file = tmp_path / "synthetic.env"
    # Public placeholders only; the test never reads a live .env.
    env_file.write_text((ROOT / ".env.example").read_text() + "\n" + "\n".join([
        "BIDOPS_IMAGE=bidops-test:app", "BIDOPS_DOCUMENT_IMAGE=bidops-test:document",
        "BIDOPS_C2_CAPABILITIES_HOST_PATH=/tmp/bidops-test-capabilities.json",
        "BIDOPS_C2_PROMPT_HOST_PATH=/tmp/bidops-test-prompt.txt",
        "BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS=www.g2b.go.kr",
    ]))
    # Explicitly remove port from template to test each mode's default.
    env_file.write_text("\n".join(l for l in env_file.read_text().splitlines() if not l.startswith("BIDOPS_WEB_PORT=")))
    for key in ("BIDOPS_ENV_FILE", "BIDOPS_MODEL_ENV_FILE", "BIDOPS_C2_ENV_FILE", "BIDOPS_ATTACHMENT_ENV_FILE"):
        env[key] = str(env_file)
    return env


def invoke(env, *args):
    return subprocess.run([str(ROOT / "scripts/compose.sh"), *args], cwd=ROOT, env=env, capture_output=True, text=True)


def render(env, mode, *services):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI is required for render-only checks")
    result = invoke({**env, "BIDOPS_ENV": mode}, "config", "--format", "json", *services)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("mode", ["dev", "mock", "prod"])
def test_docker_layout_keeps_root_context_from_another_directory(selection_env, tmp_path, mode):
    expected = render(selection_env, mode)
    for cwd in (ROOT / "docker", tmp_path):
        result = subprocess.run(
            [str(ROOT / "scripts/compose.sh"), "config", "--format", "json"],
            cwd=cwd, env={**selection_env, "BIDOPS_ENV": mode}, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == expected
    for service in expected["services"].values():
        if "build" in service:
            build = service["build"]
            assert Path(build["context"]) == ROOT
            assert build["dockerfile"].startswith("docker/")
            assert (ROOT / build["dockerfile"]).is_file()


def test_dockerfile_local_copy_sources_resolve_from_repository_root():
    for dockerfile in (ROOT / "docker").glob("*Dockerfile"):
        for line in dockerfile.read_text().splitlines():
            if not line.startswith("COPY ") or "--from=" in line:
                continue
            for source in shlex.split(line)[1:-1]:
                assert (ROOT / source).exists(), (dockerfile.name, source)


@pytest.mark.parametrize(("mode", "project", "port"), [("dev", "bidops-dev", "18789"), ("mock", "bidops-mock", "18790"), ("prod", "bidops", "18788")])
def test_modes_preserve_identity_and_boundaries(selection_env, mode, project, port):
    config = render(selection_env, mode)
    assert config["name"] == project
    services = config["services"]
    assert services["web"]["ports"][0]["published"] == port
    assert services["web"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert all(v["name"].startswith(project + "_") for v in config["volumes"].values())
    assert services["web"]["platform"] == "linux/amd64"
    worker = services["document-worker"]
    assert worker["network_mode"] == "none"
    assert not worker.get("environment")
    assert worker["deploy"]["replicas"] == 2
    assert not services["postgres"].get("ports")
    assert not services["minio"].get("ports")
    # Generic startup must never invoke initialization, migration or queue consumers.
    assert not {"migrate", "postgres-init", "minio-init", "analysis-worker", "prespec-attachment-worker", "slack-worker"} & services.keys()
    assert {"migrate", "minio-init"}.isdisjoint(services["web"].get("depends_on", {}))
    if mode == "prod":
        assert worker["platform"] == "linux/arm64"
        assert services["minio"]["image"].startswith("cgr.dev/chainguard/minio@sha256:")
        assert "model-egress" in services["web"]["networks"]
    else:
        assert "model-egress" not in config["networks"]
        assert "prespec-egress" not in config["networks"]
    if mode == "mock":
        assert services["web"]["environment"]["BIDOPS_ANALYSIS_PROVIDER"] == "mock"


@pytest.mark.parametrize(("mode", "review_mode"), [
    ("dev", "mock_reference"), ("mock", "mock_reference"), ("prod", "live"),
])
def test_engine_switches_render_for_web_and_analysis_worker(selection_env, mode, review_mode):
    names = ("web", "analysis-worker")
    defaults = render(selection_env, mode, *names)["services"]
    for name in names:
        environment = defaults[name]["environment"]
        assert environment["BIDOPS_ENGINE_REVIEW_MODE"] == "off"
        assert environment["BIDOPS_ENGINE_ANALYSIS_ENABLED"] == "false"

    path = Path(selection_env["BIDOPS_ENV_FILE"])
    with path.open("a") as env_file:
        env_file.write(
            f"\nBIDOPS_ENGINE_REVIEW_MODE={review_mode}\n"
            "BIDOPS_ENGINE_ANALYSIS_ENABLED=true\n"
            f"BIDOPS_REFERENCE_WORKFLOW_MODE={'true' if mode == 'dev' else 'false'}\n"
        )
    enabled = render(selection_env, mode, *names)["services"]
    for name in names:
        environment = enabled[name]["environment"]
        assert environment["BIDOPS_ENGINE_REVIEW_MODE"] == review_mode
        assert environment["BIDOPS_ENGINE_ANALYSIS_ENABLED"] == "true"
        assert environment["BIDOPS_REFERENCE_WORKFLOW_MODE"] == ("false" if mode == "prod" else "true")


def test_production_rendered_mock_engine_review_fails_startup(selection_env, monkeypatch):
    names = ("web", "analysis-worker")
    config = render({
        **selection_env,
        "BIDOPS_ENGINE_REVIEW_MODE": "mock_reference",
        "BIDOPS_ENGINE_ANALYSIS_ENABLED": "true",
        "BIDOPS_REFERENCE_WORKFLOW_MODE": "true",
    }, "prod", *names)
    for name in names:
        environment = config["services"][name]["environment"]
        assert environment["BIDOPS_ENV"] == "prod"
        assert environment["BIDOPS_REFERENCE_WORKFLOW_MODE"] == "true"
        for key in ("BIDOPS_ENV", "BIDOPS_ENGINE_REVIEW_MODE", "BIDOPS_ENGINE_ANALYSIS_ENABLED",
                    "BIDOPS_REFERENCE_WORKFLOW_MODE"):
            monkeypatch.setenv(key, environment[key])
        with pytest.raises(ValidationError, match="mock_reference is forbidden in prod"):
            Settings(_env_file=None)


@pytest.mark.parametrize("settings", [
    {"COMPOSE_PROJECT_NAME": "bidops"}, {"COMPOSE_PROJECT_NAME": "bidops-local"},
    {"BIDOPS_ENV": "prod", "COMPOSE_PROJECT_NAME": "bidops-dev"},
    {"COMPOSE_FILE": "foreign.yml"}, {"COMPOSE_PROFILES": "bootstrap"},
    {"BIDOPS_ENV": "mock", "BIDOPS_COMPOSE_FEATURES": "luna"},
    {"BIDOPS_ENV": "typo"}, {"BIDOPS_COMPOSE_FEATURES": "typo"},
])
def test_ambiguous_or_unsafe_selection_fails_before_docker(selection_env, settings):
    result = invoke({**selection_env, **settings, "PATH": "/usr/bin:/bin"}, "config", "--quiet")
    assert result.returncode == 2
    assert "docker: command not found" not in result.stderr


def test_profile_and_file_flags_cannot_bypass_selector(selection_env):
    for flag in ("-f", "--env-file", "-p", "--profile"):
        assert invoke(selection_env, flag, "other", "config").returncode == 2
        assert invoke(selection_env, "config", flag, "other").returncode == 2


def test_initialization_is_explicit_and_make_routes_every_target():
    source = (ROOT / "Makefile").read_text()
    assert "COMPOSE := ./scripts/compose.sh" in source
    assert "docker compose" not in source
    assert "up: start" in source and "start: check-containers" in source
    assert "run --rm --no-deps migrate" in source
    init = (ROOT / "scripts/init-runtime.sh").read_text()
    assert init.index('run --rm postgres-init') < init.index('run --rm migrate') < init.index('run --rm minio-init')


def test_explicit_worker_render_preserves_distinct_production_networks(selection_env):
    result = invoke({**selection_env, "BIDOPS_ENV": "prod"}, "config", "--format", "json", "web", "analysis-worker", "prespec-attachment-worker")
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert "model-egress" in services["analysis-worker"]["networks"]
    assert "prespec-egress" not in services["analysis-worker"]["networks"]
    assert "prespec-egress" in services["prespec-attachment-worker"]["networks"]
    assert "model-egress" not in services["prespec-attachment-worker"]["networks"]
    assert not any(k.startswith("BIDOPS_QUARANTINE") for k in services["analysis-worker"]["environment"])
    assert not any(k.startswith("BIDOPS_MODEL_RESPONSE") for k in services["web"]["environment"])


def test_overview_flag_and_policy_path_render_identically_for_the_three_overview_services(selection_env):
    """개요 run을 등록·실행하는 세 서비스가 같은 플래그·정책 경로를 본다(2026-11-19).

    첨부 worker에 정책 경로가 없으면 그 worker가 등록한 개요 run은 기본 정책 digest를
    동결해 실행 전에 `binding_mismatch`로 끝난다. 합성 env 값만 쓰며 렌더 결과를 출력하지
    않는다 — 비교하는 것은 두 키뿐이다.
    """

    path = Path(selection_env["BIDOPS_ENV_FILE"])
    path.write_text(path.read_text() + "\nBIDOPS_PRESPEC_OVERVIEW_ENABLED=true\n"
                    "BIDOPS_PRESPEC_OVERVIEW_POLICY_PATH=/app/synthetic/prespec-overview-policy-test.json\n")
    services_names = ("web", "analysis-worker", "prespec-attachment-worker")
    result = invoke({**selection_env, "BIDOPS_ENV": "prod"}, "config", "--format", "json", *services_names)
    assert result.returncode == 0, "prod render failed"
    services = json.loads(result.stdout)["services"]
    keys = ("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "BIDOPS_PRESPEC_OVERVIEW_POLICY_PATH")
    rendered = {name: tuple(services[name]["environment"].get(key) for key in keys) for name in services_names}
    assert set(rendered.values()) == {("true", "/app/synthetic/prespec-overview-policy-test.json")}
    # 첨부 worker는 상시 실행(자동 재시작)이다. analysis-worker의 재시작 정책은 이 변경의 대상이 아니다.
    assert services["prespec-attachment-worker"]["restart"] == "unless-stopped"


def test_capability_selection_is_persisted_in_selected_env_and_mock_blocks_it(selection_env):
    path = Path(selection_env["BIDOPS_ENV_FILE"])
    path.write_text(path.read_text() + '\nBIDOPS_COMPOSE_FEATURES="luna"\nBIDOPS_CODEX_AUTH_FILE=/tmp/synthetic-codex-auth.json\n')
    result = invoke(selection_env, "config", "--format", "json", "codex-runner")
    assert result.returncode == 0, result.stderr
    runner = json.loads(result.stdout)["services"]["codex-runner"]
    assert set(runner["networks"]) == {"luna-internal", "luna-egress"}
    assert not runner.get("ports")
    assert invoke({**selection_env, "BIDOPS_ENV": "mock"}, "config", "--quiet").returncode == 2


def test_engine_live_feature_mounts_the_key_only_into_analysis_worker(selection_env):
    """ADR-0081: the OpenAI key is a compose secret of analysis-worker only; web never gets it."""
    path = Path(selection_env["BIDOPS_ENV_FILE"])
    path.write_text(path.read_text() + '\nBIDOPS_COMPOSE_FEATURES="engine-live"\n'
                    'BIDOPS_ENGINE_OPENAI_KEY_FILE=/tmp/synthetic-openai-key\n')
    result = invoke(selection_env, "config", "--format", "json", "web", "analysis-worker")
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    worker, web = rendered["services"]["analysis-worker"], rendered["services"]["web"]
    assert [secret["source"] for secret in worker["secrets"]] == ["engine_openai_key"]
    assert worker["environment"]["BIDOPS_ENGINE_LIVE_KEY_FILE"] == "/run/secrets/engine_openai_key"
    assert not web.get("secrets") and "BIDOPS_ENGINE_LIVE_KEY_FILE" not in web["environment"]
    for service in (web, worker):
        assert service["environment"]["BIDOPS_ENGINE_LIVE_DAILY_NOTICE_CAP"] == "0"
    assert invoke({**selection_env, "BIDOPS_ENV": "mock"}, "config", "--quiet").returncode == 2


def test_local_env_generation_is_private_exclusive_and_never_production(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / "env").mkdir()
    shutil.copy2(ROOT / "scripts/create-dev-env.py", scripts)
    import sys
    result = subprocess.run([sys.executable, str(scripts / "create-dev-env.py")], env={**os.environ, "BIDOPS_ENV": "dev"}, capture_output=True)
    assert result.returncode == 0
    path = tmp_path / "env/dev.env"
    before = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    values = dict(line.split("=", 1) for line in before.decode().splitlines() if line and not line.startswith("#"))
    passwords = [v for k, v in values.items() if k.endswith("_PASSWORD")]
    assert len(passwords) == len(set(passwords))
    subprocess.run([sys.executable, str(scripts / "create-dev-env.py")], env={**os.environ, "BIDOPS_ENV": "dev"}, check=True, capture_output=True)
    assert path.read_bytes() == before
    assert subprocess.run([sys.executable, str(scripts / "create-dev-env.py")], env={**os.environ, "BIDOPS_ENV": "prod"}, capture_output=True).returncode != 0
    assert not (tmp_path / "env/prod.env").exists()


def test_document_lock_preserves_exact_application_versions_and_native_hashes():
    import re
    def versions(path):
        return {re.sub(r"[-_.]", "-", line.split(" --hash=")[0]).lower(): line for line in path.read_text().splitlines() if line and not line.startswith("#")}
    app = versions(ROOT / "web/backend/requirements.lock")
    native = versions(ROOT / "web/backend/requirements-document.lock")
    assert app.keys() == native.keys()
    for name, line in native.items():
        assert "--hash=sha256:" in line
        for digest in re.findall(r"--hash=sha256:[a-f0-9]{64}", app[name]):
            assert digest in line
    dockerfile = (ROOT / "docker/Document.Dockerfile").read_text()
    assert "cargo build --release --locked" in dockerfile
    assert "--require-hashes" in dockerfile
    assert ".sdlc" not in dockerfile


def test_make_down_stops_profiled_project_containers_without_removing_volumes(tmp_path):
    """Real Compose smoke left the profiled analysis worker running with `compose stop`."""
    log = tmp_path / "commands"
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n'
                      'if [ "$1" = ps ]; then printf "aaa111\\nbbb222\\n"; fi\n')
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
           "COMMAND_LOG": str(log), "BIDOPS_ENV": "dev", "COMPOSE_PROJECT_NAME": "bidops-dev"}
    result = subprocess.run(["make", "down"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        "ps --quiet --filter label=com.docker.compose.project=bidops-dev", "stop aaa111 bbb222"]
    log.unlink()
    rejected = subprocess.run(["make", "down"], cwd=ROOT,
                              env={**env, "COMPOSE_PROJECT_NAME": "bidops"}, capture_output=True)
    assert rejected.returncode != 0
    assert not log.exists()
