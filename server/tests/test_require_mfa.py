"""RADD-1279 — an instance can require a second factor.

The negative is the point: with `require_mfa` on, a password with no second
factor is refused AT `create_session` (not hidden in the SPA), the refusal
hands out a ticket that opens enrolment and nothing else, and the paths the
policy does not cover (LDAP, SSO, an enrolled account's code step) are
untouched. Everything runs inside one rolled-back session.
"""

import time
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.exceptions import ConflictError
from radd.modules.auth import mfa_policy, service as auth_service, totp
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME, InstanceRole, LoginMethod
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope

PASSWORD = "require-mfa-pass-1"


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def client(db):
    app = create_app()

    async def override():
        yield db

    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _user(db, *, role: InstanceRole = InstanceRole.MEMBER):
    return await auth_service.create_user(
        db,
        UserCreate(
            email=f"mfa-{uuid.uuid4().hex[:8]}@example.com",
            name="MFA Probe",
            password=PASSWORD,
            instance_role=role,
        ),
    )


async def _enrol(db, user) -> str:
    row = await auth_service.totp_setup(db, user)
    await auth_service.totp_confirm(db, user, totp.code_at(row.secret, int(time.time())))
    return row.secret


async def _policy(db, on: bool) -> None:
    # actor_id=None: the seed/system path, which the guard does not gate.
    await settings_service.set_value(db, SettingKey.REQUIRE_MFA, SettingScope.INSTANCE, None, on)


async def _login(client, user):
    return await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})


async def test_policy_off_changes_nothing(db, client):
    user = await _user(db)
    response = await _login(client, user)
    assert response.status_code == 204
    assert SESSION_COOKIE_NAME in response.cookies


async def test_policy_on_refuses_at_create_session(db):
    """The seam itself refuses — not a check a route could forget."""
    user = await _user(db)
    await _policy(db, True)
    with pytest.raises(mfa_policy.MfaEnrollmentRequired):
        await auth_service.create_session(db, user, method=LoginMethod.PASSWORD)
    # The IdP owns MFA for directory and SSO sign-ins, and a code step is MFA.
    for method in (LoginMethod.LDAP, LoginMethod.SSO, LoginMethod.PASSWORD_TOTP):
        assert await auth_service.create_session(db, user, method=method)


async def test_refused_login_gets_a_ticket_that_opens_enrolment_only(db, client):
    user = await _user(db)
    await _policy(db, True)

    refused = await _login(client, user)
    assert refused.status_code == 401
    assert refused.json()["detail"] == mfa_policy.MFA_ENROLLMENT_REQUIRED
    assert SESSION_COOKIE_NAME not in refused.cookies
    ticket = refused.json()["enrollment_ticket"]

    # The ticket is not a session: presented as one, it opens nothing.
    as_cookie = await client.get("/api/v1/auth/me", cookies={SESSION_COOKIE_NAME: ticket})
    assert as_cookie.json().get("anonymous") is True or as_cookie.status_code == 401
    as_bearer = await client.get("/api/v1/auth/totp", headers={"Authorization": f"Bearer {ticket}"})
    assert as_bearer.status_code == 401

    setup = await client.post("/api/v1/auth/mfa-enrollment/setup", json={"ticket": ticket})
    assert setup.status_code == 200
    secret = setup.json()["secret"]

    wrong = await client.post(
        "/api/v1/auth/mfa-enrollment/confirm", json={"ticket": ticket, "code": "000000"}
    )
    assert wrong.status_code == 401 and SESSION_COOKIE_NAME not in wrong.cookies

    confirmed = await client.post(
        "/api/v1/auth/mfa-enrollment/confirm",
        json={"ticket": ticket, "code": totp.code_at(secret, int(time.time()))},
    )
    assert confirmed.status_code == 200
    assert len(confirmed.json()["recovery_codes"]) == totp.RECOVERY_CODE_COUNT
    assert SESSION_COOKIE_NAME in confirmed.cookies
    assert await mfa_policy.is_enrolled(db, user.id)

    # Single use: the confirm burned it.
    replay = await client.post("/api/v1/auth/mfa-enrollment/setup", json={"ticket": ticket})
    assert replay.status_code == 401


async def test_enrolled_account_keeps_the_existing_two_step(db, client):
    user = await _user(db)
    secret = await _enrol(db, user)
    await _policy(db, True)
    first = await _login(client, user)
    assert first.status_code == 401 and first.json()["detail"] == "totp_required"
    second = await client.post(
        "/api/v1/auth/login/totp",
        json={"email": user.email, "password": PASSWORD, "code": totp.code_at(secret, int(time.time()))},
    )
    assert second.status_code == 204 and SESSION_COOKIE_NAME in second.cookies


async def test_an_expired_ticket_is_refused(db, client):
    user = await _user(db)
    raw = await mfa_policy.issue_ticket(db, user)
    row = await mfa_policy._live_ticket(db, raw)
    row.expires_at = row.created_at  # already past
    await db.flush()
    response = await client.post("/api/v1/auth/mfa-enrollment/setup", json={"ticket": raw})
    assert response.status_code == 401


async def test_the_switch_cannot_lock_out_the_admin_flipping_it(db):
    admin = await _user(db, role=InstanceRole.ADMIN)
    with pytest.raises(ConflictError):
        await settings_service.set_value(
            db, SettingKey.REQUIRE_MFA, SettingScope.INSTANCE, None, True, actor_id=admin.id
        )
    await _enrol(db, admin)
    assert await settings_service.set_value(
        db, SettingKey.REQUIRE_MFA, SettingScope.INSTANCE, None, True, actor_id=admin.id
    ) is True
    # Turning it off is never gated.
    await settings_service.set_value(
        db, SettingKey.REQUIRE_MFA, SettingScope.INSTANCE, None, False, actor_id=admin.id
    )


async def test_admin_sees_enrolment_and_can_reset_it(db, client):
    admin = await _user(db, role=InstanceRole.ADMIN)
    person = await _user(db)
    await _enrol(db, person)
    cookie = await auth_service.create_session(db, admin, method=LoginMethod.PASSWORD_TOTP)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)

    listed = await client.get("/api/v1/users", params={"q": person.email})
    assert [u["mfa_enabled"] for u in listed.json() if u["id"] == str(person.id)] == [True]

    reset = await client.delete(f"/api/v1/users/{person.id}/totp")
    assert reset.status_code == 204
    assert not await mfa_policy.is_enrolled(db, person.id)
    again = await client.delete(f"/api/v1/users/{person.id}/totp")
    assert again.status_code == 409


async def test_a_member_cannot_reset_someone_elses_mfa(db, client):
    member = await _user(db)
    person = await _user(db)
    await _enrol(db, person)
    client.cookies.set(
        SESSION_COOKIE_NAME,
        await auth_service.create_session(db, member, method=LoginMethod.PASSWORD_TOTP),
    )
    response = await client.delete(f"/api/v1/users/{person.id}/totp")
    assert response.status_code == 403
    assert await mfa_policy.is_enrolled(db, person.id)
