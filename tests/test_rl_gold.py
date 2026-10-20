#!/usr/bin/env python3
"""Unit checks for scripts/rl-gold.py (RL-05 plan T1, T3, T4).

The tool is outside the product and reads only files. Every case uses synthetic
sources, a synthetic gold written by the test and the approved criteria file at
its HP path. No real company data, no network, no database. The export-cards cases
need the backend package (``web/backend``) and are skipped, with a reason, when it
is not importable in the interpreter that runs the tests.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/rl-gold.py"
CRITERIA = ROOT / "docs/work/groups/HP/preparation/acceptance-criteria.approved.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("rl_gold", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rl = _load_module()

try:
    sys.path.insert(0, str(ROOT / "web/backend"))
    from app.deep_review.services import document_segments  # noqa: F401

    BACKEND_IMPORTABLE = True
except Exception:  # noqa: BLE001 - any import failure means the backend env is absent
    BACKEND_IMPORTABLE = False

COMPANY = "b" * 64
ONTOLOGY = "c" * 64
AUTHORED_AT = "2026-10-20T09:30:00+09:00"
CARDS_PER_DOCUMENT = 12
CONDITIONS_PER_DOCUMENT = 5


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def cli(*argv: str) -> tuple[int, dict]:
    """Run the tool's main() and return (exit code, parsed stdout JSON)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            code = rl.main(list(argv))
        except SystemExit as exit_:
            code = int(exit_.code or 0)
    return code, json.loads(buffer.getvalue())


