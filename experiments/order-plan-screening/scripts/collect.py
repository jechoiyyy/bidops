#!/usr/bin/env python3
"""Collect and freeze the fixed three-day G2B service order-plan population."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from common import (
    RAW_PAGE_SCHEMA,
    RUN_SCHEMA,
    POPULATION_SCHEMA,
    ExperimentError,
    capabilities_projection,
    digest_json,
    external_preview,
    load_json,
    load_methods_config,
    parse_timezone_timestamp,
    sha256_file,
    validate_external_approval,
    validate_population,
    write_json_new,
)


KST = timezone(timedelta(hours=9))
EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
ENDPOINT_ID = "g2b_order_plan_service_pps_search_v1"
ENDPOINT = (
    "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/"
    "getOrderPlanSttusListServcPPSSrch"
)
ALLOWED_BUSINESS_DIVISIONS = {"일반용역", "기술용역"}
ORDER_SCOPE_FROM_MONTH = "200412"
ORDER_SCOPE_TO_MONTH = "999912"
WARNING_REQUESTS = 700
STOP_REQUESTS = 900


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--from-date", type=date.fromisoformat, default=date(2026, 8, 24))
    parser.add_argument("--to-date", type=date.fromisoformat, default=date(2026, 8, 27))
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument(
        "--from-raw",
        type=Path,
        help="네트워크 호출 없이 이 raw 디렉터리의 불변 page JSON을 새 run으로 정규화합니다.",
    )
    parser.add_argument(
        "--company-capabilities",
        type=Path,
        default=EXPERIMENT_ROOT / "config/company-capabilities.json",
    )
    parser.add_argument(
        "--methods-config",
        type=Path,
        default=EXPERIMENT_ROOT / "config/methods.json",
    )
    parser.add_argument(
        "--external-approval",
        type=Path,
        help="동일 raw를 새 run으로 확정할 때 Luna preview와 일치하는 불변 승인 JSON입니다.",
    )
    return parser.parse_args()


def get_service_key() -> str:
    key = os.environ.get("BIDOPS_G2B_API_KEY", "").strip()
    if not key:
        raise ExperimentError("service_key_missing", "BIDOPS_G2B_API_KEY가 필요합니다")
    return urllib.parse.unquote(key)


def query_for_window(from_date: date, to_date: date, page: int, rows: int) -> dict[str, str]:
    if to_date <= from_date:
        raise ExperimentError("invalid_window", "to-date는 from-date보다 뒤여야 합니다")
    if rows < 1 or rows > 999:
        raise ExperimentError("invalid_page_size", "rows는 1..999여야 합니다")
    inclusive_end = datetime.combine(to_date, datetime_time.min) - timedelta(minutes=1)
    return {
        "pageNo": str(page),
        "numOfRows": str(rows),
        "type": "json",
        # PPSSrch requires an order-month range even when publication time is
        # the experiment boundary. Use the service's documented first month
        # through the maximum YYYYMM sentinel so this second dimension cannot
        # silently narrow the three-day publication population.
        "orderBgnYm": ORDER_SCOPE_FROM_MONTH,
        "orderEndYm": ORDER_SCOPE_TO_MONTH,
        "inqryBgnDt": from_date.strftime("%Y%m%d0000"),
        "inqryEndDt": inclusive_end.strftime("%Y%m%d%H%M"),
    }


class G2BFetcher:
    def __init__(
        self,
        service_key: str,
        timeout: int,
        max_attempts: int,
        opener: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if timeout < 1 or max_attempts < 1 or max_attempts > 3:
            raise ExperimentError("invalid_http_config", "timeout 또는 max_attempts가 잘못됐습니다")
        self.service_key = service_key
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )
        self.sleeper = sleeper
        self.request_count = 0
        self.warning_emitted = False

    def fetch(self, public_query: dict[str, str]) -> tuple[dict[str, Any], int]:
        last_code = "g2b_request_failed"
        for attempt in range(1, self.max_attempts + 1):
            if self.request_count >= STOP_REQUESTS:
                raise ExperimentError("request_budget_exhausted", "900회 방어선에서 신규 API 호출을 중지했습니다")
            self.request_count += 1
            if self.request_count >= WARNING_REQUESTS and not self.warning_emitted:
                print("warning: G2B 요청 수가 700회 방어선에 도달했습니다", file=sys.stderr)
                self.warning_emitted = True
            params = dict(public_query)
            params["serviceKey"] = self.service_key
            url = ENDPOINT + "?" + urllib.parse.urlencode(params)
            request = urllib.request.Request(url, headers={"Accept": "application/json"})
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    payload = response.read().decode("utf-8", errors="strict")
                document = json.loads(payload)
                if not isinstance(document, dict):
                    raise ExperimentError("invalid_api_response", "G2B 응답 최상위가 object가 아닙니다")
                if self.service_key and self.service_key in payload:
                    raise ExperimentError("secret_reflected", "G2B 응답이 인증정보를 반사해 저장을 중지했습니다")
                return document, attempt
            except ExperimentError:
                raise
            except urllib.error.HTTPError as exc:
                last_code = f"g2b_http_{exc.code}"
                retryable = exc.code >= 500 or exc.code == 429
            except (urllib.error.URLError, TimeoutError):
                last_code = "g2b_connection_failed"
                retryable = True
            except (UnicodeError, json.JSONDecodeError):
                last_code = "invalid_api_response"
                retryable = False
            if not retryable or attempt == self.max_attempts:
                raise ExperimentError(last_code, "G2B API 요청이 안전한 실패로 종료됐습니다")
            self.sleeper(min(2 ** (attempt - 1), 2))
        raise ExperimentError(last_code, "G2B API 요청이 실패했습니다")


def extract_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int, int]:
    container = payload.get("response", payload)
    if not isinstance(container, dict):
        raise ExperimentError("invalid_api_response", "G2B response object가 없습니다")
    header = container.get("header")
    if not isinstance(header, dict) or str(header.get("resultCode")) != "00":
        code = str(header.get("resultCode")) if isinstance(header, dict) else "missing"
        raise ExperimentError("g2b_result_error", f"G2B resultCode가 정상이 아닙니다: {code}")
    body = container.get("body")
    if not isinstance(body, dict):
        raise ExperimentError("invalid_api_response", "G2B body object가 없습니다")
    try:
        total = int(body["totalCount"])
        page_no = int(body["pageNo"])
        rows = int(body["numOfRows"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExperimentError("invalid_api_response", "G2B pagination metadata가 잘못됐습니다") from exc
    items_value = body.get("items") or []
    if isinstance(items_value, dict):
        items_value = items_value.get("item") or []
    if isinstance(items_value, dict):
        items_value = [items_value]
    if not isinstance(items_value, list) or not all(isinstance(item, dict) for item in items_value):
        raise ExperimentError("invalid_api_response", "G2B items 형식이 잘못됐습니다")
    return items_value, total, page_no, rows


def items_pointer_prefix(payload: dict[str, Any]) -> str:
    """Return the JSON Pointer prefix used by the accepted response shape."""

    container = payload.get("response", payload)
    body = container.get("body") if isinstance(container, dict) else None
    items_value = body.get("items") if isinstance(body, dict) else None
    prefix = "/payload/response/body" if "response" in payload else "/payload/body"
    if isinstance(items_value, dict):
        return prefix + "/items/item"
    return prefix + "/items"


def parse_g2b_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentError("missing_source_timestamp", f"{field} 값이 없습니다")
    formats = ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y%m%d%H%M")
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    raise ExperimentError("invalid_source_timestamp", f"{field} 형식이 잘못됐습니다")


def nullable_amount(value: Any, unknown_fields: list[str], field: str) -> int | None:
    if value is None or value == "":
        unknown_fields.append(field)
        return None
    try:
        parsed = int(str(value).replace(",", ""))
    except ValueError:
        unknown_fields.append(field)
        return None
    if parsed < 0:
        unknown_fields.append(field)
        return None
    return parsed


def normalize_items(
    page_documents: Iterable[tuple[str, dict[str, Any]]],
    run_id: str,
    from_date: date,
    to_date: date,
    created_at: str,
    raw_input_sha256: str,
) -> dict[str, Any]:
    window_start = datetime.combine(from_date, datetime_time.min, KST)
    window_end = datetime.combine(to_date, datetime_time.min, KST)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_name, wrapper in page_documents:
        if wrapper.get("schema_version") != RAW_PAGE_SCHEMA:
            raise ExperimentError("schema_mismatch", f"raw page schema가 다릅니다: {raw_name}")
        payload = wrapper.get("payload")
        if not isinstance(payload, dict) or wrapper.get("payload_sha256") != digest_json(payload):
            raise ExperimentError("hash_mismatch", f"raw payload hash가 다릅니다: {raw_name}")
        items, _total, _page_no, _rows = extract_page(payload)
        pointer_prefix = items_pointer_prefix(payload)
        for index, item in enumerate(items):
            plan_id = item.get("orderPlanUntyNo")
            if not isinstance(plan_id, str) or not plan_id.strip():
                raise ExperimentError("missing_plan_id", f"공식 발주계획통합번호가 없습니다: {raw_name}#{index}")
            plan_id = plan_id.strip()
            if plan_id in seen:
                raise ExperimentError("duplicate_plan_id", f"중복 plan_id가 있습니다: {plan_id}")
            seen.add(plan_id)
            published = parse_g2b_timestamp(item.get("nticeDt"), "nticeDt")
            if not window_start <= published < window_end:
                raise ExperimentError("window_boundary_mismatch", f"조회 반개구간 밖 레코드가 있습니다: {plan_id}")
            business_division = item.get("bsnsDivNm")
            if business_division not in ALLOWED_BUSINESS_DIVISIONS:
                raise ExperimentError("business_scope_mismatch", f"허용 범위 밖 업무구분입니다: {plan_id}")
            title = item.get("bizNm")
            if not isinstance(title, str) or not title.strip():
                raise ExperimentError("missing_title", f"사업명이 없습니다: {plan_id}")
            unknown_fields: list[str] = []
            changed_at: str | None
            if item.get("chgDt") in (None, ""):
                changed_at = None
                unknown_fields.append("changed_at")
            else:
                changed_at = parse_g2b_timestamp(item.get("chgDt"), "chgDt").isoformat()
            order_year = str(item.get("orderYear") or "").strip()
            order_month = str(item.get("orderMnth") or "").strip().zfill(2)
            if len(order_year) == 4 and order_year.isdigit() and order_month in {f"{n:02d}" for n in range(1, 13)}:
                planned_order_month: str | None = f"{order_year}-{order_month}"
            else:
                planned_order_month = None
                unknown_fields.append("planned_order_month")
            normalized.append(
                {
                    "plan_id": plan_id,
                    "title": title.strip(),
                    "agency_code": item.get("orderInsttCd") or None,
                    "agency_name": item.get("orderInsttNm") or None,
                    "supervising_agency_name": item.get("totlmngInsttNm") or None,
                    "business_division": business_division,
                    "business_division_code": item.get("bsnsDivCd") or None,
                    "service_type": item.get("bsnsTyNm") or None,
                    "service_type_code": item.get("bsnsTyCd") or None,
                    "budget_amount": nullable_amount(item.get("sumOrderAmt"), unknown_fields, "budget_amount"),
                    "contract_amount": nullable_amount(
                        item.get("orderContrctAmt"), unknown_fields, "contract_amount"
                    ),
                    "planned_order_month": planned_order_month,
                    "procurement_method": item.get("prcrmntMethd") or None,
                    "contract_method": item.get("cntrctMthdNm") or None,
                    "sw_business_status": None,
                    "official_url": None,
                    "published_at": published.isoformat(),
                    "changed_at": changed_at,
                    "first_discovered_at": created_at,
                    "last_discovered_at": created_at,
                    "unknown_fields": sorted(set(unknown_fields + ["sw_business_status", "official_url"])),
                    "source": {
                        "raw_ref": f"raw/{raw_name}#{pointer_prefix}/{index}",
                        "source_sha256": digest_json(item),
                    },
                }
            )
    normalized.sort(key=lambda item: item["plan_id"])
    population = {
        "schema_version": POPULATION_SCHEMA,
        "run_id": run_id,
        "created_at": created_at,
        "input_sha256": raw_input_sha256,
        "population_sha256": digest_json(normalized),
        "items": normalized,
    }
    return validate_population(population)


def raw_aggregate_hash(wrappers: Iterable[dict[str, Any]]) -> str:
    bindings = [
        {
            "endpoint_id": wrapper.get("endpoint_id"),
            "query": wrapper.get("query"),
            "page_no": wrapper.get("page_no"),
            "payload_sha256": wrapper.get("payload_sha256"),
        }
        for wrapper in wrappers
    ]
    return digest_json(bindings)


def read_raw_pages(raw_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    if raw_dir.is_symlink():
        raise ExperimentError("raw_path_rejected", "raw 디렉터리 symlink는 허용하지 않습니다")
    paths = sorted(raw_dir.glob("page-*.json"))
    if not paths:
        raise ExperimentError("raw_pages_missing", "raw page가 없습니다")
    pages: list[tuple[str, dict[str, Any]]] = []
    expected_page = 1
    expected_total: int | None = None
    item_count = 0
    response_rows: int | None = None
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ExperimentError("raw_path_rejected", f"raw page는 일반 파일이어야 합니다: {path.name}")
        if path.name != f"page-{expected_page:05d}.json":
            raise ExperimentError("pagination_incomplete", "raw page 파일명이 연속적이지 않습니다")
        wrapper = load_json(path)
        if not isinstance(wrapper, dict):
            raise ExperimentError("invalid_contract", f"raw page가 object가 아닙니다: {path.name}")
        if wrapper.get("schema_version") != RAW_PAGE_SCHEMA:
            raise ExperimentError("schema_mismatch", f"raw page schema가 다릅니다: {path.name}")
        attempts = wrapper.get("request_attempts")
        if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 3:
            raise ExperimentError("invalid_contract", f"raw request_attempts가 잘못됐습니다: {path.name}")
        parse_timezone_timestamp(wrapper.get("collected_at"), f"{path.name}.collected_at")
        payload = wrapper.get("payload")
        if not isinstance(payload, dict) or wrapper.get("payload_sha256") != digest_json(payload):
            raise ExperimentError("hash_mismatch", f"raw page hash가 다릅니다: {path.name}")
        items, total, page_no, rows = extract_page(payload)
        if rows < 1 or rows > 999:
            raise ExperimentError("pagination_mismatch", "raw page numOfRows가 허용 범위 밖입니다")
        if response_rows is None:
            response_rows = rows
        elif rows != response_rows:
            raise ExperimentError("pagination_changed", "raw page 사이 numOfRows가 바뀌었습니다")
        if page_no != expected_page or wrapper.get("page_no") != page_no:
            raise ExperimentError("pagination_incomplete", "raw page 번호가 연속적이지 않습니다")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ExperimentError("pagination_changed", "페이지 사이 totalCount가 바뀌었습니다")
        item_count += len(items)
        pages.append((path.name, wrapper))
        expected_page += 1
    if expected_total is None or item_count != expected_total:
        raise ExperimentError("pagination_incomplete", "raw 모집단 건수와 totalCount가 다릅니다")
    expected_page_count = max(1, (expected_total + int(response_rows) - 1) // int(response_rows))
    if len(pages) != expected_page_count:
        raise ExperimentError("pagination_incomplete", "raw page 개수가 totalCount와 맞지 않습니다")
    return pages


def validate_raw_queries(
    pages: Iterable[tuple[str, dict[str, Any]]],
    from_date: date,
    to_date: date,
) -> None:
    """Bind replayed pages to the exact endpoint and half-open population window."""

    for name, wrapper in pages:
        if wrapper.get("endpoint_id") != ENDPOINT_ID:
            raise ExperimentError("raw_query_mismatch", f"raw endpoint가 다릅니다: {name}")
        query = wrapper.get("query")
        if not isinstance(query, dict):
            raise ExperimentError("raw_query_mismatch", f"raw query가 object가 아닙니다: {name}")
        try:
            page = int(query["pageNo"])
            rows = int(query["numOfRows"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExperimentError("raw_query_mismatch", f"raw pagination query가 잘못됐습니다: {name}") from exc
        expected = query_for_window(from_date, to_date, page, rows)
        if query != expected or page != wrapper.get("page_no"):
            raise ExperimentError("raw_query_mismatch", f"raw query가 실험 범위와 다릅니다: {name}")


def collect_pages(
    raw_dir: Path,
    from_date: date,
    to_date: date,
    rows: int,
    fetcher: G2BFetcher,
) -> list[tuple[str, dict[str, Any]]]:
    if raw_dir.exists() and any(raw_dir.iterdir()):
        raise ExperimentError("artifact_exists", "기존 raw 디렉터리를 덮어쓸 수 없습니다")
    raw_dir.mkdir(parents=True, exist_ok=True)
    page = 1
    expected_total: int | None = None
    received = 0
    while expected_total is None or received < expected_total:
        query = query_for_window(from_date, to_date, page, rows)
        payload, attempts = fetcher.fetch(query)
        items, total, response_page, response_rows = extract_page(payload)
        if response_page != page or response_rows != rows:
            raise ExperimentError("pagination_mismatch", "G2B 응답 pagination이 요청과 다릅니다")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ExperimentError("pagination_changed", "수집 중 totalCount가 바뀌었습니다")
        if not items and received < total:
            raise ExperimentError("pagination_incomplete", "마지막 이전에 빈 G2B page를 받았습니다")
        collected_at = datetime.now(KST).isoformat()
        wrapper = {
            "schema_version": RAW_PAGE_SCHEMA,
            "endpoint_id": ENDPOINT_ID,
            "query": query,
            "page_no": page,
            "request_attempts": attempts,
            "collected_at": collected_at,
            "payload_sha256": digest_json(payload),
            "payload": payload,
        }
        write_json_new(raw_dir / f"page-{page:05d}.json", wrapper)
        received += len(items)
        if received > total:
            raise ExperimentError("pagination_overflow", "수집 건수가 totalCount를 초과했습니다")
        page += 1
    pages = read_raw_pages(raw_dir)
    validate_raw_queries(pages, from_date, to_date)
    if fetcher.request_count >= STOP_REQUESTS:
        raise ExperimentError("request_budget_exhausted", "수집 호출 수가 900회 방어선을 넘었습니다")
    return pages


def copy_raw_pages(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ExperimentError("raw_path_rejected", "원본 raw는 symlink가 아닌 디렉터리여야 합니다")
    if destination.exists() and any(destination.iterdir()):
        raise ExperimentError("artifact_exists", "기존 raw 디렉터리를 덮어쓸 수 없습니다")
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob("page-*.json")):
        if path.is_symlink() or not path.is_file():
            raise ExperimentError("raw_path_rejected", f"raw page symlink를 복사할 수 없습니다: {path.name}")
        target = destination / path.name
        try:
            with path.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
        except FileExistsError as exc:
            raise ExperimentError("artifact_exists", f"raw page를 덮어쓸 수 없습니다: {path.name}") from exc
        except OSError as exc:
            raise ExperimentError("raw_copy_failed", f"raw page 복사에 실패했습니다: {path.name}") from exc


def build_run_document(
    args: argparse.Namespace,
    population: dict[str, Any],
    pages: list[tuple[str, dict[str, Any]]],
    request_count: int,
    capabilities_path: Path,
    methods_path: Path,
) -> dict[str, Any]:
    capabilities_document = load_json(capabilities_path)
    capabilities = capabilities_projection(capabilities_document, require_approved=False)
    methods = load_methods_config(methods_path)
    method_bindings = {
        name: {
            "method_version": config.get("method_version"),
            "model_name": config.get("model_name"),
            "model_revision": config.get("model_revision"),
            "prompt_id": config.get("prompt_id"),
            "prompt_sha256": config.get("prompt_sha256"),
            "config_sha256": digest_json(config),
        }
        for name, config in methods["methods"].items()
    }
    external: dict[str, Any]
    if capabilities_document.get("approval_status") == "approved":
        preview = external_preview(
            population,
            capabilities,
            methods["model_plan_allowed_fields"],
            method_bindings["luna"]["model_revision"],
            method_bindings["luna"]["prompt_sha256"],
            methods["methods"]["luna"]["batch_size"],
        )
        external = {"status": "pending_approval", **preview}
    else:
        external = {
            "status": "blocked",
            "reason": "capabilities_not_approved",
            "model": method_bindings["luna"]["model_revision"],
            "purpose": "order_plan_screening_comparison",
            "prompt_sha256": method_bindings["luna"]["prompt_sha256"],
            "company_capabilities_sha256": digest_json(capabilities),
            "payload_fields": list(methods["model_plan_allowed_fields"]),
            "record_count": len(population["items"]),
            "batch_size": methods["methods"]["luna"]["batch_size"],
            "batch_count": (
                len(population["items"]) + methods["methods"]["luna"]["batch_size"] - 1
            )
            // methods["methods"]["luna"]["batch_size"],
            "preview_sha256": None,
        }
    collected_times = [wrapper["collected_at"] for _name, wrapper in pages]
    return {
        "schema_version": RUN_SCHEMA,
        "run_id": args.run_id,
        "created_at": population["created_at"],
        "input_sha256": population["input_sha256"],
        "population_sha256": population["population_sha256"],
        "population_count": len(population["items"]),
        "selection": {"top_k": methods["top_k"]},
        "model_payload": {
            "allowed_plan_fields": list(methods["model_plan_allowed_fields"]),
            "company_capabilities_sha256": digest_json(capabilities),
            "batch_sizes": {
                "qwen": methods["methods"]["qwen"]["batch_size"],
                "luna": methods["methods"]["luna"]["batch_size"],
            },
        },
        "query_window": {
            "from": datetime.combine(args.from_date, datetime_time.min, KST).isoformat(),
            "to_exclusive": datetime.combine(args.to_date, datetime_time.min, KST).isoformat(),
            "business_divisions": sorted(ALLOWED_BUSINESS_DIVISIONS),
            "prefilters": [],
            "api_order_month_scope": {
                "from": ORDER_SCOPE_FROM_MONTH,
                "to_inclusive": ORDER_SCOPE_TO_MONTH,
                "purpose": "required_api_dimension_without_population_prefilter",
            },
        },
        "collection": {
            "endpoint_id": ENDPOINT_ID,
            "page_count": len(pages),
            "request_count": request_count,
            "first_collected_at": min(collected_times),
            "last_collected_at": max(collected_times),
            "raw_input_sha256": population["input_sha256"],
            "complete": True,
        },
        "config": {
            "company_capabilities_sha256": sha256_file(capabilities_path),
            "methods_sha256": sha256_file(methods_path),
            "company_capabilities_approval_status": capabilities_document.get("approval_status"),
            "company_capabilities_summary_sha256": capabilities_document.get("summary_sha256"),
        },
        "methods": method_bindings,
        "external_transmission": external,
    }


def main() -> int:
    args = parse_args()
    try:
        if not args.run_id.strip() or "/" in args.run_id or "\\" in args.run_id or ".." in args.run_id:
            raise ExperimentError("invalid_run_id", "run_id가 안전하지 않습니다")
        output_dir = args.output_dir.resolve()
        if (output_dir / "run.json").exists() or (output_dir / "population.json").exists():
            raise ExperimentError("artifact_exists", "기존 run 또는 population을 덮어쓸 수 없습니다")
        raw_dir = output_dir / "raw"
        if args.from_raw:
            copy_raw_pages(args.from_raw.absolute(), raw_dir)
            pages = read_raw_pages(raw_dir)
            validate_raw_queries(pages, args.from_date, args.to_date)
            request_count = sum(int(wrapper.get("request_attempts", 1)) for _name, wrapper in pages)
        else:
            fetcher = G2BFetcher(get_service_key(), args.timeout, args.max_attempts)
            pages = collect_pages(raw_dir, args.from_date, args.to_date, args.rows, fetcher)
            request_count = fetcher.request_count
        wrappers = [wrapper for _name, wrapper in pages]
        raw_hash = raw_aggregate_hash(wrappers)
        created_at = min(wrapper["collected_at"] for wrapper in wrappers)
        population = normalize_items(
            pages, args.run_id, args.from_date, args.to_date, created_at, raw_hash
        )
        run = build_run_document(
            args,
            population,
            pages,
            request_count,
            args.company_capabilities.resolve(),
            args.methods_config.resolve(),
        )
        if args.external_approval is not None:
            external = run["external_transmission"]
            if external.get("status") != "pending_approval":
                raise ExperimentError("external_preview_unavailable", "승인 가능한 외부 payload preview가 없습니다")
            preview = {key: value for key, value in external.items() if key != "status"}
            approval = validate_external_approval(
                load_json(args.external_approval.resolve()), run, preview
            )
            run["external_transmission"] = {
                "status": "approved",
                **preview,
                "approved_by": approval["approved_by"],
                "approved_at": approval["approved_at"],
            }
        write_json_new(output_dir / "population.json", population)
        write_json_new(output_dir / "run.json", run)
        print(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "population_count": len(population["items"]),
                    "page_count": len(pages),
                    "request_count": request_count,
                    "status": "complete",
                },
                ensure_ascii=False,
            )
        )
        return 0
    except ExperimentError as exc:
        print(json.dumps({"status": "failed", "error_code": exc.code}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
