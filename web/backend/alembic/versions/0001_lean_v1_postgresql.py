"""Create the closed Lean v1 PostgreSQL model.

The declarative table set is copied as the DDL source here: the ERD has one
closed set (13 legacy projections + 25 new tables), and keeping the migration
generated from that set prevents a second, drifting model.  The copy removes
columns introduced after this revision so current ORM metadata cannot make a
clean historical upgrade depend on future tables.  The revision binds those
tables explicitly to ``bidops`` and is only runnable against PostgreSQL 17.

The table list is pinned to the legacy plus Lean v1 tuples rather than to the
whole metadata. The screening runtime tables joined the same metadata when the
T15 branch was merged, and they are created by
``0003_screening_runtime_pg`` instead; an unpinned ``create_all`` would
create them here as well and make the clean and existing-database paths differ.
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import MetaData, UniqueConstraint, text

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


def _remove_column_added_after_lean_v1(table, column_name: str) -> None:
    """Remove a later column and its dependent schema objects from a copy.

    Revision 0001 historically used the live declarative metadata.  A copied
    table set keeps later model additions from changing the revision while
    preserving the original single-source definition for the other columns.
    """

    for index in tuple(table.indexes):
        if column_name in index.columns:
            table.indexes.remove(index)

    for constraint in tuple(table.constraints):
        if column_name not in constraint.columns:
            continue
        # ``Table.constraints`` and ``Table.foreign_keys`` are separate
        # collections.  Detach both sides before removing the local column so
        # dependency sorting cannot retain the later FK target.
        for foreign_key in getattr(constraint, "elements", ()):
            table.foreign_keys.discard(foreign_key)
            foreign_key.parent.foreign_keys.discard(foreign_key)
        table.constraints.remove(constraint)

    table._columns.remove(table.c[column_name])


def _lean_v1_metadata() -> MetaData:
    """Return the 0001 schema snapshot without mutating ORM metadata."""

    metadata = MetaData()
    for name in LEAN_V1_TABLES:
        Base.metadata.tables[name].to_metadata(metadata, schema="bidops")

    profile_version = metadata.tables["bidops.profile_version"]
    deep_review = metadata.tables["bidops.deep_review"]
    for index in tuple(deep_review.indexes):
        if index.name in {
            "uq_deep_review_legacy_inputs",
            "uq_deep_review_company_inputs",
        }:
            deep_review.indexes.remove(index)
    _remove_column_added_after_lean_v1(profile_version, "company_id")
    _remove_column_added_after_lean_v1(deep_review, "company_id")
    deep_review.append_constraint(
        UniqueConstraint(
            "notice_id",
            "bundle_id",
            "profile_version_id",
            "policy_version_id",
            name="uq_deep_review_inputs",
        )
    )
    return metadata


def _lean_v1_tables(metadata: MetaData) -> list:
    return [metadata.tables[f"bidops.{name}"] for name in LEAN_V1_TABLES]


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS bidops"))
    metadata = _lean_v1_metadata()
    # ``checkfirst=False`` makes a clean migration fail loudly if a partially
    # provisioned database is supplied instead of silently hiding drift.
    metadata.create_all(bind=connection, tables=_lean_v1_tables(metadata), checkfirst=False)


def downgrade() -> None:
    # T1 is a forward cutover. A downgrade is only available to an explicitly
    # opted-in disposable validation database; the purpose-named opt-in fails
    # closed by default and does not expose connection details.
    if os.environ.get(DISPOSABLE_DOWNGRADE_ENV) != "1":
        raise RuntimeError(
            f"Alembic downgrade is disabled; set {DISPOSABLE_DOWNGRADE_ENV}=1 only for disposable validation"
        )
    metadata = _lean_v1_metadata()
    metadata.drop_all(
        bind=op.get_bind(), tables=_lean_v1_tables(metadata), checkfirst=False
    )
