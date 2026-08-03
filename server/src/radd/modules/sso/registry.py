"""SSO provider registry (spec 110) — CRUD, env seeding, and the login-page snapshot.

Mirrors `ai/registry.py`: rows are the source of truth, the env `oidc_*` settings
survive as seed-only input, and a process-local snapshot lets the SYNC kernel
capability check (and the unauthenticated login-options endpoint) answer without
a database round trip.
"""

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ConflictError, NotFoundError

from .models import SsoProvider, SsoProviderDefaultGrant, SsoProviderDefaultTeam
from .schemas import SsoDefaultGrant, SsoProviderCreate, SsoProviderUpdate
from .types import KIND_DEFAULTS, WILDCARD_DOMAIN, SsoEntity, SsoKind, SsoProviderSource

logger = logging.getLogger(__name__)

# [(id, name, kind)] for every ENABLED, fully-configured provider — what the
# login page renders buttons from. Refreshed on write + at startup.
_snapshot: list[dict] = []


def snapshot() -> list[dict]:
    return list(_snapshot)


def configured(provider: SsoProvider) -> bool:
    """A row only reaches the login page once it can actually complete a flow."""
    return bool(provider.client_id and provider.client_secret and issuer_of(provider))


def issuer_of(provider: SsoProvider) -> str:
    return provider.issuer or KIND_DEFAULTS[SsoKind(provider.kind)]["issuer"]


def scopes_of(provider: SsoProvider) -> str:
    return provider.scopes or KIND_DEFAULTS[SsoKind(provider.kind)]["scopes"]


async def refresh_snapshot(session: AsyncSession) -> None:
    global _snapshot
    rows = await list_providers(session)
    _snapshot = [
        {"id": str(p.id), "name": p.name, "kind": p.kind}
        for p in rows
        if p.enabled and configured(p)
    ]


# --- CRUD ---------------------------------------------------------------------


async def list_providers(session: AsyncSession) -> list[SsoProvider]:
    result = await session.execute(
        select(SsoProvider).order_by(SsoProvider.position, SsoProvider.name)
    )
    return list(result.scalars())


async def get_provider(session: AsyncSession, provider_id: uuid.UUID) -> SsoProvider:
    provider = await session.get(SsoProvider, provider_id)
    if provider is None:
        raise NotFoundError(SsoEntity.PROVIDER, provider_id)
    return provider


async def _assert_name_free(
    session: AsyncSession, name: str, *, exclude: uuid.UUID | None = None
) -> None:
    query = select(SsoProvider.id).where(SsoProvider.name == name)
    if exclude is not None:
        query = query.where(SsoProvider.id != exclude)
    if (await session.execute(query.limit(1))).first() is not None:
        raise ConflictError(SsoEntity.PROVIDER, reason=f"a provider named {name!r} exists")


def _clean_domains(domains: list[str]) -> list[str]:
    """Normalize what an admin typed into bare lowercase domains.

    People paste "@radd-hq.com", "HJarrar.com", and whole addresses — all three
    mean the same thing, and a list that silently doesn't match is a support
    ticket, so normalize rather than validate-and-reject."""
    cleaned: list[str] = []
    for raw in domains:
        domain = raw.strip().lower().lstrip("@")
        if "@" in domain:  # a full address was pasted — keep the domain part
            domain = domain.rsplit("@", 1)[1]
        domain = domain.strip().strip(".")
        if domain and domain not in cleaned:
            cleaned.append(domain)
    return cleaned


async def create_provider(
    session: AsyncSession,
    data: SsoProviderCreate,
    source: SsoProviderSource = SsoProviderSource.USER,
) -> SsoProvider:
    kind = SsoKind(data.kind)
    if kind is SsoKind.OIDC and not (data.issuer or "").strip():
        raise ConflictError(SsoEntity.PROVIDER, reason="a generic OIDC provider needs an issuer URL")
    name = (data.name or "").strip() or KIND_DEFAULTS[kind]["name"]
    await _assert_name_free(session, name)
    provider = SsoProvider(
        name=name,
        kind=kind.value,
        enabled=data.enabled,
        position=data.position,
        issuer=(data.issuer or "").strip().rstrip("/"),
        client_id=(data.client_id or "").strip(),
        client_secret=(data.client_secret or "").strip(),
        scopes=(data.scopes or "").strip(),
        auto_provision=data.auto_provision,
        allowed_signup_domains=_clean_domains(data.allowed_signup_domains),
        require_verified_email=data.require_verified_email,
        group_claim=(data.group_claim or "groups").strip(),
        # RADD-777. An explicit field list means a new column is silently
        # dropped on create until it is added here — which is exactly what
        # happened, and what made two of the new tests pass VACUOUSLY: they
        # asserted "no grant" against a provider that had never stored a role.

        admin_groups=(data.admin_groups or "").strip(),
        source=source.value,
    )
    session.add(provider)
    await session.flush()
    await _replace_default_grants(session, provider, data.default_grants)
    await _replace_default_teams(session, provider, data.default_team_ids)
    return provider


async def _replace_default_grants(
    session: AsyncSession, provider: SsoProvider, grants: list[SsoDefaultGrant]
) -> None:
    """Full replacement — the views/sharing idiom (RADD-780).

    Delete-then-insert rather than diffing: the set is tiny, the write is one
    admin action, and a diff would need a stable identity for rows whose whole
    content IS their identity (provider, role, scope).
    """
    await session.execute(
        delete(SsoProviderDefaultGrant).where(
            SsoProviderDefaultGrant.provider_id == provider.id
        )
    )
    seen: set[tuple[uuid.UUID, uuid.UUID | None]] = set()
    for grant in grants:
        key = (grant.role_id, grant.project_id)
        if key in seen:  # the same role twice on one scope is one grant
            continue
        seen.add(key)
        session.add(
            SsoProviderDefaultGrant(
                provider_id=provider.id, role_id=grant.role_id, project_id=grant.project_id
            )
        )
    await session.flush()


