"""Directory GROUP operations (spec 84) — all on the SERVICE-ACCOUNT bind
(spec 49): paged group search for the pickers, one-group lookup by DN, and the
transitive (nested-membership, LDAP_MATCHING_RULE_IN_CHAIN) member resolution
the team↔group sync and the group import run on. The ldap3 wire calls are
synchronous and wrapped in asyncio.to_thread, exactly as the login bind.

Spec 85: search bases resolve through the settings cascade — the async
wrappers take a session, resolve the base (group search → the GROUPS base,
member resolution → the USERS base, since member entries are user objects),
and pass it to the sync wire functions as a plain parameter."""

import asyncio
import logging

import ldap3
from ldap3.utils.conv import escape_filter_chars
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError

from . import service
from .types import (
    LDAP_MATCHING_RULE_IN_CHAIN,
    DirectoryGroup,
    DirectoryUnreachable,
    DirectoryUser,
    LdapEntity,
)

logger = logging.getLogger(__name__)

# Displayed member counts read the DIRECT `member` attribute (cheap); the sync
# itself always resolves membership transitively so nested groups count.
# `memberOf` (RADD-831) carries the group's DIRECT parents — the nesting edges.
_GROUP_ATTRIBUTES = ("cn", "description", "member", "memberOf")


def require_bind_account() -> None:
    """Spec 84 endpoints answer 409 (not 403) when the bind account is absent —
    the caller is authorized, the DEPLOY is missing a piece."""
    if not service.bind_account_enabled():
        raise ConflictError(
            LdapEntity.LDAP,
            reason="no LDAP bind account is configured (RADD_LDAP_BIND_DN/_PASSWORD)",
        )


def group_query_filter(q: str) -> str:
    if not q.strip():
        return "(objectClass=group)"
    return f"(&(objectClass=group)(cn=*{escape_filter_chars(q.strip())}*))"


def transitive_group_members_filter(group_dn: str, exclude_disabled: bool = True) -> str:
    """Every person that is a (possibly NESTED) member of the group — the
    spec-42 matching-rule idiom generalized to whole-group resolution.
    `ldap_exclude_disabled` applies here too (spec 100 → RADD-831): a disabled
    account must not arrive as a group member and quietly hold grants."""
    person = "(objectCategory=person)(objectClass=user)"
    if exclude_disabled:
        person += f"(!{service.DISABLED_ACCOUNT_CLAUSE})"
    return (
        f"(&{person}"
        f"(memberOf:{LDAP_MATCHING_RULE_IN_CHAIN}:={escape_filter_chars(group_dn)}))"
    )


def _first(value: object) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "").strip()


def _entry_to_group(dn: str, attributes: dict) -> DirectoryGroup | None:
    cn = _first(attributes.get("cn"))
    if not cn or not dn:
        return None
    member = attributes.get("member") or []
    if not isinstance(member, (list, tuple)):
        member = [member]
    member_of = attributes.get("memberOf") or []
    if not isinstance(member_of, (list, tuple)):
        member_of = [member_of]
    return DirectoryGroup(
        cn=cn,
        dn=dn,
        description=_first(attributes.get("description")),
        member_count=len(member),
        member_of=tuple(str(parent).strip() for parent in member_of if str(parent).strip()),
    )


def _search_groups_sync(q: str, base: str) -> list[DirectoryGroup]:
    conn = service.service_connection()
    groups: list[DirectoryGroup] = []
    try:
        entries = conn.extend.standard.paged_search(
            search_base=base,
            search_filter=group_query_filter(q),
            attributes=list(_GROUP_ATTRIBUTES),
            paged_size=settings.ldap_page_size,
            generator=True,
        )
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            group = _entry_to_group(str(entry.get("dn") or ""), entry.get("attributes") or {})
            if group:
                groups.append(group)
    finally:
        conn.unbind()
    logger.info("ldap group search %r under %s: %d groups", q, base, len(groups))
    return sorted(groups, key=lambda g: g.cn.lower())


