"""Page ACTION nodes for automations (RADD-1267): comment on the page an event
is about, and move it under another page.

Contributed the way `milestones/automation.py` contributes its own (RADD-923):
the pages plugin declares `subject="page"`, the kernel hands the node the page
ids the event named, and the executor supplies the savepoint, the budget and
the loop guard. Nothing here imports `automations`.

Two nodes rather than one "edit page": a comment is a REPLY on the page's
discussion — the thing a "page went stale" automation wants — and a move is a
tree operation with its own rules (`pages.service.update_page` refuses a cycle
and a cross-space parent). Editing the body from an automation is deliberately
absent: the collaborative editor's write guard (spec 122) owns page bodies, and
an automation rewriting one under a live session is exactly what that guard
exists to refuse.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from radd.sdk import AutomationNodeSpec

COMMENT_NODE_KEY = "page.comment"
MOVE_NODE_KEY = "page.move"

COMMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["body"],
    "properties": {
        "body": {"type": "string", "title": "Comment", "minLength": 1, "maxLength": 10000},
        "visibility": {
            "type": "string",
            "title": "Visibility",
            "enum": ["public", "internal"],
            "default": "public",
        },
    },
}

MOVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "parent": {
            "type": "string",
            "title": "Under page (number, e.g. 12402) — empty for the space root",
            "maxLength": 32,
        },
    },
}


@dataclass
class _CommentPlan:
    page_id: uuid.UUID | None
    body: str
    visibility: str
    detail: str
    resolves: bool = True


@dataclass
class _MovePlan:
    page_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    detail: str
    resolves: bool = True


async def _page(ctx: Any):
    from .models import Page

    if not ctx.subject_ids:
        return None
    return await ctx.session.get(Page, ctx.subject_ids[0])


async def plan_comment(ctx: Any) -> _CommentPlan:
    body = str(ctx.node.params.get("body") or "").strip()
    visibility = str(ctx.node.params.get("visibility") or "public")
    if not body:
        return _CommentPlan(None, body, visibility, "page.comment: no comment text", False)
    page = await _page(ctx)
    if page is None:
        return _CommentPlan(None, body, visibility, "page.comment: no page reached this node", False)
    return _CommentPlan(page.id, body, visibility, f"page.comment on {page.title!r} ({visibility})")


async def apply_comment(ctx: Any, plan: _CommentPlan) -> None:
    from radd.modules.comments import service as comments
    from radd.modules.comments.schemas import CommentCreate
    from radd.modules.comments.types import CommentVisibility

    await comments.create_comment(
        ctx.session,
        plan.page_id,
        CommentCreate(body=plan.body, visibility=CommentVisibility(plan.visibility)),
        ctx.actor,
        entity_type="page",
    )


async def plan_move(ctx: Any) -> _MovePlan:
    from sqlalchemy import select

    from .models import Page

    page = await _page(ctx)
    if page is None:
        return _MovePlan(None, None, "page.move: no page reached this node", False)
    raw = str(ctx.node.params.get("parent") or "").strip()
    if not raw:
        if page.parent_id is None:
            return _MovePlan(page.id, None, "page.move: already at the space root", False)
        return _MovePlan(page.id, None, f"page.move {page.title!r} -> space root")
    try:
        number = int(raw)
    except ValueError:
        return _MovePlan(page.id, None, f"page.move: {raw!r} is not a page number", False)
    parent = (
        await ctx.session.execute(
            select(Page).where(Page.number == number, Page.archived_at.is_(None))
        )
    ).scalar_one_or_none()
    if parent is None:
        return _MovePlan(page.id, None, f"page.move: no page #{number}", False)
    if parent.space_id != page.space_id:
        return _MovePlan(page.id, None, f"page.move: #{number} is in another space", False)
    if parent.id == page.id:
        return _MovePlan(page.id, None, "page.move: a page cannot be its own parent", False)
    if page.parent_id == parent.id:
        return _MovePlan(page.id, None, f"page.move: already under #{number}", False)
    return _MovePlan(page.id, parent.id, f"page.move {page.title!r} -> under {parent.title!r}")


async def apply_move(ctx: Any, plan: _MovePlan) -> None:
    from . import service
    from .schemas import PageUpdate

    await service.update_page(ctx.session, plan.page_id, PageUpdate(parent_id=plan.parent_id), ctx.actor.id)


COMMENT_NODE = AutomationNodeSpec(
    key=COMMENT_NODE_KEY,
    kind="action",
    label="Comment on the page",
    description="Add a comment to the page this event is about.",
    group="Pages",
    params_schema=COMMENT_SCHEMA,
    subject="page",
    arity="item",
    needs_items=False,  # it needs a PAGE, not an item — see `subject`
    permission="comment.write",
    plan=plan_comment,
    apply=apply_comment,
)

MOVE_NODE = AutomationNodeSpec(
    key=MOVE_NODE_KEY,
    kind="action",
    label="Move the page",
    description="Move the page this event is about under another page in its space, or to the root.",
    group="Pages",
    params_schema=MOVE_SCHEMA,
    subject="page",
    arity="item",
    needs_items=False,
    permission="page.write",
    plan=plan_move,
    apply=apply_move,
)
