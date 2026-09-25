"""RADD-1253: GitLab connections as rows, and which host is trusted for a payload.

GitLab sends the hook's secret token back verbatim (`X-Gitlab-Token`), so the
interesting invariant is the spec-111 one: a payload from a KNOWN project is
verified against that project's own connection and nothing else — a second
host's genuine token must not authorise writes against the first host's
projects. Plus the receiver end to end (link, and RADD-1309's triggers — a
merge fires "GitLab: merge request merged" and moves nothing by itself)
against live Postgres inside a rolled-back transaction.
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
        assert other.status_code == 200 and other.json() == {"linked": 0, "triggered": 0}

    rows = list((await db.execute(select(ItemVcsLink).where(ItemVcsLink.item_id == item.id))).scalars())
    assert [(r.provider, r.ref_type, r.external_id, r.status) for r in rows] == [
        ("gitlab", "merge_request", "pr:acme/rx:7", "open")
    ]
    assert rows[0].title == f"{key} do the thing (!7)"


async def _events_after(db, head: int, event_type: str) -> list:
    from radd.modules.events import service as events

    return [e for e in await events.read_after(db, head, 500) if e.event_type == event_type]


async def _head(db) -> int:
    from radd.modules.events.models import Event

    return (await db.execute(select(Event.id).order_by(Event.id.desc()).limit(1))).scalar() or 0


async def test_a_merge_fires_the_trigger_and_changes_nothing_else(db):
    """RADD-1309. The receiver used to move every issue a merged MR named to the
    project's waiting-for-release state, unasked. The project here HAS that
    state and an on-release transition — the precondition under which the old
    code moved the issue — so "state unchanged" is not vacuous. With an
    automation on the trigger, the issue moves where the automation says."""
    import httpx

    from radd.modules.auth.models import User
    from radd.modules.automations import engine, service as automations
    from radd.modules.automations.schemas import RuleCreate
    from radd.modules.gitlab.types import GitlabTrigger
    from radd.modules.items.enums import ItemEvent
    from radd.modules.releases.models import Release
    from radd.modules.workflow import service as workflow, transitions
    from radd.modules.workflow.schemas import StateCreate, TransitionCreate
    from radd.modules.workflow.types import StateCategory

    connection = await _connection(db, f"tr-{uuid.uuid4().hex[:6]}", "hook-secret")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"TR{uuid.uuid4().hex[:4].upper()}", name="Triggers")
    )
    await service.create_repo(
        db, RepoCreate(connection_id=connection.id, full_name="acme/tr", project_id=project.id)
    )
    states = await workflow.list_states(db, project.id)
    waiting = await workflow.create_state(
        db, StateCreate(project_id=project.id, name="Waiting for release", category=StateCategory.DONE, position=len(states) + 1)
    )
    done = next(s for s in states if s.name == "Done")
    await transitions.create_transition(
        db, TransitionCreate(project_id=project.id, from_state_id=waiting.id, to_state_id=done.id, on_release=True)
    )
    owner = User(name="Owner", email=f"{uuid.uuid4()}@test.invalid", instance_role="admin")
    db.add(owner)
    await db.flush()
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="merge me"), actor=owner)
    before = item.state.id

    def mr(action: str, state: str, changes: dict | None = None, oldrev: str = "") -> bytes:
        return json.dumps({
            "object_kind": "merge_request",
            "project": {"path_with_namespace": "acme/tr"},
            "object_attributes": {
                "iid": 9, "title": f"{item.key} ship it", "source_branch": "feat", "target_branch": "main",
                "state": state, "action": action, "url": "https://tr.example.com/acme/tr/-/merge_requests/9",
                **({"oldrev": oldrev} if oldrev else {}),
            },
            **({"changes": changes} if changes is not None else {}),
        }).encode()

    headers = {"X-Gitlab-Token": "hook-secret", "Content-Type": "application/json"}
    transport = httpx.ASGITransport(app=_app(db))
    head = await _head(db)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        merged = await client.post("/integrations/gitlab", content=mr("merge", "merged"), headers=headers)
        assert merged.json() == {"linked": 1, "triggered": 1}
        # A later edit of the merged MR repeats `state: merged` and fires nothing.
        edited = await client.post("/integrations/gitlab", content=mr("update", "merged"), headers=headers)
        assert edited.json() == {"linked": 1, "triggered": 0}
        # RADD-1330: an update that CHANGED something fires "updated" (never
        # "merged" again); a bookkeeping-only stamp still fires nothing.
        stamp = mr("update", "merged", changes={"updated_at": {"previous": "a", "current": "b"}})
        assert (await client.post("/integrations/gitlab", content=stamp, headers=headers)).json()["triggered"] == 0
        retitled = mr("update", "merged", changes={"title": {"previous": "x", "current": "y"}, "updated_at": {}})
        assert (await client.post("/integrations/gitlab", content=retitled, headers=headers)).json()["triggered"] == 1
        pushed = mr("update", "opened", oldrev="abc123")
        assert (await client.post("/integrations/gitlab", content=pushed, headers=headers)).json()["triggered"] == 1
        release = await client.post("/integrations/gitlab", content=json.dumps({
            "object_kind": "release", "action": "create", "tag": "v2.1.0", "name": "Two one",
            "description": "notes", "url": "https://tr.example.com/acme/tr/-/releases/v2.1.0",
            "project": {"path_with_namespace": "acme/tr"},
        }).encode(), headers=headers)
        assert release.json() == {"linked": 0, "triggered": 1}

    assert (await items_service.require_item(db, item.id)).state_id == before
    assert await _events_after(db, head, ItemEvent.UPDATED.value) == []
    assert (await db.scalar(select(Release).where(Release.project_id == project.id))) is None

    fired = await _events_after(db, head, GitlabTrigger.MR_MERGED.value)
    assert len(fired) == 1
    updates = await _events_after(db, head, GitlabTrigger.MR_UPDATED.value)
    assert [[c["field"] for c in u.payload["changes"]] for u in updates] == [["title"], ["commits"]]
    assert updates[0].payload["changes"][0] == {"field": "title", "from": "x", "to": "y"}
    assert all(u.payload["action"] == "updated" for u in updates)
    event = fired[0]
    assert event.payload["item"]["id"] == str(item.id)
    assert event.payload["action"] == "merged" and event.payload["repo"] == "acme/tr"
    assert event.payload["ref"]["number"] == "9" and event.payload["ref"]["target_branch"] == "main"
    [published] = await _events_after(db, head, GitlabTrigger.RELEASE_PUBLISHED.value)
    assert published.payload["version"] == "2.1.0" and published.payload["tag"] == "v2.1.0"
    assert published.payload["project"]["id"] == str(project.id)

    # The behaviour the receiver used to hard-code, as an automation someone built.
    await automations.create_rule(db, RuleCreate.model_validate({
        "name": "merged → waiting",
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": GitlabTrigger.MR_MERGED.value}},
            {"id": "act", "kind": "action", "type": "action.set_state", "params": {"state": waiting.name}},
        ],
        "edges": [{"source": "trg", "port": "out", "target": "act"}],
    }), owner.id)
    await engine.apply_event(db, event)  # a SYSTEM-actor event: RADD-1308 is what lets it through
    assert (await items_service.require_item(db, item.id)).state_id == waiting.id


async def test_pipelines_stamp_ci_and_fire_and_deployments_fire_with_the_environment(db):
    """RADD-1255. A pipeline for a linked branch moves its CI badge; one that
    reached an outcome also fires "GitLab: CI finished". A finished deployment of
    that branch fires "GitLab: deployment finished" with its environment. A
    pipeline for a branch no issue mentions writes nothing, and a running
    deployment fires nothing."""
    import httpx

    from radd.modules.auth.models import User
    from radd.modules.gitlab.types import GitlabTrigger

    connection = await _connection(db, f"ci-{uuid.uuid4().hex[:6]}", "hook-secret")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"CI{uuid.uuid4().hex[:4].upper()}", name="Pipelines")
    )
    await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="acme/ci", project_id=project.id))
    owner = User(name="Owner", email=f"{uuid.uuid4()}@test.invalid", instance_role="admin")
    db.add(owner)
    await db.flush()
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="ship"), actor=owner)
    branch = f"{item.key.lower()}-work"
    headers = {"X-Gitlab-Token": "hook-secret", "Content-Type": "application/json"}
    project_json = {"path_with_namespace": "acme/ci", "web_url": "https://gl.example.com/acme/ci"}

    def body(payload: dict) -> bytes:
        return json.dumps({"project": project_json, **payload}).encode()

    def pipeline(ref: str, status: str) -> bytes:
        return body({"object_kind": "pipeline", "object_attributes": {
            "id": 77, "ref": ref, "sha": "c0ffee", "status": status, "tag": False,
            "url": "https://gl.example.com/acme/ci/-/pipelines/77",
        }})

    transport = httpx.ASGITransport(app=_app(db))
    head = await _head(db)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # The branch gets linked by a push naming the issue.
        pushed = await client.post("/integrations/gitlab", content=body({
            "object_kind": "push", "ref": f"refs/heads/{branch}", "commits": [],
        }), headers=headers)
        assert pushed.json()["linked"] == 1
        running = await client.post("/integrations/gitlab", content=pipeline(branch, "running"), headers=headers)
        assert running.json() == {"linked": 1, "triggered": 0}
        [link] = list((await db.execute(select(ItemVcsLink).where(ItemVcsLink.item_id == item.id))).scalars())
        assert link.ci_state == "running"
        failed = await client.post("/integrations/gitlab", content=pipeline(branch, "failed"), headers=headers)
        assert failed.json() == {"linked": 1, "triggered": 1}
        stranger = await client.post("/integrations/gitlab", content=pipeline("nobody-mentions-this", "success"), headers=headers)
        assert stranger.json() == {"linked": 0, "triggered": 0}

        def deployment(status: str) -> bytes:
            return body({"object_kind": "deployment", "status": status, "environment": "production",
                         "ref": branch, "sha": "c0ffee", "environment_external_url": "https://app.example.com",
                         "user": {"username": "deployer"}})

        assert (await client.post("/integrations/gitlab", content=deployment("running"), headers=headers)).json()["triggered"] == 0
        assert (await client.post("/integrations/gitlab", content=deployment("success"), headers=headers)).json()["triggered"] == 1

    await db.refresh(link)
    assert link.ci_state == "failure" and link.ci_url.endswith("/pipelines/77")
    [ci] = await _events_after(db, head, GitlabTrigger.CI_COMPLETED.value)
    assert ci.payload["ci"] == {"state": "failure", "url": "https://gl.example.com/acme/ci/-/pipelines/77"}
    assert ci.payload["item"]["id"] == str(item.id)
    [deployed] = await _events_after(db, head, GitlabTrigger.DEPLOYMENT_FINISHED.value)
    assert deployed.payload["environment"] == "production" and deployed.payload["status"] == "success"
    assert deployed.payload["url"] == "https://app.example.com"
    assert deployed.payload["author"]["username"] == "deployer"

