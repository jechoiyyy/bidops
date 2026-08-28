from __future__ import annotations

import unittest
from datetime import date

from helpers import FIXED_TIME

from collect import (  # noqa: E402
    ENDPOINT_ID,
    ORDER_SCOPE_FROM_MONTH,
    ORDER_SCOPE_TO_MONTH,
    extract_page,
    normalize_items,
    query_for_window,
    raw_aggregate_hash,
    validate_raw_queries,
)
from common import RAW_PAGE_SCHEMA, ExperimentError, digest_json  # noqa: E402


def source_item(
    plan_id: str,
    published_at: str = "2026-08-24 00:00:00",
    business_division: str = "일반용역",
) -> dict:
    return {
        "orderPlanUntyNo": plan_id,
        "bizNm": f"사업 {plan_id}",
        "bsnsDivNm": business_division,
        "bsnsDivCd": "01",
        "bsnsTyNm": "신규(단기)",
        "bsnsTyCd": "신120001",
        "nticeDt": published_at,
        "chgDt": "",
        "orderYear": "2026",
        "orderMnth": "09",
        "sumOrderAmt": "",
        "orderContrctAmt": "1000",
        "orderInsttCd": "A1",
        "orderInsttNm": "기관",
        "prcrmntMethd": "자체조달",
        "cntrctMthdNm": "일반경쟁",
    }


def payload(items: list[dict], page: int = 1, total: int | None = None) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {
                "totalCount": str(len(items) if total is None else total),
                "pageNo": str(page),
                "numOfRows": "500",
                "items": items,
            },
        }
    }


def wrapper(items: list[dict]) -> dict:
    source = payload(items)
    return {
        "schema_version": RAW_PAGE_SCHEMA,
        "endpoint_id": "test",
        "query": {"pageNo": "1"},
        "page_no": 1,
        "request_attempts": 1,
        "collected_at": FIXED_TIME,
        "payload_sha256": digest_json(source),
        "payload": source,
    }


class CollectionContractTests(unittest.TestCase):
    def test_publication_window_does_not_narrow_order_month_scope(self) -> None:
        query = query_for_window(date(2026, 8, 24), date(2026, 8, 27), 1, 500)
        self.assertEqual(query["orderBgnYm"], ORDER_SCOPE_FROM_MONTH)
        self.assertEqual(query["orderEndYm"], ORDER_SCOPE_TO_MONTH)
        self.assertEqual(query["inqryBgnDt"], "202608240000")
        self.assertEqual(query["inqryEndDt"], "202608262359")

    def test_replayed_raw_query_must_match_exact_population_scope(self) -> None:
        wrapped = wrapper([source_item("P1")])
        wrapped["endpoint_id"] = ENDPOINT_ID
        wrapped["query"] = query_for_window(date(2026, 8, 24), date(2026, 8, 27), 1, 500)
        validate_raw_queries([("page-00001.json", wrapped)], date(2026, 8, 24), date(2026, 8, 27))
        wrapped["query"]["orderBgnYm"] = "202608"
        with self.assertRaises(ExperimentError) as caught:
            validate_raw_queries(
                [("page-00001.json", wrapped)], date(2026, 8, 24), date(2026, 8, 27)
            )
        self.assertEqual(caught.exception.code, "raw_query_mismatch")

    def test_extracts_current_list_response_shape(self) -> None:
        items, total, page, rows = extract_page(payload([source_item("P1")]))
        self.assertEqual(len(items), 1)
        self.assertEqual((total, page, rows), (1, 1, 500))

    def test_normalization_preserves_unknown_as_null(self) -> None:
        wrapped = wrapper([source_item("P1")])
        raw_hash = raw_aggregate_hash([wrapped])
        population = normalize_items(
            [("page-00001.json", wrapped)],
            "run-1",
            __import__("datetime").date(2026, 8, 24),
            __import__("datetime").date(2026, 8, 27),
            FIXED_TIME,
            raw_hash,
        )
        item = population["items"][0]
        self.assertIsNone(item["budget_amount"])
        self.assertIsNone(item["sw_business_status"])
        self.assertIn("budget_amount", item["unknown_fields"])

    def test_duplicate_plan_id_is_rejected(self) -> None:
        wrapped = wrapper([source_item("P1"), source_item("P1")])
        with self.assertRaises(ExperimentError) as caught:
            normalize_items(
                [("page-00001.json", wrapped)],
                "run-1",
                __import__("datetime").date(2026, 8, 24),
                __import__("datetime").date(2026, 8, 27),
                FIXED_TIME,
                raw_aggregate_hash([wrapped]),
            )
        self.assertEqual(caught.exception.code, "duplicate_plan_id")

    def test_end_boundary_is_exclusive(self) -> None:
        wrapped = wrapper([source_item("P1", "2026-08-27 00:00:00")])
        with self.assertRaises(ExperimentError) as caught:
            normalize_items(
                [("page-00001.json", wrapped)],
                "run-1",
                __import__("datetime").date(2026, 8, 24),
                __import__("datetime").date(2026, 8, 27),
                FIXED_TIME,
                raw_aggregate_hash([wrapped]),
            )
        self.assertEqual(caught.exception.code, "window_boundary_mismatch")

    def test_non_service_scope_is_rejected(self) -> None:
        wrapped = wrapper([source_item("P1", business_division="물품")])
        with self.assertRaises(ExperimentError) as caught:
            normalize_items(
                [("page-00001.json", wrapped)],
                "run-1",
                __import__("datetime").date(2026, 8, 24),
                __import__("datetime").date(2026, 8, 27),
                FIXED_TIME,
                raw_aggregate_hash([wrapped]),
            )
        self.assertEqual(caught.exception.code, "business_scope_mismatch")


if __name__ == "__main__":
    unittest.main()
