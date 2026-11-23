"""Company wiki maintenance: the compiled "work-unit evidence map" and its ingest step.

The wiki keeps raw sources (past RFP requirements) apart from compiled knowledge. This
module owns the compiled layer:

- ``work-units.json`` (sidecar, not a page): the taxonomy of work units, which past
  requirement is evidence for which unit, and units confirmed to have no record.
- ``capabilities/work-units.md`` (hub) and ``capabilities/work-<topic>.md`` pages rendered
  from the sidecar, so a reader goes index -> hub -> topic page -> the cited requirement.
- ``log.txt``: append-only change log.

Ingest is a file contract. A model (outside this package) reads one project's
requirements and writes a mapping file; ``ingest-apply`` validates it, merges it into the
sidecar, re-renders the pages, appends the log and lints the tree. No transport here.

    python -m bid_deep_engine.wiki_tools init --root WIKI --taxonomy taxonomy.json
    python -m bid_deep_engine.wiki_tools ingest-apply --root WIKI --mapping mapping.json
    python -m bid_deep_engine.wiki_tools render --root WIKI [--allow P2023-10 ...]
    python -m bid_deep_engine.wiki_tools feedback-apply --root WIKI --feedback feedback.json
    python -m bid_deep_engine.wiki_tools lint --root WIKI
    python -m bid_deep_engine.wiki_tools check --root WIKI
    python -m bid_deep_engine.wiki_tools stats --root WIKI
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from bid_deep_engine.company.knowledge import lint_knowledge

SIDECAR = "work-units.json"
SIDECAR_SCHEMA = "bidops.wiki-work-units.v1"
MAPPING_SCHEMA = "bidops.wiki-ingest-mapping.v1"
LOG_FILE = "log.txt"
HUB_SLUG = "work-units"
PAGE_PREFIX = "work-"
INDEX_HEAD = "- 업무별 근거 지도"
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
UNIT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+(?:-[a-z0-9]+)*$")
PROJECT_RE = re.compile(r"^P\d{4}-\d{2}$")


class WikiToolError(ValueError):
    """Invalid sidecar, taxonomy or mapping. The message names the first problem."""


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _check_taxonomy(topics: list[dict]) -> set[str]:
    seen_topics: set[str] = set()
    units: set[str] = set()
    for topic in topics:
        tid = topic.get("id", "")
        if not ID_RE.match(tid) or tid in seen_topics or not topic.get("title"):
            raise WikiToolError(f"bad topic: {tid!r}")
        seen_topics.add(tid)
        for unit in topic.get("units", []):
            uid = unit.get("id", "")
            if not UNIT_RE.match(uid) or not uid.startswith(tid + ".") or uid in units or not unit.get("title"):
                raise WikiToolError(f"bad unit: {uid!r}")
            units.add(uid)
    return units


def load_sidecar(root: Path) -> dict:
    data = _read(root / SIDECAR)
    if data.get("schema") != SIDECAR_SCHEMA:
        raise WikiToolError("unexpected sidecar schema")
    _check_taxonomy(data["topics"])
    return data


def init(root: Path, taxonomy: dict) -> dict:
    _check_taxonomy(taxonomy["topics"])
    data = {"schema": SIDECAR_SCHEMA, "topics": taxonomy["topics"], "evidence": [], "no_record": [], "sources": {}}
    _write(root / SIDECAR, data)
    _log(root, f"init | 업무 단위 분류 {len(taxonomy['topics'])}개 주제")
    return data


def apply_mapping(data: dict, mapping: dict, *, today: str) -> dict:
    """Merge one project's mapping. Re-ingesting a project replaces its earlier evidence."""
    if mapping.get("schema") != MAPPING_SCHEMA:
        raise WikiToolError("unexpected mapping schema")
    project = mapping.get("project", "")
    if not PROJECT_RE.match(project):
        raise WikiToolError(f"bad project id: {project!r}")
    topics = {t["id"]: t for t in data["topics"]}
    for new in mapping.get("new_units", []):
        topic = topics.get(new.get("topic", ""))
        if topic is None:
            raise WikiToolError(f"new unit names an unknown topic: {new.get('topic')!r}")
        if not any(u["id"] == new["id"] for u in topic["units"]):
            topic["units"].append({"id": new["id"], "title": new["title"], "covers": new.get("covers", ""), "not": ""})
    units = _check_taxonomy(data["topics"])
    rows, seen = [], set()
    for item in mapping.get("assignments", []):
        req_id = str(item.get("req_id", "")).strip()
        if not req_id:
            raise WikiToolError("assignment without req_id")
        for unit in item.get("units", []):
            if unit not in units:
                raise WikiToolError(f"{project} {req_id}: unknown unit {unit!r}")
            if (req_id, unit) in seen:
                continue
            seen.add((req_id, unit))
            rows.append({"project": project, "req_id": req_id, "unit": unit})
    data["evidence"] = [e for e in data["evidence"] if e["project"] != project] + rows
    data["sources"][project] = {
        "requirements": len(mapping.get("assignments", [])),
        "unassigned": sum(1 for a in mapping.get("assignments", []) if not a.get("units")),
        "source": mapping.get("source", ""),
        "ingested_at": today,
    }
    return data


