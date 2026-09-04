"""screening의 서버측 관리 CLI 명령.

`run_one` 이 `python -m app.screening.cli`의 본체이고, `score_candidate_quality`
는 자기 이름으로 실행하는 별도 명령이다. 두 명령을 하나의 하위 명령 체계로
합치는 것은 T8 몫이다.

`main`·`build_parser`는 이름으로 가려 내보낸다. 패키지를 import하는 것만으로
orchestrator·worker까지 끌어오면 `python -m app.screening.cli.score_candidate_quality`
가 필요 없는 모듈을 지고 시작하기 때문이다.
"""

from __future__ import annotations

from importlib import import_module

_RUN_ONE_EXPORTS = {"build_parser", "main"}


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in _RUN_ONE_EXPORTS:
        return getattr(import_module(".run_one", __name__), name)
    raise AttributeError(name)


__all__ = sorted(_RUN_ONE_EXPORTS)
