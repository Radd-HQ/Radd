"""Team-name choices without loading managers or calculating write capabilities."""
import uuid

from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.choices import ChoiceRead, page
from radd.modules.auth import authz
from radd.modules.auth.models import User
from .models import Team
from .schemas import TeamReferenceRead


async def list_options(session: AsyncSession, actor: User, *, q: str = "", limit: int = 50,
                       offset: int = 0, value: str | None = None) -> tuple[list[ChoiceRead], int]:
    if not await authz.holds(session, actor, authz.Permission.TEAM_READ):
        return [], 0
    projection = select(Team.name.label("value"), Team.name.label("label"), literal("").label("hint"))
    return await page(session, projection, q=q, limit=limit, offset=offset, value=value)


async def reference_options(session: AsyncSession, actor: User, *, q: str = "", limit: int = 50,
                            offset: int = 0, value: str | None = None, exclude: list[str] | None = None) -> tuple[list[ChoiceRead], int]:
    """ID-valued choices for relationships; name-valued automation options stay compatible."""
    from sqlalchemy import String, cast
    if not await authz.holds(session, actor, authz.Permission.TEAM_READ):
        return [], 0
    projection = select(cast(Team.id, String).label("value"), Team.name.label("label"), literal("").label("hint"))
    return await page(session, projection, q=q, limit=limit, offset=offset, value=value, exclude=exclude)


async def references(session: AsyncSession, actor: User, ids: list[uuid.UUID], *,
                     include_counts: bool = False) -> list[TeamReferenceRead]:
    from .reading import member_counts

    if not ids or not await authz.holds(session, actor, authz.Permission.TEAM_READ):
        return []
    rows = (await session.execute(select(Team.id, Team.name).where(Team.id.in_(ids)))).all()
    counts = await member_counts(session, [row.id for row in rows]) if include_counts else {}
    return [TeamReferenceRead(id=row.id, name=row.name,
        member_count=counts.get(row.id, 0) if include_counts else None) for row in rows]
