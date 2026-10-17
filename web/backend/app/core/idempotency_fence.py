"""`IdempotencyRecord` 영수증 fence 공용 규칙.

사람 mutation(회사별 추적 PATCH, 브리핑 반응 PATCH 등)은 같은 모양의 멱등 영수증을
쓴다. 영수증 id는 범위(operation·aggregate·claimed_name·request_id)의 canonical JSON에서
결정적으로 만들고, 요청 내용은 canonical JSON의 sha256으로 고정한다. 같은 범위·같은
hash면 저장 snapshot을 재생하고, hash가 다르면 `idempotency_conflict`다.

core는 도메인 DTO를 모른다. 여기서는 영수증 행의 범위·hash·상태·JSON 원시값만
검사하고, snapshot을 DTO로 검증하는 일은 호출한 도메인 서비스가 한다. 오류는 안전한
code 하나(`idempotency_conflict`·`processing_failed`)로만 알린다 — 호출부가 자기 오류
형으로 바꾼다.

이 규칙은 원래 `lifecycle/services/opportunity_tracking.py`의 사설 함수였다. 브리핑
반응(RL-01)이 같은 fence를 쓰게 되면서 복제 대신 여기로 옮겼다. 영수증 id 계산식은
바뀌지 않았다(이미 저장된 영수증이 그대로 재생된다).
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from .models import IdempotencyRecord


class IdempotencyFenceError(ValueError):
    """영수증이 요청과 맞지 않는다. `code`는 `idempotency_conflict`·`processing_failed`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def canonical_json(value: Any) -> bytes:
    """정렬된 키·최소 구분자·UTF-8 그대로의 JSON 바이트. NaN·Infinity는 거부한다."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def request_sha256(payload: Mapping[str, Any]) -> str:
    """요청 내용 canonical JSON의 sha256 hex."""

    return sha256(canonical_json(dict(payload))).hexdigest()


def receipt_id(
    namespace: UUID,
    *,
    operation: str,
    aggregate_type: str,
    aggregate_id: str,
    claimed_name: str,
    request_id: UUID,
) -> UUID:
    """영수증 행 id. 범위가 같으면 언제나 같은 UUIDv5다."""

    scope = {
        "operation": operation,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "claimed_name": claimed_name,
        "request_id": str(request_id),
    }
    return uuid5(namespace, canonical_json(scope).decode("utf-8"))


def json_primitives(value: Any) -> bool:
    """JSON wire 원시값(str·int·bool·유한 float·None·list·str 키 dict)만으로 이뤄졌는가."""

    if value is None or isinstance(value, (str, int, bool)):
        return True
    if isinstance(value, float):
        return value == value and value not in {float("inf"), float("-inf")}
    if isinstance(value, list):
        return all(json_primitives(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and json_primitives(item)
            for key, item in value.items()
        )
    return False


def load_receipt(
    session: Session,
    *,
    receipt: UUID,
    operation: str,
    aggregate_type: str,
    aggregate_id: str,
    claimed_name: str,
    request_id: UUID,
    request_hash: str,
    expected_status: int = 200,
) -> dict[str, Any] | None:
    """저장된 영수증의 snapshot 사본. 없으면 `None`.

    - 범위(id·operation·aggregate·claimed_name·request_id)가 다르면 `processing_failed`
    - 같은 범위인데 요청 hash가 다르면 `idempotency_conflict`
    - 저장 상태가 `expected_status`가 아니거나 snapshot이 JSON 원시값 객체가 아니면
      `processing_failed`
    """

    record = session.get(IdempotencyRecord, receipt)
    if record is None:
        return None
    if not (
        record.id == receipt
        and record.operation == operation
        and record.aggregate_type == aggregate_type
        and record.aggregate_id == aggregate_id
        and record.claimed_name == claimed_name
        and record.request_id == request_id
    ):
        raise IdempotencyFenceError("processing_failed")
    if record.request_sha256 != request_hash:
        raise IdempotencyFenceError("idempotency_conflict")
    if record.response_status != expected_status or not isinstance(record.response_snapshot, Mapping):
        raise IdempotencyFenceError("processing_failed")
    snapshot = dict(record.response_snapshot)
    if not json_primitives(snapshot):
        raise IdempotencyFenceError("processing_failed")
    return snapshot


def new_receipt(
    *,
    receipt: UUID,
    operation: str,
    aggregate_type: str,
    aggregate_id: str,
    claimed_name: str,
    request_id: UUID,
    request_hash: str,
    snapshot: dict[str, Any],
    response_status: int = 200,
) -> IdempotencyRecord:
    """같은 transaction에 넣을 영수증 행. snapshot은 JSON 원시값이어야 한다."""

    if not json_primitives(snapshot):
        raise IdempotencyFenceError("processing_failed")
    return IdempotencyRecord(
        id=receipt,
        operation=operation,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        claimed_name=claimed_name,
        request_id=request_id,
        request_sha256=request_hash,
        response_status=response_status,
        response_snapshot=snapshot,
    )


__all__ = [
    "IdempotencyFenceError",
    "canonical_json",
    "json_primitives",
    "load_receipt",
    "new_receipt",
    "receipt_id",
    "request_sha256",
]
