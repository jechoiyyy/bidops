"""Company input for the engine and BidOps block provenance mapping.

Two company inputs exist. `bidops.engine-input.v1` carries BidOps company facts, which
`project_company` projects conservatively (credit rating and portfolio titles only).
`bidops.engine-input.v2` carries the engine's own company files and knowledge tree
(`company_bundle`), which `company_inputs` loads unchanged with the upstream loader.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .company.knowledge import KnowledgeError, load_knowledge, portfolio_gate_texts
from .company.loader import ProfileError, load_evidence_view
from .company.provenance import CompanyEvidenceView
from .company.schema import CompanyProfile

INPUT_V1 = "bidops.engine-input.v1"
INPUT_V2 = "bidops.engine-input.v2"
_YAML_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.ya?ml")
_PAGE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class EngineError(ValueError):
    """A defined, content-free failure code of the engine boundary."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def project_company(payload):
    facts = payload.get("profile_payload", {}).get("facts", [])
    nodes = {
        n["id"]: n
        for n in payload.get("graph_nodes", [])
        if isinstance(n, dict) and isinstance(n.get("id"), str)
    }
    profile = {
        "schema_version": 1,
        "company": {"name": payload["company_name"]},
        "portfolio_file": "unused.yaml",
    }
    mapped = []
    for fact in facts:
        if fact.get("status") != "confirmed" or not fact.get("quote"):
            continue
        key = fact["fact_key"]
        value = fact.get("value")
        if not isinstance(value, dict):
            continue
        if key in {"qual:credit_rating", "qual:credit"} and isinstance(
            value.get("detail"), str
        ):
            credit = {"grade": value["detail"]}
            until = value.get("valid_until")
            if isinstance(until, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", until):
                credit["valid_until"] = until
            profile.setdefault("registrations", {})["credit_rating"] = credit
            mapped.append(
                {
                    "fact_key": key,
                    "fields": ["registrations.credit_rating." + k for k in credit],
                }
            )
        match = re.fullmatch(r"project:(\d{4}-\d{2})", key)
        label = nodes.get(key, {}).get("label")
        if match and isinstance(label, str) and isinstance(value.get("agency"), str):
            item = {"id": "P" + match[1], "title": label, "client": value["agency"]}
            if type(value.get("amount_krw")) is int and value["amount_krw"] >= 0:
                item["amount_krw"] = value["amount_krw"]
            profile.setdefault("portfolio", []).append(item)
            mapped.append(
                {
                    "fact_key": key,
                    "fields": [
                        "portfolio." + item["id"] + "." + k for k in item if k != "id"
                    ],
                }
            )
    return CompanyProfile.model_validate(profile), mapped


@dataclass(frozen=True)
class CompanyInputs:
    """What the pipeline reads about the company, and what the output records about it."""

    profile: object  # CompanyEvidenceView
    company_input_hash: str
    knowledge: object | None
    portfolio_texts: dict | None
    record: dict


def company_bundle_sha256(bundle):
    """Digest of the company files and knowledge pages a bundle carries."""
    body = {
        "profile_file": bundle.get("profile_file"),
        "files": bundle.get("files"),
        "knowledge": bundle.get("knowledge") or {},
    }
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_company_bundle(directory, slug):
    """Bundle the company files `<slug>*.yaml` and the knowledge tree `<slug>/` of a folder.

    This is the local layout BidOps keeps outside Git (`wiki/<slug>.yaml`, `wiki/<slug>/`).
    Symbolic links are not followed and only `.md` pages are taken, as the loader does.
    """
    base = Path(directory)
    profile = base / f"{slug}.yaml"
    files = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted([profile, *base.glob(f"{slug}.*.yaml")])
        if path.is_file() and not path.is_symlink()
    }
    tree = base / slug
    pages = {}
    if tree.is_dir() and not tree.is_symlink():
        for path in sorted(tree.rglob("*.md")):
            if path.is_file() and not path.is_symlink():
                pages[path.relative_to(tree).as_posix()] = path.read_text(encoding="utf-8")
    bundle = {"profile_file": profile.name, "files": files, "knowledge": pages}
    bundle["bundle_sha256"] = company_bundle_sha256(bundle)
    return bundle


