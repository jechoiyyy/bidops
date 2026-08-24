#!/usr/bin/env python3
"""The renderer presents the screening JSON and never judges a notice itself."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/render_report.py"
SPEC = importlib.util.spec_from_file_location("bidops_render_report", SCRIPT)
assert SPEC and SPEC.loader
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)


def result(
    identifier: str,
    grade: str = "우선 검토",
    *,
    role: str = "analysis",
    category: str | None = None,
    readiness: str = "부분 확인 필요",
    title: str = "공고 제목",
) -> dict:
    return {
        "notice": {
            "notice_id": identifier,
            "title": title,
            "agency": "테스트기관",
            "sample_role": role,
            "sample_stratum": "AI/데이터",
            "procurement_class": {"large": "ICT 서비스", "middle": "SW 및 시스템 개발"},
            "region_limit": {"basis": None, "joint_contract_regions": []},
            "lifecycle": {"pre_spec_no": None, "re_notice": "N", "change_reason": None},
            "focus_matches": [],
        },
        "judgment": {
            "grade": grade,
            "readiness": readiness,
            "primary_focus": "AI/데이터",
            "exclusion_category": category,
            "summary": "요약",
            "perspectives": [],
            "matched_performances": [],
            "counterarguments": [],
            "verification_items": [],
            "next_action": "다음 조치",
        },
    }


class ExclusionCategoryTests(unittest.TestCase):
    def test_category_comes_from_the_judgment(self) -> None:
        item = result("bid:1:00", "제외", category="감리·평가", readiness="해당 없음")
        self.assertEqual("감리·평가", RENDER.exclusion_category(item))

    def test_missing_category_is_reported_as_unrecorded(self) -> None:
        """The renderer never infers a reason from the title."""
        item = result(
            "bid:2:00", "제외", readiness="해당 없음", title="정보시스템 감리 용역"
        )
        self.assertEqual("사유 미기재", RENDER.exclusion_category(item))


class PartitionTests(unittest.TestCase):
    def test_audit_records_never_enter_the_review_queue(self) -> None:
        results = [
            result("bid:1:00"),
            result("bid:2:00", "제외", category="공사·인프라", readiness="해당 없음"),
            result("bid:3:00", role="audit"),
            result("bid:4:00", "제외", role="audit", category="행사·교육·홍보", readiness="해당 없음"),
        ]
        queue, excluded, audits = RENDER.partition_results(results)
        self.assertEqual(["bid:1:00"], [item["notice"]["notice_id"] for item in queue])
        self.assertEqual(["bid:2:00"], [item["notice"]["notice_id"] for item in excluded])
        self.assertEqual(
            ["bid:3:00", "bid:4:00"], [item["notice"]["notice_id"] for item in audits]
        )

    def test_audit_records_that_are_not_excluded_are_counted_as_misses(self) -> None:
        results = [
            result("bid:3:00", role="audit"),
            result("bid:4:00", "제외", role="audit", category="행사·교육·홍보", readiness="해당 없음"),
        ]
        self.assertEqual(1, RENDER.audit_miss_count(results))


class WeeklyReportTests(unittest.TestCase):
    def test_statistics_separate_the_queue_from_the_audit_sample(self) -> None:
        results = [
            result("bid:1:00"),
            result("bid:2:00", "검토 권장"),
            result("bid:3:00", "제외", category="공사·인프라", readiness="해당 없음"),
            result("bid:4:00", role="audit"),
        ]
        stats = RENDER.weekly_statistics(results)
        self.assertEqual(
            {
                "검토 대기열": 2,
                "우선 검토": 1,
                "검토 권장": 1,
                "제외": 1,
                "감사 표본 회수": 1,
            },
            dict(stats),
        )

    def test_report_renders_without_a_second_judgment_pass(self) -> None:
        data = {
            "schema_version": "bidops.screening.v2",
            "source_window": {"from": "2026-08-17", "to": "2026-08-23"},
            "results": [result("bid:1:00")],
        }
        html = RENDER.render_weekly(data, {"bid:1:00": "bid-1-00.html"})
        self.assertIn("검토 대기열", html)
        self.assertIn("bid-1-00.html", html)


class DetailPageTests(unittest.TestCase):
    def test_signal_provenance_is_shown_beside_the_concept(self) -> None:
        item = result("bid:1:00")
        item["notice"]["focus_matches"] = [
            {
                "axis": "AI/데이터",
                "label": "빅데이터",
                "matched_field": "pubPrcrmntMidClsfcNm",
                "matched_text": "빅데이터",
                "field_kind": "classification",
            }
        ]
        html = RENDER.render_detail(item)
        self.assertIn("빅데이터", html)
        self.assertIn("분류명", html)

    def test_markup_in_notice_text_is_escaped(self) -> None:
        item = result("bid:1:00", title="<script>alert(1)</script>")
        html = RENDER.render_detail(item)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_non_http_source_link_is_dropped(self) -> None:
        item = result("bid:1:00")
        item["notice"]["url"] = "javascript:alert(1)"
        self.assertNotIn("javascript:", RENDER.render_detail(item))


class FileNameTests(unittest.TestCase):
    def test_distinct_notice_ids_never_share_a_file_name(self) -> None:
        names = RENDER.detail_file_names(
            [result("bid:a/b:00"), result("bid:a-b:00"), result("bid:1:00")]
        )
        self.assertEqual(3, len(set(names.values())))


class StaleDetailTests(unittest.TestCase):
    """A detail page left by an earlier run would outlive its judgment."""

    def test_pages_not_written_by_this_run_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            detail_dir = Path(directory) / "details"
            detail_dir.mkdir()
            (detail_dir / "bid-old-000.html").write_text("이전 실행", encoding="utf-8")
            keep = detail_dir / "bid-1-00.html"
            keep.write_text("현재 실행", encoding="utf-8")
            removed = RENDER.remove_stale_details(detail_dir, {"bid-1-00.html"})
        self.assertEqual(["bid-old-000.html"], removed)

    def test_non_html_files_are_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            detail_dir = Path(directory) / "details"
            detail_dir.mkdir()
            note = detail_dir / "메모.txt"
            note.write_text("보관", encoding="utf-8")
            removed = RENDER.remove_stale_details(detail_dir, set())
        self.assertEqual([], removed)


class FeedbackTests(unittest.TestCase):
    def test_template_carries_both_correction_axes(self) -> None:
        text = RENDER.render_feedback([result("bid:1:00")])
        self.assertIn("schema_version: bidops.feedback.v2", text)
        self.assertIn("corrected_grade", text)
        self.assertIn("corrected_readiness", text)
        self.assertIn("weakest_perspective", text)


if __name__ == "__main__":
    unittest.main()
