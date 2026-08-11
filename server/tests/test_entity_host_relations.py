"""The generated-CRUD row filter says what it cannot do (RADD-1040).

`relation_holds_row` is the SYNC gate: it treats a query-gated relation
(`holds=None` — membership living in another table, the `@participant` shape)
as NOT held. Failing closed is right; a leak would be worse. But
`AuthEntityHost.visible_rows` is what every plugin entity's generated `GET
/<entity>` uses, so a plugin registering an expensive relation on its own
entity gets rows that quietly vanish for exactly the actors the relation was
written to admit — and from outside that is indistinguishable from "the
feature does not work".

So the rows still stay hidden, and the operator is told why, once per
(entity, relation) rather than once per row of every listing.

Rolled-back transactions on the compose DB (the permission resolution is
real — a fabricated permission set would prove nothing about the path that
actually runs).
"""

import logging
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.kernel.registry import register_relation, registries
from radd.kernel.specs import RelationSpec
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.entityhost import AuthEntityHost
from radd.modules.auth.models import Role, User
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole

# Side effect: workflow's project.created hook seeds default states.
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.auth import entityhost
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

# The entity under test is the north-star plugin's, and the relation is one it
# does not have: a plugin CAN register an expensive relation, which is the whole
# point of the warning. `item.read@<key>` is the real atom shape — generated
# CRUD gates a project-scoped entity on item.read and narrows it by whatever
# RelationSpecs the entity registered.
_ENTITY = "milestone"
_RELATION = "shepherded"
_ATOM = f"item.read@{_RELATION}"


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await auth_roles.ensure_builtin_roles(session)
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
def query_gated_relation():
    """A relation with no pure row form — participants' shape, on a plugin
    entity. Registered directly (the conftest reloads the registries per test,
    so this cannot leak into another one), and popped anyway."""
    register_relation(
        RelationSpec(
            resource=_ENTITY,
            key=_RELATION,
            label="shepherded by them",
            # Membership lives elsewhere; there is nothing on the loaded row to
            # test, which is exactly what `holds=None` declares.
            where=lambda actor: SimpleNamespace(),
            holds=None,
            expensive=True,
        )
    )
    entityhost._query_gated_warned.discard((_ENTITY, _RELATION))
    yield
    registries.relations.pop((_ENTITY, _RELATION), None)
    entityhost._query_gated_warned.discard((_ENTITY, _RELATION))


async def _member(db, name: str) -> User:
    user = User(
        email=f"eh-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _grant_via_baseline(db, atom: str) -> None:
    """Put a qualified read on the floor every active user holds, and drop the
    per-session memo so the next resolution sees it (the RADD-773 shape)."""
    baseline = (
        await db.execute(select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value))
    ).scalar_one()
    baseline.permissions = [*baseline.permissions, atom]
    await db.flush()
    db.info.pop("radd.baseline_permissions", None)


async def test_a_query_gated_relation_is_dropped_and_reported(
    db, query_gated_relation, caplog
):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"EH{uuid.uuid4().hex[:4].upper()}", name="E")
    )
    actor = await _member(db, "Shepherd")
    await _grant_via_baseline(db, _ATOM)
    # Only `visible_rows`'s own reads matter here (project_id), so the row does
    # not need the plugin's table — the path under test never loads one.
    row = SimpleNamespace(id=uuid.uuid4(), project_id=project.id)

    host = AuthEntityHost()
    with caplog.at_level(logging.WARNING, logger=entityhost.__name__):
        visible = await host.visible_rows(db, actor, _ENTITY, [row])
        # Called twice on purpose: the warning is once per (entity, relation),
        # not once per listing — and certainly not once per ROW.
        visible_again = await host.visible_rows(db, actor, _ENTITY, [row])

    assert visible == [] and visible_again == []  # narrowed, never widened
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert _ENTITY in message and _RELATION in message
    assert "holds=None" in message  # names the spec's own vocabulary


async def test_no_warning_when_the_actor_could_not_use_the_relation(
    db, query_gated_relation, caplog
):
    """Scoped to relations the actor's permissions would actually have needed:
    an instance whose plugins register expensive relations nobody holds stays
    silent, and the warning keeps meaning something."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"EQ{uuid.uuid4().hex[:4].upper()}", name="E")
    )
    actor = await _member(db, "Ordinary")  # Baseline only: @own / @participant
    row = SimpleNamespace(id=uuid.uuid4(), project_id=project.id)

    host = AuthEntityHost()
    with caplog.at_level(logging.WARNING, logger=entityhost.__name__):
        await host.visible_rows(db, actor, _ENTITY, [row])
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


async def test_an_unqualified_reader_still_sees_every_row(db, query_gated_relation):
    """The relation narrowing only runs below `@any`; an admin (or anyone
    holding item.read outright) is untouched by the whole mechanism."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"EA{uuid.uuid4().hex[:4].upper()}", name="E")
    )
    admin = User(
        email=f"eh-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    row = SimpleNamespace(id=uuid.uuid4(), project_id=project.id)
    assert await AuthEntityHost().visible_rows(db, admin, _ENTITY, [row]) == [row]
