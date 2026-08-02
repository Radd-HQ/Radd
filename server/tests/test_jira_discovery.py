"""Jira import discovery endpoints (specs 90, 100) over an in-process ASGI app
with the Jira layer stubbed — there is no Jira server in CI, and these tests are
about the ROUTING contract: admin-gated, 409 when no connection exists, 422 on
bad JQL, and a connection-status shape that never 500s.

Spec 100 moved "which Jira" from `settings` into a database row, so the stubs
target `connections` (which connection) and `service` (what Jira said) rather
than the old module-level `client.configured()`.
"""

from dataclasses import dataclass
import uuid

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth.deps import current_user
from radd.modules.auth.types import InstanceRole
from radd.modules.jiraimport import client, connections, service
from radd.modules.jiraimport.client import JiraClient
from radd.modules.jiraimport.router import router as jira_router
from radd.modules.jiraimport.types import JiraAuthMode, JiraCreds, JiraEntity, JiraProject


class _User:
    def __init__(self, admin: bool):
        self.instance_role = InstanceRole.ADMIN.value if admin else InstanceRole.MEMBER.value


@dataclass
class _Connection:
    """Duck-types the JiraConnection row for `creds_of` and the status shape."""

    id: uuid.UUID
    name: str = "Test Jira"
    base_url: str = "https://jira.example.com"
    auth_mode: str = JiraAuthMode.PAT.value
    username: str = ""
    credential: str = "tok"
    verify_ssl: bool = True