async def _replace_default_teams(
    session: AsyncSession, provider: SsoProvider, team_ids: list[uuid.UUID]
) -> None:
    """Full replacement, same idiom as the grants above (RADD-781)."""
    await session.execute(
        delete(SsoProviderDefaultTeam).where(SsoProviderDefaultTeam.provider_id == provider.id)
    )
    for team_id in dict.fromkeys(team_ids):  # order-preserving dedupe
        session.add(SsoProviderDefaultTeam(provider_id=provider.id, team_id=team_id))
    await session.flush()


async def default_teams(session: AsyncSession, provider_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.execute(
        select(SsoProviderDefaultTeam.team_id).where(
            SsoProviderDefaultTeam.provider_id == provider_id
        )
    )
    return list(rows.scalars())


async def default_grants(
    session: AsyncSession, provider_id: uuid.UUID
) -> list[SsoProviderDefaultGrant]:
    rows = await session.execute(
        select(SsoProviderDefaultGrant).where(
            SsoProviderDefaultGrant.provider_id == provider_id
        )
    )
    return list(rows.scalars())


async def update_provider(
    session: AsyncSession, provider_id: uuid.UUID, data: SsoProviderUpdate
) -> SsoProvider:
    provider = await get_provider(session, provider_id)
    patch = data.model_dump(exclude_unset=True)
    if "name" in patch and (patch["name"] or "").strip():
        await _assert_name_free(session, patch["name"].strip(), exclude=provider_id)
    for field in ("name", "issuer", "client_id", "scopes", "group_claim", "admin_groups"):
        if field in patch:
            value = (patch[field] or "").strip()
            setattr(provider, field, value.rstrip("/") if field == "issuer" else value)
    for field in ("enabled", "position", "auto_provision", "require_verified_email"):
        if field in patch:
            setattr(provider, field, patch[field])
    # An explicit null CLEARS it (RADD-777) — the house PATCH semantics, and the
    # only way to say "new accounts get nothing extra" once a role was chosen.
    # `exclude_unset` is what makes that expressible: an omitted key leaves the
    # value alone, a key set to None removes it. Left out of the loop above only
    # because these fields all coerce and this one must not.
    if data.default_grants is not None:
        await _replace_default_grants(session, provider, data.default_grants)
    if data.default_team_ids is not None:
        await _replace_default_teams(session, provider, data.default_team_ids)
    if "allowed_signup_domains" in patch:
        provider.allowed_signup_domains = _clean_domains(patch["allowed_signup_domains"] or [])
    # An EMPTY secret on update means "keep the stored one" — the read model
    # never returns it, so a round-tripped form would otherwise blank it.
    if patch.get("client_secret"):
        provider.client_secret = patch["client_secret"].strip()
    if not provider.name:
        provider.name = KIND_DEFAULTS[SsoKind(provider.kind)]["name"]
    await session.flush()
    return provider


async def delete_provider(session: AsyncSession, provider_id: uuid.UUID) -> None:
    """Deleting a provider drops its identity links (CASCADE) — the accounts
    themselves survive, they simply lose that way in."""
    provider = await get_provider(session, provider_id)
    await session.delete(provider)
    await session.flush()


# --- env seeding (startup) ----------------------------------------------------


async def seed_from_env() -> None:
    """Turn a spec-40 environment configuration into a provider row, ONCE.

    Runs only when the table is empty, so an admin who deletes the seeded row
    never has it silently reappear. Seeded rows are ordinary editable providers.
    """
    async with SessionLocal() as session:
        existing = await session.execute(select(SsoProvider.id).limit(1))
        if existing.first() is None and settings.oidc_issuer and settings.oidc_client_id:
            await _seed_provider(session)
            await session.commit()
        await refresh_snapshot(session)


async def _seed_provider(session: AsyncSession) -> None:
    issuer = settings.oidc_issuer.rstrip("/")
    google = "accounts.google.com" in issuer
    provider = await create_provider(
        session,
        SsoProviderCreate(
            name=_seed_name(issuer),
            kind=SsoKind.GOOGLE if google else SsoKind.OIDC,
            issuer="" if google else issuer,
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            scopes=settings.oidc_scopes,
            # Spec 40 had no allowlist, so a seeded row would silently change
            # meaning under the new rule. Preserve the OLD behavior for the row
            # the env created: auto_provision on with an empty list means "no
            # signups" for new rows, so carry the intent across explicitly.
            auto_provision=settings.oidc_auto_provision,
            allowed_signup_domains=_env_domains(),
            group_claim=settings.oidc_group_claim,
            admin_groups=settings.oidc_admin_groups,
        ),
        source=SsoProviderSource.ENV,
    )
    logger.info("sso: seeded provider %r from the environment", provider.name)


def _env_domains() -> list[str]:
    """`RADD_OIDC_SIGNUP_DOMAINS` seeds the allowlist. Empty + auto-provision on
    reproduces spec 40's "anyone at the IdP may sign up" via the wildcard."""
    raw = [d for d in settings.oidc_signup_domains.split(",") if d.strip()]
    if raw:
        return raw
    return [WILDCARD_DOMAIN] if settings.oidc_auto_provision else []


def _seed_name(issuer: str) -> str:
    host = issuer.split("://", 1)[-1].split("/", 1)[0]
    if "accounts.google.com" in host:
        return "Google"
    return host or "SSO"
