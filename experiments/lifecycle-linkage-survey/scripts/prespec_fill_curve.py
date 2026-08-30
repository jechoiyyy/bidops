#!/usr/bin/env python3
"""Measure an age-to-fill curve for pre-specification linkage fields.

The order-plan curve in ``plan_fill_curve.py`` answered one question: how long
after publication does ``bidNtceNoList`` stop filling in?  T-2c asks the same
question of pre-specifications, which carry ``bidNtceNoList`` and ``chgDt``
too but were only ever measured in a single three-day cohort (29/650).

The design is the same cross-section: several publication cohorts of equal
width, observed once each, at increasing ages.  Different cohorts are not
repeated observations of the same records, so a longitudinal re-query of one
window remains the source of truth if the two disagree.

Collection requires ``--execute``.  Raw pages are preserved per window and
``--from-raw`` recomputes without any network call.  Contact fields
(``ofclNm``, ``ofclTelNo``) are never copied into the derived artifacts.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[2]
sys.path.insert(0, str(_SCRIPT_DIR.parents[1] / "order-plan-screening" / "scripts"))
sys.path.insert(0, str(_SCRIPT_DIR))

from common import ExperimentError, load_json, write_json_new  # noqa: E402
from endpoints import ENDPOINTS, KST  # noqa: E402
import survey  # noqa: E402


CURVE_SCHEMA = "bidops.lifecycle-prespec-fill-curve.v1"
MANIFEST_SCHEMA = "bidops.lifecycle-prespec-fill-curve-manifest.v1"
DEFAULT_ROWS = 500
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_WINDOW_DAYS = 3
# Ages chosen to bracket the order-plan curve's plateau at 15-17 days and to
# keep one long point well inside the endpoint's 365-day inquiry cap.
DEFAULT_AGES = (3, 9, 17, 31, 60, 150)
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "data" / "experiments" / "lifecycle-linkage-survey"
# The endpoint measured in the 2026-08-28 survey.  Both pre-spec operations
# returned identical fields and values over 650 records; PPSSrch is the one
# the product collector uses.
ENDPOINT_KEY = "prespec_search"


@dataclass(frozen=True)
class Window:
    age_days: int
    from_date: date
    to_date: date  # exclusive

    @property
    def slug(self) -> str:
        return f"age-{self.age_days:03d}"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def build_windows(observed_on: date, ages: Sequence[int], width_days: int) -> list[Window]:
    if width_days < 1:
        raise ExperimentError("invalid_window", "window 폭은 1일 이상이어야 합니다")
    seen: set[int] = set()
    windows: list[Window] = []
    for age in sorted(ages):
        if age < 1:
            raise ExperimentError("invalid_age", "age는 1일 이상이어야 합니다")
        if age > 365 - width_days:
            raise ExperimentError("age_exceeds_cap", "inqryDiv=1은 365일 상한이 있습니다")
        if age in seen:
            raise ExperimentError("duplicate_age", f"중복된 age: {age}")
        seen.add(age)
        end = observed_on - timedelta(days=age)
        windows.append(Window(age, end - timedelta(days=width_days), end))
    return windows


def summarise(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Count the two linkage signals without interpreting absent values."""

    total = len(items)
    with_bid_list = sum(1 for item in items if _text(item.get("bidNtceNoList")))
    with_changed = sum(1 for item in items if _text(item.get("chgDt")))
    sw_target = sum(1 for item in items if _text(item.get("swBizObjYn")) == "Y")
    with_attachment = sum(
        1
        for item in items
        if any(_text(item.get(f"specDocFileUrl{index}")) for index in range(1, 6))
    )
    # A field that is absent from every record is reported as unknown rather
    # than as a zero fill rate; the two are not the same observation.
    present_keys = {key for item in items for key in item}
    return {
        "records": total,
        "bid_ntce_no_list": {
            "filled": with_bid_list,
            "rate": (with_bid_list / total) if total else None,
            "field_present": "bidNtceNoList" in present_keys if total else None,
        },
        "changed_at": {
            "filled": with_changed,
            "rate": (with_changed / total) if total else None,
            "field_present": "chgDt" in present_keys if total else None,
        },
        "sw_business_object": {
            "filled": sw_target,
            "rate": (sw_target / total) if total else None,
        },
        "attachment_url": {
            "filled": with_attachment,
            "rate": (with_attachment / total) if total else None,
        },
    }


