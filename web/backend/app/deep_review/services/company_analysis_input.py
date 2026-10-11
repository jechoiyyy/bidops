"""CompanyAnalysisInput and FrozenProvenance builders (demo contract §5, §10).

Both purposes (``company_fit`` here, ``deep_review`` in a later step) build the
same frozen input shape from:

* the company's **active** knowledge binding, resolved through the DEMO-02
  services (``company_knowledge_public_graph`` for the whole graph version,
  ``input_versions.profile_context`` for the v2 profile and its evidence);
* caller-supplied requirements (``company_knowledge_retrieval`` builders);
* the purpose policy identity and declared model binding.

Retrieval (concept matching, graph paths, profile selection, coverage) is
delegated unchanged to ``company_knowledge_retrieval.build_company_retrieval``.
Errors are ``CompanyAnalysisError`` with a contract gate code; no source text,
path, or secret is carried in an error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.company_ontology import OntologyValidationError, ValidatedOntology, parse_ontology
from ...core.model_binding import canonical_json_bytes
from ...lifecycle.models import Company
from ..models import (
    CompanyKnowledgeBinding,
    CompanyKnowledgeVersion,
    ContentObject,
    DocumentBundle,
    DocumentBundleItem,
    DocumentVersion,
    KnowledgeOntologyVersion,
    ProfileVersion,
)
from .company_knowledge import CompanyKnowledgeServiceError, company_knowledge_public_graph
from .company_knowledge_retrieval import CompanyRetrievalError, build_company_retrieval
from .input_versions import InputVersionError, canonical_json_hash, profile_context


COMPANY_ANALYSIS_INPUT_SCHEMA = "bidops.company-analysis-input.v1"
PROFILE_SCHEMA_V2 = "bidops.company-profile.v2"
PURPOSES = frozenset({"company_fit", "deep_review"})

#: Every key of CompanyAnalysisInput (contract §5), in no particular order.
COMPANY_ANALYSIS_INPUT_KEYS = frozenset({
    "schema_version", "purpose", "execution_nonce", "target_review_id", "company_id",
    "profile_version_id", "profile_sha256", "graph_version_id", "graph_sha256",
    "ontology_version", "ontology_sha256", "notice_id", "document_version_ids", "bundle_id",
    "overview_run_id", "overview_sha256", "policy_version_id", "policy_sha256",
    "model_name", "model_revision", "generation_config_sha256",
    "requirements", "profile_facts", "profile_evidence", "graph_nodes", "graph_edges",
    "graph_paths", "coverage",
})
#: Every key of FrozenProvenance (contract §10).
FROZEN_PROVENANCE_KEYS = frozenset({
    "input_sha256", "purpose", "company_id", "profile_version_id", "profile_sha256",
    "graph_version_id", "graph_sha256", "ontology_version", "ontology_sha256", "documents",
    "overview_run_id", "overview_sha256", "bundle_id", "policy_version_id", "policy_sha256",
    "model_name", "model_revision", "generation_config_sha256",
})


class CompanyAnalysisError(ValueError):
    """A contract gate code (``company_not_found`` etc.) without source detail."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CompanyKnowledgeContext:
    """The active binding of one company, resolved and validated once."""

    company: Company
    binding: CompanyKnowledgeBinding
    graph: CompanyKnowledgeVersion
    profile: ProfileVersion
    ontology_row: KnowledgeOntologyVersion
    ontology: ValidatedOntology
    graph_nodes: tuple[Mapping[str, Any], ...]
    graph_edges: tuple[Mapping[str, Any], ...]
    profile_context: Mapping[str, Any]


