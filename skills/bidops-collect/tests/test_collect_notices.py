#!/usr/bin/env python3
"""Retrieval, provenance, and field-extraction tests for the BidOps collector."""

from __future__ import annotations

import importlib.util
import argparse
import hashlib
import io
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


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
        "orderPlanUntyNo": "R26DD20999999",
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
        self.assertEqual("R26DD20999999", lifecycle["order_plan_no"])

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

    # 측정된 PPSSrch 응답은 규격서 URL을 specDocFileUrl1~5로만 노출한다.
    # 650건 중 586건이 최소 하나를 갖고, 나머지는 원문에 URL이 없다.
    def test_spec_document_urls_become_attachments(self) -> None:
        notice = COLLECT.normalize_prespec(
            {
                "bfSpecRgstNo": "20260800100",
                "bfSpecNm": "행정정보 통합 검색 고도화",
                "specDocFileUrl1": "https://example.g2b/spec-1.hwp",
                "specDocFileUrl3": "https://example.g2b/spec-3.pdf",
            },
            "fixture",
        )
        urls = [item["url"] for item in notice["attachments"]]
        self.assertEqual(
            ["https://example.g2b/spec-1.hwp", "https://example.g2b/spec-3.pdf"], urls
        )
        self.assertNotIn("attachments", notice["unknown_fields"])

    def test_missing_spec_document_urls_stay_unknown_rather_than_silently_empty(self) -> None:
        notice = COLLECT.normalize_prespec(
            {"bfSpecRgstNo": "20260800101", "bfSpecNm": "첨부 없는 사전규격"},
            "fixture",
        )
        self.assertEqual([], notice["attachments"])
        self.assertIn("attachments", notice["unknown_fields"])

    def test_sw_flag_business_division_and_bid_notice_list_are_preserved(self) -> None:
        notice = COLLECT.normalize_prespec(
            {
                "bfSpecRgstNo": "20260800102",
                "bfSpecNm": "통합관제 시스템 구축",
                "swBizObjYn": "Y",
                "bsnsDivNm": "일반용역",
                "bidNtceNoList": "R26BK01698278000",
            },
            "fixture",
        )
        self.assertEqual("Y", notice["qualification_flags"]["sw_business_status"])
        self.assertEqual("일반용역", notice["qualification_flags"]["business_division"])
        self.assertEqual("R26BK01698278000", notice["lifecycle"]["bid_ntice_no_list"])

    # ADR-0024: swBizObjYn으로 걸러 내지 않는다. 650건 중 Y는 55건(8.5%)뿐이라
    # 필터를 켜면 91.5%가 사라진다. 표시 값으로만 쓴다.
    def test_non_software_prespec_is_normalized_and_not_dropped(self) -> None:
        notice = COLLECT.normalize_prespec(
            {
                "bfSpecRgstNo": "20260800103",
                "bfSpecNm": "SW 대상이 아닌 용역",
                "swBizObjYn": "N",
                "bsnsDivNm": "기술용역",
            },
            "fixture",
        )
        self.assertEqual("pre:20260800103", notice["notice_id"])
        self.assertEqual("N", notice["qualification_flags"]["sw_business_status"])

    # 응답에 없는 필드를 읽던 경로가 사라졌다. specDocFileUrl(번호 없음)과
    # bfSpecDtlUrl은 PPSSrch 응답에 존재하지 않으므로 url 자리에 넣지 않는다.
    def test_url_is_not_filled_from_fields_absent_in_the_response(self) -> None:
        notice = COLLECT.normalize_prespec(
            {
                "bfSpecRgstNo": "20260800104",
                "bfSpecNm": "존재하지 않는 필드 확인",
                "specDocFileUrl": "https://example.g2b/legacy.hwp",
                "bfSpecDtlUrl": "https://example.g2b/legacy-detail",
            },
            "fixture",
        )
        self.assertIsNone(notice["url"])

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


