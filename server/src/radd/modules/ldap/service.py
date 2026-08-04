"""LDAP/AD sign-in (spec 42): direct bind as <username>@<domain> — the user's
own credentials authenticate the connection, so no service/bind account is
stored. Email, display name, and admin-group membership (transitive, so nested
groups count) are read from the user's own entry on that same connection.
Provisioning + role sync mirror OIDC (spec 40): `password_hash NULL` marks the
account SSO-only, and the workspace role re-syncs on every login."""

import asyncio
import logging
from dataclasses import replace, dataclass

import ldap3
from ldap3.utils.conv import escape_filter_chars
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ForbiddenError, UnauthorizedError
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole, UserSource
from radd.modules.events import service as events
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey

from .types import (
    LDAP_MATCHING_RULE_IN_CHAIN,
    USERNAME_RE,
    DirectoryUser,
    LdapEntity,
    LdapEvent,
)

logger = logging.getLogger(__name__)

# Uniform for bad shape / rejected bind — reveals nothing about which.
BAD_CREDENTIALS = "invalid username or password"


@dataclass(frozen=True)
class LdapConn:
    """The directory CONNECTION (RADD-846): five values an admin may edit on
    Settings → Directory, with the RADD_LDAP_* env as seed/fallback."""

    url: str
    user_domain: str
    bind_dn: str
    bind_password: str
    admin_groups: str


def _env_conn() -> LdapConn:
    return LdapConn(
        url=settings.ldap_url,
        user_domain=settings.ldap_user_domain,
        bind_dn=settings.ldap_bind_dn,
        bind_password=settings.ldap_bind_password,
        admin_groups=settings.ldap_admin_groups,
    )


#: The module-level RESOLVED connection every sync helper below reads. Seeded
#: from env at import; every session-bearing boundary (login, sync ticks, the
#: directory routes, startup) refreshes it through the settings cascade first,
#: so a Directory-page edit applies with no restart. The capability manifest's
#: sync check reads it as-is — at worst one edit behind in a process that has
#: not crossed a boundary since, never wrong about its own last resolution.
_conn: LdapConn = _env_conn()


async def refresh_conn(session: AsyncSession) -> LdapConn:
    """Resolve the connection through the cascade (DB override → env) and
    swap the overlay. Call at every async boundary that leads to ldap3."""
    global _conn

    async def value(key: SettingKey) -> str:
        return str(await settings_service.resolve(session, key) or "").strip()

    _conn = LdapConn(
        url=await value(SettingKey.LDAP_URL),
        user_domain=await value(SettingKey.LDAP_USER_DOMAIN),
        bind_dn=await value(SettingKey.LDAP_BIND_DN),
        bind_password=await value(SettingKey.LDAP_BIND_PASSWORD),
        admin_groups=await value(SettingKey.LDAP_ADMIN_GROUPS),
    )
    return _conn


async def warm() -> None:
    """Startup hook: resolve once so a DB-configured instance reports the
    right capabilities before any request crosses a boundary."""
    from radd.db import SessionLocal

    async with SessionLocal() as session:
        await refresh_conn(session)


def enabled() -> bool:
    return bool(_conn.url and _conn.user_domain)


def _timeout() -> int:
    """ldap3's socket receive_timeout must be an INT — a float (e.g. 5.0) breaks
    the TLS socket open against real AD with 'required argument is not an integer'."""
    return max(1, int(settings.ldap_timeout_seconds))


def base_dn() -> str:
    """RADD_LDAP_BASE_DN, else derived: ad.example.com → DC=ad,DC=example,DC=com."""
    if settings.ldap_base_dn:
        return settings.ldap_base_dn
    return ",".join(f"DC={part}" for part in _conn.user_domain.split("."))


def admin_group_names() -> list[str]:
    return [g.strip() for g in _conn.admin_groups.split(",") if g.strip()]


def group_search_filter(group_cn: str) -> str:
    return f"(&(objectClass=group)(cn={escape_filter_chars(group_cn)}))"


def transitive_member_filter(username: str, group_dn: str) -> str:
    """The user, only if a (possibly nested) member of the group."""
    return (
        f"(&(sAMAccountName={escape_filter_chars(username)})"
        f"(memberOf:{LDAP_MATCHING_RULE_IN_CHAIN}:={escape_filter_chars(group_dn)}))"
    )


def directory_user_from_entry(username: str, attributes: dict, is_admin: bool) -> DirectoryUser:
    """Entry attributes → DirectoryUser, with the documented fallbacks: no
    mail attribute → the UPN (email-shaped by construction), no display
    name → the username."""

    def first(value: object) -> str:
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        return str(value or "").strip()

    email = first(attributes.get(settings.ldap_email_attribute))
    name = first(attributes.get(settings.ldap_name_attribute))
    return DirectoryUser(
        username=username,
        email=(email or f"{username}@{_conn.user_domain}").lower(),
        name=name or username,
        is_admin=is_admin,
    )


def bind_account_enabled() -> bool:
    return bool(_conn.url and _conn.bind_dn and _conn.bind_password)


