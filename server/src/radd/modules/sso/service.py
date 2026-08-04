"""OIDC single sign-on (spec 40 → spec 110).

The flow is unchanged and standards-plain: authorization code + PKCE, `id_token`
verified against the issuer's JWKS. What spec 110 changed is that the provider is
a database ROW rather than the environment, so several IdPs coexist, and that
provisioning is now explicit about the two questions the env design left implicit:

  WHO IS THIS?    A (provider, subject) identity, pinned on first login. Email is
                  used ONCE, to find the account this person already has — and
                  only when the IdP says it verified that address. Subsequent
                  logins ignore email entirely, so a rename in AD doesn't fork
                  the account and a recycled address can't inherit a leaver's.

  MAY THEY IN?    An existing account: yes (the domain list gates CREATION, not
                  sign-in). A new account: only if the provider auto-provisions
                  AND the email's domain is on that provider's allowlist.
"""

import base64
import hashlib
import json
import logging
import secrets
import time
import uuid

import httpx
import jwt
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole, UserSource
from radd.modules.events import service as events

from . import registry
from .models import SsoProvider, UserIdentity
from .types import WILDCARD_DOMAIN, SsoEntity, SsoEvent, SsoKind

logger = logging.getLogger(__name__)

# Per-provider caches — an instance runs several issuers now, so a single
# module-level cache would have served Google's metadata for Okta's flow.
_metadata_cache: dict[uuid.UUID, dict] = {}
_jwks_clients: dict[uuid.UUID, PyJWKClient] = {}


def enabled() -> bool:
    """Any provider ready to complete a flow (drives the kernel capability)."""
    return bool(registry.snapshot())


def invalidate_caches(provider_id: uuid.UUID | None = None) -> None:
    """Editing a row must not leave the old issuer's discovery document live."""
    if provider_id is None:
        _metadata_cache.clear()
        _jwks_clients.clear()
        return
    _metadata_cache.pop(provider_id, None)
    _jwks_clients.pop(provider_id, None)


async def metadata(provider: SsoProvider) -> dict:
    """Issuer discovery document, cached per provider for the process lifetime."""
    cached = _metadata_cache.get(provider.id)
    if cached is None:
        url = registry.issuer_of(provider).rstrip("/") + "/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            cached = response.json()
        _metadata_cache[provider.id] = cached
    return cached


def _jwks(provider: SsoProvider, jwks_uri: str) -> PyJWKClient:
    client = _jwks_clients.get(provider.id)
    if client is None:
        client = PyJWKClient(jwks_uri)
        _jwks_clients[provider.id] = client
    return client


# --- authorization request ----------------------------------------------------


def new_flow(provider: SsoProvider) -> dict:
    """state + nonce + PKCE verifier for one authorization request, tagged with
    the provider so the callback knows which issuer to verify against."""
    return {
        "provider_id": str(provider.id),
        "state": secrets.token_urlsafe(24),
        "nonce": secrets.token_urlsafe(24),
        "verifier": secrets.token_urlsafe(48),
        "at": int(time.time()),
    }


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def redirect_uri() -> str:
    """One callback for every provider — the flow cookie carries which. Keeping a
    single URI means adding a provider needs no new registration on our side."""
    from radd.config import settings

    return settings.app_base_url.rstrip("/") + "/api/v1/auth/oidc/callback"


async def authorization_url(provider: SsoProvider, flow: dict) -> str:
    meta = await metadata(provider)
    params = httpx.QueryParams(
        response_type="code",
        client_id=provider.client_id,
        redirect_uri=redirect_uri(),
        scope=registry.scopes_of(provider),
        state=flow["state"],
        nonce=flow["nonce"],
        code_challenge=code_challenge(flow["verifier"]),
        code_challenge_method="S256",
    )
    return f"{meta['authorization_endpoint']}?{params}"


async def exchange_code(provider: SsoProvider, code: str, flow: dict) -> dict:
    """Code → verified id_token claims."""
    meta = await metadata(provider)
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(),
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "code_verifier": flow["verifier"],
            },
        )
        response.raise_for_status()
        tokens = response.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise ForbiddenError(f"{provider.name} returned no id_token")
    signing_key = _jwks(provider, meta["jwks_uri"]).get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=provider.client_id,
        issuer=meta["issuer"],
    )
    if claims.get("nonce") != flow["nonce"]:
        raise ForbiddenError("sign-in nonce mismatch — retry")
    return claims


