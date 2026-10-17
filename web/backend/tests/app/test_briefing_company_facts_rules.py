"""RL-01 브리핑 규칙이 실제 회사 그래프 projection을 읽는 통합 검사 (deep_review → lifecycle).

그래프는 RL-00 검사와 같은 합성 실회사 파일을 실제 import·activate 경로로 만든다.
제공자(deep_review)가 넘긴 확정 사실만 lifecycle 규칙 엔진에 닿고, `proposed`
신용등급·`unknown` 세부 노드는 어떤 점수에도 쓰이지 않는다(T2의 실제 그래프 판).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.deep_review import register_lifecycle_extensions
from app.deep_review.services.company_knowledge import (
    activate_company_knowledge,
    import_company_knowledge,
)
from app.lifecycle import ExtensionRegistry
from app.lifecycle.services.briefing_policy import load_briefing_policy
from app.lifecycle.services.briefing_rules import (
    build_recommendations,
    company_rules,
    notice_candidate,
)
from tests.deep_review.test_company_knowledge import (  # noqa: F401 - shared fixtures
    _prepared_real,
    engine,
    fictional_import_demo,
    object_store,
)

NOW = datetime(2026, 10, 16, 22, 30, tzinfo=UTC)


def _notice(notice_id: int, title: str, *, agency: str, price: int | None):
    return notice_candidate(
        SimpleNamespace(
            id=notice_id, title=title, agency=agency, demand_agency=None,
            estimated_price=None if price is None else Decimal(price), budget=None,
            region_limit_json=None, deadline_at=NOW + timedelta(days=20),
            qualification_flags_json={"sw_business_status": "Y"},
        ),
        stage="pre_spec",
        first_observed_at=NOW - timedelta(hours=8),
    )


def test_rules_read_the_confirmed_facts_of_the_active_real_graph(engine) -> None:
    registry = register_lifecycle_extensions(ExtensionRegistry())
    with Session(engine) as session:
        with session.begin():
            imported = import_company_knowledge(session, _prepared_real(), actor="등록 담당자")
            activate_company_knowledge(
                session,
                company_id=imported.company_id,
                graph_version_id=imported.graph_version_id,
                actor="활성 담당자",
            )
        projection = registry.company_facts_projection(session)

    rules = company_rules(projection)
    assert rules.graph_version_id == imported.graph_version_id
    assert [(domain.fact_key, domain.tier) for domain in rules.domains] == [("pref:domain:01", 1)]
    assert [keyword.text for keyword in rules.exclusion_keywords["hardware"]] == ["하드웨어"]
    assert rules.allowed_regions is None  # 합성 그래프에는 excl:region이 없다
    assert rules.amount_floor_krw == 100_000_000
    assert [project.fact_key for project in rules.projects] == ["project:2024-01"]

    result = build_recommendations(
        [
            _notice(1, "공공 플랫폼 운영", agency="합성구청", price=200_000_000),
            _notice(2, "공공 장비 하드웨어 납품", agency="합성구청", price=200_000_000),
            _notice(3, "공공 홈페이지 소규모", agency="합성구청", price=50_000_000),
        ],
        rules,
        load_briefing_policy(),
        now=NOW,
    )
    assert [(item.candidate.notice_id, item.score) for item in result.items] == [(1, 40)]
    assert result.items[0].reasons == ({"kind": "keyword", "text": "공공"},)
    assert result.excluded_counts["hardware"] == 1
    assert result.excluded_counts["amount_floor"] == 1