def user_search_base() -> str:
    return settings.ldap_user_search_base or base_dn()


async def resolved_user_base(session: AsyncSession) -> str:
    """Spec 85: the cascade-resolved USERS base (instance override → env
    RADD_LDAP_USER_SEARCH_BASE). Empty resolves to base_dn() at USE time —
    the same fallback `user_search_base()` applies to the raw env value."""
    value = str(
        await settings_service.resolve(session, SettingKey.LDAP_USER_SYNC_BASE) or ""
    ).strip()
    return value or base_dn()


async def resolved_exclude_disabled(session: AsyncSession) -> bool:
    """The cascade-resolved toggle (Settings → Directory beats the env default)."""
    return bool(await settings_service.resolve(session, SettingKey.LDAP_EXCLUDE_DISABLED))


async def resolved_group_base(session: AsyncSession) -> str:
    """Spec 85: the cascade-resolved GROUPS base (instance override → env
    RADD_LDAP_GROUP_SEARCH_BASE), falling back to base_dn() when empty."""
    value = str(
        await settings_service.resolve(session, SettingKey.LDAP_GROUP_SEARCH_BASE) or ""
    ).strip()
    return value or base_dn()


def _entry_to_directory_user(attributes: dict) -> DirectoryUser | None:
    """A directory entry (from the service-account search) → DirectoryUser.
    is_admin is left False for bulk import — a user's real role syncs on their
    first interactive (direct-bind) login. Entries without an email are skipped."""
    username_attr = attributes.get("sAMAccountName")
    if isinstance(username_attr, (list, tuple)):
        username_attr = username_attr[0] if username_attr else ""
    username = str(username_attr or "").strip()
    if not username:
        return None
    user = directory_user_from_entry(username, attributes, is_admin=False)
    # directory_user_from_entry falls back to a synthesized UPN; for bulk import we
    # only want entries that carry a real mail attribute.
    email_attr = attributes.get(settings.ldap_email_attribute)
    if isinstance(email_attr, (list, tuple)):
        email_attr = email_attr[0] if email_attr else ""
    if not str(email_attr or "").strip():
        return None
    return user


def service_connection() -> ldap3.Connection:
    """A SERVICE-ACCOUNT connection (specs 49/84) — enumeration/group search
    only; interactive login stays direct-bind. Caller must unbind."""
    if not bind_account_enabled():
        raise ForbiddenError(
            "LDAP bind account is not configured (Settings → Directory, or RADD_LDAP_BIND_DN)"
        )
    server = ldap3.Server(
        _conn.url, get_info=ldap3.NONE, connect_timeout=_timeout()
    )
    return ldap3.Connection(
        server,
        user=_conn.bind_dn,
        password=_conn.bind_password,
        auto_bind=True,
        receive_timeout=_timeout(),
    )


# AD's userAccountControl ACCOUNTDISABLE bit, via the bitwise-AND matching rule.
# Not memorable, and not something an admin should have to type into a raw filter —
# which is why it is a toggle rather than part of the filter string.
DISABLED_ACCOUNT_CLAUSE = "(userAccountControl:1.2.840.113556.1.4.803:=2)"


def base_user_filter(exclude_disabled: bool = True) -> str:
    """The configured filter, with disabled accounts excluded unless told otherwise.

    Composed rather than baked into `ldap_user_filter`, so the toggle is a
    checkbox in Settings → Directory instead of a redeploy — and so a deploy that
    already hand-wrote the clause is not given it twice.
    """
    configured = settings.ldap_user_filter
    if not exclude_disabled or DISABLED_ACCOUNT_CLAUSE in configured:
        return configured
    return f"(&{configured}(!{DISABLED_ACCOUNT_CLAUSE}))"


def user_query_filter(q: str, exclude_disabled: bool = True) -> str:
    """The bulk-enumeration filter, optionally narrowed by a search term over
    cn/sAMAccountName/mail (spec 84 import-from-AD picker)."""
    base = base_user_filter(exclude_disabled)
    if not q.strip():
        return base
    term = escape_filter_chars(q.strip())
    return (
        f"(&{base}"
        f"(|(cn=*{term}*)(sAMAccountName=*{term}*)({settings.ldap_email_attribute}=*{term}*)))"
    )


def search_directory_users(
    q: str = "", base: str | None = None, exclude_disabled: bool = True
) -> list[DirectoryUser]:
    """Bind with the SERVICE ACCOUNT and page the directory for user entries
    (spec 49; q narrowing added by spec 84). Blocking ldap3 — callers run it
    via asyncio.to_thread or a script. `base` (spec 85) is the cascade-resolved
    search base from `resolved_user_base()`; None = the raw-env fallback (kept
    for scripts/import_ad_users.py, which has no session)."""
    search_base = base or user_search_base()
    conn = service_connection()
    users: list[DirectoryUser] = []
    try:
        entries = conn.extend.standard.paged_search(
            search_base=search_base,
            search_filter=user_query_filter(q, exclude_disabled),
            attributes=["sAMAccountName", settings.ldap_email_attribute, settings.ldap_name_attribute],
            paged_size=settings.ldap_page_size,
            generator=True,
        )
        seen: set[str] = set()
        for entry in entries:
            attrs = entry.get("attributes") if isinstance(entry, dict) else None
            if not attrs:
                continue
            user = _entry_to_directory_user(attrs)
            if user and user.email not in seen:
                seen.add(user.email)
                users.append(user)
    finally:
        conn.unbind()
    logger.info("ldap directory enumeration: %d users under %s", len(users), search_base)
    return users


