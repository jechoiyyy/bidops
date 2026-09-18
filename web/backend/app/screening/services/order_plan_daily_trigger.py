"""C-2 일일 자동 실행 스위치 (결정 21, contracts "일일 자동 실행 스위치 REST").

스위치는 policy 버전에 묶인 append-only 행이다. 현재 값은 **현재 active 버전의 최신 행**
이고, 새 버전을 활성화하면 그 버전에는 행이 없으므로 꺼진 것으로 본다.

`effective_state(session, settings)`는 실행 게이트가 ``X-BidOps-Trigger: daily_script|
manual_resume`` 요청에 같은 조건을 다시 계산할 때 import한다. 조회·기록·실행 게이트가
같은 함수를 쓰므로 답이 갈리지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.models import AuditEvent, IdempotencyRecord
from ..models import OrderPlanScreeningDailyTrigger, OrderPlanScreeningPolicy
from .order_plan_policy import C2PolicyError, execution_transport_allowed, mounted_files
from .order_plan_screening import (
    OrderPlanScreeningError,
    OrderPlanScreeningService,
    _now,
    _safe_actor,
    _sha256_json,
)


SET_OPERATION = "c2_daily_trigger_set"
PRODUCER = "daily-trigger-api"
CONSUMER = "human-review-client"
AGGREGATE_TYPE = "order_plan_screening_policy"


@dataclass(frozen=True)
class DailyTriggerState:
    """`effective_enabled`와 그 근거. ``reasons``는 contracts 표의 순서다."""

    effective_enabled: bool
    policy: OrderPlanScreeningPolicy | None
    switch: OrderPlanScreeningDailyTrigger | None
    reasons: tuple[str, ...]


def _latest_switch(session: Session, *conditions: Any) -> OrderPlanScreeningDailyTrigger | None:
    return session.scalar(
        select(OrderPlanScreeningDailyTrigger)
        .where(*conditions)
        .order_by(OrderPlanScreeningDailyTrigger.set_at.desc(), OrderPlanScreeningDailyTrigger.id.desc())
        .limit(1)
    )


def effective_state(session: Session, settings: Settings) -> DailyTriggerState:
    """네 조건(환경 cap ∧ 스위치 ∧ 전송 허용 ∧ active·passed·파일)이 모두 참일 때만 켜진다."""

    reasons: list[str] = []
    if not settings.c2_daily_trigger_enabled:
        reasons.append("env_cap_off")
    policy = session.scalar(
        select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_status == "active")
    )
    if policy is None:
        reasons.append("no_active_policy")
        return DailyTriggerState(False, None, None, tuple(reasons))
    switch = _latest_switch(session, OrderPlanScreeningDailyTrigger.policy_version == policy.policy_version)
    if switch is None:
        other = _latest_switch(session, OrderPlanScreeningDailyTrigger.policy_version != policy.policy_version)
        reasons.append("switch_bound_to_other_version" if other is not None and other.enabled else "switch_off")
    elif not switch.enabled:
        reasons.append("switch_off")
    if policy.quality_gate_status != "passed":
        reasons.append("quality_gate_not_passed")
    if not execution_transport_allowed(settings, policy):
        reasons.append("execution_transport_not_allowed")
    if mounted_files(settings, policy).missing is not None:
        reasons.append("policy_file_missing")
    return DailyTriggerState(not reasons, policy, switch, tuple(reasons))


def _switch_view(switch: OrderPlanScreeningDailyTrigger | None) -> dict[str, Any] | None:
    if switch is None:
        return None
    return {"enabled": switch.enabled, "reason": switch.reason, "set_by": switch.set_by, "set_at": switch.set_at}


class OrderPlanDailyTriggerService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._idempotency = OrderPlanScreeningService(self.settings)

    def state(self, session: Session) -> dict[str, Any]:
        state = effective_state(session, self.settings)
        return {
            "schema_version": "daily-trigger-state-response.v1",
            "producer": PRODUCER,
            "consumer": CONSUMER,
            "effective_enabled": state.effective_enabled,
            "policy_version": state.policy.policy_version if state.policy is not None else None,
            "policy_sha256": state.policy.policy_sha256 if state.policy is not None else None,
            "switch": _switch_view(state.switch),
            "reasons": list(state.reasons),
        }

    def set_switch(self, session: Session, payload: Any, actor: str | None, actor_format: str | None = None) -> dict[str, Any]:
        request_id: UUID = payload.request_id
        claimed_name = _safe_actor(actor, actor_format, request_id)
        request_hash = _sha256_json(payload.model_dump(mode="json"))
        replay = self._idempotency._idempotent(session, SET_OPERATION, request_id, request_hash)
        if replay is not None:
            return replay
        try:
            # 활성화와 같은 policy 행을 잠가, 기록 중에 active 버전이 바뀌지 않게 한다.
            policy = session.scalar(
                select(OrderPlanScreeningPolicy)
                .where(OrderPlanScreeningPolicy.policy_status == "active")
                .with_for_update()
            )
            if policy is None or policy.policy_version != payload.policy_version:
                raise C2PolicyError("invalid_request", "현재 active policy 버전에만 스위치를 기록할 수 있습니다", status_code=422, request_id=request_id)
            if payload.explicit_confirmation is not True:
                raise C2PolicyError("invalid_request", "스위치 변경 확인이 필요합니다", status_code=422, request_id=request_id)
            if payload.reason is not None and not payload.reason.strip():
                raise C2PolicyError("invalid_request", "스위치 사유가 비어 있습니다", status_code=422, request_id=request_id)
            now = _now()
            session.add(OrderPlanScreeningDailyTrigger(
                id=uuid4(),
                policy_version=policy.policy_version,
                policy_sha256=policy.policy_sha256,
                enabled=payload.enabled,
                reason=payload.reason,
                set_by=claimed_name,
                set_at=now,
                request_id=request_id,
            ))
            event_id = uuid4()
            session.add(AuditEvent(
                id=event_id,
                actor_kind="human",
                claimed_name=claimed_name,
                action="c2.daily_trigger_set",
                aggregate_type=AGGREGATE_TYPE,
                aggregate_id=policy.policy_version,
                safe_metadata={"enabled": payload.enabled, "policy_sha256": policy.policy_sha256},
                request_id=str(request_id),
                created_at=now,
            ))
            session.flush()
            # 환경 cap이 꺼져 있어도 행은 기록된다. 결과는 기록 직후의 상태로 드러난다.
            state = effective_state(session, self.settings)
            response = {
                "schema_version": "daily-trigger-set-response.v1",
                "producer": PRODUCER,
                "consumer": CONSUMER,
                "request_id": str(request_id),
                "policy_version": policy.policy_version,
                "policy_sha256": policy.policy_sha256,
                "enabled": payload.enabled,
                "reason": payload.reason,
                "set_by": claimed_name,
                "set_at": now.isoformat(),
                "audit_event_id": str(event_id),
                "effective_enabled": state.effective_enabled,
                "reasons": list(state.reasons),
            }
            session.add(IdempotencyRecord(
                id=uuid4(),
                operation=SET_OPERATION,
                aggregate_type=AGGREGATE_TYPE,
                aggregate_id=policy.policy_version,
                claimed_name=claimed_name,
                request_id=request_id,
                request_sha256=request_hash,
                response_status=201,
                response_snapshot=response,
                created_at=now,
            ))
            session.flush()
            session.commit()
            return response
        except OrderPlanScreeningError:
            session.rollback()
            raise
        except IntegrityError as error:
            session.rollback()
            replay = self._idempotency._idempotent(session, SET_OPERATION, request_id, request_hash)
            if replay is not None:
                return replay
            raise C2PolicyError("processing_failed", "C-2 일일 스위치를 기록할 수 없습니다", status_code=500, request_id=request_id) from error


__all__ = ["DailyTriggerState", "OrderPlanDailyTriggerService", "effective_state"]
