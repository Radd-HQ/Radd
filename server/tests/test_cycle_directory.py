"""Cycle pages filter status and team visibility before taking a window."""
import uuid
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth import service as auth
from radd.modules.auth.models import User, Role, GlobalRoleGrant
from radd.modules.auth.types import SESSION_COOKIE_NAME
from radd.modules.cycles import directory, service
from radd.modules.cycles.models import Cycle, CycleTeam
from radd.modules.cycles.types import CycleStatus, cycle_status
from radd.modules.teams import service as teams
from radd.modules.teams.schemas import TeamCreate
from radd.modules.auth.types import LoginMethod

TODAY = date(2026, 9, 10)


@pytest.fixture
async def world(monkeypatch):
    # HTTP handlers must evaluate the fixed fixtures on their reference date,
    # including after midnight or when the suite runs months later.
    from importlib import import_module
    from radd.modules.projects.models import Project

    cycle_router = import_module("radd.modules.cycles.router")
    class FixtureDate(date):
        @classmethod
        def today(cls):
            return TODAY
    monkeypatch.setattr(cycle_router, "date", FixtureDate)
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        actor = User(email=f"cycle-dir-{uuid.uuid4()}@test.invalid", name="Reader", instance_role="member")
        admin = User(email=f"cycle-dir-admin-{uuid.uuid4()}@test.invalid", name="Admin", instance_role="admin")
        # Global item-read grants need an actual project to authorize reports;
        # do not depend on committed projects left by another test module.
        project = Project(key="CD" + uuid.uuid4().hex[:8].upper(), name="Cycle report scope")
        db.add_all([actor, admin, project])
        await db.flush()
        mine = await teams.create_team(db, TeamCreate(name=f"Mine {uuid.uuid4()}"))
        other = await teams.create_team(db, TeamCreate(name=f"Other {uuid.uuid4()}"))
        await teams.add_team_member(db, mine.id, actor.id)
        prefix = f"Window {uuid.uuid4().hex[:8]}"
        rows = []
        dates = [(None, None, None), (TODAY, TODAY, None),
                 (TODAY + timedelta(days=1), TODAY + timedelta(days=2), None),
                 (TODAY - timedelta(days=2), TODAY - timedelta(days=1), None),
                 (None, TODAY, None), (TODAY, None, datetime(2026, 1, 1))]
        for i in range(125):
            start, end, completed = dates[i % len(dates)]
            row = Cycle(name=f"{prefix} {i:03}", start_date=start, end_date=end, completed_at=completed)
            db.add(row)
            await db.flush()
            if i % 3:
                db.add(CycleTeam(cycle_id=row.id, team_id=mine.id if i % 3 == 1 else other.id))
            rows.append(row)
        await db.flush()
        yield db, actor, admin, rows, prefix
        await db.rollback()
    await engine.dispose()


async def test_status_and_visibility_apply_before_page_and_counts(world):
    db, actor, admin, rows, prefix = world
    expected = {row.id for i, row in enumerate(rows) if i % 3 != 2}
    seen = []
    for offset in range(0, len(expected), 20):
        page, teams_by_id, total = await directory.page(db, actor, q=prefix, limit=20, offset=offset, today=TODAY)
        assert total == len(expected) and len(page) <= 20
        assert set(teams_by_id) <= {row.id for row in page}
        seen.extend(row.id for row in page)
    assert len(seen) == len(set(seen)) and set(seen) == expected
    counts = await directory.counts(db, actor, q=prefix, today=TODAY)
    for status in CycleStatus:
        expected_status = {row.id for row in rows if row.id in expected and
            cycle_status(row.start_date, row.end_date, TODAY, row.completed_at) == status}
        page, _, total = await directory.page(db, actor, q=prefix, status=status, today=TODAY)
        assert {row.id for row in page} == expected_status
        assert total == counts.get(status, 0) == len(expected_status)
    page, _, total = await directory.page(db, admin, q=prefix, today=TODAY, limit=200)
    assert len(page) == total == 125
    page, _, total = await directory.page(db, actor, q="%_", limit=20, today=TODAY)
    assert page == [] and total == 0


