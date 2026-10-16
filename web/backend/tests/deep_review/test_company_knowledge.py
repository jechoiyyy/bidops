"""DEMO-02 STEP-002 immutable registration and binding tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.core.models import AuditEvent
from app.deep_review.models import (
    CompanyKnowledgeBinding,
    CompanyKnowledgeBindingEvent,
    CompanyKnowledgeEdge,
    CompanyKnowledgeNode,
    CompanyKnowledgeSource,
    CompanyKnowledgeVersion,
    KnowledgeOntologyVersion,
    ProfileEvidence,
    ProfileVersion,
)
from app.deep_review.services import assets
from app.deep_review.services import input_versions
from app.deep_review.services.company_knowledge import (
    CompanyKnowledgeServiceError,
    activate_company_knowledge,
    import_company_knowledge,
    prepare_company_knowledge,
)
from app.lifecycle.models import Company
from tests.postgres import migrated_engine, requires_postgres


RELATIONS = [
    ("has_capability", ["company"], ["capability"]),
    ("uses_technology", ["project", "capability"], ["technology"]),
    ("operates_in", ["company", "project"], ["domain"]),
    ("has_staff", ["company"], ["staff_group"]),
    ("performed", ["company"], ["project"]),
    ("supports_capability", ["project", "staff_group"], ["capability"]),
    ("holds_qualification", ["company"], ["qualification"]),
    (
        "supported_by",
        ["company", "capability", "technology", "domain", "staff_group", "project", "qualification", "requirement"],
        ["evidence"],
    ),
    ("has_requirement", ["notice"], ["requirement"]),
    ("requires_capability", ["requirement"], ["capability"]),
    ("requires_qualification", ["requirement"], ["qualification"]),
]


def _raw(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _ontology() -> dict:
    return {
        "schema_version": "bidops.company-ontology.v1",
        "version": "ontology-v1",
        "concepts": [
            {"id": "cap.delivery", "label": "구축 역량", "aliases": ["시스템 구축"], "kind": "capability"},
            {"id": "tech.python", "label": "Python", "aliases": ["파이썬"], "kind": "technology"},
            {"id": "domain.public", "label": "공공 업무", "aliases": ["공공 SI"], "kind": "domain"},
            {"id": "qual.synthetic", "label": "가상 자격", "aliases": ["합성 자격"], "kind": "qualification"},
        ],
        "relations": [
            {"type": name, "from_types": sources, "to_types": targets, "evidence_required": True}
            for name, sources, targets in RELATIONS
        ],
    }


def _source(ontology_sha256: str, *, scenario: str = "scenario-v1", description: str = "합성 구축 역량") -> dict:
    return {
        "schema_version": "bidops.company-knowledge-source.v1",
        "company": {"slug": "synthetic-si", "name": "합성 SI", "is_fictional": True},
        "scenario_version": scenario,
        "ontology_version": "ontology-v1",
        "ontology_sha256": ontology_sha256,
        "nodes": [
            {
                "id": "company.synthetic", "type": "company", "label": "합성 SI",
                "concept_id": None, "status": "confirmed", "origin": "fictional_scenario",
                "value": "가상회사",
                "source_refs": [{"source_id": "self", "locator": {"json_pointer": "/nodes/0/value"}, "quote": "가상회사"}],
            },
            {
                "id": "cap.delivery", "type": "capability", "label": "구축 역량",
                "concept_id": "cap.delivery", "status": "confirmed", "origin": "fictional_scenario",
                "value": {"scope": "core", "description": description},
                "source_refs": [{"source_id": "self", "locator": {"json_pointer": "/nodes/1/value/description"}, "quote": description}],
            },
            {
                "id": "qual.synthetic", "type": "qualification", "label": "가상 자격",
                "concept_id": "qual.synthetic", "status": "unknown", "origin": "fictional_scenario",
                "value": None, "source_refs": [],
            },
            {
                "id": "evidence.delivery", "type": "evidence", "label": "합성 근거",
                "concept_id": None, "status": "confirmed", "origin": "fictional_scenario",
                "value": {"fact_key": "cap.delivery"},
                "source_refs": [{"source_id": "self", "locator": {"json_pointer": "/nodes/1/value/description"}, "quote": description}],
            },
        ],
        "edges": [
            {
                "id": "edge.company-capability", "type": "has_capability",
                "from_id": "company.synthetic", "to_id": "cap.delivery",
                "status": "confirmed", "origin": "fictional_scenario",
                "source_refs": [{"source_id": "self", "locator": {"json_pointer": "/nodes/1/value/description"}, "quote": description}],
            },
            {
                "id": "edge.capability-evidence", "type": "supported_by",
                "from_id": "cap.delivery", "to_id": "evidence.delivery",
                "status": "confirmed", "origin": "fictional_scenario",
                "source_refs": [{"source_id": "self", "locator": {"json_pointer": "/nodes/1/value/description"}, "quote": description}],
            },
        ],
    }


def _ref(pointer: str, quote: str) -> list[dict]:
    return [{"source_id": "self", "locator": {"json_pointer": pointer}, "quote": quote}]


def _real_source(
    ontology_sha256: str,
    *,
    slug: str = "real-test-co",
    name: str = "실회사 검사",
    version: str = "real-test-2026-10-16",
    credit_status: str = "proposed",
) -> dict:
    """RL-00 실회사 파일 (`is_fictional=false`): 새 origin·`proposed`·value 확장 표.

    회사 자료가 아니라 계약 모양만 갖춘 합성 값이다. ``credit_status="confirmed"``는
    재등록(T7)에서 제안값을 사람이 확인한 새 버전을 흉내 낸다.
    """

    credit_origin = "agent_proposal" if credit_status == "proposed" else "user_interview"
    nodes = [
        {
            "id": "company:real", "type": "company", "label": name, "concept_id": None,
            "status": "confirmed", "origin": "homepage", "value": name,
            "source_refs": _ref("/nodes/0/value", name),
        },
        {
            "id": "qual:held", "type": "qualification", "label": "보유 자격",
            "concept_id": "qual.synthetic", "status": "confirmed", "origin": "user_interview",
            "value": {"held": True, "detail": None, "valid_until": None, "issued_on": None, "file_name": None},
            "source_refs": _ref("/nodes/1/value/held", "true"),
        },
        {
            "id": "qual:held.detail", "type": "qualification", "label": "보유 자격 세부",
            "concept_id": "qual.synthetic", "status": "unknown", "origin": "user_interview",
            "value": None, "source_refs": [],
        },
        {
            "id": "qual:credit", "type": "qualification", "label": "신용등급",
            "concept_id": "qual.synthetic", "status": credit_status, "origin": credit_origin,
            "value": {"held": True, "detail": "BBB-", "valid_until": "2027-06-30", "issued_on": None,
                      "file_name": "credit.pdf"},
            "source_refs": _ref("/nodes/3/value/detail", "BBB-"),
        },
        {
            "id": "staff:onsite", "type": "staff_group", "label": "상주 인력",
            "concept_id": None, "status": "confirmed", "origin": "user_interview",
            "value": {"role": "onsite", "total": None, "available": 6, "as_of": None,
                      "region": "대구", "grade": None},
            "source_refs": _ref("/nodes/4/value/region", "대구"),
        },
        {
            "id": "project:2024-01", "type": "project", "label": "검사 사업",
            "concept_id": None, "status": "confirmed", "origin": "homepage",
            "value": {"role": None, "scope": None, "amount_krw": None, "started_on": None,
                      "ended_on": None, "agency": "검사기관", "year": 2024},
            "source_refs": _ref("/nodes/5/value/agency", "검사기관"),
        },
        {
            "id": "pref:domain:01", "type": "domain", "label": "선호 분야",
            "concept_id": "domain.public", "status": "confirmed", "origin": "user_interview",
            "value": {"tier": 1, "keywords": ["공공"], "excluded": False, "kind": None},
            "source_refs": _ref("/nodes/6/value/keywords/0", "공공"),
        },
        {
            "id": "excl:hardware", "type": "domain", "label": "하드웨어 제외",
            "concept_id": "domain.public", "status": "confirmed", "origin": "user_interview",
            "value": {"tier": None, "keywords": ["하드웨어"], "excluded": True, "kind": "hardware"},
            "source_refs": _ref("/nodes/7/value/kind", "hardware"),
        },
        {
            "id": "pref:amount_floor", "type": "capability", "label": "최소 금액",
            "concept_id": "cap.delivery", "status": "confirmed", "origin": "user_interview",
            "value": {"scope": "core", "description": "최소 사업 금액", "params": {"krw": 100000000}},
            "source_refs": _ref("/nodes/8/value/params/krw", "100000000"),
        },
        {
            "id": "cap:brochure", "type": "capability", "label": "소개서 역량",
            "concept_id": "cap.delivery", "status": "confirmed", "origin": "company_brochure",
            "value": {"scope": "core", "description": "회사소개서 역량"},
            "source_refs": _ref("/nodes/9/value/description", "회사소개서 역량"),
        },
        {
            "id": "ev:project", "type": "evidence", "label": "실적 근거",
            "concept_id": None, "status": "confirmed", "origin": "homepage",
            "value": {"fact_key": "project:2024-01"},
            "source_refs": _ref("/nodes/5/value/agency", "검사기관"),
        },
    ]
    edges = [
        {
            "id": "edge:performed", "type": "performed", "from_id": "company:real",
            "to_id": "project:2024-01", "status": "confirmed", "origin": "homepage",
            "source_refs": _ref("/nodes/5/value/agency", "검사기관"),
        },
        {
            "id": "edge:holds", "type": "holds_qualification", "from_id": "company:real",
            "to_id": "qual:held", "status": "confirmed", "origin": "user_interview",
            "source_refs": _ref("/nodes/1/value/held", "true"),
        },
        {
            "id": "edge:project-evidence", "type": "supported_by", "from_id": "project:2024-01",
            "to_id": "ev:project", "status": "confirmed", "origin": "homepage",
            "source_refs": _ref("/nodes/5/value/agency", "검사기관"),
        },
    ]
    return {
        "schema_version": "bidops.company-knowledge-source.v1",
        "company": {"slug": slug, "name": name, "is_fictional": False},
        "scenario_version": version,
        "ontology_version": "ontology-v1",
        "ontology_sha256": ontology_sha256,
        "nodes": nodes,
        "edges": edges,
    }


#: `_real_source()`의 비evidence 노드 상태 수 (= profile facts). import 출력의
#: `status_counts`와 workload `company_attention`(proposed+unknown)이 이 값을 따른다.
REAL_STATUS_COUNTS = {"confirmed": 8, "proposed": 1, "inferred": 0, "unknown": 1}


def _prepared_real(**overrides):
    from app.core.company_ontology import parse_ontology

    ontology_raw = _raw(_ontology())
    ontology = parse_ontology(ontology_raw)
    return prepare_company_knowledge(ontology_raw, _raw(_real_source(ontology.sha256, **overrides)))


def _prepared(*, scenario: str = "scenario-v1", description: str = "합성 구축 역량"):
    ontology_raw = _raw(_ontology())
    from app.core.company_ontology import parse_ontology

    ontology = parse_ontology(ontology_raw)
    return prepare_company_knowledge(
        ontology_raw,
        _raw(_source(ontology.sha256, scenario=scenario, description=description)),
    )


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request):
    if request.param == "postgres":
        with migrated_engine() as bind:
            yield bind
        return
    bind = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(bind)
    try:
        yield bind
    finally:
        bind.dispose()


@pytest.fixture(autouse=True)
def fictional_import_demo(monkeypatch: pytest.MonkeyPatch):
    """RL-00: 가상회사 import·dry-run은 ``BIDOPS_DEMO_ENABLED=true``에서만 열린다.

    이 모듈의 가상 fixture 검사는 데모가 켜진 세계를 전제로 한다. demo off 거부는
    `tests/app/test_company_knowledge_cli.py`·`test_company_knowledge_api.py`가 본다.
    """

    from app.core.config import get_settings

    monkeypatch.setenv("BIDOPS_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def object_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    values: dict[tuple[str, str], tuple[bytes, assets.ObjectMetadata]] = {}
    monkeypatch.setattr(
        assets,
        "get_settings",
        lambda: SimpleNamespace(
            object_store_backend="filesystem",
            attachments_dir=tmp_path,
        ),
    )

    def store_named(namespace, key, data, **_kwargs):
        digest = hashlib.sha256(data).hexdigest()
        metadata = assets.ObjectMetadata(namespace, key, f"version-{digest}", digest, len(data))
        values[(namespace, key)] = (data, metadata)
        path = assets.asset_root(tmp_path) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path, metadata

    def read_object(namespace, key, *, version_id=None, **_kwargs):
        data, metadata = values[(namespace, key)]
        if version_id is not None and version_id != metadata.object_version_id:
            raise assets.AssetError("service_unavailable", "unavailable")
        return data, metadata

    monkeypatch.setattr(assets, "store_named", store_named)
    monkeypatch.setattr(assets, "read_object", read_object)
    return values


def _counts(session: Session) -> dict[str, int]:
    return {
        model.__tablename__: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in (
            Company, KnowledgeOntologyVersion, CompanyKnowledgeSource,
            CompanyKnowledgeVersion, CompanyKnowledgeNode, CompanyKnowledgeEdge,
            ProfileVersion, ProfileEvidence, CompanyKnowledgeBinding,
            CompanyKnowledgeBindingEvent, AuditEvent,
        )
    }


def test_t3_import_is_atomic_idempotent_and_builds_minimum_profile_v2(engine) -> None:
    prepared = _prepared()
    with Session(engine) as session:
        with session.begin():
            created = import_company_knowledge(session, prepared, actor="등록 담당자")
        with session.begin():
            replay = import_company_knowledge(session, prepared, actor="다른 담당자")
        assert replay == type(replay)(
            company_id=created.company_id,
            profile_version_id=created.profile_version_id,
            graph_version_id=created.graph_version_id,
            ontology_version="ontology-v1",
            source_sha256=prepared.source.source_sha256,
            graph_sha256=prepared.graph.sha256,
            created=False,
        )
        profile = session.get(ProfileVersion, created.profile_version_id)
        assert profile is not None
        assert profile.profile_payload["schema"] == "bidops.company-profile.v2"
        assert profile.profile_payload["graph_version_id"] == str(created.graph_version_id)
        facts = profile.profile_payload["facts"]
        assert [fact["fact_key"] for fact in facts] == sorted(
            ["company.synthetic", "cap.delivery", "qual.synthetic"]
        )
        unknown = next(fact for fact in facts if fact["fact_key"] == "qual.synthetic")
        assert unknown["value"] is None and unknown["quote"] == ""
        assert session.scalar(select(func.count()).select_from(ProfileEvidence)) == 2
        assert session.scalar(select(func.count()).select_from(CompanyKnowledgeVersion)) == 1
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "company.register")
        )
        assert audit is not None
        assert audit.claimed_name == "등록 담당자"
        assert audit.aggregate_id == str(created.company_id)


def test_t6_profile_v2_context_consumes_strict_projection_without_private_source(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The consumer validates frozen DB lineage without source-namespace access."""

    with Session(engine) as session:
        with session.begin():
            imported = import_company_knowledge(
                session, _prepared(), actor="등록 담당자"
            )
        profile = session.get(ProfileVersion, imported.profile_version_id)
        assert profile is not None
        monkeypatch.setattr(
            assets,
            "read_object",
            lambda *_args, **_kwargs: pytest.fail(
                "profile v2 consumption must not read private source bytes"
            ),
        )

        context = input_versions.profile_context(session, profile)

        assert context["profile_version_id"] == str(profile.id)
        assert context["profile_sha256"] == imported.source_sha256
        assert [fact["fact_key"] for fact in context["facts"]] == [
            "cap.delivery",
            "company.synthetic",
            "qual.synthetic",
        ]
        assert all(
            fact["origin"] == "fictional_scenario" for fact in context["facts"]
        )
        unknown = next(
            fact for fact in context["facts"] if fact["fact_key"] == "qual.synthetic"
        )
        assert unknown["status"] == "unknown"
        assert unknown["value"] is None
        assert unknown["quote"] == ""
        assert {row["fact_key"] for row in context["evidence"]} == {
            "cap.delivery",
            "company.synthetic",
        }
        public_json = json.dumps(context, ensure_ascii=False)
        assert not any(
            private_key in public_json
            for private_key in (
                "source_file",
                "source_path",
                "source_url",
                "json_pointer",
                "object_key",
                "object_version_id",
            )
        )


