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

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
import unicodedata
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.company_ontology import (
    OntologyConcept,
    OntologyValidationError,
    ValidatedOntology,
    normalize_term,
    parse_ontology,
)
from ...core.model_binding import canonical_json_bytes
from ...core.model_client import sanitize_for_prompt
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
from .company_knowledge_retrieval import CompanyRetrievalError, build_company_retrieval, match_concepts
from .input_versions import InputVersionError, canonical_json_hash, profile_context


COMPANY_ANALYSIS_INPUT_SCHEMA = "bidops.company-analysis-input.v1"
#: HP-03 v2 envelope; RL-03 nests ``card_analysis`` (``card-v1`` policies only).
COMPANY_ANALYSIS_INPUT_V2_SCHEMA = "bidops.company-analysis-input.v2"
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
#: Every key of CompanyAnalysisInput v2: v1 keys + ``card_analysis`` (RL-03).
COMPANY_ANALYSIS_INPUT_V2_KEYS = COMPANY_ANALYSIS_INPUT_KEYS | {"card_analysis"}
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
    """notice → the document-version set a **v2-era** company fit froze (sorted by id). Three queries max.

    The latest ready bundle's documents (``ready_bundle_document_sets``), else
    every ``is_current`` DocumentVersion row of the notice.  Since the
    2026-10-11 amendment (§9, STEP-008) a new fit enqueue requires a ready
    bundle and freezes exactly its documents, so the fallback is no longer a
    fit input.  It remains only for the currentness of attempts frozen on a
    ``bidops.company-fit-policy.v2`` row before the amendment, which may have
    recorded a notice's current documents without a bundle
    (``company_fit.company_current_flags``).
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
    overview_run_id: UUID | None,
    overview_sha256: str | None,
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
    select_all_facts: bool = False,
) -> dict[str, Any]:
    """Assemble one CompanyAnalysisInput v1 (contract §5); ``select_all_facts`` must stay false.

    ``generation_config_sha256`` is the canonical hash of the policy's
    ``generation``.  Any retrieval failure (fallback units, required facts over
    budget, broken graph) is ``company_input_invalid``.  v1 always carries a
    completed overview: a null ``overview_*`` is ``company_input_invalid``
    (only the v2 ``card-v1`` envelope freezes them as null, RL-03 D1).
    """

    if overview_run_id is None or overview_sha256 is None or select_all_facts:
        raise CompanyAnalysisError("company_input_invalid")
    return _assemble_input(
        purpose=purpose, execution_nonce=execution_nonce, knowledge=knowledge, notice_id=notice_id,
        document_version_ids=document_version_ids, overview_run_id=overview_run_id,
        overview_sha256=overview_sha256, policy_version_id=policy_version_id, policy_sha256=policy_sha256,
        model_name=model_name, model_revision=model_revision, generation=generation,
        requirements=requirements, path_limit_per_requirement=path_limit_per_requirement,
        profile_characters=profile_characters, bundle_id=bundle_id, target_review_id=target_review_id,
        select_all_facts=False,
    )


def _assemble_input(
    *,
    purpose: str,
    execution_nonce: UUID,
    knowledge: CompanyKnowledgeContext,
    notice_id: int,
    document_version_ids: Sequence[UUID],
    overview_run_id: UUID | None,
    overview_sha256: str | None,
    policy_version_id: UUID,
    policy_sha256: str,
    model_name: str,
    model_revision: str | None,
    generation: Mapping[str, Any],
    requirements: Sequence[Mapping[str, Any]],
    path_limit_per_requirement: int,
    profile_characters: int,
    bundle_id: UUID | None,
    target_review_id: UUID | None,
    select_all_facts: bool,
) -> dict[str, Any]:
    if purpose not in PURPOSES or (overview_run_id is None) != (overview_sha256 is None):
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
            select_all_facts=select_all_facts,
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
        "overview_run_id": None if overview_run_id is None else str(overview_run_id),
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


def build_company_analysis_input_v2(
    *,
    card_analysis: Mapping[str, Any],
    purpose: str,
    execution_nonce: UUID,
    knowledge: CompanyKnowledgeContext,
    notice_id: int,
    document_version_ids: Sequence[UUID],
    policy_version_id: UUID,
    policy_sha256: str,
    model_name: str,
    model_revision: str | None,
    generation: Mapping[str, Any],
    requirements: Sequence[Mapping[str, Any]],
    path_limit_per_requirement: int,
    profile_characters: int,
    overview_run_id: UUID | None = None,
    overview_sha256: str | None = None,
    bundle_id: UUID | None = None,
    target_review_id: UUID | None = None,
) -> dict[str, Any]:
    """Assemble one CompanyAnalysisInput v2 for an RL ``card-v1`` deep review.

    Exactly the v1 keys + ``card_analysis`` (``bidops.card-analysis-input.v1``).
    ``overview_*`` are both null for ``card-v1`` (RL-03 D1) -- both null or
    both set is enforced.  Retrieval freezes **every** binding fact with its
    node and evidence (D2: the transfer projection later sends every
    ``confirmed`` fact with its value).  ``card_analysis.company_binding``
    must be the same binding as the top-level identity; any mismatch is
    ``company_input_invalid``.
    """

    from ..schemas.card_analysis import CardAnalysisInput
    from ..schemas.company_analysis import validate_company_analysis_input

    if purpose != "deep_review":
        raise CompanyAnalysisError("company_input_invalid")
    try:
        frozen_card = CardAnalysisInput.model_validate(card_analysis).model_dump(mode="json")
    except (TypeError, ValueError):
        raise CompanyAnalysisError("company_input_invalid") from None
    value = _assemble_input(
        purpose=purpose, execution_nonce=execution_nonce, knowledge=knowledge, notice_id=notice_id,
        document_version_ids=document_version_ids, overview_run_id=overview_run_id,
        overview_sha256=overview_sha256, policy_version_id=policy_version_id, policy_sha256=policy_sha256,
        model_name=model_name, model_revision=model_revision, generation=generation,
        requirements=requirements, path_limit_per_requirement=path_limit_per_requirement,
        profile_characters=profile_characters, bundle_id=bundle_id, target_review_id=target_review_id,
        select_all_facts=True,
    )
    value["schema_version"] = COMPANY_ANALYSIS_INPUT_V2_SCHEMA
    value["card_analysis"] = frozen_card
    if set(value) != COMPANY_ANALYSIS_INPUT_V2_KEYS:
        raise CompanyAnalysisError("company_input_invalid")
    fact_keys = {row["fact_key"] for row in value["profile_facts"]}
    binding_keys = {
        fact.get("fact_key") for fact in knowledge.profile_context.get("facts", []) if isinstance(fact, Mapping)
    }
    if fact_keys != binding_keys or value["coverage"]["excluded_fact_keys"]:
        raise CompanyAnalysisError("company_input_invalid")
    try:
        validate_company_analysis_input(value)
    except ValueError:
        raise CompanyAnalysisError("company_input_invalid") from None
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


# --- RL-03 compare fact allowlist (spec "대조 fact_key allowlist") -------------------
#
# The deterministic compare (STEP-005) reads company facts only through these
# (fact_key, value path) pairs of the frozen input -- never a scalar guess, a
# sum of other nodes, or a fact outside the list.  ``qual:social_enterprise``
# and ``qual:staff_certifications`` are bonus/information items and are not
# compared.

CARD_COMPARE_FACT_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "staff:onsite": (("available",), ("region",)),
    # 회사소개서 confirmed 58명; never replaced by a sum of the field nodes.
    "staff:total": (("total",),),
    # v2 fixture: ``total`` is null, ``available`` = 5.
    "staff:design_publishing": (("available",),),
    # ``detail`` null → item names cannot be compared → unknown.
    "qual:direct_production": (("held",), ("detail",)),
    "qual:procurement_1468": (("held",),),
    # ``valid_until`` null → a validity requirement stays unknown.
    "qual:sme_certificate": (("held",), ("valid_until",)),
    "qual:sw_business": (("held",),),
    # proposed in the v2 fixture → always unknown (``proposed_fact``).
    "qual:credit_rating": (("held",), ("detail",)),
    # ``detail`` null → ISMS / ISMS-P cannot be told apart → unknown.
    "qual:infosec_cert": (("detail",),),
    # held=true means "no sanction" (requirement met).
    "qual:sanction_free": (("held",),),
    # the branch string ("대구(본점), 세종") is ``detail``; ``held`` alone decides nothing.
    "qual:branch": (("detail",),),
    "pref:solo_cap": (("params", "krw"),),
    "pref:consortium": (("params",),),
    "pref:subcontract": (("params", "allowed"),),
}


@dataclass(frozen=True)
class CardFactReading:
    """One allowlisted company value read from the frozen input.

    ``state``: ``confirmed`` (``value`` usable) | ``null`` (confirmed fact,
    value at the path is null → unknown) | ``proposed`` | ``unknown`` |
    ``inferred`` (not evidence; compare answers unknown) | ``absent`` (fact
    missing from the frozen input).
    """

    fact_key: str
    path: tuple[str, ...]
    state: str
    value: Any = None


def card_fact_value(frozen: Mapping[str, Any], fact_key: str, path: Sequence[str]) -> CardFactReading:
    """Read an allowlisted ``(fact_key, path)``; anything outside the list is ``company_input_invalid``."""

    path = tuple(path)
    if path not in CARD_COMPARE_FACT_PATHS.get(fact_key, ()):
        raise CompanyAnalysisError("company_input_invalid")
    fact = next(
        (row for row in frozen.get("profile_facts", []) if isinstance(row, Mapping) and row.get("fact_key") == fact_key),
        None,
    )
    if fact is None:
        return CardFactReading(fact_key, path, "absent")
    status = fact.get("status")
    if status != "confirmed":
        return CardFactReading(fact_key, path, str(status))
    value: Any = fact.get("value")
    for part in path:
        value = value.get(part) if isinstance(value, Mapping) else None
    if value is None:
        return CardFactReading(fact_key, path, "null")
    return CardFactReading(fact_key, path, "confirmed", deepcopy(value))


# --- RL-03 transfer payload projection (spec "전송 payload 규칙", D2) ----------------
#
# The frozen v2 input (``deep_review_preview.input_snapshot``) is never sent as
# is.  Each Luna stage payload is a deterministic projection of it:
#
# * notice: the frozen card/segment units of the batch (+ previous validated
#   stage results, supplied by the caller);
# * extract: ontology concepts as ``{id, label, aliases}`` (ontology text, not
#   company data; 2026-10-17 결정 B10);
# * company (role/synthesis only): only the facts **referenced** by that
#   call's compare results (role = ``constraint_results[].fact_ids`` of its
#   compare rows; synthesis = the union over its three roles; 결정 B11).  A
#   referenced ``confirmed`` fact carries ``fact_key, type, label, status,
#   origin, value`` and its ``confirmed`` evidence ``profile_evidence_id,
#   fact_key, quote``; a referenced ``proposed``/``unknown``/``inferred`` fact is
#   ``{fact_key, status}`` only; unreferenced facts are never sent;
# * synthesis of a ``card-sections-v2``/``-v3`` input (결정 B24): also
#   ``missing_sections`` = the frozen ``card_analysis.missing_sections``
#   exactly (possibly empty) so the model knows which source areas were not
#   found; a ``card-sections-v1`` synthesis payload has no such key;
# * extract of a ``card-sections-v3`` input (결정 B30): every unit is the
#   frozen unit plus ``expected_concepts`` = ``card_expected_concepts`` of
#   its block texts (``[{concept_id, alias_text}]``, ontology terms as they
#   occur in the unit text; computed with the validator's ``match_concepts``)
#   so a contract-following answer can copy them; v1/v2 extract units are
#   the frozen units unchanged.  Policy v4 (결정 B33, stage schema
#   ``bidops.requirement-extract.v2``) sends the frozen units unchanged even
#   for ``card-sections-v3``: code fills the concepts after the call (they are
#   still computed before the call so an inexpressible unit fails closed);
# * never: notes, operational ids (approval/cap/briefing/Slack/attempt/review),
#   policy/model identity, company binding version ids or hashes.
#
# ``check_card_transfer_payload`` asserts this strictly per stage and fails
# closed with ``company_input_invalid`` before any call; every builder below
# runs it on its own output.

#: Exact top-level keys of each stage payload (``input`` of the stage prompt).
CARD_TRANSFER_STAGE_KEYS: dict[str, frozenset[str]] = {
    "extract": frozenset({"schema_version", "batch", "units", "ontology"}),
    "role": frozenset({"role", "extract", "compare", "profile_facts", "profile_evidence"}),
    "synthesis": frozenset({"roles", "profile_facts", "profile_evidence"}),
}
#: 결정 B24: the extra synthesis key of a ``card-sections-v2``/``-v3`` input.
CARD_SYNTHESIS_V2_EXTRA_KEYS = frozenset({"missing_sections"})
_MISSING_SECTIONS_SELECTORS = frozenset({"card-sections-v2", "card-sections-v3"})
#: 결정 B51: the extra synthesis key of a policy v7 payload (isolated unit ids).
CARD_SYNTHESIS_V7_EXTRA_KEYS = frozenset({"rejected_units"})
#: 결정 B30: the extra per-unit extract key of a ``card-sections-v3`` input.
CARD_EXTRACT_V3_UNIT_EXTRA_KEYS = frozenset({"expected_concepts"})
CARD_EXPECTED_CONCEPT_KEYS = frozenset({"concept_id", "alias_text"})
_EXPECTED_CONCEPTS_SELECTOR = "card-sections-v3"
#: Policy ``stage_schema`` values (결정 B33).  v2: concepts are code-filled, not sent.
_STAGE_SCHEMA_V1 = "bidops.requirement-extract.v1"
_STAGE_SCHEMA_V2 = "bidops.requirement-extract.v2"
CARD_CONFIRMED_FACT_KEYS = ("fact_key", "type", "label", "status", "origin", "value")
CARD_WITHHELD_FACT_KEYS = frozenset({"fact_key", "status"})
CARD_WITHHELD_NODE_KEYS = frozenset({"id", "status"})
CARD_TRANSFER_EVIDENCE_KEYS = ("profile_evidence_id", "fact_key", "quote")
#: Keys that never appear anywhere in a stage payload.
CARD_FORBIDDEN_TRANSFER_KEYS = frozenset({
    # model / policy identity
    "policy_identity", "policy_version_id", "policy_sha256", "model_name", "model_revision",
    "generation_config_sha256", "reasoning_effort", "cli_version",
    # company binding identity
    "company_id", "company_binding", "graph_version_id", "graph_sha256", "profile_version_id",
    "profile_sha256", "ontology_version", "ontology_sha256", "source_refs",
    # operational ids
    "approval_id", "daily_cap", "today_used", "attempt_id", "review_id", "preview_id",
    "request_id", "execution_nonce", "target_review_id", "bundle_id", "notice_id",
    "input_sha256", "briefing_id", "briefing_item_id", "slack_message_ts", "slack_channel",
    "thread_ts",
    # RL-02 notes
    "note", "notes", "note_body",
})
_FROZEN_FORBIDDEN_VALUE_KEYS = (
    "policy_version_id", "policy_sha256", "generation_config_sha256", "graph_version_id",
    "graph_sha256", "profile_version_id", "profile_sha256", "ontology_sha256", "company_id",
    "execution_nonce", "target_review_id", "bundle_id", "model_name", "model_revision",
)
_MIN_WITHHELD_TEXT = 4
_COMPANY_FACT_MARKERS = frozenset({"status", "origin", "label", "type", "profile_evidence_id"})


def _transfer_invalid() -> CompanyAnalysisError:
    return CompanyAnalysisError("company_input_invalid")


def _canonical_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _frozen_card_input(frozen: Mapping[str, Any]) -> Mapping[str, Any]:
    if (
        not isinstance(frozen, Mapping)
        or frozen.get("schema_version") != COMPANY_ANALYSIS_INPUT_V2_SCHEMA
        or set(frozen) != COMPANY_ANALYSIS_INPUT_V2_KEYS
        or not isinstance(frozen.get("card_analysis"), Mapping)
    ):
        raise _transfer_invalid()
    return frozen


def card_synthesis_missing_sections(frozen: Mapping[str, Any]) -> list[str] | None:
    """The synthesis ``missing_sections`` of a frozen input (결정 B24).

    ``card-sections-v2``/``-v3``: a copy of the frozen ``card_analysis.missing_sections``
    (possibly empty).  ``card-sections-v1``: ``None`` -- that payload carries no
    such key (a v1 input never reaches synthesis with missing sections).
    """

    card = _frozen_card_input(frozen)["card_analysis"]
    if _selector_version(card) not in _MISSING_SECTIONS_SELECTORS:
        return None
    missing = card.get("missing_sections")
    if not isinstance(missing, list) or any(not isinstance(row, str) for row in missing):
        raise _transfer_invalid()
    return list(missing)


def _selector_version(card: Mapping[str, Any]) -> str | None:
    selector = card.get("selector")
    version = selector.get("version") if isinstance(selector, Mapping) else None
    return version if isinstance(version, str) else None


def _concept_rows(ontology: Any) -> tuple[OntologyConcept, ...]:
    concepts = ontology.concepts if isinstance(ontology, ValidatedOntology) else ontology
    if isinstance(concepts, (str, bytes, Mapping)) or not isinstance(concepts, Iterable):
        raise _transfer_invalid()
    rows = tuple(concepts)
    if not rows or any(not isinstance(row, OntologyConcept) for row in rows):
        raise _transfer_invalid()
    return rows


def _normalized_with_offsets(text: str) -> tuple[str, list[int]]:
    """``normalize_term`` applied per character, with each output character's source index."""

    characters: list[str] = []
    offsets: list[int] = []
    space = True  # leading whitespace is dropped, runs collapse to one space
    for index, character in enumerate(text):
        for out in unicodedata.normalize("NFKC", character).casefold():
            if out.isspace():
                if space:
                    continue
                characters.append(" ")
                offsets.append(index)
                space = True
            else:
                characters.append(out)
                offsets.append(index)
                space = False
    return "".join(characters), offsets


