"""deep_review가 제공하는 lifecycle 확장점 `company_facts_projection` (RL-01 spec).

실회사 활성 binding의 비evidence 노드 중 `status=confirmed`만 넘긴다. 그래프는
RL-00 검사와 같은 합성 실회사 파일(`_real_source`)을 실제 import·activate 경로로
만든다 — 확정 8·제안 1·미확인 1·evidence 1 노드다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.deep_review import register_lifecycle_extensions
from app.deep_review.services.company_knowledge import (
    activate_company_knowledge,
    company_facts_projection,
    import_company_knowledge,
)
from app.lifecycle import CompanyFactsProjection, ExtensionRegistry
from tests.deep_review.test_company_knowledge import (  # noqa: F401 - shared fixtures
    REAL_STATUS_COUNTS,
    _prepared,
    _prepared_real,
    _real_source,
    engine,
    fictional_import_demo,
    object_store,
)

CONFIRMED_NON_EVIDENCE = [
    "cap:brochure",
    "company:real",
    "excl:hardware",
    "pref:amount_floor",
    "pref:domain:01",
    "project:2024-01",
    "qual:held",
    "staff:onsite",
]


def _import(session: Session, prepared, *, activate: bool):
    # 앞선 읽기가 연 암묵 transaction을 닫는다(읽기 전용이라 되돌릴 쓰기가 없다).
    session.rollback()
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


def test_projection_carries_only_confirmed_non_evidence_facts_of_the_active_graph(engine) -> None:
    assert REAL_STATUS_COUNTS["confirmed"] == len(CONFIRMED_NON_EVIDENCE)
    with Session(engine) as session:
        imported = _import(session, _prepared_real(), activate=True)
        projection = company_facts_projection(session)

    assert isinstance(projection, CompanyFactsProjection)
    assert projection.graph_version_id == imported.graph_version_id
    assert [fact.fact_key for fact in projection.facts] == CONFIRMED_NON_EVIDENCE
    assert {fact.status for fact in projection.facts} == {"confirmed"}
    keys = {fact.fact_key for fact in projection.facts}
    # proposed(신용등급)·unknown(세부)·evidence 노드는 넘기지 않는다.
    assert not keys & {"qual:credit", "qual:held.detail", "ev:project"}
    facts = {fact.fact_key: fact for fact in projection.facts}
    assert facts["pref:domain:01"].type == "domain"
    assert facts["pref:domain:01"].value == {
        "tier": 1, "keywords": ["공공"], "excluded": False, "kind": None,
    }
    assert facts["project:2024-01"].label == "검사 사업"
    assert facts["pref:amount_floor"].value["params"] == {"krw": 100000000}


def test_projection_is_none_without_a_real_company_or_an_active_graph(engine) -> None:
    with Session(engine) as session:
        assert company_facts_projection(session) is None
        # 가상회사만 있으면 실회사가 아니다.
        _import(session, _prepared(), activate=True)
        assert company_facts_projection(session) is None
        # 실회사가 등록됐어도 활성 binding이 없으면 읽을 그래프가 없다.
        _import(session, _prepared_real(), activate=False)
        assert company_facts_projection(session) is None


def test_projection_follows_the_newly_activated_graph(engine) -> None:
    with Session(engine) as session:
        first = _import(session, _prepared_real(), activate=True)
        second = _import(
            session,
            _prepared_real(credit_status="confirmed", version="real-test-2026-10-17"),
            activate=True,
        )
        projection = company_facts_projection(session)
    assert first.graph_version_id != second.graph_version_id
    assert projection.graph_version_id == second.graph_version_id
    assert "qual:credit" in {fact.fact_key for fact in projection.facts}


def test_deep_review_registers_the_company_facts_provider(engine) -> None:
    registry = register_lifecycle_extensions(ExtensionRegistry())
    register_lifecycle_extensions(registry)  # 같은 owner 재등록은 제자리 교체다.
    with Session(engine) as session:
        assert registry.company_facts_projection(session) is None
        imported = _import(session, _prepared_real(), activate=True)
        projection = registry.company_facts_projection(session)
    assert projection.graph_version_id == imported.graph_version_id
