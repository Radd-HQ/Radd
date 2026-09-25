"""The half of a webhook receiver every connector shares (RADD-1309).

Parsing stays per connector — the payload shapes differ and the connectors are
independently disableable. What does NOT differ is what happens after parsing:
resolve each planned key to an issue, upsert the link through the seam, and fire
the connector's triggers once per linked issue. That loop existed three times,
each ending in its own private "move merged work to waiting-for-release"; now it
exists once and ends in events.
"""

import uuid
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.items import service as items

from . import service
from .models import ItemVcsLink
from .triggers import RefAction, emit_ref, ref_of
from .types import VcsProvider, VcsRefType

#: Linked issues → the links this delivery wrote for each, in delivery order.
LinksByItem = dict[uuid.UUID, list[ItemVcsLink]]


class Planned(Protocol):
    """The shape every connector's `parsing.PlannedLink` already has."""

    item_key: str
    ref_type: VcsRefType
    external_id: str
    title: str
    url: str
    status: str


async def link_planned(
    session: AsyncSession,
    planned: Iterable[Planned],
    *,
    provider: VcsProvider,
    actor_id: uuid.UUID | None,
) -> LinksByItem:
    """Upsert every planned link whose key names an existing issue; a key that
    names nothing is skipped silently (text is full of things shaped like keys)."""
    resolved: dict[str, Any] = {}
    out: LinksByItem = {}
    for plan in planned:
        if plan.item_key not in resolved:
            resolved[plan.item_key] = await items.find_item_by_key(session, plan.item_key)
        item = resolved[plan.item_key]
        if item is None:
            continue
        link = await service.upsert_vcs_link(
            session,
            item.id,
            provider=provider,
            ref_type=plan.ref_type,
            external_id=plan.external_id,
            title=plan.title,
            url=plan.url,
            status=plan.status,
            actor_id=actor_id,
        )
        out.setdefault(item.id, []).append(link)
    return out


def count(links: LinksByItem) -> int:
    return sum(len(rows) for rows in links.values())


async def fire_ref_action(
    session: AsyncSession,
    trigger: StrEnum,
    links: LinksByItem,
    *,
    provider: VcsProvider,
    repo: str,
    action: RefAction,
    ref_extra: Mapping[str, Any],
    actor_id: uuid.UUID | None,
) -> int:
    """A merge/pull request was opened, merged or closed: one event per issue it names."""
    for rows in links.values():
        await emit_ref(
            session, trigger, rows[0],
            provider=provider, repo=repo, actor_id=actor_id,
            payload={"action": action.value, "ref": ref_of(rows[0], **ref_extra)},
        )
    return len(links)


async def fire_push(
    session: AsyncSession,
    trigger: StrEnum,
    links: LinksByItem,
    *,
    provider: VcsProvider,
    repo: str,
    branch: str,
    actor_id: uuid.UUID | None,
) -> int:
    """A push named these issues (in the branch name or a commit message): one
    event per issue, carrying the branch and the commits that named it."""
    for rows in links.values():
        branch_link = next((row for row in rows if row.ref_type == VcsRefType.BRANCH), rows[0])
        commits = [
            {"title": row.title, "url": row.url} for row in rows if row.ref_type == VcsRefType.COMMIT
        ]
        await emit_ref(
            session, trigger, branch_link,
            provider=provider, repo=repo, actor_id=actor_id,
            payload={"branch": branch, "ref": ref_of(branch_link), "commits": commits},
        )
    return len(links)


async def fire_ci(
    session: AsyncSession,
    trigger: StrEnum,
    stamped: Iterable[ItemVcsLink],
    *,
    provider: VcsProvider,
    repo: str,
    state: str,
    url: str,
    actor_id: uuid.UUID | None,
) -> int:
    """CI finished for a ref: one event per issue linked to it (a branch and its
    head commit may both be linked from the same issue — that is still one)."""
    by_item: LinksByItem = {}
    for link in stamped:
        by_item.setdefault(link.item_id, []).append(link)
    for rows in by_item.values():
        await emit_ref(
            session, trigger, rows[0],
            provider=provider, repo=repo, actor_id=actor_id,
            payload={"ref": ref_of(rows[0]), "ci": {"state": state, "url": url}},
        )
    return len(by_item)
