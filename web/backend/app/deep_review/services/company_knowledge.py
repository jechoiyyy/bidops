"""Immutable company-knowledge registration, binding, and read services."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.company_ontology import (
    CompanyKnowledgeValidationError,
    GraphSnapshot,
    OntologyValidationError,
    STABLE_KEY_RE,
    ValidatedCompanyKnowledge,
    ValidatedOntology,
    build_graph_snapshot,
    parse_company_knowledge_source,
    parse_ontology,
)
from ...core.db import isolated_test_boundary_active
from ...lifecycle import register_company
from ...lifecycle.models import Company
from ...lifecycle.schemas.companies import CompanyDTO
from ..models import (
    CompanyKnowledgeBinding,
    CompanyKnowledgeBindingEvent,
    CompanyKnowledgeEdge,
    CompanyKnowledgeNode,
    CompanyKnowledgeSource,
    CompanyKnowledgeVersion,
    ContentObject,
    ContentObjectLocation,
    KnowledgeOntologyVersion,
    ProfileEvidence,
    ProfileVersion,
)
from ..schemas.company_knowledge import (
    CompanyKnowledgeGraphView,
    CompanyProfileEvidenceView,
    CompanyProfileFact,
    CompanyProfileView,
    PublicKnowledgeEdge,
    PublicKnowledgeNode,
)
from . import assets
from .input_versions import InputVersionError, validate_profile_snapshot


PROFILE_SCHEMA_V2 = "bidops.company-profile.v2"
_OWNED_SOURCE_PATHS_KEY = "company_knowledge.owned_source_paths"
_COMMITTED_SOURCE_TRANSACTIONS_KEY = "company_knowledge.committed_source_transactions"


class CompanyKnowledgeServiceError(RuntimeError):
    """A stable error whose detail is safe for CLI output."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PreparedCompanyKnowledge:
    ontology: ValidatedOntology
    source: ValidatedCompanyKnowledge
    graph: GraphSnapshot


@dataclass(frozen=True)
class CompanyKnowledgeImport:
    company_id: UUID
    profile_version_id: UUID
    graph_version_id: UUID
    ontology_version: str
    source_sha256: str
    graph_sha256: str
    created: bool


@dataclass(frozen=True)
class CompanyKnowledgeActivation:
    company_id: UUID
    graph_version_id: UUID
    profile_version_id: UUID
    revision: int
    changed: bool


@dataclass(frozen=True)
class _OwnedSourcePath:
    path: Path
    transaction: Any


def _track_owned_source_path(
    session: Session,
    path: Path,
    *,
    object_key: str,
) -> None:
    """Track only this transaction's server-owned filesystem object.

    Production MinIO versions are immutable and the purpose credential has no
    delete capability.  A failed write leaves such a version for storage
    reconciliation; cleanup is enabled only for the isolated filesystem
    backend and its configured asset root.
    """

    settings = assets.get_settings()
    if (
        settings.object_store_backend != "filesystem"
        or not isolated_test_boundary_active()
    ):
        return
    root = assets.asset_root(settings.attachments_dir)
    owned_path = Path(path).resolve()
    expected_path = (root / Path(*object_key.split("/"))).resolve()
    if owned_path != expected_path:
        return
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        return
    session.info.setdefault(_OWNED_SOURCE_PATHS_KEY, []).append(
        _OwnedSourcePath(owned_path, transaction)
    )


def _owned_source_paths(session: Session) -> list[_OwnedSourcePath]:
    return session.info.get(_OWNED_SOURCE_PATHS_KEY, [])


@event.listens_for(Session, "after_commit")
def _keep_committed_company_knowledge_source(session: Session) -> None:
    if _OWNED_SOURCE_PATHS_KEY not in session.info:
        return
    transaction = session.get_nested_transaction()
    if transaction is None:
        transaction = session.get_transaction()
    if transaction is not None:
        session.info.setdefault(_COMMITTED_SOURCE_TRANSACTIONS_KEY, set()).add(
            id(transaction)
        )


@event.listens_for(Session, "after_transaction_end")
def _cleanup_abandoned_company_knowledge_source(session: Session, transaction: Any) -> None:
    if _OWNED_SOURCE_PATHS_KEY not in session.info:
        return
    committed = session.info.get(_COMMITTED_SOURCE_TRANSACTIONS_KEY, set())
    transaction_committed = id(transaction) in committed
    committed.discard(id(transaction))
    owned = _owned_source_paths(session)
    ending = [item for item in owned if item.transaction is transaction]
    if not ending:
        if not owned:
            session.info.pop(_OWNED_SOURCE_PATHS_KEY, None)
        if not committed:
            session.info.pop(_COMMITTED_SOURCE_TRANSACTIONS_KEY, None)
        return
    for item in ending:
        owned.remove(item)
    if transaction_committed and transaction.parent is not None:
        owned.extend(
            _OwnedSourcePath(item.path, transaction.parent) for item in ending
        )
    elif not transaction_committed:
        assets.cleanup_paths(item.path for item in ending)
    if not owned:
        session.info.pop(_OWNED_SOURCE_PATHS_KEY, None)
    if not committed:
        session.info.pop(_COMMITTED_SOURCE_TRANSACTIONS_KEY, None)


