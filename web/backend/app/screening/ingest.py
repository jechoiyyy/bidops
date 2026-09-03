"""판정·리뷰 적재와 C-2 선별 결과 적재 (명세 §6.2).

lifecycle `ingest_run`은 공고·발주계획·첨부 메타까지만 적재하고, 판정 계약을
알지 못한다. 이 모듈이 그 뒤를 잇는 **회차 적재 hook**이며 두 가지를 한다.

- `inspect_run_directory`: 공고를 읽기 전에 디렉터리를 보고 "이것은 C-2 전용
  결과이며 source run은 X"라고 주장한다. 감지·`source_run_id` 검증·계약 상수가
  전부 여기 있으므로, screening이 없으면 C-2 전용 디렉터리는 인식되지 않고 일반
  회차 디렉터리로 처리된다.
- `run_ingested`: 같은 transaction 안에서 `screening-results.json`·
  `screening-decisions.json`·`review-feedback.yaml`을 읽어 판정·리뷰·revision을
  기록하고 v3 lineage를 검증한다.

lifecycle 테이블(회차 경고, 발주계획, 공고 관측)에 쓰는 자리는 §4에 따라
`app.lifecycle`이 공개한 함수로만 간다. 읽기와 join은 lifecycle 모델로 직접
한다. 반대로 계약 해석 helper는 lifecycle의 `ingest` 패키지에서 그대로
가져온다 — screening → lifecycle 방향은 §4가 허용하며, 같은 산출물을 두 모듈이
서로 다르게 읽는 것이 훨씬 위험하다.
"""

from __future__ import annotations

import hashlib
import json
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.generation_config import (
    GenerationConfigError,
    config_from_value,
    validate_digest,
)
from ..lifecycle import (
    RunDirectoryClaim,
    RunIngestCounts,
    load_order_plan_artifact,
    mirror_notice_observation,
    record_ingest_warning,
)
from ..lifecycle.models import Notice, NoticeObservation, OrderPlan, Run
from .models import (
    Counterargument,
    Evidence,
    Judgment,
    JudgmentRevision,
    MatchedPerformance,
    OrderPlanScreeningArtifact,
    OrderPlanScreeningBatchAttempt,
    OrderPlanScreeningExecution,
    OrderPlanScreeningFeedback,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningResult,
    Perspective,
    Review,
    ScreeningExecution,
    VerificationItem,
)
from ..ingest.contracts import (
    DecisionArtifact,
    JudgmentContract,
    NoticeContract,
    OrderPlanArtifact,
    OrderPlanContract,
    ScreeningArtifact,
    ScreeningResultContract,
    artifact_version,
    is_blank,
    missing_judgment_fields,
    model_extra_fields,
)
# 회차 산출물을 읽는 공통 helper. lifecycle 적재기와 같은 바이트를 같은 규칙으로
# 읽어야 하므로 복제하지 않고 그대로 가져온다(§4의 허용 방향).
from ..ingest.loader import (
    EXECUTION_ID_RE,
    ORDER_PLAN_FILE,
    SHA256_RE,
    V3_GENERATION_SCHEMAS,
    _ORDER_PLAN_FIELD_ALIASES,
    _SCREENING_COMMON_NOTICE_KEYS,
    _SCREENING_INPUT_KEYS,
    _artifact_unknown_fields,
    _is_aware_iso,
    _normalize_v3_generation_binding,
    _order_plan_items,
    _plan_text,
    _raw_list,
    _read_optional_json,
    _read_screening_input,
    _screening_input_error,
)
from .c2_contracts import (
    OrderPlanScreeningDecisionsArtifact,
    OrderPlanScreeningFailuresArtifact,
    OrderPlanScreeningFeedbackArtifact,
    OrderPlanScreeningInputArtifact,
    OrderPlanScreeningPolicyArtifact,
    OrderPlanScreeningRankingArtifact,
    OrderPlanScreeningResultArtifact,
    OrderPlanScreeningTelemetryArtifact,
)
from .contracts import (
    ContractViolation as ScreeningContractViolation,
    add_two_axis_metadata,
    validate_judgment as validate_current_judgment,
)
from .ingest_feedback import load_feedback
from .judgment_revisions import judgment_revision_payload
from ..services.revisions import (
    RevisionValidationError,
    append_judgment_revision,
    current_judgment_revision,
    require_carry_origin_run,
)

FEEDBACK_FILE = "review-feedback.yaml"


