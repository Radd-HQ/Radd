"""Settings reads and writes keep template bodies and scope authority separate."""

import uuid

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import roles, service as auth
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import BuiltinRoleKey
from radd.modules.pages.models import Page, PageSpace, PageTemplate


@pytest.fixture
async def settings_world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex[:8]
        baseline = await roles.role_by_key(db, BuiltinRoleKey.BASELINE)
        baseline.permissions = []
        manager = User(name="Wiki manager", email=prefix + "@test.invalid")
        admin = User(name="Admin", email=prefix + "admin@test.invalid", instance_role="admin")
        reader = Role(key=prefix + "reader", name="Reader", permissions=["page.read"])
        owner = Role(key=prefix + "owner", name="Owner", permissions=["page.manage"])
        spaces = [PageSpace(name=prefix + str(i), slug=prefix + str(i)) for i in range(3)]
        db.add_all([manager, admin, reader, owner, *spaces]); await db.flush()
        db.add_all([GlobalRoleGrant(user_id=manager.id, role_id=reader.id, space_id=s.id) for s in spaces[:2]])
        grant = GlobalRoleGrant(user_id=manager.id, role_id=owner.id, space_id=spaces[1].id)
        db.add(grant)
        templates = [PageTemplate(name=f"{prefix} template {i:03}", description="Meeting notes %_" if i == 125 else "Notes",
                                  body="Private markdown " * 1000, space_id=spaces[1].id if i % 2 else None, created_by=admin.id)
                     for i in range(126)]
        hidden = PageTemplate(name=prefix + " hidden", body="Do not leak", space_id=spaces[2].id, created_by=admin.id)
        db.add_all([*templates, hidden]); await db.flush(); db.info.clear()
        cookie = await auth.create_session(db, manager)
        admin_cookie = await auth.create_session(db, admin)
        app = create_app()
        async def override():
            yield db
        app.dependency_overrides[get_session] = override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     cookies={"radd_session": cookie}) as client:
            yield db, client, manager, admin, spaces, templates, hidden, grant, admin_cookie, engine
        await db.rollback()
    await engine.dispose()


async def test_template_directory_filters_before_paging_and_omits_bodies(settings_world):
    db, client, _, _, spaces, templates, hidden, _, _, engine = settings_world
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        seen = []
        for offset, count in [(0, 50), (50, 50), (100, 26)]:
            response = await client.get(f"/api/v1/page-templates/directory?limit=50&offset={offset}")
            assert response.status_code == 200
            assert response.headers["X-Total-Count"] == "126"
            rows = response.json(); assert len(rows) == count
            assert all("body" not in row for row in rows)
            assert all(row["space_name"] == (spaces[1].name if row["space_id"] else None) for row in rows)
            seen.extend(row["id"] for row in rows)
        assert seen == [str(t.id) for t in templates]
        assert not any("page_templates.body" in sql for sql in statements)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    response = await client.get("/api/v1/page-templates/directory", params={"q": "%_"})
    assert [row["id"] for row in response.json()] == [str(templates[-1].id)]
    assert response.headers["X-Total-Count"] == "1"
    assert (await client.get(f"/api/v1/page-templates/{hidden.id}")).status_code == 404
    assert (await client.get(f"/api/v1/page-templates/{uuid.uuid4()}")).status_code == 404
    direct = await client.get(f"/api/v1/page-templates/{templates[-1].id}")
    assert direct.json()["body"] == templates[-1].body
    # Existing template consumers still receive their complete usable list.
    assert len((await client.get("/api/v1/page-templates")).json()) == 126
    for query in ("limit=0", "limit=201", "offset=-1", "q=" + "x" * 201):
        assert (await client.get("/api/v1/page-templates/directory?" + query)).status_code == 422


