#!/usr/bin/env python3
"""Measure an age-to-linkage-fill curve from cross-sectional order-plan windows.

Each window is collected once through the existing lifecycle survey contract.
The windows are deliberately different publication cohorts: their fill rates
are a cross-sectional approximation, not repeated observations of the same
plans.  A longitudinal re-query of one original window remains the source of
truth when the two approaches disagree.

The script has two modes:

* collection mode requires ``--execute`` and stores immutable raw pages under
  one subdirectory per window;
* ``--from-raw`` mode never constructs a fetcher and recalculates the result
  from those stored pages and the collection manifest.

No contact fields are copied into the derived JSON or Markdown.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
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


PLAN_FILL_CURVE_SCHEMA = "bidops.lifecycle-plan-fill-curve.v1"
MANIFEST_SCHEMA = "bidops.lifecycle-plan-fill-curve-manifest.v1"
DEFAULT_ROWS = 500
DEFAULT_MAX_REQUESTS = 40
DEFAULT_TIMEOUT = 120
DEFAULT_MAX_ATTEMPTS = 2
OUTPUT_JSON = "plan-fill-curve.json"
OUTPUT_MARKDOWN = "plan-fill-curve.md"
MANIFEST_NAME = "plan-fill-curve-manifest.json"
WINDOW_DIR_RE = re.compile(r"^window-[0-9]+-[0-9]{8}-[0-9]{8}$")
SOURCE_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y%m%d%H%M%S",
    "%Y%m%d%H%M",
)

DEFAULT_OUTPUT_DIR = (
    _REPO_ROOT
    / "data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/plan-fill-curve"
)


@dataclass(frozen=True)
class Window:
    """A publication window using an exclusive end date internally."""

    from_date: date
    to_exclusive: date
    identifier: str = ""

    @property
    def to_inclusive(self) -> date:
        return self.to_exclusive - timedelta(days=1)


DEFAULT_WINDOWS = (
    Window(date(2026, 8, 24), date(2026, 8, 27)),
    Window(date(2026, 8, 10), date(2026, 8, 13)),
    Window(date(2026, 7, 27), date(2026, 7, 30)),
    Window(date(2026, 7, 1), date(2026, 7, 4)),
    Window(date(2026, 6, 1), date(2026, 6, 4)),
    Window(date(2026, 4, 1), date(2026, 4, 4)),
)


LIMITATIONS = (
    "서로 다른 발행 구간을 비교하므로 같은 발주계획을 시간순으로 추적한 종단 관측이 아니다.",
    "계절성·연도별 발주 패턴 차이가 구간 간 수치에 섞일 수 있다.",
    "횡단면 채움률만으로 필요한 재조회 종료일이나 최대 k를 종단 결론으로 확정하지 않는다.",
    "횡단면과 종단 결과가 어긋나면 2026-08-24~2026-08-26 구간의 반복 재조회인 종단 관측을 정본으로 삼는다.",
)


def parse_observed_at(value: str) -> datetime:
    """Parse an ISO timestamp and require an explicit timezone."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExperimentError("invalid_timestamp", "observed-at timestamp 형식이 잘못됐습니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExperimentError("invalid_timestamp", "observed-at에 timezone 정보가 필요합니다")
    return parsed.astimezone(KST)


def parse_window_spec(spec: str) -> Window:
    """Parse ``YYYY-MM-DD:YYYY-MM-DD`` where both dates are inclusive."""

    raw = spec.strip()
    if ":" in raw:
        left, right = raw.split(":", 1)
    elif ".." in raw:
        left, right = raw.split("..", 1)
    elif "," in raw:
        left, right = raw.split(",", 1)
    else:
        raise ExperimentError(
            "invalid_window",
            "window은 YYYY-MM-DD:YYYY-MM-DD 형식이어야 합니다(종료일 포함)",
        )
    try:
        from_date = date.fromisoformat(left.strip())
        to_inclusive = date.fromisoformat(right.strip())
    except ValueError as exc:
        raise ExperimentError("invalid_window", f"window 날짜 형식이 잘못됐습니다: {spec}") from exc
    if to_inclusive < from_date:
        raise ExperimentError("invalid_window", "window 종료일은 시작일보다 빠를 수 없습니다")
    return Window(from_date, to_inclusive + timedelta(days=1))


