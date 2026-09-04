"""모듈 공개 표면 표가 실제 이름을 가리키는지 검사한다 (명세 §3·§4).

`app/lifecycle`·`app/screening`·`app/deep_review`의 `__init__.py`는 import 시점에
아무것도 끌어오지 않는다. `{공개 이름: (모듈, 속성)}` 표를 두고 모듈 `__getattr__`
가 처음 접근할 때 해석한다. 그래야 패키지 초기화가 하위 모듈을 거쳐 자기에게 돌아오는
순환이 생기지 않는다.

지연 해석의 대가는 **표의 오타가 import 시점에 드러나지 않는다**는 것이다. 대상 모듈의
이름이 바뀌거나 사라져도 그 이름을 실제로 만지는 코드가 돌 때까지 조용하다. 이 파일이
표를 전부 한 번씩 해석해 그 틈을 막는다. 경계 허용 목록이 stale 항목을 실패시키는 것과
같은 취지다.

`app/core`는 지연 공개가 아니라 평범한 eager import + `__all__`이므로 그 대조만 한다.
"""

from __future__ import annotations

from importlib import import_module

import pytest


LAZY_MODULES = ("lifecycle", "screening", "deep_review")


@pytest.mark.parametrize("module_name", LAZY_MODULES)
def test_every_export_resolves(module_name: str) -> None:
    """`_EXPORTS`의 모든 이름이 실제로 해석된다."""

    package = import_module(f"app.{module_name}")
    exports = getattr(package, "_EXPORTS", None)
    assert exports, f"app.{module_name}에 `_EXPORTS` 표가 없다."

    unresolved: dict[str, str] = {}
    for name, target in exports.items():
        try:
            getattr(package, name)
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 표의 결함이다
            unresolved[name] = f"{target} -> {type(exc).__name__}: {exc}"

    assert not unresolved, (
        f"app.{module_name}의 공개 이름이 해석되지 않는다. 대상 모듈에서 이름이 "
        "바뀌었거나 사라졌다. `_EXPORTS` 표를 실제와 맞춘다.\n"
        + "\n".join(f"  {name}: {why}" for name, why in sorted(unresolved.items()))
    )


@pytest.mark.parametrize("module_name", LAZY_MODULES)
def test_all_covers_the_exports_table(module_name: str) -> None:
    """`__all__`이 `_EXPORTS`를 모두 담고, 그 밖의 이름은 `__init__`이 직접 정의한다.

    `register_lifecycle_extensions`처럼 `__init__.py` 본문에 정의한 함수는 표에 없는
    것이 맞다. 반대로 표에 있는데 `__all__`에 없으면 `from app.<module> import *`에서만
    사라져 두 경로의 공개 표면이 갈린다.
    """

    package = import_module(f"app.{module_name}")
    exported = set(package.__all__)
    table = set(package._EXPORTS)

    assert table <= exported, (
        f"app.{module_name}의 `_EXPORTS`에 있는데 `__all__`에 없는 이름이 있다: "
        f"{sorted(table - exported)}"
    )
    directly_defined = exported - table
    missing = [name for name in sorted(directly_defined) if name not in vars(package)]
    assert not missing, (
        f"app.{module_name}의 `__all__`에 있는데 표에도 없고 `__init__.py`가 직접 "
        f"정의하지도 않은 이름이 있다: {missing}"
    )


@pytest.mark.parametrize("module_name", LAZY_MODULES)
def test_importing_the_package_pulls_in_no_submodule(module_name: str) -> None:
    """패키지 import 자체가 하위 모듈을 끌어오지 않는다 (순환 방지의 실체)."""

    import subprocess
    import sys

    probe = (
        "import sys, json;"
        f"import app.{module_name};"
        f"print(json.dumps([m for m in sys.modules if m.startswith('app.{module_name}.')]))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    pulled = sorted(m for m in eval(completed.stdout.strip().splitlines()[-1]))
    assert not pulled, (
        f"`import app.{module_name}` 만으로 하위 모듈이 딸려 왔다: {pulled}. "
        "`__init__.py`가 import 시점에 무언가를 끌어오면 순환 import가 돌아온다."
    )


def test_core_exports_resolve() -> None:
    """`app.core`는 eager 공개다. `__all__`의 이름이 전부 실재한다."""

    package = import_module("app.core")
    missing = [name for name in package.__all__ if not hasattr(package, name)]
    assert not missing, f"app.core의 `__all__`에 없는 이름이 있다: {missing}"
