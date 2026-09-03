"""Screening execution creation and the frozen input boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets
from threading import RLock
from types import MappingProxyType
from typing import Any, Callable, Mapping, NamedTuple, Sequence
from uuid import uuid4
import weakref

from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import Settings, get_settings
from ..ingest.loader import parse_run_id
from ..models import CompanyProfileSnapshot, Notice, Run, ScreeningExecution, ScreeningPolicy
from .artifacts import ArtifactError, ArtifactStore, ExecutionWorkspace, aware_iso, canonical_bytes, sha256_bytes
from .contracts import MODEL_NAME
from ..core.generation_config import GenerationConfig, generation_config_from_settings
from .ollama import ModelInspectionError, OllamaClient
from .policy import canonical_policy_bytes, policy_content_digest
from .profile_snapshot import (
    BASELINE_COMMIT,
    ProfileSnapshotError,
    create_profile_snapshot,
    read_profile_snapshot,
)
from .queue import ScreeningQueue, QueueValidationError, TRIGGER_SCOPES


COMMON_NOTICE_KEYS = (
    "notice_id", "source_type", "title", "agency", "method", "url",
    "collection_bucket", "published_at", "deadline_at", "budget",
    "estimated_price", "procurement_class", "region_limit", "lifecycle",
    "qualification_flags", "attachments", "focus_matches",
    "performance_matches", "performance_top_score", "candidate_sources",
    "unknown_fields", "sample_stratum", "sample_role", "raw_source",
)
SAMPLE_METADATA_KEYS = frozenset({"sample_stratum", "sample_role"})
JUDGMENT_MODES = {"신규", "재판정", "승계"}
REJUDGE_REASONS = {"정정", "재공고", "본공고 전환", "담당자 요청"}
EXECUTION_RE = re.compile(r"^scr-[0-9a-f]{32}$")


class ScreeningCreationError(ValueError):
    """A safe pre-enqueue validation error."""

    def __init__(self, code: str, message: str = "screening input is invalid") -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CreatedExecution:
    execution_id: str
    status: str
    model_name: str
    model_digest: str
    profile_version: str
    profile_digest: str
    artifact_dir: str
    input_artifact_path: str
    input_artifact_digest: str
    generation_config_digest: str | None = None


@dataclass(frozen=True)
class PreparedExecution:
    """An execution prepared in, but not committed from, a caller session."""

    created: CreatedExecution
    row: ScreeningExecution
    workspace: ExecutionWorkspace


_QUALITY_BINDING_CAPABILITY = object()
_QUALITY_BINDING_FACTORY_CAPABILITY = object()


def _freeze_quality_value(value: Any) -> Any:
    """Freeze the trusted quality projection before it crosses this API."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_quality_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_quality_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_quality_value(item) for item in value)
    return value


def _thaw_quality_value(value: Any) -> Any:
    """Build ordinary JSON containers for the immutable execution artifact."""

    if isinstance(value, Mapping):
        return {key: _thaw_quality_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw_quality_value(item) for item in value]
    if isinstance(value, (frozenset, set)):
        return [_thaw_quality_value(item) for item in value]
    return value


def _quality_value_is_frozen(value: Any) -> bool:
    if isinstance(value, Mapping):
        return type(value) is MappingProxyType and all(_quality_value_is_frozen(item) for item in value.values())
    if isinstance(value, tuple):
        return all(_quality_value_is_frozen(item) for item in value)
    if isinstance(value, frozenset):
        return all(_quality_value_is_frozen(item) for item in value)
    return True


@dataclass(frozen=True, slots=True, init=False, eq=False, weakref_slot=True)
class _QualitySampleBinding:
    """Raw-byte capability issued by the quality-gate service.

    Issuer facts are deliberately absent from this object.  They are held in
    the identity registry below, so copying, replacing, unpickling, or
    mutating this handle cannot manufacture a trusted binding.
    """

    sample_raw: bytes
    baseline_raw: bytes
    results_raw: bytes

    def __init__(
        self,
        *,
        capability: object,
        sample_raw: bytes,
        baseline_raw: bytes,
        results_raw: bytes,
    ) -> None:
        if capability is not _QUALITY_BINDING_CAPABILITY or not all(
            isinstance(value, bytes) for value in (sample_raw, baseline_raw, results_raw)
        ):
            raise TypeError("quality sample binding is internal")
        object.__setattr__(self, "sample_raw", bytes(sample_raw))
        object.__setattr__(self, "baseline_raw", bytes(baseline_raw))
        object.__setattr__(self, "results_raw", bytes(results_raw))

    @property
    def run_id(self) -> str:
        return _binding_facts(self).run_id

    @property
    def source_window(self) -> Mapping[str, Any]:
        return _binding_facts(self).source_window

    @property
    def notices(self) -> tuple[Mapping[str, Any], ...]:
        return _binding_facts(self).notices

    @property
    def sample_digest(self) -> str:
        return _binding_facts(self).sample_digest

    @property
    def baseline_digest(self) -> str:
        return _binding_facts(self).baseline_digest

    @property
    def results_digest(self) -> str:
        return _binding_facts(self).results_digest

    @property
    def source_token(self) -> object:
        source = _binding_facts(self).source_ref()
        if source is None:
            raise ScreeningCreationError("input_error")
        return source


@dataclass(frozen=True, slots=True, init=False, eq=False, weakref_slot=True)
class _BindingLease:
    """Opaque, one-shot authorization for a single binding reservation.

    The issuer is the only code that can construct a lease.  The fields are
    intentionally immutable, but the issuer still authenticates every field
    because object.__setattr__ and copied instances must not become valid
    transaction authorizations.
    """

    binding_identity: int
    generation: int
    previous_tag: bytes
    session_identity: int | None
    transaction_identity: int | None
    reservation_transaction_identity: int | None
    nonce: bytes
    tag: bytes

    def __init__(self, **_kwargs: Any) -> None:
        raise TypeError("binding lease is internal")


class _BindingIssuer(NamedTuple):
    """Immutable view over closure-owned binding state."""

    lookup_fn: Callable[[Any], tuple[Any, str] | None]
    reserve_fn: Callable[[Any, int | None, int | None, int | None], _BindingLease | None]
    finalize_fn: Callable[[Any, _BindingLease, int | None, int | None, Any, Any, object], Any | None]
    release_fn: Callable[[Any, _BindingLease, int | None, int | None, Any, Any, object], Any | None]

    def entry(self, value: Any) -> tuple[Any, str] | None:
        return self.lookup_fn(value)

    def reserve(
        self,
        value: Any,
        *,
        session_identity: int | None = None,
        transaction_identity: int | None = None,
        reservation_transaction_identity: int | None = None,
    ) -> _BindingLease | None:
        return self.reserve_fn(
            value,
            session_identity,
            transaction_identity,
            reservation_transaction_identity,
        )

    def finalize(
        self,
        value: Any,
        lease: _BindingLease,
        *,
        session_identity: int | None,
        transaction_identity: int | None,
        transaction: Any,
        event_transaction: Any,
        authorization: object,
    ) -> Any | None:
        return self.finalize_fn(
            value,
            lease,
            session_identity,
            transaction_identity,
            transaction,
            event_transaction,
            authorization,
        )

    def release(
        self,
        value: Any,
        lease: _BindingLease,
        *,
        session_identity: int | None,
        transaction_identity: int | None,
        transaction: Any,
        event_transaction: Any,
        authorization: object,
    ) -> Any | None:
        return self.release_fn(
            value,
            lease,
            session_identity,
            transaction_identity,
            transaction,
            event_transaction,
            authorization,
        )


class _IssuerRecord(NamedTuple):
    reference: weakref.ReferenceType[Any]
    facts: Any
    state: str
    generation: int
    tag: bytes
    lease_reference: weakref.ReferenceType[_BindingLease] | None
    lease_digest: bytes | None


class _TagVerifier(NamedTuple):
    sign_fn: Callable[[bytes], bytes]
    verify_fn: Callable[[bytes, bytes], bool]

    def sign(self, payload: bytes) -> bytes:
        return self.sign_fn(payload)

    def verify(self, payload: bytes, tag: bytes) -> bool:
        return self.verify_fn(payload, tag)


