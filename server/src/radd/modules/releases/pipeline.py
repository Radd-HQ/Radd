"""The release pipeline (spec 112): work finishes once, ships later.

`Done` answers the developer's question. The person who filed the issue is asking
a different one — is it running yet. So work lands in a WAITING state (category
`done`, because it IS finished) and a published version sweeps everything waiting
into the shipped state with the release recorded.

Two settings name the states per project. Both empty means the project does not
use the pipeline, and every function here becomes a no-op — a project that never
opted in is never touched.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import service as auth_service
from radd.modules.items.models import WorkItem
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey
from radd.modules.workflow import service as workflow_service

from . import service as releases_service
from .models import Release
from .schemas import ReleaseCreate, ReleaseUpdate
from .types import ReleaseStatus

logger = logging.getLogger(__name__)


async def _state_id_by_setting(
    session: AsyncSession, project: Project, key: SettingKey
) -> uuid.UUID | None:
    name = str(await settings_service.resolve(session, key, project_id=project.id) or "").strip()
    if not name:
        return None
    states = await workflow_service.list_states(session, project.id)
    match = next((s for s in states if s.name.lower() == name.lower()), None)
    if match is None:
        # A renamed state is a settings problem, not a crash: say so and do nothing.
        logger.warning(
            "release pipeline: project %s names state %r for %s, which does not exist",
            project.key, name, key.value,
        )
        return None
    return match.id


async def waiting_state_id(session: AsyncSession, project: Project) -> uuid.UUID | None:
    return await _state_id_by_setting(session, project, SettingKey.RELEASE_WAITING_STATE)


async def shipped_state_id(session: AsyncSession, project: Project) -> uuid.UUID | None:
    return await _state_id_by_setting(session, project, SettingKey.RELEASE_SHIPPED_STATE)


async def create_release(
    session: AsyncSession, data: ReleaseCreate, actor_id: uuid.UUID | None = None
) -> tuple[Release, int]:
    """Record a version; one born `released` ships what is waiting (RADD-1007).

    Every write path — REST, MCP, the connectors' publish webhooks — comes
    through here or `update_release`, so "a version that becomes released
    sweeps" is one rule with one home rather than a property of the webhook.
    Returns the release and how many items it shipped.
    """
    release = await releases_service.create_release(session, data, actor_id=actor_id)
    if release.status != ReleaseStatus.RELEASED.value:
        return release, 0
    project = await projects_service.get_project(session, release.project_id)
    return release, await sweep(session, project, release)


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


async def sweep(session: AsyncSession, project: Project, release: Release) -> int:
    """Move every waiting item in the project to the shipped state, recording the
    release. Idempotent: items already shipped are not in the waiting state, so a
    second run finds nothing and repoints nothing.

    This is deliberately "everything waiting" rather than "the items whose commits
    are in the tag range" — see the spec's simplifications. Deriving the latter
    needs a tag-to-tag commit walk and is only correct if every merge went through
    a linked PR.
    """
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    waiting = await waiting_state_id(session, project)
    shipped = await shipped_state_id(session, project)
    if waiting is None or shipped is None:
        return 0
    rows = await session.execute(
        select(WorkItem.id).where(WorkItem.project_id == project.id, WorkItem.state_id == waiting)
    )
    item_ids = list(rows.scalars())
    if not item_ids:
        return 0
    actor = await auth_service.get_user(session, SYSTEM_ACTOR_ID)
    moved = 0
    for item_id in item_ids:
        try:
            # Release and state in ONE patch: transition guards are checked after
            # every field in the request is applied, so a project that requires a
            # release to enter its shipped state is satisfied by this call rather
            # than blocked by it.
            await _ship_item(session, item_id, shipped, release.id, actor)
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
    session: AsyncSession, project: Project, *, version: str, name: str = "", notes: str = ""
) -> tuple[Release, int]:
    """A published version from a connector: record it, then sweep.

    Webhook delivery is at-least-once, so a repeat of the same tag reuses the
    row and re-runs the (idempotent) sweep rather than creating a second version.
    The notes are stored whole — the column is unbounded text, and a changelog
    cut mid-word at 2000 characters was a data-loss bug (RADD-907).
    """
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    existing = await releases_service.resolve_release(session, project.id, version)
    if existing is not None:
        return existing, await sweep(session, project, existing)
    return await create_release(
        session,
        ReleaseCreate(
            project_id=project.id,
            name=name or version,
            version=version,
            status=ReleaseStatus.RELEASED,
            description=notes,
        ),
        actor_id=SYSTEM_ACTOR_ID,
    )
