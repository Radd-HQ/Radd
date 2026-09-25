"""RADD-1129: the GitHub connector — payload parsing, signature and connection
resolution, the receiver's refusals, the release guard, and backfill idempotency.

Runs against live Postgres inside a rolled-back transaction where it needs rows.
"""

import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.github import backfill, parsing, service
from radd.modules.github.models import GithubConnection
from radd.modules.github.router import router as github_router
from radd.modules.github.schemas import ConnectionCreate, ConnectionUpdate, RepoCreate, RepoUpdate
from radd.modules.github.types import GITHUB_COM, GITHUB_COM_API, GithubTrigger
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.vcs.models import ItemVcsLink
from radd.modules.vcs.triggers import RefAction
from radd.modules.vcs.types import VcsRefType


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --- parsing (pure) ---

PUSH = {
    "ref": "refs/heads/feature/td-99-fix-farm",
    "repository": {"full_name": "radd-hq/radd", "html_url": "https://github.com/radd-hq/radd"},
    "commits": [
        {"id": "a" * 40, "message": "[TD-12] fix the farm\n\nlonger body", "url": "https://github.com/radd-hq/radd/commit/" + "a" * 40},
        {"id": "b" * 40, "message": "no key here", "url": ""},
    ],
}


def test_plan_push_links_branch_and_commit_with_canonical_ids():
    planned = parsing.plan_push(PUSH)
    kinds = [(p.item_key, p.ref_type, p.external_id) for p in planned]
    assert kinds == [
        ("TD-99", VcsRefType.BRANCH, "branch:radd-hq/radd:feature/td-99-fix-farm"),
        ("TD-12", VcsRefType.COMMIT, "commit:radd-hq/radd:" + "a" * 40),
    ]
    assert planned[0].url == "https://github.com/radd-hq/radd/tree/feature/td-99-fix-farm"
    assert planned[1].title == "[TD-12] fix the farm"


def test_external_ids_lowercase_the_repository_as_github_reports_it():
    """GitHub sends `Radd-HQ/Radd`; the admin typed `radd-hq/radd`; CI and backfill
    must land on the same row."""
    planned = parsing.plan_push({**PUSH, "repository": {"full_name": "Radd-HQ/Radd", "html_url": "https://github.com/Radd-HQ/Radd"}})
    assert planned[1].external_id == "commit:radd-hq/radd:" + "a" * 40
    ci = parsing.plan_ci("workflow_run", {"repository": {"full_name": "Radd-HQ/Radd"}, "workflow_run": {"head_sha": "a" * 40, "conclusion": "success"}})
    assert ci is not None and "commit:radd-hq/radd:" + "a" * 40 in ci.external_ids


def test_plan_push_ignores_tag_pushes():
    assert parsing.plan_push({**PUSH, "ref": "refs/tags/v0.36.0"}) == []


def _pr(*, state: str, merged: bool, merged_at: str | None = None) -> dict:
    return {
        "action": "closed",
        "repository": {"full_name": "radd-hq/radd"},
        "pull_request": {
            "number": 7,
            "title": "TD-5 widen the gate",
            "body": "also touches DEV-3",
            "state": state,
            "merged": merged,
            "merged_at": merged_at,
            "html_url": "https://github.com/radd-hq/radd/pull/7",
            "head": {"ref": "td-5-gate"},
        },
    }


def test_plan_pull_request_status_and_keys():
    links = parsing.plan_pull_request(_pr(state="closed", merged=True))
    assert {link.item_key for link in links} == {"TD-5", "DEV-3"}
    assert all(link.external_id == "pr:radd-hq/radd:7" and link.status == "merged" for link in links)
    assert links[0].ref_type is VcsRefType.PULL_REQUEST
    links = parsing.plan_pull_request(_pr(state="open", merged=False))
    assert links[0].status == "open"


