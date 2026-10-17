"""Manual C-2 execution, review, and immutable artifact boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from ...core.config import Settings, get_settings
from ...lifecycle.ingest.contracts import OrderPlanArtifact, OrderPlanContract
from ..c2_contracts import (
    OrderPlanScreeningInputArtifact,
    OrderPlanScreeningPolicyArtifact,
)
from ...core.models import AuditEvent, IdempotencyRecord
from ...lifecycle import active_opportunity_predicate, authoritative_link_predicate
from ...lifecycle.models import IngestWarning, Opportunity, OpportunityLink, OrderPlan, OrderPlanObservation, Run
from ..models import (
    OrderPlanScreeningArtifact,
    OrderPlanScreeningBatchAttempt,
    OrderPlanScreeningExecution,
    OrderPlanScreeningFeedback,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningQualityGate,
    OrderPlanScreeningResult,
)
from ...core.api_errors import BundleServiceError, validate_actor


#: `first_observed_from`이 받는 날짜의 계약 시간대. 사전규격 목록의
#: `observed_from`·`observed_to`와 같은 규칙으로 KST 일자 00:00을 하한으로 쓴다.
_SEOUL = ZoneInfo("Asia/Seoul")
INPUT_SCHEMA = "bidops.order-plan-screening-input.v1"
INPUT_ROW_SCHEMA = "bidops.order-plan-screening-execution-row.v1"
ARTIFACT_KINDS = {
    "screening_input": "input",
    "ranking": "ranking",
    "decisions": "decisions",
    "failures": "failures",
    "telemetry": "telemetry",
    "screening_result": "result",
}
ARTIFACT_FILENAMES = {
    "input": "screening-input.json",
    "ranking": "screening-ranking.json",
    "decisions": "screening-decisions.json",
    "failures": "screening-failures.json",
    "telemetry": "screening-telemetry.json",
    "result": "screening-results.json",
}
ARTIFACT_RESPONSE_NAMES = {value: key for key, value in ARTIFACT_KINDS.items()}
EXECUTION_OPERATION = "c2_execution_create"
STOP_OPERATION = "c2_execution_stop"
FEEDBACK_OPERATION = "c2_feedback_create"
TERMINAL_STATUSES = {"성공", "부분 성공", "실패", "중단됨"}
ACTIVE_STATUSES = {"실행 중", "중지 요청"}
# `X-BidOps-Trigger` 값(contracts "실행 트리거 헤더와 게이트"). 헤더 없음(None)은 사람의 수동 운영 실행이다.
EXECUTION_TRIGGERS = frozenset({"daily_script", "manual_resume", "gate_measurement"})
DAILY_TRIGGERS = frozenset({"daily_script", "manual_resume"})


class OrderPlanScreeningError(RuntimeError):
    """An API-safe C-2 failure."""

    def __init__(self, code: str, message: str, *, status_code: int = 409, request_id: UUID | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(code)


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical(value))


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _safe_json_bytes(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise OrderPlanScreeningError("source_run_incomplete", "C-2 source artifact를 읽을 수 없습니다", status_code=409)
    try:
        data = path.read_bytes()
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_no_duplicate_pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise OrderPlanScreeningError("source_run_incomplete", "C-2 source artifact가 유효하지 않습니다", status_code=409) from None
    if not isinstance(value, dict):
        raise OrderPlanScreeningError("source_run_incomplete", "C-2 source artifact가 유효하지 않습니다", status_code=409)
    return value, data


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _safe_copy(source: Path, target: Path) -> bytes:
    if source.is_symlink() or not source.is_file():
        raise OrderPlanScreeningError("binding_mismatch", "C-2 승인 binding을 읽을 수 없습니다", status_code=409)
    try:
        data = source.read_bytes()
        with target.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        raise OrderPlanScreeningError("immutable_conflict", "C-2 execution artifact가 이미 존재합니다", status_code=409) from None
    except OSError:
        raise OrderPlanScreeningError("binding_mismatch", "C-2 승인 binding을 읽을 수 없습니다", status_code=409) from None
    return data


def _read_pinned(path: Path, expected_sha256: str, request_id: UUID) -> bytes:
    """Read a mounted approved file and re-check its bytes digest."""

    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("not a regular file")
        data = path.read_bytes()
    except OSError:
        raise OrderPlanScreeningError("binding_mismatch", "C-2 승인 binding을 읽을 수 없습니다", request_id=request_id) from None
    if _sha256_bytes(data) != expected_sha256:
        raise OrderPlanScreeningError("binding_mismatch", "C-2 policy·binding 파일이 digest와 일치하지 않습니다", request_id=request_id)
    return data


def _safe_actor(value: str | None, actor_format: str | None, request_id: UUID | None) -> str:
    try:
        return validate_actor(value, actor_format)
    except BundleServiceError as error:
        raise OrderPlanScreeningError(error.code, error.message, status_code=error.status_code, request_id=request_id) from error


def _safe_id(value: str, label: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."} or "/" in value or "\\" in value:
        raise OrderPlanScreeningError("source_run_incomplete", f"C-2 {label} 식별자가 올바르지 않습니다", status_code=409)
    return value


def _source_directory(settings: Settings, run_id: str) -> Path:
    safe_run_id = _safe_id(run_id, "source run")
    base = safe_run_id.split("--", 1)[0]
    approved_root = settings.bidops_root.resolve(strict=False)
    runs_root = settings.bidops_root / "data" / "runs"
    candidate = runs_root / base
    try:
        resolved_runs_root = runs_root.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=False)
    except OSError:
        raise OrderPlanScreeningError("source_run_incomplete", "C-2 source run 경로를 확인할 수 없습니다", status_code=409) from None
    if (
        runs_root.is_symlink()
        or candidate.is_symlink()
        or not resolved_runs_root.is_relative_to(approved_root)
        or not resolved_candidate.is_relative_to(resolved_runs_root)
    ):
        raise OrderPlanScreeningError("source_run_incomplete", "C-2 source run 경로가 허용 범위를 벗어났습니다", status_code=409)
    return candidate


def execution_directory(settings: Settings, source_run_id: str, execution_id: UUID) -> Path:
    return _source_directory(settings, source_run_id).parent / f"{_safe_id(source_run_id, 'source run')}--c2-{execution_id}"


def _source_population(raw: dict[str, Any]) -> list[dict[str, str]]:
    if raw.get("schema_version") != "bidops.collected-order-plans.v1":
        raise OrderPlanScreeningError("source_run_incomplete", "source run schema가 C-2와 다릅니다", status_code=409)
    warnings = raw.get("warnings")
    if warnings:
        raise OrderPlanScreeningError("source_run_incomplete", "source run이 완전한 회차가 아닙니다", status_code=409)
    metadata = raw.get("metadata")
    collection = metadata.get("collection") if isinstance(metadata, Mapping) else None
    for container in (raw, metadata, collection, raw.get("counts")):
        if not isinstance(container, Mapping):
            continue
        for key in ("complete", "collection_complete"):
            if key in container and container[key] is not True:
                raise OrderPlanScreeningError("source_run_incomplete", "source run이 완전한 회차가 아닙니다", status_code=409)
        if container.get("status") in {"partial", "incomplete", "failed"}:
            raise OrderPlanScreeningError("source_run_incomplete", "source run이 완전한 회차가 아닙니다", status_code=409)
    rows = raw.get("order_plans")
    if not isinstance(rows, list) or not rows:
        raise OrderPlanScreeningError("source_run_incomplete", "source run에 발주계획 모집단이 없습니다", status_code=409)
    population: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise OrderPlanScreeningError("source_run_incomplete", "source run 발주계획 항목이 유효하지 않습니다", status_code=409)
        try:
            OrderPlanContract.model_validate(row)
        except ValidationError:
            raise OrderPlanScreeningError("source_run_incomplete", "source run 발주계획 항목이 유효하지 않습니다", status_code=409) from None
        plan_id = row.get("order_plan_unty_no") or row.get("orderPlanUntyNo") or row.get("plan_id")
        title = row.get("title") or row.get("biz_nm") or row.get("business_name")
        if not isinstance(plan_id, str) or not plan_id.strip() or not isinstance(title, str) or not title.strip() or plan_id in seen:
            raise OrderPlanScreeningError("source_run_incomplete", "source run 발주계획 식별자가 유효하지 않습니다", status_code=409)
        source_hash = row.get("source_sha256")
        if source_hash is None and isinstance(row.get("source"), Mapping):
            source_hash = row["source"].get("source_sha256")
        if not _is_sha256(source_hash):
            raise OrderPlanScreeningError("source_run_incomplete", "source run 발주계획 원문 hash가 유효하지 않습니다", status_code=409)
        seen.add(plan_id)
        population.append({"plan_id": plan_id, "title": title, "source_sha256": source_hash})
    declared = raw.get("counts")
    if isinstance(declared, Mapping):
        count = declared.get("total", declared.get("order_plans", declared.get("plans")))
        if isinstance(count, int) and count != len(population):
            raise OrderPlanScreeningError("source_run_incomplete", "source run 모집단 수가 일치하지 않습니다", status_code=409)
    return population


class OrderPlanScreeningService:
    """Own C-2 API mutations and read projections."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _idempotent(self, session: Session, operation: str, request_id: UUID, request_hash: str) -> dict[str, Any] | None:
        row = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.request_id == request_id,
            )
        )
        if row is None:
            return None
        if row.request_sha256 != request_hash:
            raise OrderPlanScreeningError("idempotency_conflict", "같은 request_id가 다른 요청에 사용되었습니다", request_id=request_id)
        if not isinstance(row.response_snapshot, Mapping):
            raise OrderPlanScreeningError("idempotency_conflict", "idempotency 응답을 재생할 수 없습니다", request_id=request_id)
        return dict(row.response_snapshot)

    def _policy_binding(
        self,
        session: Session,
        policy_version: str,
        request_id: UUID,
        *,
        purpose: str = "operational",
    ) -> tuple[OrderPlanScreeningPolicy, dict[str, Any], dict[str, Any], bytes, bytes]:
        """Gate on the DB row and pin the mounted policy·binding bytes (ADR-0060).

        The row is the only activation authority.  The policy file's
        ``policy_status`` is a publish-time snapshot, so only its enum validity
        is checked (by the artifact model) and it must agree with the binding's
        copy.  A measurement-only execution accepts an ``activation_candidate``
        row without a passed gate; every other check is the same.
        """

        from .order_plan_policy import binding_consistent, execution_transport_allowed, mounted_files

        policy = session.scalar(
            select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == policy_version).with_for_update()
        )
        if policy is None:
            raise OrderPlanScreeningError("policy_not_active", "C-2 policy가 활성 상태가 아닙니다", request_id=request_id)
        if purpose == "gate_measurement":
            allowed = policy.policy_status in {"activation_candidate", "active"}
        else:
            allowed = policy.policy_status == "active" and policy.quality_gate_status == "passed"
        if not allowed:
            raise OrderPlanScreeningError("policy_not_active", "C-2 policy가 활성 상태가 아닙니다", request_id=request_id)
        try:
            policy_model = OrderPlanScreeningPolicyArtifact.model_validate(policy.policy_payload_jsonb)
        except ValidationError:
            raise OrderPlanScreeningError("binding_mismatch", "C-2 policy binding이 유효하지 않습니다", request_id=request_id) from None
        if policy_model.policy_version != policy_version:
            raise OrderPlanScreeningError("binding_mismatch", "C-2 policy binding이 유효하지 않습니다", request_id=request_id)
        # Digests are over the mounted file bytes, never a canonical re-dump.
        # Without both regular files at the configured paths there is nothing
        # approved to freeze into the execution directory.
        if mounted_files(self.settings, policy).missing is not None:
            raise OrderPlanScreeningError("binding_mismatch", "C-2 policy·binding 파일이 digest와 일치하지 않습니다", request_id=request_id)
        policy_bytes = _read_pinned(Path(self.settings.c2_policy_path or ""), policy.policy_sha256, request_id)
        binding = policy.binding_payload_jsonb
        if not isinstance(binding, Mapping) or binding.get("schema_version") != "bidops.order-plan-screening-phase0-binding.v1":
            raise OrderPlanScreeningError("binding_mismatch", "C-2 phase0 binding이 유효하지 않습니다", request_id=request_id)
        stage1 = binding.get("stage1_binding")
        stage2 = binding.get("stage2_binding")
        if not isinstance(stage1, Mapping) or not isinstance(stage2, Mapping):
            raise OrderPlanScreeningError("binding_mismatch", "C-2 stage binding이 유효하지 않습니다", request_id=request_id)
        binding_bytes = _read_pinned(Path(self.settings.c2_binding_path or ""), policy.binding_sha256, request_id)
        # binding_consistent also rejects status=blocked with execution_allowed=true.
        policy_reference = binding.get("policy")
        if (
            not binding_consistent(policy)
            or not isinstance(policy_reference, Mapping)
            or policy_reference.get("policy_status") != policy_model.policy_status
        ):
            raise OrderPlanScreeningError("binding_mismatch", "C-2 policy와 binding이 다릅니다", request_id=request_id)
        if not execution_transport_allowed(self.settings, policy):
            raise OrderPlanScreeningError("service_unavailable", "승인된 private vLLM transport를 사용할 수 없습니다", status_code=503, request_id=request_id)
        return policy, dict(stage1), dict(stage2), policy_bytes, binding_bytes

    @staticmethod
    def _require_measurement_run(session: Session, policy_version: str, source_run_id: str, request_id: UUID) -> None:
        """A measurement-only execution may only run a gate's frozen measurement run."""

        gates = session.scalars(
            select(OrderPlanScreeningQualityGate.measurement_run_ids_json).where(
                OrderPlanScreeningQualityGate.policy_version == policy_version
            )
        ).all()
        if not any(isinstance(run_ids, list) and source_run_id in run_ids for run_ids in gates):
            raise OrderPlanScreeningError(
                "invalid_request", "게이트 측정 회차가 아닌 source run입니다", status_code=422, request_id=request_id
            )

    def _require_daily_trigger(self, session: Session, policy_version: str, request_id: UUID) -> None:
        """Recompute the daily switch for script-originated requests (결정 21)."""

        from .order_plan_daily_trigger import effective_state
        from .order_plan_policy import C2PolicyError

        state = effective_state(session, self.settings)
        if not state.effective_enabled:
            raise C2PolicyError(
                "daily_trigger_off",
                "C-2 일일 자동 실행이 꺼져 있습니다",
                request_id=request_id,
                details={"reasons": list(state.reasons)},
            )
        if state.policy is None or state.policy.policy_version != policy_version:
            raise OrderPlanScreeningError("policy_not_active", "C-2 policy가 활성 상태가 아닙니다", request_id=request_id)

    def _approved_inputs(self, stage2: Mapping[str, Any], request_id: UUID) -> tuple[tuple[Path, bytes], ...]:
        """Read the three approved stage-2 inputs and pin each to its digest.

        The generation config joins capabilities and prompt here so the values
        that shape the request are loaded from an approved artifact instead of
        being hardcoded in the adapter.  Recording a ``generation_config_sha256``
        the runtime never opened would make the judgment lineage untrue
        ([ADR-0044]).
        """

        paths = (
            (Path(self.settings.c2_capabilities_path or ""), stage2.get("company_profile_sha256")),
            (Path(self.settings.c2_prompt_path or ""), stage2.get("prompt_sha256")),
            (Path(self.settings.c2_generation_config_path or ""), stage2.get("generation_config_sha256")),
        )
        loaded: list[tuple[Path, bytes]] = []
        for path, expected in paths:
            if path.is_symlink() or not path.is_file():
                raise OrderPlanScreeningError("binding_mismatch", "승인된 C-2 review input을 읽을 수 없습니다", request_id=request_id)
            try:
                data = path.read_bytes()
            except OSError:
                raise OrderPlanScreeningError("binding_mismatch", "승인된 C-2 review input을 읽을 수 없습니다", request_id=request_id) from None
            if _sha256_bytes(data) != expected:
                raise OrderPlanScreeningError("binding_mismatch", "승인된 C-2 review input digest가 다릅니다", request_id=request_id)
            loaded.append((path, data))
        return tuple(loaded)

    def _create_response(self, execution: OrderPlanScreeningExecution) -> dict[str, Any]:
        return {
            "schema_version": "execution-create-response.v1",
            "producer": "screening-api",
            "consumer": "human-review-client",
            "execution_id": str(execution.execution_id),
            "request_id": str(execution.request_id),
            "source_run_id": execution.source_run_id,
            "policy_version": execution.policy_version,
            "status": execution.status,
            "binding_sha256": execution.binding_sha256,
            "stage1_binding_sha256": execution.stage1_binding_sha256,
            "stage2_binding_sha256": execution.stage2_binding_sha256,
            "execution_allowed": True,
        }

    def require_complete_source_run(
        self,
        session: Session,
        source_run_id: str,
        *,
        request_id: UUID | None = None,
    ) -> tuple[Run, Path, bytes, list[dict[str, str]]]:
        """C-2가 실행을 만들 수 있는 source run인지 확인하고 모집단을 돌려준다.

        세 가지를 차례로 본다 — 회차가 있는가, 적재 경고가 하나도 없는가,
        DB projection이 수집 원본 모집단과 정확히 같은가. 셋 다 실패 code는
        `source_run_incomplete` 하나이고 사유만 다르다. **어긋난 사유는 응답이
        아니라 서버 로그로 나간다**(`docs/contracts.md`가 이 code의 `details`를
        `null`로 고정하고 message를 일반 문구로 고정한다).

        회차 적재 경고는 그 자체로 "이 회차는 계약대로 다 적재되지 않았다"는
        뜻이므로 하나라도 있으면 거부한다. 적재 경로가 확장점을 등록하지 않아
        생기는 `judgment_ingest_skipped`도 여기서 걸린다 — 그것이 적재 프로세스
        결함일 뿐이더라도, 이 검사를 code로 예외 처리하면 진짜 부분 적재까지
        함께 통과한다.
        """

        run = session.get(Run, source_run_id)
        if run is None:
            raise OrderPlanScreeningError("source_run_incomplete", "source run을 찾을 수 없습니다", request_id=request_id)
        warning_codes = list(
            dict.fromkeys(
                session.scalars(
                    select(IngestWarning.code).where(IngestWarning.run_id == run.id).limit(20)
                ).all()
            )
        )
        if warning_codes:
            raise OrderPlanScreeningError(
                "source_run_incomplete",
                "source run에 ingest warning이 있습니다 (" + ", ".join(warning_codes) + ")",
                request_id=request_id,
            )
        source_path = _source_directory(self.settings, run.id) / "collected-order-plans.json"
        source_raw, source_bytes = _safe_json_bytes(source_path)
        source_population = _source_population(source_raw)
        plans = {
            row.order_plan_unty_no: row
            for row in session.scalars(
                select(OrderPlan).join(OrderPlanObservation).where(OrderPlanObservation.run_id == run.id)
            ).all()
        }
        if set(plans) != {row["plan_id"] for row in source_population} or any(
            plans[row["plan_id"]].title != row["title"]
            or plans[row["plan_id"]].source_sha256 != row["source_sha256"]
            for row in source_population
        ):
            raise OrderPlanScreeningError("source_run_incomplete", "source run DB projection이 모집단과 다릅니다", request_id=request_id)
        return run, source_path, source_bytes, source_population

    def create_execution(
        self,
        session: Session,
        payload: Any,
        actor: str | None,
        actor_format: str | None = None,
        trigger: str | None = None,
    ) -> dict[str, Any]:
        request_id = payload.request_id
        claimed_name = _safe_actor(actor, actor_format, request_id)
        if trigger is not None and trigger not in EXECUTION_TRIGGERS:
            raise OrderPlanScreeningError("invalid_request", "X-BidOps-Trigger 값이 올바르지 않습니다", status_code=422, request_id=request_id)
        purpose = "gate_measurement" if trigger == "gate_measurement" else "operational"
        # The trigger header is not part of the request hash: the same
        # request_id and body replay the original response under any header.
        request_hash = _sha256_json(payload.model_dump(mode="json"))
        replay = self._idempotent(session, EXECUTION_OPERATION, request_id, request_hash)
        if replay is not None:
            return replay
        execution_dir: Path | None = None
        try:
            # Row state, digests and transport approval (503) come first for
            # every trigger; the daily switch is rechecked only after them.
            policy, stage1, stage2, policy_bytes, binding_bytes = self._policy_binding(
                session, payload.policy_version, request_id, purpose=purpose
            )
            if trigger in DAILY_TRIGGERS:
                self._require_daily_trigger(session, payload.policy_version, request_id)
            if purpose == "gate_measurement":
                self._require_measurement_run(session, policy.policy_version, payload.source_run_id, request_id)
            active = session.scalar(
                select(OrderPlanScreeningExecution).where(
                    OrderPlanScreeningExecution.status.in_(ACTIVE_STATUSES)
                ).with_for_update()
            )
            if active is not None:
                raise OrderPlanScreeningError("active_execution_exists", "다른 C-2 execution이 실행 중입니다", request_id=request_id)
            binding_document = json.loads(binding_bytes.decode("utf-8"))
            approved_inputs = self._approved_inputs(stage2, request_id)
            run, source_path, source_bytes, source_population = self.require_complete_source_run(
                session, payload.source_run_id, request_id=request_id
            )
            population = [
                {"plan_id": row["plan_id"], "title": row["title"]}
                for row in source_population
            ]
            execution_id = uuid4()
            execution_dir = execution_directory(self.settings, run.id, execution_id)
            execution_dir.parent.mkdir(parents=True, exist_ok=True)
            execution_dir.mkdir()
            _safe_copy(source_path, execution_dir / "collected-order-plans.json")
            for source, name, data in (
                (Path(self.settings.c2_policy_path or ""), "policy.json", policy_bytes),
                (Path(self.settings.c2_binding_path or ""), "binding.json", binding_bytes),
                (approved_inputs[0][0], "capabilities.json", approved_inputs[0][1]),
                (approved_inputs[1][0], "prompt.txt", approved_inputs[1][1]),
                (approved_inputs[2][0], "generation-config.json", approved_inputs[2][1]),
            ):
                target = execution_dir / name
                if source.is_file() and not source.is_symlink() and source.read_bytes() == data:
                    _safe_copy(source, target)
                else:
                    with target.open("xb") as handle:
                        handle.write(data)
            created_at = _now()
            input_document = {
                "schema_version": INPUT_SCHEMA,
                "producer": "order-plan-screening-orchestrator",
                "consumer": "order-plan-screening-worker",
                "execution_id": str(execution_id),
                "source_run_id": run.id,
                "source_artifact": {
                    "name": "collected-order-plans.json",
                    "schema_version": "bidops.collected-order-plans.v1",
                    "sha256": _sha256_bytes(source_bytes),
                },
                "population_count": len(population),
                "population_sha256": _sha256_json(population),
                "policy": {"version": policy.policy_version, "sha256": policy.policy_sha256},
                "stage1_binding": {"version": str(stage1["method"]), "sha256": str(stage1["sha256"])},
                "stage2_binding": {"version": str(binding_document.get("binding_version") or "c2-stage2"), "sha256": policy.binding_sha256},
                "items": population,
                "status": "frozen",
                "created_at": created_at.isoformat(),
            }
            input_model = OrderPlanScreeningInputArtifact.model_validate(input_document)
            input_bytes = _canonical(input_model.model_dump(mode="json"))
            with (execution_dir / ARTIFACT_FILENAMES["input"]).open("xb") as handle:
                handle.write(input_bytes)
            input_digest = _sha256_bytes(input_bytes)
            execution = OrderPlanScreeningExecution(
                execution_id=execution_id,
                request_id=request_id,
                schema_version=INPUT_ROW_SCHEMA,
                producer="screening-api",
                consumer="screening-worker-and-review-api",
                source_run_id=run.id,
                source_artifact_name="collected-order-plans.json",
                source_artifact_schema_version="bidops.collected-order-plans.v1",
                source_artifact_sha256=_sha256_bytes(source_bytes),
                input_artifact_sha256=input_digest,
                population_count=len(population),
                population_sha256=input_document["population_sha256"],
                policy_version=policy.policy_version,
                policy_sha256=policy.policy_sha256,
                binding_sha256=policy.binding_sha256,
                stage1_binding_version=str(stage1["method"]),
                stage1_binding_sha256=str(stage1["sha256"]),
                stage2_binding_version=str(policy.binding_payload_jsonb.get("binding_version") or "c2-stage2"),
                stage2_binding_sha256=policy.binding_sha256,
                status="대기",
                active_slot=None,
                requested_by=claimed_name,
                partial_artifact=False,
                queued_at=created_at,
                created_at=created_at,
                purpose=purpose,
            )
            session.add(execution)
            # The artifact row carries a real foreign key to this execution and
            # the two mappers have no relationship() to order the unit of work.
            # PostgreSQL would otherwise see the child insert first because the
            # artifact table sorts ahead of the execution table.
            session.flush()
            session.add(OrderPlanScreeningArtifact(
                execution_id=execution_id,
                kind="input",
                schema_version=INPUT_SCHEMA,
                producer="order-plan-screening-orchestrator",
                consumer="order-plan-screening-worker",
                sha256=input_digest,
                byte_count=len(input_bytes),
                object_version=input_digest,
                validation_status="valid",
                created_at=created_at,
            ))
            session.add(AuditEvent(
                id=uuid4(),
                actor_kind="human",
                claimed_name=claimed_name,
                action="c2.execution_created",
                aggregate_type="order_plan_screening_execution",
                aggregate_id=str(execution_id),
                safe_metadata={
                    "source_run_id": run.id,
                    "population_count": len(population),
                    "source_artifact_sha256": _sha256_bytes(source_bytes),
                    "input_artifact_sha256": input_digest,
                    "policy_version": policy.policy_version,
                    "policy_sha256": policy.policy_sha256,
                    "binding_sha256": policy.binding_sha256,
                    "trigger": trigger,
                    "purpose": purpose,
                },
                request_id=str(request_id),
                created_at=created_at,
            ))
            session.add(IdempotencyRecord(
                id=uuid4(),
                operation=EXECUTION_OPERATION,
                aggregate_type="order_plan_screening_execution",
                aggregate_id=str(execution_id),
                claimed_name=claimed_name,
                request_id=request_id,
                request_sha256=request_hash,
                response_status=202,
                response_snapshot=self._create_response(execution),
                created_at=created_at,
            ))
            session.flush()
            response = self._create_response(execution)
            session.commit()
            return response
        except OrderPlanScreeningError:
            session.rollback()
            if execution_dir is not None:
                shutil.rmtree(execution_dir, ignore_errors=True)
            raise
        except IntegrityError as error:
            session.rollback()
            if execution_dir is not None:
                shutil.rmtree(execution_dir, ignore_errors=True)
            replay = self._idempotent(session, EXECUTION_OPERATION, request_id, request_hash)
            if replay is not None:
                return replay
            raise OrderPlanScreeningError("processing_failed", "C-2 execution을 생성할 수 없습니다", status_code=500, request_id=request_id) from error
        except Exception as error:
            session.rollback()
            if execution_dir is not None:
                shutil.rmtree(execution_dir, ignore_errors=True)
            raise OrderPlanScreeningError("processing_failed", "C-2 execution을 생성할 수 없습니다", status_code=500, request_id=request_id) from error

    @staticmethod
    def _counts(execution: OrderPlanScreeningExecution) -> dict[str, int]:
        return {name: int(getattr(execution, name)) for name in (
            "candidate_count", "completed_count", "failure_count", "stage1_selected_count",
            "stage1_filtered_out_count", "stage1_failed_count", "stage2_relevant_count",
            "stage2_not_relevant_count", "stage2_uncertain_count", "stage2_failed_count",
            "stage2_rejected_count", "human_review_count",
        )}

    def execution_view(self, execution: OrderPlanScreeningExecution) -> dict[str, Any]:
        return {
            "execution_id": execution.execution_id,
            "request_id": execution.request_id,
            "source_run_id": execution.source_run_id,
            "policy_version": execution.policy_version,
            "status": execution.status,
            "requested_by": execution.requested_by,
            "execution_allowed": bool(self.settings.c2_execution_allowed),
            "population_count": execution.population_count,
            "population_sha256": execution.population_sha256,
            "policy_sha256": execution.policy_sha256,
            "binding_sha256": execution.binding_sha256,
            "stage1_binding_version": execution.stage1_binding_version,
            "stage1_binding_sha256": execution.stage1_binding_sha256,
            "stage2_binding_version": execution.stage2_binding_version,
            "stage2_binding_sha256": execution.stage2_binding_sha256,
            "counts": self._counts(execution),
            "purpose": execution.purpose,
            "partial_artifact": execution.partial_artifact,
            "error_code": execution.error_code,
            "queued_at": execution.queued_at,
            "started_at": execution.started_at,
            "heartbeat_at": execution.heartbeat_at,
            "finished_at": execution.finished_at,
        }

    def list_executions(self, session: Session, *, source_run_id: str | None = None, status: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        statement = select(OrderPlanScreeningExecution)
        count_statement = select(func.count()).select_from(OrderPlanScreeningExecution)
        if source_run_id:
            statement = statement.where(OrderPlanScreeningExecution.source_run_id == source_run_id)
            count_statement = count_statement.where(OrderPlanScreeningExecution.source_run_id == source_run_id)
        if status:
            statement = statement.where(OrderPlanScreeningExecution.status == status)
            count_statement = count_statement.where(OrderPlanScreeningExecution.status == status)
        rows = session.scalars(statement.order_by(OrderPlanScreeningExecution.queued_at, OrderPlanScreeningExecution.execution_id).limit(limit).offset(offset)).all()
        return {
            "schema_version": "execution-list-response.v2",
            "producer": "screening-api",
            "consumer": "human-review-client",
            "items": [self.execution_view(row) for row in rows],
            "total": int(session.scalar(count_statement) or 0),
            "limit": limit,
            "offset": offset,
        }

    def get_execution(self, session: Session, execution_id: UUID) -> OrderPlanScreeningExecution:
        execution = session.get(OrderPlanScreeningExecution, execution_id)
        if execution is None:
            raise OrderPlanScreeningError("not_found", "C-2 execution을 찾을 수 없습니다", status_code=404)
        return execution

    def execution_detail(self, session: Session, execution_id: UUID) -> dict[str, Any]:
        execution = self.get_execution(session, execution_id)
        response = self.execution_view(execution)
        artifacts = session.scalars(
            select(OrderPlanScreeningArtifact).where(OrderPlanScreeningArtifact.execution_id == execution_id).order_by(OrderPlanScreeningArtifact.created_at, OrderPlanScreeningArtifact.kind)
        ).all()
        attempts = session.scalars(
            select(OrderPlanScreeningBatchAttempt)
            .where(OrderPlanScreeningBatchAttempt.execution_id == execution_id)
            .order_by(OrderPlanScreeningBatchAttempt.sequence, OrderPlanScreeningBatchAttempt.attempt_no)
        ).all()
        response.update({
            "schema_version": "execution-detail-response.v2",
            "producer": "screening-api",
            "consumer": "human-review-client",
            "artifacts": [self.artifact_view(row) for row in artifacts],
            "attempts": [self.attempt_view(row) for row in attempts],
        })
        return response

    @staticmethod
    def attempt_view(row: OrderPlanScreeningBatchAttempt) -> dict[str, Any]:
        """Expose binding and measurements without plan IDs or response refs."""
        return {
            "attempt_id": row.attempt_id,
            "batch_id": row.batch_id,
            "sequence": row.sequence,
            "attempt_no": row.attempt_no,
            "model_name": row.model_name,
            "model_digest": row.model_digest,
            "prompt_version": row.prompt_version,
            "prompt_sha256": row.prompt_sha256,
            "company_profile_version": row.company_profile_version,
            "company_profile_sha256": row.company_profile_sha256,
            "generation_config_sha256": row.generation_config_sha256,
            "attempt_status": row.attempt_status,
            "failure_type": row.failure_type,
            "failure_code": row.failure_code,
            "input_tokens": row.input_tokens,
            "cached_input_tokens": row.cached_input_tokens,
            "output_tokens": row.output_tokens,
            "total_tokens": row.total_tokens,
            "duration_ms": row.duration_ms,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
        }

    @staticmethod
    def artifact_view(row: OrderPlanScreeningArtifact) -> dict[str, Any]:
        return {
            "kind": ARTIFACT_RESPONSE_NAMES.get(row.kind, row.kind),
            "artifact_schema_version": row.schema_version,
            "artifact_producer": row.producer,
            "artifact_consumer": row.consumer,
            "sha256": row.sha256,
            "byte_count": row.byte_count,
            "object_version": row.object_version,
            "validation_status": row.validation_status,
            "created_at": row.created_at,
        }

    def artifact_detail(self, session: Session, execution_id: UUID, kind_name: str) -> dict[str, Any]:
        kind = ARTIFACT_KINDS.get(kind_name)
        if kind is None:
            raise OrderPlanScreeningError("artifact_kind_invalid", "C-2 artifact kind이 올바르지 않습니다", status_code=422)
        self.get_execution(session, execution_id)
        row = session.scalar(
            select(OrderPlanScreeningArtifact).where(
                OrderPlanScreeningArtifact.execution_id == execution_id,
                OrderPlanScreeningArtifact.kind == kind,
            )
        )
        if row is None:
            raise OrderPlanScreeningError("artifact_not_ready", "C-2 artifact가 아직 준비되지 않았습니다", status_code=409)
        view = self.artifact_view(row)
        return {
            "schema_version": "artifact-summary-response.v1",
            "producer": "screening-api",
            "consumer": "human-review-client",
            **view,
        }

    def stop_execution(self, session: Session, execution_id: UUID, payload: Any, actor: str | None, actor_format: str | None = None) -> dict[str, Any]:
        request_id = payload.request_id
        claimed_name = _safe_actor(actor, actor_format, request_id)
        request_hash = _sha256_json(payload.model_dump(mode="json"))
        replay = self._idempotent(session, STOP_OPERATION, request_id, request_hash)
        if replay is not None:
            return replay
        execution = session.scalar(
            select(OrderPlanScreeningExecution).where(OrderPlanScreeningExecution.execution_id == execution_id).with_for_update()
        )
        if execution is None:
            raise OrderPlanScreeningError("not_found", "C-2 execution을 찾을 수 없습니다", status_code=404, request_id=request_id)
        if execution.status in TERMINAL_STATUSES:
            raise OrderPlanScreeningError("execution_not_stoppable", "terminal C-2 execution은 중지할 수 없습니다", request_id=request_id)
        prior_stop = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "c2.execution_stop_requested",
                AuditEvent.aggregate_type == "order_plan_screening_execution",
                AuditEvent.aggregate_id == str(execution_id),
            ).order_by(AuditEvent.created_at.desc())
        )
        if prior_stop is not None and prior_stop.request_id != str(request_id):
            raise OrderPlanScreeningError("idempotency_conflict", "같은 execution에 다른 stop 요청이 이미 있습니다", request_id=request_id)
        now = _now()
        if execution.status == "대기":
            execution.started_at = now
            execution.finished_at = now
            execution.status = "중단됨"
            execution.active_slot = None
            execution.partial_artifact = True
            execution.error_code = "user_requested"
            response_status = "중단됨"
        elif execution.status == "실행 중":
            execution.status = "중지 요청"
            execution.partial_artifact = True
            response_status = "중지 요청"
        else:
            raise OrderPlanScreeningError("execution_not_stoppable", "C-2 execution은 중지 요청 상태입니다", request_id=request_id)
        response = {
            "schema_version": "execution-stop-response.v1",
            "producer": "screening-api",
            "consumer": "human-review-client",
            "execution_id": str(execution_id),
            "request_id": str(request_id),
            "status": response_status,
        }
        session.add(AuditEvent(
            id=uuid4(),
            actor_kind="human",
            claimed_name=claimed_name,
            action="c2.execution_stop_requested",
            aggregate_type="order_plan_screening_execution",
            aggregate_id=str(execution_id),
            safe_metadata={"reason": payload.reason, "status": response_status},
            request_id=str(request_id),
            created_at=now,
        ))
        session.add(IdempotencyRecord(
            id=uuid4(),
            operation=STOP_OPERATION,
            aggregate_type="order_plan_screening_execution",
            aggregate_id=str(execution_id),
            claimed_name=claimed_name,
            request_id=request_id,
            request_sha256=request_hash,
            response_status=202,
            response_snapshot=response,
            created_at=now,
        ))
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            replay = self._idempotent(session, STOP_OPERATION, request_id, request_hash)
            if replay is not None:
                return replay
            raise OrderPlanScreeningError("idempotency_conflict", "C-2 stop 요청이 충돌했습니다", request_id=request_id) from error
        return response

    @staticmethod
    def _feedback_view(row: OrderPlanScreeningFeedback) -> dict[str, Any]:
        return {
            "feedback_id": row.feedback_id,
            "execution_id": row.execution_id,
            "order_plan_pk": row.order_plan_id,
            "revision": row.revision,
            "relevance": row.relevance,
            "priority": row.priority,
            "memo": row.memo,
            "claimed_name": row.claimed_name,
            "created_at": row.created_at,
        }

    def list_feedback(self, session: Session, order_plan_id: int, execution_id: UUID | None = None) -> dict[str, Any]:
        if session.get(OrderPlan, order_plan_id) is None:
            raise OrderPlanScreeningError("not_found", "발주계획을 찾을 수 없습니다", status_code=404)
        statement = select(OrderPlanScreeningFeedback).where(OrderPlanScreeningFeedback.order_plan_id == order_plan_id)
        if execution_id is not None:
            statement = statement.where(OrderPlanScreeningFeedback.execution_id == execution_id)
        rows = session.scalars(statement.order_by(OrderPlanScreeningFeedback.revision, OrderPlanScreeningFeedback.created_at)).all()
        return {
            "schema_version": "feedback-list-response.v1",
            "producer": "screening-api",
            "consumer": "order-plan-review-client",
            "items": [self._feedback_view(row) for row in rows],
        }

    def create_feedback(self, session: Session, order_plan_id: int, payload: Any, actor: str | None, actor_format: str | None = None) -> dict[str, Any]:
        request_id = payload.request_id
        claimed_name = _safe_actor(actor, actor_format, request_id)
        request_hash = _sha256_json(payload.model_dump(mode="json"))
        replay = self._idempotent(session, FEEDBACK_OPERATION, request_id, request_hash)
        if replay is not None:
            return replay
        plan = session.get(OrderPlan, order_plan_id)
        execution = session.get(OrderPlanScreeningExecution, payload.execution_id)
        if plan is None or execution is None:
            raise OrderPlanScreeningError("not_found", "발주계획 또는 execution을 찾을 수 없습니다", status_code=404, request_id=request_id)
        result = session.scalar(
            select(OrderPlanScreeningResult).where(
                OrderPlanScreeningResult.execution_id == execution.execution_id,
                OrderPlanScreeningResult.order_plan_id == order_plan_id,
            )
        )
        if result is None:
            raise OrderPlanScreeningError("not_found", "execution에 해당 발주계획 결과가 없습니다", status_code=404, request_id=request_id)
        if payload.memo is not None and not payload.memo.strip():
            raise OrderPlanScreeningError("invalid_request", "memo는 비어 있을 수 없습니다", status_code=422, request_id=request_id)
        latest = session.scalar(
            select(OrderPlanScreeningFeedback).where(
                OrderPlanScreeningFeedback.execution_id == execution.execution_id,
                OrderPlanScreeningFeedback.order_plan_id == order_plan_id,
            ).order_by(OrderPlanScreeningFeedback.revision.desc()).with_for_update()
        )
        latest_revision = latest.revision if latest is not None else 0
        if payload.expected_revision is not None and payload.expected_revision != latest_revision:
            raise OrderPlanScreeningError("feedback_conflict", "feedback revision이 변경되었습니다", request_id=request_id)
        now = _now()
        row = OrderPlanScreeningFeedback(
            feedback_id=uuid4(),
            execution_id=execution.execution_id,
            order_plan_id=order_plan_id,
            revision=latest_revision + 1,
            schema_version="bidops.order-plan-screening-feedback.v1",
            producer="human-review-api",
            consumer="postgres-review-history",
            actor_kind="human",
            claimed_name=claimed_name,
            relevance=payload.relevance,
            priority=payload.priority,
            memo=payload.memo,
            supersedes_feedback_id=latest.feedback_id if latest is not None else None,
            created_at=now,
        )
        session.add(row)
        response = {
            "schema_version": "feedback-create-response.v1",
            "producer": "human-review-api",
            "consumer": "postgres-history",
            "feedback_id": str(row.feedback_id),
            "execution_id": str(row.execution_id),
            "order_plan_pk": row.order_plan_id,
            "revision": row.revision,
            "relevance": row.relevance,
            "priority": row.priority,
            "memo": row.memo,
            "claimed_name": row.claimed_name,
            "created_at": row.created_at.isoformat(),
        }
        session.add(AuditEvent(
            id=uuid4(),
            actor_kind="human",
            claimed_name=claimed_name,
            action="c2.feedback_created",
            aggregate_type="order_plan_screening_feedback",
            aggregate_id=str(row.feedback_id),
            safe_metadata={"execution_id": str(row.execution_id), "order_plan_pk": row.order_plan_id, "revision": row.revision, "relevance": row.relevance},
            request_id=str(request_id),
            created_at=now,
        ))
        session.add(IdempotencyRecord(
            id=uuid4(),
            operation=FEEDBACK_OPERATION,
            aggregate_type="order_plan_screening_feedback",
            aggregate_id=f"{execution.execution_id}:{order_plan_id}",
            claimed_name=claimed_name,
            request_id=request_id,
            request_sha256=request_hash,
            response_status=201,
            response_snapshot=response,
            created_at=now,
        ))
        try:
            session.flush()
            session.commit()
        except IntegrityError as error:
            session.rollback()
            replay = self._idempotent(session, FEEDBACK_OPERATION, request_id, request_hash)
            if replay is not None:
                return replay
            raise OrderPlanScreeningError("feedback_conflict", "feedback revision이 충돌했습니다", request_id=request_id) from error
        return response

    @staticmethod
    def _latest_completed_execution(session: Session, source_run_id: str | None = None) -> UUID | None:
        statement = select(OrderPlanScreeningExecution.execution_id).where(
            OrderPlanScreeningExecution.status.in_({"성공", "부분 성공"}),
        )
        if source_run_id is not None:
            statement = statement.where(OrderPlanScreeningExecution.source_run_id == source_run_id)
        return session.scalar(
            statement.order_by(
                OrderPlanScreeningExecution.finished_at.desc(),
                OrderPlanScreeningExecution.queued_at.desc(),
                OrderPlanScreeningExecution.execution_id.desc(),
            ).limit(1)
        )

    @staticmethod
    def _latest_feedback(session: Session, order_plan_id: int, execution_id: UUID | None = None) -> OrderPlanScreeningFeedback | None:
        statement = select(OrderPlanScreeningFeedback).where(OrderPlanScreeningFeedback.order_plan_id == order_plan_id)
        if execution_id is not None:
            statement = statement.where(OrderPlanScreeningFeedback.execution_id == execution_id)
        return session.scalar(statement.order_by(
                OrderPlanScreeningFeedback.created_at.desc(), OrderPlanScreeningFeedback.revision.desc()
            ))

    @staticmethod
    def _feedback_summary(row: OrderPlanScreeningFeedback | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "revision": row.revision,
            "relevance": row.relevance,
            "priority": row.priority,
            "memo": row.memo,
            "claimed_name": row.claimed_name,
            "created_at": row.created_at,
        }

    @staticmethod
    def _tracking_owners():
        """소유권 조건은 lifecycle 정본을 사용하며 확정 owner만 반환한다."""
        return select(
            OpportunityLink.order_plan_id,
            Opportunity.id.label("opportunity_id"),
        ).join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id).where(
            OpportunityLink.stage == "order_plan",
            OpportunityLink.order_plan_id.is_not(None),
            authoritative_link_predicate(OpportunityLink),
            active_opportunity_predicate(Opportunity),
        ).subquery()

    @staticmethod
    def _tracking_summary(opportunity: Opportunity | None) -> dict[str, Any] | None:
        if opportunity is None:
            return None
        return {
            "opportunity_id": opportunity.id,
            "tracking_status": opportunity.tracking_status,
            "tracking_reason": opportunity.tracking_reason,
            "tracking_selected_by": opportunity.tracking_selected_by,
            "tracking_selected_at": opportunity.tracking_selected_at,
        }

    def _order_plan_item(
        self,
        plan: OrderPlan,
        observation: OrderPlanObservation,
        result: OrderPlanScreeningResult | None,
        feedback: OrderPlanScreeningFeedback | None,
        opportunity: Opportunity | None,
        first_observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        return {
            "order_plan_pk": plan.id,
            "order_plan_unty_no": plan.order_plan_unty_no,
            "source_url": plan.source_url,
            "title": plan.title,
            "agency_name": plan.agency_name,
            "business_division": plan.business_division,
            "budget_amount": float(plan.budget_amount) if plan.budget_amount is not None else None,
            "planned_order_year": plan.planned_order_year,
            "planned_order_month": plan.planned_order_month,
            # 누적 행이 이미 들고 있는 값이라 쿼리가 늘지 않는다. `notice_posted`는 원문 `Y`/`N`
            # 문자열이며 없음(`null`)을 `N`이나 False로 바꾸지 않는다.
            "contract_method": plan.contract_method,
            "notice_posted": plan.notice_posted,
            "source_run_id": result.source_run_id if result is not None else observation.run_id,
            "observed_at": observation.observed_at,
            "stage1_status": result.stage1_status if result is not None else None,
            "stage1_rank": result.stage1_rank if result is not None else None,
            "stage1_score": float(result.stage1_score) if result is not None and result.stage1_score is not None else None,
            "nearest_capability": result.nearest_capability if result is not None else None,
            "stage2_status": result.stage2_status if result is not None else None,
            "qwen_relevance": result.qwen_relevance if result is not None else None,
            "qwen_score": float(result.qwen_score) if result is not None and result.qwen_score is not None else None,
            "qwen_reason": result.qwen_reason if result is not None else None,
            "human_feedback": self._feedback_summary(feedback),
            "tracking": self._tracking_summary(opportunity),
            "execution_id": result.execution_id if result is not None else None,
            "policy_version": result.policy_version if result is not None else None,
            "first_observed_at": first_observed_at,
        }

    @staticmethod
    def _cumulative_executions():
        """누적 범위: 활성화된 적 있는 policy의 운영 목적 완료 실행 전부(현재 active 여부는 묻지 않는다)."""
        return select(OrderPlanScreeningExecution).join(
            OrderPlanScreeningPolicy,
            OrderPlanScreeningPolicy.policy_version == OrderPlanScreeningExecution.policy_version,
        ).where(
            OrderPlanScreeningPolicy.activated_at.is_not(None),
            OrderPlanScreeningExecution.purpose == "operational",
            OrderPlanScreeningExecution.status.in_({"성공", "부분 성공"}),
        )

    @staticmethod
    def _ranked_results(executions: Any):
        """범위 실행(`executions` subquery)의 결과에 발주계획별 최신 순위(`position`)를 붙인다.

        최신 = `finished_at` 내림, 같으면 `execution_id` 내림. 목록과 브리핑 후보가 같은 규칙을 쓴다.
        """

        return select(
            OrderPlanScreeningResult,
            func.row_number().over(
                partition_by=OrderPlanScreeningResult.order_plan_id,
                order_by=(executions.c.finished_at.desc(), executions.c.execution_id.desc()),
            ).label("position"),
        ).join(executions, executions.c.execution_id == OrderPlanScreeningResult.execution_id)

    def briefing_relevant_order_plan_ids(
        self, session: Session, since: datetime, until: datetime
    ) -> list[int]:
        """RL-01 브리핑 후보: 누적 범위 최신 결과가 `relevant`이고 창 안에 처음 관측된 발주계획.

        창은 `OrderPlan.first_discovered_at ∈ (since, until]`이다. 반복 발주처 규칙과 소유
        사업기회 확인은 lifecycle 브리핑 규칙이 한다. 조회 1회.
        """

        if since.tzinfo is None or until.tzinfo is None:
            raise ValueError("briefing window bounds must be timezone-aware")
        executions = self._cumulative_executions().subquery()
        ranked = self._ranked_results(executions).subquery()
        statement = (
            select(OrderPlan.id)
            .join(ranked, and_(ranked.c.order_plan_id == OrderPlan.id, ranked.c.position == 1))
            .where(
                ranked.c.qwen_relevance == "relevant",
                OrderPlan.first_discovered_at.is_not(None),
                OrderPlan.first_discovered_at > since,
                OrderPlan.first_discovered_at <= until,
            )
            .order_by(OrderPlan.id)
        )
        return [int(value) for value in session.scalars(statement)]

    def has_cumulative_execution(self, session: Session) -> bool:
        statement = self._cumulative_executions().with_only_columns(OrderPlanScreeningExecution.execution_id)
        return session.scalar(statement.limit(1)) is not None

    @staticmethod
    def _seoul_day_start(value: date | str) -> datetime:
        """KST 일자 00:00을 DB 비교용 UTC 시각으로 바꾼다."""

        if isinstance(value, datetime):
            raise OrderPlanScreeningError(
                "invalid_request", "first_observed_from은 날짜여야 합니다", status_code=422
            )
        if isinstance(value, str):
            try:
                value = date.fromisoformat(value.strip())
            except ValueError as error:
                raise OrderPlanScreeningError(
                    "invalid_request", "first_observed_from이 올바르지 않습니다", status_code=422
                ) from error
        return datetime.combine(value, time.min, tzinfo=_SEOUL).astimezone(UTC)

    @staticmethod
    def _filter_values(value: str | None, allowed: set[str]) -> set[str] | None:
        if value is None:
            return None
        values = {part.strip() for part in value.split(",")}
        if not values or not values <= allowed:
            raise OrderPlanScreeningError("invalid_request", "필터 값이 올바르지 않습니다", status_code=422)
        return values

    def list_order_plans(
        self,
        session: Session,
        *,
        source_run_id: str | None = None,
        stage1_status: str | None = None,
        stage2_status: str | None = None,
        qwen_relevance: str | None = None,
        human_relevance: str | None = None,
        tracking_status: str | None = None,
        first_observed_from: date | str | None = None,
        issue: bool = False,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        filters = (
            ("stage1_status", self._filter_values(stage1_status, {"selected", "filtered_out", "failed", "rejected", "missing"})),
            ("stage2_status", self._filter_values(stage2_status, {"not_attempted", "success", "failed", "rejected", "unknown", "missing"})),
            ("qwen_relevance", self._filter_values(qwen_relevance, {"relevant", "not_relevant", "uncertain", "missing"})),
            ("human_relevance", self._filter_values(human_relevance, {"relevant", "not_relevant", "uncertain", "missing"})),
            ("tracking_status", self._filter_values(tracking_status, {"미선택", "계속 추적", "보류", "종료"})),
        )
        execution: OrderPlanScreeningExecution | None = None
        if source_run_id is not None:
            # 회차 모드(감사용): 그 회차의 최신 완료 실행 하나. policy·purpose를 묻지 않는다.
            execution_id = self._latest_completed_execution(session, source_run_id)
            execution = session.get(OrderPlanScreeningExecution, execution_id) if execution_id is not None else None

        observations = select(
            OrderPlanObservation,
            func.row_number().over(
                partition_by=OrderPlanObservation.order_plan_id,
                order_by=(OrderPlanObservation.observed_at.desc(), OrderPlanObservation.id.desc()),
            ).label("position"),
        )
        if source_run_id is not None:
            observations = observations.where(OrderPlanObservation.run_id == source_run_id)
        observation_rows = observations.subquery()
        observation = aliased(OrderPlanObservation, observation_rows)
        first_observations = select(
            OrderPlanObservation.order_plan_id,
            func.min(OrderPlanObservation.observed_at).label("first_observed_at"),
        ).group_by(OrderPlanObservation.order_plan_id).subquery()
        # 결과는 발주계획마다 범위 안 최신 1건이다. 누적 모드는 누적 범위 실행 전부, 회차 모드는 그 실행 하나.
        executions = (
            self._cumulative_executions()
            if source_run_id is None
            else select(OrderPlanScreeningExecution).where(
                OrderPlanScreeningExecution.execution_id == (execution.execution_id if execution is not None else None)
            )
        ).subquery()
        result_rows = self._ranked_results(executions).subquery()
        result = aliased(OrderPlanScreeningResult, result_rows)
        # feedback은 두 모드 모두 발주계획마다 최신 1건이다. 실행과 무관하다.
        feedback_rows = select(
            OrderPlanScreeningFeedback,
            func.row_number().over(
                partition_by=OrderPlanScreeningFeedback.order_plan_id,
                order_by=(OrderPlanScreeningFeedback.created_at.desc(), OrderPlanScreeningFeedback.revision.desc()),
            ).label("position"),
        ).subquery()
        feedback = aliased(OrderPlanScreeningFeedback, feedback_rows)
        owners = self._tracking_owners()
        statement = select(
            OrderPlan, observation, result, feedback, Opportunity, first_observations.c.first_observed_at,
        ).join(
            observation,
            and_(observation.order_plan_id == OrderPlan.id, observation_rows.c.position == 1),
        ).join(
            first_observations, first_observations.c.order_plan_id == OrderPlan.id,
        ).outerjoin(
            result,
            and_(result.order_plan_id == OrderPlan.id, result_rows.c.position == 1),
        ).outerjoin(
            feedback,
            and_(feedback.order_plan_id == OrderPlan.id, feedback_rows.c.position == 1),
        ).outerjoin(owners, owners.c.order_plan_id == OrderPlan.id).outerjoin(
            Opportunity, Opportunity.id == owners.c.opportunity_id,
        )
        columns = {
            "stage1_status": result.stage1_status,
            "stage2_status": result.stage2_status,
            "qwen_relevance": result.qwen_relevance,
            "human_relevance": feedback.relevance,
            "tracking_status": Opportunity.tracking_status,
        }
        for name, values in filters:
            if values is None:
                continue
            column = columns[name]
            predicate = column.in_(sorted(values - {"missing"}))
            if "missing" in values:
                # missing은 검색 전용 NULL 투영값이다. 저장 상태를 새로 만들지 않는다.
                missing_column = feedback.feedback_id if name == "human_relevance" else column
                predicate = or_(predicate, missing_column.is_(None))
            statement = statement.where(predicate)
        if first_observed_from is not None:
            # "처음 관측"은 회차와 무관한 관측 행의 최소 시각이다. 회차 모드에서도
            # 같은 값을 쓴다 — `first_observations`는 회차로 좁히지 않는다.
            statement = statement.where(
                first_observations.c.first_observed_at >= self._seoul_day_start(first_observed_from)
            )
        if issue:
            statement = statement.where(or_(
                result.stage1_status.in_({"failed", "rejected"}),
                result.stage2_status.in_({"failed", "rejected"}),
            ))
        from ...core.search import search_key, search_sql_match

        query = search_key(q)
        if query:
            statement = statement.where(or_(
                search_sql_match(OrderPlan.title, q),
                search_sql_match(OrderPlan.agency_name, q),
                search_sql_match(OrderPlan.order_plan_unty_no, q),
            ))
        total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
        rows = session.execute(statement.order_by(OrderPlan.id.asc()).limit(limit).offset(offset)).all()
        scope: dict[str, Any] | None
        if source_run_id is None:
            # 누적 범위에 실행이 실제로 있는 policy 버전만 말한다. 활성화 이력만 있고 운영 완료
            # 실행이 0건인 policy는 빠지므로 빈 목록과 `has_cumulative_execution()`이 함께 간다.
            # 조건은 복제하지 않고 범위 정본(`_cumulative_executions`)에서 파생시킨다.
            versions = self._cumulative_executions().with_only_columns(
                OrderPlanScreeningExecution.policy_version, OrderPlanScreeningPolicy.activated_at,
            ).distinct().order_by(
                OrderPlanScreeningPolicy.activated_at.asc(), OrderPlanScreeningExecution.policy_version.asc(),
            )
            scope = {
                "mode": "cumulative",
                "policy_versions": [row.policy_version for row in session.execute(versions)],
                # 활성화된 적 있는 policy 전부. 화면은 이 목록으로 "어떤 실행이 이 범위의 것인지"를
                # 가른다 — 아직 결과가 없는 대기·실행 중·실패도 범위 안이고, 한 번도 활성화되지
                # 않은 policy의 실행(참조 실행)은 밖이다. `policy_versions`는 이것의 부분집합이다.
                "activated_policy_versions": list(session.scalars(
                    select(OrderPlanScreeningPolicy.policy_version).where(
                        OrderPlanScreeningPolicy.activated_at.is_not(None),
                    ).order_by(OrderPlanScreeningPolicy.activated_at.asc(), OrderPlanScreeningPolicy.policy_version.asc())
                )),
            }
        elif execution is not None:
            scope = {
                "mode": "run",
                "execution_id": execution.execution_id,
                "source_run_id": execution.source_run_id,
                "status": execution.status,
                "finished_at": execution.finished_at,
                "policy_version": execution.policy_version,
                "purpose": execution.purpose,
            }
        else:
            scope = None
        return {
            "schema_version": "order-plan-list-response.v5",
            "producer": "order-plan-review-api",
            "consumer": "order-plan-review-client",
            "scope": scope,
            "items": [self._order_plan_item(*row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def _history_items(self, session: Session, order_plan_id: int) -> list[dict[str, Any]]:
        rows = session.scalars(
            select(OrderPlanScreeningResult).where(OrderPlanScreeningResult.order_plan_id == order_plan_id).order_by(
                OrderPlanScreeningResult.created_at.desc(), OrderPlanScreeningResult.id.desc()
            )
        ).all()
        history: list[dict[str, Any]] = []
        for result in rows:
            execution = session.get(OrderPlanScreeningExecution, result.execution_id)
            if execution is None:
                continue
            feedback_count = int(session.scalar(
                select(func.count()).select_from(OrderPlanScreeningFeedback).where(
                    OrderPlanScreeningFeedback.execution_id == result.execution_id,
                    OrderPlanScreeningFeedback.order_plan_id == order_plan_id,
                )
            ) or 0)
            history.append({
                "execution_id": execution.execution_id,
                "source_run_id": result.source_run_id,
                "policy_version": result.policy_version,
                "policy_sha256": result.policy_sha256,
                "binding_sha256": result.binding_sha256,
                "execution_status": execution.status,
                "stage1_status": result.stage1_status,
                "stage1_rank": result.stage1_rank,
                "stage1_score": float(result.stage1_score) if result.stage1_score is not None else None,
                "nearest_capability": result.nearest_capability,
                "batch_id": result.batch_id,
                "attempt_no": result.attempt_no,
                "stage2_status": result.stage2_status,
                "qwen_relevance": result.qwen_relevance,
                "qwen_score": float(result.qwen_score) if result.qwen_score is not None else None,
                "qwen_reason": result.qwen_reason,
                "feedback_revision_count": feedback_count,
                # 위에서 이미 읽은 실행 행에서 꺼내므로 쿼리가 더 늘지 않는다. 값은 그대로
                # 내고 서버가 대표 시각을 고르거나 목적을 다시 해석하지 않는다.
                "execution_purpose": execution.purpose,
                "execution_started_at": execution.started_at,
                "execution_finished_at": execution.finished_at,
            })
        return history

    def order_plan_detail(self, session: Session, order_plan_id: int) -> dict[str, Any]:
        plan = session.get(OrderPlan, order_plan_id)
        if plan is None:
            raise OrderPlanScreeningError("not_found", "발주계획을 찾을 수 없습니다", status_code=404)
        observations = sorted(plan.observations, key=lambda row: (row.observed_at, row.id))
        owners = self._tracking_owners()
        opportunity = session.scalar(select(Opportunity).join(
            owners, owners.c.opportunity_id == Opportunity.id,
        ).where(owners.c.order_plan_id == plan.id))
        return {
            "schema_version": "order-plan-detail-response.v4",
            "producer": "screening-api",
            "consumer": "order-plan-review-client",
            "order_plan_pk": plan.id,
            "order_plan_unty_no": plan.order_plan_unty_no,
            "source_url": plan.source_url,
            "title": plan.title,
            "agency_name": plan.agency_name,
            "business_division": plan.business_division,
            "business_division_code": plan.business_division_code,
            "service_type": plan.service_type,
            "budget_amount": float(plan.budget_amount) if plan.budget_amount is not None else None,
            "planned_order_year": plan.planned_order_year,
            "planned_order_month": plan.planned_order_month,
            # 이미 읽은 `plan` 행의 열이라 추가 쿼리가 없다. `bid_ntice_no_list`는 수집 원문
            # 문자열 그대로이고 서버가 목록으로 쪼개지 않는다.
            "supervising_agency_name": plan.supervising_agency_name,
            "procurement_method": plan.procurement_method,
            "contract_method": plan.contract_method,
            "notice_posted": plan.notice_posted,
            "bid_ntice_no_list": plan.bid_ntice_no_list,
            "published_at": plan.published_at,
            "observations": [
                {"source_run_id": row.run_id, "observed_at": row.observed_at, "source_sha256": row.source_sha256}
                for row in observations
            ],
            "screening_history": self._history_items(session, plan.id),
            "tracking": self._tracking_summary(opportunity),
            "latest_human_feedback": self._feedback_summary(self._latest_feedback(session, plan.id)),
        }

    def screening_history(self, session: Session, order_plan_id: int) -> dict[str, Any]:
        if session.get(OrderPlan, order_plan_id) is None:
            raise OrderPlanScreeningError("not_found", "발주계획을 찾을 수 없습니다", status_code=404)
        return {
            "schema_version": "order-plan-detail-response.v5",
            "producer": "screening-api",
            "consumer": "order-plan-review-client",
            "order_plan_pk": order_plan_id,
            "items": self._history_items(session, order_plan_id),
        }