def prepare_company_knowledge(
    ontology_raw: bytes, company_raw: bytes
) -> PreparedCompanyKnowledge:
    """Validate both source documents without touching DB, storage, or models."""

    try:
        ontology = parse_ontology(ontology_raw)
    except OntologyValidationError as error:
        raise CompanyKnowledgeServiceError("ontology_invalid") from error
    try:
        source = parse_company_knowledge_source(company_raw, ontology=ontology)
        graph = build_graph_snapshot(source, ontology=ontology)
    except CompanyKnowledgeValidationError as error:
        raise CompanyKnowledgeServiceError("source_invalid") from error
    return PreparedCompanyKnowledge(ontology=ontology, source=source, graph=graph)


def prepare_company_knowledge_files(
    ontology_path: Path, company_path: Path
) -> PreparedCompanyKnowledge:
    try:
        ontology_raw = Path(ontology_path).read_bytes()
        company_raw = Path(company_path).read_bytes()
    except OSError as error:
        raise CompanyKnowledgeServiceError("source_unavailable") from error
    return prepare_company_knowledge(ontology_raw, company_raw)


def _revalidate_prepared(
    prepared: PreparedCompanyKnowledge,
) -> PreparedCompanyKnowledge:
    """Recover trusted values from immutable bytes at the write boundary."""

    try:
        ontology = parse_ontology(prepared.ontology.canonical_bytes)
        source = parse_company_knowledge_source(
            prepared.source.raw_bytes,
            ontology=ontology,
        )
        graph = build_graph_snapshot(source, ontology=ontology)
    except (AttributeError, OntologyValidationError, CompanyKnowledgeValidationError) as error:
        raise CompanyKnowledgeServiceError("source_invalid") from error
    if (
        ontology != prepared.ontology
        or source != prepared.source
        or graph != prepared.graph
    ):
        raise CompanyKnowledgeServiceError("source_invalid")
    return PreparedCompanyKnowledge(ontology=ontology, source=source, graph=graph)


def _lock_key(value: str) -> int:
    raw = int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")
    return raw - (1 << 64) if raw >= (1 << 63) else raw


def _transaction_lock(session: Session, value: str) -> None:
    """Serialize one logical aggregate without UPDATE permission on Company."""

    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _lock_key(value)},
        )


def _profile_v2_payload(
    source: ValidatedCompanyKnowledge,
    *,
    company_id: UUID,
    graph_version_id: UUID,
) -> tuple[dict[str, Any], list[tuple[dict[str, Any], str | None]]]:
    projected: list[tuple[dict[str, Any], str | None]] = []
    for node in sorted(source.nodes, key=lambda item: item.id):
        if node.type == "evidence":
            continue
        quote = "" if node.status == "unknown" else node.source_refs[0].quote
        fact = {
            "fact_key": node.id,
            "status": node.status,
            "value": node.value,
            "section_id": node.type,
            "section_number": None,
            "locator": {"fact_key": node.id},
            "quote": quote,
            "origin": "fictional_scenario",
        }
        projected.append((fact, None if node.status == "unknown" else quote))
    payload = {
        "schema": PROFILE_SCHEMA_V2,
        "company_id": str(company_id),
        "origin": "fictional_scenario",
        "source_sha256": source.source_sha256,
        "graph_version_id": str(graph_version_id),
        "ontology_version": source.ontology_version,
        "facts": [fact for fact, _quote in projected],
        "parse_errors": [],
    }
    return payload, projected


def _ontology_row(
    session: Session, ontology: ValidatedOntology
) -> KnowledgeOntologyVersion:
    _transaction_lock(session, f"company-ontology:{ontology.version}")
    by_version = session.scalar(
        select(KnowledgeOntologyVersion).where(
            KnowledgeOntologyVersion.version == ontology.version
        )
    )
    if by_version is not None:
        if by_version.sha256 != ontology.sha256 or by_version.payload != ontology.payload:
            raise CompanyKnowledgeServiceError("ontology_version_conflict")
        return by_version
    by_digest = session.scalar(
        select(KnowledgeOntologyVersion).where(
            KnowledgeOntologyVersion.sha256 == ontology.sha256
        )
    )
    if by_digest is not None:
        raise CompanyKnowledgeServiceError("ontology_version_conflict")
    row = KnowledgeOntologyVersion(
        id=uuid4(),
        version=ontology.version,
        sha256=ontology.sha256,
        payload=ontology.payload,
    )
    session.add(row)
    session.flush()
    return row