def _term_spans(text: str, term: str) -> list[tuple[int, int]]:
    """``(start, end)`` of verbatim substrings of ``text`` whose ``normalize_term`` form is the term's."""

    needle = normalize_term(term)
    if not needle:
        return []
    normalized, offsets = _normalized_with_offsets(text)
    spans: list[tuple[int, int]] = []
    start = normalized.find(needle)
    while start >= 0:
        last = start + len(needle) - 1
        if last < len(offsets):
            begin, end = offsets[start], offsets[last] + 1
            candidate = text[begin:end]
            if candidate and candidate.strip() == candidate and normalize_term(candidate) == needle:
                spans.append((begin, end))
        start = normalized.find(needle, start + 1)
    return spans


def card_expected_concepts(texts: Sequence[str], ontology: Any) -> list[dict[str, str]]:
    """Deterministic ``concept_candidates`` of one unit (결정 B30), ``[{concept_id, alias_text}]``.

    The expected set is exactly what the extract validator demands: the union
    of ``match_concepts`` over the unit's block texts.  For every expected
    concept (id order) not yet covered, the first verbatim occurrence in the
    unit text (block order, then label/aliases order, then position) of one
    of its own ontology terms that ``match_concepts`` also accepts in its
    context is taken as ``alias_text`` when every concept
    ``match_concepts(alias_text)`` returns is expected; that alias then
    contributes one row per concept it matches (the validator requires the
    complete match set per alias).  ``alias_text`` is therefore ontology
    wording as written in the notice, never a semantic mapping.  A concept
    without such an occurrence cannot be expressed in a passing answer and is
    ``company_input_invalid`` before any call (never a guessed alias).
    Rows are sorted by ``(concept_id, alias_text)`` and unique.
    """

    if isinstance(texts, (str, bytes)) or any(not isinstance(text, str) for text in texts):
        raise _transfer_invalid()
    concepts = _concept_rows(ontology)
    by_id = {concept.id: concept for concept in concepts}
    expected = {concept_id for text in texts for concept_id in match_concepts(text, concepts)}
    rows: set[tuple[str, str]] = set()
    covered: set[str] = set()
    for concept_id in sorted(expected):
        if concept_id in covered:
            continue
        concept = by_id[concept_id]
        chosen: tuple[str, set[str]] | None = None
        for text in texts:
            for term in (concept.label, *concept.aliases):
                for begin, end in _term_spans(text, term):
                    alias = text[begin:end]
                    # The occurrence itself must match in its context (one
                    # neighbour each side), e.g. "ai" inside "mail" does not.
                    if concept_id not in match_concepts(text[max(0, begin - 1):end + 1], concepts):
                        continue
                    matched = set(match_concepts(alias, concepts))
                    if concept_id in matched and matched <= expected:
                        chosen = (alias, matched)
                        break
                if chosen is not None:
                    break
            if chosen is not None:
                break
        if chosen is None:
            raise _transfer_invalid()
        alias, matched = chosen
        rows.update((matched_id, alias) for matched_id in matched)
        covered.update(matched)
    if covered != expected:
        raise _transfer_invalid()
    return [{"concept_id": concept_id, "alias_text": alias} for concept_id, alias in sorted(rows)]


