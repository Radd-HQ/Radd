"""RADD-1314: a key the automation engine mints marks its requests automation-caused.

A script run writes back over REST with an ephemeral key. Until this, that
request's events looked human (`automated=False`), and after RADD-1308 removed
the system-actor arm of the loop guard, a script that updated its own item
re-triggered its own automation. Each check runs in its own task so the
request-scoped mark cannot leak into the next.
"""

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from radd.config import settings
from radd.modules.auth import service_tokens
from radd.modules.auth.deps import optional_user
from radd.modules.auth.models import User
from radd.modules.automations.planning import is_automation_caused
from radd.modules.events import service as events


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _request(raw: str, method: str = "PATCH") -> Request:
    return Request({
        "type": "http", "method": method, "path": f"{settings.api_prefix}/items/x",
        "headers": [(b"authorization", f"Bearer {raw}".encode())], "query_string": b"",
    })


async def _automated_after_auth(db, raw: str) -> tuple[bool, bool]:
    """(was the request marked, is an event it emits automation-caused)."""

    async def one_request() -> tuple[bool, bool]:
        user = await optional_user(_request(raw), db)
        assert user is not None
        await events.emit(
            db, event_type=events_type(), entity_type=entity_type(), entity_id=uuid.uuid4(),
            actor_id=user.id, payload={}, changes=[],
        )
        await db.flush()
        from sqlalchemy import select

        from radd.modules.events.models import Event

        row = (await db.execute(select(Event).order_by(Event.id.desc()).limit(1))).scalar_one()
        return events.is_automated(), is_automation_caused(row)

    return await asyncio.create_task(one_request())


def events_type():
    from radd.modules.items.enums import ItemEvent

    return ItemEvent.UPDATED


def entity_type():
    from radd.modules.items.enums import ItemEntity

    return ItemEntity.ITEM


async def test_an_engine_minted_key_marks_its_requests_automated(db):
    user = User(email=f"key-{uuid.uuid4().hex[:8]}@example.com", name="Key", instance_role="admin")
    db.add(user)
    await db.flush()
    _, script_raw = await service_tokens.mint_ephemeral_token(
        db, user, name="script run", ttl_seconds=60, automation_cause={"source": "script"}
    )
    _, person_raw = await service_tokens.mint_ephemeral_token(db, user, name="plain", ttl_seconds=60)

    assert await _automated_after_auth(db, script_raw) == (True, True)
    # A person's key — the same account — is not automation-caused.
    assert await _automated_after_auth(db, person_raw) == (False, False)
    # And the mark died with the request that set it.
    assert events.is_automated() is False
