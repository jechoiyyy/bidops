"""Transaction fence shared by v4 activation, dispatch and publication."""

from sqlalchemy import text
from sqlalchemy.orm import Session


# Stable two-int PostgreSQL advisory-lock namespace ("BOPS", overview slot 4).
# Never hold this lock while waiting for HTTP. SQLite tests serialize their own
# calls; actual competing transactions are tested against PostgreSQL.
V4_GATE_NAMESPACE = 0x424F5053
V4_GATE_SLOT = 4


def lock_v4_gate(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        with session.no_autoflush:
            session.execute(
                text("SELECT pg_advisory_xact_lock(:namespace, :slot)"),
                {"namespace": V4_GATE_NAMESPACE, "slot": V4_GATE_SLOT},
            )
