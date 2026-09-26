"""OIDC/OAuth2 single sign-on: authorization code + PKCE, then the kind's profile
strategy (`idp.py`).

WHO IS THIS? A (provider, subject) identity pinned on first login. Email is used
  once, and only when verified, to find an existing account; later logins ignore
  it, so a mailbox rename cannot fork the account.
MAY THEY IN? An existing account: yes. A new one: only if the provider
  auto-provisions AND the domain is on its allowlist.
"""

import base64
import hashlib
import json
import logging
import secrets
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ForbiddenError
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole, UserSource
from radd.modules.events import service as events

from . import idp, registry
from .models import SsoProvider, UserIdentity
from .types import WILDCARD_DOMAIN, ProfileStrategy, SsoEntity, SsoEvent

logger = logging.getLogger(__name__)


def enabled() -> bool:
    """Any provider ready to complete a flow (drives the kernel capability)."""
    return bool(registry.snapshot())


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
    return settings.app_base_url.rstrip("/") + "/api/v1/auth/oidc/callback"


async def authorization_url(provider: SsoProvider, flow: dict) -> str:
    meta = await idp.metadata(provider)
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri(),
        "scope": registry.scopes_of(provider),
        "state": flow["state"],
        "code_challenge": code_challenge(flow["verifier"]),
        "code_challenge_method": "S256",
    }
    # The nonce is bound into the id_token, which is where it gets checked; a
    # kind that issues none has nowhere to echo it, so it is not sent.
    if idp.defaults_of(provider).profile is ProfileStrategy.ID_TOKEN:
        params["nonce"] = flow["nonce"]
    return f"{meta['authorization_endpoint']}?{httpx.QueryParams(params)}"


async def exchange_code(provider: SsoProvider, code: str, flow: dict) -> dict:
    """Code → claims, through the kind's endpoints and profile strategy (`idp`)."""
    return await idp.exchange_code(provider, code, flow, redirect_uri())


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
    """A provider with no admin groups carries no role opinion and must not touch
    `instance_role` — a Google login ships no group claim and would demote an AD admin."""
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


def _rule_matches(domains: list[str], email: str) -> bool:
    """Empty domains = catch-all; otherwise an exact, lowercased domain match
    (see `SsoProvisioningRule`)."""
    if not domains:
        return True
    _, _, domain = email.partition("@")
    return domain.strip().lower() in {d.strip().lower() for d in domains}


async def _apply_provisioning_template(
    session: AsyncSession, provider: SsoProvider, user: User
) -> None:
    """Apply every matching rule to a NEW account, once (see SsoProvisioningRule).
    Each grant/team gets its own savepoint and a failure is logged, never raised: a
    stale rule must not block a login or discard the other rules."""
    from radd.modules.auth import grants
    from radd.modules.teams import service as teams_service

    for rule, rule_grants, team_ids in await registry.provisioning_rules(session, provider.id):
        if not _rule_matches(rule.domains, user.email):
            continue
        for template in rule_grants:
            try:
                async with session.begin_nested():
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
                async with session.begin_nested():
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
    created = False

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
            # Through auth's seam (RADD-1320), so it is a `user.created` event.
            user, _created = await auth_service.ensure_imported_user(
                session, email=email, name=name, source=UserSource.OIDC
            )
            created = True
            # Only account CREATION applies the template; re-applying it on a linked
            # or returning login would undo an admin's later revocation.
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

    before = auth_service.directory_snapshot(user)
    identity.email = email or identity.email
    identity.claims = {k: claims[k] for k in ("hd", "picture", "name") if k in claims}
    # RADD-1295: the provider's picture is the fallback avatar (an upload wins).
    # Only a provider that SENT one overwrites it — a second provider without a
    # picture must not erase the first one's.
    if claims.get("picture"):
        await auth_service.set_idp_picture(session, user, str(claims["picture"]))
    if user.source == UserSource.EMAIL:
        # RADD-828: an email-provisioned requester who signs in with the same
        # verified address JOINS their account (keeping their tickets) and
        # becomes able to log in.
        user.source = UserSource.OIDC

    if _syncs_roles(provider):
        user.instance_role = (
            InstanceRole.ADMIN.value if _is_admin(provider, claims) else InstanceRole.MEMBER.value
        )

    if not created:
        # RADD-1320: the source flip and the role re-sync were silent writes.
        await auth_service.record_user_changes(session, user, before, actor_id=user.id)

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


def safe_next_path(value: str | None) -> str | None:
    """A return path a sign-in may honour (spec 121): an absolute same-origin
    path — never a scheme, never protocol-relative, never the login page."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    if value.startswith("/login"):
        return None
    return value


def flow_cookie_value(flow: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(flow).encode()).decode()


def parse_flow_cookie(value: str, ttl: int) -> dict | None:
    try:
        flow = json.loads(base64.urlsafe_b64decode(value.encode()))
    except (ValueError, TypeError):  # bad base64/JSON — the two ways a cookie
        # can be malformed; anything else should surface (RADD-898)
        return None
    if int(time.time()) - int(flow.get("at", 0)) > ttl:
        return None
    return flow


