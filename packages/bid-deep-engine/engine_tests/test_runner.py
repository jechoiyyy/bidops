"""Runner boundary: real normalizer/pipeline/readiness with the mock_reference transport."""

import copy
import hashlib
import io
import json
import sys

import pytest

from bid_deep_engine import runner
from bid_deep_engine.company.provenance import CompanyEvidenceView
from bid_deep_engine.company.schema import CompanyProfile

DOC = "00000000-0000-0000-0000-000000000001"
ELIGIBILITY = "합성 참가자격 확인서를 제출해야 한다."


def _block(key, text, kind="paragraph", **attributes):
    return {
        "document_version_id": DOC,
        "block_key": key,
        "text": text,
        "page": 1,
        "type": kind,
        "attributes": attributes,
    }


def make_payload(extra_blocks=()):
    blocks = [
        _block("p1", "Ⅰ. 사업개요"),
        _block("p2", "합성 홈페이지 유지관리 사업"),
        _block("p3", "Ⅱ. 참가자격"),
        _block("p4", ELIGIBILITY),
        *extra_blocks,
        _block("p5", "Ⅲ. 요구사항"),
        _block("t1", "", "table", table_key="t"),
    ]
    cells = [("요구사항 고유번호", "SFR-001"), ("요구사항 명칭", "통합검색"), ("세부 내용", "통합검색 기능을 제공한다.")]
    for row, pair in enumerate(cells):
        for column, text in enumerate(pair):
            blocks.append(_block(f"t1-{row}-{column}", text, "table_cell", table_key="t", row=row, column=column))
    return {
        "schema_version": "bidops.engine-input.v1",
        "engine_version": runner.VERSION,
        "mode": "mock_reference",
        "slug": "synthetic-run",
        "title": "합성 사전규격",
        "company_name": "합성회사",
        "profile_sha256": hashlib.sha256(b"bidops profile version").hexdigest(),
        "profile_payload": {"facts": []},
        "graph_nodes": [],
        "documents": [{"document_version_id": DOC, "source_sha256": "a" * 64}],
        "primary_format": "hwpx",
        "blocks": blocks,
    }


def _assessment(out):
    return out["analysis"]["assessment"]


def _condition_kinds(out):
    provisional = _assessment(out)["provisional"]
    return [c["kind"] for c in provisional["conditions"]] if provisional else []


def test_fresh_mock_run_is_not_marked_stale():
    payload = make_payload()
    out = runner.execute(copy.deepcopy(payload))
    assert out["status"] == "partial" and out["quality_status"] == "mock_reference"
    reasons = _assessment(out)["reason_codes"]
    assert "stale_stage" not in reasons
    # facts carries a current stamp (rfp.json + bundle.json fingerprint), not legacy metadata.
    assert "legacy_metadata" not in reasons
    assert "stale_analysis" not in _condition_kinds(out)
    analysis = out["analysis"]
    projection = analysis["company_projection"]
    assert projection["source_profile_sha256"] == payload["profile_sha256"]
    assert projection["engine_company_input_hash"] == analysis["company_input_hash"]
    assert analysis["company_input_hash"] != payload["profile_sha256"]


def test_fingerprint_of_a_different_profile_still_goes_stale(monkeypatch):
    other = CompanyProfile.model_validate(
        {
            "schema_version": 1,
            "company": {"name": "합성회사"},
            "portfolio_file": "unused.yaml",
            "portfolio": [{"id": "P2024-01", "title": "다른 실적", "client": "다른 기관"}],
        }
    )
    monkeypatch.setattr(
        runner,
        "engine_company_input_hash",
        lambda profile: CompanyEvidenceView(other).company_input_hash,
    )
    out = runner.execute(make_payload())
    assert "stale_stage" in _assessment(out)["reason_codes"]
    assert "stale_analysis" in _condition_kinds(out)


def _run_main(monkeypatch, data: bytes):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))
    monkeypatch.setattr(sys, "stdout", out)
    runner.main()
    return json.loads(out.getvalue())


def _cell(row, column):
    return _block(f"bad-{row}-{column}", "셀", "table_cell", table_key="t", row=row, column=column)


def _with(**changes):
    payload = make_payload()
    payload.update(changes)
    return json.dumps(payload, ensure_ascii=False).encode()


def _without(key):
    payload = make_payload()
    del payload[key]
    return json.dumps(payload, ensure_ascii=False).encode()