def _read_pinned_source(
    session: Session, source: CompanyKnowledgeSource
) -> bytes:
    content = session.get(ContentObject, source.content_object_id)
    location = session.get(ContentObjectLocation, source.content_location_id)
    if (
        content is None
        or location is None
        or location.content_object_id != content.id
        or content.sha256 != source.source_sha256
        or content.size_bytes != source.size_bytes
        or location.namespace_key != "source"
        or location.status != "verified"
        or not location.object_key
        or not location.object_version_id
        or not location.etag
    ):
        raise CompanyKnowledgeServiceError("storage_failed")
    try:
        raw, metadata = assets.read_object(
            "source", location.object_key, version_id=location.object_version_id
        )
    except assets.AssetError as error:
        raise CompanyKnowledgeServiceError("storage_failed") from error
    if (
        len(raw) != source.size_bytes
        or hashlib.sha256(raw).hexdigest() != source.source_sha256
        or metadata.namespace != "source"
        or metadata.object_key != location.object_key
        or metadata.object_version_id != location.object_version_id
        or metadata.etag != location.etag
        or metadata.size_bytes != source.size_bytes
    ):
        raise CompanyKnowledgeServiceError("storage_failed")
    return raw


def _existing_import(
    session: Session,
    *,
    company_id: UUID,
    ontology_id: UUID,
    source: ValidatedCompanyKnowledge,
    graph: GraphSnapshot,
) -> CompanyKnowledgeImport | None:
    row = session.scalar(
        select(CompanyKnowledgeVersion).where(
            CompanyKnowledgeVersion.company_id == company_id,
            CompanyKnowledgeVersion.ontology_id == ontology_id,
            CompanyKnowledgeVersion.source_sha256 == source.source_sha256,
        )
    )
    if row is None:
        return None
    source_row = session.get(CompanyKnowledgeSource, row.source_id)
    profile = session.get(ProfileVersion, row.profile_version_id)
    expected_profile, _ = _profile_v2_payload(
        source,
        company_id=company_id,
        graph_version_id=row.id,
    )
    if (
        source_row is None
        or source_row.company_id != company_id
        or _read_pinned_source(session, source_row) != source.raw_bytes
        or row.graph_sha256 != graph.sha256
        or row.snapshot != graph.payload
        or profile is None
        or profile.company_id != company_id
        or profile.profile_sha256 != source.source_sha256
        or profile.source_kind != "company-knowledge-json-v2"
        or profile.profile_payload != expected_profile
    ):
        raise CompanyKnowledgeServiceError("storage_failed")
    return CompanyKnowledgeImport(
        company_id=company_id,
        profile_version_id=row.profile_version_id,
        graph_version_id=row.id,
        ontology_version=source.ontology_version,
        source_sha256=source.source_sha256,
        graph_sha256=graph.sha256,
        created=False,
    )


def _store_source(
    session: Session,
    source: ValidatedCompanyKnowledge,
    *,
    company_id: UUID,
) -> tuple[CompanyKnowledgeSource, ContentObject]:
    object_key = f"source/company-knowledge-{uuid4().hex}.json"
    try:
        stored_path, written = assets.store_named(
            "source",
            object_key,
            source.raw_bytes,
            content_type="application/json",
        )
        _track_owned_source_path(session, stored_path, object_key=object_key)
        reread, verified = assets.read_object(
            "source", object_key, version_id=written.object_version_id
        )
    except assets.AssetError as error:
        raise CompanyKnowledgeServiceError("storage_failed") from error
    if (
        reread != source.raw_bytes
        or written.namespace != "source"
        or written.object_key != object_key
        or not written.object_version_id
        or not written.etag
        or verified.namespace != "source"
        or verified.object_key != object_key
        or written.object_version_id != verified.object_version_id
        or written.etag != verified.etag
        or written.size_bytes != len(source.raw_bytes)
        or verified.size_bytes != len(source.raw_bytes)
    ):
        raise CompanyKnowledgeServiceError("storage_failed")

    content = session.scalar(
        select(ContentObject).where(ContentObject.sha256 == source.source_sha256)
    )
    if content is None:
        content = ContentObject(
            id=uuid4(),
            sha256=source.source_sha256,
            size_bytes=len(source.raw_bytes),
            detected_mime="application/json",
            retention_class="company-knowledge-source",
        )
        session.add(content)
        session.flush()
    elif content.size_bytes != len(source.raw_bytes):
        raise CompanyKnowledgeServiceError("storage_failed")
    location = ContentObjectLocation(
        id=uuid4(),
        content_object_id=content.id,
        namespace_key="source",
        object_key=object_key,
        object_version_id=verified.object_version_id,
        etag=verified.etag,
        status="verified",
        verified_at=datetime.now(UTC),
    )
    source_row = CompanyKnowledgeSource(
        id=uuid4(),
        company_id=company_id,
        source_sha256=source.source_sha256,
        size_bytes=len(source.raw_bytes),
        content_object_id=content.id,
        content_location_id=location.id,
    )
    session.add(location)
    session.flush()
    session.add(source_row)
    session.flush()
    return source_row, content


