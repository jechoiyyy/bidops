"""Runner boundary: real normalizer/pipeline/readiness with the mock_reference transport."""

import copy
import hashlib

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
