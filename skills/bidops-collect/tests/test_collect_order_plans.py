#!/usr/bin/env python3
"""Contract and replay tests for the independent order-plan collector."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SCRIPT = SCRIPT_DIR / "collect_order_plans.py"
SPEC = importlib.util.spec_from_file_location("bidops_collect_order_plans", SCRIPT)
assert SPEC and SPEC.loader
COLLECT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECT)


FROM_DATE = date(2026, 8, 24)
TO_DATE = date(2026, 8, 27)
DISCOVERED_AT = "2026-08-29T12:00:00+09:00"


def source_item(
    plan_id: str,
    *,
    business_division: str = "일반용역",
    published_at: str = "20260825185627",
    rcrit: str = "",
) -> dict:
    return {
        "orderPlanUntyNo": plan_id,
        "bizNm": f"실측 사업 {plan_id}",
        "orderInsttCd": "1234567",
        "orderInsttNm": "발주기관",
        "totlmngInsttNm": "총괄기관",
        "bsnsDivCd": "03",
        "bsnsDivNm": business_division,
        "bsnsTyCd": "신120001",
        "bsnsTyNm": "신규(단기)",
        "sumOrderAmt": "123,456,789",
        "orderContrctAmt": "0",
        "orderYear": "2027",
        "orderMnth": "09",
        "prcrmntMethd": "자체조달",
        "cntrctMthdNm": "제한경쟁",
        "nticeDt": published_at,
        "chgDt": "20260826101010",
        "bidNtceNoList": "R26BK01696186000",
        "ntceNticeYn": "Y",
        "rcritRgstNo": rcrit,
        "orderPlanDtlUrl": "https://www.g2b.go.kr/order-plan",
    }


def payload(items: list[dict], *, page: int, total: int, rows: int = 2) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {
                "totalCount": str(total),
                "pageNo": str(page),
                "numOfRows": str(rows),
                "items": items,
            },
        }
    }


class FakeFetcher:
    def __init__(self, responses: dict[int, dict]) -> None:
        self.responses = responses
        self.queries: list[dict[str, str]] = []

    def fetch(self, query: dict[str, str]) -> tuple[dict, int]:
        self.queries.append(dict(query))
        return self.responses[int(query["pageNo"])], 1


def collect_fixture(
    directory: Path,
    responses: dict[int, dict],
    *,
    rows: int = 2,
) -> tuple[FakeFetcher, list[tuple[str, dict]], dict]:
    fetcher = FakeFetcher(responses)
    warnings: list[str] = []
    pages = COLLECT.collect_pages(
        directory,
        FROM_DATE,
        TO_DATE,
        rows,
        fetcher,
        warnings,
    )
    artifact = COLLECT.build_artifact(
        pages,
        FROM_DATE,
        TO_DATE,
        warnings,
    )
    return fetcher, pages, artifact


class QueryAndWindowTests(unittest.TestCase):
    def test_query_sends_no_order_month_span(self) -> None:
        # From 2026-11-20 PPSSrch rejects 200412..999912 (resultCode 07) and
        # returns the whole population when the two values are left out.
        query = COLLECT.query_for_window(FROM_DATE, TO_DATE, 1, 500)
        self.assertEqual(
            {"pageNo", "numOfRows", "type", "inqryBgnDt", "inqryEndDt"}, set(query)
        )
        self.assertEqual("202608240000", query["inqryBgnDt"])
        self.assertEqual("202608262359", query["inqryEndDt"])

    def test_legacy_query_form_is_kept_for_preserved_raw_pages(self) -> None:
        query = COLLECT.query_for_window(
            FROM_DATE, TO_DATE, 1, 500, legacy_order_month_scope=True
        )
        self.assertEqual("200412", query["orderBgnYm"])
        self.assertEqual("999912", query["orderEndYm"])
        self.assertEqual("202608240000", query["inqryBgnDt"])
        self.assertEqual("202608262359", query["inqryEndDt"])

    def test_recent_mode_contains_today_and_defaults_to_21_days(self) -> None:
        start, end = COLLECT.resolve_window(None, None, today=date(2026, 8, 29))
        self.assertEqual(date(2026, 8, 9), start)
        self.assertEqual(date(2026, 8, 30), end)


class CollectionTests(unittest.TestCase):
    def test_saved_query_does_not_contain_service_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fetcher, _pages, _artifact = collect_fixture(
                Path(directory),
                {1: payload([source_item("P1")], page=1, total=1)},
            )
            self.assertNotIn("serviceKey", fetcher.queries[0])
            saved = json.loads(
                (Path(directory) / "page-00001.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("serviceKey", saved["query"])
            self.assertEqual(
                COLLECT.query_for_window(FROM_DATE, TO_DATE, 1, 2),
                saved["query"],
            )

    def test_pagination_runs_until_total_count(self) -> None:
        responses = {
            1: payload(
                [source_item("P1"), source_item("P2")], page=1, total=3
            ),
            2: payload([source_item("P3")], page=2, total=3),
        }
        with tempfile.TemporaryDirectory() as directory:
            fetcher, pages, artifact = collect_fixture(
                Path(directory), responses
            )
            self.assertEqual([1, 2], [int(query["pageNo"]) for query in fetcher.queries])
            self.assertEqual(2, len(pages))
            self.assertEqual(3, artifact["counts"]["source_total"])
            self.assertEqual(3, artifact["counts"]["total"])

    def test_out_of_scope_rows_are_excluded_and_counted(self) -> None:
        responses = {
            1: payload(
                [
                    source_item("P1", business_division="일반용역"),
                    source_item("P2", business_division="물품"),
                ],
                page=1,
                total=2,
            )
        }
        with tempfile.TemporaryDirectory() as directory:
            _fetcher, _pages, artifact = collect_fixture(
                Path(directory), responses
            )
        self.assertEqual(1, artifact["counts"]["total"])
        self.assertEqual(1, artifact["counts"]["excluded_out_of_scope"])
        self.assertEqual(1, artifact["counts"]["excluded_business_divisions"])
        self.assertEqual(
            ["기술용역", "일반용역"],
            artifact["metadata"]["business_divisions"],
        )

    def test_page_safety_limit_emits_the_same_style_warning(self) -> None:
        responses = {
            1: payload([source_item("P1")], page=1, total=2, rows=1),
            2: payload([source_item("P2")], page=2, total=2, rows=1),
        }
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher(responses)
            warnings: list[str] = []
            with mock.patch.object(COLLECT, "MAX_PAGES", 1):
                pages = COLLECT.collect_pages(
                    Path(directory), FROM_DATE, TO_DATE, 1, fetcher, warnings
                )
            self.assertEqual(1, len(pages))
            self.assertEqual(
                ["order_plan: 안전 상한 1페이지에서 중단했습니다."],
                warnings,
            )


class NormalizationTests(unittest.TestCase):
    def test_sw_status_is_null_and_unknown_and_empty_rcrit_field_is_retained(self) -> None:
        raw_item = source_item("P1", rcrit="")
        with tempfile.TemporaryDirectory() as directory:
            _fetcher, _pages, artifact = collect_fixture(
                Path(directory),
                {1: payload([raw_item], page=1, total=1)},
            )
        plan = artifact["order_plans"][0]
        self.assertIsNone(plan["sw_business_status"])
        self.assertIn("sw_business_status", plan["unknown_fields"])
        self.assertIn("rcrit_rgst_no", plan)
        self.assertIsNone(plan["rcrit_rgst_no"])
        self.assertEqual("2027", plan["planned_order_year"])
        self.assertEqual("2027-09", plan["planned_order_month"])
        self.assertEqual(123456789, plan["budget_amount"])
        self.assertEqual(64, len(plan["source_sha256"]))
        self.assertEqual("raw/page-00001.json", plan["raw_source"])
        self.assertEqual(raw_item["bidNtceNoList"], plan["bid_ntice_no_list"])

    def test_reclassify_uses_raw_pages_and_reproduces_the_same_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory) / "raw"
            _fetcher, pages, artifact = collect_fixture(
                raw_dir,
                {1: payload([source_item("P1")], page=1, total=1)},
            )
            with mock.patch.object(
                COLLECT,
                "request_json",
                side_effect=AssertionError("reclassification must not call the API"),
            ):
                records, warnings = COLLECT.reclassify_source(
                    raw_dir=raw_dir,
                    from_date=FROM_DATE,
                    to_date=TO_DATE,
                )
        self.assertEqual([], warnings)
        self.assertEqual(artifact["order_plans"], records)
        self.assertEqual(pages[0][1]["query"], COLLECT.query_for_window(FROM_DATE, TO_DATE, 1, 2))


def _rewrite_raw_query(raw_dir: Path, page: int, *, legacy: bool) -> None:
    path = raw_dir / f"page-{page:05d}.json"
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    wrapper["query"] = COLLECT.query_for_window(
        FROM_DATE,
        TO_DATE,
        page,
        int(wrapper["query"]["numOfRows"]),
        legacy_order_month_scope=legacy,
    )
    path.write_text(json.dumps(wrapper, ensure_ascii=False), encoding="utf-8")


class OrderMonthSpanTests(unittest.TestCase):
    """The 2026-11-20 PPSSrch change: the full span is rejected, omission works."""

    def test_new_runs_record_the_query_without_the_span_and_keep_the_population_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fetcher, pages, artifact = collect_fixture(
                Path(directory) / "raw",
                {1: payload([source_item("P1")], page=1, total=1)},
            )
        self.assertNotIn("orderBgnYm", fetcher.queries[0])
        self.assertNotIn("orderEndYm", fetcher.queries[0])
        self.assertNotIn("orderBgnYm", pages[0][1]["query"])
        # The artifact contract (v1) is unchanged: the population is still every
        # order month.  What was actually sent is in the raw page query.
        self.assertEqual(
            {"from": "200412", "to": "999912"},
            artifact["metadata"]["order_month_scope"],
        )

    def test_raw_pages_collected_with_the_legacy_span_still_reclassify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory) / "raw"
            _fetcher, _pages, artifact = collect_fixture(
                raw_dir,
                {
                    1: payload([source_item("P1"), source_item("P2")], page=1, total=3),
                    2: payload([source_item("P3")], page=2, total=3),
                },
            )
            _rewrite_raw_query(raw_dir, 1, legacy=True)
            _rewrite_raw_query(raw_dir, 2, legacy=True)
            records, warnings = COLLECT.reclassify_source(
                raw_dir=raw_dir, from_date=FROM_DATE, to_date=TO_DATE
            )
        self.assertEqual([], warnings)
        self.assertEqual(artifact["order_plans"], records)

    def test_one_run_cannot_mix_both_query_forms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory) / "raw"
            collect_fixture(
                raw_dir,
                {
                    1: payload([source_item("P1"), source_item("P2")], page=1, total=3),
                    2: payload([source_item("P3")], page=2, total=3),
                },
            )
            _rewrite_raw_query(raw_dir, 1, legacy=True)
            with self.assertRaises(COLLECT.CollectionError) as caught:
                COLLECT.reclassify_source(
                    raw_dir=raw_dir, from_date=FROM_DATE, to_date=TO_DATE
                )
        self.assertEqual("raw_query_mismatch", caught.exception.code)

    def test_a_narrowed_span_in_a_raw_query_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory) / "raw"
            collect_fixture(raw_dir, {1: payload([source_item("P1")], page=1, total=1)})
            path = raw_dir / "page-00001.json"
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            wrapper["query"]["orderBgnYm"] = "202611"
            wrapper["query"]["orderEndYm"] = "202612"
            path.write_text(json.dumps(wrapper, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(COLLECT.CollectionError) as caught:
                COLLECT.reclassify_source(
                    raw_dir=raw_dir, from_date=FROM_DATE, to_date=TO_DATE
                )
        self.assertEqual("raw_query_mismatch", caught.exception.code)


# The reply PPSSrch gave on 2026-11-20 for the 200412..999912 span: no
# ``response`` key, the error wrapped under the provider's class name.
G2B_RANGE_ERROR = {
    "nkoneps.com.response.ResponseError": {
        "header": {"resultCode": "07", "resultMsg": "입력범위값 초과 에러"}
    }
}


class UpstreamErrorTests(unittest.TestCase):
    def test_a_wrapped_provider_error_is_a_result_error_with_its_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory) / "raw"
            fetcher = FakeFetcher({1: G2B_RANGE_ERROR})
            with self.assertRaises(COLLECT.CollectionError) as caught:
                COLLECT.collect_pages(raw_dir, FROM_DATE, TO_DATE, 2, fetcher, [])
            self.assertEqual([], sorted(raw_dir.glob("page-*.json")))
        self.assertEqual("g2b_result_error", caught.exception.code)
        self.assertEqual("07", caught.exception.upstream_code)

    def test_a_non_zero_code_in_a_normal_envelope_keeps_its_code(self) -> None:
        reply = {"response": {"header": {"resultCode": "22", "resultMsg": "한도 초과"}}}
        with self.assertRaises(COLLECT.CollectionError) as caught:
            COLLECT._extract_page(reply)
        self.assertEqual("g2b_result_error", caught.exception.code)
        self.assertEqual("22", caught.exception.upstream_code)

    def test_cli_reports_the_code_but_never_the_provider_message(self) -> None:
        class RejectingFetcher:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def fetch(self, _query: dict[str, str]) -> tuple[dict, int]:
                return G2B_RANGE_ERROR, 1

        import contextlib
        import io

        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "run"
            with mock.patch.object(COLLECT, "G2BFetcher", RejectingFetcher), mock.patch.object(
                COLLECT, "get_service_key", return_value="not-a-real-key"
            ), contextlib.redirect_stderr(stderr):
                code = COLLECT.main(
                    [
                        "--from-date",
                        "2026-08-24",
                        "--to-date",
                        "2026-08-27",
                        "--output-dir",
                        str(output_dir),
                    ]
                )
            self.assertFalse((output_dir / "collected-order-plans.json").exists())
        self.assertEqual(2, code)
        self.assertEqual(
            {"status": "failed", "error_code": "g2b_result_error", "g2b_result_code": "07"},
            json.loads(stderr.getvalue()),
        )
        self.assertNotIn("입력범위", stderr.getvalue())

    def test_an_unusual_code_is_not_forwarded_verbatim(self) -> None:
        reply = {"X": {"header": {"resultCode": "<script>alert(1)</script>"}}}
        with self.assertRaises(COLLECT.CollectionError) as caught:
            COLLECT._extract_page(reply)
        self.assertEqual("unknown", caught.exception.upstream_code)


if __name__ == "__main__":
    unittest.main()
