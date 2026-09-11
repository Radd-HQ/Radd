"""Builtin grant administration is scoped before paging and never widens credentials."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from radd.clock import utcnow
from radd.modules.access.models import AccessGrant
from radd.modules.auth import service as auth
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.projects.models import Project
from test_field_scope_authority import scope_world as _scope_world

scope_world = _scope_world


@pytest.fixture
async def builtin_world(scope_world):
    db, client, projects, definitions, _, _ = scope_world
    role = await db.scalar(select(Role).where(Role.name == "Update fields"))
    role.permissions = ["field.manage"]
    actor = await db.scalar(select(User).where(User.name == "Field editor"))
    extra = [
        Project(key="B" + uuid.uuid4().hex[:8].upper(), name=f"Builtin project {i:03}")
        for i in range(124)
    ]
    people = [
        User(name=f"Builtin person {i:03}", email=uuid.uuid4().hex + "@test.invalid")
        for i in range(126)
    ]
    db.add_all([*extra, *people])
    await db.flush()
    db.add_all([GlobalRoleGrant(role_id=role.id, user_id=actor.id, project_id=p.id) for p in extra])
    stamp = utcnow() - timedelta(days=1)
    grants = [
        AccessGrant(
            resource_type="builtin_field",
            resource_id="assignee",
            subject_type="user",
            subject_id=p.id,
            access="read",
            project_id=projects[0].id,
            created_at=stamp,
            expires_at=stamp if i == 125 else None,
        )
        for i, p in enumerate(people)
    ]
    other = [
        AccessGrant(
            resource_type="builtin_field",
            resource_id="assignee",
            subject_type="user",
            subject_id=people[0].id,
            access="read",
            project_id=pid,
            created_at=stamp,
        )
        for pid in [None, projects[1].id, projects[2].id]
    ]
    db.add_all([*grants, *other])
    await db.flush()
    db.info.clear()
    yield db, client, projects, grants, other, people, actor


async def test_scoped_builtin_directory_filters_before_count_and_preserves_expiry(builtin_world):
    db, client, projects, grants, other, people, _ = builtin_world
    params = {
        "resource_type": "builtin_field",
        "resource_id": "assignee",
        "project_id": str(projects[0].id),
    }
    seen = []
    for offset, size in [(0, 50), (50, 50), (100, 26)]:
        r = await client.get("/api/v1/grants/directory", params={**params, "offset": offset})
        assert r.status_code == 200, r.text
        assert r.headers["X-Total-Count"] == "126" and len(r.json()) == size
        assert all(row["project_id"] == str(projects[0].id) for row in r.json())
        seen.extend(r.json())
    assert [row["id"] for row in seen] == [str(g.id) for g in sorted(grants, key=lambda g: g.id)]
    assert next(row for row in seen if row["id"] == str(grants[-1].id))["expired"]
    r = await client.get("/api/v1/grants", params=params)
    assert len(r.json()) == 125 and str(grants[-1].id) not in {row["id"] for row in r.json()}
    r = await client.get(
        "/api/v1/grants/directory", params={**params, "project_id": str(projects[1].id)}
    )
    assert r.headers["X-Total-Count"] == "1" and r.json()[0]["id"] == str(other[1].id)
    for path in ["/api/v1/grants", "/api/v1/grants/directory"]:
        for scope in [{}, {"global_only": True}, {"project_id": str(projects[2].id)}]:
            assert (
                await client.get(
                    path,
                    params={"resource_type": "builtin_field", "resource_id": "assignee", **scope},
                )
            ).status_code == 403
    assert (
        await client.get("/api/v1/grants/directory", params={**params, "q": people[1].name})
    ).headers["X-Total-Count"] == "1"
    assert (
        await client.get("/api/v1/grants/directory", params={**params, "global_only": True})
    ).status_code == 422


async def test_builtin_project_choices_caps_and_writes_use_management_authority(builtin_world):
    db, client, projects, grants, other, people, actor = builtin_world
    summary = (await client.get("/api/v1/fields/settings-summary")).json()
    assert summary["can_manage_builtin_projects"] and not summary["can_manage_builtin"]
    assert (await client.get("/api/v1/projects")).json() == []
    seen = []
    for offset, size in [(0, 50), (50, 50), (100, 26)]:
        r = await client.get(
            "/api/v1/fields/scope-projects/options",
            params={"permission": "field.manage", "offset": offset},
        )
        assert r.headers["X-Total-Count"] == "126" and len(r.json()) == size
        seen.extend(row["value"] for row in r.json())
    assert str(projects[2].id) not in seen
    body = {
        "resource_type": "builtin_field",
        "resource_id": "assignee",
        "subject_type": "user",
        "subject_id": str(people[0].id),
        "access": "write",
        "effect": "deny",
    }
    for scope in [[], [str(projects[0].id), str(projects[2].id)]]:
        assert (
            await client.post("/api/v1/grants", json={**body, "project_ids": scope})
        ).status_code == 403
    assert not list(
        await db.scalars(
            select(AccessGrant.id).where(
                AccessGrant.resource_type == "builtin_field", AccessGrant.access == "write"
            )
        )
    )
    r = await client.post("/api/v1/grants", json={**body, "project_ids": [str(projects[0].id)]})
    assert r.status_code == 201 and r.json()[0]["project_id"] == str(projects[0].id)
    assert (await client.delete("/api/v1/grants/" + r.json()[0]["id"])).status_code == 204
    for g in [other[0], other[-1]]:
        assert (await client.delete("/api/v1/grants/" + str(g.id))).status_code == 403
    assert (await client.delete("/api/v1/grants/" + str(grants[-1].id))).status_code == 204
    for grant in await db.scalars(
        select(GlobalRoleGrant).where(GlobalRoleGrant.user_id == actor.id)
    ):
        grant.expires_at = utcnow() - timedelta(seconds=1)
    await db.flush()
    db.info.clear()
    assert not (await client.get("/api/v1/fields/settings-summary")).json()[
        "can_manage_builtin_projects"
    ]
    assert (
        await client.get(
            "/api/v1/grants/directory",
            params={
                "resource_type": "builtin_field",
                "resource_id": "assignee",
                "project_id": str(projects[0].id),
            },
        )
    ).status_code == 403


async def test_builtin_reads_intersect_admin_key_scope_and_keep_global_legacy_contract(
    builtin_world,
):
    db, client, projects, grants, other, _, _ = builtin_world
    admin = User(
        name="Builtin key admin", email=uuid.uuid4().hex + "@test.invalid", instance_role="admin"
    )
    db.add(admin)
    await db.flush()
    _, key = await auth.create_api_token(
        db,
        admin,
        TokenCreate(
            name="Builtin project key", scopes={"projects": {str(projects[0].id): ["field.manage"]}}
        ),
    )
    _, global_key = await auth.create_api_token(
        db, admin, TokenCreate(name="Global builtin key", scopes={"global": ["field.manage"]})
    )
    client.cookies.clear()
    client.headers["Authorization"] = "Bearer " + key
    db.info.clear()
    params = {"resource_type": "builtin_field", "resource_id": "assignee"}
    assert (
        await client.get(
            "/api/v1/grants/directory", params={**params, "project_id": str(projects[0].id)}
        )
    ).headers["X-Total-Count"] == "126"
    for scope in [{}, {"global_only": True}, {"project_id": str(projects[1].id)}]:
        assert (
            await client.get("/api/v1/grants/directory", params={**params, **scope})
        ).status_code == 403
    client.headers["Authorization"] = "Bearer " + global_key
    db.info.clear()
    assert (await client.get("/api/v1/grants/directory", params=params)).headers[
        "X-Total-Count"
    ] == "129"
    assert len((await client.get("/api/v1/grants", params=params)).json()) == 128
    r = await client.get("/api/v1/grants/directory", params={**params, "global_only": True})
    assert r.headers["X-Total-Count"] == "1" and r.json()[0]["id"] == str(other[0].id)
