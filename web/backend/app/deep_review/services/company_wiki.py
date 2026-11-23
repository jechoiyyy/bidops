"""File-backed views of the same immutable-in-request text used for engine input."""

from collections import Counter, defaultdict
from datetime import date
from functools import cached_property
import stat
from pathlib import Path, PureWindowsPath
import re

from typing import Literal, NamedTuple
from pydantic import BaseModel, Field
import yaml

from ...core.config import get_settings
from ..schemas import company_wiki as dto
from .company_wiki_labels import Labels, display_value
from .engine_runs import company_bundle, EngineRunError


FOLDERS = {
    "category": "categories",
    "capability": "capabilities",
    "portfolio": "portfolio",
    "rule": "rules",
    "glossary": "",
}
PAGE_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
FRONT = re.compile(r"\A---[ \t]*\n(.*?)^---[ \t]*(?:\n|\Z)", re.S | re.M)
# A line containing a local absolute path can also contain spaces in the filename.
LOCAL_PATH = re.compile(
    r"""(?:^|[\s`"'(\[=:])(?:/(?!/)[^\s/]|[a-zA-Z]:[\\/]|\\\\)""", re.M
)


class WikiError(ValueError):
    def __init__(self, code="company_wiki_unreadable", status=503):
        self.code = code
        self.status = status
        super().__init__(code)


def scalar(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (str, int, float, date)):
        return str(value)
    raise WikiError()


def mapping(value):
    if not isinstance(value, dict):
        raise WikiError()
    return value


def flatten(value, path, pattern, levels, labels, item_name=""):
    if labels and labels.hides(pattern):
        return
    if isinstance(value, dict):
        for key, child in value.items():
            key = scalar(key)
            if key == "amount_krw" or key.endswith("_file"):
                continue
            yield from flatten(child, f"{path}.{key}", f"{pattern}.{key}", levels, labels, item_name)
        return
    if isinstance(value, list):
        if any(isinstance(item, (dict, list)) for item in value):
            for i, item in enumerate(value):
                fields = item if isinstance(item, dict) else {}
                identifier = next((fields[k] for k in ("item_no", "id", "name")
                                   if fields.get(k) is not None), i)
                name = next((fields[k] for k in ("name", "std", "title") if fields.get(k)), identifier)
                yield from flatten(item, f"{path}[{identifier}]", pattern + "[]", levels, labels, str(name))
            return
        value = ", ".join("null" if item is None else scalar(item) for item in value)
    value = scalar(value)
    field, key = labels.lookup(pattern) if labels else (None, "")
    yield dto.Fact(
        path=path, label=field.label.replace("{key}", key).replace("{item}", item_name) if field else None,
        value=value, display_value=display_value(value, field),
        level=mapping(levels.get(path, {})).get("level"),
    )


class Evidence(BaseModel):
    project: str
    req_id: str
    unit: str


class Source(BaseModel):
    ingested_at: str | None = None


class Note(dto.NoRecord):
    unit: str


class SourceUnit(dto.UnitName):
    covers: str | None = None
    excludes: str | None = Field(default=None, alias="not")


class SourceTopic(dto.TopicInfo):
    units: list[SourceUnit]


class Sidecar(BaseModel):
    schema_id: Literal["bidops.wiki-work-units.v1"] = Field(alias="schema")
    topics: list[SourceTopic]
    sources: dict[str, Source]
    evidence: list[Evidence]
    no_record: list[Note] = []


class EvidenceMap:
    def __init__(self, data):
        self.sources = data.sources
        self.links = Counter(row.project for row in data.evidence)
        projects = defaultdict(lambda: defaultdict(list))
        notes = defaultdict(list)
        for row in data.evidence:
            projects[row.unit][row.project].append(row.req_id)
        for note in data.no_record:
            notes[note.unit].append(note.model_dump(exclude={"unit"}))
        self.topics = data.topics
        self.projects = projects
        self.notes = notes
        units = [unit.id for topic in data.topics for unit in topic.units]
        known = set(units)
        if len(known) != len(units) or (projects.keys() | notes.keys()) - known:
            raise WikiError()
        self.unit_count = len(known)
        self.without_evidence = len(known - projects.keys())


PROJECT_ID = re.compile(r"P[0-9]{4}-[0-9]{2}")
REQ_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class ProjectSections(NamedTuple):
    scope: list[str]
    requirements: dict[str, tuple[str | None, str]]
    count: int | None