def window_directory_name(index: int, window: Window) -> str:
    return (
        f"window-{index:02d}-{window.from_date:%Y%m%d}-"
        f"{window.to_inclusive:%Y%m%d}"
    )


def _validate_windows(windows: Sequence[Window]) -> None:
    if not windows:
        raise ExperimentError("no_windows", "측정할 window가 없습니다")
    seen: set[tuple[date, date]] = set()
    for window in windows:
        if window.to_exclusive <= window.from_date:
            raise ExperimentError("invalid_window", "window 종료일은 시작일보다 뒤여야 합니다")
        key = (window.from_date, window.to_exclusive)
        if key in seen:
            raise ExperimentError("duplicate_window", "동일한 window가 중복됐습니다")
        seen.add(key)


def _require_aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ExperimentError("invalid_timestamp", "조회 시각에 timezone 정보가 필요합니다")
    return timestamp.astimezone(KST)


def _rate(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


def _nonblank(value: Any) -> bool:
    """Treat null, empty, and whitespace-only source strings as unfilled."""

    return isinstance(value, str) and bool(value.strip())


def _notice_numbers(value: Any) -> list[str]:
    if not _nonblank(value):
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _parse_source_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in SOURCE_DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 4)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 4)


def _delta_summary(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    deltas: list[float] = []
    for item in items:
        notice_at = _parse_source_datetime(item.get("nticeDt"))
        changed_at = _parse_source_datetime(item.get("chgDt"))
        if notice_at is None or changed_at is None:
            continue
        deltas.append((changed_at - notice_at).total_seconds() / 86400)
    return {
        "available_count": len(deltas),
        "unavailable_count": len(items) - len(deltas),
        "p50_days": _percentile(deltas, 0.50),
        "p90_days": _percentile(deltas, 0.90),
        "p95_days": _percentile(deltas, 0.95),
        "p99_days": _percentile(deltas, 0.99),
        "max_days": round(max(deltas), 4) if deltas else None,
    }


def calculate_window_metrics(
    window: Window,
    items: Sequence[dict[str, Any]],
    observed_at: datetime,
) -> dict[str, Any]:
    """Calculate safe aggregate metrics without retaining source records."""

    observed_at = _require_aware(observed_at)
    total = len(items)
    notice_counts = [_notice_numbers(item.get("bidNtceNoList")) for item in items]
    filled_bid = sum(bool(numbers) for numbers in notice_counts)
    count_distribution = Counter(len(numbers) for numbers in notice_counts)
    y_count = sum(item.get("ntceNticeYn") == "Y" for item in items)
    changed_count = sum(_nonblank(item.get("chgDt")) for item in items)
    return {
        "window": {
            "from": window.from_date.isoformat(),
            "to_inclusive": window.to_inclusive.isoformat(),
            "to_exclusive": window.to_exclusive.isoformat(),
        },
        "age_days": (observed_at.date() - window.to_inclusive).days,
        "total_count": total,
        "bidNtceNoList": {
            "filled_count": filled_bid,
            "fill_rate": _rate(filled_bid, total),
            "notice_number_total": sum(len(numbers) for numbers in notice_counts),
            "multi_notice_record_count": sum(len(numbers) > 1 for numbers in notice_counts),
            "max_notice_numbers_per_record": max(
                (len(numbers) for numbers in notice_counts), default=0
            ),
            "count_distribution": {
                str(count): count_value
                for count, count_value in sorted(count_distribution.items())
            },
        },
        "ntceNticeYn": {
            "y_count": y_count,
            "y_rate": _rate(y_count, total),
        },
        "chgDt": {
            "filled_count": changed_count,
            "fill_rate": _rate(changed_count, total),
        },
        "chgDt_minus_nticeDt": _delta_summary(items),
    }


def _page_request_count(wrappers: Sequence[dict[str, Any]]) -> int:
    total = 0
    for wrapper in wrappers:
        value = wrapper.get("request_attempts", 1)
        if not isinstance(value, int) or value < 1:
            raise ExperimentError("invalid_raw", "raw page request_attempts가 잘못됐습니다")
        total += value
    return total


def _parse_query_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ExperimentError("invalid_raw", f"raw query의 {field}가 없습니다")
    try:
        return datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=KST)
    except ValueError as exc:
        raise ExperimentError("invalid_raw", f"raw query의 {field} 형식이 잘못됐습니다") from exc


