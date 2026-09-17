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
    def test_query_keeps_the_full_order_month_scope(self) -> None:
        query = COLLECT.query_for_window(FROM_DATE, TO_DATE, 1, 500)
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


if __name__ == "__main__":
    unittest.main()
