"""수집 색인과 사업기회 연결 상태 확장 (spec §2.1·§3.3).

Revision ID: 0027_collection_index_and_linkage
Revises: 0026_overview_mvp

- ``collected_record_index``·``collected_record_token``: 선별 적재 여부와 무관하게
  수집 레코드마다 한 행을 남기는 검색 색인과 ``bidNtceNoList`` 토큰.
- ``notice.demand_agency``: 사전규격 수요기관(``rlDminsttNm``).
- ``opportunity_link``: status에 ``사람 확인 병합``, search_strategy에
  ``merge_confirmation``, ``검색 미확인`` 행을 구분하는 ``search_target_kind``.

기존 행은 다시 쓰지 않는다. 새 상태를 만드는 흐름은 뒤 단계가 붙인다.
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "0027_collection_index_and_linkage"
down_revision = "0026_overview_mvp"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-" + uuid5(NAMESPACE_URL, "bidops:db.migration:" + revision).hex

_STATUS = "status IN ('확정', '후보 확인 대기', '사람 확인 완료', '검색 미확인', '사람 확인 병합')"
_OLD_STATUS = "status IN ('확정', '후보 확인 대기', '사람 확인 완료', '검색 미확인')"
_STRATEGY = (
    "search_strategy IS NULL OR search_strategy IN "
    "('full', 'breaking_split', 'normalized', 'longest_fragment', 'prefix12', "
    "'merge_confirmation')"
)
_OLD_STRATEGY = (
    "search_strategy IS NULL OR search_strategy IN "
    "('full', 'breaking_split', 'normalized', 'longest_fragment', 'prefix12')"
)
_SEARCH_TARGET_KIND = (
    "search_target_kind IS NULL OR search_target_kind IN ('pre_spec', 'bid_notice')"
)
_RECORD_KIND = "record_kind IN ('order_plan', 'pre_spec', 'bid_notice')"
_SELECTION_REASON = (
    "selection_reason IS NULL OR selection_reason IN ("
    "'order_plan_all', 'pre_spec_sw', 'pre_spec_referenced', 'pre_spec_known', "
    "'bid_same_notice_no', 'bid_tracked_reference', "
    "'bid_sw_prespec_reference', 'bid_sw_industry_competitive', "
    "'tracked_backfill', 'search_result')"
)

_INDEX_INDEXES = (
    ("ix_collected_record_index_kind_key", ["record_kind", "record_key"]),
    ("ix_collected_record_index_order_plan_unty_no", ["order_plan_unty_no"]),
    ("ix_collected_record_index_bf_spec_rgst_no", ["bf_spec_rgst_no"]),
    ("ix_collected_record_index_bid_no", ["bid_no"]),
    ("ix_collected_record_index_kind_title", ["record_kind", "title_normalized"]),
    ("ix_collected_record_index_agency", ["agency"]),
)


def _column_exists(table: str, column: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table_name "
                "AND column_name = :column_name"
            ),
            {"schema": SCHEMA, "table_name": table, "column_name": column},
        )
    )


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(name, table_name=table, schema=SCHEMA, type_="check")
    op.create_check_constraint(name, table, expression, schema=SCHEMA)


def _record_migration_marker() -> None:
    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.screening_audit_event
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
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
            "occurred_at": "2026-01-01 00:00:27+00",
        },
    )


def upgrade() -> None:
    op.create_table(
        "collected_record_index",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=160),
            sa.ForeignKey(f"{SCHEMA}.run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("record_kind", sa.String(length=16), nullable=False),
        sa.Column("record_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("title_normalized", sa.Text(), nullable=True),
        sa.Column("agency", sa.String(length=255), nullable=True),
        sa.Column("demand_agency", sa.String(length=255), nullable=True),
        sa.Column("order_plan_unty_no", sa.String(length=255), nullable=True),
        sa.Column("bf_spec_rgst_no", sa.String(length=255), nullable=True),
        sa.Column("bid_no", sa.String(length=64), nullable=True),
        sa.Column("bid_ord", sa.String(length=32), nullable=True),
        sa.Column("sw_business_status", sa.String(length=16), nullable=True),
        sa.Column("sw_industry_1468", sa.String(length=16), nullable=True),
        sa.Column("contract_method", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("selection_reason", sa.String(length=64), nullable=True),
        sa.Column(
            "ingested_notice_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.notice.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "ingested_order_plan_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.order_plan.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "run_id", "record_kind", "record_key",
            name="uq_collected_record_index_run_kind_key",
        ),
        sa.CheckConstraint(_RECORD_KIND, name="ck_collected_record_index_record_kind"),
        sa.CheckConstraint(
            _SELECTION_REASON, name="ck_collected_record_index_selection_reason"
        ),
        schema=SCHEMA,
    )
    for name, columns in _INDEX_INDEXES:
        op.create_index(name, "collected_record_index", columns, schema=SCHEMA)

    op.create_table(
        "collected_record_token",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "index_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.collected_record_index.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(length=32), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_collected_record_token_token", "collected_record_token", ["token"], schema=SCHEMA
    )
    op.create_index(
        "ix_collected_record_token_index", "collected_record_token", ["index_id"], schema=SCHEMA
    )

    # ``0001`` builds ``notice`` from the current declarative model, so a
    # database created fresh already has the column.  An existing database
    # receives it here.
    if not _column_exists("notice", "demand_agency"):
        op.add_column(
            "notice",
            sa.Column("demand_agency", sa.String(length=255), nullable=True),
            schema=SCHEMA,
        )

    _replace_check("opportunity_link", "ck_opportunity_link_status", _STATUS)
    _replace_check("opportunity_link", "ck_opportunity_link_search_strategy", _STRATEGY)
    op.add_column(
        "opportunity_link",
        sa.Column("search_target_kind", sa.String(length=16), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_opportunity_link_search_target_kind",
        "opportunity_link",
        _SEARCH_TARGET_KIND,
        schema=SCHEMA,
    )
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    blockers = {
        "collected_record_index": f"SELECT 1 FROM {SCHEMA}.collected_record_index LIMIT 1",
        "notice.demand_agency": (
            f"SELECT 1 FROM {SCHEMA}.notice WHERE demand_agency IS NOT NULL LIMIT 1"
        ),
        "opportunity_link": (
            f"SELECT 1 FROM {SCHEMA}.opportunity_link WHERE status = '사람 확인 병합' "
            "OR search_strategy = 'merge_confirmation' OR search_target_kind IS NOT NULL "
            "LIMIT 1"
        ),
    }
    present = [name for name, sql in blockers.items() if bind.scalar(sa.text(sql)) is not None]
    if present:
        raise RuntimeError(
            "0027 downgrade refuses to discard collection index or linkage state; "
            f"restore from backup instead ({', '.join(present)})"
        )
    op.drop_constraint(
        "ck_opportunity_link_search_target_kind",
        table_name="opportunity_link",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_column("opportunity_link", "search_target_kind", schema=SCHEMA)
    _replace_check("opportunity_link", "ck_opportunity_link_search_strategy", _OLD_STRATEGY)
    _replace_check("opportunity_link", "ck_opportunity_link_status", _OLD_STATUS)
    op.drop_column("notice", "demand_agency", schema=SCHEMA)
    op.drop_table("collected_record_token", schema=SCHEMA)
    op.drop_table("collected_record_index", schema=SCHEMA)
    bind.execute(
        sa.text(f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"),
        {"event_id": _MIGRATION_EVENT_ID},
    )
