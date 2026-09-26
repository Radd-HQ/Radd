"""The views every new project ships with (Board, List, Planning, Roadmap): plain
saved views (owner NULL = managed through the view.* atoms), editable and deletable."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import View
from .types import ShareLevel, ViewAxis, ViewType

# (name, type, group_by) seeded per project.
DEFAULT_VIEW_DEFS: tuple[tuple[str, ViewType, str | None], ...] = (
    ("Board", ViewType.BOARD, ViewAxis.STATE.value),
    ("List", ViewType.LIST, None),
    ("Planning", ViewType.PLANNING, None),
    ("Roadmap", ViewType.ROADMAP, None),
)


async def seed_project_views(session: AsyncSession, project) -> None:
    """Idempotent by (project, name): create the missing default views (called
    from the project-created hook; a migration backfilled existing projects)."""
    for name, view_type, group_by in DEFAULT_VIEW_DEFS:
        existing = await session.scalar(
            select(View.id).where(View.project_id == project.id, View.name == name)
        )
        if existing is not None:
            continue
        session.add(
            View(
                project_id=project.id,
                name=name,
                view_type=view_type.value,
                query="",
                group_by=group_by,
                swimlane_by=None,
                cycle_filter=None,
                quick_filters=[],
                owner_id=None,
                global_access=ShareLevel.VIEWER.value,
                position=0,
            )
        )
    await session.flush()
