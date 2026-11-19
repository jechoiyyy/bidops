"""Explicit conservative v2→v1 projection and BidOps block provenance mapping."""

import re
from .company.schema import CompanyProfile


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
                raise ValueError("invalid_table_coordinates")
            maxrow = max(c["attributes"]["row"] for c in group)
            maxcol = max(c["attributes"]["column"] for c in group)
            if maxrow > 10000 or maxcol > 1000 or (maxrow + 1) * (maxcol + 1) > 200000:
                raise ValueError("table_too_large")
            rows = [[""] * (maxcol + 1) for _ in range(maxrow + 1)]
            for cell in group:
                rows[cell["attributes"]["row"]][cell["attributes"]["column"]] = cell[
                    "text"
                ]
            table_id = f"T{len(tables) + 1:03d}"
            tables.append(RawTable(id=table_id, block_idx=len(blocks), rows=rows))
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
