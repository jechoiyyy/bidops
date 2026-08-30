"""Allow bid-first opportunities and deferred official references.

Revision ID: 0006_bid_first_opportunity_registration
Revises: 0005_opportunity_links

ADR-0028 makes a bid notice a valid first registration point.  It also keeps
an official upstream number when the referenced row has not arrived yet.  No
rows are rewritten by this migration: the new state is created by the loader
and is represented by the relaxed checks below.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_bid_first_opportunity_registration"
down_revision = "0005_opportunity_links"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-9e6b4c2d1f8047a5b3c6d8e0f2a19475"

_DEFERRED_OFFICIAL = (
    "(link_type = 'official' AND evidence_external_no IS NOT NULL "
    "AND length(trim(evidence_external_no)) > 0 "
    "AND order_plan_id IS NULL AND notice_id IS NULL)"
)
_ONE_TARGET = (
    "status = '검색 미확인' OR "
    f"{_DEFERRED_OFFICIAL} OR "
    "((order_plan_id IS NOT NULL AND notice_id IS NULL) OR "
    "(order_plan_id IS NULL AND notice_id IS NOT NULL))"
)
_STAGE_TARGET = (
    "status = '검색 미확인' OR "
    f"{_DEFERRED_OFFICIAL} OR "
    "(stage = 'order_plan' AND order_plan_id IS NOT NULL AND notice_id IS NULL) OR "
    "(stage = 'notice' AND order_plan_id IS NULL AND notice_id IS NOT NULL)"
)
_TARGET_OR_DEFERRED = (
    f"((order_plan_id IS NOT NULL OR notice_id IS NOT NULL) OR {_DEFERRED_OFFICIAL})"
)
_UNCONFIRMED_WITHOUT_TARGET = (
    "((status = '검색 미확인' AND order_plan_id IS NULL AND notice_id IS NULL) OR "
    f"(status <> '검색 미확인' AND {_TARGET_OR_DEFERRED}))"
)

_OLD_OPPORTUNITY_STAGE = "first_registered_stage IN ('order_plan', 'pre_spec')"
_NEW_OPPORTUNITY_STAGE = (
    "first_registered_stage IN ('order_plan', 'pre_spec', 'bid_notice')"
)
_OLD_ONE_TARGET = (
    "status = '검색 미확인' OR "
    "((order_plan_id IS NOT NULL AND notice_id IS NULL) OR "
    "(order_plan_id IS NULL AND notice_id IS NOT NULL))"
)
_OLD_STAGE_TARGET = (
    "status = '검색 미확인' OR "
    "(stage = 'order_plan' AND order_plan_id IS NOT NULL AND notice_id IS NULL) OR "
    "(stage = 'notice' AND order_plan_id IS NULL AND notice_id IS NOT NULL)"
)
_OLD_UNCONFIRMED_WITHOUT_TARGET = (
    "status <> '검색 미확인' OR (order_plan_id IS NULL AND notice_id IS NULL)"
)


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(name, table_name=table, schema=SCHEMA, type_="check")
    op.create_check_constraint(name, table, expression, schema=SCHEMA)


def upgrade() -> None:
    _replace_check(
        "opportunity",
        "ck_opportunity_first_registered_stage",
        _NEW_OPPORTUNITY_STAGE,
    )
    _replace_check("opportunity_link", "ck_opportunity_link_one_target", _ONE_TARGET)
    _replace_check(
        "opportunity_link", "ck_opportunity_link_stage_target", _STAGE_TARGET
    )
    _replace_check(
        "opportunity_link",
        "ck_opportunity_link_unconfirmed_without_target",
        _UNCONFIRMED_WITHOUT_TARGET,
    )

    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO bidops.screening_audit_event
                (event_id, event_type, actor, target_type, target_id,
                 occurred_at, details_json)
            VALUES (:event_id, 'db.migration', 'system:migration', 'database',
                    :revision, CAST(:occurred_at AS timestamptz),
                    CAST(:details AS json))
            ON CONFLICT (event_id) DO NOTHING
            """
        ),
        {
            "event_id": _MIGRATION_EVENT_ID,
            "revision": revision,
            "details": (
                '{"migration_revision":"0006_bid_first_opportunity_registration",'
                '"action":"upgrade"}'
            ),
            "occurred_at": "2026-01-01 00:00:03+00",
        },
    )


def _assert_downgrade_safe() -> None:
    bind = op.get_bind()
    if bind.scalar(
        sa.text(
            "SELECT 1 FROM bidops.opportunity "
            "WHERE first_registered_stage = 'bid_notice' LIMIT 1"
        )
    ) is not None:
        raise RuntimeError(
            "0006 downgrade refuses to remove bid_notice opportunities; "
            "reconcile bid-first identities before retrying"
        )
    if bind.scalar(
        sa.text(
            "SELECT 1 FROM bidops.opportunity_link "
            "WHERE link_type = 'official' "
            "AND evidence_external_no IS NOT NULL "
            "AND length(trim(evidence_external_no)) > 0 "
            "AND order_plan_id IS NULL AND notice_id IS NULL LIMIT 1"
        )
    ) is not None:
        raise RuntimeError(
            "0006 downgrade refuses to discard deferred official references; "
            "resolve or export them before retrying"
        )


def downgrade() -> None:
    # The old checks cannot express rows introduced by this revision.  Refuse
    # before changing them so rollback never silently turns valid data into an
    # invalid or unreferenced state.
    _assert_downgrade_safe()
    _replace_check(
        "opportunity_link",
        "ck_opportunity_link_unconfirmed_without_target",
        _OLD_UNCONFIRMED_WITHOUT_TARGET,
    )
    _replace_check("opportunity_link", "ck_opportunity_link_stage_target", _OLD_STAGE_TARGET)
    _replace_check("opportunity_link", "ck_opportunity_link_one_target", _OLD_ONE_TARGET)
    _replace_check(
        "opportunity",
        "ck_opportunity_first_registered_stage",
        _OLD_OPPORTUNITY_STAGE,
    )
    op.get_bind().execute(
        sa.text(
            "DELETE FROM bidops.screening_audit_event WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
