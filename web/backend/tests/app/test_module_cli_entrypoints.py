"""각 모듈 CLI가 새 인터프리터에서 실제로 뜨는지 본다 (명세 §2 완료 기준 4).

`tests/app/test_acceptance_clis.py`는 `main`을 직접 import해서 부르므로, pytest가
conftest 순서로 이미 끌어와 둔 모듈 덕분에 import 순서 버그가 가려진다. 실제
운영 명령은 `python -m <진입점>`이고 그때의 import 순서는 전혀 다르다. T6의
models 분할이 만든 `app.lifecycle` 순환 import가 전체 suite 녹색인 채로 이
명령만 죽였던 것이 그 예다.

그래서 이 테스트는 subprocess로 새 인터프리터를 띄워 `--help`를 실행하고
usage 출력과 종료 코드를 확인한다. T8 2단계가 모듈 CLI를 하위 명령 체계로
합쳤으므로 **진입점 세 개와 그 아래 하위 명령 전부**를 본다. DB에는 붙지
않도록 `tmp_path` 기반 환경변수를 준다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: 모듈 CLI 진입점 세 개와 그 하위 명령 전부, 그리고 `--help`의 종료 코드.
#:
#: `app.screening.cli`만 1이다. `run_one.main`이 argparse의 `SystemExit`을 잡아
#: "입력 오류" 종료 코드로 바꾸도록 예전부터 계약되어 있고, T8 2단계는 하위
#: 명령을 합치면서 그 계약을 바꾸지 않았다(최상위 dispatch도 같은 값을 낸다).
#: `score-candidate-quality`는 예전 스크립트 그대로 argparse의 0을 쓴다.
#: 이 테스트가 보는 것은 종료 코드 자체가 아니라 **새 인터프리터에서 모듈이
#: import되어 그 하위 명령의 parser까지 도달했는가**이다.
MODULE_CLIS: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("app.screening.cli", (), 1),
    ("app.screening.cli", ("run-one",), 1),
    ("app.screening.cli", ("score-candidate-quality",), 0),
    ("app.deep_review.cli", (), 0),
    ("app.deep_review.cli", ("run-bc-e2e",), 0),
    ("app.deep_review.cli", ("run-prespec-e2e",), 0),
    ("app.deep_review.cli", ("import-profile-policy",), 0),
    ("app.deep_review.cli", ("import-company-knowledge",), 0),
    ("app.deep_review.cli", ("activate-company-knowledge",), 0),
    ("app.deep_review.cli", ("import-company-fit-policy",), 0),
    ("app.deep_review.cli", ("enqueue-company-fit",), 0),
    ("app.deep_review.cli", ("rebuild-segment-manifests",), 0),
    ("app.lifecycle.ingest.cli", (), 0),
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


@pytest.mark.parametrize(
    "module,subcommand,expected_exit",
    MODULE_CLIS,
    ids=lambda value: "-".join(value) if isinstance(value, tuple) else None,
)
def test_module_cli_starts_in_a_fresh_interpreter(
    module: str, subcommand: tuple[str, ...], expected_exit: int, tmp_path: Path
) -> None:
    command = [sys.executable, "-m", module, *subcommand, "--help"]
    printable = " ".join(["python", "-m", module, *subcommand, "--help"])
    completed = subprocess.run(
        command,
        cwd=BACKEND_ROOT,
        env=_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert "Traceback" not in completed.stderr, (
        f"{printable} 가 예외로 죽었다.\n"
        f"--- stderr ---\n{completed.stderr}"
    )
    assert completed.returncode == expected_exit, (
        f"{printable} 의 종료 코드가 {expected_exit}이 아니다 "
        f"(exit {completed.returncode}).\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    )
    assert "usage" in completed.stdout.lower(), (
        f"{printable} 가 usage를 내지 않았다.\n"
        f"--- stdout ---\n{completed.stdout}"
    )