def _read_raw_window(raw_dir: Path) -> tuple[Window, list[dict[str, Any]], list[dict[str, Any]], int]:
    wrappers = survey.read_raw_pages(raw_dir)
    endpoint_id = ENDPOINTS["order_plan"].endpoint_id
    for wrapper in wrappers:
        if wrapper.get("endpoint_id") != endpoint_id:
            raise ExperimentError("schema_mismatch", f"order_plan endpoint가 아닙니다: {raw_dir.name}")
    first_query = wrappers[0].get("query")
    if not isinstance(first_query, dict):
        raise ExperimentError("invalid_raw", f"raw query가 없습니다: {raw_dir.name}")
    from_at = _parse_query_datetime(first_query.get("inqryBgnDt"), "inqryBgnDt")
    inclusive_end_at = _parse_query_datetime(first_query.get("inqryEndDt"), "inqryEndDt")
    window = Window(
        from_at.date(),
        (inclusive_end_at + timedelta(minutes=1)).date(),
        identifier=raw_dir.name,
    )
    for wrapper in wrappers[1:]:
        query = wrapper.get("query")
        if not isinstance(query, dict):
            raise ExperimentError("invalid_raw", f"raw query가 없습니다: {raw_dir.name}")
        if query.get("inqryBgnDt") != first_query.get("inqryBgnDt") or query.get(
            "inqryEndDt"
        ) != first_query.get("inqryEndDt"):
            raise ExperimentError("raw_window_mismatch", f"한 window의 날짜 query가 다릅니다: {raw_dir.name}")
    items = survey.items_from_pages(wrappers)
    return window, wrappers, items, _page_request_count(wrappers)


def _discover_raw_windows(raw_root: Path) -> list[tuple[Window, list[dict[str, Any]], list[dict[str, Any]], int]]:
    if not raw_root.is_dir():
        raise ExperimentError("raw_missing", f"raw 디렉터리가 없습니다: {raw_root.name}")
    directories = sorted(
        path
        for path in raw_root.iterdir()
        if path.is_dir() and WINDOW_DIR_RE.fullmatch(path.name)
    )
    if not directories:
        raise ExperimentError("raw_missing", "window-* raw 하위 디렉터리가 없습니다")
    return [_read_raw_window(path) for path in directories]


def _manifest_observed_at(raw_root: Path) -> tuple[datetime | None, int | None, int | None]:
    manifest_path = raw_root / MANIFEST_NAME
    if not manifest_path.exists():
        return None, None, None
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ExperimentError("schema_mismatch", "plan-fill-curve manifest schema가 다릅니다")
    observed_value = manifest.get("observed_at")
    if not isinstance(observed_value, str):
        raise ExperimentError("invalid_manifest", "manifest observed_at이 없습니다")
    observed_at = parse_observed_at(observed_value)
    rows = manifest.get("rows")
    max_requests = manifest.get("max_requests")
    if rows is not None and (not isinstance(rows, int) or rows < 1):
        raise ExperimentError("invalid_manifest", "manifest rows가 잘못됐습니다")
    if max_requests is not None and (not isinstance(max_requests, int) or max_requests < 1):
        raise ExperimentError("invalid_manifest", "manifest max_requests가 잘못됐습니다")
    return observed_at, rows, max_requests


