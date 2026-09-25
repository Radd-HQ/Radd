"""RADD-1327: `EntitySpec.searchable`/`mentionable` are finally READ.

Milestones declared both since spec 93 and nothing looked at either flag, while
the platform doc presented searchable plugin entities as current. Now a declared
entity derives a `SearchableSpec` from its own table and its row-visibility gate,
and `/search/entities` answers from the registry — so a milestone is found by
someone who can read its project, and not by someone who cannot.
"""

import importlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.kernel import entities as kentities
from radd.kernel.registry import registries
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

search_router = importlib.import_module("radd.modules.search.router")


@pytest.fixture(autouse=True)
async def _load_milestones(_kernel_registries_loaded):
    """Milestones is a runtime-enabled plugin; dropping it in is the whole act."""
    from radd.modules.milestones import plugin as milestones_plugin

    registries.register_plugin(milestones_plugin)
    for spec in milestones_plugin.entities:
        kentities.register_entity(spec)
    await kentities.ensure_tables()
    yield


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _search(db, user, q, **kwargs):
    defaults = {"types": "", "exclude": "", "mentionable": False, "limit": 5}
    return await search_router.search_entities(session=db, user=user, q=q, **{**defaults, **kwargs})


async def test_a_milestone_is_found_by_a_reader_and_not_by_an_outsider(db):
    admin = User(email=f"ms-{uuid.uuid4().hex[:8]}@example.com", name="Reader", instance_role=InstanceRole.ADMIN.value)
    outsider = User(email=f"ms-out-{uuid.uuid4().hex[:8]}@example.com", name="Outsider", instance_role=InstanceRole.MEMBER.value)
    db.add_all([admin, outsider])
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MS{uuid.uuid4().hex[:4].upper()}", name="Milestones")
    )
    word = f"Zephyr{uuid.uuid4().hex[:6]}"
    model = kentities.model_for("milestone")
    milestone = model(project_id=project.id, title=f"{word} launch", status="open")
    db.add(milestone)
    await db.flush()

    found = await _search(db, admin, word, types="milestone")
    [group] = found.groups
    assert group.entity_type == "milestone" and group.label == "Milestones"
    [hit] = group.hits
    assert hit.id == str(milestone.id) and hit.title == f"{word} launch" and hit.url == "/milestones"

    # The `#` picker lists it too — milestones are mentionable.
    assert [g.entity_type for g in (await _search(db, admin, word, mentionable=True)).groups] == ["milestone"]

    # Someone with no read on the project finds nothing at all.
    assert (await _search(db, outsider, word, types="milestone")).groups == []


def test_the_registry_holds_issues_pages_and_the_derived_milestone():
    searchables = registries.searchables
    assert {"item", "milestone"} <= set(searchables)
    assert searchables["milestone"].mentionable is True
    # The entity ref carries the url a mention and an audit entry link to.
    assert registries.entity_refs["milestone"].url == "/milestones"
