"""One company-fit slot in the composed analysis worker; no standalone process."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.model_client import ModelClient
from ...core.models import AuditEvent
from ...core.object_store import EncryptedModelResponseStore
from ...lifecycle import lock_notice
from ...lifecycle.models import Notice
from ..models import DeepReview, DocumentBundle, PreSpecCompanyFitAttempt
from .auto_preparation import _auto_start_scope, maybe_auto_start_deep_review
from .company_fit import (CONTRACT, configured_binding, current_flags, digest, fit_policy,
                          frozen_input, overview_inputs, validate_result)
from .effective_grade import priority_notice_ids
from .input_versions import resolve_active_versions
from .model_response_storage import store_raw_model_response


def _now():
    return datetime.now(UTC)


def _audit(session: Session, row: PreSpecCompanyFitAttempt):
    session.add(AuditEvent(actor_kind="system", claimed_name="company-fit", action="prespec_company_fit.attempt",
        aggregate_type="prespec_company_fit_attempt", aggregate_id=str(row.id),
        safe_metadata={"notice_id": row.notice_id, "status": row.status, "reason_code": row.error_code,
                       "input_sha256": row.input_sha256, "quality_status": row.quality_status}))


class PreSpecCompanyFitRunner:
    def __init__(self, *, settings=None, client=None, raw_response_store=None, clock=_now):
        self.settings = settings or get_settings()
        self.client = client
        self.store = raw_response_store
        self.clock = clock

    def _enqueue_one(self, session: Session) -> None:
        # Resolve local approvals before queue construction or any model request.
        configured_binding(self.settings)
        profile, policy = resolve_active_versions(session, allow_unmeasured_reference=self.settings.reference_workflow_mode)
        ids = list(session.scalars(select(Notice.id).join(DocumentBundle, DocumentBundle.notice_id == Notice.id)
            .where(Notice.source_type == "pre_spec", DocumentBundle.status == "ready",
                   DocumentBundle.confirmed_by_name == "auto-preparation")
            .distinct().order_by(Notice.id)))
        priority = priority_notice_ids(session, ids)
        sources = overview_inputs(session, [i for i in ids if i in priority])
        existing_inputs = set(session.scalars(select(PreSpecCompanyFitAttempt.input_sha256)))
        existing_deep = set(session.scalars(select(DeepReview.bundle_id).where(
            DeepReview.profile_version_id == profile.id, DeepReview.policy_version_id == policy.id)))
        for notice_id in ids:
            source = sources.get(notice_id)
            if source is None:
                continue
            bundle_id, reason = _auto_start_scope(session, notice_id, require_company_fit=False)
            if reason is not None or bundle_id in existing_deep:
                continue
            try:
                inputs = frozen_input(session, notice_id, source, settings=self.settings)
            except (ValueError, TypeError):
                # A malformed/oversized candidate must not starve later notices.
                continue
            input_hash = digest(inputs)
            if input_hash in existing_inputs:
                continue
            lock_notice(session, notice_id)
            if session.scalar(select(PreSpecCompanyFitAttempt.id).where(PreSpecCompanyFitAttempt.input_sha256 == input_hash)):
                continue
            row = PreSpecCompanyFitAttempt(id=uuid4(), notice_id=notice_id, document_version_id=source.document_id,
                page_overview_id=source.id if source.kind == "page" else None,
                overview_result_id=source.id if source.kind == "extractive" else None,
                profile_version_id=profile.id, deep_policy_version_id=policy.id,
                input_jsonb=inputs, input_sha256=input_hash, policy_digest=inputs["policy_digest"],
                model_name=inputs["model_name"], model_revision=inputs["model_revision"],
                quality_status=source.quality_status, status="queued", created_at=self.clock())
            session.add(row)
            _audit(session, row)
            session.commit()
            return
        session.commit()

    def run_once(self, session: Session, worker_id: str) -> bool:
        if not self.settings.prespec_company_fit_enabled:
            return False
        # No measured company-fit policy exists yet. Reference workflow is an explicit opt-in.
        if not self.settings.reference_workflow_mode:
            return False
        now = self.clock()
        for row in session.scalars(select(PreSpecCompanyFitAttempt).where(
            PreSpecCompanyFitAttempt.status == "running", PreSpecCompanyFitAttempt.lease_expires_at <= now
        ).with_for_update(skip_locked=True)):
            self._finish(session, row, "failed", "lease_expired")
        session.commit()
        try:
            self._enqueue_one(session)
        except Exception:
            session.rollback()
            return False
        row = session.scalar(select(PreSpecCompanyFitAttempt).where(PreSpecCompanyFitAttempt.status == "queued")
                             .order_by(PreSpecCompanyFitAttempt.created_at, PreSpecCompanyFitAttempt.id)
                             .with_for_update(skip_locked=True).limit(1))
        if row is None:
            session.rollback()
            return False
        attempt_id, notice_id = row.id, row.notice_id
        if not self._eligible(session, row):
            self._finish(session, row, "failed", "inputs_changed")
            session.commit()
            return True
        row.status = "running"
        row.lease_owner = worker_id
        row.lease_expires_at = now + timedelta(seconds=600)
        inputs = row.input_jsonb
        _audit(session, row)
        session.commit()
        result, raw, metrics = None, None, {}
        status, error = "completed", None
        try:
            if not any(f["status"] == "confirmed" and f["value"] is not None for f in inputs["company_facts"]):
                result = validate_result({"schema_version": "bidops.prespec-company-fit-result.v1", "decision": "unknown",
                    "summary": "업무 범위를 확인할 승인된 회사 정보가 부족합니다.",
                    "reasons": [{"kind": "information_gap", "explanation": "확인된 회사 정보가 없어 과업과의 부합 여부를 판단할 수 없습니다.",
                                 "notice_refs": [inputs["notice_facts"][0]["ref"]], "company_refs": []}],
                    "verification_items": ["승인된 회사 업무 범위와 수행 역량을 확인해 주세요."]}, inputs)
            else:
                if self.client is None:
                    self.client = ModelClient.for_purpose("overview", model=inputs["model_name"],
                                                         settings=self.settings, output_contract=CONTRACT)
                identity = self.client.verify_identity()
                if identity.model != inputs["model_name"] or identity.revision != inputs["model_revision"]:
                    raise ValueError("model_binding_changed")
                model_inputs = {key: value for key, value in inputs.items() if key != "fit_policy"}
                response = self.client.invoke("company_fit", model_inputs, inputs["fit_policy"])
                raw = bytes(response.raw_response)
                metrics = {"prompt_tokens": response.prompt_tokens, "output_tokens": response.output_tokens, "latency_ms": response.latency_ms}
                try:
                    if json.loads(raw) != response.structured_output:
                        raise ValueError("raw_response_mismatch")
                    result = validate_result(response.structured_output, inputs)
                except (ValueError, TypeError):
                    status, error = "needs_human_review", "company_fit_validation_failed"
        except Exception:
            status, error = "failed", "company_fit_execution_failed"
        session.expire_all()
        row = session.scalar(select(PreSpecCompanyFitAttempt).where(PreSpecCompanyFitAttempt.id == attempt_id).with_for_update())
        if row.status != "running" or row.lease_owner != worker_id or row.lease_expires_at <= self.clock():
            session.rollback()
            return True
        try:
            if raw is not None:
                if self.store is None:
                    self.store = EncryptedModelResponseStore(self.settings)
                row.raw_response_sha256 = store_raw_model_response(session, raw, store=self.store, clock=self.clock)
            for key, value in metrics.items():
                setattr(row, key, value)
            if status == "completed" and result is not None:
                row.result_jsonb = result.model_dump(mode="json")
                row.result_sha256 = digest(row.result_jsonb)
            self._finish(session, row, status, error)
            session.commit()
        except Exception:
            session.rollback()
            row = session.scalar(select(PreSpecCompanyFitAttempt).where(PreSpecCompanyFitAttempt.id == attempt_id).with_for_update())
            if row.status == "running" and row.lease_owner == worker_id:
                row.result_jsonb = None
                row.result_sha256 = None
                self._finish(session, row, "failed", "company_fit_storage_failed")
                session.commit()
            return True
        # The shared creation service rechecks current input, policy and bundle.
        maybe_auto_start_deep_review(session, notice_id)
        return True

    def _eligible(self, session: Session, row: PreSpecCompanyFitAttempt) -> bool:
        if not current_flags(session, [row], settings=self.settings).get(row.id):
            return False
        if row.notice_id not in priority_notice_ids(session, [row.notice_id]):
            return False
        _, reason = _auto_start_scope(session, row.notice_id, require_company_fit=False)
        return reason is None

    def _finish(self, session: Session, row: PreSpecCompanyFitAttempt, status: str, error: str | None):
        row.status, row.error_code = status, error
        row.completed_at = self.clock()
        row.lease_owner, row.lease_expires_at = None, None
        _audit(session, row)
