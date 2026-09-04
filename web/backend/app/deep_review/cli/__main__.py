"""`python -m app.deep_review.cli`의 진입점.

하위 명령 dispatch는 `__init__`이 소유한다.
"""

from __future__ import annotations

from . import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
