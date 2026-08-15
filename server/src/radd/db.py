from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import MetaData, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from radd.config import settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    # eager_defaults: fetch server-generated values via RETURNING at flush time —
    # without it, reading updated_at after an UPDATE lazy-loads and breaks async sessions.
    __mapper_args__ = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def ilike_term(q: str) -> str:
    """A user-supplied search term as a contains-ILIKE pattern, wildcards
    escaped (RADD-883) — searching for "100%" must not match everything."""
    escaped = q.strip().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _connect_args() -> dict[str, str]:
    """Engine-level idle-in-transaction backstop (RADD-845). Server-side, so it
    catches every leak shape — including ones this codebase hasn't written yet."""
    if not settings.db_idle_tx_timeout_seconds:
        return {}
    ms = settings.db_idle_tx_timeout_seconds * 1000
    return {"options": f"-c idle_in_transaction_session_timeout={ms}"}


engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=settings.db_pool_pre_ping,
    connect_args=_connect_args(),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Request-scoped session: commits on success, rolls back on error."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def commit_before_streaming(session: AsyncSession) -> None:
    """End the request transaction NOW — the last session touch before
    returning a flush-through response (SSE, file delivery).

    `get_session` commits in dependency TEARDOWN, which runs only after the
    response body finishes. Buffered responses never notice; a flush-through
    response (see `CommitBeforeSendMiddleware`) holds the session checked out
    — idle in transaction, still holding the auth read's ACCESS SHARE locks —
    for the connection's whole life. Two PAT streams idling 4-5h blocked a
    production migration behind exactly that (RADD-845). A stream body that
    touches the DB afterwards autobegins its own short transaction; the
    engine's idle_in_transaction_session_timeout is the backstop for those.
    """
    await session.commit()
