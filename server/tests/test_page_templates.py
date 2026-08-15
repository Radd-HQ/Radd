"""RADD-1100 — the page-template family gets the tests it never had.

The render contract (three placeholders, unknown ones SURVIVE — they are
prompts to the author, not errors), space-scoped listing, and the
create-from-template path that RADD-712 wired into PageCreate.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.pages import service as pages_service, spaces as pages_spaces, templates
from radd.modules.pages.models import PageTemplate
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def test_render_substitutes_three_and_only_three():
    body = "# {{title}}\nBy {{author}} on {{date}}.\nCustomer: {{customer}}"
    out = templates.render(body, title="Postmortem", author="Maya", today=date(2026, 8, 15))
    assert "# Postmortem" in out
    assert "By Maya on 2026-08-15." in out
    # unknown placeholders are prompts, not errors — they survive
    assert "{{customer}}" in out


async def test_listing_scopes_to_space_plus_global(db):
    admin = User(
        email=f"pt-{uuid.uuid4().hex[:8]}@example.com",
        name="Templater",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    space = await pages_spaces.create_space(
        db, PageSpaceCreate(name=f"T{uuid.uuid4().hex[:6]}"), actor_id=admin.id
    )
    other = await pages_spaces.create_space(
        db, PageSpaceCreate(name=f"O{uuid.uuid4().hex[:6]}"), actor_id=admin.id
    )
    tag = uuid.uuid4().hex[:6]
    db.add_all(
        [
            PageTemplate(id=uuid.uuid4(), name=f"global-{tag}", body="g", created_by=admin.id),
            PageTemplate(id=uuid.uuid4(), name=f"scoped-{tag}", body="s", space_id=space.id, created_by=admin.id),
            PageTemplate(id=uuid.uuid4(), name=f"foreign-{tag}", body="f", space_id=other.id, created_by=admin.id),
        ]
    )
    await db.flush()
    names = {t.name for t in await templates.list_templates(db, space.id)}
    assert f"global-{tag}" in names
    assert f"scoped-{tag}" in names
    assert f"foreign-{tag}" not in names


async def test_create_from_template_renders_unless_body_given(db):
    admin = User(
        email=f"pt-{uuid.uuid4().hex[:8]}@example.com",
        name="Author Person",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    space = await pages_spaces.create_space(
        db, PageSpaceCreate(name=f"T{uuid.uuid4().hex[:6]}"), actor_id=admin.id
    )
    name = f"runbook-{uuid.uuid4().hex[:6]}"
    db.add(
        PageTemplate(
            id=uuid.uuid4(),
            name=name,
            body="# {{title}}\nOwner: {{author}}",
            created_by=admin.id,
        )
    )
    await db.flush()

    page = await pages_service.create_page(
        db,
        PageCreate(space_id=space.id, title="DB failover", template=name),
        actor_id=admin.id,
    )
    assert "# DB failover" in page.body
    assert "Owner: Author Person" in page.body

    # an explicit body is a deliberate choice and must win
    explicit = await pages_service.create_page(
        db,
        PageCreate(space_id=space.id, title="Notes", template=name, body="my own words"),
        actor_id=admin.id,
    )
    assert explicit.body == "my own words"

    with pytest.raises(NotFoundError):
        await pages_service.create_page(
            db,
            PageCreate(space_id=space.id, title="X", template=f"missing-{uuid.uuid4().hex[:4]}"),
            actor_id=admin.id,
        )