def _make_tag_verifier() -> _TagVerifier:
    # Keep the key in a verifier boundary separate from the issuer lookup
    # closure.  The issuer exposes neither the key nor its mutable map.
    secret = secrets.token_bytes(32)

    def sign(payload: bytes) -> bytes:
        return hmac.new(secret, payload, hashlib.sha256).digest()

    def verify(payload: bytes, tag: bytes) -> bool:
        return isinstance(tag, bytes) and hmac.compare_digest(sign(payload), tag)

    return _TagVerifier(sign, verify)


def _tag_payload(*values: Any) -> bytes:
    chunks: list[bytes] = []
    for value in values:
        if isinstance(value, bytes):
            encoded = b"b:" + value
        elif isinstance(value, (tuple, list)):
            encoded = b"j:" + json.dumps(
                value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        else:
            encoded = b"s:" + str(value).encode("utf-8")
        chunks.append(len(encoded).to_bytes(8, "big") + encoded)
    return b"".join(chunks)


def _make_binding_issuer(
    payload_fn: Callable[[Any, Any, str, int, bytes | None], bytes], verifier: _TagVerifier
) -> tuple[_BindingIssuer, Callable[[Any, Any], None], object, object, object, object]:
    lock = RLock()
    entries: dict[int, _IssuerRecord] = {}
    finalize_authorization = object()
    release_authorization = object()
    rollback_event_authorization = object()

    def lease_payload(
        value: Any,
        generation: int,
        previous_tag: bytes,
        session_identity: int | None,
        transaction_identity: int | None,
        reservation_transaction_identity: int | None,
        nonce: bytes,
    ) -> bytes:
        return _tag_payload(
            "binding-lease-v1",
            id(value),
            generation,
            previous_tag,
            session_identity,
            transaction_identity,
            reservation_transaction_identity,
            nonce,
        )

    def lease_digest(lease: _BindingLease) -> bytes:
        return hashlib.sha256(
            _tag_payload(
                "binding-lease-digest-v1",
                lease.binding_identity,
                lease.generation,
                lease.previous_tag,
                lease.session_identity,
                lease.transaction_identity,
                lease.reservation_transaction_identity,
                lease.nonce,
                lease.tag,
            )
        ).digest()

    def valid(value: Any, record: Any) -> bool:
        try:
            return (
                isinstance(record, _IssuerRecord)
                and record.reference() is value
                and verifier.verify(
                    payload_fn(
                        value,
                        record.facts,
                        record.state,
                        record.generation,
                        record.lease_digest,
                    ),
                    record.tag,
                )
            )
        except (AttributeError, TypeError, ValueError, OverflowError, KeyError):
            return False

    def entry(value: Any) -> tuple[Any, str] | None:
        key = id(value)
        with lock:
            registered = entries.get(key)
            if registered is None or not valid(value, registered):
                if registered is not None:
                    entries.pop(key, None)
                return None
            return registered.facts, registered.state

    def register(value: Any, facts: Any, state: str = "issued") -> None:
        key = id(value)

        def cleanup(reference: weakref.ReferenceType[Any]) -> None:
            with lock:
                registered = entries.get(key)
                if registered is not None and registered.reference is reference:
                    entries.pop(key, None)

        reference = weakref.ref(value, cleanup)
        with lock:
            registered = entries.get(key)
            if registered is not None and registered.reference() is not None:
                raise RuntimeError("issuer identity is already registered")
            generation = 0
            tag = verifier.sign(payload_fn(value, facts, state, generation, None))
            entries[key] = _IssuerRecord(reference, facts, state, generation, tag, None, None)

    def reserve(
        value: Any,
        session_identity: int | None,
        transaction_identity: int | None,
        reservation_transaction_identity: int | None,
    ) -> _BindingLease | None:
        key = id(value)
        with lock:
            registered = entries.get(key)
            if registered is None or not valid(value, registered):
                if registered is not None:
                    entries.pop(key, None)
                return None
            if registered.state != "issued":
                return None
            generation = registered.generation + 1
            nonce = secrets.token_bytes(32)
            lease_tag = verifier.sign(
                lease_payload(
                    value,
                    generation,
                    registered.tag,
                    session_identity,
                    transaction_identity,
                    reservation_transaction_identity,
                    nonce,
                )
            )
            lease = object.__new__(_BindingLease)
            object.__setattr__(lease, "binding_identity", id(value))
            object.__setattr__(lease, "generation", generation)
            object.__setattr__(lease, "previous_tag", bytes(registered.tag))
            object.__setattr__(lease, "session_identity", session_identity)
            object.__setattr__(lease, "transaction_identity", transaction_identity)
            object.__setattr__(
                lease,
                "reservation_transaction_identity",
                reservation_transaction_identity,
            )
            object.__setattr__(lease, "nonce", bytes(nonce))
            object.__setattr__(lease, "tag", bytes(lease_tag))
            digest = lease_digest(lease)
            tag = verifier.sign(
                payload_fn(value, registered.facts, "reserved", generation, digest)
            )
            entries[key] = _IssuerRecord(
                registered.reference,
                registered.facts,
                "reserved",
                generation,
                tag,
                weakref.ref(lease),
                digest,
            )
            return lease

    def move(
        value: Any,
        lease: _BindingLease,
        expected: str,
        replacement: str,
        session_identity: int | None,
        transaction_identity: int | None,
        transaction: Any,
        event_transaction: Any,
        authorization: object,
        expected_authorization: object,
        event_authorization: object | None = None,
    ) -> Any | None:
        key = id(value)
        with lock:
            registered = entries.get(key)
            if registered is None or not valid(value, registered):
                if registered is not None:
                    entries.pop(key, None)
                return None
            if registered.state != expected or (
                authorization is not expected_authorization
                and authorization is not event_authorization
            ):
                return None
            try:
                if (
                    type(lease) is not _BindingLease
                    or registered.lease_reference is None
                    or registered.lease_reference() is not lease
                    or not isinstance(registered.lease_digest, bytes)
                    or not hmac.compare_digest(registered.lease_digest, lease_digest(lease))
                    or lease.binding_identity != id(value)
                    or lease.generation != registered.generation
                    or lease.session_identity != session_identity
                    or lease.transaction_identity != transaction_identity
                    or not verifier.verify(
                        lease_payload(
                            value,
                            lease.generation,
                            lease.previous_tag,
                            lease.session_identity,
                            lease.transaction_identity,
                            lease.reservation_transaction_identity,
                            lease.nonce,
                        ),
                        lease.tag,
                    )
                ):
                    return None
                if transaction is None:
                    if (
                        event_transaction is not None
                        or lease.session_identity is not None
                        or lease.transaction_identity is not None
                    ):
                        return None
                elif event_transaction is None:
                    return None
                elif replacement == "used":
                    if (
                        event_transaction is not transaction
                        or event_transaction.parent is not None
                        or event_transaction.is_active
                    ):
                        return None
                elif authorization is not event_authorization:
                    return None
                elif event_transaction is transaction:
                    if transaction.is_active:
                        return None
                elif (
                    not getattr(event_transaction, "nested", False)
                    or id(event_transaction) != lease.reservation_transaction_identity
                    or event_transaction.is_active
                ):
                    return None
            except (AttributeError, TypeError, ValueError, OverflowError, KeyError):
                return None
            generation = registered.generation + 1
            tag = verifier.sign(payload_fn(value, registered.facts, replacement, generation, None))
            entries[key] = _IssuerRecord(
                registered.reference, registered.facts, replacement, generation, tag, None, None
            )
            return registered.facts

    def finalize(
        value: Any,
        lease: _BindingLease,
        session_identity: int | None,
        transaction_identity: int | None,
        transaction: Any,
        event_transaction: Any,
        authorization: object,
    ) -> Any | None:
        return move(
            value,
            lease,
            "reserved",
            "used",
            session_identity,
            transaction_identity,
            transaction,
            event_transaction,
            authorization,
            finalize_authorization,
        )

    def release(
        value: Any,
        lease: _BindingLease,
        session_identity: int | None,
        transaction_identity: int | None,
        transaction: Any,
        event_transaction: Any,
        authorization: object,
    ) -> Any | None:
        return move(
            value,
            lease,
            "reserved",
            "issued",
            session_identity,
            transaction_identity,
            transaction,
            event_transaction,
            authorization,
            release_authorization,
            rollback_event_authorization,
        )

    return (
        _BindingIssuer(entry, reserve, finalize, release),
        register,
        finalize_authorization,
        release_authorization,
        rollback_event_authorization,
    )


class _BindingFacts(NamedTuple):
    run_id: str
    source_window: Mapping[str, Any]
    notices: tuple[Mapping[str, Any], ...]
    sample_raw: bytes
    baseline_raw: bytes
    results_raw: bytes
    sample_digest: str
    baseline_digest: str
    results_digest: str
    source_ref: weakref.ReferenceType[Any]
    source_identity: int
    source_root: Path
    source_root_identity: tuple[int, int]
    source_canonical_run_id: str


def _binding_tag_payload(
    binding: _QualitySampleBinding,
    facts: _BindingFacts,
    state: str,
    generation: int,
    lease_digest: bytes | None,
) -> bytes:
    return _tag_payload(
        "binding-v1",
        id(binding),
        facts.run_id,
        facts.source_identity,
        str(facts.source_root),
        facts.source_root_identity,
        facts.source_canonical_run_id,
        facts.sample_raw,
        facts.baseline_raw,
        facts.results_raw,
        facts.sample_digest,
        facts.baseline_digest,
        facts.results_digest,
        state,
        generation,
        lease_digest,
    )


_BINDING_VERIFIER = _make_tag_verifier()
(
    _BINDING_ISSUER,
    _binding_register,
    _binding_finalize_authorization,
    _binding_release_authorization,
    _binding_rollback_event_authorization,
) = _make_binding_issuer(
    _binding_tag_payload, _BINDING_VERIFIER
)


def _binding_registry_entry(
    binding: Any, issuer: _BindingIssuer = _BINDING_ISSUER
) -> _BindingFacts | None:
    if type(binding) is not _QualitySampleBinding:
        return None
    entry = issuer.entry(binding)
    return None if entry is None else entry[0]


def _binding_registry_state(
    binding: Any, issuer: _BindingIssuer = _BINDING_ISSUER
) -> str | None:
    if type(binding) is not _QualitySampleBinding:
        return None
    entry = issuer.entry(binding)
    return None if entry is None else entry[1]


def _binding_facts(binding: _QualitySampleBinding) -> _BindingFacts:
    facts = _binding_registry_entry(binding)
    if facts is None:
        raise ScreeningCreationError("input_error")
    return facts


def _register_quality_binding(
    binding: _QualitySampleBinding,
    facts: _BindingFacts,
    register: Callable[[Any, Any], None] = _binding_register,
) -> None:
    register(binding, facts)


class _PendingQualityBinding(NamedTuple):
    binding: _QualitySampleBinding
    lease: _BindingLease
    transaction: Any
    outer_transaction: Any


def _make_quality_binding_lifecycle() -> tuple[
    Callable[[Session, _QualitySampleBinding, _BindingLease], None],
    Callable[[Session, _QualitySampleBinding], _PendingQualityBinding | None],
    Callable[[Session], tuple[_PendingQualityBinding, ...]],
    Callable[[Session, Any], tuple[_PendingQualityBinding, ...]],
    Callable[[Session], bool],
    Callable[[Session, Any], None],
    Callable[[Session, Any], bool],
]:
    """Keep active receipts in a listener-owned, non-session surface."""

    lock = RLock()
    pending_by_session: weakref.WeakKeyDictionary[
        Session, dict[int, _PendingQualityBinding]
    ] = weakref.WeakKeyDictionary()
    nested_commits_by_session: weakref.WeakKeyDictionary[Session, set[int]] = (
        weakref.WeakKeyDictionary()
    )

    def track(session: Session, binding: _QualitySampleBinding, lease: _BindingLease) -> None:
        nested = session.get_nested_transaction()
        outer = session.get_transaction()
        transaction = nested or outer
        if transaction is None or outer is None:
            raise ScreeningCreationError("input_error")
        with lock:
            pending = pending_by_session.setdefault(session, {})
            if id(binding) in pending:
                raise ScreeningCreationError("input_error")
            pending[id(binding)] = _PendingQualityBinding(binding, lease, transaction, outer)

    def untrack(
        session: Session, binding: _QualitySampleBinding
    ) -> _PendingQualityBinding | None:
        with lock:
            pending = pending_by_session.get(session)
            if pending is None:
                return None
            item = pending.pop(id(binding), None)
            if not pending:
                pending_by_session.pop(session, None)
            return item

    def pop_all(session: Session) -> tuple[_PendingQualityBinding, ...]:
        with lock:
            nested_commits_by_session.pop(session, None)
            pending = pending_by_session.pop(session, None)
            if pending is None:
                return ()
            return tuple(pending.values())

    def pop_nested(session: Session, nested: Any) -> tuple[_PendingQualityBinding, ...]:
        with lock:
            pending = pending_by_session.get(session)
            if pending is None:
                return ()
            affected = tuple(
                item
                for item in pending.values()
                if item.transaction is nested
            )
            for item in affected:
                pending.pop(id(item.binding), None)
            if not pending:
                pending_by_session.pop(session, None)
            return affected

    def has_pending(session: Session) -> bool:
        with lock:
            return bool(pending_by_session.get(session))

    def mark_nested_commit(session: Session, nested: Any) -> None:
        with lock:
            nested_commits_by_session.setdefault(session, set()).add(id(nested))

    def consume_nested_commit(session: Session, nested: Any) -> bool:
        with lock:
            committed = nested_commits_by_session.get(session)
            if committed is None or id(nested) not in committed:
                return False
            committed.remove(id(nested))
            if not committed:
                nested_commits_by_session.pop(session, None)
            return True

    return (
        track,
        untrack,
        pop_all,
        pop_nested,
        has_pending,
        mark_nested_commit,
        consume_nested_commit,
    )


(
    _track_quality_binding,
    _untrack_quality_binding,
    _pop_quality_bindings,
    _pop_nested_quality_bindings,
    _has_pending_quality_bindings,
    _mark_nested_quality_binding_commit,
    _consume_nested_quality_binding_commit,
) = _make_quality_binding_lifecycle()


def _finalize_quality_bindings(
    session: Session,
    *,
    committed: bool,
    event_transaction: Any = None,
    _event_release_authorization: object = _binding_rollback_event_authorization,
) -> None:
    # SQLAlchemy fires after_commit/after_rollback for savepoints as well as
    # the outer transaction.  During the callback the outer transaction may
    # still be visible through ``in_transaction()``; nested savepoints are
    # instead identified by ``in_nested_transaction()``.  A nested rollback
    # changes only reservations made in that savepoint; the outer event
    # changes the remaining reservations, making session reuse leak-free.
    if event_transaction is None:
        event_transaction = session.get_transaction()
    if event_transaction is None:
        return
    if committed:
        if (
            event_transaction.parent is not None
            or event_transaction.is_active
        ):
            return
        pending = _pop_quality_bindings(session)
    elif event_transaction.parent is not None:
        # A savepoint rollback is reported by after_soft_rollback after the
        # savepoint is closed.  Its lease is still bound to the outer
        # transaction, but this closed savepoint is the rollback receipt.
        if (
            not getattr(event_transaction, "nested", False)
            or event_transaction.is_active
        ):
            return
        pending = _pop_nested_quality_bindings(session, event_transaction)
    else:
        if event_transaction.is_active:
            return
        pending = _pop_quality_bindings(session)
    for item in pending:
        if committed:
            try:
                _commit_quality_binding(
                    item.binding,
                    item.lease,
                    session=session,
                    transaction=item.outer_transaction,
                    event_transaction=event_transaction,
                )
            except ScreeningCreationError:
                # A tag failure revokes the entry and the durable row remains
                # auditable; never turn an already-committed SQL transaction
                # into a misleading caller failure.
                continue
        else:
            _release_quality_binding(
                item.binding,
                item.lease,
                session=session,
                transaction=item.outer_transaction,
                event_transaction=event_transaction,
                _authorization=_event_release_authorization,
            )


@event.listens_for(Session, "after_commit")
def _quality_binding_after_commit(session: Session) -> None:
    # A nested commit has no transaction argument in this event, but the
    # documented session view still exposes its now-inactive savepoint until
    # after_transaction_end. Mark it so that an explicit ``close`` (which
    # has no rollback event) can be distinguished from a committed savepoint.
    nested = session.get_nested_transaction()
    if nested is not None and not nested.is_active:
        _mark_nested_quality_binding_commit(session, nested)
        return
    _finalize_quality_bindings(session, committed=True, event_transaction=session.get_transaction())


@event.listens_for(Session, "after_rollback")
def _quality_binding_after_rollback(session: Session) -> None:
    _finalize_quality_bindings(session, committed=False, event_transaction=session.get_transaction())


@event.listens_for(Session, "after_soft_rollback")
def _quality_binding_after_soft_rollback(session: Session, transaction: Any) -> None:
    if getattr(transaction, "parent", None) is not None:
        _finalize_quality_bindings(
            session,
            committed=False,
            event_transaction=transaction,
        )


@event.listens_for(Session, "after_transaction_end")
def _quality_binding_after_transaction_end(session: Session, transaction: Any) -> None:
    # Session.close()/invalidate() can end an outer transaction without
    # emitting after_rollback.  If commit/rollback already finalized the
    # pending list this is a no-op; otherwise the abandoned transaction has
    # no durable execution and every reservation must be released.
    if transaction.parent is not None:
        if _consume_nested_quality_binding_commit(session, transaction):
            return
        if _has_pending_quality_bindings(session):
            _finalize_quality_bindings(
                session,
                committed=False,
                event_transaction=transaction,
            )
        return
    if _has_pending_quality_bindings(session):
        _finalize_quality_bindings(
            session,
            committed=False,
            event_transaction=transaction,
        )


def _validate_quality_binding(
    binding: _QualitySampleBinding, run_id: str, project_root: Path | str
) -> tuple[_BindingFacts, object]:
    """Validate an issued binding without consuming its retry capability."""

    from .quality_gate import (
        FIXED_BASELINE_DIGEST,
        FIXED_RESULTS_DIGEST,
        FIXED_SAMPLE_DIGEST,
        _FixedInputSnapshot,
        _absolute_root,
        _snapshot_matches_raw,
        _snapshot_registry_entry,
        _trusted_root_identity,
    )

    if _binding_registry_state(binding) != "issued":
        raise ScreeningCreationError("input_error")
    facts = _binding_registry_entry(binding)
    if facts is None:
        raise ScreeningCreationError("input_error")
    if (
        not isinstance(binding.sample_raw, bytes)
        or not isinstance(binding.baseline_raw, bytes)
        or not isinstance(binding.results_raw, bytes)
        or binding.sample_raw != facts.sample_raw
        or binding.baseline_raw != facts.baseline_raw
        or binding.results_raw != facts.results_raw
        or facts.sample_digest != FIXED_SAMPLE_DIGEST
        or facts.baseline_digest != FIXED_BASELINE_DIGEST
        or facts.results_digest != FIXED_RESULTS_DIGEST
        or sha256_bytes(binding.sample_raw) != FIXED_SAMPLE_DIGEST
        or sha256_bytes(binding.baseline_raw) != FIXED_BASELINE_DIGEST
        or sha256_bytes(binding.results_raw) != FIXED_RESULTS_DIGEST
        or facts.run_id != run_id
    ):
        raise ScreeningCreationError("input_error")
    source = facts.source_ref()
    if type(source) is not _FixedInputSnapshot or not _snapshot_matches_raw(source):
        raise ScreeningCreationError("input_error")
    source_facts = _snapshot_registry_entry(source)
    if (
        source_facts is None
        or source_facts.canonical_run_id != run_id
        or source_facts.root != _absolute_root(project_root)
        or source_facts.root_identity != _trusted_root_identity(project_root)
        or facts.source_identity != id(source)
        or facts.source_root != source_facts.root
        or facts.source_root_identity != source_facts.root_identity
        or facts.source_canonical_run_id != source_facts.canonical_run_id
        or facts.sample_raw != source_facts.sample_raw
        or facts.baseline_raw != source_facts.baseline_raw
        or facts.results_raw != source_facts.results_raw
        or facts.source_window != source_facts.sample.get("source_window")
        or facts.notices != tuple(source_facts.sample.get("notices", ()))
    ):
        raise ScreeningCreationError("input_error")
    return facts, source


def _reserve_quality_binding(
    binding: _QualitySampleBinding,
    run_id: str,
    project_root: Path | str,
    *,
    session: Session | None = None,
    issuer: _BindingIssuer = _BINDING_ISSUER,
) -> tuple[_BindingFacts, object, _BindingLease]:
    """Atomically move one validated issuer binding from issued to reserved."""

    facts, source = _validate_quality_binding(binding, run_id, project_root)
    outer_transaction = session.get_transaction() if session is not None else None
    reservation_transaction = (
        (session.get_nested_transaction() or outer_transaction)
        if session is not None
        else None
    )
    if session is not None and outer_transaction is None:
        raise ScreeningCreationError("input_error")
    lease = issuer.reserve(
        binding,
        session_identity=id(session) if session is not None else None,
        transaction_identity=id(outer_transaction) if outer_transaction is not None else None,
        reservation_transaction_identity=(
            id(reservation_transaction) if reservation_transaction is not None else None
        ),
    )
    if lease is None:
        raise ScreeningCreationError("input_error")
    if session is not None:
        try:
            _track_quality_binding(session, binding, lease)
        except Exception:
            # A tracking failure must not create an active-transaction
            # release bypass. End the caller transaction first, then use the
            # same inactive transaction receipt as the event listeners.
            try:
                session.rollback()
            except Exception:
                pass
            issuer.release(
                binding,
                lease,
                session_identity=id(session),
                transaction_identity=id(outer_transaction),
                transaction=outer_transaction,
                event_transaction=outer_transaction,
                authorization=_binding_rollback_event_authorization,
            )
            raise
    return facts, source, lease


def _release_quality_binding(
    binding: _QualitySampleBinding,
    lease: _BindingLease,
    *,
    session: Session | None = None,
    transaction: Any = None,
    event_transaction: Any = None,
    issuer: _BindingIssuer = _BINDING_ISSUER,
    _authorization: object = _binding_release_authorization,
) -> bool:
    """Return a reservation to issued when no persistent row was published."""

    released = issuer.release(
        binding,
        lease,
        session_identity=id(session) if session is not None else None,
        transaction_identity=id(transaction) if transaction is not None else None,
        transaction=transaction,
        event_transaction=event_transaction,
        authorization=_authorization,
    )
    if released is not None and session is not None:
        _untrack_quality_binding(session, binding)
    return released is not None


def _commit_quality_binding(
    binding: _QualitySampleBinding,
    lease: _BindingLease,
    *,
    session: Session | None = None,
    transaction: Any = None,
    event_transaction: Any = None,
    issuer: _BindingIssuer = _BINDING_ISSUER,
    _finalize_authorization: object = _binding_finalize_authorization,
) -> None:
    """Finalize a reservation after the execution row is published."""

    if (
        issuer.finalize(
            binding,
            lease,
            session_identity=id(session) if session is not None else None,
            transaction_identity=id(transaction) if transaction is not None else None,
            transaction=transaction,
            event_transaction=event_transaction,
            authorization=_finalize_authorization,
        )
        is None
    ):
        raise ScreeningCreationError("input_error")


def _consume_quality_binding(
    binding: _QualitySampleBinding, run_id: str, project_root: Path | str
) -> tuple[_BindingFacts, object]:
    """Compatibility helper that reserves and immediately consumes a binding."""

    facts, source, lease = _reserve_quality_binding(binding, run_id, project_root)
    try:
        _commit_quality_binding(binding, lease)
    except Exception:
        _release_quality_binding(binding, lease)
        raise
    return facts, source


del _binding_register
del _BINDING_VERIFIER
del _binding_finalize_authorization
del _binding_release_authorization


def _make_quality_sample_binding(
    run_id: str,
    *,
    source_token: object,
    capability: object,
) -> _QualitySampleBinding:
    """Issue a binding only from a registered secure snapshot."""

    if capability is not _QUALITY_BINDING_FACTORY_CAPABILITY:
        raise TypeError("quality sample binding factory is internal")
    from .quality_gate import _FixedInputSnapshot, _snapshot_matches_raw, _snapshot_registry_entry

    if type(source_token) is not _FixedInputSnapshot or not _snapshot_matches_raw(source_token):
        raise TypeError("quality sample binding is invalid")
    snapshot_facts = _snapshot_registry_entry(source_token)
    if snapshot_facts is None or not isinstance(run_id, str) or run_id != snapshot_facts.canonical_run_id:
        raise TypeError("quality sample binding is invalid")
    source_window = snapshot_facts.sample.get("source_window")
    notices = snapshot_facts.sample.get("notices")
    frozen_window = _freeze_quality_value(source_window)
    frozen_notices = tuple(_freeze_quality_value(item) for item in notices) if isinstance(notices, (list, tuple)) else ()
    if (
        not isinstance(frozen_window, Mapping)
        or len(frozen_notices) != 40
        or not _quality_value_is_frozen(frozen_window)
        or not all(isinstance(item, Mapping) and _quality_value_is_frozen(item) for item in frozen_notices)
    ):
        raise TypeError("quality sample binding is invalid")
    binding = _QualitySampleBinding(
        capability=_QUALITY_BINDING_CAPABILITY,
        sample_raw=snapshot_facts.sample_raw,
        baseline_raw=snapshot_facts.baseline_raw,
        results_raw=snapshot_facts.results_raw,
    )
    _register_quality_binding(
        binding,
        _BindingFacts(
            run_id=run_id,
            source_window=frozen_window,
            notices=frozen_notices,
            sample_raw=bytes(snapshot_facts.sample_raw),
            baseline_raw=bytes(snapshot_facts.baseline_raw),
            results_raw=bytes(snapshot_facts.results_raw),
            sample_digest=snapshot_facts.sample_digest,
            baseline_digest=snapshot_facts.baseline_digest,
            results_digest=snapshot_facts.results_digest,
            source_ref=weakref.ref(source_token),
            source_identity=id(source_token),
            source_root=snapshot_facts.root,
            source_root_identity=snapshot_facts.root_identity,
            source_canonical_run_id=snapshot_facts.canonical_run_id,
        ),
    )
    return binding


def _now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScreeningCreationError("input_error", "clock must return an aware timestamp")
    return value


def _json_file(path: Path, code: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ScreeningCreationError(code) from None
    if not isinstance(value, dict):
        raise ScreeningCreationError(code)
    return value


def _safe_run_directory(settings: Settings, run_id: str) -> Path:
    if not isinstance(run_id, str) or not run_id.strip() or "\\" in run_id or Path(run_id).name != run_id:
        raise ScreeningCreationError("input_error")
    parsed = parse_run_id(run_id)
    name = parsed[0] if parsed else run_id.split("--", 1)[0]
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ScreeningCreationError("input_error")
    configured_root = Path(settings.bidops_root)
    if configured_root.is_symlink():
        raise ScreeningCreationError("input_error")
    root = configured_root.resolve()
    runs = root / "data" / "runs"
    for component in (root / "data", runs):
        if component.exists() and component.is_symlink():
            raise ScreeningCreationError("input_error")
    directory = runs / name
    try:
        directory.resolve().relative_to(runs.resolve())
    except (OSError, ValueError):
        raise ScreeningCreationError("input_error") from None
    if directory.is_symlink() or not directory.is_dir():
        raise ScreeningCreationError("input_error")
    return directory


def _policy_body(row: ScreeningPolicy) -> dict[str, Any]:
    body = {
        "schema_version": row.schema_version,
        "policy_version": row.policy_version,
        "prompt_version": row.prompt_version,
        "perspective_prompts": row.perspective_prompts_json,
        "counterargument_prompt": row.counterargument_prompt_json,
        "synthesis_prompt": row.synthesis_prompt_json,
        "candidate_selection": row.candidate_selection_json,
        "thresholds": row.thresholds_json,
    }
    try:
        canonical = canonical_policy_bytes(body)
    except Exception:
        raise ScreeningCreationError("policy_mismatch") from None
    if sha256_bytes(canonical) != row.content_digest:
        raise ScreeningCreationError("policy_mismatch")
    return body


def _notice_common(value: Any, *, require_sample_metadata: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ScreeningCreationError("input_error")
    # Collection output predates validation sampling and may omit the two
    # sample annotations.  They are optional in the ingest contract; preserve
    # their absence as explicit nulls instead of rejecting the notice or
    # inventing a stratum/role before the sample stage.
    required_keys = set(COMMON_NOTICE_KEYS).difference(SAMPLE_METADATA_KEYS)
    if require_sample_metadata:
        required_keys.update(SAMPLE_METADATA_KEYS)
    if not required_keys.issubset(value) or set(value).difference(COMMON_NOTICE_KEYS):
        raise ScreeningCreationError("input_error")
    result = {key: value.get(key) for key in COMMON_NOTICE_KEYS}
    if not isinstance(result["notice_id"], str) or not result["notice_id"].strip():
        raise ScreeningCreationError("input_error")
    raw_source = result["raw_source"]
    if not isinstance(raw_source, str) or not raw_source or raw_source.startswith("/") or "\\" in raw_source:
        raise ScreeningCreationError("input_error")
    raw_parts = raw_source.split("/")
    if any(part in {"", ".", ".."} or ":" in part for part in raw_parts):
        raise ScreeningCreationError("input_error")
    _validate_collected_notice(result)
    if require_sample_metadata and (
        not isinstance(result["sample_stratum"], str)
        or result["sample_stratum"] not in _SAMPLE_STRATA
        or not isinstance(result["sample_role"], str)
        or result["sample_role"] not in _SAMPLE_ROLES
    ):
        raise ScreeningCreationError("input_error")
    return result


_PROCUREMENT_KEYS = ("large", "middle", "detail", "code")
_REGION_KEYS = ("basis", "joint_contract_regions", "joint_contract_rate", "regional_joint_contract_limit")
_LIFECYCLE_KEYS = ("pre_spec_no", "re_notice", "changed_at", "change_reason", "unified_notice_no", "previous_failed_notice_no")
_QUALIFICATION_KEYS = ("participation_limited", "industry_limited", "information_business", "general_service", "service_division", "joint_contract_method", "performance_restricted_competition", "pq_evaluation", "technical_evaluation", "technical_evaluation_rate", "successful_bid_method")
_SAMPLE_ROLES = {"analysis", "audit"}
_SAMPLE_STRATA = {"AI/데이터", "블록체인·DID", "공공 SI·통합관리", "수행실적 유사", "분류 근접", "실적 유사 근접", "무작위"}


def _nullable_string(value: Any) -> bool:
    return value is None or (isinstance(value, str) and bool(value.strip()))


def _aware_datetime(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _decimal_string(value: Any) -> bool:
    return value is None or (isinstance(value, str) and bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value)))


def _exact_object(value: Any, keys: tuple[str, ...]) -> bool:
    return isinstance(value, Mapping) and set(value) == set(keys)


def _validate_collected_notice(item: Mapping[str, Any]) -> None:
    if item.get("source_type") not in {"bid_notice", "pre_spec"}:
        raise ScreeningCreationError("input_error")
    if not isinstance(item.get("collection_bucket"), str) or item["collection_bucket"] not in {"candidate_pool", "audit_pool"}:
        raise ScreeningCreationError("input_error")
    for key in ("title", "agency", "method", "url"):
        if not _nullable_string(item.get(key)):
            raise ScreeningCreationError("input_error")
    for key in ("published_at", "deadline_at"):
        if not _aware_datetime(item.get(key)):
            raise ScreeningCreationError("input_error")
    for key in ("budget", "estimated_price"):
        if not _decimal_string(item.get(key)):
            raise ScreeningCreationError("input_error")
    for key, keys in (("procurement_class", _PROCUREMENT_KEYS), ("region_limit", _REGION_KEYS), ("lifecycle", _LIFECYCLE_KEYS)):
        if not _exact_object(item.get(key), keys):
            raise ScreeningCreationError("input_error")
    procurement = item["procurement_class"]
    if any(not _nullable_string(procurement[key]) for key in _PROCUREMENT_KEYS):
        raise ScreeningCreationError("input_error")
    region = item["region_limit"]
    if any(not _nullable_string(region[key]) for key in ("basis", "joint_contract_rate", "regional_joint_contract_limit")):
        raise ScreeningCreationError("input_error")
    if not isinstance(region["joint_contract_regions"], list) or any(not isinstance(v, str) or not v.strip() for v in region["joint_contract_regions"]):
        raise ScreeningCreationError("input_error")
    lifecycle = item["lifecycle"]
    if not _aware_datetime(lifecycle["changed_at"]):
        raise ScreeningCreationError("input_error")
    if any(not _nullable_string(lifecycle[key]) for key in ("pre_spec_no", "re_notice", "change_reason", "unified_notice_no", "previous_failed_notice_no")):
        raise ScreeningCreationError("input_error")
    qualification = item["qualification_flags"]
    if not isinstance(qualification, Mapping) or (qualification and set(qualification) != set(_QUALIFICATION_KEYS)):
        raise ScreeningCreationError("input_error")
    if qualification and any(not _nullable_string(qualification[key]) for key in _QUALIFICATION_KEYS):
        raise ScreeningCreationError("input_error")
    for key in ("attachments", "focus_matches", "performance_matches"):
        if not isinstance(item[key], list):
            raise ScreeningCreationError("input_error")
    for child in item["attachments"]:
        if not _exact_object(child, ("name", "url")) or any(not isinstance(child[key], str) or not child[key].strip() for key in ("name", "url")):
            raise ScreeningCreationError("input_error")
    for child in item["focus_matches"]:
        keys = ("axis", "label", "matched_field", "matched_text", "field_kind")
        if not _exact_object(child, keys) or child.get("field_kind") not in {"title", "classification", "other"} or any(not isinstance(child[key], str) or not child[key].strip() for key in ("axis", "label", "matched_field", "matched_text")):
            raise ScreeningCreationError("input_error")
    for child in item["performance_matches"]:
        keys = ("project_name", "source_page", "similarity", "common_fragment", "legal_qualification_status")
        if not _exact_object(child, keys) or any(not isinstance(child[key], str) or not child[key].strip() for key in ("project_name", "legal_qualification_status")):
            raise ScreeningCreationError("input_error")
        source_page = child["source_page"]
        if isinstance(source_page, bool) or not isinstance(source_page, (str, int)) or (isinstance(source_page, str) and not source_page.strip()) or (isinstance(source_page, int) and source_page < 0):
            raise ScreeningCreationError("input_error")
        if isinstance(child["similarity"], bool) or not isinstance(child["similarity"], (int, float)) or not math.isfinite(float(child["similarity"])):
            raise ScreeningCreationError("input_error")
        if child["common_fragment"] is not None and (not isinstance(child["common_fragment"], str) or not child["common_fragment"].strip()):
            raise ScreeningCreationError("input_error")
    for key in ("candidate_sources", "unknown_fields"):
        if not isinstance(item[key], list) or any(not isinstance(value, str) or not value.strip() for value in item[key]):
            raise ScreeningCreationError("input_error")
    if item["sample_stratum"] is not None and (not isinstance(item["sample_stratum"], str) or item["sample_stratum"] not in _SAMPLE_STRATA):
        raise ScreeningCreationError("input_error")
    if item["sample_role"] is not None and (not isinstance(item["sample_role"], str) or item["sample_role"] not in _SAMPLE_ROLES):
        raise ScreeningCreationError("input_error")
    score = item["performance_top_score"]
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score))):
        raise ScreeningCreationError("input_error")


