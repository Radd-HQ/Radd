"""`commented_by` — the item SLQ field this module contributes.

Same shape as timelogging's `logged_by` (see the note there): a question about
COMMENTS whose answer is a set of ITEMS, expressed through the plugin SLQ-field
registry so items never learns about comments.

    commented_by = me
    commented_by = "alice@corp.example"
    commented_by ~ alice

VISIBILITY CAVEAT, deliberately not solved here: this matches on authorship
alone, so an internal comment (spec 50 per-team visibility) can make its item
match for someone who could not read that comment. The item itself is still
filtered by the normal project/item RBAC, so this leaks the EXISTENCE of a
comment by a person, never its content. Narrowing it to visible comments needs
the actor's team set threaded into the resolver, which the SlqFieldContext can
carry when we decide that trade is worth the join.
"""

from sqlalchemy import or_, select
from sqlalchemy.sql import Select

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
        needle = f"%{value}%"
        return stmt.where(or_(User.email.ilike(needle), User.name.ilike(needle)))
    return stmt.where(or_(User.email.ilike(value), User.name.ilike(value)))
