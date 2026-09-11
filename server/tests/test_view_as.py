"""RADD-836 U1 — "View as": read-only admin impersonation, at the HTTP surface.

The guard lives on the auth resolution seam (deps.py), so this is tested the
only way that cannot pass vacuously: real requests with a real session cookie.
Admin-only to start; while previewing, /auth/me describes the TARGET and names
the real admin; every write except exit/logout refuses; entry and exit are
events. Each assertion failed before the feature existed (404s / missing
fields).
"""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME, InstanceRole
from radd.modules.events.models import Event


@pytest.fixture(scope="module")
async def world():
    """COMMITTED: the app under test opens its own sessions."""
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        admin = User(
            email=f"va-admin-{uuid.uuid4().hex[:8]}@example.com",
            name="Admin",
            instance_role=InstanceRole.ADMIN.value,
        )
        member = User(
            email=f"va-member-{uuid.uuid4().hex[:8]}@example.com",
            name="Member",
            instance_role=InstanceRole.MEMBER.value,
        )
        session.add_all([admin, member])
        await session.flush()
        admin_cookie = await auth_service.create_session(session, admin)
        member_cookie = await auth_service.create_session(session, member)
        _, admin_pat = await auth_service.create_api_token(
            session, admin, TokenCreate(name="va")
        )
        payload = {
            "admin_id": str(admin.id),
            "member_id": str(member.id),
            "admin_cookie": admin_cookie,
            "member_cookie": member_cookie,
            "admin_pat": admin_pat,
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


async def test_only_an_admin_starts_a_preview(client, world):
    response = await client.post(
        "/api/v1/auth/view-as",
        json={"user_id": world["admin_id"]},
        cookies=_cookies(world["member_cookie"]),
    )
    assert response.status_code == 403


async def test_a_pat_has_no_session_to_preview_on(client, world):
    response = await client.post(
        "/api/v1/auth/view-as",
        json={"user_id": world["member_id"]},
        headers={"Authorization": f"Bearer {world['admin_pat']}"},
    )
    assert response.status_code == 403


async def test_preview_resolves_reads_refuses_writes_and_audits(client, world):
    cookies = _cookies(world["admin_cookie"])
    started = await client.post(
        "/api/v1/auth/view-as", json={"user_id": world["member_id"]}, cookies=cookies
    )
    assert started.status_code == 204

    # Reads resolve as the TARGET, and the payload names the real admin.
    me = (await client.get("/api/v1/auth/me", cookies=cookies)).json()
    assert me["id"] == world["member_id"]
    assert me["view_as"]["real_id"] == world["admin_id"]

    # EVERY write refuses — including ones the member could make themselves.
    write = await client.post(
        "/api/v1/views", json={"name": "sneaky", "kind": "list"}, cookies=cookies
    )
    assert write.status_code == 403
    assert "read-only" in write.json()["detail"]

    # Exit is the one exempt write; afterwards the admin is themselves again.
    ended = await client.delete("/api/v1/auth/view-as", cookies=cookies)
    assert ended.status_code == 204
    me = (await client.get("/api/v1/auth/me", cookies=cookies)).json()
    assert me["id"] == world["admin_id"]
    assert me.get("view_as") is None

    # Entry and exit are events naming the target, actored by the admin.
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        rows = (
            await session.execute(
                select(Event.event_type, Event.actor_id).where(
                    Event.event_type.in_(["auth.view_as_started", "auth.view_as_ended"]),
                    Event.entity_id == world["member_id"],
                )
            )
        ).all()
    await engine.dispose()
    kinds = {row.event_type for row in rows}
    assert kinds == {"auth.view_as_started", "auth.view_as_ended"}
    assert all(str(row.actor_id) == world["admin_id"] for row in rows)