# --- claim reading ------------------------------------------------------------


def _email_verified(claims: dict) -> bool:
    """`email_verified` is a bool per OIDC core, but enough issuers send the
    string "true" that treating it as unverified would be a false negative."""
    value = claims.get("email_verified")
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _is_admin(provider: SsoProvider, claims: dict) -> bool:
    admin_groups = {g.strip() for g in provider.admin_groups.split(",") if g.strip()}
    groups = claims.get(provider.group_claim or "groups") or []
    if isinstance(groups, str):
        groups = [groups]
    return bool(admin_groups and admin_groups & set(groups))


def _syncs_roles(provider: SsoProvider) -> bool:
    """Whether this provider has any opinion about instance roles.

    A provider with no admin groups configured carries NO role information, so it
    must leave `instance_role` untouched. Spec 40 wrote the role unconditionally,
    which meant an AD-provisioned admin signing in through Google — which ships no
    group claim at all — was silently demoted to member on every login.
    """
    return bool(provider.admin_groups.strip())


def signup_allowed(provider: SsoProvider, email: str) -> bool:
    """May this address CREATE an account? (Existing accounts never ask.)"""
    if not provider.auto_provision:
        return False
    allowed = provider.allowed_signup_domains or []
    if WILDCARD_DOMAIN in allowed:
        return True
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return bool(domain) and domain in allowed


# --- provisioning -------------------------------------------------------------


async def _identity_for(
    session: AsyncSession, provider: SsoProvider, subject: str
) -> UserIdentity | None:
    return await session.scalar(
        select(UserIdentity).where(
            UserIdentity.provider_id == provider.id, UserIdentity.subject == subject
        )
    )


async def identities_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[UserIdentity]:
    result = await session.execute(
        select(UserIdentity).where(UserIdentity.user_id == user_id).order_by(UserIdentity.created_at)
    )
    return list(result.scalars())



def _rule_matches(domains: list[str], email: str) -> bool:
    """Does this rule apply to that address? (RADD-782)

    Empty domains = the catch-all, matching everyone. Otherwise an exact match
    on the lowercased domain, the same normalization `allowed_signup_domains`
    uses — deliberately not a regex and not a subdomain wildcard, both of which
    are ways to write a rule that matches more than its author believed. This
    decides what a stranger gets on arrival.
    """
    if not domains:
        return True
    _, _, domain = email.partition("@")
    return domain.strip().lower() in {d.strip().lower() for d in domains}


async def _apply_provisioning_template(
    session: AsyncSession, provider: SsoProvider, user: User
) -> None:
    """Give a freshly created account the access its rules say it gets, once.

    EVERY matching rule applies, so a catch-all and a domain rule compose rather
    than race. Grants are additive rows, so a union is the only composition that
    cannot surprise — adding a rule can widen access but never silently remove
    another's.

    Roles become `global_role_grants` rows and teams become memberships:
    additive facts nothing reconciles. That is what makes "this must never undo
    an admin's later change" a property of the data rather than a rule someone
    has to remember — no code path reads these rules again for this account.

    Every failure here is swallowed to a log line, deliberately. A rule is
    configured weeks before it is used; a team linked to an AD group in the
    meantime (whose membership then belongs to the directory) must not turn a
    sign-in into an error for someone who did nothing wrong. They land on the
    Baseline and an admin grants the rest.
    """
    from radd.modules.auth import grants
    from radd.modules.teams import service as teams_service

    for rule, rule_grants, team_ids in await registry.provisioning_rules(session, provider.id):
        if not _rule_matches(rule.domains, user.email):
            continue
        for template in rule_grants:
            try:
                await grants.create_grant(
                    session, template.role_id, user_id=user.id, project_id=template.project_id
                )
            except Exception:  # noqa: BLE001 — a stale rule must not break a login
                logger.warning(
                    "sso: skipped role %s (project %s) from rule %s for %s",
                    template.role_id,
                    template.project_id,
                    rule.name or rule.id,
                    user.email,
                    exc_info=True,
                )
        for team_id in team_ids:
            try:
                # A team deleted after the template was written is the stale-rule
                # case that survives RADD-829 — skipped, sign-in completes.
                await teams_service.add_team_member(session, team_id, user.id)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "sso: skipped team %s from rule %s for %s",
                    team_id,
                    rule.name or rule.id,
                    user.email,
                    exc_info=True,
                )



