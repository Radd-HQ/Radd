"""Field settings expose bounded metadata and the actual mutation capabilities."""

import uuid
from datetime import timedelta

from sqlalchemy import event, select

from radd.clock import utcnow
from radd.modules.auth import service as auth
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.fields.models import FieldDefinition, FieldProject
from radd.modules.projects.models import Project
from test_field_scope_authority import scope_world as _scope_world

scope_world = _scope_world


async def test_field_windows_are_lean_stable_and_filter_authority_before_count(scope_world):
    db, client, projects, definitions, _, _ = scope_world
    stamp = utcnow()
    rows = [
        FieldDefinition(
            key=f"d{uuid.uuid4().hex[:12]}",
            name=f"Directory {i:03}",
            type="select",
            options=["Heavy option " * 1000],
            default_value="Heavy option " * 1000,
            project_links=[FieldProject(project_id=projects[0].id)],
            source="user",
            created_at=stamp,
        )
        for i in range(126)
    ]
    rows[-1].name = "Directory literal %_"
    db.add_all(rows)
    await db.flush()
    db.info.clear()
    statements = []

    def capture(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        seen = []
        for offset, count in [(0, 50), (50, 50), (100, 26)]:
            response = await client.get(
                "/api/v1/fields/directory", params={"q": "Directory", "offset": offset}
            )
            assert response.status_code == 200, response.text
            assert response.headers["X-Total-Count"] == "126" and len(response.json()) == count
            assert all(
                "options" not in r and "default_value" not in r and r["project_count"] == 1
                for r in response.json()
            )
            seen.extend(r["id"] for r in response.json())
        assert seen == [str(row.id) for row in sorted(rows, key=lambda row: row.id)]
        assert not any(
            "field_definitions.options" in s or "field_definitions.default_value" in s
            for s in statements
        )
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", capture)
    response = await client.get("/api/v1/fields/directory", params={"q": "%_"})
    assert response.headers["X-Total-Count"] == "1" and response.json()[0]["id"] == str(rows[-1].id)
    all_rows = await client.get("/api/v1/fields/directory", params={"limit": 200})
    assert (
        all_rows.headers["X-Total-Count"] == "128"
    )  # Two existing definitions have fully managed scopes.
    for field in [definitions[0], definitions[-1]]:
        assert (await client.get(f"/api/v1/fields/definitions/{field.id}")).status_code == 404
    body = await client.get(f"/api/v1/fields/definitions/{rows[-1].id}")
    assert body.json()["options"] == rows[-1].options and body.json()["can_update"]
    assert not body.json()["can_delete"] and not body.json()["can_manage"]


async def test_granular_and_reader_capabilities_match_scope_mutations(scope_world):
    db, client, projects, definitions, _, _ = scope_world
    summary = (await client.get("/api/v1/fields/settings-summary")).json()
    assert summary == {
        "can_access": True,
        "can_create": False,
        "can_create_global": False,
        "can_update_global": False,
        "can_manage_builtin": False,
        "can_manage_builtin_projects": False,
    }
    shared = (await client.get(f"/api/v1/fields/definitions/{definitions[2].id}")).json()
    assert shared["can_update"] and not shared["can_manage"] and not shared["can_delete"]
    actor = await db.scalar(select(User).where(User.name == "Field editor"))
    reader = Role(key=uuid.uuid4().hex[:10], name="Issue reader", permissions=["item.read"])
    db.add(reader)
    await db.flush()
    db.add(GlobalRoleGrant(user_id=actor.id, role_id=reader.id, project_id=projects[-1].id))
    await db.flush()
    db.info.clear()
    # Preserve legacy member metadata access, without showing unauthorized actions.
    response = await client.get("/api/v1/fields/directory")
    assert response.headers["X-Total-Count"] == "4"
    for field in [definitions[0], definitions[-1]]:
        response = await client.get(f"/api/v1/fields/definitions/{field.id}")
        assert response.status_code == 200
        assert not any(response.json()[key] for key in ["can_update", "can_delete", "can_manage"])
    assert len((await client.get("/api/v1/fields")).json()) == 4
    # Delete-only global permission grants deletion, not editing or ACL management.
    deleter = Role(key=uuid.uuid4().hex[:10], name="Delete fields", permissions=["field.delete"])
    db.add(deleter)
    await db.flush()
    db.add(GlobalRoleGrant(user_id=actor.id, role_id=deleter.id))
    await db.flush()
    db.info.clear()
    response = await client.get(f"/api/v1/fields/definitions/{definitions[0].id}")
    assert (
        response.json()["can_delete"]
        and not response.json()["can_update"]
        and not response.json()["can_manage"]
    )
    assert (await client.delete(f"/api/v1/fields/{definitions[0].id}")).status_code == 204


async def test_scope_choices_and_references_support_field_only_authority_without_name_leaks(
    scope_world,
):
    db, client, projects, _, _, _ = scope_world
    actor = await db.scalar(select(User).where(User.name == "Field editor"))
    role = await db.scalar(select(Role).where(Role.name == "Update fields"))
    new_projects = [
        Project(key=f"Z{i:03}{uuid.uuid4().hex[:4]}".upper(), name=f"Field project {i:03}")
        for i in range(126)
    ]
    db.add_all(new_projects)
    await db.flush()
    db.add_all(
        [GlobalRoleGrant(user_id=actor.id, role_id=role.id, project_id=p.id) for p in new_projects]
    )
    await db.flush()
    db.info.clear()
    seen = []
    for offset, size in [(0, 50), (50, 50), (100, 26)]:
        response = await client.get(
            "/api/v1/fields/scope-projects/options",
            params={
                "permission": "field.update",
                "q": "Field project",
                "offset": offset,
            },
        )
        assert response.status_code == 200 and response.headers["X-Total-Count"] == "126"
        assert len(response.json()) == size
        seen.extend(r["value"] for r in response.json())
    assert seen == [str(p.id) for p in new_projects]
    assert (
        await client.get("/api/v1/projects")
    ).json() == []  # No unrelated issue membership was needed.
    for permission in ["field.create", "field.update"]:
        response = await client.get(
            "/api/v1/fields/scope-projects/options",
            params={"permission": permission, "q": projects[-1].name},
        )
        assert response.json() == [] and response.headers["X-Total-Count"] == "0"
    response = await client.post(
        "/api/v1/fields/scope-projects/references", json={"ids": [str(p.id) for p in projects]}
    )
    assert {r["value"] for r in response.json()} == {str(p.id) for p in projects[:2]}
    # Expired grants immediately withdraw both choices and definition admission.
    for grant in await db.scalars(
        select(GlobalRoleGrant).where(GlobalRoleGrant.user_id == actor.id)
    ):
        grant.expires_at = utcnow() - timedelta(seconds=1)
    await db.flush()
    db.info.clear()
    assert (await client.get("/api/v1/fields/directory")).json() == []
    assert (
        await client.get(
            "/api/v1/fields/scope-projects/options", params={"permission": "field.update"}
        )
    ).json() == []


async def test_field_read_bounds_and_credentials(scope_world):
    db, client, projects, definitions, scoped_key, _ = scope_world
    client.cookies.clear()
    client.headers["Authorization"] = "Bearer " + scoped_key
    response = await client.get("/api/v1/fields/directory")
    assert response.headers["X-Total-Count"] == "2"
    assert (await client.get(f"/api/v1/fields/definitions/{definitions[0].id}")).status_code == 404
    for query in [{"limit": 201}, {"offset": -1}, {"q": "x" * 201}]:
        assert (await client.get("/api/v1/fields/directory", params=query)).status_code == 422
    assert (
        await client.post(
            "/api/v1/fields/scope-projects/references",
            json={"ids": [str(uuid.uuid4()) for _ in range(51)]},
        )
    ).status_code == 422
    assert (
        await client.get(
            "/api/v1/fields/scope-projects/options", params={"permission": "item.read"}
        )
    ).status_code == 422
    # Use a separate admin identity to mint the empty key; CurrentUser mutates credential context.
    admin = User(
        name="Empty key admin", email=uuid.uuid4().hex + "@test.invalid", instance_role="admin"
    )
    db.add(admin)
    await db.flush()
    _, key = await auth.create_api_token(db, admin, TokenCreate(name="Empty", scopes={}))
    client.headers["Authorization"] = "Bearer " + key
    db.info.clear()
    assert (await client.get("/api/v1/fields/directory")).json() == []
    assert not any((await client.get("/api/v1/fields/settings-summary")).json().values())
    assert (
        await client.post(
            "/api/v1/fields/scope-projects/references", json={"ids": [str(p.id) for p in projects]}
        )
    ).json() == []
