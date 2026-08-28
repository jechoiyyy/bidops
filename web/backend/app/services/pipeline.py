"""Run the existing BidOps skill scripts as isolated background processes."""

from __future__ import annotations

import os
import subprocess
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from ..config import Settings, get_settings
from ..db import SessionFactory
from ..ingest.loader import ingest_run, parse_run_id
from ..models import Run
from ..redaction import mask_secrets


PIPELINE_STAGES = {"collect", "sample", "report"}
JUDGMENT_STAGE = "judgment"


class PipelineBusyError(RuntimeError):
    """Raised when another process already owns the same source run."""

    def __init__(self, execution_id: str):
        super().__init__("같은 회차에서 이미 파이프라인 실행이 진행 중입니다.")
        self.execution_id = execution_id


class PipelineInputError(ValueError):
    """Raised before a subprocess is started when its input is not safe/valid."""


@dataclass(frozen=True)
class PipelineLogLine:
    timestamp: datetime
    stream: str
    level: str
    message: str


@dataclass
class PipelineExecution:
    execution_id: str
    source_run_id: str
    stage: str
    command: tuple[str, ...]
    target_directory: Path
    result_run_id: str | None = None
    from_raw: bool = False
    status: str = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lines: list[PipelineLogLine] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def add_line(self, stream: str, message: str, secrets: tuple[str, ...]) -> None:
        cleaned = mask_secrets(message.rstrip("\r\n"), secrets)
        if not cleaned:
            return
        upper = cleaned.upper()
        if "WARN" in upper:
            level = "warning"
        elif "ERROR" in upper or "TRACEBACK" in upper or stream == "stderr":
            level = "error"
        else:
            level = "info"
        with self.lock:
            self.lines.append(
                PipelineLogLine(
                    timestamp=datetime.now(timezone.utc),
                    stream=stream,
                    level=level,
                    message=cleaned,
                )
            )


