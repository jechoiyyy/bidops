"""lifecycle이 프로세스 안에서 소유하는 실행 자원 (명세 §7).

lifecycle의 in-process runtime은 회차 파이프라인 실행기(`PipelineService`) 하나다.
스레드 풀은 `PipelineService` 자신이 만들고 `shutdown()`으로 거둔다. 여기서
`start()`가 하는 일은 없다 — lifecycle은 상시 worker도 스케줄러도 갖지 않는다.

조립 계층은 `build_runtime`만 부르고 내부 구성을 알지 못한다. 모듈을 고르지
않으면 이 객체는 아예 만들어지지 않고, 그러면 `app.state.pipeline_service`도
없다(§7의 `app.state` 이름 표).
"""

from __future__ import annotations

from typing import Any

from ..core import SessionLocal, Settings, get_settings
from .services.pipeline import PipelineService


class LifecycleRuntime:
    """회차 파이프라인 실행기 하나를 소유한다."""

    def __init__(self, settings: Settings | None = None, *, session_factory: Any = None) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory or SessionLocal
        self.pipeline_service = PipelineService(
            self.settings, session_factory=self.session_factory
        )
        self._shutdown = False

    def start(self) -> None:
        """lifecycle은 상시 스레드를 띄우지 않는다."""

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self.pipeline_service.shutdown(wait=True)


def build_runtime(
    settings: Settings | None = None, session_factory: Any = None
) -> LifecycleRuntime:
    """조립 계층이 부르는 lifecycle runtime 생성자 (명세 §7)."""

    return LifecycleRuntime(settings, session_factory=session_factory)


__all__ = ["LifecycleRuntime", "build_runtime"]
