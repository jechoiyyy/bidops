"""Command line entry point for Step 2 artifact ingestion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..core.config import get_settings
from ..core.db import SessionFactory, init_db
from .loader import discover_run_dirs, ingest_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load BidOps workflow artifacts into SQLite.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", dest="run_id", help="one run directory, e.g. 20260817-20260823")
    group.add_argument("--all", action="store_true", help="ingest every directory under data/runs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    init_db()
    run_dirs = discover_run_dirs(settings.bidops_root / "data", args.run_id if not args.all else None)
    if args.run_id and not run_dirs:
        parser = build_parser()
        parser.error(f"회차 디렉토리를 찾을 수 없습니다: {args.run_id}")
    results = []
    with SessionFactory() as session:
        for run_directory in run_dirs:
            result = ingest_run(
                run_directory,
                session,
                reports_root=settings.bidops_root / "reports",
            )
            results.append(result.as_dict())
    print(json.dumps(results[0] if args.run_id else results, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

