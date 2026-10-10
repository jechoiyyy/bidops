"""Strict public contracts for company profile, graph, and evidence reads.

The public graph shape deliberately has no ``source_refs``: private source
locators (JSON pointers, object keys and versions) stay in the frozen graph
snapshot and are never serialized to API consumers (demo contract §4).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
)

from ...core.company_ontology import STABLE_KEY_RE
from ...lifecycle.schemas.companies import CompanyDTO


PROFILE_VIEW_SCHEMA = "bidops.company-profile-view.v1"
KNOWLEDGE_GRAPH_VIEW_SCHEMA = "bidops.company-knowledge-graph.v1"

Hash = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
StableKey = Annotated[str, StringConstraints(strict=True, pattern=STABLE_KEY_RE.pattern)]
FactStatus = Literal["confirmed", "inferred", "unknown"]
NodeOrigin = Literal["fictional_scenario", "public_document", "model_inference"]
NodeType = Literal[
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
RelationType = Literal[
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


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CompanyProfileFact(_StrictModel):
    fact_key: StableKey
    label: StrictStr
    status: FactStatus
    origin: Literal["fictional_scenario"]
    value: JsonValue
    evidence_ids: list[UUID]


class CompanyProfileView(_StrictModel):
    schema_version: Literal["bidops.company-profile-view.v1"]
    company: CompanyDTO
    profile_version_id: UUID
    profile_sha256: Hash
    graph_version_id: UUID
    graph_sha256: Hash
    ontology_version: StrictStr
    facts: list[CompanyProfileFact]


class PublicKnowledgeNode(_StrictModel):
    id: StableKey
    type: NodeType
    label: StrictStr
    concept_id: StrictStr | None
    status: FactStatus
    origin: NodeOrigin
    value: JsonValue
    evidence_ids: list[UUID]


class PublicKnowledgeEdge(_StrictModel):
    id: StableKey
    type: RelationType
    from_id: StableKey
    to_id: StableKey
    status: FactStatus
    origin: NodeOrigin
    evidence_ids: list[UUID]


class CompanyKnowledgeGraphView(_StrictModel):
    schema_version: Literal["bidops.company-knowledge-graph.v1"]
    company_id: UUID
    graph_version_id: UUID
    graph_sha256: Hash
    ontology_version: StrictStr
    nodes: list[PublicKnowledgeNode]
    edges: list[PublicKnowledgeEdge]
    truncated: StrictBool
    omitted_node_count: StrictInt = Field(ge=0)


class CompanyProfileEvidenceView(_StrictModel):
    evidence_id: UUID
    profile_version_id: UUID
    fact_key: StableKey
    origin: Literal["fictional_scenario"]
    quote: StrictStr
    source_sha256: Hash


__all__ = [
    "KNOWLEDGE_GRAPH_VIEW_SCHEMA",
    "PROFILE_VIEW_SCHEMA",
    "CompanyKnowledgeGraphView",
    "CompanyProfileEvidenceView",
    "CompanyProfileFact",
    "CompanyProfileView",
    "PublicKnowledgeEdge",
    "PublicKnowledgeNode",
]