def _secret_values(settings: Settings) -> tuple[str, ...]:
    """Collect likely secret values without ever putting the environment in a response."""

    values: set[str] = set()
    if settings.g2b_api_key:
        values.add(settings.g2b_api_key)
    for name, value in os.environ.items():
        upper = name.upper()
        if any(marker in upper for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and value:
            values.add(value)
    return tuple(sorted((value for value in values if len(value) >= 4), key=len, reverse=True))


def _level_for(message: str, stream: str) -> str:
    upper = message.upper()
    if "WARN" in upper:
        return "warning"
    if "ERROR" in upper or "TRACEBACK" in upper or stream == "stderr":
        return "error"
    return "info"


class PipelineService:
    """A small process runner with per-run locking and line-oriented logs.

    The service intentionally calls the files in ``skills/`` instead of importing
    their implementation.  This keeps the skill workflow and the web workflow
    on the same executable contract.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        session_factory: Callable[..., Any] = SessionFactory,
    ) -> None:
        self.settings = settings or get_settings()
        self._popen = popen
        self._session_factory = session_factory
        # Do not allocate worker threads while importing the API module.  The
        # lifespan owns service lifetime; the first requested subprocess gets
        # a lazily-created executor.
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.RLock()
        self._executions: dict[str, PipelineExecution] = {}
        self._active_by_run: dict[str, str] = {}
        self._futures: dict[str, Future[Any]] = {}

    def start(self, run: Run, stage: str, *, from_raw: bool = False) -> PipelineExecution:
        if stage == JUDGMENT_STAGE:
            raise PipelineInputError("판정 단계는 애플리케이션에서 실행하지 않습니다.")
        if stage not in PIPELINE_STAGES:
            raise PipelineInputError(f"지원하지 않는 파이프라인 단계입니다: {stage}")
        if from_raw and stage != "collect":
            raise PipelineInputError("--from-raw는 수집 단계에서만 사용할 수 있습니다.")

        source_directory = self._run_directory(run)
        if not source_directory.is_dir():
            raise PipelineInputError("회차 산출물 디렉토리를 찾을 수 없습니다.")
        with self._lock:
            active_id = self._active_by_run.get(run.id)
            if active_id:
                active = self._executions.get(active_id)
                if active and active.status in {"pending", "running"}:
                    raise PipelineBusyError(active_id)
                self._active_by_run.pop(run.id, None)

            target_directory = source_directory
            if stage == "collect":
                target_directory = self._new_snapshot_directory(source_directory)
                if from_raw:
                    self._link_preserved_raw(source_directory, target_directory)

            command = self._command(
                run,
                stage,
                target_directory,
                from_raw=from_raw,
            )
            execution = PipelineExecution(
                execution_id=f"pipe-{uuid.uuid4().hex}",
                source_run_id=run.id,
                stage=stage,
                command=tuple(command),
                target_directory=target_directory,
                from_raw=from_raw,
            )
            self._executions[execution.execution_id] = execution
            self._active_by_run[run.id] = execution.execution_id
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bidops-pipeline")
            self._futures[execution.execution_id] = self._executor.submit(self._execute, execution)
            return execution

    def shutdown(self, *, wait: bool = True) -> None:
        """Release subprocess executor resources; safe to call repeatedly."""

        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=False)

    def get(self, execution_id: str) -> PipelineExecution | None:
        with self._lock:
            return self._executions.get(execution_id)

    def latest_for(self, run_id: str, stage: str) -> PipelineExecution | None:
        with self._lock:
            candidates = [
                item
                for item in self._executions.values()
                if item.stage == stage
                and (item.source_run_id == run_id or item.result_run_id == run_id)
            ]
        return max(candidates, key=lambda item: item.created_at, default=None)

    def logs_for(self, run_id: str, execution_id: str | None = None) -> list[PipelineExecution]:
        with self._lock:
            if execution_id:
                item = self._executions.get(execution_id)
                if item is None:
                    return []
                if run_id not in {item.source_run_id, item.result_run_id}:
                    return []
                return [item]
            return sorted(
                (
                    item
                    for item in self._executions.values()
                    if run_id in {item.source_run_id, item.result_run_id}
                ),
                key=lambda item: item.created_at,
            )

    def wait(self, execution_id: str, timeout: float | None = None) -> PipelineExecution | None:
        future = self._futures.get(execution_id)
        if future is None:
            return None
        future.result(timeout=timeout)
        return self.get(execution_id)

    def _run_directory(self, run: Run) -> Path:
        parsed = parse_run_id(run.id)
        directory_name = parsed[0] if parsed else run.id.split("--", 1)[0]
        if Path(directory_name).name != directory_name or directory_name in {"", ".", ".."}:
            raise PipelineInputError("회차 디렉토리 식별자가 올바르지 않습니다.")
        return self.settings.bidops_root / "data" / "runs" / directory_name

    def _new_snapshot_directory(self, source_directory: Path) -> Path:
        runs_root = source_directory.parent
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        for _ in range(10):
            name = f"{source_directory.name}-rerun-{stamp}-{uuid.uuid4().hex[:8]}"
            target = runs_root / name
            try:
                target.mkdir(parents=False, exist_ok=False)
                return target
            except FileExistsError:
                continue
        raise PipelineInputError("새 회차 디렉토리를 만들지 못했습니다.")

    @staticmethod
    def _link_preserved_raw(source_directory: Path, target_directory: Path) -> None:
        raw_directory = source_directory / "raw"
        if not raw_directory.is_dir():
            raise PipelineInputError("재분류할 보존 원문 페이지가 없습니다.")
        # The script reads this directory and writes all new JSON next to it.  A
        # directory symlink avoids copying or modifying the preserved raw pages.
        (target_directory / "raw").symlink_to(raw_directory, target_is_directory=True)

    def _window(self, run: Run, source_directory: Path) -> tuple[date, date]:
        if run.window_from and run.window_to:
            return run.window_from, run.window_to
        raise PipelineInputError("회차에 수집 기간이 기록되어 있지 않습니다.")

    def _command(
        self,
        run: Run,
        stage: str,
        target_directory: Path,
        *,
        from_raw: bool,
    ) -> list[str]:
        source_directory = self._run_directory(run)
        if stage == "collect":
            window_from, window_to = self._window(run, source_directory)
            command = [
                "python3",
                "skills/bidops-collect/scripts/collect_notices.py",
                "--from-date",
                window_from.isoformat(),
                "--to-date",
                window_to.isoformat(),
                "--output-dir",
                str(target_directory),
            ]
            if from_raw:
                command.append("--from-raw")
            return command
        if stage == "sample":
            input_path = target_directory / "collected-notices.json"
            if not input_path.is_file():
                raise PipelineInputError("collected-notices.json이 없어 표본을 선정할 수 없습니다.")
            return [
                "python3",
                "skills/bidops-collect/scripts/select_validation_sample.py",
                str(input_path),
                "--output",
                str(target_directory / "validation-set.json"),
            ]
        input_path = target_directory / "screening-results.json"
        if not input_path.is_file():
            raise PipelineInputError("screening-results.json이 없어 보고서를 생성할 수 없습니다.")
        report_directory = self.settings.bidops_root / "reports" / target_directory.name
        return [
            "python3",
            "skills/bidops-report/scripts/render_report.py",
            str(input_path),
            "--output-dir",
            str(report_directory),
        ]

    def _execute(self, execution: PipelineExecution) -> None:
        secrets = _secret_values(self.settings)
        with execution.lock:
            execution.status = "running"
            execution.started_at = datetime.now(timezone.utc)
        environment = os.environ.copy()
        if self.settings.g2b_api_key:
            environment["BIDOPS_G2B_API_KEY"] = self.settings.g2b_api_key
        process: Any = None
        try:
            process = self._popen(
                list(execution.command),
                cwd=str(self.settings.bidops_root),
                env=environment,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            readers = [
                threading.Thread(
                    target=self._read_stream,
                    args=(process.stdout, "stdout", execution, secrets),
                    daemon=True,
                ),
                threading.Thread(
                    target=self._read_stream,
                    args=(process.stderr, "stderr", execution, secrets),
                    daemon=True,
                ),
            ]
            for reader in readers:
                reader.start()
            execution.exit_code = process.wait()
            for reader in readers:
                reader.join(timeout=5)
            if execution.exit_code == 0:
                self._reload(execution)
                with execution.lock:
                    execution.status = "success"
            else:
                with execution.lock:
                    execution.status = "failed"
                    execution.error = f"프로세스가 종료 코드 {execution.exit_code}(으)로 종료되었습니다."
        except Exception as exc:  # subprocess and re-ingest failures belong to this run
            message = mask_secrets(str(exc), secrets)
            with execution.lock:
                execution.status = "failed"
                execution.error = message or "실행 중 알 수 없는 오류가 발생했습니다."
            execution.add_line("stderr", execution.error, secrets)
            if process is not None and getattr(process, "poll", lambda: None)() is None:
                process.kill()
        finally:
            with execution.lock:
                execution.finished_at = datetime.now(timezone.utc)
            with self._lock:
                if self._active_by_run.get(execution.source_run_id) == execution.execution_id:
                    self._active_by_run.pop(execution.source_run_id, None)

    @staticmethod
    def _read_stream(
        stream: Any,
        stream_name: str,
        execution: PipelineExecution,
        secrets: tuple[str, ...],
    ) -> None:
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                execution.add_line(stream_name, line, secrets)
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()

    def _reload(self, execution: PipelineExecution) -> None:
        with self._session_factory() as session:
            result = ingest_run(
                execution.target_directory,
                session,
                reports_root=self.settings.bidops_root / "reports",
            )
            result_run = session.get(Run, result.run_id)
            # 판정이 아직 없는 회차는 이전 회차를 대체하지 않는다. 수집·표본까지만
            # 끝난 회차가 판정을 갖춘 회차를 밀어내면, 화면의 기본 회차가 판정
            # 없는 상태로 바뀌어 검토 대기열과 대시보드가 비어 버린다. 판정은
            # 에이전트가 별도로 작성하므로(ADR-006) 이 시점 차이는 정상이다.
            if (
                result_run is not None
                and result.judgments > 0
                and result_run.window_from
                and result_run.window_to
            ):
                previous_runs = session.scalars(
                    select(Run).where(
                        Run.id != result_run.id,
                        Run.window_from == result_run.window_from,
                        Run.window_to == result_run.window_to,
                        Run.status != "superseded",
                    )
                ).all()
                for previous in previous_runs:
                    previous.status = "superseded"
                    previous.superseded_by = result_run.id
                session.commit()
            with execution.lock:
                execution.result_run_id = result.run_id


def execution_response(execution: PipelineExecution) -> dict[str, Any]:
    with execution.lock:
        return {
            "execution_id": execution.execution_id,
            "source_run_id": execution.source_run_id,
            "result_run_id": execution.result_run_id,
            "stage": execution.stage,
            "status": execution.status,
            "started_at": execution.started_at,
            "finished_at": execution.finished_at,
            "exit_code": execution.exit_code,
            "error": execution.error,
            "log_count": len(execution.lines),
        }


def log_response(execution: PipelineExecution) -> list[dict[str, Any]]:
    with execution.lock:
        return [
            {
                "timestamp": line.timestamp,
                "stream": line.stream,
                "level": line.level,
                "message": mask_secrets(line.message),
            }
            for line in execution.lines
        ]