def import_company_knowledge(
    session: Session,
    prepared: PreparedCompanyKnowledge,
    *,
    actor: str,
) -> CompanyKnowledgeImport:
    """Create source/profile/graph lineage atomically; caller owns commit."""

    prepared = _revalidate_prepared(prepared)
    actor = validate_actor(actor)
    try:
        registration = register_company(
            session,
            slug=prepared.source.company.slug,
            name=prepared.source.company.name,
            is_fictional=prepared.source.company.is_fictional,
            actor=actor,
        )
    except BundleServiceError as error:
        code = (
            "company_identity_conflict"
            if error.code == "company_identity_conflict"
            else "source_invalid"
        )
        raise CompanyKnowledgeServiceError(code) from error

    company_id = registration.company_id
    _transaction_lock(session, f"company-knowledge:{company_id}")
    ontology_row = _ontology_row(session, prepared.ontology)
    existing = _existing_import(
        session,
        company_id=company_id,
        ontology_id=ontology_row.id,
        source=prepared.source,
        graph=prepared.graph,
    )
    if existing is not None:
        return existing

    graph_id = uuid4()
    profile_payload, facts = _profile_v2_payload(
        prepared.source,
        company_id=company_id,
        graph_version_id=graph_id,
    )
    _transaction_lock(session, "profile-version-sequence")
    next_profile_version = int(
        session.scalar(select(func.max(ProfileVersion.version))) or 0
    ) + 1
    source_row, content = _store_source(
        session, prepared.source, company_id=company_id
    )
    profile = ProfileVersion(
        id=uuid4(),
        company_id=company_id,
        version=next_profile_version,
        label=(
            f"company-knowledge:{prepared.source.company.slug}:"
            f"{prepared.source.source_sha256[:16]}"
        ),
        profile_payload=profile_payload,
        profile_sha256=prepared.source.source_sha256,
        source_kind="company-knowledge-json-v2",
        created_by_name=actor,
    )
    session.add(profile)
    session.flush()
    now = datetime.now(UTC)
    for fact, quote in facts:
        if quote is None:
            continue
        session.add(
            ProfileEvidence(
                id=uuid4(),
                profile_version_id=profile.id,
                fact_key=fact["fact_key"],
                content_object_id=content.id,
                source_sha256=prepared.source.source_sha256,
                locator_type="profile_fact",
                locator=fact["locator"],
                quote=quote,
                confirmed_by_name=actor,
                confirmed_at=now,
            )
        )
    graph = CompanyKnowledgeVersion(
        id=graph_id,
        company_id=company_id,
        ontology_id=ontology_row.id,
        source_id=source_row.id,
        profile_version_id=profile.id,
        source_sha256=prepared.source.source_sha256,
        graph_sha256=prepared.graph.sha256,
        snapshot=prepared.graph.payload,
    )
    session.add(graph)
    session.flush()
    # Rows are copied from the frozen snapshot (sorted ids, sorted source refs)
    # so that every stored row equals its snapshot item by construction.
    snapshot = prepared.graph.payload
    session.add_all(
        CompanyKnowledgeNode(
            graph_version_id=graph.id,
            node_id=node["id"],
            payload=node,
        )
        for node in snapshot["nodes"]
    )
    session.flush()
    session.add_all(
        CompanyKnowledgeEdge(
            graph_version_id=graph.id,
            edge_id=edge["id"],
            from_id=edge["from_id"],
            to_id=edge["to_id"],
            payload=edge,
        )
        for edge in snapshot["edges"]
    )
    try:
        session.flush()
    except IntegrityError as error:
        raise CompanyKnowledgeServiceError("storage_failed") from error
    return CompanyKnowledgeImport(
        company_id=company_id,
        profile_version_id=profile.id,
        graph_version_id=graph.id,
        ontology_version=prepared.ontology.version,
        source_sha256=prepared.source.source_sha256,
        graph_sha256=prepared.graph.sha256,
        created=True,
    )