def _write_bundle(bundle, root):
    files = bundle.get("files")
    name = bundle.get("profile_file")
    pages = bundle.get("knowledge") or {}
    if (
        not isinstance(files, dict)
        or not isinstance(pages, dict)
        or not isinstance(name, str)
        or name not in files
        or not all(
            isinstance(k, str) and _YAML_NAME.fullmatch(k) and isinstance(v, str)
            for k, v in files.items()
        )
    ):
        raise EngineError("company_bundle_invalid")
    declared = bundle.get("bundle_sha256")
    if declared is not None and declared != company_bundle_sha256(bundle):
        raise EngineError("company_bundle_invalid")
    root.mkdir(parents=True)
    for key, text in files.items():
        (root / key).write_text(text, encoding="utf-8")
    # The upstream layout: the knowledge tree sits in `knowledge/` beside the profile.
    tree = root / "knowledge"
    for rel, text in pages.items():
        parts = rel.split("/") if isinstance(rel, str) else []
        if (
            not 1 <= len(parts) <= 2
            or not all(_PAGE_PART.fullmatch(part) for part in parts)
            or not rel.endswith(".md")
            or not isinstance(text, str)
        ):
            raise EngineError("company_bundle_invalid")
        target = tree.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root / name, tree if pages else None


def company_inputs(payload, workdir):
    """Company profile, knowledge and gate texts for one run.

    v2 loads the bundled company files with the upstream loader, so provenance levels,
    the knowledge excerpt chosen per notice and the portfolio texts the gates compare are
    the upstream behavior. v1 keeps the conservative projection.
    """
    if payload.get("schema_version") == INPUT_V2:
        bundle = payload.get("company_bundle")
        if not isinstance(bundle, dict):
            raise EngineError("company_bundle_invalid")
        profile_path, tree = _write_bundle(bundle, Path(workdir) / "company")
        try:
            view = load_evidence_view(profile_path)
            knowledge = (
                load_knowledge(tree, profile=view.profile, filter_work_unit_refs=True)
                if tree is not None else None
            )
        except (ProfileError, KnowledgeError, OSError, ValueError):
            raise EngineError("company_bundle_invalid") from None
        return CompanyInputs(
            profile=view,
            company_input_hash=view.company_input_hash,
            knowledge=knowledge,
            portfolio_texts=portfolio_gate_texts(knowledge)
            if knowledge is not None
            else None,
            record={
                "source": "company_bundle",
                "mapped_fields": [],
                "complete": True,
                "source_profile_sha256": payload.get("profile_sha256"),
                "engine_company_input_hash": view.company_input_hash,
                "bundle_sha256": company_bundle_sha256(bundle),
                "knowledge_hash": knowledge.hash if knowledge is not None else None,
            },
        )
    profile, projected = project_company(payload)
    view = CompanyEvidenceView(profile)
    return CompanyInputs(
        profile=profile,
        company_input_hash=view.company_input_hash,
        knowledge=None,
        portfolio_texts=None,
        record={
            "mapped_fields": projected,
            "complete": False,
            # BidOps binding (frozen profile version hash) and the engine's own
            # fingerprint of the projected profile are kept apart for audit.
            "source_profile_sha256": payload["profile_sha256"],
            "engine_company_input_hash": view.company_input_hash,
        },
    )


