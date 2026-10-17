"""core 멱등 영수증 fence (`app/core/idempotency_fence.py`).

회사별 추적 PATCH의 사설 함수를 RL-01 브리핑 반응과 함께 쓰려고 core로 옮겼다. 영수증
id 계산식이 바뀌면 이미 저장된 영수증이 재생되지 않으므로, 옮기기 전과 같은 식(범위의
canonical JSON 문자열을 이름으로 쓴 UUIDv5)을 직접 계산해 고정한다.
"""

from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.core.idempotency_fence import (
    IdempotencyFenceError,
    canonical_json,
    json_primitives,
    load_receipt,
    new_receipt,
    receipt_id,
    request_sha256,
)
from app.core.models import IdempotencyRecord

NAMESPACE = uuid5(NAMESPACE_URL, "https://bidops.invalid/idempotency/fence-test/v1")
REQUEST = UUID("00000000-0000-4000-8000-000000000001")
SCOPE = dict(operation="op.test", aggregate_type="thing", aggregate_id="42", claimed_name="김담당", request_id=REQUEST)


def test_receipt_id_and_request_hash_keep_the_pre_extraction_formula() -> None:
    scope = {
        "operation": "op.test", "aggregate_type": "thing", "aggregate_id": "42",
        "claimed_name": "김담당", "request_id": str(REQUEST),
    }
    expected_name = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert receipt_id(NAMESPACE, **SCOPE) == uuid5(NAMESPACE, expected_name)
    payload = {"b": 1, "a": "값"}
    assert canonical_json(payload) == '{"a":"값","b":1}'.encode("utf-8")
    assert request_sha256(payload) == hashlib.sha256('{"a":"값","b":1}'.encode("utf-8")).hexdigest()
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_json_primitives_rejects_non_wire_values() -> None:
    assert json_primitives({"a": [1, "b", None, True, 1.5, {"c": "d"}]})
    assert not json_primitives({"a": float("inf")})
    assert not json_primitives({1: "non-string key"})
    assert not json_primitives({"a": REQUEST})


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[IdempotencyRecord.__table__])
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_load_receipt_replays_conflicts_and_rejects_foreign_scope(session) -> None:
    receipt = receipt_id(NAMESPACE, **SCOPE)
    assert load_receipt(session, receipt=receipt, request_hash="a" * 64, **SCOPE) is None
    session.add(new_receipt(receipt=receipt, request_hash="a" * 64, snapshot={"ok": 1}, **SCOPE))
    session.flush()

    assert load_receipt(session, receipt=receipt, request_hash="a" * 64, **SCOPE) == {"ok": 1}
    with pytest.raises(IdempotencyFenceError) as conflict:
        load_receipt(session, receipt=receipt, request_hash="b" * 64, **SCOPE)
    assert conflict.value.code == "idempotency_conflict"
    with pytest.raises(IdempotencyFenceError) as foreign:
        load_receipt(session, receipt=receipt, request_hash="a" * 64, **{**SCOPE, "claimed_name": "박담당"})
    assert foreign.value.code == "processing_failed"
    with pytest.raises(IdempotencyFenceError) as status:
        load_receipt(session, receipt=receipt, request_hash="a" * 64, expected_status=201, **SCOPE)
    assert status.value.code == "processing_failed"
    with pytest.raises(IdempotencyFenceError):
        new_receipt(receipt=receipt, request_hash="a" * 64, snapshot={"bad": REQUEST}, **SCOPE)
