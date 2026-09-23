"""Spec 113: service accounts, and keys that carry less authority than their account.

The invariant everything else rests on is the CEILING: a key's scope narrows, it
never grants. A scope naming `global.manage` on an account holding only
`item.read` must resolve to `item.read` — otherwise a scope would be a privilege
escalation primitive rather than a restriction.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import UnauthorizedError
from radd.modules.auth import authz, scopes, service, service_accounts
from radd.modules.auth.models import User
from radd.modules.auth.schemas import ServiceAccountCreate, TokenCreate
from radd.modules.auth.types import InstanceRole, Permission, UserSource
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.auth.types import LoginMethod


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"SA{uuid.uuid4().hex[:4].upper()}", name="Service accounts")
    )


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"sa-admin-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


# --- the ceiling ---


async def test_a_scope_narrows_and_never_grants(db, admin, project):
    """An admin holds everything. A key scoped to item.read holds item.read."""
    admin.token_scope = scopes.parse_scope({"projects": {str(project.id): ["item.read"]}})

    resolved = await authz.effective_permissions(db, admin, project=project)
    assert resolved == frozenset({Permission.ITEM_READ})
    assert Permission.GLOBAL_MANAGE not in resolved
    assert Permission.ITEM_CREATE not in resolved


async def test_a_scope_cannot_exceed_the_account(db, project):
    """The account holds item.read via the member floor; the key asks for
    global.manage. The intersection is what the account has, not what the key
    claims."""
    member = User(
        email=f"sa-member-{uuid.uuid4().hex[:8]}@example.com",
        name="Member",
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(member)
    await db.flush()

    unscoped = await authz.effective_permissions(db, member, project=project)
    assert Permission.GLOBAL_MANAGE not in unscoped  # the premise

    member.token_scope = scopes.parse_scope(
        {"global": ["global.manage"], "projects": {str(project.id): ["global.manage"]}}
    )
    assert Permission.GLOBAL_MANAGE not in await authz.effective_permissions(
        db, member, project=project
    )


async def test_a_project_absent_from_the_scope_yields_nothing(db, admin, project):
    other = await projects_service.create_project(
        db, ProjectCreate(key=f"SB{uuid.uuid4().hex[:4].upper()}", name="Other")
    )
    admin.token_scope = scopes.parse_scope({"projects": {str(project.id): ["item.read"]}})

    assert await authz.effective_permissions(db, admin, project=project)
    assert await authz.effective_permissions(db, admin, project=other) == frozenset()


async def test_the_batched_path_narrows_too(db, admin, project):
    """List hydration resolves permissions in a batch; if that path skipped the
    scope, a scoped key would see full authority anywhere a list is rendered."""
    admin.token_scope = scopes.parse_scope({"projects": {str(project.id): ["item.read"]}})

    batched = await authz.permissions_for_projects(db, admin, [project])
    assert batched[project.id] == frozenset({Permission.ITEM_READ})


async def test_global_atoms_apply_inside_a_project(db, admin, project):
    """A global-scoped atom is checked with project=None on some paths and inside
    a project on others; the scope must not make the answer depend on which."""
    admin.token_scope = scopes.parse_scope({"global": ["page.read", "item.read"]})

    assert Permission.PAGE_READ in await authz.effective_permissions(db, admin)
    assert Permission.PAGE_READ in await authz.effective_permissions(db, admin, project=project)


async def test_unscoped_is_unchanged(db, admin, project):
    """The personal-token path: no scope, no narrowing, byte-identical behaviour."""
    assert admin.token_scope is None
    assert await authz.effective_permissions(db, admin, project=project) == (
        await authz.effective_permissions(db, admin, project=project)
    )
    assert Permission.GLOBAL_MANAGE in await authz.effective_permissions(db, admin)


async def test_revoking_the_account_grant_narrows_the_key_with_no_key_edit(db, project):
    """Deactivating the account is the fastest form of demotion — the key stops
    working immediately, with no token change."""
    account = await service_accounts.create_account(
        db, ServiceAccountCreate(name=f"Agent {uuid.uuid4().hex[:6]}")
    )
    account.token_scope = scopes.parse_scope({"projects": {str(project.id): ["item.read"]}})
    assert await authz.effective_permissions(db, account, project=project)

    account.active = False
    await db.flush()
    assert await authz.effective_permissions(db, account, project=project) == frozenset()


# --- the account itself ---


async def test_service_accounts_cannot_log_in(db):
    account = await service_accounts.create_account(
        db, ServiceAccountCreate(name=f"No login {uuid.uuid4().hex[:6]}")
    )
    assert account.source == UserSource.SERVICE.value
    # create_session is the seam every login path mints through — local, TOTP,
    # LDAP and OIDC alike — so one refusal covers all of them.
    with pytest.raises(UnauthorizedError):
        await service.create_session(db, account, method=LoginMethod.PASSWORD)


async def test_keys_are_mintable_by_an_admin_and_carry_their_scope(db, project):
    account = await service_accounts.create_account(
        db, ServiceAccountCreate(name=f"Keyed {uuid.uuid4().hex[:6]}")
    )
    token, raw = await service_accounts.create_key(
        db,
        account.id,
        TokenCreate(
            name="agent", scopes={"projects": {str(project.id): ["item.read", "item.create"]}}
        ),
    )
    assert raw.startswith("radd_pat_")
    assert token.scopes["projects"][str(project.id)] == ["item.create", "item.read"]

    # ...and the round trip through authentication reconstructs it
    authenticated = await service.user_for_api_token(db, raw)
    assert authenticated is not None
    assert authenticated.token_scope.allowed(project.id) == frozenset(
        {Permission.ITEM_READ, Permission.ITEM_CREATE}
    )


async def test_an_unknown_atom_is_refused_at_write_time(db):
    account = await service_accounts.create_account(
        db, ServiceAccountCreate(name=f"Bad scope {uuid.uuid4().hex[:6]}")
    )
    with pytest.raises(ValueError, match="unknown permission atom"):
        await service_accounts.create_key(
            db, account.id, TokenCreate(name="bad", scopes={"global": ["item.teleport"]})
        )


async def test_synthetic_emails_are_slugged_and_undeliverable():
    assert service_accounts.synthetic_email("Radd Agent") == "radd-agent@service.radd.local"
    assert service_accounts.synthetic_email("  CI/CD  bot ") == "ci-cd-bot@service.radd.local"


# --- the pure layer ---


def test_scope_round_trips_and_reports_its_projects():
    project_id = uuid.uuid4()
    scope = scopes.parse_scope(
        {"global": ["page.read"], "projects": {str(project_id): ["item.create"]}}
    )
    assert scope.to_json() == {
        "global": ["page.read"],
        "projects": {str(project_id): ["item.create"]},
    }
    # (projects_allowing was deleted as dead product code, RADD-893 — the live
    # per-project resolution is mcp/requirements.py's, covered by test_mcp.)


def test_scope_shape_is_validated():
    assert scopes.parse_scope(None) is None
    with pytest.raises(ValueError, match="must be an object"):
        scopes.parse_scope(["item.read"])
    with pytest.raises(ValueError, match="not a uuid"):
        scopes.parse_scope({"projects": {"not-a-uuid": ["item.read"]}})
    with pytest.raises(ValueError, match="list of permission atoms"):
        scopes.parse_scope({"global": "item.read"})