def _source_notices(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    collection = _json_file(directory / "collected-notices.json", "input_error")
    if collection.get("schema_version") != "bidops.collected.v2" or not isinstance(collection.get("notices"), list):
        raise ScreeningCreationError("input_error")
    window = collection.get("source_window")
    if not isinstance(window, dict) or set(window) != {"from", "to", "timezone"} or window.get("timezone") != "Asia/Seoul":
        raise ScreeningCreationError("input_error")
    if not isinstance(window.get("from"), str) or not isinstance(window.get("to"), str):
        raise ScreeningCreationError("input_error")
    try:
        window_from = date.fromisoformat(window["from"])
        window_to = date.fromisoformat(window["to"])
    except ValueError:
        raise ScreeningCreationError("input_error") from None
    if window_from > window_to:
        raise ScreeningCreationError("input_error")
    notices: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in collection["notices"]:
        normalized = _notice_common(item)
        if normalized["notice_id"] in ids:
            raise ScreeningCreationError("input_error")
        ids.add(normalized["notice_id"])
        notices.append(normalized)
    return {"source_window": window, "notices": notices}, collection


def _notice_canonical_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in COMMON_NOTICE_KEYS if key not in SAMPLE_METADATA_KEYS}


def _notice_canonical_digest(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(_notice_canonical_fields(value)))


