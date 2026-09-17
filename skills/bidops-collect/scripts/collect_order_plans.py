#!/usr/bin/env python3
"""Collect the independent G2B order-plan artifact.

The order-plan endpoint has a different re-query window from bid notices, so
this producer deliberately remains a sibling of ``collect_notices.py``.  API
pages are stored before normalization and can be replayed with
``--from-raw`` without another network call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import urllib.error
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


# The sibling collector owns the dotenv lookup, G2B request helper, response
# body/item extraction, text conversion, and date normalization conventions.
# Add the script directory for direct execution as well as importlib-based
# tests, where Python does not automatically add the sibling directory.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from collect_notices import (  # noqa: E402
    get_body,
    get_items,
    get_service_key,
    normalize_datetime,
    request_json,
    text_value,
)


KST = timezone(timedelta(hours=9))
ENDPOINT_ID = "g2b_order_plan_service_pps_search_v1"
ENDPOINT = (
    "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/"
    "getOrderPlanSttusListServcPPSSrch"
)
ARTIFACT_SCHEMA = "bidops.collected-order-plans.v1"
RAW_PAGE_SCHEMA = "bidops.collected-order-plans-raw-page.v1"
OUTPUT_FILE = "collected-order-plans.json"
ALLOWED_BUSINESS_DIVISIONS = {"일반용역", "기술용역"}
ORDER_SCOPE_FROM_MONTH = "200412"
ORDER_SCOPE_TO_MONTH = "999912"
WARNING_REQUESTS = 700
STOP_REQUESTS = 900
MAX_PAGES = 100
DEFAULT_RECENT_DAYS = 21


class CollectionError(RuntimeError):
    """A safe, stable collection failure that never carries the API key."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class NormalizationStats:
    def __init__(
        self,
        records: list[dict[str, Any]],
        source_records: int,
        excluded_out_of_scope: int,
    ) -> None:
        self.records = records
        self.source_records = source_records
        self.excluded_out_of_scope = excluded_out_of_scope


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="최근 발주계획을 수집해 collected-order-plans.json을 생성합니다."
    )
    parser.add_argument("--from-date", type=date.fromisoformat)
    parser.add_argument(
        "--to-date",
        type=date.fromisoformat,
        help="반개구간의 끝(제외). --from-date와 함께 사용합니다.",
    )
    parser.add_argument(
        "--days",
        "--recent-days",
        dest="days",
        type=int,
        help=(
            f"오늘을 포함해 조회할 최근 일수 (기본 {DEFAULT_RECENT_DAYS}). "
            "명시 날짜 모드와 함께 사용할 수 없습니다."
        ),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument(
        "--from-raw",
        type=Path,
        help="API를 호출하지 않고 이 raw 디렉터리의 보존 page JSON을 재정규화합니다.",
    )
    return parser.parse_args(argv)


def resolve_window(
    from_date: date | None,
    to_date: date | None,
    days: int | None = None,
    *,
    today: date | None = None,
) -> tuple[date, date]:
    """Resolve explicit half-open dates or an inclusive-today recent window."""

    if (from_date is None) != (to_date is None):
        raise CollectionError(
            "invalid_window",
            "--from-date와 --to-date는 함께 지정해야 합니다.",
        )
    if from_date is not None and to_date is not None:
        if days is not None:
            raise CollectionError(
                "invalid_window",
                "명시 날짜 모드와 --days는 함께 사용할 수 없습니다.",
            )
        if to_date <= from_date:
            raise CollectionError(
                "invalid_window",
                "--to-date는 --from-date보다 뒤여야 합니다.",
            )
        return from_date, to_date

    recent_days = DEFAULT_RECENT_DAYS if days is None else days
    if recent_days < 1:
        raise CollectionError("invalid_window", "최근 일수는 1 이상이어야 합니다.")
    # ``to_date`` is exclusive throughout the pipeline.  Adding one day makes
    # the default window contain today as well as the preceding N-1 dates.
    end = (today or datetime.now(KST).date()) + timedelta(days=1)
    return end - timedelta(days=recent_days), end


def query_for_window(
    from_date: date, to_date: date, page: int, rows: int
) -> dict[str, str]:
    """Build the measured PPSSrch query without its secret serviceKey."""

    if to_date <= from_date:
        raise CollectionError("invalid_window", "to-date는 from-date보다 뒤여야 합니다.")
    if page < 1:
        raise CollectionError("invalid_page", "page는 1 이상이어야 합니다.")
    if rows < 1 or rows > 999:
        raise CollectionError("invalid_page_size", "rows는 1..999여야 합니다.")
    inclusive_end = datetime.combine(to_date, datetime_time.min) - timedelta(minutes=1)
    # PPSSrch requires an order-month range even when publication time is the
    # population boundary.  Omitting either value silently narrows the second
    # dimension of the result set.
    return {
        "pageNo": str(page),
        "numOfRows": str(rows),
        "type": "json",
        "orderBgnYm": ORDER_SCOPE_FROM_MONTH,
        "orderEndYm": ORDER_SCOPE_TO_MONTH,
        "inqryBgnDt": from_date.strftime("%Y%m%d0000"),
        "inqryEndDt": inclusive_end.strftime("%Y%m%d%H%M"),
    }


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CollectionError("invalid_json", "JSON을 canonical 형식으로 만들 수 없습니다.") from exc


def digest_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _safe_aware_timestamp(value: Any, field: str) -> str:
    """Validate a raw page timestamp while preserving its serialized value."""

    text = text_value(value)
    if not text:
        raise CollectionError("invalid_timestamp", f"{field} 값이 없습니다.")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise CollectionError("invalid_timestamp", f"{field} 형식이 잘못됐습니다.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CollectionError("invalid_timestamp", f"{field}에 timezone 정보가 없습니다.")
    return parsed.isoformat()


def _published_datetime(value: Any) -> tuple[str, datetime]:
    normalized = normalize_datetime(value)
    if normalized is None:
        raise CollectionError("missing_source_timestamp", "nticeDt 값이 없습니다.")
    try:
        parsed = datetime.fromisoformat(
            normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
        )
    except ValueError as exc:
        raise CollectionError("invalid_source_timestamp", "nticeDt 형식이 잘못됐습니다.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        # normalize_datetime preserves unknown formats.  Do not guess a
        # timezone for a value that was not recognized deterministically.
        raise CollectionError("invalid_source_timestamp", "nticeDt에 timezone을 확인할 수 없습니다.")
    return normalized, parsed


def nullable_amount(
    value: Any, unknown_fields: list[str], field: str
) -> int | None:
    """Normalize measured G2B amount strings without turning unknown into 0."""

    if value is None or value == "":
        unknown_fields.append(field)
        return None
    try:
        parsed = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        unknown_fields.append(field)
        return None
    if parsed < 0:
        unknown_fields.append(field)
        return None
    return parsed


def _planned_order_month(
    year_value: Any, month_value: Any, unknown_fields: list[str]
) -> tuple[str | None, str | None]:
    year = text_value(year_value)
    month = text_value(month_value)
    if year is None:
        unknown_fields.append("planned_order_year")
    elif len(year) != 4 or not year.isdigit():
        unknown_fields.append("planned_order_year")

    if year is not None and month is not None:
        candidate = f"{year}-{month.zfill(2)}"
        if re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", candidate):
            return year, candidate
    unknown_fields.append("planned_order_month")
    return year, None


def normalize_order_plan(
    record: dict[str, Any],
    raw_source: str,
    discovered_at: str,
    *,
    from_date: date,
    to_date: date,
) -> dict[str, Any]:
    """Map one measured G2B row to the canonical snake_case contract."""

    plan_no = text_value(record.get("orderPlanUntyNo"))
    if plan_no is None:
        raise CollectionError("missing_plan_id", "공식 발주계획통합번호가 없습니다.")

    published_at, published_datetime = _published_datetime(record.get("nticeDt"))
    window_start = datetime.combine(from_date, datetime_time.min, KST)
    window_end = datetime.combine(to_date, datetime_time.min, KST)
    if not window_start <= published_datetime.astimezone(KST) < window_end:
        raise CollectionError(
            "window_boundary_mismatch",
            f"조회 반개구간 밖 레코드입니다: {plan_no}",
        )

    unknown_fields: list[str] = ["sw_business_status"]
    planned_year, planned_month = _planned_order_month(
        record.get("orderYear"), record.get("orderMnth"), unknown_fields
    )
    changed_at = normalize_datetime(record.get("chgDt"))

    return {
        "order_plan_unty_no": plan_no,
        "title": text_value(record.get("bizNm")),
        "agency_code": text_value(record.get("orderInsttCd")),
        "agency_name": text_value(record.get("orderInsttNm")),
        "supervising_agency_name": text_value(record.get("totlmngInsttNm")),
        "business_division": text_value(record.get("bsnsDivNm")),
        "business_division_code": text_value(record.get("bsnsDivCd")),
        "service_type": text_value(record.get("bsnsTyNm")),
        "service_type_code": text_value(record.get("bsnsTyCd")),
        "budget_amount": nullable_amount(
            record.get("sumOrderAmt"), unknown_fields, "budget_amount"
        ),
        "contract_amount": nullable_amount(
            record.get("orderContrctAmt"), unknown_fields, "contract_amount"
        ),
        "planned_order_year": planned_year,
        "planned_order_month": planned_month,
        "procurement_method": text_value(record.get("prcrmntMethd")),
        "contract_method": text_value(record.get("cntrctMthdNm")),
        # The endpoint does not expose a measured SW-business status.  Keep
        # this explicit null; never derive it from the business division.
        "sw_business_status": None,
        "published_at": published_at,
        "changed_at": changed_at,
        "bid_ntice_no_list": text_value(record.get("bidNtceNoList")),
        "notice_posted": text_value(record.get("ntceNticeYn")),
        # An empty rcritRgstNo is a known, nullable contract field.  It is not
        # removed and is not converted into a fabricated identifier.
        "rcrit_rgst_no": text_value(record.get("rcritRgstNo")),
        "source_url": text_value(record.get("orderPlanDtlUrl")),
        "first_discovered_at": discovered_at,
        "last_discovered_at": discovered_at,
        "source_sha256": digest_json(record),
        "unknown_fields": sorted(set(unknown_fields)),
        "raw_source": raw_source,
    }


def _extract_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int, int]:
    try:
        body = get_body(payload)
    except RuntimeError as exc:
        # Do not propagate a provider's raw message through the CLI.  In
        # particular, an upstream error must not become a place where query
        # parameters or credentials are logged.
        raise CollectionError(
            "g2b_result_error", "G2B 응답 resultCode가 정상이 아닙니다."
        ) from exc
    try:
        total = int(body["totalCount"])
        page_no = int(body["pageNo"])
        rows = int(body["numOfRows"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CollectionError(
            "invalid_api_response", "G2B pagination metadata가 잘못됐습니다."
        ) from exc
    if total < 0 or page_no < 1 or rows < 1 or rows > 999:
        raise CollectionError("invalid_api_response", "G2B pagination 값이 잘못됐습니다.")
    items = get_items(body)
    return items, total, page_no, rows


def _fetch_result(
    fetcher: Any,
    query: dict[str, str],
) -> tuple[dict[str, Any], int]:
    try:
        result = fetcher.fetch(query) if hasattr(fetcher, "fetch") else fetcher(query)
    except CollectionError:
        raise
    except Exception as exc:  # pragma: no cover - defensive boundary for injected fetchers
        raise CollectionError("g2b_request_failed", "G2B API 요청이 실패했습니다.") from exc
    if isinstance(result, tuple) and len(result) == 2:
        payload, attempts = result
    else:
        payload, attempts = result, 1
    if not isinstance(payload, dict) or type(attempts) is not int or attempts < 1:
        raise CollectionError("invalid_api_response", "G2B 응답 또는 요청 시도 횟수가 잘못됐습니다.")
    return payload, attempts


class G2BFetcher:
    """Real API fetcher with the shared 700/900 request guardrails."""

    def __init__(
        self,
        service_key: str,
        timeout: int = 30,
        max_attempts: int = 2,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if timeout < 1 or max_attempts < 1 or max_attempts > 3:
            raise CollectionError(
                "invalid_http_config", "timeout 또는 max_attempts가 잘못됐습니다."
            )
        self.service_key = service_key
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.sleeper = sleeper
        self.request_count = 0
        self.warning_emitted = False

    @staticmethod
    def _retryable(error: RuntimeError) -> bool:
        message = str(error)
        match = re.search(r"HTTP 오류:\s*(\d+)", message)
        if match:
            status = int(match.group(1))
            return status >= 500 or status == 429
        return "연결 오류" in message

    def fetch(self, public_query: dict[str, str]) -> tuple[dict[str, Any], int]:
        last_error = "g2b_request_failed"
        for attempt in range(1, self.max_attempts + 1):
            if self.request_count >= STOP_REQUESTS:
                raise CollectionError(
                    "request_budget_exhausted",
                    "900회 방어선에서 신규 API 호출을 중지했습니다.",
                )
            self.request_count += 1
            if self.request_count >= WARNING_REQUESTS and not self.warning_emitted:
                print(
                    "warning: G2B 요청 수가 700회 방어선에 도달했습니다",
                    file=sys.stderr,
                )
                self.warning_emitted = True
            params = dict(public_query)
            params["serviceKey"] = self.service_key
            try:
                payload = request_json(ENDPOINT, params, self.timeout)
                # The response is kept verbatim in the raw page.  Refuse to
                # persist it if an upstream error reflects the credential.
                if self.service_key and self.service_key in _canonical_json_bytes(payload).decode("utf-8"):
                    raise CollectionError(
                        "secret_reflected",
                        "G2B 응답이 인증정보를 반사해 저장을 중지했습니다.",
                    )
                return payload, attempt
            except CollectionError:
                raise
            except RuntimeError as exc:
                last_error = "g2b_request_failed"
                if not self._retryable(exc) or attempt == self.max_attempts:
                    raise CollectionError(
                        last_error,
                        "G2B API 요청이 안전한 실패로 종료됐습니다.",
                    ) from exc
                self.sleeper(min(2 ** (attempt - 1), 2))
            except (urllib.error.URLError, TimeoutError):
                last_error = "g2b_connection_failed"
                if attempt == self.max_attempts:
                    raise CollectionError(
                        last_error,
                        "G2B API 연결이 안전한 실패로 종료됐습니다.",
                    )
                self.sleeper(min(2 ** (attempt - 1), 2))
        raise CollectionError(last_error, "G2B API 요청이 실패했습니다.")


def _raw_wrapper(
    payload: dict[str, Any],
    query: dict[str, str],
    page: int,
    attempts: int,
    collected_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": RAW_PAGE_SCHEMA,
        "endpoint_id": ENDPOINT_ID,
        "query": dict(query),
        "page_no": page,
        "request_attempts": attempts,
        "collected_at": collected_at,
        "payload_sha256": digest_json(payload),
        "payload": payload,
    }


def _write_json_new(path: Path, value: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except FileExistsError as exc:
        raise CollectionError("artifact_exists", f"기존 산출물을 덮어쓸 수 없습니다: {path.name}") from exc
    except (OSError, TypeError, ValueError, UnicodeError) as exc:
        raise CollectionError("artifact_write_failed", f"산출물을 쓸 수 없습니다: {path.name}") from exc


def collect_pages(
    raw_dir: Path,
    from_date: date,
    to_date: date,
    rows: int,
    fetcher: Any,
    warnings: list[str] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Fetch pages into an immutable raw directory until totalCount is met."""

    warnings = warnings if warnings is not None else []
    if raw_dir.exists() and any(raw_dir.iterdir()):
        raise CollectionError("artifact_exists", "기존 raw 디렉터리를 덮어쓸 수 없습니다.")
    raw_dir.mkdir(parents=True, exist_ok=True)

    page = 1
    expected_total: int | None = None
    received = 0
    expected_rows: int | None = None
    while True:
        if page > MAX_PAGES:
            warnings.append(
                f"order_plan: 안전 상한 {MAX_PAGES}페이지에서 중단했습니다."
            )
            break
        query = query_for_window(from_date, to_date, page, rows)
        payload, attempts = _fetch_result(fetcher, query)
        items, total, response_page, response_rows = _extract_page(payload)
        if response_page != page or response_rows != rows:
            raise CollectionError(
                "pagination_mismatch", "G2B 응답 pagination이 요청과 다릅니다."
            )
        if expected_total is None:
            expected_total = total
            expected_rows = response_rows
        elif total != expected_total:
            raise CollectionError("pagination_changed", "수집 중 totalCount가 바뀌었습니다.")
        if expected_rows != response_rows:
            raise CollectionError("pagination_changed", "페이지 사이 numOfRows가 바뀌었습니다.")
        collected_at = datetime.now(KST).isoformat()
        _write_json_new(
            raw_dir / f"page-{page:05d}.json",
            _raw_wrapper(payload, query, page, attempts, collected_at),
        )
        received += len(items)
        if received > total:
            raise CollectionError("pagination_overflow", "수집 건수가 totalCount를 초과했습니다.")
        if received >= total:
            break
        if not items:
            raise CollectionError(
                "pagination_incomplete",
                "마지막 이전에 빈 G2B page를 받았습니다.",
            )
        page += 1

    pages = read_raw_pages(raw_dir, require_complete=False)
    validate_raw_queries(pages, from_date, to_date)
    return pages


def read_raw_pages(
    raw_dir: Path,
    *,
    require_complete: bool = False,
) -> list[tuple[str, dict[str, Any]]]:
    """Read and validate preserved pages without making a network request."""

    if raw_dir.is_symlink() or not raw_dir.is_dir():
        raise CollectionError("raw_path_rejected", "raw 디렉터리는 일반 디렉터리여야 합니다.")
    paths = sorted(raw_dir.glob("page-*.json"))
    if not paths:
        raise CollectionError("raw_pages_missing", "재정규화할 raw page가 없습니다.")

    pages: list[tuple[str, dict[str, Any]]] = []
    expected_page = 1
    expected_total: int | None = None
    expected_rows: int | None = None
    item_count = 0
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise CollectionError(
                "raw_path_rejected", f"raw page는 일반 파일이어야 합니다: {path.name}"
            )
        if path.name != f"page-{expected_page:05d}.json":
            raise CollectionError("pagination_incomplete", "raw page 파일명이 연속적이지 않습니다.")
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CollectionError("invalid_json", f"raw page를 읽을 수 없습니다: {path.name}") from exc
        if not isinstance(wrapper, dict) or wrapper.get("schema_version") != RAW_PAGE_SCHEMA:
            raise CollectionError("schema_mismatch", f"raw page schema가 다릅니다: {path.name}")
        if wrapper.get("endpoint_id") != ENDPOINT_ID:
            raise CollectionError("raw_query_mismatch", f"raw endpoint가 다릅니다: {path.name}")
        attempts = wrapper.get("request_attempts")
        if type(attempts) is not int or not 1 <= attempts <= 3:
            raise CollectionError("invalid_contract", f"raw request_attempts가 잘못됐습니다: {path.name}")
        _safe_aware_timestamp(wrapper.get("collected_at"), f"{path.name}.collected_at")
        payload = wrapper.get("payload")
        if not isinstance(payload, dict) or wrapper.get("payload_sha256") != digest_json(payload):
            raise CollectionError("hash_mismatch", f"raw payload hash가 다릅니다: {path.name}")
        query = wrapper.get("query")
        if isinstance(query, dict) and "serviceKey" in query:
            raise CollectionError(
                "secret_in_artifact", "raw query에 serviceKey가 있어 저장을 중지했습니다."
            )
        items, total, page_no, response_rows = _extract_page(payload)
        if page_no != expected_page or wrapper.get("page_no") != page_no:
            raise CollectionError("pagination_incomplete", "raw page 번호가 연속적이지 않습니다.")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise CollectionError("pagination_changed", "raw page 사이 totalCount가 바뀌었습니다.")
        if expected_rows is None:
            expected_rows = response_rows
        elif response_rows != expected_rows:
            raise CollectionError("pagination_changed", "raw page 사이 numOfRows가 바뀌었습니다.")
        item_count += len(items)
        if item_count > total:
            raise CollectionError("pagination_overflow", "raw page 건수가 totalCount를 초과했습니다.")
        pages.append((path.name, wrapper))
        expected_page += 1

    assert expected_total is not None
    if require_complete and item_count != expected_total:
        raise CollectionError("pagination_incomplete", "raw 모집단 건수와 totalCount가 다릅니다.")
    return pages


def validate_raw_queries(
    pages: Iterable[tuple[str, dict[str, Any]]],
    from_date: date,
    to_date: date,
) -> None:
    for name, wrapper in pages:
        query = wrapper.get("query")
        if not isinstance(query, dict):
            raise CollectionError("raw_query_mismatch", f"raw query가 object가 아닙니다: {name}")
        page = query.get("pageNo")
        raw_rows = query.get("numOfRows")
        if not isinstance(page, str) or not isinstance(raw_rows, str):
            raise CollectionError("raw_query_mismatch", f"raw pagination query가 잘못됐습니다: {name}")
        try:
            page_number = int(page)
            row_count = int(raw_rows)
        except ValueError as exc:
            raise CollectionError(
                "raw_query_mismatch", f"raw pagination query가 잘못됐습니다: {name}"
            ) from exc
        expected = query_for_window(from_date, to_date, page_number, row_count)
        if query != expected or page_number != wrapper.get("page_no"):
            raise CollectionError("raw_query_mismatch", f"raw query가 수집 범위와 다릅니다: {name}")
        if "serviceKey" in query:
            raise CollectionError("secret_in_artifact", "raw query에 serviceKey가 있어 저장을 중지했습니다.")


def _normalization_stats(
    pages: Iterable[tuple[str, dict[str, Any]]],
    from_date: date,
    to_date: date,
) -> NormalizationStats:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_records = 0
    excluded = 0
    for raw_name, wrapper in pages:
        payload = wrapper.get("payload")
        if not isinstance(payload, dict):
            raise CollectionError("invalid_contract", f"raw payload가 object가 아닙니다: {raw_name}")
        items, _total, _page, _rows = _extract_page(payload)
        discovered_at = _safe_aware_timestamp(
            wrapper.get("collected_at"), f"{raw_name}.collected_at"
        )
        raw_source = f"raw/{raw_name}"
        for item in items:
            source_records += 1
            business_division = text_value(item.get("bsnsDivNm"))
            if business_division not in ALLOWED_BUSINESS_DIVISIONS:
                excluded += 1
                continue
            normalized = normalize_order_plan(
                item,
                raw_source,
                discovered_at,
                from_date=from_date,
                to_date=to_date,
            )
            plan_no = normalized["order_plan_unty_no"]
            if plan_no in seen:
                raise CollectionError("duplicate_plan_id", f"중복 발주계획번호가 있습니다: {plan_no}")
            seen.add(plan_no)
            records.append(normalized)
    records.sort(key=lambda item: (item.get("published_at") or "", item["order_plan_unty_no"]))
    return NormalizationStats(records, source_records, excluded)


def normalize_items(
    page_documents: Iterable[tuple[str, dict[str, Any]]],
    from_date: date,
    to_date: date,
) -> list[dict[str, Any]]:
    """Public deterministic normalizer used by unit tests and replay."""

    return _normalization_stats(page_documents, from_date, to_date).records


def reclassify_source(
    *,
    raw_dir: Path,
    from_date: date,
    to_date: date,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Re-normalize preserved raw pages without invoking the G2B API."""

    if raw_dir.is_symlink():
        raise CollectionError("raw_path_rejected", "raw 디렉터리 symlink는 허용하지 않습니다.")
    if not raw_dir.is_dir() or not any(raw_dir.glob("page-*.json")):
        return [], [f"order_plan: 재분류할 원문 페이지가 {raw_dir}에 없습니다."]
    pages = read_raw_pages(raw_dir, require_complete=False)
    validate_raw_queries(pages, from_date, to_date)
    return normalize_items(pages, from_date, to_date), []


def collect_source(
    *,
    from_date: date,
    to_date: date,
    rows: int = 500,
    timeout: int = 30,
    max_attempts: int = 2,
    raw_dir: Path,
    fetcher: Any | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect and normalize one source, following ``collect_notices``' API."""

    warnings: list[str] = []
    active_fetcher = fetcher if fetcher is not None else G2BFetcher(
        get_service_key(), timeout=timeout, max_attempts=max_attempts
    )
    pages = collect_pages(
        raw_dir,
        from_date,
        to_date,
        rows,
        active_fetcher,
        warnings,
    )
    return normalize_items(pages, from_date, to_date), warnings


def copy_raw_pages(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise CollectionError("raw_path_rejected", "원본 raw는 일반 디렉터리여야 합니다.")
    if destination.exists() and any(destination.iterdir()):
        raise CollectionError("artifact_exists", "기존 raw 디렉터리를 덮어쓸 수 없습니다.")
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob("page-*.json")):
        if path.is_symlink() or not path.is_file():
            raise CollectionError("raw_path_rejected", f"raw page를 복사할 수 없습니다: {path.name}")
        target = destination / path.name
        try:
            with path.open("rb") as source_handle, target.open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
        except FileExistsError as exc:
            raise CollectionError("artifact_exists", f"raw page를 덮어쓸 수 없습니다: {path.name}") from exc
        except OSError as exc:
            raise CollectionError("raw_copy_failed", f"raw page 복사에 실패했습니다: {path.name}") from exc


def _source_total(pages: list[tuple[str, dict[str, Any]]]) -> int:
    if not pages:
        return 0
    payload = pages[0][1].get("payload")
    if not isinstance(payload, dict):
        raise CollectionError("invalid_contract", "raw payload가 object가 아닙니다.")
    _items, total, _page, _rows = _extract_page(payload)
    return total


def build_artifact(
    pages: list[tuple[str, dict[str, Any]]],
    from_date: date,
    to_date: date,
    warnings: list[str] | None = None,
    *,
    request_count: int | None = None,
) -> dict[str, Any]:
    """Build the canonical artifact from already-preserved raw pages."""

    if not pages:
        raise CollectionError("raw_pages_missing", "발주계획 raw page가 없습니다.")
    stats = _normalization_stats(pages, from_date, to_date)
    source_total = _source_total(pages)
    if request_count is None:
        request_count = sum(int(wrapper["request_attempts"]) for _name, wrapper in pages)
    artifact_warnings = list(warnings or [])
    complete = stats.source_records >= source_total
    if not complete and not any("안전 상한" in warning for warning in artifact_warnings):
        artifact_warnings.append("발주계획 raw page가 totalCount 전에 끝나 부분 산출물입니다.")
    collected_at = min(
        _safe_aware_timestamp(wrapper.get("collected_at"), f"{name}.collected_at")
        for name, wrapper in pages
    )
    divisions = sorted(ALLOWED_BUSINESS_DIVISIONS)
    return {
        "schema_version": ARTIFACT_SCHEMA,
        "generated_at": collected_at,
        "source_window": {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "timezone": "Asia/Seoul",
        },
        "metadata": {
            "endpoint_id": ENDPOINT_ID,
            "endpoint": ENDPOINT,
            "scope": "bsnsDivNm allowlist; SW사업대상 여부로 선필터하지 않음",
            "business_division_field": "bsnsDivNm",
            "business_divisions": divisions,
            "order_month_scope": {
                "from": ORDER_SCOPE_FROM_MONTH,
                "to": ORDER_SCOPE_TO_MONTH,
            },
            "collection": {
                "page_count": len(pages),
                "request_count": request_count,
                "complete": complete,
            },
        },
        "counts": {
            "total": len(stats.records),
            "order_plans": len(stats.records),
            "in_scope": len(stats.records),
            "source_total": source_total,
            "source_records": stats.source_records,
            "excluded_out_of_scope": stats.excluded_out_of_scope,
            "excluded_business_divisions": stats.excluded_out_of_scope,
            "page_count": len(pages),
            "request_count": request_count,
        },
        "warnings": artifact_warnings,
        "order_plans": stats.records,
    }


def _request_count(pages: list[tuple[str, dict[str, Any]]]) -> int:
    return sum(int(wrapper.get("request_attempts", 0)) for _name, wrapper in pages)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        from_date, to_date = resolve_window(
            args.from_date,
            args.to_date,
            args.days,
        )
        if args.rows < 1 or args.rows > 999:
            raise CollectionError("invalid_page_size", "rows는 1..999여야 합니다.")
        output_dir = args.output_dir.resolve()
        if output_dir.exists():
            raise CollectionError("artifact_exists", "기존 회차 디렉터리를 덮어쓸 수 없습니다.")
        output_dir.mkdir(parents=True, exist_ok=False)
        raw_dir = output_dir / "raw"
        warnings: list[str] = []

        if args.from_raw is not None:
            copy_raw_pages(args.from_raw, raw_dir)
            pages = read_raw_pages(raw_dir, require_complete=False)
            validate_raw_queries(pages, from_date, to_date)
        else:
            fetcher = G2BFetcher(
                get_service_key(),
                timeout=args.timeout,
                max_attempts=args.max_attempts,
            )
            pages = collect_pages(
                raw_dir,
                from_date,
                to_date,
                args.rows,
                fetcher,
                warnings,
            )

        artifact = build_artifact(
            pages,
            from_date,
            to_date,
            warnings,
            request_count=_request_count(pages),
        )
        output_path = output_dir / OUTPUT_FILE
        _write_json_new(output_path, artifact)
        print(
            json.dumps(
                {
                    "output": str(output_path),
                    "total": artifact["counts"]["total"],
                    "excluded_out_of_scope": artifact["counts"]["excluded_out_of_scope"],
                    "page_count": artifact["counts"]["page_count"],
                    "request_count": artifact["counts"]["request_count"],
                    "complete": artifact["metadata"]["collection"]["complete"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except CollectionError as exc:
        print(
            json.dumps(
                {"status": "failed", "error_code": exc.code}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
