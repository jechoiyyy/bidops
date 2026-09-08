"""사전규격 mock 종단 인수 실행 (명세 §2 완료 기준 1·§12).

`run-bc-e2e`의 형제 명령이다. 인자·출력·종료 코드의 모양을 그대로 따르며
(`--dry-run`은 계획만 찍고 0, 실패는 안정 code를 담은 JSON 한 줄과 2),
다른 점은 **대상이 떠 있는 API가 아니라 격리된 workspace**라는 것뿐이다.

이 명령은 자기 프로세스의 환경을 소유한다. 격리 실행 경계 안에서만 돌고
(`BIDOPS_TEST_MODE=1` 또는 pytest), workspace 안의 SQLite와 filesystem 객체
저장소만 쓰며, 끝나면 환경과 확장점 registry를 원래대로 돌려놓는다.

판정 적재는 lifecycle 확장점의 몫이므로 `--extension-provider`로 제공자를
**이름으로** 받는다. deep_review는 선별 모듈을 import하지 않는다(명세 §4).
"""

from __future__ import annotations

import argparse
from importlib import import_module
import json
from pathlib import Path
from typing import Any, Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.deep_review.cli run-prespec-e2e",
        description="Run the isolated pre-specification mock end-to-end acceptance flow",
    )
    parser.add_argument("--fixture", type=Path, required=True, help="absolute pre-spec run fixture directory")
    parser.add_argument("--workspace", type=Path, required=True, help="absolute empty workspace directory")
    parser.add_argument("--confirm-workspace", type=Path, help="must exactly match --workspace before mutation")
    parser.add_argument("--output", type=Path, help="absolute evidence JSON path (required unless --dry-run)")
    parser.add_argument(
        "--extension-provider",
        action="append",
        default=[],
        metavar="MODULE:ATTRIBUTE",
        help="lifecycle 확장점 제공자 (예: app.screening:register_lifecycle_extensions)",
    )
    parser.add_argument("--actor-name", default="E2E 담당자", help="감사 표식으로 남길 담당자 이름")
    parser.add_argument("--dry-run", action="store_true", help="입력만 확인하고 계획을 출력한다")
    return parser


def _resolve_provider(reference: str) -> Any:
    """`모듈:이름` 문자열 하나를 등록 함수로 푼다.

    이름은 운영자가 준다. 이 파일이 어떤 모듈을 부를지 알지 않는다는 것이
    요점이며, 그래서 deep_review가 형제 모듈을 import하지 않는다.
    """

    from ..services.prespec_e2e import PreSpecE2EError

    module_name, _, attribute = reference.partition(":")
    if not module_name or not attribute:
        raise PreSpecE2EError("invalid_extension_provider", "확장점 제공자는 `모듈:이름` 형식이어야 한다")
    try:
        provider = getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as error:
        raise PreSpecE2EError("invalid_extension_provider", "확장점 제공자를 찾을 수 없다") from error
    if not callable(provider):
        raise PreSpecE2EError("invalid_extension_provider", "확장점 제공자가 호출 가능하지 않다")
    return provider


def _run(args: argparse.Namespace) -> dict[str, Any]:
    """등록·환경·engine을 세우고 인수 흐름을 한 번 돌린다."""

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from ...core.db import init_db
    from ...lifecycle import (
        extension_registry,
        reset_extension_registry,
        restore_extension_registry,
    )
    from ...deep_review import register_lifecycle_extensions as register_deep_review
    from ..services.prespec_e2e import (
        PreSpecE2EFixture,
        run_environment,
        run_prespec_e2e,
        write_evidence,
    )

    fixture = PreSpecE2EFixture.load(args.fixture.resolve())
    providers = [_resolve_provider(reference) for reference in args.extension_provider]
    workspace = args.workspace.resolve()

    previous_registry = extension_registry()
    registry = reset_extension_registry()
    try:
        for provider in providers:
            provider(registry)
        # deep_review 자신의 projection·hook은 이 명령이 등록한다. 형제 모듈은
        # 위에서 운영자가 이름으로 준 것만 등록된다.
        register_deep_review(registry)
        with run_environment(workspace):
            (workspace / "data").mkdir(parents=True, exist_ok=True)
            (workspace / "assets").mkdir(parents=True, exist_ok=True)
            engine = create_engine(f"sqlite:///{workspace / 'prespec-e2e.db'}")
            try:
                init_db(engine)
                evidence = run_prespec_e2e(
                    fixture,
                    workspace,
                    sessionmaker(bind=engine),
                    actor_name=args.actor_name,
                )
            finally:
                engine.dispose()
        write_evidence(args.output.resolve(), evidence)
    finally:
        restore_extension_registry(previous_registry)
    return evidence


def main(argv: Sequence[str] | None = None) -> int:
    from ..services.prespec_e2e import PreSpecE2EError, PreSpecE2EFixture

    args = build_parser().parse_args(argv)
    try:
        if args.dry_run:
            print(json.dumps(
                PreSpecE2EFixture.load(args.fixture.resolve()).plan(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ))
            return 0
        if args.confirm_workspace is None or args.confirm_workspace.resolve() != args.workspace.resolve():
            raise PreSpecE2EError("workspace_not_confirmed", "--confirm-workspace가 --workspace와 정확히 같아야 한다")
        if args.output is None:
            raise PreSpecE2EError("invalid_output", "변경을 만드는 실행에는 --output이 필요하다")
        evidence = _run(args)
        started = [
            notice["notice_key"]
            for notice in evidence["notices"]
            if notice.get("deep_review") and notice["deep_review"].get("created_by_actor_kind") == "system"
        ]
        waiting = [
            notice["notice_key"]
            for notice in evidence["notices"]
            if notice["auto_preparation_status"] == "deep_review_ready_for_click"
        ]
        print(json.dumps(
            {
                "passed": True,
                "workflow": evidence["workflow"],
                "evidence_file": str(args.output.resolve()),
                "notices": len(evidence["notices"]),
                "auto_started_notice_keys": started,
                "awaiting_click_notice_keys": waiting,
                "unsupported_attachments_excluded": evidence["attachments"]["unsupported_excluded"],
            },
            ensure_ascii=False,
            sort_keys=True,
        ))
        return 0
    except PreSpecE2EError as error:
        print(json.dumps(
            {"error": {"code": error.code, "message": str(error)}},
            ensure_ascii=False,
            sort_keys=True,
        ))
        return 2


__all__ = ["build_parser", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("이 명령은 `python -m app.deep_review.cli run-prespec-e2e <인자>`로 실행한다")
