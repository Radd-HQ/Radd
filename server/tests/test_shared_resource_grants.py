"""Real share consumers must honor grant expiry/effects, not just the inspector."""
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.clock import utcnow
from radd.config import settings
from radd.modules.access import service as grants
from radd.modules.access.types import GrantEffect, GrantSubject
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.types import SESSION_COOKIE_NAME
from radd.modules.dashboards import service as dashboards
from radd.modules.dashboards.schemas import DashboardCreate
from radd.modules.groups.models import Group, GroupMember, GroupParent
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams
from radd.modules.teams.schemas import TeamCreate
from radd.modules.views import service as views
from radd.modules.views.schemas import ViewCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.mark.parametrize("resource", ["view", "dashboard"])
@pytest.mark.parametrize("subject", [GrantSubject.USER, GrantSubject.TEAM, GrantSubject.GROUP])
async def test_share_expiry_and_denies_reach_http_consumers(db, monkeypatch, resource, subject):
    from radd.app import create_app
    from radd.db import get_session

    owner = User(email=f"share-owner-{uuid.uuid4()}@test.invalid", name="Owner", instance_role="admin")
    reader = User(email=f"share-reader-{uuid.uuid4()}@test.invalid", name="Reader", instance_role="member")
    db.add_all([owner, reader])
    await db.flush()
    project = await projects.create_project(db, ProjectCreate(key="SG"+uuid.uuid4().hex[:6], name="Share grants"), actor_id=owner.id)
    if resource == "view":
        created = await views.create_view(db, ViewCreate(name="Private", view_type="list", project_id=project.id), actor=owner)
    else:
        created = await dashboards.create_dashboard(db, DashboardCreate(name="Private"), actor=owner)
    team = await teams.create_team(db, TeamCreate(name=f"Share team {uuid.uuid4()}"))
    await teams.add_team_member(db, team.id, reader.id)
    parent = Group(dn=f"cn=parent-{uuid.uuid4()}", name="Parent")
    child = Group(dn=f"cn=child-{uuid.uuid4()}", name="Child")
    db.add_all([parent, child])
    await db.flush()
    db.add_all([GroupParent(parent_id=parent.id, child_id=child.id), GroupMember(group_id=child.id, user_id=reader.id)])
    await db.flush()
    subject_id = {GrantSubject.USER: reader.id, GrantSubject.TEAM: team.id, GrantSubject.GROUP: parent.id}[subject]
    now = utcnow()
    expires = now + timedelta(hours=1)
    temporary = await grants.add_grant(db, resource, str(created.id), subject_type=subject,
                                      subject_id=subject_id, access="owner", expires_at=expires)
    cookie = await auth.create_session(db, reader)
    app = create_app()
    async def session_override():
        yield db
    app.dependency_overrides[get_session] = session_override
    base = f"/api/v1/{resource}s"
    url = f"{base}/{created.id}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                cookies={SESSION_COOKIE_NAME: cookie}) as client:
        async def listed():
            response = await client.get(base)
            assert response.status_code == 200, response.text
            legacy = next((row for row in response.json() if row["id"] == str(created.id)), None)
            lean = await client.get(base, params={"include_shares": "false"})
            assert lean.status_code == 200, lean.text
            found = next((row for row in lean.json() if row["id"] == str(created.id)), None)
            assert found == (legacy | {"shares": []} if legacy else None)
            return legacy

        async def invisible():
            assert await listed() is None
            for method, suffix, body in [("PATCH", "", {"name": "Forbidden"}),
                                         ("DELETE", "", None),
                                         ("PUT", "/sharing", {"global_access": "viewer"})]:
                response = await client.request(method, url+suffix, json=body)
                assert response.status_code == 404, response.text
            response = await client.get("/api/v1/grants", params={"resource_type": resource, "resource_id": str(created.id)})
            assert response.status_code == 403, response.text
            if resource == "view":
                assert (await client.get(url)).status_code == 404
                response = await client.post(base+"/counts", json={"view_ids": [str(created.id)]})
                assert response.status_code == 200 and response.json() == {}
            else:
                assert (await client.get(url)).status_code == 404

        assert (await listed())["can_manage"]
        assert (await client.patch(url, json={"name": "Live grant works"})).status_code == 200
        # Expiry is immediate at the boundary; no sweeper or row deletion runs.
        monkeypatch.setattr(grants, "utcnow", lambda: expires)
        await invisible()
        assert await db.get(grants.AccessGrant, temporary.id) is temporary
        monkeypatch.setattr(grants, "utcnow", lambda: now)
        assert (await listed())["can_manage"]
        await grants.remove_grant(db, temporary.id)
        await grants.add_grant(db, resource, str(created.id), subject_type=subject,
                               subject_id=subject_id, access="owner", effect=GrantEffect.DENY)
        # A denial must never become a co-owner grant, including via nested groups.
        await invisible()
        viewer = await grants.add_grant(db, resource, str(created.id), subject_type=GrantSubject.USER,
                                       subject_id=reader.id, access="viewer")
        row = await listed()
        assert row and not row["can_manage"] and not row["can_edit"]
        assert (await client.patch(url, json={"name": "Forbidden"})).status_code == 403
        assert (await client.delete(url)).status_code == 403
        # A level denial applies to the public fallback too, while preserving
        # a different allowed level. Owners retain intrinsic ownership.
        await grants.add_grant(db, resource, str(created.id), subject_type=subject,
                               subject_id=subject_id, access="editor", effect=GrantEffect.DENY)
        if resource == "view":
            from radd.modules.views.schemas import ViewSharingUpdate
            updated = await views.update_sharing(db, created.id, ViewSharingUpdate(global_access="editor"), actor=owner)
        else:
            from radd.modules.dashboards.schemas import DashboardSharingUpdate
            updated = await dashboards.update_sharing(db, created.id, DashboardSharingUpdate(global_access="editor"), actor=owner)
        assert updated.can_manage
        assert [share.id for share in updated.shares] == [viewer.id]
        row = await listed()
        assert row and not row["can_edit"] and not row["can_manage"]
        await grants.remove_grant(db, viewer.id)
        await invisible()
        assert (await client.post("/api/v1/auth/logout")).status_code == 204
