"""RADD-1253: GitLab connections as rows, and which host is trusted for a payload.

GitLab sends the hook's secret token back verbatim (`X-Gitlab-Token`), so the
interesting invariant is the spec-111 one: a payload from a KNOWN project is
verified against that project's own connection and nothing else — a second
host's genuine token must not authorise writes against the first host's
projects. Plus the receiver end to end (link, merge → waiting state) against
live Postgres inside a rolled-back transaction.
"""

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.gitlab import service
from radd.modules.gitlab.models import GitlabConnection
from radd.modules.gitlab.router import router as gitlab_router
from radd.modules.gitlab.schemas import ConnectionCreate, ConnectionUpdate, RepoCreate, RepoUpdate
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.vcs.models import ItemVcsLink
from radd.modules.vcs.models import VcsUserLink
from radd.modules.vcs import timemirror
from radd.modules.vcs.types import VcsProvider


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _payload(path: str = "") -> dict:
    return {
        "object_kind": "push",
        "ref": "refs/heads/main",
        "project": {"path_with_namespace": path} if path else {},
        "commits": [],
    }


async def _connection(db, name: str, secret: str, *, active: bool = True) -> GitlabConnection:
    connection = await service.create_connection(
        db, ConnectionCreate(name=name, base_url=f"https://{name}.example.com", webhook_secret=secret)
    )
    if not active:
        connection.active = False
        await db.flush()
    return connection


# --- resolution ---


async def test_known_project_is_verified_against_its_own_connection(db):
    first = await _connection(db, f"first-{uuid.uuid4().hex[:6]}", "secret-one")
    second = await _connection(db, f"second-{uuid.uuid4().hex[:6]}", "secret-two")
    await service.create_repo(db, RepoCreate(connection_id=first.id, full_name="acme/sub/widgets"))

    resolved = await service.resolve_for_payload(db, _payload("acme/sub/widgets"), "secret-one")
    assert resolved is not None and resolved[0].id == first.id
    assert resolved[1] is not None and resolved[1].full_name == "acme/sub/widgets"
    # The OTHER host's genuine token must not authorise writes here.
    assert await service.resolve_for_payload(db, _payload("acme/sub/widgets"), "secret-two") is None
    assert second.active is True


async def test_unknown_project_falls_back_to_any_active_connection(db):
    await _connection(db, f"host-{uuid.uuid4().hex[:6]}", "secret-one")
    resolved = await service.resolve_for_payload(db, _payload("nobody/knows"), "secret-one")
    assert resolved is not None and resolved[1] is None
    assert await service.resolve_for_payload(db, _payload("nobody/knows"), "nope") is None


async def test_inactive_connection_and_empty_token_verify_nothing(db):
    connection = await _connection(db, f"off-{uuid.uuid4().hex[:6]}", "secret-one", active=False)
    await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="acme/off"))
    assert await service.resolve_for_payload(db, _payload("acme/off"), "secret-one") is None
    assert await service.resolve_for_payload(db, _payload("someone/else"), "secret-one") is None
    on = await _connection(db, f"on-{uuid.uuid4().hex[:6]}", "secret-three")
    await service.create_repo(db, RepoCreate(connection_id=on.id, full_name="acme/on"))
    assert await service.resolve_for_payload(db, _payload("acme/on"), "") is None
    # A connection with NO secret accepts nothing, rather than everything.
    bare = await _connection(db, f"bare-{uuid.uuid4().hex[:6]}", "")
    await service.create_repo(db, RepoCreate(connection_id=bare.id, full_name="acme/bare"))
    assert await service.resolve_for_payload(db, _payload("acme/bare"), "") is None


async def test_project_lookup_is_case_insensitive_and_strips_slashes(db):
    connection = await _connection(db, f"case-{uuid.uuid4().hex[:6]}", "secret-one")
    await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="/Acme/Widgets/"))
    resolved = await service.resolve_for_payload(db, _payload("acme/widgets"), "secret-one")
    assert resolved is not None and resolved[1] is not None and resolved[1].full_name == "Acme/Widgets"


# --- rows ---


async def test_empty_credential_on_update_keeps_the_stored_one(db):
    connection = await _connection(db, f"cred-{uuid.uuid4().hex[:6]}", "secret-one")
    connection.api_token = "glpat-abc"
    await db.flush()
    await service.update_connection(db, connection.id, ConnectionUpdate(name="renamed"))
    assert connection.webhook_secret == "secret-one" and connection.api_token == "glpat-abc"
    await service.update_connection(db, connection.id, ConnectionUpdate(webhook_secret="", api_token=""))
    assert connection.webhook_secret == "secret-one" and connection.api_token == "glpat-abc"
    await service.update_connection(db, connection.id, ConnectionUpdate(webhook_secret="rotated"))
    assert connection.webhook_secret == "rotated"


async def test_duplicate_names_and_projects_conflict(db):
    name = f"dupe-{uuid.uuid4().hex[:6]}"
    connection = await _connection(db, name, "secret-one")
    with pytest.raises(ConflictError):
        await service.create_connection(db, ConnectionCreate(name=name))
    await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="acme/dup"))
    with pytest.raises(ConflictError):
        await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="ACME/DUP"))


