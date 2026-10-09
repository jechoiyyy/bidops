"""Company identity registration and read-only lookup for the demo namespace."""

from __future__ import annotations

from dataclasses import dataclass
import re
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.models import AuditEvent
from ..models import Company


_SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


@dataclass(frozen=True)
class CompanyRegistration:
    company_id: UUID
    created: bool


def _identity_error(message: str, *, status_code: int = 409) -> BundleServiceError:
    return BundleServiceError("company_identity_conflict", message, status_code=status_code)


def _registration_values(
    *, slug: str, name: str, is_fictional: bool, actor: str
) -> tuple[str, str, str]:
    if not isinstance(slug, str) or _SLUG_PATTERN.fullmatch(slug) is None:
        raise BundleServiceError("invalid_request", "회사 slug가 올바르지 않습니다", status_code=422)
    clean_name = name.strip() if isinstance(name, str) else ""
    if not clean_name or len(clean_name) > 128:
        raise BundleServiceError("invalid_request", "회사 이름이 올바르지 않습니다", status_code=422)
    if is_fictional is not True:
        raise BundleServiceError("invalid_request", "가상 회사만 등록할 수 있습니다", status_code=422)
    return slug, clean_name, validate_actor(actor)


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
    """

    slug, name, actor = _registration_values(
        slug=slug, name=name, is_fictional=is_fictional, actor=actor
    )
    _ensure_sqlite_outer_transaction(session)
    existing = session.scalar(select(Company).where(Company.slug == slug).limit(1))
    if existing is not None:
        return _same_identity(existing, name=name, is_fictional=is_fictional)

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
            safe_metadata={"slug": company.slug, "is_fictional": True},
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