def _window_raw_dir(output_dir: Path, run_slug: str, window: Window) -> Path:
    return output_dir / run_slug / "raw" / window.slug


def collect(args: argparse.Namespace) -> int:
    if not args.execute:
        raise ExperimentError("execute_required", "외부 호출에는 --execute가 필요합니다")
    observed_on = args.observed_on or datetime.now(KST).date()
    windows = build_windows(observed_on, args.ages, args.window_days)
    endpoint = ENDPOINTS[ENDPOINT_KEY]
    fetcher = survey.SurveyFetcher(
        service_key=survey.get_service_key(),
        timeout=args.timeout,
        max_attempts=args.max_attempts,
        request_limit=args.max_requests,
    )
    run_slug = f"{observed_on.isoformat().replace('-', '')}-prespec-fill-curve"
    manifest_windows: list[dict[str, Any]] = []
    for window in windows:
        raw_dir = _window_raw_dir(args.output_dir, run_slug, window)
        received = survey.collect_pages(
            endpoint, raw_dir, window.from_date, window.to_date, args.rows, fetcher
        )
        manifest_windows.append(
            {
                "age_days": window.age_days,
                "slug": window.slug,
                "from": window.from_date.isoformat(),
                "to_exclusive": window.to_date.isoformat(),
                "received": received,
            }
        )
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "endpoint_id": endpoint.endpoint_id,
        "observed_on": observed_on.isoformat(),
        "timezone": "Asia/Seoul",
        "window_days": args.window_days,
        "rows": args.rows,
        "requests": fetcher.request_count,
        "windows": manifest_windows,
    }
    write_json_new(args.output_dir / run_slug / "manifest.json", manifest)
    return _derive(args.output_dir / run_slug)


def _derive(run_dir: Path) -> int:
    manifest = load_json(run_dir / "manifest.json")
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ExperimentError("schema_mismatch", "manifest schema가 다릅니다")
    points: list[dict[str, Any]] = []
    for entry in manifest["windows"]:
        raw_dir = run_dir / "raw" / entry["slug"]
        items = survey.items_from_pages(survey.read_raw_pages(raw_dir))
        if len(items) != entry["received"]:
            raise ExperimentError(
                "raw_count_mismatch",
                f"{entry['slug']}: manifest {entry['received']} != raw {len(items)}",
            )
        points.append({**{k: entry[k] for k in ("age_days", "from", "to_exclusive")}, **summarise(items)})
    result = {
        "schema_version": CURVE_SCHEMA,
        "endpoint_id": manifest["endpoint_id"],
        "observed_on": manifest["observed_on"],
        "timezone": manifest["timezone"],
        "window_days": manifest["window_days"],
        "design": (
            "cross-sectional: each point is a different publication cohort observed once, "
            "not a repeated observation of the same records"
        ),
        "points": points,
    }
    write_json_new(run_dir / "prespec-fill-curve.json", result)
    for point in points:
        bid = point["bid_ntce_no_list"]
        chg = point["changed_at"]
        print(
            f"age {point['age_days']:>3}d  n={point['records']:>4}  "
            f"bidNtceNoList {bid['filled']:>4} "
            f"({'n/a' if bid['rate'] is None else format(bid['rate'], '.1%')})  "
            f"chgDt {chg['filled']:>4} "
            f"({'n/a' if chg['rate'] is None else format(chg['rate'], '.1%')})"
        )
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-raw", type=Path, help="저장된 raw에서 재계산합니다")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--observed-on", type=date.fromisoformat)
    parser.add_argument("--ages", type=int, nargs="+", default=list(DEFAULT_AGES))
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--max-requests", type=int, default=60)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--execute", action="store_true", help="외부 G2B 호출을 명시적으로 허용합니다")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return _derive(args.from_raw) if args.from_raw else collect(args)
    except ExperimentError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
