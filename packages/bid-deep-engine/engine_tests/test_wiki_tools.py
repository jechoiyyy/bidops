"""The compiled work-unit evidence map: ingest mapping -> sidecar -> rendered pages that lint clean."""

import json

import pytest

from bid_deep_engine import wiki_tools
from bid_deep_engine.company.knowledge import lint_knowledge
from engine_tests.test_runner import _CATEGORY, _FALLBACK, _INDEX, _PORTFOLIO_PAGE

TAXONOMY = {
    "topics": [
        {
            "id": "booking",
            "title": "예약·결제",
            "scope": "예약과 결제 업무",
            "units": [
                {"id": "booking.timeslot", "title": "시간대 예약", "covers": "시간대 단위 예약", "not": "좌석 예매"},
                {"id": "booking.seatmap", "title": "좌석 예매", "covers": "좌석 배치도 예매", "not": ""},
            ],
        }
    ]
}


def _mapping(**changes):
    mapping = {
        "schema": wiki_tools.MAPPING_SCHEMA,
        "project": "P2025-01",
        "source": "test",
        "assignments": [{"req_id": "SFR-001", "units": ["booking.timeslot"]}, {"req_id": "SFR-002", "units": []}],
        "new_units": [],
    }
    mapping.update(changes)
    return mapping


@pytest.fixture
def wiki(tmp_path):
    for rel, text in {
        "INDEX.md": _INDEX,
        "categories/homepage.md": _CATEGORY,
        "categories/other.md": _FALLBACK,
        "portfolio/P2025-01.md": _PORTFOLIO_PAGE,
    }.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (tmp_path / "capabilities").mkdir()
    wiki_tools.init(tmp_path, json.loads(json.dumps(TAXONOMY)))
    return tmp_path


def test_ingest_renders_pages_that_lint_clean_and_are_indexed(wiki):
    data = wiki_tools.apply_mapping(wiki_tools.load_sidecar(wiki), _mapping(), today="2026-11-23")
    wiki_tools.render(wiki, data, today="2026-11-23")
    page = (wiki / "capabilities/work-booking.md").read_text(encoding="utf-8")
    assert "- [[P2025-01]] SFR-001" in page
    assert page.count("- 기록 없음") == 1  # the seat-map unit has no evidence
    index = (wiki / "INDEX.md").read_text(encoding="utf-8")
    assert "[[work-units]]" in index and "[[work-booking]]" in index
    assert lint_knowledge(wiki).errors == []
    assert wiki_tools.stats(data) | {} == {
        "topics": 1, "units": 2, "units_with_evidence": 1, "evidence_rows": 1, "projects": 1,
        "requirements": 2, "unassigned": 1, "no_record_notes": 0,
    }


def test_rendering_twice_keeps_one_index_block(wiki):
    data = wiki_tools.apply_mapping(wiki_tools.load_sidecar(wiki), _mapping(), today="2026-11-23")
    wiki_tools.render(wiki, data, today="2026-11-23")
    wiki_tools.render(wiki, data, today="2026-11-23")
    assert (wiki / "INDEX.md").read_text(encoding="utf-8").count(wiki_tools.INDEX_HEAD) == 1


def test_reingesting_a_project_replaces_its_evidence(wiki):
    data = wiki_tools.apply_mapping(wiki_tools.load_sidecar(wiki), _mapping(), today="2026-11-23")
    again = _mapping(assignments=[{"req_id": "SFR-009", "units": ["booking.seatmap"]}])
    data = wiki_tools.apply_mapping(data, again, today="2026-11-24")
    assert data["evidence"] == [{"project": "P2025-01", "req_id": "SFR-009", "unit": "booking.seatmap"}]


def test_allow_filter_hides_evidence_of_other_projects(wiki):
    data = wiki_tools.apply_mapping(wiki_tools.load_sidecar(wiki), _mapping(), today="2026-11-23")
    wiki_tools.render(wiki, data, today="2026-11-23", allow=set())
    page = (wiki / "capabilities/work-booking.md").read_text(encoding="utf-8")
    assert "P2025-01" not in page and page.count("- 기록 없음") == 2


def test_new_unit_is_added_under_its_topic(wiki):
    mapping = _mapping(
        assignments=[{"req_id": "SFR-003", "units": ["booking.waitlist"]}],
        new_units=[{"topic": "booking", "id": "booking.waitlist", "title": "대기자 관리", "covers": "대기 접수"}],
    )
    data = wiki_tools.apply_mapping(wiki_tools.load_sidecar(wiki), mapping, today="2026-11-23")
    assert [u["id"] for u in data["topics"][0]["units"]][-1] == "booking.waitlist"


@pytest.mark.parametrize(
    "changes",
    [
        {"schema": "other"},
        {"project": "not-a-project"},
        {"assignments": [{"req_id": "SFR-001", "units": ["booking.unknown"]}]},
        {"assignments": [{"req_id": "", "units": []}]},
        {"new_units": [{"topic": "missing", "id": "missing.x", "title": "x"}]},
    ],
)
def test_invalid_mapping_is_rejected(wiki, changes):
    with pytest.raises(wiki_tools.WikiToolError):
        wiki_tools.apply_mapping(wiki_tools.load_sidecar(wiki), _mapping(**changes), today="2026-11-23")


def test_cli_ingest_apply_writes_sidecar_log_and_reports_lint(wiki, tmp_path, capsys):
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(_mapping()), encoding="utf-8")
    code = wiki_tools.main(["ingest-apply", "--root", str(wiki), "--mapping", str(mapping_path), "--today", "2026-11-23"])
    assert code == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["errors"] == 0
    assert "ingest | P2025-01 | 요구사항 2건, 미분류 1건" in (wiki / wiki_tools.LOG_FILE).read_text(encoding="utf-8")
    assert wiki_tools.load_sidecar(wiki)["sources"]["P2025-01"]["ingested_at"] == "2026-11-23"


