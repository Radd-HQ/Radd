"""What the AI automation nodes send the model (spec 116), and the plumbing the
three nodes share.

* Only the sections the node's checkboxes ask for (comments/worklogs are a
  privacy cost when the question is about titles).
* Budget WHOLE items, never fields: a truncated description can cut the line
  that decides the answer.
* The budget is `ai_automation_context_chars`, sized to the model's context.
* What was cut is stated IN THE PROMPT, so the model knows it saw a sample.

The nodes read their context as a DUCK TYPE (`getattr`): `ai` contributes them
through the kernel and imports nothing from `automations`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth.models import User

from . import client, features
from .prose import prose
from .summarize import _worklog_digest
from .types import AiFeature, AiRole

logger = logging.getLogger(__name__)

#: Hard ceiling on how many items are even considered, independent of the
#: character budget — a 200-item scheduled run should not build a 200-item string
#: only to discard most of it. Sized to `automation_schedule_max_items` so the
#: two caps cannot silently disagree about what "all the items" means.
MAX_ITEMS = 200


@dataclass(frozen=True)
class ContextOptions:
    """Which sections of an item the model sees. Mirrors the node's checkboxes."""

    fields: bool = True  # type, state, priority, assignee, labels, custom fields
    description: bool = True
    comments: bool = False
    worklogs: bool = False

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> "ContextOptions":
        # A non-mapping `include` (old nodes stored a typed STRING, RADD-1064) falls
        # back to the defaults instead of raising inside `_ask` as a fake outage.
        raw = params.get("include")
        include: dict[str, Any] = raw if isinstance(raw, dict) else {}
        return cls(
            fields=bool(include.get("fields", True)),
            description=bool(include.get("description", True)),
            comments=bool(include.get("comments", False)),
            worklogs=bool(include.get("worklogs", False)),
        )


def _render_item(read: Any, comments: list[Any], options: ContextOptions, worklog: str | None) -> str:
    """One item, WHOLE. Nothing here truncates: the budget is spent by dropping
    items, so what the model sees of an item is what the item says."""
    lines = [f"--- {read.key}: {read.title}"]
    if options.fields:
        facts = [f"type={read.kind}", f"state={read.state.name}", f"priority={read.priority}"]
        if read.assignee:
            facts.append(f"assignee={read.assignee.name}")
        if read.labels:
            facts.append(f"labels={', '.join(read.labels)}")
        for key, value in (read.custom_fields or {}).items():
            if value not in (None, "", []):
                facts.append(f"{key}={value}")
        lines.append("  " + "; ".join(facts))
    if options.description and read.description:
        lines.append(f"  description: {prose(read.description)}")  # RADD-1232
    for comment in comments:
        lines.append(f"  comment by {comment.author.name}: {prose(comment.body)}")
    if worklog is not None:
        lines.append(f"  time: {worklog}")
    return "\n".join(lines)


