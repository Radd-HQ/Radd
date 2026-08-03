"""SSO provider registry + federated identity linking (spec 110).

The invariants sign-in leans on:

  * the signup allowlist gates CREATION only — an existing account signs in from
    any domain, a stranger from an unlisted one never gets an account;
  * a Google login lands on the person's existing AD account instead of forking a
    duplicate, and that account keeps its source, role and history;
  * a provider with no admin groups configured has NO opinion about roles, so
    linking can't demote the admin it just linked to (the spec-40 bug);
  * identity is pinned to the IdP's subject after the first login, so a mailbox
    rename doesn't fork the account and a recycled address can't inherit one;
  * an unverified email is never trusted, because both linking and creation key
    off the address.

CRUD tests are flushed, never committed; the session rolls back at teardown.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole, UserSource
from radd.modules.sso import registry, service
from radd.modules.sso.models import UserIdentity
from radd.modules.sso.schemas import SsoProviderCreate, SsoProviderUpdate
from radd.modules.sso.types import WILDCARD_DOMAIN, SsoKind


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _provider(db, **overrides):
    payload = {
        "name": f"google-{uuid.uuid4().hex[:8]}",
        "kind": SsoKind.GOOGLE,
        "client_id": "client-1",
        "client_secret": "secret-1",
        "allowed_signup_domains": ["hjarrar.com", "radd-hq.com"],
    }
    payload.update(overrides)
    return await registry.create_provider(db, SsoProviderCreate(**payload))


async def _user(db, email, name="Test Person", *, source=UserSource.LOCAL, role=None) -> User:
    user = User(
        email=email,
        name=name,
        source=source,
        instance_role=(role or InstanceRole.MEMBER).value,
    )
    db.add(user)
    await db.flush()
    return user


def _claims(email, sub="google-sub-1", *, verified=True, **extra):
    claims = {"sub": sub, "email": email, "email_verified": verified, "name": "Test Person"}
    claims.update(extra)
    return claims


# --- the signup allowlist -----------------------------------------------------


async def test_allowed_domain_creates_an_account(db):
    provider = await _provider(db)
    email = f"new-{uuid.uuid4().hex[:6]}@radd-hq.com"

    user = await service.provision(db, provider, _claims(email))

    assert user.email == email
    assert user.source == UserSource.OIDC
    assert user.password_hash is None  # SSO-only account


async def test_unlisted_domain_is_refused(db):
    provider = await _provider(db)

    with pytest.raises(ForbiddenError) as exc:
        await service.provision(db, provider, _claims("stranger@example.com"))

    # The message must name the fix, not the rule — it is read on the login page.
    assert "example.com" in str(exc.value)
    assert await db.scalar(select(User).where(User.email == "stranger@example.com")) is None


async def test_empty_allowlist_means_no_signups(db):
    """A provider added without a list must not quietly let the internet in."""
    provider = await _provider(db, allowed_signup_domains=[])

    with pytest.raises(ForbiddenError):
        await service.provision(db, provider, _claims("anyone@radd-hq.com"))


async def test_wildcard_opts_out_of_the_allowlist(db):
    provider = await _provider(db, allowed_signup_domains=[WILDCARD_DOMAIN])
    email = f"anyone-{uuid.uuid4().hex[:6]}@wherever.example"

    user = await service.provision(db, provider, _claims(email))

    assert user.email == email


async def test_auto_provision_off_refuses_even_a_listed_domain(db):
    provider = await _provider(db, auto_provision=False)

    with pytest.raises(ForbiddenError):
        await service.provision(db, provider, _claims("new@radd-hq.com"))


async def test_existing_account_signs_in_from_an_unlisted_domain(db):
    """The list gates CREATION, not sign-in — a contractor already on the
    instance must not be locked out because their domain isn't listed."""
    provider = await _provider(db)
    email = f"contractor-{uuid.uuid4().hex[:6]}@somewhere-else.com"
    existing = await _user(db, email)

    user = await service.provision(db, provider, _claims(email))

    assert user.id == existing.id


