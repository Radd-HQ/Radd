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
) -> tuple[list[ChoiceRead], int]:
    if not await authz.holds(session, actor, authz.Permission.ROLE_READ):
        return [], 0
    projection = select(
        cast(Role.id, String).label("value"), Role.name.label("label"), Role.key.label("hint")
    )
    if assignable:
        projection = projection.where(Role.key != BuiltinRoleKey.BASELINE)
    if key is not None:
        projection = projection.where(Role.key == key)
    return await page(session, projection, q=q, limit=limit, offset=offset, value=value)
