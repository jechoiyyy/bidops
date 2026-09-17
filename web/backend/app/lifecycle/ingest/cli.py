"""Command line entry point for Step 2 artifact ingestion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ...core.config import get_settings
from ...core.db import SessionFactory, init_db
from .loader import discover_run_dirs, ingest_run, tracked_backfill


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load BidOps workflow artifacts into SQLite.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run", dest="run_id", help="one run directory, e.g. 20260817-20260823")
    group.add_argument("--all", action="store_true", help="ingest every directory under data/runs")
    parser.add_argument(
        "--collection",
        action="store_true",
        help=(
            "with --run: index every collected record and load only the selected ones "
            "instead of the validation sample"
        ),
    )
    parser.add_argument(
        "--tracked-backfill",
        action="store_true",
        help=(
            "load index-only records referenced by 계속 추적·보류 opportunities; "
            "runs after --run when both are given"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.tracked_backfill and args.all:
        parser.error("--tracked-backfill은 --all과 함께 쓸 수 없습니다")
    if args.collection and not args.run_id:
        parser.error("--collection은 --run과 함께 씁니다")
    if not (args.run_id or args.all or args.tracked_backfill):
        parser.error("--run, --all, --tracked-backfill 중 하나가 필요합니다")
    settings = get_settings()
    init_db()
    data_root = settings.bidops_root / "data"
    run_dirs: list[Path] = []
    if args.run_id or args.all:
        run_dirs = discover_run_dirs(data_root, args.run_id if not args.all else None)
        if args.run_id and not run_dirs:
            parser.error(f"회차 디렉토리를 찾을 수 없습니다: {args.run_id}")
    results = []
    backfill: dict[str, object] | None = None
    with SessionFactory() as session:
        for run_directory in run_dirs:
            result = ingest_run(
                run_directory,
                session,
                reports_root=settings.bidops_root / "reports",
                selection="collection" if args.collection else "validation",
            )
            results.append(result.as_dict())
        if args.tracked_backfill:
            try:
                backfill = tracked_backfill(session, runs_root=data_root / "runs")
                session.commit()
            except Exception:
                session.rollback()
                raise
    if args.all:
        output: object = results
    elif args.run_id:
        output = results[0]
        if backfill is not None:
            output = {**results[0], "tracked_backfill": backfill}
    else:
        output = {"tracked_backfill": backfill}
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
