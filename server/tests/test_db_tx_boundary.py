"""RADD-845 — streaming responses must not hold the request transaction open.

`get_session` commits in dependency teardown, which for a flush-through
response (SSE, file delivery) runs only when the BODY finishes — hours later
for a held-open MCP stream. Two PAT-auth sessions idle in transaction for 4-5h
once blocked a production migration's DROP TABLE behind their ACCESS SHARE
locks. These tests pin the two halves of the fix: handlers end the transaction
before the stream starts, and the engine carries a server-side
idle-in-transaction timeout so any future leak self-heals instead of wedging
a deploy.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _admin(db) -> User:
    user = User(
        email=f"tx-{uuid.uuid4().hex[:8]}@example.com",
        name="Tx Boundary",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.commit()
    return user


async def test_mcp_stream_commits_the_auth_transaction_before_streaming(db):
    """The incident's exact shape: PAT auth SELECT opens a transaction, the
    SSE stream holds the session checked out, the transaction idles for the
    stream's life. After the handler returns — headers ready, body not yet
    consumed — the request session must have NO open transaction."""
    from radd.modules.mcp.router import mcp_stream

    admin = await _admin(db)
    # Simulate the auth dependency's read on the request session: any SELECT
    # autobegins the transaction a real PAT lookup would.
    await db.execute(text("SELECT 1"))
    assert db.in_transaction(), "precondition: the auth read opened a transaction"

    response = await mcp_stream(admin, db)
    assert response.media_type == "text/event-stream"
    assert not db.in_transaction(), (
        "the handler returned a stream while the request transaction was still "
        "open — it will idle for the connection's whole life (RADD-845)"
    )
    await response.body_iterator.aclose()


async def test_engine_carries_the_idle_in_transaction_backstop():
    """The belt: the app engine's connections carry a server-side
    idle_in_transaction_session_timeout, so a leak this codebase hasn't
    written yet costs one killed connection instead of a wedged deploy. SHOW
    proves the option survived the psycopg connect string end to end."""
    from radd.db import engine

    assert settings.db_idle_tx_timeout_seconds, "default must be on"
    async with engine.connect() as conn:
        shown = (
            await conn.execute(text("SHOW idle_in_transaction_session_timeout"))
        ).scalar_one()
    # Postgres renders 600000ms as '10min'; parse rather than string-match.
    unit = {"ms": 0.001, "s": 1, "min": 60, "h": 3600}
    for suffix, factor in unit.items():
        if shown.endswith(suffix):
            seconds = float(shown.removesuffix(suffix)) * factor
            break
    else:
        seconds = float(shown) / 1000  # bare integer = ms
    assert seconds == settings.db_idle_tx_timeout_seconds
