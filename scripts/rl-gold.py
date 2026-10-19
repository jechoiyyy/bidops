#!/usr/bin/env python3
"""Prepare and score the RL-05 human gold sample (10 collected pre-specs).

This is a tool outside the product (docs/work/groups/RL/features/RL-05-gold-acceptance/
spec.md "루트랩 재명세 차이"; precedent: scripts/score-c2-gate.py). It copies the
export/blank-gold/gold-check/score logic of the closed HP tool
(docs/work/groups/HP/preparation/hp_prepare.py) under RL schema names and the
Rootlab binding. ``coverage`` and ``graph-score`` are not carried over. The HP
file is left untouched as the closed record.

It never touches a database or the network, never calls a model, and never writes
an acceptance decision: ``decision`` is always ``null`` and a person fills it in
``acceptance.json``.

Commands (every ``--out`` is created exclusively, mode 0600):

* ``export-cards --cards-pack <dir> --out <file>``
* ``blank-gold --cards <file> --selection <file> --out <file>``
* ``gold-check --gold <file> --selection <file>``     (prints the result)
* ``score --gold <file> --prediction <file> --criteria <file> --out <file>``

Cards pack layout (the contract with ``python -m app.deep_review.cli
export-evaluation --cards``, STEP-002). The pack directory holds, per selected
document, exactly these files and nothing is read from anywhere else:

* ``<document_id>.structure.json`` — the stored ``DocumentStructure`` payload bytes,
  verbatim (so ``sha256(file bytes) == DocumentStructure.payload_sha256``). The JSON
  carries ``source_sha256`` and ``blocks`` as the product payload does.
* ``<document_id>.para_page_map.json`` — the stored page map bytes, verbatim
  (``sha256(file bytes) == page_map_sha256``). Optional: absent means the document
  has no page map and its ``page_map_sha256`` is ``null``.

``<document_id>`` is the file name before ``.structure.json``. No metadata file is
assumed; the selection is applied later by ``blank-gold``. The per-document
``sources_sha256`` is the canonical sha256 of the sorted
``[{structure_sha256, page_map_sha256}]`` list of that document's sources (one
entry: a pack document is one structure).

Output files inside the git worktree are allowed only when git-ignores them
(e.g. ``.sdlc/local-runtime/`` in ``.git/info/exclude``); anywhere else inside
the worktree is refused so raw cards and human gold never reach a commit.

All errors exit 2 and print ``{"error": <code>}`` on stdout. Source text,
credentials and malformed input values are never echoed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = Path(__file__).resolve()
sys.path.insert(0, str(ROOT / "web/backend"))

SCHEMA_CARDS = "bidops.rl-preparation-cards.v1"
SCHEMA_GOLD = "bidops.rl-human-gold.v1"
SCHEMA_GOLD_CHECK = "bidops.rl-gold-check.v1"
SCHEMA_SCORE = "bidops.rl-preparation-score.v1"
SCHEMA_SELECTION = "bidops.rl-evaluation-selection.v1"
# Read-only names for files the product CLI (STEP-002) writes and a person fills in;
# this tool does not read them but the module keeps the names in one place.
SCHEMA_ALIGNMENT = "bidops.rl-condition-alignment.v1"
SCHEMA_RECEIPT = "bidops.rl-evaluation-export-receipt.v1"
SCHEMA_ACTUAL = "bidops.rl-evaluation-actual.v1"

VERDICTS = {"진행 가능", "조건부 진행", "진행 어려움", "판단 불가"}
STATES = {"met", "gap", "unknown"}
STRUCTURE_SUFFIX = ".structure.json"
PAGE_MAP_SUFFIX = ".para_page_map.json"
# gold condition IDs must never collide with the scorer's false-positive marker.
UNMATCHED_PREFIX = "unmatched:"
PREDICTION_KEYS = {"company_sha256", "ontology_sha256", "documents"}
PREDICTION_DOCUMENT_KEYS = {
    "document_id", "source_sha256", "sources_sha256", "verdict", "met", "gap",
    "card_states", "blocking_condition_ids",
}
CRITERIA_KEYS = (
    "document_count", "verdict_correct_min", "blocking_recall_min",
    "card_accuracy_min", "critical_false_met_max",
)


class ToolError(ValueError):
    """An error whose message is a stable code and safe to print."""


def fail(code: str) -> None:
    raise ToolError(code)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def read(path: Any) -> Any:
    def unique(pairs: Any) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                fail("duplicate_json_key")
            result[key] = value
        return result

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def output_allowed(path: Any) -> None:
    """Refuse an output path inside the worktree unless git ignores it."""
    target = Path(os.path.realpath(path))
    root = Path(os.path.realpath(ROOT))
    try:
        relative = target.relative_to(root)
    except ValueError:
        return
    # rc 0 = ignored; 1 = not ignored; anything else (e.g. inside .git) fails closed.
    result = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", "--", str(relative)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=30,
    )
    if result.returncode != 0:
        fail("output_not_ignored")


def write(path: Any, value: Any) -> None:
    path = Path(path)
    output_allowed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical(value) + b"\n")


def unique_rows(rows: Any, key: str) -> dict:
    if not isinstance(rows, list):
        fail("rows_required")
    result: dict = {}
    for row in rows:
        value = row[key]
        if not isinstance(value, str) or not value or value in result:
            fail("invalid_or_duplicate_id")
        result[value] = row
    return result


def hash_value(value: Any, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{64}", value) is None:
        fail("hash_required")


def id_list(value: Any) -> set:
    if (not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value)
            or len(set(value)) != len(value)):
        fail("invalid_id_list")
    return set(value)


def written_list(document: dict, key: str) -> list:
    """Unwritten ``null`` is not confirmed-empty ``[]``: only the latter passes."""
    value = document.get(key)
    if not isinstance(value, list):
        fail("human_fields_incomplete")
    return value


def source_file(directory: Path, name: str) -> Path:
    path = directory / name
    if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
        fail("source_path_outside_input")
    return path


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------


def int_value(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_selection(selection: Any, expected_documents: int = 10) -> dict:
    if not isinstance(selection, dict) or selection.get("schema_version") != SCHEMA_SELECTION:
        fail("selection_invalid")
    for key in ("company_sha256", "ontology_sha256"):
        hash_value(selection.get(key))
    if not isinstance(selection.get("selected_on"), str) or not selection["selected_on"]:
        fail("selection_invalid")
    documents = unique_rows(selection.get("documents"), "document_id")
    if len(documents) != expected_documents:
        fail("document_count_mismatch")
    for row in documents.values():
        hash_value(row.get("source_sha256"))
        # notice_id is required: the export CLI joins attempts to the notice.
        if not int_value(row.get("notice_id")) or not int_value(row.get("opportunity_id")):
            fail("selection_invalid")
        for key in ("structure_id", "manifest_id"):
            if not isinstance(row.get(key), str) or not row[key]:
                fail("selection_invalid")
        for key in ("title", "agency"):
            if not isinstance(row.get(key), str):
                fail("selection_invalid")
    return documents


def match_selection(documents: dict, selected: dict) -> None:
    """Document ids and source hashes must equal the selection exactly."""
    if set(documents) != set(selected):
        fail("selection_mismatch")
    for key, document in documents.items():
        if document.get("source_sha256") != selected[key]["source_sha256"]:
            fail("selection_mismatch")


# --------------------------------------------------------------------------
# export-cards
# --------------------------------------------------------------------------


def source_binding(documents: list) -> str:
    """sha of the sorted (structure payload sha, page map sha) pairs; page map may be null."""
    pairs = [{"structure_sha256": d["structure_sha256"], "page_map_sha256": d["page_map_sha256"]}
             for d in documents]
    pairs.sort(key=lambda p: (p["structure_sha256"], p["page_map_sha256"] or ""))
    return digest(canonical(pairs))


def export_document(directory: Path, document_id: str) -> dict:
    from app.deep_review.services.document_segments import build_manifest_payload, resolve_card_pages

    structure_path = source_file(directory, f"{document_id}{STRUCTURE_SUFFIX}")
    page_map_name = f"{document_id}{PAGE_MAP_SUFFIX}"
    has_page_map = (directory / page_map_name).exists() or (directory / page_map_name).is_symlink()
    page_map_path = source_file(directory, page_map_name) if has_page_map else None
    structure = read(structure_path)
    page_map = read(page_map_path) if page_map_path is not None else None
    source_sha = structure["source_sha256"]
    hash_value(source_sha)
    cards = resolve_card_pages(build_manifest_payload(structure), page_map)
    rows = []
    for card in cards:
        table = card["card"]["table_key"]
        blocks = [b for b in structure["blocks"] if b.get("attributes", {}).get("table_key") == table]
        rows.append({**card, "unit_id": f"card:{source_sha}:{card['ordinal']}:{card['normalized_id']}",
                     "blocks": [{"block_key": b["block_key"], "text": b.get("text", "")} for b in blocks]})
    unique_rows(rows, "unit_id")
    source = {"source_sha256": source_sha,
              "structure_sha256": digest(structure_path.read_bytes()),
              "page_map_sha256": digest(page_map_path.read_bytes()) if page_map_path is not None else None,
              "blocks": [{"unit_id": f"block:{source_sha}:{b['block_key']}",
                          "block_key": b["block_key"], "text": b["text"]}
                         for b in structure["blocks"] if b.get("text", "").strip()]}
    unique_rows(source["blocks"], "unit_id")
    return {"document_id": document_id, "source_sha256": source_sha,
            "source_documents": [source], "sources_sha256": source_binding([source]),
            "cards": rows}


def export_cards(pack: Any) -> dict:
    directory = Path(pack)
    if not directory.is_dir():
        fail("source_path_outside_input")
    names = sorted(p.name[: -len(STRUCTURE_SUFFIX)] for p in directory.iterdir()
                   if p.name.endswith(STRUCTURE_SUFFIX) and len(p.name) > len(STRUCTURE_SUFFIX))
    if not names:
        fail("empty_pack")
    documents = [export_document(directory, name) for name in names]
    unique_rows(documents, "document_id")
    return {"schema_version": SCHEMA_CARDS, "status": "draft", "documents": documents}


# --------------------------------------------------------------------------
# blank-gold
# --------------------------------------------------------------------------


def blank_gold(pack: Any, selection: Any, expected_documents: int = 10) -> dict:
    """Whitelist source-only fields. Never copy model outputs or suggestions."""
    if not isinstance(pack, dict) or pack.get("schema_version") != SCHEMA_CARDS:
        fail("cards_invalid")
    selected = check_selection(selection, expected_documents)
    pack_documents = unique_rows(pack.get("documents"), "document_id")
    match_selection(pack_documents, selected)
    docs = []
    for document_id in sorted(pack_documents):
        d = pack_documents[document_id]
        docs.append({
            "document_id": document_id, "source_sha256": d["source_sha256"],
            "sources_sha256": d["sources_sha256"],
            "source_documents": [
                {**{k: src[k] for k in ("source_sha256", "structure_sha256", "page_map_sha256")},
                 "blocks": [{k: b[k] for k in ("unit_id", "block_key", "text")} for b in src["blocks"]]}
                for src in d["source_documents"]],
            "verdict": None, "blocking_conditions": None, "met": None, "gap": None,
            "cautions": None, "card_states": [],
            "source_cards": [{k: c[k] for k in ("unit_id", "raw_id", "title", "card", "blocks",
                                               "locator", "page_range", "mapping_status")}
                             for c in d["cards"]]})
    return {"schema_version": SCHEMA_GOLD, "status": "blank", "annotator": None,
            "authored_at": None, "written_before_model_output": None,
            "company_sha256": selection["company_sha256"],
            "ontology_sha256": selection["ontology_sha256"], "documents": docs}


# --------------------------------------------------------------------------
# gold-check
# --------------------------------------------------------------------------


def iso_with_timezone(value: Any) -> None:
    """ISO-8601 timestamp that carries a UTC offset; naive times are refused."""
    if not isinstance(value, str) or not value:
        fail("authored_at_invalid")
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        fail("authored_at_invalid")
    if "T" not in text.upper() or parsed.tzinfo is None or parsed.utcoffset() is None:
        fail("authored_at_invalid")


def source_universe(document: dict) -> tuple:
    sources = unique_rows(document["source_documents"], "source_sha256")
    if (document["source_sha256"] not in sources
            or document["sources_sha256"] != source_binding(list(sources.values()))):
        fail("source_set_binding_mismatch")
    blocks = []
    for sha, src in sources.items():
        hash_value(src["source_sha256"])
        hash_value(src["structure_sha256"])
        hash_value(src["page_map_sha256"], nullable=True)
        for block in src["blocks"]:
            if block["unit_id"] != f"block:{sha}:{block['block_key']}" or not block.get("text"):
                fail("source_block_invalid")
            blocks.append(block)
    block_ids = set(unique_rows(blocks, "unit_id"))
    cards = set(unique_rows(document["source_cards"], "unit_id"))
    for card in cards:
        parts = card.split(":")
        if len(parts) < 4 or parts[0] != "card" or parts[1] not in sources:
            fail("card_source_invalid")
    return cards, cards | block_ids


def check_gold(gold: Any, selection: Any = None, expected_documents: int = 10) -> dict:
    if (not isinstance(gold, dict) or gold.get("schema_version") != SCHEMA_GOLD
            or gold.get("status") != "human_completed"):
        fail("human_gold_incomplete")
    if not gold.get("annotator") or gold.get("written_before_model_output") is not True:
        fail("human_provenance_required")
    iso_with_timezone(gold.get("authored_at"))
    for key in ("company_sha256", "ontology_sha256"):
        hash_value(gold.get(key))
    docs = unique_rows(gold["documents"], "document_id")
    if len(docs) != expected_documents:
        fail("document_count_mismatch")
    if selection is not None:
        selected = check_selection(selection, expected_documents)
        if any(gold[k] != selection[k] for k in ("company_sha256", "ontology_sha256")):
            fail("selection_mismatch")
        match_selection(docs, selected)
    for d in docs.values():
        hash_value(d["source_sha256"])
        if d.get("verdict") not in VERDICTS:
            fail("human_fields_incomplete")
        written_list(d, "cautions")
        card_ids, universe = source_universe(d)
        for key in ("met", "gap"):
            if not id_list(written_list(d, key)) <= universe:
                fail("source_ids_required")
        if set(d["met"]) & set(d["gap"]):
            fail("contradictory_gold")
        # Conditions are human-assigned stable IDs; text-only matching needs adjudication.
        conditions = unique_rows(written_list(d, "blocking_conditions"), "condition_id")
        for condition_id, c in conditions.items():
            if condition_id.startswith(UNMATCHED_PREFIX):
                fail("condition_id_reserved")
            if not c.get("text") or not id_list(c.get("source_unit_ids")) or not set(c["source_unit_ids"]) <= universe:
                fail("condition_evidence_required")
        rows = d["card_states"]
        if (not isinstance(rows, list) or len(rows) != 10
                or len({r["unit_id"] for r in rows}) != 10):
            fail("ten_card_states_required")
        states = unique_rows(rows, "unit_id")
        if not set(states) <= card_ids or any(r["status"] not in STATES for r in states.values()):
            fail("ten_card_states_required")
        for key in ("met", "gap"):
            if any(i in states and states[i]["status"] != key for i in d[key]):
                fail("contradictory_card_state")
    return docs


# --------------------------------------------------------------------------
# score
# --------------------------------------------------------------------------


def ratio(n: int, d: int) -> dict:
    return {"numerator": n, "denominator": d, "value": n / d if d else None}


def check_criteria(criteria: Any) -> None:
    if not isinstance(criteria, dict):
        fail("criteria_invalid")
    for key in CRITERIA_KEYS:
        value = criteria.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("criteria_invalid")


def candidate_checks(rows: list, criteria: dict, criteria_sha256: str) -> dict:
    check_criteria(criteria)

    def aggregate(field: str) -> dict:
        return ratio(sum(r[field]["numerator"] for r in rows), sum(r[field]["denominator"] for r in rows))

    blocking = aggregate("blocking_recall")
    cards = aggregate("card_accuracy")
    correct = sum(r["verdict_correct"] for r in rows)

    def verdict(value: bool) -> str:
        return "pass" if value else "fail"

    def minimum(metric: dict, threshold: float) -> str:
        # A zero denominator is unmeasured, never a pass.
        return "unmeasured" if metric["value"] is None else verdict(metric["value"] >= threshold)

    checks = {
        "document_count": verdict(len(rows) == criteria["document_count"]),
        "verdict_correct": verdict(correct >= criteria["verdict_correct_min"]),
        "blocking_recall": minimum(blocking, criteria["blocking_recall_min"]),
        "card_accuracy": minimum(cards, criteria["card_accuracy_min"]),
        # A model or the scorer must never author this human adjudication.
        "critical_false_met": "pending_human_review",
    }
    return {"criteria_sha256": criteria_sha256, "checks": checks,
            "blocking_recall_micro": blocking, "card_accuracy_micro": cards,
            "verdict_correct": correct, "critical_false_met_count": None,
            "critical_false_met_max": criteria["critical_false_met_max"],
            "status": "numeric_criteria_failed" if "fail" in checks.values() else "pending_human_review",
            "acceptance": "not_decided"}


def check_prediction_shape(prediction: Any) -> dict:
    if not isinstance(prediction, dict) or set(prediction) != PREDICTION_KEYS:
        fail("prediction_shape_invalid")
    rows = prediction["documents"]
    if not isinstance(rows, list) or any(not isinstance(r, dict) or set(r) != PREDICTION_DOCUMENT_KEYS
                                         for r in rows):
        fail("prediction_shape_invalid")
    return unique_rows(rows, "document_id")


def score(gold: Any, prediction: Any, criteria: Any, criteria_sha256: str,
          expected_documents: int = 10) -> dict:
    gs = check_gold(gold, None, expected_documents)
    ps = check_prediction_shape(prediction)
    if set(gs) != set(ps) or any(gold[k] != prediction[k] for k in ("company_sha256", "ontology_sha256")):
        fail("prediction_binding_mismatch")
    out = []
    for key, g in gs.items():
        p = ps[key]
        if (p["source_sha256"] != g["source_sha256"] or p["sources_sha256"] != g["sources_sha256"]
                or p["verdict"] not in VERDICTS):
            fail("prediction_source_or_verdict_invalid")
        card_ids, universe = source_universe(g)
        for field in ("met", "gap"):
            if not id_list(p[field]) <= universe:
                fail("prediction_source_ids_required")
        if set(p["met"]) & set(p["gap"]):
            fail("contradictory_prediction")
        states = unique_rows(p["card_states"], "unit_id")
        if not set(states) <= card_ids or any(v["status"] not in STATES for v in states.values()):
            fail("prediction_card_invalid")
        sample = {r["unit_id"]: r["status"] for r in g["card_states"]}
        if not set(sample) <= set(states):
            fail("prediction_card_missing")
        expected = set(unique_rows(g["blocking_conditions"], "condition_id"))
        # No alignment, no blocking prediction: null is not "found nothing".
        if p["blocking_condition_ids"] is None:
            fail("prediction_alignment_missing")
        found = id_list(p["blocking_condition_ids"])
        # Gold condition ids or an `unmatched:<model unit>` false-positive marker; nothing else.
        if any(i not in expected and not i.startswith(UNMATCHED_PREFIX) for i in found):
            fail("prediction_condition_invalid")
        differences = [i for i, s in sample.items() if states[i]["status"] != s]
        out.append({"document_id": key, "verdict_correct": g["verdict"] == p["verdict"],
                    "blocking_recall": ratio(len(expected & found), len(expected)),
                    "met_reference_precision": ratio(len(set(g["met"]) & set(p["met"])), len(p["met"])),
                    "gap_reference_precision": ratio(len(set(g["gap"]) & set(p["gap"])), len(p["gap"])),
                    "unmatched_met_need_human_adjudication": sorted(set(p["met"]) - set(g["met"])),
                    "unmatched_gap_need_human_adjudication": sorted(set(p["gap"]) - set(g["gap"])),
                    "card_accuracy": ratio(len(sample) - len(differences), len(sample)),
                    "card_mismatches": differences, "missing_conditions": sorted(expected - found),
                    "unmatched_conditions_need_human_adjudication": sorted(found - expected)})
    return {"schema_version": SCHEMA_SCORE, "acceptance": "not_decided", "decision": None,
            "candidate_assessment": candidate_checks(out, criteria, criteria_sha256),
            "verdict_accuracy": ratio(sum(r["verdict_correct"] for r in out), len(out)),
            "documents": out,
            "note": ("variable-length reference overlap only; unmatched items and free-text conditions "
                     "need human adjudication; no automatic acceptance")}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class QuietParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: ARG002 - never echo argv values
        print(json.dumps({"error": "usage"}))
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = QuietParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True, parser_class=QuietParser)
    export = sub.add_parser("export-cards")
    export.add_argument("--cards-pack", required=True)
    export.add_argument("--out", required=True)
    blank = sub.add_parser("blank-gold")
    blank.add_argument("--cards", required=True)
    blank.add_argument("--selection", required=True)
    blank.add_argument("--out", required=True)
    check = sub.add_parser("gold-check")
    check.add_argument("--gold", required=True)
    check.add_argument("--selection", required=True)
    scored = sub.add_parser("score")
    scored.add_argument("--gold", required=True)
    scored.add_argument("--prediction", required=True)
    scored.add_argument("--criteria", required=True)
    scored.add_argument("--out", required=True)
    return parser


def file_sha(path: Any) -> str:
    return digest(Path(path).read_bytes())


def run(args: argparse.Namespace) -> dict:
    tool_sha = digest(TOOL_PATH.read_bytes())
    action = args.action
    if getattr(args, "out", None) is not None:
        # Refuse before reading anything so a rejected path never costs a half-run.
        output_allowed(args.out)
        if Path(args.out).exists():
            fail("output_exists")
    if action == "export-cards":
        result = export_cards(args.cards_pack)
        result["tool_sha256"] = tool_sha
    elif action == "blank-gold":
        result = blank_gold(read(args.cards), read(args.selection))
    elif action == "gold-check":
        check_gold(read(args.gold), read(args.selection))
        return {"schema_version": SCHEMA_GOLD_CHECK, "structurally_valid": True,
                "acceptance": "not_decided",
                "input_sha256": {"gold": file_sha(args.gold), "selection": file_sha(args.selection)},
                "tool_sha256": tool_sha}
    else:
        criteria = read(args.criteria)
        result = score(read(args.gold), read(args.prediction), criteria, file_sha(args.criteria))
        result["input_sha256"] = {"gold": file_sha(args.gold), "prediction": file_sha(args.prediction),
                                  "criteria": file_sha(args.criteria)}
        result["tool_sha256"] = tool_sha
    write(args.out, result)
    return {"status": "prepared", "action": action}


def main(argv: Any = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(run(args), ensure_ascii=False))
        return 0
    except ToolError as error:
        print(json.dumps({"error": str(error)}))
    except FileExistsError:
        print(json.dumps({"error": "output_exists"}))
    except Exception:  # noqa: BLE001 - unknown shape; never echo values
        print(json.dumps({"error": "invalid_input"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
