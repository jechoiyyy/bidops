"""C-2 policy 조회·후보 지정·활성화 경계 (ADR-0060, contracts "policy REST").

활성 여부의 정본은 ``order_plan_screening_policy`` 행이다. policy 파일 payload의
상태성 필드(``policy_status``·``activation.*``·``quality_gate.*``·``audit_sample.status``)는
발행 시점 스냅샷이므로 여기서 읽지 않는다. blocker는 전부 런타임에서 계산한다 — DB
게이트 행·evaluation, binding payload의 설정값, 마운트 파일 digest.

아래 판정 함수(`mounted_files`·`binding_consistent`·`binding_transport_approved`·
`execution_transport_allowed`·`audit_sample_approved`)는 일일 자동 실행 스위치와 실행
게이트가 같은 답을 내도록 공개한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.models import AuditEvent, IdempotencyRecord
from ..models import (
    OrderPlanScreeningPolicy,
    OrderPlanScreeningQualityEvaluation,
    OrderPlanScreeningQualityGate,
)
from .order_plan_screening import (
    OrderPlanScreeningError,
    OrderPlanScreeningService,
    _now,
    _safe_actor,
    _sha256_bytes,
    _sha256_json,
)


CANDIDATE_OPERATION = "c2_policy_candidate"
ACTIVATE_OPERATION = "c2_policy_activate"
PRODUCER = "policy-api"
CONSUMER = "human-review-client"
AGGREGATE_TYPE = "order_plan_screening_policy"
BINDING_STATUSES = frozenset({"blocked", "activation_candidate", "approved"})
PASSED = "통과"


class C2PolicyError(OrderPlanScreeningError):
    """C-2 envelope 오류에 ``details``를 싣는다(``activation_blocked``만 채운다)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        request_id: UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, status_code=status_code, request_id=request_id)
        self.details = details


def _blocker(code: str, detail: str | None = None) -> dict[str, str | None]:
    return {"code": code, "detail": detail}


# --- 공개 판정 함수 ---------------------------------------------------------
#
# policy blocker, 일일 스위치 reasons, 실행 게이트(S4b)가 모두 이 함수로 판정한다.


@dataclass(frozen=True)
class MountedFiles:
    """컨테이너 경로에 행 digest와 같은 bytes의 일반 파일이 있는가."""

    policy_present: bool
    binding_present: bool

    @property
    def missing(self) -> str | None:
        """`policy_file_missing`의 ``detail`` 값. 둘 다 있으면 ``None``."""

        if self.policy_present and self.binding_present:
            return None
        if not self.policy_present and not self.binding_present:
            return "both"
        return "binding" if self.policy_present else "policy"


def _file_matches(path: Path | None, expected_sha256: str) -> bool:
    if path is None:
        return False
    try:
        if path.is_symlink() or not path.is_file():
            return False
        return _sha256_bytes(path.read_bytes()) == expected_sha256
    except OSError:
        return False


def mounted_files(settings: Settings, policy: OrderPlanScreeningPolicy) -> MountedFiles:
    """`settings.c2_policy_path`·`c2_binding_path`의 파일 bytes digest를 행과 대조한다.

    digest는 파일 bytes 기준이다(canonical 재직렬화 아님). symlink는 없는 것으로 본다.
    """

    return MountedFiles(
        policy_present=_file_matches(settings.c2_policy_path, policy.policy_sha256),
        binding_present=_file_matches(settings.c2_binding_path, policy.binding_sha256),
    )


def _binding(policy: OrderPlanScreeningPolicy) -> Mapping[str, Any]:
    value = policy.binding_payload_jsonb
    return value if isinstance(value, Mapping) else {}


def _external_transport(binding: Mapping[str, Any]) -> Mapping[str, Any]:
    value = binding.get("external_transport")
    return value if isinstance(value, Mapping) else {}


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def binding_consistent(policy: OrderPlanScreeningPolicy) -> bool:
    """binding payload가 이 policy 행을 가리키고 status 조합이 모순이 아닌가.

    거짓이면 blocker `binding_digest_mismatch`, 실행에서는 `binding_mismatch`다.
    """

    binding = _binding(policy)
    reference = binding.get("policy")
    if not isinstance(reference, Mapping):
        return False
    if reference.get("sha256") != policy.policy_sha256 or reference.get("policy_version") != policy.policy_version:
        return False
    status = binding.get("status")
    if status not in BINDING_STATUSES:
        return False
    if status == "blocked" and _external_transport(binding).get("execution_allowed") is True:
        return False
    return True