def _bind_and_lookup(
    username: str, password: str, team_group_dns: tuple[str, ...] = ()
) -> DirectoryUser | None:
    """Blocking ldap3 round-trip (run via asyncio.to_thread). None = rejected.
    `team_group_dns` (spec 84): linked-team group DNs to probe transitively on
    the same connection — matches land in DirectoryUser.team_group_dns."""
    upn = f"{username}@{_conn.user_domain}"
    server = ldap3.Server(
        _conn.url,
        get_info=ldap3.NONE,
        connect_timeout=_timeout(),
    )
    try:
        conn = ldap3.Connection(
            server,
            user=upn,
            password=password,
            auto_bind=True,
            receive_timeout=_timeout(),
        )
    except ldap3.core.exceptions.LDAPException:
        logger.info("ldap login failed for %s (bind rejected)", username)
        return None
    try:
        search_base = base_dn()
        conn.search(
            search_base,
            f"(sAMAccountName={escape_filter_chars(username)})",
            attributes=[settings.ldap_email_attribute, settings.ldap_name_attribute],
        )
        attributes = dict(conn.entries[0].entry_attributes_as_dict) if conn.entries else {}

        is_admin = False
        for group_cn in admin_group_names():
            conn.search(search_base, group_search_filter(group_cn), attributes=["cn"])
            if not conn.entries:
                logger.warning("ldap admin group %r not found under %s", group_cn, search_base)
                continue
            group_dn = conn.entries[0].entry_dn
            conn.search(
                search_base,
                transitive_member_filter(username, group_dn),
                attributes=["cn"],
            )
            if conn.entries:
                is_admin = True
                break

        matched_dns: set[str] = set()
        for group_dn in team_group_dns:
            conn.search(
                search_base,
                transitive_member_filter(username, group_dn),
                attributes=["cn"],
            )
            if conn.entries:
                matched_dns.add(group_dn)
    finally:
        conn.unbind()
    logger.info("ldap login ok for %s: admin=%s", username, is_admin)
    user = directory_user_from_entry(username, attributes, is_admin)
    return replace(user, team_group_dns=frozenset(matched_dns))


async def authenticate(
    username: str, password: str, team_group_dns: tuple[str, ...] = ()
) -> DirectoryUser:
    if not enabled():
        raise ForbiddenError(
            "LDAP is not configured (set the server URL on Settings → Directory, or RADD_LDAP_URL)"
        )
    if not username or not password or not USERNAME_RE.match(username):
        raise UnauthorizedError(BAD_CREDENTIALS)
    directory_user = await asyncio.to_thread(_bind_and_lookup, username, password, team_group_dns)
    if directory_user is None:
        raise UnauthorizedError(BAD_CREDENTIALS)
    return directory_user


async def find_or_create_user(
    session: AsyncSession, directory_user: DirectoryUser
) -> tuple[User, bool]:
    """The spec-42 provision core, shared with the explicit imports (spec 84):
    find by email or create an SSO-only account (`password_hash NULL`,
    source=ldap). A pre-84 `unknown`-source account is claimed as ldap."""
    user = await auth_service.get_user_by_email(session, directory_user.email)
    if user is None:
        user = User(
            email=directory_user.email,
            name=directory_user.name,
            password_hash=None,
            source=UserSource.LDAP,
        )
        session.add(user)
        await session.flush()
        return user, True
    if user.source == UserSource.UNKNOWN:
        user.source = UserSource.LDAP
    return user, False


async def provision(session: AsyncSession, directory_user: DirectoryUser) -> User:
    """Find-or-create the user and re-sync the instance role from the directory
    admin mapping (spec 86: any active user holds the global member floor)."""
    existing = await auth_service.get_user_by_email(session, directory_user.email)
    if existing is None and not settings.ldap_auto_provision:
        raise ForbiddenError(
            f"no account for {directory_user.email} (auto-provisioning is off)"
        )
    user, _created = await find_or_create_user(session, directory_user)
    if not user.active:
        raise ForbiddenError("account is deactivated")

    role = InstanceRole.ADMIN.value if directory_user.is_admin else InstanceRole.MEMBER.value
    user.instance_role = role  # re-synced per login (admin group in ⇒ admin, out ⇒ member)

    await events.emit(
        session,
        event_type=LdapEvent.LOGIN,
        entity_type=LdapEntity.LDAP,
        entity_id=user.id,
        actor_id=user.id,
        payload={"email": user.email, "username": directory_user.username, "role": role},
    )
    return user