def project_sections(body):
    scope = []
    requirements = {}
    count = None
    in_scope = in_list = False
    fence = None
    for line in body.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token.startswith(fence):
                fence = None
            continue
        if fence:
            continue
        if re.match(r"^#{1,2}(?:\s|$)", line):
            in_scope = line.rstrip() == "## 수행한 요구 범위"
            in_list = False
        elif line.startswith("### "):
            in_list = line.rstrip() == "### 요구사항 전체 목록(원문)"
            if in_list and count is None:
                count = 0
        elif line.startswith("- "):
            if in_list:
                count += 1
                heading, _, text = line[2:].partition(" — ")
                parts = heading.split(maxsplit=1)
                if parts and REQ_ID.fullmatch(parts[0]):
                    requirements[parts[0]] = (parts[1] if len(parts) > 1 else None, text)
            elif in_scope and not any(token in line for token in ("`", "YAML", "라벨", "past.yaml")):
                scope.append(line[2:])
    return ProjectSections(scope, requirements, count)


def project_year(start, end, project):
    for value in (end, start, project.removeprefix("P")):
        match = re.match(r"^(\d{4})(?:\D|$)", value or "")
        if match:
            return int(match[1])
    return None


def iso_day(value):
    try:
        return date.fromisoformat(value or "").isoformat()
    except ValueError:
        return None


