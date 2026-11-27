"""Live engine runs over the OpenAI Responses API (ADR-0081): result label, approval and call ledger.

- `engine_run`: `quality_status` may be `unmeasured_reference`, and only for a wiki-scoped v3 input
  with `mode=live`; mock runs keep `mock_reference`. A live run must be covered, at commit, by an
  approval of a live preview (deferred constraint trigger), so no code path can queue a live run
  without a recorded human approval.
- `engine_review_preview`: a live preview plans 1..8 calls; a mock preview plans none.
- `engine_call`: one row per request the supervisor sends. The row is written as `reserved` before
  the request leaves and moves once to its outcome; it is never deleted. The call budget counts
  these rows, so a request whose outcome is unknown still uses its slot.
"""

from alembic import op
import sqlalchemy as sa

revision = "0046_engine_live"
down_revision = "0045_engine_review"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
CALL = "engine_call"
PURPOSES = "'extract','units','match','synth'"
FINAL_STATES = "'completed','http_error','incomplete','transport_error','outcome_unknown'"


def _guard(*, live):
    mode_ok = (
        "NEW.input_payload->>'mode' NOT IN ('mock_reference','live') "
        "OR (NEW.input_payload->>'mode' = 'live' AND NEW.company_id IS NOT NULL)"
        if live else "NEW.input_payload->>'mode' IS DISTINCT FROM 'mock_reference'"
    )
    op.execute(f"""CREATE OR REPLACE FUNCTION bidops.guard_engine_run() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'engine run immutable'; END IF;
      IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.result_payload IS NOT NULL OR NEW.result_sha256 IS NOT NULL OR NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'invalid engine creation'; END IF;
        IF NEW.company_id IS NULL THEN
          IF NEW.input_payload->>'schema_version' IS DISTINCT FROM 'bidops.engine-input.v3'
             OR NEW.input_payload #>> '{{company_bundle,slug}}' IS DISTINCT FROM NEW.company_bundle_slug
             OR NEW.input_payload #>> '{{company_bundle,bundle_sha256}}' IS DISTINCT FROM NEW.company_bundle_sha256
             OR NEW.input_payload ?| ARRAY['company_id','profile_version_id','profile_sha256','graph_version_id','graph_sha256']
          THEN RAISE EXCEPTION 'engine wiki scope mismatch'; END IF;
        ELSIF NOT EXISTS (SELECT 1 FROM bidops.profile_version p
                          WHERE p.id=NEW.profile_version_id AND p.company_id=NEW.company_id)
              OR NEW.input_payload->>'schema_version' = 'bidops.engine-input.v3'
        THEN RAISE EXCEPTION 'engine scope mismatch'; END IF;
        IF NOT EXISTS (SELECT 1 FROM bidops.document_bundle b WHERE b.id=NEW.bundle_id AND b.notice_id=NEW.notice_id) THEN RAISE EXCEPTION 'engine scope mismatch'; END IF;
        IF NEW.input_payload->>'company_id' IS DISTINCT FROM NEW.company_id::text OR NEW.input_payload->>'bundle_id' IS DISTINCT FROM NEW.bundle_id::text OR NEW.input_payload->>'notice_id' IS DISTINCT FROM NEW.notice_id::text OR NEW.input_payload->>'profile_version_id' IS DISTINCT FROM NEW.profile_version_id::text OR {mode_ok} THEN RAISE EXCEPTION 'engine input scope mismatch'; END IF;
        RETURN NEW;
      END IF;
      IF (to_jsonb(NEW) - ARRAY['status','result_payload','result_sha256','error_code','started_at','completed_at']) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','result_payload','result_sha256','error_code','started_at','completed_at']) THEN RAISE EXCEPTION 'engine input immutable'; END IF;
      IF OLD.status IN ('completed','partial','failed') THEN RAISE EXCEPTION 'engine result immutable'; END IF;
      IF NOT ((OLD.status='queued' AND NEW.status IN ('running','failed')) OR (OLD.status='running' AND NEW.status IN ('completed','partial','failed'))) THEN RAISE EXCEPTION 'invalid engine transition'; END IF;
      IF OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at THEN RAISE EXCEPTION 'engine start immutable'; END IF;
      IF NEW.status IN ('completed','partial') AND (NEW.result_payload IS NULL OR NEW.result_sha256 IS NULL OR NEW.completed_at IS NULL) THEN RAISE EXCEPTION 'engine result missing'; END IF;
      IF NEW.status='running' AND NEW.started_at IS NULL THEN RAISE EXCEPTION 'engine start missing'; END IF;
      IF NEW.status='failed' AND (NEW.error_code IS NULL OR NEW.completed_at IS NULL) THEN RAISE EXCEPTION 'engine failure missing'; END IF;
      RETURN NEW;
    END; $$""")