def _app(admin: bool = True) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(ForbiddenError)
    async def forbidden(request: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def bad_value(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    app.dependency_overrides[current_user] = lambda: _User(admin)
    # Every stub below short-circuits before the session is used.
    app.dependency_overrides[get_session] = lambda: None
    app.include_router(jira_router, prefix=settings.api_prefix)
    return app


def _client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _connected(monkeypatch):
    """Default: one usable connection. Individual tests override."""
    connection = _Connection(id=uuid.uuid4())

    async def default_connection(session):
        return connection

    async def require_connection(session, connection_id=None):
        return connection

    monkeypatch.setattr(connections, "default_connection", default_connection)
    monkeypatch.setattr(connections, "require_connection", require_connection)
    return connection


def _unconfigure(monkeypatch):
    async def default_connection(session):
        return None

    async def require_connection(session, connection_id=None):
        raise ConflictError(JiraEntity.JIRA, reason="no Jira connection is configured")

    monkeypatch.setattr(connections, "default_connection", default_connection)
    monkeypatch.setattr(connections, "require_connection", require_connection)


# --- credentials (pure) -------------------------------------------------------


def test_creds_are_usable_only_with_the_credential_their_mode_needs():
    assert JiraCreds(base_url="https://j", auth_mode=JiraAuthMode.PAT, credential="tok").usable
    # A PAT with no token, or basic auth with no username, cannot sign a request.
    assert not JiraCreds(base_url="https://j", auth_mode=JiraAuthMode.PAT).usable
    assert not JiraCreds(base_url="", auth_mode=JiraAuthMode.PAT, credential="tok").usable
    assert not JiraCreds(
        base_url="https://j", auth_mode=JiraAuthMode.BASIC, credential="pw"
    ).usable
    assert JiraCreds(
        base_url="https://j", auth_mode=JiraAuthMode.BASIC, credential="pw", username="svc"
    ).usable


def test_the_auth_mode_decides_the_http_credential():
    """PAT is a Bearer header; basic is an auth pair. Spec 90 chose between them by
    which settings happened to be set — spec 100 makes it an explicit per-connection
    mode, so a connection with both a username and a token is not ambiguous."""
    with JiraClient(
        JiraCreds(base_url="https://j", auth_mode=JiraAuthMode.PAT, credential="tok", username="svc")
    ) as jira:
        assert jira.http.headers["Authorization"] == "Bearer tok"
        assert jira.http.auth is None

    with JiraClient(
        JiraCreds(
            base_url="https://j", auth_mode=JiraAuthMode.BASIC, credential="pw", username="svc"
        )
    ) as jira:
        assert "Authorization" not in jira.http.headers
        assert jira.http.auth is not None


def test_the_client_targets_the_connections_base_url():
    creds = JiraCreds(
        base_url="https://jira.example.com/", auth_mode=JiraAuthMode.PAT, credential="tok"
    )
    with JiraClient(creds) as jira:
        # httpx normalises a base URL with a trailing slash; the trailing slash on
        # the configured URL must not survive into a doubled path.
        assert str(jira.http.base_url) == "https://jira.example.com/rest/api/2/"
    assert client.browse_url(creds, "DEV-1") == "https://jira.example.com/browse/DEV-1"


# --- status -------------------------------------------------------------------


async def test_status_unconfigured_is_a_state_not_an_error(monkeypatch):
    _unconfigure(monkeypatch)
    async with _client_for(_app()) as http:
        response = await http.get(f"{settings.api_prefix}/jira/status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False and body["ok"] is False


async def test_status_live(monkeypatch, _connected):
    async def fake_check(creds):
        return True, "svc-radd", ""

    monkeypatch.setattr(service, "check_connection", fake_check)
    async with _client_for(_app()) as http:
        response = await http.get(f"{settings.api_prefix}/jira/status")
    assert response.status_code == 200
    body = response.json()
    assert body["account"] == "svc-radd" and body["ok"] is True
    assert body["connection_name"] == _connected.name


async def test_status_reports_a_bad_credential_without_failing(monkeypatch):
    """A stale token must render next to the connection, not 500 the page."""

    async def fake_check(creds):
        return False, "", "Jira rejected the credentials (401)"

    monkeypatch.setattr(service, "check_connection", fake_check)
    async with _client_for(_app()) as http:
        response = await http.get(f"{settings.api_prefix}/jira/status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True and body["ok"] is False
    assert "401" in body["error"]


async def test_non_admin_is_forbidden():
    async with _client_for(_app(admin=False)) as http:
        response = await http.get(f"{settings.api_prefix}/jira/projects")
    assert response.status_code == 403


async def test_non_admin_cannot_list_connections():
    async with _client_for(_app(admin=False)) as http:
        response = await http.get(f"{settings.api_prefix}/jira/connections")
    assert response.status_code == 403


# --- projects + preview -------------------------------------------------------


async def test_projects_409_when_no_connection_exists(monkeypatch):
    _unconfigure(monkeypatch)
    async with _client_for(_app()) as http:
        response = await http.get(f"{settings.api_prefix}/jira/projects")
    assert response.status_code == 409


async def test_projects_lists(monkeypatch):
    async def fake_projects(creds):
        return [
            JiraProject(key="TD", name="Tools Dev", id="1"),
            JiraProject(key="DEV", name="Dev", id="2"),
        ]

    monkeypatch.setattr(service, "list_projects", fake_projects)
    async with _client_for(_app()) as http:
        response = await http.get(f"{settings.api_prefix}/jira/projects")
    assert response.status_code == 200
    assert [p["key"] for p in response.json()] == ["TD", "DEV"]


async def test_preview_bad_jql_is_422(monkeypatch):
    async def fake_preview(creds, jql, sample_size, project_key=None):
        raise ValueError("Field 'nope' does not exist")

    monkeypatch.setattr(service, "preview", fake_preview)
    async with _client_for(_app()) as http:
        response = await http.post(
            f"{settings.api_prefix}/jira/preview", json={"jql": "nope = 1"}
        )
    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]


async def test_preview_unreachable_is_409(monkeypatch):
    async def fake_preview(creds, jql, sample_size, project_key=None):
        raise client.JiraUnavailable("could not reach Jira: timeout")

    monkeypatch.setattr(service, "preview", fake_preview)
    async with _client_for(_app()) as http:
        response = await http.post(
            f"{settings.api_prefix}/jira/preview", json={"jql": "project = TD"}
        )
    assert response.status_code == 409


async def test_preview_returns_inferred_schema(monkeypatch):
    from radd.modules.jiraimport.types import InferredField, InferredType

    async def fake_preview(creds, jql, sample_size, project_key=None):
        return 1280, [
            InferredField(
                jira_id="customfield_10001",
                name="Team",
                inferred_type=InferredType.SELECT,
                populated=48,
                sample_count=50,
                is_builtin=False,
                samples=["Platform", "Pipeline"],
                distinct_values=["Pipeline", "Platform"],
            )
        ]

    monkeypatch.setattr(service, "preview", fake_preview)
    async with _client_for(_app()) as http:
        response = await http.post(
            f"{settings.api_prefix}/jira/preview", json={"jql": "project = TD", "sample_size": 50}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1280 and body["sampled"] == 50
    field = body["fields"][0]
    assert field["jira_id"] == "customfield_10001"
    assert field["distinct_values"] == ["Pipeline", "Platform"]
