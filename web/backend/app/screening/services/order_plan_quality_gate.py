"""C-2 quality gate record: gate 생성, evaluation 기록, 목록 조회.

wire 정본은 ``docs/contracts.md`` "C-2 일일 운영 계약 > 품질 게이트 REST"다.

코드는 **채점하지 않는다.** 사람이 만든 gate artifact의 pass별 측정값을 기록하고
(1) 측정 실행과 gate의 연결, (2) 판정 규칙, (3) 두 pass 중 나쁜 쪽 값만 계산한다.
판정은 이 service가 한다 — PostgreSQL의 "임계값 NULL이면 ``미측정``만" trigger는
마지막 방어이고, SQLite 격리 테스트에는 없다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.models import AuditEvent, IdempotencyRecord
from ...lifecycle.models import Run
from ..models import (
    OrderPlanScreeningExecution,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningQualityEvaluation,
    OrderPlanScreeningQualityGate,
)
from ..schemas.order_plan_quality_gates import (
    GateListItem,
    QualityEvaluationCreateRequest,
    QualityEvaluationCreateResponse,
    QualityGateCreateRequest,
    QualityGateCreateResponse,
    QualityGateListResponse,
)
from .order_plan_screening import (
    OrderPlanScreeningError,
    OrderPlanScreeningService,
    _now,
    _safe_actor,
    _sha256_json,
)


GATE_CREATE_OPERATION = "c2_quality_gate_create"
EVALUATION_CREATE_OPERATION = "c2_quality_evaluation_create"
PRODUCER = "quality-gate-api"
CONSUMER = "human-review-client"
REQUIRED_PASS_COUNT = 2
SCORING_UNIT = "per_published_day"
PASS_KEYS = ("pass_1", "pass_2")

# 판정 reason code (계약 표 그대로).
THRESHOLDS_UNDECIDED = "thresholds_undecided"
PASS_COUNT_BELOW_REQUIRED = "pass_count_below_required"
MEASUREMENT_MISSING = "measurement_missing"
PASS_EXECUTION_NOT_SUCCESS = "pass_execution_not_success"
NOT_PRODUCT_PIPELINE_RESULT = "not_product_pipeline_result"
THRESHOLD_NOT_MET = "threshold_not_met:"

# 지표 → (gate 임계값 열, 좋은 방향). "min" 지표는 임계값 이상이어야 충족하고
# 두 pass 중 작은 값이 나쁜 쪽이다. "max" 지표는 그 반대다.
METRICS: tuple[tuple[str, str, str], ...] = (
    ("recall_pct", "threshold_recall_pct", "min"),
    ("precision_pct", "threshold_precision_pct", "min"),
    ("important_missed", "threshold_important_missed_max", "max"),
    ("review_load", "threshold_review_load_max", "max"),
)


def _invalid(message: str, request_id: UUID | None) -> OrderPlanScreeningError:
    return OrderPlanScreeningError("invalid_request", message, status_code=422, request_id=request_id)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    # float는 문자열을 거쳐 요청에 적힌 자릿수 그대로 비교한다.
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _metrics_payload(metrics: Any) -> dict[str, Any]:
    return {name: getattr(metrics, name) for name, _column, _direction in METRICS}


def worst_values(passes: Sequence[Mapping[str, Any]]) -> dict[str, Decimal | None]:
    """두 pass 중 나쁜 쪽 값. 있는 pass 중 하나라도 null이면 그 지표는 null이다."""

    worst: dict[str, Decimal | None] = {}
    for name, _column, direction in METRICS:
        values = [_decimal(item.get(name)) for item in passes]
        if not values or any(value is None for value in values):
            worst[name] = None
        else:
            worst[name] = min(values) if direction == "min" else max(values)  # type: ignore[type-var]
    return worst


def judge(
    gate: OrderPlanScreeningQualityGate,
    passes: Sequence[Mapping[str, Any]],
    execution_statuses: Iterable[str],
) -> tuple[str, list[str]]:
    """계약의 판정 규칙 표. 위에서부터 첫 일치이고 계산 불가를 통과로 바꾸지 않는다."""

    thresholds = {name: _decimal(getattr(gate, column)) for name, column, _direction in METRICS}
    if any(value is None for value in thresholds.values()):
        return "미측정", [THRESHOLDS_UNDECIDED]

    hold: list[str] = []
    if len(passes) < REQUIRED_PASS_COUNT:
        hold.append(PASS_COUNT_BELOW_REQUIRED)
    if any(item.get(name) is None for item in passes for name, _column, _direction in METRICS):
        hold.append(MEASUREMENT_MISSING)
    if any(status != "성공" for status in execution_statuses):
        hold.append(PASS_EXECUTION_NOT_SUCCESS)
    if hold:
        return "보류", hold

    failed: list[str] = []
    for name, _column, direction in METRICS:
        threshold = thresholds[name]
        for item in passes:
            value = _decimal(item[name])
            met = value >= threshold if direction == "min" else value <= threshold  # type: ignore[operator]
            if not met:
                failed.append(THRESHOLD_NOT_MET + name)
                break
    if failed:
        return "미달", failed
    return "통과", []


def _merge_reasons(server: Sequence[str], human: Sequence[str]) -> list[str]:
    merged: list[str] = []
    for reason in (*server, *human):
        if reason not in merged:
            merged.append(reason)
    return merged


class OrderPlanQualityGateService:
    """Own the C-2 gate/evaluation append-only record and its read view."""

    def __init__(self, settings: Settings | None = None) -> None:
        # idempotency replay는 기존 C-2 service의 규칙을 그대로 쓴다.
        self._screening = OrderPlanScreeningService(settings)

    # --- views ---------------------------------------------------------------

    @staticmethod
    def evaluation_view(row: OrderPlanScreeningQualityEvaluation) -> dict[str, Any]:
        metrics = dict(row.metrics_json)
        pass_ids = dict(row.pass_execution_ids_json)
        return {
            "evaluation_id": row.evaluation_id,
            "gate_id": row.gate_id,
            "revision": row.revision,
            "result_status": row.result_status,
            "pass_execution_ids": {key: pass_ids.get(key) for key in PASS_KEYS},
            "measured_recall_pct": _number(_decimal(row.measured_recall_pct)),
            "measured_precision_pct": _number(_decimal(row.measured_precision_pct)),
            "measured_important_missed": row.measured_important_missed,
            "measured_review_load": row.measured_review_load,
            "metrics": {
                "pass_1": metrics.get("pass_1"),
                "pass_2": metrics.get("pass_2"),
                "agreement_pct": metrics.get("agreement_pct"),
                "reference_full_window": metrics.get("reference_full_window"),
            },
            "reasons": list(row.reasons_json),
            "artifact_sha256": row.artifact_sha256,
            "evaluated_by": row.evaluated_by,
            "evaluated_at": row.evaluated_at,
        }

    def gate_view(
        self,
        gate: OrderPlanScreeningQualityGate,
        latest: OrderPlanScreeningQualityEvaluation | None,
    ) -> dict[str, Any]:
        return {
            "gate_id": gate.gate_id,
            "policy_version": gate.policy_version,
            "policy_sha256": gate.policy_sha256,
            "binding_sha256": gate.binding_sha256,
            "gold_manifest_sha256": gate.gold_manifest_sha256,
            "gold_artifact_sha256": gate.gold_artifact_sha256,
            "gold_status": gate.gold_status,
            "scoring_input_sha256": gate.scoring_input_sha256,
            "evaluation_basis": gate.evaluation_basis,
            "scoring_unit": gate.scoring_unit,
            "measurement_run_ids": list(gate.measurement_run_ids_json),
            "required_pass_count": gate.required_pass_count,
            "thresholds": {
                "recall_pct": _number(_decimal(gate.threshold_recall_pct)),
                "precision_pct": _number(_decimal(gate.threshold_precision_pct)),
                "important_missed_max": gate.threshold_important_missed_max,
                "review_load_max": gate.threshold_review_load_max,
            },
            "created_by": gate.created_by,
            "created_at": gate.created_at,
            "latest_evaluation": self.evaluation_view(latest) if latest is not None else None,
        }

    # --- gate ----------------------------------------------------------------

    def create_gate(
        self,
        session: Session,
        payload: QualityGateCreateRequest,
        actor: str | None,
        actor_format: str | None = None,
    ) -> dict[str, Any]:
        request_id = payload.request_id
        claimed_name = _safe_actor(actor, actor_format, request_id)
        request_hash = _sha256_json(payload.model_dump(mode="json"))
        replay = self._screening._idempotent(session, GATE_CREATE_OPERATION, request_id, request_hash)
        if replay is not None:
            return replay

        policy = session.scalar(
            select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == payload.policy_version)
        )
        if policy is None:
            raise OrderPlanScreeningError("not_found", "C-2 policy를 찾을 수 없습니다", status_code=404, request_id=request_id)
        if policy.policy_sha256 != payload.policy_sha256 or policy.binding_sha256 != payload.binding_sha256:
            raise OrderPlanScreeningError("immutable_conflict", "요청 digest가 policy 행과 다릅니다", request_id=request_id)

        run_ids = list(payload.measurement_run_ids)
        if len(set(run_ids)) != len(run_ids):
            raise _invalid("측정 회차가 중복되었습니다", request_id)
        found = set(session.scalars(select(Run.id).where(Run.id.in_(run_ids))).all())
        if found != set(run_ids):
            raise _invalid("없는 측정 회차가 있습니다", request_id)
        for value in (payload.threshold_recall_pct, payload.threshold_precision_pct):
            if value is not None and not 0 <= value <= 100:
                raise _invalid("임계값이 범위를 벗어났습니다", request_id)
        for value in (payload.threshold_important_missed_max, payload.threshold_review_load_max):
            if value is not None and value < 0:
                raise _invalid("임계값이 범위를 벗어났습니다", request_id)

        now = _now()
        gate = OrderPlanScreeningQualityGate(
            gate_id="c2gate-" + uuid4().hex,
            policy_version=policy.policy_version,
            policy_sha256=payload.policy_sha256,
            binding_sha256=payload.binding_sha256,
            gold_manifest_sha256=payload.gold_manifest_sha256,
            gold_artifact_sha256=payload.gold_artifact_sha256,
            gold_status=payload.gold_status,
            scoring_input_sha256=payload.scoring_input_sha256,
            evaluation_basis=payload.evaluation_basis,
            scoring_unit=SCORING_UNIT,
            measurement_run_ids_json=run_ids,
            required_pass_count=REQUIRED_PASS_COUNT,
            threshold_recall_pct=_decimal(payload.threshold_recall_pct),
            threshold_precision_pct=_decimal(payload.threshold_precision_pct),
            threshold_important_missed_max=payload.threshold_important_missed_max,
            threshold_review_load_max=payload.threshold_review_load_max,
            created_by=claimed_name,
            created_at=now,
        )
        session.add(gate)
        response = QualityGateCreateResponse.model_validate({
            "schema_version": "order-plan-quality-gate-response.v1",
            "producer": PRODUCER,
            "consumer": CONSUMER,
            "request_id": request_id,
            **self.gate_view(gate, None),
        }).model_dump(mode="json")
        session.add(AuditEvent(
            id=uuid4(),
            actor_kind="human",
            claimed_name=claimed_name,
            action="c2.quality_gate_created",
            aggregate_type="order_plan_screening_quality_gate",
            aggregate_id=gate.gate_id,
            safe_metadata={
                "gate_id": gate.gate_id,
                "policy_version": gate.policy_version,
                "evaluation_basis": gate.evaluation_basis,
                "measurement_run_count": len(run_ids),
                "thresholds_decided": all(
                    getattr(gate, column) is not None for _name, column, _direction in METRICS
                ),
            },
            request_id=str(request_id),
            created_at=now,
        ))
        session.add(IdempotencyRecord(
            id=uuid4(),
            operation=GATE_CREATE_OPERATION,
            aggregate_type="order_plan_screening_quality_gate",
            aggregate_id=gate.gate_id,
            claimed_name=claimed_name,
            request_id=request_id,
            request_sha256=request_hash,
            response_status=201,
            response_snapshot=response,
            created_at=now,
        ))
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            replay = self._screening._idempotent(session, GATE_CREATE_OPERATION, request_id, request_hash)
            if replay is not None:
                return replay
            raise OrderPlanScreeningError("idempotency_conflict", "C-2 gate 요청이 충돌했습니다", request_id=request_id) from error
        return response

    def list_gates(self, session: Session, policy_version: str | None) -> dict[str, Any]:
        if policy_version is None or not policy_version.strip():
            raise _invalid("policy_version이 필요합니다", None)
        exists = session.scalar(
            select(OrderPlanScreeningPolicy.policy_version).where(OrderPlanScreeningPolicy.policy_version == policy_version)
        )
        if exists is None:
            raise OrderPlanScreeningError("not_found", "C-2 policy를 찾을 수 없습니다", status_code=404)

        gates = session.scalars(
            select(OrderPlanScreeningQualityGate)
            .where(OrderPlanScreeningQualityGate.policy_version == policy_version)
            .order_by(OrderPlanScreeningQualityGate.created_at.desc(), OrderPlanScreeningQualityGate.gate_id.desc())
        ).all()
        gate_ids = [gate.gate_id for gate in gates]
        latest_by_gate: dict[str, OrderPlanScreeningQualityEvaluation] = {}
        if gate_ids:
            latest_revision = (
                select(
                    OrderPlanScreeningQualityEvaluation.gate_id.label("gate_id"),
                    func.max(OrderPlanScreeningQualityEvaluation.revision).label("revision"),
                )
                .where(OrderPlanScreeningQualityEvaluation.gate_id.in_(gate_ids))
                .group_by(OrderPlanScreeningQualityEvaluation.gate_id)
                .subquery()
            )
            for row in session.scalars(
                select(OrderPlanScreeningQualityEvaluation).join(
                    latest_revision,
                    (OrderPlanScreeningQualityEvaluation.gate_id == latest_revision.c.gate_id)
                    & (OrderPlanScreeningQualityEvaluation.revision == latest_revision.c.revision),
                )
            ).all():
                latest_by_gate[row.gate_id] = row

        # 측정 실행은 policy 단위로 한 번에 읽고 gate마다 회차로 거른다(상수 회 조회).
        executions = session.scalars(
            select(OrderPlanScreeningExecution)
            .where(
                OrderPlanScreeningExecution.policy_version == policy_version,
                OrderPlanScreeningExecution.purpose == "gate_measurement",
            )
            .order_by(OrderPlanScreeningExecution.queued_at, OrderPlanScreeningExecution.execution_id)
        ).all() if gates else []

        items = []
        for gate in gates:
            run_ids = set(gate.measurement_run_ids_json)
            items.append(GateListItem.model_validate({
                **self.gate_view(gate, latest_by_gate.get(gate.gate_id)),
                "measurement_executions": [
                    {
                        "execution_id": execution.execution_id,
                        "source_run_id": execution.source_run_id,
                        "status": execution.status,
                        "queued_at": execution.queued_at,
                        "finished_at": execution.finished_at,
                    }
                    for execution in executions
                    if execution.source_run_id in run_ids
                ],
            }))
        return QualityGateListResponse(
            schema_version="order-plan-quality-gate-list-response.v1",
            producer=PRODUCER,
            consumer=CONSUMER,
            policy_version=policy_version,
            items=items,
        ).model_dump(mode="json")

    # --- evaluation ----------------------------------------------------------

    def _linked_statuses(
        self,
        session: Session,
        gate: OrderPlanScreeningQualityGate,
        pass_ids: Mapping[str, list[UUID]],
        request_id: UUID,
    ) -> list[str]:
        """계약의 연결 검사. 실패하면 기록하지 않고 invalid_request다.

        ``product_rerun``이면 pass 실행들의 status를 돌려준다(판정의 ``보류`` 입력).
        """

        if gate.evaluation_basis == "reference_artifact_rescore":
            if any(ids for ids in pass_ids.values()):
                raise _invalid("참조 재채점 gate의 pass 실행 목록은 비어 있어야 합니다", request_id)
            return []

        all_ids = [execution_id for ids in pass_ids.values() for execution_id in ids]
        if len(set(all_ids)) != len(all_ids):
            raise _invalid("같은 실행이 pass에 두 번 나옵니다", request_id)
        rows = {
            row.execution_id: row
            for row in session.scalars(
                select(OrderPlanScreeningExecution).where(OrderPlanScreeningExecution.execution_id.in_(all_ids))
            ).all()
        } if all_ids else {}
        expected_runs = list(gate.measurement_run_ids_json)
        statuses: list[str] = []
        for ids in pass_ids.values():
            runs: list[str] = []
            for execution_id in ids:
                row = rows.get(execution_id)
                if row is None:
                    raise _invalid("없는 측정 실행이 있습니다", request_id)
                if (
                    row.purpose != "gate_measurement"
                    or row.policy_version != gate.policy_version
                    or row.policy_sha256 != gate.policy_sha256
                    or row.binding_sha256 != gate.binding_sha256
                ):
                    raise _invalid("pass 실행이 gate의 측정 실행이 아닙니다", request_id)
                runs.append(row.source_run_id)
                statuses.append(row.status)
            # 회차당 실행 하나: 길이와 집합이 모두 같아야 한다.
            if len(runs) != len(expected_runs) or set(runs) != set(expected_runs):
                raise _invalid("pass 실행의 회차 집합이 gate의 측정 회차와 다릅니다", request_id)
        return statuses

    def create_evaluation(
        self,
        session: Session,
        gate_id: str,
        payload: QualityEvaluationCreateRequest,
        actor: str | None,
        actor_format: str | None = None,
    ) -> dict[str, Any]:
        request_id = payload.request_id
        claimed_name = _safe_actor(actor, actor_format, request_id)
        # 같은 body라도 gate가 다르면 다른 요청이다.
        request_hash = _sha256_json({"gate_id": gate_id, "body": payload.model_dump(mode="json")})
        replay = self._screening._idempotent(session, EVALUATION_CREATE_OPERATION, request_id, request_hash)
        if replay is not None:
            return replay

        gate = session.get(OrderPlanScreeningQualityGate, gate_id)
        if gate is None:
            raise OrderPlanScreeningError("not_found", "C-2 quality gate를 찾을 수 없습니다", status_code=404, request_id=request_id)
        # 활성화와 직렬화한다. 게이트 행은 app 역할에 UPDATE가 없어 잠그지 않는다.
        session.scalar(
            select(OrderPlanScreeningPolicy)
            .where(OrderPlanScreeningPolicy.policy_version == gate.policy_version)
            .with_for_update()
        )

        pass_ids: dict[str, list[UUID]] = {"pass_1": list(payload.pass_execution_ids.pass_1)}
        if payload.pass_execution_ids.pass_2 is not None:
            pass_ids["pass_2"] = list(payload.pass_execution_ids.pass_2)
        if payload.pass_metrics.pass_2 is not None and "pass_2" not in pass_ids:
            raise _invalid("pass_2 실행 없이 pass_2 측정값이 있습니다", request_id)
        statuses = self._linked_statuses(session, gate, pass_ids, request_id)

        passes: list[dict[str, Any]] = []
        metrics: dict[str, Any] = {}
        for key in pass_ids:
            source = getattr(payload.pass_metrics, key)
            # pass 실행은 있는데 측정값이 없으면 그 pass의 지표는 전부 null이다(보류).
            value = _metrics_payload(source) if source is not None else {name: None for name, _c, _d in METRICS}
            passes.append(value)
            metrics[key] = value
        if payload.agreement_pct is not None:
            metrics["agreement_pct"] = payload.agreement_pct
        if payload.reference_full_window is not None:
            metrics["reference_full_window"] = _metrics_payload(payload.reference_full_window)

        result_status, rule_reasons = judge(gate, passes, statuses)
        server_reasons = list(rule_reasons)
        if gate.evaluation_basis == "reference_artifact_rescore":
            server_reasons.insert(0, NOT_PRODUCT_PIPELINE_RESULT)
        reasons = _merge_reasons(server_reasons, payload.reasons)
        worst = worst_values(passes)

        if session.scalar(
            select(OrderPlanScreeningQualityEvaluation.evaluation_id).where(
                OrderPlanScreeningQualityEvaluation.artifact_sha256 == payload.artifact_sha256
            )
        ) is not None:
            raise OrderPlanScreeningError("immutable_conflict", "이미 기록된 gate artifact입니다", request_id=request_id)
        latest_revision = session.scalar(
            select(func.max(OrderPlanScreeningQualityEvaluation.revision)).where(
                OrderPlanScreeningQualityEvaluation.gate_id == gate.gate_id
            )
        ) or 0

        now = _now()
        row = OrderPlanScreeningQualityEvaluation(
            evaluation_id="c2gateeval-" + uuid4().hex,
            gate_id=gate.gate_id,
            revision=latest_revision + 1,
            result_status=result_status,
            pass_execution_ids_json={key: [str(value) for value in ids] for key, ids in pass_ids.items()},
            measured_recall_pct=worst["recall_pct"],
            measured_precision_pct=worst["precision_pct"],
            measured_important_missed=int(worst["important_missed"]) if worst["important_missed"] is not None else None,
            measured_review_load=int(worst["review_load"]) if worst["review_load"] is not None else None,
            metrics_json=metrics,
            reasons_json=reasons,
            artifact_sha256=payload.artifact_sha256,
            evaluated_by=claimed_name,
            evaluated_at=now,
        )
        session.add(row)
        response = QualityEvaluationCreateResponse.model_validate({
            "schema_version": "order-plan-quality-evaluation-response.v1",
            "producer": PRODUCER,
            "consumer": CONSUMER,
            "request_id": request_id,
            **self.evaluation_view(row),
        }).model_dump(mode="json")
        session.add(AuditEvent(
            id=uuid4(),
            actor_kind="human",
            claimed_name=claimed_name,
            action="c2.quality_evaluation_recorded",
            aggregate_type="order_plan_screening_quality_gate",
            aggregate_id=gate.gate_id,
            safe_metadata={
                "gate_id": gate.gate_id,
                "revision": row.revision,
                "result_status": result_status,
                "evaluation_basis": gate.evaluation_basis,
                "artifact_sha256": payload.artifact_sha256,
            },
            request_id=str(request_id),
            created_at=now,
        ))
        session.add(IdempotencyRecord(
            id=uuid4(),
            operation=EVALUATION_CREATE_OPERATION,
            aggregate_type="order_plan_screening_quality_gate",
            aggregate_id=gate.gate_id,
            claimed_name=claimed_name,
            request_id=request_id,
            request_sha256=request_hash,
            response_status=201,
            response_snapshot=response,
            created_at=now,
        ))
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            replay = self._screening._idempotent(session, EVALUATION_CREATE_OPERATION, request_id, request_hash)
            if replay is not None:
                return replay
            raise OrderPlanScreeningError("immutable_conflict", "C-2 evaluation 기록이 충돌했습니다", request_id=request_id) from error
        return response
