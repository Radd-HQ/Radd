"""Cycle catalog permission never grants access to its private issue totals."""
import uuid
from datetime import date

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth import service as auth
from radd.modules.auth.models import User, Role, GlobalRoleGrant
from radd.modules.auth.types import SESSION_COOKIE_NAME
from radd.modules.cycles import service as cycles
from radd.modules.cycles.schemas import CycleCreate
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging.models import ItemEstimate, Worklog
from radd.modules.auth.types import LoginMethod


async def test_http_totals_use_item_project_and_relation_visibility():
    from radd.app import create_app

    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        admin = User(email=f"stats-admin-{uuid.uuid4()}@test.invalid", name="Admin", instance_role="admin")
        reader = User(email=f"stats-reader-{uuid.uuid4()}@test.invalid", name="Reader", instance_role="member")
        own = Role(key=f"stats-own-{uuid.uuid4().hex[:8]}", name="Own cycle stats", permissions=["cycle.read", "item.read@own"])
        full = Role(key=f"stats-read-{uuid.uuid4().hex[:8]}", name="Read project", permissions=["item.read"])
        db.add_all([admin, reader, own, full])
        await db.flush()
        project_a = await projects.create_project(db, ProjectCreate(key=f"SA{uuid.uuid4().hex[:6]}", name="Granted"))
        project_b = await projects.create_project(db, ProjectCreate(key=f"SB{uuid.uuid4().hex[:6]}", name="Related only"))
        db.add_all([GlobalRoleGrant(user_id=reader.id, role_id=own.id),
                    GlobalRoleGrant(user_id=reader.id, role_id=full.id, project_id=project_a.id)])
        cycle = await cycles.create_cycle(db, CycleCreate(name="Stats permission probe"), date.today())
        for i, (project, points, estimate, logged) in enumerate([
            (project_a, 1, 1000, 100), (project_a, 2, 2000, 300),
            (project_b, 3, None, 500), (project_b, 900, 90000, 6000),
        ]):
            item = await items.create_item(db, ItemCreate(project_id=project.id, title=f"Stats item {i}",
                cycle_id=cycle.id, estimate_points=points), admin)
            row = await db.get(WorkItem, item.id)
            row.reporter_id = reader.id if i == 2 else admin.id
            if estimate is not None:
                db.add(ItemEstimate(item_id=item.id, original_estimate_seconds=estimate))
            db.add(Worklog(item_id=item.id, author_id=admin.id, worked_on=date.today(),
                          time_spent_seconds=logged, note="Aggregate test"))
        cookie = await auth.create_session(db, reader, method=LoginMethod.PASSWORD)
        from radd.db import get_session
        async def session_override():
            yield db
        app = create_app()
        app.dependency_overrides[get_session] = session_override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                    cookies={SESSION_COOKIE_NAME: cookie}) as client:
            path = f"/api/v1/cycles/{cycle.id}/stats"
            response = await client.get(path)
            assert response.status_code == 200, response.text
            stats = response.json()
            assert stats["total"] == 3 and sum(stats["by_category"].values()) == 3
            assert stats["points_total"] == 6
            assert (stats["estimate_seconds"], stats["logged_seconds"], stats["remaining_seconds"]) == (3000, 900, 2600)
            scoped = await client.get(path, params={"project_id": str(project_b.id)})
            assert scoped.status_code == 200 and scoped.json()["total"] == 1
            assert scoped.json()["points_total"] == 3 and scoped.json()["logged_seconds"] == 500
            filtered = await client.get(path, params={"q": f"project = {project_b.key}"})
            assert filtered.status_code == 200 and filtered.json()["total"] == 1
            assert filtered.json()["points_total"] == 3
            await client.post("/api/v1/auth/logout")
    await engine.dispose()
