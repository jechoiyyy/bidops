"""Command line entry point for Step 2 artifact ingestion.

이 명령은 **web 프로세스와 같은 회차 적재**를 해야 한다. `loader`는
`extension_registry()` 싱글턴에 등록된 hook만 부르므로(`_run_ingested_hooks`),
등록이 비어 있는 프로세스에서는 판정·리뷰가 적재되지 않고 회차에
`judgment_ingest_skipped` 경고가 남는다. 그 경고 하나가 C-2 실행 생성의
source run 검사(`source_run_incomplete`)를 막으므로, CLI로 적재한 회차는
일일 발주계획 트랙에서 쓸 수 없었다.

그래서 이 진입점은 `create_app`과 **같은 선택**(`BIDOPS_MODULES`)으로 확장점
제공자를 등록한다. lifecycle은 형제 모듈을 import하지 않으므로(명세 §4)
`app.deep_review.cli run-prespec-e2e`와 같은 방식으로 `모듈:이름`을 런타임에
푼다 — 이름은 설정이 주고, 이 파일은 어떤 모듈이 무엇을 등록하는지 알지 않는다.
등록은 owner 키로 제자리 교체되므로 멱등이고, 등록 자체는 migration·seed·정책
활성화·모델 호출을 하지 않는다(§9).
"""

from __future__ import annotations

import argparse
from importlib import import_module
import json
import sys
from pathlib import Path
from typing import Any

from ...core.config import get_settings
from ...core.db import SessionFactory, init_db
from .loader import discover_run_dirs, ingest_run, tracked_backfill


#: 확장점 등록 함수의 이름. 모든 제공자 모듈이 같은 이름으로 공개한다.
EXTENSION_PROVIDER_ATTRIBUTE = "register_lifecycle_extensions"

#: registry를 소유할 뿐 채우지 않는 모듈 (`create_app`의 `_EXTENSION_PROVIDERS`와
#: 같은 뜻을 반대쪽에서 쓴 것이다 — 여기서는 제외 목록이 자기 자신뿐이다).
_REGISTRY_OWNER_MODULE = "lifecycle"


def register_configured_extensions(registry: Any | None = None) -> tuple[str, ...]:
    """`BIDOPS_MODULES`가 고른 모듈의 확장점을 등록하고 그 이름을 돌려준다.

    선택된 모듈 중 lifecycle 자신을 뺀 나머지는 모두 확장점 제공자다. 제공자를
    찾지 못하면 **fail closed** — 조용히 건너뛰면 지금 고치는 결함(등록 없는
    프로세스가 경고만 남기고 성공으로 끝난다)이 그대로 되살아난다.
    """

    from ..extensions import extension_registry

    if registry is None:
        registry = extension_registry()
    root_package = (__package__ or "app.lifecycle.ingest").split(".")[0]
    registered: list[str] = []
    for module_name in get_settings().modules:
        if module_name == _REGISTRY_OWNER_MODULE:
            continue
        module = import_module(f"{root_package}.{module_name}")
        provider = getattr(module, EXTENSION_PROVIDER_ATTRIBUTE, None)
        if not callable(provider):
            raise RuntimeError(
                f"모듈 {module_name}에 확장점 등록 함수 "
                f"{EXTENSION_PROVIDER_ATTRIBUTE}가 없습니다"
            )
        provider(registry)
        registered.append(module_name)
    return tuple(registered)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load BidOps workflow artifacts into SQLite.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run", dest="run_id", help="one run directory, e.g. 20260817-20260823")
    group.add_argument("--all", action="store_true", help="ingest every directory under data/runs")
    parser.add_argument(
        "--collection",
        action="store_true",
        help=(
            "with --run: index every collected record and load only the selected ones "
            "instead of the validation sample"
        ),
    )
    parser.add_argument(
        "--tracked-backfill",
        action="store_true",
        help=(
            "load index-only records referenced by 계속 추적·보류 opportunities; "
            "runs after --run when both are given"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.tracked_backfill and args.all:
        parser.error("--tracked-backfill은 --all과 함께 쓸 수 없습니다")
    if args.collection and not args.run_id:
        parser.error("--collection은 --run과 함께 씁니다")
    if not (args.run_id or args.all or args.tracked_backfill):
        parser.error("--run, --all, --tracked-backfill 중 하나가 필요합니다")
    settings = get_settings()
    # 적재 전에 등록한다. 등록이 모듈 `models`를 들이므로 격리 SQLite 경계에서
    # `init_db`가 만드는 table 집합도 web 프로세스와 같아진다.
    registered = register_configured_extensions()
    # stdout은 호출 스크립트가 JSON으로 파싱한다. 진단 한 줄은 stderr로 낸다.
    print(f"extensions: {', '.join(registered) or '(없음)'}", file=sys.stderr)
    init_db()
    data_root = settings.bidops_root / "data"
    run_dirs: list[Path] = []
    if args.run_id or args.all:
        run_dirs = discover_run_dirs(data_root, args.run_id if not args.all else None)
        if args.run_id and not run_dirs:
            parser.error(f"회차 디렉토리를 찾을 수 없습니다: {args.run_id}")
    results = []
    backfill: dict[str, object] | None = None
    with SessionFactory() as session:
        for run_directory in run_dirs:
            result = ingest_run(
                run_directory,
                session,
                reports_root=settings.bidops_root / "reports",
                selection="collection" if args.collection else "validation",
            )
            results.append(result.as_dict())
        if args.tracked_backfill:
            try:
                backfill = tracked_backfill(session, runs_root=data_root / "runs")
                session.commit()
            except Exception:
                session.rollback()
                raise
    if args.all:
        output: object = results
    elif args.run_id:
        output = results[0]
        if backfill is not None:
            output = {**results[0], "tracked_backfill": backfill}
    else:
        output = {"tracked_backfill": backfill}
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