def _front(slug: str, title: str, today: str, sources: list[str]) -> str:
    lines = ["---", f"slug: {slug}", f"title: {title}", "kind: capability", "tags: [업무 근거]",
             f"updated: {today}", "confidence: confirmed", "sources:"]
    lines += [f"  - {s}" for s in sources] + ["---", ""]
    return "\n".join(lines)


def render(root: Path, data: dict, *, today: str, allow: set[str] | None = None) -> list[str]:
    """Write the hub and one page per topic. ``allow`` limits evidence to those projects."""
    evidence: dict[str, dict[str, list[str]]] = {}
    for row in data["evidence"]:
        if allow is not None and row["project"] not in allow:
            continue
        evidence.setdefault(row["unit"], {}).setdefault(row["project"], []).append(row["req_id"])
    no_record: dict[str, list[dict]] = {}
    for row in data.get("no_record", []):
        no_record.setdefault(row["unit"], []).append(row)
    folder = root / "capabilities"
    for old in folder.glob(f"{PAGE_PREFIX}*.md"):
        old.unlink()
    source = [f"{SIDECAR} (과거 수주 사업 RFP 요구사항 분류, 사용자 지시 2026-10-25 수주 실적 RFP = 수행 범위)"]
    hub = [_front(HUB_SLUG, "업무별 근거 지도", today, source),
           "## 읽는 법", "",
           "- 공고의 요구사항이 어떤 종류의 업무인지 아래 주제에서 찾고, 주제 페이지에서 업무 단위별로 근거가 되는 실적과 요구사항 번호를 본다.",
           "- 근거의 원문은 실적 페이지의 `요구사항 전체 목록(원문)`에서 그 번호의 줄을 읽는다.",
           "- 업무 단위에 실적이 없으면 `기록 없음`이다. 그 업무는 수행 기록이 없다는 뜻이다.", "",
           "## 주제", ""]
    written = []
    for topic in data["topics"]:
        slug = PAGE_PREFIX + topic["id"]
        body = [_front(slug, f"업무 근거 — {topic['title']}", today, source),
                "## 범위", "", f"- {topic.get('scope', '')}", f"- 전체 지도: [[{HUB_SLUG}]]", "",
                "## 업무 단위별 근거", ""]
        summary = []
        for unit in topic["units"]:
            found = evidence.get(unit["id"], {})
            summary.append(f"{unit['title']}({len(found)})")
            body += [f"### {unit['title']}", "", f"- 단위 id: `{unit['id']}`"]
            if unit.get("covers"):
                body.append(f"- 범위: {unit['covers']}" + (f" 다른 단위: {unit['not']}" if unit.get("not") else ""))
            if found:
                for project in sorted(found):
                    body.append(f"- [[{project}]] " + ", ".join(found[project]))
            else:
                body.append("- 기록 없음")
            for row in no_record.get(unit["id"], []):
                body.append(f"- 기록 없음으로 확인: {row['note']} ({row.get('as_of', '')})")
            body.append("")
        (folder / f"{slug}.md").write_text("\n".join(body), encoding="utf-8")
        written.append(slug)
        hub.append(f"- [[{slug}]] {topic['title']} — " + ", ".join(summary))
    hub += ["", "괄호 안 숫자는 근거가 있는 실적 수다.", ""]
    (folder / f"{HUB_SLUG}.md").write_text("\n".join(hub), encoding="utf-8")
    _update_index(root, written)
    return written


