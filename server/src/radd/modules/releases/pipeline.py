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
from radd.modules.projects.models import Project
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey
from radd.modules.workflow import service as workflow_service

from . import service as releases_service
from .schemas import ReleaseCreate
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


async def ensure_release(
    session: AsyncSession, project: Project, *, version: str, name: str = "", notes: str = ""
):
    """Find-or-create the version. Webhook delivery is at-least-once, so a repeat
    of the same tag must reuse the row rather than create a second one."""
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    existing = await releases_service.list_releases(session, project.id)
    match = next((r for r in existing if r.version == version), None)
    if match is not None:
        return match
    return await releases_service.create_release(
        session,
        ReleaseCreate(
            project_id=project.id,
            name=name or version,
            version=version,
            status=ReleaseStatus.RELEASED,
            description=notes[:2000],
        ),
        actor_id=SYSTEM_ACTOR_ID,
    )


async def sweep(session: AsyncSession, project: Project, release) -> int:
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
            await items_update(session, item_id, shipped, release.id, actor)
            moved += 1
        except Exception:
            logger.exception("release sweep: %s could not be shipped", item_id)
    logger.info("release sweep: %s items -> %s in %s", moved, release.version, project.key)
    return moved


async def items_update(session, item_id, state_id, release_id, actor):
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemUpdate

    await items_service.update_item(
        session, item_id, ItemUpdate(state_id=state_id, release_id=release_id), actor
    )


async def on_release_published(
    session: AsyncSession, project: Project, *, version: str, name: str = "", notes: str = ""
) -> tuple[object, int]:
    """A published version: record it, then sweep. Returns (release, items moved)."""
    release = await ensure_release(session, project, version=version, name=name, notes=notes)
    return release, await sweep(session, project, release)