async def provision(session: AsyncSession, provider: SsoProvider, claims: dict) -> User:
    """Resolve verified claims to a local account, linking or creating as policy allows."""
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise ForbiddenError(f"{provider.name} returned no subject claim")
    email = (claims.get("email") or "").strip().lower()
    name = (claims.get("name") or "").strip() or (email.split("@", 1)[0] if email else subject)

    identity = await _identity_for(session, provider, subject)
    linked = False

    if identity is not None:
        # Known identity — authoritative. Email is deliberately NOT consulted.
        user = await session.get(User, identity.user_id)
        if user is None:  # pragma: no cover — CASCADE makes this unreachable
            raise ForbiddenError("the account behind this sign-in no longer exists")
    else:
        if not email:
            raise ForbiddenError(f"{provider.name} returned no email claim")
        if provider.require_verified_email and not _email_verified(claims):
            raise ForbiddenError(
                f"{provider.name} has not verified {email}. Verify the address with "
                "the provider and sign in again."
            )
        user = await auth_service.get_user_by_email(session, email)
        if user is None:
            if not signup_allowed(provider, email):
                raise ForbiddenError(
                    f"{email} has no Radd account, and new accounts from "
                    f"{email.rsplit('@', 1)[-1]} aren't allowed. Ask an administrator "
                    "to add the domain or create the account."
                )
            # password_hash NULL = SSO-only account (the auth model reserved this).
            user = User(email=email, name=name, password_hash=None, source=UserSource.OIDC)
            session.add(user)
            await session.flush()
            # The provider's starting grant (RADD-777) — HERE and nowhere else.
            #
            # This branch is the only one that CREATES an account. The `linked`
            # branch below is an existing account gaining another door, and a
            # returning login reaches neither. Putting the grant on any of the
            # others would re-apply it, which is spec 40's demotion bug in a new
            # costume: an admin revokes it, the person signs in, it is back.
            await _apply_provisioning_template(session, provider, user)
        else:
            # The account already exists under another sign-in method (usually AD).
            # It keeps its `source`, its role and its history — this login just
            # becomes another door into it, which is the whole point.
            linked = True
        identity = UserIdentity(
            provider_id=provider.id, user_id=user.id, subject=subject, email=email
        )
        session.add(identity)

    if not user.active:
        raise ForbiddenError("account is deactivated")

    identity.email = email or identity.email
    identity.claims = {k: claims[k] for k in ("hd", "picture", "name") if k in claims}
    if user.source in (UserSource.UNKNOWN, UserSource.EMAIL):
        # spec 84: claim pre-84 SSO-only rows; RADD-828: an email-provisioned
        # requester who signs in with the same verified address JOINS their
        # account (keeping their tickets) and becomes able to log in.
        user.source = UserSource.OIDC

    if _syncs_roles(provider):
        user.instance_role = (
            InstanceRole.ADMIN.value if _is_admin(provider, claims) else InstanceRole.MEMBER.value
        )

    if linked:
        await events.emit(
            session,
            event_type=SsoEvent.IDENTITY_LINKED,
            entity_type=SsoEntity.SSO,
            entity_id=user.id,
            actor_id=user.id,
            payload={"email": email, "provider": provider.name, "source": user.source},
        )
        logger.info(
            "sso: linked %s identity %s to existing %s account %s",
            provider.name,
            subject,
            user.source,
            email,
        )

    await events.emit(
        session,
        event_type=SsoEvent.LOGIN,
        entity_type=SsoEntity.SSO,
        entity_id=user.id,
        actor_id=user.id,
        payload={"email": email, "provider": provider.name, "role": user.instance_role},
    )
    return user


# --- flow cookie --------------------------------------------------------------


def flow_cookie_value(flow: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(flow).encode()).decode()


def parse_flow_cookie(value: str, ttl: int) -> dict | None:
    try:
        flow = json.loads(base64.urlsafe_b64decode(value.encode()))
    except Exception:
        return None
    if int(time.time()) - int(flow.get("at", 0)) > ttl:
        return None
    return flow


def google_kind(provider: SsoProvider) -> bool:
    return SsoKind(provider.kind) is SsoKind.GOOGLE
