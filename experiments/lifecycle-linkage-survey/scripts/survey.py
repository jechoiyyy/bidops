#!/usr/bin/env python3
"""Survey the G2B lifecycle endpoints and the links between them.

This experiment answers three questions that the product flow depends on but
that have never been measured:

  A. Does an already-collected order plan reappear, with updated linkage
     fields, when its original publication window is queried again?
  B. Does the pre-specification response carry an order-plan key, an
     SW-scope field, and attachment URLs?
  C. How often does the bid notice actually carry its pre-specification
     registration number?

The output is evidence, not a product change.  Nothing here writes to the
application database, and no value is inferred when the source is silent.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_EXPERIMENTS_ROOT = _SCRIPT_DIR.parents[1]
# The order-plan experiment already owns the immutable-artifact contracts this
# survey needs.  Import them instead of restating hashing and write rules.
sys.path.insert(0, str(_EXPERIMENTS_ROOT / "order-plan-screening" / "scripts"))
sys.path.insert(0, str(_SCRIPT_DIR))

from common import (  # noqa: E402
    ExperimentError,
    digest_json,
    load_json,
    write_json_new,
)
from endpoints import ENDPOINTS, KST, Endpoint  # noqa: E402


RAW_PAGE_SCHEMA = "bidops.lifecycle-survey-raw-page.v1"
SURVEY_SCHEMA = "bidops.lifecycle-survey.v1"
# The frozen order-plan experiment writes this schema; a baseline replay must
# accept it so the re-collection can be compared against it.
ACCEPTED_BASELINE_SCHEMAS = (RAW_PAGE_SCHEMA, "bidops.order-plan-raw-page.v1")

WARNING_REQUESTS = 700
STOP_REQUESTS = 900

# Field-name fragments that mark a contact person rather than procurement
# facts.  Their values are counted but never copied into an artifact, because
# the survey report is committed to the repository.
PERSONAL_FIELD_HINTS = ("ofcl", "tel", "fax", "email", "mobile", "hpno", "chrg", "mngr")
EXAMPLE_MAX_CHARS = 60


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def get_service_key() -> str:
    import os

    key = os.environ.get("BIDOPS_G2B_API_KEY", "").strip()
    if not key:
        raise ExperimentError("service_key_missing", "BIDOPS_G2B_API_KEY가 필요합니다")
    return urllib.parse.unquote(key)


class SurveyFetcher:
    """Endpoint-parameterised G2B client with the experiment's call budget."""

    def __init__(
        self,
        service_key: str,
        timeout: int = 30,
        max_attempts: int = 2,
        opener: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        quote_via: Callable[..., str] = urllib.parse.quote_plus,
        request_limit: int | None = None,
    ):
        if timeout < 1 or max_attempts < 1 or max_attempts > 3:
            raise ExperimentError("invalid_http_config", "timeout 또는 max_attempts가 잘못됐습니다")
        if request_limit is not None and request_limit < 1:
            raise ExperimentError("invalid_request_limit", "request_limit는 1 이상이어야 합니다")
        self.service_key = service_key
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )
        self.sleeper = sleeper
        # Keep quote_plus as the default for byte-for-byte compatibility with
        # every existing collector and test.  Isolation probes may inject
        # urllib.parse.quote to distinguish '+' from '%20' for spaces.
        self.quote_via = quote_via
        # Optional per-run budget used by bounded probes.  Existing callers
        # leave this unset and retain the survey-wide 900-call guard below.
        self.request_limit = request_limit
        self.request_count = 0
        self.warning_emitted = False

    def fetch(self, url: str, public_query: dict[str, str]) -> tuple[dict[str, Any], int]:
        last_code = "g2b_request_failed"
        for attempt in range(1, self.max_attempts + 1):
            if self.request_limit is not None and self.request_count >= self.request_limit:
                raise ExperimentError(
                    "request_budget_exhausted",
                    f"{self.request_limit}회 요청 상한에서 신규 API 호출을 중지했습니다",
                )
            if self.request_count >= STOP_REQUESTS:
                raise ExperimentError(
                    "request_budget_exhausted", "900회 방어선에서 신규 API 호출을 중지했습니다"
                )
            self.request_count += 1
            if self.request_count >= WARNING_REQUESTS and not self.warning_emitted:
                print("warning: G2B 요청 수가 700회 방어선에 도달했습니다", file=sys.stderr)
                self.warning_emitted = True
            params = dict(public_query)
            params["serviceKey"] = self.service_key
            request = urllib.request.Request(
                url + "?" + urllib.parse.urlencode(params, quote_via=self.quote_via),
                headers={"Accept": "application/json"},
            )
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    payload = response.read().decode("utf-8", errors="strict")
                document = json.loads(payload)
                if not isinstance(document, dict):
                    raise ExperimentError("invalid_api_response", "G2B 응답 최상위가 object가 아닙니다")
                if self.service_key and self.service_key in payload:
                    raise ExperimentError(
                        "secret_reflected", "G2B 응답이 인증정보를 반사해 저장을 중지했습니다"
                    )
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