def test_pr_action_reads_the_action_never_the_state():
    """RADD-1309: a merge is `closed` + merged; an edit of a merged PR still says
    merged and must fire nothing."""
    def action(name, **pr):
        return parsing.pr_action({**_pr(**pr), "action": name})

    assert action("closed", state="closed", merged=True) is RefAction.MERGED
    # GitHub sometimes omits `merged` on re-deliveries but always carries merged_at.
    assert action("closed", state="closed", merged=False, merged_at="2026-09-11T10:00:00Z") is RefAction.MERGED
    assert action("closed", state="closed", merged=False) is RefAction.CLOSED
    assert action("opened", state="open", merged=False) is RefAction.OPENED
    assert action("reopened", state="open", merged=False) is RefAction.OPENED
    # RADD-1330: an edit of a merged PR is "updated", never "merged" again.
    assert action("edited", state="closed", merged=True) is RefAction.UPDATED
    assert action("synchronize", state="open", merged=False) is RefAction.UPDATED
    assert action("labeled", state="open", merged=False) is None


def test_plan_ci_covers_the_three_shapes():
    repo = {"full_name": "radd-hq/radd"}
    run = parsing.plan_ci("workflow_run", {"repository": repo, "workflow_run": {"head_sha": "c" * 40, "head_branch": "main", "conclusion": "success", "html_url": "u"}})
    assert run is not None and run.state == "success" and run.url == "u"
    assert set(run.external_ids) == {"branch:radd-hq/radd:main", "commit:radd-hq/radd:" + "c" * 40}
    suite = parsing.plan_ci("check_suite", {"repository": repo, "check_suite": {"head_sha": "d" * 40, "head_branch": "main", "status": "in_progress", "conclusion": None}})
    assert suite is not None and suite.state == "running"
    check = parsing.plan_ci("check_run", {"repository": repo, "check_run": {"head_sha": "e" * 40, "conclusion": "timed_out", "details_url": "d", "check_suite": {"head_branch": "fix"}}})
    assert check is not None and check.state == "failure" and check.url == "d" and "branch:radd-hq/radd:fix" in check.external_ids
    assert parsing.plan_ci("check_run", {"repository": repo, "check_run": {}}) is None


def test_signature_accepts_prefixed_and_bare_hex():
    body = b'{"x":1}'
    hexdigest = hmac.new(b"s", body, hashlib.sha256).hexdigest()
    assert service.verify_signature(body, "sha256=" + hexdigest, "s")
    assert service.verify_signature(body, hexdigest, "s")
    assert not service.verify_signature(body, "sha256=" + hexdigest, "other")
    assert not service.verify_signature(body, "", "s")
    assert not service.verify_signature(body, hexdigest, "")


def test_api_url_is_derived_from_the_web_host():
    assert GithubConnection(base_url=GITHUB_COM).api_url == GITHUB_COM_API
    assert GithubConnection(base_url="https://ghe.example.com/").api_url == "https://ghe.example.com/api/v3"


# --- rows ---


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _connection(db, name: str, secret: str, *, active: bool = True, token: str = "") -> GithubConnection:
    connection = await service.create_connection(
        db, ConnectionCreate(name=name, webhook_secret=secret, api_token=token)
    )
    if not active:
        connection.active = False
        await db.flush()
    return connection


def _payload(full_name: str = "") -> tuple[dict, bytes]:
    payload = {"ref": "refs/heads/main", "repository": {"full_name": full_name} if full_name else {}}
    return payload, json.dumps(payload).encode()


async def test_known_repo_is_verified_against_its_own_connection_only(db):
    first = await _connection(db, f"first-{uuid.uuid4().hex[:6]}", "secret-one")
    await _connection(db, f"second-{uuid.uuid4().hex[:6]}", "secret-two")
    await service.create_repo(db, RepoCreate(connection_id=first.id, full_name="Acme/Widgets"))
    payload, body = _payload("acme/widgets")  # case-insensitive lookup
    resolved = await service.resolve_for_payload(db, payload, body, _sign(body, "secret-one"))
    assert resolved is not None and resolved[0].id == first.id and resolved[1] is not None
    assert await service.resolve_for_payload(db, payload, body, _sign(body, "secret-two")) is None


