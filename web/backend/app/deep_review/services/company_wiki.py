"""File-backed views of the same immutable-in-request text used for engine input."""

from collections import Counter, defaultdict
from datetime import date
import stat
from pathlib import Path, PureWindowsPath
import re

from typing import Literal
from pydantic import BaseModel, Field
import yaml

from ...core.config import get_settings
from ..schemas import company_wiki as dto
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


def flatten(value, path, section, levels):
    if isinstance(value, dict):
        for key, child in value.items():
            key = scalar(key)
            if key == "amount_krw" or key.endswith("_file"):
                continue
            yield from flatten(
                child, f"{path}.{key}" if path else key, section or key, levels
            )
        return
    if isinstance(value, list):
        if any(isinstance(item, (dict, list)) for item in value):
            for i, item in enumerate(value):
                identifier = i
                if isinstance(item, dict):
                    identifier = next(
                        (
                            item[k]
                            for k in ("item_no", "id", "name")
                            if item.get(k) is not None
                        ),
                        i,
                    )
                yield from flatten(item, f"{path}[{identifier}]", section, levels)
            return
        value = ", ".join("null" if item is None else scalar(item) for item in value)
    yield dto.Fact(
        path=path,
        section=section,
        value=scalar(value),
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


class Sidecar(BaseModel):
    schema_id: Literal["bidops.wiki-work-units.v1"] = Field(alias="schema")
    topics: list[dict]
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
        self.topics = []
        known = set()
        for topic in data.topics:
            units = []
            for unit in topic["units"]:
                uid = unit["id"]
                if uid in known:
                    raise WikiError()
                known.add(uid)
                units.append(
                    dto.Unit.model_validate(
                        {
                            **unit,
                            "projects": [
                                dto.Project(project=p, req_ids=ids)
                                for p, ids in projects.get(uid, {}).items()
                            ],
                            "no_record": notes.get(uid, []),
                        }
                    )
                )
            self.topics.append(dto.Topic.model_validate({**topic, "units": units}))
        if (projects.keys() | notes.keys()) - known:
            raise WikiError()
        self.unit_count = len(known)
        self.without_evidence = len(known - projects.keys())


def requirement_count(body):
    count = None
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
        if line.rstrip() == "### 요구사항 전체 목록(원문)":
            count = 0
        elif count is not None:
            if re.match(r"^#{1,3}(?:\s|$)", line):
                break
            if line.startswith("- "):
                count += 1
    return count


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

    def evidence(self):
        raw = self.side_file("work-units.json")
        return None if raw is None else EvidenceMap(Sidecar.model_validate_json(raw))

    def page(self, kind, slug):
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
            body=self.public_prose(raw[front.end() :]),
            bundle_sha256=self.digest,
        )

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
        pages = Counter(p.kind for p in self.all_pages())
        work = self.evidence()
        log = []
        for line in reversed((self.side_file("log.txt") or "").splitlines()[-20:]):
            match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) \| (.*)", line)
            if not match:
                raise WikiError()
            log.append(dto.LogEntry(date=match[1], text=self.public_prose(match[2])))
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
            log=log,
        )

    def profile(self):
        provenance = self.files.get(f"{self.slug}.provenance.yaml", {"fields": {}})
        levels = mapping(mapping(provenance)["fields"])
        return dto.Profile(
            bundle_sha256=self.digest,
            facts=list(flatten(self.profile_data, "", "", levels)),
        )

    def portfolio(self):
        work = self.evidence()
        pages = {
            page.slug: page for page in self.all_pages() if page.kind == "portfolio"
        }
        items = []
        for record in self.records:
            project = record["id"]
            page = pages.get(project)
            period = record.get("period")
            source = work.sources.get(project) if work else None
            items.append(
                dto.PortfolioItem(
                    id=project,
                    **{
                        k: scalar(record.get(k))
                        for k in ("title", "client", "type", "role")
                    },
                    period_start=scalar(
                        period.get("start") if isinstance(period, dict) else period
                    ),
                    period_end=scalar(
                        period.get("end") if isinstance(period, dict) else period
                    ),
                    has_page=page is not None,
                    requirement_count=requirement_count(
                        self.knowledge[f"portfolio/{project}.md"]
                    )
                    if page
                    else None,
                    ingested=source is not None if work else None,
                    ingested_at=source.ingested_at if source else None,
                    evidence_links=work.links[project] if work else None,
                )
            )
        return dto.Portfolio(bundle_sha256=self.digest, items=items)

    def work_units(self):
        work = self.evidence()
        if work is None:
            raise WikiError("company_wiki_work_units_unavailable", 404)
        return dto.WorkUnits(bundle_sha256=self.digest, topics=work.topics)

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

        def public(value):
            if isinstance(value, str):
                return wiki.public_text(value)
            if isinstance(value, list):
                return [public(item) for item in value]
            if isinstance(value, dict):
                return {key: public(item) for key, item in value.items()}
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
