"""Audited company-fit card mode switch (PS-01 C4·C8, ADR-0080).

The latest `prespec_company_fit_mode` row is the requested mode; `BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE`
is the deployment cap. `company_fit.card_mode_with_card` evaluates both. Rows are recorded only
through `set_mode` (REST `POST /api/pre-specs/company-fit/mode` and the
`set-company-fit-mode` CLI), each with one audit event.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.models import AuditEvent
from ..models import PreSpecCompanyFitMode

MODES = ("off", "suggest")
PREREQUISITE_REASONS = frozenset({
    "company_fit_disabled", "company_fit_reference_only", "company_fit_model_unavailable",
    "card_unavailable", "card_sha256_mismatch",
})


class CompanyFitModeError(ValueError):
    def __init__(self, code: str, status: int = 409, details: dict | None = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.details = details


def latest_row(session: Session | None) -> PreSpecCompanyFitMode | None:
    if session is None:
        return None
    return session.scalars(
        select(PreSpecCompanyFitMode)
        .order_by(PreSpecCompanyFitMode.set_at.desc(), PreSpecCompanyFitMode.id.desc())
        .limit(1)
    ).first()


def _reason(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise CompanyFitModeError("reason_invalid", 422)
    return value


def set_mode(session: Session, *, mode: str, reason: str | None, request_id: UUID, actor: str,
             settings=None, now: datetime | None = None) -> tuple[dict, bool]:
    """Record a mode row (C8). Returns (C4 state after the call, created)."""
    from .company_fit import PROMPT_VERSION_CARD, card_mode_with_card  # noqa: PLC0415

    settings = settings or get_settings()
    if mode == "auto_request":
        raise CompanyFitModeError("mode_not_available", 422)
    if mode not in MODES:
        raise CompanyFitModeError("mode_invalid", 422)
    reason = _reason(reason)
    previous = session.scalar(select(PreSpecCompanyFitMode).where(PreSpecCompanyFitMode.request_id == request_id))
    if previous is not None:
        if (previous.mode, previous.set_by, previous.reason) != (mode, actor, reason):
            raise CompanyFitModeError("request_id_conflict")
        return card_mode_with_card(settings, session)[0], False
    state, card = card_mode_with_card(settings, session)
    if mode == "suggest":
        if state["reason_code"] in PREREQUISITE_REASONS or card is None:
            raise CompanyFitModeError("prerequisites_unmet", 409, {"reason_code": state["reason_code"] or "card_unavailable"})
        if getattr(settings, "prespec_company_fit_card_mode", "off") != "suggest":
            raise CompanyFitModeError("prerequisites_unmet", 409, {"reason_code": "switch_capped_off"})
    row = PreSpecCompanyFitMode(
        id=uuid4(), mode=mode, prompt_version=PROMPT_VERSION_CARD,
        card_version=card.card_version if card else None, card_sha256=card.card_sha256 if card else None,
        reason=reason, set_by=actor, set_at=now or datetime.now(UTC), request_id=request_id,
    )
    session.add(row)
    session.add(AuditEvent(
        actor_kind="human", claimed_name=actor, action="prespec_company_fit.mode",
        aggregate_type="prespec_company_fit_mode", aggregate_id=str(row.id),
        safe_metadata={"mode": mode, "prompt_version": row.prompt_version, "card_sha256": row.card_sha256,
                       "reason": reason, "request_id": str(request_id)},
        request_id=str(request_id),
    ))
    session.flush()
    state = card_mode_with_card(settings, session)[0]
    session.commit()
    return state, True