def _record_warning(
    session: Session,
    run_id: str,
    level: str,
    code: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    """회차 경고는 lifecycle 테이블이므로 lifecycle 공개 함수로만 쓴다(§4)."""

    record_ingest_warning(
        session, run_id=run_id, level=level, code=code, message=message, context=context
    )


def _record_unknown_fields(
    session: Session,
    run_id: str,
    fields: list[str],
    source: str,
) -> None:
    for field_name in fields:
        _record_warning(
            session,
            run_id,
            "info",
            "unknown_field",
            f"알 수 없는 필드를 무시했습니다: {field_name}",
            {"file": source, "field": field_name},
        )


C2_INPUT_SCHEMA = "bidops.order-plan-screening-input.v1"


C2_RESULT_SCHEMA = "bidops.order-plan-screening-result.v1"


C2_POLICY_SCHEMA = "bidops.order-plan-screening-policy.v1"


C2_BINDING_SCHEMA = "bidops.order-plan-screening-phase0-binding.v1"


C2_IMPORT_ACTOR = "system:order-plan-screening-artifact-import"


C2_BATCH_SIZE = 25


C2_ARTIFACTS = (
    ("input", "screening-input.json", OrderPlanScreeningInputArtifact),
    ("ranking", "screening-ranking.json", OrderPlanScreeningRankingArtifact),
    ("decisions", "screening-decisions.json", OrderPlanScreeningDecisionsArtifact),
    ("failures", "screening-failures.json", OrderPlanScreeningFailuresArtifact),
    ("telemetry", "screening-telemetry.json", OrderPlanScreeningTelemetryArtifact),
    ("result", "screening-results.json", OrderPlanScreeningResultArtifact),
)


class OrderPlanScreeningContractError(ValueError):
    """A C-2 artifact is absent, malformed, or has broken lineage."""


class OrderPlanScreeningConflictError(ValueError):
    """The same C-2 identity was presented with different immutable bytes."""


@dataclass(frozen=True)
class VerifiedV3Lineage:
    """Database and sibling-artifact binding for one current v3 publication."""

    execution_id: str
    source_run_id: str
    input_notices: dict[str, dict[str, Any]]


def _as_judgment(value: Any) -> JudgmentContract:
    return value if isinstance(value, JudgmentContract) else JudgmentContract.model_validate(value)


def _generation_binding_matches(
    value: dict[str, Any],
    expected_config: dict[str, Any] | None,
    expected_digest: str | None,
    artifact_name: str,
) -> str | None:
    if expected_config is None or expected_digest is None:
        return None
    if (
        value.get("generation_config") != expected_config
        or value.get("generation_config_digest") != expected_digest
    ):
        return f"{artifact_name} generation binding does not match its source"
    return None


def _clear_judgment(session: Session, judgment: Judgment) -> None:
    """Replace child rows on re-ingest without changing the judgment identity."""

    for perspective in list(judgment.perspectives):
        for evidence in list(perspective.evidence):
            session.delete(evidence)
        session.delete(perspective)
    for child in list(judgment.counterarguments):
        session.delete(child)
    for child in list(judgment.verification_items):
        session.delete(child)
    for child in list(judgment.matched_performances):
        session.delete(child)
    session.flush()


def _load_judgment(
    session: Session,
    run_id: str,
    notice: Notice,
    judgment: JudgmentContract,
    raw: dict[str, Any],
    schema_version: str,
    source_file: str,
    *,
    verified_lineage: VerifiedV3Lineage | None = None,
) -> Judgment | None:
    judgment_notice_id = raw.get("notice_id") or notice.notice_key
    missing = missing_judgment_fields(judgment, judgment_notice_id)
    if missing:
        _record_warning(
            session,
            run_id,
            "error",
            "judgment_required_field_missing",
            "필수 판정 필드가 없어 해당 판정을 적재하지 않았습니다.",
            {"notice_id": notice.notice_key, "fields": missing, "file": source_file},
        )
        return None

    extra_fields = model_extra_fields(judgment, "judgment")
    _record_unknown_fields(session, run_id, extra_fields, source_file)

    perspectives = _raw_list(raw.get("perspectives"))
    counterarguments = _raw_list(raw.get("counterarguments"))
    verification_items = _raw_list(raw.get("verification_items"))
    if len(perspectives) < 5:
        _record_warning(
            session,
            run_id,
            "warning",
            "perspectives_below_contract",
            f"관점이 계약 기준보다 적습니다: {len(perspectives)}개",
            {
                "notice_id": notice.notice_key,
                "actual_count": len(perspectives),
                "schema_version": schema_version,
            },
        )
    if not counterarguments:
        _record_warning(
            session,
            run_id,
            "warning",
            "counterarguments_missing",
            "반론이 없어 빈 목록으로 적재했습니다.",
            {"notice_id": notice.notice_key, "schema_version": schema_version},
        )
    if not verification_items:
        _record_warning(
            session,
            run_id,
            "warning",
            "verification_items_missing",
            "확인 항목이 없어 빈 목록으로 적재했습니다.",
            {"notice_id": notice.notice_key, "schema_version": schema_version},
        )

    payload = judgment_revision_payload(raw, schema_version=schema_version)
    if verified_lineage is None:
        existing_revision = session.scalar(
            select(JudgmentRevision).where(
                JudgmentRevision.notice_id == notice.id,
                JudgmentRevision.source_kind == "legacy_import",
                JudgmentRevision.run_id == run_id,
            )
        )
        revision = append_judgment_revision(
            session,
            notice_id=notice.id,
            source_kind="legacy_import",
            run_id=run_id,
            payload=payload,
        )
    else:
        existing_revision = session.scalar(
            select(JudgmentRevision).where(
                JudgmentRevision.notice_id == notice.id,
                JudgmentRevision.recording_execution_id
                == verified_lineage.execution_id,
            )
        )
        source_notice = verified_lineage.input_notices.get(notice.notice_key)
        if source_notice is None:
            raise ValueError("verified v3 judgment is outside its frozen input")
        mode = source_notice.get("judgment_mode")
        if mode == "승계":
            if existing_revision is not None:
                source_revision_id = existing_revision.source_revision_id
            else:
                parent = current_judgment_revision(session, notice.id)
                source_revision_id = parent.id if parent is not None else None
            if source_revision_id is None:
                raise RevisionValidationError(
                    "carry-over judgment has no prior same-notice revision"
                )
            require_carry_origin_run(
                session,
                source_revision_id,
                expected_source_run_id=source_notice.get("carry_over_from"),
            )
            revision = append_judgment_revision(
                session,
                notice_id=notice.id,
                source_kind="carry_over",
                run_id=verified_lineage.source_run_id,
                recording_execution_id=verified_lineage.execution_id,
                source_revision_id=source_revision_id,
                payload=payload,
            )
        elif mode in {"신규", "재판정"}:
            revision = append_judgment_revision(
                session,
                notice_id=notice.id,
                source_kind="runtime",
                run_id=verified_lineage.source_run_id,
                recording_execution_id=verified_lineage.execution_id,
                payload=payload,
            )
        else:  # pragma: no cover - verified lineage rejects this first.
            raise ValueError("verified v3 judgment mode is invalid")

    # Immutable-scope replay validates through the core append operation but
    # must not revert or churn the mutable current projection.  This matters
    # when an older execution is replayed after a later rejudgment.
    # 공고는 판정으로 향하는 relationship 을 갖지 않는다(§4). 판정 테이블의 소유
    # 모듈이므로 현재 projection 행을 여기서 직접 읽는다.
    current = session.scalar(select(Judgment).where(Judgment.notice_id == notice.id))
    if (
        existing_revision is not None
        and revision.id == existing_revision.id
        and current is not None
    ):
        return current

    if current is None:
        current = Judgment(notice=notice)
        session.add(current)
    else:
        _clear_judgment(session, current)
    current.schema_version = schema_version
    current.grade = judgment.grade
    current.readiness = judgment.readiness
    current.primary_focus = judgment.primary_focus
    current.exclusion_category = judgment.exclusion_category
    current.summary = judgment.summary
    current.next_action = judgment.next_action

    for position, raw_perspective in enumerate(perspectives, start=1):
        if not isinstance(raw_perspective, dict):
            _record_warning(
                session,
                run_id,
                "warning",
                "perspective_invalid",
                "관점 항목이 객체가 아니어서 건너뛰었습니다.",
                {"notice_id": notice.notice_key, "position": position},
            )
            continue
        perspective_model = raw_perspective
        perspective = Perspective(
            judgment=current,
            position=raw_perspective.get("position", position),
            name=raw_perspective.get("name"),
            assessment=raw_perspective.get("assessment"),
            reason=raw_perspective.get("reason"),
        )
        session.add(perspective)
        _record_unknown_fields(
            session,
            run_id,
            model_extra_fields(
                # Re-validation makes nested unknown fields visible even when
                # the parent union selected a raw mapping.
                _model_or_none(perspective_model, "perspective"),
                "perspective",
            ),
            source_file,
        )
        for raw_evidence in _raw_list(raw_perspective.get("evidence")):
            if not isinstance(raw_evidence, dict):
                continue
            evidence = Evidence(
                perspective=perspective,
                source=raw_evidence.get("source"),
                status=raw_evidence.get("status"),
                fact=raw_evidence.get("fact"),
            )
            session.add(evidence)
            _record_unknown_fields(
                session,
                run_id,
                _model_extra_from_raw(raw_evidence, {"source", "status", "fact"}, "perspective.evidence"),
                source_file,
            )

    for position, raw_counterargument in enumerate(counterarguments, start=1):
        if isinstance(raw_counterargument, str):
            text = raw_counterargument
            counter_position = position
        elif isinstance(raw_counterargument, dict):
            text = raw_counterargument.get("text")
            counter_position = raw_counterargument.get("position", position)
            _record_unknown_fields(
                session,
                run_id,
                _model_extra_from_raw(raw_counterargument, {"position", "text"}, "judgment.counterarguments"),
                source_file,
            )
        else:
            text = None
            counter_position = position
        session.add(
            Counterargument(judgment=current, position=counter_position, text=text)
        )

    for raw_item in verification_items:
        if not isinstance(raw_item, dict):
            continue
        session.add(
            VerificationItem(
                judgment=current,
                item=raw_item.get("item"),
                why=raw_item.get("why"),
                blocking=bool(raw_item.get("blocking", False)),
                status=raw_item.get("status"),
            )
        )
        _record_unknown_fields(
            session,
            run_id,
            _model_extra_from_raw(
                raw_item, {"item", "why", "blocking", "status"}, "judgment.verification_items"
            ),
            source_file,
        )

    for raw_performance in _raw_list(raw.get("matched_performances")):
        if not isinstance(raw_performance, dict):
            continue
        session.add(
            MatchedPerformance(
                judgment=current,
                name=raw_performance.get("name") or raw_performance.get("project_name"),
                match_reason=raw_performance.get("match_reason"),
                mismatch_or_limit=raw_performance.get("mismatch_or_limit"),
                source=raw_performance.get("source") or raw_performance.get("source_page"),
                status=raw_performance.get("status") or raw_performance.get("legal_qualification_status"),
            )
        )
        _record_unknown_fields(
            session,
            run_id,
            _model_extra_from_raw(
                raw_performance,
                {
                    "name",
                    "project_name",
                    "match_reason",
                    "mismatch_or_limit",
                    "source",
                    "source_page",
                    "similarity",
                    "common_fragment",
                    "status",
                    "legal_qualification_status",
                },
                "judgment.matched_performances",
            ),
            source_file,
        )
    return current


def _model_or_none(raw: Any, kind: str) -> BaseModel:
    from ..ingest.contracts import PerspectiveContract

    if kind == "perspective":
        return PerspectiveContract.model_validate(raw)
    return PerspectiveContract.model_validate(raw)


def _model_extra_from_raw(raw: dict[str, Any], known: set[str], prefix: str) -> list[str]:
    return [f"{prefix}.{key}" for key in raw if key not in known]


_DECISIONS_V3_KEYS = {
    "schema_version", "execution_id", "run_id", "generated_at", "screening_basis",
    "model_name", "model_digest", "prompt_version", "policy_version",
    "company_profile_version", "company_profile_digest", "judgments",
    "generation_config", "generation_config_digest",
}


_SCREENING_V3_KEYS = {
    "schema_version", "execution_id", "generated_at", "screening_basis",
    "source_window", "model_name", "model_digest", "prompt_version",
    "policy_version", "company_profile_version", "company_profile_digest",
    "generation_config", "generation_config_digest", "candidate_count",
    "result_count", "failure_count", "partial_artifact", "failure_artifact",
    "results",
}


_V3_JUDGMENT_KEYS = {
    "notice_id", "judgment_mode", "model_name", "model_digest",
    "prompt_version", "policy_version", "company_profile_version",
    "company_profile_digest", "judged_in_run", "recorded_in_run",
    "carried_over", "rejudge_reason", "grade", "readiness",
    "primary_focus", "exclusion_category", "summary", "next_action",
    "perspectives", "matched_performances", "counterarguments",
    "counterargument_resolutions", "verification_items",
    "two_axis_mixing_flag", "two_axis_mixing_label",
}


def _v3_generation_artifact_error(
    raw: Any, artifact_name: str, expected_keys: set[str]
) -> str | None:
    """Validate top-level v3 identity and the generation binding.

    Nested judgment validation remains deliberately owned by the producer
    merge contract; ingest still refuses an artifact whose frozen generation
    metadata is malformed or cannot be bound to its sibling artifact.
    """

    if not isinstance(raw, dict):
        return f"{artifact_name} top-level value is not an object"
    missing_keys = expected_keys - set(raw)
    if missing_keys:
        return f"{artifact_name} top-level fields are missing"
    if raw.get("schema_version") not in V3_GENERATION_SCHEMAS:
        return f"{artifact_name} schema version is invalid"
    if not isinstance(raw.get("execution_id"), str) or EXECUTION_ID_RE.fullmatch(raw["execution_id"]) is None:
        return f"{artifact_name} execution id is invalid"
    for key in ("run_id", "prompt_version", "policy_version", "company_profile_version"):
        if key in raw and (not isinstance(raw.get(key), str) or not raw[key].strip()):
            return f"{artifact_name} identity field is invalid"
    run_id = raw.get("run_id")
    if isinstance(run_id, str) and ("/" in run_id or "\\" in run_id or Path(run_id).name != run_id):
        return f"{artifact_name} run identity is unsafe"
    generated = raw.get("generated_at")
    if not _is_aware_iso(generated):
        return f"{artifact_name} generated_at is invalid"
    profile_digest = raw.get("company_profile_digest")
    if not isinstance(profile_digest, str) or SHA256_RE.fullmatch(profile_digest) is None:
        return f"{artifact_name} profile digest is invalid"
    if raw.get("company_profile_version") != f"company-profile.sha256:{profile_digest}":
        return f"{artifact_name} profile identity is invalid"
    if not isinstance(raw.get("model_name"), str) or not raw["model_name"].strip():
        return f"{artifact_name} model name is invalid"
    if not isinstance(raw.get("model_digest"), str) or SHA256_RE.fullmatch(raw["model_digest"]) is None:
        return f"{artifact_name} model digest is invalid"
    try:
        config = config_from_value(raw.get("generation_config"))
        validate_digest(config, raw.get("generation_config_digest"))
    except (GenerationConfigError, AttributeError, TypeError):
        return f"{artifact_name} generation binding is invalid"
    if raw.get("generation_config") != config.canonical_value():
        return f"{artifact_name} generation config is not canonical"
    return None


def _verified_v3_lineage(
    session: Session,
    *,
    screening_input: dict[str, Any] | None,
    decisions: dict[str, Any] | None,
    results: dict[str, Any] | None,
    input_digest: str | None,
) -> tuple[VerifiedV3Lineage | None, str | None]:
    """Bind current v3 siblings to their exact persisted execution.

    Filenames and publication directories are not lineage.  Runtime
    revisions are enabled only when the three artifacts agree with each other
    and with the immutable ``ScreeningExecution`` row and input digest.
    """

    if not all(isinstance(value, dict) for value in (screening_input, decisions, results)):
        return None, "current v3 runtime lineage requires input, decisions, and results siblings"
    assert screening_input is not None and decisions is not None and results is not None
    if screening_input.get("schema_version") != "bidops.screening-input.v1":
        return None, "screening input schema is not current v3 input"
    if decisions.get("schema_version") != "bidops.decisions.v3":
        return None, "screening decisions schema is not v3"
    if results.get("schema_version") != "bidops.screening.v3":
        return None, "screening results schema is not v3"
    if set(screening_input) != _SCREENING_INPUT_KEYS:
        return None, "screening input fields are not exact"
    if set(decisions) != _DECISIONS_V3_KEYS:
        return None, "screening decisions fields are not exact"
    if set(results) != _SCREENING_V3_KEYS:
        return None, "screening results fields are not exact"

    input_error = _screening_input_error(screening_input)
    if input_error is not None:
        return None, f"screening input is invalid: {input_error}"
    for value, name, keys in (
        (decisions, "screening-decisions.json", _DECISIONS_V3_KEYS),
        (results, "screening-results.json", _SCREENING_V3_KEYS),
    ):
        error = _v3_generation_artifact_error(value, name, keys)
        if error is not None:
            return None, error

    execution_id = screening_input["execution_id"]
    if decisions.get("execution_id") != execution_id or results.get("execution_id") != execution_id:
        return None, "v3 sibling execution ids do not match"
    source_run_id = screening_input["run_id"]
    if decisions.get("run_id") != source_run_id:
        return None, "v3 sibling source run ids do not match"
    for key in (
        "generated_at",
        "prompt_version",
        "policy_version",
        "company_profile_version",
        "company_profile_digest",
        "generation_config",
        "generation_config_digest",
    ):
        if decisions.get(key) != screening_input.get(key) or results.get(key) != screening_input.get(key):
            return None, f"v3 sibling {key} binding does not match"
    for key in ("screening_basis", "model_name", "model_digest"):
        if results.get(key) != decisions.get(key):
            return None, f"v3 sibling {key} binding does not match"
    if results.get("source_window") != screening_input.get("source_window"):
        return None, "v3 sibling source window does not match"

    execution = session.scalar(
        select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id)
    )
    if execution is None:
        return None, "screening execution does not exist"
    expected_execution = {
        "source_run_id": source_run_id,
        "policy_version": screening_input["policy_version"],
        "prompt_version": screening_input["prompt_version"],
        "model_name": decisions["model_name"],
        "model_digest": decisions["model_digest"],
        "company_profile_version": screening_input["company_profile_version"],
        "company_profile_digest": screening_input["company_profile_digest"],
        "generation_config_json": screening_input["generation_config"],
        "generation_config_digest": screening_input["generation_config_digest"],
        "candidate_count": screening_input["candidate_count"],
        "input_artifact_digest": input_digest,
    }
    if any(getattr(execution, key) != value for key, value in expected_execution.items()):
        return None, "v3 artifacts do not match the persisted screening execution"

    input_notices = screening_input.get("notices")
    raw_decisions = decisions.get("judgments")
    raw_results = results.get("results")
    if not isinstance(input_notices, list) or not isinstance(raw_decisions, list) or not isinstance(raw_results, list):
        return None, "v3 judgment arrays are invalid"
    if (
        type(results.get("candidate_count")) is not int
        or type(results.get("result_count")) is not int
        or type(results.get("failure_count")) is not int
        or results["candidate_count"] != len(input_notices)
        or results["result_count"] != len(raw_results)
        or results["candidate_count"] != results["result_count"] + results["failure_count"]
    ):
        return None, "v3 result counts are invalid"
    if results.get("partial_artifact") is not (results["failure_count"] > 0):
        return None, "v3 partial artifact flag is invalid"
    expected_failure_artifact = "screening-failures.json" if results["failure_count"] else None
    if results.get("failure_artifact") != expected_failure_artifact:
        return None, "v3 failure artifact binding is invalid"

    input_by_id = {
        item.get("notice_id"): item
        for item in input_notices
        if isinstance(item, dict) and isinstance(item.get("notice_id"), str)
    }
    if len(input_by_id) != len(input_notices):
        return None, "v3 input notice identities are invalid"
    reconstructed: list[dict[str, Any]] = []
    for result in raw_results:
        if not isinstance(result, dict) or set(result) != {"notice", "judgment"}:
            return None, "v3 result item fields are not exact"
        notice = result.get("notice")
        judgment = result.get("judgment")
        if not isinstance(notice, dict) or set(notice) != set(_SCREENING_COMMON_NOTICE_KEYS):
            return None, "v3 result notice fields are not exact"
        notice_id = notice.get("notice_id")
        source_notice = input_by_id.get(notice_id)
        if source_notice is None:
            return None, "v3 result notice is outside the frozen input"
        if notice != {key: source_notice[key] for key in _SCREENING_COMMON_NOTICE_KEYS}:
            return None, "v3 result notice does not match the frozen input"
        if not isinstance(judgment, dict):
            return None, "v3 result judgment is invalid"
        complete = {"notice_id": notice_id, **judgment}
        if set(complete) != _V3_JUDGMENT_KEYS:
            return None, "v3 judgment fields are not exact"
        base = {
            key: complete[key]
            for key in (
                "notice_id",
                "grade",
                "readiness",
                "primary_focus",
                "exclusion_category",
                "summary",
                "perspectives",
                "matched_performances",
                "counterarguments",
                "counterargument_resolutions",
                "verification_items",
                "next_action",
            )
        }
        try:
            validate_current_judgment(base, notice=source_notice)
        except ScreeningContractViolation:
            return None, "v3 judgment contract is invalid"
        axes = add_two_axis_metadata(base)
        if (
            complete.get("two_axis_mixing_flag")
            != axes["two_axis_mixing_flag"]
            or complete.get("two_axis_mixing_label")
            != axes["two_axis_mixing_label"]
        ):
            return None, "v3 judgment two-axis metadata is invalid"
        mode = source_notice.get("judgment_mode")
        if (
            complete.get("judgment_mode") != mode
            or complete.get("recorded_in_run") != source_run_id
            or complete.get("rejudge_reason") != source_notice.get("rejudge_reason")
        ):
            return None, "v3 judgment recording lineage does not match its input"
        if mode in {"신규", "재판정"}:
            if complete.get("judged_in_run") != source_run_id or complete.get("carried_over") is not False:
                return None, "v3 runtime judgment origin is invalid"
            for key in (
                "model_name",
                "model_digest",
                "prompt_version",
                "policy_version",
                "company_profile_version",
                "company_profile_digest",
            ):
                if complete.get(key) != getattr(execution, key):
                    return None, "v3 runtime judgment model binding is invalid"
        elif mode == "승계":
            if complete.get("judged_in_run") != source_notice.get("carry_over_from") or complete.get("carried_over") is not True:
                return None, "v3 carry-over judgment origin is invalid"
        else:
            return None, "v3 judgment mode is invalid"
        reconstructed.append(complete)
    if reconstructed != raw_decisions:
        return None, "v3 result judgments do not match their decisions sibling"
    if execution.scope == "single_notice":
        if len(input_notices) != 1 or execution.notice_id not in input_by_id:
            return None, "single-notice execution binding is invalid"
    return (
        VerifiedV3Lineage(
            execution_id=execution_id,
            source_run_id=source_run_id,
            input_notices=input_by_id,
        ),
        None,
    )


