"""Page automation contributions (RADD-1267/1322/1324): comment-on-page and
move-page actions, the "Page is in space" gate and `{{page.*}}` tokens. Editing a
body is deliberately absent — the co-editing write guard (spec 122) owns page
bodies. Nothing here imports `automations`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from radd.sdk import AutomationNodeKind, AutomationNodeSpec, NodeArity, NodePort, TokenProviderSpec

SPACE_GATE_KEY = "gate.page_space"
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
    # RADD-1324: rendered — `{{page.title}}` used to be posted verbatim.
    body = (await ctx.render(str(ctx.node.params.get("body") or ""))).strip()
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
    kind=AutomationNodeKind.ACTION.value,
    label="Comment on the page",
    description="Add a comment to the page this event is about.",
    group="Pages",
    params_schema=COMMENT_SCHEMA,
    subject="page",
    arity=NodeArity.ITEM.value,
    needs_items=False,  # it needs a PAGE, not an item — see `subject`
    permission="comment.write",
    plan=plan_comment,
    apply=apply_comment,
)

MOVE_NODE = AutomationNodeSpec(
    key=MOVE_NODE_KEY,
    kind=AutomationNodeKind.ACTION.value,
    label="Move the page",
    description="Move the page this event is about under another page in its space, or to the root.",
    group="Pages",
    params_schema=MOVE_SCHEMA,
    subject="page",
    arity=NodeArity.ITEM.value,
    needs_items=False,
    permission="page.write",
    plan=plan_move,
    apply=apply_move,
)


# --- "Page is in space" (RADD-1248), owned by pages since RADD-1322 ---------


def page_space_is(payload: dict[str, Any], params: dict[str, Any]) -> bool:
    """Is the event's page in one of these spaces? A page event carries
    `page_space`, a page comment the space inside `page`; a saved value may be an
    id or a slug (RADD-1371)."""
    wanted = {str(v).strip().lower() for v in (params.get("spaces") or []) if str(v).strip()}
    if not wanted:
        return False
    space = payload.get("page_space")
    if not isinstance(space, dict):
        page = payload.get("page")
        space = page.get("space") if isinstance(page, dict) else None
    keys = {str(space.get(k)).lower() for k in ("id", "slug") if space.get(k)} if isinstance(space, dict) else set()
    hit = bool(keys & wanted)
    return not hit if params.get("negate") else hit


async def _plan_space(ctx: Any) -> str:
    return "true" if page_space_is(dict(ctx.packet.facts.payload or {}), dict(ctx.node.params)) else "false"


SPACE_GATE = AutomationNodeSpec(
    key=SPACE_GATE_KEY,
    kind=AutomationNodeKind.GATE.value,
    label="Page is in space",
    group="Gates",
    keywords="page wiki space docs runbook in space",
    default_params={"spaces": [], "negate": False},
    ports=(NodePort.TRUE.value, NodePort.FALSE.value),
    needs_items=False,
    reads_event=True,
    plan=_plan_space,
)


# --- {{page.*}} tokens (RADD-1248), owned by pages since RADD-1324 -----------


def resolve_page_token(field_name: str, payload: dict[str, Any]) -> str | None:
    """The `page` ref the kernel wrote: on a page event and on a page comment
    alike. The space rides inside the ref, but page events also carry a
    top-level `page_space` ref — either answers `page.space`."""
    page = payload.get("page")
    if not isinstance(page, dict):
        return None
    if field_name == "space":
        space = page.get("space") or payload.get("page_space")
        return str(space.get("slug")) if isinstance(space, dict) and space.get("slug") else None
    if field_name == "url":
        from radd.config import settings
        from radd.mailrender import page_url

        number = page.get("number")
        return page_url(settings.app_base_url, number) if number else None
    value = page.get(field_name)
    return None if value is None or isinstance(value, dict) else str(value)


PAGE_TOKENS = TokenProviderSpec(
    root="page",
    tokens=(
        ("title", "The page's title, on a page event or a page comment."),
        ("path", "Its readable address inside the space, e.g. onboarding/laptops."),
        ("space", "Its space's slug."),
        ("url", "A permalink to the page (survives renames and moves)."),
    ),
    resolve=resolve_page_token,
)
