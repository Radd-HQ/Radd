"""RADD-1435: GitLab, GitHub and Forgejo run on one connector kit in vcs; each keeps
its parser, its walker and its spec. The rules below are the kit's, so each runs
once per host — through the host's real receiver — rather than trusting that three
bindings of one implementation agree.
"""

import hashlib
import hmac
import importlib
import json
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError
from radd.kernel import registries
from radd.modules.vcs import triggers
from radd.modules.vcs.admin_router import list_connectors
from radd.modules.vcs.connector_kit.schemas import ConnectionCreate, RepoCreate


@dataclass(frozen=True)
class Host:
    name: str

    def module(self, sub: str) -> Any:
        return importlib.import_module(f"radd.modules.{self.name}.{sub}")

    @property
    def store(self):
        return self.module("service").store

    def push(self, repo: str) -> dict:
        """A keyless push naming `repo`, in the host's own shape."""
        if self.name == "gitlab":
            return {"object_kind": "push", "ref": "refs/heads/main", "commits": [], "project": {"path_with_namespace": repo}}
        return {"ref": "refs/heads/main", "commits": [], "repository": {"full_name": repo}}

    def headers(self, body: bytes, secret: str) -> dict[str, str]:
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return {
            "forgejo": {"X-Forgejo-Signature": digest, "X-Forgejo-Event": "push"},
            "github": {"X-Hub-Signature-256": f"sha256={digest}", "X-GitHub-Event": "push"},
            "gitlab": {"X-Gitlab-Token": secret, "X-Gitlab-Event": "Push Hook"},
        }[self.name] | {"Content-Type": "application/json"}


HOSTS = [Host("forgejo"), Host("github"), Host("gitlab")]


def _client(host: Host, session=None) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(host.module("router").router)

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session

    @app.exception_handler(ForbiddenError)
    async def _forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _connection(db, host: Host, secret: str):
    return await host.store.create_connection(
        db, ConnectionCreate(name=f"{host.name}-{uuid.uuid4().hex[:6]}", base_url="https://h.example.com", webhook_secret=secret)
    )


@pytest.mark.parametrize("host", HOSTS, ids=lambda h: h.name)
async def test_a_payload_signed_for_another_hosts_connection_is_refused(db, host: Host):
    """Spec 111: a delivery naming a repository recorded on host A is verified
    against A's connection and nothing else. Host B's secret is genuine and B is
    active — and it still must not authorise a write against A's repository."""
    first = await _connection(db, host, "secret-a")
    await _connection(db, host, "secret-b")
    repo = f"acme/{uuid.uuid4().hex[:8]}"
    await host.store.create_repo(db, RepoCreate(connection_id=first.id, full_name=repo))
    body = json.dumps(host.push(repo)).encode()
    path = f"/integrations/{host.name}"
    async with _client(host, db) as client:
        foreign = await client.post(path, content=body, headers=host.headers(body, "secret-b"))
        own = await client.post(path, content=body, headers=host.headers(body, "secret-a"))
    assert foreign.status_code == 403
    assert own.status_code == 200 and own.json() == {"linked": 0, "triggered": 0}


@pytest.mark.parametrize("host", HOSTS, ids=lambda h: h.name)
async def test_a_body_that_is_not_an_object_is_refused(host: Host):
    """Valid JSON that is not an object is refused before anything reads it (it
    was a 500 on GitHub and Forgejo, whose parsers call `payload.get`)."""
    async with _client(host) as client:
        response = await client.post(f"/integrations/{host.name}", content=b"[1, 2]", headers=host.headers(b"[1, 2]", "s"))
    assert response.status_code == 403


@pytest.mark.parametrize("host", HOSTS, ids=lambda h: h.name)
async def test_repository_paths_are_stored_trimmed_and_unique_whatever_the_case(db, host: Host):
    connection = await _connection(db, host, f"s-{uuid.uuid4().hex[:6]}")
    repo = await host.store.create_repo(db, RepoCreate(connection_id=connection.id, full_name=" /Acme/Widgets/ "))
    assert repo.full_name == "Acme/Widgets"
    with pytest.raises(ConflictError):
        await host.store.create_repo(db, RepoCreate(connection_id=connection.id, full_name="acme/widgets"))


