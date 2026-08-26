"""Frozen, stage-aware Ollama generation configuration.

Generation settings are execution data, not process configuration.  This
module is the single source of truth for the canonical representation used at
enqueue time, in screening-input.v1, and by every model request.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3
from types import MappingProxyType
from typing import Any, Final, Mapping


GENERATION_CONFIG_SCHEMA: Final[str] = "bidops.generation-config.v1"
DEFAULT_NUM_CTX: Final[int] = 16_384
DEFAULT_PERSPECTIVE_NUM_PREDICT: Final[int] = 2_048
DEFAULT_COUNTERARGUMENT_NUM_PREDICT: Final[int] = 2_048
DEFAULT_SYNTHESIS_NUM_PREDICT: Final[int] = 4_096

# These bounds deliberately reject values that are technically accepted by a
# particular Ollama build but are unsafe or non-reproducible for this worker.
MIN_NUM_CTX: Final[int] = 1
MAX_NUM_CTX: Final[int] = 131_072
MIN_NUM_PREDICT: Final[int] = 1
MAX_NUM_PREDICT: Final[int] = 32_768

STAGE_PERSPECTIVE: Final[str] = "perspective"
STAGE_COUNTERARGUMENT: Final[str] = "counterargument"
STAGE_SYNTHESIS: Final[str] = "synthesis"
STAGE_KEYS: Final[tuple[str, ...]] = (
    STAGE_PERSPECTIVE,
    STAGE_COUNTERARGUMENT,
    STAGE_SYNTHESIS,
)

_PERSPECTIVE_STAGE_NAMES: Final[frozenset[str]] = frozenset(
    {"기술 적합성", "실적 정합성", "공공 SI 적합성", "사업성·자격 제약", "전략 부합"}
)


class GenerationConfigError(ValueError):
    """A generation configuration is malformed or outside safe bounds."""


def _strict_int(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise GenerationConfigError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def stage_key(stage: str) -> str:
    """Map a runtime stage name to the canonical three-stage map."""

    if stage in _PERSPECTIVE_STAGE_NAMES:
        return STAGE_PERSPECTIVE
    if stage in {STAGE_COUNTERARGUMENT, "counterargument.v1", "반론 검토"}:
        return STAGE_COUNTERARGUMENT
    if stage in {STAGE_SYNTHESIS, "judgment.v3", "종합 판정"}:
        return STAGE_SYNTHESIS
    raise GenerationConfigError("stage is not a permitted generation stage")


@dataclass(frozen=True)
class GenerationConfig:
    """Immutable canonical generation policy for one execution."""

    num_ctx: int = DEFAULT_NUM_CTX
    perspective_num_predict: int = DEFAULT_PERSPECTIVE_NUM_PREDICT
    counterargument_num_predict: int = DEFAULT_COUNTERARGUMENT_NUM_PREDICT
    synthesis_num_predict: int = DEFAULT_SYNTHESIS_NUM_PREDICT
    think: bool = False
    stream: bool = False

    def __post_init__(self) -> None:
        _strict_int(self.num_ctx, "num_ctx", minimum=MIN_NUM_CTX, maximum=MAX_NUM_CTX)
        for label, value in (
            ("perspective_num_predict", self.perspective_num_predict),
            ("counterargument_num_predict", self.counterargument_num_predict),
            ("synthesis_num_predict", self.synthesis_num_predict),
        ):
            _strict_int(value, label, minimum=MIN_NUM_PREDICT, maximum=MAX_NUM_PREDICT)
            if value > self.num_ctx:
                raise GenerationConfigError(f"{label} cannot exceed num_ctx")
        if type(self.think) is not bool or type(self.stream) is not bool:
            raise GenerationConfigError("think and stream must be boolean")
        if self.think or self.stream:
            raise GenerationConfigError("think and stream must both be false")

    @property
    def stages(self) -> Mapping[str, int]:
        return MappingProxyType(
            {
                STAGE_PERSPECTIVE: self.perspective_num_predict,
                STAGE_COUNTERARGUMENT: self.counterargument_num_predict,
                STAGE_SYNTHESIS: self.synthesis_num_predict,
            }
        )

    def budget_for_stage(self, stage: str) -> int:
        return self.stages[stage_key(stage)]

    def stage_options(self, stage: str) -> dict[str, int]:
        # Return a new object so transport/payload callers cannot mutate the
        # frozen configuration retained by an execution.
        return {"num_ctx": self.num_ctx, "num_predict": self.budget_for_stage(stage)}

    def canonical_value(self) -> dict[str, Any]:
        return {
            "schema_version": GENERATION_CONFIG_SCHEMA,
            "num_ctx": self.num_ctx,
            "num_predict": {
                STAGE_PERSPECTIVE: self.perspective_num_predict,
                STAGE_COUNTERARGUMENT: self.counterargument_num_predict,
                STAGE_SYNTHESIS: self.synthesis_num_predict,
            },
            "think": False,
            "stream": False,
        }

    def canonical_json(self) -> str:
        return canonical_json(self.canonical_value())

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def canonical_json(value: Mapping[str, Any]) -> str:
    """Serialize a validated config with one deterministic JSON algorithm."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError):
        raise GenerationConfigError("generation config is not canonical JSON") from None


