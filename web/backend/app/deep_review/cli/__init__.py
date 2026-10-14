"""deep_review의 서버측 관리 CLI 명령.

`python -m app.deep_review.cli`가 아래 하위 명령을 모두 받는다.

- ``run-bc-e2e``: 문서 준비(B)에서 심층 검토(C)까지의 격리 인수 흐름을 돌린다.
- ``run-prespec-e2e``: 사전규격 회차 적재부터 보고서·최종 의견까지의 mock
  종단 인수 흐름을 격리 workspace에서 돌린다.
- ``import-profile-policy``: 불변 회사 프로필·분석 policy 판을 import한다.
- ``import-company-knowledge``: 가상회사 원본에서 profile/graph 버전을 등록한다.
- ``activate-company-knowledge``: 회사의 active profile/graph binding을 갱신한다.
- ``import-company-fit-policy``: 승인된 DEMO 회사 핏 policy 파일을 불변 행으로 등록한다(활성화 없음).
- ``enqueue-company-fit``: 회사·공고 한 건의 회사 핏 attempt를 동결 입력과 함께 대기열에 넣는다(worker 역할).
- ``enqueue-overview``: 사전규격 공고 한 건의 개요 run을 대기열에 넣는다.
- ``prepare-overviews``: 이미 적재된 사전규격의 자동 준비를 한 번에 돌린다.
- ``close-overview-run``: 활성 개요 run 하나를 사람이 닫는다.
- ``rebuild-segment-manifests``: 과거 ready 구조에 현재 segment manifest를
  멱등 생성한다(worker 역할).

T8 2단계가 두 스크립트에 패키지 진입점을 만들어 하나의 하위 명령 체계로
합쳤다. 합친 것은 **진입점뿐**이고, 각 하위 명령의 인자·출력·종료 코드는
예전 스크립트와 같다. dispatch는 하위 명령 이름만 보고 기존 ``main(argv)``에
나머지 인자를 그대로 넘긴다(각 명령의 파서는 여전히 자기 모듈이 소유한다).

고른 하위 명령의 모듈만 늦게 import한다. `import-profile-policy`가 DB를,
`run-bc-e2e`가 인수 API client를, `run-prespec-e2e`가 취득·개요·심층 실행
경로를 끌어오므로 패키지 import만으로 셋을 다 지고 시작하지 않게 한다.
"""

from __future__ import annotations

import argparse
import sys
from importlib import import_module
from typing import Sequence

PROG = "python -m app.deep_review.cli"

#: 하위 명령 이름 → (구현 모듈, 도움말 한 줄).
_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "run-bc-e2e": (".run_bc_e2e", "문서 준비(B)에서 심층 검토(C)까지 인수 흐름을 돌린다"),
    "run-prespec-e2e": (
        ".run_prespec_e2e",
        "사전규격 회차 적재부터 보고서·최종 의견까지 mock 종단 인수 흐름을 돌린다",
    ),
    "import-profile-policy": (
        ".import_profile_policy",
        "불변 회사 프로필·분석 policy 판을 import한다",
    ),
    "import-company-knowledge": (
        ".import_company_knowledge",
        "온톨로지와 가상회사 지식 원본을 불변 버전으로 등록한다",
    ),
    "activate-company-knowledge": (
        ".activate_company_knowledge",
        "회사의 profile/graph binding을 원자적으로 활성화한다",
    ),
    "import-company-fit-policy": (
        ".import_company_fit_policy",
        "승인된 DEMO 회사 핏 policy 파일을 불변 행으로 등록한다 (활성화하지 않음)",
    ),
    "enqueue-company-fit": (
        ".enqueue_company_fit",
        "회사·공고 한 건의 회사 핏 attempt를 동결 입력과 함께 대기열에 넣는다 (worker 역할)",
    ),
    "enqueue-overview": (
        ".enqueue_overview",
        "사전규격 공고 한 건의 개요 run을 대기열에 넣는다",
    ),
    "prepare-overviews": (
        ".prepare_overviews",
        "자격을 갖춘 사전규격의 자동 준비를 한 번에 돌린다 (개요 backfill)",
    ),
    "close-deep-review": (".close_deep_review", "대기 심층검토를 감사와 함께 중단하거나 활성 목록 조회"),
    "close-overview-run": (
        ".close_overview_run",
        "활성 사전규격 개요 run 하나를 닫는다 (queued→cancelled, running→failed)",
    ),
    "rebuild-segment-manifests": (
        ".rebuild_segment_manifests",
        "과거 ready 구조에 현재 segment manifest를 멱등 생성한다 (worker 역할)",
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


def main(argv: Sequence[str] | None = None) -> int:
    """하위 명령을 골라 기존 ``main(argv)``을 그대로 부른다."""

    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else None
    if command in _SUBCOMMANDS:
        module = import_module(_SUBCOMMANDS[command][0], __name__)
        return module.main(args[1:])
    # 두 하위 명령 모두 argparse의 종료 코드를 그대로 쓴다(`--help`는 0,
    # 잘못된 입력은 2). 최상위 진입점도 같은 계약을 따른다.
    build_parser().parse_args(args)
    raise AssertionError("required subparser must have exited")  # pragma: no cover


__all__ = ["PROG", "build_parser", "main"]
