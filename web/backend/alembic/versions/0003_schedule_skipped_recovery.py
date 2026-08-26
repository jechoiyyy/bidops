"""Allow manual recovery of skipped schedule executions.

Revision 0002 shipped the schedule relation triggers before skipped executions
were recoverable.  Keep 0002's trigger semantics intact for existing history,
then replace only those three triggers in this migration so upgrading an
already-0002 database has the same behavior as a fresh database at head.
"""

from __future__ import annotations

from alembic import op


revision = "0003_schedule_skipped_recovery"
down_revision = "0002_screening_runtime"
branch_labels = None
depends_on = None


_TRIGGER_NAMES = (
    "schedule_execution_relation_target_update",
    "schedule_execution_relation_update",
    "schedule_execution_relation_insert",
)


def _drop_relation_triggers() -> None:
    for name in _TRIGGER_NAMES:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")


def _create_relation_triggers(allow_skipped: bool) -> None:
    terminal = "'실패', '부분 성공', '건너뜀'" if allow_skipped else "'실패', '부분 성공'"
    op.execute(
        "CREATE TRIGGER schedule_execution_relation_insert "
        "BEFORE INSERT ON schedule_execution "
        "WHEN (NEW.duplicate_of_execution_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM schedule_execution target WHERE target.execution_id = "
        "NEW.duplicate_of_execution_id AND target.run_key = NEW.run_key AND "
        "target.job_kind = NEW.job_kind)) OR "
        "(NEW.recovery_of_execution_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM schedule_execution target WHERE target.execution_id = "
        "NEW.recovery_of_execution_id AND target.run_key = NEW.run_key AND "
        "target.job_kind = NEW.job_kind AND target.status IN ("
        f"{terminal}))) "
        "BEGIN SELECT RAISE(ABORT, 'schedule execution relation mismatch'); END"
    )
    op.execute(
        "CREATE TRIGGER schedule_execution_relation_update "
        "BEFORE UPDATE OF run_key, job_kind, duplicate_of_execution_id, "
        "recovery_of_execution_id ON schedule_execution "
        "WHEN (NEW.duplicate_of_execution_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM schedule_execution target WHERE target.execution_id = "
        "NEW.duplicate_of_execution_id AND target.run_key = NEW.run_key AND "
        "target.job_kind = NEW.job_kind)) OR "
        "(NEW.recovery_of_execution_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM schedule_execution target WHERE target.execution_id = "
        "NEW.recovery_of_execution_id AND target.run_key = NEW.run_key AND "
        "target.job_kind = NEW.job_kind AND target.status IN ("
        f"{terminal}))) "
        "BEGIN SELECT RAISE(ABORT, 'schedule execution relation mismatch'); END"
    )
    op.execute(
        "CREATE TRIGGER schedule_execution_relation_target_update "
        "BEFORE UPDATE OF run_key, job_kind, status ON schedule_execution "
        "WHEN EXISTS (SELECT 1 FROM schedule_execution child WHERE "
        "(child.duplicate_of_execution_id = NEW.execution_id OR "
        "child.recovery_of_execution_id = NEW.execution_id) AND "
        "(NEW.run_key <> OLD.run_key OR NEW.job_kind <> OLD.job_kind OR "
        "(child.recovery_of_execution_id = NEW.execution_id AND NEW.status NOT IN ("
        f"{terminal})))) "
        "BEGIN SELECT RAISE(ABORT, 'schedule execution target relation mismatch'); END"
    )


def upgrade() -> None:
    _drop_relation_triggers()
    _create_relation_triggers(allow_skipped=True)


def downgrade() -> None:
    _drop_relation_triggers()
    _create_relation_triggers(allow_skipped=False)
