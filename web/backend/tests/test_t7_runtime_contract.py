"""Static deployment-boundary checks for the isolated Lean v1 template."""

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[3]


def test_real_qwen_is_not_embedded_in_the_application_compose():
    compose = yaml.safe_load((ROOT / "docker-compose.t7.yml").read_text(encoding="utf-8"))
    assert "ollama" not in compose["services"]
    assert "vllm" not in compose["services"]


def test_t7_worker_network_and_command_boundaries_are_explicit():
    compose = yaml.safe_load((ROOT / "docker-compose.t7.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    worker = services["document-worker"]
    assert worker["network_mode"] == "none"
    assert worker["environment"] == {}
    assert worker["command"] == ["python", "-m", "app.workers.document"]
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
    document_worker = (ROOT / "web/backend/app/workers/document.py").read_text(encoding="utf-8")
    assert "SessionLocal" not in document_worker and "convert_one" in document_worker

    analysis = services["analysis-worker"]
    assert set(analysis["networks"]) == {"database", "analysis"}
    assert analysis["environment"]["BIDOPS_ANALYSIS_WORKER_CONCURRENCY"] == "1"
    assert analysis["environment"]["BIDOPS_VLLM_BASE_URL"] == "${BIDOPS_VLLM_BASE_URL:-http://127.0.0.1:8000/v1}"
    assert analysis["environment"]["BIDOPS_VLLM_ALLOWED_HOSTS"] == "${BIDOPS_VLLM_ALLOWED_HOSTS:-}"
    assert analysis["environment"]["BIDOPS_VLLM_MODEL"] == "qwen3.8-27B"
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
    analysis_worker = (ROOT / "web/backend/app/workers/analysis.py").read_text(encoding="utf-8")
    assert "SessionLocal" in analysis_worker and "run_once" in analysis_worker and "rollback" in analysis_worker
    minio = services["minio"]
    assert set(minio["networks"]) == {"storage", "analysis"}


def test_t7_compose_commands_and_recovery_scripts_exist():
    compose = yaml.safe_load((ROOT / "docker-compose.t7.yml").read_text(encoding="utf-8"))
    for service in compose["services"].values():
        command = service.get("command")
        if command and command[:3] == ["python", "-m", "app.workers.document"]:
            assert (ROOT / "web/backend/app/workers/document.py").is_file()
        if command and command[:3] == ["python", "-m", "app.workers.analysis"]:
            assert (ROOT / "web/backend/app/workers/analysis.py").is_file()
        entrypoint = service.get("entrypoint", [])
        if entrypoint and isinstance(entrypoint, list) and entrypoint[0].startswith("/app/scripts/"):
            assert (ROOT / "scripts" / Path(entrypoint[0]).name).is_file()

    for script in ("postgres-init.sh", "migrate.sh", "minio-init.sh", "backup-postgres.sh", "backup-objects.sh", "restore.sh", "verify-active-hashes.sh", "init-runtime.sh"):
        assert (ROOT / "scripts" / script).is_file()
    ops = compose["services"]["ops"]
    assert ops["profiles"] == ["ops"]
    assert ops["entrypoint"] == ["/bin/sh"]
    assert set(ops["networks"]) == {"database", "storage"}
    assert (ROOT / "web/Ops.Dockerfile").is_file()
    ops_dockerfile = (ROOT / "web/Ops.Dockerfile").read_text(encoding="utf-8")
    assert "COPY --from=minio-client /usr/bin/mc" in ops_dockerfile
    assert "postgresql-client coreutils" in ops_dockerfile
    db_source = (ROOT / "web/backend/app/db.py").read_text(encoding="utf-8")
    postgres_branch = db_source.split('if target.dialect.name == "postgresql":', 1)[1].split("else:", 1)[0]
    assert 'connection.execute(text("CREATE SCHEMA' not in postgres_branch
    assert "Base.metadata.create_all" not in postgres_branch
    assert "to_regclass('bidops.run')" in postgres_branch


def test_remote_vllm_egress_is_an_explicit_override():
    override = yaml.safe_load((ROOT / "docker-compose.t7.remote-vllm.yml").read_text(encoding="utf-8"))
    assert set(override["services"]["analysis-worker"]["networks"]) == {"database", "analysis", "model-egress"}
    assert override["networks"] == {"model-egress": None}


def test_non_http_workers_disable_the_shared_web_image_healthcheck():
    compose = yaml.safe_load((ROOT / "docker-compose.t7.yml").read_text(encoding="utf-8"))
    for name in ("document-worker", "analysis-worker"):
        assert compose["services"][name]["healthcheck"] == {"disable": True}


def test_codex_reference_override_is_explicitly_gated_and_worker_scoped():
    override = yaml.safe_load((ROOT / "docker-compose.t7.codex-reference.yml").read_text(encoding="utf-8"))
    web = override["services"]["web"]
    worker = override["services"]["analysis-worker"]
    assert web["environment"]["BIDOPS_ANALYSIS_PROVIDER"] == "codex-exec"
    assert web["environment"]["BIDOPS_OPENAI_ENABLED"] == "true"
    assert "BIDOPS_CODEX_EXEC_APPROVED_NOTICE_IDS" in web["environment"]
    assert worker["environment"]["BIDOPS_CODEX_EXEC_BIN"] == "/usr/local/bin/codex"
    assert worker["environment"]["CODEX_HOME"] == "/codex-home"
    assert "codex-egress" in worker["networks"]
    assert all(volume["read_only"] is True for volume in worker["volumes"])
    assert "volumes" not in web


def test_mock_reference_override_has_no_model_egress_or_external_provider_gate():
    override = yaml.safe_load((ROOT / "docker-compose.t7.mock-reference.yml").read_text(encoding="utf-8"))
    assert set(override["services"]) == {"web", "analysis-worker"}
    for service in override["services"].values():
        environment = service["environment"]
        assert environment["BIDOPS_ANALYSIS_PROVIDER"] == "mock"
        assert environment["BIDOPS_REFERENCE_WORKFLOW_MODE"] == "true"
        assert environment["BIDOPS_OPENAI_ENABLED"] == "false"
        assert environment["BIDOPS_CODEX_EXEC_ENABLED"] == "false"
        assert "networks" not in service and "volumes" not in service


def test_t7_minio_versioning_and_object_first_recovery_contract():
    bootstrap = (ROOT / "scripts/minio-init.sh").read_text(encoding="utf-8")
    backup = (ROOT / "scripts/backup-objects.sh").read_text(encoding="utf-8")
    restore = (ROOT / "scripts/restore.sh").read_text(encoding="utf-8")
    verify = (ROOT / "scripts/verify-active-hashes.sh").read_text(encoding="utf-8")
    assert bootstrap.count("mc version enable") == 1
    assert "for bucket in bidops-source bidops-structure bidops-quarantine bidops-model-response" in bootstrap
    assert "mc ilm add --expire-days 90 local/bidops-model-response" in bootstrap
    assert "mc find --versions" in backup and "object-versions.tsv" in backup
    assert "--version-id" in backup
    assert "RESTORE_MINIO_ALIAS" in restore
    assert restore.index("version_manifest") < restore.index("pg_restore")
    assert "OBJECT_VERIFY_ALIAS" in verify and "mc stat --version-id" in verify and "mc cat --version-id" in verify
    assert verify.index("mc cat") < verify.index("psql")
