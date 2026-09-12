"""Static deployment-boundary checks for the isolated Lean v1 template."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[4]


def test_runtime_image_installs_native_rhwp_and_pinned_fallback_fonts():
    dockerfile = (ROOT / "web/Dockerfile").read_text(encoding="utf-8")
    binary = "app/deep_review/document_mcp/vendor/rhwp/bin/rhwp"

    # fc-list must be installed explicitly: the font manifest fingerprint
    # requires it and Chromium no longer pulls fontconfig in transitively.
    assert "fontconfig fonts-nanum fonts-noto-cjk" in dockerfile
    assert f"/app/web/backend/{binary}" in dockerfile
    assert (ROOT / "web/backend" / binary).is_file()


def test_runtime_image_copies_only_allowlisted_reference_material():
    dockerfile = (ROOT / "web/Dockerfile").read_text(encoding="utf-8")
    dockerignore_lines = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    copy_instructions = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.lstrip().startswith("COPY ")
    ]

    assert not any(
        re.match(r"^COPY(?:\s+--\S+)*\s+docs/reference(?:\s|$)", line)
        for line in copy_instructions
    )
    assert not any(
        "docs/reference/company-profile.md" in line
        or "[루트랩]회사소개서_260804.pdf" in line
        or "docs/reference/company-performance-titles.tsv" in line
        or "baseline_company_profile.md" in line
        for line in copy_instructions
    )
    assert "COPY web/backend/ ./" in copy_instructions
    assert "docs/reference/*" in dockerignore_lines
    assert "docs/reference/company-performance-titles.tsv" in dockerignore_lines
    assert "web/backend/app/screening/baseline_company_profile.md" in dockerignore_lines
    assert "!docs/reference/company-performance-titles.tsv" not in dockerignore_lines

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    web_volumes = compose["services"]["web"]["volumes"]
    assert (
        "./docs/reference/company-profile.md:/app/docs/reference/company-profile.md:ro"
        in web_volumes
    )
    assert (
        "./docs/reference/company-performance-titles.tsv:/app/docs/reference/company-performance-titles.tsv:ro"
        in web_volumes
    )
    assert (
        "./web/backend/app/screening/baseline_company_profile.md:"
        "/app/web/backend/app/screening/baseline_company_profile.md:ro"
        in web_volumes
    )


def test_real_qwen_is_not_embedded_in_the_application_compose():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "ollama" not in compose["services"]
    assert "vllm" not in compose["services"]


def test_worker_network_and_command_boundaries_are_explicit():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    worker = services["document-worker"]
    assert worker["network_mode"] == "none"
    assert worker["mem_limit"] == "1g"
    assert worker["pids_limit"] == 128
    assert worker["environment"] == {}
    assert worker["command"] == ["python", "-m", "app.deep_review.workers.document"]
    assert worker["deploy"]["replicas"] == 2
    assert worker["volumes"] == ["document-scratch:/scratch"]
    web = services["web"]
    assert set(web["networks"]) == {"database", "storage", "scanning"}
    assert web["environment"]["BIDOPS_CLAMAV_HOST"] == "clamav"
    assert web["environment"]["BIDOPS_OBJECT_STORE_BACKEND"] == "minio"
    assert web["environment"]["BIDOPS_ACTIVE_PROFILE_VERSION_ID"] == "${BIDOPS_ACTIVE_PROFILE_VERSION_ID:-}"
    assert web["environment"]["BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID"] == "${BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID:-}"
    assert "BIDOPS_MODEL_RESPONSE_ACCESS_KEY" not in web["environment"]
    assert "document-scratch:/scratch" in web["volumes"]
    document_worker = (ROOT / "web/backend/app/deep_review/workers/document.py").read_text(encoding="utf-8")
    assert "SessionLocal" not in document_worker and "convert_one" in document_worker

    analysis = services["analysis-worker"]
    assert set(analysis["networks"]) == {"database", "analysis", "scanning"}
    assert analysis["environment"]["BIDOPS_ANALYSIS_WORKER_CONCURRENCY"] == "1"
    assert analysis["environment"]["BIDOPS_VLLM_BASE_URL"] == "${BIDOPS_VLLM_BASE_URL:-http://127.0.0.1:8000/v1}"
    assert analysis["environment"]["BIDOPS_VLLM_ALLOWED_HOSTS"] == "${BIDOPS_VLLM_ALLOWED_HOSTS:-}"
    assert analysis["environment"]["BIDOPS_VLLM_API_KEY"] == "${BIDOPS_VLLM_API_KEY:-EMPTY}"
    assert analysis["environment"]["BIDOPS_OBJECT_STORE_BACKEND"] == "minio"
    assert analysis["environment"]["BIDOPS_STRUCTURE_READ_ACCESS_KEY"].startswith("${BIDOPS_STRUCTURE_READ_ACCESS_KEY")
    assert analysis["environment"]["BIDOPS_MODEL_RESPONSE_ACCESS_KEY"].startswith("${BIDOPS_MODEL_RESPONSE_ACCESS_KEY")
    # The overview runner writes source snapshots and reads/writes structure
    # artifacts from inside this worker, so it needs both credential pairs.
    assert analysis["environment"]["BIDOPS_SOURCE_ACCESS_KEY"].startswith("${BIDOPS_SOURCE_ACCESS_KEY")
    assert analysis["environment"]["BIDOPS_SOURCE_SECRET_KEY"].startswith("${BIDOPS_SOURCE_SECRET_KEY")
    assert analysis["environment"]["BIDOPS_STRUCTURE_ACCESS_KEY"].startswith("${BIDOPS_STRUCTURE_ACCESS_KEY")
    assert analysis["environment"]["BIDOPS_STRUCTURE_SECRET_KEY"].startswith("${BIDOPS_STRUCTURE_SECRET_KEY")
    assert "BIDOPS_QUARANTINE_ACCESS_KEY" not in analysis["environment"]
    assert analysis["environment"]["BIDOPS_CLAMAV_HOST"] == "clamav"
    assert analysis["environment"]["BIDOPS_CLAMAV_PORT"] == "3310"
    assert analysis["environment"]["BIDOPS_CLAMAV_TIMEOUT_SECONDS"] == "15"
    # Company-fit queue construction freezes the active inputs before any call.
    assert analysis["environment"]["BIDOPS_ACTIVE_PROFILE_VERSION_ID"] == "${BIDOPS_ACTIVE_PROFILE_VERSION_ID:-}"
    assert analysis["environment"]["BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID"] == "${BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID:-}"
    for service in (web, analysis):
        assert service["environment"]["BIDOPS_PRESPEC_COMPANY_FIT_ENABLED"] == "${BIDOPS_PRESPEC_COMPANY_FIT_ENABLED:-false}"
        assert service["environment"]["BIDOPS_PRESPEC_COMPANY_FIT_MODEL"] == "${BIDOPS_PRESPEC_COMPANY_FIT_MODEL:-}"
        assert service["environment"]["BIDOPS_PRESPEC_OVERVIEW_ENABLED"] == "${BIDOPS_PRESPEC_OVERVIEW_ENABLED:-false}"
    assert "vllm" not in analysis["depends_on"]
    assert "pipeline-data:/app/data" in analysis["volumes"]
    assert "document-scratch:/scratch" in analysis["volumes"]
    assert all("./experiments/order-plan-screening:" not in volume for volume in web["volumes"] + analysis["volumes"])
    # Only the three approved C-2 artifacts are mounted, never the experiment
    # tree.  The generation config joined them so the runtime reads the values
    # it records instead of hardcoding them ([ADR-0044]).
    for service in (web, analysis):
        for artifact in (
            "order-plan-screening-policy.v2.json",
            "order-plan-screening-phase0-binding.v2.json",
            "order-plan-screening-generation-config.v4.json",
        ):
            assert any(
                volume.startswith(f"./experiments/order-plan-screening/config/{artifact}:")
                for volume in service["volumes"]
            )
    analysis_worker = (ROOT / "web/backend/app/workers/analysis.py").read_text(encoding="utf-8")
    assert "SessionLocal" in analysis_worker and "run_once" in analysis_worker and "rollback" in analysis_worker
    minio = services["minio"]
    assert set(minio["networks"]) == {"storage", "analysis"}


def test_host_exposure_lives_only_in_the_edge_overlay():
    """기반 파일은 host에 아무것도 publish하지 않는다.

    모든 network가 internal이라 Docker는 `ports:`를 조용히 무시한다. 기반
    파일에 선언을 남겨 두면 열린 것처럼 읽히지만 실제로는 닿지 않는다.
    그래서 노출은 edge overlay 하나만 소유한다.
    """

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, service in compose["services"].items():
        assert "ports" not in service, f"{name} declares a port the base stack cannot publish"
    assert all(network.get("internal") is True for network in compose["networks"].values())

    edge = yaml.safe_load((ROOT / "docker-compose.edge.yml").read_text(encoding="utf-8"))
    assert set(edge["services"]) == {"web"}
    assert edge["services"]["web"]["networks"] == ["edge"]
    assert edge["networks"]["edge"]["driver"] == "bridge"
    # 발행 포트는 명시적인 host-IP 필드를 갖는다. "<host>:<container>" 형식은
    # Docker가 모든 host interface에 bind하게 만든다.
    ports = edge["services"]["web"]["ports"]
    assert ports == ["${BIDOPS_WEB_BIND_HOST:-127.0.0.1}:${BIDOPS_WEB_PORT:-18787}:8787"]
    assert ports[0].count(":") >= 2


def test_compose_commands_and_recovery_scripts_exist():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for service in compose["services"].values():
        command = service.get("command")
        if command and command[:3] == ["python", "-m", "app.deep_review.workers.document"]:
            assert (ROOT / "web/backend/app/deep_review/workers/document.py").is_file()
        if command and command[:3] == ["python", "-m", "app.workers.analysis"]:
            assert (ROOT / "web/backend/app/workers/analysis.py").is_file()
        entrypoint = service.get("entrypoint", [])
        if entrypoint and isinstance(entrypoint, list) and entrypoint[0].startswith("/app/scripts/"):
            assert (ROOT / "scripts" / Path(entrypoint[0]).name).is_file()

    for script in ("postgres-init.sh", "migrate.sh", "minio-init.sh", "backup-postgres.sh", "backup-objects.sh", "restore.sh", "generate-active-hash-manifest.sh", "verify-active-hashes.sh", "init-runtime.sh"):
        assert (ROOT / "scripts" / script).is_file()
    ops = compose["services"]["ops"]
    assert ops["profiles"] == ["ops"]
    assert ops["entrypoint"] == ["/bin/sh"]
    assert set(ops["networks"]) == {"database", "storage"}
    assert (ROOT / "web/Ops.Dockerfile").is_file()
    ops_dockerfile = (ROOT / "web/Ops.Dockerfile").read_text(encoding="utf-8")
    assert "COPY --from=minio-client /usr/bin/mc" in ops_dockerfile
    assert "postgresql-client coreutils" in ops_dockerfile
    db_source = (ROOT / "web/backend/app/core/db.py").read_text(encoding="utf-8")
    postgres_branch = db_source.split('if target.dialect.name == "postgresql":', 1)[1].split("else:", 1)[0]
    assert 'connection.execute(text("CREATE SCHEMA' not in postgres_branch
    assert "Base.metadata.create_all" not in postgres_branch
    assert "to_regclass('bidops.run')" in postgres_branch


def test_model_egress_is_one_explicit_override_for_every_purpose():
    """세 용도가 한 transport를 쓰므로 egress overlay도 하나다."""

    override = yaml.safe_load((ROOT / "docker-compose.model-egress.yml").read_text(encoding="utf-8"))
    assert set(override["services"]) == {"web", "analysis-worker"}
    assert override["networks"] == {"model-egress": None}
    for service in override["services"].values():
        assert service["networks"] == ["model-egress"]
        # egress overlay는 network와 설정만 열고 파일을 마운트하지 않는다.
        assert "volumes" not in service

    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "model-egress" not in base["networks"]
    assert all(network.get("internal") is True for network in base["networks"].values())


def test_model_overlay_never_defaults_an_endpoint_for_an_unused_purpose():
    """overlay는 주소를 발명하지 않고, 비면 앱이 fail closed한다.

    기본값을 채워 두면 승인되지 않은 주소로 조용히 나갈 수 있으므로 모든
    endpoint는 빈 기본값이다. 빈 값으로 남은 용도는 `resolve_model_endpoint`가
    네트워크 접촉 전에 거부한다(core/test_model_client.py의
    `test_for_purpose_fails_closed_before_touching_the_network`). 허용 host와 선언
    revision도 MVP 기간 동안 비어 있을 수 있다(ADR-0050 완화).
    """

    override = yaml.safe_load((ROOT / "docker-compose.model-egress.yml").read_text(encoding="utf-8"))
    purposes = ("SCREENING", "OVERVIEW", "DEEP_REVIEW")
    web = override["services"]["web"]["environment"]
    worker = override["services"]["analysis-worker"]["environment"]
    for purpose in purposes:
        for suffix in ("BASE_URL", "ALLOWED_HOSTS", "MODEL_REVISION"):
            name = f"BIDOPS_VLLM_{purpose}_{suffix}"
            assert web[name] == "${" + name + ":-}"
            # 분석 worker는 C-1 판정을 하지 않으므로 screening 설정을 받지 않는다.
            if purpose != "SCREENING":
                assert worker[name] == "${" + name + ":-}"
    assert not [name for name in worker if "SCREENING" in name]
    for name in ("BIDOPS_VLLM_BASE_URL", "BIDOPS_VLLM_ALLOWED_HOSTS", "BIDOPS_VLLM_MODEL_REVISION"):
        assert web[name] == "${" + name + ":-}"
        assert worker[name] == "${" + name + ":-}"
    assert web["BIDOPS_VLLM_SCREENING_MODEL"] == "${BIDOPS_VLLM_SCREENING_MODEL:-qwen3.8-27B}"
    assert not [name for name in {**web, **worker} if "OLLAMA" in name]

    example = (ROOT / "env/model.env.example").read_text(encoding="utf-8")
    for purpose in purposes:
        assert f"BIDOPS_VLLM_{purpose}_BASE_URL=\n" in example
        assert f"BIDOPS_VLLM_{purpose}_ALLOWED_HOSTS=\n" in example
        assert f"BIDOPS_VLLM_{purpose}_MODEL_REVISION=\n" in example
    assert "OLLAMA" not in example


def test_c2_order_plan_inputs_are_a_separate_explicit_override():
    """회사 역량 파일과 프롬프트는 이미지가 아니라 승인된 host 경로에서 온다."""

    override = yaml.safe_load((ROOT / "docker-compose.c2-order-plan.yml").read_text(encoding="utf-8"))
    assert set(override["services"]) == {"web", "analysis-worker"}
    # 이 overlay는 입력만 담당한다. 전송 경로는 model-egress overlay가 열어야 한다.
    assert "networks" not in override
    for service in override["services"].values():
        assert "networks" not in service
        environment = service["environment"]
        assert environment["BIDOPS_C2_EXECUTION_ALLOWED"] == "${BIDOPS_C2_EXECUTION_ALLOWED:-false}"
        assert environment["BIDOPS_C2_CAPABILITIES_PATH"] == "/run/c2/company-capabilities.json"
        assert environment["BIDOPS_C2_PROMPT_PATH"] == "/run/c2/order-plan-prompt.txt"
        assert all("./experiments/order-plan-screening:" not in volume for volume in service["volumes"])
        assert any(":/run/c2/company-capabilities.json:ro" in volume for volume in service["volumes"])
        assert any(":/run/c2/order-plan-prompt.txt:ro" in volume for volume in service["volumes"])
        # 경로를 주지 않으면 overlay가 기동 전에 멈춘다.
        assert any(volume.startswith("${BIDOPS_C2_CAPABILITIES_HOST_PATH:?") for volume in service["volumes"])
        assert any(volume.startswith("${BIDOPS_C2_PROMPT_HOST_PATH:?") for volume in service["volumes"])


def test_prespec_attachment_worker_is_idle_without_its_egress_override():
    """worker는 기반 스택이 profile로 소유하고, overlay는 egress만 연다."""

    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    worker = base["services"]["prespec-attachment-worker"]
    assert worker["profiles"] == ["prespec"]
    assert set(worker["networks"]) == {"database", "storage", "scanning"}
    assert worker["environment"]["BIDOPS_G2B_ATTACHMENT_ENABLED"] == "false"
    assert "BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS" not in worker["environment"]
    assert worker["command"] == ["python", "-m", "app.deep_review.workers.prespec_attachment"]
    assert worker["healthcheck"] == {"disable": True}
    assert "document-scratch:/scratch" in worker["volumes"]
    assert "BIDOPS_STRUCTURE_ACCESS_KEY" in worker["environment"]
    assert "BIDOPS_STRUCTURE_SECRET_KEY" in worker["environment"]

    web_environment = base["services"]["web"]["environment"]
    assert "BIDOPS_STRUCTURE_READ_ACCESS_KEY" in web_environment
    assert "BIDOPS_STRUCTURE_READ_SECRET_KEY" in web_environment
    assert "prespec-egress" not in base["networks"]
    assert all(network.get("internal") is True for network in base["networks"].values())

    override = yaml.safe_load(
        (ROOT / "docker-compose.prespec-attachment.yml").read_text(encoding="utf-8")
    )
    assert set(override["services"]) == {"prespec-attachment-worker"}
    overlay_worker = override["services"]["prespec-attachment-worker"]
    assert overlay_worker["networks"] == ["prespec-egress"]
    assert overlay_worker["environment"]["BIDOPS_G2B_ATTACHMENT_ENABLED"] == "true"
    assert overlay_worker["environment"]["BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS"].startswith(
        "${BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS:?"
    )
    assert override["networks"] == {"prespec-egress": None}


def test_non_http_workers_disable_the_shared_web_image_healthcheck():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name in ("document-worker", "analysis-worker"):
        assert compose["services"][name]["healthcheck"] == {"disable": True}


def test_mock_reference_override_has_no_model_egress_or_external_provider_gate():
    override = yaml.safe_load((ROOT / "docker-compose.mock-reference.yml").read_text(encoding="utf-8"))
    assert set(override["services"]) == {"web", "analysis-worker"}
    for service in override["services"].values():
        environment = service["environment"]
        assert environment["BIDOPS_ANALYSIS_PROVIDER"] == "mock"
        assert environment["BIDOPS_REFERENCE_WORKFLOW_MODE"] == "true"
        assert environment["BIDOPS_OPENAI_ENABLED"] == "false"
        assert "networks" not in service and "volumes" not in service


def test_minio_versioning_and_object_first_recovery_contract():
    bootstrap = (ROOT / "scripts/minio-init.sh").read_text(encoding="utf-8")
    backup = (ROOT / "scripts/backup-objects.sh").read_text(encoding="utf-8")
    restore = (ROOT / "scripts/restore.sh").read_text(encoding="utf-8")
    generate_active = (ROOT / "scripts/generate-active-hash-manifest.sh").read_text(encoding="utf-8")
    verify = (ROOT / "scripts/verify-active-hashes.sh").read_text(encoding="utf-8")
    assert bootstrap.count("mc version enable") == 1
    # Versioning must fail closed: no swallowed failure, and the enabled state is
    # read back because `mc version info` exits 0 for an un-versioned bucket too.
    assert "|| true" not in bootstrap.split("mc version enable")[1].splitlines()[0]
    assert 'mc version info --json "local/$bucket"' in bootstrap
    assert '*\'"versioning":{"status":"Enabled"\'*)' in bootstrap
    assert '"bucket versioning is not enabled: $bucket" >&2' in bootstrap
    assert "for bucket in bidops-source bidops-structure bidops-quarantine bidops-model-response" in bootstrap
    assert "mc ilm add --expire-days 90 local/bidops-model-response" in bootstrap
    assert "mc find --versions" in backup and "object-versions.tsv" in backup
    assert "--version-id" in backup
    assert "{version}\\t{}" in backup and 'suffix=" ($version_id)"' in backup
    assert "RESTORE_MINIO_ALIAS" in restore
    assert restore.index("version_manifest") < restore.index("pg_restore")
    assert "object-version-mapping.tsv" in restore
    assert "target_version_id" in restore and "mc stat --json" in restore
    assert "versioned object backup hash verification failed" in restore
    assert "generate-active-hash-manifest.sh" in restore
    assert "psql" in generate_active
    assert "content_object_location" in generate_active
    assert "content.sha256" in generate_active
    assert "location.status = 'verified'" in generate_active
    assert "location.purged_at IS NULL" in generate_active
    assert "OBJECT_VERIFY_ALIAS" in verify
    assert "OBJECT_VERSION_MAPPING_MANIFEST" in verify
    assert "mc stat --version-id \"$target_version_id\"" in verify
    assert "mc cat --version-id \"$target_version_id\"" in verify
    assert "active hash manifest does not match database active object set" in verify
    assert "restored object missing" in verify
    assert "restored object extra" in verify
    assert "duplicate active object" in verify
    assert "duplicate source mapping" in verify
    assert "duplicate target object" in verify
    assert "comm -23" in verify and "comm -13" in verify
    assert "SELECT 1 FROM bidops.document_bundle LIMIT 1" not in verify


def test_web_test_entry_point_runs_every_declared_gate():
    """The named entry point is the gate; a check outside it is optional.

    `docs/standards.md` requires backend tests, a production build, and screen
    regression for web changes.  Each of those lived in prose or in a separate
    command at some point, and a gate that has to be remembered separately is
    the one that gets skipped.  Pin all three to this script so dropping one is
    a test failure rather than a quiet loss of coverage.
    """

    harness = (ROOT / "web/run-web-tests.sh").read_text(encoding="utf-8")

    assert '"$PYTHON" -m pytest' in harness
    assert "npm run build" in harness
    # 화면 게이트는 의미·구조 두 층을 함께 도는 `test:screens`다. 스크립트가
    # 실제로 부르는 이름을 그대로 고정한다 — 스크립트에만 있고 여기에 없는
    # 게이트가 생기면 조용히 빠질 수 있기 때문이다.
    assert "npm run test:screens" in harness
    declared = {
        line.split("npm run ", 1)[1].strip()
        for line in harness.splitlines()
        if line.strip().startswith("npm run ")
    }
    assert declared == {"build", "test:screens"}

    # PostgreSQL is not optional here.  Without a maintenance URL the backend
    # suite skips every `requires_postgres` test and still exits 0, so the
    # script must supply one or refuse to run.
    assert 'export BIDOPS_TEST_POSTGRES_URL="$TEST_PG_ADMIN_URL"' in harness
    assert "set -euo pipefail" in harness
