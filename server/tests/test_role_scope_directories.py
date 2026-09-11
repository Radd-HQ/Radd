"""Directory windows preserve grants and enforce name/choice visibility."""

import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.clock import utcnow
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import roles, service as auth
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import BuiltinRoleKey
from radd.modules.groups.models import Group
from radd.modules.items.models import WorkItem
from radd.modules.workflow.models import State
from radd.modules.pages.models import PageSpace
from radd.modules.projects.models import Project
from radd.modules.teams.models import Team


@pytest.mark.parametrize("subject_kind", ["user", "team", "group"])
async def test_subject_windows_keep_expired_and_hidden_grants_without_leaking_names(subject_kind):
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex[:8]
        actor = User(name="Reader", email=prefix + "@test.invalid")
        target = (
            User(name="Target", email=prefix + "-target@test.invalid")
            if subject_kind == "user"
            else Team(name=prefix)
            if subject_kind == "team"
            else Group(name=prefix, dn=prefix)
        )
        baseline = await roles.role_by_key(db, BuiltinRoleKey.BASELINE)
        baseline.permissions = []
        catalog = Role(key=prefix + "catalog", name="Catalog", permissions=["role.read"])
        reader = Role(key=prefix + "reader", name="Reader", permissions=["item.read", "page.read"])
        choices = [
            Role(key=prefix + str(i), name=f"{prefix} role {i:03}", permissions=[])
            for i in range(126)
        ]
        projects = [
            Project(key=prefix + str(i), name=prefix + " project " + str(i)) for i in range(2)
        ]
        spaces = [
            PageSpace(slug=prefix + str(i), name=prefix + " space " + str(i)) for i in range(2)
        ]
        db.add_all([actor, target, catalog, reader, *choices, *projects, *spaces])
        await db.flush()
        subject = {subject_kind + "_id": target.id}
        grant_time = utcnow() - timedelta(days=1)
        rows = [
            GlobalRoleGrant(
                **subject,
                role_id=role.id,
                project_id=projects[i % 2].id if i % 3 == 0 else None,
                space_id=spaces[i % 2].id if i % 3 == 1 else None,
                created_at=grant_time,
                expires_at=utcnow() - timedelta(hours=1) if i == 125 else None,
            )
            for i, role in enumerate(choices)
        ]
        db.add_all(rows)
        db.add_all(
            [
                GlobalRoleGrant(user_id=actor.id, role_id=catalog.id),
                GlobalRoleGrant(user_id=actor.id, role_id=reader.id, project_id=projects[0].id),
                GlobalRoleGrant(user_id=actor.id, role_id=reader.id, space_id=spaces[0].id),
            ]
        )
        await db.flush()
        db.info.clear()
        _, token = await auth.create_api_token(db, actor, TokenCreate(name="Directory"))

        async def override():
            yield db

        app = create_app()
        app.dependency_overrides[get_session] = override
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            params = {subject_kind + "_id": str(target.id), "limit": 50}
            seen = []
            for offset, count in [(0, 50), (50, 50), (100, 26)]:
                r = await client.get(
                    "/api/v1/role-grants/directory", params={**params, "offset": offset}
                )
                assert r.status_code == 200, r.text
                assert r.headers["x-total-count"] == "126"
                assert len(r.json()) == count
                seen.extend(r.json())
            assert {r["id"] for r in seen} == {str(r.id) for r in rows}
            assert len({r["id"] for r in seen}) == 126
            assert [r["id"] for r in seen] == [
                str(row.id) for row in sorted(rows, key=lambda row: row.id)
            ]
            assert any(r["expires_at"] for r in seen)
            assert all(r["role_name"].startswith(prefix) for r in seen)
            for row in seen:
                expected = (
                    projects[0].key
                    if row["project_id"] == str(projects[0].id)
                    else spaces[0].name
                    if row["space_id"] == str(spaces[0].id)
                    else None
                )
                assert row["scope_label"] == expected
            # Revoking role.read must hide labels and choices even though the
            # subject's grant IDs are still readable under the member floor.
            catalog.permissions = []
            await db.flush()
            db.info.clear()
            r = await client.get("/api/v1/role-grants/directory", params=params)
            assert all(row["role_name"] is None for row in r.json())
            r = await client.get("/api/v1/roles/options", params={"value": str(choices[125].id)})
            assert r.status_code == 200 and r.json() == [] and r.headers["x-total-count"] == "0"
            r = await client.get("/api/v1/page-spaces/options", params={"q": prefix})
            assert r.status_code == 200 and [row["value"] for row in r.json()] == [
                str(spaces[0].id)
            ]
            r = await client.get("/api/v1/page-spaces/options", params={"value": str(spaces[1].id)})
            assert r.json() == [] and r.headers["x-total-count"] == "0"
            baseline.permissions = ["item.read@own"]
            state = State(project_id=projects[1].id, name="Open", category="todo", position=0)
            db.add(state)
            await db.flush()
            db.add(
                WorkItem(
                    project_id=projects[1].id,
                    number=1,
                    title="Own issue",
                    kind="issue",
                    state_id=state.id,
                    priority="medium",
                    reporter_id=actor.id,
                )
            )
            await db.flush()
            db.info.clear()
            catalog_rows = (await client.get("/api/v1/projects")).json()
            assert str(projects[1].id) in {row["id"] for row in catalog_rows}
            r = await client.get("/api/v1/role-grants/directory", params=params)
            related = [row for row in r.json() if row["project_id"] == str(projects[1].id)]
            assert related and all(row["scope_label"] == projects[1].key for row in related)
            for bad in [
                {"limit": 0},
                {"offset": -1},
                {"limit": 201},
                {"user_id": str(actor.id), "team_id": str(actor.id)},
            ]:
                r = await client.get("/api/v1/role-grants/directory", params={**params, **bad})
                assert r.status_code in (409, 422), r.text
        await db.rollback()
    await engine.dispose()


