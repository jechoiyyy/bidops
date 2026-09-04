"""`python -m app.screening.cli`의 진입점.

T7 2단계가 `app/screening/cli.py`를 패키지로 바꾸면서, 기존 명령 문자열과
인자를 그대로 유지하려고 둔 파일이다.
"""

from __future__ import annotations

from .run_one import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
