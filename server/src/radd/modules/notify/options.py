"""Subscription candidates: authorized names minus existing rules before paging."""
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.choices import ChoiceRead, page
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.projects.models import Project
from radd.modules.teams import service as teams
from . import subjects
from .models import NotificationRule
from .types import RuleScope


async def subscription_options(session: AsyncSession, actor: User, *, scope: RuleScope,
                               q: str = "", limit: int = 50, offset: int = 0) -> tuple[list[ChoiceRead], int]:
    held = list(await session.scalars(select(NotificationRule.scope_id).where(
        NotificationRule.user_id == actor.id, NotificationRule.scope == scope,
        NotificationRule.scope_id.is_not(None))))
    exclude = [str(identifier) for identifier in held]
    if scope == RuleScope.TEAM:
        return await teams.reference_options(session, actor, q=q, limit=limit, offset=offset, exclude=exclude)
    if scope != RuleScope.PROJECT:
        # A non-item subject's container (a wiki SPACE): its provider's picker,
        # or nothing while that plugin is disabled (RADD-1385).
        return await subjects.scope_options(
            session, actor, scope, q=q, limit=limit, offset=offset, exclude=exclude
        )
    visible = await authz.visible_projects(session, actor)
    projection = select(cast(Project.id, String).label("value"), Project.name.label("label"),
                        Project.key.label("hint")).where(Project.id.in_(visible))
    return await page(session, projection, q=q, limit=limit, offset=offset, exclude=exclude)