async def test_unknown_repo_requires_registration(db):
    await _connection(db, f"host-{uuid.uuid4().hex[:6]}", "secret-one")
    await _connection(db, f"off-{uuid.uuid4().hex[:6]}", "secret-off", active=False)
    payload, body = _payload("nobody/knows-this")
    resolved = await service.resolve_for_payload(db, payload, body, _sign(body, "secret-one"))
    assert resolved is None
    assert await service.resolve_for_payload(db, payload, body, _sign(body, "secret-off")) is None
    assert await service.resolve_for_payload(db, payload, body, "") is None


async def test_empty_credential_on_update_keeps_the_stored_one_and_names_conflict(db):
    name = f"cred-{uuid.uuid4().hex[:6]}"
    connection = await _connection(db, name, "secret-one", token="tok")
    await service.update_connection(db, connection.id, ConnectionUpdate(webhook_secret="", api_token=""))
    assert connection.webhook_secret == "secret-one" and connection.api_token == "tok"
    with pytest.raises(ConflictError):
        await service.create_connection(db, ConnectionCreate(name=name))
    repo = await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="acme/dup"))
    with pytest.raises(ConflictError):
        await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="ACME/DUP"))
    await service.update_repo(db, repo.id, RepoUpdate(project_id=None))
    assert repo.project_id is None


# --- the receiver ---


def _app(monkeypatch, *secrets: str) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(ForbiddenError)
    async def forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    async def fake_session():
        yield None

    rows = [SimpleNamespace(id=i, name=f"c{i}", webhook_secret=s, active=True) for i, s in enumerate(secrets)]

    async def fake_list(session):
        return rows

    monkeypatch.setattr(service, "list_connections", fake_list)
    app.dependency_overrides[get_session] = fake_session
    app.include_router(github_router, prefix=settings.api_prefix)
    return app


KEYLESS = json.dumps({"ref": "refs/heads/main", "commits": [], "repository": {}}).encode()


async def test_receiver_refuses_without_a_verifying_connection(monkeypatch):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(monkeypatch)), base_url="http://t") as client:
        response = await client.post(f"{settings.api_prefix}/integrations/github", content=KEYLESS, headers={"X-Hub-Signature-256": _sign(KEYLESS, "anything"), "X-GitHub-Event": "push"})
    assert response.status_code == 403
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(monkeypatch, "s3cret")), base_url="http://t") as client:
        response = await client.post(f"{settings.api_prefix}/integrations/github", content=KEYLESS, headers={"X-Hub-Signature-256": _sign(KEYLESS, "wrong"), "X-GitHub-Event": "push"})
    assert response.status_code == 403


async def test_receiver_answers_ping_and_keyless_push(monkeypatch):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(monkeypatch, "s3cret")), base_url="http://t") as client:
        for event in ("ping", "push", "create"):
            response = await client.post(f"{settings.api_prefix}/integrations/github", content=KEYLESS, headers={"X-Hub-Signature-256": _sign(KEYLESS, "s3cret"), "X-GitHub-Event": event})
            assert response.status_code == 200 and response.json() == {"linked": 0, "triggered": 0}


async def test_release_guard_fires_only_for_published_non_draft(monkeypatch):
    """RADD-1309: a published release fires "GitHub: release published" and
    ships NOTHING itself — whether a version is recorded is an automation's
    call. A draft, an edit, a tagless release fire nothing."""
    import importlib

    github_router_module = importlib.import_module("radd.modules.github.router")

    fired: list[dict] = []

    async def fake_emit(session, event_type, **kwargs):
        fired.append({"event_type": event_type, **kwargs})

    monkeypatch.setattr(github_router_module.triggers, "emit_release", fake_emit)
    project_id = uuid.uuid4()
    repo = SimpleNamespace(id=uuid.uuid4(), project_id=project_id)
    base = {
        "release": {"tag_name": "v0.36.0", "name": "Radd 0.36.0", "body": "notes", "draft": False},
        "repository": {"full_name": "radd-hq/radd"},
    }
    handle = github_router_module._handle_release
    assert await handle(None, {**base, "action": "published"}, repo) == {"linked": 0, "triggered": 1}
    assert await handle(None, {**base, "action": "edited"}, repo) == {"linked": 0, "triggered": 0}
    draft = {**base, "action": "published", "release": {**base["release"], "draft": True}}
    assert await handle(None, draft, repo) == {"linked": 0, "triggered": 0}
    # An unrecorded repository still fires — with no project subject.
    assert await handle(None, {**base, "action": "published"}, None) == {"linked": 0, "triggered": 1}
    assert [(f["version"], f["tag"], f["project_id"]) for f in fired] == [
        ("0.36.0", "v0.36.0", project_id), ("0.36.0", "v0.36.0", None)
    ]
    assert fired[0]["event_type"] == GithubTrigger.RELEASE_PUBLISHED