def source_evidence(analysis, payload, sections=None):
    """Map exact verified quotes to frozen BidOps blocks.

    The search is limited to the blocks of the section the engine cites for that quote
    (`Evidence.section_id`, resolved through `sections` and the block projection).
    Only when the engine names no usable section, or the quote is not inside it, is the
    whole frozen input searched. Every occurrence found is listed; `location_status` is
    `exact` for a single occurrence and `ambiguous` otherwise, and `basis` says whether
    the cited section or the whole input was searched. No match means no locator.
    """
    documents = {d["document_version_id"]: d for d in payload["documents"]}
    source = payload["blocks"]
    _, _, origins = _project_blocks(payload)
    section_blocks = {}
    for section in sections or ():
        indices = sorted(
            {
                origin
                for idx in range(section.block_start, section.block_end + 1)
                if 0 <= idx < len(origins)
                for origin in origins[idx]
            }
        )
        section_blocks[section.id] = indices
    everything = list(range(len(source)))
    found = []

    def occurrences(quote, indices):
        hits = []
        for index in indices:
            text = source[index]["text"]
            start = text.find(quote)
            while start >= 0:
                hits.append((index, start))
                start = text.find(quote, start + 1)
        return hits

    def walk(value, path):
        if isinstance(value, dict):
            if isinstance(value.get("quote"), str) and value.get("verified") is True:
                quote = value["quote"]
                if quote:
                    cited = section_blocks.get(value.get("section_id"))
                    hits = occurrences(quote, cited) if cited else []
                    basis = "cited_section"
                    if not hits:
                        hits = occurrences(quote, everything)
                        basis = "whole_input"
                    status = "exact" if len(hits) == 1 else "ambiguous"
                    for index, start in hits:
                        block = source[index]
                        found.append(
                            {
                                "evidence_path": path,
                                "document_version_id": block["document_version_id"],
                                "source_sha256": documents[
                                    block["document_version_id"]
                                ]["source_sha256"],
                                "block_key": block["block_key"],
                                "page": block.get("page"),
                                "start": start,
                                "end": start + len(quote),
                                "location_status": status,
                                "basis": basis,
                            }
                        )
            for k, v in value.items():
                walk(v, path + "/" + k)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, path + "/" + str(i))

    walk(analysis, "")
    return found


def raw_blocks(payload):
    """Preserve structured table cells and source order for upstream normalization."""
    blocks, tables, _ = _project_blocks(payload)
    return blocks, tables


def _project_blocks(payload):
    """Engine blocks/tables plus, per engine block, the indices of its BidOps blocks."""
    from .ingest.models import Block, RawTable

    blocks = []
    tables = []
    origins = []
    cells = {}
    for index, block in enumerate(payload["blocks"]):
        if block.get("type") == "table_cell":
            key = (
                block["document_version_id"],
                block.get("attributes", {}).get("table_key"),
            )
            cells.setdefault(key, []).append((index, block))
    for index, block in enumerate(payload["blocks"]):
        kind = block.get("type")
        if kind == "table_cell":
            continue
        if kind == "table":
            members = cells.get(
                (
                    block["document_version_id"],
                    block.get("attributes", {}).get("table_key"),
                ),
                [],
            )
            group = [cell for _, cell in members]
            if not group:
                continue
            if any(
                type(c["attributes"].get("row")) is not int
                or type(c["attributes"].get("column")) is not int
                or c["attributes"]["row"] < 0
                or c["attributes"]["column"] < 0
                for c in group
            ):
                raise EngineError("invalid_table_coordinates")
            maxrow = max(c["attributes"]["row"] for c in group)
            maxcol = max(c["attributes"]["column"] for c in group)
            if maxrow > 10000 or maxcol > 1000 or (maxrow + 1) * (maxcol + 1) > 200000:
                raise EngineError("table_too_large")
            rows = [[""] * (maxcol + 1) for _ in range(maxrow + 1)]
            for cell in group:
                rows[cell["attributes"]["row"]][cell["attributes"]["column"]] = cell[
                    "text"
                ]
            table_id = f"T{len(tables) + 1:03d}"
            tables.append(
                RawTable(
                    id=table_id,
                    block_idx=len(blocks),
                    rows=rows,
                    document_version_id=block["document_version_id"],
                )
            )
            blocks.append(
                Block(
                    idx=len(blocks),
                    kind="table",
                    text="\n".join(" | ".join(r) for r in rows),
                    table_id=table_id,
                    page=block.get("page"),
                )
            )
            origins.append([index, *(i for i, _ in members)])
        else:
            for line in block["text"].splitlines():
                if line.strip():
                    blocks.append(
                        Block(
                            idx=len(blocks),
                            kind="paragraph",
                            text=line,
                            page=block.get("page"),
                        )
                    )
                    origins.append([index])
    return blocks, tables, origins
