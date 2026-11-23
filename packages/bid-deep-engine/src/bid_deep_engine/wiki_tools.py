"""Company wiki maintenance: the compiled "work-unit evidence map" and its ingest step.

The wiki keeps raw sources (past RFP requirements) apart from compiled knowledge. This
module owns the compiled layer:

- ``work-units.json`` (sidecar, not a page): the taxonomy of work units, which past
  requirement is evidence for which unit, and units confirmed to have no record.
- ``capabilities/work-units.md`` (hub) and ``capabilities/work-<topic>.md`` pages rendered
  from the sidecar, so a reader goes index -> hub -> topic page -> the cited requirement.
- ``log.txt``: append-only change log.

Ingest is a file contract with one prompt per project. ``ingest-prompt`` builds the prompt
(instructions, taxonomy, the project's requirements); the caller sends it to the model;
``ingest-validate`` checks the answer and, when it is wrong, writes the one allowed
second-attempt prompt naming the problems; ``ingest-apply`` merges a valid mapping into the
sidecar, re-renders the pages, appends the log and lints the tree. No transport here.

    python -m bid_deep_engine.wiki_tools init --root WIKI --taxonomy taxonomy.json
    python -m bid_deep_engine.wiki_tools ingest-prompt --root WIKI --source requirements.json > prompt.txt
    python -m bid_deep_engine.wiki_tools ingest-validate --root WIKI --source requirements.json \\
        --response response.txt --out mapping.json --repair-prompt retry.txt
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

import yaml

from bid_deep_engine.runner import document_from_blocks
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


INGEST_PROMPT_HEAD = """# 작업: 과거 수주 사업의 요구사항을 업무 단위로 분류

아래 "분류표"와 "요구사항"만 보고, 요구사항 하나하나가 어떤 종류의 업무(업무 단위)를 담고 있는지 분류한다. 도구를 쓰거나 파일을 읽지 않는다. 답은 JSON 객체 하나만 출력한다(설명·코드 블록 표시 없이).

## 분류 기준

1. 요구사항을 업무 단위로 나눈다. 한 요구사항에 여러 업무가 들어 있는 경우가 많다(예: "하자 및 유지보수" = 하자보수 + 장애 대응 + 교육).
2. 요구사항이 실제로 담고 있는 업무 단위 id를 분류표에서 모두 고른다.
   - 같은 단위: 실무자가 같은 일이라고 부르는 것. 주기·횟수, 기간·기한, 수량, 도구·제품·매체, 서식·산출물 이름, 법령·지침 이름, 알림 채널, 대상 이름의 차이는 단위를 나누는 이유가 아니다.
   - 다른 단위: 활동 자체가 다르거나 그 일이 생기는 계기가 다른 것.
3. 요구사항 본문이 그 업무를 실제로 요구할 때만 고른다. 주제가 비슷하다거나 요구사항 번호의 접두어만 보고 고르지 않는다. 제목뿐이거나 내용이 없는 줄에는 아무것도 고르지 않는다. `name`·`definition`이 비어 있으면 `details`를 읽는다.
4. 하드웨어 작업(장비 수리, 부품 교체, 예비 장비, 물리 설치·이전)은 같은 요구사항의 소프트웨어 단위와 별도로 하드웨어 주제의 단위에도 넣는다.
5. 어느 단위에도 맞지 않는 업무가 있으면 가장 가까운 주제 아래에 새 단위를 제안한다. 실무자가 같은 일이라고 부를 기존 단위가 있으면 그것을 쓴다. 새 단위는 꼭 필요할 때만 만든다.

## 출력 형식

{"schema": "bidops.wiki-ingest-mapping.v1", "project": "<요구사항 자료의 project>", "title": "<요구사항 자료의 title>", "source": "과거 수주 사업 RFP 요구사항", "assignments": [{"req_id": "SER-003", "units": ["<분류표의 단위 id>"]}], "new_units": [{"topic": "<기존 주제 id>", "id": "<주제 id>.<새-이름>", "title": "한글 제목", "covers": "한 문장"}]}