def _update_index(root: Path, slugs: list[str]) -> None:
    path = root / "INDEX.md"
    lines = path.read_text(encoding="utf-8").split("\n")
    kept, skipping = [], False
    for line in lines:
        if line.startswith(INDEX_HEAD):
            skipping = True
            continue
        if skipping and (line.startswith("- ") or line.startswith("#")):
            skipping = False
        if not skipping:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    block = [INDEX_HEAD, f"  - [[{HUB_SLUG}]] 업무 단위에서 근거 실적·요구사항 번호로 가는 지도"]
    block += [f"    - [[{slug}]]" for slug in slugs]
    path.write_text("\n".join(kept + block) + "\n", encoding="utf-8")


def _log(root: Path, text: str, *, today: str | None = None) -> None:
    with open(root / LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(f"{today or date.today().isoformat()} | {text}\n")


FEEDBACK_SCHEMA = "bidops.wiki-feedback.v1"


def apply_feedback(data: dict, feedback: dict, *, today: str) -> dict:
    """Write back what an analysis confirmed. Only items a person marked ``approved`` are applied.

    ``no_record``: the analysis looked for this unit's work and found no past record; the unit
    page then says so with the date and the notice it came from. ``missing_unit``: work the
    taxonomy has no unit for; the unit is added (empty) so the next ingest can file under it.
    """
    if feedback.get("schema") != FEEDBACK_SCHEMA:
        raise WikiToolError("unexpected feedback schema")
    topics = {t["id"]: t for t in data["topics"]}
    units = _check_taxonomy(data["topics"])
    counts = {"no_record": 0, "missing_unit": 0, "skipped": 0}
    for item in feedback.get("items", []):
        if item.get("approved") is not True:
            counts["skipped"] += 1
            continue
        kind = item.get("type")
        if kind == "no_record":
            if item.get("unit") not in units:
                raise WikiToolError(f"feedback names an unknown unit: {item.get('unit')!r}")
            row = {"unit": item["unit"], "note": str(item.get("note", "")).strip(), "as_of": today,
                   "source": feedback.get("notice", "")}
            if not any(r["unit"] == row["unit"] and r["note"] == row["note"] for r in data.setdefault("no_record", [])):
                data["no_record"].append(row)
                counts["no_record"] += 1
        elif kind == "missing_unit":
            topic = topics.get(item.get("topic", ""))
            uid = item.get("id", "")
            if topic is None or not UNIT_RE.match(uid) or not uid.startswith(topic["id"] + ".") or not item.get("title"):
                raise WikiToolError(f"bad missing_unit item: {uid!r}")
            if uid not in units:
                topic["units"].append({"id": uid, "title": item["title"], "covers": item.get("note", ""), "not": ""})
                units.add(uid)
                counts["missing_unit"] += 1
        else:
            raise WikiToolError(f"unknown feedback type: {kind!r}")
    return counts


def _norm_title(text: str) -> str:
    return re.sub(r"[\s·ㆍ/,()\-]+", "", text or "")


def check_content(root: Path, data: dict) -> dict:
    """Content health of the compiled layer (the form lint does not look at these)."""
    units = [(t["id"], u) for t in data["topics"] for u in t["units"]]
    titles: dict[str, list[str]] = {}
    slugs: dict[str, list[str]] = {}
    for _, unit in units:
        titles.setdefault(_norm_title(unit["title"]), []).append(unit["id"])
        slugs.setdefault(unit["id"].split(".", 1)[1], []).append(unit["id"])
    used = {e["unit"] for e in data["evidence"]}
    lines: dict[str, set[str]] = {}
    for page in (root / "portfolio").glob("P*.md"):
        lines[page.stem] = set(re.findall(r"^- (\S+) ", page.read_text(encoding="utf-8"), flags=re.M))
    listed = {p for p, ids in lines.items() if ids and "요구사항 전체 목록" in (root / "portfolio" / f"{p}.md").read_text(encoding="utf-8")}
    dangling = sorted({f"{e['project']} {e['req_id']}" for e in data["evidence"]
                       if e["project"] not in lines or e["req_id"] not in lines[e["project"]]})
    contradicted = sorted({r["unit"] for r in data.get("no_record", []) if r["unit"] in used})
    return {
        "duplicate_titles": sorted(v for v in titles.values() if len(v) > 1),
        "same_slug_in_other_topic": sorted(v for v in slugs.values() if len(v) > 1),
        "units_without_evidence": sorted(u["id"] for _, u in units if u["id"] not in used),
        "evidence_without_source_line": dangling,
        "no_record_but_has_evidence": contradicted,
        "pages_with_requirement_list_not_ingested": sorted(listed - set(data["sources"])),
        "ingested_without_page": sorted(set(data["sources"]) - set(lines)),
    }


def stats(data: dict) -> dict:
    units = [u["id"] for t in data["topics"] for u in t["units"]]
    covered = {e["unit"] for e in data["evidence"]}
    return {
        "topics": len(data["topics"]), "units": len(units), "units_with_evidence": len(covered & set(units)),
        "evidence_rows": len(data["evidence"]), "projects": len(data["sources"]),
        "requirements": sum(s["requirements"] for s in data["sources"].values()),
        "unassigned": sum(s.get("unassigned", 0) for s in data["sources"].values()),
        "no_record_notes": len(data.get("no_record", [])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bid_deep_engine.wiki_tools")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "ingest-apply", "feedback-apply", "render", "lint", "check", "stats"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--root", required=True)
        cmd.add_argument("--today", default=date.today().isoformat())
    sub.choices["init"].add_argument("--taxonomy", required=True)
    sub.choices["ingest-apply"].add_argument("--mapping", required=True, nargs="+")
    sub.choices["render"].add_argument("--allow", nargs="*")
    sub.choices["feedback-apply"].add_argument("--feedback", required=True)
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.command == "init":
            init(root, _read(Path(args.taxonomy)))
        elif args.command == "ingest-apply":
            data = load_sidecar(root)
            for name in args.mapping:
                mapping = _read(Path(name))
                apply_mapping(data, mapping, today=args.today)
                source = data["sources"][mapping["project"]]
                _log(root, f"ingest | {mapping['project']} | 요구사항 {source['requirements']}건, 미분류 {source['unassigned']}건",
                     today=args.today)
            _write(root / SIDECAR, data)
            render(root, data, today=args.today)
        elif args.command == "feedback-apply":
            data = load_sidecar(root)
            feedback = _read(Path(args.feedback))
            counts = apply_feedback(data, feedback, today=args.today)
            _write(root / SIDECAR, data)
            _log(root, f"feedback | {feedback.get('notice', '')} | 기록 없음 {counts['no_record']}건, 새 단위 {counts['missing_unit']}건, "
                       f"미승인 {counts['skipped']}건", today=args.today)
            render(root, data, today=args.today)
        elif args.command == "check":
            print(json.dumps(check_content(root, load_sidecar(root)), ensure_ascii=False, indent=1))
            return 0
        elif args.command == "render":
            data = load_sidecar(root)
            render(root, data, today=args.today, allow=set(args.allow) if args.allow is not None else None)
        if args.command in {"ingest-apply", "feedback-apply", "render", "lint"}:
            report = lint_knowledge(root)
            for line in report.errors:
                print(f"error: {line}", file=sys.stderr)
            print(json.dumps({"pages": report.pages, "errors": len(report.errors), "warnings": len(report.warnings)}))
            return 1 if report.errors else 0
        print(json.dumps(stats(load_sidecar(root)), ensure_ascii=False))
        return 0
    except (WikiToolError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