class ImmutableCollectionTests(unittest.TestCase):
    def args(self, root: Path, *, output: Path | None = None, source: Path | None = None):
        return argparse.Namespace(
            from_date=date(2026, 9, 1), to_date=date(2026, 9, 2),
            output_dir=output or root / "new-run", allowed_root=root, from_raw=source,
            skip_bids=False, skip_prespecs=True, rows=500, timeout=1,
        )

    def payload(self, *, total=1):
        return {"response": {"header": {"resultCode": "00"}, "body": {
            "totalCount": total, "items": [{"bidNtceNo": "RAW-1", "bidNtceOrd": "00",
                                            "bidNtceNm": "통합 플랫폼 구축"}],
        }}}

    def invoke(self, args):
        with patch.object(COLLECT, "parse_args", return_value=args), patch("sys.stdout", new=io.StringIO()):
            return COLLECT.main()

    def test_existing_raw_page_is_rejected_before_http(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory)
            page = raw_dir / "prespec-page-001.json"
            original = b'{"original": true}'
            page.write_bytes(original)
            with patch.object(COLLECT, "request_json", return_value={}) as request:
                with self.assertRaises(RuntimeError):
                    COLLECT.collect_source(
                        source="prespec", endpoint="https://example.invalid", service_key="",
                        from_date=date(2026, 9, 1), to_date=date(2026, 9, 1),
                        rows=500, timeout=1, raw_dir=raw_dir,
                    )
            request.assert_not_called()
            self.assertEqual(original, page.read_bytes())

    def test_existing_empty_output_is_rejected_before_key_loading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing"
            output.mkdir()
            args = argparse.Namespace(
                from_date=date(2026, 9, 1), to_date=date(2026, 9, 1), output_dir=output,
                allowed_root=Path(directory), from_raw=None, skip_bids=False,
                skip_prespecs=True, rows=500, timeout=1,
            )
            with patch.object(COLLECT, "parse_args", return_value=args), patch.object(
                COLLECT, "get_service_key", side_effect=AssertionError("key loaded")
            ) as key:
                with self.assertRaises(RuntimeError):
                    COLLECT.main()
            key.assert_not_called()
            self.assertEqual([], list(output.iterdir()))

    def test_unsafe_output_paths_are_rejected_without_key_or_http(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "existing-file").write_bytes(b"preserved")
            (root / "alias").symlink_to(root, target_is_directory=True)
            (root / "broken").symlink_to(root / "absent")
            paths = [root / "existing-file", root / "alias" / "new", root / "broken",
                     root / ".." / "escape", root.parent / "outside-run"]
            for output in paths:
                with self.subTest(output=output.name), patch.object(COLLECT, "get_service_key") as key, patch.object(
                    COLLECT, "request_json"
                ) as request:
                    with self.assertRaises(RuntimeError):
                        self.invoke(self.args(root, output=output))
                    key.assert_not_called()
                    request.assert_not_called()
            self.assertEqual(b"preserved", (root / "existing-file").read_bytes())

    def test_reclassification_copies_bytes_and_records_origin_hash_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original" / "raw"
            source.mkdir(parents=True)
            data = json.dumps(self.payload(), ensure_ascii=False).encode("utf-8")
            (source / "bid-page-001.json").write_bytes(data)
            args = self.args(root, source=source)
            with patch.object(COLLECT, "get_service_key") as key, patch.object(COLLECT, "request_json") as request:
                self.assertEqual(0, self.invoke(args))
            key.assert_not_called()
            request.assert_not_called()
            copied = args.output_dir / "raw" / "bid-page-001.json"
            self.assertFalse(copied.is_symlink())
            self.assertNotEqual(copied.stat().st_ino, (source / copied.name).stat().st_ino)
            self.assertEqual(data, copied.read_bytes())
            self.assertEqual(data, (source / copied.name).read_bytes())
            provenance = json.loads((args.output_dir / "collection-provenance.json").read_text())
            self.assertEqual("bidops.collection-provenance.v1", provenance["schema_version"])
            self.assertEqual("original/raw", provenance["source_raw"])
            self.assertTrue(provenance["complete"])
            self.assertEqual([{"path": "raw/bid-page-001.json", "source_path": "original/raw/bid-page-001.json",
                               "sha256": hashlib.sha256(data).hexdigest()}], provenance["raw_pages"])
            result = json.loads((args.output_dir / "collected-notices.json").read_text())
            self.assertEqual("bidops.collected.v2", result["schema_version"])
            self.assertEqual({"from": "2026-09-01", "to": "2026-09-02", "timezone": "Asia/Seoul"}, result["source_window"])
            self.assertEqual(str(copied), result["notices"][0]["raw_source"])

    def test_unsafe_raw_sources_are_rejected_without_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw"
            source.mkdir()
            page = source / "bid-page-001.json"
            for kind in ("symlink", "fifo", "directory"):
                with self.subTest(kind=kind):
                    if kind == "symlink":
                        page.symlink_to(root / "absent")
                    elif kind == "fifo":
                        os.mkfifo(page)
                    else:
                        page.mkdir()
                    args = self.args(root, source=source)
                    with self.assertRaises(RuntimeError):
                        self.invoke(args)
                    self.assertFalse(args.output_dir.exists())
                    page.rmdir() if kind == "directory" else page.unlink()
            alias = root / "raw-alias"
            alias.symlink_to(source, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                self.invoke(self.args(root, source=alias))

    def test_invalid_raw_json_is_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw"
            source.mkdir()
            page = source / "bid-page-001.json"
            page.write_bytes(b'{"response": {"body": {}}}')
            args = self.args(root, source=source)
            with self.assertRaisesRegex(RuntimeError, "collection_raw_invalid"):
                self.invoke(args)
            self.assertFalse((args.output_dir / "collected-notices.json").exists())
            self.assertEqual(b'{"response": {"body": {}}}', page.read_bytes())
            self.assertFalse(json.loads((args.output_dir / "collection-provenance.json").read_text())["complete"])

    def test_partial_http_failure_keeps_raw_and_inclusive_dates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.args(root)
            with patch.object(COLLECT, "get_service_key", return_value="fake"), patch.object(
                COLLECT, "request_json", side_effect=[self.payload(total=2), RuntimeError("offline")]
            ) as request:
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    self.invoke(args)
            self.assertEqual("202609010000", request.call_args_list[0].args[1]["inqryBgnDt"])
            self.assertEqual("202609022359", request.call_args_list[0].args[1]["inqryEndDt"])
            self.assertTrue((args.output_dir / "raw/bid-page-001.json").is_file())
            self.assertFalse((args.output_dir / "collected-notices.json").exists())
            self.assertFalse(json.loads((args.output_dir / "collection-provenance.json").read_text())["complete"])
            replay = self.args(root, output=root / "replay", source=args.output_dir / "raw")
            self.assertEqual(1, self.invoke(replay))
            result = json.loads((replay.output_dir / "collected-notices.json").read_text())
            self.assertTrue(result["warnings"])
            self.assertFalse(json.loads((replay.output_dir / "collection-provenance.json").read_text())["complete"])

    def test_final_write_failure_never_marks_provenance_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.args(root)
            original_write = COLLECT.write_json_new
            def fail_final(path, payload):
                if path.name == "collected-notices.json":
                    raise OSError("disk_write_failed")
                return original_write(path, payload)
            with patch.object(COLLECT, "get_service_key", return_value="fake"), patch.object(
                COLLECT, "request_json", return_value=self.payload()
            ), patch.object(COLLECT, "write_json_new", side_effect=fail_final):
                with self.assertRaisesRegex(OSError, "disk_write_failed"):
                    self.invoke(args)
            provenance = json.loads((args.output_dir / "collection-provenance.json").read_text())
            self.assertFalse(provenance["complete"])
            self.assertTrue((args.output_dir / "raw" / "bid-page-001.json").exists())
            self.assertFalse((args.output_dir / "collected-notices.json").exists())

    def test_exclusive_file_creation_preserves_files_and_serializes_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "collected-notices.json"
            with self.assertRaises(TypeError):
                COLLECT.write_json_new(path, {"invalid": object()})
            self.assertFalse(path.exists())
            path.write_bytes(b"original")
            with self.assertRaisesRegex(RuntimeError, "collection_file_exists"):
                COLLECT.write_json_new(path, {})
            self.assertEqual(b"original", path.read_bytes())

    def test_page_limit_retains_warning_and_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory))
            with patch.object(COLLECT, "get_service_key", return_value="fake"), patch.object(
                COLLECT, "request_json", return_value=self.payload(total=101)
            ) as request:
                self.assertEqual(1, self.invoke(args))
            self.assertEqual(100, request.call_count)
            result = json.loads((args.output_dir / "collected-notices.json").read_text())
            self.assertIn("100페이지", result["warnings"][0])
            self.assertFalse(json.loads((args.output_dir / "collection-provenance.json").read_text())["complete"])

    def test_two_processes_compete_for_one_directory_and_loser_never_calls_http(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory))
            context = multiprocessing.get_context("fork")
            barrier, results = context.Barrier(2), context.Queue()

            def run():
                with patch.object(COLLECT, "get_service_key", return_value="fake") as key, patch.object(
                    COLLECT, "request_json", return_value=self.payload()
                ) as request:
                    barrier.wait(timeout=5)
                    try:
                        status = self.invoke(args)
                    except RuntimeError:
                        status = 1
                    results.put((status, key.call_count, request.call_count))

            processes = [context.Process(target=run) for _ in range(2)]
            for process in processes:
                process.start()
            try:
                outcomes = [results.get(timeout=10) for _ in processes]
                self.assertEqual([(0, 1, 1), (1, 0, 0)], sorted(outcomes))
            finally:
                for process in processes:
                    process.join(timeout=5)
                    if process.is_alive():
                        process.terminate()
                        process.join()
                results.close()

    def test_bare_from_raw_explains_required_source_argument(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--from-date", "2026-09-01", "--to-date", "2026-09-01",
             "--output-dir", "unused", "--from-raw"], capture_output=True, text=True,
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("--from-raw SOURCE_RAW", completed.stderr)
        self.assertIn("--output-dir", completed.stderr)


if __name__ == "__main__":
    unittest.main()
