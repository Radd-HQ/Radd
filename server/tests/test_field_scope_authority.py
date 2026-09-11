"""Field scope changes require authority on both sides of the transition."""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import roles, service as auth
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import BuiltinRoleKey
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition, FieldProject
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.projects.models import Project


@pytest.fixture
async def scope_world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex[:8]
        baseline = await roles.role_by_key(db, BuiltinRoleKey.BASELINE)
        baseline.permissions = []
        actor = User(name="Field editor", email=prefix + "@test.invalid")
        admin = User(name="Admin", email=prefix + "admin@test.invalid", instance_role="admin")
        editor = Role(key=prefix, name="Update fields", permissions=["field.update"])
        projects = [Project(key=f"F{prefix.upper()}{i}", name=f"Scope {i}") for i in range(3)]
        db.add_all([actor, admin, editor, *projects])
        await db.flush()
        db.add_all([
            GlobalRoleGrant(user_id=actor.id, role_id=editor.id, project_id=p.id)
            for p in projects[:2]
        ])
        definitions = []
        for index, scope in enumerate([[], [projects[0].id], [p.id for p in projects[:2]], [p.id for p in projects]]):
            definitions.append(await fields.create_field(db, FieldDefinitionCreate(
                key=f"f{prefix}_{index}", name=f"Original {index}", type="text", project_ids=scope,
            )))
        # Mint both before HTTP: CurrentUser attaches credential context to the
        # identity-map User, so minting after a scoped request is not equivalent.
        _, scoped_key = await auth.create_api_token(db, admin, TokenCreate(
            name="Project editor", scopes={"projects": {str(p.id): ["field.update"] for p in projects[:2]}},
        ))
        _, global_key = await auth.create_api_token(db, admin, TokenCreate(
            name="Global editor", scopes={"global": ["field.update"]},
        ))
        await db.flush()
        db.info.clear()
        app = create_app()
        async def override():
            yield db
        app.dependency_overrides[get_session] = override
        cookie = await auth.create_session(db, actor)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     cookies={"radd_session": cookie}) as client:
            yield db, client, projects, definitions, scoped_key, global_key
        await db.rollback()
    await engine.dispose()


async def assert_unchanged(db, definition, scope, name):
    # Read persisted columns, rather than trusting the ORM relationship cache.
    ids = set(await db.scalars(select(FieldProject.project_id).where(FieldProject.field_id == definition.id)))
    assert ids == set(scope)
    assert await db.scalar(select(FieldDefinition.name).where(FieldDefinition.id == definition.id)) == name


@pytest.mark.parametrize("credential", ["session", "scoped_admin_key"])
async def test_scope_transition_cannot_erase_global_or_uncontrolled_authority(scope_world, credential):
    db, client, projects, definitions, scoped_key, _ = scope_world
    if credential == "scoped_admin_key":
        client.cookies.clear()
        client.headers["Authorization"] = "Bearer " + scoped_key
    global_field, scoped, shared, outside = definitions
    refused = [
        (scoped, []),                     # Scoped -> global needs global update.
        (global_field, [projects[0].id]), # Global -> scoped needs global update.
        (global_field, []),              # Remaining global is not a bypass.
        (scoped, [projects[2].id]),        # Moving away still checks the new scope.
        (shared, [projects[0].id, projects[2].id]),
        (outside, [projects[0].id]),       # Cannot strip a project you don't control.
    ]
    for definition, destination in refused:
        before = list(definition.project_ids)
        name = definition.name
        response = await client.patch(f"/api/v1/fields/{definition.id}", json={
            "project_ids": [str(p) for p in destination], "name": "Must not persist",
        })
        assert response.status_code == 403, response.text
        await assert_unchanged(db, definition, before, name)


async def test_project_editor_can_edit_and_move_within_all_authorized_scopes(scope_world):
    db, client, projects, definitions, _, _ = scope_world
    _, scoped, shared, _ = definitions
    for body, expected in [
        ({"name": "Renamed"}, [projects[0].id]),
        ({"project_ids": None, "name": "Null keeps scope"}, [projects[0].id]),
        ({"project_ids": [str(p.id) for p in projects[:2]]}, [p.id for p in projects[:2]]),
        ({"project_ids": [str(projects[1].id)]}, [projects[1].id]),
    ]:
        response = await client.patch(f"/api/v1/fields/{scoped.id}", json=body)
        assert response.status_code == 200, response.text
        assert set(response.json()["project_ids"]) == {str(p) for p in expected}
        await assert_unchanged(db, scoped, expected, response.json()["name"])
    response = await client.patch(f"/api/v1/fields/{shared.id}", json={"project_ids": [str(projects[0].id)]})
    assert response.status_code == 200
    # A granular update grant does not acquire create, delete or ACL authority.
    assert (await client.delete(f"/api/v1/fields/{scoped.id}")).status_code == 403
    assert (await client.get("/api/v1/grants/directory", params={"resource_type": "field", "resource_id": str(scoped.id)})).status_code == 403
    assert (await client.post("/api/v1/fields", json={"key": "forbidden", "name": "Forbidden", "type": "text", "project_ids": [str(projects[0].id)]})).status_code == 403


async def test_global_update_credential_can_cross_global_boundary_without_admin_bypass(scope_world):
    db, client, projects, definitions, _, global_key = scope_world
    client.cookies.clear()
    client.headers["Authorization"] = "Bearer " + global_key
    global_field, scoped, _, _ = definitions
    for definition, destination in [(scoped, []), (global_field, [projects[2].id])]:
        response = await client.patch(f"/api/v1/fields/{definition.id}", json={"project_ids": [str(p) for p in destination]})
        assert response.status_code == 200, response.text
        await assert_unchanged(db, definition, destination, definition.name)
    assert (await client.delete(f"/api/v1/fields/{scoped.id}")).status_code == 403
