"""A request's statements are bounded; background work is not (RADD-1532)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from radd import db as radd_db
from radd.config import settings
from radd.db import SessionLocal, bound_statements, is_statement_timeout


async def test_a_statement_past_the_limit_is_cancelled_and_recognised(monkeypatch):
    monkeypatch.setattr(settings, "db_statement_timeout_seconds", 1)
    async with SessionLocal() as session:
        await bound_statements(session)
        with pytest.raises(DBAPIError) as stopped:
            await session.execute(text("SELECT pg_sleep(3)"))
        assert is_statement_timeout(stopped.value)
        await session.rollback()


async def test_the_limit_ends_with_the_transaction_and_never_follows_the_connection(monkeypatch):
    """SET LOCAL: a pooled connection handed to a background job next must not
    inherit a request's cap."""
    monkeypatch.setattr(settings, "db_statement_timeout_seconds", 1)
    async with SessionLocal() as session:
        await bound_statements(session)
        assert (await session.execute(text("SHOW statement_timeout"))).scalar_one() == "1s"
        await session.commit()
        assert (await session.execute(text("SHOW statement_timeout"))).scalar_one() == "0"


async def test_zero_disables_it(monkeypatch):
    monkeypatch.setattr(settings, "db_statement_timeout_seconds", 0)
    async with SessionLocal() as session:
        await bound_statements(session)
        assert (await session.execute(text("SHOW statement_timeout"))).scalar_one() == "0"


async def test_a_request_session_is_bound_and_an_ordinary_error_is_not_mistaken_for_a_timeout(monkeypatch):
    monkeypatch.setattr(settings, "db_statement_timeout_seconds", 7)
    sessions = radd_db.get_session()
    session = await anext(sessions)
    try:
        assert (await session.execute(text("SHOW statement_timeout"))).scalar_one() == "7s"
        with pytest.raises(DBAPIError) as other:
            await session.execute(text("SELECT 1 / 0"))
        assert not is_statement_timeout(other.value)
    finally:
        await sessions.aclose()
