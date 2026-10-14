"""Small, synthetic CLI checks for the HP-01 evidence script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[4]
SCRIPT = ROOT / "scripts" / "hp-card-inventory-check.py"


def _write_pair(directory: Path, name: str = "synthetic") -> None:
    structure = {
        "schema": "bidops.document-structure.v1",
        "structure_id": "00000000-0000-0000-0000-000000000001",
        "document_version_id": "00000000-0000-0000-0000-000000000002",
        "source_sha256": "b" * 64,
        "blocks": [
            {
                "block_key": "paragraph-before-card",
                "type": "paragraph",
                "page": 1,
                "text": "합성 앞 문단",
                "attributes": {},
            },
            {
                "block_key": "card-table",
                "type": "table",
                "page": 1,
                "text": "",
                "attributes": {"table_key": "card-table"},
            },
        ],
        "warnings": [],
        "created_at": "2026-10-14T00:00:00+00:00",
    }
    fields = [
        ("요구사항분류", "기능"),
        ("요구사항번호", "SFR-001"),
        ("요구사항명", "합성 카드 제목"),
        ("정의", "민감한 원문 정의"),
        ("세부내용", "민감한 원문 상세"),
    ]
    for row, (label, value) in enumerate(fields):
        for column, text in enumerate((label, value)):
            structure["blocks"].append({
                "block_key": f"card-r{row}-c{column}",
                "parent_block_key": "card-table",
                "type": "table_cell",
                "page": 1,
                "text": text,
                "attributes": {"table_key": "card-table", "row": row, "column": column},
            })
    page_map = {
        "schema": "bidops.para-page-map.v1",
        "blocks": [{"block_key": "paragraph-before-card", "page_first": 7, "page_last": 7}],
    }
    (directory / f"{name}.structure.json").write_text(
        json.dumps(structure, ensure_ascii=False), encoding="utf-8"
    )
    (directory / f"{name}.para_page_map.json").write_text(
        json.dumps(page_map, ensure_ascii=False), encoding="utf-8"
    )


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "web" / "backend")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_evidence_cli_summarizes_cards_without_emitting_source_text(tmp_path: Path) -> None:
    _write_pair(tmp_path)
    output_path = tmp_path / "evidence.json"

    result = _run("--dir", str(tmp_path), "--out", str(output_path))

    assert result.returncode == 0
    rows = json.loads(result.stdout)
    assert rows == json.loads(output_path.read_text(encoding="utf-8"))
    assert rows == [{
        "name": "synthetic",
        "card_count": 1,
        "inherited_page_count": 1,
        "mapped_page_count": 0,
        "unavailable_count": 0,
        "prefixes": ["SFR"],
        "categories": ["기능"],
        "duplicate_ids": [],
        # The preceding anchor text is not a segment heading. Preserve the
        # product's resulting coverage warning instead of suppressing it.
        "warnings": ["coverage_gap:0-0"],
    }]
    assert "민감한 원문" not in result.stdout


def test_evidence_cli_rejects_unpaired_input_without_replacing_output(tmp_path: Path) -> None:
    _write_pair(tmp_path)
    output_path = tmp_path / "evidence.json"
    first = _run("--dir", str(tmp_path), "--out", str(output_path))
    original = output_path.read_bytes()

    second = _run("--dir", str(tmp_path), "--out", str(output_path))

    assert first.returncode == 0
    assert second.returncode != 0
    assert second.stdout == ""
    assert output_path.read_bytes() == original
    assert "민감한 원문" not in second.stderr


def test_evidence_cli_reports_unmatched_directory_pair_without_source_text(tmp_path: Path) -> None:
    _write_pair(tmp_path)
    (tmp_path / "synthetic.para_page_map.json").unlink()

    result = _run("--dir", str(tmp_path))

    assert result.returncode == 2
    assert result.stdout == ""
    assert "민감한 원문" not in result.stderr