async def search_groups(session: AsyncSession, q: str = "") -> list[DirectoryGroup]:
    """Paged group search under the cascade-resolved GROUPS base (spec 85)."""
    return await asyncio.to_thread(_search_groups_sync, q, await service.resolved_group_base(session))


def _get_group_sync(group_dn: str) -> DirectoryGroup | None:
    """One group by DN (BASE-scope read) — the import path re-reads the CN so
    the server, not the client, names the team.

    None means the group is genuinely NOT THERE. Spec 87: a failure to reach the
    directory raises `DirectoryUnreachable` instead, because callers now act on
    the difference — an absent group marks a team stale (its AD group was renamed
    or deleted), and a DC that blinked must never be read that way.
    """
    try:
        # Inside the try: service_connection() binds eagerly (auto_bind), so an
        # unreachable DC or a rejected bind surfaces HERE, not as an escaping
        # LDAPException that a caller might mistake for "no such group".
        conn = service.service_connection()
    except ldap3.core.exceptions.LDAPException as exc:
        logger.warning("ldap group lookup could not connect for %s", group_dn, exc_info=True)
        raise DirectoryUnreachable(f"could not reach the directory: {exc}") from exc
    try:
        # ldap3 reports a missing DN as a failed result (noSuchObject), not an
        # exception, unless raise_exceptions is set — so the empty-entries check
        # below is the usual "not there" path and the handler is belt-and-braces.
        conn.search(
            group_dn,
            "(objectClass=group)",
            search_scope=ldap3.BASE,
            attributes=list(_GROUP_ATTRIBUTES),
        )
    except ldap3.core.exceptions.LDAPNoSuchObjectResult:
        return None  # the DN itself is gone — an answer, not a failure
    except ldap3.core.exceptions.LDAPException as exc:
        logger.warning("ldap group lookup failed for %s", group_dn, exc_info=True)
        raise DirectoryUnreachable(f"could not look up {group_dn}: {exc}") from exc
    else:
        if not conn.entries:
            return None
        entry = conn.entries[0]
        return _entry_to_group(entry.entry_dn, dict(entry.entry_attributes_as_dict))
    finally:
        conn.unbind()


async def get_group(group_dn: str) -> DirectoryGroup | None:
    """None = the group is not in the directory. Raises DirectoryUnreachable when
    the directory could not be asked at all (spec 87)."""
    return await asyncio.to_thread(_get_group_sync, group_dn)


def _search_group_members_sync(
    group_dn: str, base: str, exclude_disabled: bool
) -> list[DirectoryUser]:
    """TRANSITIVE members of one group, as DirectoryUsers (username required;
    email falls back to the synthesized UPN — matching is by email/UPN)."""
    conn = service.service_connection()
    members: list[DirectoryUser] = []
    try:
        entries = conn.extend.standard.paged_search(
            search_base=base,
            search_filter=transitive_group_members_filter(group_dn, exclude_disabled),
            attributes=[
                "sAMAccountName",
                settings.ldap_email_attribute,
                settings.ldap_name_attribute,
            ],
            paged_size=settings.ldap_page_size,
            generator=True,
        )
        seen: set[str] = set()
        for entry in entries:
            attrs = entry.get("attributes") if isinstance(entry, dict) else None
            if not attrs:
                continue
            username = _first(attrs.get("sAMAccountName"))
            if not username:
                continue
            user = service.directory_user_from_entry(username, attrs, is_admin=False)
            if user.email not in seen:
                seen.add(user.email)
                members.append(user)
    finally:
        conn.unbind()
    logger.info("ldap transitive members of %s: %d", group_dn, len(members))
    return members


async def search_group_members(session: AsyncSession, group_dn: str) -> list[DirectoryUser]:
    """Transitive member resolution under the cascade-resolved USERS base
    (spec 85 — member entries are user objects, so the users base scopes them)."""
    return await asyncio.to_thread(
        _search_group_members_sync,
        group_dn,
        await service.resolved_user_base(session),
        await service.resolved_exclude_disabled(session),
    )