def _fallback_observed_at(
    raw_windows: Sequence[tuple[Window, Sequence[dict[str, Any]], Sequence[dict[str, Any]], int]]
) -> datetime:
    timestamps: list[datetime] = []
    for _window, wrappers, _items, _requests in raw_windows:
        for wrapper in wrappers:
            value = wrapper.get("collected_at")
            if isinstance(value, str):
                try:
                    timestamps.append(parse_observed_at(value))
                except ExperimentError:
                    continue
    if not timestamps:
        raise ExperimentError("invalid_raw", "raw에서 조회 시각을 복원할 수 없습니다")
    return min(timestamps)


def _build_document(
    raw_windows: Sequence[tuple[Window, Sequence[dict[str, Any]], Sequence[dict[str, Any]], int]],
    observed_at: datetime,
    mode: str,
    rows: int | None,
    max_requests: int | None,
    observed_at_source: str,
) -> dict[str, Any]:
    observed_at = _require_aware(observed_at)
    window_reports: list[dict[str, Any]] = []
    for window, wrappers, items, request_count in raw_windows:
        report = calculate_window_metrics(window, items, observed_at)
        report["id"] = window.identifier
        report["page_count"] = len(wrappers)
        report["request_count"] = request_count
        report["raw_directory"] = window.identifier
        window_reports.append(report)
    window_reports.sort(key=lambda report: (report["age_days"], report["window"]["from"]))
    return {
        "schema_version": PLAN_FILL_CURVE_SCHEMA,
        "created_at": datetime.now(KST).isoformat(),
        "mode": mode,
        "observed_at": observed_at.isoformat(),
        "observed_at_source": observed_at_source,
        "endpoint_id": ENDPOINTS["order_plan"].endpoint_id,
        "rows": rows,
        "max_requests": max_requests,
        "window_count": len(window_reports),
        "request_count": sum(report["request_count"] for report in window_reports),
        "page_count": sum(report["page_count"] for report in window_reports),
        "curve_order": "age_days_ascending",
        "limitations": list(LIMITATIONS),
        "windows": window_reports,
    }


def _write_markdown_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise ExperimentError("artifact_exists", f"기존 리포트를 덮어쓸 수 없습니다: {path.name}") from exc
    except OSError as exc:
        raise ExperimentError("artifact_write_failed", f"리포트를 쓸 수 없습니다: {path.name}") from exc


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _rate_text(value: Any) -> str:
    return "unknown" if value is None else f"{value * 100:.1f}%"


def _number_text(value: Any) -> str:
    return "unknown" if value is None else str(value)


