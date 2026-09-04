"""screening이 프로세스 안에서 소유하는 실행 자원 (명세 §7).

C-1 판정 FIFO(불변 입력 저장소·orchestrator·worker와 그 스레드), 하나뿐인 모델
클라이언트, 스케줄러와 예약 파이프라인이 여기 있다. 조립 계층은 `build_runtime`
만 부르고 내부 구성을 알지 못한다.

지켜지는 불변 조건:

- worker는 항상 살아 있고 스케줄러는 `BIDOPS_SCHEDULER_ENABLED`가 켜졌을 때만
  start한다(기본 비활성, §9).
- 프로세스당 모델 슬롯은 하나다. orchestrator와 worker가 **같은** 클라이언트를
  나눠 쓴다.
- 새 worker가 FIFO를 잡기 전에 `recover_stale()`이 먼저 돈다.

`RuntimePipelineBridge`는 skill 스크립트를 subprocess로 부르고 그 산출물을
lifecycle의 `ingest_run`으로 적재한다. 방향은 screening → lifecycle 공개 이름
이며(§4 허용), skill 구현 코드는 import하지 않는다.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import subprocess
import threading
from typing import Any

from ..core import SessionLocal, Settings, get_settings, parse_run_id
from ..lifecycle import ingest_run
from .execution_store import ScreeningExecutionStore
from .mock_transport import MockScreeningTransport
from .ollama import OllamaClient
from .orchestrator import ScreeningOrchestrator
from .services.scheduled_pipeline import ScheduledPipeline
from .services.scheduler import SchedulerService
from .worker import ScreeningWorker


logger = logging.getLogger(__name__)


class RuntimePipelineBridge:
    """Invoke the existing skill scripts and ingest their artifacts.

    The bridge is intentionally a subprocess/file-contract adapter: it never
    imports skill implementation code and it leaves model work to the shared
    screening FIFO worker.
    """

    def __init__(self, settings: Settings, session_factory: Any) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def _run(self, command: list[str]) -> bool:
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.settings.bidops_root),
                env=None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=max(1, self.settings.model_timeout),
            )
            return completed.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _run_directory(self, run_id: str) -> Path:
        parsed = parse_run_id(run_id)
        name = parsed[0] if parsed else run_id.split("--", 1)[0]
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("invalid scheduled run id")
        return Path(self.settings.bidops_root) / "data" / "runs" / name

    def _ingest(self, directory: Path) -> dict[str, Any]:
        with self.session_factory() as session:
            result = ingest_run(directory, session, reports_root=self.settings.bidops_root / "reports")
            session.commit()
            return {"status": "success", "run_id": result.run_id, "candidate_count": result.notices, "result_count": result.judgments}

    def run_stage(self, stage: str, **kwargs: Any) -> dict[str, Any]:
        run_id = kwargs.get("run_id")
        run_key = kwargs.get("run_key")
        try:
            if stage == "collect":
                run_id = str(run_key)
                directory = self._run_directory(run_id)
                directory.mkdir(parents=True, exist_ok=True)
                ok = self._run([
                    "python3", "skills/bidops-collect/scripts/collect_notices.py",
                    "--from-date", kwargs["window_from"].isoformat(),
                    "--to-date", kwargs["window_to"].isoformat(),
                    "--output-dir", str(directory),
                ])
                return self._ingest(directory) if ok else {"status": "failed", "failure_reason": "collect_failed"}
            if not isinstance(run_id, str):
                return {"status": "failed", "failure_reason": f"{stage}_run_missing"}
            directory = self._run_directory(run_id)
            if stage == "sample":
                ok = self._run([
                    "python3", "skills/bidops-collect/scripts/select_validation_sample.py",
                    str(directory / "collected-notices.json"), "--output", str(directory / "validation-set.json"),
                ])
                return {"status": "success", "run_id": run_id} if ok else {"status": "failed", "failure_reason": "sample_failed"}
            if stage == "merge_load":
                screening_id = kwargs.get("screening_execution_id")
                if not isinstance(screening_id, str):
                    return {"status": "failed", "failure_reason": "merge_load_run_missing"}
                execution_dir = Path(self.settings.bidops_root) / "data" / "screening-executions" / screening_id
                decisions = execution_dir / "screening-decisions.json"
                failures = execution_dir / "screening-failures.json"
                command = [
                    "python3", "skills/bidops-screen/scripts/build_screening_results.py",
                    str(execution_dir / "screening-input.json"), str(decisions), "--output", str(directory / "screening-results.json"),
                ]
                # The v3 merge consumes the frozen screening input.  A failure
                # artifact is optional for a fully successful execution.
                if failures.is_file():
                    command[4:4] = ["--failures", str(failures)]
                ok = self._run(command)
                return self._ingest(directory) if ok else {"status": "failed", "failure_reason": "merge_load_failed"}
            if stage == "report":
                ok = self._run([
                    "python3", "skills/bidops-report/scripts/render_report.py",
                    str(directory / "screening-results.json"), "--output-dir",
                    str(self.settings.bidops_root / "reports" / directory.name),
                ])
                return {"status": "success", "run_id": run_id} if ok else {"status": "failed", "failure_reason": "report_failed"}
            if stage == "weekly_report":
                return {"status": "success", "run_id": run_id}
        except (OSError, ValueError, KeyError, TypeError):
            logger.error(
                "runtime stage failed",
                extra={
                    "bidops": {
                        "event": "runtime.stage_failed",
                        "stage": stage,
                        "run_id": run_id,
                    }
                },
                exc_info=True,
            )
        return {"status": "failed", "failure_reason": f"{stage}_failed"}


class ScreeningRuntime:
    """Own one queue/store/orchestrator/worker and one scheduler lifecycle."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: Any = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory or SessionLocal
        self.store = ScreeningExecutionStore(session_factory=self.session_factory, settings=self.settings)
        transport = MockScreeningTransport() if self.settings.screening_provider == "mock" else None
        self.ollama = OllamaClient(settings=self.settings, transport=transport)
        self.orchestrator = ScreeningOrchestrator(
            self.settings,
            session_factory=self.session_factory,
            queue=self.store,
            ollama=self.ollama,
        )
        self.worker = ScreeningWorker(
            self.settings,
            store=self.store,
            session_factory=self.session_factory,
            ollama=self.ollama,
        )
        self._schedule_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bidops-schedule")
        self.scheduler_service = SchedulerService(
            self.settings,
            session_factory=self.session_factory,
            ollama=self.ollama,
            on_daily=lambda execution_id: self.dispatch_schedule(execution_id, "daily"),
            on_weekly=lambda execution_id: self.dispatch_schedule(execution_id, "weekly"),
        )
        self.scheduled_pipeline = ScheduledPipeline(
            self.settings,
            session_factory=self.session_factory,
            scheduler=self.scheduler_service,
            pipeline=RuntimePipelineBridge(self.settings, self.session_factory),
            orchestrator=self.orchestrator,
            worker=self.worker,
            ollama=self.ollama,
        )
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self._started = False
        self._shutdown = False
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._shutdown = False
            # Recovery must happen before a new worker can claim the FIFO.
            self.store.recover_stale()
            self.stop_event.clear()
            self.worker_thread = threading.Thread(
                target=self.worker.run_forever,
                args=(self.stop_event,),
                name="bidops-screening-worker",
                daemon=True,
            )
            self.worker_thread.start()
            # The worker is always live.  The scheduler is only a clock source
            # and is constrained by the environment safety switch.
            if self.settings.scheduler_enabled:
                self.scheduler_service.start()
            self._started = True

    def dispatch_schedule(self, execution_id: str, job_kind: str) -> None:
        if self._shutdown:
            return
        callback = self.scheduled_pipeline.run_daily if job_kind == "daily" else self.scheduled_pipeline.run_weekly
        self._schedule_executor.submit(callback, execution_id)

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self.stop_event.set()
            try:
                self.scheduler_service.shutdown(wait=False)
            finally:
                thread = self.worker_thread
                if thread is not None and thread.is_alive():
                    thread.join(timeout=5.0)
                self._schedule_executor.shutdown(wait=True, cancel_futures=False)
                self._started = False


def build_runtime(
    settings: Settings | None = None,
    session_factory: Any = None,
) -> ScreeningRuntime:
    """조립 계층이 부르는 screening runtime 생성자 (명세 §7)."""

    return ScreeningRuntime(settings, session_factory=session_factory)


__all__ = ["RuntimePipelineBridge", "ScreeningRuntime", "build_runtime"]
