"""RADD-1296 — tick a checklist box without editing the text.

The rewriter changes ONE marker and refuses rather than guesses; the three
endpoints (description, comment, page) reuse each surface's own write path,
and check permission before comparing bodies so a 409 leaks nothing.
"""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd import tasklists
from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import SESSION_COOKIE_NAME, LoginMethod
from radd.tasklists import TaskToggle, TaskToggleConflict

BODY = "\n".join([
    "Intro",
    "- [ ] first",
    "- [x] second",
    "  - [ ] nested",
    "```",
    "- [ ] inside a fence is code, not a task",
    "```",
    "> - [ ] quoted",
    "1. [X] ordered",
    "- [] not a task",
])


def test_markers_follow_gfm_and_skip_code():
    assert tasklists.task_states(BODY) == [False, True, False, False, True]


def test_toggle_changes_exactly_one_marker():
    out = tasklists.toggle(BODY, TaskToggle(index=3, checked=True, expected_body=BODY))
    assert out == BODY.replace("> - [ ] quoted", "> - [x] quoted")
    back = tasklists.toggle(out, TaskToggle(index=4, checked=False, expected_body=out))
    assert back.splitlines()[8] == "1. [ ] ordered"


def test_crlf_bodies_keep_their_line_endings():
    body = "- [ ] a\r\n- [ ] b\r\n"
    out = tasklists.toggle(body, TaskToggle(index=1, checked=True, expected_body=body))
    assert out == "- [ ] a\r\n- [x] b\r\n"


@pytest.mark.parametrize(
    "request_",
    [
        TaskToggle(index=0, checked=True, expected_body=BODY + " edited"),  # stale body
        TaskToggle(index=1, checked=True, expected_body=BODY),  # already checked
        TaskToggle(index=9, checked=True, expected_body=BODY),  # no such box
    ],
)
def test_refuses_rather_than_guesses(request_):
    with pytest.raises(TaskToggleConflict):
        tasklists.toggle(BODY, request_)


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        admin = User(email=f"tt-{uuid.uuid4().hex[:8]}@example.com", name="Admin", instance_role="admin")
        stranger = User(email=f"tt-{uuid.uuid4().hex[:8]}@example.com", name="Stranger", instance_role="member")
        db.add_all([admin, stranger])
        await db.flush()
        app = create_app()

        async def override():
            yield db

        app.dependency_overrides[get_session] = override
        transport = httpx.ASGITransport(app=app)

        async def client_for(user):
            token = await auth_service.create_session(db, user, method=LoginMethod.PASSWORD_TOTP)
            return httpx.AsyncClient(
                transport=transport, base_url="http://test/api/v1", cookies={SESSION_COOKIE_NAME: token}
            )

        admin_client = await client_for(admin)
        stranger_client = await client_for(stranger)
        yield db, admin_client, stranger_client
        await admin_client.aclose()
        await stranger_client.aclose()
        await db.rollback()
    await engine.dispose()


async def _project(client):
    key = f"TT{uuid.uuid4().hex[:4].upper()}"
    return (await client.post("/projects", json={"key": key, "name": "Tasks"})).json()


async def test_description_toggle(world):
    _db, admin, stranger = world
    project = await _project(admin)
    item = (await admin.post("/items", json={"project_id": project["id"], "title": "T", "description": BODY})).json()
    url = f"/items/{item['id']}/description/tasks"

    ok = await admin.post(url, json={"index": 0, "checked": True, "expected_body": BODY})
    assert ok.status_code == 200
    assert ok.json()["description"] == BODY.replace("- [ ] first", "- [x] first", 1)

    # The page the reader rendered is now stale: refused, nothing overwritten.
    stale = await admin.post(url, json={"index": 2, "checked": True, "expected_body": BODY})
    assert stale.status_code == 409
    # A stranger learns nothing — not even that the body differs.
    probe = await stranger.post(url, json={"index": 0, "checked": False, "expected_body": "guess"})
    assert probe.status_code in (403, 404)


async def test_comment_toggle(world):
    _db, admin, stranger = world
    project = await _project(admin)
    item = (await admin.post("/items", json={"project_id": project["id"], "title": "T"})).json()
    comment = (await admin.post(f"/items/{item['id']}/comments", json={"body": "- [ ] ship it"})).json()
    ok = await admin.post(
        f"/comments/{comment['id']}/tasks", json={"index": 0, "checked": True, "expected_body": "- [ ] ship it"}
    )
    assert ok.status_code == 200 and ok.json()["body"] == "- [x] ship it"
    probe = await stranger.post(
        f"/comments/{comment['id']}/tasks", json={"index": 0, "checked": False, "expected_body": "- [x] ship it"}
    )
    assert probe.status_code in (403, 404)


async def test_page_toggle_is_a_versioned_save(world):
    _db, admin, _stranger = world
    space = (await admin.post("/page-spaces", json={"name": "Tasks", "slug": f"tt-{uuid.uuid4().hex[:6]}"})).json()
    page = (await admin.post("/pages", json={"space_id": space["id"], "title": "Checklist", "body": BODY})).json()
    ok = await admin.post(f"/pages/{page['id']}/tasks", json={"index": 1, "checked": False, "expected_body": BODY})
    assert ok.status_code == 200
    assert ok.json()["version"] == page["version"] + 1
    assert "- [ ] second" in ok.json()["body"]
