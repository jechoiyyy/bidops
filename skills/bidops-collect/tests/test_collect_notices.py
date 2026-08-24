#!/usr/bin/env python3
"""Retrieval, provenance, and field-extraction tests for the BidOps collector."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/collect_notices.py"
SPEC = importlib.util.spec_from_file_location("bidops_collect_notices", SCRIPT)
assert SPEC and SPEC.loader
COLLECT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECT)


def labels_of(signals, axis=None):
    return {
        signal["label"]
        for signal in signals
        if axis is None or signal["axis"] == axis
    }


def axes_of(signals):
    return {signal["axis"] for signal in signals}


class ConceptMatchingTests(unittest.TestCase):
    def test_ai_agent_case_width_and_separator_variants_match(self) -> None:
        for variant in ("AI Agent", "ai agent", "Ai-Agent", "ＡＩ　Ａｇｅｎｔ"):
            with self.subTest(variant=variant):
                signals = COLLECT.focus_signals(
                    (("bidNtceNm", "title", f"{variant} 기반 업무자동화"),)
                )
                self.assertIn("AI Agent", labels_of(signals, "AI/데이터"))

    def test_ontology_korean_and_english_variants_match(self) -> None:
        for variant in ("온톨로지", "ontology", "ONTOLOGIES", "Semantic-Web"):
            with self.subTest(variant=variant):
                signals = COLLECT.focus_signals(
                    (("bidNtceNm", "title", f"{variant} 기반 지식 서비스"),)
                )
                self.assertIn("온톨로지", labels_of(signals, "AI/데이터"))

    def test_short_ai_alias_does_not_match_inside_unrelated_word(self) -> None:
        signals = COLLECT.focus_signals((("bidNtceNm", "title", "training 운영 용역"),))
        self.assertNotIn("AI/데이터", axes_of(signals))

    def test_maintenance_requires_digital_context(self) -> None:
        facility = COLLECT.focus_signals(
            (("bidNtceNm", "title", "도로 포장 유지보수 폐기물처리 용역"),)
        )
        software = COLLECT.focus_signals(
            (("bidNtceNm", "title", "상황통제시스템 유지보수 용역"),)
        )
        self.assertNotIn("공공 SI·통합관리", axes_of(facility))
        self.assertIn("유지관리", labels_of(software, "공공 SI·통합관리"))

    def test_concept_is_not_formed_across_a_field_boundary(self) -> None:
        """The tail of one field and the head of the next never form a phrase."""
        signals = COLLECT.focus_signals((
            ("bidNtceNm", "title", "통합 정보"),
            ("pubPrcrmntMidClsfcNm", "classification", "시스템 구축"),
        ))
        self.assertNotIn("정보시스템", labels_of(signals))
        self.assertIn("시스템 구축", labels_of(signals))


class SignalProvenanceTests(unittest.TestCase):
    def test_title_signal_records_its_field_and_alias(self) -> None:
        notice = COLLECT.normalize_bid(
            {
                "bidNtceNo": "T-1",
                "bidNtceOrd": "00",
                "bidNtceNm": "빅데이터 플랫폼 구축 용역",
                "pubPrcrmntMidClsfcNm": "SW 및 시스템 개발",
            },
            "fixture",
        )
        signal = next(
            item for item in notice["focus_matches"] if item["label"] == "빅데이터"
        )
        self.assertEqual("bidNtceNm", signal["matched_field"])
        self.assertEqual("title", signal["field_kind"])
        self.assertEqual("빅데이터", signal["matched_text"])
        self.assertIn("focus_title", notice["candidate_sources"])

    def test_classification_only_match_is_marked_as_classification(self) -> None:
        """A label attached to every service notice is not a title concept."""
        notice = COLLECT.normalize_bid(
            {
                "bidNtceNo": "T-2",
                "bidNtceOrd": "00",
                "bidNtceNm": "시니어 특화 스피드온 UX·UI 혁신 컨설팅 용역",
                "pubPrcrmntClsfcNm": "정보시스템 감리",
            },
            "fixture",
        )
        kinds = {signal["field_kind"] for signal in notice["focus_matches"]}
        self.assertEqual({"classification"}, kinds)
        self.assertEqual(["focus_classification"], notice["candidate_sources"])
        self.assertEqual("candidate_pool", notice["collection_bucket"])


class PerformanceRetrievalTests(unittest.TestCase):
    def test_performance_similarity_can_create_candidate_without_focus_keyword(self) -> None:
        notice = COLLECT.normalize_bid(
            {
                "bidNtceNo": "TEST-1",
                "bidNtceOrd": "00",
                "bidNtceNm": "연구장비 공동활용 예약관리 통합 개선",
            },
            "fixture",
        )
        self.assertEqual([], notice["focus_matches"])
        self.assertTrue(notice["performance_matches"])
        self.assertEqual("candidate_pool", notice["collection_bucket"])
        self.assertEqual(["performance_similarity"], notice["candidate_sources"])

    def test_irrelevant_facility_work_remains_in_audit_pool(self) -> None:
        notice = COLLECT.normalize_bid(
            {
                "bidNtceNo": "TEST-2",
                "bidNtceOrd": "00",
                "bidNtceNm": "청사 조경 및 수목 관리 용역",
            },
            "fixture",
        )
        self.assertEqual([], notice["focus_matches"])
        self.assertEqual([], notice["performance_matches"])
        self.assertEqual("audit_pool", notice["collection_bucket"])

    def test_best_similarity_is_kept_even_when_below_threshold(self) -> None:
        """Near misses must stay measurable so the audit sample can target them."""
        matches, score = COLLECT.performance_signals("연구장비 공동활용 예약관리 통합 개선")
        self.assertTrue(matches)
        self.assertGreaterEqual(score, COLLECT.PERFORMANCE_THRESHOLD)
        _, empty_score = COLLECT.performance_signals("청사 조경 및 수목 관리 용역")
        self.assertEqual(0.0, empty_score)

    def test_all_pdf_performance_titles_are_preserved_as_reference_data(self) -> None:
        lines = [
            line
            for line in COLLECT.PERFORMANCE_REFERENCE_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(130, len(lines))


class FieldExtractionTests(unittest.TestCase):
    RECORD = {
        "bidNtceNo": "R26BK00000001",
        "bidNtceOrd": "000",
        "bidNtceNm": "통합관제시스템 고도화 용역",
        "dminsttNm": "테스트청",
        "bidNtceDt": "202608180900",
        "bidClseDt": "202608281800",
        "asignBdgtAmt": "300000000",
        "presmptPrce": "272727272",
        "cntrctCnclsMthdNm": "협상에 의한 계약",
        "pubPrcrmntLrgClsfcNm": "ICT 서비스",
        "pubPrcrmntMidClsfcNm": "SW 및 시스템 개발",
        "pubPrcrmntClsfcNm": "응용소프트웨어 개발",
        "pubPrcrmntClsfcNo": "81112002",
        "rgnLmtBidLocplcJdgmBssNm": "본사또는참여지사소재지",
        "jntcontrctDutyRgnNm1": "대구광역시",
        "jntcontrctDutyRgnNm2": "경상북도",
        "rgnDutyJntcontrctRt": "40",
        "cmmnSpldmdCorpRgnLmtYn": "Y",
        "bfSpecRgstNo": "20260800123",
        "reNtceYn": "Y",
        "chgDt": "202608200930",
        "chgNtceRsn": "과업내용서 정정",
        "untyNtceNo": "20260812345",
        "befBidBbancNo": "R26BK00000000",
        "arsltCmptYn": "Y",
        "pqEvalYn": "N",
        "tpEvalYn": "Y",
        "techAbltEvlRt": "90",
        "infoBizYn": "Y",
        "indstrytyLmtYn": "Y",
        "bidPrtcptLmtYn": "Y",
        "sucsfbidMthdNm": "협상에의한계약",
        "srvceDivNm": "일반용역",
    }

    def test_region_limit_comes_from_the_regional_judgement_basis(self) -> None:
        notice = COLLECT.normalize_bid(dict(self.RECORD), "fixture")
        region = notice["region_limit"]
        self.assertEqual("본사또는참여지사소재지", region["basis"])
        self.assertEqual(["대구광역시", "경상북도"], region["joint_contract_regions"])
        self.assertEqual("40", region["joint_contract_rate"])
        self.assertEqual("Y", region["regional_joint_contract_limit"])

    def test_procurement_classification_is_preserved(self) -> None:
        notice = COLLECT.normalize_bid(dict(self.RECORD), "fixture")
        self.assertEqual(
            {
                "large": "ICT 서비스",
                "middle": "SW 및 시스템 개발",
                "detail": "응용소프트웨어 개발",
                "code": "81112002",
            },
            notice["procurement_class"],
        )

    def test_lifecycle_fields_support_prespec_and_rebid_tracking(self) -> None:
        notice = COLLECT.normalize_bid(dict(self.RECORD), "fixture")
        lifecycle = notice["lifecycle"]
        self.assertEqual("20260800123", lifecycle["pre_spec_no"])
        self.assertEqual("Y", lifecycle["re_notice"])
        self.assertEqual("2026-08-20T09:30:00+09:00", lifecycle["changed_at"])
        self.assertEqual("과업내용서 정정", lifecycle["change_reason"])
        self.assertEqual("R26BK00000000", lifecycle["previous_failed_notice_no"])

    def test_qualification_flags_carry_eligibility_signals(self) -> None:
        notice = COLLECT.normalize_bid(dict(self.RECORD), "fixture")
        flags = notice["qualification_flags"]
        self.assertEqual("Y", flags["performance_restricted_competition"])
        self.assertEqual("Y", flags["technical_evaluation"])
        self.assertEqual("90", flags["technical_evaluation_rate"])
        self.assertEqual("Y", flags["information_business"])
        self.assertEqual("Y", flags["industry_limited"])


class PrespecNormalizationTests(unittest.TestCase):
    def test_title_prefers_the_business_name_over_the_product_class(self) -> None:
        notice = COLLECT.normalize_prespec(
            {
                "bfSpecRgstNo": "20260800999",
                "bfSpecNm": "지식그래프 기반 행정정보 검색 고도화",
                "prdctClsfcNoNm": "응용소프트웨어 개발서비스",
                "asignBdgtAmt": "150000000",
            },
            "fixture",
        )
        self.assertEqual("지식그래프 기반 행정정보 검색 고도화", notice["title"])
        self.assertIn("지식그래프", labels_of(notice["focus_matches"]))

    def test_budget_amount_is_never_matched_as_description_text(self) -> None:
        notice = COLLECT.normalize_prespec(
            {
                "bfSpecRgstNo": "20260800998",
                "bfSpecNm": "청사 조경 관리",
                "asignBdgtAmt": "150000000",
            },
            "fixture",
        )
        matched_fields = {
            signal["matched_field"] for signal in notice["focus_matches"]
        }
        self.assertNotIn("asignBdgtAmt", matched_fields)
        self.assertEqual("150000000", notice["budget"])


class ReclassifyTests(unittest.TestCase):
    def test_preserved_pages_are_reclassified_without_calling_the_api(self) -> None:
        payload = {
            "response": {
                "header": {"resultCode": "00"},
                "body": {
                    "totalCount": 1,
                    "items": [
                        {
                            "bidNtceNo": "RAW-1",
                            "bidNtceOrd": "00",
                            "bidNtceNm": "빅데이터 분석 플랫폼 구축",
                        }
                    ],
                },
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory)
            (raw_dir / "bid-page-001.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            records, warnings = COLLECT.reclassify_source(source="bid", raw_dir=raw_dir)
        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        self.assertEqual("bid:RAW-1:00", records[0]["notice_id"])
        self.assertIn("빅데이터", labels_of(records[0]["focus_matches"]))

    def test_missing_pages_are_reported_as_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            records, warnings = COLLECT.reclassify_source(
                source="prespec", raw_dir=Path(directory)
            )
        self.assertEqual([], records)
        self.assertEqual(1, len(warnings))


if __name__ == "__main__":
    unittest.main()
