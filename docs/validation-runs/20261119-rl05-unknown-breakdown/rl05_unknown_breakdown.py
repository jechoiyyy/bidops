"""RL-05 unknown card breakdown (launch-hardening D-2) -- replay of stored outputs, no model call.

Reads the stored RL-05 evaluation files (Git outside), the Rootlab company
source v4 and ontology v2, and the RL-03 product functions (imported
read-only from ``web/backend``; nothing is reimplemented), then prints a
deterministic JSON breakdown of the 447 card states:

* stored (exact): matrix ``fit_status`` and compare ``reason_codes`` per unit
  as exported by ``export-evaluation --actual`` (never recomputed);
* reconstructed from unit text (deterministic, approximate): allowlisted fact
  anchors (``fact_anchor_matches``), concept candidates
  (``card_expected_concepts``), graph paths (``search_graph_paths``) and the
  constraint-independent concept reasons (``_concept_reasons``) -- checked
  against the stored codes;
* probes: product ``constraint_comparison`` on ideal constraints built from
  the gold blocking blocks (block text verbatim as quote), to show at which
  compare step a perfect extraction still stops.

Output holds identifiers, codes and counts only -- no notice text, no company
values.  Needs the backend's Python dependencies (pydantic etc., no new
package).  Usage (repository root)::

    <backend venv python> docs/validation-runs/20261119-rl05-unknown-breakdown/rl05_unknown_breakdown.py \
        --eval-dir <main checkout>/.sdlc/local-runtime/rl-evaluation-20261019 \
        --company-source <fixtures>/company/rootlab/rootlab.source.v4.json \
        --ontology <fixtures>/company/rootlab/ontology.v2.json > breakdown.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
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
from app.deep_review.services.card_analysis import (  # noqa: E402
    CARD_FACT_ANCHORS,
    CARD_FACT_KINDS,
    fact_anchor_matches,
    resolve_fact_key,
)
from app.deep_review.services.card_compare import (  # noqa: E402
    _concept_reasons,
    _regions,
    _scope_unverified,
    _validated_graph_context,
    constraint_comparison,
)
from app.deep_review.services.company_analysis_input import (  # noqa: E402
    CARD_COMPARE_FACT_PATHS,
    CompanyAnalysisError,
    card_expected_concepts,
)
from app.deep_review.services.company_knowledge_retrieval import (  # noqa: E402
    match_concepts,
    normalize_graph,
    search_graph_paths,
)

PATH_LIMIT = 32  # analysis-policy-luna-rl-v11 chunking.path_limit_per_requirement

#: Subject label of each allowlisted fact key (display grouping only).
FACT_SUBJECT = {
    "staff:onsite": "상주 인력·장소",
    "staff:total": "인력 규모",
    "staff:design_publishing": "인력 규모",
    "qual:direct_production": "자격·인증",
    "qual:procurement_1468": "자격·인증",
    "qual:sme_certificate": "자격·인증",
    "qual:sw_business": "자격·인증",
    "qual:credit_rating": "자격·인증",
    "qual:infosec_cert": "자격·인증",
    "qual:sanction_free": "자격·인증",
    "qual:branch": "소재지·지역제한",
    "pref:solo_cap": "사업 금액",
    "pref:consortium": "공동수급·하도급",
    "pref:subcontract": "공동수급·하도급",
}
#: Analysis-only lexical markers for subjects that have NO allowlisted fact key.
#: Not a product rule; only used to count how many cards mention the subject.
LEXICAL_SUBJECTS = {
    "[어휘] 수행 실적": ("실적",),
    "[어휘] HW·장비 유지관리": ("하드웨어", "HW", "H/W", "전산장비", "부품"),
}
STAGES = (
    "S1 추출 항목 격리(extract_rejected)",
    "S2 계약 유형 고정 unknown(contract_unaccepted)",
    "S3 확인 사실과 일치한 제약 있음(confirmed_match)",
    "S4 회사 사실에 닿았으나 판단 불가(unsupported/scope/proposed/unknown_fact)",
    "S5 회사 사실 연결 없음(unmapped만)",
    "S6 원자 조건 미완(incomplete_unit만)",
    "S0 대조 행 없음",
)
FACT_LEVEL = {"unsupported_comparison", "scope_unverified", "proposed_fact", "unknown_fact"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stage_of(codes: list[str]) -> str:
    if not codes:
        return STAGES[6]
    if "extract_rejected" in codes:
        return STAGES[0]
    if "contract_unaccepted" in codes:
        return STAGES[1]
    if "confirmed_match" in codes:
        return STAGES[2]
    if FACT_LEVEL & set(codes):
        return STAGES[3]
    if "unmapped" in codes:
        return STAGES[4]
    return STAGES[5]


def card_prefix(unit_id: str) -> str:
    match = re.match(r"[A-Z]+", unit_id.rsplit(":", 1)[-1])
    return match.group(0) if match else "?"


def lexical_subjects(text: str) -> list[str]:
    upper = text.upper()
    return sorted(label for label, terms in LEXICAL_SUBJECTS.items() if any(term.upper() in upper for term in terms))


def graph_inputs(snapshot_payload: dict[str, Any], ontology: Any) -> tuple[list[dict], list[dict]]:
    nodes = [
        {key: node[key] for key in ("id", "type", "label", "concept_id", "status", "origin", "value")}
        | {"evidence_ids": []}
        for node in snapshot_payload["nodes"]
    ]
    edges = [
        {key: edge[key] for key in ("id", "type", "from_id", "to_id", "status", "origin")} | {"evidence_ids": []}
        for edge in snapshot_payload["edges"]
    ]
    return normalize_graph(nodes, edges, ontology=ontology.concepts)


def probe(block_text: str, source_sha: str, block_key: str, frozen: dict, known: set[str]) -> list[dict[str, Any]]:
    """Ideal-extraction probes on one block (quote = the block text verbatim)."""

    rows: list[dict[str, Any]] = []
    locator = {"source_sha256": source_sha, "block_key": block_key}
    candidates = [("text", block_text, None, "eq")]
    for match in re.finditer(r"([0-9]+)\s*명\s*(이상)?", block_text):
        candidates.append(("count", int(match.group(1)), "person", "gte" if match.group(2) else "eq"))
    for kind, value, unit, operator in candidates:
        constraint = CardRequirementConstraint.model_validate({
            "kind": kind, "value": value, "unit": unit, "operator": operator,
            "fact_key": None, "quote": block_text, "locator": locator,
        })
        anchored = sorted(key for key in CARD_FACT_ANCHORS if fact_anchor_matches(key, block_text))
        resolved = resolve_fact_key(constraint)
        try:
            status, reason, _ = constraint_comparison(constraint, frozen, known)
        except Exception as error:  # noqa: BLE001 - recorded as a probe outcome
            status, reason = "error", getattr(error, "code", type(error).__name__)
        rows.append({
            "block_key": block_key, "kind": kind, "operator": operator, "anchored_fact_keys": anchored,
            "resolved_fact_key": resolved, "status": status, "reason_code": reason,
            "scope_term_rule": bool(resolved) and _scope_unverified(resolved, constraint),
            "regions_in_quote": sorted(_regions(block_text)),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-dir", required=True, type=Path)
    parser.add_argument("--company-source", required=True, type=Path)
    parser.add_argument("--ontology", required=True, type=Path)
    args = parser.parse_args()
    ev = args.eval_dir

    paths = {
        "actual": ev / "final" / "actual.v1.json",
        "gold": ev / "gold.v1.json",
        "score": ev / "final" / "score.v1.json",
        "receipt": ev / "final" / "receipt.json",
        "selection": ev / "selection.v1.json",
        "company_source": args.company_source,
        "ontology": args.ontology,
    }
    digests = {name: sha256(path) for name, path in paths.items()}
    receipt = load(paths["receipt"])
    actual = load(paths["actual"])
    gold = load(paths["gold"])
    score = load(paths["score"])
    checks = {
        "actual_matches_receipt": digests["actual"] == receipt["actual_sha256"],
        "gold_matches_receipt": digests["gold"] == receipt["gold_sha256"],
        "selection_matches_receipt": digests["selection"] == receipt["selection_sha256"],
        "score_gold_input_matches": score["input_sha256"]["gold"] == receipt["gold_sha256"],
    }
    ontology = parse_ontology(paths["ontology"].read_bytes())
    source = parse_company_knowledge_source(paths["company_source"].read_bytes(), ontology=ontology)
    snapshot = build_graph_snapshot(source, ontology=ontology)
    checks["ontology_canonical_matches_actual"] = ontology.sha256 == actual["ontology_sha256"]
    checks["graph_snapshot_matches_actual_company"] = snapshot.sha256 == actual["company_sha256"]
    if not all(checks.values()):
        print(json.dumps({"error": "input_mismatch", "checks": checks}, indent=2))
        return 2

    payload = snapshot.payload
    node_list, edge_list = graph_inputs(payload, ontology)
    frozen = {"profile_facts": [
        {"fact_key": node["id"], "status": node["status"], "value": node["value"]} for node in payload["nodes"]
    ]}
    known = {node["id"] for node in payload["nodes"]}
    fact_status = {key: next((n["status"] for n in payload["nodes"] if n["id"] == key), "absent")
                   for key in CARD_COMPARE_FACT_PATHS}
    excluded_nodes = sorted(n["id"] for n in payload["nodes"] if n["id"].startswith("excl:"))
    concept_label_hits = {}
    for node_id in [*excluded_nodes, "pref:onsite_cap"]:
        node = next(n for n in payload["nodes"] if n["id"] == node_id)
        concept = ontology.concepts_by_id[node["concept_id"]]
        concept_label_hits[node_id] = {
            "concept_id": concept.id, "alias_count": len(concept.aliases), "label_chars": len(concept.label),
            "status": node["status"], "type": node["type"], "allowlisted": node_id in CARD_COMPARE_FACT_PATHS,
        }

    gold_docs = {doc["document_id"]: doc for doc in gold["documents"]}
    score_docs = {doc["document_id"]: doc for doc in score["documents"]}
    block_text: dict[str, str] = {}
    card_blocks: dict[str, list[dict[str, str]]] = {}
    card_meta: dict[str, dict[str, Any]] = {}
    for doc in gold["documents"]:
        for block in doc["source_documents"][0]["blocks"] if len(doc["source_documents"]) == 1 else []:
            block_text[block["unit_id"]] = block["text"]
        for card in doc["source_cards"]:
            card_blocks[card["unit_id"]] = card["blocks"]
            card_meta[card["unit_id"]] = {"prefix": card_prefix(card["unit_id"]),
                                          "category": (card.get("card") or {}).get("category")}

    totals = Counter()
    code_cards = Counter()
    code_units_all = Counter()
    stage_cards = Counter()
    by_notice: list[dict[str, Any]] = []
    prefix_stage: dict[str, Counter] = defaultdict(Counter)
    subject_stage: dict[str, Counter] = defaultdict(Counter)
    subject_cards = Counter()
    combo_cards = Counter()
    consistency = Counter()
    unmapped_origin = Counter()
    anchor_vs_stage: dict[str, Counter] = defaultdict(Counter)
    unit_rows: dict[str, dict[str, Any]] = {}
    concept_unmapped = Counter()
    mismatches: list[dict[str, Any]] = []
    multi_anchor: dict[str, Counter] = defaultdict(Counter)

    for doc in actual["documents"]:
        doc_id = doc["document_id"]
        decisions = {row["unit_id"]: row for row in doc["unit_decisions"]}
        sources = {row["unit_id"]: row["source_unit_ids"] for row in doc["unit_sources"]}
        unit_texts: dict[str, list[str]] = {}
        for unit_id, owned in sources.items():
            if unit_id.startswith("card:"):
                unit_texts[unit_id] = [b["text"] for b in card_blocks.get(unit_id, [])]
            else:
                unit_texts[unit_id] = [block_text.get(block_id, "") for block_id in owned]
        requirements = [
            {"id": unit_id, "text": "\n".join(texts), "concept_ids": match_concepts("\n".join(texts), ontology),
             "mandatory": None, "source_units": [], "document_requirement_ids": []}
            for unit_id, texts in unit_texts.items()
        ]
        search = search_graph_paths(requirements, node_list, edge_list, path_limit_per_requirement=PATH_LIMIT)
        gpaths, gnodes, gedges = _validated_graph_context(search["graph_paths"], node_list, edge_list, set())
        notice = Counter()
        notice_codes = Counter()
        for unit_id, texts in unit_texts.items():
            row = decisions[unit_id]
            codes = list(row["reason_codes"])
            text = "\n".join(texts)
            anchors = sorted(key for key in CARD_FACT_ANCHORS if fact_anchor_matches(key, text))
            try:
                candidates = [c["concept_id"] for c in card_expected_concepts(texts, ontology)]
                inexpressible = False
            except CompanyAnalysisError:
                candidates, inexpressible = [], True
            item = SimpleNamespace(unit_id=unit_id,
                                   concept_candidates=[SimpleNamespace(concept_id=c) for c in candidates])
            concept_reasons = _concept_reasons(item, gpaths, gnodes, gedges, set())
            predicted_unmapped = "unmapped" in concept_reasons
            predicted_partial = "partial_path" in concept_reasons
            rejected = "extract_rejected" in codes
            if not rejected:
                consistency["checked_units"] += 1
                for concept_id in candidates:
                    single = SimpleNamespace(unit_id=unit_id, concept_candidates=[SimpleNamespace(concept_id=concept_id)])
                    if "unmapped" in _concept_reasons(single, gpaths, gnodes, gedges, set()):
                        concept_unmapped[concept_id] += 1
                if predicted_unmapped and "unmapped" not in codes:
                    consistency["predicted_concept_unmapped_but_not_stored"] += 1
                    mismatches.append({"document_id": doc_id, "unit": unit_id.split(":")[0] + ":" + unit_id[-12:],
                                       "stored": codes, "predicted_concept_reasons": sorted(set(concept_reasons))})
                if predicted_partial and "partial_path" not in codes:
                    consistency["predicted_partial_but_not_stored"] += 1
                if inexpressible:
                    consistency["inexpressible_concepts"] += 1
                if "unmapped" in codes:
                    unmapped_origin["concept_unmapped_predicted" if predicted_unmapped
                                    else "constraint_only(no unique allowlisted anchor)"] += 1
            for code in codes:
                code_units_all[code] += 1
            unit_rows[unit_id] = {
                "document_id": doc_id, "kind": unit_id.split(":", 1)[0], "fit_status": row["fit_status"],
                "reason_codes": codes, "stage": stage_of(codes), "anchors": anchors,
                "regions_in_text": sorted(_regions(text)), "concept_candidate_count": len(candidates),
                "concept_reasons_predicted": sorted(set(concept_reasons)),
                "extract_present": row["normalized_requirement"] is not None,
            }
            if not unit_id.startswith("card:"):
                continue
            totals["cards"] += 1
            totals[f"fit_{row['fit_status']}"] += 1
            stage = stage_of(codes)
            stage_cards[stage] += 1
            notice[stage] += 1
            combo_cards[" + ".join(codes) or "(없음)"] += 1
            for code in codes:
                code_cards[code] += 1
                notice_codes[code] += 1
            prefix_stage[card_meta.get(unit_id, {}).get("prefix", "?")][stage] += 1
            subjects = sorted({FACT_SUBJECT[key] for key in anchors}) + lexical_subjects(text)
            for subject in subjects or ["(회사 사실 주제 없음)"]:
                subject_cards[subject] += 1
                subject_stage[subject][stage] += 1
            anchor_vs_stage["허용 사실 앵커 있음" if anchors else "허용 사실 앵커 없음"][stage] += 1
            if anchors:
                # a block quoted whole with >=2 text-compatible anchors resolves to None (unmapped)
                multi = any(
                    sum(1 for key in CARD_FACT_ANCHORS if "text" in CARD_FACT_KINDS[key]
                        and fact_anchor_matches(key, block)) >= 2
                    for block in texts
                )
                multi_anchor["카드 안에 앵커 2개 이상인 블록 있음" if multi else "없음"][stage] += 1
        by_notice.append({
            "document_id": doc_id, "cards": sum(notice.values()), "segments": len(unit_texts) - sum(notice.values()),
            "model_verdict": doc["verdict"], "gold_verdict": gold_docs[doc_id]["verdict"],
            "gold_blocking": len(gold_docs[doc_id]["blocking_conditions"]),
            "missed_blocking": len(score_docs[doc_id]["missing_conditions"]),
            "stages": dict(sorted(notice.items())), "codes": dict(sorted(notice_codes.items())),
        })

    # --- gold card states that are not unknown (scored sample of 100) ---------------
    gold_non_unknown = []
    for doc in gold["documents"]:
        for row in doc["card_states"]:
            if row["status"] != "unknown":
                unit = unit_rows.get(row["unit_id"], {})
                gold_non_unknown.append({
                    "document_id": doc["document_id"], "card": row["unit_id"].rsplit(":", 1)[-1],
                    "gold": row["status"], "model": unit.get("fit_status"), "reason_codes": unit.get("reason_codes"),
                    "stage": unit.get("stage"), "anchors": unit.get("anchors"),
                })

    # --- the 7 missed blocking conditions -------------------------------------------
    traces = []
    for doc in actual["documents"]:
        doc_id = doc["document_id"]
        owners: dict[str, list[str]] = defaultdict(list)
        for row in doc["unit_sources"]:
            for source_id in row["source_unit_ids"]:
                owners[source_id].append(row["unit_id"])
        for condition in gold_docs[doc_id]["blocking_conditions"]:
            if condition["condition_id"] not in score_docs[doc_id]["missing_conditions"]:
                continue
            covered, uncovered, units, probes = [], [], [], []
            for source_id in condition["source_unit_ids"]:
                (covered if source_id in owners else uncovered).append(source_id.rsplit(":", 1)[-1])
                for unit_id in owners.get(source_id, []):
                    unit = unit_rows[unit_id]
                    units.append({"source": source_id.rsplit(":", 1)[-1], "unit": unit_id.split(":")[0] + ":" + unit_id[-12:]}
                                 | {k: unit[k] for k in ("fit_status", "reason_codes", "stage", "anchors",
                                                         "regions_in_text", "concept_reasons_predicted")})
                # probes on the condition's own text blocks (block ids) and card cells with an anchor
                blocks = []
                if source_id.startswith("block:"):
                    blocks.append((source_id.split(":")[1], source_id.rsplit(":", 1)[-1], block_text.get(source_id, "")))
                else:
                    sha = source_id.split(":")[1]
                    blocks.extend((sha, b["block_key"], b["text"]) for b in card_blocks.get(source_id, [])
                                  if any(fact_anchor_matches(k, b["text"]) for k in CARD_FACT_ANCHORS)
                                  or lexical_subjects(b["text"]))
                for sha, key, text in blocks:
                    if text.strip():
                        probes.extend({"source": source_id.rsplit(":", 1)[-1]} | p
                                      for p in probe(text, sha, key, frozen, known))
            traces.append({
                "document_id": doc_id, "condition_id": condition["condition_id"],
                "source_ids_covered_by_units": covered, "source_ids_not_in_any_unit": uncovered,
                "units": units, "probes": probes,
            })

    probe_outcomes = Counter(
        (p["resolved_fact_key"] or "-", p["kind"], p["status"], p["reason_code"], p["scope_term_rule"])
        for trace in traces for p in trace["probes"]
    )
    result = {
        "schema_version": "bidops.rl05-unknown-breakdown.v1",
        "inputs": {name: {"path_name": paths[name].name, "sha256": digests[name]} for name in paths}
        | {"ontology_canonical_sha256": ontology.sha256, "graph_snapshot_sha256": snapshot.sha256},
        "input_checks": checks,
        "company_allowlist_fact_status": fact_status,
        "unallowlisted_company_facts": concept_label_hits,
        "totals": dict(totals),
        "units_all_reason_codes": dict(code_units_all.most_common()),
        "cards_by_reason_code": dict(code_cards.most_common()),
        "cards_by_stage": {stage: stage_cards[stage] for stage in STAGES},
        "cards_by_code_combination": dict(combo_cards.most_common()),
        "cards_by_anchor_presence_and_stage": {k: dict(sorted(v.items())) for k, v in sorted(anchor_vs_stage.items())},
        "anchored_cards_by_multi_anchor_block_and_stage": {k: dict(sorted(v.items())) for k, v in sorted(multi_anchor.items())},
        "cards_by_subject": dict(subject_cards.most_common()),
        "cards_by_subject_and_stage": {k: dict(sorted(v.items())) for k, v in sorted(subject_stage.items())},
        "cards_by_requirement_prefix_and_stage": {
            k: dict(sorted(v.items())) for k, v in sorted(prefix_stage.items(), key=lambda kv: -sum(kv[1].values()))
        },
        "unmapped_origin_non_rejected_units": dict(unmapped_origin),
        "reconstruction_consistency": dict(consistency),
        "reconstruction_mismatches": mismatches,
        "concept_unmapped_units_by_concept": dict(concept_unmapped.most_common()),
        "by_notice": by_notice,
        "gold_card_states_not_unknown": gold_non_unknown,
        "missed_blocking_traces": traces,
        "probe_outcomes": [
            {"resolved_fact_key": k[0], "kind": k[1], "status": k[2], "reason_code": k[3],
             "scope_term_rule": k[4], "count": n}
            for k, n in sorted(probe_outcomes.items())
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
