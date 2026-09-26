"""RADD-1009: a project can be renamed and described after creation.

Three things the browser never offered, at the seam that matters:
- `project.manage` on THAT project is the gate (an admin passes; a Member —
  who holds item.* but not project.manage — is refused);
- the KEY never changes, whatever the body says (item keys derive from it);
- a real change emits `project.updated` with the diff, a no-op emits nothing.
"""


import httpx
import pytest

from radd.app import create_app
from radd.modules.auth import roles as auth_roles, service as auth
from radd.modules.auth.models import GlobalRoleGrant
from radd.modules.auth.types import SESSION_COOKIE_NAME, BuiltinRoleKey, InstanceRole
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectUpdate
from radd.modules.projects.types import ProjectEntity, ProjectEvent
from radd.modules.auth.types import LoginMethod

from _factories import make_project, make_user


@pytest.fixture
async def project(db):
    return await make_project(db, "PU", "Before")


def _client(cookie: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://test",
        cookies={SESSION_COOKIE_NAME: cookie},
    )


async def test_service_changes_name_and_description_and_emits_the_diff(db, project):
    actor = await make_user(db, role=InstanceRole.ADMIN)
    await projects_service.update_project(
        db, project, ProjectUpdate(name="  After  ", description="What it is for"), actor_id=actor.id
    )
    assert (project.name, project.description) == ("After", "What it is for")

    feed = await events.entity_activity(
        db, entity_type=ProjectEntity.PROJECT.value, entity_id=project.id
    )
    updates = [e for e in feed if e.event_type == ProjectEvent.PROJECT_UPDATED.value]
    assert len(updates) == 1
    assert updates[0].payload["changes"] == [
        {"field": "name", "from": "Before", "to": "After"},
        {"field": "description", "from": "", "to": "What it is for"},
    ]

    # A PATCH that changes nothing is not an update.
    await projects_service.update_project(db, project, ProjectUpdate(name="After"), actor_id=actor.id)
    feed = await events.entity_activity(
        db, entity_type=ProjectEntity.PROJECT.value, entity_id=project.id
    )
    assert sum(e.event_type == ProjectEvent.PROJECT_UPDATED.value for e in feed) == 1


async def test_blank_name_is_refused_by_the_schema():
    with pytest.raises(ValueError):
        ProjectUpdate(name="   ")
    assert "key" not in ProjectUpdate.model_fields


async def test_http_admin_renames_member_is_refused_key_unchanged(db, project):
    admin = await make_user(db, role=InstanceRole.ADMIN)
    member = await make_user(db)
    member_role = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(role_id=member_role.id, user_id=member.id, project_id=project.id))
    await db.flush()
    admin_cookie = await auth.create_session(db, admin, method=LoginMethod.PASSWORD)
    member_cookie = await auth.create_session(db, member, method=LoginMethod.PASSWORD)
    await db.commit()

    path = f"/api/v1/projects/{project.id}"
    async with _client(admin_cookie) as client:
        response = await client.patch(
            path, json={"name": "Renamed", "description": "Described", "key": "NOPE"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "Renamed"
        assert body["description"] == "Described"
        assert body["key"] == project.key  # an unknown field is ignored, never applied

        blank = await client.patch(path, json={"name": "   "})
        assert blank.status_code == 422

    async with _client(member_cookie) as client:
        # The member READS the project (item.read via the grant)…
        assert (await client.get(path)).status_code == 200
        # …but cannot manage it.
        refused = await client.patch(path, json={"name": "Hijacked"})
        assert refused.status_code == 403

    async with _client(admin_cookie) as client:
        after = (await client.get(path)).json()
        assert (after["name"], after["key"]) == ("Renamed", project.key)
