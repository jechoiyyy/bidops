"""DEMO-02 STEP-005 company profile/graph/evidence read API (spec T4·T6)."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.core.db import get_db, init_db
from app.deep_review.models import (
    CompanyKnowledgeBinding,
    CompanyKnowledgeSource,
    CompanyKnowledgeVersion,
    ContentObject,
    ContentObjectLocation,
    ProfileEvidence,
    ProfileVersion,
)
from app.deep_review.services import assets
from app.deep_review.services import company_knowledge as company_knowledge_service
from app.deep_review.services.company_knowledge import (
    activate_company_knowledge,
    import_company_knowledge,
    prepare_company_knowledge,
    prepare_company_knowledge_files,
)
from app.deep_review.services.input_versions import InputVersionError
from tests.deep_review.test_company_knowledge import (  # noqa: F401 - shared fixtures
    _ontology,
    _prepared,
    _raw,
    _source,
    engine,
    object_store,
)


FIXTURES = Path(__file__).parents[4] / "docs" / "demo-fixtures"
ONTOLOGY_FILE = FIXTURES / "ontology.v1.json"
COMPANY_FILES = tuple(sorted((FIXTURES / "companies").glob("*.v1.json")))
FORBIDDEN_PUBLIC_KEYS = (
    "source_refs",
    "json_pointer",
    "object_key",
    "object_version_id",
    "source_file",
    "content_location",
    "locator",
    "etag",
)
ENVELOPE_KEYS = {"error", "request_id"}


def _schemas():
    # Imported lazily so that, before STEP-005 exists, the missing module is a
    # test failure rather than a collection error.
    from app.deep_review.schemas import company_knowledge as schemas

    return schemas


def _application(engine, monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True):
    sessions = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def request_session():
        with sessions() as session:
            yield session

    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(demo_enabled=enabled),
    )
    application = main_module.create_app(
        modules=("lifecycle", "deep_review"), mount_frontend=False
    )
    application.dependency_overrides[get_db] = request_session
    return application, sessions


def _import(sessions, prepared, *, activate: bool):
    with sessions() as session:
        with session.begin():
            imported = import_company_knowledge(session, prepared, actor="등록 담당자")
            if activate:
                activate_company_knowledge(
                    session,
                    company_id=imported.company_id,
                    graph_version_id=imported.graph_version_id,
                    actor="활성 담당자",
                )
    return imported


def _second_company():
    first = _prepared()
    source = deepcopy(_source(first.ontology.sha256))
    source["company"] = {"slug": "second-si", "name": "두번째 SI", "is_fictional": True}
    source["nodes"][0]["label"] = "두번째 SI"
    return prepare_company_knowledge(_raw(_ontology()), _raw(source))


def _profile_path(company_id) -> str:
    return f"/api/companies/{company_id}/profile"


def _graph_path(company_id) -> str:
    return f"/api/companies/{company_id}/knowledge-graph"


def _evidence_path(company_id, evidence_id) -> str:
    return f"/api/companies/{company_id}/profile-evidence/{evidence_id}"


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == ENVELOPE_KEYS, body
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert body["error"]["details"] is None
    assert body["request_id"] is None


def _profile(client, company_id, **params):
    response = client.get(_profile_path(company_id), params=params)
    assert response.status_code == 200, response.text
    _schemas().CompanyProfileView.model_validate_json(response.text)
    return response.json()


def _graph(client, company_id, **params):
    response = client.get(_graph_path(company_id), params=params)
    assert response.status_code == 200, response.text
    _schemas().CompanyKnowledgeGraphView.model_validate_json(response.text)
    return response.json()


def _evidence(client, company_id, evidence_id):
    response = client.get(_evidence_path(company_id, evidence_id))
    assert response.status_code == 200, response.text
    _schemas().CompanyProfileEvidenceView.model_validate_json(response.text)
    return response.json()


def _evidence_ids(profile_body) -> list[str]:
    return [
        evidence_id
        for fact in profile_body["facts"]
        for evidence_id in fact["evidence_ids"]
    ]


# --- T4 ---------------------------------------------------------------------


def test_t4_profile_requires_binding_but_explicit_version_is_readable(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch)
    imported = _import(sessions, _prepared(), activate=False)
    client = TestClient(application)

    _assert_error(
        client.get(_profile_path(imported.company_id)), 409, "company_profile_not_ready"
    )
    _assert_error(
        client.get(_graph_path(imported.company_id)), 409, "company_profile_not_ready"
    )

    profile = _profile(
        client, imported.company_id, graph_version_id=str(imported.graph_version_id)
    )
    assert set(profile) == {
        "schema_version", "company", "profile_version_id", "profile_sha256",
        "graph_version_id", "graph_sha256", "ontology_version", "facts",
    }
    assert profile["schema_version"] == "bidops.company-profile-view.v1"
    assert profile["company"]["company_id"] == str(imported.company_id)
    assert profile["company"]["slug"] == "synthetic-si"
    assert set(profile["company"]) == {
        "company_id", "slug", "name", "is_fictional", "created_at"
    }
    assert profile["profile_version_id"] == str(imported.profile_version_id)
    assert profile["graph_version_id"] == str(imported.graph_version_id)
    assert profile["profile_sha256"] == imported.source_sha256
    assert profile["graph_sha256"] == imported.graph_sha256
    assert profile["ontology_version"] == "ontology-v1"
    graph = _graph(
        client, imported.company_id, graph_version_id=str(imported.graph_version_id)
    )
    assert graph["schema_version"] == "bidops.company-knowledge-graph.v1"
    assert graph["graph_version_id"] == str(imported.graph_version_id)
    assert graph["company_id"] == str(imported.company_id)

    with sessions() as session:
        # Reading never activates anything.
        assert session.get(CompanyKnowledgeBinding, imported.company_id) is None


def test_t4_past_version_is_reproduced_after_activating_a_new_version(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch)
    first = _import(sessions, _prepared(), activate=True)
    client = TestClient(application)

    v1_profile = _profile(client, first.company_id)
    v1_graph = _graph(client, first.company_id)
    v1_graph_small = _graph(client, first.company_id, depth=1, limit=2)
    v1_evidence = {
        evidence_id: _evidence(client, first.company_id, evidence_id)
        for evidence_id in _evidence_ids(v1_profile)
    }
    assert v1_profile["graph_version_id"] == str(first.graph_version_id)
    assert len(v1_evidence) == 2

    second = _import(
        sessions,
        _prepared(scenario="scenario-v2", description="변경된 합성 역량"),
        activate=True,
    )
    assert second.company_id == first.company_id
    assert second.graph_version_id != first.graph_version_id

    current = _profile(client, first.company_id)
    assert current["graph_version_id"] == str(second.graph_version_id)
    assert current["profile_version_id"] == str(second.profile_version_id)
    assert current["profile_sha256"] == second.source_sha256
    capability = next(
        fact for fact in current["facts"] if fact["fact_key"] == "cap.delivery"
    )
    assert capability["value"]["description"] == "변경된 합성 역량"
    current_graph = _graph(client, first.company_id)
    assert current_graph["graph_version_id"] == str(second.graph_version_id)
    assert current_graph["graph_sha256"] == second.graph_sha256
    for evidence_id in _evidence_ids(current):
        assert evidence_id not in v1_evidence
        assert _evidence(client, first.company_id, evidence_id)["quote"] in {
            "가상회사", "변경된 합성 역량"
        }

    past = str(first.graph_version_id)
    assert _profile(client, first.company_id, graph_version_id=past) == v1_profile
    assert _graph(client, first.company_id, graph_version_id=past) == v1_graph
    assert (
        _graph(client, first.company_id, graph_version_id=past, depth=1, limit=2)
        == v1_graph_small
    )
    for evidence_id, body in v1_evidence.items():
        assert _evidence(client, first.company_id, evidence_id) == body


def test_t4_other_company_unknown_and_legacy_resources_are_not_found(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch)
    alpha = _import(sessions, _prepared(), activate=True)
    beta = _import(sessions, _second_company(), activate=True)
    assert alpha.company_id != beta.company_id
    client = TestClient(application)
    beta_profile = _profile(client, beta.company_id)
    beta_evidence_id = _evidence_ids(beta_profile)[0]

    beta_graph = str(beta.graph_version_id)
    _assert_error(
        client.get(_profile_path(alpha.company_id), params={"graph_version_id": beta_graph}),
        404,
        "not_found",
    )
    _assert_error(
        client.get(_graph_path(alpha.company_id), params={"graph_version_id": beta_graph}),
        404,
        "not_found",
    )
    _assert_error(
        client.get(_evidence_path(alpha.company_id, beta_evidence_id)), 404, "not_found"
    )
    missing_graph = str(uuid4())
    _assert_error(
        client.get(_profile_path(alpha.company_id), params={"graph_version_id": missing_graph}),
        404,
        "not_found",
    )
    _assert_error(
        client.get(_evidence_path(alpha.company_id, uuid4())), 404, "not_found"
    )

    unknown_company = uuid4()
    _assert_error(client.get(_profile_path(unknown_company)), 404, "not_found")
    _assert_error(client.get(_graph_path(unknown_company)), 404, "not_found")
    _assert_error(
        client.get(_profile_path(unknown_company), params={"graph_version_id": beta_graph}),
        404,
        "not_found",
    )
    _assert_error(
        client.get(_evidence_path(unknown_company, beta_evidence_id)), 404, "not_found"
    )

    with sessions() as session:
        with session.begin():
            content = ContentObject(
                id=uuid4(),
                sha256="a" * 64,
                size_bytes=1,
                detected_mime="text/markdown",
                retention_class="fixture",
            )
            legacy = ProfileVersion(
                id=uuid4(),
                company_id=None,
                version=900,
                label="legacy-profile",
                profile_payload={"schema": "bidops.company-profile.v1"},
                profile_sha256="a" * 64,
                source_kind="fixture",
            )
            session.add_all([content, legacy])
            session.flush()
            legacy_evidence = ProfileEvidence(
                id=uuid4(),
                profile_version_id=legacy.id,
                fact_key="legacy.fact",
                content_object_id=content.id,
                source_sha256="a" * 64,
                locator_type="profile_fact",
                locator={"fact_key": "legacy.fact"},
                quote="기존 전역 프로필 인용",
                confirmed_by_name="기존 담당자",
                confirmed_at=datetime.now(UTC),
            )
            session.add(legacy_evidence)
        legacy_evidence_id = legacy_evidence.id
    legacy_response = client.get(_evidence_path(alpha.company_id, legacy_evidence_id))
    _assert_error(legacy_response, 404, "not_found")
    assert "기존 전역 프로필 인용" not in legacy_response.text

    # The other company's own reads are unaffected.
    assert _profile(client, beta.company_id) == beta_profile


def test_t4_demo_disabled_hides_company_knowledge_paths_before_validation(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch, enabled=False)
    imported = _import(sessions, _prepared(), activate=True)
    client = TestClient(application)
    with sessions() as session:
        evidence_id = session.scalar(
            select(ProfileEvidence.id).where(
                ProfileEvidence.profile_version_id == imported.profile_version_id
            )
        )
    assert evidence_id is not None
    for path in (
        _profile_path(imported.company_id),
        _graph_path(imported.company_id),
        _evidence_path(imported.company_id, evidence_id),
        "/api/companies/not-a-uuid/profile",
        "/api/companies/not-a-uuid/knowledge-graph?depth=99&root_node_id=BAD",
        "/api/companies/not-a-uuid/profile-evidence/not-a-uuid",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json() == {"detail": "Not Found"}, path


def test_t4_company_knowledge_routes_are_provided_by_deep_review() -> None:
    from app import deep_review

    paths = {route.path for route in deep_review.company_knowledge_router.routes}
    assert paths == {
        "/api/companies/{company_id}/profile",
        "/api/companies/{company_id}/knowledge-graph",
        "/api/companies/{company_id}/profile-evidence/{evidence_id}",
    }
    assert ("deep_review", "company_knowledge_router") in main_module._ROUTER_REGISTRATION


# --- T6 ---------------------------------------------------------------------


def _fixture_sources() -> dict[str, tuple[bytes, dict]]:
    return {
        path.name: (path.read_bytes(), json.loads(path.read_bytes()))
        for path in COMPANY_FILES
    }


def _import_fixtures(sessions):
    assert len(COMPANY_FILES) == 3
    imported = {}
    for path in COMPANY_FILES:
        prepared = prepare_company_knowledge_files(ONTOLOGY_FILE, path)
        imported[path.name] = _import(sessions, prepared, activate=True)
    return imported


def _fixture_digests() -> dict[str, str]:
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ONTOLOGY_FILE, *COMPANY_FILES)
    }


def _fact_ref(node: dict) -> tuple[str, str]:
    (ref,) = node["source_refs"]
    return ref["locator"]["json_pointer"], ref["quote"]


def test_t6_profile_and_evidence_match_frozen_source_facts(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _fixture_digests()
    application, sessions = _application(engine, monkeypatch)
    imported = _import_fixtures(sessions)
    client = TestClient(application)

    for name, (raw, source) in _fixture_sources().items():
        row = imported[name]
        digest = hashlib.sha256(raw).hexdigest()
        profile = _profile(client, row.company_id)
        assert profile["profile_sha256"] == digest
        assert profile["company"]["slug"] == source["company"]["slug"]
        assert profile["company"]["name"] == source["company"]["name"]
        assert profile["company"]["is_fictional"] is True
        fact_nodes = sorted(
            (node for node in source["nodes"] if node["type"] != "evidence"),
            key=lambda node: node["id"],
        )
        assert [fact["fact_key"] for fact in profile["facts"]] == [
            node["id"] for node in fact_nodes
        ]
        assert any(node["status"] == "unknown" for node in fact_nodes)
        for fact, node in zip(profile["facts"], fact_nodes):
            assert set(fact) == {
                "fact_key", "label", "status", "origin", "value", "evidence_ids"
            }
            assert fact["label"] == node["label"]
            assert fact["status"] == node["status"]
            assert fact["value"] == node["value"]
            assert fact["origin"] == "fictional_scenario"
            if node["status"] == "unknown":
                assert fact["value"] is None
                assert fact["evidence_ids"] == []
                continue
            assert len(fact["evidence_ids"]) == 1
            evidence = _evidence(client, row.company_id, fact["evidence_ids"][0])
            assert evidence == {
                "evidence_id": fact["evidence_ids"][0],
                "profile_version_id": str(row.profile_version_id),
                "fact_key": node["id"],
                "origin": "fictional_scenario",
                "quote": _fact_ref(node)[1],
                "source_sha256": digest,
            }
    assert _fixture_digests() == before


def test_t6_public_responses_never_expose_private_locators_or_paths(
    engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    application, sessions = _application(engine, monkeypatch)
    imported = _import_fixtures(sessions)
    client = TestClient(application)
    with sessions() as session:
        locations = list(session.scalars(select(ContentObjectLocation)))
        object_keys = [location.object_key for location in locations]
        version_ids = [location.object_version_id for location in locations]
        source_ids = [str(row.id) for row in session.scalars(select(CompanyKnowledgeSource))]
    assert object_keys and all(object_keys)
    private_values = [
        *object_keys,
        *version_ids,
        *source_ids,
        str(tmp_path),
        str(assets.asset_root(tmp_path)),
        str(FIXTURES),
    ]
    for row in imported.values():
        profile_response = client.get(_profile_path(row.company_id))
        graph_response = client.get(
            _graph_path(row.company_id), params={"depth": 3, "limit": 500}
        )
        responses = [profile_response, graph_response]
        responses.extend(
            client.get(_evidence_path(row.company_id, evidence_id))
            for evidence_id in _evidence_ids(profile_response.json())
        )
        graph = graph_response.json()
        assert set(graph) == {
            "schema_version", "company_id", "graph_version_id", "graph_sha256",
            "ontology_version", "nodes", "edges", "truncated", "omitted_node_count",
        }
        assert graph["nodes"] and graph["edges"]
        assert all(
            set(node) == {
                "id", "type", "label", "concept_id", "status", "origin", "value",
                "evidence_ids",
            }
            for node in graph["nodes"]
        )
        assert all(
            set(edge) == {
                "id", "type", "from_id", "to_id", "status", "origin", "evidence_ids"
            }
            for edge in graph["edges"]
        )
        for response in responses:
            assert response.status_code == 200, response.text
            for marker in (*FORBIDDEN_PUBLIC_KEYS, *private_values):
                assert marker not in response.text, marker


def _independent_distances(source: dict, root: str, depth: int) -> dict[str, int]:
    """Level-synchronous frontier expansion, written apart from the service."""

    distances = {root: 0}
    for level in range(1, depth + 1):
        frontier = {node for node, distance in distances.items() if distance == level - 1}
        for edge in source["edges"]:
            for here, there in (
                (edge["from_id"], edge["to_id"]),
                (edge["to_id"], edge["from_id"]),
            ):
                if here in frontier and there not in distances:
                    distances[there] = level
    return distances


def _expected_evidence_ids(source: dict, item: dict, fact_evidence: dict[str, list[str]]):
    if item.get("status") == "unknown":
        return []
    if "from_id" not in item and item["type"] != "evidence":
        return fact_evidence[item["id"]]
    by_ref = {
        _fact_ref(node): node["id"]
        for node in source["nodes"]
        if node["type"] != "evidence" and node["status"] != "unknown"
    }
    expected: list[str] = []
    for ref in item["source_refs"]:
        fact_key = by_ref[(ref["locator"]["json_pointer"], ref["quote"])]
        for evidence_id in fact_evidence[fact_key]:
            if evidence_id not in expected:
                expected.append(evidence_id)
    return expected


TRUNCATION_CASES = (
    (None, 1, 200),
    (None, 2, 200),
    (None, 3, 500),
    (None, 1, 3),
    (None, 2, 5),
    (None, 2, 17),
    (None, 3, 10),
    (None, 3, 1),
    ("first-capability", 1, 200),
    ("first-capability", 2, 4),
    ("first-evidence", 3, 7),
)
NODE_KEYS = ("id", "type", "label", "concept_id", "status", "origin", "value")
EDGE_KEYS = ("id", "type", "from_id", "to_id", "status", "origin")


def test_t6_graph_truncation_is_exact_on_frozen_fixtures(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch)
    imported = _import_fixtures(sessions)
    client = TestClient(application)
    saw_truncation = False
    saw_complete = False
    saw_unknown_edge = False

    for name, (_raw_bytes, source) in _fixture_sources().items():
        row = imported[name]
        profile = _profile(client, row.company_id)
        fact_evidence = {fact["fact_key"]: fact["evidence_ids"] for fact in profile["facts"]}
        nodes_by_id = {node["id"]: node for node in source["nodes"]}
        (company_node,) = [node for node in source["nodes"] if node["type"] == "company"]
        roots = {
            None: company_node["id"],
            "first-capability": sorted(
                node["id"] for node in source["nodes"] if node["type"] == "capability"
            )[0],
            "first-evidence": sorted(
                node["id"] for node in source["nodes"] if node["type"] == "evidence"
            )[0],
        }
        for root_key, depth, limit in TRUNCATION_CASES:
            root = roots[root_key]
            params = {"depth": depth, "limit": limit}
            if root_key is not None:
                params["root_node_id"] = root
            graph = _graph(client, row.company_id, **params)
            distances = _independent_distances(source, root, depth)
            ordered = sorted(distances, key=lambda node_id: (distances[node_id], node_id))
            returned = ordered[:limit]
            assert [node["id"] for node in graph["nodes"]] == returned, (name, params)
            assert graph["omitted_node_count"] == len(distances) - len(returned)
            assert graph["truncated"] is (len(distances) > len(returned))
            saw_truncation |= graph["truncated"]
            saw_complete |= not graph["truncated"]
            returned_set = set(returned)
            expected_edges = sorted(
                (
                    edge
                    for edge in source["edges"]
                    if edge["from_id"] in returned_set and edge["to_id"] in returned_set
                ),
                key=lambda edge: edge["id"],
            )
            assert [edge["id"] for edge in graph["edges"]] == [
                edge["id"] for edge in expected_edges
            ], (name, params)
            assert all(
                edge["from_id"] in returned_set and edge["to_id"] in returned_set
                for edge in graph["edges"]
            )
            assert graph["graph_version_id"] == str(row.graph_version_id)
            assert graph["graph_sha256"] == row.graph_sha256
            assert graph["ontology_version"] == row.ontology_version
            for node in graph["nodes"]:
                stored = nodes_by_id[node["id"]]
                assert {key: node[key] for key in NODE_KEYS} == {
                    key: stored[key] for key in NODE_KEYS
                }
                assert node["evidence_ids"] == _expected_evidence_ids(
                    source, stored, fact_evidence
                ), node["id"]
            for edge, stored in zip(graph["edges"], expected_edges):
                assert {key: edge[key] for key in EDGE_KEYS} == {
                    key: stored[key] for key in EDGE_KEYS
                }
                assert edge["evidence_ids"] == _expected_evidence_ids(
                    source, stored, fact_evidence
                ), edge["id"]
                if stored["status"] == "unknown":
                    saw_unknown_edge = True
                    assert edge["evidence_ids"] == []
                else:
                    assert edge["evidence_ids"]
    assert saw_truncation and saw_complete and saw_unknown_edge


def test_t6_graph_traversal_terminates_on_cycles(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch)
    imported = _import_fixtures(sessions)
    client = TestClient(application)
    for name, (_raw_bytes, source) in _fixture_sources().items():
        graph = _graph(client, imported[name].company_id, depth=3, limit=500)
        ids = [node["id"] for node in graph["nodes"]]
        assert len(ids) == len(set(ids))
        # A connected undirected subgraph with at least as many edges as nodes
        # contains a cycle; traversal still terminates with each node once.
        assert len(graph["edges"]) >= len(ids)
        assert set(ids) == set(_independent_distances(source, "company", 3))
        assert graph["truncated"] is False
        assert graph["omitted_node_count"] == 0


def test_t6_graph_query_validation_and_absent_root(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch)
    imported = _import(sessions, _prepared(), activate=True)
    client = TestClient(application)
    path = _graph_path(imported.company_id)

    _assert_error(client.get(path, params={"root_node_id": "absent.node"}), 404, "not_found")
    for params in (
        {"root_node_id": "Bad Root"},
        {"root_node_id": "1starts-with-digit"},
        {"root_node_id": "a" * 129},
        {"root_node_id": ""},
        {"depth": 0},
        {"depth": 4},
        {"depth": "two"},
        {"limit": 0},
        {"limit": 501},
        {"graph_version_id": "not-a-uuid"},
    ):
        response = client.get(path, params=params)
        assert response.status_code == 422, (params, response.text)
        assert "detail" in response.json(), params
    assert client.get(
        _profile_path(imported.company_id), params={"graph_version_id": "x"}
    ).status_code == 422
    assert client.get("/api/companies/not-a-uuid/profile").status_code == 422
    assert client.get(_evidence_path(imported.company_id, "not-a-uuid")).status_code == 422

    default = _graph(client, imported.company_id)
    assert [node["id"] for node in default["nodes"]] == [
        "company.synthetic", "cap.delivery", "evidence.delivery"
    ]
    assert default["truncated"] is False and default["omitted_node_count"] == 0
    depth_one = _graph(client, imported.company_id, depth=1)
    assert [node["id"] for node in depth_one["nodes"]] == [
        "company.synthetic", "cap.delivery"
    ]
    assert [edge["id"] for edge in depth_one["edges"]] == ["edge.company-capability"]
    limited = _graph(client, imported.company_id, limit=1)
    assert [node["id"] for node in limited["nodes"]] == ["company.synthetic"]
    assert limited["edges"] == []
    assert limited["truncated"] is True and limited["omitted_node_count"] == 2
    # The unknown qualification is not connected; rooted there it is alone.
    unknown = _graph(client, imported.company_id, root_node_id="qual.synthetic")
    assert unknown["nodes"] == [
        {
            "id": "qual.synthetic", "type": "qualification", "label": "가상 자격",
            "concept_id": "qual.synthetic", "status": "unknown",
            "origin": "fictional_scenario", "value": None, "evidence_ids": [],
        }
    ]
    assert unknown["edges"] == []


def _safe_processing_failed(response, *leaks: str) -> None:
    _assert_error(response, 500, "processing_failed")
    for leak in leaks:
        assert leak not in response.text


def test_t6_inconsistent_frozen_lineage_fails_closed(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch)
    imported = _import(sessions, _prepared(), activate=True)
    client = TestClient(application)
    evidence_id = _evidence_ids(_profile(client, imported.company_id))[0]

    def reject(*_args, **_kwargs):
        raise InputVersionError("service_unavailable", "내부 계보 메시지 /private/x")

    monkeypatch.setattr(company_knowledge_service, "validate_profile_snapshot", reject)
    for response in (
        client.get(_profile_path(imported.company_id)),
        client.get(_graph_path(imported.company_id)),
        client.get(
            _profile_path(imported.company_id),
            params={"graph_version_id": str(imported.graph_version_id)},
        ),
        client.get(_evidence_path(imported.company_id, evidence_id)),
    ):
        _safe_processing_failed(
            response, "내부 계보 메시지", "/private/x", "service_unavailable"
        )

    def explode(*_args, **_kwargs):
        raise RuntimeError("unexpected secret /private/source.json")

    monkeypatch.setattr(company_knowledge_service, "validate_profile_snapshot", explode)
    for response in (
        client.get(_profile_path(imported.company_id)),
        client.get(_graph_path(imported.company_id)),
        client.get(_evidence_path(imported.company_id, evidence_id)),
    ):
        _safe_processing_failed(response, "unexpected secret", "/private/source.json")


def test_t6_tampered_frozen_rows_fail_closed_without_correction(
    object_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raw SQL bypasses the ORM append-only guard; SQLite has no DB trigger."""

    bind = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(bind)
    try:
        application, sessions = _application(bind, monkeypatch)
        imported = _import(sessions, _prepared(), activate=True)
        client = TestClient(application)
        evidence_id = _evidence_ids(_profile(client, imported.company_id))[0]
        original_quote = _evidence(client, imported.company_id, evidence_id)["quote"]
        with sessions() as session:
            with session.begin():
                session.execute(
                    text(
                        "UPDATE profile_evidence SET quote = :quote "
                        "WHERE id = :evidence_id"
                    ),
                    {"quote": "변조된 인용", "evidence_id": UUID(evidence_id).hex},
                )
            assert session.scalar(
                select(ProfileEvidence.quote).where(
                    ProfileEvidence.id == UUID(evidence_id)
                )
            ) == "변조된 인용"
        for response in (
            client.get(_profile_path(imported.company_id)),
            client.get(_graph_path(imported.company_id)),
            client.get(
                _graph_path(imported.company_id),
                params={"graph_version_id": str(imported.graph_version_id)},
            ),
            client.get(_evidence_path(imported.company_id, evidence_id)),
        ):
            _safe_processing_failed(response, "변조된 인용")

        with sessions() as session:
            with session.begin():
                session.execute(
                    text(
                        "UPDATE profile_evidence SET quote = :quote "
                        "WHERE id = :evidence_id"
                    ),
                    {"quote": original_quote, "evidence_id": UUID(evidence_id).hex},
                )
        assert _evidence(client, imported.company_id, evidence_id)["quote"] == original_quote

        with sessions() as session:
            with session.begin():
                session.execute(
                    text(
                        "UPDATE company_knowledge_version SET graph_sha256 = :digest "
                        "WHERE id = :graph_id"
                    ),
                    {"digest": "f" * 64, "graph_id": imported.graph_version_id.hex},
                )
            graph = session.get(CompanyKnowledgeVersion, imported.graph_version_id)
            assert graph is not None and graph.graph_sha256 == "f" * 64
        _safe_processing_failed(client.get(_graph_path(imported.company_id)), "f" * 64)
    finally:
        bind.dispose()


