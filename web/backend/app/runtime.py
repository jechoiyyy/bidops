"""모듈별 in-process runtime의 조립 (명세 §7).

상시 자원은 이제 소유 모듈이 만든다. lifecycle은 회차 파이프라인 실행기를,
screening은 C-1 판정 FIFO(store·orchestrator·worker와 그 스레드)·모델 클라이언트·
스케줄러·예약 파이프라인을 소유하고, deep_review는 API 프로세스 안에 자원을 갖지
않는다(별도 worker 프로세스가 한다).

이 파일이 하는 일은 셋뿐이다.

1. `BIDOPS_MODULES`가 고른 모듈의 `build_runtime`을 **지정 순서대로** 부른다.
2. router가 쓰는 이름을 그 모듈 runtime으로 넘겨 준다. 고르지 않은 모듈의
   이름은 존재하지 않으므로 `hasattr`가 False이고, 그러면 `main.py`의 lifespan이
   `app.state`에 올리지 않는다(§7의 `app.state` 이름 표).
3. `start()`는 지정 순서대로, `shutdown()`은 그 역순으로 부른다.

API 모듈은 FastAPI lifespan에서만 이 객체를 만든다. router를 import하는 것이
스레드나 모델 연결이나 스케줄러 job을 만들지 않는다(§9).
"""

from __future__ import annotations

from typing import Any

from .core import SessionLocal, Settings, get_settings
from . import deep_review, lifecycle, screening


#: 모듈 이름 → 그 모듈의 공개 표면.
_MODULE_PACKAGES = {
    "lifecycle": lifecycle,
    "screening": screening,
    "deep_review": deep_review,
}

#: runtime 객체 위의 이름 → 그것을 소유한 모듈 (§7).
#:
#: `main.py`의 lifespan이 이 이름들을 읽어 `app.state`에 올린다. `store`·
#: `orchestrator`·`worker`는 `app.state`에서 `screening_` 접두사를 달지만 runtime
#: 위에서는 지금 이름 그대로다 — 그 대응표는 lifespan이 갖는다.
_DELEGATED_NAMES: dict[str, str] = {
    "pipeline_service": "lifecycle",
    "store": "screening",
    "orchestrator": "screening",
    "worker": "screening",
    "worker_thread": "screening",
    "stop_event": "screening",
    "ollama": "screening",
    "scheduler_service": "screening",
    "scheduled_pipeline": "screening",
    "dispatch_schedule": "screening",
}


class ApplicationRuntime:
    """지정한 모듈의 runtime을 만들어 함께 start·shutdown한다."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: Any = None,
        modules: Any = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory or SessionLocal
        self.modules: tuple[str, ...] = (
            tuple(modules) if modules is not None else self.settings.modules
        )
        self._runtimes: list[tuple[str, Any]] = []
        self._by_module: dict[str, Any] = {}
        # lifecycle의 회차 파이프라인 실행기는 screening의 예약 파이프라인이
        # 소유 관계로 들고 있는 것이라 만들어진 뒤에 넘긴다. lifecycle을 함께
        # 고르지 않으면 ``None``이고, 그 adapter는 subprocess·파일 계약으로만
        # 단계를 돌리므로 그대로 동작한다.
        pipeline: Any = None
        for name in self.modules:
            package = _MODULE_PACKAGES[name]
            if name == "screening":
                runtime = package.build_runtime(
                    self.settings, self.session_factory, pipeline=pipeline
                )
            else:
                runtime = package.build_runtime(self.settings, self.session_factory)
            if name == "lifecycle":
                pipeline = runtime.pipeline_service
            self._runtimes.append((name, runtime))
            self._by_module[name] = runtime
        self._started = False
        self._shutdown = False

    def __getattr__(self, name: str) -> Any:
        # `__getattr__`은 보통 조회가 실패했을 때만 불린다. 고르지 않은 모듈의
        # 이름은 여기서 AttributeError가 되고, 그래서 `hasattr`가 False다.
        owner = _DELEGATED_NAMES.get(name)
        if owner is not None:
            runtime = self.__dict__.get("_by_module", {}).get(owner)
            if runtime is not None:
                return getattr(runtime, name)
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r} "
            f"(등록된 모듈: {self.__dict__.get('modules', ())})"
        )

    def runtime_for(self, module: str) -> Any:
        """모듈 runtime을 낸다. 고르지 않은 모듈이면 ``None``."""

        return self._by_module.get(module)

    def start(self) -> None:
        if self._started:
            return
        self._shutdown = False
        started: list[Any] = []
        try:
            for _name, runtime in self._runtimes:
                runtime.start()
                started.append(runtime)
        except Exception:
            for runtime in reversed(started):
                runtime.shutdown()
            raise
        self._started = True

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        # start의 역순으로 거둔다: screening의 worker·스케줄러가 먼저 멈추고
        # 그다음 lifecycle의 파이프라인 스레드 풀이 닫힌다.
        #
        # 앞 모듈의 shutdown이 실패해도 **뒤 모듈까지 반드시 거둔다.** 이주 전
        # `ApplicationRuntime.shutdown`은 scheduler 종료를 `try`에, worker join과
        # 스레드 풀 정리를 `finally`에 두어 그것을 보장했다. 모듈로 나뉜 뒤 단순
        # 반복문으로 두면 screening이 던질 때 lifecycle의 `PipelineService` 스레드
        # 풀이 회수되지 않는다. 첫 예외는 전부 거둔 뒤 다시 던진다.
        failure: BaseException | None = None
        for _name, runtime in reversed(self._runtimes):
            try:
                runtime.shutdown()
            except BaseException as exc:  # noqa: BLE001 - 남은 모듈을 마저 거둔다
                if failure is None:
                    failure = exc
        self._started = False
        if failure is not None:
            raise failure


__all__ = ["ApplicationRuntime"]
