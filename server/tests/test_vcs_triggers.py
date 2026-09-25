"""RADD-1309: GitHub and Forgejo fire their OWN triggers and change nothing else.

Before this, both receivers moved every issue a merged pull request named to
the project's waiting-for-release state, and swept a published release, with no
switch. Each case below runs the real receiver against live Postgres (rolled
back) on a project that HAS a waiting state and an on-release transition — the
exact precondition under which the old code acted — so "the state did not move"
is not vacuous. GitLab's twin lives in test_gitlab_connections.py.
"""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Any

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
from radd.modules.events.models import Event
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEvent
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.releases.models import Release
from radd.modules.workflow import service as workflow, transitions
from radd.modules.workflow.schemas import StateCreate, TransitionCreate
from radd.modules.workflow.types import StateCategory


@dataclass(frozen=True)
class Host:
    name: str
    path: str  # the receiver's route
    event_header: str
    signature_header: str
    prefix: str  # what precedes the hex digest

    def module(self, sub: str) -> Any:
        import importlib

        return importlib.import_module(f"radd.modules.{self.name}.{sub}")

    def headers(self, body: bytes, secret: str, event: str) -> dict[str, str]:
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return {
            self.signature_header: self.prefix + digest,
            self.event_header: event,
            "Content-Type": "application/json",
        }


HOSTS = [
    Host("github", "/integrations/github", "X-GitHub-Event", "X-Hub-Signature-256", "sha256="),
    Host("forgejo", "/integrations/forgejo", "X-Forgejo-Event", "X-Forgejo-Signature", ""),
]


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _app(db, host: Host) -> FastAPI:
    app = FastAPI()
    app.include_router(host.module("router").router)

    async def _session():
        yield db

    app.dependency_overrides[get_session] = _session

    @app.exception_handler(ForbiddenError)
    async def _forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return app


async def _events(db, head: int, event_type: str) -> list[Event]:
    rows = await db.execute(select(Event).where(Event.id > head, Event.event_type == event_type).order_by(Event.id))
    return list(rows.scalars())


@pytest.mark.parametrize("host", HOSTS, ids=lambda h: h.name)
async def test_a_merge_ci_run_and_release_fire_triggers_and_move_nothing(db, host: Host):
    service, schemas, types = host.module("service"), host.module("schemas"), host.module("types")
    trigger = types.GithubTrigger if host.name == "github" else types.ForgejoTrigger
    secret = f"s-{uuid.uuid4().hex[:8]}"
    repo_name = f"acme/{host.name}-{uuid.uuid4().hex[:6]}"

    connection = await service.create_connection(
        db, schemas.ConnectionCreate(name=f"{host.name}-{uuid.uuid4().hex[:6]}", base_url="https://h.example.com", webhook_secret=secret)
    )
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"VT{uuid.uuid4().hex[:4].upper()}", name="VCS triggers")
    )
    await service.create_repo(
        db, schemas.RepoCreate(connection_id=connection.id, full_name=repo_name, project_id=project.id)
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
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="ship"), actor=owner)
    before = item.state.id
    branch = f"{item.key.lower()}-work"
    repository = {"full_name": repo_name, "html_url": f"https://h.example.com/{repo_name}"}

    head = (await db.execute(select(Event.id).order_by(Event.id.desc()).limit(1))).scalar() or 0
    deliveries = [
        ("push", {"ref": f"refs/heads/{branch}", "commits": [], "repository": repository}, {"linked": 1, "triggered": 1}),
        ("pull_request", {
            "action": "closed",
            "pull_request": {
                "number": 5, "title": "ship it", "state": "closed", "merged": True,
                "merged_at": "2026-09-25T10:00:00Z", "html_url": "https://h.example.com/pr/5",
                "head": {"ref": branch}, "base": {"ref": "main"}, "body": "",
            },
            "repository": repository,
            # RADD-1320: who merged it — resolved to a Radd person by email.
            "sender": {"login": "owner-on-host", "email": owner.email},
        }, {"linked": 1, "triggered": 1}),
        # An edit of the merged PR repeats its state and must fire nothing.
        ("pull_request", {
            "action": "edited",
            "pull_request": {
                "number": 5, "title": "ship it", "state": "closed", "merged": True,
                "merged_at": "2026-09-25T10:00:00Z", "html_url": "https://h.example.com/pr/5",
                "head": {"ref": branch}, "base": {"ref": "main"}, "body": "",
            },
            "repository": repository,
        }, {"linked": 1, "triggered": 0}),
        # A running report moves the badge only; a finished one fires.
        ("workflow_run", {"workflow_run": {"head_branch": branch, "status": "in_progress"}, "repository": repository},
         {"linked": 1, "triggered": 0}),
        ("workflow_run", {"workflow_run": {"head_branch": branch, "conclusion": "failure", "html_url": "https://ci/1"}, "repository": repository},
         {"linked": 1, "triggered": 1}),
        ("release", {"action": "published", "release": {"tag_name": "v3.0.0", "name": "Three", "body": "n", "draft": False}, "repository": repository},
         {"linked": 0, "triggered": 1}),
    ]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db, host)), base_url="http://t") as client:
        for event, payload, expected in deliveries:
            body = json.dumps(payload).encode()
            response = await client.post(host.path, content=body, headers=host.headers(body, secret, event))
            assert response.status_code == 200, (event, response.text)
            assert {k: response.json()[k] for k in ("linked", "triggered")} == expected, (event, payload.get("action"))

    assert (await items_service.require_item(db, item.id)).state_id == before
    assert await _events(db, head, ItemEvent.UPDATED.value) == []
    assert await db.scalar(select(Release).where(Release.project_id == project.id)) is None

    [merged] = await _events(db, head, trigger.PR_MERGED.value)
    assert merged.payload["item"]["id"] == str(item.id) and merged.payload["action"] == "merged"
    assert merged.payload["ref"]["number"] == "5" and merged.payload["ref"]["source_branch"] == branch
    assert merged.payload["author"] == {"username": "owner-on-host", "email": owner.email}
    assert merged.payload["user"]["id"] == str(owner.id), "the host account maps to the Radd person"
    [pushed] = await _events(db, head, trigger.PUSHED.value)
    assert pushed.payload["branch"] == branch
    [ci] = await _events(db, head, trigger.CI_COMPLETED.value)
    assert ci.payload["ci"] == {"state": "failure", "url": "https://ci/1"}
    [published] = await _events(db, head, trigger.RELEASE_PUBLISHED.value)
    assert published.payload["version"] == "3.0.0" and published.payload["project"]["id"] == str(project.id)
    assert await _events(db, head, trigger.PR_CLOSED.value) == []
