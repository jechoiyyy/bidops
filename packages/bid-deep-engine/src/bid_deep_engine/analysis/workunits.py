"""Compile and apply the work-unit taxonomy carried in company Markdown pages."""

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from bid_deep_engine.analysis.llm import (
    CallRecord,
    LlmCallError,
    LlmClient,
    LlmOutputError,
    LlmRefusal,
    LlmTruncated,
)
from bid_deep_engine.analysis.prompt_files import prompt_bytes
from bid_deep_engine.company.knowledge import (
    PORTFOLIO_TOP_K,
    WORK_UNIT_EVIDENCE_RE,
    WORK_UNIT_SECTION,
    Knowledge,
    KnowledgeSelection,
    is_work_topic,
    portfolio_evidence_excerpt,
    prepare_knowledge,
)
from bid_deep_engine.ingest.models import RfpDocument

_UNIT_ID = re.compile(r"- 단위 id: `([a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+(?:-[a-z0-9]+)*)`")


@dataclass(frozen=True)
class WorkUnit:
    id: str
    title: str
    covers: str
    exclusions: str
    evidence: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class WorkTopic:
    slug: str
    title: str
    scope: str
    units: tuple[WorkUnit, ...]


@dataclass(frozen=True)
class WorkUnitMap:
    topics: tuple[WorkTopic, ...]
    units: dict[str, WorkUnit]
    basis_projects: int

    def taxonomy(self) -> str:
        # wiki_tools imports runner, which imports the analysis pipeline.
        from bid_deep_engine.wiki_tools import taxonomy_text

        return taxonomy_text({
            "topics": [
                {
                    "id": topic.slug.removeprefix("work-"),
                    "title": topic.title,
                    "scope": topic.scope,
                    "units": [
                        {"id": u.id, "title": u.title, "covers": u.covers, "not": u.exclusions}
                        for u in topic.units
                    ],
                }
                for topic in self.topics
            ]
        })


def _parse_unit(
    block: str, topic_id: str, portfolio: set[str]
) -> WorkUnit | None:
    title, *lines = block.splitlines()
    ids = [m[1] for line in lines if (m := _UNIT_ID.fullmatch(line))]
    if len(ids) != 1 or not ids[0].startswith(f"{topic_id}.") or not title.strip():
        return None
    scope = next((line.removeprefix("- 범위: ") for line in lines if line.startswith("- 범위: ")), "")
    covers, _, exclusions = scope.partition(" 다른 단위: ")
    evidence: dict[tuple[str, str], None] = {}
    for line in lines:
        if not line.startswith("- [["):
            continue
        match = WORK_UNIT_EVIDENCE_RE.fullmatch(line)
        if match is None:
            return None
        project, refs = match.groups()
        if project in portfolio:
            evidence.update(dict.fromkeys((project, req_id.strip()) for req_id in refs.split(",")))
    return WorkUnit(ids[0], title.strip(), covers, exclusions, tuple(evidence))


def parse_work_unit_map(knowledge: Knowledge) -> WorkUnitMap | None:
    """Recover the map from topic pages, dropping evidence for absent portfolio pages."""
    portfolio = {slug for slug, page in knowledge.pages.items() if page.meta.kind == "portfolio"}
    topics: list[WorkTopic] = []
    units: dict[str, WorkUnit] = {}
    for slug, page in sorted(knowledge.pages.items()):
        if not is_work_topic(slug, page.meta.kind):
            continue
        scope_block, separator, unit_block = ("\n" + page.body).partition(f"\n{WORK_UNIT_SECTION}\n")
        scope_lines = scope_block.split("\n## 범위\n", 1)[-1].splitlines()
        scope = next(
            (line[2:].strip() for line in scope_lines if line.startswith("- ") and
             not line.startswith("- 전체 지도:")),
            "",
        )
        blocks = re.split(r"^### ", unit_block, flags=re.MULTILINE)[1:]
        if not separator or not blocks:
            return None
        topic_units = []
        for block in blocks:
            unit = _parse_unit(block, slug.removeprefix("work-"), portfolio)
            if unit is None or unit.id in units:
                return None
            units[unit.id] = unit
            topic_units.append(unit)
        title = page.meta.title.removeprefix("업무 근거 — ")
        topics.append(WorkTopic(slug, title, scope, tuple(topic_units)))
    if not topics:
        return None
    projects = {project for unit in units.values() for project, _ in unit.evidence}
    return WorkUnitMap(tuple(topics), units, len(projects))


class WorkUnitAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    req_id: str
    units: list[str]
    uncovered: list[str]


class WorkUnitAssignmentsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignments: list[WorkUnitAssignment]


def validate_assignments(
    work_map: WorkUnitMap, doc: RfpDocument, assignments: list[WorkUnitAssignment]
) -> list[str]:
    errors = []
    expected = [req.key for req in doc.requirements]
    actual = [item.req_id for item in assignments]
    if actual != expected:
        errors.append(f"요구사항 id 목록과 순서가 다르다. 올바른 순서: {', '.join(expected)}")
    for item in assignments:
        for unit_id in item.units:
            if unit_id not in work_map.units:
                errors.append(f"{item.req_id}: 분류표에 없는 단위 {unit_id}")
    return errors