- 요구사항 자료의 모든 요구사항 id가 자료 순서대로 정확히 한 번씩 `assignments`에 있어야 한다. `req_id`는 원문 그대로 쓴다. `units`는 빈 배열일 수 있다.
- 단위 id는 분류표에 적힌 그대로 쓴다(주제 id와 점까지 포함). 분류표에 없는 id는 `new_units`에 적은 것만 쓸 수 있다. 새 단위 id는 `<기존 주제 id>.<소문자-영문-이름>` 형식이다.
"""


def taxonomy_text(data: dict) -> str:
    lines = []
    for topic in data["topics"]:
        lines.append(f"## {topic['id']} — {topic['title']}: {topic.get('scope', '')}")
        for unit in topic["units"]:
            lines.append(f"- {unit['id']} | {unit['title']} | {unit.get('covers', '')}"
                         + (f" | 아님: {unit['not']}" if unit.get("not") else ""))
    return "\n".join(lines)


def build_ingest_prompt(data: dict, source: dict) -> str:
    """One prompt for one project: instructions, the taxonomy and the project's requirements."""
    return (INGEST_PROMPT_HEAD + "\n## 분류표\n\n" + taxonomy_text(data) + "\n\n## 요구사항\n\n"
            + json.dumps(source, ensure_ascii=False))


def parse_ingest_response(text: str) -> dict:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise WikiToolError("response holds no JSON object")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise WikiToolError(f"response JSON is invalid: {exc}") from exc


def validate_mapping(data: dict, mapping: dict, source: dict) -> list[str]:
    """Problems that stop a mapping from being applied. Empty list means it can be applied."""
    errors: list[str] = []
    topics = {t["id"] for t in data["topics"]}
    units = {u["id"] for t in data["topics"] for u in t["units"]}
    if mapping.get("schema") != MAPPING_SCHEMA or mapping.get("project") != source.get("project"):
        errors.append("schema 또는 project 값이 다르다")
    new: set[str] = set()
    for item in mapping.get("new_units", []):
        uid = str(item.get("id", ""))
        if item.get("topic") not in topics or not UNIT_RE.match(uid) or not uid.startswith(f"{item.get('topic')}.") or not item.get("title"):
            errors.append(f"새 단위 형식 오류: {uid}")
        new.add(uid)
    want = [str(r["id"]) for r in source.get("requirements", [])]
    got = [str(a.get("req_id")) for a in mapping.get("assignments", [])]
    if want != got:
        missing = [x for x in want if x not in got]
        extra = [x for x in got if x not in want]
        errors.append(f"요구사항 id 목록이 자료와 다르다(빠짐 {missing[:10]}, 자료에 없음 {extra[:10]}, 결과 {len(got)}건/자료 {len(want)}건)")
    by_slug: dict[str, list[str]] = {}
    for uid in units:
        by_slug.setdefault(uid.split(".", 1)[1], []).append(uid)
    for item in mapping.get("assignments", []):
        for uid in item.get("units", []):
            if uid in units or uid in new:
                continue
            hint = by_slug.get(str(uid).split(".", 1)[-1], [])
            errors.append(f"{item.get('req_id')}: 분류표에 없는 단위 {uid}" + (f" (비슷한 단위: {', '.join(sorted(hint))})" if hint else ""))
    return errors


AMOUNT = re.compile(r"\d[\d,.]*\s*(?:[천백]\s*)?(?:만\s*)?(?:억(?:\s*원)?|원)")
MENTIONED_ID = re.compile(r"(?<![A-Z])[A-Z]{2,4}-\d{2,3}(?!\d)")
SCOPE_HEAD = "## 수행한 요구 범위"
LIST_HEAD = "### 요구사항 전체 목록(원문)"
LIST_NOTE = "원문 RFP의 요구사항을 빠짐없이 옮긴 목록이다. 수주 실적의 RFP 요구 범위는 수행한 범위로 본다(사용자 지시 2026-10-25)."


def source_from_blocks(blocks: list[dict], project: str, title: str) -> dict:
    if not PROJECT_RE.fullmatch(project) or not isinstance(blocks, list):
        raise WikiToolError("invalid source input")
    requirements = []
    if blocks:
        # The projection already contains converted blocks. The format hint is only
        # needed for document metadata/page mapping, neither of which leaves here.
        _, document = document_from_blocks({"blocks": blocks, "slug": project, "title": title,
                                            "primary_format": "hwpx"})
        for req in document.requirements:
            requirements.append({
                "id": req.key, "name": AMOUNT.sub("(금액 생략)", req.name),
                "definition": AMOUNT.sub("(금액 생략)", req.definition) if req.definition else None,
                "details": AMOUNT.sub("(금액 생략)", req.details)[:700],
            })
    mentioned = {rid for block in blocks for rid in MENTIONED_ID.findall(block["text"])}
    listed = {r["id"].partition("@")[0] for r in requirements}
    return {"project": project, "title": title, "requirements": requirements,
            "unlisted_ids": sorted(mentioned - listed)}


