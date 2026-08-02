"""`roadmap` — the item SLQ field this module contributes (roadmap wave).

"Which items are pinned to this roadmap?" is a question about VIEW MEMBERSHIP,
but the answer is a set of ITEMS, so it belongs in the item dialect — the same
spec-97 inversion as `logged_by`/`commented_by`. This module hands back a
Select over its OWN tables (view_members joined to views for name matching)
and the items engine wraps it as `work_item.id IN (…)`; item RBAC then applies
to the results like any other query, so membership never widens what an actor
can see.

    roadmap = "Q3 Prague"        -- exact view name (case-insensitive)
    roadmap = "0548235e-9a66-…"     -- a view id (what the roadmap surface emits)
    roadmap ~ Q3                    -- members of ANY view whose name contains Q3
    roadmap != "Q3 Prague"       -- negation applied by the engine

Semantics are EXACT membership — hand-picked items only. "An epic's children
ride along" is roadmap-surface policy, composed client-side with the existing
`epic IN (…)` field, so other surfaces filtering by `roadmap` get the least
surprising answer. View VISIBILITY is deliberately not consulted (the resolver
is a pure Select, no session): knowing a private roadmap's name only ever
surfaces items the actor could already read.
"""

import uuid

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
        return stmt.where(View.name.ilike(f"%{value}%"))
    return stmt.where(View.name.ilike(value))