@pytest.mark.parametrize("host", [Host("forgejo"), Host("github")], ids=lambda h: h.name)
async def test_only_a_published_non_draft_release_fires(monkeypatch, host: Host):
    """Forgejo sends GitHub's release shape, so it takes GitHub's guard: a draft
    fires nothing (Forgejo used to fire on one)."""
    fired: list[str] = []

    async def fake_emit(session, event_type, **kwargs):
        fired.append(kwargs["version"])

    monkeypatch.setattr(triggers, "emit_release", fake_emit)
    handle = host.module("router")._handle_release
    repo = SimpleNamespace(id=uuid.uuid4(), connection_id=uuid.uuid4(), project_id=None, publish_on_release=False)
    release = {"tag_name": "v1.2.0", "name": "One two", "body": "", "draft": True}
    payload = {"action": "published", "release": release, "repository": {"full_name": "acme/app"}}
    assert await handle(None, payload, repo) == {"linked": 0, "triggered": 0}
    assert await handle(None, {**payload, "release": {**release, "draft": False}}, repo) == {"linked": 0, "triggered": 1}
    assert fired == ["1.2.0"]


async def test_the_connectors_endpoint_follows_what_is_loaded(db, admin):
    """Settings → Version control draws one tab per entry; a disabled connector's
    spec leaves the socket with its plugin, and so leaves the page."""
    rows = await list_connectors(db, admin)
    assert [row.provider for row in rows] == ["forgejo", "github", "gitlab"]
    github = next(row for row in rows if row.provider == "github")
    assert github.title == "GitHub" and github.change_noun == "pull request"
    assert github.default_base_url == "https://github.com"
    assert next(row for row in rows if row.provider == "forgejo").default_base_url == ""

    plugin = registries.plugins["github"]
    registries.unregister_plugin(plugin)
    try:
        assert [row.provider for row in await list_connectors(db, admin)] == ["forgejo", "gitlab"]
    finally:
        registries.register_plugin(plugin)


# --- RADD-1451: one allowlist of merge/pull request changes, shared by every host ---


def test_only_allowlisted_fields_report_a_change_and_only_with_the_sides_the_host_sent():
    from radd.modules.gitlab import parsing as gitlab_parsing
    from radd.modules.vcs.connector_kit import github_shape
    from radd.modules.vcs.connector_kit.changes import MrChangeField

    # GitLab stamps these on every `update`; none is a change to automate on.
    bookkeeping = {
        "head_pipeline_id": {"previous": 1, "current": 2},
        "merge_status": {"previous": "checking", "current": "can_be_merged"},
        "total_time_spent": {"previous": 0, "current": 600},
        "time_change": {"previous": 0, "current": 600},
        "updated_at": {"previous": "a", "current": "b"},
    }
    assert gitlab_parsing.mr_changes({"changes": bookkeeping}) == []
    assert gitlab_parsing.mr_changes({"changes": {**bookkeeping, "title": {"previous": "x", "current": "y"}}}) == [
        {"field": MrChangeField.TITLE.value, "from": "x", "to": "y"}
    ]
    assert gitlab_parsing.mr_changes({"changes": {"milestone_id": {"previous": None, "current": 7}}}) == [
        {"field": MrChangeField.MILESTONE.value, "from": None, "to": 7}
    ]
    # `time_spent_changed` still reads the raw time keys the allowlist drops.
    assert gitlab_parsing.time_spent_changed({"changes": bookkeeping})

    # GitHub/Forgejo: the body is `body`, a base-branch change is `base`/`ref`.
    edited = {"action": "edited", "pull_request": {"title": "T", "body": "B", "base": {"ref": "develop"}}}
    assert github_shape.pr_changes({**edited, "changes": {"locked": {"from": False}}}) == []
    assert github_shape.pr_changes({**edited, "changes": {"body": {"from": "old body"}}}) == [
        {"field": MrChangeField.DESCRIPTION.value, "from": "old body", "to": "B"}
    ]
    assert github_shape.pr_changes({**edited, "changes": {"base": {"ref": {"from": "main"}, "sha": {"from": "a"}}}}) == [
        {"field": MrChangeField.TARGET_BRANCH.value, "from": "main", "to": "develop"}
    ]
    assert github_shape.pr_changes({**edited, "changes": {"ref": {"from": "main"}}}) == [
        {"field": MrChangeField.TARGET_BRANCH.value, "from": "main", "to": "develop"}
    ]

    # New commits: the sides the host sent, never an "old"/"new" placeholder.
    assert github_shape.pr_changes({"action": "synchronize", "before": "a1", "after": "b2"}) == [
        {"field": MrChangeField.COMMITS.value, "from": "a1", "to": "b2"}
    ]
    assert github_shape.pr_changes({"action": "synchronized", "pull_request": {"head": {"sha": "b2"}}}) == [
        {"field": MrChangeField.COMMITS.value, "to": "b2"}
    ]
    assert github_shape.pr_changes({"action": "synchronize"}) == [{"field": MrChangeField.COMMITS.value}]
    assert gitlab_parsing.mr_changes({"object_attributes": {"oldrev": "a1"}}) == [
        {"field": MrChangeField.COMMITS.value, "from": "a1"}
    ]
