"""The Baseline pre-flight report (RADD-825).

"Narrowing the Baseline would remove access for N users across M projects —
here is who, and where." Computed by resolving every active human account's
effective access twice — once under the Baseline as stored, once under the
PROPOSED set — through the real resolvers (`effective_permissions` +
`project_permission_map`), never a re-derivation that could drift from
enforcement. The floor is swapped by seeding the same `session.info` memo the
resolvers read, so both worlds run the exact code a request would.

An admin runs this from the Baseline editor, grants the roles that restore
intended access, and re-runs it until the diff is what they meant.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .authz import _BASELINE_CACHE_KEY, _PROJECT_MAP_CACHE_KEY, _READABLE_CACHE_KEY
from .models import User
from .schemas import BaselinePreflightRead, BaselinePreflightRow
from .types import InstanceRole, Permission, UserSource, split_permission

#: Detail rows are capped; the COUNTS always cover everyone (no silent caps —
#: `truncated` says the list is a sample, never that the numbers are).
REPORT_ROW_CAP = 200


def _swap_floor(session: AsyncSession, user_id: uuid.UUID, floor: frozenset[str]) -> None:
    """Point the resolvers' memoised floor at `floor` and drop this actor's
    downstream memos so the next resolution recomputes under it."""
    session.info[_BASELINE_CACHE_KEY] = floor
    session.info.pop(f"{_PROJECT_MAP_CACHE_KEY}:{user_id}", None)
    session.info.pop(f"{_READABLE_CACHE_KEY}:{user_id}", None)


async def baseline_preflight(
    session: AsyncSession, proposed: list[str]
) -> BaselinePreflightRead:
    current = await authz.baseline_permissions(session)
    proposed_set = frozenset(str(p) for p in proposed)

    # The row-level diff, classified: an atom whose base survives in a
    # narrower @relation form NARROWS; one with no surviving form is REMOVED.
    leaving = sorted(str(a) for a in current if str(a) not in proposed_set)
    narrowed, removed = [], []
    for atom in leaving:
        base, _ = split_permission(atom)
        if any(split_permission(p)[0] == base for p in proposed_set):
            narrowed.append(atom)
        else:
            removed.append(atom)

    users = list(
        (
            await session.execute(
                select(User)
                .where(
                    User.active,
                    User.source.notin_(
                        [UserSource.SERVICE.value, UserSource.EMAIL.value, UserSource.PRINCIPAL.value]
                    ),
                )
                .order_by(User.name)
            )
        ).scalars()
    )

    from radd.modules.projects import service as projects_service

    project_keys = {p.id: p.key for p in await projects_service.list_projects(session)}
    rows: list[BaselinePreflightRow] = []
    users_affected = 0
    projects_lost: set[uuid.UUID] = set()
    try:
        for user in users:
            if user.instance_role == InstanceRole.ADMIN.value:
                continue  # resolves to everything in both worlds
            _swap_floor(session, user.id, frozenset(str(a) for a in current))
            current_global = await authz.effective_permissions(session, user)
            _swap_floor(session, user.id, proposed_set)
            proposed_global = await authz.effective_permissions(session, user)
            lost = sorted(
                str(a) for a in current_global if str(a) not in
                {str(p) for p in proposed_global}
            )
            if not lost:
                continue
            users_affected += 1

            retained: list[str] = []
            lost_project_count = 0
            if any(split_permission(a)[0] == str(Permission.ITEM_READ) for a in lost):
                per_project = await authz.project_permission_map(session, user)
                for pid, perms in per_project.items():
                    # EXACT membership: the proposed floor's @own holds the
                    # base everywhere, so "retained" means FULL project read
                    # via a project-scoped source, not the narrow floor.
                    if Permission.ITEM_READ in perms:
                        retained.append(project_keys.get(pid, str(pid)))
                    else:
                        lost_project_count += 1
                        projects_lost.add(pid)
                retained.sort()
            if len(rows) < REPORT_ROW_CAP:
                rows.append(
                    BaselinePreflightRow(
                        user_id=user.id,
                        name=user.name,
                        email=user.email,
                        lost=lost,
                        retained_project_keys=retained,
                        lost_project_count=lost_project_count,
                    )
                )
    finally:
        # The report must leave no fingerprints: later resolutions on this
        # session go back to reading the STORED floor.
        authz.forget_baseline(session)
        for user in users:
            session.info.pop(f"{_PROJECT_MAP_CACHE_KEY}:{user.id}", None)
            session.info.pop(f"{_READABLE_CACHE_KEY}:{user.id}", None)

    return BaselinePreflightRead(
        proposed=sorted(proposed_set),
        narrowed=narrowed,
        removed=removed,
        users_affected=users_affected,
        projects_affected=len(projects_lost),
        total_users_checked=len(users),
        rows=rows,
        truncated=users_affected > len(rows),
    )
