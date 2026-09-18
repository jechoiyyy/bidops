"""C-2 탈락 건 감사 표본 산출과 append-only 기록 (spec §5, contracts "감사 표본 REST").

입력은 한 실행의 ``stage1_status='filtered_out'`` 결과 행이고, 설정은 그 실행이 고정한
policy payload의 ``audit_sample``에서만 읽는다. 값이 없거나 형식이 틀리면 추정하지 않고
``pending_human_approval``로 닫는다.

층 규칙은 ``audit_sample.strata_rules``다(spec §5의 층 정의를 지금 데이터로 계산할 수 있게
v3 policy가 발행할 키, 자유 형식 dict라 검증 모델은 그대로다):

- ``classification_proximity``: ``{"field": <order_plan 열>, "values": [<문자열>, ...]}``.
  ``field``는 ``CLASSIFICATION_FIELDS`` 중 하나이고, 그 열 값이 ``values``에 있으면 이 층이다.
- ``performance_similarity_proximity``: ``{"rank_window": W}`` — ``top_k < stage1_rank <= top_k + W``.
- ``uniform_hash``: 규칙 없음(나머지 전부).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.models import AuditEvent, IdempotencyRecord
from ...lifecycle.models import OrderPlan
from ..models import (
    OrderPlanScreeningAuditSample,
    OrderPlanScreeningExecution,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningResult,
)
from .order_plan_screening import (
    OrderPlanScreeningError,
    _safe_actor,
    _sha256_bytes,
    _sha256_json,
)


AUDIT_SAMPLE_OPERATION = "c2_audit_sample_draw"
AUDIT_SAMPLE_ACTION = "c2.audit_sample_drawn"
SELECTION_ORDER = "stratum_priority_then_sha256_plan_id"
STRATA = ("classification_proximity", "performance_similarity_proximity", "uniform_hash")
CLASSIFICATION_FIELDS = frozenset(
    {"business_division_code", "service_type_code", "procurement_method", "contract_method", "agency_code"}
)
COMPLETED_STATUSES = frozenset({"성공", "부분 성공"})
TRIGGERS = frozenset({"daily_script", "manual_resume"})

PENDING_SETTINGS = "max_per_execution_and_review_cadence"
PENDING_STRATA_RULES = "audit_sample_strata_rules"
REASON_GATE_MEASUREMENT = "execution.purpose.gate_measurement"
REASON_AT_OR_BELOW_TOP_K = "stage1.population.at_or_below_top_k"


def _now() -> datetime:
    return datetime.now(UTC)


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None


def _nonblank(value: Any, limit: int) -> str | None:
    return value if isinstance(value, str) and value.strip() and len(value) <= limit else None


def plan_id_sha256(order_plan_unty_no: str) -> str:
    return _sha256_bytes(order_plan_unty_no.encode("utf-8"))


def _strata(audit: Mapping[str, Any]) -> tuple[str, ...] | None:
    """정책 ``strata``·``selection_order``·``replacement``가 이 구현이 따르는 형태인지."""

    strata = audit.get("strata")
    if (
        not isinstance(strata, list)
        or not strata
        or any(item not in STRATA for item in strata)
        or len(set(strata)) != len(strata)
        # 나머지 전부를 받는 층이 없으면 어떤 탈락 건은 층이 없다.
        or "uniform_hash" not in strata
    ):
        return None
    if audit.get("selection_order") != SELECTION_ORDER or audit.get("replacement") != "none":
        return None
    return tuple(strata)


def _strata_rules(audit: Mapping[str, Any], strata: tuple[str, ...]) -> tuple[str, dict[str, Any] | None]:
    """``("absent"|"valid"|"invalid", 규칙)``. 층 목록에 있는 규칙 층마다 규칙이 하나씩 있어야 한다."""

    raw = audit.get("strata_rules")
    if raw is None:
        return "absent", None
    needed = {stratum for stratum in strata if stratum != "uniform_hash"}
    if not isinstance(raw, Mapping) or set(raw) != needed:
        return "invalid", None
    rules: dict[str, Any] = {}
    if "classification_proximity" in needed:
        rule = raw["classification_proximity"]
        if not isinstance(rule, Mapping) or set(rule) != {"field", "values"}:
            return "invalid", None
        values = rule["values"]
        if (
            rule["field"] not in CLASSIFICATION_FIELDS
            or not isinstance(values, list)
            or not values
            or not all(isinstance(item, str) and item.strip() for item in values)
        ):
            return "invalid", None
        rules["classification_proximity"] = (rule["field"], frozenset(values))
    if "performance_similarity_proximity" in needed:
        rule = raw["performance_similarity_proximity"]
        if not isinstance(rule, Mapping) or set(rule) != {"rank_window"}:
            return "invalid", None
        window = _positive_int(rule["rank_window"])
        if window is None:
            return "invalid", None
        rules["performance_similarity_proximity"] = window
    return "valid", rules


def _assign(
    plan: OrderPlan,
    result: OrderPlanScreeningResult,
    strata: tuple[str, ...],
    rules: Mapping[str, Any],
    top_k: int,
) -> str:
    """정책 ``strata`` 순서에서 처음 일치하는 층 하나(``replacement: none``)."""

    for stratum in strata:
        if stratum == "classification_proximity":
            field, values = rules["classification_proximity"]
            if getattr(plan, field) in values:
                return stratum
        elif stratum == "performance_similarity_proximity":
            window = rules["performance_similarity_proximity"]
            if result.stage1_rank is not None and top_k < result.stage1_rank <= top_k + window:
                return stratum
        else:
            return stratum
    raise AssertionError("uniform_hash stratum is required")  # _strata가 보장한다


def compute_sample(
    candidates: list[tuple[OrderPlanScreeningResult, OrderPlan]],
    audit: Mapping[str, Any],
    *,
    top_k: int,
    max_per_execution: int,
) -> list[dict[str, Any]] | str:
    """표본 item 목록, 또는 사람 결정이 필요하면 ``pending_decision`` 문자열.

    입력 순서와 무관하게 같은 입력은 같은 목록을 낸다.
    """

    strata = _strata(audit)
    if strata is None:
        return PENDING_STRATA_RULES
    rule_state, rules = _strata_rules(audit, strata)
    exceeds = len(candidates) > max_per_execution
    if rule_state == "invalid" or (exceeds and rule_state == "absent"):
        return PENDING_STRATA_RULES
    keyed: list[tuple[int, str, int, OrderPlanScreeningResult, OrderPlan, str]] = []
    for result, plan in candidates:
        if rule_state == "absent":
            # 탈락이 상한 이하라 전건이다. 층 배분이 표본을 바꾸지 않으므로 규칙 없이 한 층으로 둔다.
            stratum = "uniform_hash"
        else:
            stratum = _assign(plan, result, strata, rules or {}, top_k)
        digest = plan_id_sha256(plan.order_plan_unty_no)
        priority = strata.index(stratum) if stratum in strata else len(strata)
        keyed.append((priority, digest, plan.id, result, plan, stratum))
    keyed.sort(key=lambda item: (item[0], item[1], item[2]))
    items: list[dict[str, Any]] = []
    for rank, (_, digest, _, result, plan, stratum) in enumerate(keyed[:max_per_execution], start=1):
        items.append({
            "order_plan_pk": plan.id,
            "order_plan_unty_no": plan.order_plan_unty_no,
            "title": plan.title,
            "stratum": stratum,
            "selection_rank": rank,
            "plan_id_sha256": digest,
            "stage1_rank": result.stage1_rank,
            "stage1_score": float(result.stage1_score) if result.stage1_score is not None else None,
            "nearest_capability": result.nearest_capability,
        })
    return items


class OrderPlanAuditSampleService:
    """감사 표본 미리보기(GET)와 기록(POST)."""

    # --- 조회 ---------------------------------------------------------------

    @staticmethod
    def _execution(session: Session, execution_id: UUID, *, lock: bool, request_id: UUID | None) -> OrderPlanScreeningExecution:
        statement = select(OrderPlanScreeningExecution).where(OrderPlanScreeningExecution.execution_id == execution_id)
        if lock:
            statement = statement.with_for_update()
        execution = session.scalar(statement)
        if execution is None:
            raise OrderPlanScreeningError("not_found", "C-2 execution을 찾을 수 없습니다", status_code=404, request_id=request_id)
        return execution

    @staticmethod
    def _policy_payload(session: Session, execution: OrderPlanScreeningExecution) -> tuple[dict[str, Any], int]:
        policy = session.scalar(
            select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == execution.policy_version)
        )
        payload = policy.policy_payload_jsonb if policy is not None else None
        stage1 = payload.get("stage1") if isinstance(payload, Mapping) else None
        top_k = _positive_int(stage1.get("top_k")) if isinstance(stage1, Mapping) else None
        if policy is None or policy.policy_sha256 != execution.policy_sha256 or top_k is None:
            # 실행이 고정한 policy를 읽을 수 없으면 계산하지 않는다.
            raise OrderPlanScreeningError("processing_failed", "C-2 policy를 읽을 수 없습니다", status_code=500)
        audit = payload.get("audit_sample")
        return (dict(audit) if isinstance(audit, Mapping) else {}), top_k

    @staticmethod
    def _candidates(session: Session, execution_id: UUID) -> list[tuple[OrderPlanScreeningResult, OrderPlan]]:
        rows = session.execute(
            select(OrderPlanScreeningResult, OrderPlan)
            .join(OrderPlan, OrderPlan.id == OrderPlanScreeningResult.order_plan_id)
            .where(
                OrderPlanScreeningResult.execution_id == execution_id,
                OrderPlanScreeningResult.stage1_status == "filtered_out",
            )
            .order_by(OrderPlan.id)
        ).all()
        return [(result, plan) for result, plan in rows]

    @staticmethod
    def _stored(session: Session, execution_id: UUID) -> list[tuple[OrderPlanScreeningAuditSample, OrderPlanScreeningResult, OrderPlan]]:
        rows = session.execute(
            select(OrderPlanScreeningAuditSample, OrderPlanScreeningResult, OrderPlan)
            .join(OrderPlan, OrderPlan.id == OrderPlanScreeningAuditSample.order_plan_id)
            .join(
                OrderPlanScreeningResult,
                (OrderPlanScreeningResult.execution_id == OrderPlanScreeningAuditSample.execution_id)
                & (OrderPlanScreeningResult.order_plan_id == OrderPlanScreeningAuditSample.order_plan_id),
            )
            .where(OrderPlanScreeningAuditSample.execution_id == execution_id)
            .order_by(OrderPlanScreeningAuditSample.selection_rank)
        ).all()
        return [(sample, result, plan) for sample, result, plan in rows]

    @staticmethod
    def _base(execution: OrderPlanScreeningExecution, filtered_out_count: int) -> dict[str, Any]:
        return {
            "producer": "screening-api",
            "consumer": "human-review-client",
            "execution_id": str(execution.execution_id),
            "status": None,
            "reason": None,
            "pending_decision": None,
            "policy_version": execution.policy_version,
            "policy_sha256": execution.policy_sha256,
            "population_count": execution.population_count,
            "filtered_out_count": filtered_out_count,
            "max_per_execution": None,
            "review_cadence": None,
            "sample": None,
            "drawn_by": None,
            "drawn_at": None,
        }

    @staticmethod
    def _stored_view(view: dict[str, Any], stored: list[tuple[OrderPlanScreeningAuditSample, OrderPlanScreeningResult, OrderPlan]]) -> dict[str, Any]:
        first = stored[0][0]
        view.update({
            "status": "drawn",
            "filtered_out_count": first.filtered_out_count,
            "max_per_execution": first.max_per_execution,
            "review_cadence": first.review_cadence,
            "drawn_by": first.drawn_by,
            "drawn_at": first.drawn_at.isoformat(),
            "sample": [
                {
                    "order_plan_pk": plan.id,
                    "order_plan_unty_no": plan.order_plan_unty_no,
                    "title": plan.title,
                    "stratum": sample.stratum,
                    "selection_rank": sample.selection_rank,
                    "plan_id_sha256": sample.plan_id_sha256,
                    "stage1_rank": result.stage1_rank,
                    "stage1_score": float(result.stage1_score) if result.stage1_score is not None else None,
                    "nearest_capability": result.nearest_capability,
                }
                for sample, result, plan in stored
            ],
        })
        return view

    def _evaluate(
        self, session: Session, execution: OrderPlanScreeningExecution, request_id: UUID | None
    ) -> tuple[dict[str, Any], list[dict[str, Any]] | None, list[Any]]:
        """상태 결정표를 위에서부터 적용한다.

        돌려주는 것: (view, 새로 계산한 표본 또는 ``None``, 이미 기록된 행).
        view의 ``status``가 ``None``이면 호출자가 ``preview``/``drawn``을 정한다.
        """

        if execution.status not in COMPLETED_STATUSES:
            raise OrderPlanScreeningError(
                "execution_not_completed", "완료된 C-2 execution이 아닙니다", status_code=409, request_id=request_id
            )
        candidates = self._candidates(session, execution.execution_id)
        view = self._base(execution, len(candidates))
        audit, top_k = self._policy_payload(session, execution)
        if execution.purpose == "gate_measurement":
            view.update(status="not_applicable", reason=REASON_GATE_MEASUREMENT)
            return view, None, []
        if execution.population_count <= top_k:
            view.update(status="not_applicable", reason=REASON_AT_OR_BELOW_TOP_K)
            return view, None, []
        max_per_execution = _positive_int(audit.get("max_per_execution"))
        review_cadence = _nonblank(audit.get("review_cadence"), 64)
        view.update(max_per_execution=max_per_execution, review_cadence=review_cadence)
        if audit.get("enabled") is not True or max_per_execution is None or review_cadence is None:
            view.update(status="pending_human_approval", pending_decision=PENDING_SETTINGS)
            return view, None, []
        stored = self._stored(session, execution.execution_id)
        if stored:
            return self._stored_view(view, stored), None, stored
        sample = compute_sample(candidates, audit, top_k=top_k, max_per_execution=max_per_execution)
        if isinstance(sample, str):
            view.update(status="pending_human_approval", pending_decision=sample)
            return view, None, []
        view["sample"] = sample
        return view, sample, []

    def preview(self, session: Session, execution_id: UUID) -> dict[str, Any]:
        execution = self._execution(session, execution_id, lock=False, request_id=None)
        view, _, _ = self._evaluate(session, execution, None)
        if view["status"] is None:
            view["status"] = "preview"
        return {"schema_version": "audit-sample-preview-response.v1", **view}

    # --- 기록 ---------------------------------------------------------------

    @staticmethod
    def _replay(session: Session, request_id: UUID, request_hash: str) -> tuple[int, dict[str, Any]] | None:
        row = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.operation == AUDIT_SAMPLE_OPERATION,
                IdempotencyRecord.request_id == request_id,
            )
        )
        if row is None:
            return None
        if row.request_sha256 != request_hash or not isinstance(row.response_snapshot, Mapping):
            raise OrderPlanScreeningError("idempotency_conflict", "같은 request_id가 다른 요청에 사용되었습니다", request_id=request_id)
        return row.response_status, dict(row.response_snapshot)

    def _recomputed_matches(self, session: Session, execution: OrderPlanScreeningExecution, stored: list[Any]) -> bool:
        audit, top_k = self._policy_payload(session, execution)
        first = stored[0][0]
        candidates = self._candidates(session, execution.execution_id)
        sample = compute_sample(candidates, audit, top_k=top_k, max_per_execution=first.max_per_execution)
        if isinstance(sample, str):
            return False
        expected = [(item["order_plan_pk"], item["stratum"], item["selection_rank"], item["plan_id_sha256"]) for item in sample]
        actual = [(row.order_plan_id, row.stratum, row.selection_rank, row.plan_id_sha256) for row, _, _ in stored]
        return (
            expected == actual
            and all(
                row.filtered_out_count == len(candidates)
                and row.policy_sha256 == execution.policy_sha256
                and row.policy_version == execution.policy_version
                for row, _, _ in stored
            )
        )

    @staticmethod
    def _response(view: dict[str, Any], request_id: UUID, audit_event_id: UUID | None) -> dict[str, Any]:
        return {
            "schema_version": "audit-sample-draw-response.v1",
            **view,
            "request_id": str(request_id),
            "audit_event_id": str(audit_event_id) if audit_event_id is not None else None,
        }

    def draw(
        self,
        session: Session,
        execution_id: UUID,
        payload: Any,
        actor: str | None,
        actor_format: str | None = None,
        trigger: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """``(HTTP status, 응답)``. 첫 기록은 201, 그 밖의 성공은 200이다."""

        request_id = payload.request_id
        if trigger is not None and trigger not in TRIGGERS:
            raise OrderPlanScreeningError("invalid_request", "X-BidOps-Trigger 값이 올바르지 않습니다", status_code=422, request_id=request_id)
        claimed_name = _safe_actor(actor, actor_format, request_id)
        # 경로의 execution도 요청의 일부다. 헤더는 hash에 넣지 않는다(공통 규칙).
        request_hash = _sha256_json({"execution_id": str(execution_id), "body": payload.model_dump(mode="json")})
        replay = self._replay(session, request_id, request_hash)
        if replay is not None:
            return replay
        execution = self._execution(session, execution_id, lock=True, request_id=request_id)
        view, sample, stored = self._evaluate(session, execution, request_id)
        if stored:
            if not self._recomputed_matches(session, execution, stored):
                raise OrderPlanScreeningError("immutable_conflict", "기록된 감사 표본과 다시 계산한 표본이 다릅니다", request_id=request_id)
            return 200, self._response(view, request_id, None)
        if sample is None:
            # pending_human_approval·not_applicable은 아무것도 기록하지 않는다.
            return 200, self._response(view, request_id, None)

        now = _now()
        max_per_execution = view["max_per_execution"]
        review_cadence = view["review_cadence"]
        for item in sample:
            session.add(OrderPlanScreeningAuditSample(
                id=uuid4(),
                execution_id=execution.execution_id,
                order_plan_id=item["order_plan_pk"],
                stratum=item["stratum"],
                selection_rank=item["selection_rank"],
                plan_id_sha256=item["plan_id_sha256"],
                filtered_out_count=view["filtered_out_count"],
                max_per_execution=max_per_execution,
                review_cadence=review_cadence,
                policy_version=execution.policy_version,
                policy_sha256=execution.policy_sha256,
                drawn_by=claimed_name,
                drawn_at=now,
            ))
        audit_event_id = uuid4()
        session.add(AuditEvent(
            id=audit_event_id,
            actor_kind="human",
            claimed_name=claimed_name,
            action=AUDIT_SAMPLE_ACTION,
            aggregate_type="order_plan_screening_execution",
            aggregate_id=str(execution.execution_id),
            safe_metadata={
                "trigger": trigger,
                "sample_count": len(sample),
                "filtered_out_count": view["filtered_out_count"],
                "max_per_execution": max_per_execution,
                "review_cadence": review_cadence,
                "policy_version": execution.policy_version,
            },
            request_id=str(request_id),
            created_at=now,
        ))
        view.update(status="drawn", drawn_by=claimed_name, drawn_at=now.isoformat())
        response = self._response(view, request_id, audit_event_id)
        session.add(IdempotencyRecord(
            id=uuid4(),
            operation=AUDIT_SAMPLE_OPERATION,
            aggregate_type="order_plan_screening_execution",
            aggregate_id=str(execution.execution_id),
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
            replay = self._replay(session, request_id, request_hash)
            if replay is not None:
                return replay
            # 다른 요청이 먼저 기록했다(UNIQUE(execution_id, order_plan_id)). 기록된 행으로 답한다.
            execution = self._execution(session, execution_id, lock=False, request_id=request_id)
            view, _, stored = self._evaluate(session, execution, request_id)
            if stored and self._recomputed_matches(session, execution, stored):
                return 200, self._response(view, request_id, None)
            raise OrderPlanScreeningError("immutable_conflict", "감사 표본 기록이 충돌했습니다", request_id=request_id) from error
        return 201, response

