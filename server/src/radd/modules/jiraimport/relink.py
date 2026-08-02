"""Resolving cross-project references after the fact (spec 100).

The answer to "I import DEV first, but its issues link to TD, which I haven't
imported yet". Spec 90 dropped a dead web link at that point and never looked
again, so importing TD later left every DEV→TD link permanently broken.

Anything unresolved is recorded as a `jira_pending_ref` with a stand-in web link.
This pass retries them against the CURRENT database, replaces the stand-in with a
real parent or link, and clears the row. It runs automatically at the end of
every import — so importing TD fixes DEV immediately — and on demand.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemLinkCreate, ItemUpdate
from radd.modules.weblinks import service as weblinks_service
from radd.modules.weblinks.schemas import WebLinkCreate
from radd.modules.weblinks.types import WebLinkCategory

from . import ledger
from .models import JiraPendingRef
from .types import LedgerEntity, PendingRefKind

logger = logging.getLogger(__name__)


@dataclass
class RelinkResult:
    resolved: int = 0
    still_pending: int = 0
    # Grouped by the project prefix still missing, which is what the UI shows:
    # "412 links point at TD-*, not yet imported".
    pending_by_project: dict[str, int] = field(default_factory=dict)


async def record(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None,
    actor: User,
    source_item_id: uuid.UUID,
    kind: PendingRefKind,
    target_jira_key: str,
    browse_url: str,
    link_type: str = "",
    inward: bool = False,
) -> None:
    """Park an unresolvable reference, with a visible stand-in.

    The web link matters: until the target arrives, someone reading the issue can
    still follow the reference to Jira. It is removed the moment the real link
    replaces it.
    """
    web_link_id: uuid.UUID | None = None
    try:
        created = await weblinks_service.create_web_link(
            session,
            source_item_id,
            WebLinkCreate(
                url=browse_url,
                title=f"{target_jira_key} (Jira)",
                category=WebLinkCategory.EXTERNAL,
            ),
            actor_id=actor.id,
        )
        web_link_id = created.id
        if run_id:
            ledger.created(
                session, run_id, LedgerEntity.WEB_LINK, created.id, subject=target_jira_key
            )
    except Exception:  # noqa: BLE001 — the pending row is what matters
        logger.warning("could not place a stand-in web link for %s", target_jira_key)
    session.add(
        JiraPendingRef(
            run_id=run_id,
            source_item_id=source_item_id,
            kind=kind.value,
            target_jira_key=target_jira_key.upper(),
            link_type=link_type,
            inward=inward,
            web_link_id=web_link_id,
        )
    )


async def resolve_all(
    session: AsyncSession, actor: User, *, key_map: dict[str, str] | None = None
) -> RelinkResult:
    """Retry every pending reference, from every run.

    Cross-run by design: that is the whole point — a reference recorded while
    importing DEV is resolved by the import of TD, weeks later.

    `key_map` translates a Jira key to the Radd key it was imported under, for
    the run that is finishing right now; anything else is looked up as-is.
    """
    result = RelinkResult()
    rows = list((await session.execute(select(JiraPendingRef))).scalars())
    for ref in rows:
        radd_key = (key_map or {}).get(ref.target_jira_key, ref.target_jira_key)
        target = await items_service.find_item_by_key(session, radd_key)
        if target is None:
            result.still_pending += 1
            prefix = ref.target_jira_key.rpartition("-")[0] or ref.target_jira_key
            result.pending_by_project[prefix] = result.pending_by_project.get(prefix, 0) + 1
            continue
        if await _apply(session, ref, target.id, actor):
            await _clear(session, ref, actor)
            result.resolved += 1
        else:
            result.still_pending += 1
    await session.flush()
    return result


async def _apply(
    session: AsyncSession, ref: JiraPendingRef, target_id: uuid.UUID, actor: User
) -> bool:
    try:
        if PendingRefKind(ref.kind) is PendingRefKind.PARENT:
            await items_service.update_item(
                session, ref.source_item_id, ItemUpdate(parent_id=target_id), actor
            )
            return True
        # An INWARD Jira link ("this is blocked by X") is really X→this, so the
        # endpoints swap to keep a directional type pointing the right way.
        source, other = (
            (target_id, ref.source_item_id) if ref.inward else (ref.source_item_id, target_id)
        )
        await items_service.add_item_link(
            session,
            source,
            ItemLinkCreate(target_id=other, link_type=ref.link_type or "relates"),
            actor,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        # A hierarchy violation or a duplicate link is not a failure to retry
        # forever — but it is not a silent success either, so it stays pending
        # and keeps its web link.
        logger.info("relink %s -> %s not applied: %s", ref.source_item_id, ref.target_jira_key, exc)
        return False


async def _clear(session: AsyncSession, ref: JiraPendingRef, actor: User) -> None:
    """The real reference exists now, so the stand-in link is noise."""
    if ref.web_link_id:
        try:
            await weblinks_service.delete_web_link(session, ref.web_link_id, actor_id=actor.id)
        except Exception:  # noqa: BLE001 — an already-deleted link is fine
            pass
    await session.delete(ref)


async def pending_summary(session: AsyncSession) -> dict[str, int]:
    """What is still waiting, by target project — the Runs page's relink prompt."""
    rows = list((await session.execute(select(JiraPendingRef.target_jira_key))).scalars())
    out: dict[str, int] = {}
    for key in rows:
        prefix = key.rpartition("-")[0] or key
        out[prefix] = out.get(prefix, 0) + 1
    return out