def reference_mapping(data: dict, source: dict) -> dict:
    units = [(unit["id"], re.findall(r"\w+", unit["title"].casefold()))
             for topic in data["topics"] for unit in topic["units"]]
    assignments = []
    for req in source["requirements"]:
        text = " ".join(req.get(key) or "" for key in ("name", "definition", "details")).casefold()
        matches = [uid for uid, words in units if any(word in text for word in words)]
        assignments.append({"req_id": req["id"], "units": matches})
    mapping = {"schema": MAPPING_SCHEMA, "project": source["project"], "title": source["title"],
               "source": "과거 수주 사업 RFP 요구사항 (mock_reference)",
               "assignments": assignments, "new_units": []}
    if not PROJECT_RE.fullmatch(source["project"]) or validate_mapping(data, mapping, source):
        raise WikiToolError("invalid reference mapping")
    return mapping


def _requirement_line(req: dict) -> str | None:
    rid, name, definition, details = (
        AMOUNT.sub("(금액 생략)", " ".join((req.get(key) or "").split()))
        for key in ("id", "name", "definition", "details")
    )
    if not rid:
        raise WikiToolError("missing requirement id")
    if not name or name == rid:
        if not definition and not details:
            return None
        name, definition = definition or details[:40], ""
    text = definition if definition and definition != name else details
    excerpt = text[:300] + ("…" if len(text) > 300 else "")
    return f"- {rid} {name}" + (f" — {excerpt}" if excerpt and excerpt != name else "")


def _update_portfolio_header(front: str, sources: list[str], today: str) -> str:
    # Replace just these YAML values. Re-serializing the mapping would discard
    # comments and rewrite unrelated fields on a human-maintained page.
    values = {"sources": json.dumps(sources, ensure_ascii=False), "updated": json.dumps(today)}
    edits = []
    for key, value in yaml.compose(front, Loader=yaml.SafeLoader).value:
        if key.value in values:
            start, end = key.start_mark.index, value.end_mark.index
            scalar = f"{key.value}: {values.pop(key.value)}"
            if front[start:end].endswith("\n"):
                scalar += "\n"
            edits.append((start, end, scalar))
    for start, end, replacement in reversed(edits):
        front = front[:start] + replacement + front[end:]
    return front + "".join(f"{key}: {value}\n" for key, value in values.items())


def expand_requirements(root: Path, project: str, source: dict, *, today: str) -> dict:
    if not PROJECT_RE.fullmatch(project) or project != source["project"]:
        raise WikiToolError("invalid project")
    page = root / "portfolio" / f"{project}.md"
    if not page.resolve().is_relative_to(root.resolve()) or not page.is_file():
        raise WikiToolError("portfolio_page_missing")
    original = page.read_text(encoding="utf-8")
    header = re.match(r"\A---\n(.*?)^---(?:\n|$)", original, re.M | re.S)
    if not header:
        raise WikiToolError("invalid portfolio page")
    meta = yaml.safe_load(header[1])
    body = original[header.end():]
    lines = [line for req in source["requirements"] if (line := _requirement_line(req))]
    block = "\n".join([LIST_HEAD, "", LIST_NOTE, "", *lines]) + "\n"
    scope = re.search(rf"^{SCOPE_HEAD}$.*?(?=^#{{1,2}} |\Z)", body, re.M | re.S)
    if scope:
        section = scope[0]
        previous = re.search(rf"^{re.escape(LIST_HEAD)}$.*?(?=^#{{1,3}} |\Z)", section, re.M | re.S)
        if previous:
            section = section[:previous.start()] + block + ("\n" if section[previous.end():] else "") + section[previous.end():]
        else:
            section = section.rstrip("\n") + "\n\n" + block
        updated = body[:scope.start()] + section.rstrip("\n") + ("\n\n" if body[scope.end():] else "\n") + body[scope.end():]
    else:
        updated = body.rstrip("\n") + "\n\n" + SCOPE_HEAD + "\n\n" + block

    sources = meta.setdefault("sources", [])
    marker = f"BidOps 변환 사전규격 RFP ({project}) (요구사항 전체 목록, "
    if updated != body or not any(s.startswith(marker) for s in sources):
        sources[:] = [s for s in sources if not s.startswith(marker)] + [marker + today + ")"]
        front = _update_portfolio_header(header[1], sources, today)
        page.write_text("---\n" + front + "---\n" + updated, encoding="utf-8")
    return {"project": project, "requirement_count": len(lines)}