async def test_repo_update_idioms_and_time_category(db):
    connection = await _connection(db, f"upd-{uuid.uuid4().hex[:6]}", "secret-one")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"GL{uuid.uuid4().hex[:4].upper()}", name="GitLab mapping")
    )
    repo = await service.create_repo(
        db, RepoCreate(connection_id=connection.id, full_name="acme/clearable", project_id=project.id)
    )
    await service.update_repo(db, repo.id, RepoUpdate(default_branch="trunk"))
    assert repo.project_id == project.id and repo.default_branch == "trunk"
    await service.update_repo(db, repo.id, RepoUpdate(project_id=None))
    assert repo.project_id is None
    from radd.modules.timelogging import categories

    await categories.ensure_default_categories(db)
    category = (await categories.list_categories(db))[1]
    await service.update_repo(db, repo.id, RepoUpdate(time_category_id=category.id))
    assert repo.time_category_id == category.id
    await service.update_repo(db, repo.id, RepoUpdate(time_category_id=None))
    assert repo.time_category_id is None


async def test_deleting_a_connection_forgets_its_identity_map(db):
    connection = await _connection(db, f"del-{uuid.uuid4().hex[:6]}", "secret-one")
    from radd.modules.auth.models import User

    user = User(email=f"gl-{uuid.uuid4().hex[:6]}@example.com", name="Mapped", instance_role="admin")
    db.add(user)
    await db.flush()
    await timemirror.set_user_link(
        db, provider=VcsProvider.GITLAB, connection_id=connection.id, username="someone", user_id=user.id, actor_id=None
    )
    await service.delete_connection(db, connection.id)
    left = await db.scalar(select(VcsUserLink).where(VcsUserLink.connection_id == connection.id))
    assert left is None


def test_api_and_graphql_urls_are_derived_from_one_base():
    connection = GitlabConnection(name="x", base_url="https://gitlab.mtl.example.com/")
    assert connection.api_url == "https://gitlab.mtl.example.com/api/v4"
    assert connection.graphql_url == "https://gitlab.mtl.example.com/api/graphql"


# --- the receiver, end to end ---


def _app(db) -> FastAPI:
    app = FastAPI()
    app.include_router(gitlab_router)

    async def _session():
        yield db

    app.dependency_overrides[get_session] = _session

    @app.exception_handler(ForbiddenError)
    async def _forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return app


async def test_receiver_refuses_a_bad_token_and_links_with_a_good_one(db):
    import httpx

    connection = await _connection(db, f"rx-{uuid.uuid4().hex[:6]}", "hook-secret")
    await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="acme/rx"))
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"RX{uuid.uuid4().hex[:4].upper()}", name="Receiver")
    )
    from radd.modules.auth.models import User

    owner = User(name="Owner", email=f"{uuid.uuid4()}@test.invalid", instance_role="admin")
    db.add(owner)
    await db.flush()
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="linked"), actor=owner)
    key = f"{project.key}-{item.number}"

    payload = {
        "object_kind": "merge_request",
        "project": {"path_with_namespace": "acme/rx", "web_url": "https://rx.example.com/acme/rx"},
        "object_attributes": {
            "iid": 7,
            "title": f"{key} do the thing",
            "description": "",
            "source_branch": "feature",
            "state": "opened",
            "action": "open",
            "url": "https://rx.example.com/acme/rx/-/merge_requests/7",
        },
    }
    body = json.dumps(payload).encode()
    transport = httpx.ASGITransport(app=_app(db))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        refused = await client.post("/integrations/gitlab", content=body, headers={"X-Gitlab-Token": "wrong", "Content-Type": "application/json"})
        assert refused.status_code == 403
        ok = await client.post("/integrations/gitlab", content=body, headers={"X-Gitlab-Token": "hook-secret", "X-Gitlab-Event": "Merge Request Hook", "Content-Type": "application/json"})
        assert ok.status_code == 200 and ok.json()["linked"] == 1
        again = await client.post("/integrations/gitlab", content=body, headers={"X-Gitlab-Token": "hook-secret", "Content-Type": "application/json"})
        assert again.status_code == 200 and again.json()["linked"] == 1
        # An unknown kind is a 200 no-op, never a 500.
        other = await client.post("/integrations/gitlab", content=json.dumps({**payload, "object_kind": "pipeline"}).encode(), headers={"X-Gitlab-Token": "hook-secret", "Content-Type": "application/json"})
        assert other.status_code == 200 and other.json() == {"linked": 0, "transitioned": 0}

    rows = list((await db.execute(select(ItemVcsLink).where(ItemVcsLink.item_id == item.id))).scalars())
    assert [(r.provider, r.ref_type, r.external_id, r.status) for r in rows] == [
        ("gitlab", "merge_request", "pr:acme/rx:7", "open")
    ]
    assert rows[0].title == f"{key} do the thing (!7)"
