#!/usr/bin/env python3
"""End-to-end check across the three skills, run on preserved API pages.

The point of this suite is the seam between the skills: a judgment written by an
agent must survive validation, merging, and rendering without any script adding
content of its own.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COLLECT = ROOT / "skills/bidops-collect/scripts/collect_notices.py"
SAMPLE = ROOT / "skills/bidops-collect/scripts/select_validation_sample.py"
BUILD = ROOT / "skills/bidops-screen/scripts/build_screening_results.py"
RENDER = ROOT / "skills/bidops-report/scripts/render_report.py"

RAW_PAGE = {
    "response": {
        "header": {"resultCode": "00"},
        "body": {
            "totalCount": 2,
            "items": [
                {
                    "bidNtceNo": "R26TEST0001",
                    "bidNtceOrd": "000",
                    "bidNtceNm": "지식그래프 기반 행정정보 검색 고도화 용역",
                    "dminsttNm": "테스트청",
                    "bidNtceDt": "202608180900",
                    "bidClseDt": "202608281800",
                    "asignBdgtAmt": "300000000",
                    "pubPrcrmntLrgClsfcNm": "ICT 서비스",
                    "pubPrcrmntMidClsfcNm": "SW 및 시스템 개발",
                    "rgnLmtBidLocplcJdgmBssNm": "본사또는참여지사소재지",
                    "bidNtceDtlUrl": "https://www.g2b.go.kr/test",
                },
                {
                    "bidNtceNo": "R26TEST0002",
                    "bidNtceOrd": "000",
                    "bidNtceNm": "청사 조경 및 수목 관리 용역",
                    "dminsttNm": "테스트청",
                    "bidNtceDt": "202608180900",
                    "pubPrcrmntMidClsfcNm": "폐기물 처리",
                },
            ],
        },
    }
}


def judgment(notice_id: str, *, excluded: bool) -> dict:
    perspectives = [
        {
            "name": name,
            "assessment": "부적합" if excluded else "적합",
            "reason": f"{name} 관점에서 확인한 내용을 기록한다.",
            "evidence": [
                {
                    "source": "나라장터 API bidNtceNm",
                    "status": "confirmed",
                    "fact": "공고명에 기재된 과업 범위",
                }
            ],
        }
        for name in (
            "기술 적합성", "실적 정합성", "공공 SI 적합성", "사업성·자격 제약", "전략 부합",
        )
    ]
    if excluded:
        return {
            "notice_id": notice_id,
            "grade": "제외",
            "readiness": "해당 없음",
            "primary_focus": "해당 없음",
            "exclusion_category": "시설·현장 용역",
            "summary": "조경 관리 용역으로 디지털 납품물이 없다.",
            "perspectives": perspectives,
            "matched_performances": [],
            "counterarguments": ["조경 관리에 정보시스템 과업이 숨어 있을 가능성은 낮다."],
            "verification_items": [],
            "next_action": "제외 사유를 기록하고 재공고 시 참조한다.",
        }
    return {
        "notice_id": notice_id,
        "grade": "우선 검토",
        "readiness": "부분 확인 필요",
        "primary_focus": "AI/데이터",
        "exclusion_category": None,
        "summary": "지식그래프 검색 고도화로 회사의 온톨로지 역량과 직접 연결된다.",
        "perspectives": perspectives,
        "matched_performances": [],
        "counterarguments": ["검색 고도화의 핵심이 UI 개편이면 온톨로지 역량의 비중이 줄어든다."],
        "verification_items": [
            {
                "item": "입찰참가자격",
                "why": "회사 프로필의 조달 자격 상태가 unknown이다.",
                "blocking": True,
                "status": "미확인",
            }
        ],
        "next_action": "첨부 제안요청서에서 지식모델 범위를 확인한다.",
    }


def run(*command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *command], capture_output=True, text=True, cwd=ROOT
    )


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.directory.name) / "run"
        raw_dir = self.run_dir / "raw"
        raw_dir.mkdir(parents=True)
        (raw_dir / "bid-page-001.json").write_text(
            json.dumps(RAW_PAGE, ensure_ascii=False), encoding="utf-8"
        )
        self.addCleanup(self.directory.cleanup)

    def collect_and_sample(self) -> dict:
        collected = run(
            str(COLLECT), "--from-date", "2026-08-17", "--to-date", "2026-08-23",
            "--output-dir", str(self.run_dir), "--from-raw", "--skip-prespecs",
        )
        self.assertEqual(0, collected.returncode, collected.stderr)
        sampled = run(
            str(SAMPLE), str(self.run_dir / "collected-notices.json"),
            "--output", str(self.run_dir / "validation-set.json"),
            "--analysis-count", "1", "--audit-count", "1",
        )
        self.assertEqual(0, sampled.returncode, sampled.stderr)
        return json.loads((self.run_dir / "validation-set.json").read_text(encoding="utf-8"))

    def write_decisions(self, validation: dict) -> Path:
        judgments = [
            judgment(
                item["notice_id"],
                excluded=item["sample_role"] == "audit",
            )
            for item in validation["notices"]
        ]
        path = self.run_dir / "screening-decisions.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "bidops.decisions.v2",
                    "screening_basis": "공고명과 API 메타데이터",
                    "judgments": judgments,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_full_run_preserves_the_agent_judgment(self) -> None:
        validation = self.collect_and_sample()
        self.assertEqual(2, len(validation["notices"]))
        self.write_decisions(validation)

        built = run(
            str(BUILD), str(self.run_dir / "validation-set.json"),
            str(self.run_dir / "screening-decisions.json"),
            "--output", str(self.run_dir / "screening-results.json"),
        )
        self.assertEqual(0, built.returncode, built.stderr)
        results = json.loads(
            (self.run_dir / "screening-results.json").read_text(encoding="utf-8")
        )
        self.assertEqual("bidops.screening.v2", results["schema_version"])
        for item in results["results"]:
            self.assertEqual(5, len(item["judgment"]["perspectives"]))

        report_dir = self.run_dir / "report"
        rendered = run(
            str(RENDER), str(self.run_dir / "screening-results.json"),
            "--output-dir", str(report_dir),
        )
        self.assertEqual(0, rendered.returncode, rendered.stderr)
        weekly = (report_dir / "weekly-monitoring.html").read_text(encoding="utf-8")
        self.assertIn("검토 대기열", weekly)
        self.assertIn("필터 감사 표본 1건 · 누락 0건", weekly)
        self.assertIn("지식그래프 검색 고도화로", weekly)
        feedback = (report_dir / "review-feedback.yaml").read_text(encoding="utf-8")
        self.assertEqual(2, feedback.count("notice_id:"))

    def test_incomplete_judgment_stops_the_pipeline(self) -> None:
        validation = self.collect_and_sample()
        path = self.write_decisions(validation)
        decisions = json.loads(path.read_text(encoding="utf-8"))
        decisions["judgments"][0].pop("counterarguments")
        path.write_text(json.dumps(decisions, ensure_ascii=False), encoding="utf-8")

        built = run(
            str(BUILD), str(self.run_dir / "validation-set.json"), str(path),
            "--output", str(self.run_dir / "screening-results.json"),
        )
        self.assertNotEqual(0, built.returncode)
        self.assertIn("반론", built.stderr)
        self.assertFalse((self.run_dir / "screening-results.json").exists())


if __name__ == "__main__":
    unittest.main()
