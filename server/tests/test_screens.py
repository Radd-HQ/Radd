"""Screen (field-layout) resolution — the core invariant: config over defaults,
issue-type over project-default over built-in, ordered. Driven against live Postgres
in a rolled-back transaction (the shared db/admin/project fixture pattern)."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldType
from radd.modules.itemtypes import service as itemtypes_service
from radd.modules.itemtypes.schemas import IssueTypeCreate
from radd.modules.screens import service as screens_service
from radd.modules.screens.schemas import ScreenFieldRow
from radd.modules.screens.types import ScreenBuiltinField, ScreenPlacement
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"scr-{uuid.uuid4().hex[:8]}@example.com",
        name="Screen Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db) -> Project:
    return await projects_service.create_project(
        db, ProjectCreate(key="SCX", name="Screens X")
    )


async def _make_field(db, project, key: str) -> str:
    """Create a custom field with a run-unique key (field keys are GLOBALLY unique
    since spec 86, so a fixed key collides with the shared DB). Returns the key."""
    unique = f"{key}{uuid.uuid4().hex[:8]}"
    await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[project.id], key=unique,
            name=unique.title(), type=FieldType.TEXT,
        ),
        actor_id=None,
    )
    return unique


def _placement(effective, field: str) -> ScreenPlacement | None:
    for row in effective.fields:
        if row.field == field:
            return row.placement
    return None


async def test_defaults_when_no_screen(db, admin, project):
    domain = await _make_field(db, project, "domain")
    eff = await screens_service.resolve_effective(db, project, None)
    assert eff.source == "default"
    # Builtins default PRIMARY; custom fields default SECONDARY (the peek-density win).
    assert _placement(eff, ScreenBuiltinField.CYCLE.value) == ScreenPlacement.PRIMARY
    assert _placement(eff, f"cf:{domain}") == ScreenPlacement.SECONDARY


async def test_project_default_screen_overrides(db, admin, project):
    domain = await _make_field(db, project, "domain")
    await screens_service.replace_screen(
        db, project, None,
        [
            ScreenFieldRow(field=f"cf:{domain}", placement=ScreenPlacement.PRIMARY),
            ScreenFieldRow(field=ScreenBuiltinField.CYCLE.value, placement=ScreenPlacement.HIDDEN),
        ],
        actor_id=admin.id,
    )
    eff = await screens_service.resolve_effective(db, project, None)
    assert eff.source == "project"
    assert _placement(eff, f"cf:{domain}") == ScreenPlacement.PRIMARY  # promoted
    assert _placement(eff, ScreenBuiltinField.CYCLE.value) == ScreenPlacement.HIDDEN  # hidden
    # the custom field was configured first → it sorts ahead of the unconfigured builtins.
    assert eff.fields[0].field == f"cf:{domain}"


async def test_issue_type_screen_beats_project_default(db, admin, project):
    itype = await itemtypes_service.create_type(
        db, IssueTypeCreate(project_id=project.id, name="Spike", color="#ff0000"), actor_id=admin.id
    )
    # Project default hides labels; the Bug screen keeps them primary.
    await screens_service.replace_screen(
        db, project, None,
        [ScreenFieldRow(field=ScreenBuiltinField.LABELS.value, placement=ScreenPlacement.HIDDEN)],
        actor_id=admin.id,
    )
    await screens_service.replace_screen(
        db, project, itype.id,
        [ScreenFieldRow(field=ScreenBuiltinField.LABELS.value, placement=ScreenPlacement.PRIMARY)],
        actor_id=admin.id,
    )
    typed = await screens_service.resolve_effective(db, project, itype.id)
    assert typed.source == "issue_type"
    assert _placement(typed, ScreenBuiltinField.LABELS.value) == ScreenPlacement.PRIMARY
    # An item of a different (unconfigured) type falls back to the project default.
    other = await screens_service.resolve_effective(db, project, uuid.uuid4())
    assert other.source == "project"
    assert _placement(other, ScreenBuiltinField.LABELS.value) == ScreenPlacement.HIDDEN


async def test_field_added_after_screen_saved_still_appears(db, admin, project):
    domain = await _make_field(db, project, "domain")
    await screens_service.replace_screen(
        db, project, None,
        [ScreenFieldRow(field=f"cf:{domain}", placement=ScreenPlacement.PRIMARY)],
        actor_id=admin.id,
    )
    site = await _make_field(db, project, "site")  # added after the screen was saved
    eff = await screens_service.resolve_effective(db, project, None)
    # The unmentioned new field isn't dropped — it defaults to SECONDARY.
    assert _placement(eff, f"cf:{site}") == ScreenPlacement.SECONDARY


async def test_empty_replace_clears_screen(db, admin, project):
    await screens_service.replace_screen(
        db, project, None,
        [ScreenFieldRow(field=ScreenBuiltinField.CYCLE.value, placement=ScreenPlacement.HIDDEN)],
        actor_id=admin.id,
    )
    await screens_service.replace_screen(db, project, None, [], actor_id=admin.id)
    eff = await screens_service.resolve_effective(db, project, None)
    assert eff.source == "default"
    assert _placement(eff, ScreenBuiltinField.CYCLE.value) == ScreenPlacement.PRIMARY


async def test_replace_rejects_unknown_field(db, admin, project):
    from radd.exceptions import ConflictError

    with pytest.raises(ConflictError):
        await screens_service.replace_screen(
            db, project, None,
            [ScreenFieldRow(field="not_a_real_field", placement=ScreenPlacement.PRIMARY)],
            actor_id=admin.id,
        )
