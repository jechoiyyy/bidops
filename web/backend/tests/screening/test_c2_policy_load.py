from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.db as core_db
from app.core.db import Base
from app.core.models import AuditEvent
from app.screening.c2_policy import C2PolicyLoadError, load_policy, main
from app.screening.models import OrderPlanScreeningPolicy
from app.screening.services.order_plan_screening import _canonical


REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG = REPO_ROOT / "experiments/order-plan-screening/config"
POLICY_V2 = CONFIG / "order-plan-screening-policy.v2.json"
BINDING_V2 = CONFIG / "order-plan-screening-phase0-binding.v2.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _write_pair(tmp_path: Path, policy: dict, binding: dict | None = None, *, name: str = "pair") -> tuple[Path, Path]:
    """Write a policy copy and a binding whose reference matches its bytes."""

    folder = tmp_path / name
    folder.mkdir()
    policy_path = folder / "policy.json"
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
    binding = json.loads(BINDING_V2.read_bytes()) if binding is None else binding
    binding["policy"]["sha256"] = _sha(policy_path.read_bytes())
    binding["policy"]["policy_version"] = policy["policy_version"]
    binding["policy"]["policy_status"] = policy["policy_status"]
    binding_path = folder / "binding.json"
    binding_path.write_text(json.dumps(binding, ensure_ascii=False, indent=2), encoding="utf-8")
    return policy_path, binding_path


def _load(session: Session, policy_path: Path, binding_path: Path):
    return load_policy(session, policy_path=policy_path, binding_path=binding_path, created_by="담당자")


def test_v2_files_load_as_draft_with_file_byte_digests_and_reload_is_noop(session: Session) -> None:
    policy_bytes = POLICY_V2.read_bytes()
    binding_bytes = BINDING_V2.read_bytes()

    first = _load(session, POLICY_V2, BINDING_V2)
    session.commit()
    row = first.row
    assert first.created is True
    assert row.policy_status == "draft"
    assert row.active_slot is None
    assert row.activated_by is None and row.activated_at is None
    assert row.quality_gate_status == "not_measured"
    # The digest is of the published bytes; the v2 file is not canonical JSON.
    assert row.policy_sha256 == _sha(policy_bytes)
    assert row.binding_sha256 == _sha(binding_bytes)
    assert row.policy_sha256 != _sha(_canonical(json.loads(policy_bytes)))
    audit = session.scalars(select(AuditEvent).where(AuditEvent.action == "c2.policy_loaded")).all()
    assert len(audit) == 1
    assert audit[0].actor_kind == "human" and audit[0].claimed_name == "담당자"
    assert audit[0].aggregate_id == row.policy_version

    second = _load(session, POLICY_V2, BINDING_V2)
    session.commit()
    assert second.created is False
    assert second.row.id == row.id
    assert session.scalar(select(func.count()).select_from(OrderPlanScreeningPolicy)) == 1
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1
    # The source files are only read.
    assert POLICY_V2.read_bytes() == policy_bytes and BINDING_V2.read_bytes() == binding_bytes


def test_same_version_with_one_byte_different_policy_is_immutable_conflict(session: Session, tmp_path: Path) -> None:
    _load(session, POLICY_V2, BINDING_V2)
    session.commit()
    changed = tmp_path / "policy.json"
    changed.write_bytes(POLICY_V2.read_bytes() + b"\n")
    binding = json.loads(BINDING_V2.read_bytes())
    binding["policy"]["sha256"] = _sha(changed.read_bytes())
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(C2PolicyLoadError) as error:
        _load(session, changed, binding_path)
    assert error.value.code == "immutable_conflict"
    assert session.scalar(select(func.count()).select_from(OrderPlanScreeningPolicy)) == 1


def test_file_policy_status_active_still_creates_draft_row(session: Session, tmp_path: Path) -> None:
    policy = json.loads(POLICY_V2.read_bytes())
    policy["policy_version"] = "c2-order-plan-screening-active-copy"
    policy["policy_status"] = "active"
    policy["activation"]["enabled"] = True
    policy["quality_gate"]["status"] = "passed"
    policy_path, binding_path = _write_pair(tmp_path, policy)

    row = _load(session, policy_path, binding_path).row
    session.commit()
    assert row.policy_status == "draft"
    assert row.active_slot is None
    assert row.quality_gate_status == "not_measured"
    assert row.policy_payload_jsonb["policy_status"] == "active"


def test_binding_policy_digest_mismatch_is_rejected(session: Session, tmp_path: Path) -> None:
    binding = json.loads(BINDING_V2.read_bytes())
    binding["policy"]["sha256"] = "0" * 64
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(C2PolicyLoadError) as error:
        _load(session, POLICY_V2, binding_path)
    assert error.value.code == "binding_policy_digest_mismatch"
    assert session.scalar(select(func.count()).select_from(OrderPlanScreeningPolicy)) == 0