def binding_transport_approved(policy: OrderPlanScreeningPolicy) -> bool:
    """binding의 전송 승인(D-d)이 기록되어 있는가. 환경 변수는 보지 않는다."""

    transport = _external_transport(_binding(policy))
    return (
        transport.get("execution_allowed") is True
        and transport.get("approval_scope") == "per_binding"
        and _nonblank(transport.get("approved_by"))
        and _nonblank(transport.get("approved_at"))
    )


def execution_transport_allowed(settings: Settings, policy: OrderPlanScreeningPolicy) -> bool:
    """실행 시점 전송 허용 — `BIDOPS_C2_EXECUTION_ALLOWED` ∧ binding `execution_allowed`."""

    return bool(settings.c2_execution_allowed) and _external_transport(_binding(policy)).get("execution_allowed") is True


def _audit_sample(policy: OrderPlanScreeningPolicy) -> Mapping[str, Any]:
    payload = policy.policy_payload_jsonb
    value = payload.get("audit_sample") if isinstance(payload, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def audit_sample_approved(policy: OrderPlanScreeningPolicy) -> bool:
    """policy 파일의 감사 표본 설정(D-c)이 있는가."""

    sample = _audit_sample(policy)
    return (
        sample.get("enabled") is True
        and _positive_int(sample.get("max_per_execution"))
        and _nonblank(sample.get("review_cadence"))
    )


# --- 게이트 선택 ------------------------------------------------------------


def _thresholds_decided(gate: OrderPlanScreeningQualityGate) -> bool:
    return None not in (
        gate.threshold_recall_pct,
        gate.threshold_precision_pct,
        gate.threshold_important_missed_max,
        gate.threshold_review_load_max,
    )


def _latest_evaluation(session: Session, gate_id: str) -> OrderPlanScreeningQualityEvaluation | None:
    return session.scalar(
        select(OrderPlanScreeningQualityEvaluation)
        .where(OrderPlanScreeningQualityEvaluation.gate_id == gate_id)
        .order_by(OrderPlanScreeningQualityEvaluation.revision.desc())
        .limit(1)
    )


def select_gate(
    session: Session, policy: OrderPlanScreeningPolicy
) -> tuple[OrderPlanScreeningQualityGate | None, OrderPlanScreeningQualityEvaluation | None]:
    """contracts "선택된 게이트" 규칙.

    같은 버전·``product_rerun``·행과 같은 digest인 gate만 후보다. 임계값이 모두 있고 최신
    evaluation이 ``통과``인 첫 후보, 없으면 가장 최근 후보를 고른다.
    """

    candidates = session.scalars(
        select(OrderPlanScreeningQualityGate)
        .where(
            OrderPlanScreeningQualityGate.policy_version == policy.policy_version,
            OrderPlanScreeningQualityGate.evaluation_basis == "product_rerun",
            OrderPlanScreeningQualityGate.policy_sha256 == policy.policy_sha256,
            OrderPlanScreeningQualityGate.binding_sha256 == policy.binding_sha256,
        )
        .order_by(OrderPlanScreeningQualityGate.created_at.desc(), OrderPlanScreeningQualityGate.gate_id.desc())
    ).all()
    if not candidates:
        return None, None
    latest = [(gate, _latest_evaluation(session, gate.gate_id)) for gate in candidates]
    for gate, evaluation in latest:
        if _thresholds_decided(gate) and evaluation is not None and evaluation.result_status == PASSED:
            return gate, evaluation
    return latest[0]


# --- 런타임 blocker ---------------------------------------------------------


@dataclass(frozen=True)
class PolicyAssessment:
    gate: OrderPlanScreeningQualityGate | None
    evaluation: OrderPlanScreeningQualityEvaluation | None
    files: MountedFiles
    blockers: list[dict[str, str | None]]


def assess_policy(session: Session, settings: Settings, policy: OrderPlanScreeningPolicy) -> PolicyAssessment:
    """단건 조회의 ``blockers[]``를 contracts 표 순서로 계산한다."""

    gate, evaluation = select_gate(session, policy)
    files = mounted_files(settings, policy)
    blockers: list[dict[str, str | None]] = []
    if gate is None:
        blockers.append(_blocker("quality_gate_missing"))
    else:
        if not _thresholds_decided(gate):
            blockers.append(_blocker("quality_gate_thresholds_undecided"))
        if evaluation is None or evaluation.result_status != PASSED:
            blockers.append(_blocker("quality_gate_not_passed", evaluation.result_status if evaluation else "none"))
    if not audit_sample_approved(policy):
        blockers.append(_blocker("audit_sample_policy_unapproved"))
    if not binding_transport_approved(policy):
        blockers.append(_blocker("execution_transport_not_allowed"))
    if not binding_consistent(policy):
        blockers.append(_blocker("binding_digest_mismatch"))
    if files.missing is not None:
        blockers.append(_blocker("policy_file_missing", files.missing))
    return PolicyAssessment(gate=gate, evaluation=evaluation, files=files, blockers=blockers)


# --- 응답 투영 --------------------------------------------------------------


def _summary(policy: OrderPlanScreeningPolicy) -> dict[str, Any]:
    return {
        "policy_version": policy.policy_version,
        "policy_status": policy.policy_status,
        "quality_gate_status": policy.quality_gate_status,
        "policy_sha256": policy.policy_sha256,
        "binding_sha256": policy.binding_sha256,
        "created_by": policy.created_by,
        "created_at": policy.created_at,
        "activated_by": policy.activated_by,
        "activated_at": policy.activated_at,
    }


def _typed(value: Any, kind: type) -> Any:
    if kind is int:
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    return value if isinstance(value, kind) else None


def _transport_view(policy: OrderPlanScreeningPolicy) -> dict[str, Any] | None:
    raw = _binding(policy).get("external_transport")
    if not isinstance(raw, Mapping):
        return None
    return {
        "execution_allowed": _typed(raw.get("execution_allowed"), bool),
        "approval_scope": _typed(raw.get("approval_scope"), str),
        "approved_by": _typed(raw.get("approved_by"), str),
        "approved_at": _typed(raw.get("approved_at"), str),
        "approval_required_per_execution": _typed(raw.get("approval_required_per_execution"), bool),
    }


def _audit_sample_view(policy: OrderPlanScreeningPolicy) -> dict[str, Any] | None:
    payload = policy.policy_payload_jsonb
    raw = payload.get("audit_sample") if isinstance(payload, Mapping) else None
    if not isinstance(raw, Mapping):
        return None
    return {
        "enabled": _typed(raw.get("enabled"), bool),
        "max_per_execution": _typed(raw.get("max_per_execution"), int),
        "review_cadence": _typed(raw.get("review_cadence"), str),
    }


def _gate_view(
    gate: OrderPlanScreeningQualityGate | None, evaluation: OrderPlanScreeningQualityEvaluation | None
) -> dict[str, Any] | None:
    if gate is None:
        return None
    return {
        "gate_id": gate.gate_id,
        "evaluation_basis": gate.evaluation_basis,
        "thresholds_decided": _thresholds_decided(gate),
        "latest_evaluation": None if evaluation is None else {
            "evaluation_id": evaluation.evaluation_id,
            "revision": evaluation.revision,
            "result_status": evaluation.result_status,
            "artifact_sha256": evaluation.artifact_sha256,
            "evaluated_at": evaluation.evaluated_at,
        },
    }


def _envelope(schema_version: str) -> dict[str, str]:
    return {"schema_version": schema_version, "producer": PRODUCER, "consumer": CONSUMER}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _blocked(blockers: list[dict[str, str | None]], request_id: UUID) -> C2PolicyError:
    return C2PolicyError(
        "activation_blocked",
        "C-2 policy 활성화 조건을 충족하지 않습니다",
        status_code=409,
        request_id=request_id,
        details={"blockers": blockers},
    )


class OrderPlanPolicyService:
    """policy REST의 조회와 두 상태 전이(candidate·activate)를 소유한다."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._idempotency = OrderPlanScreeningService(self.settings)

    # --- 조회 ---------------------------------------------------------------

    def list_policies(self, session: Session) -> dict[str, Any]:
        rows = session.scalars(
            select(OrderPlanScreeningPolicy).order_by(
                OrderPlanScreeningPolicy.created_at.desc(), OrderPlanScreeningPolicy.policy_version.desc()
            )
        ).all()
        return {**_envelope("policy-list-response.v1"), "items": [_summary(row) for row in rows], "total": len(rows)}

    def inspect_policy(self, session: Session, policy_version: str) -> dict[str, Any]:
        policy = session.scalar(
            select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == policy_version)
        )
        if policy is None:
            raise C2PolicyError("not_found", "C-2 policy를 찾을 수 없습니다", status_code=404)
        assessment = assess_policy(session, self.settings, policy)
        binding_status = _binding(policy).get("status")
        return {
            **_envelope("policy-inspect-response.v1"),
            **_summary(policy),
            "binding_status": binding_status if isinstance(binding_status, str) else None,
            "policy_file_present": assessment.files.policy_present,
            "binding_file_present": assessment.files.binding_present,
            "external_transport": _transport_view(policy),
            "audit_sample": _audit_sample_view(policy),
            "quality_gate": _gate_view(assessment.gate, assessment.evaluation),
            "activation_allowed": policy.policy_status == "activation_candidate" and not assessment.blockers,
            "blockers": assessment.blockers,
        }

    # --- 공통 ---------------------------------------------------------------

    def _locked(self, session: Session, policy_version: str, request_id: UUID) -> OrderPlanScreeningPolicy:
        policy = session.scalar(
            select(OrderPlanScreeningPolicy)
            .where(OrderPlanScreeningPolicy.policy_version == policy_version)
            .with_for_update()
        )
        if policy is None:
            raise C2PolicyError("not_found", "C-2 policy를 찾을 수 없습니다", status_code=404, request_id=request_id)
        return policy

    def _commit(
        self,
        session: Session,
        *,
        operation: str,
        aggregate_id: str,
        claimed_name: str,
        request_id: UUID,
        request_hash: str,
        status: int,
        response: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        session.add(IdempotencyRecord(
            id=uuid4(),
            operation=operation,
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=aggregate_id,
            claimed_name=claimed_name,
            request_id=request_id,
            request_sha256=request_hash,
            response_status=status,
            response_snapshot=response,
            created_at=now,
        ))
        session.flush()
        session.commit()
        return response

    def _replay_after_conflict(
        self, session: Session, operation: str, request_id: UUID, request_hash: str, error: IntegrityError
    ) -> dict[str, Any]:
        session.rollback()
        replay = self._idempotency._idempotent(session, operation, request_id, request_hash)
        if replay is not None:
            return replay
        raise C2PolicyError("processing_failed", "C-2 policy 요청을 완료할 수 없습니다", status_code=500, request_id=request_id) from error

    # --- 후보 지정 ------------------------------------------------------------

    def set_candidate(self, session: Session, payload: Any, actor: str | None, actor_format: str | None = None) -> dict[str, Any]:
        request_id = payload.request_id
        claimed_name = _safe_actor(actor, actor_format, request_id)
        request_hash = _sha256_json(payload.model_dump(mode="json"))
        replay = self._idempotency._idempotent(session, CANDIDATE_OPERATION, request_id, request_hash)
        if replay is not None:
            return replay
        if not payload.reason.strip():
            raise C2PolicyError("invalid_request", "후보 지정 사유가 비어 있습니다", status_code=422, request_id=request_id)
        try:
            policy = self._locked(session, payload.policy_version, request_id)
            if payload.candidate_sha256 != policy.policy_sha256:
                raise C2PolicyError("immutable_conflict", "후보 digest가 policy 행과 다릅니다", request_id=request_id)
            active_sha256 = session.scalar(
                select(OrderPlanScreeningPolicy.policy_sha256).where(OrderPlanScreeningPolicy.policy_status == "active")
            )
            if payload.base_policy_sha256 != active_sha256:
                raise C2PolicyError("immutable_conflict", "기준 policy digest가 현재 active 행과 다릅니다", request_id=request_id)
            if policy.policy_status != "draft":
                raise C2PolicyError("immutable_conflict", "draft policy만 후보로 지정할 수 있습니다", request_id=request_id)
            now = _now()
            policy.policy_status = "activation_candidate"
            event_id = uuid4()
            session.add(AuditEvent(
                id=event_id,
                actor_kind="human",
                claimed_name=claimed_name,
                action="c2.policy_candidate_set",
                aggregate_type=AGGREGATE_TYPE,
                aggregate_id=policy.policy_version,
                safe_metadata={
                    "from_status": "draft",
                    "to_status": "activation_candidate",
                    "policy_sha256": policy.policy_sha256,
                    "binding_sha256": policy.binding_sha256,
                    "base_policy_sha256": payload.base_policy_sha256,
                    "reason": payload.reason,
                },
                request_id=str(request_id),
                created_at=now,
            ))
            response = {
                **_envelope("policy-candidate-response.v1"),
                "request_id": str(request_id),
                "policy_version": policy.policy_version,
                "policy_status": "activation_candidate",
                "policy_sha256": policy.policy_sha256,
                "binding_sha256": policy.binding_sha256,
                "audit_event_id": str(event_id),
            }
            return self._commit(
                session,
                operation=CANDIDATE_OPERATION,
                aggregate_id=policy.policy_version,
                claimed_name=claimed_name,
                request_id=request_id,
                request_hash=request_hash,
                status=201,
                response=response,
                now=now,
            )
        except OrderPlanScreeningError:
            session.rollback()
            raise
        except IntegrityError as error:
            return self._replay_after_conflict(session, CANDIDATE_OPERATION, request_id, request_hash, error)

    # --- 활성화 --------------------------------------------------------------

    def _artifact_blockers(
        self, session: Session, policy: OrderPlanScreeningPolicy, artifact_sha256: str
    ) -> tuple[list[dict[str, str | None]], OrderPlanScreeningQualityGate | None, OrderPlanScreeningQualityEvaluation | None]:
        """활성화 검증 3~7번. 실패한 blocker를 순서대로 모두 낸다.

        3번이 evaluation을 특정하지 못하면 gate에 걸린 4·5번 조건은 평가할 대상이 없어 싣지
        않는다. 최신 revision이 아니면 gate는 특정되므로 gate 조건(basis·digest·임계값)은
        평가하되, 낡은 evaluation의 ``result_status``는 판정에 쓰지 않는다.
        """

        blockers: list[dict[str, str | None]] = []
        evaluation = session.scalar(
            select(OrderPlanScreeningQualityEvaluation).where(
                OrderPlanScreeningQualityEvaluation.artifact_sha256 == artifact_sha256
            )
        )
        gate: OrderPlanScreeningQualityGate | None = None
        latest = False
        if evaluation is None:
            blockers.append(_blocker("quality_gate_artifact_unknown"))
        else:
            gate = session.get(OrderPlanScreeningQualityGate, evaluation.gate_id)
            newest = session.scalar(
                select(func.max(OrderPlanScreeningQualityEvaluation.revision)).where(
                    OrderPlanScreeningQualityEvaluation.gate_id == evaluation.gate_id
                )
            )
            latest = evaluation.revision == newest
            if not latest:
                blockers.append(_blocker("quality_gate_evaluation_not_latest"))
        # 4번
        if evaluation is not None and latest and evaluation.result_status != PASSED:
            blockers.append(_blocker("quality_gate_not_passed", evaluation.result_status))
        if gate is not None:
            if gate.evaluation_basis != "product_rerun":
                blockers.append(_blocker("quality_gate_basis_not_product_rerun"))
            if (
                gate.policy_version != policy.policy_version
                or gate.policy_sha256 != policy.policy_sha256
                or gate.binding_sha256 != policy.binding_sha256
            ):
                blockers.append(_blocker("quality_gate_digest_mismatch"))
        if not binding_consistent(policy):
            blockers.append(_blocker("binding_digest_mismatch"))
        missing = mounted_files(self.settings, policy).missing
        if missing is not None:
            blockers.append(_blocker("policy_file_missing", missing))
        # 5번
        if gate is not None and not _thresholds_decided(gate):
            blockers.append(_blocker("quality_gate_thresholds_undecided"))
        # 6번
        if not audit_sample_approved(policy):
            blockers.append(_blocker("audit_sample_policy_unapproved"))
        # 7번
        if not binding_transport_approved(policy):
            blockers.append(_blocker("execution_transport_not_allowed"))
        return blockers, gate, evaluation

    def activate(
        self,
        session: Session,
        policy_version: str,
        payload: Any,
        actor: str | None,
        actor_format: str | None = None,
    ) -> dict[str, Any]:
        request_id = payload.request_id
        claimed_name = _safe_actor(actor, actor_format, request_id)
        # path의 버전도 요청의 일부다. 같은 body를 다른 버전에 보내면 다른 요청이다.
        request_hash = _sha256_json({"policy_version": policy_version, **payload.model_dump(mode="json")})
        replay = self._idempotency._idempotent(session, ACTIVATE_OPERATION, request_id, request_hash)
        if replay is not None:
            return replay
        try:
            # 0. 행 잠금. 게이트 행은 잠그지 않는다 — evaluation 기록도 이 행을 잠가 직렬화한다.
            policy = self._locked(session, policy_version, request_id)
            # 1.
            if policy.policy_status != "activation_candidate":
                raise _blocked([_blocker("policy_not_candidate", policy.policy_status)], request_id)
            # 2.
            if payload.policy_sha256 != policy.policy_sha256:
                raise C2PolicyError("immutable_conflict", "요청 policy digest가 행과 다릅니다", request_id=request_id)
            # 3~7.
            blockers, gate, evaluation = self._artifact_blockers(session, policy, payload.quality_gate_artifact_sha256)
            if blockers:
                raise _blocked(blockers, request_id)
            assert gate is not None and evaluation is not None
            # 8.
            if payload.explicit_confirmation is not True:
                raise C2PolicyError("invalid_request", "활성화 확인이 필요합니다", status_code=422, request_id=request_id)
            # 9. 이전 active를 먼저 내려 slot을 비운 뒤 대상을 올린다. unique index가 최종 심판이다.
            now = _now()
            previous = session.scalar(
                select(OrderPlanScreeningPolicy)
                .where(OrderPlanScreeningPolicy.policy_status == "active")
                .with_for_update()
            )
            previous_version = previous.policy_version if previous is not None else None
            try:
                if previous is not None:
                    previous.policy_status = "retired"
                    previous.active_slot = None
                    session.flush()
                policy.policy_status = "active"
                policy.active_slot = 1
                policy.quality_gate_status = "passed"
                policy.activated_by = claimed_name
                policy.activated_at = now
                session.flush()
            except IntegrityError as error:
                session.rollback()
                if getattr(getattr(error, "orig", None), "sqlstate", None) in {"23505", None}:
                    # 23505 = unique_violation(active slot). SQLite는 sqlstate가 없다.
                    raise _blocked([_blocker("active_slot_conflict")], request_id) from None
                raise C2PolicyError("processing_failed", "C-2 policy를 활성화할 수 없습니다", status_code=500, request_id=request_id) from error
            event_id = uuid4()
            session.add(AuditEvent(
                id=event_id,
                actor_kind="human",
                claimed_name=claimed_name,
                action="c2.policy_activated",
                aggregate_type=AGGREGATE_TYPE,
                aggregate_id=policy.policy_version,
                safe_metadata={
                    "from_status": "activation_candidate",
                    "to_status": "active",
                    "policy_sha256": policy.policy_sha256,
                    "binding_sha256": policy.binding_sha256,
                    "quality_gate_artifact_sha256": evaluation.artifact_sha256,
                    "evaluation_id": evaluation.evaluation_id,
                    "previous_active_policy_version": previous_version,
                },
                request_id=str(request_id),
                created_at=now,
            ))
            if previous is not None:
                session.add(AuditEvent(
                    id=uuid4(),
                    actor_kind="human",
                    claimed_name=claimed_name,
                    action="c2.policy_retired",
                    aggregate_type=AGGREGATE_TYPE,
                    aggregate_id=previous.policy_version,
                    safe_metadata={
                        "from_status": "active",
                        "to_status": "retired",
                        "replaced_by_policy_version": policy.policy_version,
                    },
                    request_id=str(request_id),
                    created_at=now,
                ))
            response = {
                **_envelope("policy-activate-response.v1"),
                "request_id": str(request_id),
                "policy_version": policy.policy_version,
                "policy_status": "active",
                "quality_gate_status": "passed",
                "policy_sha256": policy.policy_sha256,
                "binding_sha256": policy.binding_sha256,
                "gate_id": gate.gate_id,
                "evaluation_id": evaluation.evaluation_id,
                "previous_active_policy_version": previous_version,
                "activated_by": claimed_name,
                "activated_at": _iso(now),
                "audit_event_id": str(event_id),
            }
            return self._commit(
                session,
                operation=ACTIVATE_OPERATION,
                aggregate_id=policy.policy_version,
                claimed_name=claimed_name,
                request_id=request_id,
                request_hash=request_hash,
                status=200,
                response=response,
                now=now,
            )
        except OrderPlanScreeningError:
            session.rollback()
            raise
        except IntegrityError as error:
            return self._replay_after_conflict(session, ACTIVATE_OPERATION, request_id, request_hash, error)


__all__ = [
    "C2PolicyError",
    "MountedFiles",
    "OrderPlanPolicyService",
    "PolicyAssessment",
    "assess_policy",
    "audit_sample_approved",
    "binding_consistent",
    "binding_transport_approved",
    "execution_transport_allowed",
    "mounted_files",
    "select_gate",
]
