"""RADD-1034 — the member-floor directory hides mail-provisioned strangers.

`mailintake._sender_user` provisions an ACTIVE `UserSource.EMAIL` account for
every unrecognized sender (RADD-828) — correct, that is how a reply threads
back onto the right ticket. The bug was `GET /users/directory` (the endpoint
behind every people picker, RADD-769) serving those rows to every
authenticated user with no source filter at all: one forged email made
"Stranger <stranger@evil.example>" pickable by anyone, forever.

Tested at the HTTP surface (the `test_view_as.py` idiom: a committed world +
real requests with a real session cookie) because the bug lived in which ROWS
a real request gets back, not in a schema shape — `test_authz.py` already
covers the shape.
"""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import SESSION_COOKIE_NAME, InstanceRole, UserSource
from radd.modules.auth.types import LoginMethod


@pytest.fixture(scope="module")
async def world():
    """COMMITTED: the app under test opens its own sessions per request."""
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        member = User(
            email=f"du-member-{uuid.uuid4().hex[:8]}@example.com",
            name="Ordinary Member",
            instance_role=InstanceRole.MEMBER.value,
            source=UserSource.LOCAL.value,
        )
        admin = User(
            email=f"du-admin-{uuid.uuid4().hex[:8]}@example.com",
            name="Directory Admin",
            instance_role=InstanceRole.ADMIN.value,
            source=UserSource.LOCAL.value,
        )
        # What mailintake._sender_user provisions for an unrecognized sender —
        # active, EMAIL-sourced, no password.
        stranger = User(
            email=f"stranger-{uuid.uuid4().hex[:8]}@evil.example",
            name="Stranger",
            instance_role=InstanceRole.MEMBER.value,
            source=UserSource.EMAIL.value,
            active=True,
        )
        # What service_accounts.create_account provisions (spec 113).
        service_acct = User(
            email=f"svc-{uuid.uuid4().hex[:8]}@service.local",
            name="Automation Bot",
            instance_role=InstanceRole.MEMBER.value,
            source=UserSource.SERVICE.value,
            password_hash="",
        )
        session.add_all([member, admin, stranger, service_acct])
        await session.flush()
        member_cookie = await auth_service.create_session(session, member, method=LoginMethod.PASSWORD)
        admin_cookie = await auth_service.create_session(session, admin, method=LoginMethod.PASSWORD)
        payload = {
            "member_id": str(member.id),
            "admin_id": str(admin.id),
            "stranger_id": str(stranger.id),
            "service_id": str(service_acct.id),
            "member_cookie": member_cookie,
            "admin_cookie": admin_cookie,
        }
        await session.commit()
        yield payload
    await engine.dispose()


@pytest.fixture(scope="module")
def app():
    from radd.app import create_app

    return create_app()


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def _cookies(token: str) -> dict[str, str]:
    return {SESSION_COOKIE_NAME: token}


async def test_directory_excludes_email_accounts_by_default(client, world):
    response = await client.get(
        "/api/v1/users/directory", cookies=_cookies(world["member_cookie"])
    )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert world["stranger_id"] not in ids
    assert world["member_id"] in ids


async def test_include_requesters_returns_them_marked_external(client, world):
    response = await client.get(
        "/api/v1/users/directory",
        params={"include_requesters": "true"},
        cookies=_cookies(world["member_cookie"]),
    )
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}
    assert world["stranger_id"] in rows
    assert rows[world["stranger_id"]]["external"] is True
    # A colleague returned alongside them is NOT marked external.
    assert rows[world["member_id"]]["external"] is False


async def test_service_accounts_are_not_excluded(client, world):
    """The docstrings on `UserDirectoryEntry` and `preflight.py` disagree on
    whether SERVICE rows belong in a people directory — this pins down what the
    code actually does today: present, by default, unlike an EMAIL stranger.
    Unlike a forged sender, a service account is admin-provisioned (spec 113),
    and omitting it would leave the bylines it authors unresolvable — the
    `UserDirectoryEntry` docstring's own argument against filtering it."""
    response = await client.get(
        "/api/v1/users/directory", cookies=_cookies(world["member_cookie"])
    )
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}
    assert world["service_id"] in rows
    assert rows[world["service_id"]]["source"] == "service"
    assert rows[world["service_id"]]["external"] is False


async def test_settings_users_admin_list_is_unaffected(client, world):
    """`GET /users` (Settings → Users, gated on `user.manage`) must keep
    seeing EMAIL accounts — the RADD-1034 exclusion is scoped to the member
    directory endpoint, not to `list_users`/`count_users` globally."""
    response = await client.get(
        "/api/v1/users",
        params={"limit": 500},
        cookies=_cookies(world["admin_cookie"]),
    )
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}
    assert world["stranger_id"] in rows
    assert rows[world["stranger_id"]]["source"] == "email"