def write_raw_page(
    path: Path,
    endpoint: Endpoint,
    query: dict[str, str],
    page_no: int,
    request_attempts: int,
    payload: dict[str, Any],
) -> None:
    """Write one immutable raw response using the survey's secret hygiene.

    ``SurveyFetcher.fetch`` adds the service key only to its temporary wire
    query and rejects a reflected key before returning.  This shared writer
    enforces the other half of the boundary: callers may only persist the
    public query, never a query containing ``serviceKey``.
    """

    if "serviceKey" in query:
        raise ExperimentError("secret_stored", "raw query에 인증키가 있습니다")
    if not isinstance(payload, dict):
        raise ExperimentError("invalid_api_response", "raw payload가 object가 아닙니다")
    write_json_new(
        path,
        {
            "schema_version": RAW_PAGE_SCHEMA,
            "endpoint_id": endpoint.endpoint_id,
            "query": dict(query),
            "page_no": page_no,
            "request_attempts": request_attempts,
            "collected_at": datetime.now(KST).isoformat(),
            "payload_sha256": digest_json(payload),
            "payload": payload,
        },
    )


def collect_pages(
    endpoint: Endpoint,
    raw_dir: Path,
    from_date: date,
    to_date: date,
    rows: int,
    fetcher: SurveyFetcher,
) -> int:
    """Fetch every page of one endpoint window into immutable raw files."""

    if to_date <= from_date:
        raise ExperimentError("invalid_window", "to-date는 from-date보다 뒤여야 합니다")
    if rows < 1 or rows > 999:
        raise ExperimentError("invalid_page_size", "rows는 1..999여야 합니다")
    if raw_dir.exists() and any(raw_dir.iterdir()):
        raise ExperimentError("artifact_exists", "기존 raw 디렉터리를 덮어쓸 수 없습니다")
    raw_dir.mkdir(parents=True, exist_ok=True)

    page = 1
    expected_total: int | None = None
    received = 0
    while expected_total is None or received < expected_total:
        query = endpoint.query_builder(from_date, to_date, page, rows)
        payload, attempts = fetcher.fetch(endpoint.url, query)
        items, total, response_page, response_rows = extract_page(payload)
        if response_page != page or response_rows != rows:
            raise ExperimentError("pagination_mismatch", "G2B 응답 pagination이 요청과 다릅니다")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ExperimentError("pagination_changed", "수집 중 totalCount가 바뀌었습니다")
        if not items and received < total:
            raise ExperimentError("pagination_incomplete", "마지막 이전에 빈 G2B page를 받았습니다")
        write_raw_page(
            raw_dir / f"{endpoint.target}-page-{page:05d}.json",
            endpoint,
            query,
            page,
            attempts,
            payload,
        )
        received += len(items)
        if received > total:
            raise ExperimentError("pagination_overflow", "수집 건수가 totalCount를 초과했습니다")
        page += 1
    return received


def read_raw_pages(raw_dir: Path, accepted_schemas: Sequence[str] = (RAW_PAGE_SCHEMA,)) -> list[dict[str, Any]]:
    if not raw_dir.is_dir():
        raise ExperimentError("raw_missing", f"raw 디렉터리가 없습니다: {raw_dir.name}")
    wrappers: list[dict[str, Any]] = []
    for path in sorted(raw_dir.glob("*.json")):
        wrapper = load_json(path)
        if not isinstance(wrapper, dict):
            raise ExperimentError("schema_mismatch", f"raw page 형식이 다릅니다: {path.name}")
        if wrapper.get("schema_version") not in accepted_schemas:
            raise ExperimentError("schema_mismatch", f"raw page schema가 다릅니다: {path.name}")
        payload = wrapper.get("payload")
        if not isinstance(payload, dict) or wrapper.get("payload_sha256") != digest_json(payload):
            raise ExperimentError("hash_mismatch", f"raw payload hash가 다릅니다: {path.name}")
        if "serviceKey" in (wrapper.get("query") or {}):
            raise ExperimentError("secret_stored", f"raw query에 인증키가 있습니다: {path.name}")
        wrappers.append(wrapper)
    if not wrappers:
        raise ExperimentError("raw_missing", f"raw page가 없습니다: {raw_dir.name}")
    return wrappers