def test_t7_profile_v2_explicit_source_verification_pins_object_version(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        with session.begin():
            imported = import_company_knowledge(
                session, _prepared(), actor="등록 담당자"
            )
        profile = session.get(ProfileVersion, imported.profile_version_id)
        assert profile is not None
        input_versions.validate_profile_snapshot(
            session, profile, require_verified_source=True
        )

        original_read = assets.read_object

        def wrong_version(*args, **kwargs):
            raw, metadata = original_read(*args, **kwargs)
            return raw, assets.ObjectMetadata(
                metadata.namespace,
                metadata.object_key,
                "different-version",
                metadata.etag,
                metadata.size_bytes,
            )

        monkeypatch.setattr(assets, "read_object", wrong_version)
        with pytest.raises(input_versions.InputVersionError) as rejected:
            input_versions.validate_profile_snapshot(
                session, profile, require_verified_source=True
            )
        assert rejected.value.code == "service_unavailable"


@pytest.mark.parametrize(
    "tamper",
    [
        "payload_company",
        "payload_graph",
        "payload_source_hash",
        "payload_ontology",
        "payload_origin",
        "payload_source_file",
        "profile_company",
        "graph_profile",
        "graph_source_hash",
        "graph_snapshot_hash",
        "source_company",
        "source_content",
        "ontology_hash",
        "node_payload",
        "fact_projection",
        "evidence_projection",
    ],
)
def test_t6_profile_v2_consumer_rejects_inconsistent_frozen_lineage(
    engine, tamper: str
) -> None:
    prepared = _prepared()
    with Session(engine) as session:
        with session.begin():
            imported = import_company_knowledge(
                session, prepared, actor="등록 담당자"
            )
        profile = session.get(ProfileVersion, imported.profile_version_id)
        graph = session.get(CompanyKnowledgeVersion, imported.graph_version_id)
        assert profile is not None and graph is not None
        source = session.get(CompanyKnowledgeSource, graph.source_id)
        ontology = session.get(KnowledgeOntologyVersion, graph.ontology_id)
        node = session.get(
            CompanyKnowledgeNode, (graph.id, "cap.delivery")
        )
        evidence = session.scalar(
            select(ProfileEvidence).where(
                ProfileEvidence.profile_version_id == profile.id,
                ProfileEvidence.fact_key == "cap.delivery",
            )
        )
        assert source is not None and ontology is not None
        assert node is not None and evidence is not None

        payload = deepcopy(profile.profile_payload)
        if tamper == "payload_company":
            payload["company_id"] = str(uuid4())
        elif tamper == "payload_graph":
            payload["graph_version_id"] = str(uuid4())
        elif tamper == "payload_source_hash":
            payload["source_sha256"] = "f" * 64
        elif tamper == "payload_ontology":
            payload["ontology_version"] = "other-ontology"
        elif tamper == "payload_origin":
            payload["origin"] = "public_document"
        elif tamper == "payload_source_file":
            payload["source_file"] = "/private/company.json"
        elif tamper == "profile_company":
            profile.company_id = uuid4()
        elif tamper == "graph_profile":
            graph.profile_version_id = uuid4()
        elif tamper == "graph_source_hash":
            graph.source_sha256 = "f" * 64
        elif tamper == "graph_snapshot_hash":
            graph.graph_sha256 = "f" * 64
        elif tamper == "source_company":
            source.company_id = uuid4()
        elif tamper == "source_content":
            source.content_object_id = uuid4()
        elif tamper == "ontology_hash":
            ontology.sha256 = "f" * 64
        elif tamper == "node_payload":
            node.payload = {**node.payload, "label": "변조된 노드"}
        elif tamper == "fact_projection":
            payload["facts"][0] = {
                **payload["facts"][0],
                "value": "그래프에 없는 사실",
            }
        elif tamper == "evidence_projection":
            evidence.quote = "그래프에 없는 인용"
        profile.profile_payload = payload

        with session.no_autoflush, pytest.raises(
            input_versions.InputVersionError
        ) as rejected:
            input_versions.validate_profile_snapshot(session, profile)
        assert rejected.value.code == "service_unavailable"


def test_t6_profile_v2_rejects_made_up_evidence_for_unknown_fact(engine) -> None:
    with Session(engine) as session:
        with session.begin():
            imported = import_company_knowledge(
                session, _prepared(), actor="등록 담당자"
            )
            graph = session.get(
                CompanyKnowledgeVersion, imported.graph_version_id
            )
            assert graph is not None
            source = session.get(CompanyKnowledgeSource, graph.source_id)
            assert source is not None
            session.add(
                ProfileEvidence(
                    id=uuid4(),
                    profile_version_id=imported.profile_version_id,
                    fact_key="qual.synthetic",
                    content_object_id=source.content_object_id,
                    source_sha256=imported.source_sha256,
                    locator_type="profile_fact",
                    locator={"fact_key": "qual.synthetic"},
                    quote="만들어 낸 근거",
                    confirmed_by_name="검사 담당자",
                    confirmed_at=datetime.now(UTC),
                )
            )
        profile = session.get(ProfileVersion, imported.profile_version_id)
        assert profile is not None

        with pytest.raises(input_versions.InputVersionError) as rejected:
            input_versions.validate_profile_snapshot(session, profile)
        assert rejected.value.code == "service_unavailable"


def test_t7_profile_v1_consumer_keeps_fixed_source_file_contract(engine) -> None:
    with Session(engine) as session:
        profile_path = Path(__file__).parents[4] / "docs" / "reference" / "company-profile.md"
        profile = input_versions.import_profile_version(
            session, profile_path, created_by_name="검사 담당자"
        )
        input_versions.validate_profile_snapshot(
            session, profile, require_verified_source=True
        )

        payload = deepcopy(profile.profile_payload)
        payload["source_file"] = "docs/reference/another-profile.md"
        profile.profile_payload = payload
        with pytest.raises(input_versions.InputVersionError) as rejected:
            input_versions.validate_profile_snapshot(session, profile)
        assert rejected.value.code == "service_unavailable"


def test_t3_caller_rollback_removes_every_database_row(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        import_company_knowledge(session, _prepared(), actor="등록 담당자")
        session.rollback()
    with Session(engine) as session:
        assert all(count == 0 for count in _counts(session).values())
    assert list((assets.asset_root(tmp_path) / "source").glob("*")) == []


def test_t3_rollback_cleans_only_the_current_request_object(
    engine, tmp_path: Path
) -> None:
    with Session(engine) as session:
        with session.begin():
            import_company_knowledge(session, _prepared(), actor="등록 담당자")
    source_root = assets.asset_root(tmp_path) / "source"
    committed = set(source_root.glob("*"))
    assert len(committed) == 1

    with Session(engine) as session:
        import_company_knowledge(
            session,
            _prepared(scenario="scenario-v2", description="롤백할 합성 역량"),
            actor="등록 담당자",
        )
        created = set(source_root.glob("*")) - committed
        assert len(created) == 1
        session.rollback()

    assert set(source_root.glob("*")) == committed


def test_t3_nested_rollback_cleans_before_the_outer_transaction_commits(
    engine, tmp_path: Path
) -> None:
    with Session(engine) as session:
        with session.begin():
            import_company_knowledge(session, _prepared(), actor="등록 담당자")
    source_root = assets.asset_root(tmp_path) / "source"
    committed = set(source_root.glob("*"))

    with Session(engine) as session:
        with session.begin():
            with pytest.raises(RuntimeError, match="rollback nested import"):
                with session.begin_nested():
                    import_company_knowledge(
                        session,
                        _prepared(
                            scenario="scenario-v2",
                            description="savepoint rollback 합성 역량",
                        ),
                        actor="등록 담당자",
                    )
                    assert len(set(source_root.glob("*")) - committed) == 1
                    raise RuntimeError("rollback nested import")
            assert set(source_root.glob("*")) == committed

    assert set(source_root.glob("*")) == committed


def test_t3_import_revalidates_prepared_nested_values_before_any_write(engine) -> None:
    prepared = _prepared()
    capability = next(node for node in prepared.source.nodes if node.id == "cap.delivery")
    capability.value["description"] = "검증 뒤 변조"
    with Session(engine) as session:
        with pytest.raises(CompanyKnowledgeServiceError, match="source_invalid"):
            import_company_knowledge(session, prepared, actor="등록 담당자")
        session.rollback()
    with Session(engine) as session:
        assert all(count == 0 for count in _counts(session).values())


def test_t3_replay_verifies_the_exact_stored_object_version(
    engine, object_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepared()
    with Session(engine) as session:
        with session.begin():
            import_company_knowledge(session, prepared, actor="등록 담당자")

    original = assets.read_object

    def wrong_version(*args, **kwargs):
        data, metadata = original(*args, **kwargs)
        return data, assets.ObjectMetadata(
            metadata.namespace, metadata.object_key, "different-version",
            metadata.etag, metadata.size_bytes,
        )

    monkeypatch.setattr(assets, "read_object", wrong_version)
    with Session(engine) as session:
        with pytest.raises(CompanyKnowledgeServiceError, match="storage_failed"):
            import_company_knowledge(session, prepared, actor="등록 담당자")
        session.rollback()


def test_t4_activation_is_idempotent_and_preserves_previous_graph(engine) -> None:
    with Session(engine) as session:
        with session.begin():
            first = import_company_knowledge(session, _prepared(), actor="등록 담당자")
        with session.begin():
            active = activate_company_knowledge(
                session, company_id=first.company_id,
                graph_version_id=first.graph_version_id, actor="활성 담당자",
            )
        with session.begin():
            replay = activate_company_knowledge(
                session, company_id=first.company_id,
                graph_version_id=first.graph_version_id, actor="다른 담당자",
            )
        assert active.revision == replay.revision == 1
        assert active.changed is True and replay.changed is False

        with session.begin():
            second = import_company_knowledge(
                session,
                _prepared(scenario="scenario-v2", description="변경된 합성 역량"),
                actor="등록 담당자",
            )
        with session.begin():
            replacement = activate_company_knowledge(
                session, company_id=first.company_id,
                graph_version_id=second.graph_version_id, actor="활성 담당자",
            )
        assert replacement.revision == 2
        events = list(session.scalars(
            select(CompanyKnowledgeBindingEvent).order_by(CompanyKnowledgeBindingEvent.revision)
        ))
        assert [event.revision for event in events] == [1, 2]
        assert events[0].previous_graph_version_id is None
        assert events[1].previous_graph_version_id == first.graph_version_id
        assert [event.actor for event in events] == ["활성 담당자", "활성 담당자"]
        assert session.get(CompanyKnowledgeVersion, first.graph_version_id) is not None


def test_t4_rejects_cross_company_activation_without_mutating_binding(engine) -> None:
    first = _prepared()
    second_source = deepcopy(_source(first.ontology.sha256))
    second_source["company"] = {"slug": "second-si", "name": "두번째 SI", "is_fictional": True}
    second_source["nodes"][0]["label"] = "두번째 SI"
    second = prepare_company_knowledge(_raw(_ontology()), _raw(second_source))
    with Session(engine) as session:
        with session.begin():
            first_row = import_company_knowledge(session, first, actor="등록 담당자")
            second_row = import_company_knowledge(session, second, actor="등록 담당자")
        with pytest.raises(CompanyKnowledgeServiceError, match="graph_company_mismatch"):
            activate_company_knowledge(
                session, company_id=first_row.company_id,
                graph_version_id=second_row.graph_version_id, actor="활성 담당자",
            )
        session.rollback()
        assert session.get(CompanyKnowledgeBinding, first_row.company_id) is None


def test_t7_append_only_orm_rows_reject_updates_and_deletes(engine) -> None:
    with Session(engine) as session:
        with session.begin():
            imported = import_company_knowledge(session, _prepared(), actor="등록 담당자")
        graph = session.get(CompanyKnowledgeVersion, imported.graph_version_id)
        assert graph is not None
        graph.graph_sha256 = "f" * 64
        with pytest.raises(ValueError, match="append-only"):
            session.flush()
        session.rollback()


@requires_postgres
def test_t7_postgres_enforces_append_only_and_composite_company_scopes() -> None:
    first = _prepared()
    second_source = deepcopy(_source(first.ontology.sha256))
    second_source["company"] = {
        "slug": "second-si",
        "name": "두번째 SI",
        "is_fictional": True,
    }
    second_source["nodes"][0]["label"] = "두번째 SI"
    second = prepare_company_knowledge(_raw(_ontology()), _raw(second_source))

    with migrated_engine() as bind, Session(bind, expire_on_commit=False) as session:
        with session.begin():
            first_row = import_company_knowledge(session, first, actor="등록 담당자")
            second_row = import_company_knowledge(session, second, actor="등록 담당자")
        with session.begin():
            first_source = session.scalar(
                select(CompanyKnowledgeSource).where(
                    CompanyKnowledgeSource.company_id == first_row.company_id
                )
            )
            second_source_row = session.scalar(
                select(CompanyKnowledgeSource).where(
                    CompanyKnowledgeSource.company_id == second_row.company_id
                )
            )
        assert first_source is not None and second_source_row is not None

        with pytest.raises(DBAPIError):
            with session.begin():
                session.execute(
                    text(
                        "UPDATE bidops.company_knowledge_version "
                        "SET graph_sha256 = graph_sha256 WHERE id = :id"
                    ),
                    {"id": first_row.graph_version_id},
                )

        with pytest.raises(DBAPIError):
            with session.begin():
                session.execute(
                    text(
                        "INSERT INTO bidops.company_knowledge_source "
                        "(id, company_id, source_sha256, size_bytes, content_object_id, "
                        "content_location_id, created_at) VALUES "
                        "(:id, :company_id, :sha256, 1, :content_object_id, "
                        ":content_location_id, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": uuid4(),
                        "company_id": first_row.company_id,
                        "sha256": "f" * 64,
                        "content_object_id": first_source.content_object_id,
                        "content_location_id": second_source_row.content_location_id,
                    },
                )

        with pytest.raises(DBAPIError):
            with session.begin():
                session.execute(
                    text(
                        "INSERT INTO bidops.company_knowledge_binding_event "
                        "(id, company_id, revision, graph_version_id, profile_version_id, "
                        "previous_graph_version_id, actor, created_at) VALUES "
                        "(:id, :company_id, 99, :graph_id, :profile_id, "
                        ":previous_graph_id, '검사 담당자', CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": uuid4(),
                        "company_id": first_row.company_id,
                        "graph_id": first_row.graph_version_id,
                        "profile_id": first_row.profile_version_id,
                        "previous_graph_id": second_row.graph_version_id,
                    },
                )


@pytest.mark.parametrize("failure", ["store_raises", "read_back_differs"])
def test_t3_first_import_storage_failure_leaves_no_rows_or_binding(
    engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    if failure == "store_raises":
        def store_named(*_args, **_kwargs):
            raise assets.AssetError("service_unavailable", "unavailable")

        monkeypatch.setattr(assets, "store_named", store_named)
    else:
        original = assets.read_object

        def read_object(*args, **kwargs):
            data, metadata = original(*args, **kwargs)
            return data + b" ", metadata

        monkeypatch.setattr(assets, "read_object", read_object)

    with Session(engine) as session:
        with pytest.raises(CompanyKnowledgeServiceError, match="storage_failed"):
            with session.begin():
                import_company_knowledge(session, _prepared(), actor="등록 담당자")
    with Session(engine) as session:
        assert _counts(session) == {name: 0 for name in _counts(session)}
    assert list((assets.asset_root(tmp_path) / "source").glob("*")) == []


def test_n2_ontology_version_is_bounded_by_its_database_column(engine) -> None:
    from app.core.company_ontology import MAX_ONTOLOGY_VERSION_LENGTH, parse_ontology

    assert KnowledgeOntologyVersion.__table__.c.version.type.length == MAX_ONTOLOGY_VERSION_LENGTH

    def prepared_for(version: str):
        ontology = _ontology()
        ontology["version"] = version
        ontology_raw = _raw(ontology)
        try:
            ontology_sha = parse_ontology(ontology_raw).sha256
        except Exception:
            ontology_sha = "0" * 64
        source = _source(ontology_sha)
        source["ontology_version"] = version
        return prepare_company_knowledge(ontology_raw, _raw(source))

    with pytest.raises(CompanyKnowledgeServiceError, match="ontology_invalid"):
        prepared_for("v" * (MAX_ONTOLOGY_VERSION_LENGTH + 1))

    longest = prepared_for("가" * MAX_ONTOLOGY_VERSION_LENGTH)
    with Session(engine) as session:
        with session.begin():
            imported = import_company_knowledge(session, longest, actor="등록 담당자")
        assert imported.created is True
        row = session.scalar(select(KnowledgeOntologyVersion))
        assert row is not None and row.version == "가" * MAX_ONTOLOGY_VERSION_LENGTH