def activate_company_knowledge(
    session: Session,
    *,
    company_id: UUID,
    graph_version_id: UUID,
    actor: str,
) -> CompanyKnowledgeActivation:
    actor = validate_actor(actor)
    _transaction_lock(session, f"company-knowledge:{company_id}")
    company = session.get(Company, company_id)
    if company is None:
        raise CompanyKnowledgeServiceError("company_not_found")
    graph = session.get(CompanyKnowledgeVersion, graph_version_id)
    if graph is None:
        raise CompanyKnowledgeServiceError("graph_not_found")
    if graph.company_id != company_id:
        raise CompanyKnowledgeServiceError("graph_company_mismatch")
    profile = session.get(ProfileVersion, graph.profile_version_id)
    if profile is None or profile.company_id != company_id:
        raise CompanyKnowledgeServiceError("profile_invalid")

    binding = session.get(CompanyKnowledgeBinding, company_id)
    if binding is not None and binding.graph_version_id == graph.id:
        if binding.profile_version_id != graph.profile_version_id:
            raise CompanyKnowledgeServiceError("profile_invalid")
        return CompanyKnowledgeActivation(
            company_id=company_id,
            graph_version_id=graph.id,
            profile_version_id=graph.profile_version_id,
            revision=binding.revision,
            changed=False,
        )

    previous_graph_id = binding.graph_version_id if binding is not None else None
    revision = binding.revision + 1 if binding is not None else 1
    now = datetime.now(UTC)
    if binding is None:
        binding = CompanyKnowledgeBinding(
            company_id=company_id,
            graph_version_id=graph.id,
            profile_version_id=graph.profile_version_id,
            revision=revision,
            updated_at=now,
            actor=actor,
        )
        session.add(binding)
    else:
        binding.graph_version_id = graph.id
        binding.profile_version_id = graph.profile_version_id
        binding.revision = revision
        binding.updated_at = now
        binding.actor = actor
    session.add(
        CompanyKnowledgeBindingEvent(
            id=uuid4(),
            company_id=company_id,
            revision=revision,
            graph_version_id=graph.id,
            profile_version_id=graph.profile_version_id,
            previous_graph_version_id=previous_graph_id,
            actor=actor,
            created_at=now,
        )
    )
    try:
        session.flush()
    except IntegrityError as error:
        raise CompanyKnowledgeServiceError("storage_failed") from error
    return CompanyKnowledgeActivation(
        company_id=company_id,
        graph_version_id=graph.id,
        profile_version_id=graph.profile_version_id,
        revision=revision,
        changed=True,
    )


# ---------------------------------------------------------------------------
# Read API (contract §4): profile view, bounded graph view, evidence view.
#
# These are pure reads. They take no locks, never write, and never read the
# private ``source`` object bytes: the frozen DB lineage is validated through
# ``validate_profile_snapshot`` (without source verification, matching the
# API role's credentials) before anything is serialized. Any inconsistency is
# reported as ``processing_failed`` and is never "corrected" into a response.
# ---------------------------------------------------------------------------

GRAPH_DEFAULT_DEPTH = 2
GRAPH_MAX_DEPTH = 3
GRAPH_DEFAULT_LIMIT = 200
GRAPH_MAX_LIMIT = 500


@dataclass(frozen=True)
class _ResolvedKnowledge:
    company: Company
    graph: CompanyKnowledgeVersion
    profile: ProfileVersion
    ontology_version: str
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    facts: tuple[Mapping[str, Any], ...]
    evidence_by_fact: Mapping[str, UUID]


def _read_failed() -> CompanyKnowledgeServiceError:
    return CompanyKnowledgeServiceError("processing_failed")


def _validated_v2_profile(session: Session, profile: ProfileVersion) -> None:
    payload = profile.profile_payload if isinstance(profile.profile_payload, Mapping) else None
    if payload is None or payload.get("schema") != PROFILE_SCHEMA_V2:
        raise _read_failed()
    try:
        validate_profile_snapshot(session, profile)
    except InputVersionError as error:
        raise _read_failed() from error


def _evidence_by_fact(session: Session, profile_id: UUID) -> dict[str, UUID]:
    rows = session.scalars(
        select(ProfileEvidence)
        .where(ProfileEvidence.profile_version_id == profile_id)
        .order_by(ProfileEvidence.fact_key.asc(), ProfileEvidence.id.asc())
    )
    result: dict[str, UUID] = {}
    for row in rows:
        if row.fact_key in result:
            raise _read_failed()
        result[row.fact_key] = row.id
    return result