async def test_domains_are_normalized_on_write(db):
    """People paste '@Radd-HQ.com' and whole addresses; a list that silently
    doesn't match is a support ticket."""
    provider = await _provider(
        db, allowed_signup_domains=["@Radd-HQ.com", "hussein@HJarrar.com", " example.com "]
    )

    assert provider.allowed_signup_domains == ["radd-hq.com", "hjarrar.com", "example.com"]


# --- linking to an existing AD account ----------------------------------------


async def test_google_login_joins_the_existing_ad_account(db):
    provider = await _provider(db)
    email = f"hjarrar-{uuid.uuid4().hex[:6]}@example.com"
    ad_user = await _user(db, email, source=UserSource.LDAP)

    user = await service.provision(db, provider, _claims(email, sub="sub-ad-link"))

    assert user.id == ad_user.id, "must reuse the AD account, not fork a duplicate"
    assert user.source == UserSource.LDAP, "the account keeps its directory origin"
    identity = await db.scalar(
        select(UserIdentity).where(UserIdentity.provider_id == provider.id)
    )
    assert identity is not None and identity.user_id == ad_user.id


async def test_linking_does_not_demote_an_ad_admin(db):
    """The spec-40 bug: instance_role was written unconditionally, so a Google
    login — which ships no group claim at all — demoted the admin it linked to."""
    provider = await _provider(db, admin_groups="")  # no role opinion
    email = f"admin-{uuid.uuid4().hex[:6]}@example.com"
    await _user(db, email, source=UserSource.LDAP, role=InstanceRole.ADMIN)

    user = await service.provision(db, provider, _claims(email, sub="sub-admin"))

    assert user.instance_role == InstanceRole.ADMIN.value


async def test_a_provider_with_admin_groups_does_sync_the_role(db):
    provider = await _provider(db, admin_groups="radd-admins", group_claim="groups")
    email = f"lead-{uuid.uuid4().hex[:6]}@radd-hq.com"

    user = await service.provision(
        db, provider, _claims(email, sub="sub-groups", groups=["radd-admins", "staff"])
    )
    assert user.instance_role == InstanceRole.ADMIN.value

    # …and out of the group demotes on the next login (spec 40 semantics kept).
    user = await service.provision(db, provider, _claims(email, sub="sub-groups", groups=["staff"]))
    assert user.instance_role == InstanceRole.MEMBER.value


async def test_deactivated_account_is_refused(db):
    provider = await _provider(db)
    email = f"gone-{uuid.uuid4().hex[:6]}@radd-hq.com"
    user = await _user(db, email)
    user.active = False
    await db.flush()

    with pytest.raises(ForbiddenError, match="deactivated"):
        await service.provision(db, provider, _claims(email))


# --- subject pinning ----------------------------------------------------------


async def test_second_login_follows_the_subject_not_the_email(db):
    """A rename in AD must not fork the account."""
    provider = await _provider(db)
    email = f"before-{uuid.uuid4().hex[:6]}@radd-hq.com"
    first = await service.provision(db, provider, _claims(email, sub="stable-sub"))

    renamed = f"after-{uuid.uuid4().hex[:6]}@radd-hq.com"
    again = await service.provision(db, provider, _claims(renamed, sub="stable-sub"))

    assert again.id == first.id
    assert await db.scalar(select(User).where(User.email == renamed)) is None


async def test_a_recycled_address_cannot_inherit_the_pinned_account(db):
    """Same email, DIFFERENT subject = a different human. They get their own
    account (allowlist permitting), never the leaver's."""
    provider = await _provider(db)
    email = f"shared-{uuid.uuid4().hex[:6]}@radd-hq.com"
    leaver = await service.provision(db, provider, _claims(email, sub="sub-leaver"))
    # The leaver's account is renamed away, freeing the address.
    leaver.email = f"leaver-{uuid.uuid4().hex[:6]}@radd-hq.com"
    await db.flush()

    newcomer = await service.provision(db, provider, _claims(email, sub="sub-newcomer"))

    assert newcomer.id != leaver.id


# --- verified email -----------------------------------------------------------


async def test_unverified_email_is_refused(db):
    provider = await _provider(db)

    with pytest.raises(ForbiddenError, match="verified"):
        await service.provision(db, provider, _claims("new@radd-hq.com", verified=False))


