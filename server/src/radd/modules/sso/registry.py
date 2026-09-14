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
from radd.kernel import changes
from radd.modules.events import service as events

from .models import (
    SsoProvider,
    SsoProviderDefaultGrant,
    SsoProviderDefaultTeam,
    SsoProvisioningRule,
)
from .schemas import SsoProviderCreate, SsoProviderUpdate, SsoProvisioningRule as RuleSpec
from .types import KIND_DEFAULTS, WILDCARD_DOMAIN, SsoEntity, SsoEvent, SsoKind, SsoProviderSource

from radd.snapshot import Snapshot

logger = logging.getLogger(__name__)

# [(id, name, kind)] for every ENABLED, fully-configured provider — what the
# login page renders buttons from. Write-through on admin edits + startup, and
# TTL'd (RADD-899) so a second web replica converges without a restart.


async def _load_snapshot() -> list[dict]:
    from radd.db import SessionLocal

    async with SessionLocal() as session:
        return _snapshot_rows(await list_providers(session))


def _snapshot_rows(rows) -> list[dict]:
    return [
        {"id": str(p.id), "name": p.name, "kind": p.kind}
        for p in rows
        if p.enabled and configured(p)
    ]


_snapshot: Snapshot[list[dict]] = Snapshot("sso.providers", _load_snapshot, initial=[])


def snapshot() -> list[dict]:
    return list(_snapshot.get())


def configured(provider: SsoProvider) -> bool:
    """A row only reaches the login page once it can actually complete a flow."""
    return bool(provider.client_id and provider.client_secret and issuer_of(provider))


def issuer_of(provider: SsoProvider) -> str:
    return provider.issuer or KIND_DEFAULTS[SsoKind(provider.kind)].issuer


def scopes_of(provider: SsoProvider) -> str:
    return provider.scopes or KIND_DEFAULTS[SsoKind(provider.kind)].scopes


async def refresh_snapshot(session: AsyncSession) -> None:
    _snapshot.set(_snapshot_rows(await list_providers(session)))


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


#: Never in an event payload — a diff records that the secret CHANGED, no value.
SECRET_FIELDS: tuple[str, ...] = ("client_secret",)
#: Columns a provider diff never mentions (`source` is a seed marker).
_UNDIFFED: tuple[str, ...] = (*changes.DEFAULT_EXCLUDED_COLUMNS, "source")


async def _emit(
    session: AsyncSession,
    event_type: SsoEvent,
    provider: SsoProvider,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=SsoEntity.PROVIDER,
        entity_id=provider.id,
        actor_id=actor_id,
        payload={"name": provider.name, "kind": provider.kind},
        changes=diff,
    )


async def create_provider(
    session: AsyncSession,
    data: SsoProviderCreate,
    source: SsoProviderSource = SsoProviderSource.USER,
    *,
    actor_id: uuid.UUID | None = None,
) -> SsoProvider:
    kind = SsoKind(data.kind)
    if kind is SsoKind.OIDC and not (data.issuer or "").strip():
        raise ConflictError(SsoEntity.PROVIDER, reason="a generic OIDC provider needs an issuer URL")
    name = (data.name or "").strip() or KIND_DEFAULTS[kind].name
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
    await _replace_rules(session, provider, data.provisioning_rules)
    await _emit(session, SsoEvent.PROVIDER_CREATED, provider, actor_id)
    return provider


