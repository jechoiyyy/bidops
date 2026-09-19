"""C-2 참조 적재는 policy 행을 활성으로 만들지 못한다 (ADR-0060, plan S16).

활성 여부의 정본은 DB 행이다. 실행 디렉터리 참조 적재는 새 행을 비활성으로만 만들고,
적재 CLI·활성화 API가 만든 기존 행은 digest가 같으면 상태 열을 보지 않고 그대로 쓴다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.lifecycle import ingest_run
from app.lifecycle.models import Run
from app.screening.ingest import (
    OrderPlanScreeningConflictError,
    OrderPlanScreeningContractError,
)
from app.screening.models import OrderPlanScreeningExecution, OrderPlanScreeningPolicy
from tests.c2_fixtures import write_c2_fixture, write_c2_json
from tests.postgres import migrated_engine, requires_postgres


@pytest.fixture(autouse=True)
def _screening_registered(screening_extensions):
    """C-2 디렉터리 인식은 screening hook이 등록돼 있을 때만 일어난다."""


def _write_policy_fixture(tmp_path: Path, *, policy_status: str, gate_status: str = "not_measured",
                          approved: bool = False, variant: str | None = None) -> tuple[Path, str]:
    """고정 픽스처의 policy 파일 상태성 필드만 바꾸고 digest 사슬을 다시 잇는다."""

    run_dir, source_run_id = write_c2_fixture(tmp_path)
    root = Path(__file__).resolve().parents[4]
    config = root / "experiments/order-plan-screening/config"
    policy = json.loads((config / "order-plan-screening-policy.v1.json").read_bytes())
    binding = json.loads((config / "order-plan-screening-phase0-binding.v1.json").read_bytes())
    policy["policy_version"] = f"s16-reference-{policy_status}-{gate_status}"
    policy["policy_status"] = policy_status
    policy["quality_gate"]["status"] = gate_status
    if approved:
        policy["activation"].update(status="approved", enabled=True, approved_by="파일 승인자",
                                    approved_at="2026-09-01T00:00:00+00:00")
    if variant is not None:
        policy["feedback"]["s16_variant"] = variant
    policy_sha = write_c2_json(run_dir / "policy.json", policy)
    binding["policy"].update(policy_version=policy["policy_version"], sha256=policy_sha,
                             policy_status=policy_status)
    binding_sha = write_c2_json(run_dir / "binding.json", binding)
    frozen = json.loads((run_dir / "screening-input.json").read_bytes())
    frozen["policy"].update(version=policy["policy_version"], sha256=policy_sha)
    frozen["stage2_binding"]["sha256"] = binding_sha
    input_sha = write_c2_json(run_dir / "screening-input.json", frozen)
    ranking = json.loads((run_dir / "screening-ranking.json").read_bytes())
    ranking.update(input_artifact_sha256=input_sha, policy_version=policy["policy_version"], policy_sha256=policy_sha)
    ranking_sha = write_c2_json(run_dir / "screening-ranking.json", ranking)
    decisions = json.loads((run_dir / "screening-decisions.json").read_bytes())
    decisions.update(input_artifact_sha256=input_sha, ranking_artifact_sha256=ranking_sha)
    write_c2_json(run_dir / "screening-decisions.json", decisions)
    result = json.loads((run_dir / "screening-results.json").read_bytes())
    result.update(input_artifact_sha256=input_sha, policy_version=policy["policy_version"], policy_sha256=policy_sha)
    write_c2_json(run_dir / "screening-results.json", result)
    return run_dir, source_run_id


def _add_source_run(session: Session, source_run_id: str) -> None:
    session.add(Run(id=source_run_id, timezone="Asia/Seoul",
                    generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc)))
    session.commit()


def _count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


@requires_postgres
@pytest.mark.parametrize(
    ("policy_status", "gate_status"),
    [("active", "not_measured"), ("retired", "not_measured"), ("draft", "passed")],
)
def test_reference_import_rejects_active_file_status_and_passed_gate(tmp_path, policy_status, gate_status):
    with migrated_engine() as engine, Session(engine) as session:
        run_dir, source_run_id = _write_policy_fixture(
            tmp_path, policy_status=policy_status, gate_status=gate_status, approved=True,
        )
        _add_source_run(session, source_run_id)
        with pytest.raises(OrderPlanScreeningContractError, match="activation API"):
            ingest_run(run_dir, session)
        session.rollback()
        assert _count(session, OrderPlanScreeningPolicy) == 0
        assert _count(session, OrderPlanScreeningExecution) == 0


@requires_postgres
def test_reference_import_creates_an_inactive_row_from_a_candidate_file(tmp_path):
    with migrated_engine() as engine, Session(engine) as session:
        run_dir, source_run_id = _write_policy_fixture(
            tmp_path, policy_status="activation_candidate", gate_status="measured_elsewhere", approved=True,
        )
        _add_source_run(session, source_run_id)
        assert ingest_run(run_dir, session).screening_executions == 1
        policy = session.scalar(select(OrderPlanScreeningPolicy))
        assert policy.policy_status == "activation_candidate"
        assert policy.quality_gate_status == "not_measured"
        assert policy.active_slot is None
        assert policy.activated_by is None and policy.activated_at is None
        assert policy.activation_metadata_jsonb == {}
        # 파일 스냅샷은 payload에 그대로 남는다.
        assert policy.policy_payload_jsonb["activation"]["approved_by"] == "파일 승인자"


@requires_postgres
def test_existing_active_row_with_same_digests_is_reused_unchanged(tmp_path):
    with migrated_engine() as engine, Session(engine) as session:
        run_dir, source_run_id = _write_policy_fixture(tmp_path / "a", policy_status="activation_candidate")
        _add_source_run(session, source_run_id)
        ingest_run(run_dir, session)
        session.commit()
        # 활성화 API가 행을 활성으로 옮긴 뒤를 흉내 낸다(DB guard가 허용하는 한 번의 전이).
        policy = session.scalar(select(OrderPlanScreeningPolicy))
        activated_at = datetime(2026, 9, 10, tzinfo=timezone.utc)
        policy.policy_status = "active"
        policy.quality_gate_status = "passed"
        policy.active_slot = 1
        policy.activated_by = "활성화 담당"
        policy.activated_at = activated_at
        session.commit()

        assert ingest_run(run_dir, session).screening_executions == 0
        session.commit()
        session.expire_all()
        policy = session.scalar(select(OrderPlanScreeningPolicy))
        assert (policy.policy_status, policy.quality_gate_status, policy.active_slot) == ("active", "passed", 1)
        assert policy.activated_by == "활성화 담당" and policy.activated_at == activated_at

        # 같은 version의 다른 policy bytes는 기존대로 불변 충돌이다.
        other_dir, _ = _write_policy_fixture(tmp_path / "b", policy_status="activation_candidate", variant="changed")
        with pytest.raises(OrderPlanScreeningConflictError, match="immutable conflict: policy"):
            ingest_run(other_dir, session)
