"""Create the closed Lean v1 PostgreSQL model.

The declarative table set is intentionally used as the single DDL source here:
the ERD has one closed set (13 legacy projections + 25 new tables), and keeping
the migration generated from that set prevents a second, drifting model. The
revision binds those tables explicitly to ``bidops`` and is only runnable
against PostgreSQL 17.
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

from app.db import Base
from app import models  # noqa: F401 - register all tables


revision = "0001_lean_v1_postgresql"
down_revision = None
branch_labels = None
depends_on = None
DISPOSABLE_DOWNGRADE_ENV = "BIDOPS_ALLOW_DISPOSABLE_ALEMBIC_DOWNGRADE"


def _schema_bound_metadata() -> None:
    """Bind every declarative table to the single application schema."""

    for table in Base.metadata.tables.values():
        table.schema = "bidops"


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS bidops"))
    _schema_bound_metadata()
    # ``checkfirst=False`` makes a clean migration fail loudly if a partially
    # provisioned database is supplied instead of silently hiding drift.
    Base.metadata.create_all(bind=connection, checkfirst=False)


def downgrade() -> None:
    # T1 is a forward cutover. A downgrade is only available to an explicitly
    # opted-in disposable validation database; the purpose-named opt-in fails
    # closed by default and does not expose connection details.
    if os.environ.get(DISPOSABLE_DOWNGRADE_ENV) != "1":
        raise RuntimeError(
            f"Alembic downgrade is disabled; set {DISPOSABLE_DOWNGRADE_ENV}=1 only for disposable validation"
        )
    _schema_bound_metadata()
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=False)
