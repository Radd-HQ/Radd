"""Project teardown, this module's share (RADD-1174).

`projects` dispatches two in-transaction hooks and owns nothing here: INSPECTING
asks what of ours dies with the project (the confirmation dialog's numbers, and
the count the `project.deleted` event records), DELETING removes what the
database cannot cascade on its own. Registered at import, like the
`project.created` seeding hooks.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.projects.types import ProjectDeleting, ProjectHook, ProjectInspection

from .models import LinkTypeDef, LinkTypeProject
from .service import _emit
from .types import LinkTypeEvent


def _exclusively_scoped(project_id):
    """Same trap as custom fields: a link type scoped only to this project
    would become global when its scope rows cascade away."""
    return (
        select(LinkTypeProject.link_type_id)
        .group_by(LinkTypeProject.link_type_id)
        .having(func.bool_and(LinkTypeProject.project_id == project_id))
    )


@hooks.on(ProjectHook.INSPECTING)
async def count_private_link_types(session: AsyncSession, inspection: ProjectInspection) -> None:
    ids = list(await session.scalars(_exclusively_scoped(inspection.project.id)))
    inspection.add("link_types", len(ids))


@hooks.on(ProjectHook.DELETING)
async def delete_private_link_types(session: AsyncSession, deleting: ProjectDeleting) -> None:
    """Not through `service.delete_type`: its usage guard counts the links on
    the project's own items, which are still present at this moment (the purge
    runs after the hooks) and are the very rows about to go."""
    ids = list(await session.scalars(_exclusively_scoped(deleting.project.id)))
    for definition in (
        await session.execute(select(LinkTypeDef).where(LinkTypeDef.id.in_(ids)))
    ).scalars():
        await _emit(session, LinkTypeEvent.DELETED, definition, deleting.actor_id)
        await session.delete(definition)
    await session.flush()
