"""RL-04 STEP-005 pure pieces on the committed synthetic Rootlab fixture (always runs).

* the mock proposal client answers every section of the synthetic input with a
  Section that passes ``validate_proposal_section`` unchanged (statements quote
  unit text verbatim and whole, placeholders for missing facts, full coverage);
* the prompt envelope and its repair part carry rule codes and integer indexes
  only;
* the settled draft status rule (completed / partial / failed / unsettled).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.deep_review.services.input_versions import PROPOSAL_LUNA_POLICY_FILE, PROPOSAL_SECTION_KEYS, load_canonical_policy
from app.deep_review.services.mock_proposal_client import MockProposalClient, mock_section
from app.deep_review.services.proposal_draft import settled_status
from app.deep_review.services.proposal_input import proposal_transfer_payload
from app.deep_review.services.proposal_validation import validate_proposal_section
from app.deep_review.services.proposal_worker import SectionFailure, proposal_prompt
from tests.deep_review.test_proposal_input import (  # noqa: F401 - shared fixtures
    _frozen,
    _input,
    _sources,
    company,
    object_store,
    real_company_settings,
)


def _policy() -> dict:
    payload, _raw, _digest = load_canonical_policy(PROPOSAL_LUNA_POLICY_FILE)
    return payload


def test_mock_sections_pass_the_validator_for_every_section(company) -> None:
    frozen = _frozen(company.knowledge)
    sources = _sources(frozen)
    client = MockProposalClient()
    for key in PROPOSAL_SECTION_KEYS:
        value = _input(sources, key)
        payload = proposal_transfer_payload(value, sources)
        result = client.invoke_prompt(proposal_prompt(_policy(), payload), contract="proposal-section-v1")
        section = result.structured_output
        assert result.raw_response == b"" and result.provider == "mock-analysis"
        verdict = validate_proposal_section(section, section_input=value)
        assert verdict.ok, (key, verdict.safe_detail())
        assert section == mock_section(payload)  # deterministic
        kinds = [s["kind"] for p in section["paragraphs"] for s in p["sentences"]]
        assert "placeholder" in kinds
        hints = [s["placeholder_hint"] for p in section["paragraphs"] for s in p["sentences"] if s["placeholder_hint"]]
        assert len(hints) == len(value["missing_facts"]) + 1 + sum(
            1 for unit in value["units"] if not any(block["text"].strip() for block in unit["blocks"]))
        # no withheld value text is ever written by the mock
        assert "BBB0" not in json.dumps(section, ensure_ascii=False)
        if key == "requirements":
            assert {link["unit_id"] for link in section["requirement_links"]} == {
                unit["unit_id"] for unit in value["units"] if unit["kind"] == "card"}
    assert client.calls == list(PROPOSAL_SECTION_KEYS)


def test_prompt_envelope_and_repair_part_carry_codes_and_indexes_only(company) -> None:
    frozen = _frozen(company.knowledge)
    sources = _sources(frozen)
    payload = proposal_transfer_payload(_input(sources, "requirements"), sources)
    plain = json.loads(proposal_prompt(_policy(), payload))
    assert set(plain) == {"stage", "instruction", "output_contract", "input"}
    assert plain["stage"] == "requirements" and plain["input"] == payload
    assert plain["output_contract"] == _policy()["prompt_output_contract"]
    violation = {"rule_code": "statement_sources_required", "paragraph_index": 0, "sentence_index": 1,
                 "source_index": None, "link_index": None, "unit_index": None}
    repaired = json.loads(proposal_prompt(_policy(), payload, repair_detail={
        "rule_codes": ["statement_sources_required"], "violations": [violation]}))
    assert repaired["validation_repair"] == {
        "scope": "syntax_or_schema_only", "rule_codes": ["statement_sources_required"], "violations": [violation]}
    for bad in (
        {"rule_codes": ["statement_sources_required"], "violations": [], "text": "x"},
        {"rule_codes": [], "violations": []},
        {"rule_codes": ["원문 문장"], "violations": []},
        {"rule_codes": ["output_schema"], "violations": [{**violation, "quote": "원문"}]},
        {"rule_codes": ["output_schema"], "violations": [{**violation, "paragraph_index": "0"}]},
    ):
        with pytest.raises(SectionFailure):
            proposal_prompt(_policy(), payload, repair_detail=bad)


def _sections(statuses: dict[str, str]) -> dict:
    return {key: SimpleNamespace(status=status) for key, status in statuses.items()}


def test_settled_status_rule() -> None:
    every = dict.fromkeys(PROPOSAL_SECTION_KEYS, "completed")
    assert settled_status(_sections(every)) == "completed"
    assert settled_status(_sections({**every, "overview": "reviewed"})) == "completed"
    assert settled_status(_sections({**every, "strategy": "failed"})) == "partial"
    assert settled_status(_sections(dict.fromkeys(PROPOSAL_SECTION_KEYS, "failed"))) == "failed"
    assert settled_status(_sections({**every, "strategy": "queued"})) is None
    assert settled_status(_sections({**every, "strategy": "running"})) is None
    assert settled_status(_sections({key: "completed" for key in PROPOSAL_SECTION_KEYS[:5]})) is None
