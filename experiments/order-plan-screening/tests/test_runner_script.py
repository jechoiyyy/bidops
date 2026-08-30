from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "run-local-comparison.sh"


class LocalRunnerScriptTests(unittest.TestCase):
    def test_shell_contract_and_help(self) -> None:
        syntax = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        help_result = subprocess.run(
            [str(SCRIPT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--approve-capabilities", help_result.stdout)
        self.assertIn("--execute-dense", help_result.stdout)
        self.assertIn("--execute-qwen", help_result.stdout)
        self.assertIn("GPT Luna remain deferred", help_result.stdout)
        script_text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--timeout 60", script_text)
        self.assertIn("--max-attempts 3", script_text)
        self.assertIn("render_decision_report.py", script_text)

    def test_live_execution_requires_explicit_approval_arguments(self) -> None:
        result = subprocess.run(
            [str(SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--approved-by", result.stderr)


if __name__ == "__main__":
    unittest.main()
