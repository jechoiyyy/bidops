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


def source_evidence(analysis, payload):
    """Only exact substring matches in frozen blocks acquire source locators."""
    documents = {d["document_version_id"]: d for d in payload["documents"]}
    found = []

    def walk(value, path):
        if isinstance(value, dict):
            if isinstance(value.get("quote"), str) and value.get("verified") is True:
                quote = value["quote"]
                if quote:
                    for block in payload["blocks"]:
                        start = block["text"].find(quote)
                        if start >= 0:
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
    from .ingest.models import Block, RawTable

    blocks = []
    tables = []
    cells = {}
    for block in payload["blocks"]:
        if block.get("type") == "table_cell":
            key = (
                block["document_version_id"],
                block.get("attributes", {}).get("table_key"),
            )
            cells.setdefault(key, []).append(block)
    for block in payload["blocks"]:
        kind = block.get("type")
        if kind == "table_cell":
            continue
        if kind == "table":
            group = cells.get(
                (
                    block["document_version_id"],
                    block.get("attributes", {}).get("table_key"),
                ),
                [],
            )
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
    return blocks, tables