@pytest.mark.parametrize(
    ("data", "code", "error_class"),
    [
        (_with(mode="live"), "engine_live_not_approved", "EngineError"),
        (_with(schema_version="bidops.engine-input.v0"), "engine_live_not_approved", "EngineError"),
        (_with(blocks=[_block("p", "   ")]), "structure_unavailable", "EngineError"),
        (
            _with(blocks=make_payload()["blocks"] + [_cell(-1, 0)]),
            "invalid_table_coordinates",
            "EngineError",
        ),
        (
            _with(blocks=make_payload()["blocks"] + [_cell(10001, 0)]),
            "table_too_large",
            "EngineError",
        ),
        (b"{not json", "engine_input_invalid", "EngineError"),
        (b"\xff\xfe", "engine_input_invalid", "EngineError"),
        (b"[]", "engine_input_invalid", "EngineError"),
        (_without("primary_format"), "engine_pipeline_failed", "KeyError"),
    ],
)
def test_each_failure_keeps_its_defined_code_and_no_content(monkeypatch, data, code, error_class):
    out = _run_main(monkeypatch, data)
    assert out["status"] == "failed" and out["quality_status"] == "mock_reference"
    assert out["error_code"] == code and out["error_code"] in runner.ERROR_CODES
    assert out["error_class"] == error_class
    assert out["analysis"] is None and out["artifacts"] == {}
    rendered = json.dumps(out, ensure_ascii=False)
    assert ELIGIBILITY not in rendered and "primary_format" not in rendered


def test_oversized_input_is_rejected_before_parsing(monkeypatch):
    monkeypatch.setattr(runner, "MAX_INPUT", 16)
    out = _run_main(monkeypatch, _with())
    assert out["error_code"] == "input_too_large"


def test_successful_main_has_no_error_fields(monkeypatch):
    out = _run_main(monkeypatch, _with())
    assert out["status"] == "partial"
    assert out["error_code"] is None and out["error_class"] is None


def test_product_mock_infers_no_eligibility_from_any_sentence():
    out = runner.execute(make_payload())
    analysis = out["analysis"]
    assert analysis["facts"]["eligibility"] == [] and analysis["gates"] == []
    assert [(f["req_id"], f["fit"]) for f in analysis["fits"]] == [("SFR-001", "UNKNOWN")]
    assert analysis["usage"]["calls"] == 3


def test_scripted_rule_runs_the_real_gate_and_stays_unknown():
    out = runner.execute(make_payload(), mock_rules=[runner.MockRule("SME_CERT", ELIGIBILITY)])
    assert out["status"] == "partial" and out["quality_status"] == "mock_reference"
    analysis = out["analysis"]
    [rule] = analysis["facts"]["eligibility"]
    assert rule["code"] == "SME_CERT" and rule["evidence"]["quote"] == ELIGIBILITY
    assert rule["evidence"]["verified"] is True
    assert [(g["code"], g["verdict"]) for g in analysis["gates"]] == [("SME_CERT", "UNKNOWN")]
    assert "unknown_gate" in _assessment(out)["reason_codes"]
    [located] = [
        e for e in analysis["source_evidence"] if e["evidence_path"] == "/facts/eligibility/0/evidence"
    ]
    assert (located["block_key"], located["location_status"]) == ("p4", "exact")


def test_scripted_quote_absent_from_the_document_yields_no_rule():
    out = runner.execute(make_payload(), mock_rules=[runner.MockRule("SME_CERT", "문서에 없는 문장")])
    assert out["analysis"]["facts"]["eligibility"] == []


def test_repeated_sentence_is_located_in_the_cited_section_end_to_end():
    repeated = [_block("p4b", "Ⅱ-2. 제출서류"), _block("p4c", ELIGIBILITY)]
    out = runner.execute(make_payload(repeated), mock_rules=[runner.MockRule("SME_CERT", ELIGIBILITY)])
    analysis = out["analysis"]
    cited = analysis["facts"]["eligibility"][0]["evidence"]["section_id"]
    located = [
        e for e in analysis["source_evidence"] if e["evidence_path"] == "/facts/eligibility/0/evidence"
    ]
    assert len(located) == 1 and located[0]["location_status"] == "exact"
    assert located[0]["basis"] == "cited_section"
    # The cited section is the first one holding the sentence (참가자격), not 제출서류.
    assert located[0]["block_key"] == "p4" and cited is not None
