"""Record the schema head migration in the durable audit log.

The event is deliberately deterministic so both a fresh database and an
already deployed 0003 database have the same auditable migration marker.
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "0004_migration_audit"
down_revision = "0003_schedule_skipped_recovery"
branch_labels = None
depends_on = None

# A revision-derived value is deterministic but does not collide with the
# small decimal audit ids commonly used by fixtures and operators.
_EVENT_ID = "audit-e7854deca36d619ac1921856bb9bdbcd"
_REVISION = "0004_migration_audit"
_DETAILS = json.dumps(
    {"migration_revision": _REVISION, "action": "upgrade"},
    separators=(",", ":"),
)


def upgrade() -> None:
    # INSERT OR IGNORE makes a manually re-run migration harmless while the
    # fixed id keeps the audit marker stable across fresh and 0003 upgrades.
    op.get_bind().execute(
        sa.text(
            "INSERT OR IGNORE INTO audit_event "
            "(event_id, event_type, actor, target_type, target_id, occurred_at, details_json) "
            "VALUES (:event_id, :event_type, :actor, :target_type, :target_id, "
            ":occurred_at, :details_json)"
        ),
        {
            "event_id": _EVENT_ID,
            "event_type": "db.migration",
            "actor": "system:migration",
            "target_type": "database",
            "target_id": _REVISION,
            "occurred_at": "2026-01-01 00:00:00",
            "details_json": _DETAILS,
        },
    )


def downgrade() -> None:
    # Remove only this migration's deterministic marker.  Operator-created
    # audit history and the immutable 0002/0003 schema remain untouched.
    op.get_bind().execute(
        sa.text(
            "DELETE FROM audit_event WHERE event_id = :event_id "
            "AND event_type = :event_type AND actor = :actor "
            "AND target_id = :target_id"
        ),
        {
            "event_id": _EVENT_ID,
            "event_type": "db.migration",
            "actor": "system:migration",
            "target_id": _REVISION,
        },
    )
