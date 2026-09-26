"""RADD-872: kernel TaskSpecs actually run.

`registries.tasks` was write-only from spec 93 until this wave — the access
module registered its RADD-820 expiry sweep and nothing ever scheduled it, so
expired grant rows accumulated forever. Two pins: (1) every registered periodic
TaskSpec is scheduled on the task backend — since RADD-1341 by
`PluginRuntime.start_plugin`, pinned in test_plugin_runtime.py
(`test_every_periodic_taskspec_is_scheduled_with_a_gate`); (2) the sweep itself
deletes expired rows when it finally runs.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.access.models import AccessGrant
from radd.modules.access.service import sweep_expired_grants


async def test_expiry_sweep_deletes_expired_rows():
    # Committed on purpose — the sweep opens its own session, so the usual
    # rollback fixture cannot contain this; the row is deleted by the assertion.
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    grant_id = uuid.uuid4()
    async with maker() as session:
        session.add(
            AccessGrant(
                id=grant_id,
                resource_type="field",
                resource_id=f"sweep-probe-{grant_id.hex[:8]}",
                subject_type="user",
                subject_id=uuid.uuid4(),
                access="read",
                expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
            )
        )
        await session.commit()
    removed = await sweep_expired_grants()
    assert removed >= 1
    async with maker() as session:
        survivor = (
            await session.execute(select(AccessGrant).where(AccessGrant.id == grant_id))
        ).scalar_one_or_none()
    assert survivor is None
    await engine.dispose()
