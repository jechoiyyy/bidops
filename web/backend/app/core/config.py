"""Application settings and filesystem paths.

The web backend is deliberately configured independently from the existing
pipeline scripts.  Secrets, when needed by later steps, are read from the
process environment and are never given a source-code default.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_BIDOPS_ROOT = Path(__file__).resolve().parents[4]

#: 조립 계층이 고를 수 있는 도메인 모듈 (명세 §7). core는 선택 대상이 아니라
#: 항상 포함된다. 여기 있는 것은 이름뿐이며 core는 이 모듈들을 import하지 않는다.
MODULE_NAMES: tuple[str, ...] = ("lifecycle", "screening", "deep_review")

#: `BIDOPS_MODULES`를 지정하지 않았을 때의 값. 분할 전과 같은 앱이 된다.
DEFAULT_MODULES: str = ",".join(MODULE_NAMES)

def parse_modules(value: str) -> tuple[str, ...]:
    """`BIDOPS_MODULES` 문자열을 모듈 순서 목록으로 푼다 (명세 §7).

    쉼표로 나누고 공백을 떼며, 준 순서를 그대로 지킨다. **알 수 없는 이름이나
    빈 값은 예외**다 — 조용히 기본값으로 되돌아가면 "무엇이 등록됐는지"를 설정
    파일만 보고 알 수 없게 되므로 fail closed 한다.
    """

    names = [piece.strip() for piece in str(value).split(",")]
    names = [name for name in names if name]
    if not names:
        raise ValueError(
            "BIDOPS_MODULES must name at least one of " + ", ".join(MODULE_NAMES)
        )
    unknown = [name for name in names if name not in MODULE_NAMES]
    if unknown:
        raise ValueError(
            "BIDOPS_MODULES has unknown module names: "
            + ", ".join(sorted(unknown))
            + " (allowed: "
            + ", ".join(MODULE_NAMES)
            + ")"
        )
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return tuple(seen)


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
    # 등록할 도메인 모듈 (명세 §7). 문자열 그대로 받고 `modules` property가
    # 푼다 — pydantic-settings 는 복합 타입 환경변수를 JSON 으로 먼저 읽으려
    # 하므로, 쉼표 목록은 문자열 필드로 받아야 값 검증이 우리 손에 남는다.
    modules_setting: str = Field(
        default=DEFAULT_MODULES,
        validation_alias="BIDOPS_MODULES",
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
    g2b_attachment_enabled: bool = Field(
        default=False,
        validation_alias="BIDOPS_G2B_ATTACHMENT_ENABLED",
    )
    g2b_attachment_allowed_hosts: str = Field(
        default="",
        validation_alias="BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS",
    )
    g2b_attachment_timeout_seconds: float = Field(
        default=30.0,
        validation_alias="BIDOPS_G2B_ATTACHMENT_TIMEOUT_SECONDS",
    )
    # C-1 생성 예산. 실행마다 얼려 `bidops.generation-config.v1`으로 보존하고
    # stage별 `num_predict`는 호출 시점에 OpenAI 호환 `max_tokens`가 된다.
    # `num_ctx`는 대응 파라미터가 없어 binding 기록에만 남는다.
    model_context: int = Field(
        default=16384,
        validation_alias="BIDOPS_SCREENING_CONTEXT_SIZE",
    )
    model_max_output: int = Field(
        default=2048,
        validation_alias="BIDOPS_SCREENING_MAX_OUTPUT_TOKENS",
    )
    model_synthesis_output: int = Field(
        default=4096,
        validation_alias="BIDOPS_SCREENING_SYNTHESIS_MAX_OUTPUT_TOKENS",
    )
    screening_provider: Literal["vllm", "mock"] = Field(
        default="vllm",
        validation_alias="BIDOPS_SCREENING_PROVIDER",
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

    # --- Deep review analysis providers and document pipeline ---
    vllm_base_url: str = Field(
        default="http://127.0.0.1:8000/v1",
        validation_alias="BIDOPS_VLLM_BASE_URL",
    )
    # The 64-hex model artifact digest the server operator attests for this
    # deployment.  Empty by default so C-2 fails closed until it is declared.
    vllm_model_revision: str = Field(default="", validation_alias="BIDOPS_VLLM_MODEL_REVISION")
    vllm_api_key: SecretStr = Field(default_factory=lambda: SecretStr("EMPTY"), validation_alias="BIDOPS_VLLM_API_KEY")
    vllm_allowed_hosts: str = Field(default="", validation_alias="BIDOPS_VLLM_ALLOWED_HOSTS")
    # 용도별 override (명세 §6.6). 빈 값은 "지정하지 않음"이고 그때는 위의
    # 공유값을 쓴다. 공유값에도 허용 host나 선언 revision이 없으면 그 용도는
    # `resolve_model_endpoint`에서 fail closed한다 — 여기서 기본 주소를 채워
    # 넣지 않는 것이 요점이다.
    vllm_screening_base_url: str = Field(default="", validation_alias="BIDOPS_VLLM_SCREENING_BASE_URL")
    vllm_screening_allowed_hosts: str = Field(default="", validation_alias="BIDOPS_VLLM_SCREENING_ALLOWED_HOSTS")
    vllm_screening_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), validation_alias="BIDOPS_VLLM_SCREENING_API_KEY")
    vllm_screening_model_revision: str = Field(default="", validation_alias="BIDOPS_VLLM_SCREENING_MODEL_REVISION")
    vllm_overview_base_url: str = Field(default="", validation_alias="BIDOPS_VLLM_OVERVIEW_BASE_URL")
    vllm_overview_allowed_hosts: str = Field(default="", validation_alias="BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS")
    vllm_overview_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), validation_alias="BIDOPS_VLLM_OVERVIEW_API_KEY")
    vllm_overview_model_revision: str = Field(default="", validation_alias="BIDOPS_VLLM_OVERVIEW_MODEL_REVISION")
    vllm_deep_review_base_url: str = Field(default="", validation_alias="BIDOPS_VLLM_DEEP_REVIEW_BASE_URL")
    vllm_deep_review_allowed_hosts: str = Field(default="", validation_alias="BIDOPS_VLLM_DEEP_REVIEW_ALLOWED_HOSTS")
    vllm_deep_review_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), validation_alias="BIDOPS_VLLM_DEEP_REVIEW_API_KEY")
    vllm_deep_review_model_revision: str = Field(default="", validation_alias="BIDOPS_VLLM_DEEP_REVIEW_MODEL_REVISION")
    # C-1 공고 판정이 부르는 모델명. 개요·심층 검토는 policy의 `model_name`을
    # 쓰므로 설정 항목이 없다.
    vllm_screening_model: str = Field(default="qwen3.8-27B", validation_alias="BIDOPS_VLLM_SCREENING_MODEL")
    analysis_provider: Literal["vllm", "mock"] = Field(default="vllm", validation_alias="BIDOPS_ANALYSIS_PROVIDER")
    openai_enabled: bool = Field(default=False, validation_alias="BIDOPS_OPENAI_ENABLED")
    # 참조 실행 모드는 provider에 매이지 않는다 (명세 §6.5). mock provider는 아래
    # 검증이 이 모드를 필수로 요구하고, 승인된 사설 vLLM 경로도 이 모드에서는
    # 측정값 없는 policy로 실행할 수 있다. 그 결과는 `deployable=false`이며 운영
    # 완료·품질 근거·활성화 근거로 쓰지 않는다.
    reference_workflow_mode: bool = Field(default=False, validation_alias="BIDOPS_REFERENCE_WORKFLOW_MODE")
    document_worker_concurrency: int = Field(default=2, validation_alias="BIDOPS_DOCUMENT_WORKER_CONCURRENCY")
    analysis_worker_concurrency: int = Field(default=1, validation_alias="BIDOPS_ANALYSIS_WORKER_CONCURRENCY")
    document_worker_poll_seconds: float = Field(default=1.0, validation_alias="BIDOPS_DOCUMENT_WORKER_POLL_SECONDS")
    document_converter_wait_seconds: float = Field(default=45.0, validation_alias="BIDOPS_DOCUMENT_CONVERTER_WAIT_SECONDS")
    clamav_host: str = Field(default="clamav", validation_alias="BIDOPS_CLAMAV_HOST")
    clamav_port: int = Field(default=3310, validation_alias="BIDOPS_CLAMAV_PORT")
    clamav_timeout_seconds: float = Field(default=15.0, validation_alias="BIDOPS_CLAMAV_TIMEOUT_SECONDS")
    analysis_worker_poll_seconds: float = Field(default=1.0, validation_alias="BIDOPS_ANALYSIS_WORKER_POLL_SECONDS")
    # Manual C-2 execution references.  These are read-only inputs copied into
    # an execution snapshot; startup never validates, activates, or calls them.
    c2_policy_path: Path | None = Field(default=None, validation_alias="BIDOPS_C2_POLICY_PATH")
    c2_binding_path: Path | None = Field(default=None, validation_alias="BIDOPS_C2_BINDING_PATH")
    c2_capabilities_path: Path | None = Field(default=None, validation_alias="BIDOPS_C2_CAPABILITIES_PATH")
    c2_prompt_path: Path | None = Field(default=None, validation_alias="BIDOPS_C2_PROMPT_PATH")
    c2_generation_config_path: Path | None = Field(default=None, validation_alias="BIDOPS_C2_GENERATION_CONFIG_PATH")
    c2_bm25_script: Path | None = Field(default=None, validation_alias="BIDOPS_C2_BM25_SCRIPT")
    c2_merge_script: Path | None = Field(default=None, validation_alias="BIDOPS_C2_MERGE_SCRIPT")
    c2_execution_allowed: bool = Field(default=False, validation_alias="BIDOPS_C2_EXECUTION_ALLOWED")
    c2_worker_stale_seconds: int = Field(default=900, validation_alias="BIDOPS_C2_WORKER_STALE_SECONDS")
    c2_response_retention_days: int = Field(default=30, validation_alias="BIDOPS_C2_RESPONSE_RETENTION_DAYS")
    prespec_attachment_worker_concurrency: int = Field(
        default=1, validation_alias="BIDOPS_PRESPEC_ATTACHMENT_WORKER_CONCURRENCY"
    )
    prespec_attachment_worker_poll_seconds: float = Field(
        default=5.0, validation_alias="BIDOPS_PRESPEC_ATTACHMENT_WORKER_POLL_SECONDS"
    )
    prespec_attachment_lease_seconds: float = Field(
        default=120.0, validation_alias="BIDOPS_PRESPEC_ATTACHMENT_LEASE_SECONDS"
    )
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

    @field_validator("modules_setting")
    @classmethod
    def validate_modules(cls, value: str) -> str:
        """알 수 없는 이름이나 빈 값이면 여기서 죽는다 (명세 §7의 fail closed).

        `app.core.db`가 import 시점에 `get_settings()`를 부르므로 앱 객체가
        만들어지기 전에 걸린다. 검증을 model validator가 아니라 **필드**
        validator에 두는 것은 의도적이다 — 실패 메시지에 실리는 입력값이 이
        필드 하나로 좁혀지고, 다른 환경변수 값이 오류 문자열에 딸려 나가지
        않는다.
        """

        parse_modules(value)
        return value

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
        if self.screening_provider == "mock" and not self.reference_workflow_mode:
            raise ValueError("mock screening provider requires reference workflow mode")
        if self.data_dir is None:
            self.data_dir = self.bidops_root / "web" / "data"
        if self.attachments_dir is None:
            self.attachments_dir = self.data_dir / "attachments"
        if self.c2_policy_path is None:
            self.c2_policy_path = self.bidops_root / "experiments/order-plan-screening/config/order-plan-screening-policy.v2.json"
        if self.c2_binding_path is None:
            self.c2_binding_path = self.bidops_root / "experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v2.json"
        if self.c2_generation_config_path is None:
            self.c2_generation_config_path = self.bidops_root / "experiments/order-plan-screening/config/order-plan-screening-generation-config.v4.json"
        # Capabilities and prompt are deployment/company inputs.  They are
        # intentionally never inferred from the repository: an operator must
        # supply explicit paths before a C-2 execution can be created.
        if self.c2_bm25_script is None:
            self.c2_bm25_script = self.bidops_root / "skills/bidops-screen/scripts/rank_order_plans_bm25.py"
        if self.c2_merge_script is None:
            self.c2_merge_script = self.bidops_root / "skills/bidops-screen/scripts/build_order_plan_screening_results.py"
        if self.c2_worker_stale_seconds < 1 or self.c2_response_retention_days < 1:
            raise ValueError("C-2 worker limits must be positive")
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
        if self.model_context <= 0 or self.model_max_output <= 0 or self.model_synthesis_output <= 0:
            raise ValueError("model context and output budgets must be positive")
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
    def modules(self) -> tuple[str, ...]:
        """등록할 도메인 모듈을 지정 순서대로 낸다 (명세 §7)."""

        return parse_modules(self.modules_setting)

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
    def screen_heartbeat_seconds(self) -> int:
        return self.heartbeat_seconds

    @property
    def screen_stale_after_seconds(self) -> int:
        return self.stale_seconds

    @property
    def database_path(self) -> Path:
        """Return the default SQLite location."""

        return self.data_dir / "bidops.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings object."""

    return Settings()
