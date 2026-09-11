"""Fenced claim verification and immutable multi-call overview provenance."""

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0025_overview_claim_ledger"
down_revision = "0024_section_candidates"
branch_labels = None
depends_on = None
SCHEMA = "bidops"
MIGRATION_EVENT_ID = "audit-" + uuid5(NAMESPACE_URL, "bidops:db.migration:" + revision).hex


def _attempt_constraints(*, upgraded: bool) -> None:
    extra = ",'needs_human_review'" if upgraded else ""
    constraints = {
        "status": f"status IN ('queued','running','completed','failed','cancelled'{extra})",
        "target_scope": f"(status IN ('queued','running','completed'{extra}) AND target_id IS NOT NULL) OR status IN ('failed','cancelled')",
        "completion": (
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND result_id IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND result_id IS NULL) OR "
            f"(status IN ('failed','cancelled'{extra}) AND completed_at IS NOT NULL AND result_id IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND result_id IS NOT NULL)"
        ),
    }
    for name, expression in constraints.items():
        name = "ck_prespec_v4_attempt_" + name
        op.drop_constraint(name, "prespec_v4_attempt", schema=SCHEMA)
        op.create_check_constraint(name, "prespec_v4_attempt", expression, schema=SCHEMA)
    definition = op.get_bind().scalar(sa.text(
        "SELECT pg_get_functiondef('bidops.tf_prespec_v4_attempt_guard()'::regprocedure)"
    ))
    old = "('completed','failed','cancelled')"
    new = "('completed','failed','cancelled','needs_human_review')"
    source, target = (old, new) if upgraded else (new, old)
    if definition.count(source) != 2:
        raise RuntimeError("unexpected v4 attempt guard; migration refused")
    op.execute(definition.replace(source, target))