async def test_scoped_space_manager_cannot_perform_instance_or_grant_operations(settings_world):
    db, client, manager, admin, spaces, templates, _, grant, _, _ = settings_world
    response = await client.patch(f"/api/v1/page-spaces/{spaces[1].id}", json={"name": "Renamed"})
    assert response.status_code == 200 and response.json()["name"] == "Renamed"
    # Spec 121 §5: the public switch is its own call — a space-scoped manager may flip it.
    response = await client.put(f"/api/v1/page-spaces/{spaces[1].id}/public-access", json={"public": True})
    assert response.status_code == 200 and response.json()["public"] is True
    assert (await client.patch(f"/api/v1/page-spaces/{spaces[0].id}", json={"name": "Wrong"})).status_code == 403
    assert (await client.post("/api/v1/page-spaces", json={"name": "Forbidden"})).status_code == 403
    assert (await client.post("/api/v1/pages/reindex")).status_code == 403
    assert (await client.post("/api/v1/page-templates", json={"name": "Forbidden", "space_id": str(spaces[1].id)})).status_code == 403
    assert (await client.patch(f"/api/v1/page-templates/{templates[-1].id}", json={"name": "Forbidden"})).status_code == 403
    assert (await client.delete(f"/api/v1/page-templates/{templates[-1].id}")).status_code == 403
    assert (await client.post("/api/v1/role-grants", json={"role_id": str(grant.role_id), "user_id": str(admin.id), "space_ids": [str(spaces[1].id)]})).status_code == 403
    assert (await client.delete(f"/api/v1/role-grants/{grant.id}")).status_code == 403
    assert (await client.delete(f"/api/v1/page-spaces/{spaces[0].id}")).status_code == 403
    db.add(Page(space_id=spaces[1].id, title="Keep", slug="keep", body="", created_by=manager.id, updated_by=manager.id)); await db.flush()
    assert (await client.delete(f"/api/v1/page-spaces/{spaces[1].id}")).status_code == 409
    assert (await client.delete(f"/api/v1/page-spaces/{spaces[1].id}?force=true")).status_code == 204


async def test_space_access_read_uses_wiki_authority_without_issue_membership(settings_world):
    _, client, _, _, spaces, _, _, grant, _, _ = settings_world
    response = await client.get("/api/v1/role-grants", params={"space_id": str(spaces[1].id)})
    assert response.status_code == 200
    assert str(grant.id) in {row["id"] for row in response.json()}
    assert (await client.get("/api/v1/role-grants", params={"space_id": str(spaces[2].id)})).status_code == 403
    assert (await client.get("/api/v1/role-grants", params={"space_id": str(spaces[1].id), "user_id": str(uuid.uuid4())})).status_code == 409


async def test_template_reads_intersect_admin_key_and_global_editor_keeps_crud(settings_world):
    db, client, _, admin, spaces, templates, _, _, admin_cookie, _ = settings_world
    # This fixture reuses one SQLAlchemy identity map across requests. Give the
    # key its own actor so credential-local attributes cannot carry over to the
    # independent session-admin CRUD leg (real HTTP requests use fresh sessions).
    key_admin = User(name="Key admin", email=str(uuid.uuid4()) + "@test.invalid", instance_role="admin")
    db.add(key_admin); await db.flush()
    _, key = await auth.create_api_token(db, key_admin, TokenCreate(name="empty", scopes={}))
    # Avoid combining bearer and session identities in one request.
    client.cookies.clear()
    denied = await client.get("/api/v1/page-templates/directory", headers={"Authorization": "Bearer " + key})
    assert denied.status_code == 200 and denied.json() == []
    assert (await client.get(f"/api/v1/page-templates/{templates[0].id}", headers={"Authorization": "Bearer " + key})).status_code == 404
    client.cookies.set("radd_session", admin_cookie)
    created = await client.post("/api/v1/page-templates", json={"name": "Created " + str(uuid.uuid4()), "space_id": str(spaces[1].id), "body": "# {{title}}"})
    assert created.status_code == 201
    template_id = created.json()["id"]
    changed = await client.patch(f"/api/v1/page-templates/{template_id}", json={"space_id": None, "body": "{{author}}"})
    assert changed.status_code == 200 and changed.json()["space_id"] is None
    assert (await client.get(f"/api/v1/page-templates/{template_id}")).json()["body"] == "{{author}}"
    assert (await client.delete(f"/api/v1/page-templates/{template_id}")).status_code == 204