def _remove_judgments_without_screening(session: Session, notices: dict[str, Notice]) -> None:
    # ``Notice`` is cumulative as of ADR-0026.  Before that cutover this
    # helper removed the current run's projection when screening output was
    # absent or invalid; the same operation now destroys a prior run's only
    # canonical Judgment.  A failed or incomplete observation must not erase
    # the database-authoritative result that is already attached to the
    # external notice identity.  The warning at the caller still records that
    # this run produced no new judgment.
    return None


def _load_screening_results(
    session: Session,
    run_id: str,
    notices: dict[str, Notice],
    raw: dict[str, Any],
    source_file: str,
    schema_version: str,
    *,
    expected_generation_config: dict[str, Any] | None = None,
    expected_generation_digest: str | None = None,
    verified_v3_lineage: VerifiedV3Lineage | None = None,
) -> int:
    if raw.get("schema_version") == "bidops.screening.v3":
        generation_error = _v3_generation_artifact_error(
            raw, "screening-results.json", _SCREENING_V3_KEYS
        )
        if generation_error is None:
            generation_error = _generation_binding_matches(
                raw,
                expected_generation_config,
                expected_generation_digest,
                "screening-results.json",
            )
        if generation_error is not None:
            _record_warning(
                session,
                run_id,
                "error",
                "screening_results_invalid",
                "screening-results.json generation 계약을 해석하지 못했습니다.",
                {"file": source_file, "reason": generation_error},
            )
            _remove_judgments_without_screening(session, notices)
            return 0
    try:
        artifact = ScreeningArtifact.model_validate(raw)
    except ValidationError as exc:
        _record_warning(
            session,
            run_id,
            "error",
            "screening_results_invalid",
            "screening-results.json 계약을 해석하지 못했습니다.",
            {"file": source_file, "error": str(exc)},
        )
        _remove_judgments_without_screening(session, notices)
        return 0
    _record_unknown_fields(session, run_id, _artifact_unknown_fields(raw, artifact), source_file)
    raw_results = raw.get("results")
    if not isinstance(raw_results, list):
        _record_warning(
            session,
            run_id,
            "error",
            "screening_results_missing",
            "screening-results.json에 results 목록이 없습니다.",
            {"file": source_file},
        )
        _remove_judgments_without_screening(session, notices)
        return 0
    if (
        raw.get("schema_version") == "bidops.screening.v3"
        and raw_results
        and verified_v3_lineage is None
    ):
        _record_warning(
            session,
            run_id,
            "error",
            "screening_lineage_invalid",
            "screening v3 판정을 저장된 실행과 검증하지 못해 적재하지 않았습니다.",
            {"file": source_file},
        )
        return 0

    loaded = 0
    for index, raw_result in enumerate(raw_results):
        if not isinstance(raw_result, dict):
            _record_warning(
                session,
                run_id,
                "error",
                "screening_result_invalid",
                "판정 결과 항목이 객체가 아니어서 건너뛰었습니다.",
                {"file": source_file, "index": index},
            )
            continue
        try:
            result_model = ScreeningResultContract.model_validate(raw_result)
            _record_unknown_fields(
                session,
                run_id,
                _model_extra_from_raw(raw_result, {"notice", "judgment"}, f"result[{index}]"),
                source_file,
            )
            if isinstance(raw_result.get("notice"), dict):
                screening_notice_model = NoticeContract.model_validate(raw_result["notice"])
                _record_unknown_fields(
                    session,
                    run_id,
                    model_extra_fields(screening_notice_model, f"result[{index}].notice"),
                    source_file,
                )
        except ValidationError as exc:
            _record_warning(
                session,
                run_id,
                "warning",
                "screening_result_invalid",
                "screening 결과의 중첩 필드를 모두 해석하지 못했지만 판정 적재를 계속합니다.",
                {"file": source_file, "index": index, "error": str(exc)},
            )
        raw_notice = raw_result.get("notice")
        raw_judgment = raw_result.get("judgment")
        notice_id = raw_notice.get("notice_id") if isinstance(raw_notice, dict) else None
        if is_blank(notice_id) and isinstance(raw_judgment, dict):
            notice_id = raw_judgment.get("notice_id")
        if is_blank(notice_id):
            _record_warning(
                session,
                run_id,
                "error",
                "judgment_required_field_missing",
                "notice_id가 없어 해당 판정을 적재하지 않았습니다.",
                {"file": source_file, "index": index, "fields": ["notice_id"]},
            )
            continue
        notice = notices.get(str(notice_id))
        if notice is None:
            _record_warning(
                session,
                run_id,
                "error",
                "judgment_notice_not_found",
                "검증 표본에 없는 공고의 판정을 적재하지 않았습니다.",
                {"notice_id": str(notice_id), "file": source_file},
            )
            continue
        if not isinstance(raw_judgment, dict):
            _record_warning(
                session,
                run_id,
                "error",
                "judgment_missing",
                "판정 객체가 없어 해당 판정을 적재하지 않았습니다.",
                {"notice_id": str(notice_id), "file": source_file},
            )
            continue
        try:
            judgment_model = _as_judgment(raw_judgment)
        except ValidationError as exc:
            _record_warning(
                session,
                run_id,
                "error",
                "judgment_invalid",
                "판정 항목 계약을 해석하지 못해 건너뛰었습니다.",
                {"notice_id": str(notice_id), "file": source_file, "error": str(exc)},
            )
            continue
        judgment = _load_judgment(
            session,
            run_id,
            notice,
            judgment_model,
            raw_judgment,
            schema_version,
            source_file,
            verified_lineage=verified_v3_lineage,
        )
        if judgment is not None:
            loaded += 1

    session.flush()
    return loaded


