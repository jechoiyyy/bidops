"""Application settings and filesystem paths.

The web backend is deliberately configured independently from the existing
pipeline scripts.  Secrets, when needed by later steps, are read from the
process environment and are never given a source-code default.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import math
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_BIDOPS_ROOT = Path(__file__).resolve().parents[3]
_OLLAMA_DURATION = re.compile(
    r"(?:-1|0|(?:\d+(?:\.\d+)?(?:ns|us|µs|ms|s|m|h))+)$"
)


class Settings(BaseSettings):
    """Configuration for the local BidOps Admin instance."""

    model_config = SettingsConfigDict(
        extra="ignore",
        populate_by_name=True,
        env_file=DEFAULT_BIDOPS_ROOT / ".env",
        env_file_encoding="utf-8",
    )

    bidops_root: Path = Field(
        default_factory=lambda: DEFAULT_BIDOPS_ROOT,
        validation_alias=AliasChoices("BIDOPS_ROOT", "BIDOPS_PROJECT_ROOT"),
    )
    data_dir: Path | None = Field(
        default=None,
        validation_alias="BIDOPS_DATA_DIR",
    )
    attachments_dir: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "BIDOPS_ATTACHMENTS_DIR",
            "BIDOPS_ATTACHMENT_DIR",
        ),
    )
    reviewer_name: str = Field(
        default="",
        validation_alias=AliasChoices(
            "BIDOPS_REVIEWER",
            "BIDOPS_REVIEWER_NAME",
        ),
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="WARNING",
        validation_alias="BIDOPS_LOG_LEVEL",
    )
    log_traceback: bool = Field(
        default=False,
        validation_alias="BIDOPS_LOG_TRACEBACK",
    )
    database_url: str | None = Field(
        default=None,
        validation_alias="BIDOPS_DATABASE_URL",
    )
    g2b_api_key: str | None = Field(
        default=None,
        validation_alias="BIDOPS_G2B_API_KEY",
    )
    model_name: str = Field(
        default="qwen3.8:27b",
        validation_alias="BIDOPS_OLLAMA_MODEL",
    )
    model_base_url: str = Field(
        default="http://192.168.0.139:11434",
        validation_alias="BIDOPS_OLLAMA_BASE_URL",
    )
    model_timeout: int = Field(
        default=180,
        validation_alias="BIDOPS_OLLAMA_TIMEOUT_SECONDS",
    )
    # Ollama accepts a Go duration string, or a numeric nanosecond value.
    # Keep the numeric forms because 0 unloads a model and -1 keeps it loaded.
    model_keep_alive: str | int | float = Field(
        default="30m",
        validation_alias="BIDOPS_OLLAMA_KEEP_ALIVE",
    )
    model_context: int = Field(
        default=16384,
        validation_alias="BIDOPS_OLLAMA_CONTEXT_SIZE",
    )
    model_max_output: int = Field(
        default=2048,
        validation_alias="BIDOPS_OLLAMA_MAX_OUTPUT_TOKENS",
    )
    model_synthesis_output: int = Field(
        default=4096,
        validation_alias="BIDOPS_OLLAMA_SYNTHESIS_MAX_OUTPUT_TOKENS",
    )
    screen_concurrency: int = Field(
        default=1,
        validation_alias="BIDOPS_SCREEN_MAX_CONCURRENCY",
    )
    heartbeat_seconds: int = Field(
        default=5, validation_alias="BIDOPS_SCREEN_HEARTBEAT_SECONDS"
    )
    stale_seconds: int = Field(
        default=60, validation_alias="BIDOPS_SCREEN_STALE_AFTER_SECONDS"
    )
    scheduler_enabled: bool = Field(
        default=False, validation_alias="BIDOPS_SCHEDULER_ENABLED"
    )
    schedule_daily_time: str = Field(
        default="02:00", validation_alias="BIDOPS_SCHEDULE_DAILY_TIME"
    )
    schedule_weekly_time: str = Field(
        default="06:00", validation_alias="BIDOPS_SCHEDULE_WEEKLY_TIME"
    )
    schedule_prespec: bool = Field(default=False, validation_alias="BIDOPS_PRESPEC_ENABLED")
    live_test: bool = Field(default=False, validation_alias="BIDOPS_LIVE_OLLAMA_TEST")

    @field_validator("model_base_url")
    @classmethod
    def validate_model_base_url(cls, value: str) -> str:
        """Require a credential-free absolute HTTP(S) Ollama endpoint."""

        if (
            not isinstance(value, str)
            or not value
            or any(character.isspace() for character in value)
            or "?" in value
            or "#" in value
            or "\\" in value
        ):
            raise ValueError("BIDOPS_OLLAMA_BASE_URL must be an absolute HTTP(S) URL")
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            # Accessing port also validates malformed ports and brackets.
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("BIDOPS_OLLAMA_BASE_URL must be an absolute HTTP(S) URL") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not hostname
            or parsed.netloc.endswith(":")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "BIDOPS_OLLAMA_BASE_URL must use http/https without credentials, query, or fragment"
            )
        return value

    @field_validator("model_keep_alive", mode="before")
    @classmethod
    def validate_model_keep_alive(cls, value: object) -> object:
        """Accept Ollama duration strings and its numeric sentinel forms."""

        if isinstance(value, bool):
            raise ValueError("BIDOPS_OLLAMA_KEEP_ALIVE must be an Ollama duration or number")
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("BIDOPS_OLLAMA_KEEP_ALIVE must be finite")
            if value < -1:
                raise ValueError("BIDOPS_OLLAMA_KEEP_ALIVE must be -1 or greater")
            return value
        if isinstance(value, str) and _OLLAMA_DURATION.fullmatch(value):
            return value
        raise ValueError(
            "BIDOPS_OLLAMA_KEEP_ALIVE must be a duration such as 30m, 0, or -1"
        )

    # --- Deep review analysis providers and document pipeline ---
    vllm_base_url: str = Field(
        default="http://127.0.0.1:8000/v1",
        validation_alias="BIDOPS_VLLM_BASE_URL",
    )
    vllm_model: str = Field(default="qwen3.8-27B", validation_alias="BIDOPS_VLLM_MODEL")
    vllm_api_key: SecretStr = Field(default_factory=lambda: SecretStr("EMPTY"), validation_alias="BIDOPS_VLLM_API_KEY")
    vllm_allowed_hosts: str = Field(default="", validation_alias="BIDOPS_VLLM_ALLOWED_HOSTS")
    analysis_provider: Literal["vllm", "codex-exec", "mock"] = Field(default="vllm", validation_alias="BIDOPS_ANALYSIS_PROVIDER")
    openai_enabled: bool = Field(default=False, validation_alias="BIDOPS_OPENAI_ENABLED")
    codex_exec_enabled: bool = Field(default=False, validation_alias="BIDOPS_CODEX_EXEC_ENABLED")
    codex_exec_binary: str = Field(default="codex", validation_alias="BIDOPS_CODEX_EXEC_BIN")
    codex_exec_model: str = Field(default="gpt-5.6-sol", validation_alias="BIDOPS_CODEX_EXEC_MODEL")
    codex_exec_reasoning_effort: Literal["low", "medium", "high", "xhigh"] = Field(default="low", validation_alias="BIDOPS_CODEX_EXEC_REASONING_EFFORT")
    codex_exec_approved_notice_ids: str = Field(default="", validation_alias="BIDOPS_CODEX_EXEC_APPROVED_NOTICE_IDS")
    reference_workflow_mode: bool = Field(default=False, validation_alias="BIDOPS_REFERENCE_WORKFLOW_MODE")
    document_worker_concurrency: int = Field(default=2, validation_alias="BIDOPS_DOCUMENT_WORKER_CONCURRENCY")
    analysis_worker_concurrency: int = Field(default=1, validation_alias="BIDOPS_ANALYSIS_WORKER_CONCURRENCY")
    document_worker_poll_seconds: float = Field(default=1.0, validation_alias="BIDOPS_DOCUMENT_WORKER_POLL_SECONDS")
    document_converter_wait_seconds: float = Field(default=45.0, validation_alias="BIDOPS_DOCUMENT_CONVERTER_WAIT_SECONDS")
    clamav_host: str = Field(default="clamav", validation_alias="BIDOPS_CLAMAV_HOST")
    clamav_port: int = Field(default=3310, validation_alias="BIDOPS_CLAMAV_PORT")
    clamav_timeout_seconds: float = Field(default=15.0, validation_alias="BIDOPS_CLAMAV_TIMEOUT_SECONDS")
    analysis_worker_poll_seconds: float = Field(default=1.0, validation_alias="BIDOPS_ANALYSIS_WORKER_POLL_SECONDS")
    worker_id: str = Field(default="bidops-worker", validation_alias="BIDOPS_WORKER_ID")
    document_scratch_dir: Path = Field(default=Path("/scratch"), validation_alias="BIDOPS_DOCUMENT_SCRATCH_DIR")
    object_store_backend: str | None = Field(default=None, validation_alias="BIDOPS_OBJECT_STORE_BACKEND")
    object_store_endpoint: str | None = Field(default=None, validation_alias="BIDOPS_OBJECT_STORE_ENDPOINT")
    object_store_secure: bool = Field(default=False, validation_alias="BIDOPS_OBJECT_STORE_SECURE")
    source_access_key: str | None = Field(default=None, validation_alias="BIDOPS_SOURCE_ACCESS_KEY")
    source_secret_key: str | None = Field(default=None, validation_alias="BIDOPS_SOURCE_SECRET_KEY")
    structure_access_key: str | None = Field(default=None, validation_alias="BIDOPS_STRUCTURE_ACCESS_KEY")
    structure_secret_key: str | None = Field(default=None, validation_alias="BIDOPS_STRUCTURE_SECRET_KEY")
    structure_read_access_key: str | None = Field(default=None, validation_alias="BIDOPS_STRUCTURE_READ_ACCESS_KEY")
    structure_read_secret_key: str | None = Field(default=None, validation_alias="BIDOPS_STRUCTURE_READ_SECRET_KEY")
    quarantine_access_key: str | None = Field(default=None, validation_alias="BIDOPS_QUARANTINE_ACCESS_KEY")
    quarantine_secret_key: str | None = Field(default=None, validation_alias="BIDOPS_QUARANTINE_SECRET_KEY")
    model_response_access_key: str | None = Field(default=None, validation_alias="BIDOPS_MODEL_RESPONSE_ACCESS_KEY")
    model_response_secret_key: str | None = Field(default=None, validation_alias="BIDOPS_MODEL_RESPONSE_SECRET_KEY")
    model_response_encryption_key: str | None = Field(default=None, validation_alias="BIDOPS_MODEL_RESPONSE_ENCRYPTION_KEY")
    model_response_encryption_key_ref: str | None = Field(default=None, validation_alias="BIDOPS_MODEL_RESPONSE_ENCRYPTION_KEY_REF")

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("BIDOPS_LOG_LEVEL must be DEBUG, INFO, WARNING, or ERROR")
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError("BIDOPS_LOG_LEVEL must be DEBUG, INFO, WARNING, or ERROR")
        return normalized

    @model_validator(mode="after")
    def derive_paths(self) -> "Settings":
        """Derive web data paths from the project root unless overridden."""

        if self.analysis_provider == "mock" and not self.reference_workflow_mode:
            raise ValueError("mock analysis provider requires reference workflow mode")
        if self.data_dir is None:
            self.data_dir = self.bidops_root / "web" / "data"
        if self.attachments_dir is None:
            self.attachments_dir = self.data_dir / "attachments"
        if self.heartbeat_seconds >= self.stale_seconds:
            raise ValueError(
                "BIDOPS_SCREEN_HEARTBEAT_SECONDS must be less than "
                "BIDOPS_SCREEN_STALE_AFTER_SECONDS"
            )
        if self.stale_seconds < self.heartbeat_seconds * 3:
            raise ValueError(
                "BIDOPS_SCREEN_STALE_AFTER_SECONDS must be at least three times "
                "BIDOPS_SCREEN_HEARTBEAT_SECONDS"
            )
        if self.screen_concurrency != 1:
            raise ValueError("only BIDOPS_SCREEN_MAX_CONCURRENCY=1 is supported")
        if self.model_timeout <= 0 or self.model_context <= 0 or self.model_max_output <= 0 or self.model_synthesis_output <= 0:
            raise ValueError("model timeout, context, and output budgets must be positive")
        if self.model_context > 131072 or self.model_max_output > 32768 or self.model_synthesis_output > 32768:
            raise ValueError("model context/output budgets exceed the supported generation bounds")
        if self.model_max_output > self.model_context or self.model_synthesis_output > self.model_context:
            raise ValueError("model output budgets must not exceed context size")
        for name in ("schedule_daily_time", "schedule_weekly_time"):
            value = getattr(self, name)
            if len(value) != 5 or value[2] != ":":
                raise ValueError(f"{name} must use HH:MM")
            try:
                hour, minute = (int(part) for part in value.split(":"))
            except ValueError as exc:
                raise ValueError(f"{name} must use HH:MM") from exc
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError(f"{name} must use HH:MM")
        return self

    @property
    def project_root(self) -> Path:
        """Compatibility alias for callers that use the descriptive name."""

        return self.bidops_root

    def object_store_credentials(self, namespace: str, *, read_only: bool = False) -> tuple[str | None, str | None]:
        """Return purpose-specific credentials without exposing them to logs."""

        values = {
            "source": (self.source_access_key, self.source_secret_key),
            "structure": (self.structure_access_key, self.structure_secret_key),
            "quarantine": (self.quarantine_access_key, self.quarantine_secret_key),
            "model-response": (self.model_response_access_key, self.model_response_secret_key),
        }
        try:
            if namespace == "structure" and read_only:
                return self.structure_read_access_key, self.structure_read_secret_key
            return values[namespace]
        except KeyError as error:
            raise ValueError("unknown object namespace") from error

    @property
    def approved_codex_notice_ids(self) -> tuple[int, ...]:
        """Parse the explicit per-notice external transmission allowlist."""

        if not self.codex_exec_approved_notice_ids.strip():
            return ()
        values: list[int] = []
        for item in self.codex_exec_approved_notice_ids.split(","):
            value = item.strip()
            if not value or not value.isdecimal() or int(value) <= 0:
                raise ValueError("BIDOPS_CODEX_EXEC_APPROVED_NOTICE_IDS must contain positive integer IDs")
            values.append(int(value))
        if len(set(values)) != len(values):
            raise ValueError("BIDOPS_CODEX_EXEC_APPROVED_NOTICE_IDS must not contain duplicates")
        return tuple(values)

    @property
    def ollama_endpoint(self) -> str:
        return self.model_base_url

    @property
    def ollama_base_url(self) -> str:
        return self.model_base_url

    @property
    def ollama_model(self) -> str:
        return self.model_name

    @property
    def ollama_timeout_seconds(self) -> int:
        return self.model_timeout

    @property
    def ollama_keep_alive(self) -> str | int | float:
        return self.model_keep_alive

    @property
    def ollama_context_size(self) -> int:
        return self.model_context

    @property
    def ollama_max_output_tokens(self) -> int:
        return self.model_max_output

    @property
    def screen_heartbeat_seconds(self) -> int:
        return self.heartbeat_seconds

    @property
    def screen_stale_after_seconds(self) -> int:
        return self.stale_seconds

    @property
    def live_ollama_test(self) -> bool:
        return self.live_test

    @property
    def database_path(self) -> Path:
        """Return the default SQLite location."""

        return self.data_dir / "bidops.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings object."""

    return Settings()
