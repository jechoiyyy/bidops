"""Pure contracts for versioned company ontologies and synthetic knowledge sources.

This module deliberately has no database, object-store, CLI, or domain-module
dependencies.  Registration code can therefore validate and freeze an input
before it starts any write transaction.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
import hashlib
import json
import re
from typing import Any, Final, Literal, Mapping, TypeAlias
import unicodedata


ONTOLOGY_SCHEMA: Final[str] = "bidops.company-ontology.v1"
COMPANY_SOURCE_SCHEMA: Final[str] = "bidops.company-knowledge-source.v1"
GRAPH_SNAPSHOT_SCHEMA: Final[str] = "bidops.company-knowledge-snapshot.v1"

NodeType: TypeAlias = Literal[
    "company",
    "capability",
    "technology",
    "domain",
    "staff_group",
    "project",
    "qualification",
    "notice",
    "requirement",
    "evidence",
]
RelationType: TypeAlias = Literal[
    "has_capability",
    "uses_technology",
    "operates_in",
    "has_staff",
    "performed",
    "supports_capability",
    "holds_qualification",
    "supported_by",
    "has_requirement",
    "requires_capability",
    "requires_qualification",
]
ConceptKind: TypeAlias = Literal["capability", "technology", "domain", "qualification"]
FactStatus: TypeAlias = Literal["confirmed", "proposed", "inferred", "unknown"]
FactOrigin: TypeAlias = Literal[
    "fictional_scenario",
    "public_document",
    "model_inference",
    "company_brochure",
    "homepage",
    "user_interview",
    "agent_proposal",
]


NODE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "company",
        "capability",
        "technology",
        "domain",
        "staff_group",
        "project",
        "qualification",
        "notice",
        "requirement",
        "evidence",
    }
)
COMPANY_SOURCE_NODE_TYPES: Final[frozenset[str]] = NODE_TYPES - {"notice", "requirement"}
CONCEPT_KINDS: Final[frozenset[str]] = frozenset(
    {"capability", "technology", "domain", "qualification"}
)
#: RL-00: ``proposed`` = agent-proposed value not yet confirmed by a person.
#: It follows the ``confirmed`` source-ref rule (exactly one) but is never a
#: confirmation; ``inferred`` stays reserved for model inference.
FACT_STATUSES: Final[frozenset[str]] = frozenset(
    {"confirmed", "proposed", "inferred", "unknown"}
)
#: Origins a registered *real* company file may use (ADR-0073 decision 1).
REAL_COMPANY_ORIGINS: Final[frozenset[str]] = frozenset(
    {"company_brochure", "homepage", "user_interview", "agent_proposal"}
)
#: Origins a registered *fictional* company file may use (DEMO contract §3).
FICTIONAL_COMPANY_ORIGINS: Final[frozenset[str]] = frozenset({"fictional_scenario"})
#: Analysis-overlay origins; never accepted in a registration file.
OVERLAY_ORIGINS: Final[frozenset[str]] = frozenset({"public_document", "model_inference"})
ORIGINS: Final[frozenset[str]] = (
    FICTIONAL_COMPANY_ORIGINS | OVERLAY_ORIGINS | REAL_COMPANY_ORIGINS
)
#: Profile v2 top-level ``origin`` by company kind (RL-00 "저장 projection").
PROFILE_ORIGIN_REAL: Final[str] = "real_company"
PROFILE_ORIGIN_FICTIONAL: Final[str] = "fictional_scenario"
#: RL-00 status x origin rules. ``proposed`` only comes from an agent proposal;
#: interview answers are confirmed or unknown; brochure and homepage rows are
#: confirmed facts. Origins absent from this map add no status restriction.
_ORIGIN_STATUSES: Final[Mapping[str, frozenset[str]]] = {
    "user_interview": frozenset({"confirmed", "unknown"}),
    "company_brochure": frozenset({"confirmed"}),
    "homepage": frozenset({"confirmed"}),
}
DOMAIN_EXCLUSION_KINDS: Final[frozenset[str]] = frozenset(
    {"hardware", "staffing_only", "design_only", "election", "region", "amount_floor"}
)
STABLE_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
COMPANY_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
MAX_COMPANY_NAME_LENGTH: Final[int] = 128
# KnowledgeOntologyVersion.version is String(128); a longer version is a
# validation problem (ontology_invalid), never a storage failure.
MAX_ONTOLOGY_VERSION_LENGTH: Final[int] = 128
SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_HANGUL_RE: Final[re.Pattern[str]] = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_INVALID_POINTER_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(r"~(?![01])")


# Sets are part of the public contract.  Input ordering is not significant,
# but every relation must occur exactly once with these endpoints.
RELATION_ENDPOINTS: Final[Mapping[str, tuple[frozenset[str], frozenset[str]]]] = {
    "has_capability": (frozenset({"company"}), frozenset({"capability"})),
    "uses_technology": (
        frozenset({"project", "capability"}),
        frozenset({"technology"}),
    ),
    "operates_in": (frozenset({"company", "project"}), frozenset({"domain"})),
    "has_staff": (frozenset({"company"}), frozenset({"staff_group"})),
    "performed": (frozenset({"company"}), frozenset({"project"})),
    "supports_capability": (
        frozenset({"project", "staff_group"}),
        frozenset({"capability"}),
    ),
    "holds_qualification": (
        frozenset({"company"}),
        frozenset({"qualification"}),
    ),
    "supported_by": (
        frozenset(
            {
                "company",
                "capability",
                "technology",
                "domain",
                "staff_group",
                "project",
                "qualification",
                "requirement",
            }
        ),
        frozenset({"evidence"}),
    ),
    "has_requirement": (frozenset({"notice"}), frozenset({"requirement"})),
    "requires_capability": (
        frozenset({"requirement"}),
        frozenset({"capability"}),
    ),
    "requires_qualification": (
        frozenset({"requirement"}),
        frozenset({"qualification"}),
    ),
}


class CompanyOntologyError(ValueError):
    """Base class whose message starts with a stable, non-sensitive code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OntologyValidationError(CompanyOntologyError):
    """The ontology JSON does not satisfy the frozen v1 contract."""


