"""Fresh-process CLI contract for DEMO-02 company knowledge."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.company_ontology import parse_ontology
from app.core.db import schema_bound
from app.deep_review.services import assets
from app.deep_review.services.company_knowledge import (
    activate_company_knowledge,
    import_company_knowledge,
    prepare_company_knowledge,
)
from tests.app.test_runtime_database_privileges import _apply_policy, _ensure_roles
from tests.deep_review.test_company_knowledge import _ontology, _raw, _source
from tests.postgres import requires_postgres, temporary_database


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parents[1]


def _files(tmp_path: Path) -> tuple[Path, Path]:
    ontology_path = tmp_path / "ontology.json"
    company_path = tmp_path / "company.json"
    ontology_raw = _raw(_ontology())
    ontology_path.write_bytes(ontology_raw)
    company_path.write_bytes(_raw(_source(parse_ontology(ontology_raw).sha256)))
    return ontology_path, company_path


def _environment(tmp_path: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "BIDOPS_ROOT": str(PROJECT_ROOT),
            "BIDOPS_DATA_DIR": str(tmp_path / "data"),
            "BIDOPS_ATTACHMENTS_DIR": str(tmp_path / "attachments"),
            "BIDOPS_DATABASE_URL": f"sqlite:///{tmp_path / 'company-knowledge.db'}",
            "BIDOPS_OBJECT_STORE_BACKEND": "filesystem",
            "BIDOPS_TEST_MODE": "1",
            "BIDOPS_OPENAI_ENABLED": "false",
            "BIDOPS_VLLM_BASE_URL": "http://127.0.0.1:9/v1",
            "PYTHONPATH": str(BACKEND_ROOT),
        }
    )
    return environment


def _run(environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.deep_review.cli", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_t5_dry_run_has_zero_database_object_and_model_side_effects(tmp_path: Path) -> None:
    ontology, company = _files(tmp_path)
    environment = _environment(tmp_path)
    result = _run(
        environment,
        "import-company-knowledge",
        "--ontology", str(ontology),
        "--company", str(company),
        "--actor", "등록 담당자",
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["company_id"] is None
    assert payload["profile_version_id"] is None
    assert payload["graph_version_id"] is None
    assert payload["created"] is False
    assert payload["activated"] is False
    assert payload["errors"] == []
    assert payload["ontology_version"] == "ontology-v1"
    assert len(payload["source_sha256"]) == len(payload["graph_sha256"]) == 64
    assert not (tmp_path / "company-knowledge.db").exists()
    assert not (tmp_path / "attachments").exists()


def test_t5_fresh_process_import_replay_and_activate_are_json_only(tmp_path: Path) -> None:
    ontology, company = _files(tmp_path)
    environment = _environment(tmp_path)
    command = (
        "import-company-knowledge",
        "--ontology", str(ontology),
        "--company", str(company),
        "--actor", "등록 담당자",
    )
    created_result = _run(environment, *command)
    assert created_result.returncode == 0, created_result.stderr
    assert created_result.stderr == ""
    created = json.loads(created_result.stdout)
    assert created["created"] is True
    assert created["activated"] is False

    # The fresh process registered the company through the lifecycle public
    # service, which writes its own audit event in the same transaction.
    from app.core.models import AuditEvent
    from app.lifecycle.models import Company
    from sqlalchemy import select

    database = create_engine(f"sqlite:///{tmp_path / 'company-knowledge.db'}")
    try:
        with Session(database) as session:
            audits = list(
                session.scalars(
                    select(AuditEvent).where(AuditEvent.action == "company.register")
                )
            )
            company_row = session.scalar(select(Company))
    finally:
        database.dispose()
    assert company_row is not None and str(company_row.id) == created["company_id"]
    assert [(audit.aggregate_id, audit.claimed_name) for audit in audits] == [
        (created["company_id"], "등록 담당자")
    ]

    replay_result = _run(environment, *command)
    assert replay_result.returncode == 0, replay_result.stderr
    replay = json.loads(replay_result.stdout)
    assert replay["created"] is False
    assert replay["company_id"] == created["company_id"]
    assert replay["profile_version_id"] == created["profile_version_id"]
    assert replay["graph_version_id"] == created["graph_version_id"]

    activate = (
        "activate-company-knowledge",
        "--company-id", created["company_id"],
        "--graph-version-id", created["graph_version_id"],
        "--actor", "활성 담당자",
    )
    activated_result = _run(environment, *activate)
    assert activated_result.returncode == 0, activated_result.stderr
    activated = json.loads(activated_result.stdout)
    assert activated["changed"] is True
    assert activated["revision"] == 1
    assert activated["profile_version_id"] == created["profile_version_id"]

    replay_activation_result = _run(environment, *activate)
    assert replay_activation_result.returncode == 0, replay_activation_result.stderr
    replay_activation = json.loads(replay_activation_result.stdout)
    assert replay_activation["changed"] is False
    assert replay_activation["revision"] == 1


def test_t5_failure_keeps_result_shape_and_hides_internal_details(tmp_path: Path) -> None:
    ontology, company = _files(tmp_path)
    company.write_text("not-json", encoding="utf-8")
    result = _run(
        _environment(tmp_path),
        "import-company-knowledge",
        "--ontology", str(ontology),
        "--company", str(company),
        "--actor", "등록 담당자",
        "--dry-run",
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert set(payload) == {
        "company_id", "profile_version_id", "graph_version_id",
        "ontology_version", "source_sha256", "graph_sha256",
        "created", "activated", "errors",
    }
    assert payload["errors"] == ["source_invalid"]
    assert result.stderr.strip() == "source_invalid"
    assert str(company) not in result.stdout + result.stderr
    assert "not-json" not in result.stdout + result.stderr


@requires_postgres
def test_t3_t4_t7_app_role_runs_import_and_activation_with_closed_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real app credential, including ContentObject and advisory lock paths."""

    stored: dict[tuple[str, str], tuple[bytes, assets.ObjectMetadata]] = {}

    def store_named(namespace, key, data, **_kwargs):
        import hashlib

        digest = hashlib.sha256(data).hexdigest()
        metadata = assets.ObjectMetadata(namespace, key, f"v-{digest}", digest, len(data))
        stored[(namespace, key)] = (data, metadata)
        return Path(key), metadata

    def read_object(namespace, key, *, version_id=None, **_kwargs):
        data, metadata = stored[(namespace, key)]
        assert version_id is None or version_id == metadata.object_version_id
        return data, metadata

    monkeypatch.setattr(assets, "store_named", store_named)
    monkeypatch.setattr(assets, "read_object", read_object)
    first_ontology_raw = _raw(_ontology())
    ontology_sha = parse_ontology(first_ontology_raw).sha256
    first = prepare_company_knowledge(first_ontology_raw, _raw(_source(ontology_sha)))
    second = prepare_company_knowledge(
        first_ontology_raw,
        _raw(_source(ontology_sha, scenario="scenario-v2", description="두번째 합성 역량")),
    )

    _ensure_roles()
    with temporary_database() as database_url:
        policy_engine = _apply_policy(database_url)
        app_engine = schema_bound(create_engine(database_url, future=True))
        try:
            with app_engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL ROLE app")
                with Session(bind=connection, expire_on_commit=False) as session:
                    with session.begin():
                        first_row = import_company_knowledge(
                            session, first, actor="등록 담당자"
                        )
                        active = activate_company_knowledge(
                            session,
                            company_id=first_row.company_id,
                            graph_version_id=first_row.graph_version_id,
                            actor="활성 담당자",
                        )
                        second_row = import_company_knowledge(
                            session, second, actor="등록 담당자"
                        )
                        replaced = activate_company_knowledge(
                            session,
                            company_id=first_row.company_id,
                            graph_version_id=second_row.graph_version_id,
                            actor="활성 담당자",
                        )
                        assert active.revision == 1
                        assert replaced.revision == 2

            denied = (
                ("worker", "SELECT 1 FROM bidops.company_knowledge_binding"),
                ("app", "UPDATE bidops.company SET name = name"),
                (
                    "app",
                    "UPDATE bidops.knowledge_ontology_version SET sha256 = sha256",
                ),
                (
                    "app",
                    "UPDATE bidops.company_knowledge_binding "
                    "SET revision = revision + 1, graph_version_id = graph_version_id",
                ),
            )
            for role, statement in denied:
                with pytest.raises(DBAPIError):
                    with app_engine.begin() as connection:
                        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
                        connection.exec_driver_sql(statement)
        finally:
            app_engine.dispose()
            policy_engine.dispose()


def test_n2_overlong_ontology_version_is_a_validation_error_with_exit_2(tmp_path: Path) -> None:
    from app.core.company_ontology import OntologyValidationError

    ontology_value = _ontology()
    ontology_value["version"] = "v" * 129
    ontology_raw = _raw(ontology_value)
    try:
        ontology_sha = parse_ontology(ontology_raw).sha256
    except OntologyValidationError:
        ontology_sha = "0" * 64
    source = _source(ontology_sha)
    source["ontology_version"] = ontology_value["version"]
    ontology_path = tmp_path / "ontology.json"
    company_path = tmp_path / "company.json"
    ontology_path.write_bytes(ontology_raw)
    company_path.write_bytes(_raw(source))
    result = _run(
        _environment(tmp_path),
        "import-company-knowledge",
        "--ontology", str(ontology_path),
        "--company", str(company_path),
        "--actor", "등록 담당자",
    )
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["errors"] == ["ontology_invalid"]
    assert payload["created"] is False
    assert payload["company_id"] is None
    assert result.stderr.strip() == "ontology_invalid"
