"""RADD-828 — the requester model.

An email-provisioned account (`UserSource.EMAIL`) cannot log in, and its
permission floor is the seeded Requester role — item.read@own + commenting —
NEVER the Baseline. Mail ingest provisions the account (reporter, reused on
the second email), and the anonymous /public/forms surface is gone entirely.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import UnauthorizedError
from radd.modules.auth import authz, grants, service as auth
from radd.modules.auth.roles import role_by_key
from radd.modules.auth.types import BuiltinRoleKey, Permission, UserSource


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _email_user(db):
    email = f"req-{uuid.uuid4().hex[:8]}@customers.example.com"
    return await auth.ensure_imported_user(
        db, email=email, name="Walk-in Requester", source=UserSource.EMAIL
    )


async def test_email_source_cannot_log_in(db):
    user, created = await _email_user(db)
    assert created and user.source == UserSource.EMAIL.value
    # create_session is the one seam every login path (local, TOTP, LDAP,
    # OIDC) mints through — refusing there refuses them all at once.
    with pytest.raises(UnauthorizedError, match="sign in with SSO"):
        await auth.create_session(db, user)


async def test_email_floor_is_requester_not_baseline(db):
    user, _ = await _email_user(db)
    perms = await authz.effective_permissions(db, user)
    # The Requester trio…
    assert "item.read@own" in perms
    assert Permission.COMMENT_WRITE in perms
    assert Permission.ATTACHMENT_CREATE in perms
    # …and none of the Baseline's staff surface.
    assert Permission.ITEM_READ not in perms
    assert Permission.PAGE_READ not in perms
    assert Permission.LABEL_READ not in perms


async def test_staff_floor_is_still_baseline(db):
    user, _ = await auth.ensure_imported_user(
        db,
        email=f"staff-{uuid.uuid4().hex[:8]}@example.com",
        name="Staff Import",
        source=UserSource.LDAP,
    )
    floor = await authz.floor_permissions(db, user)
    requester = await role_by_key(db, BuiltinRoleKey.REQUESTER.value)
    baseline = await role_by_key(db, BuiltinRoleKey.BASELINE.value)
    assert floor == set(baseline.permissions)
    assert floor != set(requester.permissions)


async def test_explicit_grants_still_add_to_a_requester(db):
    """The Requester floor replaces the BASELINE only — a deliberate role
    grant to the person still applies (upgrading a known customer)."""
    user, _ = await _email_user(db)
    member = await role_by_key(db, BuiltinRoleKey.MEMBER.value)
    await grants.create_grant(db, role_id=member.id, user_id=user.id)
    await db.commit()
    perms = await authz.effective_permissions(db, user)
    assert Permission.ITEM_READ in perms  # via the explicit Member grant


async def test_public_forms_routes_are_gone():
    from radd.app import create_app

    app = create_app()
    paths = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        candidates = getattr(route, "effective_candidates", None)
        if candidates is not None:
            stack.extend(candidates())
            continue
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
    public_form_paths = {p for p in paths if "/public/forms" in p}
    assert public_form_paths == set()
    # …while the D9 survivors stay.
    assert any("/public/pages" in p for p in paths)
    assert any("/public/csat" in p for p in paths)


async def test_mail_ingest_provisions_and_reuses_the_requester(db):
    """An unknown sender becomes an EMAIL-source account; the second email
    from the same address reuses it instead of forking a duplicate."""
    from radd.modules.mailintake.parsing import EmailPlan
    from radd.modules.mailintake.poller import _sender_user

    email = f"cust-{uuid.uuid4().hex[:8]}@customers.example.com"
    plan = EmailPlan(
        subject="Printer on fire",
        sender_name="Pat Customer",
        sender_email=email,
        body="please help",
        item_key=None,
    )
    first = await _sender_user(db, plan)
    assert first is not None
    assert first.source == UserSource.EMAIL.value
    assert first.name == "Pat Customer"

    second = await _sender_user(db, plan)
    assert second is not None and second.id == first.id