def upgrade():
    op.drop_constraint("ck_engine_run_quality", "engine_run", type_="check", schema=SCHEMA)
    op.create_check_constraint(
        "ck_engine_run_quality", "engine_run",
        "(quality_status = 'mock_reference' AND input_payload->>'mode' = 'mock_reference') OR "
        "(quality_status = 'unmeasured_reference' AND input_payload->>'mode' = 'live')",
        schema=SCHEMA,
    )
    _guard(live=True)
    op.execute("""
        CREATE FUNCTION bidops.require_engine_live_approval() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.input_payload->>'mode' = 'live' AND NOT EXISTS (
            SELECT 1 FROM bidops.engine_review_approval a
            JOIN bidops.engine_review_preview p ON p.id = a.preview_id
            WHERE a.engine_run_id = NEW.id AND p.mode = 'live'
          ) THEN RAISE EXCEPTION 'live engine run requires an approved live preview'; END IF;
          RETURN NULL;
        END; $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER engine_run_live_approval AFTER INSERT ON bidops.engine_run
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bidops.require_engine_live_approval()
    """)

    op.drop_constraint("ck_engine_review_preview_calls", "engine_review_preview", type_="check", schema=SCHEMA)
    op.create_check_constraint(
        "ck_engine_review_preview_calls", "engine_review_preview",
        "(mode = 'mock_reference' AND planned_calls = 0) OR (mode = 'live' AND planned_calls BETWEEN 1 AND 8)",
        schema=SCHEMA,
    )

    op.create_table(
        CALL,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("engine_run_id", sa.Uuid(), sa.ForeignKey("bidops.engine_run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("notice_id", sa.Integer(), sa.ForeignKey("bidops.notice.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("transport", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("kst_date", sa.Date(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("request_bytes", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("lease_fence", sa.Integer(), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("response_status", sa.String(32)),
        sa.Column("response_sha256", sa.String(64)),
        sa.Column("served_model", sa.String(64)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("cached_input_tokens", sa.Integer()),
        sa.Column("cache_write_input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("reasoning_output_tokens", sa.Integer()),
        sa.Column("usd", sa.Numeric(12, 6)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error_class", sa.String(64)),
        sa.UniqueConstraint("engine_run_id", "seq", name="uq_engine_call_run_seq"),
        sa.CheckConstraint("seq BETWEEN 1 AND 8", name="ck_engine_call_seq"),
        sa.CheckConstraint(f"purpose IN ({PURPOSES})", name="ck_engine_call_purpose"),
        sa.CheckConstraint(f"state IN ('reserved',{FINAL_STATES})", name="ck_engine_call_state"),
        sa.CheckConstraint(
            "(state = 'reserved' AND finished_at IS NULL) OR (state <> 'reserved' AND finished_at IS NOT NULL)",
            name="ck_engine_call_finished",
        ),
        sa.CheckConstraint("usd IS NULL OR usd >= 0", name="ck_engine_call_usd"),
        schema=SCHEMA,
    )
    op.create_index("ix_bidops_engine_call_kst_date", CALL, ["kst_date"], schema=SCHEMA)
    op.create_index("ix_bidops_engine_call_notice", CALL, ["notice_id"], schema=SCHEMA)
    op.execute(f"""
        CREATE FUNCTION bidops.guard_engine_call() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'engine call immutable'; END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.state <> 'reserved' THEN RAISE EXCEPTION 'engine call must start reserved'; END IF;
            IF NOT EXISTS (SELECT 1 FROM bidops.engine_run r WHERE r.id = NEW.engine_run_id
                           AND r.notice_id = NEW.notice_id AND r.status = 'running'
                           AND r.input_payload->>'mode' = 'live')
            THEN RAISE EXCEPTION 'engine call scope mismatch'; END IF;
            RETURN NEW;
          END IF;
          IF OLD.state <> 'reserved' OR NEW.state NOT IN ({FINAL_STATES}) OR
             (to_jsonb(NEW) - ARRAY['state','finished_at','http_status','response_status','response_sha256',
               'served_model','input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens',
               'reasoning_output_tokens','usd','duration_ms','error_class'])
             IS DISTINCT FROM
             (to_jsonb(OLD) - ARRAY['state','finished_at','http_status','response_status','response_sha256',
               'served_model','input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens',
               'reasoning_output_tokens','usd','duration_ms','error_class'])
          THEN RAISE EXCEPTION 'engine call immutable'; END IF;
          RETURN NEW;
        END; $$;
    """)
    op.execute(f"""
        CREATE TRIGGER engine_call_guard BEFORE INSERT OR UPDATE OR DELETE ON bidops.{CALL}
        FOR EACH ROW EXECUTE FUNCTION bidops.guard_engine_call()
    """)
    op.execute("""INSERT INTO bidops.screening_audit_event
        (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
        VALUES ('audit-' || replace(gen_random_uuid()::text, '-', ''), 'db.migration', 'system:migration','database',
        '0046_engine_live',CURRENT_TIMESTAMP,'{"migration_revision":"0046_engine_live","action":"upgrade"}')""")


def downgrade():
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM bidops.engine_call)
             OR EXISTS (SELECT 1 FROM bidops.engine_run WHERE input_payload->>'mode' = 'live')
             OR EXISTS (SELECT 1 FROM bidops.engine_review_preview WHERE mode = 'live')
          THEN RAISE EXCEPTION '0046 downgrade refuses to discard live engine data'; END IF;
        END $$;
    """)
    op.drop_table(CALL, schema=SCHEMA)
    op.execute("DROP FUNCTION bidops.guard_engine_call()")
    op.execute("DROP TRIGGER engine_run_live_approval ON bidops.engine_run")
    op.execute("DROP FUNCTION bidops.require_engine_live_approval()")
    _guard(live=False)
    op.drop_constraint("ck_engine_review_preview_calls", "engine_review_preview", type_="check", schema=SCHEMA)
    op.create_check_constraint("ck_engine_review_preview_calls", "engine_review_preview",
                               "planned_calls >= 0", schema=SCHEMA)
    op.drop_constraint("ck_engine_run_quality", "engine_run", type_="check", schema=SCHEMA)
    op.create_check_constraint("ck_engine_run_quality", "engine_run",
                               "quality_status = 'mock_reference'", schema=SCHEMA)