def _resolve_company_knowledge(
    session: Session,
    *,
    company_id: UUID,
    graph_version_id: UUID | None,
) -> _ResolvedKnowledge:
    company = session.get(Company, company_id)
    if company is None:
        raise CompanyKnowledgeServiceError("not_found")
    if graph_version_id is None:
        binding = session.get(CompanyKnowledgeBinding, company_id)
        if binding is None:
            raise CompanyKnowledgeServiceError("company_profile_not_ready")
        graph = session.get(CompanyKnowledgeVersion, binding.graph_version_id)
        if (
            graph is None
            or graph.company_id != company_id
            or binding.profile_version_id != graph.profile_version_id
        ):
            raise _read_failed()
    else:
        graph = session.get(CompanyKnowledgeVersion, graph_version_id)
        if graph is None or graph.company_id != company_id:
            raise CompanyKnowledgeServiceError("not_found")

    profile = session.get(ProfileVersion, graph.profile_version_id)
    if profile is None or profile.company_id != company_id:
        raise _read_failed()
    _validated_v2_profile(session, profile)

    ontology = session.get(KnowledgeOntologyVersion, graph.ontology_id)
    payload = profile.profile_payload
    snapshot = graph.snapshot
    if (
        ontology is None
        or not isinstance(payload, Mapping)
        or not isinstance(snapshot, Mapping)
        or payload.get("graph_version_id") != str(graph.id)
        or payload.get("company_id") != str(company_id)
        or payload.get("source_sha256") != profile.profile_sha256
        or profile.profile_sha256 != graph.source_sha256
        or payload.get("ontology_version") != ontology.version
        or snapshot.get("ontology_version") != ontology.version
        or snapshot.get("source_sha256") != graph.source_sha256
        or snapshot.get("company_slug") != company.slug
    ):
        raise _read_failed()
    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    facts = payload.get("facts")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(facts, list):
        raise _read_failed()
    return _ResolvedKnowledge(
        company=company,
        graph=graph,
        profile=profile,
        ontology_version=ontology.version,
        nodes=tuple(nodes),
        edges=tuple(edges),
        facts=tuple(facts),
        evidence_by_fact=_evidence_by_fact(session, profile.id),
    )


def _company_dto(company: Company) -> CompanyDTO:
    return CompanyDTO(
        company_id=company.id,
        slug=company.slug,
        name=company.name,
        is_fictional=company.is_fictional,
        created_at=company.created_at,
    )


def _fact_evidence_ids(resolved: _ResolvedKnowledge, fact_key: str, status: str) -> list[UUID]:
    evidence_id = resolved.evidence_by_fact.get(fact_key)
    if status == "unknown":
        if evidence_id is not None:
            raise _read_failed()
        return []
    if evidence_id is None:
        raise _read_failed()
    return [evidence_id]


def company_profile_view(
    session: Session,
    *,
    company_id: UUID,
    graph_version_id: UUID | None = None,
) -> CompanyProfileView:
    """Project the frozen v2 profile of the active (or a named past) version."""

    resolved = _resolve_company_knowledge(
        session, company_id=company_id, graph_version_id=graph_version_id
    )
    labels = {
        node.get("id"): node.get("label")
        for node in resolved.nodes
        if isinstance(node, Mapping)
    }
    facts: list[CompanyProfileFact] = []
    for fact in resolved.facts:
        if not isinstance(fact, Mapping) or fact.get("origin") != "fictional_scenario":
            raise _read_failed()
        fact_key = fact.get("fact_key")
        status = fact.get("status")
        label = labels.get(fact_key)
        if not isinstance(fact_key, str) or not isinstance(label, str):
            raise _read_failed()
        facts.append(
            CompanyProfileFact(
                fact_key=fact_key,
                label=label,
                status=status,
                origin="fictional_scenario",
                value=fact.get("value"),
                evidence_ids=_fact_evidence_ids(resolved, fact_key, status),
            )
        )
    return CompanyProfileView(
        schema_version="bidops.company-profile-view.v1",
        company=_company_dto(resolved.company),
        profile_version_id=resolved.profile.id,
        profile_sha256=resolved.profile.profile_sha256,
        graph_version_id=resolved.graph.id,
        graph_sha256=resolved.graph.graph_sha256,
        ontology_version=resolved.ontology_version,
        facts=facts,
    )


def _source_ref_key(ref: Any) -> tuple[str, str]:
    locator = ref.get("locator") if isinstance(ref, Mapping) else None
    pointer = locator.get("json_pointer") if isinstance(locator, Mapping) else None
    quote = ref.get("quote") if isinstance(ref, Mapping) else None
    if not isinstance(pointer, str) or not isinstance(quote, str):
        raise _read_failed()
    return pointer, quote


def _reused_evidence_ids(
    item: Mapping[str, Any],
    *,
    facts_by_ref: Mapping[tuple[str, str], list[str]],
    resolved: _ResolvedKnowledge,
) -> list[UUID]:
    """Evidence ids of the non-unknown facts whose source ref ``item`` reuses."""

    if item.get("status") == "unknown":
        return []
    refs = item.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise _read_failed()
    result: list[UUID] = []
    for ref in refs:
        fact_keys = facts_by_ref.get(_source_ref_key(ref))
        if not fact_keys:
            raise _read_failed()
        for fact_key in fact_keys:
            evidence_id = resolved.evidence_by_fact.get(fact_key)
            if evidence_id is None:
                raise _read_failed()
            if evidence_id not in result:
                result.append(evidence_id)
    return result