def classify_work_units(
    client: LlmClient, doc: RfpDocument, work_map: WorkUnitMap, calls: list[CallRecord]
) -> tuple[WorkUnitAssignmentsOut | None, str | None]:
    """Make at most two calls, and return only a complete and valid assignment."""
    from bid_deep_engine.wiki_tools import build_repair_prompt

    system = prompt_bytes("system.md").decode("utf-8")
    instruction = prompt_bytes("units.md").decode("utf-8")
    document = (
        f"## 분류표\n\n{work_map.taxonomy()}\n\n## 요구사항\n\n"
        + json.dumps([
            {"id": req.key, "name": req.name, "definition": req.definition, "details": req.details[:1500]}
            for req in doc.requirements
        ], ensure_ascii=False)
    )

    for attempt in range(2):
        try:
            result = client.parse(
                WorkUnitAssignmentsOut, purpose="units", system=system, document=document,
                instruction=instruction, slug=doc.slug,
            )
        except LlmCallError:
            return None, "call_failed"
        except (LlmOutputError, LlmTruncated, LlmRefusal) as exc:
            calls.append(exc.record)
            if isinstance(exc, LlmOutputError):
                return None, "output_error"
            return None, "truncated" if isinstance(exc, LlmTruncated) else "refused"

        calls.append(result.record)
        output = WorkUnitAssignmentsOut.model_validate(result.parsed)
        errors = validate_assignments(work_map, doc, output.assignments)
        if not errors:
            return output, None
        if attempt == 0:
            instruction = build_repair_prompt(instruction, output.model_dump_json(), errors)
    return None, "invalid_assignments"


class WorkUnitEvidence(WorkUnitAssignment):
    evidence_projects: list[str]


class WorkUnitSummary(BaseModel):
    basis_projects: int
    status: Literal["classified", "unavailable"]
    reason: str | None
    assignments: list[WorkUnitEvidence]


def summarize_assignments(
    work_map: WorkUnitMap, output: WorkUnitAssignmentsOut | None, reason: str | None
) -> WorkUnitSummary:
    rows = []
    for item in output.assignments if output is not None else []:
        units = sorted(set(item.units))
        projects = sorted({p for uid in units for p, _ in work_map.units[uid].evidence})
        rows.append(WorkUnitEvidence(
            req_id=item.req_id, units=units, uncovered=item.uncovered, evidence_projects=projects,
        ))
    return WorkUnitSummary(
        basis_projects=work_map.basis_projects,
        status="classified" if output is not None else "unavailable",
        reason=reason,
        assignments=rows,
    )


def link_portfolio(
    knowledge: Knowledge, work_map: WorkUnitMap, summary: WorkUnitSummary
) -> tuple[list[str], dict[str, list[int]]]:
    project_scores: Counter[str] = Counter()
    line_scores: dict[str, Counter[str]] = defaultdict(Counter)
    for assignment in summary.assignments:
        for uid in assignment.units:
            refs = work_map.units[uid].evidence
            project_scores.update({project for project, _ in refs})
            for project, req_id in refs:
                line_scores[project][req_id] += 1
    related = sorted(project_scores, key=lambda p: (-project_scores[p], p))[:PORTFOLIO_TOP_K]
    excerpts = {}
    for slug in related:
        picked = portfolio_evidence_excerpt(knowledge.pages[slug], line_scores[slug])
        if picked is not None:
            excerpts[slug] = picked
    return related, excerpts


def render_work_unit_evidence(work_map: WorkUnitMap, summary: WorkUnitSummary) -> str:
    lines = [f"## 요구사항별 업무 근거(업무 근거 지도, 실적 {work_map.basis_projects}건 기준)"]
    for row in summary.assignments:
        uncovered = ", ".join(row.uncovered)
        if not row.units:
            if not uncovered:
                # 분류 기준 3: 내용이 없는 요구사항은 아무 단위도 고르지 않는다. 수행 기록 없음(GAP)이 아니다.
                lines.append(f"- {row.req_id}: 분류할 업무 내용 없음(판단 보류)")
                continue
            lines.append(f"- {row.req_id}: 어느 업무 단위에도 해당하지 않음 — {uncovered}")
            continue
        evidence = []
        for uid in row.units:
            unit = work_map.units[uid]
            refs = ", ".join(f"[[{project}]] {req_id}" for project, req_id in unit.evidence)
            # 근거가 지도 범위 밖에만 있는 단위는 수행 기록 없음(GAP)이 아니라 판단 보류다.
            evidence.append(
                f"{unit.title}({uid}) ← "
                + (refs or f"지도 범위(실적 {work_map.basis_projects}건) 안 근거 없음 → 판단 보류")
            )
        if uncovered:
            evidence.append(f"단위에 들지 않는 부분: {uncovered}")
        lines.append(f"- {row.req_id}: " + " / ".join(evidence))
    return "\n".join(lines)


def prepare_work_unit_knowledge(
    knowledge: Knowledge,
    doc: RfpDocument,
    work_map: WorkUnitMap | None,
    summary: WorkUnitSummary | None,
    *,
    override: list[str] | None = None,
) -> tuple[KnowledgeSelection, str, str]:
    """Render the same page selection and evidence section for match, synth and review."""
    if work_map is None or summary is None or summary.status != "classified":
        selection, text = prepare_knowledge(doc, knowledge, override=override)
        return selection, text, ""
    related, excerpts = link_portfolio(knowledge, work_map, summary)
    selection, text = prepare_knowledge(
        doc, knowledge, override=override, related_override=related, excerpt_override=excerpts,
    )
    return selection, text, render_work_unit_evidence(work_map, summary)


def work_unit_output_hash(summary: WorkUnitSummary | None) -> str | None:
    from bid_deep_engine.analysis.provenance import canonical_hash

    if summary is None or summary.status != "classified":
        return None
    return canonical_hash({
        "assignments": [
            row.model_dump(mode="json", exclude={"evidence_projects"})
            for row in summary.assignments
        ],
    })
