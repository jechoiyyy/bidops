"""RL-10 blocker probes -- replay of the D-2 ideal-extraction probes under compare rules v1 and v2.

No model call, no DB.  Reads the stored RL-05 evaluation files (Git outside), the
Rootlab company source v4 and ontology v2 (read-only), and imports the product
compare (``constraint_comparison``, ``_expected_fit``) from ``web/backend``.  For each
of the 7 blocking conditions RL-05 missed it builds the D-2 probes (the gold source
block verbatim as a text constraint quote, plus one count constraint per ``N명``)
and compares them four ways:

* ``v1_source_v4``  -- rules ``card-compare-v1`` (policies v1..v11), company source v4 as is;
* ``v2_source_v4``  -- rules ``card-compare-v2`` (policy v12), company source v4 as is;
* ``v2_fixture_f1`` -- v2 with a TEST FIXTURE: source v4 plus
  ``pref:onsite_cap.params.onsite_regions="대구"`` and ``excl:hardware.requirement_terms`` =
  the existing v4 ``keywords`` of that fact;
* ``v2_fixture_f2`` -- F1 plus illustrative extra hardware terms (``FIXTURE_F2_EXTRA_TERMS``).

The fixtures are NOT company facts: no person confirmed them.  They exist to show
what the code path does once a person confirms structured values.  The fixture
sources are parsed by the product parser (the new ``requirement_terms`` shape included).

Output holds identifiers, codes and counts only -- no notice text, no company values.
Usage (repository root)::

    <backend venv python> docs/validation-runs/20261119-rl10-compare-blockers/rl10_blocker_probes.py \\
        --eval-dir <main checkout>/.sdlc/local-runtime/rl-evaluation-20261019 \\
        --company-source <fixtures>/company/rootlab/rootlab.source.v4.json \\
        --ontology <fixtures>/company/rootlab/ontology.v2.json > probes.json
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "web" / "backend"))

import warnings  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning)

from app.core.company_ontology import (  # noqa: E402
    build_graph_snapshot,
    parse_company_knowledge_source,
    parse_ontology,
)
from app.deep_review.schemas.card_analysis import CardRequirementConstraint  # noqa: E402
from app.deep_review.services.card_compare import (  # noqa: E402
    COMPARE_RULES_V1,
    COMPARE_RULES_V2,
    PLACE_TABLE_SHA256,
    _expected_fit,
    constraint_comparison,
    resolve_places,
)

EXPECTED = {
    "actual": "e64a66944fc87b4c5b59ead01e55fa7e798bf2cf72fcd3299dd51f1a506abf07",
    "gold": "6c4ca1548c8908a0c358bb03e31bc5ac6a03364e20a425ebee0a78b8e9cd627a",
    "score": "c09b020c1f02d442ad7139b23ae8f89cff85fd6fa1ef4c2634c57297ba1120b1",
    "company_source": "78f525bcae479e50943e38616427f5f9852500a9164d5dd81a815ee8fd221af9",
    "ontology": "7e6f4d8a51a65907460f60aedb20dd96a15ddaa0e65ff707a0dd7aa58f7f96d7",
}
#: Illustrative only (F2): hardware words that occur in the missed HW blocks.  Not a proposal.
FIXTURE_F2_EXTRA_TERMS = ["HW", "전산장비", "예비장비", "예비부품"]
VARIANTS = ("v1_source_v4", "v2_source_v4", "v2_fixture_f1", "v2_fixture_f2")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_source(source: dict, extra_terms: list[str]) -> dict:
    value = deepcopy(source)
    nodes = {node["id"]: node for node in value["nodes"]}
    nodes["pref:onsite_cap"]["value"]["params"]["onsite_regions"] = "대구"
    hardware = nodes["excl:hardware"]["value"]
    hardware["requirement_terms"] = list(dict.fromkeys([*hardware["keywords"], *extra_terms]))
    return value


def frozen_of(raw: bytes, ontology: Any) -> tuple[dict, set[str], str]:
    snapshot = build_graph_snapshot(parse_company_knowledge_source(raw, ontology=ontology), ontology=ontology)
    nodes = snapshot.payload["nodes"]
    frozen = {"profile_facts": [{"fact_key": n["id"], "status": n["status"], "value": n["value"]} for n in nodes]}
    return frozen, {n["id"] for n in nodes}, snapshot.sha256


def probe_constraints(text: str, sha: str, key: str) -> list[CardRequirementConstraint]:
    locator = {"source_sha256": sha, "block_key": key}
    rows = [("text", text, None, "eq")]
    for match in re.finditer(r"([0-9]+)\s*명\s*(이상)?", text):
        rows.append(("count", int(match.group(1)), "person", "gte" if match.group(2) else "eq"))
    return [CardRequirementConstraint.model_validate({
        "kind": kind, "value": value, "unit": unit, "operator": operator, "fact_key": None,
        "quote": text, "locator": locator,
    }) for kind, value, unit, operator in rows]


def compare(constraint: CardRequirementConstraint, frozen: dict, known: set[str], rules: str, block: str):
    try:
        status, reason, fact_ids = constraint_comparison(constraint, frozen, known, rules=rules, block_text=block)
    except Exception as error:  # noqa: BLE001 - recorded as a probe outcome
        return {"status": "error", "reason_code": getattr(error, "code", type(error).__name__), "fact_ids": []}
    return {"status": status, "reason_code": reason, "fact_ids": fact_ids}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-dir", required=True, type=Path)
    parser.add_argument("--company-source", required=True, type=Path)
    parser.add_argument("--ontology", required=True, type=Path)
    args = parser.parse_args()
    paths = {
        "actual": args.eval_dir / "final" / "actual.v1.json",
        "gold": args.eval_dir / "gold.v1.json",
        "score": args.eval_dir / "final" / "score.v1.json",
        "company_source": args.company_source,
        "ontology": args.ontology,
    }
    digests = {name: sha256(path) for name, path in paths.items()}
    checks = {f"{name}_sha256": digests[name] == EXPECTED[name] for name in EXPECTED}
    if not all(checks.values()):
        print(json.dumps({"error": "input_mismatch", "checks": checks}, indent=2))
        return 2
    actual, gold, score = (load(paths[name]) for name in ("actual", "gold", "score"))
    ontology = parse_ontology(paths["ontology"].read_bytes())
    source_raw = paths["company_source"].read_bytes()
    source = json.loads(source_raw)
    companies: dict[str, tuple[dict, set[str], str]] = {}
    companies["source_v4"] = frozen_of(source_raw, ontology)
    for name, extra in (("fixture_f1", []), ("fixture_f2", FIXTURE_F2_EXTRA_TERMS)):
        raw = json.dumps(fixture_source(source, extra), ensure_ascii=False).encode("utf-8")
        companies[name] = frozen_of(raw, ontology)
    checks["graph_snapshot_matches_actual_company"] = companies["source_v4"][2] == actual["company_sha256"]
    if not checks["graph_snapshot_matches_actual_company"]:
        print(json.dumps({"error": "input_mismatch", "checks": checks}, indent=2))
        return 2
    plan = {
        "v1_source_v4": (COMPARE_RULES_V1, "source_v4"),
        "v2_source_v4": (COMPARE_RULES_V2, "source_v4"),
        "v2_fixture_f1": (COMPARE_RULES_V2, "fixture_f1"),
        "v2_fixture_f2": (COMPARE_RULES_V2, "fixture_f2"),
    }

    gold_docs = {doc["document_id"]: doc for doc in gold["documents"]}
    score_docs = {doc["document_id"]: doc for doc in score["documents"]}
    conditions = []
    totals: dict[str, Counter] = {variant: Counter() for variant in VARIANTS}
    for doc in actual["documents"]:
        doc_id = doc["document_id"]
        gdoc = gold_docs[doc_id]
        blocks: dict[str, tuple[str, str, str]] = {}
        for sdoc in gdoc["source_documents"]:
            for block in sdoc["blocks"]:
                blocks[block["unit_id"]] = (block["unit_id"].split(":")[1], block["unit_id"].rsplit(":", 1)[-1],
                                            block["text"])
        cards = {card["unit_id"]: card for card in gdoc["source_cards"]}
        owners: dict[str, list[str]] = {}
        for row in doc["unit_sources"]:
            for source_id in row["source_unit_ids"]:
                owners.setdefault(source_id, []).append(row["unit_id"])
        stored = {row["unit_id"]: row["reason_codes"] for row in doc["unit_decisions"]}
        for condition in gdoc["blocking_conditions"]:
            if condition["condition_id"] not in score_docs[doc_id]["missing_conditions"]:
                continue
            probes = []
            for source_id in condition["source_unit_ids"]:
                if source_id.startswith("block:"):
                    candidates = [blocks[source_id]] if source_id in blocks else []
                else:
                    sha = source_id.split(":")[1]
                    candidates = [(sha, block["block_key"], block["text"]) for block in cards[source_id]["blocks"]]
                for sha, key, text in candidates:
                    if not text.strip():
                        continue
                    for constraint in probe_constraints(text, sha, key):
                        row = {"source": source_id.rsplit(":", 1)[-1], "block_key": key, "kind": constraint.kind,
                               "places_in_block": sorted(resolve_places(text)[0])}
                        for variant, (rules, company) in plan.items():
                            frozen, known, _sha = companies[company]
                            row[variant] = compare(constraint, frozen, known, rules, text)
                        probes.append(row)
            outcome = {}
            for variant in VARIANTS:
                reasons = Counter(probe[variant]["reason_code"] for probe in probes)
                gaps = [probe for probe in probes if probe[variant]["status"] == "gap"]
                outcome[variant] = {
                    "condition_gap": bool(gaps),
                    "gap_probes": len(gaps),
                    "gap_fact_ids": sorted({key for probe in gaps for key in probe[variant]["fact_ids"]}),
                    "probe_reasons": dict(sorted(reasons.items())),
                }
                totals[variant].update(reasons)
            # a3: the stored covering units typed 계약 (contract_unaccepted) -- the unit fit a gap probe would give
            contract_units = sorted({
                unit for source_id in condition["source_unit_ids"] for unit in owners.get(source_id, [])
                if "contract_unaccepted" in stored.get(unit, [])
            })
            contract_fit = {}
            if contract_units:
                item = SimpleNamespace(type="계약", constraints=[object()], concept_candidates=[], unknowns=[])
                for variant, (rules, _company) in plan.items():
                    reasons = ["confirmed_contradiction", "contract_unaccepted"] if outcome[variant]["condition_gap"] \
                        else ["contract_unaccepted"]
                    contract_fit[variant] = _expected_fit(item, reasons, rules)
            conditions.append({
                "document_id": doc_id, "condition_id": condition["condition_id"], "probes": len(probes),
                "outcome": outcome, "contract_typed_covering_units": len(contract_units),
                "contract_unit_fit_with_condition_gap": contract_fit, "probe_rows": probes,
            })
    # Over-blocking scan: the same probes on EVERY gold source block of all 10 notices.  A gap
    # on a block outside every gold blocking condition is a candidate false blocker.
    scan = []
    for doc in actual["documents"]:
        doc_id = doc["document_id"]
        gdoc = gold_docs[doc_id]
        blocking_sources = {source for condition in gdoc["blocking_conditions"]
                            for source in condition["source_unit_ids"]}
        # one entry per (source sha, block key); a block cited by a gold blocking condition through
        # either its block id or its card counts as inside the condition
        units: dict[tuple[str, str], list[Any]] = {}
        for sdoc in gdoc["source_documents"]:
            for block in sdoc["blocks"]:
                entry = units.setdefault((block["unit_id"].split(":")[1], block["unit_id"].rsplit(":", 1)[-1]),
                                         [block["text"], False])
                entry[1] = entry[1] or block["unit_id"] in blocking_sources
        for card in gdoc["source_cards"]:
            for block in card["blocks"]:
                entry = units.setdefault((card["unit_id"].split(":")[1], block["block_key"]), [block["text"], False])
                entry[1] = entry[1] or card["unit_id"] in blocking_sources
        counts = {variant: Counter() for variant in VARIANTS}
        seen = {key for key, (text, _inside) in units.items() if text.strip()}
        for (sha, key), (text, in_blocking) in units.items():
            if (sha, key) not in seen:
                continue
            for variant, (rules, company) in plan.items():
                frozen, known, _sha = companies[company]
                kinds = set()
                for constraint in probe_constraints(text, sha, key):
                    row = compare(constraint, frozen, known, rules, text)
                    if row["status"] == "gap":
                        kinds.add("location" if "pref:onsite_cap" in row["fact_ids"]
                                  else "exclusion" if any(k.startswith("excl:") for k in row["fact_ids"])
                                  else "other")
                where = "in_gold_blocking" if in_blocking else "outside_gold_blocking"
                for kind in kinds:
                    counts[variant][f"{kind}_gap_blocks_{where}"] += 1
        scan.append({"document_id": doc_id, "gold_verdict": gdoc["verdict"],
                     "gold_blocking_conditions": len(gdoc["blocking_conditions"]), "blocks": len(seen),
                     **{variant: dict(sorted(counts[variant].items())) for variant in VARIANTS}})
    result = {
        "schema_version": "bidops.rl10-blocker-probes.v1",
        "inputs": {name: {"path_name": paths[name].name, "sha256": digests[name]} for name in paths}
        | {"place_table_sha256": PLACE_TABLE_SHA256,
           "graph_snapshot_sha256": {name: value[2] for name, value in companies.items()}},
        "input_checks": checks,
        "fixture_note": "fixture_f1/f2 are test fixtures, not confirmed company facts",
        "fixture_f2_extra_terms_count": len(FIXTURE_F2_EXTRA_TERMS),
        "summary": [
            {"document_id": row["document_id"], "condition_id": row["condition_id"],
             **{variant: row["outcome"][variant]["condition_gap"] for variant in VARIANTS}}
            for row in conditions
        ],
        "probe_reason_totals": {variant: dict(sorted(totals[variant].items())) for variant in VARIANTS},
        "all_blocks_gap_scan": scan,
        "conditions": conditions,
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
