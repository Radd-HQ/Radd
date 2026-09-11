"""Lean email choices for administrative authors; never the public directory."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.choices import ChoiceRead, page
from . import authz
from .models import User


async def list_options(session: AsyncSession, actor: User, *, q: str = "", limit: int = 50,
                       offset: int = 0, value: str | None = None) -> tuple[list[ChoiceRead], int]:
    await authz.require(session, actor, authz.Permission.USER_MANAGE)
    # Match existing automation vocabulary: all active accounts, including
    # deliberately provisioned service accounts and mail requesters. Emails
    # remain behind USER_MANAGE; no password/security fields are selected.
    projection = select(User.email.label("value"), User.name.label("label"),
                        User.email.label("hint")).where(User.active.is_(True))
    return await page(session, projection, q=q, limit=limit, offset=offset, value=value)