class CompanyWiki:
    def __init__(self):
        settings = get_settings()
        self.slug = settings.engine_company_bundle_slug
        try:
            bundle = company_bundle()
        except EngineRunError:
            raise WikiError() from None
        if bundle is None:
            raise WikiError("company_wiki_unavailable", 404)
        self.root = Path(settings.engine_company_bundle_dir) / self.slug
        if self.root.is_symlink() or not self.root.is_dir():
            raise WikiError()
        self.digest = bundle["bundle_sha256"]
        self.files = {k: yaml.safe_load(v) for k, v in bundle["files"].items()}
        self.profile_data = mapping(self.files[bundle["profile_file"]])
        self.records = self.files[f"{self.slug}.portfolio.yaml"]
        if not isinstance(self.records, list):
            raise WikiError()
        self.knowledge = bundle["knowledge"]
        self._sections = {}

        amounts = set()
        for record in self.records:
            amount = mapping(record).get("amount_krw")
            if str(amount).isdigit():
                amounts.update((str(amount), f"{int(amount):,}"))
        self.amounts = (
            re.compile(
                r"(?<![0-9])(?:"
                + "|".join(map(re.escape, sorted(amounts, key=len, reverse=True)))
                + r")(?![0-9])"
            )
            if amounts
            else None
        )

    def public_text(self, text):
        # Withhold the whole line for a local path, including filenames with spaces.
        if LOCAL_PATH.search(text):
            text = "".join(
                ("[경로 생략]" + ("\n" if line.endswith("\n") else ""))
                if LOCAL_PATH.search(line)
                else line
                for line in text.splitlines(keepends=True)
            )
        return text

    def public_prose(self, text):
        text = self.public_text(text)
        return self.amounts.sub("[금액 생략]", text) if self.amounts else text

    def side_file(self, name):
        path = self.root / name
        if path.is_symlink():
            return None
        try:
            if not stat.S_ISREG(path.stat().st_mode):
                raise WikiError()
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    @cached_property
    def labels(self):
        try:
            raw = self.side_file("labels.yaml")
            return Labels.model_validate(yaml.safe_load(raw)) if raw else None
        except (OSError, ValueError, RecursionError, yaml.YAMLError):
            return None

    @cached_property
    def evidence(self):
        raw = self.side_file("work-units.json")
        return None if raw is None else EvidenceMap(Sidecar.model_validate_json(raw))

    def _page(self, kind, slug):
        missing = WikiError("company_wiki_page_not_found", 404)
        if kind not in FOLDERS or not PAGE_SLUG.fullmatch(slug):
            raise missing
        if kind == "glossary" and slug != "glossary":
            raise missing
        rel = Path(FOLDERS[kind]) / f"{slug}.md"
        raw = self.knowledge.get(rel.as_posix())
        path = self.root / rel
        if (
            raw is None
            or path.is_symlink()
            or path.parent.is_symlink()
            or not path.resolve().is_relative_to(self.root.resolve())
            or not path.is_file()
        ):
            raise missing
        front = FRONT.match(raw)
        if not front:
            raise WikiError()
        meta = mapping(yaml.safe_load(front[1]))
        if meta["kind"] != kind or meta["slug"] != slug:
            raise WikiError()
        sources = meta.get("sources") or []
        if not isinstance(sources, list) or not all(
            isinstance(s, str) for s in sources
        ):
            raise WikiError()
        return dto.PageDetail(
            kind=kind,
            slug=slug,
            title=meta["title"],
            updated=scalar(meta.get("updated")),
            confidence=meta.get("confidence"),
            sources=[
                s
                for s in sources
                if not (
                    Path(s.strip()).is_absolute()
                    or PureWindowsPath(s.strip()).is_absolute()
                )
            ],
            body=raw[front.end() :],
            bundle_sha256=self.digest,
        )

    def page(self, kind, slug):
        page = self._page(kind, slug)
        page.body = self.public_prose(page.body)
        return page

    def all_pages(self):
        kinds = {folder: kind for kind, folder in FOLDERS.items()}
        for name in self.knowledge:
            rel = Path(name)
            folder = rel.parent.as_posix() if len(rel.parts) > 1 else ""
            if folder not in kinds or (not folder and name != "glossary.md"):
                continue
            if PAGE_SLUG.fullmatch(rel.stem):
                yield self.page(kinds[folder], rel.stem)

    def summary(self):
        pages = Counter()
        dates = []
        for page in self.all_pages():
            pages[page.kind] += 1
            dates.append(iso_day(page.updated))
        work = self.evidence
        titles = {r["id"]: r.get("title") for r in self.records}
        log = []
        for line in (self.side_file("log.txt") or "").splitlines():
            match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) \| (.*)", line)
            day, text = (iso_day(match[1]), match[2]) if match else (None, line)
            dates.append(day)
            entry = dto.LogEntry(date=day, text=self.public_prose(text))
            ingest = re.fullmatch(r"ingest \| (P[0-9]{4}-[0-9]{2}) \| 요구사항 (\d+)건, 미분류 (\d+)건", text)
            if ingest:
                entry.kind = "ingest"
                entry.project = ingest[1]
                entry.project_title = titles.get(ingest[1])
                entry.requirement_count = int(ingest[2])
                entry.unassigned_count = int(ingest[3])
            elif text.startswith("feedback | "):
                entry.kind = "feedback"
            elif text.startswith("init | "):
                entry.kind = "init"
            log.append(entry)
        counts = dto.WikiCounts(
            pages_by_kind={k: pages[k] for k in FOLDERS},
            portfolio_items=len(self.records),
            portfolio_pages=pages["portfolio"],
            ingested_projects=len(work.sources) if work else None,
            work_topics=len(work.topics) if work else None,
            work_units=work.unit_count if work else None,
            evidence_links=sum(work.links.values()) if work else None,
            units_without_evidence=work.without_evidence if work else None,
        )
        return dto.Summary(
            slug=self.slug,
            company_name=self.profile_data["company"]["name"],
            bundle_sha256=self.digest,
            counts=counts,
            work_units_available=bool(work),
            last_changed=max(filter(None, dates), default=None),
            labels_available=self.labels is not None, log=log[-20:][::-1],
        )

    def profile(self):
        provenance = self.files.get(f"{self.slug}.provenance.yaml", {"fields": {}})
        levels = mapping(mapping(provenance)["fields"])
        sections = []
        for key, value in self.profile_data.items():
            if key.endswith("_file") or key == "amount_krw":
                continue
            facts = list(flatten(value, key, key, levels, self.labels))
            if facts:
                sections.append(dto.Section(key=key, label=self.labels.sections.get(key) if self.labels else None,
                                            facts=facts))
        return dto.Profile(bundle_sha256=self.digest, sections=sections)

    @cached_property
    def records_by_id(self):
        return {record["id"]: record for record in self.records}

    def sections_for(self, project):
        if project not in self._sections:
            body = ""
            if project in self.records_by_id and f"portfolio/{project}.md" in self.knowledge:
                body = self._page("portfolio", project).body
            self._sections[project] = project_sections(body)
        return self._sections[project]

    def portfolio_item(self, record):
        project = record["id"]
        work = self.evidence
        source = work.sources.get(project) if work else None
        period = record.get("period")
        return dto.PortfolioItem(
            id=project,
            **{key: scalar(record.get(key)) for key in ("title", "client", "type", "role")},
            period_start=scalar(period.get("start") if isinstance(period, dict) else period),
            period_end=scalar(period.get("end") if isinstance(period, dict) else period),
            has_page=f"portfolio/{project}.md" in self.knowledge,
            requirement_count=self.sections_for(project).count,
            ingested=source is not None if work else None,
            ingested_at=source.ingested_at if source else None,
            evidence_links=work.links[project] if work else None,
        )

    def portfolio(self):
        return dto.Portfolio(bundle_sha256=self.digest, items=[self.portfolio_item(r) for r in self.records])

    def work_units(self):
        work = self.evidence
        if work is None:
            raise WikiError("company_wiki_work_units_unavailable", 404)
        topics = []
        for topic in work.topics:
            groups = [work.projects[u.id] for u in topic.units]
            topics.append(dto.TopicSummary(**topic.model_dump(exclude={"units"}), unit_count=len(groups),
                units_without_evidence=sum(not group for group in groups),
                project_count=len({project for group in groups for project in group})))
        return dto.WorkUnits(bundle_sha256=self.digest, topics=topics)

    def topic(self, topic_id):
        work = self.evidence
        topic = next((t for t in work.topics if t.id == topic_id), None) if work else None
        if not topic:
            raise WikiError("company_wiki_topic_not_found", 404)
        units = []
        for unit in topic.units:
            projects = []
            for project, req_ids in work.projects[unit.id].items():
                record = self.records_by_id.get(project)
                item = self.portfolio_item(record) if record else None
                start, end = (item.period_start, item.period_end) if item else (None, None)
                requirements = self.sections_for(project).requirements
                projects.append(dto.Project(
                    project=project, title=item.title if item else None, client=item.client if item else None,
                    period_start=start, period_end=end, year=project_year(start, end, project),
                    requirements=[dto.Requirement(req_id=rid, name=requirements.get(rid, (None, ""))[0])
                                  for rid in req_ids],
                ))
            projects.sort(key=lambda p: (p.year or 0, p.project), reverse=True)
            units.append(dto.Unit(**unit.model_dump(by_alias=True), projects=projects, project_count=len(projects),
                                  latest_year=projects[0].year if projects else None, no_record=work.notes[unit.id]))
        return dto.Topic(**topic.model_dump(exclude={"units"}), bundle_sha256=self.digest, units=units)

    def project_detail(self, project):
        record = self.records_by_id.get(project)
        if not record:
            raise WikiError("company_wiki_project_not_found", 404)
        sections = self.sections_for(project)
        groups = []
        work = self.evidence
        for topic in work.topics if work else ():
            units = [dto.UnitName(id=u.id, title=u.title) for u in topic.units if project in work.projects[u.id]]
            if units:
                groups.append(dto.ProjectWork(topic_id=topic.id, topic_title=topic.title, units=units))
        return dto.ProjectDetail(
            **self.portfolio_item(record).model_dump(), bundle_sha256=self.digest, domain=record.get("domain"),
            scope_lines=sections.scope, work_units=groups, requirements=[
                dto.Requirement(req_id=rid, name=name) for rid, (name, _) in sections.requirements.items()
            ],
        )

    def requirement(self, project, req_id):
        missing = WikiError("company_wiki_requirement_not_found", 404)
        if not PROJECT_ID.fullmatch(project) or not REQ_ID.fullmatch(req_id):
            raise missing
        requirements = self.sections_for(project).requirements
        if req_id not in requirements:
            raise missing
        name, text = requirements[req_id]
        return dto.RequirementDetail(
            bundle_sha256=self.digest, project=project, req_id=req_id, name=name, text=self.public_prose(text)[:300],
        )

    def pages(self):
        return dto.Pages(
            bundle_sha256=self.digest,
            pages=[
                dto.PageEntry(**page.model_dump(), chars=len(page.body))
                for page in self.all_pages()
            ],
        )


def read(view, *args):
    """Convert source format and I/O errors to a stable code before leaving the service."""
    try:
        wiki = CompanyWiki()
        result = view(wiki, *args).model_dump(by_alias=True)

        # Copy identifiers and structured values exactly. Redact any financial
        # values repeated in prose before returning the new projections.
        prose_fields = {"title", "topic_title", "project_title", "name", "client", "type", "role", "domain",
                        "scope", "scope_lines", "covers", "not", "note", "source", "text", "company_name"}

        def public(value, field=None):
            if isinstance(value, str):
                if field in prose_fields:
                    return wiki.public_prose(value)
                return wiki.public_text(value)
            if isinstance(value, list):
                return [public(item, field) for item in value]
            if isinstance(value, dict):
                return {key: public(item, key) for key, item in value.items()}
            return value

        return public(result)
    except WikiError:
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RecursionError,
        yaml.YAMLError,
    ):
        raise WikiError() from None