def _unit_texts(unit: Mapping[str, Any]) -> list[str]:
    blocks = unit.get("blocks") if isinstance(unit, Mapping) else None
    if not isinstance(blocks, list) or any(
        not isinstance(block, Mapping) or not isinstance(block.get("text"), str) for block in blocks
    ):
        raise _transfer_invalid()
    return [block["text"] for block in blocks]


def _without_prompt_sensitive_keys(value: Any) -> Any:
    """Drop members whose *key* the core prompt sanitizer never lets into a prompt.

    RL-00 qualification values carry ``file_name`` (an attachment file name);
    ``sanitize_for_prompt`` treats ``file``/``path``/``url``/``token``… keys as
    storage or credential metadata.  Only such keys are removed -- text is
    never rewritten (a URL/path/secret inside a value still fails the
    sanitizer-stability check below).
    """

    if isinstance(value, Mapping):
        return {
            key: _without_prompt_sensitive_keys(item)
            for key, item in value.items()
            if sanitize_for_prompt({str(key): None}) != {}
        }
    if isinstance(value, list):
        return [_without_prompt_sensitive_keys(item) for item in value]
    return deepcopy(value)


def card_referenced_fact_keys(compare: Mapping[str, Any]) -> list[str]:
    """Fact keys referenced by compare rows (``constraint_results[].fact_ids``), first-seen order (B11)."""

    keys: list[str] = []
    items = compare.get("items") if isinstance(compare, Mapping) else None
    if not isinstance(items, list):
        raise _transfer_invalid()
    for item in items:
        results = item.get("constraint_results") if isinstance(item, Mapping) else None
        if not isinstance(results, list):
            raise _transfer_invalid()
        for result in results:
            fact_ids = result.get("fact_ids") if isinstance(result, Mapping) else None
            if not isinstance(fact_ids, list) or any(not isinstance(key, str) for key in fact_ids):
                raise _transfer_invalid()
            keys.extend(key for key in fact_ids if key not in keys)
    return keys