def resolve_company_knowledge_context(session: Session, company_id: UUID) -> CompanyKnowledgeContext:
    """Resolve the active binding into graph/profile/ontology inputs.

    ``company_not_found``: no such company.  ``company_profile_not_ready``: no
    active binding, or the bound profile is not a v2 company profile.
    ``company_input_invalid``: the frozen lineage (graph/profile/ontology/
    evidence) does not validate or belongs to another company.
    """

    company = session.get(Company, company_id)
    if company is None:
        raise CompanyAnalysisError("company_not_found")
    binding = session.get(CompanyKnowledgeBinding, company_id)
    if binding is None:
        raise CompanyAnalysisError("company_profile_not_ready")
    graph = session.get(CompanyKnowledgeVersion, binding.graph_version_id)
    profile = session.get(ProfileVersion, binding.profile_version_id)
    if (
        graph is None
        or profile is None
        or graph.company_id != company_id
        or profile.company_id != company_id
        or graph.profile_version_id != profile.id
    ):
        raise CompanyAnalysisError("company_input_invalid")
    payload = profile.profile_payload if isinstance(profile.profile_payload, Mapping) else {}
    if payload.get("schema") != PROFILE_SCHEMA_V2:
        raise CompanyAnalysisError("company_profile_not_ready")
    ontology_row = session.get(KnowledgeOntologyVersion, graph.ontology_id)
    if ontology_row is None or not isinstance(ontology_row.payload, Mapping):
        raise CompanyAnalysisError("company_input_invalid")
    try:
        ontology = parse_ontology(canonical_json_bytes(ontology_row.payload))
    except (OntologyValidationError, TypeError, ValueError):
        raise CompanyAnalysisError("company_input_invalid") from None
    if ontology.sha256 != ontology_row.sha256 or ontology.version != ontology_row.version:
        raise CompanyAnalysisError("company_input_invalid")
    try:
        nodes, edges = company_knowledge_public_graph(
            session, company_id=company_id, graph_version_id=graph.id
        )
        context = profile_context(session, profile)
    except (CompanyKnowledgeServiceError, InputVersionError):
        raise CompanyAnalysisError("company_input_invalid") from None
    return CompanyKnowledgeContext(
        company=company, binding=binding, graph=graph, ontology_row=ontology_row,
        ontology=ontology, graph_nodes=tuple(nodes), graph_edges=tuple(edges),
        profile=profile, profile_context=context,
    )


def document_provenance(session: Session, document_version_ids: Sequence[UUID]) -> list[dict[str, str]]:
    """``[{document_version_id, source_sha256}]`` from immutable DocumentVersion rows.

    Sorted by ``document_version_id``; the hash is the pinned content object's.
    """

    ids = sorted({UUID(str(value)) for value in document_version_ids}, key=str)
    if not ids:
        raise CompanyAnalysisError("company_input_invalid")
    rows = session.execute(
        select(DocumentVersion.id, ContentObject.sha256)
        .join(ContentObject, ContentObject.id == DocumentVersion.content_object_id)
        .where(DocumentVersion.id.in_(ids))
    ).all()
    found = {row_id: digest for row_id, digest in rows}
    if set(found) != set(ids):
        raise CompanyAnalysisError("company_input_invalid")
    return [{"document_version_id": str(value), "source_sha256": found[value]} for value in ids]


def ready_bundle_document_sets(
    session: Session, notice_ids: Sequence[int]
) -> dict[int, tuple[UUID, list[UUID]]]:
    """notice → (latest ``ready`` bundle id, its document_version_ids sorted). Two queries.

    The notice's common current document-version set (company independent):
    the deep-review preview freezes exactly these documents (its bundle), and
    the company detail/comparison reads report them.  A notice without a
    ready bundle is absent.
    """

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return {}
    bundles: dict[int, UUID] = {}
    for bundle_id, notice_id in session.execute(
        select(DocumentBundle.id, DocumentBundle.notice_id)
        .where(DocumentBundle.notice_id.in_(ids), DocumentBundle.status == "ready")
        .order_by(DocumentBundle.revision.desc(), DocumentBundle.id.desc())
    ).all():
        bundles.setdefault(int(notice_id), bundle_id)
    if not bundles:
        return {}
    documents: dict[UUID, set[UUID]] = {}
    for bundle_id, document_id in session.execute(
        select(DocumentBundleItem.bundle_id, DocumentBundleItem.document_version_id)
        .where(DocumentBundleItem.bundle_id.in_(set(bundles.values())))
    ).all():
        documents.setdefault(bundle_id, set()).add(document_id)
    return {
        notice_id: (bundle_id, sorted(documents.get(bundle_id, set()), key=str))
        for notice_id, bundle_id in bundles.items()
    }


def notice_document_sets(session: Session, notice_ids: Sequence[int]) -> dict[int, list[UUID]]:
    """notice → the document-version set a company fit freezes (sorted by id). Three queries max.

    The latest ready bundle's documents (``ready_bundle_document_sets``, the
    same set a deep review freezes and the comparison uses), so a fit and a
    review of the same notice can be compared on one document list (§10
    verifier).  A notice without a ready bundle falls back to all its
    ``is_current`` DocumentVersion rows: the fit gates (§9) do not require a
    bundle, and the frozen list then honestly records what was current at
    enqueue (a later bundle with other documents reads as a different input).
    """

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    out = {notice_id: list(documents) for notice_id, (_bundle, documents) in ready_bundle_document_sets(session, ids).items()}
    missing = [notice_id for notice_id in ids if notice_id not in out]
    if missing:
        current: dict[int, list[UUID]] = {}
        for document_id, notice_id in session.execute(
            select(DocumentVersion.id, DocumentVersion.notice_id).where(
                DocumentVersion.notice_id.in_(missing), DocumentVersion.is_current.is_(True),
            )
        ).all():
            current.setdefault(int(notice_id), []).append(document_id)
        for notice_id, documents in current.items():
            out[notice_id] = sorted(documents, key=str)
    return out


