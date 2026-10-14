#!/usr/bin/env python3
"""Summarize requirement-card extraction from existing structure snapshots.

The script only reads the supplied JSON files and calls the deterministic
document-segment functions. It does not open a database, contact a service, or
include source text in its output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "web" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class InputError(Exception):
    """An invalid or incomplete CLI input, without source details."""


class ProcessingError(Exception):
    """A supplied document could not be summarized safely."""


class OutputError(Exception):
    """The explicit output path could not be created without replacement."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize requirement-card inventory from existing structure and page-map JSON.",
    )
    parser.add_argument("--dir", type=Path, help="directory with <name>.structure.json and <name>.para_page_map.json pairs")
    parser.add_argument("--structure", action="append", type=Path, help="structure JSON; repeat alongside --page-map")
    parser.add_argument("--page-map", action="append", type=Path, help="page-map JSON; repeat alongside --structure")
    parser.add_argument("--out", type=Path, help="create this JSON output file without replacing an existing path")
    return parser


def _document_name(structure_path: Path) -> str:
    suffix = ".structure.json"
    if structure_path.name.endswith(suffix):
        return structure_path.name[: -len(suffix)]
    return structure_path.stem


def _input_pairs(args: argparse.Namespace) -> list[tuple[str, Path, Path]]:
    if args.dir is not None:
        if args.structure or args.page_map:
            raise InputError
        directory = args.dir
        if not directory.is_dir():
            raise InputError

        structures: dict[str, Path] = {}
        page_maps: dict[str, Path] = {}
        try:
            for path in directory.iterdir():
                if path.name.endswith(".structure.json"):
                    name = path.name[: -len(".structure.json")]
                    if name:
                        structures[name] = path
                elif path.name.endswith(".para_page_map.json"):
                    name = path.name[: -len(".para_page_map.json")]
                    if name:
                        page_maps[name] = path
        except OSError as exc:
            raise InputError from exc

        names = sorted(set(structures) | set(page_maps))
        if not names or set(structures) != set(page_maps):
            raise InputError
        return [(name, structures[name], page_maps[name]) for name in names]

    structures = args.structure or []
    page_maps = args.page_map or []
    if not structures or len(structures) != len(page_maps):
        raise InputError
    return [
        (_document_name(structure), structure, page_map)
        for structure, page_map in zip(structures, page_maps, strict=True)
    ]


def _read_json_object(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError from exc
    if not isinstance(value, Mapping):
        raise InputError
    return value


def _summarize(
    name: str,
    structure_path: Path,
    page_map_path: Path,
    *,
    build_manifest_payload: Any,
    resolve_card_pages: Any,
) -> dict[str, Any]:
    structure = _read_json_object(structure_path)
    page_map = _read_json_object(page_map_path)
    if not isinstance(page_map.get("blocks"), list):
        raise InputError

    try:
        payload = build_manifest_payload(structure)
        cards = resolve_card_pages(payload, page_map)
    except Exception as exc:  # noqa: BLE001 - never echo source or parser errors
        raise ProcessingError from exc

    statuses = [card.get("mapping_status") for card in cards]
    allowed_statuses = {"mapped", "partial", "inherited", "unavailable"}
    if any(status not in allowed_statuses for status in statuses):
        raise ProcessingError

    summary = payload.get("inventory_summary")
    if not isinstance(summary, Mapping):
        raise ProcessingError
    warnings = payload.get("warnings")
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise ProcessingError

    categories = {
        str(card["card"]["category"]).strip()
        for card in cards
        if isinstance(card.get("card"), Mapping)
        and isinstance(card["card"].get("category"), str)
        and card["card"]["category"].strip()
    }
    prefixes = summary.get("prefixes", [])
    duplicate_ids = summary.get("duplicate_ids", [])
    if not isinstance(prefixes, list) or not isinstance(duplicate_ids, list):
        raise ProcessingError

    return {
        "name": name,
        "card_count": len(cards),
        "inherited_page_count": statuses.count("inherited"),
        "mapped_page_count": sum(status in {"mapped", "partial"} for status in statuses),
        "unavailable_count": statuses.count("unavailable"),
        "prefixes": sorted({str(value) for value in prefixes}),
        "categories": sorted(categories),
        "duplicate_ids": sorted({str(value) for value in duplicate_ids}),
        "warnings": warnings,
    }


def _render_json(value: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _write_new_file(path: Path, content: str) -> None:
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=".hp-card-inventory-check-",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard link creates the target only if absent, so a previous evidence
        # file (or symlink at that path) cannot be silently replaced.
        os.link(temporary_path, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise OutputError from exc
    except OSError as exc:
        raise OutputError from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        pairs = _input_pairs(args)
        # Import only the pure product functions. No service, DB, or network
        # client is constructed by this script.
        from app.deep_review.services.document_segments import (  # noqa: PLC0415
            build_manifest_payload,
            resolve_card_pages,
        )

        result = [
            _summarize(
                name,
                structure_path,
                page_map_path,
                build_manifest_payload=build_manifest_payload,
                resolve_card_pages=resolve_card_pages,
            )
            for name, structure_path, page_map_path in pairs
        ]
    except InputError:
        print("hp-card-inventory-check: invalid or incomplete input", file=sys.stderr)
        return 2
    except ImportError:
        print("hp-card-inventory-check: product modules are unavailable", file=sys.stderr)
        return 1
    except ProcessingError:
        print("hp-card-inventory-check: document processing failed", file=sys.stderr)
        return 1

    rendered = _render_json(result)
    if args.out is not None:
        try:
            _write_new_file(args.out, rendered)
        except OutputError:
            print("hp-card-inventory-check: output path could not be created safely", file=sys.stderr)
            return 1
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