async def test_unverified_email_cannot_hijack_an_existing_account(db):
    """The account-takeover vector that linking-by-email opens if unguarded."""
    provider = await _provider(db)
    email = f"target-{uuid.uuid4().hex[:6]}@example.com"
    await _user(db, email, source=UserSource.LDAP, role=InstanceRole.ADMIN)

    with pytest.raises(ForbiddenError, match="verified"):
        await service.provision(db, provider, _claims(email, sub="attacker", verified=False))


async def test_string_true_counts_as_verified(db):
    """Enough issuers send the string "true" that treating it as unverified
    would be a false negative."""
    provider = await _provider(db)
    email = f"stringy-{uuid.uuid4().hex[:6]}@radd-hq.com"

    user = await service.provision(db, provider, _claims(email, verified="true"))

    assert user.email == email


async def test_require_verified_email_can_be_switched_off(db):
    provider = await _provider(db, require_verified_email=False)
    email = f"terse-idp-{uuid.uuid4().hex[:6]}@radd-hq.com"

    user = await service.provision(db, provider, _claims(email, verified=None))

    assert user.email == email


# --- registry mechanics -------------------------------------------------------


async def test_google_kind_supplies_the_issuer_and_scopes(db):
    """An admin pastes a client id/secret and nothing else."""
    provider = await _provider(db, issuer="", scopes="")

    assert registry.issuer_of(provider) == "https://accounts.google.com"
    assert "openid" in registry.scopes_of(provider)
    assert registry.configured(provider)


async def test_generic_oidc_requires_an_issuer(db):
    with pytest.raises(ConflictError):
        await _provider(db, kind=SsoKind.OIDC, issuer="")


async def test_a_row_without_credentials_is_not_on_the_login_page(db):
    provider = await _provider(db, client_id="", client_secret="")

    assert not registry.configured(provider)
    await registry.refresh_snapshot(db)
    assert all(entry["id"] != str(provider.id) for entry in registry.snapshot())


async def test_empty_secret_on_update_keeps_the_stored_one(db):
    provider = await _provider(db)

    await registry.update_provider(db, provider.id, SsoProviderUpdate(client_secret=""))

    assert provider.client_secret == "secret-1"


async def test_duplicate_names_are_rejected(db):
    name = f"dupe-{uuid.uuid4().hex[:8]}"
    await _provider(db, name=name)

    with pytest.raises(ConflictError):
        await _provider(db, name=name)


# --- the provider's default role grant (RADD-777) -----------------------------


async def _member_role(db):
    """The seeded Member row.

    Seeded here rather than assumed: `ensure_builtin_roles` runs on app startup,
    and these tests talk to the session directly without one. It is idempotent,
    so calling it costs nothing when another test got there first.
    """
    from radd.modules.auth import roles as roles_service
    from radd.modules.auth.models import Role

    await roles_service.ensure_builtin_roles(db)
    await db.flush()
    return (await db.execute(select(Role).where(Role.key == "member"))).scalar_one()


async def _grants_for(db, user_id):
    from radd.modules.auth.models import GlobalRoleGrant

    rows = await db.execute(select(GlobalRoleGrant).where(GlobalRoleGrant.user_id == user_id))
    return rows.scalars().all()


async def test_default_role_is_granted_when_the_provider_creates_the_account(db):
    role = await _member_role(db)
    provider = await _provider(db, default_grants=[{"role_id": role.id}])

    user = await service.provision(db, provider, _claims(f"new-{uuid.uuid4().hex[:6]}@radd-hq.com"))

    held = await _grants_for(db, user.id)
    assert [(g.role_id, g.project_id) for g in held] == [(role.id, None)]


async def test_the_default_grant_is_never_re_applied(db):
    """The whole point, and the reason it is a GRANT rather than a field.

    Spec 40 wrote `instance_role` on EVERY login, so an AD-provisioned admin
    signing in through Google — which ships no group claim — was silently
    demoted each time; `_syncs_roles` exists to stop that. A default grant
    re-applied per login would be the same bug wearing a different hat: an admin
    revokes it, the person signs in, it comes back.
    """
    from radd.modules.auth import grants

    role = await _member_role(db)
    provider = await _provider(db, default_grants=[{"role_id": role.id}])
    email = f"new-{uuid.uuid4().hex[:6]}@radd-hq.com"
    user = await service.provision(db, provider, _claims(email))

    for grant in await _grants_for(db, user.id):
        await grants.delete_grant(db, grant.id)
    await db.flush()

    await service.provision(db, provider, _claims(email))

    assert await _grants_for(db, user.id) == []