def config_from_value(value: Any) -> GenerationConfig:
    """Strictly parse the persisted canonical object."""

    if not isinstance(value, Mapping) or set(value) != {
        "schema_version", "num_ctx", "num_predict", "think", "stream"
    }:
        raise GenerationConfigError("generation config keys are invalid")
    if value.get("schema_version") != GENERATION_CONFIG_SCHEMA:
        raise GenerationConfigError("generation config schema is invalid")
    budgets = value.get("num_predict")
    if not isinstance(budgets, Mapping) or set(budgets) != set(STAGE_KEYS):
        raise GenerationConfigError("generation config stage map is invalid")
    return GenerationConfig(
        num_ctx=_strict_int(value.get("num_ctx"), "num_ctx", minimum=MIN_NUM_CTX, maximum=MAX_NUM_CTX),
        perspective_num_predict=_strict_int(budgets.get(STAGE_PERSPECTIVE), "perspective_num_predict", minimum=MIN_NUM_PREDICT, maximum=MAX_NUM_PREDICT),
        counterargument_num_predict=_strict_int(budgets.get(STAGE_COUNTERARGUMENT), "counterargument_num_predict", minimum=MIN_NUM_PREDICT, maximum=MAX_NUM_PREDICT),
        synthesis_num_predict=_strict_int(budgets.get(STAGE_SYNTHESIS), "synthesis_num_predict", minimum=MIN_NUM_PREDICT, maximum=MAX_NUM_PREDICT),
        think=value.get("think"),
        stream=value.get("stream"),
    )


def config_from_json(value: str | bytes) -> GenerationConfig:
    try:
        parsed = json.loads(value)
    except (TypeError, UnicodeError, json.JSONDecodeError):
        raise GenerationConfigError("generation config JSON is invalid") from None
    return config_from_value(parsed)


def _sqlite_config_json(value: Any) -> str | None:
    """Return canonical JSON for SQLite, or NULL for any invalid value.

    SQLite deliberately has no SHA-256 primitive and its JSON1 extension only
    checks syntax.  These small deterministic UDFs bridge both gaps while
    reusing the exact Python validator used by artifact and worker code.  A
    NULL result is consumed by the database triggers as a failed validation.
    """

    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None
    try:
        return config_from_json(value).canonical_json()
    except GenerationConfigError:
        return None


def _sqlite_config_digest(value: Any) -> str | None:
    canonical = _sqlite_config_json(value)
    if canonical is None:
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def register_sqlite_functions(connection: sqlite3.Connection) -> None:
    """Install the canonical generation-config functions on one SQLite DBAPI connection."""

    if not isinstance(connection, sqlite3.Connection):
        return
    # Keep the long names explicit in sqlite_master trigger definitions.  The
    # aliases make the shared validator convenient for diagnostics without
    # changing the trigger contract.
    connection.create_function(
        "bidops_generation_config_canonical_json", 1, _sqlite_config_json, deterministic=True
    )
    connection.create_function(
        "bidops_generation_config_digest", 1, _sqlite_config_digest, deterministic=True
    )
    connection.create_function(
        "generation_config_canonical_json", 1, _sqlite_config_json, deterministic=True
    )
    connection.create_function(
        "generation_config_digest", 1, _sqlite_config_digest, deterministic=True
    )


def validate_digest(config: GenerationConfig, digest: Any) -> str:
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise GenerationConfigError("generation config digest is invalid")
    if config.digest() != digest:
        raise GenerationConfigError("generation config digest does not match config")
    return digest


def legacy_generation_config() -> GenerationConfig:
    """Configuration used to deterministically backfill existing rows."""

    return GenerationConfig(
        num_ctx=DEFAULT_NUM_CTX,
        perspective_num_predict=DEFAULT_PERSPECTIVE_NUM_PREDICT,
        counterargument_num_predict=DEFAULT_COUNTERARGUMENT_NUM_PREDICT,
        synthesis_num_predict=DEFAULT_PERSPECTIVE_NUM_PREDICT,
    )


def generation_config_from_settings(settings: Any) -> GenerationConfig:
    """Freeze process settings once, at enqueue/preparation time."""

    ctx = getattr(settings, "model_context", DEFAULT_NUM_CTX)
    normal = getattr(settings, "model_max_output", DEFAULT_PERSPECTIVE_NUM_PREDICT)
    synthesis = getattr(settings, "model_synthesis_output", DEFAULT_SYNTHESIS_NUM_PREDICT)
    # Keep all stage budgets explicit.  ``normal`` remains the established
    # default for perspective and counterargument stages.
    return GenerationConfig(num_ctx=ctx, perspective_num_predict=normal, counterargument_num_predict=normal, synthesis_num_predict=synthesis)


def ensure_generation_config(value: Any | None, digest: Any | None = None) -> tuple[GenerationConfig, str]:
    """Normalize an optional row/input config and verify its digest."""

    config = legacy_generation_config() if value is None else (
        value if isinstance(value, GenerationConfig) else config_from_value(value)
    )
    computed = config.digest()
    if digest is not None and computed != digest:
        raise GenerationConfigError("generation config digest does not match config")
    return config, computed


__all__ = [
    "DEFAULT_COUNTERARGUMENT_NUM_PREDICT", "DEFAULT_NUM_CTX", "DEFAULT_PERSPECTIVE_NUM_PREDICT", "DEFAULT_SYNTHESIS_NUM_PREDICT",
    "GENERATION_CONFIG_SCHEMA", "GenerationConfig", "GenerationConfigError", "MAX_NUM_CTX", "MAX_NUM_PREDICT", "MIN_NUM_CTX", "MIN_NUM_PREDICT",
    "STAGE_COUNTERARGUMENT", "STAGE_KEYS", "STAGE_PERSPECTIVE", "STAGE_SYNTHESIS", "canonical_json", "config_from_json", "config_from_value",
    "ensure_generation_config", "generation_config_from_settings", "legacy_generation_config", "stage_key", "validate_digest",
    "register_sqlite_functions",
]
