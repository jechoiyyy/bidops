"""Static deployment-boundary checks for the isolated Lean v1 template."""

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[3]


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
    assert "BIDOPS_MODEL_RESPONSE_ACCESS_KEY" not in web["environment"]
    assert "document-scratch:/scratch" in web["volumes"]
    document_worker = (ROOT / "web/backend/app/workers/document.py").read_text(encoding="utf-8")
    assert "SessionLocal" not in document_worker and "convert_one" in document_worker

    analysis = services["analysis-worker"]
    assert set(analysis["networks"]) == {"database", "analysis"}
    assert analysis["environment"]["BIDOPS_ANALYSIS_WORKER_CONCURRENCY"] == "1"
    assert analysis["environment"]["BIDOPS_OLLAMA_ALLOWED_HOSTS"] == "ollama"
    assert analysis["environment"]["BIDOPS_OBJECT_STORE_BACKEND"] == "minio"
    assert analysis["environment"]["BIDOPS_STRUCTURE_READ_ACCESS_KEY"].startswith("${BIDOPS_STRUCTURE_READ_ACCESS_KEY")
    assert analysis["environment"]["BIDOPS_MODEL_RESPONSE_ACCESS_KEY"].startswith("${BIDOPS_MODEL_RESPONSE_ACCESS_KEY")
    assert "BIDOPS_SOURCE_ACCESS_KEY" not in analysis["environment"]
    assert "BIDOPS_QUARANTINE_ACCESS_KEY" not in analysis["environment"]
    assert set(analysis["networks"]) == {"database", "analysis"}
    assert "storage" not in analysis["networks"]
    assert "scanning" not in analysis["networks"]
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
