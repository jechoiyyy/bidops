from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import AuditEvent, QualityGate, QualityGateEvaluation, ScreeningExecution, ScreeningPolicy
from app.screening.generation_config import GenerationConfig
from app.screening.policy import (
    PolicyActivationError,
    PolicyConflict,
    PolicyError,
    PolicyRepository,
    _seed_policy_from_path,
    canonical_policy_bytes,
    load_policy_file,
    policy_content_digest,
    seed_policy,
)


def session_for(*tables):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[table.__table__ for table in tables])
    return Session(engine)


def test_seed_is_exact_and_idempotent():
    session = session_for(ScreeningPolicy, AuditEvent)
    first = seed_policy(session, actor="operator")
    second = seed_policy(session, actor="operator")
    body = load_policy_file()
    assert first is second
    assert first.status == "activation_candidate"
    assert first.content_digest == policy_content_digest(body)
    assert canonical_policy_bytes(body).decode().count("notice_json={notice_json}") == 7
    assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "screening_policy.created"))


def test_same_version_different_content_conflicts_and_only_draft_can_candidate():
    session = session_for(ScreeningPolicy, AuditEvent)
    body = load_policy_file()
    repo = PolicyRepository(session)
    row = repo.create(body, created_by="operator")
    assert row.status == "draft"
    changed = dict(body)
    changed["thresholds"] = {**body["thresholds"], "min_valid_reviews": 11}
    with pytest.raises(PolicyConflict):
        repo.create(changed, created_by="operator")
    repo.designate_candidate(row.policy_version, actor="operator")
    with pytest.raises(PolicyConflict):
        repo.designate_candidate(row.policy_version, actor="operator")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda body: body["perspective_prompts"]["기술 적합성"].pop("output_schema"),
        lambda body: body["perspective_prompts"].update({"extra": body["perspective_prompts"]["기술 적합성"]}),
        lambda body: body["counterargument_prompt"].update({"input_fields": ["notice"]}),
        lambda body: body["synthesis_prompt"].update({"output_schema": "wrong"}),
        lambda body: body["candidate_selection"].update({"carry_over_if_unchanged": 1}),
        lambda body: body["thresholds"].update({"priority_review_rate_min_pct": 26}),
        lambda body: body["thresholds"].update({"min_valid_reviews": -1}),
    ],
)
def test_canonical_policy_rejects_invalid_nested_schema(mutator):
    body = deepcopy(load_policy_file())
    mutator(body)
    with pytest.raises(PolicyError):
        canonical_policy_bytes(body)


def test_seed_private_path_helper_fails_closed_on_modified_seed(tmp_path: Path):
    body = load_policy_file()
    body["thresholds"]["min_valid_reviews"] = 11
    modified = tmp_path / "seed_policy.json"
    modified.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    session = session_for(ScreeningPolicy, AuditEvent)
    with pytest.raises(PolicyError):
        _seed_policy_from_path(session, actor="operator", path=modified)


def _gate(session: Session, policy: ScreeningPolicy, *, result: str = "통과", revision: int = 1, suffix: str = "a"):
    now = datetime.now(timezone.utc)
    generation_config = GenerationConfig()
    generation_value = generation_config.canonical_value()
    generation_digest = generation_config.digest()
    gate_id = "gate-" + suffix * 32
    pass_a_id = "scr-" + suffix * 30 + "1" * 2
    pass_b_id = "scr-" + suffix * 30 + "2" * 2
    pass_rows = [
        ScreeningExecution(
            execution_id=execution_id,
            trigger="quality_gate",
            source_run_id="baseline",
            scope="quality_sample",
            status="성공",
            requested_by="operator",
            policy_version=policy.policy_version,
            prompt_version=policy.prompt_version,
            model_name="model",
            model_digest="c" * 64,
            company_profile_version="company-profile.sha256:" + "d" * 64,
            company_profile_digest="d" * 64,
            generation_config_json=generation_value,
            generation_config_digest=generation_digest,
            input_artifact_path=f"data/screening-executions/{execution_id}/screening-input.json",
            input_artifact_digest="e" * 64,
            artifact_dir=f"data/screening-executions/{execution_id}",
            queued_at=now,
            finished_at=now,
            candidate_count=0,
            completed_count=0,
            failure_count=0,
        )
        for execution_id in (pass_a_id, pass_b_id)
    ]
    gate = QualityGate(
        gate_id=gate_id,
        purpose="operational_approval",
        execution_status="완료",
        result_status=result,
        baseline_run_id="baseline",
        sample_artifact_path="sample.json",
        sample_artifact_digest="a" * 64,
        baseline_decisions_path="decisions.json",
        baseline_decisions_digest="b" * 64,
        policy_version=policy.policy_version,
        prompt_version=policy.prompt_version,
        model_name="model",
        model_digest="c" * 64,
        company_profile_version="company-profile.sha256:" + "d" * 64,
        company_profile_digest="d" * 64,
        generation_config_json=generation_value,
        generation_config_digest=generation_digest,
        pass_a_execution_id=pass_a_id,
        pass_b_execution_id=pass_b_id,
        created_at=now,
        completed_at=now,
        metrics_json={},
        reasons_json=[],
        created_by="operator",
    )
    evaluation = QualityGateEvaluation(
        evaluation_id="gateeval-" + suffix * 32,
        gate_id=gate_id,
        revision=revision,
        result_status=result,
        metrics_json={},
        reasons_json=[],
        valid_review_count=10,
        distinct_notice_review_count=10,
        generation_config_digest=generation_digest,
        created_at=now,
    )
    session.add_all([*pass_rows, gate, evaluation])
    return evaluation.evaluation_id


def test_activation_requires_gate_and_audits_old_active_demotion():
    session = session_for(ScreeningPolicy, AuditEvent, QualityGate, QualityGateEvaluation, ScreeningExecution)
    repo = PolicyRepository(session)
    first_body = {**load_policy_file(), "policy_version": "z-policy"}
    first = repo.create(first_body, created_by="operator")
    repo.designate_candidate(first.policy_version, actor="operator")
    gate_eval = _gate(session, first)
    repo.activate(first.policy_version, quality_gate_result_id=gate_eval, actor="operator")

    second_body = {**first_body, "policy_version": "a-policy"}
    second = repo.create(second_body, created_by="operator")
    repo.designate_candidate(second.policy_version, actor="operator")
    with pytest.raises(PolicyActivationError):
        repo.activate(second.policy_version, quality_gate_result_id="gateeval-" + "f" * 32, actor="operator")
    gate_eval2 = _gate(session, second, suffix="b")
    repo.activate(second.policy_version, quality_gate_result_id=gate_eval2, actor="operator")
    session.flush()
    rows = list(session.scalars(select(ScreeningPolicy)))
    assert sum(row.status == "active" for row in rows) == 1
    assert next(row for row in rows if row.status == "active").policy_version == second.policy_version
    assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "screening_policy.deactivated"))
    for event in session.scalars(select(AuditEvent)):
        assert "template" not in str(event.details_json)
