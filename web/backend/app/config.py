"""Application settings and filesystem paths.

The web backend is deliberately configured independently from the existing
pipeline scripts.  Secrets, when needed by later steps, are read from the
process environment and are never given a source-code default.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_BIDOPS_ROOT = Path(__file__).resolve().parents[3]


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

    @model_validator(mode="after")
    def derive_paths(self) -> "Settings":
        """Derive web data paths from the project root unless overridden."""

        if self.analysis_provider == "mock" and not self.reference_workflow_mode:
            raise ValueError("mock analysis provider requires reference workflow mode")
        if self.data_dir is None:
            self.data_dir = self.bidops_root / "web" / "data"
        if self.attachments_dir is None:
            self.attachments_dir = self.data_dir / "attachments"
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
    def database_path(self) -> Path:
        """Return the default SQLite location."""

        return self.data_dir / "bidops.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings object."""

    return Settings()