async def test_http_bounds_and_hidden_cycle_writes(world):
    from radd.app import create_app
    db, actor, admin, rows, prefix = world
    role = Role(key=f"cycle-dir-{uuid.uuid4().hex[:8]}", name="Cycle editor", permissions=["cycle.read", "cycle.update", "cycle.delete"])
    db.add(role)
    await db.flush()
    db.add(GlobalRoleGrant(user_id=actor.id, role_id=role.id))
    cookie = await auth.create_session(db, actor, method=LoginMethod.PASSWORD)
    from radd.db import get_session
    async def session_override():
        yield db
    app = create_app()
    app.dependency_overrides[get_session] = session_override
    hidden = rows[2]
    visible = rows[1]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                cookies={SESSION_COOKIE_NAME: cookie}) as client:
        response = await client.get("/api/v1/cycles", params={"q": prefix, "limit": 50})
        assert response.status_code == 200 and len(response.json()) == 50
        assert int(response.headers["X-Total-Count"]) == 84
        summary = await client.get("/api/v1/cycles/summary", params={"q": prefix})
        assert summary.status_code == 200 and sum(summary.json().values()) == 84
        dated = await client.get("/api/v1/cycles", params={"q": prefix, "dated_only": True, "limit": 200})
        expected_dated = {str(row.id) for i, row in enumerate(rows)
                          if i % 3 != 2 and row.start_date is not None and row.end_date is not None}
        assert {row["id"] for row in dated.json()} == expected_dated
        assert int(dated.headers["X-Total-Count"]) == len(expected_dated)
        for params in ({"limit": 201}, {"limit": 0}, {"offset": -1}):
            assert (await client.get("/api/v1/cycles", params=params)).status_code == 422
        for method, suffix, body in [("GET", "", None), ("PATCH", "", {"goal": "should not change"}),
                                      ("DELETE", "", None), ("POST", "/complete", {"move_open_to": None})]:
            response = await client.request(method, f"/api/v1/cycles/{hidden.id}{suffix}", json=body)
            assert response.status_code == 404, response.text
        response = await client.post(f"/api/v1/cycles/{visible.id}/complete", json={"move_open_to": str(hidden.id)})
        assert response.status_code == 404
        assert (await client.get(f"/api/v1/cycles/{visible.id}")).json()["completed_at"] is None
        await client.post("/api/v1/auth/logout")


async def test_dated_default_and_search_are_chosen_before_limit(world):
    db, actor, admin, rows, prefix = world
    # An active cycle beats a later upcoming cycle; without any active ones the
    # most recent scheduled start wins. Neither undated nor hidden rows count.
    chosen, _, total = await directory.page(db, actor, q=prefix, dated_only=True,
        recent_first=True, limit=1, today=TODAY)
    assert total > 1 and len(chosen) == 1
    assert cycle_status(chosen[0].start_date, chosen[0].end_date, TODAY, chosen[0].completed_at) == CycleStatus.ACTIVE
    future = Cycle(name=f"{prefix} latest", start_date=TODAY + timedelta(days=40), end_date=TODAY + timedelta(days=50))
    hidden = Cycle(name=f"{prefix} private active", start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=1))
    db.add_all([future, hidden])
    await db.flush()
    db.add(CycleTeam(cycle_id=hidden.id, team_id=(await service.team_ids_by_cycle(db, [rows[2].id]))[rows[2].id][0]))
    # Move the date beyond the fixtures' active dates; the newly-created future
    # cycle is the latest visible candidate, while the private active stays out.
    chosen, _, _ = await directory.page(db, actor, q=prefix, dated_only=True,
        recent_first=True, limit=1, today=TODAY + timedelta(days=1))
    assert chosen[0].id == future.id


async def test_velocity_accepts_explicitly_completed_cycles_without_dates(world):
    from radd.modules.reporting import service as reporting
    db, actor, admin, rows, prefix = world
    report = await reporting.velocity(db, last=200, actor=admin)
    # Explicitly closing a draft is supported; it must not crash the report's
    # date ordering or disappear simply because its planned dates are absent.
    closed_drafts = {row.id for row in rows if row.completed_at is not None}
    assert closed_drafts <= {row.cycle.id for row in report.rows}


async def test_cycle_reports_do_not_disclose_hidden_cycles(world):
    from radd.app import create_app
    from radd.db import get_session
    db, actor, admin, rows, prefix = world
    role = Role(key=f"report-dir-{uuid.uuid4().hex[:8]}", name="Cycle reports", permissions=["cycle.read", "item.read"])
    db.add(role)
    await db.flush()
    db.add(GlobalRoleGrant(user_id=actor.id, role_id=role.id))
    cookie = await auth.create_session(db, actor, method=LoginMethod.PASSWORD)
    async def session_override():
        yield db
    app = create_app()
    app.dependency_overrides[get_session] = session_override
    hidden_ids = {str(row.id) for i, row in enumerate(rows) if i % 3 == 2}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                cookies={SESSION_COOKIE_NAME: cookie}) as client:
        report = await client.get("/api/v1/reports/velocity", params={"last": 50})
        assert report.status_code == 200, report.text
        actual = {row["cycle"]["id"] for row in report.json()["rows"]}
        assert str(rows[3].id) in actual
        assert not actual & hidden_ids
        # Visibility must precede even the draft-date validation (otherwise a
        # hidden draft answers 409 while a missing cycle answers 404).
        hidden = await client.get("/api/v1/reports/burnup", params={"cycle_id": str(rows[5].id)})
        assert hidden.status_code == 404, hidden.text
        visible = await client.get("/api/v1/reports/burnup", params={"cycle_id": str(rows[3].id)})
        assert visible.status_code == 200, visible.text
        recent = await service.recent_completed_cycles(db, actor=actor, limit=2, today=TODAY)
        assert len(recent) == 2 and all(str(row.id) not in hidden_ids for row in recent)
        await client.post("/api/v1/auth/logout")