def upgrade() -> None:
    op.alter_column("prespec_v4_attempt", "status", type_=sa.String(32), existing_type=sa.String(16), schema=SCHEMA)
    op.add_column("prespec_v4_attempt", sa.Column("activation_id", sa.UUID(), nullable=True), schema=SCHEMA)
    op.create_foreign_key("fk_prespec_v4_attempt_activation", "prespec_v4_attempt", "audit_event", ["activation_id"], ["id"], source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="RESTRICT")
    _attempt_constraints(upgraded=True)
    op.create_index("ix_prespec_v4_attempt_job", "prespec_v4_attempt", ["work_job_id"], schema=SCHEMA)
    op.create_table(
        "prespec_overview_call_event",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), sa.ForeignKey("bidops.prespec_v4_attempt.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("event_kind", sa.String(16), nullable=False),
        *[sa.Column(name, sa.String(64), nullable=False) for name in ("input_sha256", "prompt_sha256", "binding_digest")],
        sa.Column("raw_response_sha256", sa.String(64), nullable=True),
        sa.Column("raw_response_content_object_id", sa.UUID(), sa.ForeignKey("bidops.content_object.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("raw_response_location_id", sa.UUID(), sa.ForeignKey("bidops.content_object_location.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        *[sa.Column(name, sa.Integer(), nullable=True) for name in ("prompt_tokens", "output_tokens", "latency_ms")],
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("call_id", "event_kind", name="uq_overview_call_event_kind"),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 3", name="ck_overview_call_ordinal"),
        sa.CheckConstraint("stage IN ('draft','semantic')", name="ck_overview_call_stage"),
        sa.CheckConstraint("event_kind IN ('dispatch','response','error')", name="ck_overview_call_kind"),
        sa.CheckConstraint(
            "(event_kind = 'dispatch' AND raw_response_sha256 IS NULL AND error_code IS NULL "
            "AND prompt_tokens IS NULL AND output_tokens IS NULL AND latency_ms IS NULL) OR "
            "(event_kind = 'response' AND raw_response_sha256 IS NOT NULL "
            "AND raw_response_content_object_id IS NOT NULL AND error_code IS NULL) OR "
            "(event_kind = 'error' AND error_code IS NOT NULL)", name="ck_overview_call_outcome"),
        sa.CheckConstraint(
            "(raw_response_content_object_id IS NULL AND raw_response_location_id IS NULL) OR "
            "(raw_response_content_object_id IS NOT NULL AND raw_response_location_id IS NOT NULL "
            "AND raw_response_sha256 IS NOT NULL)", name="ck_overview_call_storage"),
        sa.CheckConstraint(" AND ".join(f"({name} IS NULL OR {name} ~ '^[0-9a-f]{{64}}$')" for name in ("input_sha256", "prompt_sha256", "binding_digest", "raw_response_sha256")), name="ck_overview_call_hashes"),
        sa.CheckConstraint("prompt_tokens >= 0 AND output_tokens >= 0 AND latency_ms >= 0", name="ck_overview_call_metrics"),
        sa.CheckConstraint("error_code IS NULL OR error_code ~ '^[a-z0-9_]{1,64}$'", name="ck_overview_call_error"),
        schema=SCHEMA,
    )
    for name, columns, predicate in (
        ("uq_overview_call_terminal", ["call_id"], "event_kind IN ('response','error')"),
        ("uq_overview_call_ordinal", ["attempt_id", "ordinal"], "event_kind = 'dispatch'"),
        ("uq_overview_call_semantic", ["attempt_id"], "event_kind = 'dispatch' AND stage = 'semantic'"),
    ):
        op.create_index(name, "prespec_overview_call_event", columns, unique=True, postgresql_where=sa.text(predicate), schema=SCHEMA)
    op.create_table(
        "prespec_overview_verification",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("attempt_id", sa.UUID(), sa.ForeignKey("bidops.prespec_v4_attempt.id", ondelete="RESTRICT"), nullable=False),
        *[sa.Column(name, sa.String(64), nullable=False) for name in (
            "schema_version", "draft_sha256", "input_sha256", "policy_digest", "binding_digest",
            "model_digest", "validator_version", "payload_sha256")],
        sa.Column("payload_jsonb", JSONB(), nullable=False),
        sa.Column("overall", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("attempt_id", name="uq_overview_verification_attempt"),
        sa.CheckConstraint("schema_version = 'bidops.prespec-overview-claim-checks.v1'", name="ck_overview_verification_schema"),
        sa.CheckConstraint("overall IN ('passed','needs_human_review')", name="ck_overview_verification_overall"),
        sa.CheckConstraint("jsonb_typeof(payload_jsonb) = 'object'", name="ck_overview_verification_payload"),
        sa.CheckConstraint(" AND ".join(f"{name} ~ '^[0-9a-f]{{64}}$'" for name in ("draft_sha256", "input_sha256", "policy_digest", "binding_digest", "model_digest", "payload_sha256")), name="ck_overview_verification_hashes"),
        schema=SCHEMA,
    )
    op.add_column("prespec_page_overview", sa.Column("verification_id", sa.UUID(), nullable=True), schema=SCHEMA)
    op.add_column("prespec_page_overview", sa.Column("verification_sha256", sa.String(64), nullable=True), schema=SCHEMA)
    op.create_foreign_key("fk_page_overview_verification", "prespec_page_overview", "prespec_overview_verification", ["verification_id"], ["id"], source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="RESTRICT")
    op.drop_constraint("ck_prespec_page_overview_schema", "prespec_page_overview", schema=SCHEMA)
    op.create_check_constraint("ck_prespec_page_overview_schema", "prespec_page_overview", "schema_version IN ('bidops.prespec-overview-page-review.v3','bidops.prespec-overview-page-review.v4')", schema=SCHEMA)
    op.create_check_constraint("ck_prespec_page_overview_verification", "prespec_page_overview",
        "(schema_version = 'bidops.prespec-overview-page-review.v3' AND verification_id IS NULL AND verification_sha256 IS NULL) OR "
        "(schema_version = 'bidops.prespec-overview-page-review.v4' AND verification_id IS NOT NULL AND verification_sha256 IS NOT NULL "
        "AND validation_status = 'passed' AND evidence_check_status = 'passed')", schema=SCHEMA)
    op.execute(GUARDS)
    op.get_bind().execute(sa.text("""
INSERT INTO bidops.screening_audit_event
    (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
VALUES (:event_id,'db.migration','system:migration','database',:revision,
        '2026-01-01 00:00:25+00:00'::timestamptz,CAST(:details AS json))
ON CONFLICT (event_id) DO NOTHING
"""), {"event_id": MIGRATION_EVENT_ID, "revision": revision, "details": json.dumps({"migration_revision": revision, "action": "upgrade"})})


GUARDS = """
CREATE FUNCTION bidops.tf_overview_record_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'overview records are append-only'; END $$;
CREATE TRIGGER tr_overview_call_immutable BEFORE UPDATE OR DELETE ON bidops.prespec_overview_call_event
FOR EACH ROW EXECUTE FUNCTION bidops.tf_overview_record_immutable();
CREATE TRIGGER tr_overview_verification_immutable BEFORE UPDATE OR DELETE ON bidops.prespec_overview_verification
FOR EACH ROW EXECUTE FUNCTION bidops.tf_overview_record_immutable();

CREATE FUNCTION bidops.tf_overview_activation_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND current_user = 'app' AND NEW.status <> 'cancelled' THEN
    RAISE EXCEPTION 'app may only cancel v4 attempts';
  END IF;
  IF TG_OP = 'INSERT' AND NEW.status = 'needs_human_review' THEN
    RAISE EXCEPTION 'human review requires a running attempt';
  END IF;
  IF NEW.prompt_version = 'prespec-overview-v5' AND NEW.status IN ('queued','running')
     AND (NEW.activation_id IS NULL OR NEW.work_job_id IS NULL) THEN
    RAISE EXCEPTION 'new overview attempt requires activation and job';
  END IF;
  IF NEW.activation_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM bidops.audit_event e WHERE e.id = NEW.activation_id
      AND e.action = 'prespec_v4.activation' AND e.aggregate_type = 'prespec_v4_activation'
      AND e.safe_metadata->>'status' = 'active'
      AND e.safe_metadata->>'policy_digest' = NEW.policy_digest
      AND e.safe_metadata->'binding'->>'binding_digest' = NEW.binding_digest
      AND (NEW.prompt_version IS DISTINCT FROM 'prespec-overview-v5'
           OR e.safe_metadata->>'schema' = 'bidops.prespec-v4-activation.v2')
  ) THEN RAISE EXCEPTION 'overview activation binding rejected'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_overview_activation_guard BEFORE INSERT OR UPDATE ON bidops.prespec_v4_attempt
FOR EACH ROW EXECUTE FUNCTION bidops.tf_overview_activation_guard();

CREATE FUNCTION bidops.tf_overview_call_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE a bidops.prespec_v4_attempt; d bidops.prespec_overview_call_event;
BEGIN
  -- Serializes all events for this attempt, including opposing terminal kinds.
  SELECT * INTO a FROM bidops.prespec_v4_attempt WHERE id = NEW.attempt_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'overview call attempt missing'; END IF;
  IF NEW.binding_digest IS DISTINCT FROM a.binding_digest OR NEW.input_sha256 IS DISTINCT FROM a.input_sha256 THEN
    RAISE EXCEPTION 'overview call input binding rejected';
  END IF;
  IF NEW.event_kind = 'dispatch' THEN
    IF a.status <> 'running' OR a.activation_id IS NULL OR a.lease_expires_at <= CURRENT_TIMESTAMP THEN
      RAISE EXCEPTION 'overview dispatch requires live attempt';
    END IF;
    IF NEW.ordinal <> 1 + (SELECT count(*) FROM bidops.prespec_overview_call_event WHERE attempt_id = NEW.attempt_id AND event_kind = 'dispatch')
       OR (NEW.ordinal = 1 AND NEW.stage <> 'draft')
       OR (NEW.stage = 'draft' AND NEW.ordinal > 2)
       OR EXISTS (SELECT 1 FROM bidops.prespec_overview_call_event WHERE attempt_id = NEW.attempt_id AND stage = 'semantic' AND event_kind = 'dispatch')
    THEN RAISE EXCEPTION 'overview call budget rejected'; END IF;
  ELSE
    SELECT * INTO d FROM bidops.prespec_overview_call_event WHERE call_id = NEW.call_id AND event_kind = 'dispatch';
    IF NOT FOUND OR (d.attempt_id,d.ordinal,d.stage,d.input_sha256,d.prompt_sha256,d.binding_digest)
       IS DISTINCT FROM (NEW.attempt_id,NEW.ordinal,NEW.stage,NEW.input_sha256,NEW.prompt_sha256,NEW.binding_digest)
       OR NEW.created_at < d.created_at
    THEN RAISE EXCEPTION 'overview call dispatch mismatch'; END IF;
  END IF;
  IF NEW.raw_response_content_object_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM bidops.content_object o JOIN bidops.content_object_location l ON l.content_object_id=o.id
    WHERE o.id=NEW.raw_response_content_object_id AND o.sha256=NEW.raw_response_sha256
      AND l.id=NEW.raw_response_location_id AND l.namespace_key='model-response'
      AND l.status='verified' AND l.encryption_key_ref IS NOT NULL AND length(trim(l.encryption_key_ref)) > 0
  ) THEN RAISE EXCEPTION 'overview response storage binding rejected'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_overview_call_guard BEFORE INSERT ON bidops.prespec_overview_call_event
FOR EACH ROW EXECUTE FUNCTION bidops.tf_overview_call_guard();

CREATE FUNCTION bidops.tf_overview_verification_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE a bidops.prespec_v4_attempt; c jsonb; all_passed boolean;
BEGIN
  SELECT * INTO a FROM bidops.prespec_v4_attempt WHERE id=NEW.attempt_id FOR UPDATE;
  IF NOT FOUND OR a.status <> 'running' OR a.lease_expires_at <= CURRENT_TIMESTAMP OR a.activation_id IS NULL
     OR (a.input_sha256,a.policy_digest,a.binding_digest,a.model_digest)
        IS DISTINCT FROM (NEW.input_sha256,NEW.policy_digest,NEW.binding_digest,NEW.model_digest)
  THEN RAISE EXCEPTION 'overview verification attempt rejected'; END IF;
  IF NEW.payload_jsonb->>'schema_version' IS DISTINCT FROM NEW.schema_version
     OR NEW.payload_jsonb->>'attempt_id' IS DISTINCT FROM NEW.attempt_id::text
     OR NEW.payload_jsonb->>'draft_sha256' IS DISTINCT FROM NEW.draft_sha256
     OR NEW.payload_jsonb->>'input_sha256' IS DISTINCT FROM NEW.input_sha256
     OR NEW.payload_jsonb->>'policy_digest' IS DISTINCT FROM NEW.policy_digest
     OR NEW.payload_jsonb->>'binding_digest' IS DISTINCT FROM NEW.binding_digest
     OR NEW.payload_jsonb->>'validator_version' IS DISTINCT FROM NEW.validator_version
     OR NEW.payload_jsonb->>'overall' IS DISTINCT FROM NEW.overall
     OR jsonb_typeof(NEW.payload_jsonb->'checks') IS DISTINCT FROM 'array'
     OR jsonb_typeof(NEW.payload_jsonb->'analysis_checks') IS DISTINCT FROM 'array'
     OR jsonb_typeof(NEW.payload_jsonb->'unknown_checks') IS DISTINCT FROM 'array'
     OR jsonb_typeof(NEW.payload_jsonb->'reason_codes') IS DISTINCT FROM 'array'
  THEN RAISE EXCEPTION 'overview verification payload binding rejected'; END IF;
  all_passed := jsonb_array_length(NEW.payload_jsonb->'checks') > 0 AND NEW.payload_jsonb->'reason_codes' = '[]'::jsonb;
  FOR c IN SELECT value FROM jsonb_array_elements(NEW.payload_jsonb->'checks') LOOP
    all_passed := all_passed AND c->'deterministic'->>'status' IS NOT DISTINCT FROM 'passed'
      AND c->'semantic'->>'status' IS NOT DISTINCT FROM 'supported'
      AND c->'deterministic'->'reason_codes' IS NOT DISTINCT FROM '[]'::jsonb
      AND c->'semantic'->'reason_codes' IS NOT DISTINCT FROM '[]'::jsonb
      AND jsonb_typeof(c->'deterministic'->'verified_evidence') IS NOT DISTINCT FROM 'array'
      AND c->'deterministic'->'verified_evidence' <> '[]'::jsonb;
  END LOOP;
  FOR c IN SELECT value FROM jsonb_array_elements((NEW.payload_jsonb->'analysis_checks') || (NEW.payload_jsonb->'unknown_checks')) LOOP
    all_passed := all_passed AND c->>'status' IS NOT DISTINCT FROM 'supported'
      AND c->'reason_codes' IS NOT DISTINCT FROM '[]'::jsonb;
  END LOOP;
  IF (NEW.overall = 'passed') IS DISTINCT FROM all_passed THEN
    RAISE EXCEPTION 'overview verification outcome rejected';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_overview_verification_guard BEFORE INSERT ON bidops.prespec_overview_verification
FOR EACH ROW EXECUTE FUNCTION bidops.tf_overview_verification_guard();

CREATE FUNCTION bidops.tf_overview_result_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v bidops.prespec_overview_verification; a bidops.prespec_v4_attempt; section text; facts jsonb;
BEGIN
  IF NEW.payload_jsonb->>'schema_version' IS DISTINCT FROM NEW.schema_version THEN
    RAISE EXCEPTION 'overview result schema mismatch';
  END IF;
  IF NEW.schema_version = 'bidops.prespec-overview-page-review.v3' THEN RETURN NEW; END IF;
  SELECT * INTO v FROM bidops.prespec_overview_verification WHERE id=NEW.verification_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'overview result verification missing'; END IF;
  SELECT * INTO a FROM bidops.prespec_v4_attempt WHERE id=v.attempt_id FOR UPDATE;
  IF a.status <> 'running' OR a.lease_expires_at <= CURRENT_TIMESTAMP
     OR v.overall <> 'passed' OR v.payload_sha256 IS DISTINCT FROM NEW.verification_sha256
     OR (a.id,a.notice_id,a.document_version_id,a.input_sha256,a.source_sha256,a.pdf_sha256,a.policy_digest,a.model_digest)
        IS DISTINCT FROM (NEW.run_id,NEW.notice_id,NEW.document_version_id,NEW.input_sha256,NEW.source_sha256,NEW.pdf_sha256,NEW.policy_digest,NEW.model_digest)
     OR NEW.payload_jsonb->>'verification_id' IS DISTINCT FROM NEW.verification_id::text
     OR NEW.payload_jsonb->>'verification_sha256' IS DISTINCT FROM NEW.verification_sha256
  THEN RAISE EXCEPTION 'overview result verification binding rejected'; END IF;
  FOREACH section IN ARRAY ARRAY['business_overview','main_tasks','budget_and_period','important_conditions'] LOOP
    SELECT COALESCE(jsonb_agg(jsonb_build_object('claim_id',c->'claim_id','text',c->'text','evidence',c->'deterministic'->'verified_evidence')), '[]'::jsonb)
      INTO facts FROM jsonb_array_elements(v.payload_jsonb->'checks') c WHERE c->>'section'=section;
    IF NEW.payload_jsonb->section IS DISTINCT FROM facts THEN
      RAISE EXCEPTION 'overview result facts differ from verified claims';
    END IF;
  END LOOP;
  IF NEW.payload_jsonb->'reviewer_analysis' IS DISTINCT FROM v.payload_jsonb->'analysis' THEN
    RAISE EXCEPTION 'overview result analysis differs from verified analysis';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_overview_result_guard BEFORE INSERT ON bidops.prespec_page_overview
FOR EACH ROW EXECUTE FUNCTION bidops.tf_overview_result_guard();

CREATE FUNCTION bidops.assert_overview_publication(attempt_uuid uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE a bidops.prespec_v4_attempt; v bidops.prespec_overview_verification; r bidops.prespec_page_overview; j bidops.work_job;
BEGIN
  SELECT * INTO a FROM bidops.prespec_v4_attempt WHERE id=attempt_uuid;
  IF NOT FOUND THEN RETURN; END IF;
  SELECT * INTO v FROM bidops.prespec_overview_verification WHERE attempt_id=a.id;
  IF a.prompt_version IS DISTINCT FROM 'prespec-overview-v5' AND v.id IS NULL AND a.status <> 'needs_human_review' THEN RETURN; END IF;
  IF a.status IN ('completed','needs_human_review') THEN
    IF v.id IS NULL OR (a.status='completed') IS DISTINCT FROM (v.overall='passed') THEN
      RAISE EXCEPTION 'overview terminal requires matching verification';
    END IF;
    IF a.status='completed' THEN
      SELECT * INTO r FROM bidops.prespec_page_overview WHERE id=a.result_id;
      IF NOT FOUND OR r.schema_version <> 'bidops.prespec-overview-page-review.v4'
         OR r.verification_id IS DISTINCT FROM v.id OR r.verification_sha256 IS DISTINCT FROM v.payload_sha256
         OR r.payload_sha256 IS DISTINCT FROM a.result_sha256 THEN
        RAISE EXCEPTION 'overview completed result binding rejected';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM bidops.prespec_overview_call_event WHERE attempt_id=a.id AND stage='semantic' AND event_kind='response')
         OR NOT EXISTS (SELECT 1 FROM bidops.prespec_overview_call_event WHERE attempt_id=a.id AND stage='draft' AND event_kind='response') THEN
        RAISE EXCEPTION 'overview completed requires draft and semantic responses';
      END IF;
    END IF;
  ELSIF v.id IS NOT NULL THEN
    RAISE EXCEPTION 'overview verification must terminate attempt atomically';
  END IF;
  IF a.work_job_id IS NOT NULL THEN
    SELECT * INTO j FROM bidops.work_job WHERE id=a.work_job_id;
    IF NOT FOUND OR j.job_type <> 'prespec_v4_overview' OR j.aggregate_type <> 'prespec_v4_target' OR j.aggregate_id IS DISTINCT FROM a.target_id
       OR j.status IS DISTINCT FROM (CASE WHEN a.status='needs_human_review' THEN 'failed' ELSE a.status END)
       OR (a.status='running' AND (j.lease_owner,j.lease_expires_at) IS DISTINCT FROM (a.lease_owner,a.lease_expires_at))
       OR (a.status NOT IN ('queued','running') AND (j.completed_at IS NULL OR j.lease_owner IS NOT NULL OR j.lease_expires_at IS NOT NULL))
       OR (a.status='needs_human_review' AND j.last_error_code IS DISTINCT FROM 'claim_verification_required')
    THEN RAISE EXCEPTION 'overview job outcome must commit atomically'; END IF;
  ELSIF a.target_id IS NOT NULL THEN
    RAISE EXCEPTION 'overview execution requires job';
  END IF;
END $$;

CREATE FUNCTION bidops.tf_overview_publication_atomic() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE attempt_uuid uuid;
BEGIN
  IF TG_TABLE_NAME = 'prespec_v4_attempt' THEN
    PERFORM bidops.assert_overview_publication(NEW.id);
  ELSIF TG_TABLE_NAME = 'prespec_overview_verification' THEN
    PERFORM bidops.assert_overview_publication(NEW.attempt_id);
  ELSIF TG_TABLE_NAME = 'prespec_page_overview' THEN
    IF NEW.schema_version = 'bidops.prespec-overview-page-review.v4' THEN
      SELECT attempt_id INTO attempt_uuid FROM bidops.prespec_overview_verification WHERE id=NEW.verification_id;
      PERFORM bidops.assert_overview_publication(attempt_uuid);
      IF NOT EXISTS (SELECT 1 FROM bidops.prespec_v4_attempt WHERE id=attempt_uuid AND status='completed' AND result_id=NEW.id) THEN
        RAISE EXCEPTION 'overview result must terminate attempt atomically';
      END IF;
    END IF;
  ELSE
    FOR attempt_uuid IN SELECT id FROM bidops.prespec_v4_attempt WHERE work_job_id=NEW.id LOOP
      PERFORM bidops.assert_overview_publication(attempt_uuid);
    END LOOP;
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER tr_overview_attempt_atomic AFTER INSERT OR UPDATE ON bidops.prespec_v4_attempt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bidops.tf_overview_publication_atomic();
CREATE CONSTRAINT TRIGGER tr_overview_verification_atomic AFTER INSERT ON bidops.prespec_overview_verification
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bidops.tf_overview_publication_atomic();
CREATE CONSTRAINT TRIGGER tr_overview_result_atomic AFTER INSERT ON bidops.prespec_page_overview
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bidops.tf_overview_publication_atomic();
CREATE CONSTRAINT TRIGGER tr_overview_job_atomic AFTER UPDATE ON bidops.work_job
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bidops.tf_overview_publication_atomic();
"""


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("""
SELECT EXISTS (SELECT 1 FROM bidops.prespec_overview_call_event)
 OR EXISTS (SELECT 1 FROM bidops.prespec_overview_verification)
 OR EXISTS (SELECT 1 FROM bidops.prespec_v4_attempt WHERE activation_id IS NOT NULL OR status='needs_human_review')
 OR EXISTS (SELECT 1 FROM bidops.prespec_page_overview WHERE verification_id IS NOT NULL)
""")):
        raise RuntimeError("overview claim records exist; downgrade refused")
    for table, trigger in (
        ("prespec_v4_attempt", "tr_overview_attempt_atomic"),
        ("prespec_v4_attempt", "tr_overview_activation_guard"),
        ("prespec_page_overview", "tr_overview_result_atomic"),
        ("prespec_page_overview", "tr_overview_result_guard"),
        ("work_job", "tr_overview_job_atomic"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON bidops.{table}")
    op.drop_constraint("ck_prespec_page_overview_verification", "prespec_page_overview", schema=SCHEMA)
    op.drop_constraint("fk_page_overview_verification", "prespec_page_overview", schema=SCHEMA)
    op.drop_column("prespec_page_overview", "verification_sha256", schema=SCHEMA)
    op.drop_column("prespec_page_overview", "verification_id", schema=SCHEMA)
    op.drop_constraint("ck_prespec_page_overview_schema", "prespec_page_overview", schema=SCHEMA)
    op.create_check_constraint("ck_prespec_page_overview_schema", "prespec_page_overview", "schema_version = 'bidops.prespec-overview-page-review.v3'", schema=SCHEMA)
    op.drop_table("prespec_overview_verification", schema=SCHEMA)
    op.drop_table("prespec_overview_call_event", schema=SCHEMA)
    for name in ("tf_overview_publication_atomic()", "assert_overview_publication(uuid)", "tf_overview_result_guard()", "tf_overview_verification_guard()", "tf_overview_call_guard()", "tf_overview_activation_guard()", "tf_overview_record_immutable()"):
        op.execute(f"DROP FUNCTION bidops.{name}")
    _attempt_constraints(upgraded=False)
    op.drop_index("ix_prespec_v4_attempt_job", table_name="prespec_v4_attempt", schema=SCHEMA)
    op.drop_constraint("fk_prespec_v4_attempt_activation", "prespec_v4_attempt", schema=SCHEMA)
    op.drop_column("prespec_v4_attempt", "activation_id", schema=SCHEMA)
    op.alter_column("prespec_v4_attempt", "status", type_=sa.String(16), existing_type=sa.String(32), schema=SCHEMA)
    op.get_bind().execute(sa.text("DELETE FROM bidops.screening_audit_event WHERE event_id=:event_id"), {"event_id": MIGRATION_EVENT_ID})