# --- Review fix B1: every contract-valid import stays consumable -------------


def _role_ref(index: int, role: str) -> dict:
    return {
        "source_id": "self",
        "locator": {"json_pointer": f"/nodes/{index}/value/role"},
        "quote": role,
    }


def _staff_node(node_id: str, index: int) -> dict:
    role = f"합성 역할 {index}"
    return {
        "id": node_id, "type": "staff_group", "label": f"합성 인력 {index}",
        "concept_id": None, "status": "confirmed", "origin": "fictional_scenario",
        "value": {"role": role, "total": None, "available": None, "as_of": None},
        "source_refs": [_role_ref(index, role)],
    }


def _edge(edge_id: str, relation: str, from_id: str, to_id: str, refs: list, *, status="confirmed") -> dict:
    return {
        "id": edge_id, "type": relation, "from_id": from_id, "to_id": to_id,
        "status": status, "origin": "fictional_scenario", "source_refs": refs,
    }


def _consumable_case_source(ontology_sha256: str, case: str) -> dict:
    """Contract-valid sources that import and activate but used to be unreadable."""

    company_ref = {"source_id": "self", "locator": {"json_pointer": "/nodes/0/value"}, "quote": "가상회사"}
    capability_ref = {
        "source_id": "self",
        "locator": {"json_pointer": "/nodes/1/value/description"},
        "quote": "합성 구축 역량",
    }
    nodes = [
        {
            "id": "company.synthetic", "type": "company", "label": "합성 SI",
            "concept_id": None, "status": "confirmed", "origin": "fictional_scenario",
            "value": "가상회사", "source_refs": [company_ref],
        },
        {
            "id": "cap.delivery", "type": "capability", "label": "구축 역량",
            "concept_id": "cap.delivery", "status": "confirmed", "origin": "fictional_scenario",
            "value": {"scope": "core", "description": "합성 구축 역량"},
            "source_refs": [capability_ref],
        },
    ]
    edges = []
    if case == "unsorted_edge_refs":
        # String order puts "/nodes/10/..." before "/nodes/2/..."; the input
        # keeps the natural numeric order, and a second edge is reversed.
        for index in range(2, 11):
            nodes.append(_staff_node(f"staff.g{index:02d}", index))
            edges.append(
                _edge(
                    f"edge.staff-g{index:02d}", "has_staff", "company.synthetic",
                    f"staff.g{index:02d}", [_role_ref(index, f"합성 역할 {index}")],
                )
            )
        edges.append(
            _edge(
                "edge.multi-ref", "has_staff", "company.synthetic", "staff.g02",
                [_role_ref(2, "합성 역할 2"), _role_ref(10, "합성 역할 10")],
            )
        )
        edges.append(
            _edge(
                "edge.company-capability", "has_capability", "company.synthetic",
                "cap.delivery", [capability_ref, company_ref],
            )
        )
    elif case == "unknown_evidence":
        nodes.append(
            {
                "id": "evidence.delivery", "type": "evidence", "label": "합성 근거",
                "concept_id": None, "status": "confirmed", "origin": "fictional_scenario",
                "value": {"fact_key": "cap.delivery"}, "source_refs": [capability_ref],
            }
        )
        nodes.append(
            {
                "id": "evidence.unknown", "type": "evidence", "label": "미확인 근거",
                "concept_id": None, "status": "unknown", "origin": "fictional_scenario",
                "value": None, "source_refs": [],
            }
        )
        edges.extend(
            [
                _edge("edge.company-capability", "has_capability", "company.synthetic", "cap.delivery", [capability_ref]),
                _edge("edge.capability-evidence", "supported_by", "cap.delivery", "evidence.delivery", [capability_ref]),
                _edge(
                    "edge.company-unknown-evidence", "supported_by", "company.synthetic",
                    "evidence.unknown", [], status="unknown",
                ),
            ]
        )
    elif case == "collation_ids":
        # Python/C order: "staff-b" < "staff.a"; PostgreSQL en_US.utf8
        # ignores punctuation first and orders "staff.a" < "staff-b".
        nodes.append(_staff_node("staff.a", 2))
        nodes.append(_staff_node("staff-b", 3))
        edges.extend(
            [
                _edge("edge.a", "has_staff", "company.synthetic", "staff.a", [_role_ref(2, "합성 역할 2")]),
                _edge("edge-b", "has_staff", "company.synthetic", "staff-b", [_role_ref(3, "합성 역할 3")]),
                _edge("edge.cap", "has_capability", "company.synthetic", "cap.delivery", [capability_ref]),
            ]
        )
    else:  # pragma: no cover - parametrization guard
        raise AssertionError(case)
    return {
        "schema_version": "bidops.company-knowledge-source.v1",
        "company": {"slug": "synthetic-si", "name": "합성 SI", "is_fictional": True},
        "scenario_version": f"scenario-{case}",
        "ontology_version": "ontology-v1",
        "ontology_sha256": ontology_sha256,
        "nodes": nodes,
        "edges": edges,
    }


