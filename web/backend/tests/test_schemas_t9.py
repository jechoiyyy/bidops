"""Contract tests for the named screening, gate, policy, and schedule models."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import (
    AlwaysOnSwitchUpdateRequest,
    CompanyProfileSnapshotResponse,
    JudgmentExecutionCreateRequest,
    PolicyVersionCreateRequest,
    PolicyVersionResponse,
    QualityGateCreateRequest,
    ScheduleExecutionCreateRequest,
    ScheduleExecutionSummary,
    ScheduleSettingsUpdateRequest,
    ScreeningArtifactUrls,
    ScreeningExecutionDetailResponse,
    ScreeningExecutionResponse,
    ScreeningStopRequest,
)
from app.core.generation_config import GenerationConfig


NOW = datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64
PROFILE_VERSION = f"company-profile.sha256:{DIGEST}"
EXECUTION_ID = "scr-" + "1" * 32


def execution_payload(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "queue_no": 1,
        "execution_id": EXECUTION_ID,
        "trigger": "manual_run",
        "source_run_id": "run-1",
        "scope": "full_run",
        "notice_id": None,
        "status": "대기",
        "requested_by": " 담당자 ",
        "policy_version": "policy-1",
        "prompt_version": "prompt-1",
        "model_name": "qwen3.8:27b",
        "model_digest": DIGEST,
        "company_profile_version": PROFILE_VERSION,
        "company_profile_digest": DIGEST,
        "generation_config": GenerationConfig().canonical_value(),
        "generation_config_digest": GenerationConfig().digest(),
        "input_artifact_digest": DIGEST,
        "queued_at": NOW,
        "started_at": None,
        "finished_at": None,
        "heartbeat_at": None,
        "stop_requested_at": None,
        "stop_requested_by": None,
        "stop_reason": None,
        "candidate_count": 0,
        "completed_count": 0,
        "failure_count": 0,
        "published_run_id": None,
        "error_summary": None,
        "queue_position": 1,
        "current_notice_id": None,
        "current_stage": None,
        "result_urls": ScreeningArtifactUrls().model_dump(),
    }
    value.update(changes)
    return value


def test_screening_response_and_detail_have_exact_public_keys() -> None:
    response = ScreeningExecutionResponse.model_validate(execution_payload())
    assert set(response.model_dump()) == {
        "queue_no",
        "execution_id",
        "trigger",
        "source_run_id",
        "scope",
        "notice_id",
        "status",
        "requested_by",
        "policy_version",
        "prompt_version",
        "model_name",
        "model_digest",
        "company_profile_version",
        "company_profile_digest",
        "generation_config",
        "generation_config_digest",
        "input_artifact_digest",
        "queued_at",
        "started_at",
        "finished_at",
        "heartbeat_at",
        "stop_requested_at",
        "stop_requested_by",
        "stop_reason",
        "candidate_count",
        "completed_count",
        "failure_count",
        "published_run_id",
        "error_summary",
        "queue_position",
        "current_notice_id",
        "current_stage",
        "result_urls",
    }
    detail = ScreeningExecutionDetailResponse.model_validate(
        {**execution_payload(), "attempts": [], "failures": []}
    )
    assert set(detail.model_dump()) == set(response.model_dump()) | {"attempts", "failures"}
    with pytest.raises(ValidationError):
        ScreeningExecutionResponse.model_validate(execution_payload(queued_at=NOW.replace(tzinfo=None)))


def test_new_contract_models_forbid_extra_and_trim_actors() -> None:
    with pytest.raises(ValidationError):
        JudgmentExecutionCreateRequest(
            policy_version="p",
            profile_source="current",
            requested_by="actor",
            secret="must-not-be-accepted",
        )
    request = ScreeningStopRequest(requested_by="  담당자  ")
    assert request.requested_by == "담당자"


@pytest.mark.parametrize(
    "value",
    ["git:short", "git:" + "A" * 40, "git:" + "a" * 39, "working_tree", " current "],
)
def test_profile_source_requires_current_or_lowercase_git_commit(value: str) -> None:
    with pytest.raises(ValidationError):
        JudgmentExecutionCreateRequest(
            policy_version="p", profile_source=value, requested_by="actor"
        )


def test_profile_snapshot_omits_artifact_path_and_validates_source() -> None:
    snapshot = CompanyProfileSnapshotResponse(
        version=PROFILE_VERSION,
        digest=DIGEST,
        source_kind="git_blob",
        source_ref="b" * 40,
        created_at=NOW,
    )
    assert set(snapshot.model_dump()) == {
        "version",
        "digest",
        "source_kind",
        "source_ref",
        "created_at",
    }
    assert "artifact_path" not in snapshot.model_dump()
    with pytest.raises(ValidationError):
        CompanyProfileSnapshotResponse(
            version=PROFILE_VERSION,
            digest="b" * 64,
            source_kind="git_blob",
            source_ref="b" * 40,
            created_at=NOW,
        )


def test_quality_gate_purpose_and_policy_activation_constraints() -> None:
    with pytest.raises(ValidationError):
        QualityGateCreateRequest(
            purpose="model_comparison",
            policy_version="p",
            profile_source="current",
            created_by="actor",
        )
    policy_data = {
        "schema_version": "bidops.screening-policy.v1",
        "policy_version": "p",
        "prompt_version": "prompt",
        "perspective_prompts": {},
        "counterargument_prompt": {},
        "synthesis_prompt": {},
        "candidate_selection": {},
        "thresholds": {},
        "content_digest": DIGEST,
        "status": "draft",
        "created_at": NOW,
        "created_by": "actor",
        "activated_at": None,
        "activated_by": None,
        "quality_gate_result_id": None,
    }
    policy = PolicyVersionResponse(**policy_data)
    assert set(policy.model_dump()) == set(policy_data)
    with pytest.raises(ValidationError):
        PolicyVersionResponse(**{**policy_data, "status": "active"})


def test_schedule_date_time_and_always_on_rules() -> None:
    with pytest.raises(ValidationError):
        ScheduleSettingsUpdateRequest(updated_by="actor")
    with pytest.raises(ValidationError):
        ScheduleSettingsUpdateRequest(daily_time="24:00", updated_by="actor")
    with pytest.raises(ValidationError):
        ScheduleExecutionCreateRequest(
            job_kind="daily",
            window_from=date(2026, 8, 25),
            window_to=date(2026, 8, 26),
            requested_by="actor",
        )
    weekly = ScheduleExecutionCreateRequest(
        job_kind="weekly",
        window_from=date(2026, 8, 24),
        window_to=date(2026, 8, 30),
        requested_by="actor",
    )
    assert weekly.window_from.weekday() == 0
    with pytest.raises(ValidationError):
        AlwaysOnSwitchUpdateRequest(enabled=True, confirmed_by="actor")


def test_schedule_summary_exact_keys_and_skip_reason_contract() -> None:
    summary = ScheduleExecutionSummary(
        run_key="20260826-20260826",
        window_from=date(2026, 8, 26),
        window_to=date(2026, 8, 26),
        job_kind="daily",
        status="건너뜀",
        execution_id="sched-" + "2" * 32,
        trigger="manual",
        skip_reason="duplicate",
        requested_by="actor",
    )
    assert "response_artifact_path" not in summary.model_dump()
    with pytest.raises(ValidationError):
        ScheduleExecutionSummary(
            **{**summary.model_dump(), "skip_reason": None}
        )
