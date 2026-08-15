"""RADD-1093 — the monitoring roster comes from the code, not from table rows.

A consumer_offsets row whose name no registered consumer claims must read as
retired residue, never as a stalled worker — the attachments.gc ghost sat in
"Stalled" for 12 days after RADD-745 renamed it away.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.kernel import load_plugins
from radd.kernel.registry import registries
from radd.modules.events import service as events_service
from radd.modules.events.models import ConsumerOffset


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def test_every_live_consumer_name_is_registered():
    """The declaration ratchet: a module that adds an offset-tracked consumer
    must declare it in its manifest, or monitoring will call it retired."""
    load_plugins(settings.modules)
    expected = {
        "ai.embedder", "automations.engine", "csat.sender", "events.cascade",
        "googlechat.notifier", "mailintake.outbound", "notify.consumer",
        "search.indexer", "webhooks.dispatcher",
    }
    assert expected <= registries.consumer_names


async def test_unclaimed_offset_row_reads_as_unregistered(db):
    load_plugins(settings.modules)
    db.add(ConsumerOffset(name="renamed.away", last_event_id=1))
    await db.flush()
    rows = {row["name"]: row for row in await events_service.consumer_status(db)}
    assert rows["renamed.away"]["registered"] is False
    # live consumers with rows keep their claim
    for name, row in rows.items():
        if name in registries.consumer_names:
            assert row["registered"] is True
