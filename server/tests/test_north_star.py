"""The north-star acceptance test (spec 93 / A10, docs/plugin-platform.md §1).

The `milestones` plugin is a directory with ONE EntitySpec + a nav item. Declaring
it must light the feature up across automations, RBAC, nav, and the entity/CRUD
machinery — with zero edits to any other plugin or the kernel. This test asserts
exactly that, and that the generated model is a real, usable table.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.kernel import registries
from radd.modules.auth.types import all_permission_keys
from radd.modules.milestones.models import Milestone
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture(autouse=True)
def _load_milestones(_kernel_registries_loaded):
    """Load the milestones plugin ON TOP of the builtin set (it's a non-core plugin
    that ships in the repo but isn't in the always-on bootstrap config — it's
    runtime-enabled via the plugin manager). Mirrors what the loader does for a
    plugin declaring entities. Depends on the conftest fixture so it runs after the
    base load. This IS the north-star's 'drop in the plugin' — zero edits elsewhere."""
    from radd.kernel import entities as kentities
    from radd.modules.milestones import plugin as milestones_plugin

    registries.register_plugin(milestones_plugin)
    for spec in milestones_plugin.entities:
        kentities.register_entity(spec)
        registries.entity_routers.append(kentities.crud_router(spec))
    yield


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


# --- auto-wiring: the feature lights up with zero edits elsewhere ---

def test_milestone_is_an_automation_trigger():
    from radd.modules.automations import catalog

    assert "milestone.created" in catalog.TRIGGERS
    assert "milestone.updated" in catalog.TRIGGERS
    assert "milestone.deleted" in catalog.TRIGGERS
    assert catalog.TRIGGERS["milestone.updated"].has_changes is True


def test_milestone_has_rbac_atoms():
    atoms = all_permission_keys()
    assert {"milestone.create", "milestone.update", "milestone.delete", "milestone.manage"} <= atoms


def test_milestone_has_a_nav_item():
    nav = [n for n in registries.nav if n.key == "milestones"]
    assert nav and nav[0].path == "/milestones" and nav[0].requires == ("item.read",)


def test_milestone_entity_and_crud_router_registered():
    assert "milestone" in registries.entities
    assert registries.entities["milestone"].table == "milestones"
    # a generated CRUD router exists (mounted at /api/v1/milestones by app.py)
    assert any(
        any(getattr(r, "path", "") == "/milestones" for r in router.routes)
        for router in registries.entity_routers
    )


def test_milestone_plugin_is_disableable():
    plugin = registries.plugins["radd.milestones"]
    assert plugin.core is False  # the plugin manager may disable it


# --- the generated model is a real, usable table ---

async def test_milestone_model_roundtrips(db):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MS{uuid.uuid4().hex[:5].upper()}", name="Milestone Test")
    )
    m = Milestone(project_id=project.id, title="Ship v1", status="open")
    db.add(m)
    await db.flush()
    assert m.id is not None
    fetched = (await db.execute(select(Milestone).where(Milestone.id == m.id))).scalar_one()
    assert fetched.title == "Ship v1"
    assert fetched.status == "open"
    assert fetched.project_id == project.id
    assert fetched.created_at is not None
    # UPDATE must not lazy-load the server-generated updated_at (eager_defaults) —
    # otherwise the async session raises MissingGreenlet (caught via HTTP PATCH).
    fetched.status = "done"
    await db.flush()
    assert fetched.updated_at is not None
    assert fetched.status == "done"
