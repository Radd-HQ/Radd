"""Scalar settings cascade (specs 50/67): project → instance → env default.

DB-backed (compose Postgres, like the SLQ smoke test). Writes are flushed, never
committed — the session rolls back at teardown, so rows never persist.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError
from radd.modules.settings import service
from radd.modules.settings.types import SETTINGS_REGISTRY, SettingKey, SettingScope

KEY = SettingKey.WORK_WEEK_DAYS


@pytest.fixture
async def db_session():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def test_resolve_falls_back_to_env_default(db_session):
    resolved = await service.resolve(db_session, KEY, project_id=uuid.uuid4())
    assert resolved == SETTINGS_REGISTRY[KEY].default == config.work_week_days


async def test_resolve_cascade_narrowest_wins(db_session):
    proj, other = uuid.uuid4(), uuid.uuid4()

    await service.set_value(db_session, KEY, SettingScope.INSTANCE, None, "mon,tue")
    assert await service.resolve(db_session, KEY, project_id=proj) == "mon,tue"
    # instance-scope resolve (no project context) sees the instance value too
    assert await service.resolve(db_session, KEY) == "mon,tue"

    await service.set_value(db_session, KEY, SettingScope.PROJECT, proj, "mon,tue,wed,thu")
    assert await service.resolve(db_session, KEY, project_id=proj) == "mon,tue,wed,thu"
    # a sibling project inherits the instance value, not proj's override
    assert await service.resolve(db_session, KEY, project_id=other) == "mon,tue"

    # clearing the project override falls back to the instance value
    await service.clear_value(db_session, KEY, SettingScope.PROJECT, proj)
    assert await service.resolve(db_session, KEY, project_id=proj) == "mon,tue"


async def test_set_value_enforces_scope_id_consistency(db_session):
    # project requires a scope_id; instance forbids one.
    with pytest.raises(ConflictError):
        await service.set_value(db_session, KEY, SettingScope.PROJECT, None, "mon")
    with pytest.raises(ConflictError):
        await service.set_value(db_session, KEY, SettingScope.INSTANCE, uuid.uuid4(), "mon")


async def test_list_for_scope_marks_overrides(db_session):
    proj = uuid.uuid4()
    rows = await service.list_for_scope(db_session, SettingScope.PROJECT, proj)
    row = next(r for r in rows if r["key"] == KEY.value)
    assert row["set_here"] is False and row["value"] == config.work_week_days

    await service.set_value(db_session, KEY, SettingScope.PROJECT, proj, "mon,fri")
    rows = await service.list_for_scope(db_session, SettingScope.PROJECT, proj)
    row = next(r for r in rows if r["key"] == KEY.value)
    assert row["set_here"] is True and row["value"] == "mon,fri"