async def build_context(
    session: AsyncSession,
    item_ids: tuple[uuid.UUID, ...],
    actor: User,
    options: ContextOptions,
) -> str:
    """A plain-text digest of the items, honouring `options`.

    Reads go through the item/comment services with `actor`, so the digest can
    only ever contain what that identity could already see — the same property
    the Summarize feature relies on. An automation running as someone with
    narrow access sends a correspondingly narrow prompt.
    """
    from radd.modules.comments import service as comments_service
    from radd.modules.items import service as items_service

    if not item_ids:
        return "No items matched this run."

    budget = settings.ai_automation_context_chars
    considered = item_ids[:MAX_ITEMS]
    blocks: list[str] = []
    spent = 0
    omitted = len(item_ids) - len(considered)

    for index, item_id in enumerate(considered):
        try:
            read = await items_service.get_item(session, item_id, actor)
        except Exception:  # noqa: BLE001 — deliberate: an item that vanished mid-run,
            # or that this identity may not read, is simply absent from the prompt.
            # Failing the whole classification because one of 40 items moved would
            # turn a routing decision into an outage.
            continue

        comments: list[Any] = []
        if options.comments:
            try:
                comments = list(await comments_service.list_comments(session, item_id, actor))
            except Exception:  # noqa: BLE001 — deliberate: comments are an OPTIONAL
                # section. Omitting them degrades the prompt; raising would drop the
                # classification entirely.
                comments = []
        worklog = await _worklog_line(session, item_id, read) if options.worklogs else None

        block = _render_item(read, comments, options, worklog)
        if blocks and spent + len(block) > budget:
            # The budget is spent on whole items, so the rest are omitted rather
            # than the current one being cut in half. `blocks and` keeps a single
            # oversized item from producing an empty digest — one item over
            # budget is still a better prompt than none.
            omitted += len(considered) - index
            break
        blocks.append(block)
        spent += len(block)

    if omitted:
        # Stated in the PROMPT, not just logged: the model is answering about a
        # sample, and a confident answer about part of the set should say so.
        blocks.append(
            f"\n({omitted} further item(s) not shown — the prompt reached its "
            f"{budget}-character budget. Raise RADD_AI_AUTOMATION_CONTEXT_CHARS if "
            f"your model has room.)"
        )
    return "\n".join(blocks)


def include_schema(description: str) -> dict[str, Any]:
    """The node form's "What the model sees" checkboxes — `ContextOptions`' fields."""
    return {
        "type": "object",
        "title": "What the model sees",
        "description": description,
        "properties": {
            "fields": {
                "type": "boolean",
                "default": True,
                "title": "Fields (type, state, priority, assignee, labels, custom fields)",
            },
            "description": {"type": "boolean", "default": True, "title": "Description (in full)"},
            "comments": {"type": "boolean", "default": False, "title": "Comments (all)"},
            "worklogs": {"type": "boolean", "default": False, "title": "Logged time"},
        },
    }


def out_of_time(ctx: Any) -> bool:
    """Whether the walk's wall-clock budget is spent; a context without one has
    all the time in the world."""
    ask = getattr(ctx, "out_of_time", None)
    return bool(ask()) if callable(ask) else False


async def preflight(ctx: Any, feature: AiFeature, node_key: str) -> bool:
    """Whether an AI node may ask the model now: it has a prompt, the walk has
    time left (checked BEFORE the gate — out of time means no more work), and the
    feature is live. Never raises; False = take the `unavailable` port."""
    if not str(ctx.node.params.get("prompt") or "").strip():
        # Quiet rather than blocking: an unfinished node must not refuse anything.
        logger.info("%s: node %s has no prompt; taking unavailable", node_key, ctx.node.id)
        return False
    if out_of_time(ctx):
        logger.info("%s: node %s ran out of time; taking unavailable", node_key, ctx.node.id)
        return False
    try:
        return await features.feature_enabled(ctx.session, feature)
    except Exception:
        logger.exception("%s: could not resolve the feature gate", node_key)
        return False


async def ask_structured(
    ctx: Any,
    params: Mapping[str, Any],
    *,
    system: str,
    user: Callable[[str], str],
    schema: dict[str, Any],
) -> Mapping[str, Any]:
    """One structured chat answer about the packet's items; `user(context)` frames
    the digest `params`' checkboxes select."""
    context = await build_context(
        ctx.session, tuple(ctx.packet.item_ids), ctx.actor, ContextOptions.from_params(dict(params))
    )
    return await client.complete_structured(
        ctx.session, AiRole.CHAT, system=system, user=user(context), json_schema=schema
    )


async def _worklog_line(session: AsyncSession, item_id: uuid.UUID, read: Any) -> str | None:
    """The summarize time digest on one line; None (no line at all) when the
    project does not track time or nothing is logged, as in Summarize."""
    lines = await _worklog_digest(session, item_id, read.project_id)
    return "; ".join(lines) if lines else None
