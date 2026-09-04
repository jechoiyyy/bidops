"""screening의 서버측 관리 CLI 명령.

`python -m app.screening.cli`가 두 하위 명령을 모두 받는다.

- ``run-one``: 공고 한 건의 판정 실행을 만들고(선택적으로) 끝까지 돌린다.
- ``score-candidate-quality``: 사람이 판정한 Qwen 후보 품질 manifest를 채점한다.

T8 2단계가 두 명령을 하나의 하위 명령 체계로 합쳤다. 합친 것은 **진입점뿐**
이고, 각 하위 명령의 인자·출력·종료 코드는 예전 스크립트와 같다. 그래서
dispatch는 하위 명령 이름만 보고 기존 ``main(argv)``에 나머지 인자를 그대로
넘긴다(각 명령의 파서는 여전히 자기 모듈이 소유한다).

dispatch는 고른 하위 명령의 모듈만 늦게 import한다. 패키지를 import하는 것만으로
orchestrator·worker까지 끌어오면 `score-candidate-quality`가 필요 없는 모듈을
지고 시작하기 때문이다.
"""

from __future__ import annotations

import argparse
import sys
from importlib import import_module
from typing import Any, Sequence

PROG = "python -m app.screening.cli"

#: 하위 명령 이름 → (구현 모듈, 도움말 한 줄).
_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "run-one": (".run_one", "공고 한 건의 판정 실행을 만든다"),
    "score-candidate-quality": (
        ".score_candidate_quality",
        "사람이 판정한 Qwen 후보 품질 manifest를 채점한다",
    ),
}


def build_parser() -> argparse.ArgumentParser:
    """하위 명령 이름만 아는 최상위 파서.

    각 하위 명령의 인자는 그 명령의 모듈이 소유한다. 여기서 다시 선언하면
    두 곳이 갈라지므로, 이 파서는 ``--help``와 잘못된 하위 명령 이름만 본다.
    """

    parser = argparse.ArgumentParser(prog=PROG)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, (_module, description) in _SUBCOMMANDS.items():
        commands.add_parser(name, help=description, add_help=False)
    return parser


def main(argv: Sequence[str] | None = None, **kwargs: Any) -> int:
    """하위 명령을 골라 기존 ``main(argv)``을 그대로 부른다."""

    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else None
    if command in _SUBCOMMANDS:
        module = import_module(_SUBCOMMANDS[command][0], __name__)
        if command == "run-one":
            # `run_one.main`은 하위 명령 이름까지 포함한 argv를 파싱하고,
            # argparse의 SystemExit을 입력 오류 종료 코드로 바꾼다. 그 계약을
            # 그대로 두려고 인자를 자르지 않고 넘긴다(주입 인자도 함께).
            return module.main(args, **kwargs)
        return module.main(args[1:], **kwargs)
    try:
        build_parser().parse_args(args)
    except SystemExit:
        # `run-one`이 예전부터 지켜 온 계약이다. 최상위 진입점도 argparse의
        # 종료 코드 대신 "입력 오류"를 낸다.
        return 1
    return 1



__all__ = ["PROG", "build_parser", "main"]