async def test_linking_an_existing_account_grants_nothing(db):
    """A Google login onto an AD account is a LINK, not a creation.

    The account already has whatever access it was given; handing it the
    provider's starting role because it used a different door would be a silent
    privilege change nobody asked for.
    """
    role = await _member_role(db)
    provider = await _provider(db, default_grants=[{"role_id": role.id}])
    email = f"existing-{uuid.uuid4().hex[:6]}@radd-hq.com"
    existing = await _user(db, email)

    linked = await service.provision(db, provider, _claims(email, sub="google-sub-link"))

    assert linked.id == existing.id
    assert await _grants_for(db, linked.id) == []


async def test_no_default_role_configured_grants_nothing(db):
    provider = await _provider(db)  # no template configured
    user = await service.provision(db, provider, _claims(f"new-{uuid.uuid4().hex[:6]}@radd-hq.com"))
    assert await _grants_for(db, user.id) == []


async def test_default_grants_are_scoped_per_project(db):
    """The shape RADD-780 fixed: several roles, each at its own scope.

    RADD-777 shipped one global role, which could say "everyone gets Member
    everywhere" and nothing else — not "Viewer on this project, Member
    globally", which is what the setting exists for.
    """
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate

    role = await _member_role(db)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SS{uuid.uuid4().hex[:4].upper()}", name="Scoped")
    )
    provider = await _provider(
        db,
        default_grants=[
            {"role_id": role.id, "project_id": project.id},
            {"role_id": role.id},  # and globally
        ],
    )

    user = await service.provision(db, provider, _claims(f"new-{uuid.uuid4().hex[:6]}@radd-hq.com"))

    held = {(g.role_id, g.project_id) for g in await _grants_for(db, user.id)}
    assert held == {(role.id, project.id), (role.id, None)}


async def test_default_teams_are_joined_on_first_login(db):
    from radd.modules.teams import service as teams_service
    from radd.modules.teams.schemas import TeamCreate

    team = await teams_service.create_team(db, TeamCreate(name=f"Squad {uuid.uuid4().hex[:5]}"))
    provider = await _provider(db, default_team_ids=[team.id])

    user = await service.provision(db, provider, _claims(f"new-{uuid.uuid4().hex[:6]}@radd-hq.com"))

    members = await teams_service.list_team_members(db, team.id)
    assert user.id in {m.id for m in members}


async def test_a_stale_template_never_breaks_a_sign_in(db):
    """A template is configured weeks before it is used.

    For ROLES this turns out to be unreachable, and the failing first draft of
    this test is what showed it: the FK refuses to store a template pointing at
    a role that does not exist, and CASCADE removes the row if one is deleted
    later. The database makes the case impossible rather than the code handling
    it.

    Teams are different, and this is the case that survives: a team can be
    LINKED to an AD group after the template was written, and its membership
    then belongs to the directory (spec 87 — `add_team_member` answers 409).
    Someone signing in must not meet that failure; they land on the Baseline and
    an admin grants the rest.
    """
    from radd.modules.teams import service as teams_service
    from radd.modules.teams.schemas import TeamCreate
    from radd.modules.teams.types import TeamSource

    team = await teams_service.create_team(db, TeamCreate(name=f"Linked {uuid.uuid4().hex[:5]}"))
    provider = await _provider(db, default_team_ids=[team.id])
    # The directory takes ownership after the template was configured.
    team.source = TeamSource.DIRECTORY.value
    await db.flush()

    user = await service.provision(db, provider, _claims(f"new-{uuid.uuid4().hex[:6]}@radd-hq.com"))

    assert user.id is not None  # the sign-in completed
    assert user.id not in {m.id for m in await teams_service.list_team_members(db, team.id)}