@pytest.mark.parametrize(
    ("status", "execution_allowed", "code"),
    [
        ("blocked", True, "binding_blocked_execution_allowed"),
        ("unknown", False, "binding_status_invalid"),
    ],
)
def test_binding_status_contradictions_are_rejected(
    session: Session, tmp_path: Path, status: str, execution_allowed: bool, code: str
) -> None:
    binding = json.loads(BINDING_V2.read_bytes())
    binding["status"] = status
    binding["external_transport"]["execution_allowed"] = execution_allowed
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(C2PolicyLoadError) as error:
        _load(session, POLICY_V2, binding_path)
    assert error.value.code == code


@pytest.mark.parametrize("status", ["activation_candidate", "approved"])
def test_v3_binding_statuses_are_accepted(session: Session, tmp_path: Path, status: str) -> None:
    policy = json.loads(POLICY_V2.read_bytes())
    policy["policy_version"] = f"c2-order-plan-screening-{status}"
    binding = json.loads(BINDING_V2.read_bytes())
    binding["status"] = status
    binding["external_transport"]["execution_allowed"] = True
    policy_path, binding_path = _write_pair(tmp_path, policy, binding)

    assert _load(session, policy_path, binding_path).row.policy_status == "draft"


def test_duplicate_key_in_policy_or_binding_is_rejected(session: Session, tmp_path: Path) -> None:
    raw = POLICY_V2.read_bytes()
    duplicated = tmp_path / "policy.json"
    duplicated.write_bytes(raw.replace(b"{", b'{"producer": "phase0-contracts", ', 1))
    with pytest.raises(C2PolicyLoadError) as error:
        _load(session, duplicated, BINDING_V2)
    assert error.value.code == "policy_duplicate_key"

    duplicated_binding = tmp_path / "binding.json"
    duplicated_binding.write_bytes(BINDING_V2.read_bytes().replace(b"{", b'{"status": "blocked", ', 1))
    with pytest.raises(C2PolicyLoadError) as error:
        _load(session, POLICY_V2, duplicated_binding)
    assert error.value.code == "binding_duplicate_key"


def test_policy_schema_and_binding_version_mismatch_are_rejected(session: Session, tmp_path: Path) -> None:
    policy = json.loads(POLICY_V2.read_bytes())
    policy["decision_scope"] = "c1_notice"
    policy_path, binding_path = _write_pair(tmp_path, policy, name="scope")
    with pytest.raises(C2PolicyLoadError) as error:
        _load(session, policy_path, binding_path)
    assert error.value.code == "policy_schema_invalid"

    binding = json.loads(BINDING_V2.read_bytes())
    binding["policy"]["policy_version"] = "c2-order-plan-screening-other"
    binding_path = tmp_path / "binding-version.json"
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(C2PolicyLoadError) as error:
        _load(session, POLICY_V2, binding_path)
    assert error.value.code == "binding_policy_version_mismatch"


def test_cli_exit_codes_and_output_omit_path_and_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(core_db, "SessionLocal", sessionmaker(bind=engine, class_=Session, expire_on_commit=False))
    argv = ["load", "--policy", str(POLICY_V2), "--binding", str(BINDING_V2), "--created-by", "담당자"]

    assert main(argv) == 0
    assert main(argv) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].endswith(" created") and out[1].endswith(" unchanged")
    assert out[0].split()[1] == "draft"

    secret_dir = tmp_path / "secret-dir"
    secret_dir.mkdir()
    changed = secret_dir / "policy.json"
    changed.write_bytes(POLICY_V2.read_bytes() + b"\n")
    binding = json.loads(BINDING_V2.read_bytes())
    binding["policy"]["sha256"] = _sha(changed.read_bytes())
    binding_path = secret_dir / "binding.json"
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    assert main(["load", "--policy", str(changed), "--binding", str(binding_path), "--created-by", "담당자"]) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == "c2 policy load failed: immutable_conflict"
    assert "secret-dir" not in captured.err and "stage2" not in captured.err

    assert main(["load", "--policy", str(POLICY_V2), "--binding", str(BINDING_V2), "--created-by", "system"]) == 2
    assert capsys.readouterr().err.strip() == "c2 policy load failed: created_by_invalid"


def test_binding_policy_status_must_match_policy_file(session: Session, tmp_path: Path) -> None:
    policy = json.loads(POLICY_V2.read_bytes())
    policy["policy_version"] = "c2-order-plan-screening-status-mismatch"
    policy_path, binding_path = _write_pair(tmp_path, policy)
    binding = json.loads(binding_path.read_bytes())
    binding["policy"]["policy_status"] = "active"
    binding_path.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(C2PolicyLoadError) as error:
        _load(session, policy_path, binding_path)
    assert error.value.code == "binding_policy_status_mismatch"
    assert session.scalar(select(func.count()).select_from(OrderPlanScreeningPolicy)) == 0