async def _replace_rules(
    session: AsyncSession, provider: SsoProvider, rules: list[RuleSpec]
) -> None:
    """Full replacement of the provisioning rules and their children (RADD-782).

    Delete-then-insert, the views/sharing idiom: the set is tiny, the write is
    one admin action, and diffing would need a stable identity for rows whose
    whole content IS their identity. The children go with the rules by CASCADE.
    """
    await session.execute(
        delete(SsoProvisioningRule).where(SsoProvisioningRule.provider_id == provider.id)
    )
    await session.flush()
    for position, spec in enumerate(rules):
        rule = SsoProvisioningRule(
            provider_id=provider.id,
            name=spec.name.strip(),
            position=position,
            domains=_clean_domains(spec.domains),
        )
        session.add(rule)
        await session.flush()
        seen: set[tuple[uuid.UUID, uuid.UUID | None]] = set()
        for grant in spec.grants:
            key = (grant.role_id, grant.project_id)
            if key in seen:  # the same role twice on one scope is one grant
                continue
            seen.add(key)
            session.add(
                SsoProviderDefaultGrant(
                    rule_id=rule.id, role_id=grant.role_id, project_id=grant.project_id
                )
            )
        for team_id in dict.fromkeys(spec.team_ids):  # order-preserving dedupe
            session.add(SsoProviderDefaultTeam(rule_id=rule.id, team_id=team_id))
    await session.flush()


async def provisioning_rules(
    session: AsyncSession, provider_id: uuid.UUID
) -> list[tuple[SsoProvisioningRule, list[SsoProviderDefaultGrant], list[uuid.UUID]]]:
    """Every rule on the provider, each with its grants and teams."""
    rules = list(
        (
            await session.execute(
                select(SsoProvisioningRule)
                .where(SsoProvisioningRule.provider_id == provider_id)
                .order_by(SsoProvisioningRule.position)
            )
        ).scalars()
    )
    if not rules:
        return []
    ids = [rule.id for rule in rules]
    grants_by_rule = {identifier: [] for identifier in ids}
    teams_by_rule = {identifier: [] for identifier in ids}
    for grant in await session.scalars(select(SsoProviderDefaultGrant).where(
        SsoProviderDefaultGrant.rule_id.in_(ids)).order_by(SsoProviderDefaultGrant.id)):
        grants_by_rule[grant.rule_id].append(grant)
    for rule_id, team_id in await session.execute(select(
        SsoProviderDefaultTeam.rule_id, SsoProviderDefaultTeam.team_id).where(
        SsoProviderDefaultTeam.rule_id.in_(ids)).order_by(SsoProviderDefaultTeam.id)):
        teams_by_rule[rule_id].append(team_id)
    return [(rule, grants_by_rule[rule.id], teams_by_rule[rule.id]) for rule in rules]



async def update_provider(
    session: AsyncSession,
    provider_id: uuid.UUID,
    data: SsoProviderUpdate,
    *,
    actor_id: uuid.UUID | None = None,
) -> SsoProvider:
    provider = await get_provider(session, provider_id)
    before = changes.snapshot(provider, changes.column_fields(provider, exclude=_UNDIFFED))
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
    if data.provisioning_rules is not None:
        await _replace_rules(session, provider, data.provisioning_rules)
    if "allowed_signup_domains" in patch:
        provider.allowed_signup_domains = _clean_domains(patch["allowed_signup_domains"] or [])
    # An EMPTY secret on update means "keep the stored one" — the read model
    # never returns it, so a round-tripped form would otherwise blank it.
    if patch.get("client_secret"):
        provider.client_secret = patch["client_secret"].strip()
    if not provider.name:
        provider.name = KIND_DEFAULTS[SsoKind(provider.kind)].name
    await session.flush()
    diff = changes.diff_object(provider, before, hidden=SECRET_FIELDS)
    if data.provisioning_rules is not None:
        # Rules are replaced whole (delete-then-insert has no stable identity to
        # diff); the record says they were rewritten.
        diff.append(changes.hidden_change("provisioning_rules"))
    await _emit(session, SsoEvent.PROVIDER_UPDATED, provider, actor_id, diff)
    return provider


async def delete_provider(
    session: AsyncSession, provider_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> None:
    """Deleting a provider drops its identity links (CASCADE) — the accounts
    themselves survive, they simply lose that way in."""
    provider = await get_provider(session, provider_id)
    await _emit(session, SsoEvent.PROVIDER_DELETED, provider, actor_id)
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
