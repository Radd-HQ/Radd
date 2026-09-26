"""What every receiver does after parsing: resolve planned keys to issues, upsert the
links, and fire the connector's triggers once per issue."""

import uuid
import hashlib
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.items import service as items

from . import service
from .models import ItemVcsLink, VcsDelivery
from .triggers import HostAuthor, RefAction, emit_ref, ref_of
from .types import VcsProvider, VcsRefType

#: Linked issues → the links this delivery wrote for each, in delivery order.
LinksByItem = dict[uuid.UUID, list[ItemVcsLink]]


async def claim_delivery(session, *, provider, connection_id, delivery_id, event_type, body):
    """Claim after authentication, atomically with processing; rollbacks allow retry.

    Missing IDs are processed normally. Include the event and body because some
    hosts reuse an event UUID across related webhook notifications.
    """
    if not delivery_id:
        return True
    from sqlalchemy.dialects.postgresql import insert
    digest = hashlib.sha256(delivery_id.encode() + b"\0" + event_type.encode() + b"\0" + body).hexdigest()
    return await session.scalar(insert(VcsDelivery).values(provider=str(provider), connection_id=connection_id, digest=digest)
                                .on_conflict_do_nothing().returning(VcsDelivery.digest)) is not None


class Planned(Protocol):
    """The shape of `keys.PlannedLink` (the backfills build SimpleNamespace ones)."""

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
    connection_id: uuid.UUID | None = None,
    repo=None,
) -> LinksByItem:
    """Upsert every planned link whose key names an existing issue; a key that
    names nothing is skipped silently (text is full of things shaped like keys)."""
    by_ref: dict[str, list[Planned]] = {}
    for plan in planned:
        by_ref.setdefault(plan.external_id, []).append(plan)
    out: LinksByItem = {}
    for external_id, plans in by_ref.items():
        plan = plans[0]
        targets = {}
        # Keep historical associations current even after a key is removed.
        for link in await service.links_for_refs(session, provider=provider,
                external_ids=[external_id], connection_id=connection_id):
            item = await items.require_item(session, link.item_id)
            targets[item.id] = item
        for candidate in plans:
            item = await items.find_item_by_key(session, candidate.item_key) if candidate.item_key else None
            if item is not None:
                targets[item.id] = item
        for item in targets.values():
            if repo is not None and not repo.link_all_projects and item.project_id != repo.project_id:
                continue
            link = await service.upsert_vcs_link(
                session, item.id, provider=provider, connection_id=connection_id,
                ref_type=plan.ref_type, external_id=plan.external_id,
                title=plan.title, url=plan.url, status=plan.status, actor_id=actor_id,
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
    author: HostAuthor | None = None,
    changes: list[dict[str, Any]] | None = None,
) -> int:
    """A merge/pull request was opened, merged, closed or updated: one event per
    issue it names. An update with nothing meaningful changed fires nothing."""
    if action is RefAction.UPDATED and not changes:
        return 0
    for rows in links.values():
        await emit_ref(
            session, trigger, rows[0],
            provider=provider, repo=repo, actor_id=actor_id,
            payload={"action": action.value, "ref": ref_of(rows[0], **ref_extra)},
            author=author,
            changes=changes if action is RefAction.UPDATED else None,
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
    author: HostAuthor | None = None,
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
            author=author,
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
    name: str = "", sha: str = "", run_id: int | None = None,
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
            payload={"ref": ref_of(rows[0]), "ci": {"state": state, "url": url, "name": name, "sha": sha, "run_id": run_id}},
        )
    return len(by_item)
