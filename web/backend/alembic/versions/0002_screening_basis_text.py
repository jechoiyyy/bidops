"""Preserve full legacy screening basis text.

Revision ID: 0002_screening_basis_text
Revises: 0001_lean_v1_postgresql
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_screening_basis_text"
down_revision = "0001_lean_v1_postgresql"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "run",
        "screening_basis",
        schema="bidops",
        existing_type=sa.String(length=64),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Existing values may exceed 64 characters. A lossy or potentially
    # failing downgrade is not an approved recovery path for the cutover.
    raise RuntimeError("screening_basis TEXT downgrade is disabled")
