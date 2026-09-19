#!/usr/bin/env python3
"""Unit checks for scripts/score-c2-gate.py.

The tool is outside the product: it reads a gold TSV and an offline results
dump, and writes a gate artifact draft. These checks run with no network and no
database — every case uses a small synthetic gold and --results-json.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/score-c2-gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("score_c2_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score = _load_module()


GOLD_HEADER = "plan_id\tpublished_at\teffective_relevance\teffective_priority\tlabel_source\n"

# 두 게시일. 08-27은 관련 3건(높음 1건), 08-28은 관련 1건(높음 1건)이다.
GOLD_ROWS = [
    ("P1", "2026-08-27T09:00:00+09:00", "관련", "높음", "human"),
    ("P2", "2026-08-27T10:00:00+09:00", "관련", "보통", "human"),
    ("P3", "2026-08-27T11:00:00+09:00", "관련", "낮음", "draft"),
    ("P4", "2026-08-27T12:00:00+09:00", "비관련", "해당없음", "draft"),
    ("P5", "2026-08-27T13:00:00+09:00", "비관련", "해당없음", "draft"),
    ("P6", "2026-08-28T09:00:00+09:00", "관련", "높음", "human"),
    ("P7", "2026-08-28T10:00:00+09:00", "비관련", "해당없음", "draft"),
    ("P8", "2026-08-28T11:00:00+09:00", "비관련", "해당없음", "draft"),
]

EXEC_1 = "11111111-1111-5111-8111-111111111111"
EXEC_2 = "22222222-2222-5222-8222-222222222222"
EXEC_3 = "33333333-3333-5333-8333-333333333333"
EXEC_4 = "44444444-4444-5444-8444-444444444444"


def candidate(plan_id: str) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "stage1_status": "selected",
        "stage2_status": "success",
        "qwen_relevance": "relevant",
    }


def uncertain(plan_id: str) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "stage1_status": "selected",
        "stage2_status": "success",
        "qwen_relevance": "uncertain",
    }


def rejected_by_qwen(plan_id: str) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "stage1_status": "selected",
        "stage2_status": "success",
        "qwen_relevance": "not_relevant",
    }


def filtered_out(plan_id: str) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "stage1_status": "filtered_out",
        "stage2_status": "not_attempted",
        "qwen_relevance": None,
    }


def execution(
    execution_id: str,
    run_id: str,
    items: list[dict[str, object]],
    *,
    status: str = "성공",
    policy_sha: str = "a" * 64,
) -> dict[str, object]:
    return {
        "execution_id": execution_id,
        "source_run_id": run_id,
        "status": status,
        "purpose": "gate_measurement",
        "policy_version": "order-plan-screening-v3",
        "policy_sha256": policy_sha,
        "binding_sha256": "b" * 64,
        "population_count": len(items),
        "items": items,
    }


# pass 1: 08-27 → 후보 P1·P2·P4 (P3 누락, 낮음), 08-28 → 후보 P6·P7·P8
PASS1_DAY1 = execution(
    EXEC_1,
    "gate-gold-20260827-plans",
    [candidate("P1"), uncertain("P2"), rejected_by_qwen("P3"), candidate("P4"), filtered_out("P5")],
)
PASS1_DAY2 = execution(
    EXEC_2,
    "gate-gold-20260828-plans",
    [candidate("P6"), candidate("P7"), uncertain("P8")],
)


class ScoreC2GateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.gold = self.write_gold(GOLD_ROWS)

    def write_gold(
        self, rows: list[tuple[str, str, str, str, str]], *, name: str = "gold"
    ) -> Path:
        """gold TSV와 그 옆의 manifest.json을 함께 쓴다(채점 입력 digest가 둘 다 읽는다)."""
        directory = self.tmp / name
        directory.mkdir(exist_ok=True)
        path = directory / "gold-adjudicated-full-population.tsv"
        path.write_text(GOLD_HEADER + "".join("\t".join(row) + "\n" for row in rows), encoding="utf-8")
        (directory / "manifest.json").write_text(
            json.dumps({"status": "partially_human_adjudicated", "population_count": len(rows)}),
            encoding="utf-8",
        )
        return path

    def write_results(self, executions: list[dict[str, object]], name: str = "results.json") -> Path:
        path = self.tmp / name
        path.write_text(
            json.dumps({"schema_version": score.RESULTS_SCHEMA_VERSION, "executions": executions}),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def quiet_main(argv: list[str]) -> int:
        """도구는 요약을 stdout에, 경고를 stderr에 낸다. 검사 출력은 조용히 둔다."""
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return score.main(argv)

    def run_tool(self, argv: list[str]) -> tuple[int, dict[str, object] | None]:
        out = self.tmp / "artifact.json"
        code = self.quiet_main(["score", *argv, "--out", str(out)])
        artifact = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
        return code, artifact

    # -- 지표 -------------------------------------------------------------

    def test_recall_precision_important_missed_and_daily_review_load(self) -> None:
        results = self.write_results([PASS1_DAY1, PASS1_DAY2])
        code, artifact = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 0)
        assert artifact is not None
        metrics = artifact["passes"]["pass_1"]["metrics"]
        # gold 양성 4건 중 P1·P2·P6을 유지했고 P3(낮음)을 놓쳤다.
        self.assertEqual(metrics["recall_pct"], 75.0)
        # 검토 후보 6건 중 참 3건.
        self.assertEqual(metrics["precision_pct"], 50.0)
        # 높음 양성은 P1·P6이고 둘 다 후보다.
        self.assertEqual(metrics["important_missed"], 0)
        # 하루 기준: 08-27이 3건, 08-28이 3건 → 최댓값 3.
        self.assertEqual(metrics["review_load"], 3)
        # 참고 일괄값의 검토량은 창 전체 합계다.
        self.assertEqual(artifact["passes"]["pass_1"]["reference_full_window"]["review_load"], 6)

        day1 = artifact["passes"]["pass_1"]["by_published_day"]["2026-08-27"]
        self.assertEqual(day1["false_negative_plan_ids"], ["P3"])
        self.assertEqual(day1["false_positive"], 1)
        self.assertEqual(day1["review_candidates"], 3)

    def test_important_missed_counts_only_high_priority_gold_positives(self) -> None:
        # P1(높음)을 Qwen이 not_relevant로 떨어뜨린다.
        day1 = execution(
            EXEC_1,
            "gate-gold-20260827-plans",
            [
                rejected_by_qwen("P1"),
                candidate("P2"),
                candidate("P3"),
                filtered_out("P4"),
                filtered_out("P5"),
            ],
        )
        results = self.write_results([day1, PASS1_DAY2])
        code, artifact = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 0)
        assert artifact is not None
        pass_1 = artifact["passes"]["pass_1"]
        self.assertEqual(pass_1["metrics"]["important_missed"], 1)
        self.assertEqual(
            pass_1["by_published_day"]["2026-08-27"]["important_missed_plan_ids"], ["P1"]
        )
        # 낮음·보통 양성을 놓쳐도 중요 누락에는 들어가지 않는다.
        self.assertEqual(pass_1["totals"]["false_negative"], 1)

    def test_zero_denominator_stays_null(self) -> None:
        gold = self.write_gold(
            [
                ("P1", "2026-08-27T09:00:00+09:00", "비관련", "해당없음", "human"),
                ("P2", "2026-08-27T10:00:00+09:00", "비관련", "해당없음", "human"),
            ],
            name="gold-negative-only",
        )
        day = execution(EXEC_1, "gate-gold-20260827-plans", [filtered_out("P1"), filtered_out("P2")])
        results = self.write_results([day])
        code, artifact = self.run_tool(
            ["--gold", str(gold), "--results-json", str(results), "--pass1", EXEC_1]
        )
        self.assertEqual(code, 0)
        assert artifact is not None
        metrics = artifact["passes"]["pass_1"]["metrics"]
        # gold 양성 0건, 검토 후보 0건 → 둘 다 null. 0이나 100으로 접지 않는다.
        self.assertIsNone(metrics["recall_pct"])
        self.assertIsNone(metrics["precision_pct"])
        self.assertEqual(metrics["important_missed"], 0)
        self.assertEqual(metrics["review_load"], 0)

    # -- 두 pass ----------------------------------------------------------

    def test_agreement_and_worse_side(self) -> None:
        # pass 2는 P2를 떨어뜨리고 P5를 후보로 올린다(두 건 불일치).
        pass2_day1 = execution(
            EXEC_3,
            "gate-gold-20260827-plans",
            [
                candidate("P1"),
                rejected_by_qwen("P2"),
                rejected_by_qwen("P3"),
                candidate("P4"),
                candidate("P5"),
            ],
        )
        pass2_day2 = execution(
            EXEC_4,
            "gate-gold-20260828-plans",
            [candidate("P6"), candidate("P7"), uncertain("P8")],
        )
        results = self.write_results([PASS1_DAY1, PASS1_DAY2, pass2_day1, pass2_day2])
        code, artifact = self.run_tool(
            [
                "--gold", str(self.gold),
                "--results-json", str(results),
                "--pass1", EXEC_1, EXEC_2,
                "--pass2", EXEC_3, EXEC_4,
            ]
        )
        self.assertEqual(code, 0)
        assert artifact is not None
        agreement = artifact["agreement"]
        self.assertEqual(agreement["compared_count"], 8)
        self.assertEqual(agreement["disagreement_plan_ids"], ["P2", "P5"])
        self.assertEqual(agreement["agreement_pct"], 75.0)
        # 나쁜 쪽: recall은 작은 값(pass 2의 50), 검토량은 큰 값.
        self.assertEqual(artifact["passes"]["pass_2"]["metrics"]["recall_pct"], 50.0)
        self.assertEqual(artifact["measured_worse_side"]["recall_pct"], 50.0)
        self.assertEqual(artifact["measured_worse_side"]["review_load"], 3)
        self.assertEqual(artifact["measured_worse_side"]["important_missed"], 0)

    def test_single_pass_is_flagged(self) -> None:
        results = self.write_results([PASS1_DAY1, PASS1_DAY2])
        code, artifact = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 0)
        assert artifact is not None
        self.assertIsNone(artifact["passes"]["pass_2"])
        self.assertIsNone(artifact["agreement"])
        self.assertIn("pass_2_missing", {item["code"] for item in artifact["warnings"]})

    # -- 무결성 -----------------------------------------------------------

    def test_population_mismatch_is_an_error(self) -> None:
        short_day = execution(
            EXEC_1,
            "gate-gold-20260827-plans",
            [candidate("P1"), candidate("P2"), candidate("P3"), candidate("P4")],
        )
        results = self.write_results([short_day, PASS1_DAY2])
        code, artifact = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 2)
        self.assertIsNone(artifact)

    def test_plan_outside_gold_is_an_error(self) -> None:
        extra_day = execution(
            EXEC_1,
            "gate-gold-20260827-plans",
            [
                candidate("P1"),
                candidate("P2"),
                candidate("P3"),
                candidate("P4"),
                candidate("P5"),
                candidate("P9"),
            ],
        )
        results = self.write_results([extra_day, PASS1_DAY2])
        code, _ = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 2)

    def test_duplicate_plan_in_one_execution_is_an_error(self) -> None:
        duplicated = execution(
            EXEC_1,
            "gate-gold-20260827-plans",
            [candidate("P1"), candidate("P1")],
        )
        results = self.write_results([duplicated, PASS1_DAY2])
        code, _ = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 2)

    def test_run_id_day_mismatch_is_an_error(self) -> None:
        mislabelled = dict(PASS1_DAY1, source_run_id="gate-gold-20260830-plans")
        results = self.write_results([mislabelled, PASS1_DAY2])
        code, _ = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 2)

    def test_mixed_policy_digest_across_a_pass_is_an_error(self) -> None:
        other_bundle = execution(
            EXEC_2,
            "gate-gold-20260828-plans",
            [candidate("P6"), candidate("P7"), uncertain("P8")],
            policy_sha="c" * 64,
        )
        results = self.write_results([PASS1_DAY1, other_bundle])
        code, _ = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 2)

    def test_failed_execution_warns_but_still_scores(self) -> None:
        failing = dict(PASS1_DAY2, status="부분 성공")
        results = self.write_results([PASS1_DAY1, failing])
        code, artifact = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 0)
        assert artifact is not None
        self.assertFalse(artifact["passes"]["pass_1"]["all_successful"])
        self.assertIn("execution_not_successful", {item["code"] for item in artifact["warnings"]})
        self.assertEqual(artifact["passes"]["pass_1"]["metrics"]["recall_pct"], 75.0)

    def test_draft_labelled_gold_positive_is_reported(self) -> None:
        results = self.write_results([PASS1_DAY1, PASS1_DAY2])
        code, artifact = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 0)
        assert artifact is not None
        # P3만 관련 + draft다.
        self.assertEqual(artifact["gold"]["draft_labelled_positive_count"], 1)
        self.assertEqual(artifact["gold"]["draft_labelled_positive_plan_ids"], ["P3"])
        self.assertIn("gold_draft_positive", {item["code"] for item in artifact["warnings"]})

    # -- 산출물 -----------------------------------------------------------

    def test_artifact_is_canonical_and_body_carries_its_digest(self) -> None:
        results = self.write_results([PASS1_DAY1, PASS1_DAY2])
        out = self.tmp / "artifact.json"
        body_out = self.tmp / "body.json"
        summary_out = self.tmp / "summary.md"
        gate_id = "c2gate-" + "0" * 32
        code = self.quiet_main(
            [
                "score",
                "--gold", str(self.gold),
                "--results-json", str(results),
                "--pass1", EXEC_1, EXEC_2,
                "--gate-id", gate_id,
                "--out", str(out),
                "--body-out", str(body_out),
                "--summary-out", str(summary_out),
            ]
        )
        self.assertEqual(code, 0)
        payload = out.read_bytes()
        self.assertTrue(payload.endswith(b"\n"))
        artifact = json.loads(payload.decode("utf-8"))
        self.assertEqual(payload, score.canonical_json_bytes(artifact))
        body = json.loads(body_out.read_text(encoding="utf-8"))
        self.assertEqual(body["artifact_sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(body["schema_version"], score.EVALUATION_SCHEMA_VERSION)
        self.assertEqual(body["pass_execution_ids"], {"pass_1": [EXEC_1, EXEC_2], "pass_2": None})
        self.assertEqual(body["pass_metrics"]["pass_1"], artifact["passes"]["pass_1"]["metrics"])
        self.assertIsNone(body["pass_metrics"]["pass_2"])
        self.assertEqual(artifact["gate_id"], gate_id)
        self.assertIn("게시일별 분해", summary_out.read_text(encoding="utf-8"))

    def test_dump_results_round_trips(self) -> None:
        results = self.write_results([PASS1_DAY1, PASS1_DAY2])
        dump = self.tmp / "dump.json"
        code = self.quiet_main(
            [
                "score",
                "--gold", str(self.gold),
                "--results-json", str(results),
                "--pass1", EXEC_1, EXEC_2,
                "--out", str(self.tmp / "artifact.json"),
                "--dump-results", str(dump),
            ]
        )
        self.assertEqual(code, 0)
        second = self.tmp / "artifact2.json"
        code = self.quiet_main(
            ["score", "--gold", str(self.gold), "--results-json", str(dump), "--pass1", EXEC_1, EXEC_2, "--out", str(second)]
        )
        self.assertEqual(code, 0)
        first_metrics = json.loads((self.tmp / "artifact.json").read_text(encoding="utf-8"))
        second_metrics = json.loads(second.read_text(encoding="utf-8"))
        self.assertEqual(
            first_metrics["passes"]["pass_1"]["metrics"], second_metrics["passes"]["pass_1"]["metrics"]
        )

    def test_cli_runs_as_a_subprocess_without_network(self) -> None:
        results = self.write_results([PASS1_DAY1, PASS1_DAY2])
        out = self.tmp / "cli-artifact.json"
        completed = subprocess.run(
            [
                sys.executable, str(SCRIPT), "score",
                "--gold", str(self.gold),
                "--results-json", str(results),
                "--pass1", EXEC_1, EXEC_2,
                "--out", str(out),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("C-2 품질 게이트 채점 요약", completed.stdout)
        self.assertIn("evaluations", completed.stdout)
        self.assertIn("warning: pass_2_missing", completed.stderr)
        self.assertTrue(out.is_file())

    # -- 채점 입력 digest ---------------------------------------------------

    def test_scoring_input_digest_is_deterministic_and_order_independent(self) -> None:
        tool_sha = score.sha256_file(SCRIPT)
        gold = score.load_gold(self.gold, None)
        forward = score.build_scoring_input(
            gold, ["gate-gold-20260828-plans", "gate-gold-20260827-plans"], tool_sha
        )
        backward = score.build_scoring_input(
            gold, ["gate-gold-20260827-plans", "gate-gold-20260828-plans"], tool_sha
        )
        # 회차 id는 정렬해서 담으므로 주는 순서가 digest를 바꾸지 않는다.
        self.assertEqual(forward, backward)
        self.assertEqual(
            forward["measurement_run_ids"],
            ["gate-gold-20260827-plans", "gate-gold-20260828-plans"],
        )
        self.assertEqual(forward["schema_version"], score.SCORING_INPUT_SCHEMA_VERSION)
        self.assertEqual(forward["candidate_rule"], score.CANDIDATE_RULE)
        self.assertEqual(forward["important_rule"], score.IMPORTANT_RULE)
        self.assertEqual(forward["gold_artifact_sha256"], score.sha256_file(self.gold))

        # digest는 canonical 규칙(정렬 키·최소 구분자·끝 개행 없음)으로 고정된다.
        payload = score.canonical_digest_bytes(forward)
        self.assertFalse(payload.endswith(b"\n"))
        self.assertEqual(
            score.scoring_input_digest(forward), hashlib.sha256(payload).hexdigest()
        )
        # gold가 한 줄이라도 바뀌면 digest가 달라진다.
        other = score.load_gold(self.write_gold(GOLD_ROWS[:-1], name="gold-short"), None)
        self.assertNotEqual(
            score.scoring_input_digest(forward),
            score.scoring_input_digest(
                score.build_scoring_input(other, ["gate-gold-20260827-plans"], tool_sha)
            ),
        )

    def test_scoring_input_command_prints_gate_fields(self) -> None:
        out = self.tmp / "scoring-input.json"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
            code = score.main(
                [
                    "scoring-input",
                    "--gold", str(self.gold),
                    "--run-id", "gate-gold-20260828-plans",
                    "--run-id", "gate-gold-20260827-plans",
                    "--out", str(out),
                ]
            )
        self.assertEqual(code, 0)
        written = json.loads(out.read_text(encoding="utf-8"))
        digest = score.scoring_input_digest(written)
        printed = buffer.getvalue()
        self.assertIn(digest, printed)
        self.assertIn("gold_status", printed)
        self.assertIn("partially_human_adjudicated", printed)
        # 임계값과 policy digest는 도구가 채우지 않는다.
        self.assertNotIn("threshold_", printed)
        self.assertNotIn("policy_sha256", printed)

    def test_expect_scoring_input_sha256_mismatch_is_an_error(self) -> None:
        results = self.write_results([PASS1_DAY1, PASS1_DAY2])
        expected = score.scoring_input_digest(
            score.build_scoring_input(
                score.load_gold(self.gold, None),
                ["gate-gold-20260827-plans", "gate-gold-20260828-plans"],
                score.sha256_file(SCRIPT),
            )
        )
        code, artifact = self.run_tool(
            [
                "--gold", str(self.gold),
                "--results-json", str(results),
                "--pass1", EXEC_1, EXEC_2,
                "--expect-scoring-input-sha256", expected,
            ]
        )
        self.assertEqual(code, 0)
        assert artifact is not None
        self.assertEqual(artifact["scoring_input_sha256"], expected)

        code, _ = self.run_tool(
            [
                "--gold", str(self.gold),
                "--results-json", str(results),
                "--pass1", EXEC_1, EXEC_2,
                "--expect-scoring-input-sha256", "f" * 64,
            ]
        )
        self.assertEqual(code, 2)

    def test_missing_results_without_api_is_an_error(self) -> None:
        results = self.write_results([PASS1_DAY1])
        code, _ = self.run_tool(
            ["--gold", str(self.gold), "--results-json", str(results), "--pass1", EXEC_1, EXEC_2]
        )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
