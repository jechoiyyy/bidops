"""Pure helpers used while projecting persisted agent state.

This module has no clock, UUID generator, database, audit writer, or service
dependency.  Every result is derived solely from its arguments.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import TypeAlias

from .contracts import AgentArtifactRef, AgentName


TimestampInput: TypeAlias = datetime | None


def latest_timestamp(*timestamps: TimestampInput | Iterable[TimestampInput]) -> datetime | None:
    """Return the latest aware timestamp, ignoring null values.

    Both ``latest_timestamp(a, b)`` and ``latest_timestamp([a, b])`` are
    accepted so callers can pass either individual persisted columns or a
    collected snapshot of columns.
    """

    values: Iterable[TimestampInput]
    if len(timestamps) == 1 and timestamps[0] is not None and not isinstance(timestamps[0], datetime):
        candidate = timestamps[0]
        if isinstance(candidate, (str, bytes)):
            raise TypeError("timestamps must contain datetime values")
        values = candidate
    else:
        values = timestamps

    aware_values: list[datetime] = []
    for value in values:
        if value is None:
            continue
        if not isinstance(value, datetime):
            raise TypeError("timestamps must contain datetime values")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        aware_values.append(value)
    return max(aware_values) if aware_values else None


max_timestamp = latest_timestamp
max_saved_timestamp = latest_timestamp
latest_saved_timestamp = latest_timestamp


def _ref_identity(ref: AgentArtifactRef) -> tuple[object, str, int | None, str | None]:
    return ref.artifact_type, ref.artifact_id, ref.version, ref.sha256


def _validate_order_mapping(order: Mapping[str, int] | None) -> Mapping[str, int] | None:
    if order is None:
        return None
    for key, value in order.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("ref order keys must be nonblank strings")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("ref order values must be nonnegative integers")
    return order


def sort_unique_refs(
    refs: Iterable[AgentArtifactRef],
    order: Mapping[str, int] | None = None,
    *,
    domain_ordinals: Mapping[str, int] | None = None,
    domain_sequences: Mapping[str, int] | None = None,
    ordinal_by_id: Mapping[str, int] | None = None,
    sequence_by_id: Mapping[str, int] | None = None,
    ordinals: Mapping[str, int] | None = None,
    sequences: Mapping[str, int] | None = None,
) -> list[AgentArtifactRef]:
    """Validate and deterministically order artifact references.

    ``order``/``domain_ordinals``/``ordinal_by_id`` are preferred over
    sequence mappings.  If no domain order is supplied, artifact IDs provide
    the deterministic order.  The input collection is never mutated.
    """

    refs_copy = list(refs)
    if any(not isinstance(ref, AgentArtifactRef) for ref in refs_copy):
        raise TypeError("refs must contain AgentArtifactRef values")

    identities = [_ref_identity(ref) for ref in refs_copy]
    if len(identities) != len(set(identities)):
        raise ValueError("refs must not contain duplicates")

    mappings = [order, domain_ordinals, ordinal_by_id, ordinals]
    if sum(mapping is not None for mapping in mappings) > 1:
        raise ValueError("only one ordinal/order mapping may be supplied")
    ordinal_mapping = next((mapping for mapping in mappings if mapping is not None), None)
    ordinal_mapping = _validate_order_mapping(ordinal_mapping)

    sequence_mappings = [domain_sequences, sequence_by_id, sequences]
    if sum(mapping is not None for mapping in sequence_mappings) > 1:
        raise ValueError("only one sequence mapping may be supplied")
    sequence_mapping = next((mapping for mapping in sequence_mappings if mapping is not None), None)
    sequence_mapping = _validate_order_mapping(sequence_mapping)

    def tie_breakers(ref: AgentArtifactRef) -> tuple[str, str, int, str]:
        return (
            ref.artifact_id,
            ref.artifact_type.value,
            ref.version if ref.version is not None else -1,
            ref.sha256 or "",
        )

    if ordinal_mapping is not None:
        keyed = lambda ref: (ordinal_mapping.get(ref.artifact_id, 2**63 - 1), *tie_breakers(ref))
    elif sequence_mapping is not None:
        keyed = lambda ref: (sequence_mapping.get(ref.artifact_id, 2**63 - 1), *tie_breakers(ref))
    else:
        keyed = tie_breakers
    return sorted(refs_copy, key=keyed)


sort_artifact_refs = sort_unique_refs
ordered_unique_refs = sort_unique_refs
sort_refs = sort_unique_refs


def _require_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a nonblank string")
    return value


def document_preparation_run_id(bundle_id: str) -> str:
    return f"document-preparation:{_require_identifier(bundle_id, 'bundle_id')}"


def deep_review_run_id(review_id: str, attempt_id: str) -> str:
    return (
        f"deep-review:{_require_identifier(review_id, 'review_id')}"
        f":attempt:{_require_identifier(attempt_id, 'attempt_id')}"
    )


def decision_run_id(review_id: str) -> str:
    return f"decision:{_require_identifier(review_id, 'review_id')}"


make_document_preparation_run_id = document_preparation_run_id
make_deep_review_run_id = deep_review_run_id
make_decision_run_id = decision_run_id
run_id_for_document_preparation = document_preparation_run_id
run_id_for_deep_review = deep_review_run_id
run_id_for_decision = decision_run_id


def deterministic_run_id(agent_name: AgentName | str, *identifiers: str) -> str:
    """Assemble one of the three v1 run IDs from opaque persisted IDs."""

    name = AgentName(agent_name)
    if name is AgentName.document_preparation and len(identifiers) == 1:
        return document_preparation_run_id(identifiers[0])
    if name is AgentName.deep_review and len(identifiers) == 2:
        return deep_review_run_id(identifiers[0], identifiers[1])
    if name is AgentName.decision and len(identifiers) == 1:
        return decision_run_id(identifiers[0])
    raise ValueError("agent name and run ID identifiers do not match")


build_run_id = deterministic_run_id


__all__ = [
    "TimestampInput",
    "build_run_id",
    "deep_review_run_id",
    "decision_run_id",
    "deterministic_run_id",
    "document_preparation_run_id",
    "latest_saved_timestamp",
    "latest_timestamp",
    "make_decision_run_id",
    "make_deep_review_run_id",
    "make_document_preparation_run_id",
    "max_saved_timestamp",
    "max_timestamp",
    "ordered_unique_refs",
    "run_id_for_decision",
    "run_id_for_deep_review",
    "run_id_for_document_preparation",
    "sort_artifact_refs",
    "sort_refs",
    "sort_unique_refs",
]
