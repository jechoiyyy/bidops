"""사업기회 노트·다음 행동의 생성과 완료 (RL-02 spec "노트·다음 행동").

- 본문은 append-only다. 완료(`done_at`·`done_by`)만 다음 행동(`kind=action`)에 한 번
  채운다. 이미 완료된 행동을 다시 완료하면 바꾸지 않고 현재 값을 돌려준다(멱등).
- 멱등은 core `IdempotencyRecord` fence(`core/idempotency_fence.py`)로 한다. 범위는
  `operation`·`aggregate_type="opportunity"`·`aggregate_id=<사업기회 id>`·
  `claimed_name=actor`·`request_id`이며, 같은 범위·같은 요청 hash는 저장 snapshot을
  재생하고 hash가 다르면 `idempotency_conflict`다. 노트 테이블에는 `request_id` UNIQUE를
  두지 않는다 — 다른 actor의 같은 `request_id`는 별개의 노트다.
- 병합된 사업기회에는 쓰지 않는다(`opportunity_merged`).
- 노트 본문은 어떤 모델 입력에도 넣지 않는다. 이 모듈은 노트를 다른 곳으로 보내지 않는다.

호출자가 commit/rollback한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.idempotency_fence import (
    IdempotencyFenceError,
    load_receipt,
    new_receipt,
    receipt_id as fence_receipt_id,
    request_sha256,
)
from ...core.models import utc_now
from ..models import Opportunity, OpportunityNote
from ..schemas.opportunities import NoteView, clean_note_body, clean_note_owner

NOTE_KINDS = ("note", "action")
CREATE_OPERATION = "opportunity_note.create"
DONE_OPERATION = "opportunity_note.done"
NOTE_AGGREGATE_TYPE = "opportunity"
_NOTE_RECEIPT_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://bidops.invalid/idempotency/opportunity-note/v1"
)
#: 새 노트를 만든 응답 상태. 같은 요청의 재생은 200으로 돌려준다.
CREATED_STATUS = 201
REPLAY_STATUS = 200


class OpportunityNoteError(ValueError):
    """안전한 code 하나와 API에 그대로 내보낼 수 있는 `details`."""

    def __init__(self, code: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class NoteMutationResult:
    """응답 DTO와 영수증에 저장한 JSON snapshot(재생은 snapshot을 그대로 돌려준다)."""

    response: NoteView
    snapshot: dict[str, Any]
    response_status: int
    replayed: bool = False


def note_view(note: OpportunityNote) -> NoteView:
    return NoteView(
        note_id=note.id,
        kind=note.kind,
        body=note.body,
        actor=note.actor,
        owner=note.owner,
        created_at=note.created_at,
        done_at=note.done_at,
        done_by=note.done_by,
    )


def _now() -> datetime:
    value = utc_now()
    if value.tzinfo is None or value.utcoffset() is None:
        raise OpportunityNoteError("processing_failed")
    return value.astimezone(UTC)


def _actor(actor: Any) -> str:
    try:
        return validate_actor(actor if isinstance(actor, str) else None)
    except BundleServiceError as error:
        raise OpportunityNoteError(error.code) from None


def _opportunity(session: Session, opportunity_id: Any) -> Opportunity:
    if not isinstance(opportunity_id, int) or isinstance(opportunity_id, bool):
        raise OpportunityNoteError("invalid_request")
    # 같은 사업기회의 노트 쓰기를 직렬화한다(같은 요청의 동시 재전송은 영수증을 본다).
    opportunity = session.get(Opportunity, opportunity_id, with_for_update=True)
    if opportunity is None:
        raise OpportunityNoteError("opportunity_not_found")
    if opportunity.merged_into_opportunity_id is not None:
        raise OpportunityNoteError("opportunity_merged")
    return opportunity


def _receipt(operation: str, *, opportunity_id: int, actor: str, request_id: UUID) -> UUID:
    return fence_receipt_id(
        _NOTE_RECEIPT_NAMESPACE,
        operation=operation,
        aggregate_type=NOTE_AGGREGATE_TYPE,
        aggregate_id=str(opportunity_id),
        claimed_name=actor,
        request_id=request_id,
    )


def _load(
    session: Session,
    operation: str,
    *,
    opportunity_id: int,
    actor: str,
    request_id: UUID,
    request_hash: str,
    expected_status: int,
) -> dict[str, Any] | None:
    try:
        return load_receipt(
            session,
            receipt=_receipt(operation, opportunity_id=opportunity_id, actor=actor, request_id=request_id),
            operation=operation,
            aggregate_type=NOTE_AGGREGATE_TYPE,
            aggregate_id=str(opportunity_id),
            claimed_name=actor,
            request_id=request_id,
            request_hash=request_hash,
            expected_status=expected_status,
        )
    except IdempotencyFenceError as error:
        raise OpportunityNoteError(error.code) from None


def _replay(snapshot: dict[str, Any], *, opportunity_id: int, note_id: UUID | None = None) -> NoteMutationResult:
    try:
        response = NoteView.model_validate(snapshot)
    except Exception as error:
        raise OpportunityNoteError("processing_failed") from error
    if note_id is not None and response.note_id != note_id:
        raise OpportunityNoteError("processing_failed")
    return NoteMutationResult(response=response, snapshot=snapshot, response_status=REPLAY_STATUS, replayed=True)


def _store(
    session: Session,
    operation: str,
    *,
    note: OpportunityNote,
    opportunity_id: int,
    actor: str,
    request_id: UUID,
    request_hash: str,
    response_status: int,
) -> NoteMutationResult:
    response = note_view(note)
    snapshot = response.model_dump(mode="json")
    try:
        session.add(
            new_receipt(
                receipt=_receipt(operation, opportunity_id=opportunity_id, actor=actor, request_id=request_id),
                operation=operation,
                aggregate_type=NOTE_AGGREGATE_TYPE,
                aggregate_id=str(opportunity_id),
                claimed_name=actor,
                request_id=request_id,
                request_hash=request_hash,
                snapshot=snapshot,
                response_status=response_status,
            )
        )
        session.flush()
    except (IntegrityError, IdempotencyFenceError) as error:
        raise OpportunityNoteError("processing_failed") from error
    return NoteMutationResult(response=response, snapshot=snapshot, response_status=response_status)


def create_note(
    session: Session,
    opportunity_id: int,
    *,
    kind: str,
    body: str,
    owner: str | None,
    request_id: UUID,
    actor: str,
) -> NoteMutationResult:
    """노트 또는 다음 행동을 덧붙인다. 새 노트는 201, 같은 요청의 재생은 200이다.

    검사 순서: 입력(422 `invalid_request`·400 actor) → 사업기회 404 → 병합 409 →
    같은 영수증 재생 / 409 `idempotency_conflict` → 저장.
    """

    if not isinstance(kind, str) or kind not in NOTE_KINDS or not isinstance(request_id, UUID):
        raise OpportunityNoteError("invalid_request")
    if not isinstance(body, str) or (owner is not None and not isinstance(owner, str)):
        raise OpportunityNoteError("invalid_request")
    try:
        clean_body = clean_note_body(body)
        clean_owner = clean_note_owner(owner)
    except ValueError:
        raise OpportunityNoteError("invalid_request") from None
    clean_actor = _actor(actor)
    resolved_owner = clean_owner if clean_owner is not None else clean_actor
    opportunity = _opportunity(session, opportunity_id)

    request_hash = request_sha256(
        {
            "operation": CREATE_OPERATION,
            "opportunity_id": opportunity.id,
            "kind": kind,
            "body": clean_body,
            "owner": resolved_owner,
            "actor": clean_actor,
        }
    )
    snapshot = _load(
        session,
        CREATE_OPERATION,
        opportunity_id=opportunity.id,
        actor=clean_actor,
        request_id=request_id,
        request_hash=request_hash,
        expected_status=CREATED_STATUS,
    )
    if snapshot is not None:
        return _replay(snapshot, opportunity_id=opportunity.id)

    note = OpportunityNote(
        opportunity_id=opportunity.id,
        kind=kind,
        body=clean_body,
        actor=clean_actor,
        owner=resolved_owner,
        created_at=_now(),
        done_at=None,
        done_by=None,
    )
    session.add(note)
    try:
        session.flush()
    except IntegrityError as error:
        raise OpportunityNoteError("processing_failed") from error
    return _store(
        session,
        CREATE_OPERATION,
        note=note,
        opportunity_id=opportunity.id,
        actor=clean_actor,
        request_id=request_id,
        request_hash=request_hash,
        response_status=CREATED_STATUS,
    )


def complete_note(
    session: Session,
    opportunity_id: int,
    note_id: UUID,
    *,
    request_id: UUID,
    actor: str,
) -> NoteMutationResult:
    """다음 행동을 완료한다(`done_by`=actor). 이미 완료됐으면 바꾸지 않고 200이다.

    검사 순서: 입력 → 사업기회 404 → 병합 409 → 노트 404 `not_found`(다른 사업기회의 노트
    포함) → `kind=note` 409 `note_not_action` → 같은 영수증 재생 / 409
    `idempotency_conflict` → 이미 완료면 현재 값 → 완료 저장.
    """

    if not isinstance(note_id, UUID) or not isinstance(request_id, UUID):
        raise OpportunityNoteError("invalid_request")
    clean_actor = _actor(actor)
    opportunity = _opportunity(session, opportunity_id)
    note = session.get(OpportunityNote, note_id, with_for_update=True)
    if note is None or note.opportunity_id != opportunity.id:
        raise OpportunityNoteError("not_found")
    if note.kind != "action":
        raise OpportunityNoteError("note_not_action")

    request_hash = request_sha256(
        {
            "operation": DONE_OPERATION,
            "opportunity_id": opportunity.id,
            "note_id": str(note_id),
            "actor": clean_actor,
        }
    )
    snapshot = _load(
        session,
        DONE_OPERATION,
        opportunity_id=opportunity.id,
        actor=clean_actor,
        request_id=request_id,
        request_hash=request_hash,
        expected_status=REPLAY_STATUS,
    )
    if snapshot is not None:
        return _replay(snapshot, opportunity_id=opportunity.id, note_id=note_id)
    if note.done_at is not None:
        # 완료는 한 번뿐이다. 다른 사람·다른 요청이어도 처음 완료를 그대로 보여 준다.
        response = note_view(note)
        return NoteMutationResult(
            response=response, snapshot=response.model_dump(mode="json"), response_status=REPLAY_STATUS
        )

    note.done_at = _now()
    note.done_by = clean_actor
    try:
        session.flush()
    except IntegrityError as error:
        raise OpportunityNoteError("processing_failed") from error
    return _store(
        session,
        DONE_OPERATION,
        note=note,
        opportunity_id=opportunity.id,
        actor=clean_actor,
        request_id=request_id,
        request_hash=request_hash,
        response_status=REPLAY_STATUS,
    )


__all__ = [
    "CREATE_OPERATION",
    "CREATED_STATUS",
    "DONE_OPERATION",
    "NOTE_AGGREGATE_TYPE",
    "NOTE_KINDS",
    "REPLAY_STATUS",
    "NoteMutationResult",
    "OpportunityNoteError",
    "complete_note",
    "create_note",
    "note_view",
]
