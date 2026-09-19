"""RADD-1260: tracked time on a Forgejo pull request mirrored into the linked issue.

The Forgejo REST API is stood in for by an httpx.MockTransport carrying Gitea's
`TrackedTime` shape (`{id, created, time, user_id, user_name}`) and the
`/users/{username}` profile. Reconcile runs on every pull_request delivery and
in the backfill; the seam's invariants live in test_time_mirror.py.
"""

import hashlib
import hmac
import json
import uuid
from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.forgejo import backfill, service, timelogs
from radd.modules.forgejo.router import router as forgejo_router
from radd.modules.forgejo.schemas import ConnectionCreate, RepoCreate
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging import categories, enablement
from radd.modules.timelogging.models import Worklog


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def world(db):
    suffix = uuid.uuid4().hex[:6]
    admin = User(email=f"fj-admin-{suffix}@example.com", name="FJ Admin", instance_role=InstanceRole.ADMIN.value)
    db.add(admin)
    await db.flush()
    project = await projects_service.create_project(db, ProjectCreate(key=f"FT{suffix[:4].upper()}", name="Forgejo time"))
    await enablement.set_enabled(db, project.id, True, actor_id=admin.id)
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), actor=admin)
    await categories.ensure_default_categories(db)
    connection = await service.create_connection(
        db, ConnectionCreate(name=f"fj-{suffix}", base_url="https://git.example.com", api_token="tok", webhook_secret="s")
    )
    repo = await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="acme/widgets"))
    return {"admin": admin, "project": project, "item": item, "key": f"{project.key}-{item.number}", "connection": connection, "repo": repo}


