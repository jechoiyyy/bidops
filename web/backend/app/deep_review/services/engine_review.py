"""Human review commands and read-only projection for wiki-scoped engine runs."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select

from ...core.config import get_settings
from ...core.models import AuditEvent, IdempotencyRecord
from ...lifecycle import (
    active_opportunity_predicate, authoritative_link_predicate, lock_notice, lock_opportunity,
)
from ...lifecycle.models import Notice, Opportunity, OpportunityLink
from ..models import (
    EngineReviewAcknowledgment, EngineReviewApproval, EngineReviewPreview,
    EngineReviewRequest, EngineRun,
)
from ..schemas import engine_review as wire
from . import engine_review_inputs as inputs, engine_runs
from .engine_review_scope import TRACKING, TRACKING_ACTIVE_STATUSES, latest_pre_spec, tracking_ended_since
from .engine_runs import EngineRunError

TTL = timedelta(hours=24)
RESULT_STATUSES = {"completed", "partial"}
AGGREGATE = "engine_review"


def _now():
    return datetime.now(UTC)


def review_mode():
    return getattr(get_settings(), "engine_review_mode", "off")


def _mode_error(mode, *, preview=False):
    # `live` previews and approvals are open (ADR-0081); what leaves is bounded by the approved
    # manifest, the KST caps and the worker's key. Without the analysis switch nothing runs.
    if mode == "off":
        return "engine_disabled"
    if not engine_runs.engine_analysis_enabled():
        return "engine_disabled"
    return None


def _require_mode(mode, *, preview=False, request=False):
    error = _mode_error(mode, preview=preview)
    if error:
        raise EngineRunError(error, 409 if request and mode != "off" else 503)


def _owners(notice_ids):
    return (
        select(OpportunityLink.notice_id, Opportunity)
        .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
        .where(
            OpportunityLink.notice_id.in_(notice_ids),
            OpportunityLink.stage == "notice",
            authoritative_link_predicate(OpportunityLink),
            active_opportunity_predicate(Opportunity),
        )
    )


def _lock_scope(session, notice_id):
    # Tracking writes lock the opportunity first. Document mutations use the
    # notice lock, so revalidation and freezing use that same fence.
    owner_query = _owners([notice_id]).with_only_columns(Opportunity.id)
    owner_id = session.scalar(owner_query)
    owner = lock_opportunity(session, owner_id) if owner_id is not None else None
    notice = lock_notice(session, notice_id)
    if notice is None:
        raise EngineRunError("not_found", 404)
    session.refresh(notice)
    if notice.source_type != "pre_spec":
        raise EngineRunError("not_found", 404)
    if session.scalar(owner_query) != owner_id:
        raise EngineRunError("input_changed")
    if owner is not None:
        session.refresh(owner)
    latest = session.scalar(select(latest_pre_spec()).select_from(Notice).where(Notice.id == notice_id))
    return notice, latest, owner


def _open_request(session, notice_id):
    return session.scalar(select(EngineReviewRequest).where(
        EngineReviewRequest.notice_id == notice_id, EngineReviewRequest.closed_at.is_(None),
    ).with_for_update().execution_options(populate_existing=True))


def _audit(session, action, actor, row_id, command_id, **metadata):
    audit = AuditEvent(
        id=uuid4(), actor_kind="human", claimed_name=actor, action=f"engine_review.{action}",
        aggregate_type=AGGREGATE, aggregate_id=str(row_id),
        request_id=str(command_id), safe_metadata=metadata,
    )
    session.add(audit)
    return audit.id


def _close(session, row, reason, actor, command_id):
    row.closed_at, row.closed_reason, row.closed_by = _now(), reason, actor
    _audit(session, "closed", actor, row.id, command_id, notice_id=row.notice_id, reason=reason)
    session.flush()


def _tracking_ended_after_request(session, row):
    return session.scalar(select(tracking_ended_since(row.opportunity_id, row.requested_at)))


def _close_if_ended(session, row, owner, actor, command_id, *, reopen=False):
    if row is None:
        return None
    active = owner is not None and owner.tracking_status in TRACKING_ACTIVE_STATUSES
    if active and not _tracking_ended_after_request(session, row):
        return row
    _close(session, row, "tracking_ended", actor, command_id)
    if not reopen or not active:
        # Persist the observed close even when this command must be rejected.
        session.commit()
    return None


def _eligible(notice, latest, owner, *, allow_hold=False):
    if not latest:
        raise EngineRunError("notice_not_latest")
    if notice.review_exclusion_status == "excluded":
        raise EngineRunError("review_excluded")
    if not owner or owner.tracking_status not in (TRACKING_ACTIVE_STATUSES if allow_hold else (TRACKING,)):
        raise EngineRunError("tracking_required")


def _replay(session, action, notice_id, request_id, actor, **scope):
    # Lock request IDs across actors and notices for this command. The receipt
    # constraints still independently protect the actual business rows.
    operation = f"engine_review.{action}"
    if session.get_bind().dialect.name == "postgresql":
        key = int(inputs.digest({"operation": operation, "request_id": str(request_id)})[:16], 16)
        session.execute(select(func.pg_advisory_xact_lock(key - 2**63)))
    fingerprint = inputs.digest(scope)
    record = session.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.operation == operation, IdempotencyRecord.request_id == request_id,
    ))
    if record and (record.aggregate_id, record.claimed_name, record.request_sha256) != (
        str(notice_id), actor, fingerprint,
    ):
        raise EngineRunError("idempotency_conflict")
    return record, fingerprint


def _save_replay(session, action, notice_id, request_id, actor, fingerprint, receipt, status=200):
    session.add(IdempotencyRecord(
        operation=f"engine_review.{action}", aggregate_type=AGGREGATE,
        aggregate_id=str(notice_id), claimed_name=actor, request_id=request_id,
        request_sha256=fingerprint, response_status=status, response_snapshot={"receipt_id": str(receipt)},
    ))


def _receipt_id(record):
    return UUID(record.response_snapshot["receipt_id"])


def _request_receipt(row):
    return wire.RequestReceipt.model_validate(row)


def _preview_receipt(row, session=None):
    budget = None
    if session is not None and row.mode == "live":
        from . import engine_live  # noqa: PLC0415

        budget = engine_live.budget_snapshot(
            session, notice_id=row.manifest["notice_id"], today=engine_live.kst_today(_now()),
        )
    return wire.PreviewReceipt(
        preview_id=row.id, manifest_sha256=row.manifest_sha256, created_at=row.created_at,
        expires_at=row.expires_at, manifest=row.manifest, budget=budget,
    )


def _require_live_budget(session, notice_id, planned_calls):
    """A live approval is refused when today's caps leave no room for this notice's planned calls."""
    from . import engine_live  # noqa: PLC0415

    budget = engine_live.budget_snapshot(session, notice_id=notice_id, today=engine_live.kst_today(_now()))
    if (not budget["notice_allowed_today"] or budget["remaining_calls_today"] < planned_calls
            or budget["remaining_notice_calls"] < planned_calls or budget["remaining_usd_today"] <= 0):
        raise EngineRunError("budget_exhausted")


def _approval_receipt(session, row):
    run = session.get(EngineRun, row.engine_run_id, populate_existing=True)
    return wire.ApprovalReceipt(approval_id=row.id, run_id=run.id, state=run.status)


def _ack_receipt(row):
    return wire.AcknowledgmentReceipt(
        acknowledgment_id=row.id, result_id=row.engine_run_id, request_id=row.request_id,
        acknowledged_by=row.acknowledged_by, acknowledged_at=row.acknowledged_at,
    )


def _latest_runs(session, notice_ids):
    ranked = (
        select(
            EngineRun.id.label("run_id"),
            EngineReviewPreview.review_request_id,
            func.row_number().over(
                partition_by=EngineRun.notice_id,
                order_by=(EngineRun.created_at.desc(), EngineRun.id.desc()),
            ).label("rank"),
        )
        .join(EngineReviewApproval, EngineReviewApproval.engine_run_id == EngineRun.id)
        .join(EngineReviewPreview, EngineReviewPreview.id == EngineReviewApproval.preview_id)
        .where(EngineRun.notice_id.in_(notice_ids))
        .subquery()
    )
    return {
        run.notice_id: (run, request_id)
        for run, request_id in session.execute(
            select(EngineRun, ranked.c.review_request_id)
            .join(ranked, ranked.c.run_id == EngineRun.id)
            .where(ranked.c.rank == 1)
            .execution_options(populate_existing=True)
        )
    }


def _publishable(run, freshness):
    return run and run.status in RESULT_STATUSES and freshness == "current" and run.result_payload


LIVE_RUN_FAILURES = frozenset({
    "engine_live_key_unavailable", "engine_live_not_approved", "engine_live_deadline",
    "engine_live_process_failed", "engine_live_output_invalid", "engine_live_lease_lost",
    "engine_live_audit_failed", "http_error", "response_incomplete", "outcome_unknown",
    "frame_invalid", "frame_order_invalid", "frame_body_invalid", "frame_document_changed",
    "request_too_large", "planned_calls_exceeded", "engine_pipeline_failed", "lease_expired",
    "engine_execution_failed", "engine_output_invalid", "engine_version_changed",
})


def _readiness_reason(error_code):
    if error_code in {"company_bundle_unavailable", "company_bundle_invalid", "unsafe_document",
                      "original_hwp_required", "documents_pending", "structure_unavailable",
                      "budget_exhausted", "input_changed"}:
        return error_code
    if error_code in LIVE_RUN_FAILURES:
        return "live_run_failed"
    return "structure_unavailable"


def review_states(session, notice_ids):
    """Use a fixed number of SQL statements for an entire page or workload."""
    ids = tuple(dict.fromkeys(notice_ids))
    mode = review_mode()
    disabled = _mode_error(mode)
    if not ids:
        return {}
    if disabled:
        return {notice_id: wire.ReviewState(state="not_requested", reason=disabled) for notice_id in ids}

    notices = {
        notice.id: (notice, latest)
        for notice, latest in session.execute(
            select(Notice, latest_pre_spec().label("latest"))
            .where(Notice.id.in_(ids), Notice.source_type == "pre_spec")
            .execution_options(populate_existing=True)
        )
    }
    owners = dict(session.execute(_owners(ids).execution_options(populate_existing=True)).tuples().all())
    open_rows = {
        row.notice_id: row for row in session.scalars(select(EngineReviewRequest).where(
            EngineReviewRequest.notice_id.in_(ids), EngineReviewRequest.closed_at.is_(None),
            ~tracking_ended_since(EngineReviewRequest.opportunity_id, EngineReviewRequest.requested_at),
        ))
        if row.notice_id in owners and owners[row.notice_id].tracking_status in TRACKING_ACTIVE_STATUSES
        and row.opportunity_id == owners[row.notice_id].id
    }
    runs = _latest_runs(session, ids)
    company, company_error = None, None
    if open_rows or runs:
        try:
            company = inputs.load_company()
            if open_rows and mode == "mock_reference":
                inputs.company_metadata(company)
        except EngineRunError as error:
            company_error = _readiness_reason(error.code)
    identity = (company["slug"], company["bundle_sha256"]) if company else None
    freshness = engine_runs.currentness_many(session, [run for run, _ in runs.values()], wiki_identity=identity)
    receipts = {
        row.engine_run_id: row for row in session.scalars(select(EngineReviewAcknowledgment).where(
            EngineReviewAcknowledgment.engine_run_id.in_([run.id for run, _ in runs.values()]),
        ))
    } if runs else {}
    ready_ids = [
        notice_id for notice_id, row in open_rows.items()
        if notice_id not in runs or runs[notice_id][1] != row.id
    ]
    bundles, reasons = inputs.readiness_many(session, ready_ids) if ready_ids else ({}, {})
    previews = {}
    code_digest = None
    if ready_ids and company and not company_error and mode == "mock_reference":
        now = _now()
        for preview in session.scalars(
            select(EngineReviewPreview)
            .where(EngineReviewPreview.review_request_id.in_([open_rows[id_].id for id_ in ready_ids]),
                   EngineReviewPreview.expires_at > now)
            .order_by(EngineReviewPreview.created_at.desc(), EngineReviewPreview.id.desc())
        ):
            if inputs.has_unverified_page_count(preview.manifest):
                continue
            previews.setdefault(preview.review_request_id, preview)
        if previews:
            try:
                code_digest = engine_runs.engine_digest()
            except (EngineRunError, OSError):
                company_error = "structure_unavailable"

    def project(notice_id):
        notice, latest = notices.get(notice_id, (None, False))
        owner = owners.get(notice_id)
        tracking = owner.tracking_status if owner else None
        available = notice is not None and latest and notice.review_exclusion_status != "excluded"
        can_request = available and tracking == TRACKING
        row = open_rows.get(notice_id)
        run, run_request = runs.get(notice_id, (None, None))
        currentness = freshness[run.id] if run else None
        if not available and run:
            currentness = "stale"
        fields = {"request": _request_receipt(row) if row else None}
        if available and row and run and run_request == row.id:
            if currentness == "current" and run.status in {"queued", "running"}:
                return wire.ReviewState(state=run.status, **fields)
            if _publishable(run, currentness):
                receipt = receipts.get(run.id)
                return wire.ReviewState(
                    state="acknowledged" if receipt else "result_ready",
                    next_action=None if receipt else "review_result",
                    current_result=engine_runs.view(session, run, currentness),
                    review_receipt=_ack_receipt(receipt) if receipt else None, **fields,
                )
            if run.status == "failed" and currentness == "current":
                return wire.ReviewState(
                    state="blocked", next_action="resolve_exception",
                    reason=_readiness_reason(run.error_code), **fields,
                )
        if run and currentness != "current" and (not row or run_request == row.id):
            return wire.ReviewState(
                state="stale", next_action="request" if can_request else None,
                reason="input_changed" if currentness == "stale" else company_error or "input_changed",
                current_result=engine_runs.view(session, run, currentness) if run.result_payload else None, **fields,
            )
        if not row or not available:
            return wire.ReviewState(
                state="not_requested", next_action="request" if can_request else None,
                reason=None if tracking in TRACKING_ACTIVE_STATUSES else "tracking_required",
            )
        if identity and row.company_bundle_slug != identity[0]:
            return wire.ReviewState(
                state="stale", reason="input_changed", next_action="request" if can_request else None, **fields,
            )
        reason = _mode_error(mode, preview=True) or company_error or reasons.get(notice_id)
        if reason == "documents_pending":
            return wire.ReviewState(state="preparing", reason=reason, **fields)
        if reason:
            return wire.ReviewState(state="blocked", next_action="resolve_exception", reason=reason, **fields)
        preview = previews.get(row.id)
        bundle = bundles[notice_id]
        if preview and (
            preview.bundle_id != bundle.id
            or preview.manifest["company_bundle_sha256"] != identity[1]
            or preview.manifest["engine_sha256"] != code_digest
            or preview.manifest["title"] != (notice.title or "공고명 미확인")
        ):
            preview = None
        return wire.ReviewState(
            state="awaiting_approval", next_action="approve" if tracking == TRACKING else None,
            reason=None if tracking == TRACKING else "tracking_required",
            preview=_preview_receipt(preview, session) if preview else None, **fields,
        )

    return {notice_id: project(notice_id) for notice_id in ids}


def review_state(session, notice_id):
    if review_mode() != "off" and not session.scalar(
        select(Notice.id).where(Notice.id == notice_id, Notice.source_type == "pre_spec")
    ):
        raise EngineRunError("not_found", 404)
    return review_states(session, [notice_id])[notice_id]


def request_review(session, notice_id, payload, actor, *, include_state=True):
    mode = review_mode()
    _require_mode(mode, request=True)
    notice, latest, owner = _lock_scope(session, notice_id)
    previous = _open_request(session, notice_id)
    row = _close_if_ended(session, previous, owner, actor, payload.request_id, reopen=True)
    try:
        record, fingerprint = _replay(
            session, "request", notice_id, payload.request_id, actor, origin=payload.origin,
        )
        if not record:
            _eligible(notice, latest, owner)
            company = inputs.load_company()
    except EngineRunError:
        if previous and row is None and previous.closed_reason == "tracking_ended":
            session.commit()
        raise
    if record:
        receipt = _request_receipt(session.get(EngineReviewRequest, _receipt_id(record)))
        session.commit()
        return receipt, False, review_state(session, notice_id).state if include_state else None
    if row:
        run, run_request = _latest_runs(session, [notice_id]).get(notice_id, (None, None))
        replace = row.company_bundle_slug != company["slug"] or row.opportunity_id != owner.id
        if run and run_request == row.id:
            identity = (company["slug"], company["bundle_sha256"])
            freshness = engine_runs.currentness_many(session, [run], wiki_identity=identity)[run.id]
            replace |= freshness == "stale" or run.status == "failed"
        if replace:
            _close(session, row, "superseded", actor, payload.request_id)
            row = None
    created = row is None
    if created:
        row = EngineReviewRequest(
            id=uuid4(), notice_id=notice_id, opportunity_id=owner.id,
            company_bundle_slug=company["slug"], origin=payload.origin, requested_by=actor,
            requested_at=_now(), request_id=payload.request_id,
        )
        session.add(row)
        _audit(session, "requested", actor, row.id, payload.request_id,
               notice_id=notice_id, opportunity_id=owner.id, origin=payload.origin)
        # Flushes the request before checking the attachment eligibility predicate.
        from .prespec_attachments import refresh_fetch_eligibility
        refresh_fetch_eligibility(session, notice_ids=[notice_id])
    _save_replay(session, "request", notice_id, payload.request_id, actor, fingerprint, row.id,
                 201 if created else 200)
    receipt = _request_receipt(row)
    session.commit()
    if created:
        # This also handles originals that were acquired before the request.
        # It uses the existing isolated, retryable preparation path.
        from .auto_preparation import maybe_auto_prepare
        maybe_auto_prepare(session, [notice_id])
        session.commit()
    return receipt, created, review_state(session, notice_id).state if include_state else None


def request_review_batch(session, payload, actor):
    _require_mode(review_mode(), request=True)
    if not 1 <= len(payload.notice_ids) <= 200 or payload.origin != "tracking_start":
        raise EngineRunError("invalid_batch", 422)
    items = []
    for notice_id in dict.fromkeys(payload.notice_ids):
        command = wire.RequestCommand(request_id=uuid5(payload.request_id, str(notice_id)), origin=payload.origin)
        try:
            receipt, created, _ = request_review(session, notice_id, command, actor, include_state=False)
            items.append(wire.BatchResult(
                notice_id=notice_id, outcome="requested" if created else "already_requested", request=receipt,
            ))
        except EngineRunError as error:
            session.rollback()
            items.append(wire.BatchResult(notice_id=notice_id, outcome="ineligible", reason=error.code))
        except Exception:
            session.rollback()
            items.append(wire.BatchResult(notice_id=notice_id, outcome="ineligible", reason="engine_unavailable"))
    return wire.BatchResponse(items=items)


def _preview_scope(session, notice_id, preview_id):
    return session.execute(
        select(EngineReviewPreview, EngineReviewRequest)
        .join(EngineReviewRequest, EngineReviewRequest.id == EngineReviewPreview.review_request_id)
        .where(EngineReviewPreview.id == preview_id, EngineReviewRequest.notice_id == notice_id)
    ).one_or_none()


def _require_request(row, owner):
    if not row:
        raise EngineRunError("request_required")
    if row.opportunity_id != owner.id:
        raise EngineRunError("input_changed")


def _frozen_manifest(session, notice, row):
    company = inputs.load_company()
    if company["slug"] != row.company_bundle_slug:
        raise EngineRunError("input_changed")
    return inputs.freeze(session, notice, company)


def _check_manifest(session, notice, row, preview, supplied_digest, *, now):
    if preview.mode != review_mode() or preview.manifest_sha256 != supplied_digest:
        raise EngineRunError("input_changed")
    if preview.expires_at <= now:
        raise EngineRunError("preview_expired")
    try:
        frozen, manifest = _frozen_manifest(session, notice, row)
    except EngineRunError as error:
        if error.status >= 500:
            raise
        raise EngineRunError("input_changed") from None
    if preview.expires_at <= _now():
        raise EngineRunError("preview_expired")
    manifest["valid_from"] = preview.created_at.isoformat()
    if inputs.digest(manifest) != supplied_digest or inputs.digest(preview.manifest) != supplied_digest:
        raise EngineRunError("input_changed")
    return frozen


def create_preview(session, notice_id, payload, actor):
    _require_mode(review_mode(), preview=True)
    notice, latest, owner = _lock_scope(session, notice_id)
    row = _close_if_ended(session, _open_request(session, notice_id), owner, actor, payload.request_id)
    _eligible(notice, latest, owner, allow_hold=True)
    _require_request(row, owner)
    record, fingerprint = _replay(session, "preview", notice_id, payload.request_id, actor,
                                  review_request_id=str(row.id))
    now = _now()
    if record:
        preview = session.get(EngineReviewPreview, _receipt_id(record))
        _check_manifest(session, notice, row, preview, preview.manifest_sha256, now=now)
    else:
        _, manifest = _frozen_manifest(session, notice, row)
        now = _now()
        preview = None
        for candidate, approval_id in session.execute(
            select(EngineReviewPreview, EngineReviewApproval.id)
            .outerjoin(EngineReviewApproval, EngineReviewApproval.preview_id == EngineReviewPreview.id)
            .where(EngineReviewPreview.review_request_id == row.id)
            .order_by(EngineReviewPreview.created_at.desc(), EngineReviewPreview.id.desc())
        ):
            if {**manifest, "valid_from": candidate.created_at.isoformat()} == candidate.manifest:
                if candidate.expires_at > now:
                    preview = candidate
                    break
                if approval_id:
                    raise EngineRunError("preview_expired")
            if approval_id:
                raise EngineRunError("input_changed")
        if preview is None:
            manifest["valid_from"] = now.isoformat()
            preview = EngineReviewPreview(
                id=uuid4(), review_request_id=row.id, bundle_id=UUID(manifest["bundle_id"]),
                manifest=manifest, manifest_sha256=inputs.digest(manifest), mode=manifest["mode"],
                planned_calls=manifest["planned_calls"], created_by=actor, created_at=now, expires_at=now + TTL,
            )
            session.add(preview)
            _audit(session, "preview_created", actor, preview.id, payload.request_id,
                   notice_id=notice_id, manifest_sha256=preview.manifest_sha256)
        _save_replay(session, "preview", notice_id, payload.request_id, actor, fingerprint, preview.id)
    result = _preview_receipt(preview, session)
    session.commit()
    return result


def approve(session, notice_id, payload, actor):
    _require_mode(review_mode(), preview=True)
    notice, latest, owner = _lock_scope(session, notice_id)
    row = _close_if_ended(session, _open_request(session, notice_id), owner, actor, payload.request_id)
    record, fingerprint = _replay(
        session, "approve", notice_id, payload.request_id, actor,
        preview_id=str(payload.preview_id), manifest_sha256=payload.manifest_sha256,
    )
    if record:
        result = _approval_receipt(session, session.get(EngineReviewApproval, _receipt_id(record)))
        session.commit()
        return result
    _eligible(notice, latest, owner)
    _require_request(row, owner)
    scope = _preview_scope(session, notice_id, payload.preview_id)
    if not scope or scope[1].id != row.id:
        raise EngineRunError("input_changed")
    preview = scope[0]
    approval = session.scalar(select(EngineReviewApproval).where(
        EngineReviewApproval.preview_id == preview.id,
    ))
    if approval:
        if preview.manifest_sha256 != payload.manifest_sha256:
            raise EngineRunError("input_changed")
    else:
        now = _now()
        frozen = _check_manifest(session, notice, row, preview, payload.manifest_sha256, now=now)
        if preview.mode == "live":
            _require_live_budget(session, notice_id, preview.planned_calls)
        # Receipt and WorkJob are flushed and committed together. A separate
        # engine request UUID keeps the existing company API's keyspace intact.
        run = engine_runs.create_wiki_run(session, frozen, request_id=uuid4(), actor=actor)
        session.flush()
        approval = EngineReviewApproval(
            id=uuid4(), preview_id=preview.id, engine_run_id=run.id,
            approved_by=actor, approved_at=_now(), request_id=payload.request_id,
        )
        session.add(approval)
        _audit(session, "approved", actor, approval.id, payload.request_id,
               notice_id=notice_id, preview_id=str(preview.id), run_id=str(run.id),
               manifest_sha256=preview.manifest_sha256)
    _save_replay(session, "approve", notice_id, payload.request_id, actor, fingerprint, approval.id, 202)
    result = _approval_receipt(session, approval)
    session.commit()
    return result


def dismiss(session, notice_id, payload, actor):
    _require_mode(review_mode(), preview=True)
    notice, latest, owner = _lock_scope(session, notice_id)
    record, fingerprint = _replay(session, "dismiss", notice_id, payload.request_id, actor,
                                  preview_id=str(payload.preview_id))
    scope = _preview_scope(session, notice_id, payload.preview_id)
    if not scope:
        raise EngineRunError("input_changed")
    preview, row = scope
    if record:
        result = wire.DismissalReceipt(dismissal_id=_receipt_id(record), request=_request_receipt(row))
    else:
        existing = session.scalar(select(AuditEvent.id).where(
            AuditEvent.action == "engine_review.dismissed", AuditEvent.aggregate_id == str(row.id),
            AuditEvent.safe_metadata["preview_id"].as_string() == str(preview.id),
        )) if row.closed_reason == "dismissed" else None
        if existing:
            _save_replay(session, "dismiss", notice_id, payload.request_id, actor, fingerprint, existing)
            result = wire.DismissalReceipt(dismissal_id=existing, request=_request_receipt(row))
            session.commit()
            return result
        _eligible(notice, latest, owner, allow_hold=True)
        if (row.closed_at is not None or row.opportunity_id != owner.id
                or _tracking_ended_after_request(session, row)
                or session.scalar(select(EngineReviewApproval.id).where(EngineReviewApproval.preview_id == preview.id))):
            raise EngineRunError("input_changed")
        _check_manifest(session, notice, row, preview, preview.manifest_sha256, now=_now())
        _close(session, row, "dismissed", actor, payload.request_id)
        dismissal_id = _audit(session, "dismissed", actor, row.id, payload.request_id,
                              notice_id=notice_id, preview_id=str(preview.id))
        _save_replay(session, "dismiss", notice_id, payload.request_id, actor, fingerprint, dismissal_id)
        result = wire.DismissalReceipt(dismissal_id=dismissal_id, request=_request_receipt(row))
    session.commit()
    return result


def acknowledge(session, notice_id, payload, actor):
    _require_mode(review_mode())
    notice, latest, owner = _lock_scope(session, notice_id)
    record, fingerprint = _replay(session, "acknowledge", notice_id, payload.request_id, actor,
                                  result_id=str(payload.result_id))
    if record:
        result = _ack_receipt(session.get(EngineReviewAcknowledgment, _receipt_id(record)))
        session.commit()
        return result
    _eligible(notice, latest, owner, allow_hold=True)
    row = _open_request(session, notice_id)
    _require_request(row, owner)
    if _tracking_ended_after_request(session, row):
        raise EngineRunError("input_changed")
    run, request_id = _latest_runs(session, [notice_id]).get(notice_id, (None, None))
    if not run or run.id != payload.result_id or request_id != row.id or not _publishable(
        run, engine_runs.currentness_many(session, [run])[run.id],
    ):
        raise EngineRunError("input_changed")
    receipt = session.scalar(select(EngineReviewAcknowledgment).where(
        EngineReviewAcknowledgment.engine_run_id == run.id,
    ))
    if receipt is None:
        receipt = EngineReviewAcknowledgment(
            id=uuid4(), engine_run_id=run.id, acknowledged_by=actor, acknowledged_at=_now(),
            request_id=payload.request_id,
        )
        session.add(receipt)
        _audit(session, "acknowledged", actor, receipt.id, payload.request_id,
               notice_id=notice_id, run_id=str(run.id))
    _save_replay(session, "acknowledge", notice_id, payload.request_id, actor, fingerprint, receipt.id)
    result = _ack_receipt(receipt)
    session.commit()
    return result


def workload_counts(session):
    from ...lifecycle import WorkloadCount

    keys = ("engine_approval_pending", "engine_result_pending")
    error = _mode_error(review_mode())
    if error:
        return dict.fromkeys(keys, WorkloadCount(None, error))
    ids = session.scalars(select(EngineReviewRequest.notice_id).where(
        EngineReviewRequest.closed_at.is_(None),
    )).all()
    states = review_states(session, ids).values()
    return {
        keys[0]: WorkloadCount(sum(state.next_action == "approve" for state in states)),
        keys[1]: WorkloadCount(sum(state.next_action == "review_result" for state in states)),
    }