@pytest.mark.parametrize(
    "resource,permission", [("roles", "role.read"), ("page-spaces", "page.read")]
)
async def test_role_and_space_options_are_bounded_lean_searchable_and_key_scoped(
    resource, permission
):
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex
        actor = User(name="Admin", email=prefix + "@test.invalid", instance_role="admin")
        rows = [
            Role(key=prefix + str(i), name=f"{prefix} choice {i:03}", permissions=["global.manage"])
            if resource == "roles"
            else PageSpace(name=f"{prefix} choice {i:03}", slug=prefix + str(i))
            for i in range(126)
        ]
        literal = (
            Role(key=prefix + "literal", name=prefix + " %_", permissions=[])
            if resource == "roles"
            else PageSpace(name=prefix + " %_", slug=prefix + "literal")
        )
        db.add_all([actor, *rows, literal])
        await db.flush()
        _, token = await auth.create_api_token(
            db, actor, TokenCreate(name="Read", scopes={"global": [permission]})
        )
        _, empty = await auth.create_api_token(db, actor, TokenCreate(name="Empty", scopes={}))

        async def override():
            yield db

        app = create_app()
        app.dependency_overrides[get_session] = override
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            url = f"/api/v1/{resource}/options"
            seen = []
            for offset, count in [(0, 50), (50, 50), (100, 26)]:
                r = await client.get(
                    url, params={"q": prefix + " choice", "offset": offset, "limit": 50}
                )
                assert r.status_code == 200 and r.headers["x-total-count"] == "126", r.text
                assert len(r.json()) == count
                assert all(set(row) == {"value", "label", "hint"} for row in r.json())
                seen.extend(row["value"] for row in r.json())
            assert seen == [str(row.id) for row in rows]
            r = await client.get(url, params={"value": str(rows[-1].id), "limit": 1})
            assert r.json()[0]["value"] == str(rows[-1].id)
            r = await client.get(url, params={"q": "  " + prefix + " %_  "})
            assert [row["value"] for row in r.json()] == [str(literal.id)]
            if resource == "roles":
                r = await client.get(url, params={"key": rows[-1].key})
                assert [row["value"] for row in r.json()] == [str(rows[-1].id)]
            r = await client.get(url, headers={"Authorization": f"Bearer {empty}"})
            assert r.json() == [] and r.headers["x-total-count"] == "0"
            for bad in [{"limit": 0}, {"offset": -1}, {"q": "x" * 201}, {"limit": 201}]:
                assert (await client.get(url, params=bad)).status_code == 422
        await db.rollback()
    await engine.dispose()