def test_feedback_applies_only_approved_items_and_shows_on_the_page(wiki):
    data = wiki_tools.apply_mapping(wiki_tools.load_sidecar(wiki), _mapping(), today="2026-11-23")
    feedback = {
        "schema": wiki_tools.FEEDBACK_SCHEMA,
        "notice": "R26BD00000001",
        "items": [
            {"type": "no_record", "unit": "booking.seatmap", "note": "좌석 배치도 예매 기록 없음", "approved": True},
            {"type": "no_record", "unit": "booking.timeslot", "note": "미승인 항목", "approved": False},
            {"type": "missing_unit", "topic": "booking", "id": "booking.refund", "title": "환불 관리", "approved": True},
        ],
    }
    counts = wiki_tools.apply_feedback(data, feedback, today="2026-11-24")
    assert counts == {"no_record": 1, "missing_unit": 1, "skipped": 1}
    wiki_tools.render(wiki, data, today="2026-11-24")
    page = (wiki / "capabilities/work-booking.md").read_text(encoding="utf-8")
    assert "기록 없음으로 확인: 좌석 배치도 예매 기록 없음 (2026-11-24)" in page
    assert "- 단위 id: `booking.refund`" in page and "미승인 항목" not in page
    assert lint_knowledge(wiki).errors == []


def test_feedback_with_unknown_unit_is_rejected(wiki):
    feedback = {"schema": wiki_tools.FEEDBACK_SCHEMA, "items": [{"type": "no_record", "unit": "booking.x", "approved": True}]}
    with pytest.raises(wiki_tools.WikiToolError):
        wiki_tools.apply_feedback(wiki_tools.load_sidecar(wiki), feedback, today="2026-11-24")


def test_content_check_reports_gaps_and_contradictions(wiki):
    data = wiki_tools.load_sidecar(wiki)
    data["topics"][0]["units"].append({"id": "booking.timeslot-2", "title": "시간대 예약", "covers": "", "not": ""})
    data = wiki_tools.apply_mapping(data, _mapping(), today="2026-11-23")
    data["no_record"].append({"unit": "booking.timeslot", "note": "x", "as_of": "2026-11-23", "source": ""})
    report = wiki_tools.check_content(wiki, data)
    assert report["duplicate_titles"] == [["booking.timeslot", "booking.timeslot-2"]]
    assert "booking.seatmap" in report["units_without_evidence"]
    assert report["evidence_without_source_line"] == ["P2025-01 SFR-001"]  # the fixture page has no such line
    assert report["no_record_but_has_evidence"] == ["booking.timeslot"]
    assert report["ingested_without_page"] == []


SOURCE = {"project": "P2025-01", "title": "t", "requirements": [{"id": "SFR-001", "name": "예약"}, {"id": "SFR-002", "name": "기타"}]}


def test_ingest_prompt_carries_taxonomy_and_requirements(wiki):
    prompt = wiki_tools.build_ingest_prompt(wiki_tools.load_sidecar(wiki), SOURCE)
    assert "- booking.timeslot | 시간대 예약 | 시간대 단위 예약 | 아님: 좌석 예매" in prompt
    assert '"id": "SFR-002"' in prompt and prompt.startswith("# 작업")


def test_valid_response_passes_and_wrong_topic_prefix_is_reported_with_a_hint(wiki):
    data = wiki_tools.load_sidecar(wiki)
    good = wiki_tools.parse_ingest_response("설명\n" + json.dumps(_mapping()) + "\n끝")
    assert wiki_tools.validate_mapping(data, good, SOURCE) == []
    bad = _mapping(assignments=[{"req_id": "SFR-001", "units": ["other.timeslot"]}, {"req_id": "SFR-002", "units": []}])
    errors = wiki_tools.validate_mapping(data, bad, SOURCE)
    assert errors == ["SFR-001: 분류표에 없는 단위 other.timeslot (비슷한 단위: booking.timeslot)"]
    retry = wiki_tools.build_repair_prompt("PROMPT", json.dumps(bad), errors)
    assert retry.startswith("PROMPT") and "비슷한 단위: booking.timeslot" in retry


def test_missing_requirement_and_bad_json_are_rejected(wiki):
    data = wiki_tools.load_sidecar(wiki)
    short = _mapping(assignments=[{"req_id": "SFR-001", "units": []}])
    assert "빠짐 ['SFR-002']" in wiki_tools.validate_mapping(data, short, SOURCE)[0]
    with pytest.raises(wiki_tools.WikiToolError):
        wiki_tools.parse_ingest_response("no json here")


def test_cli_validate_writes_mapping_or_repair_prompt(wiki, tmp_path, capsys):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(SOURCE), encoding="utf-8")
    response = tmp_path / "response.txt"
    response.write_text(json.dumps(_mapping(assignments=[{"req_id": "SFR-001", "units": ["x.y"]}, {"req_id": "SFR-002", "units": []}])), encoding="utf-8")
    args = ["ingest-validate", "--root", str(wiki), "--source", str(source), "--response", str(response),
            "--out", str(tmp_path / "m.json"), "--repair-prompt", str(tmp_path / "retry.txt")]
    assert wiki_tools.main(args) == 1
    assert not (tmp_path / "m.json").exists() and "분류표에 없는 단위 x.y" in (tmp_path / "retry.txt").read_text(encoding="utf-8")
    response.write_text(json.dumps(_mapping()), encoding="utf-8")
    capsys.readouterr()
    assert wiki_tools.main(args) == 0
    assert json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))["project"] == "P2025-01"