# --- backfill against a fake GitHub API, twice ---


async def test_backfill_is_idempotent_and_uses_canonical_ids(db):
    key = f"GH{uuid.uuid4().hex[:4].upper()}"
    project = await projects_service.create_project(db, ProjectCreate(key=key, name="GitHub backfill"))
    from radd.modules.auth.models import User

    owner = User(name="Owner", email=f"{uuid.uuid4()}@test.invalid", instance_role="admin")
    db.add(owner)
    await db.flush()
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="linked"), actor=owner)
    connection = await _connection(db, f"bf-{uuid.uuid4().hex[:6]}", "s", token="tok")
    repo = await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="radd-hq/radd"))
    sha = "f" * 40

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        path = request.url.path
        if request.url.params.get("page") != "1":
            return httpx.Response(200, json=[])
        if path.endswith("/branches"):
            return httpx.Response(200, json=[{"name": f"{item.key.lower()}-work"}, {"name": "main"}])
        if path.endswith("/pulls"):
            return httpx.Response(200, json=[{"number": 4, "title": f"{item.key} widen", "body": "", "state": "closed", "merged_at": "2026-09-11T00:00:00Z", "html_url": "https://github.com/radd-hq/radd/pull/4", "head": {"ref": "x"}}])
        if path.endswith("/commits"):
            return httpx.Response(200, json=[{"sha": sha, "commit": {"message": f"[{item.key}] done"}, "html_url": f"https://github.com/radd-hq/radd/commit/{sha}"}, {"sha": "0" * 40, "commit": {"message": "OTHER-1 not ours"}}])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    from radd.modules.events.models import Event

    head = (await db.execute(select(Event.id).order_by(Event.id.desc()).limit(1))).scalar() or 0
    first = await backfill.run(db, connection, repo, transport=transport)
    second = await backfill.run(db, connection, repo, transport=transport)
    # RADD-1314: a backfill replays history quietly.
    emitted = list((await db.execute(select(Event).where(Event.id > head))).scalars())
    assert emitted and all(e.silent for e in emitted)
    assert first.as_dict() == second.as_dict()
    assert first.linked == 3 and first.unknown_keys == ["OTHER-1"]
    rows = (await db.execute(select(ItemVcsLink).where(ItemVcsLink.item_id == item.id))).scalars().all()
    assert len(rows) == 3  # twice run, three links
    ids = {row.external_id for row in rows}
    assert ids == {f"branch:radd-hq/radd:{item.key.lower()}-work", "pr:radd-hq/radd:4", f"commit:radd-hq/radd:{sha}"}
    assert {row.provider for row in rows} == {"github"}
    merged = next(row for row in rows if row.ref_type == VcsRefType.PULL_REQUEST)
    assert merged.status == "merged"
    # The webhook parser produces the same commit id, so a later push cannot add a second row.
    planned = parsing.plan_push({"ref": "refs/heads/main", "repository": {"full_name": "radd-hq/radd", "html_url": "https://github.com/radd-hq/radd"}, "commits": [{"id": sha, "message": f"[{item.key}] done"}]})
    assert planned[0].external_id in ids
    count = await db.scalar(select(func.count()).select_from(ItemVcsLink).where(ItemVcsLink.item_id == item.id))
    assert count == 3
