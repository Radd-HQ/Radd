"""Confluence page restrictions → Radd access grants (spec 117, RADD-1017).

**The mapping is identity, by DN.** Radd already mirrors AD: `groups` holds `dn`
uniquely with real nesting via `group_parents`, and `GrantSubject.GROUP` is a
first-class access-grant subject that `pages`' `_PAGE_SPEC` already accepts,
matched THROUGH nesting (RADD-832). So a restriction naming an AD group becomes a
grant naming the same AD group. No translation layer, no new concept — the
assumption is that one directory sits behind both systems, and it is checkable.

The plan's `groups` table is the FALLBACK, for principals that do not resolve: a
group predating the current directory, a deleted user, an instance whose AD was
never connected.

**An unresolved principal with no fallback fails its page.** A wiki import that
silently opens a restricted page is a data leak, and it is the failure nobody
notices — the page looks perfectly fine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.access import service as access_service
from radd.modules.access.types import Access, GrantSubject
from radd.modules.auth.models import User
from radd.modules.groups import service as groups_service
from radd.modules.teams.models import Team

from .schemas import GroupMapping, PlanOptions
from .types import (
    GroupAction,
    MappingSection,
    Problem,
    ProblemKind,
    UnresolvedPrincipal,
)

#: The resource type `pages` registers with the spec-92 access framework.
PAGE_RESOURCE = "page"

#: Confluence's two operations map onto the two accesses `_PAGE_SPEC` declares.
#: `implied_by={read: (write,)}` there means write does not imply exclusive read,
#: which is what makes "view open, edit restricted" expressible.
_OPERATION_ACCESS = {"read": Access.READ.value, "update": Access.WRITE.value}


def principals_of(restrictions: dict) -> list[str]:
    """Every user and group a page's restrictions actually NAME.

    Confluence always returns the envelope — `read` and `update` keys, each with
    empty `user`/`group` result lists — so the payload is truthy for every page
    whether or not anything is restricted. Taking that at face value reported
    "5787 restricted pages" for a space with 34, and made the import resolve
    principals 5787 times to find none.

    Walks defensively: a shape this does not recognise yields NO principals, and
    the run's FAIL default then refuses the page rather than importing it open.
    """
    found: list[str] = []
    for operation in _OPERATION_ACCESS:
        block = (restrictions or {}).get(operation) or {}
        inner = block.get("restrictions") or {}
        for raw in ((inner.get("user") or {}).get("results") or []):
            name = raw.get("username") or raw.get("displayName") or ""
            if name:
                found.append(f"user:{name}")
        for raw in ((inner.get("group") or {}).get("results") or []):
            if raw.get("name"):
                found.append(f"group:{raw['name']}")
    return found


def is_restricted(restrictions: dict) -> bool:
    """Whether a page is restricted AT ALL — see `principals_of`."""
    return bool(principals_of(restrictions))


@dataclass(slots=True)
class Resolution:
    """What one page's restrictions became."""

    grants: list[tuple[GrantSubject, uuid.UUID, str]] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    #: True when something could not be resolved and no fallback was configured.
    blocked: bool = False


async def resolve(
    session: AsyncSession,
    restrictions: dict,
    *,
    options: PlanOptions,
    overrides: dict[str, GroupMapping],
    page_title: str = "",
) -> Resolution:
    """Turn one page's restriction payload into grants to write."""
    out = Resolution()
    for operation, access in _OPERATION_ACCESS.items():
        block = (restrictions or {}).get(operation) or {}
        inner = block.get("restrictions") or {}
        for raw in ((inner.get("user") or {}).get("results") or []):
            name = raw.get("username") or raw.get("displayName") or ""
            await _principal(
                session, out, f"user:{name}", name, access,
                options=options, overrides=overrides, page_title=page_title, is_user=True,
            )
        for raw in ((inner.get("group") or {}).get("results") or []):
            name = raw.get("name") or ""
            await _principal(
                session, out, f"group:{name}", name, access,
                options=options, overrides=overrides, page_title=page_title, is_user=False,
            )
    return out