def dump(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def selection_for(count: int = 10) -> dict:
    return {
        "schema_version": rl.SCHEMA_SELECTION,
        "documents": [
            {"document_id": f"doc-{i:02d}", "notice_id": 1000 + i, "opportunity_id": 2000 + i,
             "source_sha256": sha(f"source-{i}"), "structure_id": f"structure-{i}",
             "manifest_id": f"manifest-{i}", "title": f"synthetic title {i}", "agency": "synthetic agency"}
            for i in range(count)
        ],
        "company_sha256": COMPANY, "ontology_sha256": ONTOLOGY, "selected_on": "2026-10-19",
    }


def gold_document(i: int) -> dict:
    """One synthetic gold document: 12 source cards, 10 sampled states, 5 conditions."""
    source = sha(f"source-{i}")
    blocks = [{"unit_id": f"block:{source}:p{n}", "block_key": f"p{n}", "text": f"synthetic paragraph {n}"}
              for n in range(3)]
    sources = [{"source_sha256": source, "structure_sha256": sha(f"structure-{i}"),
                # even documents have no page map: null must be accepted and bound.
                "page_map_sha256": None if i % 2 == 0 else sha(f"page-map-{i}"), "blocks": blocks}]
    cards = [f"card:{source}:{n}:SFR-{n}" for n in range(CARDS_PER_DOCUMENT)]
    statuses = ["met", "gap", "unknown"]
    states = [{"unit_id": cards[n], "status": statuses[n % 3]} for n in range(10)]
    return {
        "document_id": f"doc-{i:02d}", "source_sha256": source,
        "sources_sha256": rl.source_binding(sources), "source_documents": sources,
        "source_cards": [{"unit_id": c} for c in cards],
        "verdict": "조건부 진행", "cautions": [],
        "met": [s["unit_id"] for s in states if s["status"] == "met"],
        "gap": [s["unit_id"] for s in states if s["status"] == "gap"],
        "card_states": states,
        "blocking_conditions": [
            {"condition_id": f"cond-{i}-{k}", "text": f"synthetic condition {k}",
             "source_unit_ids": [blocks[0]["unit_id"]]}
            for k in range(CONDITIONS_PER_DOCUMENT)
        ],
    }


def synthetic_gold(count: int = 10) -> dict:
    return {"schema_version": rl.SCHEMA_GOLD, "status": "human_completed",
            "annotator": "SYNTHETIC-TEST-NOT-HUMAN", "authored_at": AUTHORED_AT,
            "written_before_model_output": True,
            "company_sha256": COMPANY, "ontology_sha256": ONTOLOGY,
            "documents": [gold_document(i) for i in range(count)]}


def synthetic_prediction(gold: dict) -> dict:
    """A prediction that equals the gold: every condition found, every state identical."""
    return {
        "company_sha256": gold["company_sha256"], "ontology_sha256": gold["ontology_sha256"],
        "documents": [
            {"document_id": d["document_id"], "source_sha256": d["source_sha256"],
             "sources_sha256": d["sources_sha256"], "verdict": d["verdict"],
             "met": list(d["met"]), "gap": list(d["gap"]),
             "card_states": copy.deepcopy(d["card_states"]),
             "blocking_condition_ids": [c["condition_id"] for c in d["blocking_conditions"]]}
            for d in gold["documents"]
        ],
    }


def rejects(case: unittest.TestCase, code: str, function, *args, **kwargs) -> None:
    with case.assertRaises(rl.ToolError) as caught:
        function(*args, **kwargs)
    case.assertEqual(str(caught.exception), code)


class GoldCheckTests(unittest.TestCase):
    def test_complete_gold_passes_with_matching_selection(self) -> None:
        self.assertEqual(len(rl.check_gold(synthetic_gold(), selection_for())), 10)

    def test_blank_is_not_gold(self) -> None:
        rejects(self, "human_gold_incomplete", rl.check_gold, {"status": "blank"})

    def test_fewer_than_ten_documents(self) -> None:
        rejects(self, "document_count_mismatch", rl.check_gold, synthetic_gold(9), selection_for())
        rejects(self, "document_count_mismatch", rl.check_gold, synthetic_gold(9))

    def test_duplicate_card_among_ten_states(self) -> None:
        gold = synthetic_gold()
        states = gold["documents"][3]["card_states"]
        states[9] = dict(states[0])
        rejects(self, "ten_card_states_required", rl.check_gold, gold)

    def test_nine_or_eleven_card_states(self) -> None:
        gold = synthetic_gold()
        gold["documents"][0]["card_states"].pop()
        rejects(self, "ten_card_states_required", rl.check_gold, gold)
        gold = synthetic_gold()
        gold["documents"][0]["card_states"].append(
            {"unit_id": gold["documents"][0]["source_cards"][10]["unit_id"], "status": "met"})
        rejects(self, "ten_card_states_required", rl.check_gold, gold)

    def test_card_state_outside_source_cards(self) -> None:
        gold = synthetic_gold()
        gold["documents"][0]["card_states"][0]["unit_id"] = "card:" + "f" * 64 + ":0:SFR-0"
        rejects(self, "ten_card_states_required", rl.check_gold, gold)

    def test_foreign_block_rejected(self) -> None:
        # A block id whose source hash is not a source of this document.
        gold = synthetic_gold()
        gold["documents"][0]["source_documents"][0]["blocks"].append(
            {"unit_id": "block:" + "f" * 64 + ":x", "block_key": "x", "text": "synthetic"})
        rejects(self, "source_block_invalid", rl.check_gold, gold)
        # A met/gap/condition reference to a block that is not in the document.
        foreign = "block:" + "f" * 64 + ":x"
        gold = synthetic_gold()
        gold["documents"][0]["met"].append(foreign)
        rejects(self, "source_ids_required", rl.check_gold, gold)
        gold = synthetic_gold()
        gold["documents"][0]["blocking_conditions"][0]["source_unit_ids"] = [foreign]
        rejects(self, "condition_evidence_required", rl.check_gold, gold)

    def test_tampered_source_set_binding(self) -> None:
        gold = synthetic_gold()
        gold["documents"][0]["source_documents"][0]["structure_sha256"] = "f" * 64
        rejects(self, "source_set_binding_mismatch", rl.check_gold, gold)

    def test_sources_binding_ignores_source_hash_and_allows_null_page_map(self) -> None:
        binding = rl.source_binding(
            [{"structure_sha256": "1" * 64, "page_map_sha256": None, "source_sha256": "a" * 64}])
        self.assertEqual(binding, rl.source_binding(
            [{"structure_sha256": "1" * 64, "page_map_sha256": None, "source_sha256": "e" * 64}]))
        self.assertNotEqual(binding, rl.source_binding(
            [{"structure_sha256": "1" * 64, "page_map_sha256": "2" * 64}]))
        expected = hashlib.sha256(
            json.dumps([{"page_map_sha256": None, "structure_sha256": "1" * 64}],
                       sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(binding, expected)

    def test_binding_mismatch_against_selection(self) -> None:
        gold = synthetic_gold()
        for key in ("company_sha256", "ontology_sha256"):
            selection = selection_for()
            selection[key] = "d" * 64
            rejects(self, "selection_mismatch", rl.check_gold, gold, selection)
        selection = selection_for()
        selection["documents"][4]["source_sha256"] = "d" * 64
        rejects(self, "selection_mismatch", rl.check_gold, gold, selection)
        selection = selection_for()
        selection["documents"][4]["document_id"] = "doc-other"
        rejects(self, "selection_mismatch", rl.check_gold, gold, selection)

    def test_selection_requires_notice_id_and_shape(self) -> None:
        for mutate in (lambda s: s["documents"][0].pop("notice_id"),
                       lambda s: s["documents"][0].update(notice_id="1000"),
                       lambda s: s["documents"][0].update(opportunity_id=True),
                       lambda s: s["documents"][0].pop("manifest_id"),
                       lambda s: s.update(schema_version="bidops.hp-evaluation-selection.v1"),
                       lambda s: s.pop("selected_on")):
            selection = selection_for()
            mutate(selection)
            rejects(self, "selection_invalid", rl.check_gold, synthetic_gold(), selection)
        selection = selection_for(9)
        rejects(self, "document_count_mismatch", rl.check_gold, synthetic_gold(), selection)

    def test_authored_at_must_be_iso_with_timezone(self) -> None:
        for value in ("2026-10-20T09:30:00+09:00", "2026-10-20T00:30:00Z", "2026-10-20T00:30:00+00:00"):
            gold = synthetic_gold()
            gold["authored_at"] = value
            rl.check_gold(gold)
        for value in ("2026-10-20T09:30:00", "2026-10-20", "synthetic", "20261020 093000", "",
                      None, 1760920200):
            gold = synthetic_gold()
            gold["authored_at"] = value
            rejects(self, "authored_at_invalid", rl.check_gold, gold)

    def test_human_provenance_required(self) -> None:
        for key, value in (("annotator", None), ("annotator", ""), ("written_before_model_output", False),
                           ("written_before_model_output", None)):
            gold = synthetic_gold()
            gold[key] = value
            rejects(self, "human_provenance_required", rl.check_gold, gold)

    def test_unwritten_null_differs_from_confirmed_empty(self) -> None:
        for field in ("met", "gap", "cautions", "blocking_conditions"):
            gold = synthetic_gold()
            gold["documents"][0][field] = None
            rejects(self, "human_fields_incomplete", rl.check_gold, gold)
        gold = synthetic_gold()
        gold["documents"][0]["verdict"] = None
        rejects(self, "human_fields_incomplete", rl.check_gold, gold)
        # Confirmed-empty lists are valid; card states stay consistent with met/gap.
        gold = synthetic_gold()
        document = gold["documents"][0]
        document["met"], document["gap"], document["cautions"], document["blocking_conditions"] = [], [], [], []
        rl.check_gold(gold)

    def test_met_gap_overlap_and_state_contradiction(self) -> None:
        gold = synthetic_gold()
        gold["documents"][0]["gap"].append(gold["documents"][0]["met"][0])
        rejects(self, "contradictory_gold", rl.check_gold, gold)
        gold = synthetic_gold()
        gold["documents"][0]["card_states"][0]["status"] = "gap"
        rejects(self, "contradictory_card_state", rl.check_gold, gold)

    def test_unmatched_prefix_is_reserved_for_gold_conditions(self) -> None:
        gold = synthetic_gold()
        gold["documents"][0]["blocking_conditions"][0]["condition_id"] = "unmatched:model-unit-1"
        rejects(self, "condition_id_reserved", rl.check_gold, gold)

    def test_duplicate_json_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.json"
            path.write_text('{"a":1,"a":2}')
            rejects(self, "duplicate_json_key", rl.read, path)


class CliGoldCheckTests(unittest.TestCase):
    def test_gold_check_prints_result_and_never_decides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            gold = dump(base / "gold.json", synthetic_gold())
            selection = dump(base / "selection.json", selection_for())
            code, result = cli("gold-check", "--gold", str(gold), "--selection", str(selection))
            self.assertEqual(code, 0)
            self.assertEqual(result["schema_version"], "bidops.rl-gold-check.v1")
            self.assertIs(result["structurally_valid"], True)
            self.assertEqual(result["acceptance"], "not_decided")
            self.assertEqual(result["input_sha256"]["gold"], hashlib.sha256(gold.read_bytes()).hexdigest())

    def test_errors_exit_two_with_code_on_stdout_and_do_not_echo_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            gold = synthetic_gold()
            gold["documents"][0]["verdict"] = "SECRET-VALUE"
            gold_path = dump(base / "gold.json", gold)
            selection = dump(base / "selection.json", selection_for())
            code, result = cli("gold-check", "--gold", str(gold_path), "--selection", str(selection))
            self.assertEqual((code, result), (2, {"error": "human_fields_incomplete"}))
            broken = base / "broken.json"
            broken.write_text("{not json")
            code, result = cli("gold-check", "--gold", str(broken), "--selection", str(selection))
            self.assertEqual((code, result), (2, {"error": "invalid_input"}))
            code, result = cli("gold-check", "--gold", str(base / "missing.json"), "--selection", str(selection))
            self.assertEqual((code, result), (2, {"error": "invalid_input"}))

    def test_usage_errors_exit_two_with_error_on_stdout(self) -> None:
        for argv in ([], ["gold-check"], ["score", "--gold", "x"], ["unknown-command"]):
            code, result = cli(*argv)
            self.assertEqual((code, result), (2, {"error": "usage"}))


class OutputPathTests(unittest.TestCase):
    """--out is exclusive create; an output path inside the worktree must be git-ignored."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name).resolve() / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / ".gitignore").write_text("local-runtime/\n")
        (self.repo / "tracked").mkdir()
        self.outside = Path(self.tmp.name).resolve() / "outside"
        self.outside.mkdir()
        patcher = mock.patch.object(rl, "ROOT", self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.gold = dump(self.outside / "gold.json", synthetic_gold())
        self.selection = dump(self.outside / "selection.json", selection_for())
        self.prediction = dump(self.outside / "prediction.json", synthetic_prediction(synthetic_gold()))

    def score_to(self, out: Path) -> tuple[int, dict]:
        return cli("score", "--gold", str(self.gold), "--prediction", str(self.prediction),
                   "--criteria", str(CRITERIA), "--out", str(out))

    def test_git_ignored_path_inside_worktree_is_allowed(self) -> None:
        out = self.repo / "local-runtime/rl-evaluation-20261020/acceptance-score.json"
        code, result = self.score_to(out)
        self.assertEqual((code, result), (0, {"status": "prepared", "action": "score"}))
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)

    def test_tracked_path_inside_worktree_is_refused(self) -> None:
        for out in (self.repo / "tracked/score.json", self.repo / "score.json"):
            code, result = self.score_to(out)
            self.assertEqual((code, result), (2, {"error": "output_not_ignored"}))
            self.assertFalse(out.exists())

    def test_refused_output_does_not_create_directories(self) -> None:
        out = self.repo / "newdir/deeper/score.json"
        code, result = self.score_to(out)
        self.assertEqual((code, result), (2, {"error": "output_not_ignored"}))
        self.assertFalse((self.repo / "newdir").exists())

    def test_path_outside_worktree_is_allowed(self) -> None:
        code, _ = self.score_to(self.outside / "nested/score.json")
        self.assertEqual(code, 0)

    def test_symlink_into_tracked_area_is_refused(self) -> None:
        link = self.repo / "local-runtime"
        link.mkdir()
        (link / "escape").symlink_to(self.repo / "tracked")
        code, result = self.score_to(link / "escape" / "score.json")
        self.assertEqual((code, result), (2, {"error": "output_not_ignored"}))

    def test_existing_output_is_never_overwritten(self) -> None:
        out = self.outside / "score.json"
        out.write_text("original")
        code, result = self.score_to(out)
        self.assertEqual((code, result), (2, {"error": "output_exists"}))
        self.assertEqual(out.read_text(), "original")
        with self.assertRaises(FileExistsError):
            rl.write(out, {"v": 2})


@unittest.skipUnless(BACKEND_IMPORTABLE, "web/backend is not importable in this interpreter")
class ExportAndBlankGoldTests(unittest.TestCase):
    """export-cards reads the cards pack layout; blank-gold applies the selection."""

    @staticmethod
    def structure(source_sha: str, cards: int = 10) -> dict:
        blocks = [{"block_key": "paragraph-1", "parent_block_key": None, "type": "paragraph", "page": 1,
                   "bbox": None, "text": "제3장 기능 요구사항", "confidence": None, "attributes": {}},
                  {"block_key": "card-table-1-block", "parent_block_key": None, "type": "table", "page": 1,
                   "bbox": None, "text": "", "confidence": None, "attributes": {"table_key": "card-table-1"}}]
        row = 0
        for n in range(cards):
            for label, value in (("요구사항분류", "기능 요구사항"), ("요구사항고유번호", f"SFR-{n + 1:03d}"),
                                 ("요구사항명칭", f"합성 항목 {n + 1}"), ("정의", "합성 정의"),
                                 ("세부내용", "합성 세부내용")):
                for column, text in enumerate((label, value)):
                    blocks.append({"block_key": f"card-table-1-r{row}-c{column}",
                                   "parent_block_key": "card-table-1-block", "type": "table_cell", "page": 1,
                                   "bbox": None, "text": text, "confidence": None,
                                   "attributes": {"table_key": "card-table-1", "row": row, "column": column}})
                row += 1
        return {"schema": "bidops.document-structure.v1", "structure_id": "synthetic",
                "document_version_id": "synthetic", "source_sha256": source_sha, "blocks": blocks,
                "warnings": [], "created_at": "2026-10-19T00:00:00+00:00"}

    def build_pack(self, base: Path, count: int = 10) -> Path:
        pack = base / "pack"
        pack.mkdir()
        for i in range(count):
            (pack / f"doc-{i:02d}.structure.json").write_text(
                json.dumps(self.structure(sha(f"source-{i}")), ensure_ascii=False), encoding="utf-8")
            if i % 2:
                (pack / f"doc-{i:02d}.para_page_map.json").write_text(
                    json.dumps({"blocks": [{"block_key": "paragraph-1", "page_first": 1, "page_last": 1}]}))
        return pack

    def test_pack_to_blank_gold_to_complete_gold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            pack = self.build_pack(base)
            selection = dump(base / "selection.json", selection_for())
            cards = base / "cards.json"
            self.assertEqual(cli("export-cards", "--cards-pack", str(pack), "--out", str(cards))[0], 0)
            exported = rl.read(cards)
            self.assertEqual(exported["schema_version"], "bidops.rl-preparation-cards.v1")
            self.assertEqual([d["document_id"] for d in exported["documents"]],
                             [f"doc-{i:02d}" for i in range(10)])
            first, second = exported["documents"][0], exported["documents"][1]
            self.assertEqual(first["source_sha256"], sha("source-0"))
            self.assertEqual(len(first["cards"]), 10)
            # Hashes are over the stored file bytes; a missing page map is null.
            structure_bytes = (pack / "doc-00.structure.json").read_bytes()
            self.assertEqual(first["source_documents"][0]["structure_sha256"],
                             hashlib.sha256(structure_bytes).hexdigest())
            self.assertIsNone(first["source_documents"][0]["page_map_sha256"])
            self.assertEqual(second["source_documents"][0]["page_map_sha256"],
                             hashlib.sha256((pack / "doc-01.para_page_map.json").read_bytes()).hexdigest())
            self.assertEqual(first["sources_sha256"], rl.source_binding(first["source_documents"]))
            self.assertEqual(first["cards"][0]["unit_id"], f"card:{sha('source-0')}:{first['cards'][0]['ordinal']}:SFR-1")

            blank_path = base / "gold.v1.json"
            code, result = cli("blank-gold", "--cards", str(cards), "--selection", str(selection),
                               "--out", str(blank_path))
            self.assertEqual((code, result), (0, {"status": "prepared", "action": "blank-gold"}))
            blank = rl.read(blank_path)
            self.assertEqual(blank["schema_version"], "bidops.rl-human-gold.v1")
            self.assertEqual(blank["status"], "blank")
            self.assertEqual((blank["company_sha256"], blank["ontology_sha256"]), (COMPANY, ONTOLOGY))
            for key in ("annotator", "authored_at", "written_before_model_output"):
                self.assertIsNone(blank[key])
            self.assertEqual(len(blank["documents"]), 10)
            for document in blank["documents"]:
                for key in ("verdict", "blocking_conditions", "met", "gap", "cautions"):
                    self.assertIsNone(document[key])
                self.assertEqual(document["card_states"], [])
            # A blank form is not gold.
            code, result = cli("gold-check", "--gold", str(blank_path), "--selection", str(selection))
            self.assertEqual((code, result), (2, {"error": "human_gold_incomplete"}))

            # A person fills the form; the structure the tool produced must then pass gold-check.
            blank["status"] = "human_completed"
            blank["annotator"] = "SYNTHETIC-TEST-NOT-HUMAN"
            blank["authored_at"] = AUTHORED_AT
            blank["written_before_model_output"] = True
            for document in blank["documents"]:
                ids = [c["unit_id"] for c in document["source_cards"]]
                document.update(verdict="판단 불가", cautions=[], met=ids[:1], gap=ids[1:2],
                                blocking_conditions=[],
                                card_states=[{"unit_id": ids[0], "status": "met"}, {"unit_id": ids[1], "status": "gap"}]
                                + [{"unit_id": i, "status": "unknown"} for i in ids[2:10]])
            filled = dump(base / "gold.filled.json", blank)
            code, result = cli("gold-check", "--gold", str(filled), "--selection", str(selection))
            self.assertEqual(code, 0, result)

    def test_blank_gold_requires_pack_to_equal_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            pack = self.build_pack(base)
            cards = rl.export_cards(pack)
            rejects(self, "document_count_mismatch", rl.blank_gold, cards, selection_for(9))
            mismatched = selection_for()
            mismatched["documents"][2]["source_sha256"] = "d" * 64
            rejects(self, "selection_mismatch", rl.blank_gold, cards, mismatched)
            renamed = selection_for()
            renamed["documents"][2]["document_id"] = "doc-other"
            rejects(self, "selection_mismatch", rl.blank_gold, cards, renamed)
            short = copy.deepcopy(cards)
            short["documents"].pop()
            rejects(self, "selection_mismatch", rl.blank_gold, short, selection_for())

    def test_blank_gold_discards_extra_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cards = rl.export_cards(self.build_pack(Path(directory)))
            for document in cards["documents"]:
                document["model_answer"] = "SECRET"
                for card in document["cards"]:
                    card["concept_ids"] = ["SECRET"]
            self.assertNotIn("SECRET", json.dumps(rl.blank_gold(cards, selection_for())))

    def test_pack_input_guards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            rejects(self, "empty_pack", rl.export_cards, base)
            rejects(self, "source_path_outside_input", rl.export_cards, base / "missing")
            pack = self.build_pack(base, 1)
            outside = base / "outside.json"
            outside.write_text((pack / "doc-00.structure.json").read_text())
            (pack / "doc-00.structure.json").unlink()
            (pack / "doc-00.structure.json").symlink_to(outside)
            rejects(self, "source_path_outside_input", rl.export_cards, pack)


class ScoreBoundaryTests(unittest.TestCase):
    """Criteria v1 numbers: 8/10, 0.8, 0.7, critical false-met 0; denominator 0 = unmeasured."""

    criteria = json.loads(CRITERIA.read_text())

    def rows(self, correct: int = 10, blocking: tuple = (4, 5), cards: tuple = (7, 10), count: int = 10) -> list:
        return [{"verdict_correct": i < correct, "blocking_recall": rl.ratio(*blocking),
                 "card_accuracy": rl.ratio(*cards)} for i in range(count)]

    def checks(self, rows: list) -> dict:
        return rl.candidate_checks(rows, self.criteria, "x" * 64)

    def test_criteria_file_is_the_approved_v1(self) -> None:
        self.assertTrue(hashlib.sha256(CRITERIA.read_bytes()).hexdigest().startswith("e7148fb4"))

    def test_exact_boundaries_pass(self) -> None:
        result = self.checks(self.rows(correct=8))
        for key in ("document_count", "verdict_correct", "blocking_recall", "card_accuracy"):
            self.assertEqual(result["checks"][key], "pass", key)
        self.assertEqual(result["status"], "pending_human_review")
        self.assertEqual(result["acceptance"], "not_decided")

    def test_just_below_boundaries_fail(self) -> None:
        self.assertEqual(self.checks(self.rows(correct=7))["checks"]["verdict_correct"], "fail")
        self.assertEqual(self.checks(self.rows(blocking=(39, 50)))["checks"]["blocking_recall"], "fail")
        self.assertEqual(self.checks(self.rows(cards=(69, 100)))["checks"]["card_accuracy"], "fail")
        result = self.checks(self.rows(correct=7))
        self.assertEqual(result["status"], "numeric_criteria_failed")

    def test_micro_aggregation_not_mean_of_ratios(self) -> None:
        rows = self.rows(blocking=(1, 1))
        rows[0]["blocking_recall"] = rl.ratio(0, 20)
        metric = self.checks(rows)["blocking_recall_micro"]
        self.assertEqual((metric["numerator"], metric["denominator"]), (9, 29))

    def test_zero_denominator_is_unmeasured_never_pass(self) -> None:
        result = self.checks(self.rows(blocking=(0, 0), cards=(0, 0)))
        self.assertEqual(result["checks"]["blocking_recall"], "unmeasured")
        self.assertEqual(result["checks"]["card_accuracy"], "unmeasured")
        self.assertIsNone(result["blocking_recall_micro"]["value"])
        self.assertNotEqual(result["status"], "numeric_criteria_failed")

    def test_critical_false_met_is_never_authored_by_the_tool(self) -> None:
        result = self.checks(self.rows())
        self.assertEqual(result["checks"]["critical_false_met"], "pending_human_review")
        self.assertIsNone(result["critical_false_met_count"])
        self.assertEqual(result["critical_false_met_max"], 0)

    def test_fewer_than_ten_documents_cannot_meet_the_criteria(self) -> None:
        self.assertEqual(self.checks(self.rows(count=5))["checks"]["document_count"], "fail")

    def test_invalid_criteria_rejected(self) -> None:
        for bad in (None, {}, {**self.criteria, "blocking_recall_min": "0.8"},
                    {**self.criteria, "document_count": True}):
            rejects(self, "criteria_invalid", rl.candidate_checks, self.rows(), bad, "x" * 64)

    def test_end_to_end_boundary_through_the_cli(self) -> None:
        """8/10 verdicts, 40/50 conditions, 70/100 card states: all four sit exactly on the line."""
        gold = synthetic_gold()
        prediction = synthetic_prediction(gold)
        for i, document in enumerate(prediction["documents"]):
            if i < 2:
                document["verdict"] = "진행 가능"
            document["blocking_condition_ids"].pop()
            for state in document["card_states"][:3]:
                state["status"] = "unknown" if state["status"] != "unknown" else "met"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            args = ("score", "--gold", str(dump(base / "gold.json", gold)),
                    "--prediction", str(dump(base / "prediction.json", prediction)),
                    "--criteria", str(CRITERIA), "--out", str(base / "score.json"))
            self.assertEqual(cli(*args), (0, {"status": "prepared", "action": "score"}))
            result = rl.read(base / "score.json")
            self.assertEqual(result["schema_version"], "bidops.rl-preparation-score.v1")
            self.assertIsNone(result["decision"])
            self.assertEqual(result["acceptance"], "not_decided")
            assessment = result["candidate_assessment"]
            self.assertEqual(assessment["verdict_correct"], 8)
            self.assertEqual((assessment["blocking_recall_micro"]["numerator"],
                              assessment["blocking_recall_micro"]["denominator"]), (40, 50))
            self.assertEqual((assessment["card_accuracy_micro"]["numerator"],
                              assessment["card_accuracy_micro"]["denominator"]), (70, 100))
            self.assertEqual(assessment["status"], "pending_human_review")
            self.assertEqual(assessment["criteria_sha256"], hashlib.sha256(CRITERIA.read_bytes()).hexdigest())
            self.assertEqual(result["input_sha256"]["gold"], hashlib.sha256((base / "gold.json").read_bytes()).hexdigest())
            self.assertEqual(result["tool_sha256"], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
            # Exclusive create: a second run to the same file is refused.
            self.assertEqual(cli(*args), (2, {"error": "output_exists"}))

    def test_end_to_end_just_below_fails_numeric_criteria(self) -> None:
        gold = synthetic_gold()
        prediction = synthetic_prediction(gold)
        for document in prediction["documents"]:
            document["verdict"] = "진행 가능"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            code, _ = cli("score", "--gold", str(dump(base / "gold.json", gold)),
                          "--prediction", str(dump(base / "prediction.json", prediction)),
                          "--criteria", str(CRITERIA), "--out", str(base / "score.json"))
            self.assertEqual(code, 0)
            assessment = rl.read(base / "score.json")["candidate_assessment"]
            self.assertEqual(assessment["checks"]["verdict_correct"], "fail")
            self.assertEqual(assessment["status"], "numeric_criteria_failed")

    def test_gold_without_blocking_conditions_everywhere_is_unmeasured_end_to_end(self) -> None:
        gold = synthetic_gold()
        for document in gold["documents"]:
            document["blocking_conditions"] = []
        prediction = synthetic_prediction(gold)
        result = rl.score(gold, prediction, self.criteria, "x" * 64)
        self.assertIsNone(result["documents"][0]["blocking_recall"]["value"])
        self.assertEqual(result["candidate_assessment"]["checks"]["blocking_recall"], "unmeasured")


class AlignmentPredictionTests(unittest.TestCase):
    """HP-06 T5 as it reaches the scorer: alignment missing, arbitrary gold ID, false positive."""

    criteria = json.loads(CRITERIA.read_text())

    def score(self, prediction: dict, gold: dict | None = None) -> dict:
        gold = gold or synthetic_gold()
        return rl.score(gold, prediction, self.criteria, "x" * 64)

    def test_missing_alignment_is_not_scored_as_zero(self) -> None:
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["blocking_condition_ids"] = None
        rejects(self, "prediction_alignment_missing", self.score, prediction)
        del prediction["documents"][0]["blocking_condition_ids"]
        rejects(self, "prediction_shape_invalid", self.score, prediction)

    def test_arbitrary_gold_id_rejected(self) -> None:
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["blocking_condition_ids"].append("cond-made-up")
        rejects(self, "prediction_condition_invalid", self.score, prediction)
        # A real gold ID of another document is arbitrary for this one too.
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["blocking_condition_ids"].append("cond-1-0")
        rejects(self, "prediction_condition_invalid", self.score, prediction)

    def test_false_positive_is_kept_and_does_not_change_recall(self) -> None:
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["blocking_condition_ids"].append("unmatched:model-unit-7")
        document = self.score(prediction)["documents"][0]
        self.assertEqual(document["unmatched_conditions_need_human_adjudication"], ["unmatched:model-unit-7"])
        self.assertEqual(document["blocking_recall"]["value"], 1)
        self.assertEqual(document["missing_conditions"], [])

    def test_missing_condition_is_reported(self) -> None:
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["blocking_condition_ids"].remove("cond-0-0")
        document = self.score(prediction)["documents"][0]
        self.assertEqual(document["missing_conditions"], ["cond-0-0"])
        self.assertEqual(document["blocking_recall"]["numerator"], 4)

    def test_prediction_shape_is_exact(self) -> None:
        prediction = synthetic_prediction(synthetic_gold())
        prediction["schema_version"] = "extra"
        rejects(self, "prediction_shape_invalid", self.score, prediction)
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["note"] = "extra"
        rejects(self, "prediction_shape_invalid", self.score, prediction)

    def test_prediction_binding_and_source_checks(self) -> None:
        prediction = synthetic_prediction(synthetic_gold())
        prediction["company_sha256"] = "d" * 64
        rejects(self, "prediction_binding_mismatch", self.score, prediction)
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"].pop()
        rejects(self, "prediction_binding_mismatch", self.score, prediction)
        for key in ("source_sha256", "sources_sha256"):
            prediction = synthetic_prediction(synthetic_gold())
            prediction["documents"][0][key] = "d" * 64
            rejects(self, "prediction_source_or_verdict_invalid", self.score, prediction)
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["verdict"] = "unknown verdict"
        rejects(self, "prediction_source_or_verdict_invalid", self.score, prediction)

    def test_prediction_card_and_reference_lists(self) -> None:
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["card_states"].pop()
        rejects(self, "prediction_card_missing", self.score, prediction)
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["card_states"][0]["unit_id"] = "not-in-source"
        rejects(self, "prediction_card_invalid", self.score, prediction)
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["met"].append("block:" + "f" * 64 + ":x")
        rejects(self, "prediction_source_ids_required", self.score, prediction)
        prediction = synthetic_prediction(synthetic_gold())
        prediction["documents"][0]["gap"].append(prediction["documents"][0]["met"][0])
        rejects(self, "contradictory_prediction", self.score, prediction)

    def test_variable_reference_lists_and_unmatched_adjudication(self) -> None:
        gold = synthetic_gold()
        gold["documents"][0]["met"] = []
        prediction = synthetic_prediction(gold)
        extra = gold["documents"][0]["source_cards"][11]["unit_id"]
        prediction["documents"][0]["met"] = [extra]
        document = self.score(prediction, gold)["documents"][0]
        self.assertEqual(document["unmatched_met_need_human_adjudication"], [extra])
        self.assertEqual(document["met_reference_precision"]["value"], 0)

    def test_no_automatic_acceptance(self) -> None:
        result = self.score(synthetic_prediction(synthetic_gold()))
        self.assertEqual(result["acceptance"], "not_decided")
        self.assertIsNone(result["decision"])
        self.assertEqual(result["verdict_accuracy"]["value"], 1)


if __name__ == "__main__":
    unittest.main()
