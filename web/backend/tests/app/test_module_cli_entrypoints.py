"""각 모듈 CLI가 새 인터프리터에서 실제로 뜨는지 본다 (명세 §2 완료 기준 4).

`tests/test_acceptance_clis.py`는 `main`을 직접 import해서 부르므로, pytest가
conftest 순서로 이미 끌어와 둔 모듈 덕분에 import 순서 버그가 가려진다. 실제
운영 명령은 `python -m <진입점>`이고 그때의 import 순서는 전혀 다르다. T6의
models 분할이 만든 `app.lifecycle` 순환 import가 전체 suite 녹색인 채로 이
명령만 죽였던 것이 그 예다.

그래서 이 테스트는 subprocess로 새 인터프리터를 띄워 `--help`를 실행하고 exit
0과 usage 출력을 확인한다. DB에는 붙지 않도록 `tmp_path` 기반 환경변수를 준다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: 지금 존재하는 모듈 CLI 진입점 전부와 `--help`의 종료 코드.
#:
#: `app.screening.cli`만 1이다. `run_one.main`이 argparse의 `SystemExit`을 잡아
#: "입력 오류" 종료 코드로 바꾸도록 이미 계약되어 있고, 이 테스트는 그 계약을
#: 바꾸지 않는다. 이 테스트가 보는 것은 종료 코드 자체가 아니라 **새
#: 인터프리터에서 모듈이 import되어 parser까지 도달했는가**이다.
MODULE_CLIS: tuple[tuple[str, int], ...] = (
    ("app.screening.cli", 1),
    ("app.screening.cli.score_candidate_quality", 0),
    ("app.deep_review.cli.import_profile_policy", 0),
    ("app.deep_review.cli.run_bc_e2e", 0),
    ("app.ingest.cli", 0),
)


def _environment(tmp_path: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("BIDOPS_ROOT", None)
    environment.update(
        {
            "BIDOPS_DATA_DIR": str(tmp_path / "data"),
            "BIDOPS_ATTACHMENTS_DIR": str(tmp_path / "attachments"),
            "BIDOPS_DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}",
            "PYTHONPATH": str(BACKEND_ROOT),
        }
    )
    return environment


@pytest.mark.parametrize("module,expected_exit", MODULE_CLIS)
def test_module_cli_starts_in_a_fresh_interpreter(
    module: str, expected_exit: int, tmp_path: Path
) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=BACKEND_ROOT,
        env=_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert "Traceback" not in completed.stderr, (
        f"python -m {module} --help 가 예외로 죽었다.\n"
        f"--- stderr ---\n{completed.stderr}"
    )
    assert completed.returncode == expected_exit, (
        f"python -m {module} --help 의 종료 코드가 {expected_exit}이 아니다 "
        f"(exit {completed.returncode}).\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    )
    assert "usage" in completed.stdout.lower(), (
        f"python -m {module} --help 가 usage를 내지 않았다.\n"
        f"--- stdout ---\n{completed.stdout}"
    )