def items_from_pages(wrappers: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for wrapper in wrappers:
        page_items, _total, _page_no, _rows = extract_page(wrapper["payload"])
        items.extend(page_items)
    return items


def is_personal_field(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in PERSONAL_FIELD_HINTS)


def example_value(name: str, value: Any) -> str:
    if is_personal_field(name):
        return "<담당자 정보 · 예시 생략>"
    text = str(value)
    if len(text) > EXAMPLE_MAX_CHARS:
        return text[:EXAMPLE_MAX_CHARS] + "…"
    return text


def field_stats(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill rate and one safe example per field, including always-empty ones.

    An always-empty field is evidence too: it may be a linkage slot that the
    source fills only later, so it must not be dropped from the report.
    """

    names: list[str] = []
    seen: set[str] = set()
    for item in items:
        for name in item:
            if name not in seen:
                seen.add(name)
                names.append(name)
    total = len(items)
    stats: list[dict[str, Any]] = []
    for name in sorted(names):
        filled = 0
        example: Any = None
        for item in items:
            value = item.get(name)
            if value not in (None, "", [], {}):
                filled += 1
                if example is None:
                    example = value
        stats.append(
            {
                "field": name,
                "filled": filled,
                "total": total,
                "fill_rate": round(filled / total, 4) if total else None,
                "example": example_value(name, example) if example is not None else None,
                "personal": is_personal_field(name),
            }
        )
    return stats


def index_by_key(items: Sequence[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ExperimentError("missing_record_key", f"레코드 키 {key}가 없습니다")
        identifier = value.strip()
        if identifier in indexed:
            raise ExperimentError("duplicate_record_key", f"중복 레코드 키가 있습니다: {identifier}")
        indexed[identifier] = item
    return indexed


def compare_observations(
    baseline: Sequence[dict[str, Any]],
    current: Sequence[dict[str, Any]],
    key: str,
) -> dict[str, Any]:
    """Diff two observations of the same window, keyed by the record key.

    This is the measurement behind question A: whether re-querying a past
    publication window returns records whose linkage fields have since been
    filled in.
    """

    base_index = index_by_key(baseline, key)
    current_index = index_by_key(current, key)
    common = sorted(set(base_index) & set(current_index))
    changed_field_counts: dict[str, int] = {}
    changed_records = 0
    examples: list[dict[str, Any]] = []
    for identifier in common:
        before = base_index[identifier]
        after = current_index[identifier]
        changed = sorted(
            name
            for name in set(before) | set(after)
            if before.get(name) != after.get(name)
        )
        if not changed:
            continue
        changed_records += 1
        for name in changed:
            changed_field_counts[name] = changed_field_counts.get(name, 0) + 1
        if len(examples) < 5:
            examples.append(
                {
                    "record_key": identifier,
                    "changed_fields": changed,
                    "before": {
                        name: example_value(name, before.get(name))
                        for name in changed
                        if before.get(name) not in (None, "")
                    },
                    "after": {
                        name: example_value(name, after.get(name))
                        for name in changed
                        if after.get(name) not in (None, "")
                    },
                }
            )
    return {
        "record_key": key,
        "baseline_count": len(base_index),
        "current_count": len(current_index),
        "common_count": len(common),
        "only_in_baseline": sorted(set(base_index) - set(current_index))[:20],
        "only_in_current": sorted(set(current_index) - set(base_index))[:20],
        "changed_record_count": changed_records,
        "changed_field_counts": dict(sorted(changed_field_counts.items(), key=lambda pair: (-pair[1], pair[0]))),
        "examples": examples,
    }


def linkage_probe(target: str, items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Report which cross-entity keys this endpoint actually carries.

    Absence is recorded as `unknown` rather than a negative claim: a field the
    source never returns and a field this survey did not look for are different
    findings.
    """

    candidates = {
        "order_plan": ("orderPlanUntyNo", "bidNtceNoList", "rcritRgstNo", "bfSpecRgstNo", "ntceNticeYn"),
        "prespec": ("bfSpecRgstNo", "orderPlanUntyNo", "bidNtceNo", "untyNtceNo", "sptDprtNm"),
        "prespec_search": (
            "bfSpecRgstNo",
            "orderPlanUntyNo",
            "bidNtceNo",
            "bidNtceNoList",
            "untyNtceNo",
            "refNo",
            "swBizObjYn",
        ),
        "bid": ("bidNtceNo", "bfSpecRgstNo", "untyNtceNo", "orderPlanUntyNo"),
    }.get(target, ())
    present = {name for item in items for name in item}
    probe: dict[str, Any] = {}
    for name in candidates:
        if name not in present:
            probe[name] = {"status": "absent_from_response"}
            continue
        filled = sum(1 for item in items if item.get(name) not in (None, "", [], {}))
        probe[name] = {
            "status": "present",
            "filled": filled,
            "total": len(items),
            "fill_rate": round(filled / len(items), 4) if items else None,
        }
    return probe


def build_survey(
    run_id: str,
    target_reports: list[dict[str, Any]],
    comparison: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": SURVEY_SCHEMA,
        "run_id": run_id,
        "created_at": datetime.now(KST).isoformat(),
        "targets": target_reports,
        "order_plan_recheck": comparison,
    }


def render_markdown(survey: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# 생애주기 연결 조사 — {survey['run_id']}")
    lines.append("")
    lines.append(f"수행 시각: {survey['created_at']}")
    lines.append("")

    comparison = survey.get("order_plan_recheck")
    if comparison:
        lines.append("## A. 발주계획 갱신 재관측")
        lines.append("")
        lines.append(f"- 기준 관측: {comparison['baseline_count']}건")
        lines.append(f"- 재조회 관측: {comparison['current_count']}건")
        lines.append(f"- 공통 레코드: {comparison['common_count']}건")
        lines.append(f"- 값이 바뀐 레코드: {comparison['changed_record_count']}건")
        lines.append("")
        if comparison["changed_field_counts"]:
            lines.append("| 변경된 필드 | 건수 |")
            lines.append("|---|---|")
            for name, count in comparison["changed_field_counts"].items():
                lines.append(f"| `{name}` | {count} |")
        else:
            lines.append("공통 레코드에서 변경된 필드가 없다.")
        lines.append("")
        if comparison["only_in_current"]:
            lines.append(f"재조회에만 있는 레코드 예시: {', '.join(comparison['only_in_current'][:5])}")
            lines.append("")

    for report in survey["targets"]:
        lines.append(f"## {report['target']} — {report['description']}")
        lines.append("")
        lines.append(f"- endpoint_id: `{report['endpoint_id']}`")
        lines.append(f"- 조회 구간: {report['window']['from']} ~ {report['window']['to_exclusive']} (반개구간)")
        lines.append(f"- 수집 건수: {report['record_count']}건, page {report['page_count']}개")
        lines.append("")
        lines.append("### 연결 키 존재 여부")
        lines.append("")
        lines.append("| 필드 | 상태 | 채움 |")
        lines.append("|---|---|---|")
        for name, probe in report["linkage"].items():
            if probe["status"] == "absent_from_response":
                lines.append(f"| `{name}` | 응답에 없음 | unknown |")
            else:
                lines.append(f"| `{name}` | 존재 | {probe['filled']}/{probe['total']} |")
        lines.append("")
        lines.append("### 전체 필드")
        lines.append("")
        lines.append("| 필드 | 채움 | 비율 | 예시 |")
        lines.append("|---|---|---|---|")
        for row in report["fields"]:
            rate = "-" if row["fill_rate"] is None else f"{row['fill_rate'] * 100:.1f}%"
            example = row["example"] if row["example"] is not None else "-"
            example = example.replace("|", "\\|")
            lines.append(f"| `{row['field']}` | {row['filled']}/{row['total']} | {rate} | {example} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def target_report(
    endpoint: Endpoint,
    wrappers: Sequence[dict[str, Any]],
    items: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    queries = [wrapper["query"] for wrapper in wrappers]
    return {
        "target": endpoint.target,
        "description": endpoint.description,
        "endpoint_id": endpoint.endpoint_id,
        "window": {
            "from": queries[0].get("inqryBgnDt"),
            "to_exclusive": queries[0].get("inqryEndDt"),
        },
        "page_count": len(wrappers),
        "record_count": len(items),
        "linkage": linkage_probe(endpoint.target, items),
        "fields": field_stats(items),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="G2B를 호출해 불변 raw page를 저장합니다")
    collect.add_argument("--run-id", required=True)
    collect.add_argument("--output-dir", required=True, type=Path)
    collect.add_argument("--target", action="append", choices=sorted(ENDPOINTS), required=True)
    collect.add_argument("--from-date", required=True, type=date.fromisoformat)
    collect.add_argument("--to-date", required=True, type=date.fromisoformat, help="반개구간의 끝(제외)")
    collect.add_argument("--rows", type=int, default=500)
    collect.add_argument("--timeout", type=int, default=30)
    collect.add_argument("--max-attempts", type=int, default=2)
    collect.add_argument(
        "--execute",
        action="store_true",
        help="외부 G2B 호출을 명시적으로 허용합니다. 없으면 아무 호출도 하지 않습니다.",
    )

    report = sub.add_parser("report", help="저장된 raw page로 조사 결과를 만듭니다")
    report.add_argument("--run-id", required=True)
    report.add_argument("--raw-dir", required=True, type=Path)
    report.add_argument("--output-dir", required=True, type=Path)
    report.add_argument(
        "--baseline-raw",
        type=Path,
        help="발주계획 재조회를 비교할 기준 raw 디렉터리(고정 실험의 raw)입니다.",
    )
    report.add_argument("--markdown", type=Path, help="markdown 리포트를 쓸 경로입니다.")
    return parser.parse_args(argv)


def run_collect(args: argparse.Namespace) -> int:
    if not args.execute:
        print(
            "외부 호출이 승인되지 않았습니다. --execute를 명시하면 G2B를 호출합니다.",
            file=sys.stderr,
        )
        return 2
    if not args.run_id.strip() or any(part in args.run_id for part in ("/", "\\", "..")):
        raise ExperimentError("invalid_run_id", "run_id가 안전하지 않습니다")
    output_dir = args.output_dir.resolve()
    raw_dir = output_dir / "raw"
    fetcher = SurveyFetcher(
        get_service_key(), timeout=args.timeout, max_attempts=args.max_attempts
    )
    collected: dict[str, int] = {}
    for target in args.target:
        endpoint = ENDPOINTS[target]
        collected[target] = collect_pages(
            endpoint, raw_dir / target, args.from_date, args.to_date, args.rows, fetcher
        )
        print(f"{target}: {collected[target]}건 수집")
    # One run directory can hold several windows (the order-plan recheck uses a
    # past window while the other endpoints use a recent one), so the manifest
    # is named after its target set instead of colliding on a single file.
    manifest_name = "collection-" + "-".join(sorted(args.target)) + ".json"
    write_json_new(
        output_dir / manifest_name,
        {
            "run_id": args.run_id,
            "collected_at": datetime.now(KST).isoformat(),
            "window": {"from": args.from_date.isoformat(), "to_exclusive": args.to_date.isoformat()},
            "targets": collected,
            "request_count": fetcher.request_count,
        },
    )
    return 0


def run_report(args: argparse.Namespace) -> int:
    raw_root = args.raw_dir.resolve()
    output_dir = args.output_dir.resolve()
    target_reports: list[dict[str, Any]] = []
    order_plan_items: list[dict[str, Any]] | None = None
    for target in sorted(ENDPOINTS):
        target_dir = raw_root / target
        if not target_dir.is_dir():
            continue
        endpoint = ENDPOINTS[target]
        wrappers = read_raw_pages(target_dir)
        items = items_from_pages(wrappers)
        target_reports.append(target_report(endpoint, wrappers, items))
        if target == "order_plan":
            order_plan_items = items
    if not target_reports:
        raise ExperimentError("raw_missing", "조사할 raw target 디렉터리가 없습니다")

    comparison: dict[str, Any] | None = None
    if args.baseline_raw is not None:
        if order_plan_items is None:
            raise ExperimentError("raw_missing", "비교하려면 order_plan raw가 필요합니다")
        baseline_items = items_from_pages(
            read_raw_pages(args.baseline_raw.resolve(), ACCEPTED_BASELINE_SCHEMAS)
        )
        comparison = compare_observations(
            baseline_items, order_plan_items, ENDPOINTS["order_plan"].record_key
        )

    survey = build_survey(args.run_id, target_reports, comparison)
    write_json_new(output_dir / "survey.json", survey)
    if args.markdown is not None:
        markdown_path = args.markdown.resolve()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with markdown_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(render_markdown(survey))
        except FileExistsError as exc:
            raise ExperimentError(
                "artifact_exists", f"기존 리포트를 덮어쓸 수 없습니다: {markdown_path.name}"
            ) from exc
    print(f"survey.json 작성: {output_dir / 'survey.json'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "collect":
            return run_collect(args)
        return run_report(args)
    except ExperimentError as exc:
        print(f"error[{exc.code}]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
