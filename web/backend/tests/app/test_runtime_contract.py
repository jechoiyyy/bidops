"""Static deployment-boundary checks for the isolated Lean v1 template."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[4]


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
    assert set(analysis["networks"]) == {"database", "analysis"}
    assert analysis["environment"]["BIDOPS_ANALYSIS_WORKER_CONCURRENCY"] == "1"
    assert analysis["environment"]["BIDOPS_VLLM_BASE_URL"] == "${BIDOPS_VLLM_BASE_URL:-http://127.0.0.1:8000/v1}"
    assert analysis["environment"]["BIDOPS_VLLM_ALLOWED_HOSTS"] == "${BIDOPS_VLLM_ALLOWED_HOSTS:-}"
    assert analysis["environment"]["BIDOPS_VLLM_API_KEY"] == "${BIDOPS_VLLM_API_KEY:-EMPTY}"
    assert analysis["environment"]["BIDOPS_OBJECT_STORE_BACKEND"] == "minio"
    assert analysis["environment"]["BIDOPS_STRUCTURE_READ_ACCESS_KEY"].startswith("${BIDOPS_STRUCTURE_READ_ACCESS_KEY")
    assert analysis["environment"]["BIDOPS_MODEL_RESPONSE_ACCESS_KEY"].startswith("${BIDOPS_MODEL_RESPONSE_ACCESS_KEY")
    assert "BIDOPS_SOURCE_ACCESS_KEY" not in analysis["environment"]
    assert "BIDOPS_QUARANTINE_ACCESS_KEY" not in analysis["environment"]
    assert "BIDOPS_ACTIVE_PROFILE_VERSION_ID" not in analysis["environment"]
    assert "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID" not in analysis["environment"]
    assert set(analysis["networks"]) == {"database", "analysis"}
    assert "storage" not in analysis["networks"]
    assert "scanning" not in analysis["networks"]
    assert "vllm" not in analysis["depends_on"]
    assert "pipeline-data:/app/data" in analysis["volumes"]
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


def test_admin_ports_bind_to_loopback_by_default():
    """The application API is the access boundary; admin surfaces are not."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    admin_ports = services["postgres"]["ports"] + services["minio"]["ports"]
    assert admin_ports == [
        "${BIDOPS_ADMIN_BIND_HOST:-127.0.0.1}:${BIDOPS_POSTGRES_PORT:-15432}:5432",
        "${BIDOPS_ADMIN_BIND_HOST:-127.0.0.1}:${BIDOPS_MINIO_PORT:-19000}:9000",
        "${BIDOPS_ADMIN_BIND_HOST:-127.0.0.1}:${BIDOPS_MINIO_CONSOLE_PORT:-19001}:9001",
    ]
    # Every published admin port carries an explicit host-IP field.  A mapping
    # written as "<host>:<container>" lets Docker bind every host interface.
    for mapping in admin_ports:
        assert mapping.count(":") >= 2 and mapping.startswith("${BIDOPS_ADMIN_BIND_HOST:-127.0.0.1}:")


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


def test_remote_vllm_egress_is_an_explicit_override():
    override = yaml.safe_load((ROOT / "docker-compose.remote-vllm.yml").read_text(encoding="utf-8"))
    assert set(override["services"]["analysis-worker"]["networks"]) == {"database", "analysis", "model-egress"}
    assert override["networks"] == {"model-egress": None}
    for service in override["services"].values():
        assert service["environment"]["BIDOPS_C2_CAPABILITIES_PATH"] == "/run/c2/company-capabilities.json"
        assert service["environment"]["BIDOPS_C2_PROMPT_PATH"] == "/run/c2/order-plan-prompt.txt"
        assert all("./experiments/order-plan-screening:" not in volume for volume in service["volumes"])
        assert any(":/run/c2/company-capabilities.json:ro" in volume for volume in service["volumes"])
        assert any(":/run/c2/order-plan-prompt.txt:ro" in volume for volume in service["volumes"])


def test_screening_egress_is_an_explicit_override():
    override = yaml.safe_load((ROOT / "docker-compose.screening.yml").read_text(encoding="utf-8"))
    assert set(override["services"]) == {"web"}
    assert set(override["services"]["web"]["networks"]) == {
        "database", "storage", "scanning", "model-egress",
    }
    assert override["networks"] == {"model-egress": None}
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "model-egress" not in base["networks"]
    assert all(network.get("internal") is True for network in base["networks"].values())


def test_screening_overlay_fails_closed_without_endpoint_host_and_revision():
    """endpoint·허용 host·선언 revision 중 하나라도 없으면 overlay가 멈춘다.

    기본값을 채워 두면 C-1이 승인되지 않은 주소로 조용히 나갈 수 있다. 세
    값에는 `:?` 형식만 쓴다.
    """

    override = yaml.safe_load((ROOT / "docker-compose.screening.yml").read_text(encoding="utf-8"))
    environment = override["services"]["web"]["environment"]
    for name in (
        "BIDOPS_VLLM_SCREENING_BASE_URL",
        "BIDOPS_VLLM_SCREENING_ALLOWED_HOSTS",
        "BIDOPS_VLLM_SCREENING_MODEL_REVISION",
    ):
        assert environment[name].startswith("${" + name + ":?")
    assert environment["BIDOPS_VLLM_SCREENING_MODEL"] == "${BIDOPS_VLLM_SCREENING_MODEL:-qwen3.8-27B}"
    assert not [name for name in environment if "OLLAMA" in name]

    example = (ROOT / "env/screening.env.example").read_text(encoding="utf-8")
    assert "BIDOPS_VLLM_SCREENING_BASE_URL=\n" in example
    assert "BIDOPS_VLLM_SCREENING_ALLOWED_HOSTS=\n" in example
    assert "BIDOPS_VLLM_SCREENING_MODEL_REVISION=\n" in example
    assert "OLLAMA" not in example


def test_prespec_attachment_egress_is_an_explicit_override():
    override = yaml.safe_load(
        (ROOT / "docker-compose.prespec-attachment.yml").read_text(encoding="utf-8")
    )
    assert set(override["services"]) == {"prespec-attachment-worker"}
    worker = override["services"]["prespec-attachment-worker"]
    assert set(worker["networks"]) == {
        "database", "storage", "scanning", "prespec-egress",
    }
    assert worker["environment"]["BIDOPS_G2B_ATTACHMENT_ENABLED"] == "true"
    assert worker["environment"]["BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS"].startswith(
        "${BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS:?"
    )
    assert worker["command"] == ["python", "-m", "app.deep_review.workers.prespec_attachment"]
    assert worker["healthcheck"] == {"disable": True}
    assert override["networks"] == {"prespec-egress": None}
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "prespec-egress" not in base["networks"]
    assert all(network.get("internal") is True for network in base["networks"].values())


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
