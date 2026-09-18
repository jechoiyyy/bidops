"""Shared foundation used by every domain module.

core는 도메인 모듈(lifecycle·screening·deep_review)과 조립 계층을 알지 못한다.
표준 라이브러리와 외부 패키지만 import하며, 테이블은 audit_event·
idempotency_record 둘만 소유한다(명세 §5.1).

조립 계층은 이 `__init__`에 올린 공개 이름만 쓴다. 도메인 모듈은 하위 모듈을
직접 import해도 된다(명세 §4의 허용 표에서 core 대상에는 공개 이름 제한이 없다).
"""

from __future__ import annotations

from .config import (
    DEFAULT_MODULES,
    MODULE_NAMES,
    Settings,
    get_settings,
    parse_modules,
)
from .db import (
    ALEMBIC_HEAD,
    ALEMBIC_VERSION_NUM_WIDTH,
    Base,
    MIGRATION_COMMAND,
    SessionLocal,
    assert_postgresql_runtime,
    engine,
    ensure_database_current,
    get_db,
    init_db,
    isolated_test_boundary_active,
    schema_bound,
    settings,
)
from .generation_config import (
    GENERATION_CONFIG_SCHEMA,
    MAX_NUM_CTX,
    MAX_NUM_PREDICT,
    MIN_NUM_CTX,
    MIN_NUM_PREDICT,
)
from .gpu_rest import GpuRestGate
from .health import router as health_router
from .logging_setup import configure
from .model_client import ModelIdentityCheckState
from .object_store import ObjectStoreError, assert_object_store_runtime
from .run_id import deterministic_run_id, parse_run_id

__all__ = [
    "ALEMBIC_HEAD",
    "ALEMBIC_VERSION_NUM_WIDTH",
    "Base",
    "DEFAULT_MODULES",
    "GENERATION_CONFIG_SCHEMA",
    "GpuRestGate",
    "MAX_NUM_CTX",
    "MAX_NUM_PREDICT",
    "MIGRATION_COMMAND",
    "MIN_NUM_CTX",
    "MIN_NUM_PREDICT",
    "MODULE_NAMES",
    "ModelIdentityCheckState",
    "ObjectStoreError",
    "SessionLocal",
    "Settings",
    "assert_object_store_runtime",
    "assert_postgresql_runtime",
    "configure",
    "deterministic_run_id",
    "engine",
    "ensure_database_current",
    "get_db",
    "get_settings",
    "health_router",
    "init_db",
    "isolated_test_boundary_active",
    "parse_modules",
    "parse_run_id",
    "schema_bound",
    "settings",
]
