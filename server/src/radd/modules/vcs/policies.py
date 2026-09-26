"""What a repository's own switches do (RADD-1369).

Every delivery links refs and fires the connector's triggers; that part never
changes anything else (RADD-1309). These two behaviours run only for a
repository someone switched them on for in Settings → Version control:

* **Move merged issues to waiting for release** — every issue a merged change
  names moves to its project's waiting state (spec 112: the from-state of the
  first on-release transition). A project that does not ship through releases
  has no waiting state and is skipped; an issue already in a done category is
  left alone, so a late merge never reopens shipped work.
* **Publish version on release** — a published release/tag records the version
  in the repository's default project and sweeps what is waiting into it,
  through the same seam the "Publish version and sweep" node uses.

Both act as the actor the receiver passes (the system actor, like the rest of
a delivery). They are not automations, so automations with an "Issue updated"
trigger see the moves.
Shared by GitLab, GitHub and Forgejo, whose repository rows carry the switches.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import service as auth
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemUpdate
from radd.modules.projects import service as projects
from radd.modules.releases import pipeline
from radd.modules.workflow import service as workflow
from radd.modules.workflow.types import StateCategory

logger = logging.getLogger(__name__)


async def move_merged(
    session: AsyncSession, repo: Any, item_ids: list[uuid.UUID], *, actor_id: uuid.UUID
) -> int:
    """Move the issues a merged change named to their waiting state, when the
    repository's `move_on_merge` is on. Returns how many moved."""
    if repo is None or not repo.move_on_merge or not item_ids:
        return 0
    actor = await auth.get_user(session, actor_id)
    moved = 0
    for item_id in item_ids:
        item = await items.require_item(session, item_id)
        project = await projects.get_project(session, item.project_id)
        target = await pipeline.waiting_state_id(session, project)
        if target is None or item.state_id == target:
            continue
        categories = {state.id: state.category for state in await workflow.list_states(session, project.id)}
        if categories.get(item.state_id) == StateCategory.DONE.value:
            continue
        try:
            async with session.begin_nested():
                await items.update_item(session, item.id, ItemUpdate(state_id=target), actor)
            moved += 1
        except Exception:  # noqa: BLE001 — one refused move (a guard) must not lose the delivery
            logger.exception("vcs: merged-issue move failed for item %s", item.id)
    return moved


async def publish_release(
    session: AsyncSession, repo: Any, *, version: str, actor_id: uuid.UUID, name: str = "", notes: str = ""
) -> int:
    """Record a published release in the repository's default project and sweep,
    when its `publish_on_release` is on. Returns how many issues shipped."""
    if repo is None or not repo.publish_on_release or repo.project_id is None or not version:
        return 0
    project = await projects.get_project(session, repo.project_id)
    _release, shipped = await pipeline.on_release_published(
        session, project, version=version, name=name, notes=notes, actor_id=actor_id
    )
    return shipped