def _validation_notices(directory: Path) -> list[dict[str, Any]]:
    value = _json_file(directory / "validation-set.json", "input_error")
    if value.get("schema_version") != "bidops.validation-set.v2" or not isinstance(value.get("notices"), list):
        raise ScreeningCreationError("input_error")
    result: list[dict[str, Any]] = []
    for item in value["notices"]:
        if not isinstance(item, Mapping):
            raise ScreeningCreationError("input_error")
        result.append(_notice_common(item, require_sample_metadata=True))
    if len({item["notice_id"] for item in result}) != len(result):
        raise ScreeningCreationError("input_error")
    return result


def _quality_source_from_validation(directory: Path) -> dict[str, Any]:
    """Use the trusted validation projection for fixed quality samples.

    Historical fixed runs intentionally retain only the three reviewed
    artifacts (validation, baseline decisions, and screening results).  A
    quality gate must not require a mutable collection artifact or synthesize
    one on disk; the validation notices are already normalized and carry the
    fixed sample annotations.
    """

    value = _json_file(directory / "validation-set.json", "input_error")
    source_window = value.get("source_window")
    if not isinstance(source_window, dict):
        raise ScreeningCreationError("input_error")
    notices = _validation_notices(directory)
    return {"source_window": source_window, "notices": notices}, value


