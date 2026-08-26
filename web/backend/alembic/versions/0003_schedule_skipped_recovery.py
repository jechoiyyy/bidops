"""Allow manual recovery of skipped schedule executions.

Revision 0002 shipped the schedule relation triggers before skipped executions
were recoverable.  Keep 0002's trigger semantics intact for existing history,
then replace the schedule relation and projection triggers in this migration
so upgrading an already-0002 database has the same behavior as a fresh
database at head.
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
_PROJECTION_TRIGGER_NAMES = (
    "screening_policy_projection_changed",
    "quality_gate_evaluation_projection_changed",
)


def _drop_relation_triggers() -> None:
    for name in _TRIGGER_NAMES:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")


def _drop_projection_triggers() -> None:
    for name in _PROJECTION_TRIGGER_NAMES:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")


def _create_projection_triggers(with_disable_audit: bool) -> None:
    if not with_disable_audit:
        op.execute(
            "CREATE TRIGGER screening_policy_projection_changed AFTER UPDATE OF status, active_slot, quality_gate_result_id ON screening_policy "
            "WHEN NEW.status <> 'active' OR NEW.active_slot IS NULL OR NEW.quality_gate_result_id IS NOT OLD.quality_gate_result_id "
            "BEGIN UPDATE always_on_state SET enabled = 0, updated_at = COALESCE(NEW.activated_at, OLD.activated_at, CURRENT_TIMESTAMP), updated_by = 'system:policy' WHERE enabled = 1 AND policy_version = NEW.policy_version; END"
        )
        op.execute(
            "CREATE TRIGGER quality_gate_evaluation_projection_changed AFTER INSERT ON quality_gate_evaluation "
            "BEGIN UPDATE quality_gate SET result_status = NEW.result_status, metrics_json = NEW.metrics_json, reasons_json = NEW.reasons_json WHERE gate_id = NEW.gate_id; "
            "UPDATE always_on_state SET enabled = 0, updated_at = NEW.created_at, updated_by = 'system:quality-gate' WHERE enabled = 1 AND NEW.result_status IN ('미달', '미측정', '보류') AND quality_gate_result_id IN (SELECT evaluation_id FROM quality_gate_evaluation WHERE gate_id = NEW.gate_id); END"
        )
        return

    # The audit INSERT intentionally precedes the disable UPDATE.  The
    # enabled=1 predicate is evaluated against the pre-trigger state, while
    # both statements remain in the caller's SQLite transaction.  A rowid
    # derived event id is collision-free for this ordinary rowid table and
    # remains valid under the audit_event's audit-<32 hex> contract.
    op.execute(
        "CREATE TRIGGER screening_policy_projection_changed AFTER UPDATE OF status, active_slot, quality_gate_result_id ON screening_policy "
        "WHEN NEW.status <> 'active' OR NEW.active_slot IS NULL OR NEW.quality_gate_result_id IS NOT OLD.quality_gate_result_id "
        "BEGIN INSERT INTO audit_event(event_id, event_type, actor, target_type, target_id, occurred_at, details_json) "
        "SELECT 'audit-' || printf('%032x', COALESCE((SELECT max(rowid) FROM audit_event), 0) + 1), 'schedule.always_on_disabled', 'system:policy', 'schedule', '1', COALESCE(NEW.activated_at, OLD.activated_at, CURRENT_TIMESTAMP), json_object('reason', 'policy_inactive') "
        "FROM always_on_state WHERE enabled = 1 AND policy_version = NEW.policy_version; "
        "UPDATE always_on_state SET enabled = 0, updated_at = COALESCE(NEW.activated_at, OLD.activated_at, CURRENT_TIMESTAMP), updated_by = 'system:policy' WHERE enabled = 1 AND policy_version = NEW.policy_version; END"
    )
    op.execute(
        "CREATE TRIGGER quality_gate_evaluation_projection_changed AFTER INSERT ON quality_gate_evaluation "
        "BEGIN UPDATE quality_gate SET result_status = NEW.result_status, metrics_json = NEW.metrics_json, reasons_json = NEW.reasons_json WHERE gate_id = NEW.gate_id; "
        "INSERT INTO audit_event(event_id, event_type, actor, target_type, target_id, occurred_at, details_json) "
        "SELECT 'audit-' || printf('%032x', COALESCE((SELECT max(rowid) FROM audit_event), 0) + 1), 'schedule.always_on_disabled', 'system:quality-gate', 'schedule', '1', NEW.created_at, json_object('reason', 'quality_gate_not_passing') "
        "FROM always_on_state WHERE enabled = 1 AND NEW.result_status IN ('미달', '미측정', '보류') AND quality_gate_result_id IN (SELECT evaluation_id FROM quality_gate_evaluation WHERE gate_id = NEW.gate_id); "
        "UPDATE always_on_state SET enabled = 0, updated_at = NEW.created_at, updated_by = 'system:quality-gate' WHERE enabled = 1 AND NEW.result_status IN ('미달', '미측정', '보류') AND quality_gate_result_id IN (SELECT evaluation_id FROM quality_gate_evaluation WHERE gate_id = NEW.gate_id); END"
    )


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
    _drop_projection_triggers()
    _create_projection_triggers(with_disable_audit=True)


def downgrade() -> None:
    _drop_projection_triggers()
    _create_projection_triggers(with_disable_audit=False)
    _drop_relation_triggers()
    _create_relation_triggers(allow_skipped=False)