def build_repair_prompt(prompt: str, response: str, errors: list[str]) -> str:
    """Second and last attempt: the first answer and what the check found wrong with it."""
    return (prompt + "\n\n## 앞선 답과 검사 결과\n\n앞선 답:\n" + response.strip()
            + "\n\n검사에서 나온 문제:\n" + "\n".join(f"- {e}" for e in errors)
            + "\n\n문제를 고친 전체 JSON 객체 하나를 다시 출력한다. 문제가 없는 부분은 바꾸지 않는다.")


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


class _IngestArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "error: invalid arguments\n")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ingest = bool(argv) and argv[0] in {"source-from-blocks", "reference-mapping", "expand-requirements"}
    parser_type = _IngestArgumentParser if ingest else argparse.ArgumentParser
    parser = parser_type(prog="bid_deep_engine.wiki_tools")
    sub = parser.add_subparsers(dest="command", required=True)
    source_cmd = sub.add_parser("source-from-blocks")
    source_cmd.add_argument("--project", required=True)
    source_cmd.add_argument("--title", required=True)
    sub.add_parser("reference-mapping").add_argument("--root", required=True)
    expand_cmd = sub.add_parser("expand-requirements")
    expand_cmd.add_argument("--root", required=True)
    expand_cmd.add_argument("--project", required=True)
    for name in ("init", "ingest-prompt", "ingest-validate", "ingest-apply", "feedback-apply", "render", "lint", "check", "stats"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--root", required=True)
        cmd.add_argument("--today", default=date.today().isoformat())
    sub.choices["init"].add_argument("--taxonomy", required=True)
    sub.choices["ingest-apply"].add_argument("--mapping", required=True, nargs="+")
    sub.choices["render"].add_argument("--allow", nargs="*")
    sub.choices["feedback-apply"].add_argument("--feedback", required=True)
    sub.choices["ingest-prompt"].add_argument("--source", required=True)
    for name in ("ingest-validate",):
        sub.choices[name].add_argument("--source", required=True)
        sub.choices[name].add_argument("--response", required=True)
        sub.choices[name].add_argument("--out", help="write the mapping here when it is valid")
        sub.choices[name].add_argument("--repair-prompt", help="write the second-attempt prompt here when it is not")
    args = parser.parse_args(argv)
    if ingest:
        try:
            payload = json.load(sys.stdin)
            if args.command == "source-from-blocks":
                result = source_from_blocks(payload["blocks"], args.project, args.title)
            elif args.command == "reference-mapping":
                result = reference_mapping(load_sidecar(Path(args.root)), payload)
            else:
                result = expand_requirements(Path(args.root), args.project, payload, today=date.today().isoformat())
            print(json.dumps(result, ensure_ascii=False))
            return 0
        except Exception as exc:
            # Parser, filesystem and YAML exceptions can include source text or local paths.
            print(f"error: {type(exc).__name__}", file=sys.stderr)
            return 2
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
        elif args.command == "ingest-prompt":
            print(build_ingest_prompt(load_sidecar(root), _read(Path(args.source))))
            return 0
        elif args.command == "ingest-validate":
            data, source = load_sidecar(root), _read(Path(args.source))
            response = Path(args.response).read_text(encoding="utf-8")
            try:
                mapping = parse_ingest_response(response)
                errors = validate_mapping(data, mapping, source)
            except WikiToolError as exc:
                mapping, errors = None, [str(exc)]
            if not errors and args.out:
                _write(Path(args.out), mapping)
            if errors and args.repair_prompt:
                Path(args.repair_prompt).write_text(
                    build_repair_prompt(build_ingest_prompt(data, source), response, errors), encoding="utf-8")
            print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
            return 0 if not errors else 1
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