def _times(rows, *, admin_email):
    """MockTransport: `/issues/{n}/times` answers `rows`; `/users/dev` has the admin's email, nobody else has one."""
    calls = {"times": 0, "users": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/times"):
            calls["times"] += 1
            return httpx.Response(200, json=rows if int(request.url.params.get("page", "1")) == 1 else [])
        if "/api/v1/users/" in path:
            username = path.rsplit("/", 1)[-1]
            calls["users"].append(username)
            return httpx.Response(200, json={"login": username, "email": admin_email if username == "dev" else ""})
        if path.endswith("/repository/branches") or path.endswith("/branches"):
            return httpx.Response(200, json=[])
        if path.endswith("/pulls"):
            return httpx.Response(200, json=[{"number": 7, "title": "PR", "body": "", "state": "open", "merged": False, "head": {"ref": "x"}, "html_url": "https://git.example.com/acme/widgets/pulls/7"}])
        if path.endswith("/commits"):
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    return handler, calls


async def _worklogs(db, item_id):
    return list((await db.execute(select(Worklog).where(Worklog.item_id == item_id).order_by(Worklog.external_id))).scalars())


async def test_reconcile_mirrors_tracked_times_and_parks_unknown_authors(db, world):
    admin = world["admin"]
    handler, calls = _times(
        [
            {"id": 11, "created": "2026-09-18T09:30:00Z", "time": 2700, "user_id": 1, "user_name": "dev"},
            {"id": 12, "created": "2026-09-19T10:00:00Z", "time": 600, "user_id": 2, "user_name": "ghost"},
            {"id": 13, "created": "2026-09-19T10:00:00Z", "time": 0, "user_id": 1, "user_name": "dev"},
        ],
        admin_email=admin.email,
    )
    report = await timelogs.reconcile_pull_request(
        db, world["connection"], world["repo"],
        full_name="acme/widgets", index=7, title=f"{world['key']} fix", head_branch="fix", body="",
        transport=httpx.MockTransport(handler),
    )
    assert (report.created, report.pending, report.unmatched_authors) == (1, 1, {"ghost"})
    assert sorted(calls["users"]) == ["dev", "ghost"]
    rows = await _worklogs(db, world["item"].id)
    assert len(rows) == 1 and rows[0].external_id == "11" and rows[0].time_spent_seconds == 2700
    assert rows[0].worked_on == date(2026, 9, 18) and rows[0].external_scope == "pr:acme/widgets:7"
    assert rows[0].author_id == admin.id and "dated by when it was added" in rows[0].note


async def test_deleted_tracked_time_leaves_on_the_next_reconcile(db, world):
    admin = world["admin"]
    first, _ = _times([{"id": 21, "created": "2026-09-18T09:30:00Z", "time": 60, "user_id": 1, "user_name": "dev"}], admin_email=admin.email)
    await timelogs.reconcile_pull_request(db, world["connection"], world["repo"], full_name="acme/widgets", index=8, title=f"{world['key']}", head_branch="", body="", transport=httpx.MockTransport(first))
    assert len(await _worklogs(db, world["item"].id)) == 1
    empty, _ = _times([], admin_email=admin.email)
    report = await timelogs.reconcile_pull_request(db, world["connection"], world["repo"], full_name="acme/widgets", index=8, title=f"{world['key']}", head_branch="", body="", transport=httpx.MockTransport(empty))
    assert report.deleted == 1 and await _worklogs(db, world["item"].id) == []


def _app(db) -> FastAPI:
    app = FastAPI()
    app.include_router(forgejo_router)

    async def _session():
        yield db

    app.dependency_overrides[get_session] = _session

    @app.exception_handler(ForbiddenError)
    async def _forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return app


async def test_pull_request_delivery_triggers_the_reconcile(db, world, monkeypatch):
    """No tracked-time webhook exists, so EVERY pull_request delivery reconciles."""
    admin = world["admin"]
    handler, calls = _times([{"id": 31, "created": "2026-09-18T09:30:00Z", "time": 1800, "user_id": 1, "user_name": "dev"}], admin_email=admin.email)
    monkeypatch.setattr(timelogs, "_TRANSPORT_FOR_TESTS", httpx.MockTransport(handler), raising=False)
    payload = {
        "action": "opened",
        "repository": {"full_name": "acme/widgets", "html_url": "https://git.example.com/acme/widgets"},
        "pull_request": {"number": 9, "title": f"{world['key']} timed", "body": "", "state": "open", "merged": False,
                         "head": {"ref": "feature"}, "html_url": "https://git.example.com/acme/widgets/pulls/9"},
    }
    body = json.dumps(payload).encode()
    signature = hmac.new(b"s", body, hashlib.sha256).hexdigest()
    transport = httpx.ASGITransport(app=_app(db))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/integrations/forgejo", content=body, headers={"X-Forgejo-Signature": signature, "X-Forgejo-Event": "pull_request", "Content-Type": "application/json"})
    assert response.status_code == 200
    result = response.json()
    assert result["linked"] == 1 and result["worklogs"]["created"] == 1
    assert calls["times"] == 1
    rows = await _worklogs(db, world["item"].id)
    assert [r.external_scope for r in rows] == ["pr:acme/widgets:9"]


async def test_backfill_reconciles_each_pull_request_once(db, world):
    admin = world["admin"]
    handler, calls = _times([{"id": 41, "created": "2026-09-01T09:00:00Z", "time": 3600, "user_id": 1, "user_name": "dev"}], admin_email=admin.email)
    # the /pulls stub names no key in its title — give it one
    def keyed(request):
        r = handler(request)
        if request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=[{"number": 7, "title": f"{world['key']} PR", "body": "", "state": "open", "merged": False, "head": {"ref": "x"}, "html_url": "u"}])
        return r
    transport = httpx.MockTransport(keyed)
    first = await backfill.run(db, world["connection"], world["repo"], transport=transport)
    second = await backfill.run(db, world["connection"], world["repo"], transport=transport)
    assert first.pull_requests == 1 and first.worklogs.get("created") == 1
    assert second.worklogs.get("created", 0) == 0 and second.worklogs.get("unchanged") == 1
    assert len(await _worklogs(db, world["item"].id)) == 1