def _bounded_component(
    node_ids: set[str],
    edges: Sequence[Mapping[str, Any]],
    *,
    root: str,
    depth: int,
) -> dict[str, int]:
    """Undirected BFS distances <= depth; visited nodes are never re-enqueued."""

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        source, target = edge.get("from_id"), edge.get("to_id")
        if source not in adjacency or target not in adjacency:
            raise _read_failed()
        adjacency[source].add(target)
        adjacency[target].add(source)
    distances = {root: 0}
    queue: deque[str] = deque([root])
    while queue:
        current = queue.popleft()
        distance = distances[current]
        if distance >= depth:
            continue
        for neighbour in sorted(adjacency[current]):
            if neighbour in distances:
                continue
            distances[neighbour] = distance + 1
            queue.append(neighbour)
    return distances


def _nodes_by_id(resolved: _ResolvedKnowledge) -> dict[str, Mapping[str, Any]]:
    nodes_by_id: dict[str, Mapping[str, Any]] = {}
    for node in resolved.nodes:
        node_id = node.get("id") if isinstance(node, Mapping) else None
        if not isinstance(node_id, str) or node_id in nodes_by_id:
            raise _read_failed()
        nodes_by_id[node_id] = node
    return nodes_by_id


def _edges(resolved: _ResolvedKnowledge) -> list[Mapping[str, Any]]:
    edges = [edge for edge in resolved.edges if isinstance(edge, Mapping)]
    if len(edges) != len(resolved.edges):
        raise _read_failed()
    return edges


def _facts_by_ref(nodes_by_id: Mapping[str, Mapping[str, Any]]) -> dict[tuple[str, str], list[str]]:
    facts_by_ref: dict[tuple[str, str], list[str]] = {}
    for node_id in sorted(nodes_by_id):
        node = nodes_by_id[node_id]
        if node.get("type") == "evidence" or node.get("status") == "unknown":
            continue
        refs = node.get("source_refs")
        if not isinstance(refs, list) or len(refs) != 1:
            raise _read_failed()
        facts_by_ref.setdefault(_source_ref_key(refs[0]), []).append(node_id)
    return facts_by_ref


def _public_node(
    resolved: _ResolvedKnowledge,
    node_id: str,
    node: Mapping[str, Any],
    facts_by_ref: Mapping[tuple[str, str], list[str]],
) -> PublicKnowledgeNode:
    if node.get("type") == "evidence":
        evidence_ids = _reused_evidence_ids(node, facts_by_ref=facts_by_ref, resolved=resolved)
    else:
        evidence_ids = _fact_evidence_ids(resolved, node_id, node.get("status"))
    return PublicKnowledgeNode(
        id=node_id,
        type=node.get("type"),
        label=node.get("label"),
        concept_id=node.get("concept_id"),
        status=node.get("status"),
        origin=node.get("origin"),
        value=node.get("value"),
        evidence_ids=evidence_ids,
    )


def _public_edge(
    resolved: _ResolvedKnowledge,
    edge: Mapping[str, Any],
    facts_by_ref: Mapping[tuple[str, str], list[str]],
) -> PublicKnowledgeEdge:
    return PublicKnowledgeEdge(
        id=edge.get("id"),
        type=edge.get("type"),
        from_id=edge.get("from_id"),
        to_id=edge.get("to_id"),
        status=edge.get("status"),
        origin=edge.get("origin"),
        evidence_ids=_reused_evidence_ids(edge, facts_by_ref=facts_by_ref, resolved=resolved),
    )