class CompanyKnowledgeValidationError(CompanyOntologyError):
    """The company knowledge source does not satisfy the frozen v1 contract."""


class CompanyIdentityValidationError(ValueError):
    """A company identity cannot be passed to lifecycle registration unchanged."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OntologyConcept:
    id: str
    label: str
    aliases: tuple[str, ...]
    kind: ConceptKind

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "aliases": list(self.aliases),
            "kind": self.kind,
        }


@dataclass(frozen=True)
class OntologyRelation:
    type: RelationType
    from_types: tuple[NodeType, ...]
    to_types: tuple[NodeType, ...]
    evidence_required: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "from_types": list(self.from_types),
            "to_types": list(self.to_types),
            "evidence_required": self.evidence_required,
        }


@dataclass(frozen=True)
class ValidatedOntology:
    version: str
    concepts: tuple[OntologyConcept, ...]
    relations: tuple[OntologyRelation, ...]
    sha256: str
    canonical_bytes: bytes = field(repr=False)

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": ONTOLOGY_SCHEMA,
            "version": self.version,
            "concepts": [concept.as_dict() for concept in self.concepts],
            "relations": [relation.as_dict() for relation in self.relations],
        }

    @property
    def concepts_by_id(self) -> dict[str, OntologyConcept]:
        return {concept.id: concept for concept in self.concepts}


@dataclass(frozen=True)
class CompanyIdentity:
    slug: str
    name: str
    is_fictional: bool


def normalize_company_identity(
    *, slug: Any, name: Any, is_fictional: Any
) -> CompanyIdentity:
    """Apply the exact pure identity rules used by ``register_company``.

    Keeping normalization in core lets dry-run validation and lifecycle
    registration consume the same result without importing either domain into
    the other.  The lifecycle service historically trims the name, so this
    helper preserves that behavior.

    RL-00: both real (``False``) and fictional (``True``) companies are valid
    identities; anything that is not exactly a bool is rejected.  Whether a
    fictional registration is *allowed* (demo flag) and whether another real
    company already exists are decided by the services that can read settings
    and the database, not here.
    """

    if not isinstance(slug, str) or COMPANY_SLUG_RE.fullmatch(slug) is None:
        raise CompanyIdentityValidationError("company_slug_invalid")
    clean_name = name.strip() if isinstance(name, str) else ""
    if not clean_name or len(clean_name) > MAX_COMPANY_NAME_LENGTH:
        raise CompanyIdentityValidationError("company_name_invalid")
    if type(is_fictional) is not bool:
        raise CompanyIdentityValidationError("company_is_fictional_invalid")
    return CompanyIdentity(slug=slug, name=clean_name, is_fictional=is_fictional)


def registration_origin_allowed(origin: Any, *, is_fictional: bool) -> bool:
    """Whether a registration file of this company kind may use ``origin``.

    Real files use the four confirmation sources; fictional files keep the
    single ``fictional_scenario`` origin.  Overlay origins are never allowed.
    """

    if not isinstance(origin, str):
        return False
    allowed = FICTIONAL_COMPANY_ORIGINS if is_fictional else REAL_COMPANY_ORIGINS
    return origin in allowed


def status_origin_allowed(status: Any, origin: Any) -> bool:
    """RL-00 status x origin combination rule shared by write and read checks."""

    if not isinstance(status, str) or status not in FACT_STATUSES:
        return False
    if not isinstance(origin, str) or origin not in ORIGINS:
        return False
    if status == "proposed" and origin != "agent_proposal":
        return False
    allowed = _ORIGIN_STATUSES.get(origin)
    return allowed is None or status in allowed


def profile_origin_for(*, is_fictional: bool) -> str:
    """Top-level profile v2 ``origin`` for a company kind."""

    return PROFILE_ORIGIN_FICTIONAL if is_fictional else PROFILE_ORIGIN_REAL


@dataclass(frozen=True, order=True)
class SourceRef:
    json_pointer: str
    quote: str
    source_id: str = field(default="self", compare=False)

    def as_dict(self, *, source_sha256: str | None = None) -> dict[str, Any]:
        value: dict[str, Any] = {
            "source_id": self.source_id,
            "locator": {"json_pointer": self.json_pointer},
            "quote": self.quote,
        }
        if source_sha256 is not None:
            value["source_sha256"] = source_sha256
        return value


@dataclass(frozen=True)
class CompanyKnowledgeNode:
    id: str
    type: NodeType
    label: str
    concept_id: str | None
    status: FactStatus
    origin: FactOrigin
    value: Any
    source_refs: tuple[SourceRef, ...]

    def as_dict(self, *, source_sha256: str | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "concept_id": self.concept_id,
            "status": self.status,
            "origin": self.origin,
            "value": deepcopy(self.value),
            "source_refs": [
                ref.as_dict(source_sha256=source_sha256) for ref in self.source_refs
            ],
        }


@dataclass(frozen=True)
class CompanyKnowledgeEdge:
    id: str
    type: RelationType
    from_id: str
    to_id: str
    status: FactStatus
    origin: FactOrigin
    source_refs: tuple[SourceRef, ...]

    def as_dict(self, *, source_sha256: str | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "status": self.status,
            "origin": self.origin,
            "source_refs": [
                ref.as_dict(source_sha256=source_sha256) for ref in self.source_refs
            ],
        }


@dataclass(frozen=True)
class ValidatedCompanyKnowledge:
    company: CompanyIdentity
    scenario_version: str
    ontology_version: str
    ontology_sha256: str
    nodes: tuple[CompanyKnowledgeNode, ...]
    edges: tuple[CompanyKnowledgeEdge, ...]
    source_sha256: str
    raw_bytes: bytes = field(repr=False)
    _payload: dict[str, Any] = field(repr=False)

    @property
    def payload(self) -> dict[str, Any]:
        return deepcopy(self._payload)


@dataclass(frozen=True)
class GraphSnapshot:
    sha256: str
    canonical_bytes: bytes = field(repr=False)
    _payload: dict[str, Any] = field(repr=False)

    @property
    def payload(self) -> dict[str, Any]:
        return deepcopy(self._payload)


class _DuplicateJSONKey(ValueError):
    pass


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey
        result[key] = value
    return result


def _parse_json_object(raw: bytes, error_type: type[CompanyOntologyError]) -> dict[str, Any]:
    if not isinstance(raw, bytes):
        raise error_type("json_bytes_required")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise error_type("utf8_invalid") from None
    # A UTF-8 BOM is an encoding signature, not part of the accepted JSON text.
    if text.startswith("\ufeff"):
        raise error_type("utf8_bom_invalid")
    try:
        value = json.loads(text, object_pairs_hook=_object_pairs)
    except _DuplicateJSONKey:
        raise error_type("duplicate_json_key") from None
    except (json.JSONDecodeError, TypeError, ValueError):
        raise error_type("json_invalid") from None
    if not isinstance(value, dict):
        raise error_type("json_object_required")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return the canonical UTF-8 JSON representation used by all digests."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise CompanyOntologyError("canonical_json_invalid") from None


def sha256_bytes(raw: bytes) -> str:
    if not isinstance(raw, bytes):
        raise CompanyOntologyError("hash_bytes_required")
    return hashlib.sha256(raw).hexdigest()


def normalize_term(value: str) -> str:
    """Normalize a label/alias for deterministic ambiguity checks and matching."""

    if not isinstance(value, str):
        raise OntologyValidationError("term_invalid")
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _strict_object(
    value: Any,
    keys: set[str],
    *,
    error_type: type[CompanyOntologyError],
    code: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise error_type(code)
    return value


def _nonempty_string(
    value: Any,
    *,
    error_type: type[CompanyOntologyError],
    code: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(code)
    return value


def _stable_key(
    value: Any,
    *,
    error_type: type[CompanyOntologyError],
    code: str,
) -> str:
    if not isinstance(value, str) or STABLE_KEY_RE.fullmatch(value) is None:
        raise error_type(code)
    return value


def _string_list(
    value: Any,
    *,
    error_type: type[CompanyOntologyError],
    code: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise error_type(code)
    result: list[str] = []
    for item in value:
        result.append(_nonempty_string(item, error_type=error_type, code=code))
    return tuple(result)


def parse_ontology(raw: bytes) -> ValidatedOntology:
    """Parse, strictly validate, and hash one v1 ontology JSON document."""

    value = _parse_json_object(raw, OntologyValidationError)
    _strict_object(
        value,
        {"schema_version", "version", "concepts", "relations"},
        error_type=OntologyValidationError,
        code="ontology_keys_invalid",
    )
    if value["schema_version"] != ONTOLOGY_SCHEMA:
        raise OntologyValidationError("ontology_schema_invalid")
    version = _nonempty_string(
        value["version"], error_type=OntologyValidationError, code="ontology_version_invalid"
    )
    if len(version) > MAX_ONTOLOGY_VERSION_LENGTH:
        raise OntologyValidationError("ontology_version_invalid")

    raw_concepts = value["concepts"]
    if not isinstance(raw_concepts, list) or not raw_concepts:
        raise OntologyValidationError("concepts_invalid")
    concepts: list[OntologyConcept] = []
    concept_ids: set[str] = set()
    normalized_terms: dict[str, str] = {}
    for raw_concept in raw_concepts:
        concept = _strict_object(
            raw_concept,
            {"id", "label", "aliases", "kind"},
            error_type=OntologyValidationError,
            code="concept_keys_invalid",
        )
        concept_id = _stable_key(
            concept["id"], error_type=OntologyValidationError, code="concept_id_invalid"
        )
        if concept_id in concept_ids:
            raise OntologyValidationError("duplicate_concept_id")
        concept_ids.add(concept_id)
        label = _nonempty_string(
            concept["label"], error_type=OntologyValidationError, code="concept_label_invalid"
        )
        aliases = _string_list(
            concept["aliases"], error_type=OntologyValidationError, code="concept_aliases_invalid"
        )
        kind = concept["kind"]
        if not isinstance(kind, str) or kind not in CONCEPT_KINDS:
            raise OntologyValidationError("concept_kind_invalid")

        for position, term in enumerate((label, *aliases)):
            normalized = normalize_term(term)
            if not normalized:
                raise OntologyValidationError("term_invalid")
            if position > 0 and _HANGUL_RE.search(normalized) and len(normalized) < 2:
                raise OntologyValidationError("alias_too_short")
            if normalized in normalized_terms:
                raise OntologyValidationError("ambiguous_term")
            normalized_terms[normalized] = concept_id
        concepts.append(
            OntologyConcept(
                id=concept_id,
                label=label,
                aliases=aliases,
                kind=kind,
            )
        )

    raw_relations = value["relations"]
    if not isinstance(raw_relations, list):
        raise OntologyValidationError("relations_invalid")
    relations: list[OntologyRelation] = []
    relation_types: set[str] = set()
    for raw_relation in raw_relations:
        relation = _strict_object(
            raw_relation,
            {"type", "from_types", "to_types", "evidence_required"},
            error_type=OntologyValidationError,
            code="relation_keys_invalid",
        )
        relation_type = relation["type"]
        if (
            not isinstance(relation_type, str)
            or relation_type not in RELATION_ENDPOINTS
            or relation_type in relation_types
        ):
            raise OntologyValidationError("relation_declaration_invalid")
        relation_types.add(relation_type)
        from_types = _string_list(
            relation["from_types"],
            error_type=OntologyValidationError,
            code="relation_declaration_invalid",
        )
        to_types = _string_list(
            relation["to_types"],
            error_type=OntologyValidationError,
            code="relation_declaration_invalid",
        )
        expected_from, expected_to = RELATION_ENDPOINTS[relation_type]
        if (
            len(from_types) != len(set(from_types))
            or len(to_types) != len(set(to_types))
            or frozenset(from_types) != expected_from
            or frozenset(to_types) != expected_to
            or relation["evidence_required"] is not True
        ):
            raise OntologyValidationError("relation_declaration_invalid")
        relations.append(
            OntologyRelation(
                type=relation_type,
                from_types=from_types,
                to_types=to_types,
                evidence_required=True,
            )
        )
    if relation_types != set(RELATION_ENDPOINTS):
        raise OntologyValidationError("relation_declaration_invalid")

    payload = {
        "schema_version": ONTOLOGY_SCHEMA,
        "version": version,
        "concepts": [concept.as_dict() for concept in concepts],
        "relations": [relation.as_dict() for relation in relations],
    }
    canonical = canonical_json_bytes(payload)
    return ValidatedOntology(
        version=version,
        concepts=tuple(concepts),
        relations=tuple(relations),
        sha256=sha256_bytes(canonical),
        canonical_bytes=canonical,
    )


def _parse_source_ref(value: Any) -> SourceRef:
    source_ref = _strict_object(
        value,
        {"source_id", "locator", "quote"},
        error_type=CompanyKnowledgeValidationError,
        code="source_ref_keys_invalid",
    )
    if source_ref["source_id"] != "self":
        raise CompanyKnowledgeValidationError("source_id_invalid")
    locator = _strict_object(
        source_ref["locator"],
        {"json_pointer"},
        error_type=CompanyKnowledgeValidationError,
        code="source_locator_invalid",
    )
    pointer = locator["json_pointer"]
    if not isinstance(pointer, str):
        raise CompanyKnowledgeValidationError("source_pointer_invalid")
    quote = source_ref["quote"]
    if not isinstance(quote, str):
        raise CompanyKnowledgeValidationError("source_quote_invalid")
    return SourceRef(json_pointer=pointer, quote=quote)


def _parse_source_refs(value: Any) -> tuple[SourceRef, ...]:
    if not isinstance(value, list):
        raise CompanyKnowledgeValidationError("source_refs_invalid")
    refs = tuple(_parse_source_ref(item) for item in value)
    if len(refs) != len(set(refs)):
        raise CompanyKnowledgeValidationError("duplicate_source_ref")
    return refs


def _nullable_nonnegative_int(value: Any, *, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise CompanyKnowledgeValidationError("integer_invalid")
    if value < 0:
        raise CompanyKnowledgeValidationError("negative_number")
    return value


def _nullable_date(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CompanyKnowledgeValidationError("date_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise CompanyKnowledgeValidationError("date_invalid") from None
    if parsed.isoformat() != value:
        raise CompanyKnowledgeValidationError("date_invalid")
    return value


def _nullable_nonempty_string(value: Any) -> str | None:
    if value is None:
        return None
    return _nonempty_string(
        value, error_type=CompanyKnowledgeValidationError, code="node_value_invalid"
    )


def _key_set(value: Any, *allowed: frozenset[str]) -> frozenset[str]:
    """Return the exact key set of a strict object among the allowed shapes.

    RL-00 extensions are additive: the DEMO shape stays valid as is, and the
    extended shape is a second strict shape ("?" is nullable, never omittable).
    """

    if not isinstance(value, dict):
        raise CompanyKnowledgeValidationError("node_value_invalid")
    keys = frozenset(value)
    if keys not in allowed:
        raise CompanyKnowledgeValidationError("node_value_invalid")
    return keys


_DOMAIN_KEYS: Final[frozenset[str]] = frozenset({"tier", "keywords", "excluded", "kind"})
_QUALIFICATION_KEYS: Final[frozenset[str]] = frozenset(
    {"held", "detail", "valid_until", "issued_on", "file_name"}
)
_CAPABILITY_KEYS: Final[frozenset[str]] = frozenset({"scope", "description"})
_CAPABILITY_RL_KEYS: Final[frozenset[str]] = _CAPABILITY_KEYS | {"params"}
_STAFF_KEYS: Final[frozenset[str]] = frozenset({"role", "total", "available", "as_of"})
_STAFF_RL_KEYS: Final[frozenset[str]] = _STAFF_KEYS | {"region", "grade"}
_PROJECT_KEYS: Final[frozenset[str]] = frozenset(
    {"role", "scope", "amount_krw", "started_on", "ended_on"}
)
_PROJECT_RL_KEYS: Final[frozenset[str]] = _PROJECT_KEYS | {"agency", "year"}


def _domain_value(value: Any) -> Any:
    if value is None or isinstance(value, str):
        if isinstance(value, str) and not value.strip():
            raise CompanyKnowledgeValidationError("node_value_invalid")
        return value
    _key_set(value, _DOMAIN_KEYS)
    tier = value["tier"]
    if tier is not None and (type(tier) is not int or tier not in {1, 2, 3}):
        raise CompanyKnowledgeValidationError("node_value_invalid")
    _string_list(
        value["keywords"], error_type=CompanyKnowledgeValidationError, code="node_value_invalid"
    )
    excluded = value["excluded"]
    if type(excluded) is not bool:
        raise CompanyKnowledgeValidationError("node_value_invalid")
    kind = value["kind"]
    if kind is not None and (not isinstance(kind, str) or kind not in DOMAIN_EXCLUSION_KINDS):
        raise CompanyKnowledgeValidationError("node_value_invalid")
    if excluded and kind is None:
        raise CompanyKnowledgeValidationError("node_value_invalid")
    return deepcopy(value)


def _qualification_value(value: Any) -> Any:
    if value is None or isinstance(value, str):
        if isinstance(value, str) and not value.strip():
            raise CompanyKnowledgeValidationError("node_value_invalid")
        return value
    _key_set(value, _QUALIFICATION_KEYS)
    if type(value["held"]) is not bool:
        raise CompanyKnowledgeValidationError("node_value_invalid")
    _nullable_nonempty_string(value["detail"])
    _nullable_date(value["valid_until"])
    _nullable_date(value["issued_on"])
    file_name = _nullable_nonempty_string(value["file_name"])
    # Only the file name of a certificate copy is recorded; the copy itself and
    # any storage path stay outside the graph (ui-spec §4.6).
    if file_name is not None and ("/" in file_name or "\\" in file_name):
        raise CompanyKnowledgeValidationError("node_value_invalid")
    return deepcopy(value)


def _capability_params(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise CompanyKnowledgeValidationError("node_value_invalid")
    for key, item in value.items():
        _nonempty_string(key, error_type=CompanyKnowledgeValidationError, code="node_value_invalid")
        if isinstance(item, bool):
            continue
        if type(item) is int:
            # Amounts, counts, months and ratios: never negative (contract §3).
            _nullable_nonnegative_int(item, name=key)
            continue
        if isinstance(item, str) and item.strip():
            continue
        raise CompanyKnowledgeValidationError("node_value_invalid")


def _node_value(node_type: str, value: Any) -> Any:
    if node_type in {"company", "technology"}:
        if value is not None and not isinstance(value, str):
            raise CompanyKnowledgeValidationError("node_value_invalid")
        if isinstance(value, str) and not value.strip():
            raise CompanyKnowledgeValidationError("node_value_invalid")
        return value
    if node_type == "domain":
        return _domain_value(value)
    if node_type == "qualification":
        return _qualification_value(value)
    if node_type == "capability":
        if value is None:
            return None
        keys = _key_set(value, _CAPABILITY_KEYS, _CAPABILITY_RL_KEYS)
        item = value
        if not isinstance(item["scope"], str) or item["scope"] not in {"core", "non_core"}:
            raise CompanyKnowledgeValidationError("node_value_invalid")
        _nonempty_string(
            item["description"],
            error_type=CompanyKnowledgeValidationError,
            code="node_value_invalid",
        )
        if "params" in keys:
            _capability_params(item["params"])
        return deepcopy(item)
    if node_type == "staff_group":
        # "?" means nullable, not omittable: every declared key is required.
        keys = _key_set(value, _STAFF_KEYS, _STAFF_RL_KEYS)
        _nonempty_string(
            value["role"],
            error_type=CompanyKnowledgeValidationError,
            code="node_value_invalid",
        )
        total = _nullable_nonnegative_int(value.get("total"), name="total")
        available = _nullable_nonnegative_int(value.get("available"), name="available")
        if total is not None and available is not None and available > total:
            raise CompanyKnowledgeValidationError("available_exceeds_total")
        _nullable_date(value.get("as_of"))
        if "region" in keys:
            _nullable_nonempty_string(value["region"])
            _nullable_nonempty_string(value["grade"])
        return deepcopy(value)
    if node_type == "project":
        keys = _key_set(value, _PROJECT_KEYS, _PROJECT_RL_KEYS)
        if keys == _PROJECT_KEYS:
            # The DEMO shape is unchanged: role and scope stay required strings.
            _nonempty_string(
                value["role"],
                error_type=CompanyKnowledgeValidationError,
                code="node_value_invalid",
            )
            _nonempty_string(
                value["scope"],
                error_type=CompanyKnowledgeValidationError,
                code="node_value_invalid",
            )
        else:
            # RL-00 homepage rows: only name/agency/year are known; nothing
            # else is invented, so role and scope may be null.
            _nullable_nonempty_string(value["role"])
            _nullable_nonempty_string(value["scope"])
            _nullable_nonempty_string(value["agency"])
            _nullable_nonnegative_int(value["year"], name="year")
        _nullable_nonnegative_int(value.get("amount_krw"), name="amount_krw")
        started = _nullable_date(value.get("started_on"))
        ended = _nullable_date(value.get("ended_on"))
        if started is not None and ended is not None and ended < started:
            raise CompanyKnowledgeValidationError("date_order_invalid")
        return deepcopy(value)
    if node_type == "evidence":
        if value is None:
            return None
        item = _strict_object(
            value,
            {"fact_key"},
            error_type=CompanyKnowledgeValidationError,
            code="node_value_invalid",
        )
        _stable_key(
            item["fact_key"],
            error_type=CompanyKnowledgeValidationError,
            code="evidence_fact_key_invalid",
        )
        return deepcopy(item)
    # Overlay-only types: registration sources reject these node types before
    # value parsing; the exact value shapes are still fixed here (contract §3).
    if node_type == "notice":
        item = _strict_object(
            value,
            {"notice_id"},
            error_type=CompanyKnowledgeValidationError,
            code="node_value_invalid",
        )
        if type(item["notice_id"]) is not int:
            raise CompanyKnowledgeValidationError("node_value_invalid")
        return deepcopy(item)
    if node_type == "requirement":
        item = _strict_object(
            value,
            {"text", "mandatory"},
            error_type=CompanyKnowledgeValidationError,
            code="node_value_invalid",
        )
        _nonempty_string(
            item["text"],
            error_type=CompanyKnowledgeValidationError,
            code="node_value_invalid",
        )
        if item["mandatory"] is not None and type(item["mandatory"]) is not bool:
            raise CompanyKnowledgeValidationError("node_value_invalid")
        return deepcopy(item)
    raise CompanyKnowledgeValidationError("node_type_invalid")


def _decode_pointer_component(component: str) -> str:
    if _INVALID_POINTER_ESCAPE_RE.search(component):
        raise CompanyKnowledgeValidationError("source_pointer_invalid")
    return component.replace("~1", "/").replace("~0", "~")


def _resolve_pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise CompanyKnowledgeValidationError("source_pointer_invalid")
    current = document
    for raw_component in pointer[1:].split("/"):
        component = _decode_pointer_component(raw_component)
        if isinstance(current, dict):
            if component not in current:
                raise CompanyKnowledgeValidationError("source_pointer_invalid")
            current = current[component]
        elif isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", component):
                raise CompanyKnowledgeValidationError("source_pointer_invalid")
            index = int(component)
            if index >= len(current):
                raise CompanyKnowledgeValidationError("source_pointer_invalid")
            current = current[index]
        else:
            raise CompanyKnowledgeValidationError("source_pointer_invalid")
    return current


def _scalar_quote(value: Any) -> str:
    if isinstance(value, (dict, list)):
        raise CompanyKnowledgeValidationError("source_pointer_not_scalar")
    if isinstance(value, str):
        return value
    if value is None or type(value) in {bool, int}:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    raise CompanyKnowledgeValidationError("source_pointer_not_scalar")


def _validate_fact_ref(
    ref: SourceRef,
    *,
    document: Mapping[str, Any],
    node_index: int,
) -> None:
    prefix = f"/nodes/{node_index}/value"
    if ref.json_pointer != prefix and not ref.json_pointer.startswith(prefix + "/"):
        raise CompanyKnowledgeValidationError("source_pointer_invalid")
    pointed = _resolve_pointer(document, ref.json_pointer)
    if _scalar_quote(pointed) != ref.quote:
        raise CompanyKnowledgeValidationError("source_quote_mismatch")


def parse_company_knowledge_source(
    raw: bytes,
    *,
    ontology: ValidatedOntology,
) -> ValidatedCompanyKnowledge:
    """Validate raw company JSON (real or fictional) against one validated ontology."""

    if not isinstance(ontology, ValidatedOntology):
        raise CompanyKnowledgeValidationError("ontology_binding_invalid")
    value = _parse_json_object(raw, CompanyKnowledgeValidationError)
    _strict_object(
        value,
        {
            "schema_version",
            "company",
            "scenario_version",
            "ontology_version",
            "ontology_sha256",
            "nodes",
            "edges",
        },
        error_type=CompanyKnowledgeValidationError,
        code="source_keys_invalid",
    )
    if value["schema_version"] != COMPANY_SOURCE_SCHEMA:
        raise CompanyKnowledgeValidationError("source_schema_invalid")
    company_value = _strict_object(
        value["company"],
        {"slug", "name", "is_fictional"},
        error_type=CompanyKnowledgeValidationError,
        code="company_keys_invalid",
    )
    try:
        company = normalize_company_identity(
            slug=company_value["slug"],
            name=company_value["name"],
            is_fictional=company_value["is_fictional"],
        )
    except CompanyIdentityValidationError as exc:
        raise CompanyKnowledgeValidationError(exc.code) from None
    scenario_version = _nonempty_string(
        value["scenario_version"],
        error_type=CompanyKnowledgeValidationError,
        code="scenario_version_invalid",
    )
    if value["ontology_version"] != ontology.version:
        raise CompanyKnowledgeValidationError("ontology_version_mismatch")
    if (
        not isinstance(value["ontology_sha256"], str)
        or SHA256_RE.fullmatch(value["ontology_sha256"]) is None
        or value["ontology_sha256"] != ontology.sha256
    ):
        raise CompanyKnowledgeValidationError("ontology_hash_mismatch")

    raw_nodes = value["nodes"]
    if not isinstance(raw_nodes, list):
        raise CompanyKnowledgeValidationError("nodes_invalid")
    nodes: list[CompanyKnowledgeNode] = []
    node_ids: set[str] = set()
    company_count = 0
    non_evidence_count = 0
    concepts = ontology.concepts_by_id
    for index, raw_node in enumerate(raw_nodes):
        node = _strict_object(
            raw_node,
            {"id", "type", "label", "concept_id", "status", "origin", "value", "source_refs"},
            error_type=CompanyKnowledgeValidationError,
            code="node_keys_invalid",
        )
        node_id = _stable_key(
            node["id"], error_type=CompanyKnowledgeValidationError, code="node_id_invalid"
        )
        if node_id in node_ids:
            raise CompanyKnowledgeValidationError("duplicate_id")
        node_ids.add(node_id)
        node_type = node["type"]
        if not isinstance(node_type, str) or node_type not in COMPANY_SOURCE_NODE_TYPES:
            raise CompanyKnowledgeValidationError("node_type_invalid")
        if node_type == "company":
            company_count += 1
        if node_type != "evidence":
            non_evidence_count += 1
        label = _nonempty_string(
            node["label"],
            error_type=CompanyKnowledgeValidationError,
            code="node_label_invalid",
        )
        concept_id = node["concept_id"]
        if node_type in CONCEPT_KINDS:
            if not isinstance(concept_id, str) or concept_id not in concepts:
                raise CompanyKnowledgeValidationError("concept_reference_invalid")
            if concepts[concept_id].kind != node_type:
                raise CompanyKnowledgeValidationError("concept_kind_mismatch")
        elif concept_id is not None:
            raise CompanyKnowledgeValidationError("concept_reference_invalid")
        status = node["status"]
        if not isinstance(status, str) or status not in FACT_STATUSES:
            raise CompanyKnowledgeValidationError("node_status_invalid")
        origin = node["origin"]
        if not registration_origin_allowed(origin, is_fictional=company.is_fictional):
            raise CompanyKnowledgeValidationError("source_origin_invalid")
        if not status_origin_allowed(status, origin):
            raise CompanyKnowledgeValidationError("status_origin_invalid")
        refs = _parse_source_refs(node["source_refs"])
        if status == "unknown":
            if node["value"] is not None:
                raise CompanyKnowledgeValidationError("unknown_value_invalid")
            if refs:
                raise CompanyKnowledgeValidationError("unknown_source_refs_invalid")
            parsed_value = None
        else:
            parsed_value = _node_value(node_type, node["value"])
            if len(refs) != 1:
                raise CompanyKnowledgeValidationError("fact_source_ref_count_invalid")
            if node_type != "evidence":
                _validate_fact_ref(refs[0], document=value, node_index=index)
        nodes.append(
            CompanyKnowledgeNode(
                id=node_id,
                type=node_type,
                label=label,
                concept_id=concept_id,
                status=status,
                origin=origin,
                value=parsed_value,
                source_refs=refs,
            )
        )
    if company_count != 1:
        raise CompanyKnowledgeValidationError("company_node_count_invalid")
    if not 1 <= non_evidence_count <= 256:
        raise CompanyKnowledgeValidationError("profile_fact_count_invalid")

    nodes_by_id = {node.id: node for node in nodes}
    reusable_refs: set[SourceRef] = set()
    for node in nodes:
        if node.type != "evidence" and node.status != "unknown":
            reusable_refs.update(node.source_refs)
    for node in nodes:
        if node.type != "evidence" or node.status == "unknown":
            continue
        if not isinstance(node.value, dict):
            raise CompanyKnowledgeValidationError("evidence_fact_key_invalid")
        fact = nodes_by_id.get(node.value["fact_key"])
        if fact is None or fact.type == "evidence" or fact.status == "unknown":
            raise CompanyKnowledgeValidationError("evidence_fact_key_invalid")
        if node.source_refs != fact.source_refs:
            raise CompanyKnowledgeValidationError("source_ref_not_reused")

    raw_edges = value["edges"]
    if not isinstance(raw_edges, list):
        raise CompanyKnowledgeValidationError("edges_invalid")
    edges: list[CompanyKnowledgeEdge] = []
    edge_ids: set[str] = set()
    for raw_edge in raw_edges:
        edge = _strict_object(
            raw_edge,
            {"id", "type", "from_id", "to_id", "status", "origin", "source_refs"},
            error_type=CompanyKnowledgeValidationError,
            code="edge_keys_invalid",
        )
        edge_id = _stable_key(
            edge["id"], error_type=CompanyKnowledgeValidationError, code="edge_id_invalid"
        )
        if edge_id in edge_ids:
            raise CompanyKnowledgeValidationError("duplicate_id")
        edge_ids.add(edge_id)
        relation_type = edge["type"]
        if not isinstance(relation_type, str) or relation_type not in RELATION_ENDPOINTS:
            raise CompanyKnowledgeValidationError("edge_type_invalid")
        from_id = edge["from_id"]
        to_id = edge["to_id"]
        if not isinstance(from_id, str) or not isinstance(to_id, str):
            raise CompanyKnowledgeValidationError("edge_reference_invalid")
        from_node = nodes_by_id.get(from_id)
        to_node = nodes_by_id.get(to_id)
        if from_node is None or to_node is None:
            raise CompanyKnowledgeValidationError("edge_reference_invalid")
        allowed_from, allowed_to = RELATION_ENDPOINTS[relation_type]
        if from_node.type not in allowed_from or to_node.type not in allowed_to:
            raise CompanyKnowledgeValidationError("edge_endpoint_invalid")
        status = edge["status"]
        if not isinstance(status, str) or status not in FACT_STATUSES:
            raise CompanyKnowledgeValidationError("edge_status_invalid")
        origin = edge["origin"]
        if not registration_origin_allowed(origin, is_fictional=company.is_fictional):
            raise CompanyKnowledgeValidationError("source_origin_invalid")
        if not status_origin_allowed(status, origin):
            raise CompanyKnowledgeValidationError("status_origin_invalid")
        refs = _parse_source_refs(edge["source_refs"])
        if status == "unknown":
            if refs:
                raise CompanyKnowledgeValidationError("unknown_source_refs_invalid")
        else:
            if not refs:
                raise CompanyKnowledgeValidationError("edge_source_refs_required")
            if any(ref not in reusable_refs for ref in refs):
                raise CompanyKnowledgeValidationError("source_ref_not_reused")
        if relation_type == "supported_by" and status != "unknown":
            if not isinstance(to_node.value, dict) or to_node.value.get("fact_key") != from_id:
                raise CompanyKnowledgeValidationError("evidence_fact_key_invalid")
        edges.append(
            CompanyKnowledgeEdge(
                id=edge_id,
                type=relation_type,
                from_id=from_id,
                to_id=to_id,
                status=status,
                origin=origin,
                source_refs=refs,
            )
        )

    return ValidatedCompanyKnowledge(
        company=company,
        scenario_version=scenario_version,
        ontology_version=ontology.version,
        ontology_sha256=ontology.sha256,
        nodes=tuple(nodes),
        edges=tuple(edges),
        source_sha256=sha256_bytes(raw),
        raw_bytes=raw,
        _payload=deepcopy(value),
    )


def build_graph_snapshot(
    source: ValidatedCompanyKnowledge,
    *,
    ontology: ValidatedOntology,
) -> GraphSnapshot:
    """Build the UUID-free, deterministically ordered persisted graph snapshot.

    The dataclass prevents field reassignment, but JSON values inside it are
    ordinary mutable containers for ergonomic downstream consumption.  Reparse
    the immutable source bytes and compare the complete validated result before
    hashing so a mutated nested value can never be combined with the original
    source digest.
    """

    if not isinstance(source, ValidatedCompanyKnowledge) or not isinstance(
        ontology, ValidatedOntology
    ):
        raise CompanyKnowledgeValidationError("snapshot_input_invalid")
    if (
        source.ontology_version != ontology.version
        or source.ontology_sha256 != ontology.sha256
    ):
        raise CompanyKnowledgeValidationError("ontology_binding_invalid")

    if sha256_bytes(source.raw_bytes) != source.source_sha256:
        raise CompanyKnowledgeValidationError("source_integrity_invalid")
    trusted_source = parse_company_knowledge_source(source.raw_bytes, ontology=ontology)
    if trusted_source != source:
        raise CompanyKnowledgeValidationError("source_integrity_invalid")

    nodes = [
        node.as_dict(source_sha256=trusted_source.source_sha256)
        for node in sorted(trusted_source.nodes, key=lambda item: item.id)
    ]
    edges = [
        edge.as_dict(source_sha256=trusted_source.source_sha256)
        for edge in sorted(trusted_source.edges, key=lambda item: item.id)
    ]
    for item in (*nodes, *edges):
        item["source_refs"].sort(
            key=lambda ref: (ref["locator"]["json_pointer"], ref["quote"])
        )
    payload = {
        "schema_version": GRAPH_SNAPSHOT_SCHEMA,
        "company_slug": trusted_source.company.slug,
        "ontology_version": ontology.version,
        "ontology_sha256": ontology.sha256,
        "source_sha256": trusted_source.source_sha256,
        "nodes": nodes,
        "edges": edges,
    }
    canonical = canonical_json_bytes(payload)
    return GraphSnapshot(
        sha256=sha256_bytes(canonical),
        canonical_bytes=canonical,
        _payload=payload,
    )


def _relation_signature(relation: OntologyRelation) -> tuple[str, frozenset[str], frozenset[str], bool]:
    return (
        relation.type,
        frozenset(relation.from_types),
        frozenset(relation.to_types),
        relation.evidence_required,
    )


def validate_alias_only_revision(
    previous: ValidatedOntology,
    candidate: ValidatedOntology,
) -> None:
    """Require a new ontology version that only adds concept aliases.

    Reordering concepts, relations, or aliases is immaterial.  Existing aliases
    cannot be removed; the DEMO contract describes the revision as one alias
    enrichment after corpus selection.
    """

    if not isinstance(previous, ValidatedOntology) or not isinstance(candidate, ValidatedOntology):
        raise OntologyValidationError("alias_only_revision_invalid")
    if previous.version == candidate.version:
        raise OntologyValidationError("alias_only_revision_invalid")
    previous_concepts = previous.concepts_by_id
    candidate_concepts = candidate.concepts_by_id
    if set(previous_concepts) != set(candidate_concepts):
        raise OntologyValidationError("alias_only_revision_invalid")
    alias_added = False
    for concept_id, old in previous_concepts.items():
        new = candidate_concepts[concept_id]
        if old.label != new.label or old.kind != new.kind:
            raise OntologyValidationError("alias_only_revision_invalid")
        old_aliases = set(old.aliases)
        new_aliases = set(new.aliases)
        if not old_aliases <= new_aliases:
            raise OntologyValidationError("alias_only_revision_invalid")
        alias_added = alias_added or old_aliases != new_aliases
    if {
        _relation_signature(relation) for relation in previous.relations
    } != {_relation_signature(relation) for relation in candidate.relations}:
        raise OntologyValidationError("alias_only_revision_invalid")
    if not alias_added:
        raise OntologyValidationError("alias_only_revision_invalid")


__all__ = [
    "COMPANY_SLUG_RE",
    "COMPANY_SOURCE_NODE_TYPES",
    "COMPANY_SOURCE_SCHEMA",
    "CONCEPT_KINDS",
    "DOMAIN_EXCLUSION_KINDS",
    "FACT_STATUSES",
    "FICTIONAL_COMPANY_ORIGINS",
    "GRAPH_SNAPSHOT_SCHEMA",
    "MAX_COMPANY_NAME_LENGTH",
    "MAX_ONTOLOGY_VERSION_LENGTH",
    "NODE_TYPES",
    "ONTOLOGY_SCHEMA",
    "ORIGINS",
    "OVERLAY_ORIGINS",
    "PROFILE_ORIGIN_FICTIONAL",
    "PROFILE_ORIGIN_REAL",
    "REAL_COMPANY_ORIGINS",
    "RELATION_ENDPOINTS",
    "CompanyIdentity",
    "CompanyIdentityValidationError",
    "CompanyKnowledgeEdge",
    "CompanyKnowledgeNode",
    "CompanyKnowledgeValidationError",
    "CompanyOntologyError",
    "GraphSnapshot",
    "OntologyConcept",
    "OntologyRelation",
    "OntologyValidationError",
    "SourceRef",
    "ValidatedCompanyKnowledge",
    "ValidatedOntology",
    "build_graph_snapshot",
    "canonical_json_bytes",
    "normalize_term",
    "normalize_company_identity",
    "parse_company_knowledge_source",
    "parse_ontology",
    "profile_origin_for",
    "registration_origin_allowed",
    "sha256_bytes",
    "status_origin_allowed",
    "validate_alias_only_revision",
]
