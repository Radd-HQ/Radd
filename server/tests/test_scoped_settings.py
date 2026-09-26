"""Scalar settings cascade (specs 50/67): project → instance → env default.

DB-backed (compose Postgres, like the SLQ smoke test). Writes are flushed, never
committed — the session rolls back at teardown, so rows never persist.
"""

import uuid

import pytest

from radd.config import settings as config
from radd.exceptions import ConflictError
from radd.modules.settings import service
from radd.modules.settings.types import SettingKey, SettingScope, setting_spec

KEY = SettingKey.WORK_WEEK_DAYS


async def test_resolve_falls_back_to_env_default(db):
    resolved = await service.resolve(db, KEY, project_id=uuid.uuid4())
    assert resolved == setting_spec(KEY).default == config.work_week_days


async def test_resolve_cascade_narrowest_wins(db):
    proj, other = uuid.uuid4(), uuid.uuid4()

    await service.set_value(db, KEY, SettingScope.INSTANCE, None, "mon,tue")
    assert await service.resolve(db, KEY, project_id=proj) == "mon,tue"
    # instance-scope resolve (no project context) sees the instance value too
    assert await service.resolve(db, KEY) == "mon,tue"

    await service.set_value(db, KEY, SettingScope.PROJECT, proj, "mon,tue,wed,thu")
    assert await service.resolve(db, KEY, project_id=proj) == "mon,tue,wed,thu"
    # a sibling project inherits the instance value, not proj's override
    assert await service.resolve(db, KEY, project_id=other) == "mon,tue"

    # clearing the project override falls back to the instance value
    await service.clear_value(db, KEY, SettingScope.PROJECT, proj)
    assert await service.resolve(db, KEY, project_id=proj) == "mon,tue"


async def test_set_value_enforces_scope_id_consistency(db):
    # project requires a scope_id; instance forbids one.
    with pytest.raises(ConflictError):
        await service.set_value(db, KEY, SettingScope.PROJECT, None, "mon")
    with pytest.raises(ConflictError):
        await service.set_value(db, KEY, SettingScope.INSTANCE, uuid.uuid4(), "mon")


async def test_list_for_scope_marks_overrides(db):
    proj = uuid.uuid4()
    rows = await service.list_for_scope(db, SettingScope.PROJECT, proj)
    row = next(r for r in rows if r["key"] == KEY.value)
    assert row["set_here"] is False and row["value"] == config.work_week_days

    await service.set_value(db, KEY, SettingScope.PROJECT, proj, "mon,fri")
    rows = await service.list_for_scope(db, SettingScope.PROJECT, proj)
    row = next(r for r in rows if r["key"] == KEY.value)
    assert row["set_here"] is True and row["value"] == "mon,fri"
