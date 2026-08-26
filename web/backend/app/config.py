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
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
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

    @model_validator(mode="after")
    def derive_paths(self) -> "Settings":
        """Derive web data paths from the project root unless overridden."""

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
