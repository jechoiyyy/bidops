"""Read-only HTTP contract against an invented company and a temporary wiki."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import yaml

from app.core.config import get_settings
from app.deep_review import company_wiki_router
from app.deep_review.services.engine_runs import company_bundle


BASE = "/api/company-wiki"
BODY = (
    "\n## 개요\n- 설명\n### 요구사항 전체 목록(원문)\n- R1\n- R2\n"
    "### 다른 절\n- 포함하지 않음\n"
)


@pytest.fixture
def wiki(tmp_path, monkeypatch):
    monkeypatch.setenv("BIDOPS_ENGINE_COMPANY_BUNDLE_DIR", str(tmp_path))
    monkeypatch.setenv("BIDOPS_ENGINE_COMPANY_BUNDLE_SLUG", "sample")
    get_settings.cache_clear()
    root = tmp_path / "sample"
    root.mkdir()
    profile = {
        "company": {"name": "예시", "regions": ["가", "나"], "blank": None},
        "registrations": {
            "direct_production": [{"item_no": "001", "status": "unknown"}]
        },
        "people": {"by_year": {2025: 2}},
        "portfolio_file": "sample.portfolio.yaml",
        "provenance_file": "sample.provenance.yaml",
    }
    records = [
        {
            "id": "P1",
            "title": "가상 실적",
            "client": "가상 기관",
            "role": "unknown",
            "type": "구축",
            "amount_krw": 987654321,
            "period": {"start": "unknown"},
        },
        {"id": "P2"},
    ]
    levels = {"registrations.direct_production[001].status": {"level": "demo"}}
    for filename, data in [
        ("sample.yaml", profile),
        ("sample.portfolio.yaml", records),
        ("sample.provenance.yaml", {"fields": levels}),
    ]:
        (tmp_path / filename).write_text(yaml.safe_dump(data, allow_unicode=True))
    for kind, folder, slug in [
        ("portfolio", "portfolio", "P1"),
        ("category", "categories", "group"),
        ("capability", "capabilities", "skill"),
        ("rule", "rules", "one"),
        ("glossary", "", "glossary"),
    ]:
        (root / folder).mkdir(exist_ok=True)
        (root / folder / f"{slug}.md").write_text(
            f"---\nkind: {kind}\nslug: {slug}\ntitle: 문서 {slug}\nupdated: 2026-01-02\n"
            f"confidence: demo\nsources: [참조, '{tmp_path}/private']\n---\n" + BODY
        )
    for name in ["INDEX.md", "SCHEMA.md"]:
        (root / name).write_text("별도 색인")
    sidecar = {
        "schema": "bidops.wiki-work-units.v1",
        "topics": [
            {
                "id": "t",
                "title": "주제",
                "scope": "범위",
                "units": [
                    {"id": "t.a", "title": "가", "covers": "포함", "not": "제외"},
                    {"id": "t.b", "title": "나"},
                ],
            }
        ],
        "sources": {"P1": {"ingested_at": "2026-01-02"}},
        "evidence": [
            {"unit": "t.a", "project": "P1", "req_id": r} for r in ("R1", "R2")
        ],
        "no_record": [
            {"unit": "t.b", "note": "확인", "as_of": "2026-01-03", "source": "면담"}
        ],
    }
    (root / "work-units.json").write_text(json.dumps(sidecar))
    (root / "log.txt").write_text(
        "".join(f"2026-01-{i:02} | 추가 | {i}\n" for i in range(1, 23))
    )
    app = FastAPI()
    app.include_router(company_wiki_router)
    try:
        with TestClient(app) as client:
            yield client, root
    finally:
        get_settings.cache_clear()


def error(response, status, code):
    assert response.status_code == status
    detail = response.json()["error"]
    assert detail == {
        "code": code,
        "message": "회사 위키를 조회할 수 없습니다",
        "details": None,
    }


def test_six_views_share_engine_digest_and_only_public_fields(wiki):
    client, root = wiki
    digest = company_bundle()["bundle_sha256"]

    def get(suffix):
        r = client.get(BASE + suffix)
        assert r.status_code == 200, r.text
        assert r.json()["bundle_sha256"] == digest
        for private in ("amount_krw", "987654321", str(root.parent)):
            assert private not in r.text
        return r.json()

    summary = get("")
    assert (
        summary["slug"],
        summary["company_name"],
        summary["work_units_available"],
    ) == ("sample", "예시", True)
    assert summary["counts"] == {
        "pages_by_kind": dict.fromkeys(
            ("category", "capability", "portfolio", "rule", "glossary"), 1
        ),
        "portfolio_items": 2,
        "portfolio_pages": 1,
        "ingested_projects": 1,
        "work_topics": 1,
        "work_units": 2,
        "evidence_links": 2,
        "units_without_evidence": 1,
    }
    assert summary["log"] == [
        {"date": f"2026-01-{i:02}", "text": f"추가 | {i}"} for i in range(22, 2, -1)
    ]
    facts = {
        f["path"]: (f["section"], f["value"], f["level"])
        for f in get("/profile")["facts"]
    }
    assert facts == {
        "people.by_year.2025": ("people", "2", None),
        "company.blank": ("company", None, None),
        "company.name": ("company", "예시", None),
        "company.regions": ("company", "가, 나", None),
        "registrations.direct_production[001].item_no": ("registrations", "001", None),
        "registrations.direct_production[001].status": (
            "registrations",
            "unknown",
            "demo",
        ),
    }
    first, second = get("/portfolio")["items"]
    assert first == {
        "id": "P1",
        "title": "가상 실적",
        "client": "가상 기관",
        "type": "구축",
        "role": "unknown",
        "period_start": "unknown",
        "period_end": None,
        "has_page": True,
        "requirement_count": 2,
        "ingested": True,
        "ingested_at": "2026-01-02",
        "evidence_links": 2,
    }
    assert (
        second["has_page"],
        second["requirement_count"],
        second["ingested"],
        second["evidence_links"],
    ) == (False, None, False, 0)
    (topic,) = get("/work-units")["topics"]
    assert (topic["id"], topic["title"], topic["scope"]) == ("t", "주제", "범위")
    a, b = topic["units"]
    assert a == {
        "id": "t.a",
        "title": "가",
        "covers": "포함",
        "not": "제외",
        "projects": [{"project": "P1", "req_ids": ["R1", "R2"]}],
        "no_record": [],
    }
    assert b["projects"] == [] and b["no_record"] == [
        {"note": "확인", "as_of": "2026-01-03", "source": "면담"}
    ]
    pages = get("/pages")["pages"]
    assert len(pages) == 5
    for p in pages:
        assert p["chars"] == len(BODY)
        detail = get(f"/pages/{p['kind']}/{p['slug']}")
        assert detail == {
            **{k: v for k, v in p.items() if k != "chars"},
            "bundle_sha256": digest,
            "sources": ["참조"],
            "body": BODY,
        }
        assert detail["title"] == "문서 " + p["slug"]
        assert (detail["confidence"], detail["updated"]) == ("demo", "2026-01-02")


def test_absent_side_files_and_empty_map_are_distinct(wiki):
    client, root = wiki
    (root / "log.txt").unlink()
    path = root / "work-units.json"
    path.unlink()
    summary = client.get(BASE).json()
    assert summary["log"] == [] and summary["work_units_available"] is False
    for key in (
        "ingested_projects",
        "work_topics",
        "work_units",
        "evidence_links",
        "units_without_evidence",
    ):
        assert summary["counts"][key] is None
    error(client.get(BASE + "/work-units"), 404, "company_wiki_work_units_unavailable")
    assert client.get(BASE + "/portfolio").json()["items"][0]["ingested"] is None
    path.write_text(
        json.dumps(
            {
                "schema": "bidops.wiki-work-units.v1",
                "topics": [],
                "evidence": [],
                "sources": {},
            }
        )
    )
    again = client.get(BASE).json()
    assert again["work_units_available"] and again["counts"]["work_units"] == 0
    assert again["bundle_sha256"] == summary["bundle_sha256"]


@pytest.mark.parametrize("setting", ["DIR", "SLUG"])
def test_unconfigured(wiki, monkeypatch, setting):
    client, _ = wiki
    monkeypatch.setenv("BIDOPS_ENGINE_COMPANY_BUNDLE_" + setting, "")
    get_settings.cache_clear()
    error(client.get(BASE), 404, "company_wiki_unavailable")


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("../sample.yaml", "[broken"),
        ("work-units.json", "{"),
        ("work-units.json", '{"schema": "unexpected"}'),
    ],
)
def test_broken_input(wiki, name, data):
    client, root = wiki
    (root / name).write_text(data)
    error(client.get(BASE), 503, "company_wiki_unreadable")


def test_page_boundaries(wiki):
    client, root = wiki
    outside = root.parent / "secret.md"
    outside.write_bytes(b"\xff")
    (root / "rules/link.md").symlink_to(outside)
    deep = root / "rules/nested"
    deep.mkdir()
    (deep / "private.md").write_bytes(b"\xff")
    for path in [
        "invalid/one",
        "rule/a..b",
        "rule/link",
        "rule/nested/private",
        "rule/private",
    ]:
        error(client.get(BASE + "/pages/" + path), 404, "company_wiki_page_not_found")
    assert client.get(BASE + "/pages").status_code == 200


def test_rereads_pages_and_withholds_private_prose(wiki):
    client, root = wiki
    initial = client.get(BASE).json()["bundle_sha256"]
    page = root / "portfolio/P1.md"
    page.write_text(
        page.read_text().split("### 요구사항")[0]
        + f"원본: {root}/private file\n금액 987,654,321원\n"
    )
    detail = client.get(BASE + "/pages/portfolio/P1").json()
    assert detail["bundle_sha256"] != initial
    assert str(root) not in detail["body"] and "987,654,321" not in detail["body"]
    assert (
        client.get(BASE + "/portfolio").json()["items"][0]["requirement_count"] is None
    )
