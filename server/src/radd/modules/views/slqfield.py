"""`roadmap` — item SLQ field: items hand-pinned to a view.

The answer is a set of ITEMS, so it lives in the item dialect (like `logged_by`):
this returns a Select over view_members and the items engine wraps it as
`work_item.id IN (…)`, so item RBAC still applies.

    roadmap = "Q3 Prague"   -- exact view name (case-insensitive)
    roadmap = "<view id>"   -- what the roadmap surface emits
    roadmap ~ Q3            -- members of any view whose name contains Q3

EXACT membership (an epic's children are the roadmap surface's policy). View
visibility is not consulted: a private roadmap's name only surfaces items the
actor could already read.
"""

import uuid

from radd.db import escape_like

from sqlalchemy import false, select
from sqlalchemy.sql import Select

from radd.kernel import SlqFieldContext

from .models import View, ViewMember


def roadmap_member_item_ids(contains: bool, value: str, ctx: SlqFieldContext) -> Select:
    """Work-item ids pinned to the view(s) `value` names."""
    if ctx.is_me:  # `roadmap = me` is meaningless — match nothing, loudly simple.
        return select(ViewMember.item_id).where(false())
    stmt = select(ViewMember.item_id)
    if not contains:
        try:
            return stmt.where(ViewMember.view_id == uuid.UUID(value))
        except ValueError:
            pass
    stmt = stmt.join(View, View.id == ViewMember.view_id)
    if contains:
        return stmt.where(View.name.ilike(f"%{escape_like(value)}%"))
    return stmt.where(View.name.ilike(escape_like(value)))
