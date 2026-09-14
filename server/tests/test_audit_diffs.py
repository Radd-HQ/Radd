"""Every existing `updated` emitter carries a diff (spec 123, RADD-1168).

A sample across the modules the sweep touched — roles, users, teams, fields,
releases — pinning the shape an auditor reads: old → new for scalars,
added/removed for collections, NAMES where the stored value is an id. The
contract in `test_event_changes.py` is what guarantees the rest of the
emitters; these are the ones whose resolution logic is non-trivial.

DB-backed tests are flushed, never committed; the session rolls back at teardown.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import roles, service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import RoleCreate, RoleUpdate, UserAdminUpdate
from radd.modules.auth.types import AuthEvent, InstanceRole
from radd.modules.events import service as events
from radd.modules.fields import service as fields
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldEvent, FieldType
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.releases import service as releases
from radd.modules.releases.schemas import ReleaseCreate, ReleaseUpdate
from radd.modules.releases.types import ReleaseEvent, ReleaseStatus
from radd.modules.teams import service as teams
from radd.modules.teams.schemas import TeamCreate
from radd.modules.teams.types import TeamEvent


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"diffs-{uuid.uuid4().hex[:8]}@example.com",
        name="Diff Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _latest(db, event_type: str, entity_id) -> dict:
    await db.flush()
    rows = await events.query_events(db, event_types=[event_type], entity_id=str(entity_id), limit=1)
    assert rows, f"no {event_type} for {entity_id}"
    return rows[0].payload


async def test_role_permissions_diff_as_added_and_removed(db, admin):
    role = await roles.create_role(
        db,
        RoleCreate(key=f"r{uuid.uuid4().hex[:6]}", name="Auditor", permissions=["item.read"]),
        actor_id=admin.id,
    )
    await roles.update_role(
        db,
        role.id,
        RoleUpdate(name="Reviewer", permissions=["item.read", "comment.write"]),
        actor_id=admin.id,
    )
    payload = await _latest(db, AuthEvent.ROLE_UPDATED, role.id)
    assert payload["changes"] == [
        {"field": "name", "from": "Auditor", "to": "Reviewer"},
        {"field": "permissions", "added": ["comment.write"], "removed": []},
    ]
    # The payload keeps the full list — consumers that read it are untouched.
    assert payload["permissions"] == ["item.read", "comment.write"]


async def test_admin_user_edit_records_old_values(db, admin):
    user = User(email=f"u-{uuid.uuid4().hex[:8]}@example.com", name="Before", instance_role="member")
    db.add(user)
    await db.flush()
    await auth.update_user_admin(
        db, user.id, UserAdminUpdate(name="After", instance_role=InstanceRole.ADMIN), actor=admin
    )
    payload = await _latest(db, AuthEvent.USER_UPDATED, user.id)
    assert payload["action"] == "admin_updated" and payload["name"] == "After"
    assert payload["changes"] == [
        {"field": "name", "from": "Before", "to": "After"},
        {"field": "instance_role", "from": "member", "to": "admin"},
    ]


async def test_team_membership_diff_names_the_person(db, admin):
    team = await teams.create_team(db, TeamCreate(name=f"t-{uuid.uuid4().hex[:6]}"), actor_id=admin.id)
    await teams.add_team_member(db, team.id, admin.id, actor_id=admin.id)
    payload = await _latest(db, TeamEvent.UPDATED, team.id)
    assert payload["changes"] == [{"field": "members", "added": ["Diff Admin"], "removed": []}]
    await teams.remove_team_member(db, team.id, admin.id, actor_id=admin.id)
    payload = await _latest(db, TeamEvent.UPDATED, team.id)
    assert payload["changes"] == [{"field": "members", "added": [], "removed": ["Diff Admin"]}]


async def test_field_option_growth_is_an_options_diff(db, admin):
    definition = await fields.create_field(
        db,
        FieldDefinitionCreate(
            key=f"opt_{uuid.uuid4().hex[:6]}", name="Size", type=FieldType.SELECT, options=["S"]
        ),
        actor_id=admin.id,
    )
    await fields.extend_options(db, definition.id, ["M", "L"], actor_id=admin.id)
    payload = await _latest(db, FieldEvent.UPDATED, definition.id)
    assert payload["changes"] == [{"field": "options", "added": ["M", "L"], "removed": []}]


async def test_release_status_diff_and_project_subject(db, admin):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"RL{uuid.uuid4().hex[:4].upper()}", name="Rel"), actor_id=admin.id
    )
    release = await releases.create_release(
        db, ReleaseCreate(project_id=project.id, name="One", version="1.0"), actor_id=admin.id
    )
    await releases.update_release(
        db, release.id, ReleaseUpdate(status=ReleaseStatus.RELEASED), actor_id=admin.id
    )
    payload = await _latest(db, ReleaseEvent.UPDATED, release.id)
    assert payload["changes"] == [{"field": "status", "from": "planned", "to": "released"}]
    assert payload["project"]["key"] == project.key
