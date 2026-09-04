"""deep_review의 in-process runtime 자리 (명세 §7).

deep_review는 API 프로세스 안에서 스레드도 스케줄러도 소유하지 않는다. 문서
준비·심층 검토·첨부 fetch는 모두 **별도 worker 프로세스**(`python -m
app.deep_review.workers.*`)가 하고, 그 프로세스는 자기 진입점에서 자원을
만든다. 그래서 여기 있는 runtime은 비어 있다.

조립 계층이 세 모듈을 같은 모양으로 다루도록 빈 객체를 두었다. deep_review가
나중에 in-process 자원을 갖게 되면 그 자리는 여기다 — 조립 계층은 바뀌지 않는다.
"""

from __future__ import annotations

from typing import Any

from ..core import Settings


class DeepReviewRuntime:
    """만들고 거둘 in-process 자원이 없다."""

    def __init__(self, settings: Settings | None = None, *, session_factory: Any = None) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def start(self) -> None:
        """별도 worker 프로세스가 하므로 여기서 띄울 것이 없다."""

    def shutdown(self) -> None:
        """거둘 자원이 없다."""


def build_runtime(
    settings: Settings | None = None, session_factory: Any = None
) -> DeepReviewRuntime:
    """조립 계층이 부르는 deep_review runtime 생성자 (명세 §7)."""

    return DeepReviewRuntime(settings, session_factory=session_factory)


__all__ = ["DeepReviewRuntime", "build_runtime"]
