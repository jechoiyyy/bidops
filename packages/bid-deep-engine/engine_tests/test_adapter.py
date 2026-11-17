from bid_deep_engine.adapter import project_company, source_evidence, raw_blocks


def test_projection_preserves_proposed_and_unknown():
    payload = {
        "company_name": "합성",
        "profile_payload": {
            "facts": [
                {
                    "fact_key": "qual:credit_rating",
                    "status": "proposed",
                    "quote": "AAA",
                    "value": {"detail": "AAA"},
                },
                {
                    "fact_key": "project:2024-01",
                    "status": "confirmed",
                    "quote": "합성기관",
                    "value": {"agency": "합성기관", "amount_krw": None},
                },
            ]
        },
        "graph_nodes": [{"id": "project:2024-01", "label": "합성 사업"}],
    }
    profile, mapped = project_company(payload)
    assert profile.registrations.credit_rating.grade == "unknown"
    assert profile.portfolio[0].client == "합성기관"
    assert profile.portfolio[0].amount_krw == "unknown"
    assert len(mapped) == 1


def test_evidence_only_matches_verified_exact_frozen_quote():
    payload = {
        "documents": [{"document_version_id": "d", "source_sha256": "a" * 64}],
        "blocks": [
            {
                "document_version_id": "d",
                "block_key": "b",
                "page": 2,
                "text": "원문 근거 문장",
            }
        ],
    }
    assert source_evidence({"e": {"quote": "근거", "verified": False}}, payload) == []
    assert (
        source_evidence({"e": {"quote": "조작한 인용", "verified": True}}, payload)
        == []
    )
    found = source_evidence({"e": {"quote": "근거", "verified": True}}, payload)
    assert found[0]["start"] == 3 and found[0]["block_key"] == "b"


def test_table_cells_are_preserved_without_duplicate_paragraphs():
    payload = {
        "blocks": [
            {
                "document_version_id": "d",
                "type": "table",
                "text": "",
                "page": 1,
                "attributes": {"table_key": "t"},
            },
            {
                "document_version_id": "d",
                "type": "table_cell",
                "text": "SFR-001",
                "page": 1,
                "attributes": {"table_key": "t", "row": 0, "column": 0},
            },
            {
                "document_version_id": "d",
                "type": "table_cell",
                "text": "검색",
                "page": 1,
                "attributes": {"table_key": "t", "row": 0, "column": 1},
            },
        ]
    }
    blocks, tables = raw_blocks(payload)
    assert len(blocks) == len(tables) == 1
    assert tables[0].rows == [["SFR-001", "검색"]]