def build_company_analysis_input(
    *,
    purpose: str,
    execution_nonce: UUID,
    knowledge: CompanyKnowledgeContext,
    notice_id: int,
    document_version_ids: Sequence[UUID],
    overview_run_id: UUID,
    overview_sha256: str,
    policy_version_id: UUID,
    policy_sha256: str,
    model_name: str,
    model_revision: str | None,
    generation: Mapping[str, Any],
    requirements: Sequence[Mapping[str, Any]],
    path_limit_per_requirement: int,
    profile_characters: int,
    bundle_id: UUID | None = None,
    target_review_id: UUID | None = None,
) -> dict[str, Any]:
    """Assemble one CompanyAnalysisInput (contract §5).

    ``generation_config_sha256`` is the canonical hash of the policy's
    ``generation``.  Any retrieval failure (fallback units, required facts over
    budget, broken graph) is ``company_input_invalid``.
    """

    if purpose not in PURPOSES:
        raise CompanyAnalysisError("company_input_invalid")
    try:
        retrieval = build_company_retrieval(
            requirements,
            ontology=knowledge.ontology,
            graph_nodes=knowledge.graph_nodes,
            graph_edges=knowledge.graph_edges,
            profile=knowledge.profile_context,
            path_limit_per_requirement=path_limit_per_requirement,
            profile_budget=profile_characters,
        )
    except CompanyRetrievalError:
        raise CompanyAnalysisError("company_input_invalid") from None
    value: dict[str, Any] = {
        "schema_version": COMPANY_ANALYSIS_INPUT_SCHEMA,
        "purpose": purpose,
        "execution_nonce": str(execution_nonce),
        "target_review_id": None if target_review_id is None else str(target_review_id),
        "company_id": str(knowledge.company.id),
        "profile_version_id": str(knowledge.profile.id),
        "profile_sha256": knowledge.profile.profile_sha256,
        "graph_version_id": str(knowledge.graph.id),
        "graph_sha256": knowledge.graph.graph_sha256,
        "ontology_version": knowledge.ontology_row.version,
        "ontology_sha256": knowledge.ontology_row.sha256,
        "notice_id": int(notice_id),
        "document_version_ids": [str(value) for value in document_version_ids],
        "bundle_id": None if bundle_id is None else str(bundle_id),
        "overview_run_id": str(overview_run_id),
        "overview_sha256": overview_sha256,
        "policy_version_id": str(policy_version_id),
        "policy_sha256": policy_sha256,
        "model_name": model_name,
        "model_revision": model_revision,
        "generation_config_sha256": canonical_json_hash(dict(generation)),
        **retrieval,
    }
    if set(value) != COMPANY_ANALYSIS_INPUT_KEYS:
        raise CompanyAnalysisError("company_input_invalid")
    return value


def frozen_provenance(
    input_value: Mapping[str, Any],
    *,
    input_sha256: str,
    documents: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """FrozenProvenance for a frozen CompanyAnalysisInput (contract §10).

    Identity fields are copied from the input itself so view and provenance
    can never disagree; ``documents`` come from ``document_provenance``.
    """

    copied = (
        "purpose", "company_id", "profile_version_id", "profile_sha256", "graph_version_id",
        "graph_sha256", "ontology_version", "ontology_sha256", "overview_run_id",
        "overview_sha256", "bundle_id", "policy_version_id", "policy_sha256", "model_name",
        "model_revision", "generation_config_sha256",
    )
    value: dict[str, Any] = {key: input_value[key] for key in copied}
    value["input_sha256"] = input_sha256
    value["documents"] = [
        {"document_version_id": str(row["document_version_id"]), "source_sha256": str(row["source_sha256"])}
        for row in documents
    ]
    if [row["document_version_id"] for row in value["documents"]] != sorted(input_value["document_version_ids"]):
        raise CompanyAnalysisError("company_input_invalid")
    if set(value) != FROZEN_PROVENANCE_KEYS:
        raise CompanyAnalysisError("company_input_invalid")
    return value


__all__ = [
    "COMPANY_ANALYSIS_INPUT_KEYS",
    "COMPANY_ANALYSIS_INPUT_SCHEMA",
    "CompanyAnalysisError",
    "CompanyKnowledgeContext",
    "FROZEN_PROVENANCE_KEYS",
    "build_company_analysis_input",
    "document_provenance",
    "frozen_provenance",
    "notice_document_sets",
    "ready_bundle_document_sets",
    "resolve_company_knowledge_context",
]
