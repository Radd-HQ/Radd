"""`commented_by`: the item SLQ field this module contributes through the plugin
SLQ-field registry, so items never learns about comments.

    commented_by = me
    commented_by = "alice@corp.example"
    commented_by ~ alice

VISIBILITY CAVEAT, deliberately unsolved: this matches on authorship alone, so an
internal comment can make its item match for someone who cannot read that
comment. Item RBAC still applies, so it leaks a comment's EXISTENCE, never its
content. Narrowing needs the actor's team set in SlqFieldContext.
"""

from sqlalchemy import or_, select
from sqlalchemy.sql import Select

from radd.db import escape_like
from radd.kernel import SlqFieldContext
from radd.modules.auth.models import User

from .models import Comment
from .types import CommentParentType


def commented_by_item_ids(contains: bool, value: str, ctx: SlqFieldContext) -> Select:
    """Work-item ids carrying at least one comment by the matching author."""
    # `commented_by` is an ITEM-dialect field: page comments are not items and
    # must not leak into an item query's id set (RADD-717).
    stmt = select(Comment.entity_id).where(Comment.entity_type == CommentParentType.ITEM)
    if ctx.is_me:
        return stmt.where(Comment.author_id == ctx.current_user_id)

    stmt = stmt.join(User, User.id == Comment.author_id)
    if contains:
        needle = f"%{escape_like(value)}%"
        return stmt.where(or_(User.email.ilike(needle), User.name.ilike(needle)))
    exact = escape_like(value)
    return stmt.where(or_(User.email.ilike(exact), User.name.ilike(exact)))
