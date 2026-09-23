"""Directory SQL must match live sharing policy before search/count/paging."""
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.clock import utcnow
from radd.config import settings
from radd.modules.access import service as access
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.types import SESSION_COOKIE_NAME
from radd.modules.dashboards import service as dashboards
from radd.modules.dashboards.models import Dashboard
from radd.modules.groups.models import Group, GroupMember, GroupParent
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams
from radd.modules.teams.schemas import TeamCreate
from radd.modules.views import service as views
from radd.modules.views.models import View
from radd.modules.auth.types import LoginMethod


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.mark.parametrize("resource", ["view", "dashboard"])
async def test_visibility_precedes_directory_window(db, resource, monkeypatch):
    from radd.app import create_app
    from radd.db import get_session
    owner = User(email=f"dir-owner-{uuid.uuid4()}@test.invalid", name="Owner", instance_role="admin")
    reader = User(email=f"dir-reader-{uuid.uuid4()}@test.invalid", name="Reader", instance_role="member")
    db.add_all([owner, reader])
    await db.flush()
    project = await projects.create_project(db, ProjectCreate(key="SD"+uuid.uuid4().hex[:6], name="Directory scope"))
    team = await teams.create_team(db, TeamCreate(name=f"Directory team {uuid.uuid4()}"))
    await teams.add_team_member(db, team.id, reader.id)
    parent = Group(dn=f"cn=parent-{uuid.uuid4()}", name="Parent")
    child = Group(dn=f"cn=child-{uuid.uuid4()}", name="Child")
    db.add_all([parent, child])
    await db.flush()
    db.add_all([GroupParent(parent_id=parent.id, child_id=child.id), GroupMember(group_id=child.id, user_id=reader.id)])
    prefix = f"Directory {uuid.uuid4().hex[:8]}"
    rows = []
    grants_by_id = {}
    now = utcnow()
    for i in range(180):
        mode = i % 10
        values = {"name": f"{prefix} {i:03}", "owner_id": reader.id if mode == 0 else owner.id,
                  "global_access": "viewer" if mode in (1, 7) else "editor" if mode == 9 else None}
        row = (View(**values, view_type="queue" if i % 3 == 0 else "list", query="",
                    project_id=None if i % 2 else project.id) if resource == "view" else Dashboard(**values))
        db.add(row)
        await db.flush()
        def grant(subject_type, subject_id, level, *, effect="allow", expires_at=None):
            result = access.AccessGrant(resource_type=resource, resource_id=str(row.id),
                subject_type=subject_type, subject_id=subject_id, access=level,
                effect=effect, expires_at=expires_at)
            db.add(result)
            return result
        grants = []
        if mode == 2:
            grants.append(grant("user", reader.id, "viewer"))
        elif mode == 3:
            grants.append(grant("team", team.id, "editor"))
        elif mode == 4:
            grants.append(grant("group", parent.id, "viewer", expires_at=now+timedelta(days=1)))
        elif mode == 5:
            grants.append(grant("user", reader.id, "owner", expires_at=now-timedelta(days=1)))
        elif mode == 6:
            grants.append(grant("user", reader.id, "owner", effect="deny"))
        elif mode == 7:
            grants.append(grant("user", reader.id, "viewer", effect="deny"))
        elif mode == 8:
            grants.extend([grant("team", team.id, "owner"), grant("user", reader.id, "owner", effect="deny"),
                           grant("group", parent.id, "viewer")])
        elif mode == 9:
            grants.append(grant("user", reader.id, "editor", effect="deny", expires_at=now-timedelta(days=1)))
        rows.append(row)
        grants_by_id[row.id] = [g for g in grants if g.expires_at is None or g.expires_at > now]
    await db.flush()
    service = views if resource == "view" else dashboards
    expected = [r for r in rows if r.owner_id == reader.id or service._grant_level(
        r, grants_by_id[r.id], reader.id, {team.id}, {parent.id, child.id}) is not None]
    assert len(expected) == 126
    hydrated = []
    original_hydrate = service._hydrate
    async def capture(session, actor, candidates, **options):
        hydrated.append(len(candidates))
        return await original_hydrate(session, actor, candidates, **options)
    monkeypatch.setattr(service, "_hydrate", capture)
    cookie = await auth.create_session(db, reader, method=LoginMethod.PASSWORD)
    app = create_app()
    async def override():
        yield db
    app.dependency_overrides[get_session] = override
    base = f"/api/v1/{resource}s"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                cookies={SESSION_COOKIE_NAME: cookie}) as client:
        seen = []
        for offset in (0, 50, 100):
            response = await client.get(base, params={"q": prefix, "limit": 50, "offset": offset})
            assert response.status_code == 200, response.text
            assert int(response.headers["X-Total-Count"]) == 126
            seen.extend(row["id"] for row in response.json())
        assert seen == [str(row.id) for row in expected]
        assert max(hydrated) == 50
        assert (await client.get(base+"/summary", params={"q": prefix})).json() == {"total": 126}
        assert (await client.get(base, params={"q": prefix+" %_", "limit": 50})).json() == []
        response = await client.get(base, params={"q": expected[-1].name, "limit": 1})
        assert response.headers["X-Total-Count"] == "1" and response.json()[0]["id"] == str(expected[-1].id)
        assert (await client.get(base+f"/{expected[-1].id}")).json()["id"] == str(expected[-1].id)
        hidden = next(row for row in rows if row not in expected)
        assert (await client.get(base+f"/{hidden.id}")).status_code == 404
        for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
            assert (await client.get(base, params=params)).status_code == 422
        if resource == "view":
            for filters, matching in [
                ({"project_id": str(project.id)}, expected),
                ({"project_id": str(project.id), "include_global": False}, [r for r in expected if r.project_id == project.id]),
                ({"global_only": True, "exclude_type": "queue"}, [r for r in expected if r.project_id is None and r.view_type != "queue"]),
                ({"view_type": "queue"}, [r for r in expected if r.view_type == "queue"]),
            ]:
                response = await client.get(base, params={"q": prefix, "limit": 200, **filters})
                assert response.headers["X-Total-Count"] == str(len(matching))
                assert [r["id"] for r in response.json()] == [str(r.id) for r in matching]
                assert (await client.get(base+"/summary", params={"q": prefix, **filters})).json() == {"total": len(matching)}
        await client.post("/api/v1/auth/logout")