@pytest.mark.parametrize("case", ["unsorted_edge_refs", "unknown_evidence", "collation_ids"])
def test_b1_contract_valid_source_is_consumable_after_import_and_activation(
    engine, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    from app.core.company_ontology import parse_ontology
    from app.deep_review.services.input_versions import (
        profile_context,
        validate_profile_snapshot,
    )

    ontology_raw = _raw(_ontology())
    source = _consumable_case_source(parse_ontology(ontology_raw).sha256, case)
    prepared = prepare_company_knowledge(ontology_raw, _raw(source))
    application, sessions = _application(engine, monkeypatch)
    imported = _import(sessions, prepared, activate=True)
    assert imported.created is True

    nodes = {node["id"]: node for node in source["nodes"]}
    edges = {edge["id"]: edge for edge in source["edges"]}
    fact_ids = sorted(node_id for node_id, node in nodes.items() if node["type"] != "evidence")
    with sessions() as session:
        profile = session.get(ProfileVersion, imported.profile_version_id)
        assert profile is not None
        validate_profile_snapshot(session, profile)
        context = profile_context(session, profile)
    assert [fact["fact_key"] for fact in context["facts"]] == fact_ids
    assert sorted(row["fact_key"] for row in context["evidence"]) == sorted(
        node_id for node_id in fact_ids if nodes[node_id]["status"] != "unknown"
    )

    client = TestClient(application)
    profile_body = _profile(client, imported.company_id)
    evidence_by_fact = {fact["fact_key"]: fact["evidence_ids"] for fact in profile_body["facts"]}
    assert sorted(evidence_by_fact) == fact_ids
    for fact_key, evidence_ids in evidence_by_fact.items():
        assert len(evidence_ids) == (0 if nodes[fact_key]["status"] == "unknown" else 1)
        for evidence_id in evidence_ids:
            evidence = _evidence(client, imported.company_id, evidence_id)
            assert evidence["fact_key"] == fact_key
            assert evidence["quote"] == nodes[fact_key]["source_refs"][0]["quote"]

    facts_by_ref: dict[tuple[str, str], list[str]] = {}
    for node in source["nodes"]:
        if node["type"] != "evidence" and node["status"] != "unknown":
            facts_by_ref.setdefault(_fact_ref(node), []).append(node["id"])

    def expected(item: dict) -> list[str]:
        result: set[str] = set()
        for ref in item["source_refs"]:
            for fact_key in facts_by_ref[(ref["locator"]["json_pointer"], ref["quote"])]:
                result.update(evidence_by_fact[fact_key])
        return sorted(result)

    graph = _graph(client, imported.company_id, depth=3, limit=500)
    assert graph["truncated"] is False and graph["omitted_node_count"] == 0
    assert {node["id"] for node in graph["nodes"]} == set(nodes)
    assert [edge["id"] for edge in graph["edges"]] == sorted(edges)
    for node in graph["nodes"]:
        source_node = nodes[node["id"]]
        wanted = (
            expected(source_node)
            if source_node["type"] == "evidence"
            else sorted(evidence_by_fact[node["id"]])
        )
        assert sorted(node["evidence_ids"]) == wanted, node["id"]
    for edge in graph["edges"]:
        assert sorted(edge["evidence_ids"]) == expected(edges[edge["id"]]), edge["id"]

    public_edges = {edge["id"]: edge for edge in graph["edges"]}
    public_nodes = {node["id"]: node for node in graph["nodes"]}
    if case == "unsorted_edge_refs":
        assert len(public_edges["edge.multi-ref"]["evidence_ids"]) == 2
        assert len(public_edges["edge.company-capability"]["evidence_ids"]) == 2
    elif case == "unknown_evidence":
        assert public_nodes["evidence.unknown"]["evidence_ids"] == []
        assert public_nodes["evidence.unknown"]["status"] == "unknown"
        assert public_nodes["evidence.unknown"]["value"] is None
        assert public_edges["edge.company-unknown-evidence"]["evidence_ids"] == []
        assert len(public_nodes["evidence.delivery"]["evidence_ids"]) == 1
    else:
        assert {"staff.a", "staff-b"} <= set(public_nodes)
        assert {"edge.a", "edge-b"} <= set(public_edges)

    with sessions() as session:
        # Stored rows equal the frozen snapshot by construction.
        graph_row = session.get(CompanyKnowledgeVersion, imported.graph_version_id)
        assert graph_row is not None
        from app.deep_review.models import CompanyKnowledgeEdge, CompanyKnowledgeNode

        node_rows = {
            row.node_id: row.payload
            for row in session.scalars(
                select(CompanyKnowledgeNode).where(
                    CompanyKnowledgeNode.graph_version_id == graph_row.id
                )
            )
        }
        edge_rows = {
            row.edge_id: (row.from_id, row.to_id, row.payload)
            for row in session.scalars(
                select(CompanyKnowledgeEdge).where(
                    CompanyKnowledgeEdge.graph_version_id == graph_row.id
                )
            )
        }
    assert node_rows == {node["id"]: node for node in graph_row.snapshot["nodes"]}
    assert edge_rows == {
        edge["id"]: (edge["from_id"], edge["to_id"], edge)
        for edge in graph_row.snapshot["edges"]
    }