async def _principal(
    session: AsyncSession,
    out: Resolution,
    key: str,
    name: str,
    access: str,
    *,
    options: PlanOptions,
    overrides: dict[str, GroupMapping],
    page_title: str,
    is_user: bool,
) -> None:
    if not name:
        return
    override = overrides.get(key)
    if override is not None and override.action is GroupAction.FAIL:
        _block(out, key, name, page_title, "explicitly set to fail")
        return
    if override is not None and override.action is GroupAction.MAP:
        if override.group_id:
            out.grants.append((GrantSubject.GROUP, override.group_id, access))
            return
        if override.team_id:
            out.grants.append((GrantSubject.TEAM, override.team_id, access))
            return

    subject = await _identity(session, name, is_user=is_user)
    if subject is not None:
        out.grants.append((subject[0], subject[1], access))
        return

    # Nothing resolved. The fallback is the ONLY thing standing between this and
    # a restricted page importing open.
    if options.unresolved_principal is UnresolvedPrincipal.MAP_TO:
        if options.unresolved_group_id:
            out.grants.append((GrantSubject.GROUP, options.unresolved_group_id, access))
            return
        if options.unresolved_team_id:
            out.grants.append((GrantSubject.TEAM, options.unresolved_team_id, access))
            return
    _block(out, key, name, page_title, "no matching group, team or user")


def _block(out: Resolution, key: str, name: str, page_title: str, why: str) -> None:
    out.blocked = True
    out.problems.append(Problem(
        kind=ProblemKind.RESTRICTION,
        message=f"{page_title or 'a page'} is restricted to {name!r}, which did not "
                f"resolve ({why}) — the page was NOT imported, because importing it "
                "open would expose it",
        subject=name,
        section=MappingSection.GROUPS,
        mapping_key=key,
    ))


async def _identity(
    session: AsyncSession, name: str, *, is_user: bool
) -> tuple[GrantSubject, uuid.UUID] | None:
    """Match the principal to ITSELF.

    A group is matched by DN first — the only globally unique handle a directory
    gives — then by display name, then by a same-named team, because a studio that
    mirrors AD groups as teams has the same people behind both.
    """
    if is_user:
        user = await session.scalar(
            select(User).where(
                func.lower(User.email) == name.lower()
            )
        )
        if user is None:
            # Confluence usernames are AD sAMAccountNames far more often than they
            # are email addresses.
            user = await session.scalar(
                select(User).where(func.lower(User.name) == name.lower())
            )
        return (GrantSubject.USER, user.id) if user else None

    # Through the service, not the table: `groups` is not one of the spine models
    # a module may import directly (RADD-885), and `group_by_dn` is exactly the
    # public seam this needs.
    group = await groups_service.group_by_dn(session, name)
    if group is None:
        # Confluence names a group by its CN, not its DN, far more often than not.
        candidates = await groups_service.list_groups(session, q=name)
        group = next(
            (g for g in candidates if g.name.lower() == name.lower()), None
        )
    if group is not None:
        return (GrantSubject.GROUP, group.id)
    team = await session.scalar(select(Team).where(func.lower(Team.name) == name.lower()))
    return (GrantSubject.TEAM, team.id) if team else None


async def apply(
    session: AsyncSession,
    page_id: uuid.UUID,
    resolution: Resolution,
    *,
    actor_id: uuid.UUID,
) -> int:
    """Write the grants. `pages` is default-OPEN until restricted, so writing the
    first grant is what closes the page — and RADD-948 then closes its whole
    subtree, which is what Confluence's own inheritance already did."""
    written = 0
    for subject_type, subject_id, access in resolution.grants:
        await access_service.add_grant(
            session,
            PAGE_RESOURCE,
            str(page_id),
            subject_type=subject_type,
            subject_id=subject_id,
            access=access,
            actor_id=actor_id,
        )
        written += 1
    return written