def render_markdown(document: dict[str, Any]) -> str:
    lines = [
        "# 발주계획 게시 후 경과일수 → 연결 채움률 횡단면 곡선",
        "",
        "이 결과는 서로 다른 과거 구간을 한 번씩 조회한 횡단면 측정이다. 같은 계획의 갱신을 추적한 종단 결론이 아니다.",
        "",
        f"조회 시각: `{document['observed_at']}` ({document['observed_at_source']})",
        f"모드: `{document['mode']}` · 구간 {document['window_count']}개 · page {document['page_count']}개 · 실제 요청 {document['request_count']}회",
        f"`numOfRows`: {_number_text(document['rows'])} · 호출 상한: {_number_text(document['max_requests'])}",
        "",
        "## 한계",
        "",
    ]
    lines.extend(f"- {limitation}" for limitation in document["limitations"])
    lines.extend(
        [
            "",
            "## 구간별 측정",
            "",
            "채움률은 `bidNtceNoList`가 문자열이고 `strip()` 후 비어 있지 않은 레코드의 비율이다. `null`, 빈 문자열, 공백만 있는 문자열은 미충족이다. 날짜 차이를 계산할 수 없는 레코드는 0일로 바꾸지 않고 unavailable로 남겼다.",
            "",
            "| 경과일 | 구간 | 총 건수 | 공고번호 채움 | 공고번호 총 개수 / 복수 건수 | ntceNticeYn=Y | chgDt 있음 | chgDt-nticeDt p50 / p90 / p95 / p99 / max (일) |",
            "|---:|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for report in document["windows"]:
        bid = report["bidNtceNoList"]
        notice = report["ntceNticeYn"]
        changed = report["chgDt"]
        delta = report["chgDt_minus_nticeDt"]
        interval = f"{report['window']['from']} ~ {report['window']['to_inclusive']}"
        delta_text = " / ".join(
            _number_text(delta[key])
            for key in ("p50_days", "p90_days", "p95_days", "p99_days", "max_days")
        )
        lines.append(
            f"| {report['age_days']} | {interval} | {report['total_count']} | {bid['filled_count']}/{report['total_count']} ({_rate_text(bid['fill_rate'])}) | {bid['notice_number_total']} / {bid['multi_notice_record_count']} | {notice['y_count']}/{report['total_count']} ({_rate_text(notice['y_rate'])}) | {changed['filled_count']}/{report['total_count']} ({_rate_text(changed['fill_rate'])}) | {delta_text} (가용 {delta['available_count']}, unavailable {delta['unavailable_count']}) |"
        )
    lines.extend(["", "## 채움률 곡선 (경과일수 오름차순)", "", "| 경과일수 | `bidNtceNoList` 채움률 | 총 건수 |", "|---:|---:|---:|"])
    for report in document["windows"]:
        lines.append(
            f"| {report['age_days']} | {_rate_text(report['bidNtceNoList']['fill_rate'])} | {report['total_count']} |"
        )
    lines.extend(
        [
            "",
            "페이지 요청 수는 구간별 `max(1, ceil(total_count / numOfRows))`이며, `request_count`에는 SurveyFetcher 재시도까지 포함한다.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_outputs(output_dir: Path, document: dict[str, Any]) -> None:
    output_dir = output_dir.resolve()
    write_json_new(output_dir / OUTPUT_JSON, document)
    _write_markdown_new(output_dir / OUTPUT_MARKDOWN, render_markdown(document))


def collect_curve(
    windows: Sequence[Window],
    output_dir: Path,
    *,
    rows: int = DEFAULT_ROWS,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    timeout: int = DEFAULT_TIMEOUT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    observed_at: datetime | None = None,
    fetcher: Any | None = None,
) -> dict[str, Any]:
    """Collect all windows and write the immutable raw pages plus reports."""

    _validate_windows(windows)
    if rows < 1 or rows > 999:
        raise ExperimentError("invalid_page_size", "rows는 1..999여야 합니다")
    if max_requests < 1:
        raise ExperimentError("invalid_request_limit", "max-requests는 1 이상이어야 합니다")
    if max_requests < len(windows):
        raise ExperimentError(
            "request_budget_too_small",
            f"구간 {len(windows)}개를 위한 최소 요청 상한은 {len(windows)}회입니다",
        )
    if timeout < 1 or max_attempts < 1 or max_attempts > 3:
        raise ExperimentError("invalid_http_config", "timeout 또는 max_attempts가 잘못됐습니다")
    observed_at = _require_aware(observed_at or datetime.now(KST))
    output_dir = output_dir.resolve()
    raw_root = output_dir / "raw"
    if raw_root.exists() and any(raw_root.iterdir()):
        raise ExperimentError("artifact_exists", "기존 plan-fill-curve raw를 덮어쓸 수 없습니다")

    if fetcher is None:
        fetcher = survey.SurveyFetcher(
            survey.get_service_key(),
            timeout=timeout,
            max_attempts=max_attempts,
            request_limit=max_requests,
        )
    raw_windows: list[tuple[Window, list[dict[str, Any]], list[dict[str, Any]], int]] = []
    endpoint = ENDPOINTS["order_plan"]
    for index, source_window in enumerate(windows, start=1):
        identifier = window_directory_name(index, source_window)
        window = Window(
            source_window.from_date,
            source_window.to_exclusive,
            identifier=identifier,
        )
        window_raw = raw_root / identifier
        survey.collect_pages(
            endpoint,
            window_raw,
            window.from_date,
            window.to_exclusive,
            rows,
            fetcher,
        )
        read_window, wrappers, items, request_count = _read_raw_window(window_raw)
        if (
            read_window.from_date != window.from_date
            or read_window.to_exclusive != window.to_exclusive
        ):
            raise ExperimentError("raw_window_mismatch", f"저장된 window 날짜가 다릅니다: {identifier}")
        raw_windows.append((window, wrappers, items, request_count))
        if sum(entry[3] for entry in raw_windows) > max_requests:
            raise ExperimentError("request_budget_exhausted", "plan-fill-curve 요청 상한을 초과했습니다")

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "observed_at": observed_at.isoformat(),
        "rows": rows,
        "max_requests": max_requests,
        "request_count": sum(entry[3] for entry in raw_windows),
        "windows": [
            {
                "id": window.identifier,
                "from": window.from_date.isoformat(),
                "to_exclusive": window.to_exclusive.isoformat(),
                "raw_directory": window.identifier,
            }
            for window, _wrappers, _items, _requests in raw_windows
        ],
    }
    write_json_new(raw_root / MANIFEST_NAME, manifest)
    document = _build_document(
        raw_windows,
        observed_at,
        "collect",
        rows,
        max_requests,
        "collection_start",
    )
    _write_outputs(output_dir, document)
    return document


def recompute_from_raw(raw_path: Path, output_dir: Path) -> dict[str, Any]:
    """Recalculate reports from stored pages without constructing a fetcher."""

    raw_path = raw_path.resolve()
    if (raw_path / "raw").is_dir() and not any(
        child.is_dir() and WINDOW_DIR_RE.fullmatch(child.name) for child in raw_path.iterdir()
    ):
        raw_root = raw_path / "raw"
    else:
        raw_root = raw_path
    raw_windows = _discover_raw_windows(raw_root)
    observed_at, rows, max_requests = _manifest_observed_at(raw_root)
    if observed_at is None:
        observed_at = _fallback_observed_at(raw_windows)
        observed_source = "raw.collected_at_minimum"
    else:
        observed_source = "collection_manifest"
    if rows is None:
        query = raw_windows[0][1][0].get("query")
        rows_value = query.get("numOfRows") if isinstance(query, dict) else None
        try:
            rows = int(rows_value)
        except (TypeError, ValueError) as exc:
            raise ExperimentError("invalid_raw", "raw에서 numOfRows를 복원할 수 없습니다") from exc
    document = _build_document(
        raw_windows,
        observed_at,
        "from_raw",
        rows,
        max_requests,
        observed_source,
    )
    _write_outputs(output_dir, document)
    return document


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--window",
        dest="window_specs",
        action="append",
        help="측정 구간 FROM:TO (두 날짜 모두 포함); 여러 번 지정할 수 있습니다",
    )
    parser.add_argument("--from-raw", type=Path, help="저장된 plan-fill-curve raw에서 재계산합니다")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument(
        "--observed-at",
        type=parse_observed_at,
        help="조회 시각 ISO timestamp (예: 2026-08-29T12:00:00+09:00)",
    )
    parser.add_argument("--execute", action="store_true", help="외부 G2B 호출을 명시적으로 허용합니다")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.from_raw is not None:
            if args.window_specs:
                raise ExperimentError("invalid_options", "--from-raw와 --window은 함께 쓸 수 없습니다")
            document = recompute_from_raw(args.from_raw, args.output_dir)
        else:
            if not args.execute:
                print(
                    "외부 호출이 승인되지 않았습니다. 수집에는 --execute를 명시하고, 저장 raw 재계산에는 --from-raw를 사용하세요.",
                    file=sys.stderr,
                )
                return 2
            windows = (
                tuple(parse_window_spec(spec) for spec in args.window_specs)
                if args.window_specs
                else DEFAULT_WINDOWS
            )
            document = collect_curve(
                windows,
                args.output_dir,
                rows=args.rows,
                max_requests=args.max_requests,
                timeout=args.timeout,
                max_attempts=args.max_attempts,
                observed_at=args.observed_at,
            )
        print(
            f"plan-fill-curve 완료 · 구간 {document['window_count']}개 · "
            f"실제 요청 {document['request_count']}회"
        )
        return 0
    except ExperimentError as exc:
        print(f"error[{exc.code}]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
