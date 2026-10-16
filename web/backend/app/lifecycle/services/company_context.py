"""Company identity registration and read-only lookup.

RL-00 (ADR-0073): exactly one real company (``is_fictional=false``) may exist
DB-wide; fictional demo companies stay allowed beside it.  Whether a fictional
registration is permitted (``BIDOPS_DEMO_ENABLED``) is decided by the caller
that reads settings (deep_review ``prepare_company_knowledge``), not here.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.company_ontology import (
    CompanyIdentityValidationError,
    normalize_company_identity,
)
from ...core.models import AuditEvent
from ..models import Company


@dataclass(frozen=True)
class CompanyRegistration:
    company_id: UUID
    created: bool


def _identity_error(message: str, *, status_code: int = 409) -> BundleServiceError:
    return BundleServiceError("company_identity_conflict", message, status_code=status_code)


def _registration_values(
    *, slug: str, name: str, is_fictional: bool, actor: str
) -> tuple[str, str, str]:
    try:
        identity = normalize_company_identity(
            slug=slug,
            name=name,
            is_fictional=is_fictional,
        )
    except CompanyIdentityValidationError as exc:
        messages = {
            "company_slug_invalid": "회사 slug가 올바르지 않습니다",
            "company_name_invalid": "회사 이름이 올바르지 않습니다",
            "company_is_fictional_invalid": "가상회사 표식은 true 또는 false여야 합니다",
        }
        raise BundleServiceError(
            "invalid_request",
            messages[exc.code],
            status_code=422,
        ) from None
    return identity.slug, identity.name, validate_actor(actor)


def _same_identity(company: Company, *, name: str, is_fictional: bool) -> CompanyRegistration:
    if company.name != name or company.is_fictional is not is_fictional:
        raise _identity_error("같은 slug에 다른 회사 identity를 등록할 수 없습니다")
    return CompanyRegistration(company_id=company.id, created=False)


def _ensure_sqlite_outer_transaction(session: Session) -> None:
    """Start SQLite's physical transaction before opening a savepoint.

    Python's SQLite driver does not begin a database transaction for a SELECT.
    If SAVEPOINT is the first transactional statement, releasing it persists the
    write and a later caller rollback cannot undo it.  PostgreSQL begins the
    outer transaction normally and does not need this compatibility boundary.
    """

    if session.get_bind().dialect.name != "sqlite":
        return
    connection = session.connection()
    proxied = connection.connection
    driver_connection = getattr(proxied, "driver_connection", proxied)
    if not driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")


_REAL_COMPANY_LOCK = "company-real-registration"


def _real_company_lock(session: Session) -> None:
    """Serialize real-company registration for the rest of the transaction.

    There is no partial unique index (RL-00 adds no migration), so two
    transactions registering *different* real slugs are ordered by a
    transaction-scoped advisory lock; the later one then sees the winner.
    SQLite tests are single-writer and need no lock.
    """

    if session.get_bind().dialect.name != "postgresql":
        return
    raw = int.from_bytes(hashlib.sha256(_REAL_COMPANY_LOCK.encode("utf-8")).digest()[:8], "big")
    key = raw - (1 << 64) if raw >= (1 << 63) else raw
    session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": key})


def _other_real_company_exists(session: Session, slug: str) -> bool:
    return (
        session.scalar(
            select(Company.id)
            .where(Company.is_fictional.is_(False), Company.slug != slug)
            .limit(1)
        )
        is not None
    )


def register_company(
    session: Session,
    *,
    slug: str,
    name: str,
    is_fictional: bool,
    actor: str,
) -> CompanyRegistration:
    """Register an immutable company identity without owning the transaction.

    The caller commits or rolls back the surrounding transaction. A savepoint
    confines a concurrent unique-slug collision so the winner can be read and
    checked without rolling back unrelated caller work.

    A real company (``is_fictional=False``) is rejected with
    ``real_company_exists`` when another real company with a different slug is
    already registered. The same real slug stays idempotent.
    """

    slug, name, actor = _registration_values(
        slug=slug, name=name, is_fictional=is_fictional, actor=actor
    )
    _ensure_sqlite_outer_transaction(session)
    if not is_fictional:
        _real_company_lock(session)
    existing = session.scalar(select(Company).where(Company.slug == slug).limit(1))
    if existing is not None:
        return _same_identity(existing, name=name, is_fictional=is_fictional)
    if not is_fictional and _other_real_company_exists(session, slug):
        raise BundleServiceError(
            "real_company_exists", "실회사는 하나만 등록할 수 있습니다", status_code=409
        )

    company = Company(id=uuid4(), slug=slug, name=name, is_fictional=is_fictional)
    try:
        with session.begin_nested():
            session.add(company)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(Company)
            .where(Company.slug == slug)
            .execution_options(populate_existing=True)
            .limit(1)
        )
        if existing is None:
            raise BundleServiceError(
                "processing_failed", "회사 identity를 등록할 수 없습니다", status_code=500
            ) from None
        return _same_identity(existing, name=name, is_fictional=is_fictional)

    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=actor,
            action="company.register",
            aggregate_type="company",
            aggregate_id=str(company.id),
            safe_metadata={"slug": company.slug, "is_fictional": is_fictional},
        )
    )
    session.flush()
    return CompanyRegistration(company_id=company.id, created=True)


def list_companies(
    session: Session, *, limit: int, offset: int
) -> tuple[list[Company], int]:
    total = int(session.scalar(select(func.count()).select_from(Company)) or 0)
    rows = list(
        session.scalars(
            select(Company).order_by(Company.slug.asc()).limit(limit).offset(offset)
        ).all()
    )
    return rows, total


def get_company(session: Session, company_id: UUID) -> Company | None:
    return session.get(Company, company_id)


__all__ = [
    "CompanyRegistration",
    "get_company",
    "list_companies",
    "register_company",
]
