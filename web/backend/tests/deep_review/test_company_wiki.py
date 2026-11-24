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
            "id": "P2025-01",
            "title": "가상 실적",
            "client": "가상 기관",
            "role": "unknown",
            "type": "구축",
            "amount_krw": 987654321,
            "period": {"start": "unknown"},
        },
        {"id": "P2024-02"},
    ]
    levels = {"registrations.direct_production[001].status": {"level": "demo"}}
    for filename, data in [
        ("sample.yaml", profile),
        ("sample.portfolio.yaml", records),
        ("sample.provenance.yaml", {"fields": levels}),
    ]:
        (tmp_path / filename).write_text(yaml.safe_dump(data, allow_unicode=True))
    for kind, folder, slug in [
        ("portfolio", "portfolio", "P2025-01"),
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
        "sources": {"P2025-01": {"ingested_at": "2026-01-02"}},
        "evidence": [
            {"unit": "t.a", "project": "P2025-01", "req_id": r} for r in ("R1", "R2")
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


def test_views_share_engine_digest_and_only_public_fields(wiki):
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
    assert [(row["date"], row["text"], row["kind"]) for row in summary["log"]] == [
        (f"2026-01-{i:02}", f"추가 | {i}", "other") for i in range(22, 2, -1)
    ]
    facts = {
        f["path"]: (section["key"], f["value"], f["level"])
        for section in get("/profile")["sections"] for f in section["facts"]
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
        "id": "P2025-01",
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
    assert topic == dict(id="t", title="주제", scope="범위", unit_count=2, units_without_evidence=1, project_count=1)
    a, b = get("/work-units/t")["units"]
    assert a == {
        "id": "t.a",
        "title": "가",
        "covers": "포함",
        "not": "제외",
        "project_count": 1, "latest_year": 2025,
        "projects": [dict(project="P2025-01", title="가상 실적", client="가상 기관",
                          period_start="unknown", period_end=None, year=2025,
                          requirements=[dict(req_id=r, name=None) for r in ("R1", "R2")])],
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
    assert [(row["date"], row["text"], row["kind"]) for row in summary["log"]] == [] and summary["work_units_available"] is False
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
    page = root / "portfolio/P2025-01.md"
    page.write_text(
        page.read_text().split("### 요구사항")[0]
        + f"원본: {root}/private file\n금액 987,654,321원\n"
    )
    detail = client.get(BASE + "/pages/portfolio/P2025-01").json()
    assert detail["bundle_sha256"] != initial
    assert str(root) not in detail["body"] and "987,654,321" not in detail["body"]
    assert (
        client.get(BASE + "/portfolio").json()["items"][0]["requirement_count"] is None
    )


def test_profile_labels(wiki):
    client, root = wiki
    path = root.parent / "sample.yaml"
    profile = yaml.safe_load(path.read_text())
    profile["company"].update({
        "cash": {"2020": 500000000, "2021": 3769270000, "2022": 30000000},
        "people": 35, "share": 15, "count": 9, "empty": [], "allowed": True,
    })
    profile["registrations"]["direct_production"][0]["name"] = "시험 품목"
    path.write_text(yaml.safe_dump(profile))
    digest = client.get(BASE).json()["bundle_sha256"]
    labels = {
        "schema": "bidops.wiki-labels.v1", "sections": {"company": "회사"},
        "hidden": ["registrations.direct_production[].name"],
        "fields": {
            "company.cash.*": {"label": "{key}년", "unit": "krw"},
            "company.cash.2020": {"label": "설립 자본", "unit": "krw"},
            "company.people": {"label": "인원", "unit": "people"},
            "company.share": {"label": "비중", "unit": "percent"},
            "company.count": {"label": "등록", "unit": "count"},
            "company.allowed": {"label": "가능 여부", "values": {"true": "가능"}},
            "registrations.direct_production[].status": {"label": "{item} 상태", "values": {"unknown": "대체"}},
        },
    }
    labels["fields"]["registrations.direct_production[].item_no"] = {"label": "{item} 번호"}
    (root / "labels.yaml").write_text(yaml.safe_dump(labels, sort_keys=False))
    summary = client.get(BASE).json()
    assert summary["bundle_sha256"] == digest and summary["labels_available"]
    sections = client.get(BASE + "/profile").json()["sections"]
    assert {row["key"]: row["label"] for row in sections} == dict(company="회사", registrations=None, people=None)
    facts = {f["path"]: (f["label"], f["display_value"]) for s in sections for f in s["facts"]}
    assert facts["company.cash.2020"] == ("설립 자본", "5억 원")
    assert facts["company.cash.2021"] == ("2021년", "37억 6,927만 원")
    assert facts["company.cash.2022"] == ("2022년", "3,000만 원")
    assert facts["company.people"] == ("인원", "35명")
    assert facts["company.share"] == ("비중", "15%")
    assert facts["company.count"] == ("등록", "9건")
    assert facts["company.allowed"] == ("가능 여부", "가능")
    assert facts["company.empty"] == (None, "")
    assert facts["company.blank"] == (None, None)
    assert facts["registrations.direct_production[001].status"] == ("시험 품목 상태", "unknown")
    assert "registrations.direct_production[001].name" not in facts
    profile["registrations"]["direct_production"] = [
        {"id": "s", "std": "표준", "title": "후순위", "item_no": "가"},
        {"title": "제목", "item_no": "나"}, {"item_no": "다"},
    ]
    path.write_text(yaml.safe_dump(profile))
    sections = client.get(BASE + "/profile").json()["sections"]
    labels = [f["label"] for s in sections for f in s["facts"] if f["path"].endswith(".item_no")]
    assert labels == ["표준 번호", "제목 번호", "다 번호"]


@pytest.mark.parametrize("contents", [None, "[", "schema: wrong", "schema: bidops.wiki-labels.v1\nfields: []"])
def test_optional_labels(wiki, contents):
    client, root = wiki
    if contents is not None:
        (root / "labels.yaml").write_text(contents)
    assert client.get(BASE).json()["labels_available"] is False
    result = client.get(BASE + "/profile")
    assert result.status_code == 200
    assert all(s["label"] is None and all(f["label"] is None and f["value"] == f["display_value"]
               for f in s["facts"]) for s in result.json()["sections"])


def test_log_and_last_changed(wiki):
    client, root = wiki
    log = root / "log.txt"
    log.write_text("2026-02-03 | ingest | P2025-01 | 요구사항 70건, 미분류 10건\n"
                   "2026-01-02 | feedback | 검토\n2026-01-02 | init | 분류\n알 수 없는 기록")
    summary = client.get(BASE).json()
    assert summary["last_changed"] == "2026-02-03"
    other, init, feedback, ingest = summary["log"]
    assert (other["kind"], other["text"], other["date"]) == ("other", "알 수 없는 기록", None)
    assert (init["kind"], feedback["kind"]) == ("init", "feedback")
    assert (ingest["kind"], ingest["project"], ingest["project_title"], ingest["requirement_count"],
            ingest["unassigned_count"]) == ("ingest", "P2025-01", "가상 실적", 70, 10)
    log.unlink()
    assert client.get(BASE).json()["last_changed"] == "2026-01-02"
    for page in root.rglob("*.md"):
        page.write_text(page.read_text().replace("updated: 2026-01-02", "updated: null"))
    assert client.get(BASE).json()["last_changed"] is None


def test_project_and_requirement_details(wiki):
    client, root = wiki
    page = root / "portfolio/P2025-01.md"
    excerpt = "가" * 310
    page.write_text(page.read_text().split("## 개요")[0] + "## 수행한 요구 범위\n- 관제 지원\n"
        "- `관리`\n- YAML 참고\n- 라벨 참고\n- past.yaml 참고\n### 요구사항 전체 목록(원문)\n"
        f"- R1 요구 하나 — {excerpt}\n- R2 요구 둘 — 참고 {root}/secret\n"
        "- R3 요구 셋 — 계약 987,654,321원\n## 다음 절\n- 포함하지 않음\n")
    path = root.parent / "sample.portfolio.yaml"
    records = yaml.safe_load(path.read_text())
    records[0]["domain"] = ["문서"]
    path.write_text(yaml.safe_dump(records))
    project = BASE + "/portfolio/P2025-01"
    detail = client.get(project).json()
    assert detail["domain"] == ["문서"]
    assert detail["scope_lines"] == ["관제 지원"]
    assert detail["requirements"] == [dict(req_id="R" + str(i), name="요구 " + name)
                                      for i, name in enumerate(("하나", "둘", "셋"), 1)]
    assert detail["work_units"] == [dict(topic_id="t", topic_title="주제", units=[dict(id="t.a", title="가")])]
    assert detail["requirement_count"] == 3
    def requirement(rid):
        response = client.get(project + "/requirements/" + rid)
        assert response.status_code == 200
        for private in (str(root), "987,654,321", "amount_krw"):
            assert private not in response.text
        return response.json()
    row = requirement("R1")
    assert (row["name"], row["project"], row["req_id"], row["text"]) == ("요구 하나", "P2025-01", "R1", excerpt[:300])
    for suffix in ("/work-units/t", "/portfolio/P2025-01"):
        response = client.get(BASE + suffix)
        assert response.status_code == 200 and str(root) not in response.text and "987,654,321" not in response.text
    assert requirement("R2")["text"] == "[경로 생략]"
    assert "[금액 생략]" in requirement("R3")["text"]
    for suffix, code in [("work-units/missing", "topic"), ("portfolio/P2100-99", "project"),
                         ("portfolio/P2100-99/requirements/R1", "requirement"),
                         ("portfolio/P2025-01/requirements/missing", "requirement"),
                         ("portfolio/P2025-01/requirements/_bad", "requirement"),
                         ("portfolio/P1/requirements/R1", "requirement")]:
        error(client.get(BASE + "/" + suffix), 404, f"company_wiki_{code}_not_found")


def test_project_order_and_distinct_topic_counts(wiki):
    client, root = wiki
    path = root.parent / "sample.portfolio.yaml"
    records = yaml.safe_load(path.read_text())
    records[0]["period"] = dict(start="2021-01", end="2024-03")
    records[1]["period"] = dict(start="2025-02")
    records.append(dict(id="P2024-03", title="다른 실적"))
    path.write_text(yaml.safe_dump(records))
    path = root / "work-units.json"
    work = json.loads(path.read_text())
    work["evidence"].extend(dict(unit=unit, project=project, req_id="RX")
                            for unit, project in [("t.a", "P2024-02"), ("t.a", "P2024-03"), ("t.b", "P2024-02")])
    path.write_text(json.dumps(work))
    topic, = client.get(BASE + "/work-units").json()["topics"]
    assert (topic["project_count"], topic["units_without_evidence"]) == (3, 0)
    unit = client.get(BASE + "/work-units/t").json()["units"][0]
    assert (unit["project_count"], unit["latest_year"]) == (3, 2025)
    assert [(p["year"], p["project"]) for p in unit["projects"]] == [
        (2025, "P2024-02"), (2024, "P2025-01"), (2024, "P2024-03")]


def test_reviewed_answers_reads_citations_and_snapshot_changes(wiki):
    from io import StringIO
    from app.deep_review.cli.wiki_evaluation import record
    from app.deep_review.services.company_wiki import CompanyWiki

    client, root = wiki
    url = BASE + "/quality"
    assert client.get(url).json()["status"] == "unmeasured"
    requests = [
        {"tool": "Read", "page": "rule/missing"},
        {"tool": "Read", "page": "category/group"},
        {"tool": "Read", "page": "category/group"},
        {"tool": "Read", "page": "capability/skill"},
        {"tool": "finish", "answer": "구축과 운영을 확인했습니다."},
    ]
    output = StringIO()
    replies = StringIO()
    record(CompanyWiki(), "build", map(json.dumps, requests), replies, output)
    trace = json.loads(output.getvalue())
    assert trace["tool_calls"] == 4
    assert trace["read_pages"] == ["category/group", "category/group", "capability/skill"]
    assert json.loads(replies.getvalue().splitlines()[0]) == {"error": "company_wiki_page_not_found"}
    report = dict(schema_version="bidops.wiki-evaluation.v1", dataset_version="synthetic-v1",
                  bundle_sha256=trace["bundle_sha256"], work_units_sha256=trace["work_units_sha256"],
                  model_version="fixture", reviewed_on="2026-11-24", reviewer="test",
                  rubric_version="v1", cases=[dict(
                      id="build", question="구축과 운영이 모두 확인되는가?", expected_answer="일부만 확인",
                      answer=trace["answer"], correct=False, answerable=True, abstained=False,
                      reviewer_note="운영 근거 없음", required_groups=[["rule/one", "category/group"]],
                      read_pages=trace["read_pages"], tool_calls=trace["tool_calls"], tokens=None,
                      claims=[
                          dict(text="구축", grounded=True, citations=[
                              dict(page="category/group", quote="요구사항 전체 목록", supports_claim=True)]),
                          dict(text="운영", grounded=False, citations=[
                              dict(page="rule/one", quote="없는 원문", supports_claim=True)]),
                      ],
                  )])
    from app.deep_review.cli.assemble_wiki_evaluation import assemble
    for name in ("tool_calls", "read_pages"):
        del report["cases"][0][name]
    with pytest.raises(ValueError, match="snapshot mismatch"):
        assemble(report, [{**trace, "bundle_sha256": "0" * 64}])
    report = assemble(report, [trace]).model_dump(mode="json")
    path = root / "answer-evaluation.json"
    path.write_text(json.dumps(report))
    result = client.get(url).json()
    assert result["status"] == "reviewed"
    metrics = {row["label"]: (row["numerator"], row["denominator"]) for row in result["metrics"]}
    assert metrics["인용이 주장을 뒷받침"] == (1, 2)
    assert metrics["인용으로 뒷받침한 주장"] == (1, 2)
    assert metrics["근거 없는 단정"] == (1, 2)
    assert metrics["필수 근거 열람률 (Recall)"] == (1, 1)
    assert metrics["열람 페이지 관련도 (Precision)"] == (1, 2)
    assert metrics["자료 부족 시 답변 보류"] == (0, 0)
    assert not result["evaluation"]["cases"][0]["claims"][1]["citations"][0]["supports_claim"]
    report["cases"].append(dict(
        id="qual", question="자격 보유 여부는?", expected_answer="확인 불가", answer="확인 불가",
        correct=True, answerable=False, abstained=True, reviewer_note="증빙 부족", claims=[],
        required_groups=[["rule/one"]], read_pages=None, tool_calls=None, tokens=None,
    ))
    path.write_text(json.dumps(report))
    more = client.get(url).json()
    ratios = {row["label"]: (row["numerator"], row["denominator"]) for row in more["metrics"]}
    assert ratios["자료 부족 시 답변 보류"] == (1, 1)
    assert ratios["필수 근거 열람률 (Recall)"] == (1, 1)
    assert ratios["읽기 기록이 있는 질문"] == (1, 2)
    units = root / "work-units.json"
    units.write_text(units.read_text() + "\n")
    assert client.get(url).json()["status"] == "stale"
    assert client.get(url).json()["evaluation"] is None
    path.write_text("{}")
    error(client.get(url), 503, "company_wiki_unreadable")