def _feedback_path(run_directory: Path, reports_root: Path | None) -> Path:
    root = reports_root if reports_root is not None else run_directory.parent.parent / "reports"
    return root / run_directory.name / "review-feedback.yaml"


def _load_feedback(
    session: Session,
    run: Run,
    notices: dict[str, Notice],
    run_directory: Path,
    reports_root: Path | None,
) -> int:
    from .feedback import load_feedback

    return load_feedback(session, run, notices, _feedback_path(run_directory, reports_root))


def _c2_canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise OrderPlanScreeningContractError("C-2 JSON is not canonicalizable") from exc


def _c2_digest_json(value: Any) -> str:
    return hashlib.sha256(_c2_canonical_json(value)).hexdigest()


def _c2_no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _c2_read_json(path: Path, model: type[BaseModel], label: str) -> tuple[dict[str, Any], BaseModel, str]:
    if path.is_symlink() or not path.is_file():
        raise OrderPlanScreeningContractError(f"{label} is absent or unsafe")
    try:
        raw_bytes = path.read_bytes()
        raw_value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_c2_no_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
        )
        parsed = model.model_validate(raw_value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise OrderPlanScreeningContractError(f"{label} failed strict validation") from exc
    if not isinstance(raw_value, dict):
        raise OrderPlanScreeningContractError(f"{label} must be a JSON object")
    return raw_value, parsed, hashlib.sha256(raw_bytes).hexdigest()


def _c2_safe_run_file(directory: Path, name: str) -> Path:
    if name.startswith(("/", "\\")) or "/" in name or "\\" in name or name in {".", ".."}:
        raise OrderPlanScreeningContractError("C-2 artifact name is unsafe")
    candidate = directory / name
    try:
        if candidate.is_symlink() or candidate.resolve().parent != directory.resolve():
            raise OrderPlanScreeningContractError("C-2 artifact path is outside its run")
    except OSError as exc:
        raise OrderPlanScreeningContractError("C-2 artifact path cannot be checked") from exc
    return candidate


def _c2_reference_file(
    directory: Path,
    explicit: str | Path | None,
    names: tuple[str, ...],
    repository_name: str,
) -> Path:
    if explicit is not None:
        candidate = Path(explicit).resolve()
        if candidate.is_symlink() or not candidate.is_file():
            raise OrderPlanScreeningContractError("C-2 binding reference is absent or unsafe")
        return candidate
    candidates = [directory / name for name in names]
    candidates.append(Path(__file__).resolve().parents[4] / repository_name)
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    raise OrderPlanScreeningContractError("C-2 binding reference is absent")


def _c2_timestamp(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError as exc:
            raise OrderPlanScreeningContractError(f"{label} timestamp is invalid") from exc
    else:
        raise OrderPlanScreeningContractError(f"{label} timestamp is invalid")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OrderPlanScreeningContractError(f"{label} timestamp has no timezone")
    return parsed


def _c2_sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise OrderPlanScreeningContractError("C-2 binding file is unreadable") from exc


def _c2_same_lineage(*documents: dict[str, Any]) -> tuple[str, str]:
    execution_ids = {document.get("execution_id") for document in documents}
    source_run_ids = {document.get("source_run_id") for document in documents}
    if len(execution_ids) != 1 or len(source_run_ids) != 1:
        raise OrderPlanScreeningContractError("C-2 sibling execution lineage differs")
    execution_id = next(iter(execution_ids))
    source_run_id = next(iter(source_run_ids))
    if not isinstance(execution_id, str) or not isinstance(source_run_id, str):
        raise OrderPlanScreeningContractError("C-2 lineage identifiers are invalid")
    return execution_id, source_run_id


def _c2_source_population(raw: dict[str, Any]) -> list[dict[str, str]]:
    rows, _ = _order_plan_items(raw)
    if rows is None:
        raise OrderPlanScreeningContractError("source order-plan artifact has no population")
    population: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise OrderPlanScreeningContractError("source order-plan population contains a non-object")
        try:
            OrderPlanContract.model_validate(row)
        except ValidationError as exc:
            raise OrderPlanScreeningContractError("source order-plan population is invalid") from exc
        plan_id = _plan_text(row, *_ORDER_PLAN_FIELD_ALIASES["order_plan_unty_no"])
        title = _plan_text(row, "title", "biz_nm", "business_name")
        if plan_id is None or title is None or plan_id in seen:
            raise OrderPlanScreeningContractError("source order-plan population identity is invalid")
        seen.add(plan_id)
        population.append({"plan_id": plan_id, "title": title})
    return population


def _c2_check_siblings(
    input_raw: dict[str, Any],
    ranking_raw: dict[str, Any],
    decisions_raw: dict[str, Any],
    failures_raw: dict[str, Any],
    telemetry_raw: dict[str, Any],
    result_raw: dict[str, Any],
    input_digest: str,
    ranking_digest: str,
) -> None:
    execution_id, source_run_id = _c2_same_lineage(
        input_raw, ranking_raw, decisions_raw, failures_raw, telemetry_raw, result_raw
    )
    try:
        uuid_module.UUID(execution_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise OrderPlanScreeningContractError("execution_id must be a UUID") from exc
    if input_raw["schema_version"] != C2_INPUT_SCHEMA or result_raw["schema_version"] != C2_RESULT_SCHEMA:
        raise OrderPlanScreeningContractError("C-2 input/result schema is unsupported")
    if ranking_raw["input_artifact_sha256"] != input_digest or decisions_raw["input_artifact_sha256"] != input_digest or result_raw["input_artifact_sha256"] != input_digest:
        raise OrderPlanScreeningContractError("C-2 input artifact digest does not match siblings")
    if decisions_raw["ranking_artifact_sha256"] != ranking_digest:
        raise OrderPlanScreeningContractError("C-2 ranking artifact digest does not match")
    if ranking_raw["policy_version"] != input_raw["policy"]["version"] or ranking_raw["policy_sha256"] != input_raw["policy"]["sha256"]:
        raise OrderPlanScreeningContractError("C-2 ranking policy binding differs")
    if result_raw["policy_version"] != input_raw["policy"]["version"] or result_raw["policy_sha256"] != input_raw["policy"]["sha256"]:
        raise OrderPlanScreeningContractError("C-2 result policy binding differs")

    input_ids = [item["plan_id"] for item in input_raw["items"]]
    ranking_ids = [item["plan_id"] for item in ranking_raw["items"]]
    result_ids = [item["plan_id"] for item in result_raw["items"]]
    if ranking_ids != input_ids or result_ids != input_ids:
        raise OrderPlanScreeningContractError("C-2 artifacts do not contain the same full population")
    if ranking_raw["population_count"] != input_raw["population_count"]:
        raise OrderPlanScreeningContractError("C-2 ranking population count differs")
    if decisions_raw["candidate_count"] != ranking_raw["selected_count"]:
        raise OrderPlanScreeningContractError("C-2 candidate count differs from ranking")

    batches = {batch["batch_id"]: batch for batch in decisions_raw["batches"]}
    if len(batches) != len(decisions_raw["batches"]):
        raise OrderPlanScreeningContractError("C-2 decision batch identity is duplicated")
    candidate_ids = [
        item["plan_id"] for item in ranking_raw["items"] if item["stage1_status"] == "selected"
    ]
    candidate_set = set(candidate_ids)
    batch_ids: list[str] = []
    batched_candidates: set[str] = set()
    for batch in decisions_raw["batches"]:
        if batch["batch_id"] in batch_ids or len(batch["plan_ids"]) == 0:
            raise OrderPlanScreeningContractError("C-2 batch identity is invalid")
        batch_ids.append(batch["batch_id"])
        expected_plan_ids = candidate_ids[(len(batch_ids) - 1) * C2_BATCH_SIZE : len(batch_ids) * C2_BATCH_SIZE]
        if batch["plan_ids"] != expected_plan_ids:
            raise OrderPlanScreeningContractError("C-2 batch order or population is invalid")
        if set(batch["plan_ids"]) - candidate_set or set(batch["plan_ids"]) & batched_candidates:
            raise OrderPlanScreeningContractError("C-2 batch plan identities overlap")
        batched_candidates.update(batch["plan_ids"])
        if batch["attempt_count"] > 2:
            raise OrderPlanScreeningContractError("C-2 attempt count exceeds policy")
    if not batched_candidates <= candidate_set:
        raise OrderPlanScreeningContractError("C-2 batches contain a non-selected population")

    decision_items = {item["plan_id"]: item for item in decisions_raw["items"]}
    if len(decision_items) != len(decisions_raw["items"]):
        raise OrderPlanScreeningContractError("C-2 decision item identity is duplicated")
    for plan_id, item in decision_items.items():
        batch = batches.get(item["batch_id"])
        if batch is None or batch["status"] != "success" or item["attempt_no"] != batch["attempt_count"]:
            raise OrderPlanScreeningContractError("C-2 decision item is not the final successful attempt")
    successful_batch_plan_ids = {
        plan_id
        for batch in decisions_raw["batches"]
        if batch["status"] == "success"
        for plan_id in batch["plan_ids"]
    }
    if set(decision_items) != successful_batch_plan_ids:
        raise OrderPlanScreeningContractError("C-2 decision items do not match successful candidates")

    failures_by_batch = {failure["batch_id"]: failure for failure in failures_raw["failures"]}
    if len(failures_by_batch) != len(failures_raw["failures"]):
        raise OrderPlanScreeningContractError("C-2 failure batch identity is duplicated")
    failed_batches = {batch_id for batch_id, batch in batches.items() if batch["status"] != "success"}
    if set(failures_by_batch) != failed_batches:
        raise OrderPlanScreeningContractError("C-2 failure artifact does not cover failed batches")
    for batch_id, failure in failures_by_batch.items():
        batch = batches[batch_id]
        if failure["plan_ids"] != batch["plan_ids"] or failure["sequence"] != batch["sequence"] or failure["attempt_count"] != batch["attempt_count"]:
            raise OrderPlanScreeningContractError("C-2 failure batch binding differs")

    telemetry_batches = {batch["batch_id"]: batch for batch in telemetry_raw["batches"]}
    if len(telemetry_batches) != len(telemetry_raw["batches"]):
        raise OrderPlanScreeningContractError("C-2 telemetry batch identity is duplicated")
    if set(telemetry_batches) != set(batches):
        raise OrderPlanScreeningContractError("C-2 telemetry batch set differs")
    for batch_id, telemetry_batch in telemetry_batches.items():
        batch = batches[batch_id]
        if telemetry_batch["sequence"] != batch["sequence"] or len(telemetry_batch["attempts"]) != batch["attempt_count"]:
            raise OrderPlanScreeningContractError("C-2 telemetry attempt binding differs")
        attempt_numbers = [attempt["attempt_no"] for attempt in telemetry_batch["attempts"]]
        if attempt_numbers != list(range(1, batch["attempt_count"] + 1)):
            raise OrderPlanScreeningContractError("C-2 telemetry attempts are not contiguous")
        expected_status = batch["status"]
        allowed_telemetry_statuses = {expected_status}
        if expected_status != "success":
            allowed_telemetry_statuses.add("unknown")
        if telemetry_batch["status"] not in allowed_telemetry_statuses:
            raise OrderPlanScreeningContractError("C-2 telemetry batch status differs")
        if telemetry_batch["attempts"][-1]["status"] != expected_status:
            raise OrderPlanScreeningContractError("C-2 telemetry final attempt status differs")

    failure_by_plan = {
        plan_id: failure
        for failure in failures_raw["failures"]
        for plan_id in failure["plan_ids"]
    }
    for item in result_raw["items"]:
        plan_id = item["plan_id"]
        if item["stage1_status"] != "selected":
            if item["stage2_status"] != "not_attempted":
                raise OrderPlanScreeningContractError("C-2 non-selected item was attempted")
            continue
        if item["stage2_status"] == "success":
            decision = decision_items.get(plan_id)
            if decision is None or item["batch_id"] != decision["batch_id"] or item["attempt_no"] != decision["attempt_no"]:
                raise OrderPlanScreeningContractError("C-2 successful result does not match decision")
        elif item["stage2_status"] == "not_attempted":
            if plan_id in decision_items or plan_id in failure_by_plan:
                raise OrderPlanScreeningContractError("C-2 not_attempted result has a decision or failure")
        else:
            failure = failure_by_plan.get(plan_id)
            if failure is None or item["failure_code"] != failure["error_code"] or item["stage2_status"] != failure["outcome"]:
                raise OrderPlanScreeningContractError("C-2 failed result does not match failure artifact")


def _c2_compare_or_add(
    session: Session,
    existing: Any,
    values: dict[str, Any],
    *,
    label: str,
    identity: str,
    model: type[Any],
) -> Any:
    if existing is not None:
        def equal(stored: Any, incoming: Any) -> bool:
            if isinstance(stored, Decimal) or isinstance(incoming, Decimal):
                try:
                    return Decimal(str(stored)) == Decimal(str(incoming))
                except (InvalidOperation, ValueError):
                    return False
            return stored == incoming

        if any(
            not equal(getattr(existing, field_name), value)
            for field_name, value in values.items()
        ):
            raise OrderPlanScreeningConflictError(f"C-2 immutable conflict: {label}={identity}")
        return existing
    row = model(**values)
    session.add(row)
    session.flush()
    return row


def _c2_policy_row(
    session: Session,
    directory: Path,
    input_model: OrderPlanScreeningInputArtifact,
    result_model: OrderPlanScreeningResultArtifact,
    *,
    policy_path: str | Path | None,
    binding_path: str | Path | None,
) -> tuple[OrderPlanScreeningPolicy, str]:
    policy_file = _c2_reference_file(
        directory,
        policy_path,
        ("order-plan-screening-policy.v1.json", "policy.json"),
        "experiments/order-plan-screening/config/order-plan-screening-policy.v1.json",
    )
    policy_raw, policy_model, policy_digest = _c2_read_json(
        policy_file, OrderPlanScreeningPolicyArtifact, "C-2 policy"
    )
    binding_file = _c2_reference_file(
        directory,
        binding_path,
        ("order-plan-screening-phase0-binding.v1.json", "binding.json"),
        "experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v1.json",
    )
    try:
        binding_raw = json.loads(
            binding_file.read_bytes().decode("utf-8"),
            object_pairs_hook=_c2_no_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise OrderPlanScreeningContractError("C-2 phase0 binding failed strict validation") from exc
    if not isinstance(binding_raw, dict) or binding_raw.get("schema_version") != C2_BINDING_SCHEMA:
        raise OrderPlanScreeningContractError("C-2 phase0 binding schema is unsupported")
    binding_digest = _c2_sha256_file(binding_file)
    if policy_digest != input_model.policy.sha256 or policy_digest != result_model.policy_sha256:
        raise OrderPlanScreeningContractError("C-2 policy digest does not match the frozen artifacts")
    if policy_model.policy_version != input_model.policy.version or policy_model.policy_version != result_model.policy_version:
        raise OrderPlanScreeningContractError("C-2 policy version does not match the frozen artifacts")
    if binding_digest != input_model.stage2_binding.sha256:
        raise OrderPlanScreeningContractError("C-2 phase0 binding digest does not match the frozen input")
    if binding_raw.get("policy", {}).get("policy_version") != policy_model.policy_version or binding_raw.get("policy", {}).get("sha256") != policy_digest:
        raise OrderPlanScreeningContractError("C-2 phase0 policy reference differs")
    if binding_raw.get("status") != "blocked":
        raise OrderPlanScreeningContractError("C-2 phase0 binding is not blocked as required")
    activation = policy_raw.get("activation")
    quality_gate = policy_raw.get("quality_gate")
    if not isinstance(activation, dict) or not isinstance(quality_gate, dict):
        raise OrderPlanScreeningContractError("C-2 policy activation metadata is missing")
    activated_by = activation.get("approved_by")
    activated_at = activation.get("approved_at")
    activated_at_value = _c2_timestamp(activated_at, "policy.activation.approved_at") if activated_at is not None else None
    values = {
        "policy_version": policy_model.policy_version,
        "schema_version": policy_model.schema_version,
        "producer": policy_model.producer,
        "consumer": policy_model.consumer,
        "policy_status": policy_model.policy_status,
        "decision_scope": policy_model.decision_scope,
        "policy_payload_jsonb": policy_raw,
        "binding_payload_jsonb": binding_raw,
        "policy_sha256": policy_digest,
        "binding_sha256": binding_digest,
        "activation_metadata_jsonb": activation,
        "quality_gate_status": quality_gate.get("status"),
        "active_slot": 1 if policy_model.policy_status == "active" else None,
        "created_by": policy_model.producer,
        "created_at": policy_model.created_at,
        "activated_by": activated_by,
        "activated_at": activated_at_value,
    }
    existing = session.scalar(
        select(OrderPlanScreeningPolicy).where(
            OrderPlanScreeningPolicy.policy_version == policy_model.policy_version
        )
    )
    row = _c2_compare_or_add(
        session, existing, values, label="policy", identity=policy_model.policy_version,
        model=OrderPlanScreeningPolicy,
    )
    return row, binding_digest


def _c2_execution_row(
    session: Session,
    input_model: OrderPlanScreeningInputArtifact,
    result_model: OrderPlanScreeningResultArtifact,
    source_run_id: str,
    source_artifact_raw: dict[str, Any],
    source_artifact_sha256: str,
    input_digest: str,
    binding_digest: str,
    policy: OrderPlanScreeningPolicy,
) -> OrderPlanScreeningExecution:
    execution_id = uuid_module.UUID(input_model.execution_id)
    counts = result_model.counts
    successful = counts.stage2_relevant + counts.stage2_not_relevant + counts.stage2_uncertain
    failures = counts.stage1_failed + counts.stage2_failed + counts.stage2_rejected + sum(
        item.stage2_status == "unknown" for item in result_model.items
    )
    status = "성공" if result_model.status == "성공" else "부분 성공" if result_model.status == "부분 성공" else "실패"
    values = {
        "execution_id": execution_id,
        "request_id": execution_id,
        "schema_version": "bidops.order-plan-screening-execution-row.v1",
        "producer": "screening-api",
        "consumer": "screening-worker-and-review-api",
        "source_run_id": source_run_id,
        "source_artifact_name": input_model.source_artifact.name,
        "source_artifact_schema_version": input_model.source_artifact.schema_version,
        "source_artifact_sha256": source_artifact_sha256,
        "input_artifact_sha256": input_digest,
        "population_count": input_model.population_count,
        "population_sha256": input_model.population_sha256,
        "policy_version": policy.policy_version,
        "policy_sha256": result_model.policy_sha256,
        "binding_sha256": binding_digest,
        "stage1_binding_version": input_model.stage1_binding.version,
        "stage1_binding_sha256": input_model.stage1_binding.sha256,
        "stage2_binding_version": input_model.stage2_binding.version,
        "stage2_binding_sha256": input_model.stage2_binding.sha256,
        "status": status,
        "active_slot": None,
        "requested_by": C2_IMPORT_ACTOR,
        "partial_artifact": result_model.partial_artifact,
        "candidate_count": counts.stage1_selected,
        "completed_count": successful,
        "failure_count": failures,
        "stage1_selected_count": counts.stage1_selected,
        "stage1_filtered_out_count": counts.stage1_filtered_out,
        "stage1_failed_count": counts.stage1_failed,
        "stage2_relevant_count": counts.stage2_relevant,
        "stage2_not_relevant_count": counts.stage2_not_relevant,
        "stage2_uncertain_count": counts.stage2_uncertain,
        "stage2_failed_count": counts.stage2_failed,
        "stage2_rejected_count": counts.stage2_rejected,
        "human_review_count": counts.human_review_count,
        "error_code": "policy_rejected" if result_model.status == "거부됨" else None,
        "queued_at": input_model.created_at,
        "started_at": result_model.created_at,
        "finished_at": result_model.created_at,
        "created_at": result_model.created_at,
    }
    existing = session.get(OrderPlanScreeningExecution, execution_id)
    return _c2_compare_or_add(
        session, existing, values, label="execution", identity=input_model.execution_id,
        model=OrderPlanScreeningExecution,
    )


def _c2_artifact_rows(
    session: Session,
    execution_id: uuid_module.UUID,
    artifacts: dict[str, tuple[dict[str, Any], BaseModel, str, Path]],
) -> int:
    count = 0
    for kind, (raw, model, digest, path) in artifacts.items():
        values = {
            "execution_id": execution_id,
            "kind": kind,
            "schema_version": raw["schema_version"],
            "producer": raw["producer"],
            "consumer": raw["consumer"],
            "sha256": digest,
            "byte_count": path.stat().st_size,
            "object_version": None,
            "validation_status": "valid",
            "created_at": getattr(model, "created_at"),
        }
        existing = session.scalar(
            select(OrderPlanScreeningArtifact).where(
                OrderPlanScreeningArtifact.execution_id == execution_id,
                OrderPlanScreeningArtifact.kind == kind,
            )
        )
        _c2_compare_or_add(
            session, existing, values, label="artifact", identity=kind,
            model=OrderPlanScreeningArtifact,
        )
        count += 0 if existing is not None else 1
    return count


def _c2_attempt_rows(
    session: Session,
    execution_id: uuid_module.UUID,
    decisions: OrderPlanScreeningDecisionsArtifact,
    failures: OrderPlanScreeningFailuresArtifact,
    telemetry: OrderPlanScreeningTelemetryArtifact,
    created_at: datetime,
) -> int:
    failures_by_batch = {failure.batch_id: failure for failure in failures.failures}
    telemetry_by_batch = {batch.batch_id: batch for batch in telemetry.batches}
    expected_keys: set[tuple[str, int]] = set()
    count = 0
    for batch in decisions.batches:
        telemetry_batch = telemetry_by_batch[batch.batch_id]
        failure = failures_by_batch.get(batch.batch_id)
        for telemetry_attempt in telemetry_batch.attempts:
            key = (batch.batch_id, telemetry_attempt.attempt_no)
            expected_keys.add(key)
            attempt_status = telemetry_attempt.status
            failure_type = failure.failure_type if failure is not None and attempt_status in {"failed", "rejected"} else None
            failure_code = failure.error_code if failure is not None and attempt_status in {"failed", "rejected"} else None
            if attempt_status == "failed" and failure is None:
                failure_type, failure_code = "unknown", "retry_attempt_failed"
            started_at = telemetry_attempt.started_at
            finished_at = telemetry_attempt.finished_at or created_at
            measurement = telemetry_attempt.measurement
            plan_ids = list(batch.plan_ids)
            values = {
                "execution_id": execution_id,
                "batch_id": batch.batch_id,
                "sequence": batch.sequence,
                "attempt_no": telemetry_attempt.attempt_no,
                "schema_version": "bidops.order-plan-screening-batch-attempt-row.v1",
                "producer": "screening-worker",
                "consumer": "screening-merge-and-observability",
                "plan_count": len(plan_ids),
                "plan_ids_jsonb": plan_ids,
                "plan_ids_sha256": _c2_digest_json(plan_ids),
                "model_name": decisions.binding.model_name,
                "model_digest": decisions.binding.model_digest,
                "prompt_version": decisions.binding.prompt_version,
                "prompt_sha256": decisions.binding.prompt_sha256,
                "company_profile_version": decisions.binding.company_profile_version,
                "company_profile_sha256": decisions.binding.company_profile_sha256,
                "generation_config_sha256": decisions.binding.generation_config_sha256,
                "attempt_status": attempt_status,
                "failure_type": failure_type,
                "failure_code": failure_code,
                "response_object_ref": None,
                "input_tokens": measurement.input_tokens,
                "cached_input_tokens": measurement.cached_input_tokens,
                "output_tokens": measurement.output_tokens,
                "total_tokens": measurement.total_tokens,
                "duration_ms": measurement.duration_ms,
                "started_at": started_at,
                "finished_at": finished_at,
                "created_at": created_at,
            }
            existing = session.scalar(
                select(OrderPlanScreeningBatchAttempt).where(
                    OrderPlanScreeningBatchAttempt.execution_id == execution_id,
                    OrderPlanScreeningBatchAttempt.batch_id == batch.batch_id,
                    OrderPlanScreeningBatchAttempt.attempt_no == telemetry_attempt.attempt_no,
                )
            )
            _c2_compare_or_add(
                session, existing, values, label="batch attempt",
                identity=f"{batch.batch_id}/{telemetry_attempt.attempt_no}",
                model=OrderPlanScreeningBatchAttempt,
            )
            count += 0 if existing is not None else 1
    existing_keys = set(
        session.execute(
            select(
                OrderPlanScreeningBatchAttempt.batch_id,
                OrderPlanScreeningBatchAttempt.attempt_no,
            ).where(OrderPlanScreeningBatchAttempt.execution_id == execution_id)
        ).all()
    )
    if set(existing_keys) != expected_keys:
        raise OrderPlanScreeningConflictError("C-2 batch attempt population differs")
    return count


def _c2_result_rows(
    session: Session,
    execution_id: uuid_module.UUID,
    source_run_id: str,
    input_digest: str,
    result: OrderPlanScreeningResultArtifact,
    plans: dict[str, OrderPlan],
    binding_digest: str,
) -> int:
    count = 0
    expected_plan_ids = set(plans)
    if {item.plan_id for item in result.items} != expected_plan_ids:
        raise OrderPlanScreeningContractError("C-2 result does not cover source plans")
    for item in result.items:
        plan = plans.get(item.plan_id)
        if plan is None:
            raise OrderPlanScreeningContractError("C-2 result references an unknown order plan")
        item_payload = item.model_dump(mode="json", exclude_none=False)
        values = {
            "execution_id": execution_id,
            "source_run_id": source_run_id,
            "order_plan_id": plan.id,
            "schema_version": "bidops.order-plan-screening-result-row.v1",
            "producer": "order-plan-screening-merge",
            "consumer": "postgres-loader-and-review-api",
            "input_artifact_sha256": input_digest,
            "policy_version": result.policy_version,
            "policy_sha256": result.policy_sha256,
            "binding_sha256": binding_digest,
            "result_sha256": _c2_digest_json(item_payload),
            "stage1_rank": item.stage1_rank,
            "stage1_score": item.stage1_score,
            "nearest_capability": item.nearest_capability,
            "stage1_status": item.stage1_status,
            "stage2_status": item.stage2_status,
            "qwen_relevance": item.qwen_relevance,
            "qwen_score": item.qwen_score,
            "qwen_reason": item.qwen_reason,
            "batch_id": item.batch_id,
            "attempt_no": item.attempt_no,
            "failure_code": item.failure_code,
            "created_at": result.created_at,
        }
        existing = session.scalar(
            select(OrderPlanScreeningResult).where(
                OrderPlanScreeningResult.execution_id == execution_id,
                OrderPlanScreeningResult.order_plan_id == plan.id,
            )
        )
        _c2_compare_or_add(
            session, existing, values, label="result", identity=item.plan_id,
            model=OrderPlanScreeningResult,
        )
        count += 0 if existing is not None else 1
    existing_ids = set(
        session.scalars(
            select(OrderPlanScreeningResult.order_plan_id).where(
                OrderPlanScreeningResult.execution_id == execution_id
            )
        )
    )
    if existing_ids != {plans[item.plan_id].id for item in result.items}:
        raise OrderPlanScreeningConflictError("C-2 result population differs")
    return count


def _c2_feedback_row(
    session: Session,
    path: Path,
    execution_id: uuid_module.UUID,
    plans: dict[str, OrderPlan],
) -> int:
    if not path.exists():
        return 0
    raw, model, _digest = _c2_read_json(
        path, OrderPlanScreeningFeedbackArtifact, "C-2 feedback"
    )
    assert isinstance(model, OrderPlanScreeningFeedbackArtifact)
    if model.execution_id != str(execution_id) or model.plan_id not in plans:
        raise OrderPlanScreeningContractError("C-2 feedback lineage is invalid")
    feedback_id = uuid_module.UUID(model.feedback_id)
    values = {
        "feedback_id": feedback_id,
        "execution_id": execution_id,
        "order_plan_id": plans[model.plan_id].id,
        "revision": model.revision,
        "schema_version": model.schema_version,
        "producer": model.producer,
        "consumer": model.consumer,
        "actor_kind": model.actor_kind,
        "claimed_name": model.claimed_name,
        "relevance": model.relevance,
        "priority": model.priority,
        "memo": model.memo,
        "supersedes_feedback_id": uuid_module.UUID(model.supersedes_feedback_id) if model.supersedes_feedback_id else None,
        "created_at": model.created_at,
    }
    existing = session.get(OrderPlanScreeningFeedback, feedback_id)
    _c2_compare_or_add(
        session, existing, values, label="feedback", identity=model.feedback_id,
        model=OrderPlanScreeningFeedback,
    )
    return 0 if existing is not None else 1


def load_order_plan_screening(
    run_directory: str | Path,
    session: Session,
    *,
    policy_path: str | Path | None = None,
    binding_path: str | Path | None = None,
) -> RunIngestCounts:
    """Strictly load one C-2 artifact set into one caller-owned transaction."""

    directory = Path(run_directory).resolve()
    artifacts: dict[str, tuple[dict[str, Any], BaseModel, str, Path]] = {}
    for kind, filename, model in C2_ARTIFACTS:
        path = _c2_safe_run_file(directory, filename)
        raw, parsed, digest = _c2_read_json(path, model, filename)
        artifacts[kind] = (raw, parsed, digest, path)
    input_raw, input_model, input_digest, _ = artifacts["input"]
    ranking_raw, ranking_model, ranking_digest, _ = artifacts["ranking"]
    decisions_raw, decisions_model, _decisions_digest, _ = artifacts["decisions"]
    failures_raw, failures_model, _failures_digest, _ = artifacts["failures"]
    telemetry_raw, telemetry_model, _telemetry_digest, _ = artifacts["telemetry"]
    result_raw, result_model, _result_digest, _ = artifacts["result"]
    assert isinstance(input_model, OrderPlanScreeningInputArtifact)
    assert isinstance(ranking_model, OrderPlanScreeningRankingArtifact)
    assert isinstance(decisions_model, OrderPlanScreeningDecisionsArtifact)
    assert isinstance(failures_model, OrderPlanScreeningFailuresArtifact)
    assert isinstance(telemetry_model, OrderPlanScreeningTelemetryArtifact)
    assert isinstance(result_model, OrderPlanScreeningResultArtifact)
    _c2_check_siblings(
        input_raw, ranking_raw, decisions_raw, failures_raw, telemetry_raw, result_raw,
        input_digest, ranking_digest,
    )
    if input_model.source_artifact.name != "collected-order-plans.json":
        source_path = _c2_safe_run_file(directory, input_model.source_artifact.name)
    else:
        source_path = _c2_safe_run_file(directory, "collected-order-plans.json")
    source_raw, source_model, source_digest = _c2_read_json(
        source_path, OrderPlanArtifact, input_model.source_artifact.name
    )
    if source_digest != input_model.source_artifact.sha256:
        raise OrderPlanScreeningContractError("source order-plan artifact digest differs")
    source_population = _c2_source_population(source_raw)
    input_population = [item.model_dump(mode="json") for item in input_model.items]
    if source_population != input_population or _c2_digest_json(input_population) != input_model.population_sha256:
        raise OrderPlanScreeningContractError("C-2 input is not the complete source population")

    source_run_id = input_model.source_run_id
    source_run = session.get(Run, source_run_id)
    if source_run is None:
        raise OrderPlanScreeningContractError("C-2 source run does not exist")
    # 발주계획은 lifecycle 테이블이다. 같은 transaction 안에서 lifecycle이 공개한
    # 적재 함수로 넣는다(§4).
    load_order_plan_artifact(
        session,
        run_id=source_run_id,
        raw=source_raw,
        timezone_name=source_run.timezone,
        source_file=str(source_path),
    )
    policy, binding_digest = _c2_policy_row(
        session, directory, input_model, result_model,
        policy_path=policy_path, binding_path=binding_path,
    )
    existing_execution = session.get(
        OrderPlanScreeningExecution, uuid_module.UUID(input_model.execution_id)
    )
    execution = _c2_execution_row(
        session, input_model, result_model, source_run_id, source_raw,
        input_model.source_artifact.sha256, input_digest, binding_digest, policy,
    )
    execution_id = execution.execution_id
    artifact_count = _c2_artifact_rows(session, execution_id, artifacts)
    attempt_count = _c2_attempt_rows(
        session, execution_id, decisions_model, failures_model, telemetry_model,
        result_model.created_at,
    )
    plans = {
        plan.order_plan_unty_no: plan
        for plan in session.scalars(select(OrderPlan)).all()
        if plan.order_plan_unty_no in {item.plan_id for item in result_model.items}
    }
    result_count = _c2_result_rows(
        session, execution_id, source_run_id, input_digest, result_model,
        plans, binding_digest,
    )
    feedback_count = _c2_feedback_row(
        session, _c2_safe_run_file(directory, "screening-feedback.json"),
        execution_id, plans,
    )
    return RunIngestCounts(
        # `IngestResult.order_plans`는 C-2 전용 디렉터리에서 적재된 결과 건수를
        # 그대로 실어 왔다. hook 경로로 옮기면서 그 값을 잃지 않게 함께 채운다.
        order_plans=result_count,
        screening_executions=0 if existing_execution is not None else 1,
        screening_attempts=attempt_count,
        screening_results=result_count,
        screening_artifacts=artifact_count,
        screening_feedback=feedback_count,
    )


# A descriptive alias keeps the loader API discoverable to callers that use
# the C-2 noun from the contract.
load_c2_artifacts = load_order_plan_screening




# --- 회차 적재 hook (명세 §6.2) ----------------------------------------------


def _c2_source_run_id(directory: Path) -> str | None:
    """C-2 전용 디렉터리이면 그 source run을 돌려준다. 아니면 `None`.

    감지 규칙과 `source_run_id` 검증이 여기 있다. lifecycle은 이 판단을 하지
    못하므로, screening이 없으면 같은 디렉터리가 일반 회차 디렉터리로 처리된다.
    """

    screening_input_candidate = _read_optional_json(directory / "screening-input.json")
    screening_raw = _read_optional_json(directory / "screening-results.json")
    decisions_raw = _read_optional_json(directory / "screening-decisions.json")
    c2_specific_sibling_present = any(
        (directory / name).is_file()
        for name in (
            "screening-ranking.json",
            "screening-failures.json",
            "screening-telemetry.json",
            "screening-feedback.json",
        )
    )
    c2_decisions_present = (
        isinstance(decisions_raw, dict)
        and decisions_raw.get("schema_version") == "bidops.order-plan-screening-decisions.v1"
    )
    c2_present = (
        (
            isinstance(screening_input_candidate, dict)
            and screening_input_candidate.get("schema_version") == C2_INPUT_SCHEMA
        )
        or (
            isinstance(screening_raw, dict)
            and screening_raw.get("schema_version") == C2_RESULT_SCHEMA
        )
        or c2_specific_sibling_present
        or c2_decisions_present
    )
    if not c2_present:
        return None
    source_run_id = (
        screening_input_candidate.get("source_run_id")
        if isinstance(screening_input_candidate, dict)
        else None
    )
    if not isinstance(source_run_id, str) or not source_run_id.strip():
        raise OrderPlanScreeningContractError("C-2 source_run_id is missing")
    return source_run_id


def _claimed_c2_load(
    session: Session,
    directory: Path,
    *,
    policy_path: Path | None = None,
    binding_path: Path | None = None,
) -> RunIngestCounts:
    """`RunDirectoryClaim.load` 계약에 맞춘 어댑터.

    `load_order_plan_screening(run_directory, session, ...)`은 인자 순서가 반대라
    여기서 맞춰 넘긴다. 확장점이 순서를 못박아 두었기 때문에 이 어긋남이 런타임까지
    숨지 않는다.
    """

    return load_order_plan_screening(
        directory, session, policy_path=policy_path, binding_path=binding_path
    )


def inspect_c2_directory(directory: Path) -> RunDirectoryClaim | None:
    """C-2 전용 디렉터리면 주장을, 아니면 `None`을 돌려준다."""

    source_run_id = _c2_source_run_id(Path(directory))
    if source_run_id is None:
        return None
    return RunDirectoryClaim(source_run_id=source_run_id, load=_claimed_c2_load)


def _feedback_file(directory: Path, reports_root: Path | None) -> Path:
    root = reports_root if reports_root is not None else directory.parent.parent / "reports"
    return root / directory.name / FEEDBACK_FILE


def _run_notice_map(session: Session, run_id: str) -> dict[str, Notice]:
    """이 회차에서 관측된 공고를 식별자로 찾는 표.

    판정은 회차에 관측된 공고에만 붙는다. 판정 산출물이 그 밖의 공고를 가리키면
    `judgment_notice_not_found` 경고로 남기고 적재하지 않는다.
    """

    rows = session.scalars(
        select(Notice)
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(NoticeObservation.run_id == run_id)
        .distinct()
    ).all()
    return {notice.notice_key: notice for notice in rows}


def _generation_binding(
    *artifacts: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """v3 산출물이 합의한 generation binding. 서로 어긋나면 `(None, None)`.

    저장은 lifecycle이 회차 projection에 한다. screening은 어느 값이 유효한
    binding인지만 판단한다 — 그 판단이 v3 계약의 일부이기 때문이다.
    """

    config: dict[str, Any] | None = None
    digest: str | None = None
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("schema_version") not in V3_GENERATION_SCHEMAS:
            continue
        candidate = artifact.get("generation_config")
        candidate_digest = artifact.get("generation_config_digest")
        if isinstance(candidate, dict) and isinstance(candidate_digest, str):
            if config is None:
                config, digest = candidate, candidate_digest
            elif config != candidate or digest != candidate_digest:
                # 산출물 간 불일치는 엄격 적재기가 이미 거절한다. 겉보기에
                # 유효한 회차 아래에 섞인 binding을 저장하지 않는다.
                return None, None
    return config, digest


def _run_scoped_counts(session: Session, run_id: str) -> tuple[int, int]:
    """회차 범위의 판정·리뷰 건수. 두 테이블 모두 screening 소유다(§5.1)."""

    judgments = int(
        session.scalar(
            select(func.count(func.distinct(Judgment.id)))
            .join(Notice, Judgment.notice_pk == Notice.id)
            .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
            .where(NoticeObservation.run_id == run_id)
        )
        or 0
    )
    reviews = int(
        session.scalar(
            select(func.count(func.distinct(Review.id)))
            .join(Notice, Review.notice_pk == Notice.id)
            .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
            .where(NoticeObservation.run_id == run_id)
        )
        or 0
    )
    return judgments, reviews


def load_run_judgments(
    session: Session,
    run_id: str,
    directory: Path,
    *,
    reports_root: Path | None = None,
) -> RunIngestCounts:
    """공고 적재가 끝난 회차에 판정·리뷰·revision을 적재한다.

    lifecycle이 이미 적재한 공고만 대상으로 하며, 판정 계약 해석과 v3 lineage
    검증은 전부 여기서 한다. 경고는 lifecycle 공개 함수를 통해 같은 회차에
    기록되므로 API 응답에서 기존과 같은 순서로 보인다.
    """

    directory = Path(directory)
    run = session.get(Run, run_id)
    if run is None:  # pragma: no cover - 호출부가 회차를 만든 뒤에만 부른다.
        raise ValueError(f"판정을 적재할 회차가 없습니다: {run_id}")

    screening_input_path = directory / "screening-input.json"
    screening_path = directory / "screening-results.json"
    decisions_path = directory / "screening-decisions.json"
    validation_raw = _read_optional_json(directory / "validation-set.json")
    collection_raw = _read_optional_json(directory / "collected-notices.json")
    order_plan_raw = _read_optional_json(directory / ORDER_PLAN_FILE)

    screening_input_present, screening_input_raw, screening_input_invalid = _read_screening_input(
        screening_input_path
    )
    screening_input_digest = None
    if screening_input_raw is not None and screening_input_invalid is None:
        try:
            screening_input_digest = hashlib.sha256(screening_input_path.read_bytes()).hexdigest()
        except OSError:
            screening_input_invalid = "file became unreadable"
    screening_raw = _read_optional_json(screening_path)
    decisions_raw = _read_optional_json(decisions_path)
    order_plan_only = (
        order_plan_raw is not None
        and validation_raw is None
        and screening_input_raw is None
        and collection_raw is None
    )

    decisions_generation_invalid = False
    screening_generation_invalid = False
    if isinstance(decisions_raw, dict) and decisions_raw.get("schema_version") in V3_GENERATION_SCHEMAS:
        decisions_raw, generation_error = _normalize_v3_generation_binding(
            decisions_raw, "screening-decisions.json"
        )
        if generation_error is not None or decisions_raw is None:
            decisions_generation_invalid = True
            _record_warning(
                session,
                run_id,
                "error",
                "decisions_invalid",
                "screening-decisions.json generation 계약을 해석하지 못했습니다.",
                {"file": str(decisions_path), "reason": generation_error or "invalid"},
            )
            decisions_raw = None
    if isinstance(screening_raw, dict) and screening_raw.get("schema_version") in V3_GENERATION_SCHEMAS:
        screening_raw, generation_error = _normalize_v3_generation_binding(
            screening_raw, "screening-results.json"
        )
        if generation_error is not None or screening_raw is None:
            screening_generation_invalid = True
            _record_warning(
                session,
                run_id,
                "error",
                "screening_results_invalid",
                "screening-results.json generation 계약을 해석하지 못했습니다.",
                {"file": str(screening_path), "reason": generation_error or "invalid"},
            )
            screening_raw = None

    verified_v3_lineage = None
    if isinstance(screening_raw, dict) and screening_raw.get("schema_version") == "bidops.screening.v3":
        verified_v3_lineage, lineage_error = _verified_v3_lineage(
            session,
            screening_input=screening_input_raw,
            decisions=decisions_raw,
            results=screening_raw,
            input_digest=screening_input_digest,
        )
        if lineage_error is not None:
            _record_warning(
                session,
                run_id,
                "error",
                "screening_lineage_invalid",
                "screening v3 산출물을 저장된 실행에 연결하지 못했습니다.",
                {"file": str(screening_path), "reason": lineage_error},
            )

    # 판정 산출물이 가리키는 공고는 lifecycle이 이미 적재했다. 그 공고가 이
    # 회차에 관측된 것만 대상으로 한다.
    notices = {} if (screening_input_present and screening_input_invalid is not None) else _run_notice_map(
        session, run_id
    )

    if verified_v3_lineage is not None and verified_v3_lineage.source_run_id != run_id:
        # 동결 입력이 가리키는 source run의 관측을 먼저 세운다. revision이 그
        # 회차를 참조하므로 순서를 뒤집을 수 없다. 공고 관측은 lifecycle
        # 테이블이므로 공개 함수로만 만든다(§4).
        for notice_key in verified_v3_lineage.input_notices:
            notice = notices.get(notice_key)
            if notice is None:
                continue
            mirror_notice_observation(
                session,
                notice_id=notice.id,
                from_run_id=run_id,
                to_run_id=verified_v3_lineage.source_run_id,
            )

    decisions_schema = None
    if decisions_raw is not None:
        try:
            if decisions_raw.get("schema_version") == "bidops.decisions.v3":
                generation_error = _v3_generation_artifact_error(
                    decisions_raw, "screening-decisions.json", _DECISIONS_V3_KEYS
                )
                input_config = (
                    screening_input_raw.get("generation_config")
                    if isinstance(screening_input_raw, dict)
                    else None
                )
                input_digest = (
                    screening_input_raw.get("generation_config_digest")
                    if isinstance(screening_input_raw, dict)
                    else None
                )
                if generation_error is None:
                    generation_error = _generation_binding_matches(
                        decisions_raw,
                        input_config,
                        input_digest,
                        "screening-decisions.json",
                    )
                if generation_error is not None:
                    decisions_generation_invalid = True
                    _record_warning(
                        session,
                        run_id,
                        "error",
                        "decisions_invalid",
                        "screening-decisions.json generation 계약을 해석하지 못했습니다.",
                        {"file": str(decisions_path), "reason": generation_error},
                    )
                    decisions_raw = None
                    raise ValueError("invalid v3 generation binding")
            decisions_model = DecisionArtifact.model_validate(decisions_raw)
            _record_unknown_fields(
                session,
                run_id,
                _artifact_unknown_fields(decisions_raw, decisions_model),
                str(decisions_path),
            )
            decisions_schema = artifact_version(decisions_model) or decisions_raw.get("schema_version")
        except ValidationError as exc:
            _record_warning(
                session,
                run_id,
                "error",
                "decisions_invalid",
                "screening-decisions.json 계약을 해석하지 못했습니다.",
                {"file": str(decisions_path), "error": str(exc)},
            )
        except ValueError:
            # 안전한 generation 전용 경고는 위에서 이미 기록했다.
            pass
    if decisions_schema == "bidops.decisions.v1":
        _record_warning(
            session,
            run_id,
            "warning",
            "decisions_schema_gap",
            "계약 v2가 요구되지만 decisions.v1 산출물을 적재했습니다.",
            {"actual": decisions_schema, "expected": "bidops.decisions.v2"},
        )

    if screening_raw is None:
        if not order_plan_only:
            _record_warning(
                session,
                run_id,
                "warning",
                "screening_results_missing",
                "screening-results.json이 없어 공고만 적재했습니다.",
                {"file": str(screening_path)},
            )
        _remove_judgments_without_screening(session, notices)
    else:
        screening_schema = screening_raw.get("schema_version")
        inferred_schema = {
            "bidops.screening.v1": "bidops.decisions.v1",
            "bidops.screening.v2": "bidops.decisions.v2",
        }.get(screening_schema, screening_schema or "unknown")
        result_schema = decisions_schema or inferred_schema
        if decisions_generation_invalid:
            # 신뢰할 수 없는 형제 decision 산출물을 가진 v3 결과는 안전한
            # projection이 아니다. 중첩 행에 쓸 만한 등급이 있어도 적재하지 않는다.
            _record_warning(
                session,
                run_id,
                "error",
                "screening_results_invalid",
                "screening-decisions.json generation binding이 유효하지 않아 판정을 적재하지 않았습니다.",
                {"file": str(screening_path), "reason": "decisions generation binding is invalid"},
            )
            _remove_judgments_without_screening(session, notices)
        else:
            expected_config = None
            expected_digest = None
            for source in (screening_input_raw, decisions_raw):
                if isinstance(source, dict) and source.get("schema_version") in V3_GENERATION_SCHEMAS:
                    expected_config = source.get("generation_config")
                    expected_digest = source.get("generation_config_digest")
                    break
            _load_screening_results(
                session,
                run_id,
                notices,
                screening_raw,
                str(screening_path),
                result_schema,
                expected_generation_config=expected_config,
                expected_generation_digest=expected_digest,
                verified_v3_lineage=verified_v3_lineage,
            )

    load_feedback(session, run, notices, _feedback_file(directory, reports_root))

    if screening_input_invalid is not None or decisions_generation_invalid or screening_generation_invalid:
        generation_config, generation_digest = None, None
    else:
        generation_config, generation_digest = _generation_binding(
            screening_input_raw, decisions_raw, screening_raw
        )

    judgments, reviews = _run_scoped_counts(session, run_id)
    return RunIngestCounts(
        judgments=judgments,
        reviews=reviews,
        generation_config=generation_config,
        generation_config_digest=generation_digest,
    )


class ScreeningRunIngestHook:
    """`RunIngestHook` 구현. 조립 계층이 registry에 등록한다(§6)."""

    def inspect_run_directory(self, directory: Path) -> RunDirectoryClaim | None:
        return inspect_c2_directory(directory)

    def run_ingested(
        self,
        session: Session,
        run_id: str,
        directory: Path,
        *,
        reports_root: Path | None = None,
    ) -> RunIngestCounts:
        return load_run_judgments(session, run_id, directory, reports_root=reports_root)


__all__ = [
    "C2_INPUT_SCHEMA",
    "C2_RESULT_SCHEMA",
    "OrderPlanScreeningConflictError",
    "OrderPlanScreeningContractError",
    "ScreeningRunIngestHook",
    "VerifiedV3Lineage",
    "inspect_c2_directory",
    "load_order_plan_screening",
    "load_run_judgments",
]
