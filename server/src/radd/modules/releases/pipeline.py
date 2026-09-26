"""The release pipeline (spec 112, RADD-1285): work waits in a done-category
state (it IS finished; the filer's question is whether it is running yet) and a
published version moves everything waiting on, with the release recorded.

What moves where is a WORKFLOW fact — transitions marked `on_release`. A project
with none does not ship through releases; every function here is a no-op for it.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import service as auth_service
from radd.modules.items.models import WorkItem
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project
from radd.modules.workflow import service as workflow_service

from . import service as releases_service
from .models import Release
from .schemas import ReleaseCreate, ReleaseUpdate
from .types import ReleaseStatus

logger = logging.getLogger(__name__)


async def waiting_state_id(session: AsyncSession, project: Project) -> uuid.UUID | None:
    """Where finished-but-unshipped work waits: the from-state of the project's
    first on-release transition (spec 112 / RADD-1285). None = the project does
    not ship through releases. A repository's "move merged issues" switch moves
    work here (RADD-1369)."""
    rows = await workflow_service.release_transitions(session, project.id)
    return rows[0].from_state_id if rows else None


async def create_release(
    session: AsyncSession,
    data: ReleaseCreate,
    actor_id: uuid.UUID | None = None,
    *,
    sweep_as: uuid.UUID | None = None,
) -> tuple[Release, int]:
    """Record a version; one born `released` ships what is waiting (RADD-1007).

    Every write path — REST, MCP, a release automation (RADD-1309) — comes
    through here or `update_release`, so "a version that becomes released
    sweeps" is one rule with one home rather than a property of any one caller.
    Returns the release and how many items it shipped.
    """
    release = await releases_service.create_release(session, data, actor_id=actor_id)
    if release.status != ReleaseStatus.RELEASED.value:
        return release, 0
    project = await projects_service.get_project(session, release.project_id)
    return release, await sweep(session, project, release, actor_id=sweep_as)


async def update_release(
    session: AsyncSession,
    release_id: uuid.UUID,
    data: ReleaseUpdate,
    actor_id: uuid.UUID | None = None,
) -> tuple[Release, int]:
    """Edit a version; the planned → released transition sweeps (RADD-1007).
    Re-marking an already-released version does not re-sweep — that is what
    `POST /releases/{id}/sweep` and the `sweep_release` tool are for."""
    was_released = (await releases_service.get_release(session, release_id)).status
    release = await releases_service.update_release(session, release_id, data, actor_id=actor_id)
    became_released = (
        release.status == ReleaseStatus.RELEASED.value
        and was_released != ReleaseStatus.RELEASED.value
    )
    if not became_released:
        return release, 0
    project = await projects_service.get_project(session, release.project_id)
    return release, await sweep(session, project, release)


async def sweep(
    session: AsyncSession, project: Project, release: Release, *, actor_id: uuid.UUID | None = None
) -> int:
    """Perform every on-release transition, recording the release. Idempotent:
    shipped items are no longer in a from-state. Deliberately "everything waiting",
    not "commits in the tag range" (that needs a commit walk and is only right if
    every merge went through a linked PR). Made as the system unless `actor_id`
    names someone (the sweep node passes its automation's actor, RADD-1315)."""
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    rows = await workflow_service.release_transitions(session, project.id)
    if not rows:
        return 0
    actor = await auth_service.get_user(session, actor_id or SYSTEM_ACTOR_ID)
    moved = 0
    for row in rows:
        item_ids = list((await session.execute(
            select(WorkItem.id).where(
                WorkItem.project_id == project.id, WorkItem.state_id == row.from_state_id
            )
        )).scalars())
        for item_id in item_ids:
            try:
                # Release and state in ONE patch: guards are checked after every
                # field in the request is applied, so "Requires a release" on the
                # target is satisfied by this call rather than blocking it.
                await _ship_item(session, item_id, row.to_state_id, release.id, actor)
                moved += 1
            except Exception:
                logger.exception("release sweep: %s could not be shipped", item_id)
    logger.info("release sweep: %s items -> %s in %s", moved, release.version, project.key)
    return moved


async def _ship_item(session, item_id, state_id, release_id, actor):
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemUpdate

    await items_service.update_item(
        session, item_id, ItemUpdate(state_id=state_id, release_id=release_id), actor
    )


async def on_release_published(
    session: AsyncSession,
    project: Project,
    *,
    version: str,
    name: str = "",
    notes: str = "",
    actor_id: uuid.UUID | None = None,
) -> tuple[Release, int]:
    """A published version: record it, then sweep (the sweep node, RADD-1310, and a
    repository's "Publish version on release" switch, RADD-1369). Delivery is
    at-least-once, so a repeated tag reuses the row and re-runs the idempotent
    sweep. Notes are stored whole (RADD-907: a 2000-char cut lost changelogs)."""
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    actor_id = actor_id or SYSTEM_ACTOR_ID
    existing = await releases_service.resolve_release(session, project.id, version)
    if existing is not None:
        return existing, await sweep(session, project, existing, actor_id=actor_id)
    return await create_release(
        session,
        ReleaseCreate(
            project_id=project.id,
            name=name or version,
            version=version,
            status=ReleaseStatus.RELEASED,
            description=notes,
        ),
        actor_id=actor_id,
        sweep_as=actor_id,
    )
