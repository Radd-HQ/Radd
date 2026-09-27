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


#: The LIKE escape character every pattern this codebase builds relies on —
#: Postgres's default, so a bare `.ilike(pattern)` reads it without `escape=`.
LIKE_ESCAPE = "\\"


def escape_like(text: str) -> str:
    """User text as a LIKE literal: `%`, `_` and the escape itself escaped
    (RADD-883, RADD-1452). The one escape helper — the SLQ dialects re-export it
    from `items.slq`, the kernel's entity search and every directory read it here —
    so `a_b` matches `a_b` and never `aXb`."""
    return text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")


def ilike_term(q: str) -> str:
    """A user-supplied search term as a contains-ILIKE pattern, wildcards
    escaped — searching for "100%" must not match everything."""
    return f"%{escape_like(q.strip())}%"


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
    """End the request transaction NOW, before returning a flush-through response (SSE, file
    delivery): `get_session` commits only after the body finishes, so a long stream would
    idle in transaction holding the auth read's locks (RADD-845)."""
    await session.commit()
