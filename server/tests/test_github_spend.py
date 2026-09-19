"""RADD-1261: the `/spend` comment convention on GitHub pull requests.

GitHub has no time tracking, so a PR comment carries the entry. Pure parsing
first; then the receiver end to end over an ASGI transport: a created comment
logs, an edited one updates the same rows, a deleted one removes them, and a
push's commit-author emails fill the identity map so the next comment by that
login resolves. The seam's invariants live in test_time_mirror.py.
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
from radd.modules.github import service, spend
from radd.modules.github.router import router as github_router
from radd.modules.github.schemas import ConnectionCreate, RepoCreate
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging import categories, enablement
from radd.modules.timelogging.models import Worklog
from radd.modules.vcs import timemirror
from radd.modules.vcs.models import VcsPendingWorklog
from radd.modules.vcs.types import VcsProvider

SECRET = "gh-secret"


# --- pure ---


def test_parse_spend_lines():
    commands = spend.parse_spend(
        "Looks good.\n/spend 1h30\n/spend 45m 2026-09-18\n/SPEND 2h 2026-09-18 pairing on the migration\n/spend 1h RADD-412 review\nnot /spend 5m inline"
    )
    assert [(c.position, c.duration_text, c.spent_on, c.key_override, c.note) for c in commands] == [
        (0, "1h30", None, None, ""),
        (1, "45m", date(2026, 9, 18), None, ""),
        (2, "2h", date(2026, 9, 18), None, "pairing on the migration"),
        (3, "1h", None, "RADD-412", "review"),
    ]
    assert spend.parse_spend("nothing here") == []
    assert spend.is_unspend("/unspend") and spend.is_unspend("thanks\n/unspend\n") and not spend.is_unspend("/unspend now")
    assert spend.comment_entry_id("Radd-HQ/Radd", 99, 1) == "comment:radd-hq/radd:99:1"
    assert spend.comment_prefix("radd-hq/radd", 99) == "comment:radd-hq/radd:99:"


# --- live ---


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
    admin = User(email=f"gh-admin-{suffix}@example.com", name="GH Admin", instance_role=InstanceRole.ADMIN.value)
    db.add(admin)
    await db.flush()
    project = await projects_service.create_project(db, ProjectCreate(key=f"GH{suffix[:4].upper()}", name="GitHub spend"))
    await enablement.set_enabled(db, project.id, True, actor_id=admin.id)
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), actor=admin)
    await categories.ensure_default_categories(db)
    connection = await service.create_connection(db, ConnectionCreate(name=f"gh-{suffix}", webhook_secret=SECRET))
    repo = await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="acme/widgets"))
    return {"admin": admin, "project": project, "item": item, "key": f"{project.key}-{item.number}", "connection": connection, "repo": repo}


def _app(db) -> FastAPI:
    app = FastAPI()
    app.include_router(github_router)

    async def _session():
        yield db

    app.dependency_overrides[get_session] = _session

    @app.exception_handler(ForbiddenError)
    async def _forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return app


async def _deliver(db, event: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db)), base_url="http://test") as client:
        response = await client.post("/integrations/github", content=body, headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": event, "Content-Type": "application/json"})
    assert response.status_code == 200, response.text
    return response.json()


def _comment(action: str, comment_id: int, body: str, *, number: int, title: str, login: str) -> dict:
    return {
        "action": action,
        "repository": {"full_name": "acme/widgets", "html_url": "https://github.com/acme/widgets"},
        "issue": {"number": number, "title": title, "body": "", "pull_request": {"url": "https://api.github.com/repos/acme/widgets/pulls/%d" % number}},
        "comment": {"id": comment_id, "body": body, "created_at": "2026-09-19T10:00:00Z", "user": {"login": login}},
        "sender": {"login": login},
    }


async def _worklogs(db, item_id):
    return list((await db.execute(select(Worklog).where(Worklog.item_id == item_id).order_by(Worklog.external_id))).scalars())


async def test_comment_created_edited_deleted(db, world):
    admin = world["admin"]
    key = world["key"]
    # The login is known: map it by hand (GitHub hides emails).
    await timemirror.set_user_link(db, provider=VcsProvider.GITHUB, connection_id=world["connection"].id, username="octo", user_id=admin.id, actor_id=admin.id)

    created = await _deliver(db, "issue_comment", _comment("created", 501, "/spend 1h30\n/spend 45m 2026-09-18 pairing", number=5, title=f"{key} the PR", login="octo"))
    assert created["worklogs"]["created"] == 2
    rows = await _worklogs(db, world["item"].id)
    assert [(r.external_id, r.time_spent_seconds, r.worked_on, r.note) for r in rows] == [
        ("comment:acme/widgets:501:0", 5400, date(2026, 9, 19), "Logged on #5 the PR" if False else rows[0].note),
        ("comment:acme/widgets:501:1", 2700, date(2026, 9, 18), "pairing"),
    ]
    assert rows[0].note.startswith("Logged on #5")
    assert all(r.author_id == admin.id and r.external_scope == "pr:acme/widgets:5" for r in rows)

    # Edited: one line removed, the other changed → same row id, updated; the second gone.
    edited = await _deliver(db, "issue_comment", _comment("edited", 501, "/spend 2h", number=5, title=f"{key} the PR", login="octo"))
    assert (edited["worklogs"]["updated"], edited["worklogs"]["deleted"]) == (1, 1)
    rows = await _worklogs(db, world["item"].id)
    assert [(r.external_id, r.time_spent_seconds) for r in rows] == [("comment:acme/widgets:501:0", 7200)]

    # A second comment on the same PR must not disturb the first one's rows.
    await _deliver(db, "issue_comment", _comment("created", 502, "/spend 10m", number=5, title=f"{key} the PR", login="octo"))
    assert len(await _worklogs(db, world["item"].id)) == 2

    # Deleted: only that comment's rows go.
    deleted = await _deliver(db, "issue_comment", _comment("deleted", 502, "/spend 10m", number=5, title=f"{key} the PR", login="octo"))
    assert deleted["worklogs"]["deleted"] == 1
    assert [r.external_id for r in await _worklogs(db, world["item"].id)] == ["comment:acme/widgets:501:0"]


async def test_key_override_and_unknown_login_parks(db, world):
    admin = world["admin"]
    key = world["key"]
    other = await items_service.create_item(db, ItemCreate(project_id=world["project"].id, title="other"), actor=admin)
    other_key = f"{world['project'].key}-{other.number}"
    await timemirror.set_user_link(db, provider=VcsProvider.GITHUB, connection_id=world["connection"].id, username="octo", user_id=admin.id, actor_id=admin.id)
    await _deliver(db, "issue_comment", _comment("created", 601, f"/spend 1h {other_key} review", number=6, title=f"{key} the PR", login="octo"))
    assert [r.item_id for r in await _worklogs(db, other.id)] == [other.id]
    assert await _worklogs(db, world["item"].id) == []
    # An unmapped login parks the entry — nothing is guessed.
    result = await _deliver(db, "issue_comment", _comment("created", 602, "/spend 30m", number=6, title=f"{key} the PR", login="stranger"))
    assert result["worklogs"]["pending"] == 1
    parked = await db.scalar(select(VcsPendingWorklog).where(VcsPendingWorklog.external_id == "comment:acme/widgets:602:0"))
    assert parked is not None and parked.external_username == "stranger"


async def test_push_commit_author_email_fills_the_identity_map(db, world):
    """GitHub hides emails on comments, but a push carries commits[].author.email
    + .username — a match records the mapping so later comments resolve."""
    admin = world["admin"]
    key = world["key"]
    push = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "acme/widgets", "html_url": "https://github.com/acme/widgets"},
        "commits": [{"id": "c" * 40, "message": f"[{key}] work", "url": "", "author": {"name": "GH Admin", "email": admin.email, "username": "octo"}}],
    }
    await _deliver(db, "push", push)
    links = await timemirror.list_user_links(db, provider=VcsProvider.GITHUB, connection_id=world["connection"].id)
    assert [(link.external_username, link.user_id, link.matched_by) for link in links] == [("octo", admin.id, "email")]
    result = await _deliver(db, "issue_comment", _comment("created", 701, "/spend 15m", number=7, title=f"{key} the PR", login="octo"))
    assert result["worklogs"]["created"] == 1


async def test_unspend_removes_the_authors_entries_on_the_pr(db, world):
    admin = world["admin"]
    key = world["key"]
    await timemirror.set_user_link(db, provider=VcsProvider.GITHUB, connection_id=world["connection"].id, username="octo", user_id=admin.id, actor_id=admin.id)
    await _deliver(db, "issue_comment", _comment("created", 801, "/spend 1h", number=8, title=f"{key} the PR", login="octo"))
    await _deliver(db, "issue_comment", _comment("created", 802, "/spend 2h", number=8, title=f"{key} the PR", login="octo"))
    assert len(await _worklogs(db, world["item"].id)) == 2
    result = await _deliver(db, "issue_comment", _comment("created", 803, "/unspend", number=8, title=f"{key} the PR", login="octo"))
    assert result["worklogs"]["deleted"] == 2
    assert await _worklogs(db, world["item"].id) == []


async def test_non_pr_comments_and_invalid_durations_are_ignored(db, world):
    key = world["key"]
    payload = _comment("created", 901, "/spend 1h", number=9, title=f"{key} an issue", login="octo")
    del payload["issue"]["pull_request"]  # a plain issue comment, not a PR
    result = await _deliver(db, "issue_comment", payload)
    assert "worklogs" not in result or result["worklogs"].get("created", 0) == 0
    bad = await _deliver(db, "issue_comment", _comment("created", 902, "/spend soon", number=9, title=f"{key} the PR", login="octo"))
    assert bad["worklogs"].get("invalid") == 1
