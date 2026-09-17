"""형제 도메인 모듈 없이도 mapper 구성이 성공하는지 검사한다 (명세 §2.6·§4).

§4는 "lifecycle 모델은 다른 모듈의 모델로 향하는 `relationship`을 갖지 않는다.
관계는 소유 모듈이 자기 모델에서 단방향으로 선언한다. 이렇게 해야 어느 모듈을
import하지 않아도 mapper 구성이 성공한다"고 못박았다. 이 파일이 그 문장을
실행으로 확인한다.

같은 프로세스 안에서는 앞선 test module이 이미 네 모듈을 모두 `Base.registry`에
등록했을 수 있어 부분 집합을 만들 수 없다. 그래서 검사마다 **새 인터프리터**를
띄워 지정한 models만 import하고 `configure_mappers()`를 부른다. 두 가지를 함께
본다.

1. `configure_mappers()`가 성공한다 — 풀 수 없는 relationship 문자열이 없다.
2. 등록된 테이블 집합이 그 모듈들의 소유 테이블 합집합과 **정확히** 같다 —
   어느 모듈이 형제 모듈을 조용히 끌어오지 않는다.

되돌아온 교차 relationship은 1이나 2 중 하나에서 반드시 걸린다. lifecycle이
`Mapped["Judgment"]`를 다시 가지면 lifecycle 단독 실행에서 1이 깨지고,
lifecycle이 screening models를 import하면 2가 깨진다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from . import boundary_map as bmap

BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: 모듈 → 그 models를 import했을 때 함께 들어오는 모듈들(자기 자신 포함).
#: core는 아무도 import하지 않고, screening·deep_review는 lifecycle 모델을 읽기
#: 방향으로 import한다(§4).
CLOSURE: dict[str, frozenset[str]] = {
    bmap.CORE: frozenset({bmap.CORE}),
    bmap.LIFECYCLE: frozenset({bmap.CORE, bmap.LIFECYCLE}),
    bmap.SCREENING: frozenset({bmap.CORE, bmap.LIFECYCLE, bmap.SCREENING}),
    bmap.DEEP_REVIEW: frozenset({bmap.CORE, bmap.LIFECYCLE, bmap.DEEP_REVIEW}),
}

_PROBE = """
import importlib, json, sys

for name in sys.argv[1:]:
    importlib.import_module(name)

from sqlalchemy.orm import configure_mappers

configure_mappers()

from app.core.db import Base

print(json.dumps(sorted(Base.metadata.tables)))
"""


def _tables_owned_by(modules: frozenset[str]) -> set[str]:
    return {table for table, owner in bmap.TABLE_OWNER.items() if owner in modules}


def _configure_in_fresh_interpreter(modules: tuple[str, ...], tmp_path: Path) -> list[str]:
    """새 인터프리터에서 주어진 모듈의 models만 import하고 mapper를 구성한다."""

    environment = dict(os.environ)
    # DB에 붙지 않는다. import 시점의 engine 생성과 data_dir 준비만 만족시킨다.
    environment.update(
        {
            "BIDOPS_DATA_DIR": str(tmp_path / "data"),
            "BIDOPS_ATTACHMENTS_DIR": str(tmp_path / "attachments"),
            "BIDOPS_DATABASE_URL": f"sqlite:///{(tmp_path / 'isolation.db').as_posix()}",
            "PYTHONPATH": str(BACKEND_ROOT),
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, *(f"app.{name}.models" for name in modules)],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, (
        f"{modules}만 import한 인터프리터에서 mapper 구성이 실패했다. "
        "다른 모듈의 모델로 향하는 relationship이 돌아왔는지 확인한다.\n"
        f"{completed.stderr[-4000:]}"
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    "modules",
    [
        (bmap.CORE,),
        (bmap.LIFECYCLE,),
        (bmap.SCREENING,),
        (bmap.DEEP_REVIEW,),
        (bmap.SCREENING, bmap.DEEP_REVIEW),
    ],
    ids=["core", "lifecycle", "screening", "deep_review", "screening+deep_review"],
)
def test_mappers_configure_without_the_sibling_modules(
    modules: tuple[str, ...], tmp_path: Path
) -> None:
    registered = _configure_in_fresh_interpreter(modules, tmp_path)

    expected_modules = frozenset().union(*(CLOSURE[name] for name in modules))
    assert set(registered) == _tables_owned_by(expected_modules), (
        f"{modules}만 import했는데 등록된 테이블 집합이 다르다. "
        "형제 모듈을 끌어오는 import가 생겼는지 확인한다."
    )


def test_the_four_modules_together_declare_the_whole_schema(tmp_path: Path) -> None:
    """네 모듈을 모두 들이면 스키마 전체가 그대로 나온다."""

    registered = _configure_in_fresh_interpreter(
        (bmap.CORE, bmap.LIFECYCLE, bmap.SCREENING, bmap.DEEP_REVIEW), tmp_path
    )

    assert len(registered) == 77
    assert set(registered) == set(bmap.TABLE_OWNER)