def company_knowledge_public_graph(
    session: Session,
    *,
    company_id: UUID,
    graph_version_id: UUID,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The whole, untruncated public graph of one company graph version.

    Analysis input builders (DEMO-03) need every node and edge, never the
    bounded REST neighbourhood.  Rows are ``PublicKnowledgeNode``/``Edge``
    JSON (no ``source_refs``), id sorted, with the same evidence mapping as
    the read API: fact nodes carry their own ProfileEvidence id (none when
    unknown); evidence nodes and relations carry the evidence ids of the
    non-unknown facts whose source ref they reuse.  Lineage problems raise
    ``CompanyKnowledgeServiceError("processing_failed")``; a graph of another
    company raises ``not_found``.
    """

    resolved = _resolve_company_knowledge(
        session, company_id=company_id, graph_version_id=graph_version_id
    )
    nodes_by_id = _nodes_by_id(resolved)
    edges = _edges(resolved)
    for edge in edges:
        if edge.get("from_id") not in nodes_by_id or edge.get("to_id") not in nodes_by_id:
            raise _read_failed()
    facts_by_ref = _facts_by_ref(nodes_by_id)
    nodes = [
        _public_node(resolved, node_id, nodes_by_id[node_id], facts_by_ref).model_dump(mode="json")
        for node_id in sorted(nodes_by_id)
    ]
    public_edges = [
        _public_edge(resolved, edge, facts_by_ref).model_dump(mode="json")
        for edge in sorted(edges, key=lambda item: str(item.get("id")))
    ]
    return nodes, public_edges


def company_knowledge_graph_view(
    session: Session,
    *,
    company_id: UUID,
    graph_version_id: UUID | None = None,
    root_node_id: str | None = None,
    depth: int = GRAPH_DEFAULT_DEPTH,
    limit: int = GRAPH_DEFAULT_LIMIT,
) -> CompanyKnowledgeGraphView:
    """Return a bounded, source-locator-free neighbourhood of one graph version."""

    if (
        isinstance(depth, bool)
        or not isinstance(depth, int)
        or not 1 <= depth <= GRAPH_MAX_DEPTH
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= GRAPH_MAX_LIMIT
        or (
            root_node_id is not None
            and (not isinstance(root_node_id, str) or not STABLE_KEY_RE.fullmatch(root_node_id))
        )
    ):
        raise CompanyKnowledgeServiceError("invalid_request")
    resolved = _resolve_company_knowledge(
        session, company_id=company_id, graph_version_id=graph_version_id
    )
    nodes_by_id = _nodes_by_id(resolved)
    edges = _edges(resolved)

    if root_node_id is None:
        company_nodes = [
            node_id for node_id, node in nodes_by_id.items() if node.get("type") == "company"
        ]
        if len(company_nodes) != 1:
            raise _read_failed()
        root = company_nodes[0]
    elif root_node_id in nodes_by_id:
        root = root_node_id
    else:
        raise CompanyKnowledgeServiceError("not_found")

    facts_by_ref = _facts_by_ref(nodes_by_id)

    distances = _bounded_component(set(nodes_by_id), edges, root=root, depth=depth)
    ordered = sorted(distances, key=lambda node_id: (distances[node_id], node_id))
    returned = ordered[:limit]
    returned_set = set(returned)

    public_nodes = [
        _public_node(resolved, node_id, nodes_by_id[node_id], facts_by_ref)
        for node_id in returned
    ]
    public_edges = [
        _public_edge(resolved, edge, facts_by_ref)
        for edge in sorted(edges, key=lambda item: str(item.get("id")))
        if edge.get("from_id") in returned_set and edge.get("to_id") in returned_set
    ]
    omitted = len(distances) - len(returned)
    return CompanyKnowledgeGraphView(
        schema_version="bidops.company-knowledge-graph.v1",
        company_id=resolved.company.id,
        graph_version_id=resolved.graph.id,
        graph_sha256=resolved.graph.graph_sha256,
        ontology_version=resolved.ontology_version,
        nodes=public_nodes,
        edges=public_edges,
        truncated=omitted > 0,
        omitted_node_count=omitted,
    )


def company_profile_evidence_view(
    session: Session,
    *,
    company_id: UUID,
    evidence_id: UUID,
) -> CompanyProfileEvidenceView:
    """Return one company-owned evidence quote without source text or paths."""

    company = session.get(Company, company_id)
    if company is None:
        raise CompanyKnowledgeServiceError("not_found")
    evidence = session.get(ProfileEvidence, evidence_id)
    if evidence is None:
        raise CompanyKnowledgeServiceError("not_found")
    profile = session.get(ProfileVersion, evidence.profile_version_id)
    # Legacy NULL-company profiles and other companies' profiles are absent
    # from this company's path.
    if profile is None or profile.company_id is None or profile.company_id != company_id:
        raise CompanyKnowledgeServiceError("not_found")
    _validated_v2_profile(session, profile)
    if (
        evidence.source_sha256 != profile.profile_sha256
        or evidence.locator_type != "profile_fact"
        or evidence.locator != {"fact_key": evidence.fact_key}
    ):
        raise _read_failed()
    return CompanyProfileEvidenceView(
        evidence_id=evidence.id,
        profile_version_id=profile.id,
        fact_key=evidence.fact_key,
        origin="fictional_scenario",
        quote=evidence.quote,
        source_sha256=evidence.source_sha256,
    )


__all__ = [
    "CompanyKnowledgeActivation",
    "CompanyKnowledgeImport",
    "CompanyKnowledgeServiceError",
    "PreparedCompanyKnowledge",
    "activate_company_knowledge",
    "company_knowledge_graph_view",
    "company_knowledge_public_graph",
    "company_profile_evidence_view",
    "company_profile_view",
    "import_company_knowledge",
    "prepare_company_knowledge",
    "prepare_company_knowledge_files",
]
