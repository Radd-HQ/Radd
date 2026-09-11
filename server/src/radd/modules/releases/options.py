"""Permission-filtered choices without loading complete resource definitions."""
import uuid
from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from radd.choices import ChoiceRead, page
from radd.modules.auth import authz
from radd.modules.auth.models import User
from .models import Release


async def list_options(session: AsyncSession, actor: User, *, q: str = "", limit: int = 50,
                       offset: int = 0, value: str | None = None,
                       project_id: uuid.UUID | None = None) -> tuple[list[ChoiceRead], int]:
    readable = await authz.readable_projects(session, actor)
    query = select(Release.version.label("value"), Release.version.label("label"),
                   literal("").label("hint")).distinct()
    query = query.where(Release.project_id.in_(readable))
    if project_id is not None:
        query = query.where(Release.project_id == project_id)
    return await page(session, query, q=q, limit=limit, offset=offset, value=value)
