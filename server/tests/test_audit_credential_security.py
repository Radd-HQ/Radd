"""HTTP regressions for credential delegation and scope-aware admin gates."""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth import service
from radd.modules.auth.models import User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME


@pytest.fixture
async def credentials():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        admin = User(email=f"audit-{uuid.uuid4()}@example.com", name="Audit", instance_role="admin")
        robot = User(email=f"audit-{uuid.uuid4()}@example.com", name="Robot", source="service")
        db.add_all([admin, robot])
        await db.flush()
        cookie = await service.create_session(db, admin)
        tokens = []
        for user, scope in ((admin, {}), (admin, {"global": ["item.read"]}), (robot, {})):
            _, raw = await service.create_api_token(
                db, user, TokenCreate(name="limited", scopes=scope)
            )
            tokens.append(raw)
        await db.commit()
    await engine.dispose()
    return cookie, tokens


async def test_keys_cannot_delegate_or_bypass_admin_scope(credentials):
    from radd.app import create_app

    cookie, tokens = credentials
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        for token in tokens:
            headers = {"Authorization": f"Bearer {token}"}
            for method, path, payload in (
                ("POST", "/tokens", {"name": "unrestricted"}),
                ("POST", "/tokens", {"name": "forever", "expires_at": "2099-01-01T00:00:00Z"}),
                ("GET", "/tokens", None),
                ("GET", "/backups/status", None),
                ("PUT", "/plugins/ai/contribution-settings", {"disabled": []}),
                ("GET", "/scoped-settings?scope=instance", None),
                ("PATCH", "/auth/me", {"name": "Hijacked"}),
            ):
                response = await client.request(
                    method, "/api/v1" + path, headers=headers, json=payload
                )
                assert response.status_code == 403, (method, path, response.text)
        response = await client.post(
            "/api/v1/tokens", json={"name": "session-issued"}, cookies={SESSION_COOKIE_NAME: cookie}
        )
        assert response.status_code == 201
        response = await client.get(
            "/api/v1/plugins/contribution-settings", cookies={SESSION_COOKIE_NAME: cookie}
        )
        assert response.status_code == 200
        for scope in ({"projects": ["bad"]}, {"projects": "bad"}, {"global": False}):
            response = await client.post(
                "/api/v1/tokens",
                json={"name": "malformed", "scopes": scope},
                cookies={SESSION_COOKIE_NAME: cookie},
            )
            assert response.status_code == 422


def test_login_limits_account_ip_expiry_and_memory(monkeypatch):
    from fastapi import HTTPException
    from radd.modules.auth.throttle import LoginThrottle

    monkeypatch.setattr(settings, "auth_login_account_attempts", 2)
    monkeypatch.setattr(settings, "auth_login_ip_attempts", 3)
    monkeypatch.setattr(settings, "auth_login_window_seconds", 10)
    monkeypatch.setattr(settings, "auth_login_bucket_limit", 4)
    limiter = LoginThrottle()
    limiter.check("A@example.com", "1", now=0)
    limiter.check("a@example.com", "2", now=1)
    with pytest.raises(HTTPException) as denied:
        limiter.check(" A@example.com ", "3", now=2)
    assert denied.value.status_code == 429
    assert denied.value.headers["Retry-After"] == "8"
    limiter.check("a@example.com", "1", now=11)
    assert len(limiter.buckets) <= 4


async def test_password_verification_leaves_event_loop_responsive(monkeypatch):
    import asyncio
    import threading
    from radd.modules.auth import security

    entered, release = threading.Event(), threading.Event()

    def slow_verify(*args):
        entered.set()
        assert release.wait(2)
        return True

    monkeypatch.setattr(security, "verify_password", slow_verify)
    task = asyncio.create_task(security.verify_password_async("secret", "hash"))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        assert not task.done()
    finally:
        release.set()
    assert await task


@pytest.mark.parametrize(
    "path,body",
    [
        ("/auth/login", {"email": "throttle@example.com", "password": "wrong-password"}),
        (
            "/auth/login/totp",
            {"email": "throttle@example.com", "password": "wrong-password", "code": "123456"},
        ),
        ("/auth/ldap/login", {"username": "throttle", "password": "wrong-password"}),
    ],
)
async def test_all_password_login_routes_share_admission_limits(monkeypatch, path, body):
    from radd.app import create_app
    from radd.modules.auth import throttle

    limiter = throttle.LoginThrottle()
    monkeypatch.setattr(throttle, "login_throttle", limiter)
    monkeypatch.setattr(settings, "auth_login_account_attempts", 1)
    limiter.check(body.get("email", body.get("username")), "127.0.0.1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1" + path, json=body)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