def card_company_transfer(frozen: Mapping[str, Any], fact_keys: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    """``{profile_facts, profile_evidence}`` of exactly the referenced facts (D2 + 결정 B11).

    Rows keep the frozen ``profile_facts`` order.  A key that is not a frozen
    fact is ``company_input_invalid``.  ``confirmed`` values are sent whole
    except prompt-sensitive metadata keys (``_without_prompt_sensitive_keys``);
    the part must be stable under the core prompt sanitizer or the payload
    check fails closed.
    """

    frozen = _frozen_card_input(frozen)
    if isinstance(fact_keys, (str, bytes)):
        raise _transfer_invalid()
    referenced = set(fact_keys)
    nodes = {
        row.get("id"): row for row in frozen.get("graph_nodes", []) if isinstance(row, Mapping)
    }
    facts: list[dict[str, Any]] = []
    confirmed: set[str] = set()
    known: set[str] = set()
    for fact in frozen.get("profile_facts", []):
        if not isinstance(fact, Mapping) or not isinstance(fact.get("fact_key"), str):
            raise _transfer_invalid()
        key = fact["fact_key"]
        known.add(key)
        if key not in referenced:
            continue
        node = nodes.get(key)
        if node is None or node.get("status") != fact.get("status"):
            raise _transfer_invalid()
        if fact.get("status") == "confirmed":
            confirmed.add(key)
            facts.append({
                "fact_key": key, "type": node.get("type"), "label": node.get("label"),
                "status": "confirmed", "origin": fact.get("origin"),
                "value": _without_prompt_sensitive_keys(fact.get("value")),
            })
        else:
            facts.append({"fact_key": key, "status": fact.get("status")})
    if not referenced <= known:
        raise _transfer_invalid()
    evidence = [
        {name: row.get(name) for name in CARD_TRANSFER_EVIDENCE_KEYS}
        for row in frozen.get("profile_evidence", [])
        if isinstance(row, Mapping) and row.get("fact_key") in confirmed
    ]
    return {"profile_facts": facts, "profile_evidence": evidence}


def _withheld_texts(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        if len(value) >= _MIN_WITHHELD_TEXT:
            out.append(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            out.extend(_withheld_texts(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_withheld_texts(item))
    return out


def _walk_transfer(value: Any, withheld: Mapping[str, str]) -> None:
    if isinstance(value, Mapping):
        keys = set(value)
        if keys & CARD_FORBIDDEN_TRANSFER_KEYS:
            raise _transfer_invalid()
        fact_key = value.get("fact_key")
        # A company fact row (or its evidence) is recognised by its own keys; an
        # extract constraint also names a ``fact_key`` (allowlist link to the
        # notice condition) but carries no company status/origin/label/value.
        if isinstance(fact_key, str) and fact_key in withheld and keys & _COMPANY_FACT_MARKERS:
            if keys != CARD_WITHHELD_FACT_KEYS or value.get("status") != withheld[fact_key]:
                raise _transfer_invalid()
        node_id = value.get("id")
        if isinstance(node_id, str) and node_id in withheld:
            if keys != CARD_WITHHELD_NODE_KEYS or value.get("status") != withheld[node_id]:
                raise _transfer_invalid()
        for item in value.values():
            _walk_transfer(item, withheld)
    elif isinstance(value, list):
        for item in value:
            _walk_transfer(item, withheld)


def check_card_transfer_payload(
    stage: str,
    payload: Mapping[str, Any],
    frozen: Mapping[str, Any],
    *,
    fact_keys: Iterable[str] | None = None,
    operational_values: Sequence[Any] = (),
    ontology: Any = None,
    stage_schema: str = _STAGE_SCHEMA_V1,
    rejected_units: Sequence[str] | None = None,
) -> None:
    """Strict D2 check of one stage payload against its frozen v2 input.

    ``company_input_invalid`` when: the top-level keys are not the stage's
    exact set; an extract batch/unit is not the frozen card/segment unit or the
    ontology rows are not ``{id, label, aliases}`` (B10) -- with ``ontology``
    given they must equal its projection; a ``card-sections-v3`` extract unit
    is the frozen unit plus exactly ``expected_concepts`` =
    ``card_expected_concepts`` of its texts (``ontology`` required, 결정 B30)
    and a v1/v2 unit carries no such key; with ``stage_schema`` =
    ``bidops.requirement-extract.v2`` (policy v4, 결정 B33) no unit carries it
    (``ontology`` required, the expected concepts must still be computable);
    the company part is
    not exactly ``card_company_transfer(frozen, referenced)`` -- role:
    referenced = the fact ids of its own ``compare`` (``fact_keys``, when given,
    must equal it); synthesis: ``fact_keys`` is required (union over the
    roles, B11); any object
    carries a forbidden key; a non-confirmed fact/node appears with more than
    ``{fact_key|id, status}``; or a frozen identity value, a caller-supplied
    operational value, or text of a non-confirmed fact value occurs anywhere.
    """

    frozen = _frozen_card_input(frozen)
    expected_keys = CARD_TRANSFER_STAGE_KEYS.get(stage)
    missing_sections = card_synthesis_missing_sections(frozen) if stage == "synthesis" else None
    if expected_keys is not None and missing_sections is not None:
        expected_keys = expected_keys | CARD_SYNTHESIS_V2_EXTRA_KEYS
    if rejected_units is not None:
        # 결정 B51 (policy v7): the synthesis names the isolated units (ids only).
        if stage != "synthesis" or expected_keys is None:
            raise _transfer_invalid()
        expected_keys = expected_keys | CARD_SYNTHESIS_V7_EXTRA_KEYS
    if expected_keys is None or not isinstance(payload, Mapping) or set(payload) != expected_keys:
        raise _transfer_invalid()
    if missing_sections is not None and payload.get("missing_sections") != missing_sections:
        # 결정 B24: exactly the frozen list, in its order (possibly empty).
        raise _transfer_invalid()
    card = frozen["card_analysis"]
    if rejected_units is not None:
        frozen_unit_ids = {row.get("unit_id") for row in card.get("units", []) if isinstance(row, Mapping)}
        if (
            isinstance(rejected_units, (str, bytes))
            or payload.get("rejected_units") != list(rejected_units)
            or any(not isinstance(unit_id, str) or unit_id not in frozen_unit_ids for unit_id in rejected_units)
            or len(set(rejected_units)) != len(list(rejected_units))
        ):
            raise _transfer_invalid()
    withheld = {
        fact["fact_key"]: fact.get("status")
        for fact in frozen.get("profile_facts", [])
        if isinstance(fact, Mapping) and isinstance(fact.get("fact_key"), str) and fact.get("status") != "confirmed"
    }
    if stage == "extract":
        batch = payload.get("batch")
        batches = card.get("batches") if isinstance(card.get("batches"), list) else []
        if (
            payload.get("schema_version") != card.get("schema_version")
            or not isinstance(batch, Mapping)
            or batch not in batches
        ):
            raise _transfer_invalid()
        units = {row.get("unit_id"): row for row in card.get("units", []) if isinstance(row, Mapping)}
        expected_units = [units.get(unit_id) for unit_id in batch.get("unit_ids", [])]
        if any(row is None or row.get("kind") not in {"card", "segment"} for row in expected_units):
            raise _transfer_invalid()
        sent_units = payload.get("units")
        if stage_schema not in {_STAGE_SCHEMA_V1, _STAGE_SCHEMA_V2}:
            raise _transfer_invalid()
        if stage_schema == _STAGE_SCHEMA_V2:
            if ontology is None or sent_units != expected_units:
                raise _transfer_invalid()
            for frozen_unit in expected_units:
                card_expected_concepts(_unit_texts(frozen_unit), ontology)
        elif _selector_version(card) == _EXPECTED_CONCEPTS_SELECTOR:
            # 결정 B30: frozen unit + exactly the deterministic expected concepts.
            if ontology is None or not isinstance(sent_units, list) or len(sent_units) != len(expected_units):
                raise _transfer_invalid()
            for sent, frozen_unit in zip(sent_units, expected_units):
                if (
                    not isinstance(sent, Mapping)
                    or set(sent) != set(frozen_unit) | CARD_EXTRACT_V3_UNIT_EXTRA_KEYS
                    or {key: sent[key] for key in frozen_unit} != frozen_unit
                    or sent["expected_concepts"] != card_expected_concepts(_unit_texts(frozen_unit), ontology)
                ):
                    raise _transfer_invalid()
        elif sent_units != expected_units:
            raise _transfer_invalid()
        sent_ontology = payload.get("ontology")
        if not isinstance(sent_ontology, list) or any(
            not isinstance(row, Mapping) or set(row) != {"id", "label", "aliases"} for row in sent_ontology
        ):
            raise _transfer_invalid()
        if ontology is not None and sent_ontology != _ontology_projection(ontology):
            raise _transfer_invalid()
    else:
        if stage == "role":
            referenced = card_referenced_fact_keys(payload.get("compare"))
            if fact_keys is not None and set(fact_keys) != set(referenced):
                raise _transfer_invalid()
        else:
            if fact_keys is None:
                raise _transfer_invalid()
            referenced = list(fact_keys)
        company = card_company_transfer(frozen, referenced)
        if (
            payload.get("profile_facts") != company["profile_facts"]
            or payload.get("profile_evidence") != company["profile_evidence"]
            # Same rule as ``company_part_is_prompt_safe`` on what is actually sent.
            or sanitize_for_prompt(company) != company
        ):
            raise _transfer_invalid()
    _walk_transfer(dict(payload), withheld)
    text = _canonical_text(dict(payload))
    forbidden = [frozen.get(key) for key in _FROZEN_FORBIDDEN_VALUE_KEYS]
    forbidden.extend(operational_values)
    for fact in frozen.get("profile_facts", []):
        if isinstance(fact, Mapping) and fact.get("fact_key") in withheld:
            forbidden.extend(_withheld_texts(fact.get("value")))
            forbidden.extend(_withheld_texts(fact.get("quote")))
    for value in forbidden:
        if value is None:
            continue
        needle = str(value)
        if needle and needle in text:
            raise _transfer_invalid()


def _ontology_projection(ontology: Any) -> list[dict[str, Any]]:
    """Extract ontology rows ``{id, label, aliases}`` (ontology text only, 결정 B10)."""

    return [{"id": row.id, "label": row.label, "aliases": list(row.aliases)} for row in _concept_rows(ontology)]


def card_extract_transfer(
    frozen: Mapping[str, Any],
    batch_index: int,
    ontology: Any,
    *,
    operational_values: Sequence[Any] = (),
    stage_schema: str = _STAGE_SCHEMA_V1,
) -> dict[str, Any]:
    """The checked extract payload of one frozen batch (no company material).

    A ``card-sections-v3`` input adds ``expected_concepts`` to every unit (결정 B30)
    unless the policy's ``stage_schema`` is ``bidops.requirement-extract.v2``
    (policy v4, 결정 B33): then code fills the concepts after the call and the
    units are sent unchanged.
    """

    frozen = _frozen_card_input(frozen)
    card = frozen["card_analysis"]
    batches = card.get("batches")
    if type(batch_index) is not int or not isinstance(batches, list) or not 0 <= batch_index < len(batches):
        raise _transfer_invalid()
    batch = batches[batch_index]
    units = {row.get("unit_id"): row for row in card.get("units", []) if isinstance(row, Mapping)}
    sent_units = [deepcopy(units.get(unit_id)) for unit_id in batch.get("unit_ids", [])]
    if stage_schema == _STAGE_SCHEMA_V1 and _selector_version(card) == _EXPECTED_CONCEPTS_SELECTOR:
        for unit in sent_units:
            if not isinstance(unit, dict):
                raise _transfer_invalid()
            unit["expected_concepts"] = card_expected_concepts(_unit_texts(unit), ontology)
    payload = {
        "schema_version": card.get("schema_version"),
        "batch": deepcopy(batch),
        "units": sent_units,
        "ontology": _ontology_projection(ontology),
    }
    check_card_transfer_payload("extract", payload, frozen, operational_values=operational_values,
                                ontology=ontology, stage_schema=stage_schema)
    return payload


def card_role_transfer(
    frozen: Mapping[str, Any],
    *,
    role: str,
    extract: Mapping[str, Any],
    compare: Mapping[str, Any],
    operational_values: Sequence[Any] = (),
) -> dict[str, Any]:
    """The checked ``card-role-v1`` payload: frozen role inputs + the facts its compare references (B11)."""

    payload = {"role": role, "extract": deepcopy(dict(extract)), "compare": deepcopy(dict(compare)),
               **card_company_transfer(frozen, card_referenced_fact_keys(compare))}
    check_card_transfer_payload("role", payload, frozen, operational_values=operational_values)
    return payload


def card_synthesis_transfer(
    frozen: Mapping[str, Any],
    *,
    roles: Sequence[Mapping[str, Any]],
    fact_keys: Sequence[str],
    operational_values: Sequence[Any] = (),
    rejected_units: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The checked ``card-synthesis-v1`` payload: three role results + the union of their referenced facts (B11).

    A ``card-sections-v2`` input adds ``missing_sections`` (결정 B24).  Policy v7
    (결정 B51) adds ``rejected_units`` = the isolated unit ids (possibly empty);
    ``None`` keeps the v1-v6 payload without the key.
    """

    payload = {"roles": [deepcopy(dict(row)) for row in roles], **card_company_transfer(frozen, fact_keys)}
    missing_sections = card_synthesis_missing_sections(frozen)
    if missing_sections is not None:
        payload["missing_sections"] = missing_sections
    if rejected_units is not None:
        payload["rejected_units"] = list(rejected_units)
    check_card_transfer_payload("synthesis", payload, frozen, fact_keys=fact_keys,
                                operational_values=operational_values, rejected_units=rejected_units)
    return payload


__all__ = [
    "CARD_COMPARE_FACT_PATHS",
    "CARD_CONFIRMED_FACT_KEYS",
    "CARD_EXPECTED_CONCEPT_KEYS",
    "CARD_EXTRACT_V3_UNIT_EXTRA_KEYS",
    "CARD_FORBIDDEN_TRANSFER_KEYS",
    "CARD_TRANSFER_EVIDENCE_KEYS",
    "CARD_SYNTHESIS_V2_EXTRA_KEYS",
    "CARD_SYNTHESIS_V7_EXTRA_KEYS",
    "CARD_TRANSFER_STAGE_KEYS",
    "card_synthesis_missing_sections",
    "CARD_WITHHELD_FACT_KEYS",
    "COMPANY_ANALYSIS_INPUT_KEYS",
    "COMPANY_ANALYSIS_INPUT_SCHEMA",
    "COMPANY_ANALYSIS_INPUT_V2_KEYS",
    "COMPANY_ANALYSIS_INPUT_V2_SCHEMA",
    "CardFactReading",
    "CompanyAnalysisError",
    "CompanyKnowledgeContext",
    "FROZEN_PROVENANCE_KEYS",
    "build_company_analysis_input",
    "build_company_analysis_input_v2",
    "card_company_transfer",
    "card_expected_concepts",
    "card_fact_value",
    "card_referenced_fact_keys",
    "card_extract_transfer",
    "card_role_transfer",
    "card_synthesis_transfer",
    "check_card_transfer_payload",
    "document_provenance",
    "frozen_provenance",
    "notice_document_sets",
    "ready_bundle_document_sets",
    "resolve_company_knowledge_context",
]
