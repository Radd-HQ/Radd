"""`logged_by` — the item SLQ field this module contributes.

"Which issues has Alice logged time on?" is a question about WORKLOGS, but the
answer is a set of ITEMS, so it belongs in the item dialect. The plugin SLQ-field
registry (spec 94) is exactly that seam: this module hands back a Select of
matching work-item ids and the items engine wraps it as `work_item.id IN (…)`.
Items never learns that worklogs exist, and this module never touches the items
tables — the only shared model is the `auth.User` spine.

    logged_by = me
    logged_by = "alice@corp.example"
    logged_by ~ alice            -- substring over name/email
    logged_by != me              -- negation is applied by the engine

Itemless worklogs (spec 59) simply never match: their `item_id` is NULL, so they
cannot name an item, which is the correct answer rather than an omission.
"""

from sqlalchemy import or_, select
from sqlalchemy.sql import Select

from radd.kernel import SlqFieldContext
from radd.modules.auth.models import User

from ..models import Worklog


def logged_by_item_ids(contains: bool, value: str, ctx: SlqFieldContext) -> Select:
    """Work-item ids with at least one worklog whose author matches `value`.

    `me` resolves to the acting user. Otherwise the value matches a person by
    email or name — exactly when `contains` is False, substring when it is True,
    both case-insensitively, so `logged_by ~ ali` behaves like the builtin
    people fields rather than inventing a second convention.
    """
    stmt = select(Worklog.item_id).where(Worklog.item_id.is_not(None))
    if ctx.is_me:
        return stmt.where(Worklog.author_id == ctx.current_user_id)

    stmt = stmt.join(User, User.id == Worklog.author_id)
    if contains:
        needle = f"%{value}%"
        return stmt.where(or_(User.email.ilike(needle), User.name.ilike(needle)))
    return stmt.where(or_(User.email.ilike(value), User.name.ilike(value)))
