#!/usr/bin/env python3
"""Split a frozen order-plan run into per-published-day gold runs.

The input run's ``collected-order-plans.json`` is read-only (source runs are
immutable).  Each Asia/Seoul published date present in the artifact becomes a
new, independent run directory named ``gate-gold-<YYYYMMDD>-plans`` so it can
be fed into C-2 quality-gate measurement one day at a time.  Item objects are
never modified: they are copied by reference into the day they belong to, so
``source_sha256`` and every other field survive unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))
INPUT_FILE = "collected-order-plans.json"
DEFAULT_OUTPUT_ROOT = Path("data/runs")


class SplitError(RuntimeError):
    """A safe, stable failure that never carries file contents."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "gold 회차의 collected-order-plans.json을 published_at의 KST 날짜별로 "
            "나눠 새 회차 디렉터리를 만듭니다."
        )
    )
    parser.add_argument("--input-run", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` that fails closed on a duplicate JSON object key."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SplitError("duplicate_key", f"입력 JSON에 중복 key가 있습니다: {key}")
        result[key] = value
    return result


def read_input_artifact(input_run: Path) -> tuple[bytes, dict[str, Any]]:
    """Read the immutable source artifact without ever writing to it."""

    if input_run.is_symlink() or not input_run.is_dir():
        raise SplitError("input_run_invalid", "입력 회차 디렉터리가 아닙니다.")
    input_path = input_run / INPUT_FILE
    if input_path.is_symlink() or not input_path.is_file():
        raise SplitError("input_missing", f"입력 산출물이 없습니다: {input_path}")
    try:
        raw_bytes = input_path.read_bytes()
    except OSError as exc:
        raise SplitError("input_unreadable", "입력 산출물을 읽을 수 없습니다.") from exc
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise SplitError("invalid_encoding", "입력 산출물이 UTF-8이 아닙니다.") from exc
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise SplitError("invalid_json", "입력 산출물이 유효한 JSON이 아닙니다.") from exc
    if not isinstance(data, dict):
        raise SplitError("invalid_contract", "입력 산출물이 JSON object가 아닙니다.")
    return raw_bytes, data


def _parse_date_bound(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise SplitError("invalid_source_window", f"source_window.{field} 값이 없습니다.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SplitError(
            "invalid_source_window", f"source_window.{field} 형식이 잘못됐습니다: {value}"
        ) from exc


def _parse_published_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SplitError("missing_published_at", "order_plans 항목에 published_at이 없습니다.")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise SplitError(
            "invalid_published_at", f"published_at 형식이 잘못됐습니다: {value}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SplitError(
            "invalid_published_at", f"published_at에 timezone 정보가 없습니다: {value}"
        )
    return parsed


def group_by_published_day(
    order_plans: list[Any], window_from: date, window_to: date
) -> dict[date, list[dict[str, Any]]]:
    """Group items by their Asia/Seoul published date, preserving input order.

    Fails closed (raising, writing nothing) on any item missing
    ``published_at`` or falling outside the input's half-open source_window.
    """

    groups: dict[date, list[dict[str, Any]]] = {}
    for item in order_plans:
        if not isinstance(item, dict):
            raise SplitError("invalid_contract", "order_plans 항목이 object가 아닙니다.")
        published_dt = _parse_published_datetime(item.get("published_at"))
        published_day = published_dt.astimezone(KST).date()
        if not window_from <= published_day < window_to:
            raise SplitError(
                "window_boundary_mismatch",
                f"published_at이 source_window 밖입니다: {item.get('published_at')}",
            )
        groups.setdefault(published_day, []).append(item)
    return groups


def _output_run_id(day: date) -> str:
    return f"gate-gold-{day:%Y%m%d}-plans"


def build_day_artifact(
    data: dict[str, Any],
    day: date,
    items: list[dict[str, Any]],
    *,
    input_run_id: str,
    artifact_sha256: str,
) -> dict[str, Any]:
    """Build one day's artifact, keeping the input's top-level key set."""

    counts_in = data.get("counts")
    page_count = counts_in.get("page_count") if isinstance(counts_in, dict) else None
    request_count = counts_in.get("request_count") if isinstance(counts_in, dict) else None

    metadata = deepcopy(data.get("metadata"))
    if not isinstance(metadata, dict):
        raise SplitError("invalid_contract", "metadata가 object가 아닙니다.")
    metadata["derived_from"] = {
        "run_id": input_run_id,
        "artifact_sha256": artifact_sha256,
        "tool": "split_order_plan_run_by_day.py",
        "published_day": day.isoformat(),
    }

    output = dict(data)
    output["order_plans"] = list(items)
    output["source_window"] = {
        "from": day.isoformat(),
        "to": (day + timedelta(days=1)).isoformat(),
        "timezone": "Asia/Seoul",
    }
    output["counts"] = {
        "total": len(items),
        "order_plans": len(items),
        "in_scope": len(items),
        "source_total": len(items),
        "source_records": len(items),
        "excluded_out_of_scope": 0,
        "excluded_business_divisions": 0,
        "page_count": page_count,
        "request_count": request_count,
    }
    output["warnings"] = []
    output["metadata"] = metadata
    return output


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-split-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.rename(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def split_run(input_run: Path, output_root: Path) -> list[tuple[str, int]]:
    """Split one immutable run into per-day gold runs.

    Returns ``(run_id, count)`` pairs sorted by day. Nothing is written if any
    validation step fails, and nothing is written if any output directory
    already exists.
    """

    raw_bytes, data = read_input_artifact(input_run)
    artifact_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    input_run_id = input_run.resolve(strict=False).name

    source_window = data.get("source_window")
    if not isinstance(source_window, dict):
        raise SplitError("invalid_source_window", "source_window가 object가 아닙니다.")
    window_from = _parse_date_bound(source_window.get("from"), "from")
    window_to = _parse_date_bound(source_window.get("to"), "to")
    if window_to <= window_from:
        raise SplitError("invalid_source_window", "source_window.to는 from보다 뒤여야 합니다.")

    order_plans = data.get("order_plans")
    if not isinstance(order_plans, list) or not order_plans:
        raise SplitError("source_run_incomplete", "입력 회차에 order_plans가 없습니다.")

    groups = group_by_published_day(order_plans, window_from, window_to)

    # Resolve every output directory before writing anything: one existing
    # directory must abort the whole split, not just its own day.
    planned: list[tuple[date, Path]] = []
    for day in sorted(groups):
        output_dir = output_root / _output_run_id(day)
        if output_dir.exists() or output_dir.is_symlink():
            raise SplitError(
                "artifact_exists", f"기존 출력 디렉터리를 덮어쓸 수 없습니다: {output_dir}"
            )
        planned.append((day, output_dir))

    results: list[tuple[str, int]] = []
    for day, output_dir in planned:
        items = groups[day]
        artifact = build_day_artifact(
            data,
            day,
            items,
            input_run_id=input_run_id,
            artifact_sha256=artifact_sha256,
        )
        _atomic_write_json(output_dir / INPUT_FILE, artifact)
        results.append((output_dir.name, len(items)))
    return results


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        results = split_run(args.input_run, args.output_root)
    except SplitError as exc:
        print(
            json.dumps({"status": "failed", "error_code": exc.code}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    for run_id, count in results:
        print(f"{run_id} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
