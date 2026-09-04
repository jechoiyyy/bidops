"""Create the closed Lean v1 PostgreSQL model.

The declarative table set is intentionally used as the single DDL source here:
the ERD has one closed set (13 legacy projections + 25 new tables), and keeping
the migration generated from that set prevents a second, drifting model. The
revision binds those tables explicitly to ``bidops`` and is only runnable
against PostgreSQL 17.

The table list is pinned to the legacy plus Lean v1 tuples rather than to the
whole metadata. The screening runtime tables joined the same metadata when the
T15 branch was merged, and they are created by
``0003_screening_runtime_pg`` instead; an unpinned ``create_all`` would
create them here as well and make the clean and existing-database paths differ.
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

from app.core import Base
# 명세 §3의 예외: migration revision 파일은 각 모듈의 `models` 하위 모듈을
# 직접 import한다. 네 모듈을 모두 들여야 ``Base.metadata``에 이 revision이
# 만드는 38개 table이 모두 등록된다.
from app.core.models import CORE_LEAN_V1_TABLES
from app.deep_review.models import DEEP_REVIEW_LEAN_V1_TABLES
from app.lifecycle.models import LIFECYCLE_LEGACY_TABLES
from app.screening.models import SCREENING_LEGACY_TABLES


revision = "0001_lean_v1_postgresql"
down_revision = None
branch_labels = None
depends_on = None
DISPOSABLE_DOWNGRADE_ENV = "BIDOPS_ALLOW_DISPOSABLE_ALEMBIC_DOWNGRADE"


# 이주 전 `app/models.py`가 갖고 있던 두 tuple을 소유 모듈의 조각에서 다시
# 만든다. 집합은 그대로이고 순서만 모듈별로 묶인다. `create_all`·`drop_all`은
# 의존 순서로 다시 정렬하므로 생성되는 테이블 집합과 순서 모두 바뀌지 않는다.
LEGACY_TABLES = LIFECYCLE_LEGACY_TABLES + SCREENING_LEGACY_TABLES
NEW_TABLES = DEEP_REVIEW_LEAN_V1_TABLES + CORE_LEAN_V1_TABLES
LEAN_V1_TABLES = LEGACY_TABLES + NEW_TABLES


def _schema_bound_metadata() -> None:
    """Bind every declarative table to the single application schema."""

    for table in Base.metadata.tables.values():
        table.schema = "bidops"


def _lean_v1_tables() -> list:
    return [Base.metadata.tables[name] for name in LEAN_V1_TABLES]


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS bidops"))
    _schema_bound_metadata()
    # ``checkfirst=False`` makes a clean migration fail loudly if a partially
    # provisioned database is supplied instead of silently hiding drift.
    Base.metadata.create_all(bind=connection, tables=_lean_v1_tables(), checkfirst=False)


def downgrade() -> None:
    # T1 is a forward cutover. A downgrade is only available to an explicitly
    # opted-in disposable validation database; the purpose-named opt-in fails
    # closed by default and does not expose connection details.
    if os.environ.get(DISPOSABLE_DOWNGRADE_ENV) != "1":
        raise RuntimeError(
            f"Alembic downgrade is disabled; set {DISPOSABLE_DOWNGRADE_ENV}=1 only for disposable validation"
        )
    _schema_bound_metadata()
    Base.metadata.drop_all(bind=op.get_bind(), tables=_lean_v1_tables(), checkfirst=False)