def _quality_sample_selection(
    collection_notices: list[dict[str, Any]], validation_notices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {item["notice_id"]: item for item in collection_notices}
    selected: list[dict[str, Any]] = []
    for validation in validation_notices:
        collection = by_id.get(validation["notice_id"])
        if collection is None:
            raise ScreeningCreationError("input_error")
        if (
            _notice_canonical_fields(collection) != _notice_canonical_fields(validation)
            or _notice_canonical_digest(collection) != _notice_canonical_digest(validation)
        ):
            raise ScreeningCreationError("input_error")
        # Collection is authoritative for the notice.  Only the two strict
        # validation annotations are added to the frozen sample projection.
        selected.append({
            **collection,
            "sample_stratum": validation["sample_stratum"],
            "sample_role": validation["sample_role"],
        })
    return selected


def _prior_maps(directory: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Read adjacent prior v3 input/decisions, without modifying either."""
    input_path = directory / "screening-input.json"
    decisions_path = directory / "screening-decisions.json"
    if not input_path.is_file() or not decisions_path.is_file():
        return {}, {}
    try:
        source = _json_file(input_path, "input_error")
        decisions = _json_file(decisions_path, "input_error")
    except ScreeningCreationError:
        return {}, {}
    if source.get("schema_version") != "bidops.screening-input.v1" or decisions.get("schema_version") != "bidops.decisions.v3":
        return {}, {}
    old_notices = {item.get("notice_id"): item for item in source.get("notices", []) if isinstance(item, dict)}
    old_judgments = {item.get("notice_id"): item for item in decisions.get("judgments", []) if isinstance(item, dict)}
    return old_notices, old_judgments


def _mode_for(item: Mapping[str, Any], scope: str, old_notice: Mapping[str, Any] | None, old_judgment: Mapping[str, Any] | None) -> tuple[str, str | None, str | None]:
    if scope in {"quality_sample", "single_notice"}:
        return "신규", None, None
    if not old_notice or not old_judgment:
        return "신규", None, None
    if old_judgment.get("schema_version") not in (None, "bidops.decisions.v3"):
        return "신규", None, None
    old_lifecycle = old_notice.get("lifecycle")
    current_lifecycle = item.get("lifecycle")
    if old_lifecycle == current_lifecycle:
        # The source judgment's first-judged run is the provenance identity
        # carried into the new input.  It must never be replaced by the
        # current run merely because a prior artifact was recorded there.
        return "승계", str(old_judgment.get("judged_in_run") or ""), None
    if isinstance(old_lifecycle, Mapping) and isinstance(current_lifecycle, Mapping):
        change_reason = current_lifecycle.get("change_reason")
        if change_reason in REJUDGE_REASONS - {"담당자 요청"} and change_reason != old_lifecycle.get("change_reason"):
            return "재판정", None, str(change_reason)
        if current_lifecycle.get("re_notice") != old_lifecycle.get("re_notice") and current_lifecycle.get("re_notice") not in (None, "", "N", "아니오", False):
            return "재판정", None, "재공고"
        old_pre = old_lifecycle.get("pre_spec_no")
        current_pre = current_lifecycle.get("pre_spec_no")
        old_unified = old_lifecycle.get("unified_notice_no")
        current_unified = current_lifecycle.get("unified_notice_no")
        if current_unified and current_unified != old_unified and (old_pre or current_pre):
            return "재판정", None, "본공고 전환"
        # A changed_at-only or otherwise ambiguous difference is not evidence
        # for a 담당자 요청; keep it 신규 until an explicit request exists.
        return "신규", None, None
    return "신규", None, None


def _trusted_quality_source(
    binding: _QualitySampleBinding, run_id: str, project_root: Path | str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate and thaw the only fixed source accepted by prepare."""

    facts, _source = _validate_quality_binding(binding, run_id, project_root)
    if (
        not _quality_value_is_frozen(facts.source_window)
        or not _quality_value_is_frozen(facts.notices)
        or len(facts.notices) != 40
    ):
        raise ScreeningCreationError("input_error")
    source = {"source_window": _thaw_quality_value(facts.source_window)}
    notices: list[dict[str, Any]] = []
    for item in facts.notices:
        thawed = _thaw_quality_value(item)
        try:
            notices.append(_notice_common(thawed, require_sample_metadata=True))
        except ScreeningCreationError:
            raise
    if len(notices) != 40:
        raise ScreeningCreationError("input_error")
    source["notices"] = notices
    return source, notices


class ScreeningOrchestrator:
    """Create a frozen execution then append its queue row with that ID."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: Any | None = None,
        queue: ScreeningQueue | None = None,
        ollama: OllamaClient | Any | None = None,
        ollama_client: OllamaClient | Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if isinstance(session_factory, Session):
            session_factory = sessionmaker(bind=session_factory.get_bind(), class_=Session, autoflush=False, expire_on_commit=False)
        self.session_factory = session_factory
        self.queue = queue or ScreeningQueue(session_factory=session_factory, settings=self.settings)
        self.ollama = ollama or ollama_client or OllamaClient(settings=self.settings)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def create_execution(
        self,
        *,
        run_id: str,
        policy_version: str,
        profile_source: str = "current",
        requested_by: str,
        scope: str = "full_run",
        notice_id: str | None = None,
        trigger: str | None = None,
    ) -> CreatedExecution:
        if scope not in {"single_notice", "full_run", "quality_sample"}:
            raise ScreeningCreationError("input_error")
        trigger = trigger or {"single_notice": "cli_single", "full_run": "manual_run", "quality_sample": "quality_gate"}[scope]
        if TRIGGER_SCOPES.get(trigger) != scope:
            raise ScreeningCreationError("input_error")
        execution_id = "scr-" + uuid4().hex
        workspace: ExecutionWorkspace | None = None
        source_dir = _safe_run_directory(self.settings, run_id)
        try:
            source, _collection = _source_notices(source_dir)
        except ScreeningCreationError:
            if scope != "quality_sample":
                raise
            source, _collection = _quality_source_from_validation(source_dir)
        notices = source["notices"]
        old_notices, old_judgments = _prior_maps(source_dir)
        with self._session() as session:
            run = session.scalar(select(Run).where(Run.id == run_id))
            if run is None or run.status not in {"active", "complete", "성공", "부분 성공"}:
                raise ScreeningCreationError("input_error")
            policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version))
            if policy is None:
                raise ScreeningCreationError("policy_mismatch")
            body = _policy_body(policy)
            if policy.status not in ({"activation_candidate", "active"} if trigger != "schedule" else {"active"}):
                raise ScreeningCreationError("input_error")
            # Candidate selection is policy-controlled.  Read and validate the
            # immutable policy body before consulting any source candidates.
            if scope == "full_run":
                buckets = body.get("candidate_selection", {}).get("include_collection_buckets", ["candidate_pool"])
                if not isinstance(buckets, list) or any(not isinstance(bucket, str) for bucket in buckets):
                    raise ScreeningCreationError("policy_mismatch")
                selected = [item for item in notices if item.get("collection_bucket") in buckets]
            elif scope == "quality_sample":
                selected = _quality_sample_selection(notices, _validation_notices(source_dir))
            else:
                selected = [item for item in notices if item["notice_id"] == notice_id]
                if len(selected) != 1:
                    raise ScreeningCreationError("input_error")
            # A single-notice execution binds one DB Notice row. Full and
            # quality executions are artifact-authoritative and may contain
            # collected candidates outside the validation-set DB projection.
            if scope == "single_notice":
                db_notice = session.scalar(select(Notice).where(Notice.notice_key == notice_id))
                if db_notice is None:
                    raise ScreeningCreationError("input_error")
            try:
                snapshot = create_profile_snapshot(session, profile_source=profile_source, project_root=Path(self.settings.bidops_root))
                profile_digest = snapshot.digest
                profile_version = snapshot.version
            except (ProfileSnapshotError, OSError):
                raise ScreeningCreationError("profile_snapshot") from None
            try:
                model_identity = self.ollama.inspect_model()
            except (ModelInspectionError, OSError, ConnectionError, TimeoutError):
                raise ScreeningCreationError("model_inspection") from None
            if model_identity.model_name != MODEL_NAME:
                raise ScreeningCreationError("model_inspection")
            generated_at = aware_iso(_now(self.clock))
            # Read generation settings exactly once.  The resulting canonical
            # object is persisted before enqueue; workers never re-read env.
            generation_config = generation_config_from_settings(self.settings)
            frozen: list[dict[str, Any]] = []
            for item in selected:
                mode, carry, reason = ("신규", None, None) if scope == "quality_sample" else _mode_for(item, scope, old_notices.get(item["notice_id"]), old_judgments.get(item["notice_id"]))
                frozen.append({**item, "judgment_mode": mode, "carry_over_from": carry if mode == "승계" else None, "rejudge_reason": reason if mode == "재판정" else None})
            input_value = {
                "schema_version": "bidops.screening-input.v1", "execution_id": execution_id, "run_id": run_id,
                "generated_at": generated_at, "source_window": source["source_window"],
                "policy_version": policy.policy_version, "prompt_version": policy.prompt_version,
                "company_profile_version": profile_version, "company_profile_digest": profile_digest,
                "candidate_count": len(frozen), "notices": frozen,
                "generation_config": generation_config.canonical_value(),
                "generation_config_digest": generation_config.digest(),
            }
            try:
                store = ArtifactStore(Path(self.settings.bidops_root))
                workspace = store.create_execution_workspace(execution_id)
                input_path, input_digest = workspace.write_json("screening-input.json", input_value)
            except ArtifactError:
                if workspace is not None:
                    try:
                        store.remove_execution(workspace)
                    except ArtifactError:
                        pass
                    finally:
                        workspace.close()
                raise ScreeningCreationError("artifact_write") from None
            # The profile snapshot is part of the immutable preflight binding;
            # commit it before Queue opens its own fresh session.
            try:
                session.commit()
            except Exception:
                if workspace is not None:
                    try:
                        store.remove_execution(workspace)
                    except ArtifactError:
                        pass
                    finally:
                        workspace.close()
                raise
        policy_identity = policy_version
        prompt_identity = input_value["prompt_version"]
        model_name = model_identity.model_name
        model_digest = model_identity.digest
        notice_pk: int | None = None
        try:
            if scope == "single_notice":
                notice_pk = self._notice_pk(run_id, notice_id)
            if workspace is None:
                raise ScreeningCreationError("artifact_write")
            workspace.require_named()
            row = self.queue.enqueue(
                execution_id=execution_id, trigger=trigger, source_run_id=run_id, scope=scope,
                requested_by=requested_by, policy_version=policy_identity, prompt_version=prompt_identity,
                model_name=model_name, model_digest=model_digest,
                company_profile_version=profile_version, company_profile_digest=profile_digest,
                generation_config=generation_config.canonical_value(), generation_config_digest=generation_config.digest(),
                input_artifact_path=input_path, input_artifact_digest=input_digest,
                artifact_dir=f"data/screening-executions/{execution_id}", candidate_count=len(frozen),
                **({"notice_pk": notice_pk, "notice_id": notice_id} if scope == "single_notice" else {}),
            )
        except Exception as exc:
            try:
                if workspace is not None:
                    ArtifactStore(Path(self.settings.bidops_root)).remove_execution(workspace)
            except ArtifactError:
                # The queue row was not created, but leaving an explicitly
                # nonpublished orphan is safer than deleting an unexpected
                # path. The fresh execution ID remains unreferenced.
                pass
            if isinstance(exc, QueueValidationError):
                raise ScreeningCreationError("input_error") from None
            raise ScreeningCreationError("queue_failure") from None
        finally:
            if workspace is not None:
                workspace.close()
        return CreatedExecution(row.execution_id, row.status, row.model_name, row.model_digest, row.company_profile_version, row.company_profile_digest, row.artifact_dir, row.input_artifact_path, row.input_artifact_digest, row.generation_config_digest)

    def prepare_execution(
        self,
        session: Session,
        *,
        run_id: str,
        policy_version: str,
        profile_source: str = "current",
        requested_by: str,
        scope: str = "full_run",
        notice_id: str | None = None,
        trigger: str | None = None,
        _quality_binding: _QualitySampleBinding | None = None,
    ) -> PreparedExecution:
        """Prepare one execution in a caller-owned transaction.

        Unlike ``create_execution``, this method never opens a queue session
        or commits.  It is the transaction boundary used by quality gates to
        prepare both ordinary FIFO rows before publishing either one.
        """

        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        if scope not in {"single_notice", "full_run", "quality_sample"}:
            raise ScreeningCreationError("input_error")
        trigger = trigger or {"single_notice": "cli_single", "full_run": "manual_run", "quality_sample": "quality_gate"}[scope]
        if TRIGGER_SCOPES.get(trigger) != scope:
            raise ScreeningCreationError("input_error")
        # Fixed quality execution is intentionally a capability-only path.
        # ``prepare_execution`` is public and must never fall back to reading
        # the mutable validation-set.json supplied by a caller.
        if scope == "quality_sample" and _quality_binding is None:
            raise ScreeningCreationError("input_error")
        if scope != "quality_sample" and _quality_binding is not None:
            raise ScreeningCreationError("input_error")
        execution_id = "scr-" + uuid4().hex
        workspace: ExecutionWorkspace | None = None
        source_dir = None if scope == "quality_sample" else _safe_run_directory(self.settings, run_id)
        if scope == "quality_sample":
            source, notices = _trusted_quality_source(_quality_binding, run_id, self.settings.bidops_root)
            old_notices, old_judgments = {}, {}
        else:
            source, _collection = _source_notices(source_dir)
            notices = source["notices"]
            old_notices, old_judgments = _prior_maps(source_dir)
        run = session.scalar(select(Run).where(Run.id == run_id))
        if run is None or run.status not in {"active", "complete", "성공", "부분 성공"}:
            raise ScreeningCreationError("input_error")
        policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version))
        if policy is None:
            raise ScreeningCreationError("policy_mismatch")
        body = _policy_body(policy)
        if policy.status not in ({"activation_candidate", "active"} if trigger != "schedule" else {"active"}):
            raise ScreeningCreationError("input_error")
        if scope == "full_run":
            buckets = body.get("candidate_selection", {}).get("include_collection_buckets", ["candidate_pool"])
            if not isinstance(buckets, list) or any(not isinstance(bucket, str) for bucket in buckets):
                raise ScreeningCreationError("policy_mismatch")
            selected = [item for item in notices if item.get("collection_bucket") in buckets]
        elif scope == "quality_sample":
            selected = [{key: _thaw_quality_value(value) for key, value in item.items()} for item in notices]
        else:
            selected = [item for item in notices if item["notice_id"] == notice_id]
            if len(selected) != 1:
                raise ScreeningCreationError("input_error")
            db_notice = session.scalar(select(Notice).where(Notice.notice_key == notice_id))
            if db_notice is None:
                raise ScreeningCreationError("input_error")
        try:
            snapshot = create_profile_snapshot(session, profile_source=profile_source, project_root=Path(self.settings.bidops_root))
            profile_digest = snapshot.digest
            profile_version = snapshot.version
        except (ProfileSnapshotError, OSError):
            raise ScreeningCreationError("profile_snapshot") from None
        try:
            model_identity = self.ollama.inspect_model()
        except (ModelInspectionError, OSError, ConnectionError, TimeoutError):
            raise ScreeningCreationError("model_inspection") from None
        if model_identity.model_name != MODEL_NAME:
            raise ScreeningCreationError("model_inspection")
        generated_at = aware_iso(_now(self.clock))
        generation_config = generation_config_from_settings(self.settings)
        frozen: list[dict[str, Any]] = []
        for item in selected:
            mode, carry, reason = ("신규", None, None) if scope == "quality_sample" else _mode_for(item, scope, old_notices.get(item["notice_id"]), old_judgments.get(item["notice_id"]))
            frozen.append({**item, "judgment_mode": mode, "carry_over_from": carry if mode == "승계" else None, "rejudge_reason": reason if mode == "재판정" else None})
        input_value = {
            "schema_version": "bidops.screening-input.v1", "execution_id": execution_id, "run_id": run_id,
            "generated_at": generated_at, "source_window": source["source_window"],
            "policy_version": policy.policy_version, "prompt_version": policy.prompt_version,
            "company_profile_version": profile_version, "company_profile_digest": profile_digest,
            "candidate_count": len(frozen), "notices": frozen,
            "generation_config": generation_config.canonical_value(),
            "generation_config_digest": generation_config.digest(),
        }
        store = ArtifactStore(Path(self.settings.bidops_root))
        if scope == "quality_sample":
            _reserve_quality_binding(
                _quality_binding,
                run_id,
                self.settings.bidops_root,
                session=session,
            )
        try:
            workspace = store.create_execution_workspace(execution_id)
            input_path, input_digest = workspace.write_json("screening-input.json", input_value)
            workspace.require_named()
            queue_notice = selected[0]["notice_id"] if scope == "single_notice" else None
            queue_notice_pk = db_notice.id if scope == "single_notice" else None
            row = self.queue.enqueue_in_session(
                session,
                execution_id=execution_id,
                trigger=trigger,
                source_run_id=run_id,
                scope=scope,
                requested_by=requested_by,
                policy_version=policy_version,
                prompt_version=input_value["prompt_version"],
                model_name=model_identity.model_name,
                model_digest=model_identity.digest,
                company_profile_version=profile_version,
                company_profile_digest=profile_digest,
                generation_config=generation_config.canonical_value(), generation_config_digest=generation_config.digest(),
                input_artifact_path=input_path,
                input_artifact_digest=input_digest,
                artifact_dir=f"data/screening-executions/{execution_id}",
                candidate_count=len(frozen),
                **({"notice_pk": queue_notice_pk, "notice_id": queue_notice} if scope == "single_notice" else {}),
            )
        except Exception as exc:
            # A reservation is released by the caller transaction's
            # rollback/close event. Releasing while it is active would let
            # an exception path manufacture a second execution.
            try:
                if workspace is not None:
                    store.remove_execution(workspace)
            except ArtifactError:
                pass
            finally:
                if workspace is not None:
                    workspace.close()
            if isinstance(exc, (ArtifactError, QueueValidationError)):
                raise ScreeningCreationError("artifact_write" if isinstance(exc, ArtifactError) else "input_error") from None
            raise ScreeningCreationError("queue_failure") from None
        created = CreatedExecution(row.execution_id, row.status, row.model_name, row.model_digest, row.company_profile_version, row.company_profile_digest, row.artifact_dir, row.input_artifact_path, row.input_artifact_digest, row.generation_config_digest)
        if workspace is None:
            raise ScreeningCreationError("artifact_write")
        return PreparedExecution(created=created, row=row, workspace=workspace)

    create = create_execution
    enqueue = create_execution

    def _session(self) -> Session:
        if self.session_factory is None:
            from ..core.db import SessionLocal
            return SessionLocal()
        value = self.session_factory()
        if not isinstance(value, Session):
            raise TypeError("session factory did not return a Session")
        return value

    def _notice_pk(self, run_id: str, notice_id: str | None) -> int:
        with self._session() as session:
            row = session.scalar(select(Notice).where(Notice.notice_key == notice_id))
            if row is None:
                raise ScreeningCreationError("input_error")
            return row.id


ExecutionOrchestrator = ScreeningOrchestrator
ScreeningExecutionOrchestrator = ScreeningOrchestrator
ScreeningExecutionService = ScreeningOrchestrator
create_execution = ScreeningOrchestrator.create_execution


__all__ = ["CreatedExecution", "ExecutionOrchestrator", "PreparedExecution", "ScreeningCreationError", "ScreeningExecutionOrchestrator", "ScreeningExecutionService", "ScreeningOrchestrator", "create_execution"]
