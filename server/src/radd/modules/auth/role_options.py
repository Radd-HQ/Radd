"""Role references without downloading permission definitions."""

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.choices import ChoiceRead, page
from . import authz
from .models import Role, User
from .types import BuiltinRoleKey


async def list_options(
    session: AsyncSession,
    actor: User,
    *,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    value: str | None = None,
    key: str | None = None,
    assignable: bool = False,
    project_id=None,
    space_id=None,
) -> tuple[list[ChoiceRead], int]:
    if not await authz.holds(session, actor, authz.Permission.ROLE_READ):
        return [], 0
    projection = select(
        cast(Role.id, String).label("value"), Role.name.label("label"), Role.key.label("hint")
    )
    if assignable:
        projection = projection.where(Role.key != BuiltinRoleKey.BASELINE)
        if value is None and not await authz.holds(session, actor, authz.Permission.ROLE_UPDATE):
            if project_id is None or space_id is not None:
                return [], 0
            from radd.modules.projects import service as projects
            from radd.exceptions import ForbiddenError
            from .roles_router import ensure_delegated_role_coverage

            project = await projects.get_project(session, project_id)
            if not await authz.holds(session, actor, authz.Permission.MEMBER_CREATE, project=project):
                return [], 0
            allowed = []
            for role in await session.scalars(select(Role)):
                try:
                    await ensure_delegated_role_coverage(session, actor, role, project)
                except ForbiddenError:
                    continue
                allowed.append(role.id)
            projection = projection.where(Role.id.in_(allowed))
    if key is not None:
        projection = projection.where(Role.key == key)
    return await page(session, projection, q=q, limit=limit, offset=offset, value=value)
